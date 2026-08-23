"""Public-contract tests for durable local base-Gemma evaluation coordination."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from studio.bundle import EnvironmentBundle
from studio.policy_evaluation.coordinator import (
    CalibrationAssessment,
    CalibrationLevelOutcome,
    EvaluationAttemptSummary,
    EvaluationCoordinator,
    EvaluationCoordinatorError,
    EvaluationRunner,
    assess_calibration,
)
from studio.policy_evaluation.model_runner import (
    CanonicalModelRunner,
    EvaluationAttempt,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from studio.policy_evaluation.repository import (
    EvaluationRepository,
    EvaluationRepositoryError,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from tests.evaluation.attested_provider_support import SignedLocalGemmaTestProvider

SUCCESS_SCENARIO = "eeg-30ddbcb4ceb8016d"
FAILURE_SCENARIO = "eeg-414eb6bd4efed5b8"
SUCCESS_ACTIONS = (
    "inspect_configuration",
    "inspect_eeg_signals",
    "inspect_onset_route",
    "inspect_response_timeline",
    "inspect_recording_timeline",
    "complete_preflight",
)


def _complete_all_success_calibration_levels() -> tuple[CalibrationLevelOutcome, ...]:
    return tuple(
        CalibrationLevelOutcome(
            level=level,
            label=f"Level {level}",
            total_scenarios=1,
            completed_scenarios=1,
            scientific_successes=1,
            scientific_failures=0,
            infrastructure_errors=0,
            has_success_and_failure=False,
        )
        for level in range(6)
    )


def _complete_ready_calibration_levels() -> tuple[CalibrationLevelOutcome, ...]:
    outcomes = (
        (1, 0),
        (1, 1),
        (1, 1),
        (0, 1),
        (1, 0),
        (0, 1),
    )
    return tuple(
        CalibrationLevelOutcome(
            level=level,
            label=f"Level {level}",
            total_scenarios=successes + failures,
            completed_scenarios=successes + failures,
            scientific_successes=successes,
            scientific_failures=failures,
            infrastructure_errors=0,
            has_success_and_failure=successes > 0 and failures > 0,
        )
        for level, (successes, failures) in enumerate(outcomes)
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"status": "ready"}, "readiness status"),
        (
            {
                "scientific_accuracy": 0.5,
                "overall_accuracy_in_target": True,
            },
            "scientific accuracy",
        ),
        ({"no_infrastructure_errors": False}, "infrastructure-error flag"),
    ),
)
def test_calibration_assessment_rejects_internally_inconsistent_aggregates(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "status": "not_ready",
        "summary": "Calibration does not meet the target band.",
        "scientific_accuracy": 1.0,
        "overall_accuracy_in_target": False,
        "levels_1_and_2_mixed": False,
        "no_infrastructure_errors": True,
        "authenticated_local_runtime": True,
        "levels": _complete_all_success_calibration_levels(),
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        CalibrationAssessment.model_validate(values)


def test_complete_authenticated_mixed_development_matrix_is_calibration_ready() -> None:
    scenario_levels = {
        f"scenario-{ordinal:02d}": level
        for ordinal, level in enumerate(
            (0,) * 4 + (1,) * 6 + (2,) * 6 + (3,) * 4 + (4,) * 6 + (5,) * 6,
            start=1,
        )
    }
    scenario_ids = tuple(scenario_levels)
    attempts = tuple(
        EvaluationAttemptSummary(
            attempt_id=f"attempt-{ordinal:04d}",
            ordinal=ordinal - 1,
            scenario_id=scenario_id,
            disposition=(
                "scientific_success" if ordinal % 2 else "scientific_failure"
            ),
            summary="Deterministic scientific outcome.",
            interaction_digest="sha256:" + f"{ordinal:064x}",
            runtime_trace_digest="sha256:" + f"{ordinal + 32:064x}",
            result_digest="sha256:" + f"{ordinal + 64:064x}",
        )
        for ordinal, scenario_id in enumerate(scenario_ids, start=1)
    )

    assessment = assess_calibration(
        "completed",
        attempts,
        scenario_ids,
        scenario_levels,
        set(scenario_ids),
    )

    assert assessment.status == "ready"
    assert assessment.scientific_accuracy == 0.5
    assert assessment.overall_accuracy_in_target is True
    assert assessment.levels_1_and_2_mixed is True
    assert assessment.no_infrastructure_errors is True
    assert assessment.authenticated_local_runtime is True


def test_fully_durable_matrix_can_remain_pending_until_repository_finalizes() -> None:
    assessment = CalibrationAssessment(
        status="pending",
        summary="The repository has not finalized the matrix yet.",
        scientific_accuracy=1.0,
        overall_accuracy_in_target=False,
        levels_1_and_2_mixed=False,
        no_infrastructure_errors=False,
        authenticated_local_runtime=False,
        levels=_complete_all_success_calibration_levels(),
    )

    assert assessment.status == "pending"
    assert assessment.no_infrastructure_errors is False
    assert assessment.authenticated_local_runtime is False


def test_ready_evidence_cannot_be_serialized_as_not_ready() -> None:
    with pytest.raises(ValidationError, match="readiness status"):
        CalibrationAssessment(
            status="not_ready",
            summary="This contradicts the complete evidence.",
            scientific_accuracy=0.5,
            overall_accuracy_in_target=True,
            levels_1_and_2_mixed=True,
            no_infrastructure_errors=True,
            authenticated_local_runtime=True,
            levels=_complete_ready_calibration_levels(),
        )


class _RunnerFactory:
    def __init__(self) -> None:
        self.created_for: list[EnvironmentBundle] = []

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        self.created_for.append(bundle.model_copy(deep=True))
        raise AssertionError("launching a durable plan must not call inference")


class _ScriptedProvider(SignedLocalGemmaTestProvider):
    def __init__(self, responses: Sequence[str] | None) -> None:
        self._responses = None if responses is None else iter(responses)

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self._responses is None:
            raise TimeoutError("private endpoint detail must be normalized")
        action = next(self._responses)
        return ModelResponse(
            response_id=f"response-{request.turn}",
            returned_model="google/gemma-4-E4B-it",
            message=ModelMessage.assistant(
                f"Apply {action}.",
                tool_calls=(
                    ModelToolCall(
                        call_id=f"call-{request.turn}",
                        name=action,
                        arguments={},
                    ),
                ),
            ),
        )


class _MixedRunner:
    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        self.scenario_ids: list[str] = []

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        self.scenario_ids.append(scenario_id)
        actions: Sequence[str] | None
        if scenario_id == SUCCESS_SCENARIO:
            actions = SUCCESS_ACTIONS
        elif scenario_id == FAILURE_SCENARIO:
            actions = ("complete_preflight",)
        else:
            actions = None
        return CanonicalModelRunner(
            bundle=self._bundle,
            runtime_bridge=EvaluationRuntimeBridge(self._bundle),
            provider=_ScriptedProvider(actions),
            max_turns=8,
            max_tool_calls=8,
        ).run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _MixedRunnerFactory:
    def __init__(self) -> None:
        self.runners: list[_MixedRunner] = []

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        runner = _MixedRunner(bundle)
        self.runners.append(runner)
        return runner


class _InjectedProcessCrash(BaseException):
    pass


class _CrashingRunner:
    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._delegate = _MixedRunner(bundle)
        self.calls = 0

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        self.calls += 1
        if self.calls > 1:
            raise _InjectedProcessCrash()
        return self._delegate.run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _CrashingRunnerFactory:
    def __init__(self) -> None:
        self.runners: list[_CrashingRunner] = []

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        runner = _CrashingRunner(bundle)
        self.runners.append(runner)
        return runner


class _BlockingRunner:
    def __init__(
        self,
        bundle: EnvironmentBundle,
        entered: Event,
        release: Event,
    ) -> None:
        self._delegate = _MixedRunner(bundle)
        self._entered = entered
        self._release = release
        self._first = True

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        if self._first:
            self._first = False
            self._entered.set()
            if not self._release.wait(timeout=5):
                raise RuntimeError("test execution was not released")
        return self._delegate.run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _BlockingRunnerFactory:
    def __init__(self, entered: Event, release: Event) -> None:
        self._entered = entered
        self._release = release

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        return _BlockingRunner(bundle, self._entered, self._release)


class _UnsafeContentProvider(SignedLocalGemmaTestProvider):
    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, _request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            response_id="unsafe-response",
            returned_model="google/gemma-4-E4B-it",
            message=ModelMessage.assistant(self._content),
        )


class _UnsafeRunnerFactory:
    def __init__(self, content: str) -> None:
        self._content = content

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        return CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_UnsafeContentProvider(self._content),
            max_turns=2,
            max_tool_calls=2,
        )


def _persist_one_attempt(
    tmp_path: Path,
) -> tuple[EvaluationCoordinator, str, Path, str]:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_CrashingRunnerFactory(),
    )
    queued = coordinator.launch()
    with pytest.raises(_InjectedProcessCrash):
        coordinator.execute(queued.evaluation_id)
    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT trace_ref, trace_digest
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = 'attempt-0001'
            """,
            (queued.evaluation_id,),
        ).fetchone()
    assert row is not None
    trace_ref, trace_digest = row
    return coordinator, queued.evaluation_id, tmp_path / trace_ref, trace_digest


