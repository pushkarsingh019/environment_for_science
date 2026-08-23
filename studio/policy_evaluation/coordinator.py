"""Durable orchestration for the fixed local base-Gemma development evaluation."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from environments.eeg._curriculum_contract import CANONICAL_OBJECTIVE
from environments.eeg.curriculum import load_development_scenario_set
from studio.bundle import EnvironmentBundle
from studio.runtime import (
    IncompleteTerminationReason,
    RunSnapshot,
    RuntimeContractError,
)

from .model_runner import (
    CanonicalEvaluationTrace,
    EvaluationAttempt,
    InfrastructureError,
    ModelIdentity,
)
from .repository import (
    EvaluationPlan,
    EvaluationRepository,
    EvaluationRepositoryError,
    EvaluationStatus,
    StoredAttemptIndexSlot,
    StoredAttemptSlot,
    StoredEvaluation,
    StoredEvaluationIndex,
)
from .runtime_bridge import EvaluationRuntimeBridge

EvaluationProfile = Literal["base-gemma-development-v1"]
AttemptDisposition = Literal[
    "scientific_success", "scientific_failure", "infrastructure_error"
]
CalibrationStatus = Literal["pending", "ready", "not_ready"]
CalibrationLevel = Literal[0, 1, 2, 3, 4, 5]

_CALIBRATION_LEVELS: tuple[tuple[CalibrationLevel, str, tuple[str, ...]], ...] = (
    (0, "Nominal orientation", ("nominal_orientation",)),
    (1, "Observable integration", ("marker_only", "integration_preflight")),
    (2, "Obvious EEG evidence", ("eeg_preflight",)),
    (3, "Ambiguity and controls", ("ambiguity",)),
    (4, "Runtime validity", ("runtime_recovery",)),
    (5, "Taught compounds", ("compound_recovery",)),
)
_STAGE_TO_LEVEL = {
    stage: level
    for level, _label, stages in _CALIBRATION_LEVELS
    for stage in stages
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvaluationRunner(Protocol):
    """Narrow injected seam implemented by the canonical model runner."""

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt: ...


class EvaluationRunnerFactory(Protocol):
    """Create one runner without persisting provider transport configuration."""

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner: ...


class EvaluationCoordinatorError(ValueError):
    """Safe public failure from evaluation orchestration."""

    def __init__(
        self,
        message: str,
        *,
        code: Literal["invalid", "conflict", "not_found", "internal"],
    ) -> None:
        super().__init__(message)
        self.code = code


class EvaluationProgress(_FrozenModel):
    """Ordinary-language progress with scientific and infrastructure outcomes split."""

    phase: EvaluationStatus
    message: str = Field(min_length=1)
    completed_scenarios: int = Field(ge=0)
    total_scenarios: int = Field(ge=1)
    scientific_successes: int = Field(ge=0)
    scientific_failures: int = Field(ge=0)
    infrastructure_errors: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> EvaluationProgress:
        outcomes = (
            self.scientific_successes
            + self.scientific_failures
            + self.infrastructure_errors
        )
        if outcomes != self.completed_scenarios:
            raise ValueError("evaluation progress outcome counts do not add up")
        if self.completed_scenarios > self.total_scenarios:
            raise ValueError("evaluation progress exceeds its scenario matrix")
        return self


class EvaluationAttemptSummary(_FrozenModel):
    """Compact safe result used by progress and result-selection views."""

    attempt_id: str = Field(pattern=r"^attempt-[0-9]{4}$")
    ordinal: int = Field(ge=0)
    scenario_id: str = Field(min_length=1)
    disposition: AttemptDisposition
    summary: str = Field(min_length=1)
    interaction_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    runtime_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )


class CalibrationLevelOutcome(_FrozenModel):
    """Aggregate scientific outcomes for one approved difficulty level."""

    level: CalibrationLevel
    label: str = Field(min_length=1)
    total_scenarios: int = Field(ge=1)
    completed_scenarios: int = Field(ge=0)
    scientific_successes: int = Field(ge=0)
    scientific_failures: int = Field(ge=0)
    infrastructure_errors: int = Field(ge=0)
    has_success_and_failure: bool

    @model_validator(mode="after")
    def validate_counts(self) -> CalibrationLevelOutcome:
        outcomes = (
            self.scientific_successes
            + self.scientific_failures
            + self.infrastructure_errors
        )
        if outcomes != self.completed_scenarios:
            raise ValueError("calibration level outcome counts do not add up")
        if self.completed_scenarios > self.total_scenarios:
            raise ValueError("calibration level exceeds its scenario count")
        mixed = self.scientific_successes > 0 and self.scientific_failures > 0
        if mixed != self.has_success_and_failure:
            raise ValueError("calibration level mixture flag is inconsistent")
        return self


class CalibrationAssessment(_FrozenModel):
    """Server-derived readiness evidence without scenario causal truth."""

    status: CalibrationStatus
    summary: str = Field(min_length=1)
    scientific_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    target_accuracy_minimum: float = Field(default=0.2, ge=0.0, le=1.0)
    target_accuracy_maximum: float = Field(default=0.7, ge=0.0, le=1.0)
    overall_accuracy_in_target: bool
    levels_1_and_2_mixed: bool
    no_infrastructure_errors: bool
    authenticated_local_runtime: bool
    levels: tuple[CalibrationLevelOutcome, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_assessment(self) -> CalibrationAssessment:
        if tuple(level.level for level in self.levels) != (0, 1, 2, 3, 4, 5):
            raise ValueError("calibration levels must be complete and ordered")
        if self.target_accuracy_minimum >= self.target_accuracy_maximum:
            raise ValueError("calibration accuracy bounds must be ordered")
        in_target = (
            self.scientific_accuracy is not None
            and self.target_accuracy_minimum
            <= self.scientific_accuracy
            <= self.target_accuracy_maximum
        )
        if in_target != self.overall_accuracy_in_target:
            raise ValueError("calibration accuracy flag is inconsistent")
        mixed = self.levels[1].has_success_and_failure and self.levels[
            2
        ].has_success_and_failure
        if mixed != self.levels_1_and_2_mixed:
            raise ValueError("calibration level mixture is inconsistent")
        scientific_successes = sum(
            level.scientific_successes for level in self.levels
        )
        scientific_failures = sum(
            level.scientific_failures for level in self.levels
        )
        scientific_attempts = scientific_successes + scientific_failures
        aggregate_accuracy = (
            scientific_successes / scientific_attempts
            if scientific_attempts
            else None
        )
        if self.scientific_accuracy != aggregate_accuracy:
            raise ValueError("calibration scientific accuracy is inconsistent")
        complete = all(
            level.completed_scenarios == level.total_scenarios
            for level in self.levels
        )
        final_no_infrastructure_errors = complete and all(
            level.infrastructure_errors == 0 for level in self.levels
        )
        if self.status == "pending":
            if self.no_infrastructure_errors or self.authenticated_local_runtime:
                raise ValueError(
                    "pending calibration cannot claim finalized readiness evidence"
                )
        elif self.no_infrastructure_errors != final_no_infrastructure_errors:
            raise ValueError("calibration infrastructure-error flag is inconsistent")
        if self.authenticated_local_runtime and not complete:
            raise ValueError("incomplete calibration cannot authenticate every row")
        ready = (
            complete
            and self.overall_accuracy_in_target
            and self.levels_1_and_2_mixed
            and self.no_infrastructure_errors
            and self.authenticated_local_runtime
        )
        # ``pending`` remains valid during the narrow interval after the final
        # attempt is durable but before the coordinator finalizes the matrix.
        if self.status == "ready" and not ready:
            raise ValueError("calibration readiness status is inconsistent")
        if self.status == "not_ready" and ready:
            raise ValueError("calibration readiness status is inconsistent")
        if self.status == "not_ready" and not complete:
            raise ValueError("incomplete calibration cannot be final")
        return self


class EvaluationSummary(_FrozenModel):
    """Small list entry for loading an existing local evaluation."""

    evaluation_id: str = Field(pattern=r"^evaluation-[0-9a-f]{32}$")
    profile: EvaluationProfile
    model: ModelIdentity
    status: EvaluationStatus
    progress: EvaluationProgress


class EvaluationSnapshot(_FrozenModel):
    """Durable plan, progress, and compact terminal attempts."""

    evaluation_id: str = Field(pattern=r"^evaluation-[0-9a-f]{32}$")
    status: EvaluationStatus
    plan: EvaluationPlan
    progress: EvaluationProgress
    calibration: CalibrationAssessment
    attempts: tuple[EvaluationAttemptSummary, ...]


class EvaluationReplayReport(_FrozenModel):
    source_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    replay_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trace_matches: bool
    source_result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    replay_result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_matches: bool


class EvaluationReplay(_FrozenModel):
    """Read-only deterministic replay or a stored infrastructure outcome."""

    evaluation_id: str = Field(pattern=r"^evaluation-[0-9a-f]{32}$")
    attempt: EvaluationAttemptSummary
    interaction: CanonicalEvaluationTrace
    snapshot: RunSnapshot | None = None
    report: EvaluationReplayReport | None = None
    infrastructure_error: InfrastructureError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> EvaluationReplay:
        scientific = self.attempt.disposition != "infrastructure_error"
        if scientific != (self.snapshot is not None and self.report is not None):
            raise ValueError("evaluation replay does not match its attempt disposition")
        if scientific == (self.infrastructure_error is not None):
            raise ValueError("evaluation replay infrastructure shape is invalid")
        if (
            self.interaction.interaction_digest != self.attempt.interaction_digest
            or self.interaction.runtime_trace_digest
            != self.attempt.runtime_trace_digest
        ):
            raise ValueError("evaluation replay interaction does not match its attempt")
        if self.interaction.infrastructure_error != self.infrastructure_error:
            raise ValueError("evaluation replay error lineage is inconsistent")
        return self


class EvaluationCoordinator:
    """Launch, resume, load, and replay one fixed development calibration profile."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        runner_factory: EvaluationRunnerFactory,
    ) -> None:
        self._scenario_set = load_development_scenario_set()
        self._bundle = self._scenario_set.environment_bundle
        self._scenario_levels = {
            reference.scenario_id: _STAGE_TO_LEVEL[reference.stage]
            for reference in self._scenario_set.catalog
        }
        self._runner_factory = runner_factory
        self._repository = EvaluationRepository(artifact_root)
        self._plan = self._fixed_plan()
        try:
            self._repository.reconcile_stale_running()
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error

    def launch(
        self,
        profile: EvaluationProfile = "base-gemma-development-v1",
    ) -> EvaluationSnapshot:
        """Reserve the approved development matrix without starting inference."""
        if profile != "base-gemma-development-v1":
            raise EvaluationCoordinatorError(
                "unknown local evaluation profile",
                code="invalid",
            )
        try:
            return self._snapshot(self._repository.create(self._plan))
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error

    def list(self) -> tuple[EvaluationSummary, ...]:
        """List existing evaluations without loading full canonical attempts."""
        try:
            return tuple(self._summary(record) for record in self._repository.list())
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error

    def load(self, evaluation_id: str) -> EvaluationSnapshot:
        """Load one integrity-validated durable evaluation."""
        try:
            return self._snapshot(self._repository.load(evaluation_id))
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error

    def execute(self, evaluation_id: str) -> EvaluationSnapshot:
        """Run or resume every empty slot through the injected canonical runner."""
        try:
            with self._repository.execution_lock(evaluation_id) as acquired:
                if not acquired:
                    raise EvaluationCoordinatorError(
                        "the evaluation is already running",
                        code="conflict",
                    )
                try:
                    claimed = self._repository.claim(evaluation_id)
                    self._validate_record_plan(claimed)
                    if claimed.status == "completed":
                        return self._snapshot(claimed)
                    runner = self._runner_factory(self._bundle.model_copy(deep=True))
                    for slot in claimed.slots:
                        if slot.attempt is not None:
                            continue
                        attempt = runner.run(
                            scenario_id=slot.scenario_id,
                            objective=claimed.plan.objective,
                            model=claimed.plan.model.model_copy(deep=True),
                        )
                        self._repository.record_attempt(
                            evaluation_id,
                            slot.attempt_id,
                            attempt,
                        )
                    return self._snapshot(
                        self._repository.complete(evaluation_id)
                    )
                except EvaluationRepositoryError as error:
                    self._interrupt_after_failure(evaluation_id)
                    raise _coordinator_error(error) from error
                except EvaluationCoordinatorError:
                    self._interrupt_after_failure(evaluation_id)
                    raise
                except Exception:
                    self._interrupt_after_failure(evaluation_id)
                    raise EvaluationCoordinatorError(
                        "evaluation execution stopped before completion",
                        code="internal",
                    ) from None
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error

    def replay(
        self,
        evaluation_id: str,
        attempt_id: str,
    ) -> EvaluationReplay:
        """Open an attempt and deterministically replay actions without inference."""
        try:
            record = self._repository.load(evaluation_id)
            self._validate_record_plan(record)
            slot = next(
                (item for item in record.slots if item.attempt_id == attempt_id),
                None,
            )
            if slot is None:
                raise EvaluationCoordinatorError(
                    "evaluation attempt was not found",
                    code="not_found",
                )
            if slot.attempt is None:
                raise EvaluationCoordinatorError(
                    "evaluation attempt has not completed",
                    code="conflict",
                )
            attempt = slot.attempt
            summary = self._attempt_summary(slot)
            if attempt.infrastructure_error is not None:
                return EvaluationReplay(
                    evaluation_id=evaluation_id,
                    attempt=summary,
                    interaction=attempt.trace.model_copy(deep=True),
                    infrastructure_error=attempt.infrastructure_error.model_copy(
                        deep=True
                    ),
                )
            source = attempt.completed_run
            if source is None or source.result_digest is None:
                raise EvaluationCoordinatorError(
                    "the scientific evaluation attempt is incomplete",
                    code="internal",
                )
            bridge = EvaluationRuntimeBridge(self._bundle.model_copy(deep=True))
            state = bridge.start(slot.scenario_id, record.plan.model.policy_identity())
            for action in attempt.trace.accepted_actions:
                state = bridge.apply(state, action.model_copy(deep=True))
            termination_reason = _incomplete_termination_reason(source)
            replayed = (
                bridge.finalize_incomplete(
                    state,
                    termination_reason=termination_reason,
                )
                if termination_reason is not None
                else bridge.finalize(state)
            )
            if replayed.result_digest is None:
                raise EvaluationCoordinatorError(
                    "the deterministic evaluation replay did not produce a result",
                    code="internal",
                )
            return EvaluationReplay(
                evaluation_id=evaluation_id,
                attempt=summary,
                interaction=attempt.trace.model_copy(deep=True),
                snapshot=replayed,
                report=EvaluationReplayReport(
                    source_trace_digest=attempt.trace.runtime_trace_digest,
                    replay_trace_digest=replayed.trace_digest,
                    trace_matches=(
                        replayed.trace_digest == attempt.trace.runtime_trace_digest
                    ),
                    source_result_digest=source.result_digest,
                    replay_result_digest=replayed.result_digest,
                    result_matches=(replayed.result_digest == source.result_digest),
                ),
            )
        except EvaluationRepositoryError as error:
            raise _coordinator_error(error) from error
        except RuntimeContractError:
            raise EvaluationCoordinatorError(
                "the deterministic evaluation replay could not be completed",
                code="internal",
            ) from None

    def _interrupt_after_failure(self, evaluation_id: str) -> None:
        with suppress(EvaluationRepositoryError):
            self._repository.interrupt(evaluation_id)

    def _fixed_plan(self) -> EvaluationPlan:
        identity = self._scenario_set.identity
        return EvaluationPlan(
            plan_revision="science-environment-evaluation-plan/1",
            profile="base-gemma-development-v1",
            environment_id=self._bundle.bundle_id,
            bundle_revision=self._bundle.bundle_revision,
            bundle_digest=_bundle_digest(self._bundle),
            split="development",
            curriculum_package_digest=identity.package_digest,
            model=ModelIdentity(
                provider="local-openai-compatible",
                requested_model="google/gemma-4-E4B-it",
                adapter_revision="local-gemma-openai-chat/1",
            ),
            model_revision="ee0ef6023621cff504d758262d4e04895a5af4a2",
            objective=CANONICAL_OBJECTIVE,
            scenario_ids=self._scenario_set.scenario_ids,
        )

    def _snapshot(self, record: StoredEvaluation) -> EvaluationSnapshot:
        self._validate_record_plan(record)
        attempts = tuple(
            self._attempt_summary(slot)
            for slot in record.slots
            if slot.attempt is not None
        )
        progress = _progress(record.status, attempts, len(record.plan.scenario_ids))
        authenticated_scenarios = {
            slot.scenario_id
            for slot in record.slots
            if slot.attempt is not None
            and slot.attempt.trace.run.local_gemma_attestation is not None
        }
        return EvaluationSnapshot(
            evaluation_id=record.evaluation_id,
            status=record.status,
            plan=record.plan.model_copy(deep=True),
            progress=progress,
            calibration=assess_calibration(
                record.status,
                attempts,
                record.plan.scenario_ids,
                self._scenario_levels,
                authenticated_scenarios,
            ),
            attempts=attempts,
        )

    def _summary(self, record: StoredEvaluationIndex) -> EvaluationSummary:
        self._validate_record_plan(record)
        attempts = tuple(
            self._attempt_summary_from_index(slot)
            for slot in record.slots
            if slot.index is not None
        )
        return EvaluationSummary(
            evaluation_id=record.evaluation_id,
            profile=record.plan.profile,
            model=record.plan.model.model_copy(deep=True),
            status=record.status,
            progress=_progress(
                record.status,
                attempts,
                len(record.plan.scenario_ids),
            ),
        )

    def _validate_record_plan(
        self, record: StoredEvaluation | StoredEvaluationIndex
    ) -> None:
        if record.plan != self._plan:
            raise EvaluationCoordinatorError(
                "the stored evaluation plan does not match the approved profile",
                code="internal",
            )

    @staticmethod
    def _attempt_summary(slot: StoredAttemptSlot) -> EvaluationAttemptSummary:
        attempt = slot.attempt
        if attempt is None:
            raise RuntimeError("an empty slot has no attempt summary")
        if attempt.infrastructure_error is not None:
            disposition: AttemptDisposition = "infrastructure_error"
            summary = attempt.infrastructure_error.summary
            result_digest = None
        else:
            completed = attempt.completed_run
            if completed is None or completed.verifier_result is None:
                raise EvaluationCoordinatorError(
                    "a stored scientific attempt is incomplete",
                    code="internal",
                )
            disposition = (
                "scientific_success"
                if completed.verifier_result.passed
                else "scientific_failure"
            )
            summary = completed.verifier_result.summary
            result_digest = completed.result_digest
        return EvaluationAttemptSummary(
            attempt_id=slot.attempt_id,
            ordinal=slot.ordinal,
            scenario_id=slot.scenario_id,
            disposition=disposition,
            summary=summary,
            interaction_digest=attempt.trace.interaction_digest,
            runtime_trace_digest=attempt.trace.runtime_trace_digest,
            result_digest=result_digest,
        )

    @staticmethod
    def _attempt_summary_from_index(
        slot: StoredAttemptIndexSlot,
    ) -> EvaluationAttemptSummary:
        index = slot.index
        if index is None:
            raise RuntimeError("an empty slot has no attempt summary")
        return EvaluationAttemptSummary(
            attempt_id=slot.attempt_id,
            ordinal=slot.ordinal,
            scenario_id=slot.scenario_id,
            disposition=index.disposition,
            summary=index.summary,
            interaction_digest=index.interaction_digest,
            runtime_trace_digest=index.runtime_trace_digest,
            result_digest=index.result_digest,
        )


