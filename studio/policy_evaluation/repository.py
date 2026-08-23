"""Durable write-once storage for local model-evaluation plans and attempts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat as stat_module
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from studio.runtime import validate_completed_run_snapshot

from .artifact_safety import validate_artifact_safe
from .attempt_trace_store import (
    AttemptTraceStore,
    AttemptTraceStoreError,
    validate_trace_artifact_identity,
)
from .model_runner import EvaluationAttempt, ModelIdentity

EvaluationStatus = Literal["queued", "running", "completed", "interrupted"]
RepositoryErrorCode = Literal["conflict", "not_found", "storage"]
AttemptDisposition = Literal["scientific_success", "scientific_failure", "infrastructure_error"]
_DATABASE_NAME = "evaluations.sqlite3"
_LOCK_DIRECTORY_NAME = ".evaluation-locks"
_SCHEMA_VERSION = 3
_EVALUATION_ID = re.compile(r"^evaluation-[0-9a-f]{32}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_SLOT_COLUMNS = frozenset(
    {
        "evaluation_id",
        "attempt_id",
        "ordinal",
        "scenario_id",
        "trace_ref",
        "trace_digest",
        "disposition",
        "summary",
        "interaction_digest",
        "runtime_trace_digest",
        "result_digest",
        "authenticated_local_runtime",
        "index_digest",
    }
)
_PLAN_COLUMN_SCHEMA = (
    ("created_sequence", "INTEGER", 0, None, 1, 0),
    ("evaluation_id", "TEXT", 1, None, 0, 0),
    ("plan_json", "TEXT", 1, None, 0, 0),
    ("plan_digest", "TEXT", 1, None, 0, 0),
    ("status", "TEXT", 1, None, 0, 0),
)
_ATTEMPT_SLOT_COLUMN_SCHEMA = (
    ("evaluation_id", "TEXT", 1, None, 1, 0),
    ("attempt_id", "TEXT", 1, None, 2, 0),
    ("ordinal", "INTEGER", 1, None, 0, 0),
    ("scenario_id", "TEXT", 1, None, 0, 0),
    ("trace_ref", "TEXT", 0, None, 0, 0),
    ("trace_digest", "TEXT", 0, None, 0, 0),
    ("disposition", "TEXT", 0, None, 0, 0),
    ("summary", "TEXT", 0, None, 0, 0),
    ("interaction_digest", "TEXT", 0, None, 0, 0),
    ("runtime_trace_digest", "TEXT", 0, None, 0, 0),
    ("result_digest", "TEXT", 0, None, 0, 0),
    ("authenticated_local_runtime", "INTEGER", 0, None, 0, 0),
    ("index_digest", "TEXT", 0, None, 0, 0),
)
_PLAN_UNIQUE_INDEX_SCHEMA = (
    ("u", 0, (("evaluation_id", 0, "BINARY"),)),
)
_ATTEMPT_SLOT_UNIQUE_INDEX_SCHEMA = (
    (
        "pk",
        0,
        (("evaluation_id", 0, "BINARY"), ("attempt_id", 0, "BINARY")),
    ),
    (
        "u",
        0,
        (("evaluation_id", 0, "BINARY"), ("ordinal", 0, "BINARY")),
    ),
    (
        "u",
        0,
        (("evaluation_id", 0, "BINARY"), ("scenario_id", 0, "BINARY")),
    ),
)
_ATTEMPT_SLOT_FOREIGN_KEY_SCHEMA = (
    (
        "evaluation_plans",
        "evaluation_id",
        "evaluation_id",
        "NO ACTION",
        "NO ACTION",
        "NONE",
    ),
)
_PLAN_CHECK_SCHEMA = (
    "status IN ('queued', 'running', 'completed', 'interrupted')",
)
_ATTEMPT_SLOT_CHECK_SCHEMA = (
    "ordinal >= 0",
    """disposition IN (
        'scientific_success',
        'scientific_failure',
        'infrastructure_error'
    )""",
    "authenticated_local_runtime IN (0, 1)",
    """(
        trace_ref IS NULL
        AND trace_digest IS NULL
        AND disposition IS NULL
        AND summary IS NULL
        AND interaction_digest IS NULL
        AND runtime_trace_digest IS NULL
        AND result_digest IS NULL
        AND authenticated_local_runtime IS NULL
        AND index_digest IS NULL
    )
    OR (
        trace_ref IS NOT NULL
        AND trace_digest IS NOT NULL
        AND disposition IS NOT NULL
        AND summary IS NOT NULL
        AND interaction_digest IS NOT NULL
        AND runtime_trace_digest IS NOT NULL
        AND authenticated_local_runtime IS NOT NULL
        AND index_digest IS NOT NULL
        AND (
            (
                disposition = 'infrastructure_error'
                AND result_digest IS NULL
            )
            OR (
                disposition IN ('scientific_success', 'scientific_failure')
                AND result_digest IS NOT NULL
            )
        )
    )""",
)
_PLAN_TABLE_DEFINITION = """(
    created_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL UNIQUE,
    plan_json TEXT NOT NULL,
    plan_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'interrupted')
    )
)"""
_ATTEMPT_SLOT_TABLE_DEFINITION = """(
    evaluation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    scenario_id TEXT NOT NULL,
    trace_ref TEXT,
    trace_digest TEXT,
    disposition TEXT CHECK (
        disposition IN (
            'scientific_success',
            'scientific_failure',
            'infrastructure_error'
        )
    ),
    summary TEXT,
    interaction_digest TEXT,
    runtime_trace_digest TEXT,
    result_digest TEXT,
    authenticated_local_runtime INTEGER CHECK (
        authenticated_local_runtime IN (0, 1)
    ),
    index_digest TEXT,
    PRIMARY KEY (evaluation_id, attempt_id),
    UNIQUE (evaluation_id, ordinal),
    UNIQUE (evaluation_id, scenario_id),
    FOREIGN KEY (evaluation_id)
        REFERENCES evaluation_plans(evaluation_id),
    CHECK (
        (
            trace_ref IS NULL
            AND trace_digest IS NULL
            AND disposition IS NULL
            AND summary IS NULL
            AND interaction_digest IS NULL
            AND runtime_trace_digest IS NULL
            AND result_digest IS NULL
            AND authenticated_local_runtime IS NULL
            AND index_digest IS NULL
        )
        OR (
            trace_ref IS NOT NULL
            AND trace_digest IS NOT NULL
            AND disposition IS NOT NULL
            AND summary IS NOT NULL
            AND interaction_digest IS NOT NULL
            AND runtime_trace_digest IS NOT NULL
            AND authenticated_local_runtime IS NOT NULL
            AND index_digest IS NOT NULL
            AND (
                (
                    disposition = 'infrastructure_error'
                    AND result_digest IS NULL
                )
                OR (
                    disposition IN (
                        'scientific_success', 'scientific_failure'
                    )
                    AND result_digest IS NOT NULL
                )
            )
        )
    )
)"""
_EXECUTION_LOCK_STRIPE_COUNT = 64
_PROCESS_EXECUTION_LOCKS = tuple(RLock() for _ in range(_EXECUTION_LOCK_STRIPE_COUNT))


class EvaluationRepositoryError(ValueError):
    """Safe failure at the durable evaluation boundary."""

    def __init__(self, message: str, *, code: RepositoryErrorCode) -> None:
        super().__init__(message)
        self.code = code


class EvaluationPlan(BaseModel):
    """Immutable server-owned identity of one local calibration matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    plan_revision: Literal["science-environment-evaluation-plan/1"]
    profile: Literal["base-gemma-development-v1"]
    environment_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    split: Literal["development"]
    curriculum_package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model: ModelIdentity
    model_revision: Literal["ee0ef6023621cff504d758262d4e04895a5af4a2"]
    objective: str = Field(min_length=1)
    scenario_ids: tuple[str, ...] = Field(min_length=32, max_length=32)

    @model_validator(mode="after")
    def validate_fixed_matrix(self) -> EvaluationPlan:
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("evaluation scenario identities must be unique")
        expected_model = ModelIdentity(
            provider="local-openai-compatible",
            requested_model="google/gemma-4-E4B-it",
            adapter_revision="local-gemma-openai-chat/1",
        )
        if self.model != expected_model:
            raise ValueError("evaluation plan must use the approved base-Gemma identity")
        return self