def _canonical_jsonl(records: Sequence[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(
            record,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
        for record in records
    )


def _replace_indexed_trace(
    tmp_path: Path,
    evaluation_id: str,
    attempt_id: str,
    payload: bytes,
) -> Path:
    digest_hex = hashlib.sha256(payload).hexdigest()
    trace_ref = (
        f"evaluation-attempt-traces/sha256/{digest_hex[:2]}/{digest_hex}.jsonl"
    )
    trace_path = tmp_path / trace_ref
    trace_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    trace_path.write_bytes(payload)
    trace_path.chmod(0o600)
    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT ordinal, scenario_id, disposition, summary, interaction_digest,
                   runtime_trace_digest, result_digest,
                   authenticated_local_runtime
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = ?
            """,
            (evaluation_id, attempt_id),
        ).fetchone()
        assert row is not None
        trace_digest = f"sha256:{digest_hex}"
        index_document = {
            "authenticated_local_runtime": bool(row[7]),
            "attempt_id": attempt_id,
            "disposition": row[2],
            "evaluation_id": evaluation_id,
            "interaction_digest": row[4],
            "ordinal": row[0],
            "result_digest": row[6],
            "runtime_trace_digest": row[5],
            "scenario_id": row[1],
            "summary": row[3],
            "trace_digest": trace_digest,
            "trace_ref": trace_ref,
        }
        index_payload = json.dumps(
            index_document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        index_digest = "sha256:" + hashlib.sha256(index_payload).hexdigest()
        connection.execute(
            """
            UPDATE evaluation_attempt_slots
            SET trace_ref = ?, trace_digest = ?, index_digest = ?
            WHERE evaluation_id = ? AND attempt_id = ?
            """,
            (
                trace_ref,
                trace_digest,
                index_digest,
                evaluation_id,
                attempt_id,
            ),
        )
    return trace_path


def test_launch_reserves_the_fixed_endpoint_free_development_plan(
    tmp_path: Path,
) -> None:
    factory = _RunnerFactory()
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=factory,
    )

    launched = coordinator.launch(profile="base-gemma-development-v1")

    assert launched.status == "queued"
    assert launched.plan.profile == "base-gemma-development-v1"
    assert launched.plan.split == "development"
    assert launched.plan.model.provider == "local-openai-compatible"
    assert launched.plan.model.requested_model == "google/gemma-4-E4B-it"
    assert launched.plan.model.adapter_revision == "local-gemma-openai-chat/1"
    assert launched.plan.model_revision == (
        "ee0ef6023621cff504d758262d4e04895a5af4a2"
    )
    assert len(launched.plan.scenario_ids) == 32
    assert len(set(launched.plan.scenario_ids)) == 32
    assert launched.progress.completed_scenarios == 0
    assert launched.progress.total_scenarios == 32
    assert launched.progress.message == (
        "Ready to evaluate 32 development scenarios with base Gemma."
    )
    assert launched.attempts == ()
    assert factory.created_for == []
    serialized = launched.model_dump_json().casefold()
    for forbidden in (
        "base_url",
        "endpoint",
        "api_key",
        "password",
        "secret",
        "http://",
        "https://",
        "127.0.0.1",
    ):
        assert forbidden not in serialized
    with pytest.raises(ValidationError):
        launched.status = "completed"

    assert coordinator.load(launched.evaluation_id) == launched
    listed = coordinator.list()
    assert len(listed) == 1
    assert listed[0].evaluation_id == launched.evaluation_id
    assert listed[0].progress == launched.progress
    database = tmp_path / "evaluations.sqlite3"
    assert database.is_file()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_execute_persists_all_outcome_classes_and_completes_the_matrix(
    tmp_path: Path,
) -> None:
    factory = _MixedRunnerFactory()
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=factory,
    )
    queued = coordinator.launch()

    completed = coordinator.execute(queued.evaluation_id)

    assert completed.status == "completed"
    assert completed.progress.completed_scenarios == 32
    assert completed.progress.scientific_successes == 1
    assert completed.progress.scientific_failures == 1
    assert completed.progress.infrastructure_errors == 30
    assert completed.progress.message == (
        "Completed all 32 development scenarios: 1 scientific success, "
        "1 scientific failure, and 30 infrastructure errors."
    )
    assert len(completed.attempts) == 32
    assert {
        attempt.scenario_id: attempt.disposition for attempt in completed.attempts
    }[SUCCESS_SCENARIO] == "scientific_success"
    assert {
        attempt.scenario_id: attempt.disposition for attempt in completed.attempts
    }[FAILURE_SCENARIO] == "scientific_failure"
    assert len(factory.runners) == 1
    assert tuple(factory.runners[0].scenario_ids) == completed.plan.scenario_ids
    assert coordinator.load(completed.evaluation_id) == completed

    repeated = coordinator.execute(completed.evaluation_id)
    assert repeated == completed
    assert len(factory.runners) == 1


def test_attempt_trace_is_canonical_content_addressed_jsonl_not_a_sqlite_blob(
    tmp_path: Path,
) -> None:
    coordinator, evaluation_id, trace_path, trace_digest = _persist_one_attempt(
        tmp_path
    )
    queued = coordinator.load(evaluation_id)

    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(evaluation_attempt_slots)"
            )
        }
        assert "attempt_json" not in columns
        row = connection.execute(
            """
            SELECT trace_ref, trace_digest
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = 'attempt-0001'
            """,
            (evaluation_id,),
        ).fetchone()
    assert row is not None
    trace_ref, trace_digest = row
    digest_hex = trace_digest.removeprefix("sha256:")
    assert trace_ref == (
        f"evaluation-attempt-traces/sha256/{digest_hex[:2]}/{digest_hex}.jsonl"
    )

    payload = trace_path.read_bytes()
    trace_root = tmp_path / "evaluation-attempt-traces"
    assert stat.S_IMODE(trace_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((trace_root / "sha256").stat().st_mode) == 0o700
    assert stat.S_IMODE(trace_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((trace_root / ".pending").stat().st_mode) == 0o700
    assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600
    assert trace_path.stat().st_nlink == 1
    assert payload.endswith(b"\n")
    assert "sha256:" + hashlib.sha256(payload).hexdigest() == trace_digest
    records = [json.loads(line) for line in payload.splitlines()]
    assert records[0] == {
        "attempt_id": "attempt-0001",
        "evaluation_id": evaluation_id,
        "format_version": "science-evaluation-attempt-trace/1",
        "record_type": "header",
        "scenario_id": queued.plan.scenario_ids[0],
    }
    assert records[-1]["record_type"] == "outcome"
    assert "message" in {record["record_type"] for record in records}
    assert "runtime_event" in {record["record_type"] for record in records}
    for line, record in zip(payload.splitlines(), records):
        assert line == json.dumps(
            record,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    database_bytes = database.read_bytes()
    assert b"Apply inspect_configuration." not in database_bytes
    assert b"simulation_label" not in database_bytes
    assert b"attestation_version" not in database_bytes


def test_listing_uses_only_the_lightweight_sqlite_index(tmp_path: Path) -> None:
    coordinator, evaluation_id, _trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    trace_root = tmp_path / "evaluation-attempt-traces"
    unavailable = tmp_path / "trace-store-unavailable"
    trace_root.rename(unavailable)

    listed = coordinator.list()

    assert len(listed) == 1
    assert listed[0].evaluation_id == evaluation_id
    assert listed[0].progress.completed_scenarios == 1
    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ):
        coordinator.load(evaluation_id)


@pytest.mark.parametrize(
    "mutation",
    (
        "summary = summary || ' forged'",
        "interaction_digest = 'sha256:' || printf('%064d', 0)",
        "authenticated_local_runtime = 1 - authenticated_local_runtime",
    ),
)
def test_listing_refuses_a_tampered_lightweight_index(
    tmp_path: Path,
    mutation: str,
) -> None:
    coordinator, evaluation_id, _trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        connection.execute(
            f"""
            UPDATE evaluation_attempt_slots
            SET {mutation}
            WHERE evaluation_id = ? AND attempt_id = 'attempt-0001'
            """,
            (evaluation_id,),
        )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.list()

    assert captured.value.code == "internal"


def test_listing_refuses_intact_indexes_swapped_between_reserved_slots(
    tmp_path: Path,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_MixedRunnerFactory(),
    )
    completed = coordinator.execute(coordinator.launch().evaluation_id)
    database = tmp_path / "evaluations.sqlite3"
    indexed_columns = (
        "trace_ref",
        "trace_digest",
        "disposition",
        "summary",
        "interaction_digest",
        "runtime_trace_digest",
        "result_digest",
        "authenticated_local_runtime",
        "index_digest",
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = tuple(
            connection.execute(
                f"""
                SELECT attempt_id, {", ".join(indexed_columns)}
                FROM evaluation_attempt_slots
                WHERE evaluation_id = ?
                ORDER BY ordinal
                LIMIT 2
                """,
                (completed.evaluation_id,),
            )
        )
        assert len(rows) == 2
        assignments = ", ".join(f"{column} = ?" for column in indexed_columns)
        for destination, source in zip(rows, reversed(rows)):
            connection.execute(
                f"""
                UPDATE evaluation_attempt_slots
                SET {assignments}
                WHERE evaluation_id = ? AND attempt_id = ?
                """,
                (
                    *(source[column] for column in indexed_columns),
                    completed.evaluation_id,
                    destination["attempt_id"],
                ),
            )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.list()

    assert captured.value.code == "internal"


@pytest.mark.parametrize("mutation", ("missing", "truncated", "tampered", "mode"))
def test_loading_refuses_missing_partial_tampered_or_unsafe_trace_artifacts(
    tmp_path: Path,
    mutation: str,
) -> None:
    coordinator, evaluation_id, trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    if mutation == "missing":
        trace_path.unlink()
    elif mutation == "truncated":
        trace_path.write_bytes(trace_path.read_bytes()[:-1])
    elif mutation == "tampered":
        payload = trace_path.read_bytes()
        trace_path.write_bytes(payload.replace(b"observation", b"observatioN", 1))
    else:
        trace_path.chmod(0o644)

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(evaluation_id)

    assert captured.value.code == "internal"


def test_loading_refuses_a_symlinked_trace_artifact(tmp_path: Path) -> None:
    coordinator, evaluation_id, trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(trace_path.read_bytes())
    outside.chmod(0o600)
    trace_path.unlink()
    trace_path.symlink_to(outside)

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(evaluation_id)

    assert captured.value.code == "internal"


def test_trace_reference_cannot_escape_the_private_artifact_store(
    tmp_path: Path,
) -> None:
    coordinator, evaluation_id, _trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        connection.execute(
            """
            UPDATE evaluation_attempt_slots
            SET trace_ref = '../../outside.jsonl'
            WHERE evaluation_id = ? AND attempt_id = 'attempt-0001'
            """,
            (evaluation_id,),
        )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(evaluation_id)

    assert captured.value.code == "internal"


def test_loading_refuses_noncanonical_jsonl_even_after_consistent_redigest(
    tmp_path: Path,
) -> None:
    coordinator, evaluation_id, trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    records = [json.loads(line) for line in trace_path.read_bytes().splitlines()]
    noncanonical = b"".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for record in records
    )
    _replace_indexed_trace(
        tmp_path,
        evaluation_id,
        "attempt-0001",
        noncanonical,
    )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(evaluation_id)

    assert captured.value.code == "internal"


def test_repository_restart_cleans_partial_and_unreferenced_crash_residue(
    tmp_path: Path,
) -> None:
    _coordinator, evaluation_id, trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    trace_root = tmp_path / "evaluation-attempt-traces"
    pending = trace_root / ".pending" / ("pending-" + "a" * 32 + ".tmp")
    pending.write_bytes(b'{"partial":')
    pending.chmod(0o600)
    orphan_payload = trace_path.read_bytes() + b"orphan"
    orphan_digest = hashlib.sha256(orphan_payload).hexdigest()
    orphan = (
        trace_root
        / "sha256"
        / orphan_digest[:2]
        / f"{orphan_digest}.jsonl"
    )
    orphan.parent.mkdir(mode=0o700)
    orphan.write_bytes(orphan_payload)
    orphan.chmod(0o600)

    reopened = EvaluationRepository(tmp_path)

    assert reopened.load(evaluation_id).slots[0].attempt is not None
    assert trace_path.is_file()
    assert not pending.exists()
    assert not orphan.exists()


def _create_legacy_attempt_table(database: Path, *, populated: bool) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE evaluation_attempt_slots (
                evaluation_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                scenario_id TEXT NOT NULL,
                attempt_json TEXT,
                attempt_digest TEXT
            )
            """
        )
        if populated:
            connection.execute(
                """
                INSERT INTO evaluation_attempt_slots(
                    evaluation_id, attempt_id, ordinal, scenario_id,
                    attempt_json, attempt_digest
                ) VALUES (?, 'attempt-0001', 0, 'scenario-legacy', '{}', ?)
                """,
                (
                    "evaluation-" + "a" * 32,
                    "sha256:" + hashlib.sha256(b"{}").hexdigest(),
                ),
            )


def test_empty_legacy_blob_schema_migrates_without_trusting_attempt_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "evaluations.sqlite3"
    _create_legacy_attempt_table(database, populated=False)

    EvaluationRepository(tmp_path)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(evaluation_attempt_slots)"
            )
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "attempt_json" not in columns
    assert "trace_ref" in columns
    assert "index_digest" in columns


