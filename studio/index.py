"""Durable local indexes for frozen Environments and their runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager, suppress
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

StudioIndexErrorCode = Literal["invalid", "conflict", "not_found", "storage"]
RunMutationOperation = Literal["action", "verify"]
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_LOCK_STRIPE_COUNT = 64
_PROCESS_RUN_LOCK_STRIPES = tuple(
    RLock() for _ in range(_RUN_LOCK_STRIPE_COUNT)
)


class StudioIndexError(ValueError):
    """Base class for failures at the durable Studio index boundary."""

    def __init__(self, message: str, *, code: StudioIndexErrorCode) -> None:
        super().__init__(message)
        self.code = code


class StudioIndexValidationError(StudioIndexError):
    """Raised when a record cannot be represented safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid")


class StudioIndexConflict(StudioIndexError):
    """Raised when an identity is already bound to different content."""

    def __init__(self, identity: str) -> None:
        super().__init__(
            f"Studio index identity {identity!r} is already recorded differently",
            code="conflict",
        )
        self.identity = identity


class StudioIndexNotFound(StudioIndexError):
    """Raised when a requested durable identity is absent."""

    def __init__(self, identity: str) -> None:
        super().__init__(f"Studio index identity {identity!r} was not found", code="not_found")
        self.identity = identity


class StudioIndexStorageError(StudioIndexError):
    """Raised when local index persistence cannot satisfy its contract."""

    def __init__(self) -> None:
        super().__init__("the Studio index could not be persisted", code="storage")


class FrozenEnvironmentRecord(BaseModel):
    """Detached durable material needed to rehydrate one frozen Environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frozen_environment_id: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bundle_document: dict[str, Any]
    metadata_document: dict[str, Any]


class RunIndexRecord(BaseModel):
    """Detached durable routing and immutable trace-header binding for one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    frozen_environment_id: str | None = Field(default=None, min_length=1)
    trace_header_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    trace_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )


class RunTraceIntent(BaseModel):
    """Exact durable append prepared before one run-trace mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str = Field(min_length=1)
    operation: RunMutationOperation
    expected_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_journal_bytes: int = Field(ge=0)
    append_payload: bytes = Field(min_length=1)


class StudioIndex:
    """SQLite-backed index for immutable frozen Environments and run routing."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._database_path = self._artifact_root / "studio-index.sqlite3"
        self._run_lock_directory = self._artifact_root / ".run-locks"
        try:
            self._artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._run_lock_directory.mkdir(mode=0o700, exist_ok=True)
            os.chmod(self._run_lock_directory, 0o700)
            self._prepare_database()
        except StudioIndexError:
            raise
        except (OSError, sqlite3.Error):
            raise StudioIndexStorageError() from None

    @property
    def database_path(self) -> Path:
        """Return the database file owned by this index."""
        return self._database_path

    @contextmanager
    def lock_run(self, run_id: str) -> Iterator[None]:
        """Serialize one run across threads and Studio processes sharing this root."""
        run_id = _validated_identity(run_id, "run identity")
        stripe_index = _run_lock_stripe(run_id)
        lock_path = self._run_lock_directory / f"stripe-{stripe_index:02d}.lock"
        with _PROCESS_RUN_LOCK_STRIPES[stripe_index]:
            descriptor: int | None = None
            try:
                flags = os.O_RDWR | os.O_CREAT
                flags |= getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(lock_path, flags, 0o600)
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError:
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
                raise StudioIndexStorageError() from None
            try:
                yield
            finally:
                with suppress(OSError):
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                with suppress(OSError):
                    os.close(descriptor)

    def record_frozen(
        self,
        *,
        frozen_environment_id: str,
        revision_digest: str,
        bundle_document: Mapping[str, Any],
        metadata_document: Mapping[str, Any],
    ) -> FrozenEnvironmentRecord:
        """Idempotently persist one canonical frozen Environment record."""
        frozen_environment_id = _validated_identity(
            frozen_environment_id, "frozen Environment identity"
        )
        bundle_json, computed_digest = _canonical_document(bundle_document)
        metadata_json, _ = _canonical_document(metadata_document)
        if not _DIGEST_PATTERN.fullmatch(revision_digest):
            raise StudioIndexValidationError("revision digest must be a SHA-256 digest")
        if revision_digest != computed_digest:
            raise StudioIndexValidationError(
                "revision digest does not match the canonical bundle document"
            )

        with self._immediate_transaction() as connection:
            existing = connection.execute(
                """
                SELECT frozen_environment_id, revision_digest, bundle_json, metadata_json
                FROM frozen_environment_index
                WHERE frozen_environment_id = ?
                """,
                (frozen_environment_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO frozen_environment_index (
                        frozen_environment_id, revision_digest, bundle_json, metadata_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        frozen_environment_id,
                        revision_digest,
                        bundle_json,
                        metadata_json,
                    ),
                )
                existing = connection.execute(
                    """
                    SELECT frozen_environment_id, revision_digest, bundle_json, metadata_json
                    FROM frozen_environment_index
                    WHERE frozen_environment_id = ?
                    """,
                    (frozen_environment_id,),
                ).fetchone()
            elif (
                existing["revision_digest"] != revision_digest
                or existing["bundle_json"] != bundle_json
                or existing["metadata_json"] != metadata_json
            ):
                raise StudioIndexConflict(frozen_environment_id)
            if existing is None:
                raise StudioIndexStorageError()
            return _frozen_from_row(cast(sqlite3.Row, existing))

    def get_frozen(self, frozen_environment_id: str) -> FrozenEnvironmentRecord:
        """Return one detached frozen Environment record."""
        frozen_environment_id = _validated_identity(
            frozen_environment_id, "frozen Environment identity"
        )
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT frozen_environment_id, revision_digest, bundle_json, metadata_json
                    FROM frozen_environment_index
                    WHERE frozen_environment_id = ?
                    """,
                    (frozen_environment_id,),
                ).fetchone()
            if row is None:
                raise StudioIndexNotFound(frozen_environment_id)
            return _frozen_from_row(cast(sqlite3.Row, row))
        except StudioIndexError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            raise StudioIndexStorageError() from None

    def list_frozen(self) -> tuple[FrozenEnvironmentRecord, ...]:
        """Return every frozen Environment in deterministic identity order."""
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT frozen_environment_id, revision_digest, bundle_json, metadata_json
                    FROM frozen_environment_index
                    ORDER BY frozen_environment_id
                    """
                ).fetchall()
            return tuple(_frozen_from_row(row) for row in rows)
        except StudioIndexError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            raise StudioIndexStorageError() from None

    def record_run(
        self,
        *,
        run_id: str,
        frozen_environment_id: str | None,
        trace_header_digest: str,
        trace_digest: str,
    ) -> RunIndexRecord:
        """Idempotently persist one run's source and canonical header binding."""
        run_id = _validated_identity(run_id, "run identity")
        if frozen_environment_id is not None:
            frozen_environment_id = _validated_identity(
                frozen_environment_id, "frozen Environment identity"
            )
        if not _DIGEST_PATTERN.fullmatch(trace_header_digest):
            raise StudioIndexValidationError(
                "trace-header digest must be a SHA-256 digest"
            )
        if not _DIGEST_PATTERN.fullmatch(trace_digest):
            raise StudioIndexValidationError("trace digest must be a SHA-256 digest")
        with self._immediate_transaction() as connection:
            if frozen_environment_id is not None:
                frozen_exists = connection.execute(
                    """
                    SELECT 1
                    FROM frozen_environment_index
                    WHERE frozen_environment_id = ?
                    """,
                    (frozen_environment_id,),
                ).fetchone()
                if frozen_exists is None:
                    raise StudioIndexNotFound(frozen_environment_id)
            existing = connection.execute(
                """
                SELECT run_id, frozen_environment_id, trace_header_digest, trace_digest
                FROM run_index
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO run_index (
                        run_id, frozen_environment_id, trace_header_digest, trace_digest
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        frozen_environment_id,
                        trace_header_digest,
                        trace_digest,
                    ),
                )
                record = RunIndexRecord(
                    run_id=run_id,
                    frozen_environment_id=frozen_environment_id,
                    trace_header_digest=trace_header_digest,
                    trace_digest=trace_digest,
                )
            else:
                if (
                    existing["frozen_environment_id"] != frozen_environment_id
                    or existing["trace_header_digest"] != trace_header_digest
                    or existing["trace_digest"] != trace_digest
                ):
                    raise StudioIndexConflict(run_id)
                record = _run_from_row(cast(sqlite3.Row, existing))
            return record

    def prepare_run_trace(
        self,
        *,
        run_id: str,
        operation: RunMutationOperation,
        expected_trace_digest: str,
        target_trace_digest: str,
        base_journal_bytes: int,
        append_payload: bytes,
    ) -> RunTraceIntent:
        """CAS-create the exact durable intent required before a journal append."""
        intent = _validated_trace_intent(
            run_id=run_id,
            operation=operation,
            expected_trace_digest=expected_trace_digest,
            target_trace_digest=target_trace_digest,
            base_journal_bytes=base_journal_bytes,
            append_payload=append_payload,
            stored=False,
        )
        with self._immediate_transaction() as connection:
            route = connection.execute(
                """
                SELECT run_id, frozen_environment_id, trace_header_digest, trace_digest
                FROM run_index
                WHERE run_id = ?
                """,
                (intent.run_id,),
            ).fetchone()
            if route is None:
                raise StudioIndexNotFound(intent.run_id)
            if route["trace_digest"] != intent.expected_trace_digest:
                raise StudioIndexConflict(intent.run_id)
            existing = connection.execute(
                """
                SELECT run_id, operation, expected_trace_digest, target_trace_digest,
                       base_journal_bytes, append_payload
                FROM run_trace_intent
                WHERE run_id = ?
                """,
                (intent.run_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO run_trace_intent (
                        run_id, operation, expected_trace_digest, target_trace_digest,
                        base_journal_bytes, append_payload
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent.run_id,
                        intent.operation,
                        intent.expected_trace_digest,
                        intent.target_trace_digest,
                        intent.base_journal_bytes,
                        intent.append_payload,
                    ),
                )
                return intent
            stored_intent = _trace_intent_from_row(cast(sqlite3.Row, existing))
            if stored_intent != intent:
                raise StudioIndexConflict(intent.run_id)
            return stored_intent

    def get_run_trace_intent(self, run_id: str) -> RunTraceIntent | None:
        """Return the exact prepared append for a run, when one remains unresolved."""
        run_id = _validated_identity(run_id, "run identity")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT run_id, operation, expected_trace_digest, target_trace_digest,
                           base_journal_bytes, append_payload
                    FROM run_trace_intent
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
            return (
                None
                if row is None
                else _trace_intent_from_row(cast(sqlite3.Row, row))
            )
        except StudioIndexError:
            raise
        except (sqlite3.Error, ValidationError):
            raise StudioIndexStorageError() from None

    def resolve_run_trace_intent(
        self,
        intent: RunTraceIntent,
        *,
        observed_trace_digest: str,
    ) -> RunIndexRecord:
        """Atomically abort an unappended intent or commit its validated target."""
        intent = _validated_trace_intent(
            run_id=intent.run_id,
            operation=intent.operation,
            expected_trace_digest=intent.expected_trace_digest,
            target_trace_digest=intent.target_trace_digest,
            base_journal_bytes=intent.base_journal_bytes,
            append_payload=intent.append_payload,
            stored=False,
        )
        if not _DIGEST_PATTERN.fullmatch(observed_trace_digest):
            raise StudioIndexValidationError(
                "observed trace digest must be a SHA-256 digest"
            )
        if observed_trace_digest not in (
            intent.expected_trace_digest,
            intent.target_trace_digest,
        ):
            raise StudioIndexConflict(intent.run_id)

        with self._immediate_transaction() as connection:
            route = connection.execute(
                """
                SELECT run_id, frozen_environment_id, trace_header_digest, trace_digest
                FROM run_index
                WHERE run_id = ?
                """,
                (intent.run_id,),
            ).fetchone()
            if route is None:
                raise StudioIndexNotFound(intent.run_id)
            stored = connection.execute(
                """
                SELECT run_id, operation, expected_trace_digest, target_trace_digest,
                       base_journal_bytes, append_payload
                FROM run_trace_intent
                WHERE run_id = ?
                """,
                (intent.run_id,),
            ).fetchone()
            if (
                route["trace_digest"] != intent.expected_trace_digest
                or stored is None
                or _trace_intent_from_row(cast(sqlite3.Row, stored)) != intent
            ):
                raise StudioIndexConflict(intent.run_id)
            if observed_trace_digest == intent.target_trace_digest:
                cursor = connection.execute(
                    """
                    UPDATE run_index
                    SET trace_digest = ?
                    WHERE run_id = ? AND trace_digest = ?
                    """,
                    (
                        intent.target_trace_digest,
                        intent.run_id,
                        intent.expected_trace_digest,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StudioIndexConflict(intent.run_id)
            deleted = connection.execute(
                "DELETE FROM run_trace_intent WHERE run_id = ?",
                (intent.run_id,),
            )
            if deleted.rowcount != 1:
                raise StudioIndexConflict(intent.run_id)
            updated = connection.execute(
                """
                SELECT run_id, frozen_environment_id, trace_header_digest, trace_digest
                FROM run_index
                WHERE run_id = ?
                """,
                (intent.run_id,),
            ).fetchone()
            if updated is None or updated["trace_digest"] != observed_trace_digest:
                raise StudioIndexConflict(intent.run_id)
            return _run_from_row(cast(sqlite3.Row, updated))

    def get_run(self, run_id: str) -> RunIndexRecord:
        """Return the durable Environment source for one run."""
        run_id = _validated_identity(run_id, "run identity")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT run_id, frozen_environment_id, trace_header_digest, trace_digest
                    FROM run_index
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
            if row is None:
                raise StudioIndexNotFound(run_id)
            return _run_from_row(cast(sqlite3.Row, row))
        except StudioIndexError:
            raise
        except (sqlite3.Error, ValidationError):
            raise StudioIndexStorageError() from None

    def _prepare_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS frozen_environment_index (
                        frozen_environment_id TEXT PRIMARY KEY,
                        revision_digest TEXT NOT NULL,
                        bundle_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_index (
                        run_id TEXT PRIMARY KEY,
                        frozen_environment_id TEXT,
                        trace_header_digest TEXT,
                        trace_digest TEXT,
                        FOREIGN KEY (frozen_environment_id)
                            REFERENCES frozen_environment_index (frozen_environment_id)
                    )
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(run_index)")
                }
                if "trace_header_digest" not in columns:
                    connection.execute(
                        "ALTER TABLE run_index ADD COLUMN trace_header_digest TEXT"
                    )
                if "trace_digest" not in columns:
                    connection.execute(
                        "ALTER TABLE run_index ADD COLUMN trace_digest TEXT"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_trace_intent (
                        run_id TEXT PRIMARY KEY,
                        operation TEXT NOT NULL,
                        expected_trace_digest TEXT NOT NULL,
                        target_trace_digest TEXT NOT NULL,
                        base_journal_bytes INTEGER NOT NULL,
                        append_payload BLOB NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES run_index (run_id)
                    )
                    """
                )
                connection.commit()
            except sqlite3.Error:
                _rollback(connection)
                raise
        os.chmod(self._database_path, 0o600)

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except StudioIndexError:
            if connection is not None:
                _rollback(connection)
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError):
            if connection is not None:
                _rollback(connection)
            raise StudioIndexStorageError() from None
        finally:
            if connection is not None:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except sqlite3.Error:
            connection.close()
            raise


