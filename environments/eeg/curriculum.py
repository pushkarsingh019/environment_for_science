"""Training-safe, content-addressed access to the frozen EEG curriculum.

Only the training and development resources are packaged here. The held-out
loader, its nominal type, and cross-split release audit live in the evaluator
package, which is excluded from the training wheel.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from importlib.resources import files
from statistics import median
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from environments.eeg._curriculum_contract import (
    CANONICAL_OBJECTIVE,
    METRIC_DEFINITIONS,
)
from studio.bundle import EnvironmentBundle
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    IncompleteTerminationReason,
    RunSnapshot,
    RuntimeContractError,
)

CurriculumSplit = Literal["training", "development", "held_out"]
CurriculumStage = Literal[
    "marker_only",
    "nominal_orientation",
    "integration_preflight",
    "eeg_preflight",
    "ambiguity",
    "runtime_recovery",
    "compound_recovery",
]
ConsoleStage = Literal["preflight", "short_acquisition"]
ScenarioCategory = Literal["nominal", "individual", "ambiguous", "pair", "triple"]
HarnessErrorCategory = Literal["protocol", "schema", "timeout", "tool_execution"]
FaultFamily = Literal[
    "local_contact",
    "flatline_clipping",
    "reference_ground",
    "participant_artifact",
    "environmental_contamination",
    "duplicate_onset",
    "missing_onset",
    "visible_onset_cue",
    "response_mismatch",
    "recording_mismatch",
    "configuration_mismatch",
]

_PACKAGE_RESOURCES: dict[str, str] = {
    "training": "curriculum_training_v1.json",
    "development": "curriculum_development_v1.json",
}
_APPROVED_PACKAGE_DIGESTS = {
    "training": "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c",
    "development": "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197",
}
_APPROVED_RELEASE_CONTRACT_DIGEST = (
    "sha256:4c914bcb9774e967298048a00bb98e301578524495a5d8e54d56413f113c38ea"
)
_EXPECTED_COUNTS: dict[CurriculumSplit, int] = {
    "training": 96,
    "development": 32,
    "held_out": 64,
}
_EXPECTED_CATEGORY_COUNTS: dict[CurriculumSplit, dict[str, int]] = {
    "training": {
        "nominal": 8,
        "individual": 44,
        "ambiguous": 24,
        "pair": 20,
        "triple": 0,
    },
    "development": {
        "nominal": 4,
        "individual": 12,
        "ambiguous": 8,
        "pair": 8,
        "triple": 0,
    },
    "held_out": {
        "nominal": 8,
        "individual": 16,
        "ambiguous": 16,
        "pair": 16,
        "triple": 8,
    },
}
_EXPECTED_CROSS_CUTTING: dict[CurriculumSplit, dict[str, int]] = {
    "training": {
        "unavailable": 12,
        "runtime_onset": 24,
        "optional_transient": 4,
        "reserved_nuisance": 0,
    },
    "development": {
        "unavailable": 4,
        "runtime_onset": 8,
        "optional_transient": 2,
        "reserved_nuisance": 0,
    },
    "held_out": {
        "unavailable": 12,
        "runtime_onset": 16,
        "optional_transient": 8,
        "reserved_nuisance": 32,
    },
}
_FAULT_FAMILIES: tuple[FaultFamily, ...] = (
    "local_contact",
    "flatline_clipping",
    "reference_ground",
    "participant_artifact",
    "environmental_contamination",
    "duplicate_onset",
    "missing_onset",
    "visible_onset_cue",
    "response_mismatch",
    "recording_mismatch",
    "configuration_mismatch",
)
_AMBIGUITY_FAMILIES = (
    "widespread_noise",
    "quiet_channel",
    "unstable_channel",
    "flash_without_marker",
    "response_without_identity",
    "noisy_cap_site",
    "short_shared_transient",
)
_REWARD_COMPONENT_METRICS = (
    "terminal_correctness",
    "safety_compliance",
    "fresh_validation",
    "targeted_intervention",
    "data_stewardship",
    "efficiency",
)
_SUFFICIENT_STATISTIC_PAIRS = (
    ("invalid_continuation_fault_count", "runtime_fault_count"),
    ("pause_latency_observed", "runtime_fault_count"),
    ("first_intervention_relevant_count", "first_intervention_count"),
    ("recovery_success_count", "recoverable_scenario_count"),
    ("retested_remediation_count", "state_changing_remediation_count"),
    ("trace_frequency_supported_decision_count", "eeg_quality_decision_count"),
    ("annotated_invalid_runtime_duration", "invalid_runtime_duration"),
    ("overannotated_valid_runtime_duration", "valid_runtime_duration"),
    ("optional_channel_over_intervention_count", "optional_channel_scenario_count"),
    ("valid_close_count", "close_decision_count"),
)
_COUNT_METRICS = tuple(
    dict.fromkeys(
        (
            "invalid_start_or_resume_episode",
            "pause_latency_logical_events",
            "correct_terminal_count",
            "excess_intervention_count",
            "actions_to_correct_terminal",
            *(
                key
                for pair in _SUFFICIENT_STATISTIC_PAIRS
                for key in pair
            ),
        )
    )
)
class CurriculumContractError(ValueError):
    """A content-safe failure to load or audit a curriculum package."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CurriculumIdentity(_FrozenModel):
    release_id: str = Field(min_length=1)
    curriculum_revision: str = Field(min_length=1)
    split: CurriculumSplit
    package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ScenarioReference(_FrozenModel):
    """Non-causal scenario reference safe for a trusted harness catalog."""

    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    stage: CurriculumStage


class SeededScenarioChoice(_FrozenModel):
    """Neutral scenario choice safe to expose in the scientist console."""

    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    label: str = Field(min_length=1)
    stage: ConsoleStage


class PolicyScenarioInput(_FrozenModel):
    """The complete manifest projection allowed into training inputs."""

    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    objective: str = Field(min_length=1)


class HarnessErrorRecord(_FrozenModel):
    category: HarnessErrorCategory
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")