@pytest.mark.parametrize("future_version", (4, 999))
def test_repository_rejects_future_schema_versions_without_downgrading(
    tmp_path: Path,
    future_version: int,
) -> None:
    EvaluationRepository(tmp_path)
    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(f"PRAGMA user_version = {future_version}")

    with pytest.raises(
        EvaluationRepositoryError,
        match="schema is unsupported",
    ) as captured:
        EvaluationRepository(tmp_path)

    assert captured.value.code == "storage"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == future_version


@pytest.mark.parametrize(
    "table_name",
    ("evaluation_plans", "evaluation_attempt_slots"),
)
def test_repository_rejects_unexpected_columns_in_current_schema(
    tmp_path: Path,
    table_name: str,
) -> None:
    EvaluationRepository(tmp_path)
    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN future_extension TEXT"
        )
        connection.execute("PRAGMA user_version = 3")

    with pytest.raises(
        EvaluationRepositoryError,
        match="schema is unsupported",
    ) as captured:
        EvaluationRepository(tmp_path)

    assert captured.value.code == "storage"


def _rebuild_current_table_with_weakened_definition(
    database: Path,
    *,
    table_name: str,
    required_fragment: str,
    weakened_fragment: str,
) -> None:
    weakened_table = f"{table_name}_weakened"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        original_sql = row[0]
        assert original_sql.count(required_fragment) == 1
        weakened_sql = original_sql.replace(
            f"CREATE TABLE {table_name}",
            f"CREATE TABLE {weakened_table}",
            1,
        ).replace(required_fragment, weakened_fragment, 1)
        columns = tuple(
            column[1]
            for column in connection.execute(f"PRAGMA table_info({table_name})")
        )
        assert columns
        column_list = ", ".join(columns)
        connection.execute(weakened_sql)
        connection.execute(
            f"INSERT INTO {weakened_table}({column_list}) "
            f"SELECT {column_list} FROM {table_name}"
        )
        connection.execute(f"DROP TABLE {table_name}")
        connection.execute(
            f"ALTER TABLE {weakened_table} RENAME TO {table_name}"
        )
        connection.execute("PRAGMA user_version = 3")


