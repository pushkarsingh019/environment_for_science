"""Durable local index for workstation-only Gemma acceptance jobs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .training_acceptance import (
    AcceptanceArtifactError,
    AcceptanceArtifactVerifier,
    TrainingAcceptanceEvidence,
)

TrainingJobStatus = Literal["queued", "running", "failed", "completed"]
_DATABASE_NAME = "training-acceptance-jobs.sqlite3"
_IMPORT_DIRECTORY = "training-acceptance-imports"


class TrainingJobError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: Literal["not_found", "conflict", "storage"],
    ) -> None:
        super().__init__(message)
        self.code = code


class TrainingAcceptanceJob(BaseModel):
    """Scientist-readable status without framework or transport configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: str = Field(pattern=r"^training-acceptance-[a-z0-9]{8,64}$")
    status: TrainingJobStatus
    message: str = Field(min_length=1)
    artifact_reference: str = Field(
        pattern=(
            r"^training-acceptance-imports/"
            r"training-acceptance-[a-z0-9]{8,64}$"
        )
    )
    evidence: TrainingAcceptanceEvidence | None = None


class TrainingAcceptanceJobService:
    """Queue locally, verify imported evidence, and never execute model compute."""

    def __init__(self, artifact_root: Path) -> None:
        self._root = Path(artifact_root).expanduser().resolve()
        self._database = self._root / _DATABASE_NAME
        self._imports = self._root / _IMPORT_DIRECTORY
        self._lock = RLock()
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._imports.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._root, 0o700)
            os.chmod(self._imports, 0o700)
            self._prepare()
        except (OSError, sqlite3.Error) as error:
            raise TrainingJobError(
                "the training acceptance index could not be opened",
                code="storage",
            ) from error

    def launch(self) -> TrainingAcceptanceJob:
        """Reserve evidence slots; no local model or optimizer process is started."""
        job_id = f"training-acceptance-{uuid4().hex}"
        message = (
            "Queued for the approved training and inference workstations. "
            "No model compute will run on this computer."
        )
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO training_acceptance_jobs(
                        job_id, status, message, evidence_json, evidence_digest
                    ) VALUES (?, 'queued', ?, NULL, NULL)
                    """,
                    (job_id, message),
                )
                connection.commit()
            return self.load(job_id)
        except sqlite3.Error as error:
            raise TrainingJobError(
                "the training acceptance job could not be queued",
                code="storage",
            ) from error

    def begin(self, job_id: str) -> TrainingAcceptanceJob:
        return self._transition(
            job_id,
            expected="queued",
            target="running",
            message=(
                "The bounded workstation acceptance run is in progress; awaiting "
                "verified optimization, checkpoint, reload, and tool-loop evidence."
            ),
        )

    def retry(self, job_id: str) -> TrainingAcceptanceJob:
        return self._transition(
            job_id,
            expected="failed",
            target="queued",
            message=(
                "Queued again after artifact verification failed. Replace only the "
                "fixed imported evidence directory before restarting."
            ),
        )

    def verify(self, job_id: str) -> TrainingAcceptanceJob:
        current = self.load(job_id)
        if current.status != "running":
            raise TrainingJobError(
                "only a running acceptance job can verify artifacts",
                code="conflict",
            )
        try:
            evidence = AcceptanceArtifactVerifier().verify(
                self.import_directory(job_id)
            )
            if evidence.job_id != job_id:
                raise AcceptanceArtifactError(
                    "artifact evidence belongs to another acceptance job"
                )
        except AcceptanceArtifactError as error:
            return self._record_terminal(
                job_id,
                expected="running",
                status="failed",
                message=f"Artifact verification failed: {error}",
                evidence=None,
            )
        return self._record_terminal(
            job_id,
            expected="running",
            status="completed",
            message=(
                "Bounded Gemma acceptance completed: optimization was finite, the "
                "adapter changed, resumable and portable artifacts were present, "
                "and the freshly reloaded identity completed held-out tool loops."
            ),
            evidence=evidence,
        )

    def load(self, job_id: str) -> TrainingAcceptanceJob:
        try:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT job_id, status, message, evidence_json, evidence_digest
                    FROM training_acceptance_jobs
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
            if row is None:
                raise TrainingJobError(
                    "training acceptance job was not found",
                    code="not_found",
                )
            return self._job(row)
        except TrainingJobError:
            raise
        except (json.JSONDecodeError, sqlite3.Error, ValidationError, ValueError) as error:
            raise TrainingJobError(
                "the training acceptance index failed integrity validation",
                code="storage",
            ) from error

    def list(self) -> tuple[TrainingAcceptanceJob, ...]:
        try:
            with self._lock, closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT job_id, status, message, evidence_json, evidence_digest
                    FROM training_acceptance_jobs
                    ORDER BY created_sequence DESC
                    """
                ).fetchall()
            return tuple(self._job(row) for row in rows)
        except (json.JSONDecodeError, sqlite3.Error, ValidationError, ValueError) as error:
            raise TrainingJobError(
                "the training acceptance index failed integrity validation",
                code="storage",
            ) from error

    def reset_demo(self) -> int:
        """Remove mutable demonstration rows while preserving verified evidence."""

        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "DELETE FROM training_acceptance_jobs WHERE status != 'completed'"
                )
                row = connection.execute(
                    "SELECT COUNT(*) FROM training_acceptance_jobs WHERE status = 'completed'"
                ).fetchone()
                connection.commit()
            if row is None:
                raise ValueError("missing completed acceptance job count")
            return int(row[0])
        except (sqlite3.Error, ValueError) as error:
            raise TrainingJobError(
                "the training acceptance demo state could not be reset",
                code="storage",
            ) from error

    def import_directory(self, job_id: str) -> Path:
        self.load(job_id)
        directory = self._imports / job_id
        try:
            directory.mkdir(mode=0o700, parents=False, exist_ok=True)
            if directory.is_symlink():
                raise OSError("symbolic import directory")
            os.chmod(directory, 0o700)
            return directory
        except OSError as error:
            raise TrainingJobError(
                "the fixed artifact import directory is unavailable",
                code="storage",
            ) from error

    def _transition(
        self,
        job_id: str,
        *,
        expected: TrainingJobStatus,
        target: TrainingJobStatus,
        message: str,
    ) -> TrainingAcceptanceJob:
        try:
            with self._lock, self._connect() as connection:
                updated = connection.execute(
                    """
                    UPDATE training_acceptance_jobs
                    SET status = ?, message = ?, evidence_json = NULL,
                        evidence_digest = NULL
                    WHERE job_id = ? AND status = ?
                    """,
                    (target, message, job_id, expected),
                )
                if updated.rowcount != 1:
                    if connection.execute(
                        "SELECT 1 FROM training_acceptance_jobs WHERE job_id = ?",
                        (job_id,),
                    ).fetchone() is None:
                        raise TrainingJobError(
                            "training acceptance job was not found",
                            code="not_found",
                        )
                    raise TrainingJobError(
                        "training acceptance job status does not allow this operation",
                        code="conflict",
                    )
                connection.commit()
            return self.load(job_id)
        except TrainingJobError:
            raise
        except sqlite3.Error as error:
            raise TrainingJobError(
                "the training acceptance job could not be updated",
                code="storage",
            ) from error

    def _record_terminal(
        self,
        job_id: str,
        *,
        expected: TrainingJobStatus,
        status: Literal["failed", "completed"],
        message: str,
        evidence: TrainingAcceptanceEvidence | None,
    ) -> TrainingAcceptanceJob:
        evidence_json: str | None = None
        evidence_digest: str | None = None
        if evidence is not None:
            evidence_json = _canonical_json(evidence.model_dump(mode="json"))
            evidence_digest = _digest(evidence_json.encode("utf-8"))
        try:
            with self._lock, self._connect() as connection:
                updated = connection.execute(
                    """
                    UPDATE training_acceptance_jobs
                    SET status = ?, message = ?, evidence_json = ?, evidence_digest = ?
                    WHERE job_id = ? AND status = ?
                    """,
                    (
                        status,
                        message,
                        evidence_json,
                        evidence_digest,
                        job_id,
                        expected,
                    ),
                )
                if updated.rowcount != 1:
                    raise TrainingJobError(
                        "training acceptance job status changed during verification",
                        code="conflict",
                    )
                connection.commit()
            return self.load(job_id)
        except TrainingJobError:
            raise
        except sqlite3.Error as error:
            raise TrainingJobError(
                "the training acceptance result could not be recorded",
                code="storage",
            ) from error

    def _job(self, row: sqlite3.Row) -> TrainingAcceptanceJob:
        evidence_json = row["evidence_json"]
        evidence_digest = row["evidence_digest"]
        evidence: TrainingAcceptanceEvidence | None = None
        if (evidence_json is None) != (evidence_digest is None):
            raise ValueError("partial training evidence index")
        if evidence_json is not None:
            if _digest(evidence_json.encode("utf-8")) != evidence_digest:
                raise ValueError("training evidence digest mismatch")
            evidence = TrainingAcceptanceEvidence.model_validate_json(evidence_json)
        status = row["status"]
        if (status == "completed") != (evidence is not None):
            raise ValueError("training evidence does not match job status")
        job_id = row["job_id"]
        return TrainingAcceptanceJob(
            job_id=job_id,
            status=status,
            message=row["message"],
            artifact_reference=f"{_IMPORT_DIRECTORY}/{job_id}",
            evidence=evidence,
        )

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_acceptance_jobs(
                    created_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(
                        status IN ('queued', 'running', 'failed', 'completed')
                    ),
                    message TEXT NOT NULL,
                    evidence_json TEXT,
                    evidence_digest TEXT,
                    CHECK(
                        (status = 'completed' AND evidence_json IS NOT NULL
                            AND evidence_digest IS NOT NULL)
                        OR
                        (status != 'completed' AND evidence_json IS NULL
                            AND evidence_digest IS NULL)
                    )
                )
                """
            )
            connection.commit()
        os.chmod(self._database, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "TrainingAcceptanceJob",
    "TrainingAcceptanceJobService",
    "TrainingJobError",
    "TrainingJobStatus",
]