def _progress(
    status: EvaluationStatus,
    attempts: tuple[EvaluationAttemptSummary, ...],
    total: int,
) -> EvaluationProgress:
    completed = len(attempts)
    successes = sum(item.disposition == "scientific_success" for item in attempts)
    failures = sum(item.disposition == "scientific_failure" for item in attempts)
    infrastructure = sum(
        item.disposition == "infrastructure_error" for item in attempts
    )
    if status == "queued":
        message = f"Ready to evaluate {total} development scenarios with base Gemma."
    elif status == "running":
        message = f"Evaluated {completed} of {total} development scenarios."
    elif status == "completed":
        message = (
            f"Completed all {total} development scenarios: "
            f"{_count_phrase(successes, 'scientific success', 'scientific successes')}, "
            f"{_count_phrase(failures, 'scientific failure', 'scientific failures')}, and "
            f"{_count_phrase(infrastructure, 'infrastructure error', 'infrastructure errors')}."
        )
    else:
        noun = "scenario" if completed == 1 else "scenarios"
        verb = "remains" if completed == 1 else "remain"
        message = (
            "Evaluation stopped before all scenarios finished; "
            f"{completed} completed {noun} {verb} available."
        )
    return EvaluationProgress(
        phase=status,
        message=message,
        completed_scenarios=completed,
        total_scenarios=total,
        scientific_successes=successes,
        scientific_failures=failures,
        infrastructure_errors=infrastructure,
    )