@pytest.mark.parametrize(
    ("table_name", "required_fragment", "weakened_fragment"),
    (
        (
            "evaluation_plans",
            "created_sequence INTEGER PRIMARY KEY AUTOINCREMENT",
            "created_sequence INTEGER",
        ),
        (
            "evaluation_plans",
            "created_sequence INTEGER PRIMARY KEY AUTOINCREMENT",
            "created_sequence INTEGER PRIMARY KEY /* AUTOINCREMENT */",
        ),
        (
            "evaluation_plans",
            "evaluation_id TEXT NOT NULL UNIQUE",
            "evaluation_id TEXT NOT NULL",
        ),
        (
            "evaluation_plans",
            "plan_json TEXT NOT NULL",
            "plan_json TEXT",
        ),
        (
            "evaluation_plans",
            "plan_digest TEXT NOT NULL",
            "plan_digest BLOB NOT NULL",
        ),
        (
            "evaluation_plans",
            """status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'interrupted')
    )""",
            "status TEXT NOT NULL",
        ),
        (
            "evaluation_plans",
            "status TEXT NOT NULL CHECK",
            "status TEXT COLLATE NOCASE NOT NULL CHECK",
        ),
        (
            "evaluation_plans",
            "plan_json TEXT NOT NULL",
            "plan_json TEXT COLLATE RTRIM NOT NULL",
        ),
        (
            "evaluation_plans",
            """status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'interrupted')
    )""",
            """status TEXT NOT NULL /* CHECK (
        status IN ('queued', 'running', 'completed', 'interrupted')
    ) */""",
        ),
        (
            "evaluation_attempt_slots",
            "ordinal INTEGER NOT NULL CHECK (ordinal >= 0)",
            "ordinal INTEGER NOT NULL",
        ),
        (
            "evaluation_attempt_slots",
            "scenario_id TEXT NOT NULL",
            "scenario_id TEXT",
        ),
        (
            "evaluation_attempt_slots",
            "ordinal INTEGER NOT NULL CHECK (ordinal >= 0)",
            "ordinal TEXT NOT NULL CHECK (ordinal >= 0)",
        ),
        (
            "evaluation_attempt_slots",
            "PRIMARY KEY (evaluation_id, attempt_id),",
            "",
        ),
        (
            "evaluation_attempt_slots",
            "UNIQUE (evaluation_id, ordinal),",
            "",
        ),
        (
            "evaluation_attempt_slots",
            "UNIQUE (evaluation_id, scenario_id),",
            "",
        ),
        (
            "evaluation_attempt_slots",
            """FOREIGN KEY (evaluation_id)
        REFERENCES evaluation_plans(evaluation_id),""",
            "",
        ),
        (
            "evaluation_attempt_slots",
            """disposition TEXT CHECK (
        disposition IN (
            'scientific_success',
            'scientific_failure',
            'infrastructure_error'
        )
    )""",
            "disposition TEXT",
        ),
        (
            "evaluation_attempt_slots",
            "disposition TEXT CHECK",
            "disposition TEXT COLLATE NOCASE CHECK",
        ),
        (
            "evaluation_attempt_slots",
            "summary TEXT,",
            "summary TEXT COLLATE RTRIM,",
        ),
        (
            "evaluation_attempt_slots",
            """authenticated_local_runtime INTEGER CHECK (
        authenticated_local_runtime IN (0, 1)
    )""",
            "authenticated_local_runtime INTEGER",
        ),
        (
            "evaluation_attempt_slots",
            """    CHECK (
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
    )""",
            "    CHECK (1)",
        ),
    ),
)
def test_repository_rejects_current_schema_with_weakened_table_constraints(
    tmp_path: Path,
    table_name: str,
    required_fragment: str,
    weakened_fragment: str,
) -> None:
    EvaluationRepository(tmp_path)
    _rebuild_current_table_with_weakened_definition(
        tmp_path / "evaluations.sqlite3",
        table_name=table_name,
        required_fragment=required_fragment,
        weakened_fragment=weakened_fragment,
    )

    with pytest.raises(
        EvaluationRepositoryError,
        match="schema is unsupported",
    ) as captured:
        EvaluationRepository(tmp_path)

    assert captured.value.code == "storage"