@dataclass(frozen=True)
class StoredAttemptSlot:
    """One predeclared durable position in an evaluation matrix."""

    attempt_id: str
    ordinal: int
    scenario_id: str
    attempt: EvaluationAttempt | None


@dataclass(frozen=True)
class StoredEvaluation:
    """Integrity-validated evaluation record returned to orchestration."""

    evaluation_id: str
    plan: EvaluationPlan
    status: EvaluationStatus
    slots: tuple[StoredAttemptSlot, ...]


@dataclass(frozen=True)
class StoredAttemptIndex:
    """Minimal terminal metadata used without opening the canonical trace."""

    disposition: AttemptDisposition
    summary: str
    interaction_digest: str
    runtime_trace_digest: str
    result_digest: str | None
    authenticated_local_runtime: bool


@dataclass(frozen=True)
class StoredAttemptIndexSlot:
    """One lightweight predeclared slot in the SQLite progress index."""

    attempt_id: str
    ordinal: int
    scenario_id: str
    index: StoredAttemptIndex | None


@dataclass(frozen=True)
class StoredEvaluationIndex:
    """Plan and progress index returned without reading attempt artifacts."""

    evaluation_id: str
    plan: EvaluationPlan
    status: EvaluationStatus
    slots: tuple[StoredAttemptIndexSlot, ...]