def _frozen_from_row(row: sqlite3.Row) -> FrozenEnvironmentRecord:
    bundle_document, computed_digest = _stored_document(row["bundle_json"])
    metadata_document, _ = _stored_document(row["metadata_json"])
    if row["revision_digest"] != computed_digest:
        raise StudioIndexStorageError()
    return FrozenEnvironmentRecord(
        frozen_environment_id=row["frozen_environment_id"],
        revision_digest=row["revision_digest"],
        bundle_document=deepcopy(bundle_document),
        metadata_document=deepcopy(metadata_document),
    )


def _run_from_row(row: sqlite3.Row) -> RunIndexRecord:
    return RunIndexRecord(
        run_id=row["run_id"],
        frozen_environment_id=row["frozen_environment_id"],
        trace_header_digest=row["trace_header_digest"],
        trace_digest=row["trace_digest"],
    )


def _trace_intent_from_row(row: sqlite3.Row) -> RunTraceIntent:
    return _validated_trace_intent(
        run_id=row["run_id"],
        operation=row["operation"],
        expected_trace_digest=row["expected_trace_digest"],
        target_trace_digest=row["target_trace_digest"],
        base_journal_bytes=row["base_journal_bytes"],
        append_payload=row["append_payload"],
        stored=True,
    )


def _validated_trace_intent(
    *,
    run_id: object,
    operation: object,
    expected_trace_digest: object,
    target_trace_digest: object,
    base_journal_bytes: object,
    append_payload: object,
    stored: bool,
) -> RunTraceIntent:
    try:
        intent = RunTraceIntent.model_validate(
            {
                "run_id": run_id,
                "operation": operation,
                "expected_trace_digest": expected_trace_digest,
                "target_trace_digest": target_trace_digest,
                "base_journal_bytes": base_journal_bytes,
                "append_payload": append_payload,
            }
        )
    except ValidationError:
        if stored:
            raise StudioIndexStorageError() from None
        raise StudioIndexValidationError("run trace intent is invalid") from None
    if intent.expected_trace_digest == intent.target_trace_digest:
        if stored:
            raise StudioIndexStorageError()
        raise StudioIndexValidationError(
            "run trace intent must advance to a different digest"
        )
    if not intent.append_payload.endswith(b"\n"):
        if stored:
            raise StudioIndexStorageError()
        raise StudioIndexValidationError(
            "run trace intent payload must end at a canonical record boundary"
        )
    try:
        lines = intent.append_payload.decode("utf-8").splitlines()
        if not lines:
            raise ValueError("prepared append is empty")
        for line in lines:
            document = json.loads(line)
            if not isinstance(document, dict):
                raise ValueError("prepared append records must be objects")
            _validate_json_value(document, path="prepared append")
            canonical = json.dumps(
                document,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if canonical != line:
                raise ValueError("prepared append record is not canonical")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        if stored:
            raise StudioIndexStorageError() from None
        raise StudioIndexValidationError(
            "run trace intent payload must contain canonical JSON records"
        ) from None
    return intent


def _stored_document(raw_document: object) -> tuple[dict[str, Any], str]:
    if not isinstance(raw_document, str):
        raise StudioIndexStorageError()
    try:
        parsed = json.loads(raw_document)
        if not isinstance(parsed, dict):
            raise StudioIndexStorageError()
        canonical, digest = _canonical_document(parsed)
    except (json.JSONDecodeError, StudioIndexValidationError):
        raise StudioIndexStorageError() from None
    if canonical != raw_document:
        raise StudioIndexStorageError()
    return parsed, digest


def _rollback(connection: sqlite3.Connection) -> None:
    with suppress(sqlite3.Error):
        connection.rollback()


def _validated_identity(identity: str, label: str) -> str:
    if not isinstance(identity, str) or not identity.strip():
        raise StudioIndexValidationError(f"{label} must not be empty")
    return identity


def _run_lock_stripe(run_id: str) -> int:
    stable_hash = hashlib.sha256(run_id.encode("utf-8")).digest()
    return int.from_bytes(stable_hash[:8], "big") % _RUN_LOCK_STRIPE_COUNT


def _canonical_document(document: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(document, Mapping):
        raise StudioIndexValidationError("indexed documents must be JSON objects")
    detached = dict(document)
    try:
        _validate_json_value(detached, path="document")
        canonical = json.dumps(
            detached,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise StudioIndexValidationError(
            "indexed documents must contain only JSON-compatible values"
        ) from None
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, f"sha256:{digest}"


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