def test_populated_legacy_blob_schema_fails_closed_for_explicit_migration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "evaluations.sqlite3"
    _create_legacy_attempt_table(database, populated=True)

    with pytest.raises(
        EvaluationRepositoryError,
        match="require explicit migration",
    ) as captured:
        EvaluationRepository(tmp_path)

    assert captured.value.code == "storage"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT attempt_json FROM evaluation_attempt_slots"
        ).fetchone()[0] == "{}"


def test_v2_index_migration_refuses_a_summary_not_derived_from_its_trace(
    tmp_path: Path,
) -> None:
    _coordinator, _evaluation_id, _trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            CREATE TABLE evaluation_attempt_slots_v2_forged (
                evaluation_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                scenario_id TEXT NOT NULL,
                trace_ref TEXT,
                trace_digest TEXT,
                disposition TEXT,
                summary TEXT,
                interaction_digest TEXT,
                runtime_trace_digest TEXT,
                result_digest TEXT,
                authenticated_local_runtime INTEGER,
                PRIMARY KEY (evaluation_id, attempt_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO evaluation_attempt_slots_v2_forged(
                evaluation_id, attempt_id, ordinal, scenario_id,
                trace_ref, trace_digest, disposition, summary,
                interaction_digest, runtime_trace_digest, result_digest,
                authenticated_local_runtime
            )
            SELECT evaluation_id, attempt_id, ordinal, scenario_id,
                   trace_ref, trace_digest, disposition, 'Forged scientific summary.',
                   interaction_digest, runtime_trace_digest, result_digest,
                   authenticated_local_runtime
            FROM evaluation_attempt_slots
            """
        )
        connection.execute("DROP TABLE evaluation_attempt_slots")
        connection.execute(
            "ALTER TABLE evaluation_attempt_slots_v2_forged "
            "RENAME TO evaluation_attempt_slots"
        )
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(
        EvaluationRepositoryError,
        match="migration failed integrity validation",
    ) as captured:
        EvaluationRepository(tmp_path)

    assert captured.value.code == "storage"
    with sqlite3.connect(database) as connection:
        summary = connection.execute(
            "SELECT summary FROM evaluation_attempt_slots"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(evaluation_attempt_slots)"
            )
        }
    assert summary == "Forged scientific summary."
    assert "index_digest" not in columns


def test_v2_index_migration_derives_and_backfills_an_honest_trace_index(
    tmp_path: Path,
) -> None:
    coordinator, evaluation_id, _trace_path, _trace_digest = _persist_one_attempt(
        tmp_path
    )
    expected = coordinator.load(evaluation_id).attempts[0]
    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            CREATE TABLE evaluation_attempt_slots_v2_honest AS
            SELECT evaluation_id, attempt_id, ordinal, scenario_id,
                   trace_ref, trace_digest, disposition, summary,
                   interaction_digest, runtime_trace_digest, result_digest,
                   authenticated_local_runtime
            FROM evaluation_attempt_slots
            """
        )
        connection.execute("DROP TABLE evaluation_attempt_slots")
        connection.execute(
            "ALTER TABLE evaluation_attempt_slots_v2_honest "
            "RENAME TO evaluation_attempt_slots"
        )
        connection.execute("PRAGMA user_version = 2")

    reopened = EvaluationRepository(tmp_path)

    listed = reopened.list()[0].slots[0].index
    assert listed is not None
    assert listed.summary == expected.summary
    assert listed.interaction_digest == expected.interaction_digest
    assert reopened.load(evaluation_id).slots[0].attempt is not None
    with sqlite3.connect(database) as connection:
        index_digest = connection.execute(
            "SELECT index_digest FROM evaluation_attempt_slots"
        ).fetchone()[0]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert isinstance(index_digest, str) and index_digest.startswith("sha256:")


def test_restart_interrupts_a_stale_execution_and_resumes_only_empty_slots(
    tmp_path: Path,
) -> None:
    crashing_factory = _CrashingRunnerFactory()
    first = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=crashing_factory,
    )
    queued = first.launch()

    with pytest.raises(_InjectedProcessCrash):
        first.execute(queued.evaluation_id)

    abandoned = first.load(queued.evaluation_id)
    assert abandoned.status == "running"
    assert len(abandoned.attempts) == 1
    preserved_attempt = abandoned.attempts[0]

    resume_factory = _MixedRunnerFactory()
    reopened = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=resume_factory,
    )
    interrupted = reopened.load(queued.evaluation_id)

    assert interrupted.status == "interrupted"
    assert interrupted.progress.message == (
        "Evaluation stopped before all scenarios finished; "
        "1 completed scenario remains available."
    )
    assert interrupted.attempts == (preserved_attempt,)

    completed = reopened.execute(queued.evaluation_id)
    assert completed.status == "completed"
    assert completed.attempts[0] == preserved_attempt
    assert len(resume_factory.runners) == 1
    assert tuple(resume_factory.runners[0].scenario_ids) == (
        queued.plan.scenario_ids[1:]
    )