def assess_calibration(
    status: EvaluationStatus,
    attempts: tuple[EvaluationAttemptSummary, ...],
    scenario_ids: tuple[str, ...],
    scenario_levels: dict[str, CalibrationLevel],
    authenticated_scenarios: set[str],
) -> CalibrationAssessment:
    """Assess one fixed matrix without exposing scenario causal truth."""
    attempts_by_scenario = {attempt.scenario_id: attempt for attempt in attempts}
    level_outcomes: list[CalibrationLevelOutcome] = []
    for level, label, _stages in _CALIBRATION_LEVELS:
        level_scenarios = tuple(
            scenario_id
            for scenario_id in scenario_ids
            if scenario_levels[scenario_id] == level
        )
        completed = tuple(
            attempts_by_scenario[scenario_id]
            for scenario_id in level_scenarios
            if scenario_id in attempts_by_scenario
        )
        successes = sum(
            attempt.disposition == "scientific_success" for attempt in completed
        )
        failures = sum(
            attempt.disposition == "scientific_failure" for attempt in completed
        )
        infrastructure = sum(
            attempt.disposition == "infrastructure_error" for attempt in completed
        )
        level_outcomes.append(
            CalibrationLevelOutcome(
                level=level,
                label=label,
                total_scenarios=len(level_scenarios),
                completed_scenarios=len(completed),
                scientific_successes=successes,
                scientific_failures=failures,
                infrastructure_errors=infrastructure,
                has_success_and_failure=successes > 0 and failures > 0,
            )
        )

    scientific_successes = sum(
        attempt.disposition == "scientific_success" for attempt in attempts
    )
    scientific_failures = sum(
        attempt.disposition == "scientific_failure" for attempt in attempts
    )
    scientific_attempts = scientific_successes + scientific_failures
    scientific_accuracy = (
        scientific_successes / scientific_attempts if scientific_attempts else None
    )
    overall_in_target = (
        scientific_accuracy is not None and 0.2 <= scientific_accuracy <= 0.7
    )
    levels_mixed = (
        level_outcomes[1].has_success_and_failure
        and level_outcomes[2].has_success_and_failure
    )
    complete = status == "completed" and len(attempts) == len(scenario_ids)
    no_infrastructure = complete and all(
        attempt.disposition != "infrastructure_error" for attempt in attempts
    )
    authenticated_runtime = complete and authenticated_scenarios == set(scenario_ids)
    ready = (
        complete
        and overall_in_target
        and levels_mixed
        and no_infrastructure
        and authenticated_runtime
    )
    if not complete:
        assessment_status: CalibrationStatus = "pending"
        summary = "Readiness can be assessed after all development scenarios finish."
    elif ready:
        assessment_status = "ready"
        summary = (
            "The development run is within the target accuracy band, levels 1 and 2 "
            "both contain successes and failures, no infrastructure errors remain, "
            "and every row has authenticated local-runtime evidence."
        )
    else:
        assessment_status = "not_ready"
        summary = (
            "The development run does not yet satisfy every pre-training readiness "
            "criterion."
        )
    return CalibrationAssessment(
        status=assessment_status,
        summary=summary,
        scientific_accuracy=scientific_accuracy,
        overall_accuracy_in_target=overall_in_target,
        levels_1_and_2_mixed=levels_mixed,
        no_infrastructure_errors=no_infrastructure,
        authenticated_local_runtime=authenticated_runtime,
        levels=tuple(level_outcomes),
    )