class EvaluationRepository:
    """SQLite index over immutable plans and write-once JSONL attempt traces."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._database_path = self._artifact_root / _DATABASE_NAME
        try:
            self._artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            with self._open_artifact_root() as artifact_root_fd:
                self._ensure_private_directory(
                    artifact_root_fd,
                    _LOCK_DIRECTORY_NAME,
                )
                self._ensure_database_file(artifact_root_fd)
            self._trace_store = AttemptTraceStore(self._artifact_root)
            self._prepare_database()
            self._cleanup_trace_crash_residue()
        except EvaluationRepositoryError:
            raise
        except (AttemptTraceStoreError, OSError, sqlite3.Error):
            raise EvaluationRepositoryError(
                "the evaluation repository could not be opened",
                code="storage",
            ) from None

    @property
    def database_path(self) -> Path:
        return self._database_path

    def create(self, plan: EvaluationPlan) -> StoredEvaluation:
        """Persist one immutable plan and all of its empty attempt slots."""
        if not isinstance(plan, EvaluationPlan):
            raise TypeError("evaluation repository requires a typed plan")
        evaluation_id = f"evaluation-{uuid4().hex}"
        plan_json, plan_digest = _canonical_model(plan)
        try:
            with self._immediate_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO evaluation_plans(
                        evaluation_id, plan_json, plan_digest, status
                    ) VALUES (?, ?, ?, 'queued')
                    """,
                    (evaluation_id, plan_json, plan_digest),
                )
                connection.executemany(
                    """
                    INSERT INTO evaluation_attempt_slots(
                        evaluation_id, attempt_id, ordinal, scenario_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    tuple(
                        (
                            evaluation_id,
                            _attempt_id(ordinal),
                            ordinal,
                            scenario_id,
                        )
                        for ordinal, scenario_id in enumerate(plan.scenario_ids)
                    ),
                )
            return self.load(evaluation_id)
        except EvaluationRepositoryError:
            raise
        except sqlite3.IntegrityError:
            raise EvaluationRepositoryError(
                "the evaluation identity is already reserved",
                code="conflict",
            ) from None

    def load(self, evaluation_id: str) -> StoredEvaluation:
        """Load and validate one complete durable record."""
        _validate_evaluation_id(evaluation_id)
        try:
            with closing(self._connect()) as connection:
                return self._load_record(connection, evaluation_id)
        except EvaluationRepositoryError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError, ValueError):
            raise EvaluationRepositoryError(
                "the evaluation repository failed integrity validation",
                code="storage",
            ) from None

    def list(self) -> tuple[StoredEvaluationIndex, ...]:
        """Return newest-first progress indexes without reading trace artifacts."""
        try:
            with closing(self._connect()) as connection:
                identities = tuple(
                    row["evaluation_id"]
                    for row in connection.execute(
                        """
                        SELECT evaluation_id
                        FROM evaluation_plans
                        ORDER BY created_sequence DESC
                        """
                    )
                )
                return tuple(self._load_index(connection, identity) for identity in identities)
        except EvaluationRepositoryError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError, ValueError):
            raise EvaluationRepositoryError(
                "the evaluation repository failed integrity validation",
                code="storage",
            ) from None

    def claim(self, evaluation_id: str) -> StoredEvaluation:
        """Claim a queued or interrupted matrix for one execution pass."""
        try:
            with self._immediate_transaction() as connection:
                record = self._load_record(connection, evaluation_id)
                if record.status == "completed":
                    return record
                if record.status == "running":
                    raise EvaluationRepositoryError(
                        "the evaluation is already running",
                        code="conflict",
                    )
                updated = connection.execute(
                    """
                    UPDATE evaluation_plans
                    SET status = 'running'
                    WHERE evaluation_id = ? AND status = ?
                    """,
                    (evaluation_id, record.status),
                )
                if updated.rowcount != 1:
                    raise EvaluationRepositoryError(
                        "the evaluation status changed before execution",
                        code="conflict",
                    )
            return self.load(evaluation_id)
        except EvaluationRepositoryError:
            raise

    def record_attempt(
        self,
        evaluation_id: str,
        attempt_id: str,
        attempt: EvaluationAttempt,
    ) -> StoredEvaluationIndex:
        """Fill exactly one predeclared slot without permitting replacement."""
        if not isinstance(attempt, EvaluationAttempt):
            raise TypeError("evaluation repository requires a typed attempt")
        try:
            with self._immediate_transaction() as connection:
                record = self._load_index(connection, evaluation_id)
                if record.status != "running":
                    raise EvaluationRepositoryError(
                        "evaluation attempts are accepted only while running",
                        code="conflict",
                    )
                slot = next(
                    (item for item in record.slots if item.attempt_id == attempt_id),
                    None,
                )
                if slot is None:
                    raise EvaluationRepositoryError(
                        "evaluation attempt slot was not found",
                        code="not_found",
                    )
                if slot.index is not None:
                    raise EvaluationRepositoryError(
                        "evaluation attempt slots are write-once",
                        code="conflict",
                    )
                _validate_attempt(
                    record.plan,
                    StoredAttemptSlot(
                        attempt_id=slot.attempt_id,
                        ordinal=slot.ordinal,
                        scenario_id=slot.scenario_id,
                        attempt=None,
                    ),
                    attempt,
                )
                artifact = self._trace_store.persist(
                    evaluation_id=evaluation_id,
                    attempt_id=attempt_id,
                    attempt=attempt,
                )
                index = _attempt_index(attempt)
                updated = connection.execute(
                    """
                    UPDATE evaluation_attempt_slots
                    SET trace_ref = ?, trace_digest = ?,
                        disposition = ?, summary = ?,
                        interaction_digest = ?, runtime_trace_digest = ?,
                        result_digest = ?, authenticated_local_runtime = ?,
                        index_digest = ?
                    WHERE evaluation_id = ? AND attempt_id = ?
                      AND trace_ref IS NULL AND trace_digest IS NULL
                    """,
                    (
                        artifact.reference,
                        artifact.digest,
                        index.disposition,
                        index.summary,
                        index.interaction_digest,
                        index.runtime_trace_digest,
                        index.result_digest,
                        int(index.authenticated_local_runtime),
                        _attempt_index_digest(
                            evaluation_id=evaluation_id,
                            attempt_id=attempt_id,
                            ordinal=slot.ordinal,
                            scenario_id=slot.scenario_id,
                            trace_ref=artifact.reference,
                            trace_digest=artifact.digest,
                            index=index,
                        ),
                        evaluation_id,
                        attempt_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise EvaluationRepositoryError(
                        "evaluation attempt slots are write-once",
                        code="conflict",
                    )
            with closing(self._connect()) as connection:
                return self._load_index(connection, evaluation_id)
        except AttemptTraceStoreError:
            raise EvaluationRepositoryError(
                "the evaluation repository failed integrity validation",
                code="storage",
            ) from None
        except EvaluationRepositoryError:
            raise

    def complete(self, evaluation_id: str) -> StoredEvaluation:
        """Seal a matrix only after every predeclared slot has an attempt."""
        try:
            with self._immediate_transaction() as connection:
                record = self._load_record(connection, evaluation_id)
                if record.status == "completed":
                    return record
                if record.status != "running":
                    raise EvaluationRepositoryError(
                        "only a running evaluation can be completed",
                        code="conflict",
                    )
                if any(slot.attempt is None for slot in record.slots):
                    raise EvaluationRepositoryError(
                        "the evaluation matrix is not complete",
                        code="conflict",
                    )
                updated = connection.execute(
                    """
                    UPDATE evaluation_plans
                    SET status = 'completed'
                    WHERE evaluation_id = ? AND status = 'running'
                    """,
                    (evaluation_id,),
                )
                if updated.rowcount != 1:
                    raise EvaluationRepositoryError(
                        "the evaluation status changed before completion",
                        code="conflict",
                    )
            return self.load(evaluation_id)
        except EvaluationRepositoryError:
            raise

    def interrupt(self, evaluation_id: str) -> StoredEvaluation:
        """Retain completed slots while marking an unfinished execution stopped."""
        try:
            with self._immediate_transaction() as connection:
                record = self._load_record(connection, evaluation_id)
                if record.status == "running":
                    connection.execute(
                        """
                        UPDATE evaluation_plans
                        SET status = 'interrupted'
                        WHERE evaluation_id = ? AND status = 'running'
                        """,
                        (evaluation_id,),
                    )
            return self.load(evaluation_id)
        except EvaluationRepositoryError:
            raise

    @contextmanager
    def execution_lock(
        self,
        evaluation_id: str,
        *,
        blocking: bool = True,
    ) -> Iterator[bool]:
        """Serialize one evaluation across threads and local Studio processes."""
        _validate_evaluation_id(evaluation_id)
        stripe = _execution_lock_stripe(evaluation_id)
        process_lock = _PROCESS_EXECUTION_LOCKS[stripe]
        process_lock_acquired = process_lock.acquire(blocking=blocking)
        if not process_lock_acquired:
            yield False
            return
        try:
            descriptor: int | None = None
            acquired = False
            try:
                with (
                    self._open_artifact_root() as artifact_root_fd,
                    self._open_owned_directory(
                        artifact_root_fd,
                        _LOCK_DIRECTORY_NAME,
                    ) as lock_directory_fd,
                ):
                    os.fchmod(lock_directory_fd, 0o700)
                    flags = os.O_RDWR | os.O_CREAT
                    flags |= getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(
                        f"{evaluation_id}.lock",
                        flags,
                        0o600,
                        dir_fd=lock_directory_fd,
                    )
                    self._validate_owned_regular_file(descriptor)
                    os.fchmod(descriptor, 0o600)
                    operation = fcntl.LOCK_EX
                    if not blocking:
                        operation |= fcntl.LOCK_NB
                    try:
                        fcntl.flock(descriptor, operation)
                        acquired = True
                    except BlockingIOError:
                        if blocking:
                            raise
                    yield acquired
            except EvaluationRepositoryError:
                raise
            except OSError:
                raise EvaluationRepositoryError(
                    "the evaluation execution lock could not be acquired",
                    code="storage",
                ) from None
            finally:
                if descriptor is not None:
                    if acquired:
                        with suppress(OSError):
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                    with suppress(OSError):
                        os.close(descriptor)
        finally:
            process_lock.release()

    def reconcile_stale_running(self) -> tuple[str, ...]:
        """Mark only unlocked running rows interrupted after a process restart."""
        try:
            with closing(self._connect()) as connection:
                running = tuple(
                    row["evaluation_id"]
                    for row in connection.execute(
                        """
                        SELECT evaluation_id
                        FROM evaluation_plans
                        WHERE status = 'running'
                        ORDER BY created_sequence
                        """
                    )
                )
            interrupted: list[str] = []
            for evaluation_id in running:
                with self.execution_lock(evaluation_id, blocking=False) as acquired:
                    if not acquired:
                        continue
                    with self._immediate_transaction() as connection:
                        updated = connection.execute(
                            """
                            UPDATE evaluation_plans
                            SET status = 'interrupted'
                            WHERE evaluation_id = ? AND status = 'running'
                            """,
                            (evaluation_id,),
                        )
                    if updated.rowcount == 1:
                        interrupted.append(evaluation_id)
            return tuple(interrupted)
        except EvaluationRepositoryError:
            raise
        except sqlite3.Error:
            raise EvaluationRepositoryError(
                "the evaluation repository could not reconcile interrupted work",
                code="storage",
            ) from None

    def _load_record(
        self,
        connection: sqlite3.Connection,
        evaluation_id: str,
    ) -> StoredEvaluation:
        row = connection.execute(
            """
            SELECT evaluation_id, plan_json, plan_digest, status
            FROM evaluation_plans
            WHERE evaluation_id = ?
            """,
            (evaluation_id,),
        ).fetchone()
        if row is None:
            raise EvaluationRepositoryError(
                f"unknown evaluation {evaluation_id!r}",
                code="not_found",
            )
        plan = _stored_model(
            raw_json=row["plan_json"],
            stored_digest=row["plan_digest"],
            model_type=EvaluationPlan,
        )
        status = cast(EvaluationStatus, row["status"])
        if status not in ("queued", "running", "completed", "interrupted"):
            raise ValueError("evaluation status is invalid")
        slot_rows = tuple(
            connection.execute(
                """
                SELECT evaluation_id, attempt_id, ordinal, scenario_id,
                       trace_ref, trace_digest, disposition, summary,
                       interaction_digest, runtime_trace_digest, result_digest,
                       authenticated_local_runtime, index_digest
                FROM evaluation_attempt_slots
                WHERE evaluation_id = ?
                ORDER BY ordinal
                """,
                (evaluation_id,),
            )
        )
        expected = tuple(
            (_attempt_id(ordinal), ordinal, scenario_id)
            for ordinal, scenario_id in enumerate(plan.scenario_ids)
        )
        observed = tuple(
            (row["attempt_id"], row["ordinal"], row["scenario_id"]) for row in slot_rows
        )
        if observed != expected:
            raise ValueError("evaluation attempt slots do not match the plan")
        slots: list[StoredAttemptSlot] = []
        for slot_row in slot_rows:
            stored_index = _stored_attempt_index(slot_row)
            attempt = None
            if stored_index is not None:
                trace_ref = slot_row["trace_ref"]
                trace_digest = slot_row["trace_digest"]
                if not isinstance(trace_ref, str) or not isinstance(trace_digest, str):
                    raise ValueError("evaluation attempt trace reference is invalid")
                try:
                    attempt = self._trace_store.load(
                        reference=trace_ref,
                        digest=trace_digest,
                        evaluation_id=evaluation_id,
                        attempt_id=slot_row["attempt_id"],
                        scenario_id=slot_row["scenario_id"],
                    )
                except AttemptTraceStoreError as error:
                    raise ValueError(
                        "stored evaluation attempt failed integrity validation"
                    ) from error
            if attempt is not None:
                provisional_slot = StoredAttemptSlot(
                    attempt_id=slot_row["attempt_id"],
                    ordinal=slot_row["ordinal"],
                    scenario_id=slot_row["scenario_id"],
                    attempt=None,
                )
                try:
                    _validate_attempt(plan, provisional_slot, attempt)
                except EvaluationRepositoryError as error:
                    raise ValueError(
                        "stored evaluation attempt failed integrity validation"
                    ) from error
                if _attempt_index(attempt) != stored_index:
                    raise ValueError("stored evaluation attempt index failed integrity validation")
            slots.append(
                StoredAttemptSlot(
                    attempt_id=slot_row["attempt_id"],
                    ordinal=slot_row["ordinal"],
                    scenario_id=slot_row["scenario_id"],
                    attempt=attempt,
                )
            )
        if status == "completed" and any(slot.attempt is None for slot in slots):
            raise ValueError("a completed evaluation has an empty attempt slot")
        return StoredEvaluation(
            evaluation_id=row["evaluation_id"],
            plan=plan,
            status=status,
            slots=tuple(slots),
        )

    def _load_index(
        self,
        connection: sqlite3.Connection,
        evaluation_id: str,
    ) -> StoredEvaluationIndex:
        row = connection.execute(
            """
            SELECT evaluation_id, plan_json, plan_digest, status
            FROM evaluation_plans
            WHERE evaluation_id = ?
            """,
            (evaluation_id,),
        ).fetchone()
        if row is None:
            raise EvaluationRepositoryError(
                f"unknown evaluation {evaluation_id!r}",
                code="not_found",
            )
        plan = _stored_model(
            raw_json=row["plan_json"],
            stored_digest=row["plan_digest"],
            model_type=EvaluationPlan,
        )
        status = cast(EvaluationStatus, row["status"])
        if status not in ("queued", "running", "completed", "interrupted"):
            raise ValueError("evaluation status is invalid")
        slot_rows = tuple(
            connection.execute(
                """
                SELECT evaluation_id, attempt_id, ordinal, scenario_id,
                       trace_ref, trace_digest, disposition, summary,
                       interaction_digest, runtime_trace_digest, result_digest,
                       authenticated_local_runtime, index_digest
                FROM evaluation_attempt_slots
                WHERE evaluation_id = ?
                ORDER BY ordinal
                """,
                (evaluation_id,),
            )
        )
        expected = tuple(
            (_attempt_id(ordinal), ordinal, scenario_id)
            for ordinal, scenario_id in enumerate(plan.scenario_ids)
        )
        observed = tuple(
            (slot_row["attempt_id"], slot_row["ordinal"], slot_row["scenario_id"])
            for slot_row in slot_rows
        )
        if observed != expected:
            raise ValueError("evaluation attempt slots do not match the plan")
        slots = tuple(
            StoredAttemptIndexSlot(
                attempt_id=slot_row["attempt_id"],
                ordinal=slot_row["ordinal"],
                scenario_id=slot_row["scenario_id"],
                index=_stored_attempt_index(slot_row),
            )
            for slot_row in slot_rows
        )
        if status == "completed" and any(slot.index is None for slot in slots):
            raise ValueError("a completed evaluation has an empty attempt slot")
        return StoredEvaluationIndex(
            evaluation_id=row["evaluation_id"],
            plan=plan,
            status=status,
            slots=slots,
        )

    def _prepare_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                schema_version = connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
                if not 0 <= schema_version <= _SCHEMA_VERSION:
                    raise EvaluationRepositoryError(
                        "the evaluation repository schema is unsupported",
                        code="storage",
                    )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS evaluation_plans "
                    + _PLAN_TABLE_DEFINITION
                )
                _validate_table_schema(
                    connection,
                    table_name="evaluation_plans",
                    expected_columns=_PLAN_COLUMN_SCHEMA,
                    expected_unique_indexes=_PLAN_UNIQUE_INDEX_SCHEMA,
                    expected_foreign_keys=(),
                    expected_checks=_PLAN_CHECK_SCHEMA,
                    expected_autoincrement=True,
                    expected_create_sql=(
                        "CREATE TABLE evaluation_plans " + _PLAN_TABLE_DEFINITION
                    ),
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(evaluation_attempt_slots)")
                }
                if not columns:
                    _create_attempt_slot_table(connection, "evaluation_attempt_slots")
                elif "attempt_json" in columns:
                    embedded_attempts = connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM evaluation_attempt_slots
                        WHERE attempt_json IS NOT NULL OR attempt_digest IS NOT NULL
                        """
                    ).fetchone()[0]
                    if embedded_attempts:
                        raise EvaluationRepositoryError(
                            "legacy embedded evaluation attempts require explicit migration",
                            code="storage",
                        )
                    _create_attempt_slot_table(connection, "evaluation_attempt_slots_v2")
                    connection.execute(
                        """
                        INSERT INTO evaluation_attempt_slots_v2(
                            evaluation_id, attempt_id, ordinal, scenario_id
                        )
                        SELECT evaluation_id, attempt_id, ordinal, scenario_id
                        FROM evaluation_attempt_slots
                        """
                    )
                    connection.execute("DROP TABLE evaluation_attempt_slots")
                    connection.execute(
                        "ALTER TABLE evaluation_attempt_slots_v2 RENAME TO evaluation_attempt_slots"
                    )
                elif "index_digest" not in columns and {
                    "trace_ref",
                    "trace_digest",
                }.issubset(columns):
                    connection.execute(
                        "ALTER TABLE evaluation_attempt_slots ADD COLUMN index_digest TEXT"
                    )
                    rows = tuple(
                        connection.execute(
                            """
                            SELECT trace_ref, trace_digest, disposition, summary,
                                   interaction_digest, runtime_trace_digest,
                                   result_digest, authenticated_local_runtime,
                                   evaluation_id, attempt_id, ordinal, scenario_id
                            FROM evaluation_attempt_slots
                            WHERE trace_ref IS NOT NULL
                            """
                        )
                    )
                    for row in rows:
                        try:
                            index = self._validated_v2_migration_index(
                                connection,
                                row,
                            )
                        except (
                            AttemptTraceStoreError,
                            EvaluationRepositoryError,
                            ValidationError,
                            ValueError,
                        ):
                            raise EvaluationRepositoryError(
                                "legacy evaluation index migration failed integrity validation",
                                code="storage",
                            ) from None
                        connection.execute(
                            """
                            UPDATE evaluation_attempt_slots
                            SET index_digest = ?
                            WHERE evaluation_id = ? AND attempt_id = ?
                            """,
                            (
                                _attempt_index_digest(
                                    evaluation_id=row["evaluation_id"],
                                    attempt_id=row["attempt_id"],
                                    ordinal=row["ordinal"],
                                    scenario_id=row["scenario_id"],
                                    trace_ref=row["trace_ref"],
                                    trace_digest=row["trace_digest"],
                                    index=index,
                                ),
                                row["evaluation_id"],
                                row["attempt_id"],
                            ),
                        )
                    _rebuild_current_attempt_slot_table(connection)
                elif not _ATTEMPT_SLOT_COLUMNS.issubset(columns):
                    raise EvaluationRepositoryError(
                        "the evaluation repository schema is unsupported",
                        code="storage",
                    )
                _validate_table_schema(
                    connection,
                    table_name="evaluation_attempt_slots",
                    expected_columns=_ATTEMPT_SLOT_COLUMN_SCHEMA,
                    expected_unique_indexes=_ATTEMPT_SLOT_UNIQUE_INDEX_SCHEMA,
                    expected_foreign_keys=_ATTEMPT_SLOT_FOREIGN_KEY_SCHEMA,
                    expected_checks=_ATTEMPT_SLOT_CHECK_SCHEMA,
                    expected_autoincrement=False,
                    expected_create_sql=(
                        "CREATE TABLE evaluation_attempt_slots "
                        + _ATTEMPT_SLOT_TABLE_DEFINITION
                    ),
                )
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                connection.commit()
            except EvaluationRepositoryError:
                connection.rollback()
                raise
            except sqlite3.Error:
                connection.rollback()
                raise

    def _validated_v2_migration_index(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> StoredAttemptIndex:
        """Authenticate one pre-index-digest row against its immutable trace."""
        stored_index = _stored_attempt_index_without_digest(row)
        evaluation_id = row["evaluation_id"]
        attempt_id = row["attempt_id"]
        ordinal = row["ordinal"]
        scenario_id = row["scenario_id"]
        if (
            stored_index is None
            or not isinstance(evaluation_id, str)
            or not isinstance(attempt_id, str)
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not isinstance(scenario_id, str)
        ):
            raise ValueError("legacy evaluation attempt index is incomplete")
        _validate_evaluation_id(evaluation_id)
        plan_row = connection.execute(
            """
            SELECT plan_json, plan_digest
            FROM evaluation_plans
            WHERE evaluation_id = ?
            """,
            (evaluation_id,),
        ).fetchone()
        if plan_row is None:
            raise ValueError("legacy evaluation attempt has no plan")
        plan = cast(
            EvaluationPlan,
            _stored_model(
                raw_json=plan_row["plan_json"],
                stored_digest=plan_row["plan_digest"],
                model_type=EvaluationPlan,
            ),
        )
        if (
            ordinal < 0
            or ordinal >= len(plan.scenario_ids)
            or attempt_id != _attempt_id(ordinal)
            or scenario_id != plan.scenario_ids[ordinal]
        ):
            raise ValueError("legacy evaluation attempt slot does not match its plan")
        slot = StoredAttemptSlot(
            attempt_id=attempt_id,
            ordinal=ordinal,
            scenario_id=scenario_id,
            attempt=None,
        )
        attempt = self._trace_store.load(
            reference=row["trace_ref"],
            digest=row["trace_digest"],
            evaluation_id=evaluation_id,
            attempt_id=attempt_id,
            scenario_id=scenario_id,
        )
        _validate_attempt(plan, slot, attempt)
        derived_index = _attempt_index(attempt)
        if derived_index != stored_index:
            raise ValueError("legacy evaluation attempt index does not match its trace")
        return derived_index

    def _cleanup_trace_crash_residue(self) -> None:
        try:
            with self._immediate_transaction() as connection:
                references = {
                    row["trace_ref"]
                    for row in connection.execute(
                        """
                        SELECT trace_ref
                        FROM evaluation_attempt_slots
                        WHERE trace_ref IS NOT NULL
                        """
                    )
                }
                if not all(isinstance(reference, str) for reference in references):
                    raise EvaluationRepositoryError(
                        "the evaluation repository failed integrity validation",
                        code="storage",
                    )
                self._trace_store.cleanup_unreferenced(cast(set[str], references))
        except AttemptTraceStoreError:
            raise EvaluationRepositoryError(
                "the evaluation repository could not recover trace artifacts",
                code="storage",
            ) from None

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except EvaluationRepositoryError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.Error:
            if connection is not None:
                connection.rollback()
            raise EvaluationRepositoryError(
                "the evaluation repository could not persist the operation",
                code="storage",
            ) from None
        finally:
            if connection is not None:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        with self._open_artifact_root() as artifact_root_fd:
            database_fd = os.open(
                _DATABASE_NAME,
                os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=artifact_root_fd,
            )
            try:
                expected = self._validate_owned_regular_file(database_fd)
                os.fchmod(database_fd, 0o600)
                connection: sqlite3.Connection | None = None
                try:
                    connection = sqlite3.connect(
                        self._database_path,
                        isolation_level=None,
                    )
                    observed = os.stat(
                        _DATABASE_NAME,
                        dir_fd=artifact_root_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not stat_module.S_ISREG(observed.st_mode)
                        or observed.st_uid != os.getuid()
                        or observed.st_nlink != 1
                        or (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino)
                    ):
                        raise OSError("evaluation database identity changed while opening")
                except BaseException:
                    if connection is not None:
                        connection.close()
                    raise
            finally:
                os.close(database_fd)
        assert connection is not None
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _open_artifact_root(self) -> Iterator[int]:
        descriptor = os.open(
            self._artifact_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            status = os.fstat(descriptor)
            if not stat_module.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
                raise OSError("evaluation artifact root ownership is invalid")
            yield descriptor
        finally:
            os.close(descriptor)

    def _ensure_private_directory(self, parent_fd: int, name: str) -> None:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        with self._open_owned_directory(parent_fd, name) as descriptor:
            os.fchmod(descriptor, 0o700)

    @contextmanager
    def _open_owned_directory(self, parent_fd: int, name: str) -> Iterator[int]:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            status = os.fstat(descriptor)
            if not stat_module.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
                raise OSError("evaluation repository directory ownership is invalid")
            yield descriptor
        finally:
            os.close(descriptor)

    def _ensure_database_file(self, artifact_root_fd: int) -> None:
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        created = False
        try:
            descriptor = os.open(
                _DATABASE_NAME,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=artifact_root_fd,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(
                _DATABASE_NAME,
                flags,
                dir_fd=artifact_root_fd,
            )
        try:
            self._validate_owned_regular_file(descriptor)
            os.fchmod(descriptor, 0o600)
            if created:
                os.fsync(descriptor)
                os.fsync(artifact_root_fd)
        finally:
            os.close(descriptor)

    @staticmethod
    def _validate_owned_regular_file(descriptor: int) -> os.stat_result:
        status = os.fstat(descriptor)
        if (
            not stat_module.S_ISREG(status.st_mode)
            or status.st_uid != os.getuid()
            or status.st_nlink != 1
        ):
            raise OSError("evaluation repository file ownership is invalid")
        return status


def _create_attempt_slot_table(
    connection: sqlite3.Connection,
    table_name: Literal["evaluation_attempt_slots", "evaluation_attempt_slots_v2"],
) -> None:
    connection.execute(
        f"CREATE TABLE {table_name} " + _ATTEMPT_SLOT_TABLE_DEFINITION
    )


def _rebuild_current_attempt_slot_table(connection: sqlite3.Connection) -> None:
    temporary_table: Literal["evaluation_attempt_slots_v2"] = (
        "evaluation_attempt_slots_v2"
    )
    _create_attempt_slot_table(connection, temporary_table)
    columns = ", ".join(column[0] for column in _ATTEMPT_SLOT_COLUMN_SCHEMA)
    connection.execute(
        f"""
        INSERT INTO {temporary_table}({columns})
        SELECT {columns}
        FROM evaluation_attempt_slots
        """
    )
    connection.execute("DROP TABLE evaluation_attempt_slots")
    connection.execute(
        f"ALTER TABLE {temporary_table} RENAME TO evaluation_attempt_slots"
    )


def _validate_table_schema(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    expected_columns: tuple[tuple[str, str, int, None, int, int], ...],
    expected_unique_indexes: tuple[
        tuple[str, int, tuple[tuple[str, int, str], ...]], ...
    ],
    expected_foreign_keys: tuple[
        tuple[str, str, str, str, str, str], ...
    ],
    expected_checks: tuple[str, ...],
    expected_autoincrement: bool,
    expected_create_sql: str,
) -> None:
    columns = tuple(
        (
            row["name"],
            str(row["type"]).upper(),
            row["notnull"],
            row["dflt_value"],
            row["pk"],
            row["hidden"],
        )
        for row in connection.execute(
            """
            SELECT name, type, "notnull", dflt_value, pk, hidden
            FROM pragma_table_xinfo(?)
            ORDER BY cid
            """,
            (table_name,),
        )
    )
    unique_indexes = []
    for index in connection.execute(
        """
        SELECT name, "unique", origin, partial
        FROM pragma_index_list(?)
        ORDER BY seq
        """,
        (table_name,),
    ):
        if index["unique"] != 1:
            continue
        indexed_columns = tuple(
            (row["name"], row["desc"], row["coll"])
            for row in connection.execute(
                """
                SELECT name, "desc", coll
                FROM pragma_index_xinfo(?)
                WHERE key = 1
                ORDER BY seqno
                """,
                (index["name"],),
            )
        )
        unique_indexes.append(
            (index["origin"], index["partial"], indexed_columns)
        )
    foreign_keys = tuple(
        (
            row["table"],
            row["from"],
            row["to"],
            row["on_update"],
            row["on_delete"],
            row["match"],
        )
        for row in connection.execute(
            """
            SELECT "table", "from", "to", on_update, on_delete, "match"
            FROM pragma_foreign_key_list(?)
            ORDER BY id, seq
            """,
            (table_name,),
        )
    )
    schema_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_schema
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    create_sql = schema_row["sql"] if schema_row is not None else None
    checks = (
        _extract_check_expressions(create_sql)
        if isinstance(create_sql, str)
        else ()
    )
    expected_normalized_checks = tuple(
        sorted(_normalize_sql_expression(check) for check in expected_checks)
    )
    observed_autoincrement = (
        isinstance(create_sql, str)
        and _contains_sql_keyword(create_sql, "autoincrement")
    )
    if (
        columns != expected_columns
        or tuple(sorted(unique_indexes, key=repr))
        != tuple(sorted(expected_unique_indexes, key=repr))
        or foreign_keys != expected_foreign_keys
        or checks != expected_normalized_checks
        or observed_autoincrement != expected_autoincrement
        or not isinstance(create_sql, str)
        or _sql_token_shape(create_sql) != _sql_token_shape(expected_create_sql)
    ):
        raise EvaluationRepositoryError(
            "the evaluation repository schema is unsupported",
            code="storage",
        )


def _extract_check_expressions(create_sql: str) -> tuple[str, ...]:
    expressions: list[str] = []
    cursor = 0
    while cursor < len(create_sql):
        comment_end = _sql_comment_end(create_sql, cursor)
        if comment_end is not None:
            cursor = comment_end
            continue
        character = create_sql[cursor]
        if character in "'\"`[":
            cursor = _skip_sql_quoted_value(create_sql, cursor)
            continue
        if not _sql_keyword_at(create_sql, cursor, "check"):
            cursor += 1
            continue
        after_index = cursor + 5
        while after_index < len(create_sql) and create_sql[after_index].isspace():
            after_index += 1
        if after_index >= len(create_sql) or create_sql[after_index] != "(":
            cursor += 1
            continue
        expression, cursor = _read_sql_parenthesized_value(create_sql, after_index)
        expressions.append(_normalize_sql_expression(expression))
    return tuple(sorted(expressions))


def _contains_sql_keyword(sql: str, keyword: str) -> bool:
    cursor = 0
    while cursor < len(sql):
        comment_end = _sql_comment_end(sql, cursor)
        if comment_end is not None:
            cursor = comment_end
            continue
        if sql[cursor] in "'\"`[":
            cursor = _skip_sql_quoted_value(sql, cursor)
            continue
        if _sql_keyword_at(sql, cursor, keyword):
            return True
        cursor += 1
    return False


def _sql_keyword_at(sql: str, start: int, keyword: str) -> bool:
    if sql[start : start + len(keyword)].casefold() != keyword.casefold():
        return False
    before = sql[start - 1] if start > 0 else " "
    after_index = start + len(keyword)
    after = sql[after_index] if after_index < len(sql) else " "
    return not (
        before.isalnum()
        or before == "_"
        or after.isalnum()
        or after == "_"
    )


def _sql_comment_end(sql: str, start: int) -> int | None:
    if sql.startswith("--", start):
        newline = sql.find("\n", start + 2)
        return len(sql) if newline < 0 else newline + 1
    if sql.startswith("/*", start):
        closing = sql.find("*/", start + 2)
        return len(sql) if closing < 0 else closing + 2
    return None


def _sql_token_shape(sql: str) -> tuple[str, ...]:
    tokens: list[str] = []
    cursor = 0
    while cursor < len(sql):
        comment_end = _sql_comment_end(sql, cursor)
        if comment_end is not None:
            cursor = comment_end
            continue
        character = sql[cursor]
        if character.isspace():
            cursor += 1
            continue
        if character in "'\"`[":
            end = _skip_sql_quoted_value(sql, cursor)
            quoted = sql[cursor:end]
            if character == "'":
                tokens.append(quoted)
            else:
                closing = "]" if character == "[" else character
                identifier = quoted[1:-1].replace(closing * 2, closing)
                tokens.append(
                    identifier.casefold()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier)
                    else quoted
                )
            cursor = end
            continue
        if character in "(),":
            tokens.append(character)
            cursor += 1
            continue
        start = cursor
        while cursor < len(sql):
            if (
                sql[cursor].isspace()
                or sql[cursor] in "'\"`[(),"
                or _sql_comment_end(sql, cursor) is not None
            ):
                break
            cursor += 1
        tokens.append(sql[start:cursor].casefold())
    return tuple(tokens)


def _skip_sql_quoted_value(sql: str, start: int) -> int:
    opening = sql[start]
    closing = "]" if opening == "[" else opening
    cursor = start + 1
    while cursor < len(sql):
        if sql[cursor] != closing:
            cursor += 1
            continue
        if cursor + 1 < len(sql) and sql[cursor + 1] == closing:
            cursor += 2
            continue
        return cursor + 1
    return len(sql)


def _read_sql_parenthesized_value(sql: str, start: int) -> tuple[str, int]:
    depth = 0
    cursor = start
    while cursor < len(sql):
        comment_end = _sql_comment_end(sql, cursor)
        if comment_end is not None:
            cursor = comment_end
            continue
        character = sql[cursor]
        if character in "'\"`[":
            cursor = _skip_sql_quoted_value(sql, cursor)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return sql[start + 1 : cursor], cursor + 1
        cursor += 1
    return "", len(sql)


def _normalize_sql_expression(expression: str) -> str:
    tokens: list[str] = []
    cursor = 0
    while cursor < len(expression):
        comment_end = _sql_comment_end(expression, cursor)
        if comment_end is not None:
            cursor = comment_end
            continue
        character = expression[cursor]
        if character.isspace():
            cursor += 1
            continue
        if character in "'\"`[":
            end = _skip_sql_quoted_value(expression, cursor)
            tokens.append(expression[cursor:end])
            cursor = end
            continue
        if character in "(),":
            tokens.append(character)
            cursor += 1
            continue
        start = cursor
        while cursor < len(expression):
            if (
                expression[cursor].isspace()
                or expression[cursor] in "'\"`[(),"
                or _sql_comment_end(expression, cursor) is not None
            ):
                break
            cursor += 1
        tokens.append(expression[start:cursor].casefold())
    collapsed = " ".join(tokens)
    return re.sub(r"\s*([(),])\s*", r"\1", collapsed)


def _attempt_id(ordinal: int) -> str:
    return f"attempt-{ordinal + 1:04d}"


def _execution_lock_stripe(evaluation_id: str) -> int:
    stable_hash = hashlib.sha256(evaluation_id.encode("utf-8")).digest()
    return int.from_bytes(stable_hash[:8], "big") % _EXECUTION_LOCK_STRIPE_COUNT


def _validate_evaluation_id(evaluation_id: str) -> None:
    if _EVALUATION_ID.fullmatch(evaluation_id) is None:
        raise EvaluationRepositoryError(
            "evaluation identity is invalid",
            code="not_found",
        )


def _canonical_model(model: BaseModel) -> tuple[str, str]:
    document = model.model_dump(mode="json", exclude_none=True)
    validate_artifact_safe(document)
    return _canonical_document(document)


def _canonical_document(document: Mapping[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(
        dict(document),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return serialized, f"sha256:{digest}"


def _stored_model(
    *,
    raw_json: object,
    stored_digest: object,
    model_type: type[BaseModel],
) -> Any:
    if not isinstance(raw_json, str) or not isinstance(stored_digest, str):
        raise ValueError("stored model representation is invalid")
    document = json.loads(raw_json)
    if not isinstance(document, dict):
        raise ValueError("stored model must be an object")
    validate_artifact_safe(document)
    canonical, digest = _canonical_document(document)
    if canonical != raw_json or digest != stored_digest:
        raise ValueError("stored model digest does not match")
    return model_type.model_validate_json(raw_json)


def _attempt_index(attempt: EvaluationAttempt) -> StoredAttemptIndex:
    if attempt.infrastructure_error is not None:
        disposition: AttemptDisposition = "infrastructure_error"
        summary = attempt.infrastructure_error.summary
        result_digest = None
    else:
        completed = attempt.completed_run
        if (
            completed is None
            or completed.verifier_result is None
            or completed.result_digest is None
        ):
            raise ValueError("scientific evaluation attempt is incomplete")
        disposition = (
            "scientific_success" if completed.verifier_result.passed else "scientific_failure"
        )
        summary = completed.verifier_result.summary
        result_digest = completed.result_digest
    return StoredAttemptIndex(
        disposition=disposition,
        summary=summary,
        interaction_digest=attempt.trace.interaction_digest,
        runtime_trace_digest=attempt.trace.runtime_trace_digest,
        result_digest=result_digest,
        authenticated_local_runtime=(attempt.trace.run.local_gemma_attestation is not None),
    )


def _stored_attempt_index(row: sqlite3.Row) -> StoredAttemptIndex | None:
    index = _stored_attempt_index_without_digest(row)
    stored_digest = row["index_digest"]
    if index is None:
        if stored_digest is not None:
            raise ValueError("empty evaluation attempt slot has an index digest")
        return None
    if not isinstance(stored_digest, str) or stored_digest != _attempt_index_digest(
        evaluation_id=row["evaluation_id"],
        attempt_id=row["attempt_id"],
        ordinal=row["ordinal"],
        scenario_id=row["scenario_id"],
        trace_ref=row["trace_ref"],
        trace_digest=row["trace_digest"],
        index=index,
    ):
        raise ValueError("evaluation attempt summary index digest does not match")
    return index


def _stored_attempt_index_without_digest(
    row: sqlite3.Row,
) -> StoredAttemptIndex | None:
    indexed_columns = (
        "trace_ref",
        "trace_digest",
        "disposition",
        "summary",
        "interaction_digest",
        "runtime_trace_digest",
        "result_digest",
        "authenticated_local_runtime",
    )
    values = tuple(row[column] for column in indexed_columns)
    if all(value is None for value in values):
        return None
    if any(row[column] is None for column in indexed_columns if column != "result_digest"):
        raise ValueError("evaluation attempt slot index is incomplete")
    trace_ref = row["trace_ref"]
    trace_digest = row["trace_digest"]
    if not isinstance(trace_ref, str) or not isinstance(trace_digest, str):
        raise ValueError("evaluation attempt trace index is invalid")
    validate_trace_artifact_identity(trace_ref, trace_digest)
    disposition = row["disposition"]
    summary = row["summary"]
    interaction_digest = row["interaction_digest"]
    runtime_trace_digest = row["runtime_trace_digest"]
    result_digest = row["result_digest"]
    authenticated = row["authenticated_local_runtime"]
    if (
        disposition not in ("scientific_success", "scientific_failure", "infrastructure_error")
        or not isinstance(summary, str)
        or not summary
        or not isinstance(interaction_digest, str)
        or _DIGEST.fullmatch(interaction_digest) is None
        or not isinstance(runtime_trace_digest, str)
        or _DIGEST.fullmatch(runtime_trace_digest) is None
        or authenticated not in (0, 1)
    ):
        raise ValueError("evaluation attempt summary index is invalid")
    if disposition == "infrastructure_error":
        if result_digest is not None:
            raise ValueError("infrastructure attempt index has a result digest")
    elif not isinstance(result_digest, str) or _DIGEST.fullmatch(result_digest) is None:
        raise ValueError("scientific attempt index has no result digest")
    return StoredAttemptIndex(
        disposition=cast(AttemptDisposition, disposition),
        summary=summary,
        interaction_digest=interaction_digest,
        runtime_trace_digest=runtime_trace_digest,
        result_digest=result_digest,
        authenticated_local_runtime=bool(authenticated),
    )


def _attempt_index_digest(
    *,
    evaluation_id: str,
    attempt_id: str,
    ordinal: int,
    scenario_id: str,
    trace_ref: str,
    trace_digest: str,
    index: StoredAttemptIndex,
) -> str:
    _serialized, digest = _canonical_document(
        {
            "authenticated_local_runtime": index.authenticated_local_runtime,
            "attempt_id": attempt_id,
            "disposition": index.disposition,
            "evaluation_id": evaluation_id,
            "interaction_digest": index.interaction_digest,
            "ordinal": ordinal,
            "result_digest": index.result_digest,
            "runtime_trace_digest": index.runtime_trace_digest,
            "scenario_id": scenario_id,
            "summary": index.summary,
            "trace_digest": trace_digest,
            "trace_ref": trace_ref,
        }
    )
    return digest


def _validate_attempt(
    plan: EvaluationPlan,
    slot: StoredAttemptSlot,
    attempt: EvaluationAttempt,
) -> None:
    if attempt.scenario_id != slot.scenario_id or attempt.trace.model != plan.model:
        raise EvaluationRepositoryError(
            "the evaluation attempt does not match its reserved slot",
            code="conflict",
        )
    completed = attempt.completed_run
    if completed is None:
        if attempt.infrastructure_error is None:
            raise EvaluationRepositoryError(
                "the evaluation attempt is not terminal",
                code="conflict",
            )
        return
    try:
        validate_completed_run_snapshot(completed)
    except ValueError:
        raise EvaluationRepositoryError(
            "the scientific evaluation attempt failed integrity validation",
            code="conflict",
        ) from None
    invalid = (
        completed.scenario_id != slot.scenario_id
        or completed.policy_agent != plan.model.policy_identity()
        or completed.status != "completed"
        or completed.verifier_result is None
        or completed.result_digest is None
        or completed.trace != attempt.trace.runtime_events
        or completed.trace_digest != attempt.trace.runtime_trace_digest
    )
    if invalid:
        raise EvaluationRepositoryError(
            "the scientific evaluation attempt failed integrity validation",
            code="conflict",
        )


__all__ = [
    "EvaluationPlan",
    "EvaluationRepository",
    "EvaluationRepositoryError",
    "EvaluationStatus",
    "StoredAttemptSlot",
    "StoredAttemptIndex",
    "StoredAttemptIndexSlot",
    "StoredEvaluation",
    "StoredEvaluationIndex",
]