def test_opening_another_coordinator_does_not_interrupt_live_execution(
    tmp_path: Path,
) -> None:
    entered = Event()
    release = Event()
    first = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_BlockingRunnerFactory(entered, release),
    )
    queued = first.launch()

    with ThreadPoolExecutor(max_workers=2) as executor:
        execution = executor.submit(first.execute, queued.evaluation_id)
        assert entered.wait(timeout=2)
        reopening = executor.submit(
            EvaluationCoordinator,
            artifact_root=tmp_path,
            runner_factory=_RunnerFactory(),
        )
        try:
            reopened = reopening.result(timeout=1)
            live = reopened.load(queued.evaluation_id)
            assert live.status == "running"
            assert live.progress.completed_scenarios == 0
        finally:
            release.set()
        assert execution.result(timeout=20).status == "completed"


def test_replay_is_deterministic_and_never_calls_the_model_runner(
    tmp_path: Path,
) -> None:
    execution_factory = _MixedRunnerFactory()
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=execution_factory,
    )
    completed = coordinator.execute(coordinator.launch().evaluation_id)
    success = next(
        attempt
        for attempt in completed.attempts
        if attempt.disposition == "scientific_success"
    )
    infrastructure = next(
        attempt
        for attempt in completed.attempts
        if attempt.disposition == "infrastructure_error"
    )
    runner_count = len(execution_factory.runners)

    replayed = coordinator.replay(completed.evaluation_id, success.attempt_id)

    assert replayed.attempt == success
    assert replayed.snapshot is not None
    assert replayed.snapshot.verifier_result is not None
    assert replayed.snapshot.verifier_result.passed is True
    assert replayed.report is not None
    assert replayed.report.trace_matches is True
    assert replayed.report.result_matches is True
    assert replayed.report.source_trace_digest == success.runtime_trace_digest
    assert replayed.report.replay_trace_digest == success.runtime_trace_digest
    assert replayed.report.source_result_digest == success.result_digest
    assert replayed.report.replay_result_digest == success.result_digest
    assert replayed.infrastructure_error is None
    assert len(execution_factory.runners) == runner_count

    opened_error = coordinator.replay(
        completed.evaluation_id,
        infrastructure.attempt_id,
    )

    assert opened_error.attempt == infrastructure
    assert opened_error.snapshot is None
    assert opened_error.report is None
    assert opened_error.infrastructure_error is not None
    assert opened_error.infrastructure_error.category == "inference"
    assert "private endpoint" not in opened_error.model_dump_json().casefold()
    assert len(execution_factory.runners) == runner_count


