"""Durable scientist-facing lifecycle for full EEG curriculum training."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

CurriculumJobStatus = Literal["queued", "running", "failed", "completed"]


class CurriculumJobError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: Literal["not_found", "conflict", "storage"],
    ) -> None:
        super().__init__(message)
        self.code = code


class CurriculumTrainingJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: str = Field(pattern=r"^eeg-training-[a-z0-9]{8,64}$")
    status: CurriculumJobStatus
    message: str = Field(min_length=1)
    training_scenarios: Literal[96]
    development_scenarios: Literal[32]
    heldout_scenarios: Literal[64]
    training_package_digest: Literal[
        "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
    ]
    development_package_digest: Literal[
        "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
    ]
    heldout_package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_id: str | None = Field(
        default=None,
        pattern=r"^eeg-training-result-[a-z0-9]{8,64}$",
    )
    result_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )


def _heldout_package_digest() -> str:
    from evaluation.eeg.curriculum import load_held_out_scenario_set

    return load_held_out_scenario_set().identity.package_digest


class CurriculumTrainingJobRepository:
    def __init__(self, artifact_root: Path) -> None:
        self._root = artifact_root.expanduser().resolve()
        self._database = self._root / "curriculum-training-jobs.sqlite3"
        self._lock = RLock()
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._root, 0o700)
            self._prepare()
        except (OSError, sqlite3.Error) as error:
            raise CurriculumJobError(
                "the curriculum training index could not be opened",
                code="storage",
            ) from error

    def launch(self) -> CurriculumTrainingJob:
        job_id = f"eeg-training-{uuid4().hex}"
        message = (
            "Queued for the approved GPU workstation. The immutable 96-scenario "
            "training split is reserved; no model compute runs on this computer."
        )
        try:
            with self._lock, closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO curriculum_jobs(
                        job_id, status, message, result_id, result_digest
                    ) VALUES (?, 'queued', ?, NULL, NULL)
                    """,
                    (job_id, message),
                )
                connection.commit()
            return self.load(job_id)
        except sqlite3.Error as error:
            raise CurriculumJobError(
                "the curriculum training job could not be queued",
                code="storage",
            ) from error

    def begin(self, job_id: str) -> CurriculumTrainingJob:
        return self._transition(
            job_id,
            expected="queued",
            target="running",
            message=(
                "Workstation training is running on the immutable training split. "
                "Development diagnostics and sealed held-out evaluation remain separate."
            ),
        )

    def fail(
        self,
        job_id: str,
        *,
        reason: Literal[
            "artifact_verification",
            "workstation_unavailable",
            "training_execution",
        ],
    ) -> CurriculumTrainingJob:
        messages = {
            "artifact_verification": (
                "Training evidence verification failed. No scientific comparison "
                "was published; inspect the sanitized artifact receipt and retry."
            ),
            "workstation_unavailable": (
                "The approved workstation was unavailable. No local fallback was used."
            ),
            "training_execution": (
                "The workstation training run failed. Partial results were not scored."
            ),
        }
        return self._transition(
            job_id,
            expected="running",
            target="failed",
            message=messages[reason],
        )

    def complete(
        self,
        job_id: str,
        *,
        result_id: str,
        result_digest: str,
    ) -> CurriculumTrainingJob:
        if (
            not result_id.startswith("eeg-training-result-")
            or re.fullmatch(r"sha256:[0-9a-f]{64}", result_digest) is None
        ):
            raise CurriculumJobError(
                "verified curriculum result identity is invalid",
                code="conflict",
            )
        try:
            with self._lock, closing(self._connect()) as connection:
                updated = connection.execute(
                    """
                    UPDATE curriculum_jobs
                    SET status = 'completed',
                        message = ?, result_id = ?, result_digest = ?
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (
                        "Training, fresh adapter reload, development diagnostics, and "
                        "paired held-out evaluation completed with verified provenance.",
                        result_id,
                        result_digest,
                        job_id,
                    ),
                )
                if updated.rowcount != 1:
                    self._raise_transition_error(connection, job_id)
                connection.commit()
            return self.load(job_id)
        except CurriculumJobError:
            raise
        except sqlite3.Error as error:
            raise CurriculumJobError(
                "the curriculum training result could not be recorded",
                code="storage",
            ) from error

    def load(self, job_id: str) -> CurriculumTrainingJob:
        try:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT job_id, status, message, result_id, result_digest
                    FROM curriculum_jobs WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
            if row is None:
                raise CurriculumJobError(
                    "curriculum training job was not found",
                    code="not_found",
                )
            return self._job(row)
        except CurriculumJobError:
            raise
        except (sqlite3.Error, ValueError) as error:
            raise CurriculumJobError(
                "the curriculum training index failed integrity validation",
                code="storage",
            ) from error

    def list(self) -> tuple[CurriculumTrainingJob, ...]:
        try:
            with self._lock, closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT job_id, status, message, result_id, result_digest
                    FROM curriculum_jobs ORDER BY created_sequence DESC
                    """
                ).fetchall()
            return tuple(self._job(row) for row in rows)
        except (sqlite3.Error, ValueError) as error:
            raise CurriculumJobError(
                "the curriculum training index failed integrity validation",
                code="storage",
            ) from error

    def reset_demo(self) -> int:
        """Remove mutable demonstration rows while preserving verified results."""

        try:
            with self._lock, closing(self._connect()) as connection:
                connection.execute(
                    "DELETE FROM curriculum_jobs WHERE status != 'completed'"
                )
                row = connection.execute(
                    "SELECT COUNT(*) FROM curriculum_jobs WHERE status = 'completed'"
                ).fetchone()
                connection.commit()
            if row is None:
                raise ValueError("missing completed curriculum job count")
            return int(row[0])
        except (sqlite3.Error, ValueError) as error:
            raise CurriculumJobError(
                "the curriculum training demo state could not be reset",
                code="storage",
            ) from error

    def _transition(
        self,
        job_id: str,
        *,
        expected: CurriculumJobStatus,
        target: CurriculumJobStatus,
        message: str,
    ) -> CurriculumTrainingJob:
        try:
            with self._lock, closing(self._connect()) as connection:
                updated = connection.execute(
                    """
                    UPDATE curriculum_jobs
                    SET status = ?, message = ?, result_id = NULL, result_digest = NULL
                    WHERE job_id = ? AND status = ?
                    """,
                    (target, message, job_id, expected),
                )
                if updated.rowcount != 1:
                    self._raise_transition_error(connection, job_id)
                connection.commit()
            return self.load(job_id)
        except CurriculumJobError:
            raise
        except sqlite3.Error as error:
            raise CurriculumJobError(
                "the curriculum training job could not be updated",
                code="storage",
            ) from error

    @staticmethod
    def _raise_transition_error(
        connection: sqlite3.Connection,
        job_id: str,
    ) -> None:
        exists = connection.execute(
            "SELECT 1 FROM curriculum_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if exists is None:
            raise CurriculumJobError(
                "curriculum training job was not found",
                code="not_found",
            )
        raise CurriculumJobError(
            "curriculum training job status does not allow this operation",
            code="conflict",
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> CurriculumTrainingJob:
        status = row["status"]
        result_id = row["result_id"]
        result_digest = row["result_digest"]
        if (status == "completed") != (
            result_id is not None and result_digest is not None
        ):
            raise ValueError("curriculum result does not match job status")
        return CurriculumTrainingJob(
            job_id=row["job_id"],
            status=status,
            message=row["message"],
            training_scenarios=96,
            development_scenarios=32,
            heldout_scenarios=64,
            training_package_digest=(
                "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
            ),
            development_package_digest=(
                "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
            ),
            heldout_package_digest=_heldout_package_digest(),
            result_id=result_id,
            result_digest=result_digest,
        )

    def _prepare(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS curriculum_jobs(
                    created_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(
                        status IN ('queued', 'running', 'failed', 'completed')
                    ),
                    message TEXT NOT NULL,
                    result_id TEXT,
                    result_digest TEXT,
                    CHECK(
                        (status = 'completed' AND result_id IS NOT NULL
                            AND result_digest IS NOT NULL)
                        OR
                        (status != 'completed' AND result_id IS NULL
                            AND result_digest IS NULL)
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


__all__ = [
    "CurriculumJobError",
    "CurriculumTrainingJob",
    "CurriculumTrainingJobRepository",
]