class CurriculumAttempt(_FrozenModel):
    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    rollout_index: int = Field(ge=0)
    model_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    run: RunSnapshot | None = None
    error: HarnessErrorRecord | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> CurriculumAttempt:
        if (self.run is None) == (self.error is None):
            raise ValueError("an attempt must contain exactly one run or harness error")
        if self.run is not None and self.run.scenario_id != self.scenario_id:
            raise ValueError("an attempt run does not match its scenario slot")
        return self


class _FaultOccurrence(_FrozenModel):
    occurrence_id: str = Field(pattern=r"^oc-[0-9a-f]{16}$")
    family: FaultFamily
    domain: Literal["configuration", "eeg", "onset", "response", "recording"]
    activation: Literal["preflight", "runtime"]
    activation_trial: int | None = Field(default=None, ge=1, le=2)
    visible_variant: str = Field(min_length=1)
    target: str = Field(min_length=1)
    inspection_actions: tuple[str, ...] = Field(min_length=1)
    recovery_ladder: tuple[str, ...] = Field(min_length=1)
    retest_action: str = Field(min_length=1)
    invalidates: tuple[
        Literal["configuration", "eeg", "onset", "response", "recording"], ...
    ] = Field(min_length=1)
    unavailable: bool

    @model_validator(mode="after")
    def validate_activation(self) -> _FaultOccurrence:
        if (self.activation == "runtime") != (self.activation_trial is not None):
            raise ValueError("only a runtime occurrence declares an activation trial")
        if len(self.inspection_actions) != len(set(self.inspection_actions)):
            raise ValueError("fault inspection actions must be unique")
        if len(self.invalidates) != len(set(self.invalidates)):
            raise ValueError("fault invalidation domains must be unique")
        return self


class _CurriculumScenarioRecord(_FrozenModel):
    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    blueprint_id: str = Field(pattern=r"^bp-[0-9a-f]{16}$")
    nuisance_id: str = Field(pattern=r"^nz-[0-9a-f]{16}$")
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=9_223_372_036_854_775_807)
    stage: CurriculumStage
    category: ScenarioCategory
    faults: tuple[FaultFamily, ...]
    occurrences: tuple[_FaultOccurrence, ...]
    ambiguity_family: str | None = Field(default=None, min_length=1)
    unavailable: bool
    unavailable_fault: FaultFamily | None
    unavailable_path: Literal["eeg", "onset", "response", "recording"] | None
    runtime_onset: bool
    optional_transient: bool
    negative_control_kind: Literal[
        "none", "optional_channel", "benign_transient", "benign_mimic"
    ]
    role_requirement: Literal["required", "optional", "not_applicable"]
    nuisance_family: Literal["familiar", "reserved"]
    episode_scope: Literal["preflight", "full"]

    @model_validator(mode="after")
    def validate_semantics(self) -> _CurriculumScenarioRecord:
        expected_fault_counts: dict[ScenarioCategory, set[int]] = {
            "nominal": {0},
            "individual": {1},
            "ambiguous": {0, 1},
            "pair": {2},
            "triple": {3},
        }
        if len(self.faults) not in expected_fault_counts[self.category]:
            raise ValueError("scenario category and causal component count disagree")
        if len(self.faults) != len(set(self.faults)):
            raise ValueError("causal component identities must be unique")
        if tuple(occurrence.family for occurrence in self.occurrences) != self.faults:
            raise ValueError("fault occurrences do not match causal components")
        if len({occurrence.occurrence_id for occurrence in self.occurrences}) != len(
            self.occurrences
        ):
            raise ValueError("fault occurrence identities must be unique")
        if (self.category == "ambiguous") != (self.ambiguity_family is not None):
            raise ValueError("only ambiguous scenarios declare an ambiguity family")
        if self.unavailable:
            if (
                self.unavailable_fault is None
                or self.unavailable_fault not in self.faults
                or self.unavailable_path is None
            ):
                raise ValueError("an unavailable scenario must identify one unavailable path")
        elif self.unavailable_fault is not None or self.unavailable_path is not None:
            raise ValueError("a recoverable scenario cannot identify an unavailable path")
        if self.optional_transient and (self.faults or self.unavailable):
            raise ValueError("an optional or benign transient cannot be a blocking fault")
        expected_role = (
            "optional"
            if self.negative_control_kind == "optional_channel"
            else (
                "not_applicable"
                if self.category == "nominal"
                and self.negative_control_kind == "none"
                else "required"
            )
        )
        if self.role_requirement != expected_role:
            raise ValueError("negative-control kind and role requirement disagree")
        if self.optional_transient != (
            self.negative_control_kind in {"optional_channel", "benign_transient"}
        ):
            raise ValueError("the combined negative-control quota marker disagrees")
        if self.runtime_onset and not self.faults:
            raise ValueError("a runtime onset requires a blocking causal component")
        runtime_occurrences = tuple(
            occurrence for occurrence in self.occurrences if occurrence.activation == "runtime"
        )
        if self.runtime_onset != (len(runtime_occurrences) == 1):
            raise ValueError("runtime onset must bind exactly one fault occurrence")
        if sum(occurrence.unavailable for occurrence in self.occurrences) != int(
            self.unavailable
        ):
            raise ValueError("unavailability must bind exactly one occurrence")
        if self.unavailable and not any(
            occurrence.family == self.unavailable_fault and occurrence.unavailable
            for occurrence in self.occurrences
        ):
            raise ValueError("the unavailable occurrence does not match the scenario path")
        expected_scope = (
            "full"
            if self.runtime_onset or self.category in {"pair", "triple"}
            else "preflight"
        )
        if self.episode_scope != expected_scope:
            raise ValueError("episode scope does not match the frozen curriculum stage")
        expected_digest = _digest(
            self.model_dump(mode="json", exclude={"manifest_digest"})
        )
        if self.manifest_digest != expected_digest:
            raise ValueError("scenario manifest digest mismatch")
        return self