def test_attempt_slots_are_predeclared_write_once_and_digest_checked(
    tmp_path: Path,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_CrashingRunnerFactory(),
    )
    queued = coordinator.launch()
    with pytest.raises(_InjectedProcessCrash):
        coordinator.execute(queued.evaluation_id)

    repository = EvaluationRepository(tmp_path)
    stored = repository.load(queued.evaluation_id)
    completed_slot = stored.slots[0]
    assert completed_slot.attempt is not None
    assert len(stored.slots) == 32
    assert sum(slot.attempt is not None for slot in stored.slots) == 1
    with pytest.raises(EvaluationRepositoryError, match="write-once") as captured:
        repository.record_attempt(
            queued.evaluation_id,
            completed_slot.attempt_id,
            completed_slot.attempt,
        )
    assert captured.value.code == "conflict"

    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT trace_ref, trace_digest
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = ?
            """,
            (queued.evaluation_id, completed_slot.attempt_id),
        ).fetchone()
        assert row is not None
        trace_ref, trace_digest = row
        assert isinstance(trace_digest, str) and trace_digest.startswith("sha256:")
    trace_path = tmp_path / trace_ref
    trace_path.write_bytes(trace_path.read_bytes() + b" ")

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as tampered:
        coordinator.load(queued.evaluation_id)
    assert getattr(tampered.value, "code", None) == "internal"


@pytest.mark.parametrize(
    "evaluation_id",
    (
        "evaluation-" + "a" * 31 + "/",
        "evaluation-" + "A" * 32,
    ),
)
def test_repository_rejects_noncanonical_evaluation_identities(
    tmp_path: Path,
    evaluation_id: str,
) -> None:
    repository = EvaluationRepository(tmp_path)

    with pytest.raises(EvaluationRepositoryError, match="identity is invalid") as error:
        repository.load(evaluation_id)

    assert error.value.code == "not_found"


def test_repository_refuses_a_symlinked_database_without_mutating_its_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.sqlite3"
    with sqlite3.connect(outside) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('unchanged')")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "evaluations.sqlite3").symlink_to(outside)

    with pytest.raises(
        EvaluationRepositoryError,
        match="could not be opened",
    ) as captured:
        EvaluationRepository(artifact_root)

    assert captured.value.code == "storage"
    with sqlite3.connect(outside) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == (
            "unchanged"
        )
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        } == {"sentinel"}


def test_repository_refuses_a_symlinked_lock_directory_without_chmod_or_files(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-locks"
    outside.mkdir(mode=0o755)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / ".evaluation-locks").symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        EvaluationRepositoryError,
        match="could not be opened",
    ) as captured:
        EvaluationRepository(artifact_root)

    assert captured.value.code == "storage"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert tuple(outside.iterdir()) == ()


def test_repository_database_creation_is_safe_under_concurrent_initialization(
    tmp_path: Path,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        repositories = tuple(
            executor.map(lambda _ordinal: EvaluationRepository(tmp_path), range(16))
        )

    assert all(
        repository.database_path == tmp_path / "evaluations.sqlite3"
        for repository in repositories
    )
    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        } >= {"evaluation_plans", "evaluation_attempt_slots"}


def test_consistently_redigested_attempt_cannot_change_its_reserved_scenario(
    tmp_path: Path,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_CrashingRunnerFactory(),
    )
    queued = coordinator.launch()
    with pytest.raises(_InjectedProcessCrash):
        coordinator.execute(queued.evaluation_id)

    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        trace_ref = connection.execute(
            """
            SELECT trace_ref
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = 'attempt-0001'
            """,
            (queued.evaluation_id,),
        ).fetchone()[0]
    records = [json.loads(line) for line in (tmp_path / trace_ref).read_bytes().splitlines()]
    records[0]["scenario_id"] = queued.plan.scenario_ids[1]
    _replace_indexed_trace(
        tmp_path,
        queued.evaluation_id,
        "attempt-0001",
        _canonical_jsonl(records),
    )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(queued.evaluation_id)
    assert captured.value.code == "internal"


def test_consistently_redigested_attempt_cannot_change_scientific_result(
    tmp_path: Path,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_MixedRunnerFactory(),
    )
    completed = coordinator.execute(coordinator.launch().evaluation_id)
    failure = next(
        attempt
        for attempt in completed.attempts
        if attempt.disposition == "scientific_failure"
    )

    with sqlite3.connect(tmp_path / "evaluations.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT trace_ref
            FROM evaluation_attempt_slots
            WHERE evaluation_id = ? AND attempt_id = ?
            """,
            (completed.evaluation_id, failure.attempt_id),
        ).fetchone()
        assert row is not None
        records = [
            json.loads(line)
            for line in (tmp_path / row[0]).read_bytes().splitlines()
        ]
    outcome = next(record for record in records if record["record_type"] == "outcome")
    outcome["payload"]["completed_run"]["verifier_result"]["passed"] = True
    _replace_indexed_trace(
        tmp_path,
        completed.evaluation_id,
        failure.attempt_id,
        _canonical_jsonl(records),
    )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="failed integrity validation",
    ) as captured:
        coordinator.load(completed.evaluation_id)
    assert captured.value.code == "internal"