def _count_phrase(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _bundle_digest(bundle: EnvironmentBundle) -> str:
    payload = json.dumps(
        bundle.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _incomplete_termination_reason(
    snapshot: RunSnapshot,
) -> IncompleteTerminationReason | None:
    result = snapshot.verifier_result
    if result is None:
        return None
    reason = result.evidence.get("termination_reason")
    if reason is None:
        return None
    allowed = {
        "model_ended_before_terminal",
        "turn_budget_exhausted",
        "tool_call_budget_exhausted",
        "output_budget_exhausted",
    }
    if not isinstance(reason, str) or reason not in allowed:
        raise EvaluationCoordinatorError(
            "the stored incomplete evaluation reason is invalid",
            code="internal",
        )
    return cast(IncompleteTerminationReason, reason)


def _coordinator_error(error: EvaluationRepositoryError) -> EvaluationCoordinatorError:
    if error.code == "not_found":
        code: Literal["conflict", "not_found", "internal"] = "not_found"
    elif error.code == "conflict":
        code = "conflict"
    else:
        code = "internal"
    return EvaluationCoordinatorError(str(error), code=code)


__all__ = [
    "AttemptDisposition",
    "assess_calibration",
    "CalibrationAssessment",
    "CalibrationLevelOutcome",
    "CalibrationStatus",
    "EvaluationAttemptSummary",
    "EvaluationCoordinator",
    "EvaluationCoordinatorError",
    "EvaluationPlan",
    "EvaluationProfile",
    "EvaluationProgress",
    "EvaluationReplay",
    "EvaluationReplayReport",
    "EvaluationRunner",
    "EvaluationRunnerFactory",
    "EvaluationSnapshot",
    "EvaluationSummary",
]
