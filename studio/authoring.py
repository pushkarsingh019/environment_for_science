"""Reversible local persistence for one authored Environment draft."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DraftActorRole = Literal[
    "environment_author",
    "authoring_assistant",
    "policy_agent",
    "studio",
]
DraftOperation = Literal["initialize", "edit", "undo", "redo", "restore_seed"]
DraftErrorCode = Literal["invalid", "conflict", "forbidden", "storage"]
DraftStateValidator = Callable[[dict[str, Any]], Mapping[str, Any]]


class DraftRepositoryError(ValueError):
    """Base class for failures at the persistent draft boundary."""

    def __init__(self, message: str, *, code: DraftErrorCode) -> None:
        super().__init__(message)
        self.code = code


class DraftValidationError(DraftRepositoryError):
    """Raised when caller input cannot become a valid draft operation."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid")


class DraftRevisionConflict(DraftRepositoryError):
    """Raised when the caller edited an obsolete optimistic revision."""

    def __init__(self, *, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            "the draft changed after the requested revision",
            code="conflict",
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class DraftSeedConflict(DraftRepositoryError):
    """Raised when a persisted workspace is reopened with another seed."""

    def __init__(self) -> None:
        super().__init__(
            "the persisted draft was initialized from a different seed",
            code="conflict",
        )


class DraftAuthorizationError(DraftRepositoryError):
    """Raised when a run-side identity attempts to edit authoring state."""

    def __init__(self) -> None:
        super().__init__(
            "Policy agents cannot change the Environment draft",
            code="forbidden",
        )


class DraftOperationUnavailable(DraftRepositoryError):
    """Raised when undo or redo has no reachable draft state."""

    def __init__(self, operation: Literal["undo", "redo"]) -> None:
        super().__init__(f"there is no draft change to {operation}", code="conflict")
        self.operation = operation


class DraftStorageError(DraftRepositoryError):
    """Raised when local draft persistence cannot satisfy its contract."""

    def __init__(self) -> None:
        super().__init__(
            "the Environment draft could not be persisted",
            code="storage",
        )


class DraftActor(BaseModel):
    """Product identity responsible for one draft operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: DraftActorRole


class DraftChange(BaseModel):
    """Append-only attribution for one successful draft operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=1)
    operation: DraftOperation
    actor: DraftActor
    description: str = Field(min_length=1)
    before_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    after_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DraftSnapshot(BaseModel):
    """Detached caller-visible state of the authored draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    state: dict[str, Any]
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    can_undo: bool
    can_redo: bool
    last_change: DraftChange


_STUDIO_ACTOR = DraftActor(
    id="science-environment-studio",
    name="Science Environment Studio",
    role="studio",
)


class DraftRepository:
    """SQLite-backed reversible workspace for one JSON-compatible draft."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        workspace_id: str,
        seed_state: dict[str, Any],
        state_validator: DraftStateValidator | None = None,
    ) -> None:
        self._workspace_id = _validated_workspace_id(workspace_id)
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._database_path = self._artifact_root / "draft-workspace.sqlite3"
        self._state_validator = state_validator
        seed_json, seed_digest = self._validated_state(seed_state)
        self._seed_json = seed_json
        self._seed_digest = seed_digest
        try:
            self._artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._prepare_database()
            self._initialize(seed_json, seed_digest)
        except DraftRepositoryError:
            raise
        except (OSError, sqlite3.Error):
            raise DraftStorageError() from None

    @property
    def database_path(self) -> Path:
        """Return the local database file owned by this repository."""
        return self._database_path

    def current(self) -> DraftSnapshot:
        """Return a detached snapshot of the current draft state."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN")
                snapshot = self._read_snapshot(connection)
                connection.commit()
                return snapshot
        except DraftRepositoryError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            raise DraftStorageError() from None

    def list_activity(self) -> tuple[DraftChange, ...]:
        """Return the complete append-only draft activity in revision order."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN")
                workspace = self._workspace_row(connection)
                self._verify_seed_integrity(connection, workspace)
                state = self._state_row(connection, workspace["current_state_id"])
                self._verified_state_document(state)
                activity = self._verified_activity(
                    connection,
                    revision=workspace["revision"],
                    current_digest=state["content_digest"],
                )
                self._verify_state_origin(
                    state,
                    activity=activity,
                    revision=workspace["revision"],
                )
                connection.commit()
                return activity
        except DraftRepositoryError:
            raise
        except (sqlite3.Error, ValidationError):
            raise DraftStorageError() from None

    def apply(
        self,
        *,
        state: dict[str, Any],
        expected_revision: int,
        actor: DraftActor,
        description: str,
    ) -> DraftSnapshot:
        """Validate and transactionally apply one attributed draft edit."""
        self._require_editor(actor)
        description = _validated_description(description)
        state_json, state_digest = self._validated_state(state)
        return self._append_state(
            expected_revision=expected_revision,
            actor=actor,
            description=description,
            operation="edit",
            content=(state_json, state_digest),
        )

    def undo(
        self,
        *,
        expected_revision: int,
        actor: DraftActor,
        description: str,
    ) -> DraftSnapshot:
        """Move to the previous reachable draft state as an attributed revision."""
        self._require_editor(actor)
        description = _validated_description(description)
        return self._navigate(
            expected_revision=expected_revision,
            actor=actor,
            description=description,
            operation="undo",
        )

    def redo(
        self,
        *,
        expected_revision: int,
        actor: DraftActor,
        description: str,
    ) -> DraftSnapshot:
        """Move to the next reachable draft state as an attributed revision."""
        self._require_editor(actor)
        description = _validated_description(description)
        return self._navigate(
            expected_revision=expected_revision,
            actor=actor,
            description=description,
            operation="redo",
        )

    def restore_seed(
        self,
        *,
        expected_revision: int,
        actor: DraftActor,
        description: str,
    ) -> DraftSnapshot:
        """Restore the validated seed as a new, undoable draft revision."""
        self._require_editor(actor)
        description = _validated_description(description)
        return self._append_state(
            expected_revision=expected_revision,
            actor=actor,
            description=description,
            operation="restore_seed",
            content=None,
        )

    def _append_state(
        self,
        *,
        expected_revision: int,
        actor: DraftActor,
        description: str,
        operation: Literal["edit", "restore_seed"],
        content: tuple[str, str] | None,
    ) -> DraftSnapshot:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workspace = self._workspace_row(connection)
            self._require_revision(expected_revision, workspace["revision"])
            previous_snapshot = self._read_snapshot(connection)
            next_revision = workspace["revision"] + 1
            if content is None:
                self._verify_seed_integrity(connection, workspace)
                content_json = self._seed_json
                content_digest = self._seed_digest
            else:
                content_json, content_digest = content
            cursor = connection.execute(
                """
                INSERT INTO draft_states (
                    workspace_id, created_revision, content_json, content_digest
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self._workspace_id,
                    next_revision,
                    content_json,
                    content_digest,
                ),
            )
            state_id = cursor.lastrowid
            if state_id is None:
                raise DraftStorageError()
            undo_stack = _stack_from_json(workspace["undo_stack_json"])
            undo_stack.append(workspace["current_state_id"])
            connection.execute(
                """
                UPDATE draft_workspaces
                SET revision = ?, current_state_id = ?, undo_stack_json = ?,
                    redo_stack_json = '[]'
                WHERE workspace_id = ?
                """,
                (
                    next_revision,
                    state_id,
                    _canonical_stack(undo_stack),
                    self._workspace_id,
                ),
            )
            self._record_change(
                connection,
                revision=next_revision,
                operation=operation,
                actor=actor,
                description=description,
                before_digest=previous_snapshot.content_digest,
                after_digest=content_digest,
            )
            snapshot = self._read_snapshot(connection)
            connection.commit()
            return snapshot
        except DraftRepositoryError:
            connection.rollback()
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            connection.rollback()
            raise DraftStorageError() from None
        finally:
            connection.close()

    def _navigate(
        self,
        *,
        expected_revision: int,
        actor: DraftActor,
        description: str,
        operation: Literal["undo", "redo"],
    ) -> DraftSnapshot:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workspace = self._workspace_row(connection)
            self._require_revision(expected_revision, workspace["revision"])
            previous_snapshot = self._read_snapshot(connection)
            undo_stack = _stack_from_json(workspace["undo_stack_json"])
            redo_stack = _stack_from_json(workspace["redo_stack_json"])
            source_stack = undo_stack if operation == "undo" else redo_stack
            destination_stack = redo_stack if operation == "undo" else undo_stack
            if not source_stack:
                raise DraftOperationUnavailable(operation)
            target_state_id = source_stack.pop()
            target_state = self._state_row(connection, target_state_id)
            self._verified_state_document(target_state)
            activity = self._verified_activity(
                connection,
                revision=workspace["revision"],
                current_digest=previous_snapshot.content_digest,
            )
            self._verify_state_origin(
                target_state,
                activity=activity,
                revision=workspace["revision"],
            )
            destination_stack.append(workspace["current_state_id"])
            next_revision = workspace["revision"] + 1
            connection.execute(
                """
                UPDATE draft_workspaces
                SET revision = ?, current_state_id = ?, undo_stack_json = ?,
                    redo_stack_json = ?
                WHERE workspace_id = ?
                """,
                (
                    next_revision,
                    target_state_id,
                    _canonical_stack(undo_stack),
                    _canonical_stack(redo_stack),
                    self._workspace_id,
                ),
            )
            self._record_change(
                connection,
                revision=next_revision,
                operation=operation,
                actor=actor,
                description=description,
                before_digest=previous_snapshot.content_digest,
                after_digest=target_state["content_digest"],
            )
            snapshot = self._read_snapshot(connection)
            connection.commit()
            return snapshot
        except DraftRepositoryError:
            connection.rollback()
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            connection.rollback()
            raise DraftStorageError() from None
        finally:
            connection.close()

    def _read_snapshot(self, connection: sqlite3.Connection) -> DraftSnapshot:
        workspace = self._workspace_row(connection)
        self._verify_seed_integrity(connection, workspace)
        state = self._state_row(connection, workspace["current_state_id"])
        state_document = self._verified_state_document(state)
        undo_stack = _stack_from_json(workspace["undo_stack_json"])
        redo_stack = _stack_from_json(workspace["redo_stack_json"])
        activity = self._verified_activity(
            connection,
            revision=workspace["revision"],
            current_digest=state["content_digest"],
        )
        self._verify_state_origin(
            state,
            activity=activity,
            revision=workspace["revision"],
        )
        last_change = activity[-1]
        return DraftSnapshot(
            workspace_id=self._workspace_id,
            revision=workspace["revision"],
            state=deepcopy(state_document),
            content_digest=state["content_digest"],
            can_undo=bool(undo_stack),
            can_redo=bool(redo_stack),
            last_change=last_change,
        )

    def _verified_activity(
        self,
        connection: sqlite3.Connection,
        *,
        revision: int,
        current_digest: str,
    ) -> tuple[DraftChange, ...]:
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise DraftStorageError()
        rows = connection.execute(
            """
            SELECT revision, operation, actor_id, actor_name, actor_role,
                   description, before_digest, after_digest
            FROM draft_activity
            WHERE workspace_id = ?
            ORDER BY revision
            """,
            (self._workspace_id,),
        ).fetchall()
        if [row["revision"] for row in rows] != list(range(1, revision + 1)):
            raise DraftStorageError()
        activity = tuple(
            self._change_from_row(row["revision"], row) for row in rows
        )
        previous_digest: str | None = None
        for change in activity:
            if change.before_digest != previous_digest:
                raise DraftStorageError()
            if (change.revision == 1) != (change.operation == "initialize"):
                raise DraftStorageError()
            previous_digest = change.after_digest
        if previous_digest != current_digest:
            raise DraftStorageError()
        return activity

    @staticmethod
    def _verify_state_origin(
        state: sqlite3.Row,
        *,
        activity: tuple[DraftChange, ...],
        revision: int,
    ) -> None:
        created_revision = state["created_revision"]
        if (
            not isinstance(created_revision, int)
            or isinstance(created_revision, bool)
            or created_revision < 1
            or created_revision > revision
        ):
            raise DraftStorageError()
        origin = activity[created_revision - 1]
        if origin.operation not in {"initialize", "edit", "restore_seed"}:
            raise DraftStorageError()
        if origin.after_digest != state["content_digest"]:
            raise DraftStorageError()

    def _verified_state_document(self, state: sqlite3.Row) -> dict[str, Any]:
        return self._verified_document(
            content_json=state["content_json"],
            content_digest=state["content_digest"],
        )

    def _verified_document(
        self,
        *,
        content_json: str,
        content_digest: str,
    ) -> dict[str, Any]:
        try:
            document = json.loads(content_json)
            if not isinstance(document, dict):
                raise DraftStorageError()
            canonical, verified_digest = self._validated_state(document)
        except (json.JSONDecodeError, DraftValidationError):
            raise DraftStorageError() from None
        if canonical != content_json or verified_digest != content_digest:
            raise DraftStorageError()
        return deepcopy(document)

    def _verify_seed_integrity(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
    ) -> None:
        self._verified_document(
            content_json=workspace["seed_state_json"],
            content_digest=workspace["seed_digest"],
        )
        if (
            workspace["seed_state_json"] != self._seed_json
            or workspace["seed_digest"] != self._seed_digest
        ):
            raise DraftStorageError()
        seed_states = connection.execute(
            """
            SELECT content_json, content_digest
            FROM draft_states
            WHERE workspace_id = ? AND created_revision = 1
            """,
            (self._workspace_id,),
        ).fetchall()
        if len(seed_states) != 1:
            raise DraftStorageError()
        seed_state = seed_states[0]
        self._verified_state_document(seed_state)
        if (
            seed_state["content_json"] != self._seed_json
            or seed_state["content_digest"] != self._seed_digest
        ):
            raise DraftStorageError()
        initialization = connection.execute(
            """
            SELECT operation, actor_id, actor_name, actor_role, description,
                   before_digest, after_digest
            FROM draft_activity
            WHERE workspace_id = ? AND revision = 1
            """,
            (self._workspace_id,),
        ).fetchone()
        if initialization is None:
            raise DraftStorageError()
        change = self._change_from_row(1, initialization)
        if (
            change.operation != "initialize"
            or change.before_digest is not None
            or change.after_digest != self._seed_digest
        ):
            raise DraftStorageError()

    @staticmethod
    def _change_from_row(revision: int, row: sqlite3.Row) -> DraftChange:
        return DraftChange(
            revision=revision,
            operation=row["operation"],
            actor=DraftActor(
                id=row["actor_id"],
                name=row["actor_name"],
                role=row["actor_role"],
            ),
            description=row["description"],
            before_digest=row["before_digest"],
            after_digest=row["after_digest"],
        )

    def _workspace_row(self, connection: sqlite3.Connection) -> sqlite3.Row:
        workspace = connection.execute(
            """
            SELECT revision, current_state_id, undo_stack_json, redo_stack_json,
                   seed_state_json, seed_digest
            FROM draft_workspaces
            WHERE workspace_id = ?
            """,
            (self._workspace_id,),
        ).fetchone()
        if workspace is None:
            raise DraftStorageError()
        return cast(sqlite3.Row, workspace)

    def _state_row(
        self, connection: sqlite3.Connection, state_id: int
    ) -> sqlite3.Row:
        state = connection.execute(
            """
            SELECT created_revision, content_json, content_digest
            FROM draft_states
            WHERE state_id = ? AND workspace_id = ?
            """,
            (state_id, self._workspace_id),
        ).fetchone()
        if state is None:
            raise DraftStorageError()
        return cast(sqlite3.Row, state)

    def _record_change(
        self,
        connection: sqlite3.Connection,
        *,
        revision: int,
        operation: DraftOperation,
        actor: DraftActor,
        description: str,
        before_digest: str | None,
        after_digest: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO draft_activity (
                workspace_id, revision, operation, actor_id, actor_name,
                actor_role, description, before_digest, after_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._workspace_id,
                revision,
                operation,
                actor.id,
                actor.name,
                actor.role,
                description,
                before_digest,
                after_digest,
            ),
        )

    @staticmethod
    def _require_editor(actor: DraftActor) -> None:
        if actor.role not in {"environment_author", "authoring_assistant"}:
            raise DraftAuthorizationError()

    def _validated_state(self, state: dict[str, Any]) -> tuple[str, str]:
        candidate = deepcopy(state)
        try:
            if self._state_validator is not None:
                candidate = dict(self._state_validator(candidate))
            return _canonical_state(candidate)
        except (TypeError, ValueError):
            raise DraftValidationError(
                "draft state did not pass validation"
            ) from None

    @staticmethod
    def _require_revision(expected_revision: int, actual_revision: int) -> None:
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise DraftValidationError(
                "expected draft revision must be a positive integer"
            )
        if expected_revision != actual_revision:
            raise DraftRevisionConflict(
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )

    def _prepare_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS draft_states (
                    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    created_revision INTEGER NOT NULL,
                    content_json TEXT NOT NULL,
                    content_digest TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS draft_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    current_state_id INTEGER NOT NULL,
                    undo_stack_json TEXT NOT NULL,
                    redo_stack_json TEXT NOT NULL,
                    seed_state_json TEXT NOT NULL,
                    seed_digest TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS draft_activity (
                    workspace_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    description TEXT NOT NULL,
                    before_digest TEXT,
                    after_digest TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, revision)
                );
                """
            )
        os.chmod(self._database_path, 0o600)

    def _initialize(self, seed_json: str, seed_digest: str) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT seed_digest FROM draft_workspaces WHERE workspace_id = ?",
                (self._workspace_id,),
            ).fetchone()
            if existing is not None:
                if existing["seed_digest"] != seed_digest:
                    raise DraftSeedConflict()
                connection.commit()
                return
            cursor = connection.execute(
                """
                INSERT INTO draft_states (
                    workspace_id, created_revision, content_json, content_digest
                ) VALUES (?, 1, ?, ?)
                """,
                (self._workspace_id, seed_json, seed_digest),
            )
            state_id = cursor.lastrowid
            if state_id is None:
                raise DraftStorageError()
            connection.execute(
                """
                INSERT INTO draft_workspaces (
                    workspace_id, revision, current_state_id, undo_stack_json,
                    redo_stack_json, seed_state_json, seed_digest
                ) VALUES (?, 1, ?, '[]', '[]', ?, ?)
                """,
                (self._workspace_id, state_id, seed_json, seed_digest),
            )
            connection.execute(
                """
                INSERT INTO draft_activity (
                    workspace_id, revision, operation, actor_id, actor_name,
                    actor_role, description, before_digest, after_digest
                ) VALUES (?, 1, 'initialize', ?, ?, ?, ?, NULL, ?)
                """,
                (
                    self._workspace_id,
                    _STUDIO_ACTOR.id,
                    _STUDIO_ACTOR.name,
                    _STUDIO_ACTOR.role,
                    "Initialized the seeded draft",
                    seed_digest,
                ),
            )
            connection.commit()
        except DraftRepositoryError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise DraftStorageError() from None
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


def _canonical_state(state: dict[str, Any]) -> tuple[str, str]:
    _validate_json_value(state, path="state")
    canonical = json.dumps(
        state,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, f"sha256:{digest}"


def _validated_description(description: str) -> str:
    if not isinstance(description, str) or not description.strip():
        raise DraftValidationError("draft change description must not be empty")
    return description.strip()


def _validated_workspace_id(workspace_id: str) -> str:
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise DraftValidationError("draft workspace identity must not be empty")
    return workspace_id


def _stack_from_json(document: str) -> list[int]:
    value = json.loads(document)
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in value
    ):
        raise DraftStorageError()
    return value


def _canonical_stack(state_ids: list[int]) -> str:
    return json.dumps(state_ids, separators=(",", ":"))


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a value that is not JSON-compatible")