@pytest.mark.parametrize(
    "private_material",
    (
        "https://10.0.0.7/v1?token=do-not-store",
        "adapter connection failed at [fd00::1]:8000",
        "adapter connection failed at gemma-gateway.lab.internal:8000",
        "OPENAI_ACCESS_TOKEN=do-not-store",
        '{"hf_token":"do-not-store"}',
        "ghp_" + "a" * 36,
        "adapter failed at gpu-box",
        "gemma.private.example",
        "/opt/private-models/gemma",
    ),
)
def test_transport_material_is_rejected_before_attempt_persistence(
    tmp_path: Path,
    private_material: str,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_UnsafeRunnerFactory(private_material),
    )
    queued = coordinator.launch()

    with pytest.raises(
        EvaluationCoordinatorError,
        match="stopped before completion",
    ) as captured:
        coordinator.execute(queued.evaluation_id)

    assert captured.value.code == "internal"
    interrupted = coordinator.load(queued.evaluation_id)
    assert interrupted.status == "interrupted"
    assert interrupted.attempts == ()
    persisted = (tmp_path / "evaluations.sqlite3").read_bytes().lower()
    assert private_material.encode("utf-8").lower() not in persisted


def test_server_owned_plan_rejects_a_consistently_redigested_database_edit(
    tmp_path: Path,
) -> None:
    coordinator = EvaluationCoordinator(
        artifact_root=tmp_path,
        runner_factory=_RunnerFactory(),
    )
    launched = coordinator.launch()
    database = tmp_path / "evaluations.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT plan_json FROM evaluation_plans WHERE evaluation_id = ?",
            (launched.evaluation_id,),
        ).fetchone()
        assert row is not None
        document = json.loads(row[0])
        document["bundle_revision"] = "forged-revision"
        rewritten = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = "sha256:" + hashlib.sha256(rewritten.encode("utf-8")).hexdigest()
        connection.execute(
            """
            UPDATE evaluation_plans
            SET plan_json = ?, plan_digest = ?
            WHERE evaluation_id = ?
            """,
            (rewritten, digest, launched.evaluation_id),
        )

    with pytest.raises(
        EvaluationCoordinatorError,
        match="does not match the approved profile",
    ) as captured:
        coordinator.load(launched.evaluation_id)
    assert captured.value.code == "internal"
