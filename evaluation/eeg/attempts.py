"""Persistent, write-once attempt matrix for final EEG evaluation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from environments.eeg.curriculum import (
    CurriculumAttempt,
    CurriculumContractError,
)

if TYPE_CHECKING:
    from evaluation.eeg.curriculum import HeldOutScenarioSet

_LEDGER_REVISION = "eeg-heldout-attempt-ledger-1"
_OPEN_TOKEN = object()


class HeldOutAttemptLedger:
    """A predeclared SQLite matrix whose terminal slots cannot be overwritten."""

    def __init__(
        self,
        *,
        token: object,
        path: Path,
        scenario_set: HeldOutScenarioSet,
        model_configuration_digest: str,
        rollouts_per_scenario: int,
    ) -> None:
        if token is not _OPEN_TOKEN:
            raise TypeError("use open_held_out_attempt_ledger")
        self._path = path
        self._scenario_ids = scenario_set.scenario_ids
        self._release_id = scenario_set.identity.release_id
        self._package_digest = scenario_set.identity.package_digest
        self._model_configuration_digest = model_configuration_digest
        self._rollouts_per_scenario = rollouts_per_scenario
        self._initialize_or_validate()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def evaluation_id(self) -> str:
        return self._metadata()["evaluation_id"]

    @property
    def ledger_digest(self) -> str | None:
        return self._metadata().get("ledger_digest")

    def record(self, attempt: CurriculumAttempt) -> None:
        """Persist exactly one terminal run or harness error into a reserved slot."""

        if not isinstance(attempt, CurriculumAttempt):
            raise CurriculumContractError("the evaluator ledger requires a typed attempt")
        if attempt.model_configuration_digest != self._model_configuration_digest:
            raise CurriculumContractError(
                "the attempt does not match the evaluator model configuration"
            )
        if attempt.scenario_id not in self._scenario_ids or not (
            0 <= attempt.rollout_index < self._rollouts_per_scenario
        ):
            raise CurriculumContractError("the attempt does not match a reserved ledger slot")
        if attempt.run is not None and (
            attempt.run.status != "completed" or attempt.run.verifier_result is None
        ):
            raise CurriculumContractError(
                "a run outcome must be terminal before it enters the evaluator ledger"
            )

        attempt_document = attempt.model_dump(mode="json", exclude_none=True)
        attempt_json = _canonical_bytes(attempt_document).decode("utf-8")
        attempt_digest = _digest(attempt_document)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                metadata = _read_metadata(connection)
                self._validate_metadata(metadata)
                if "ledger_digest" in metadata:
                    raise CurriculumContractError(
                        "the evaluator attempt ledger is already sealed"
                    )
                row = connection.execute(
                    """
                    SELECT attempt_digest
                    FROM attempt_slots
                    WHERE scenario_id = ? AND rollout_index = ?
                    """,
                    (attempt.scenario_id, attempt.rollout_index),
                ).fetchone()
                if row is None:
                    raise CurriculumContractError(
                        "the attempt does not match a reserved ledger slot"
                    )
                if row[0] is not None:
                    raise CurriculumContractError(
                        "the evaluator attempt slot already has a terminal outcome"
                    )
                connection.execute(
                    """
                    UPDATE attempt_slots
                    SET attempt_json = ?, attempt_digest = ?
                    WHERE scenario_id = ? AND rollout_index = ?
                    """,
                    (
                        attempt_json,
                        attempt_digest,
                        attempt.scenario_id,
                        attempt.rollout_index,
                    ),
                )
        except sqlite3.Error as error:
            raise CurriculumContractError(
                "the evaluator attempt ledger could not record an outcome"
            ) from error

    def seal(self) -> str:
        """Seal a complete matrix and return its immutable content digest."""

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                metadata = _read_metadata(connection)
                self._validate_metadata(metadata)
                attempts = self._load_attempts(connection)
                missing = connection.execute(
                    "SELECT COUNT(*) FROM attempt_slots WHERE attempt_json IS NULL"
                ).fetchone()[0]
                if missing:
                    raise CurriculumContractError(
                        "the evaluator ledger requires a complete attempt matrix before seal"
                    )
                expected_digest = self._ledger_digest(metadata, attempts)
                stored_digest = metadata.get("ledger_digest")
                if stored_digest is not None:
                    if stored_digest != expected_digest:
                        raise CurriculumContractError(
                            "the sealed evaluator attempt ledger failed integrity validation"
                        )
                    return stored_digest
                connection.execute(
                    "INSERT INTO ledger_metadata(key, value) VALUES('ledger_digest', ?)",
                    (expected_digest,),
                )
                return expected_digest
        except sqlite3.Error as error:
            raise CurriculumContractError(
                "the evaluator attempt ledger could not be sealed"
            ) from error

    def _sealed_payload_for(
        self,
        scenario_set: HeldOutScenarioSet,
    ) -> tuple[tuple[CurriculumAttempt, ...], str, str]:
        if (
            scenario_set.identity.release_id != self._release_id
            or scenario_set.identity.package_digest != self._package_digest
            or scenario_set.scenario_ids != self._scenario_ids
        ):
            raise CurriculumContractError(
                "the evaluator attempt ledger belongs to a different curriculum package"
            )
        try:
            with self._connect() as connection:
                metadata = _read_metadata(connection)
                self._validate_metadata(metadata)
                ledger_digest = metadata.get("ledger_digest")
                if ledger_digest is None:
                    raise CurriculumContractError(
                        "the evaluator attempt ledger must be sealed before aggregation"
                    )
                attempts = self._load_attempts(connection)
                if ledger_digest != self._ledger_digest(metadata, attempts):
                    raise CurriculumContractError(
                        "the sealed evaluator attempt ledger failed integrity validation"
                    )
                return attempts, metadata["evaluation_id"], ledger_digest
        except sqlite3.Error as error:
            raise CurriculumContractError(
                "the evaluator attempt ledger could not be read"
            ) from error

    def _initialize_or_validate(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ledger_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS attempt_slots (
                        scenario_id TEXT NOT NULL,
                        rollout_index INTEGER NOT NULL CHECK (rollout_index >= 0),
                        attempt_json TEXT,
                        attempt_digest TEXT,
                        PRIMARY KEY (scenario_id, rollout_index),
                        CHECK (
                            (attempt_json IS NULL AND attempt_digest IS NULL)
                            OR (attempt_json IS NOT NULL AND attempt_digest IS NOT NULL)
                        )
                    )
                    """
                )
                metadata = _read_metadata(connection)
                if not metadata:
                    metadata = self._initial_metadata()
                    connection.executemany(
                        "INSERT INTO ledger_metadata(key, value) VALUES(?, ?)",
                        tuple(metadata.items()),
                    )
                    connection.executemany(
                        """
                        INSERT INTO attempt_slots(scenario_id, rollout_index)
                        VALUES(?, ?)
                        """,
                        tuple(
                            (scenario_id, rollout_index)
                            for scenario_id in self._scenario_ids
                            for rollout_index in range(self._rollouts_per_scenario)
                        ),
                    )
                self._validate_metadata(metadata)
                slots = tuple(
                    connection.execute(
                        """
                        SELECT scenario_id, rollout_index
                        FROM attempt_slots
                        ORDER BY scenario_id, rollout_index
                        """
                    )
                )
                expected_slots = tuple(
                    sorted(
                        (scenario_id, rollout_index)
                        for scenario_id in self._scenario_ids
                        for rollout_index in range(self._rollouts_per_scenario)
                    )
                )
                if slots != expected_slots:
                    raise CurriculumContractError(
                        "the evaluator attempt ledger plan failed integrity validation"
                    )
        except (OSError, sqlite3.Error) as error:
            raise CurriculumContractError(
                "the evaluator attempt ledger could not be opened"
            ) from error

    def _initial_metadata(self) -> dict[str, str]:
        return {
            "ledger_revision": _LEDGER_REVISION,
            "evaluation_id": f"eeg-evaluation-{uuid.uuid4().hex[:16]}",
            "release_id": self._release_id,
            "package_digest": self._package_digest,
            "model_configuration_digest": self._model_configuration_digest,
            "rollouts_per_scenario": str(self._rollouts_per_scenario),
            "scenario_ids_digest": _digest(self._scenario_ids),
        }

    def _validate_metadata(self, metadata: dict[str, str]) -> None:
        expected = {
            "ledger_revision": _LEDGER_REVISION,
            "release_id": self._release_id,
            "package_digest": self._package_digest,
            "model_configuration_digest": self._model_configuration_digest,
            "rollouts_per_scenario": str(self._rollouts_per_scenario),
            "scenario_ids_digest": _digest(self._scenario_ids),
        }
        metadata_mismatch = any(
            metadata.get(key) != value for key, value in expected.items()
        )
        if metadata_mismatch or not _valid_evaluation_id(metadata.get("evaluation_id")):
            raise CurriculumContractError(
                "the evaluator attempt ledger metadata does not match the declared plan"
            )
        if set(metadata) - {*expected, "evaluation_id", "ledger_digest"}:
            raise CurriculumContractError(
                "the evaluator attempt ledger metadata failed integrity validation"
            )

    def _load_attempts(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[CurriculumAttempt, ...]:
        attempts: list[CurriculumAttempt] = []
        rows = connection.execute(
            """
            SELECT attempt_json, attempt_digest
            FROM attempt_slots
            WHERE attempt_json IS NOT NULL
            ORDER BY scenario_id, rollout_index
            """
        )
        try:
            for attempt_json, attempt_digest in rows:
                document = json.loads(attempt_json)
                if _digest(document) != attempt_digest:
                    raise CurriculumContractError(
                        "an evaluator attempt slot failed integrity validation"
                    )
                attempts.append(CurriculumAttempt.model_validate(document))
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise CurriculumContractError(
                "an evaluator attempt slot failed integrity validation"
            ) from error
        return tuple(attempts)

    def _ledger_digest(
        self,
        metadata: dict[str, str],
        attempts: tuple[CurriculumAttempt, ...],
    ) -> str:
        return _digest(
            {
                "ledger_revision": metadata["ledger_revision"],
                "evaluation_id": metadata["evaluation_id"],
                "release_id": metadata["release_id"],
                "package_digest": metadata["package_digest"],
                "model_configuration_digest": metadata[
                    "model_configuration_digest"
                ],
                "rollouts_per_scenario": int(metadata["rollouts_per_scenario"]),
                "scenario_ids_digest": metadata["scenario_ids_digest"],
                "attempts": [
                    attempt.model_dump(mode="json", exclude_none=True)
                    for attempt in attempts
                ],
            }
        )

    def _metadata(self) -> dict[str, str]:
        try:
            with self._connect() as connection:
                metadata = _read_metadata(connection)
                self._validate_metadata(metadata)
                return metadata
        except sqlite3.Error as error:
            raise CurriculumContractError(
                "the evaluator attempt ledger could not be read"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0)
        connection.execute("PRAGMA synchronous = FULL")
        return connection


def open_held_out_attempt_ledger(
    *,
    artifact_root: Path,
    scenario_set: HeldOutScenarioSet,
    model_configuration_digest: str,
    rollouts_per_scenario: int,
) -> HeldOutAttemptLedger:
    """Create or reopen the one write-once ledger for a declared evaluation plan."""

    from evaluation.eeg.curriculum import HeldOutScenarioSet

    if not isinstance(artifact_root, Path):
        raise CurriculumContractError("the evaluator artifact root must be a path")
    if not isinstance(scenario_set, HeldOutScenarioSet):
        raise CurriculumContractError(
            "the evaluator ledger requires a held-out scenario set"
        )
    if not _valid_sha256(model_configuration_digest):
        raise CurriculumContractError(
            "the evaluator model configuration digest is invalid"
        )
    if (
        isinstance(rollouts_per_scenario, bool)
        or not isinstance(rollouts_per_scenario, int)
        or rollouts_per_scenario < 1
    ):
        raise CurriculumContractError(
            "the evaluator rollout count must be a positive integer"
        )
    plan_digest = hashlib.sha256(
        _canonical_bytes(
            {
                "ledger_revision": _LEDGER_REVISION,
                "release_id": scenario_set.identity.release_id,
                "package_digest": scenario_set.identity.package_digest,
                "model_configuration_digest": model_configuration_digest,
                "rollouts_per_scenario": rollouts_per_scenario,
            }
        )
    ).hexdigest()[:16]
    path = artifact_root.resolve() / f"eeg-heldout-attempts-{plan_digest}.sqlite3"
    return HeldOutAttemptLedger(
        token=_OPEN_TOKEN,
        path=path,
        scenario_set=scenario_set,
        model_configuration_digest=model_configuration_digest,
        rollouts_per_scenario=rollouts_per_scenario,
    )


def _read_metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return dict(connection.execute("SELECT key, value FROM ledger_metadata"))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _valid_evaluation_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("eeg-evaluation-")
        and len(value) == len("eeg-evaluation-") + 16
        and all(character in "0123456789abcdef" for character in value[-16:])
    )


__all__ = ["HeldOutAttemptLedger", "open_held_out_attempt_ledger"]