class _CurriculumPackageDocument(_FrozenModel):
    package_revision: Literal["eeg-curriculum-package-1"]
    release_id: str = Field(min_length=1)
    curriculum_revision: str = Field(min_length=1)
    split: CurriculumSplit
    canonical_objective: str = Field(min_length=1)
    contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenarios: tuple[_CurriculumScenarioRecord, ...]
    seeded_examples: tuple[SeededScenarioChoice, ...] = ()

    @model_validator(mode="after")
    def validate_package(self) -> _CurriculumPackageDocument:
        if self.canonical_objective != CANONICAL_OBJECTIVE:
            raise ValueError("the canonical curriculum objective changed")
        if self.contract_digest != _APPROVED_RELEASE_CONTRACT_DIGEST:
            raise ValueError("the frozen curriculum contract changed")
        if len(self.scenarios) != _EXPECTED_COUNTS[self.split]:
            raise ValueError("scenario count does not match the frozen split")
        scenario_ids = [record.scenario_id for record in self.scenarios]
        blueprint_ids = [record.blueprint_id for record in self.scenarios]
        nuisance_ids = [record.nuisance_id for record in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario identities must be unique within a package")
        if len(blueprint_ids) != len(set(blueprint_ids)):
            raise ValueError("blueprint identities must be unique within a package")
        if len(nuisance_ids) != len(set(nuisance_ids)):
            raise ValueError("nuisance identities must be unique within a package")
        if any(example.scenario_id not in scenario_ids for example in self.seeded_examples):
            raise ValueError("a seeded example does not belong to its package")
        if self.split != "training" and self.seeded_examples:
            raise ValueError("only the training package can declare console examples")
        expected_digest = _digest(
            self.model_dump(mode="json", exclude={"package_digest"})
        )
        if self.package_digest != expected_digest:
            raise ValueError("curriculum package digest mismatch")
        return self


class CurriculumIntegrityReport(_FrozenModel):
    valid: Literal[True]
    release_id: str
    curriculum_revision: str
    release_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    split_counts: dict[str, int]
    category_counts: dict[str, dict[str, int]]
    cross_cutting_counts: dict[str, dict[str, int]]
    unavailable_path_counts: dict[str, dict[str, int]]
    identity_families_disjoint: Literal[True]
    combination_policy_valid: Literal[True]


class Rate(_FrozenModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_ratio(self) -> Rate:
        if self.numerator > self.denominator:
            raise ValueError("a rate numerator cannot exceed its denominator")
        expected = (
            self.numerator / self.denominator if self.denominator else None
        )
        if (self.value is None) != (expected is None) or (
            self.value is not None
            and expected is not None
            and not math.isclose(self.value, expected, rel_tol=0.0, abs_tol=1e-12)
        ):
            raise ValueError("a rate value does not match its counts")
        return self


class AbortMetrics(_FrozenModel):
    explicit_aborts: int = Field(ge=0)
    eligible_aborts: int = Field(ge=0)
    unavailable_attempts: int = Field(ge=0)
    non_unavailable_attempts: int = Field(ge=0)
    unnecessary_aborts: int = Field(ge=0)
    safe_abort_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    safe_abort_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    unnecessary_abort_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_abort_rates(self) -> AbortMetrics:
        if (
            self.eligible_aborts > self.explicit_aborts
            or self.eligible_aborts > self.unavailable_attempts
            or self.unnecessary_aborts > self.non_unavailable_attempts
        ):
            raise ValueError("abort metric counts are inconsistent")
        expected = (
            (
                self.safe_abort_precision,
                self.eligible_aborts / self.explicit_aborts
                if self.explicit_aborts
                else None,
            ),
            (
                self.safe_abort_recall,
                self.eligible_aborts / self.unavailable_attempts
                if self.unavailable_attempts
                else None,
            ),
            (
                self.unnecessary_abort_rate,
                self.unnecessary_aborts / self.non_unavailable_attempts
                if self.non_unavailable_attempts
                else None,
            ),
        )
        if any(not _optional_ratio_matches(actual, target) for actual, target in expected):
            raise ValueError("abort metric rates do not match their counts")
        return self


class StratumReport(_FrozenModel):
    count: int = Field(ge=0)
    mean_reward: float | None = Field(default=None, ge=0.0, le=1.0)
    exact_terminal_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_reward_components: dict[str, float | None]
    abort: AbortMetrics
    diagnostics: DiagnosticReport


class MetricDistribution(_FrozenModel):
    eligible_count: int = Field(ge=0)
    count: int = Field(ge=0)
    minimum: float | None = Field(default=None, ge=0.0)
    median: float | None = Field(default=None, ge=0.0)
    maximum: float | None = Field(default=None, ge=0.0)
    values: tuple[float, ...]

    @model_validator(mode="after")
    def validate_distribution(self) -> MetricDistribution:
        if (
            self.count != len(self.values)
            or self.count > self.eligible_count
            or any(not math.isfinite(value) or value < 0.0 for value in self.values)
            or tuple(sorted(self.values)) != self.values
        ):
            raise ValueError("diagnostic distribution counts or values are inconsistent")
        expected = (
            self.values[0] if self.values else None,
            float(median(self.values)) if self.values else None,
            self.values[-1] if self.values else None,
        )
        actual = (self.minimum, self.median, self.maximum)
        if any(
            not _optional_ratio_matches(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        ):
            raise ValueError("diagnostic distribution summaries are inconsistent")
        return self


class DiagnosticReport(_FrozenModel):
    invalid_start_or_resume_rate: Rate
    invalid_continuation_rate: Rate
    pause_latency_logical_events: MetricDistribution
    first_intervention_relevance: Rate
    recovery_success: Rate
    retest_coverage: Rate
    trace_frequency_inspection_rate: Rate
    annotation_coverage: Rate
    annotation_overreach: Rate
    optional_channel_over_intervention: Rate
    excess_intervention_count: MetricDistribution
    actions_to_correct_terminal: MetricDistribution


class CurriculumReport(_FrozenModel):
    claim_scope: Literal["within_eeg_compositional_generalization"]
    release_id: str
    curriculum_revision: str
    package_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    split: CurriculumSplit
    model_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evaluation_id: str | None = Field(
        default=None,
        pattern=r"^eeg-evaluation-[0-9a-f]{16}$",
    )
    attempt_ledger_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    attempted_runs: int = Field(ge=1)
    completed_runs: int = Field(ge=0)
    attempted_scenario_coverage: Rate
    scenario_coverage: Rate
    rollout_success: Rate
    mean_reward: float | None = Field(default=None, ge=0.0, le=1.0)
    exact_terminal_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_close_precision: Rate
    replay_conformance: Rate
    combination_generalization_gap: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
    )
    harness_errors: int = Field(ge=0)
    harness_errors_by_category: dict[HarnessErrorCategory, int]
    harness_error_rate: Rate
    mean_reward_components: dict[str, float | None]
    diagnostics: DiagnosticReport
    abort: AbortMetrics
    by_category: dict[str, StratumReport]
    by_fault_family: dict[str, StratumReport]
    by_lifecycle_onset: dict[str, StratumReport]
    by_role_requirement: dict[str, StratumReport]
    by_ambiguity_family: dict[str, StratumReport]
    by_nuisance_family: dict[str, StratumReport]
    by_combination_order: dict[str, StratumReport]

    @model_validator(mode="after")
    def validate_attempt_accounting(self) -> CurriculumReport:
        error_total = sum(self.harness_errors_by_category.values())
        has_ledger_provenance = (
            self.evaluation_id is not None and self.attempt_ledger_digest is not None
        )
        if (
            any(count <= 0 for count in self.harness_errors_by_category.values())
            or error_total != self.harness_errors
            or self.attempted_runs != self.completed_runs + self.harness_errors
            or self.rollout_success.numerator != self.completed_runs
            or self.rollout_success.denominator != self.attempted_runs
            or self.harness_error_rate.numerator != self.harness_errors
            or self.harness_error_rate.denominator != self.attempted_runs
            or self.attempted_scenario_coverage.denominator
            != self.scenario_coverage.denominator
            or (self.evaluation_id is None) != (self.attempt_ledger_digest is None)
            or (self.split == "held_out") != has_ledger_provenance
        ):
            raise ValueError("curriculum attempt accounting is inconsistent")
        return self


def _validate_attempt_ledger(
    attempts: Sequence[CurriculumAttempt],
    records: Mapping[str, _CurriculumScenarioRecord],
    *,
    require_complete: bool,
) -> tuple[tuple[CurriculumAttempt, ...], str]:
    raw_ledger = tuple(attempts)
    if not raw_ledger or any(
        not isinstance(attempt, CurriculumAttempt) for attempt in raw_ledger
    ):
        raise CurriculumContractError(
            "a curriculum report requires a typed, non-empty attempt ledger"
        )
    ledger = tuple(
        sorted(raw_ledger, key=lambda attempt: (attempt.scenario_id, attempt.rollout_index))
    )
    slots = {(attempt.scenario_id, attempt.rollout_index) for attempt in ledger}
    if len(slots) != len(ledger):
        raise CurriculumContractError("curriculum attempt slots must be unique")
    attempted_scenario_ids = {attempt.scenario_id for attempt in ledger}
    if not attempted_scenario_ids <= set(records):
        raise CurriculumContractError("curriculum attempt ledger contains an unknown scenario")
    model_configuration_digests = {
        attempt.model_configuration_digest for attempt in ledger
    }
    if len(model_configuration_digests) != 1:
        raise CurriculumContractError(
            "curriculum attempts must share one model configuration digest"
        )

    rollout_indices_by_scenario: dict[str, set[int]] = {}
    for attempt in ledger:
        rollout_indices_by_scenario.setdefault(attempt.scenario_id, set()).add(
            attempt.rollout_index
        )
    expected_indices: tuple[int, ...] | None = None
    for scenario_id in sorted(rollout_indices_by_scenario):
        indices = tuple(sorted(rollout_indices_by_scenario[scenario_id]))
        if indices != tuple(range(len(indices))):
            raise CurriculumContractError(
                "curriculum rollout indices must be contiguous and start at zero"
            )
        if expected_indices is None:
            expected_indices = indices
        elif indices != expected_indices:
            raise CurriculumContractError(
                "curriculum scenarios must have equal rollout coverage"
            )
    if require_complete and attempted_scenario_ids != set(records):
        raise CurriculumContractError(
            "a final report requires complete held-out attempt coverage"
        )
    return ledger, next(iter(model_configuration_digests))


class _ScenarioSet:
    """Shared implementation hidden behind purpose-specific nominal classes."""

    def __init__(self, package: _CurriculumPackageDocument) -> None:
        self._package = package
        self._bundle: EnvironmentBundle | None = None

    @property
    def identity(self) -> CurriculumIdentity:
        return CurriculumIdentity(
            release_id=self._package.release_id,
            curriculum_revision=self._package.curriculum_revision,
            split=self._package.split,
            package_digest=self._package.package_digest,
            contract_digest=self._package.contract_digest,
        )

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(record.scenario_id for record in self._package.scenarios)

    @property
    def catalog(self) -> tuple[ScenarioReference, ...]:
        return tuple(
            ScenarioReference(
                scenario_id=record.scenario_id,
                manifest_digest=record.manifest_digest,
                stage=record.stage,
            )
            for record in self._package.scenarios
        )

    @property
    def environment_bundle(self) -> EnvironmentBundle:
        if self._bundle is None:
            from environments.eeg._curriculum_bundle import (
                materialize_curriculum_bundle,
            )

            self._bundle = materialize_curriculum_bundle(
                self._package.model_dump(mode="json")
            )
        return self._bundle.model_copy(deep=True)

    def aggregate(
        self,
        attempts: Sequence[CurriculumAttempt],
    ) -> CurriculumReport:
        """Aggregate an immutable, package-bound scenario/rollout attempt ledger."""

        if self._package.split == "held_out":
            raise CurriculumContractError(
                "held-out reports require a persistent sealed attempt ledger"
            )
        return self._aggregate_attempts(attempts)

    def _aggregate_attempts(
        self,
        attempts: Sequence[CurriculumAttempt],
        *,
        evaluation_id: str | None = None,
        attempt_ledger_digest: str | None = None,
    ) -> CurriculumReport:
        """Trusted aggregation seam used by the evaluator-owned persistent ledger."""

        records = {record.scenario_id: record for record in self._package.scenarios}
        ledger, model_configuration_digest = _validate_attempt_ledger(
            attempts,
            records,
            require_complete=self._package.split == "held_out",
        )
        runs = tuple(attempt.run for attempt in ledger if attempt.run is not None)
        if len({run.run_id for run in runs}) != len(runs):
            raise CurriculumContractError("curriculum report contains a duplicate run")
        joined: list[tuple[RunSnapshot, _CurriculumScenarioRecord]] = []
        replay_runtime = _replay_runtime(self.environment_bundle)
        for run in runs:
            record = records.get(run.scenario_id)
            result = run.verifier_result
            if run.status != "completed" or result is None or record is None:
                raise CurriculumContractError(
                    "curriculum report received an incomplete or unknown run"
                )
            if run.trace_header.split != self._package.split:
                raise CurriculumContractError("curriculum run split provenance mismatch")
            canonical_incomplete = (
                result.outcome_category == "incomplete"
                and set(result.evidence) == {"termination_reason"}
                and result.evidence["termination_reason"]
                in {
                    "model_ended_before_terminal",
                    "output_budget_exhausted",
                    "turn_budget_exhausted",
                    "tool_call_budget_exhausted",
                }
            )
            if not canonical_incomplete and (
                result.evidence.get("curriculum_package_digest")
                != self._package.package_digest
                or result.outcome_category != record.category
            ):
                raise CurriculumContractError("curriculum run package provenance mismatch")
            _validate_run_integrity(run, replay_runtime)
            _atomic_metric(result.metrics, "reward")
            _atomic_metric(result.metrics, "terminal_correctness")
            _binary_metric(result.metrics, "exact_terminal_success")
            _atomic_metric(result.metrics, "explicit_abort")
            _atomic_metric(result.metrics, "eligible_safe_abort")
            for metric_name in METRIC_DEFINITIONS:
                _metric_value(result.metrics, metric_name)
            if canonical_incomplete:
                if any(
                    _metric_value(result.metrics, metric_name) != 0.0
                    for metric_name in METRIC_DEFINITIONS
                ):
                    raise CurriculumContractError(
                        "incomplete curriculum result contains scientific credit"
                    )
            else:
                _validate_sufficient_statistics(run, record)
            joined.append((run, record))

        scenario_ids = {run.scenario_id for run, _record in joined}
        attempted_scenario_ids = {attempt.scenario_id for attempt in ledger}

        rewards = [
            _atomic_metric(run.verifier_result.metrics, "reward")
            for run, _record in joined
            if run.verifier_result is not None
        ]
        exact = [
            _binary_metric(run.verifier_result.metrics, "exact_terminal_success")
            for run, _record in joined
            if run.verifier_result is not None
        ]
        abort_metrics = _abort_metrics(joined)
        by_category = _strata(
            joined,
            ("nominal", "individual", "ambiguous", "pair", "triple"),
            _category_labels,
        )
        by_fault_family = _strata(joined, _FAULT_FAMILIES, _fault_labels)
        by_lifecycle_onset = _strata(
            joined,
            ("preflight", "runtime"),
            _lifecycle_labels,
        )
        by_ambiguity_family = _strata(
            joined,
            _AMBIGUITY_FAMILIES,
            _ambiguity_labels,
        )
        by_role_requirement = _strata(
            joined,
            ("required", "optional", "not_applicable"),
            _role_requirement_labels,
        )
        by_nuisance_family = _strata(
            joined,
            ("familiar", "reserved"),
            _nuisance_labels,
        )
        by_combination_order = _strata(
            joined,
            tuple(str(order) for order in range(4)),
            _combination_order_labels,
        )
        close_decisions = _sum_count(joined, "close_decision_count")
        valid_closes = _sum_count(joined, "valid_close_count")
        mean_reward_components = _mean_reward_components(joined)
        diagnostics = _diagnostic_report(joined)
        individual_exact = by_category["individual"].exact_terminal_accuracy
        combination_runs = [
            _binary_metric(run.verifier_result.metrics, "exact_terminal_success")
            for run, record in joined
            if run.verifier_result is not None and record.category in {"pair", "triple"}
        ]
        combination_exact = _mean_or_none(combination_runs)
        combination_gap = (
            individual_exact - combination_exact
            if self._package.split == "held_out"
            and individual_exact is not None
            and combination_exact is not None
            else None
        )
        harness_error_categories: dict[HarnessErrorCategory, int] = {}
        for category in ("protocol", "schema", "timeout", "tool_execution"):
            count = sum(
                attempt.error is not None and attempt.error.category == category
                for attempt in ledger
            )
            if count:
                harness_error_categories[category] = count
        harness_errors = sum(harness_error_categories.values())
        total_attempts = len(ledger)
        return CurriculumReport(
            claim_scope="within_eeg_compositional_generalization",
            release_id=self._package.release_id,
            curriculum_revision=self._package.curriculum_revision,
            package_digest=self._package.package_digest,
            split=self._package.split,
            model_configuration_digest=model_configuration_digest,
            evaluation_id=evaluation_id,
            attempt_ledger_digest=attempt_ledger_digest,
            attempted_runs=total_attempts,
            completed_runs=len(joined),
            attempted_scenario_coverage=Rate(
                numerator=len(attempted_scenario_ids),
                denominator=len(records),
                value=len(attempted_scenario_ids) / len(records),
            ),
            scenario_coverage=Rate(
                numerator=len(scenario_ids),
                denominator=len(records),
                value=len(scenario_ids) / len(records),
            ),
            rollout_success=_rate(len(joined), total_attempts),
            mean_reward=_mean_or_none(rewards),
            exact_terminal_accuracy=_mean_or_none(exact),
            valid_close_precision=_rate(valid_closes, close_decisions),
            replay_conformance=Rate(
                numerator=len(joined),
                denominator=len(joined),
                value=1.0 if joined else None,
            ),
            combination_generalization_gap=combination_gap,
            harness_errors=harness_errors,
            harness_errors_by_category=harness_error_categories,
            harness_error_rate=Rate(
                numerator=harness_errors,
                denominator=total_attempts,
                value=harness_errors / total_attempts if total_attempts else None,
            ),
            mean_reward_components=mean_reward_components,
            diagnostics=diagnostics,
            abort=abort_metrics,
            by_category=by_category,
            by_fault_family=by_fault_family,
            by_lifecycle_onset=by_lifecycle_onset,
            by_role_requirement=by_role_requirement,
            by_ambiguity_family=by_ambiguity_family,
            by_nuisance_family=by_nuisance_family,
            by_combination_order=by_combination_order,
        )


class TrainingScenarioSet(_ScenarioSet):
    """Only the frozen 96-row optimization package."""

    @property
    def seeded_examples(self) -> tuple[SeededScenarioChoice, ...]:
        return tuple(item.model_copy(deep=True) for item in self._package.seeded_examples)

    def training_inputs(self) -> tuple[PolicyScenarioInput, ...]:
        return tuple(
            PolicyScenarioInput(
                scenario_id=record.scenario_id,
                objective=self._package.canonical_objective,
            )
            for record in self._package.scenarios
        )

    def training_artifact_bytes(self) -> bytes:
        document = {
            "artifact_revision": "eeg-policy-inputs-1",
            "curriculum_revision": self._package.curriculum_revision,
            "package_digest": self._package.package_digest,
            "scenario_count": len(self._package.scenarios),
            "scenarios": [item.model_dump(mode="json") for item in self.training_inputs()],
        }
        return _canonical_bytes(document)


class DevelopmentScenarioSet(_ScenarioSet):
    """Only the frozen 32-row tuning package."""


def load_training_scenario_set(
    document: Mapping[str, Any] | bytes | str | None = None,
) -> TrainingScenarioSet:
    return TrainingScenarioSet(_load_package("training", document))


def load_development_scenario_set(
    document: Mapping[str, Any] | bytes | str | None = None,
) -> DevelopmentScenarioSet:
    return DevelopmentScenarioSet(_load_package("development", document))


def _load_package(
    split: CurriculumSplit,
    document: Mapping[str, Any] | bytes | str | None,
    *,
    approved_digest: str | None = None,
) -> _CurriculumPackageDocument:
    expected_digest = _APPROVED_PACKAGE_DIGESTS.get(split, approved_digest)
    if expected_digest is None:
        raise CurriculumContractError(
            "an evaluator-owned package requires an approved release receipt"
        )
    try:
        if document is None:
            resource_name = _PACKAGE_RESOURCES.get(split)
            if resource_name is None:
                raise ValueError("the evaluator-owned package is not a training resource")
            resource = files("environments.eeg").joinpath(resource_name)
            package = _CurriculumPackageDocument.model_validate_json(resource.read_bytes())
        elif isinstance(document, Mapping):
            package = _CurriculumPackageDocument.model_validate(document)
        else:
            package = _CurriculumPackageDocument.model_validate_json(document)
    except (OSError, ValidationError, ValueError) as error:
        raise CurriculumContractError(
            f"the {split} EEG curriculum package failed integrity validation"
        ) from error
    if package.split != split:
        raise CurriculumContractError("the EEG curriculum package has the wrong purpose")
    if package.package_digest != expected_digest:
        raise CurriculumContractError(
            "the EEG curriculum package is not the approved frozen release"
        )
    return package


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _replay_runtime(bundle: EnvironmentBundle) -> EnvironmentRuntime:
    from environments.eeg.runtime import EegEnvironmentModule

    return EnvironmentRuntime(EegEnvironmentModule(bundle.model_copy(deep=True)))


def _validate_run_integrity(
    run: RunSnapshot,
    runtime: EnvironmentRuntime,
) -> None:
    result = run.verifier_result
    if (
        run.status != "completed"
        or result is None
        or run.result_digest is None
        or not run.trace
        or run.trace[-1].type != "verifier"
        or run.trace[-1].verifier
        != result.model_dump(mode="json", exclude_none=True)
        or run.scenario_id != run.trace_header.scenario_id
        or run.revision_digest != run.trace_header.revision_digest
        or run.scenario_digest != run.trace_header.scenario_digest
        or run.policy_agent != run.trace_header.policy_agent
    ):
        raise CurriculumContractError("curriculum run integrity validation failed")
    latest_observation = next(
        (
            event.observation
            for event in reversed(run.trace)
            if event.type == "observation" and event.observation is not None
        ),
        None,
    )
    if latest_observation != run.observation:
        raise CurriculumContractError("curriculum run integrity validation failed")

    try:
        replayed = runtime.start(run.scenario_id, run.policy_agent)
        for event in run.trace:
            if event.type == "action" and event.action is not None:
                replayed = runtime.apply_action(
                    replayed.run_id,
                    EnvironmentAction.model_validate(event.action),
                )
        if result.outcome_category == "incomplete":
            replayed = runtime.finalize_incomplete(
                replayed.run_id,
                termination_reason=cast(
                    IncompleteTerminationReason,
                    result.evidence["termination_reason"],
                ),
            )
        else:
            replayed = runtime.verify(replayed.run_id)
    except (RuntimeContractError, ValidationError, ValueError) as error:
        raise CurriculumContractError("curriculum run replay validation failed") from error
    if (
        replayed.trace_header != run.trace_header
        or replayed.trace != run.trace
        or replayed.trace_digest != run.trace_digest
        or replayed.verifier_result != run.verifier_result
        or replayed.result_digest != run.result_digest
        or replayed.observation != run.observation
    ):
        raise CurriculumContractError("curriculum run replay validation failed")


def _stratum(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
    predicate: Callable[[_CurriculumScenarioRecord], bool],
) -> StratumReport:
    selected_pairs = tuple((run, record) for run, record in joined if predicate(record))
    selected = [run for run, _record in selected_pairs]
    rewards = [
        _atomic_metric(run.verifier_result.metrics, "reward")
        for run in selected
        if run.verifier_result is not None
    ]
    exact = [
        _binary_metric(run.verifier_result.metrics, "exact_terminal_success")
        for run in selected
        if run.verifier_result is not None
    ]
    return StratumReport(
        count=len(selected),
        mean_reward=_mean_or_none(rewards),
        exact_terminal_accuracy=_mean_or_none(exact),
        mean_reward_components=_mean_reward_components(selected_pairs),
        abort=_abort_metrics(selected_pairs),
        diagnostics=_diagnostic_report(selected_pairs),
    )


def _strata(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
    labels: Sequence[str],
    labeler: Callable[[_CurriculumScenarioRecord], Sequence[str]],
) -> dict[str, StratumReport]:
    return {
        label: _stratum(
            joined,
            partial(_record_has_label, labeler=labeler, label=label),
        )
        for label in labels
    }


def _record_has_label(
    record: _CurriculumScenarioRecord,
    *,
    labeler: Callable[[_CurriculumScenarioRecord], Sequence[str]],
    label: str,
) -> bool:
    return label in labeler(record)


def _category_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return (record.category,)


def _fault_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return record.faults


def _lifecycle_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return ("runtime" if record.runtime_onset else "preflight",)


def _ambiguity_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return (record.ambiguity_family,) if record.ambiguity_family is not None else ()


def _role_requirement_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return (record.role_requirement,)


def _nuisance_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return (record.nuisance_family,)


def _combination_order_labels(record: _CurriculumScenarioRecord) -> Sequence[str]:
    return (str(len(record.faults)),)


def _metric_value(metrics: Mapping[str, float], key: str) -> float:
    value = metrics.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0.0
    ):
        raise CurriculumContractError(f"curriculum run has no valid {key} metric")
    return float(value)


def _atomic_metric(metrics: Mapping[str, float], key: str) -> float:
    value = _metric_value(metrics, key)
    if value > 1.0:
        raise CurriculumContractError(f"curriculum run has no valid {key} metric")
    return value


def _binary_metric(metrics: Mapping[str, float], key: str) -> float:
    value = _atomic_metric(metrics, key)
    if value not in {0.0, 1.0}:
        raise CurriculumContractError(f"curriculum run has no binary {key} metric")
    return value


def _mean_or_none(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _optional_ratio_matches(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)


def _mean_reward_components(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
) -> dict[str, float | None]:
    return {
        key: _mean_or_none(
            [
                _atomic_metric(run.verifier_result.metrics, key)
                for run, _record in joined
                if run.verifier_result is not None
            ]
        )
        for key in _REWARD_COMPONENT_METRICS
    }


def _validate_sufficient_statistics(
    run: RunSnapshot,
    record: _CurriculumScenarioRecord,
) -> None:
    result = run.verifier_result
    if result is None:
        raise CurriculumContractError("curriculum run has no verifier statistics")
    metrics = result.metrics
    for key in _COUNT_METRICS:
        _count_metric(metrics, key)
    for numerator_key, denominator_key in _SUFFICIENT_STATISTIC_PAIRS:
        numerator = _count_metric(metrics, numerator_key)
        denominator = _count_metric(metrics, denominator_key)
        if numerator > denominator:
            raise CurriculumContractError(
                "curriculum run has inconsistent sufficient statistics"
            )

    expected_recoverable = int(bool(record.faults) and not record.unavailable)
    expected_optional = int(record.negative_control_kind == "optional_channel")
    explicit_abort = int(_binary_metric(metrics, "explicit_abort"))
    eligible_abort = int(_binary_metric(metrics, "eligible_safe_abort"))
    exact_success = int(_binary_metric(metrics, "exact_terminal_success"))
    valid_close = int(_binary_metric(metrics, "valid_close"))
    close_actions = sum(
        event.type == "action"
        and event.action is not None
        and event.action.get("type") in {"complete_preflight", "close_acquisition"}
        for event in run.trace
    )
    if (
        _count_metric(metrics, "runtime_fault_count") > int(record.runtime_onset)
        or _count_metric(metrics, "recoverable_scenario_count") != expected_recoverable
        or _count_metric(metrics, "optional_channel_scenario_count")
        != expected_optional
        or int(_binary_metric(metrics, "unavailable_scenario"))
        != int(record.unavailable)
        or eligible_abort > explicit_abort
        or eligible_abort > int(record.unavailable)
        or _count_metric(metrics, "valid_close_count") != valid_close
        or exact_success != int(valid_close == 1 or eligible_abort == 1)
        or _count_metric(metrics, "correct_terminal_count")
        != exact_success
        or _count_metric(metrics, "close_decision_count") != close_actions
    ):
        raise CurriculumContractError(
            "curriculum run sufficient statistics disagree with provenance"
        )


def _diagnostic_report(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
) -> DiagnosticReport:
    invalid_start_or_resume = sum(
        int(_binary_metric(run.verifier_result.metrics, "invalid_start_or_resume_episode"))
        for run, _record in joined
        if run.verifier_result is not None
    )
    pause_eligible = _sum_count(joined, "runtime_fault_count")
    pause_values = [
        _metric_value(run.verifier_result.metrics, "pause_latency_logical_events")
        for run, _record in joined
        if run.verifier_result is not None
        and _binary_metric(run.verifier_result.metrics, "pause_latency_observed") == 1.0
    ]
    correct_terminal_count = _sum_count(joined, "correct_terminal_count")
    actions_to_terminal = [
        _metric_value(run.verifier_result.metrics, "actions_to_correct_terminal")
        for run, _record in joined
        if run.verifier_result is not None
        and _binary_metric(run.verifier_result.metrics, "correct_terminal_count") == 1.0
    ]
    return DiagnosticReport(
        invalid_start_or_resume_rate=_rate(invalid_start_or_resume, len(joined)),
        invalid_continuation_rate=_metric_rate(
            joined,
            numerator="invalid_continuation_fault_count",
            denominator="runtime_fault_count",
        ),
        pause_latency_logical_events=_distribution(
            pause_values,
            eligible_count=pause_eligible,
        ),
        first_intervention_relevance=_metric_rate(
            joined,
            numerator="first_intervention_relevant_count",
            denominator="first_intervention_count",
        ),
        recovery_success=_metric_rate(
            joined,
            numerator="recovery_success_count",
            denominator="recoverable_scenario_count",
        ),
        retest_coverage=_metric_rate(
            joined,
            numerator="retested_remediation_count",
            denominator="state_changing_remediation_count",
        ),
        trace_frequency_inspection_rate=_metric_rate(
            joined,
            numerator="trace_frequency_supported_decision_count",
            denominator="eeg_quality_decision_count",
        ),
        annotation_coverage=_metric_rate(
            joined,
            numerator="annotated_invalid_runtime_duration",
            denominator="invalid_runtime_duration",
        ),
        annotation_overreach=_metric_rate(
            joined,
            numerator="overannotated_valid_runtime_duration",
            denominator="valid_runtime_duration",
        ),
        optional_channel_over_intervention=_metric_rate(
            joined,
            numerator="optional_channel_over_intervention_count",
            denominator="optional_channel_scenario_count",
        ),
        excess_intervention_count=_distribution(
            [
                _metric_value(run.verifier_result.metrics, "excess_intervention_count")
                for run, _record in joined
                if run.verifier_result is not None
            ],
            eligible_count=len(joined),
        ),
        actions_to_correct_terminal=_distribution(
            actions_to_terminal,
            eligible_count=correct_terminal_count,
        ),
    )


def _metric_rate(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
    *,
    numerator: str,
    denominator: str,
) -> Rate:
    pairs = tuple(
        (
            _count_metric(run.verifier_result.metrics, numerator),
            _count_metric(run.verifier_result.metrics, denominator),
        )
        for run, _record in joined
        if run.verifier_result is not None
    )
    if any(numerator_value > denominator_value for numerator_value, denominator_value in pairs):
        raise CurriculumContractError("curriculum diagnostic counts are inconsistent")
    return _rate(
        sum(numerator_value for numerator_value, _denominator_value in pairs),
        sum(denominator_value for _numerator_value, denominator_value in pairs),
    )


def _sum_count(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
    key: str,
) -> int:
    return sum(
        _count_metric(run.verifier_result.metrics, key)
        for run, _record in joined
        if run.verifier_result is not None
    )


def _count_metric(metrics: Mapping[str, float], key: str) -> int:
    value = _metric_value(metrics, key)
    if not value.is_integer():
        raise CurriculumContractError(f"curriculum run has no integral {key} metric")
    return int(value)


def _rate(numerator: int, denominator: int) -> Rate:
    if numerator > denominator:
        raise CurriculumContractError("curriculum diagnostic counts are inconsistent")
    return Rate(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
    )


def _distribution(
    values: Sequence[float],
    *,
    eligible_count: int,
) -> MetricDistribution:
    ordered = tuple(sorted(values))
    if len(ordered) > eligible_count:
        raise CurriculumContractError("curriculum diagnostic distribution is inconsistent")
    return MetricDistribution(
        eligible_count=eligible_count,
        count=len(ordered),
        minimum=ordered[0] if ordered else None,
        median=float(median(ordered)) if ordered else None,
        maximum=ordered[-1] if ordered else None,
        values=ordered,
    )


def _abort_metrics(
    joined: Sequence[tuple[RunSnapshot, _CurriculumScenarioRecord]],
) -> AbortMetrics:
    explicit = sum(
        int(_binary_metric(run.verifier_result.metrics, "explicit_abort"))
        for run, _record in joined
        if run.verifier_result is not None
    )
    eligible = sum(
        int(_binary_metric(run.verifier_result.metrics, "eligible_safe_abort"))
        for run, _record in joined
        if run.verifier_result is not None
    )
    unavailable_attempts = sum(record.unavailable for _run, record in joined)
    non_unavailable_attempts = sum(not record.unavailable for _run, record in joined)
    unnecessary_aborts = sum(
        bool(
            run.verifier_result is not None
            and _binary_metric(run.verifier_result.metrics, "explicit_abort")
        )
        and not record.unavailable
        for run, record in joined
    )
    if eligible > explicit or eligible > unavailable_attempts:
        raise CurriculumContractError("curriculum abort metrics are inconsistent")
    return AbortMetrics(
        explicit_aborts=explicit,
        eligible_aborts=eligible,
        unavailable_attempts=unavailable_attempts,
        non_unavailable_attempts=non_unavailable_attempts,
        unnecessary_aborts=unnecessary_aborts,
        safe_abort_precision=eligible / explicit if explicit else None,
        safe_abort_recall=(
            eligible / unavailable_attempts if unavailable_attempts else None
        ),
        unnecessary_abort_rate=(
            unnecessary_aborts / non_unavailable_attempts
            if non_unavailable_attempts
            else None
        ),
    )


__all__ = [
    "AbortMetrics",
    "CurriculumContractError",
    "CurriculumAttempt",
    "ConsoleStage",
    "CurriculumIdentity",
    "CurriculumIntegrityReport",
    "CurriculumReport",
    "CurriculumStage",
    "DevelopmentScenarioSet",
    "DiagnosticReport",
    "HarnessErrorCategory",
    "HarnessErrorRecord",
    "MetricDistribution",
    "PolicyScenarioInput",
    "ScenarioReference",
    "SeededScenarioChoice",
    "TrainingScenarioSet",
    "Rate",
    "StratumReport",
    "load_development_scenario_set",
    "load_training_scenario_set",
]
