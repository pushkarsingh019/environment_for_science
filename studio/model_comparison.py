"""Scientifically constrained four-model comparison and offline fixture index."""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .curriculum_analysis import (
    HeldOutEvaluationEvidence,
    PairedBootstrapAnalysis,
    paired_bootstrap_success,
)
from .runtime import RunSnapshot, validate_completed_run_snapshot

if TYPE_CHECKING:
    from evaluation.eeg.curriculum import HeldOutScenarioSet


def _heldout_scenario_set() -> HeldOutScenarioSet:
    from evaluation.eeg.curriculum import load_held_out_scenario_set

    return load_held_out_scenario_set()


FixtureState = Literal[
    "successful",
    "inconclusive",
    "regressed",
    "partially_unavailable",
    "adapter_error",
]
ModelRole = Literal[
    "base_gemma",
    "trained_gemma",
    "openai_reference",
    "gemini_reference",
]
ModelResultStatus = Literal[
    "available",
    "credential_missing",
    "provider_failure",
    "adapter_failure",
    "scientific_failure",
]


class ComparisonIndexError(ValueError):
    def __init__(self, message: str, *, code: Literal["not_found", "storage"]):
        super().__init__(message)
        self.code = code


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ComparisonFailure(_FrozenModel):
    category: Literal["credential", "provider", "adapter", "scientific"]
    summary: str = Field(min_length=1)


class ScenarioResultLink(_FrozenModel):
    scenario_id: str = Field(pattern=r"^eeg-[0-9a-f]{16}$")
    run_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,100}$")
    runtime_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    success: bool
    verifier_score: float = Field(ge=0.0, le=1.0)
    replay_route: str = Field(
        pattern=(
            r"^/api/model-comparison/replays/"
            r"(base_gemma|trained_gemma|openai_reference|gemini_reference)/"
            r"eeg-[0-9a-f]{16}$"
        )
    )


class ComparisonStratum(_FrozenModel):
    count: int = Field(ge=0)
    task_success: float | None = Field(default=None, ge=0.0, le=1.0)
    verifier_score: float | None = Field(default=None, ge=0.0, le=1.0)


class ComparisonMetrics(_FrozenModel):
    scenario_count: int = Field(ge=1)
    task_success: float = Field(ge=0.0, le=1.0)
    verifier_score: float = Field(ge=0.0, le=1.0)
    abort_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    abort_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_action_count: float = Field(ge=0.0)
    tool_errors: int = Field(ge=0)
    strata: dict[
        Literal["individual", "ambiguous", "pair", "triple"],
        ComparisonStratum,
    ]


class ComparisonModelResult(_FrozenModel):
    role: ModelRole
    label: str = Field(min_length=1)
    reference_model: bool
    requested_model: str = Field(min_length=1)
    returned_model: str | None = Field(default=None, min_length=1)
    adapter_identity: str | None = Field(default=None, min_length=1)
    adapter_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    model_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    run_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,100}$")
    status: ModelResultStatus
    metrics: ComparisonMetrics | None
    failure: ComparisonFailure | None
    scenarios: tuple[ScenarioResultLink, ...]

    @model_validator(mode="after")
    def validate_availability(self) -> ComparisonModelResult:
        available = self.status == "available"
        if (
            available != (self.metrics is not None)
            or available != (self.failure is None)
            or available != bool(self.scenarios)
            or self.reference_model
            != (self.role in {"openai_reference", "gemini_reference"})
            or (self.adapter_identity is None) != (self.adapter_digest is None)
            or (
                self.metrics is not None
                and self.metrics.scenario_count != len(self.scenarios)
            )
        ):
            raise ValueError("model result availability or role is inconsistent")
        return self


class ComparisonProvenance(_FrozenModel):
    scenario_manifest_id: Literal["eeg-curriculum-release-1:held_out"]
    scenario_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    environment_bundle_id: Literal["eeg-curriculum"]
    environment_bundle_revision: Literal["1.4.0"]
    scoring_revision: Literal["eeg-curriculum-scorer-1"]


    @model_validator(mode="after")
    def validate_manifest(self) -> ComparisonProvenance:
        if self.scenario_manifest_digest != _heldout_scenario_set().identity.package_digest:
            raise ValueError("comparison scenario manifest provenance is invalid")
        return self


class MesoscopeGeneralityTrack(_FrozenModel):
    claim_scope: Literal["platform_generality"]
    label: Literal["Separate mesoscope platform-generality evidence"]
    compiler_route: Literal["/api/platform-evidence/mesoscope"]
    replay_route: Literal["/api/platform-evidence/mesoscope/replay"]
    eeg_training_evidence: Literal[False]


class ModelComparisonResult(_FrozenModel):
    comparison_version: Literal["scientist-model-comparison/1"]
    comparison_id: str = Field(pattern=r"^model-comparison-[a-z0-9-]{8,80}$")
    source: Literal["seeded_offline_fixture", "real_evaluation"]
    fixture_state: FixtureState | None
    fixture_notice: str | None
    claim_scope: Literal["within_eeg_compositional_generalization"]
    training_result_id: str | None = Field(
        default=None,
        pattern=r"^eeg-training-result-[a-z0-9]{8,64}$",
    )
    training_artifact_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    provenance: ComparisonProvenance
    models: tuple[ComparisonModelResult, ...] = Field(min_length=4, max_length=4)
    gemma_contrast: PairedBootstrapAnalysis | None
    training_claim: Literal["improved", "inconclusive", "regressed", "unavailable"]
    mesoscope: MesoscopeGeneralityTrack

    @model_validator(mode="after")
    def validate_comparison_claims(self) -> ModelComparisonResult:
        roles = tuple(model.role for model in self.models)
        expected_roles: tuple[ModelRole, ...] = (
            "base_gemma",
            "trained_gemma",
            "openai_reference",
            "gemini_reference",
        )
        base, trained = self.models[:2]
        contrast_available = (
            base.status == "available" and trained.status == "available"
        )
        expected_claim = (
            self.gemma_contrast.conclusion
            if self.gemma_contrast is not None
            else "unavailable"
        )
        if (
            roles != expected_roles
            or contrast_available != (self.gemma_contrast is not None)
            or self.training_claim != expected_claim
            or (self.source == "seeded_offline_fixture")
            != (self.fixture_state is not None and self.fixture_notice is not None)
            or (self.source == "real_evaluation")
            != (
                self.training_result_id is not None
                and self.training_artifact_digest is not None
            )
            or self.mesoscope.eeg_training_evidence is not False
        ):
            raise ValueError("comparison provenance or claim rule is inconsistent")
        return self


class ComparisonReplay(_FrozenModel):
    replay_version: Literal["scientist-model-comparison-replay/1"]
    source: Literal["seeded_offline_fixture", "real_evaluation"]
    provenance: ComparisonProvenance
    model_role: ModelRole
    model_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    adapter_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    training_artifact_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    scenario: ScenarioResultLink
    reproducible: bool
    canonical_snapshot: RunSnapshot | None

    @model_validator(mode="after")
    def validate_replay_source(self) -> ComparisonReplay:
        is_real = self.source == "real_evaluation"
        if is_real != self.reproducible or is_real != (self.canonical_snapshot is not None):
            raise ValueError("comparison replay source is inconsistent")
        return self


class ModelComparisonRepository:
    """Persist fixture selection and immutable real results without deleting either."""

    def __init__(self, artifact_root: Path) -> None:
        self._root = artifact_root.expanduser().resolve()
        self._database = self._root / "model-comparisons.sqlite3"
        self._lock = RLock()
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._root, 0o700)
            self._prepare()
        except (OSError, sqlite3.Error) as error:
            raise ComparisonIndexError(
                "the model comparison index could not be opened",
                code="storage",
            ) from error

    def current(self) -> ModelComparisonResult:
        try:
            with self._lock, closing(self._connect()) as connection:
                state = connection.execute(
                    """
                    SELECT mode, fixture_state, real_result_id
                    FROM comparison_state
                    WHERE singleton = 1
                    """
                ).fetchone()
                if state is None:
                    raise ValueError("missing comparison state")
                if state[0] == "fixture":
                    return seeded_comparison(state[1])
                row = connection.execute(
                    "SELECT result_json, result_digest FROM real_results WHERE result_id = ?",
                    (state[2],),
                ).fetchone()
                if row is None or _digest_bytes(row[0].encode()) != row[1]:
                    raise ValueError("real comparison integrity failure")
                return ModelComparisonResult.model_validate_json(row[0])
        except (sqlite3.Error, ValueError) as error:
            raise ComparisonIndexError(
                "the model comparison index failed integrity validation",
                code="storage",
            ) from error

    def select_fixture(self, state: FixtureState) -> ModelComparisonResult:
        result = seeded_comparison(state)
        try:
            with self._lock, closing(self._connect()) as connection:
                connection.execute(
                    """
                    UPDATE comparison_state
                    SET mode = 'fixture', fixture_state = ?, real_result_id = NULL
                    WHERE singleton = 1
                    """,
                    (state,),
                )
                connection.commit()
            return result
        except sqlite3.Error as error:
            raise ComparisonIndexError(
                "the model comparison fixture could not be selected",
                code="storage",
            ) from error

    def install_real(
        self,
        result: ModelComparisonResult,
        *,
        base_ledger_root: Path,
        trained_ledger_root: Path,
    ) -> ModelComparisonResult:
        if result.source != "real_evaluation":
            raise ValueError("only real comparison evidence can enter the immutable index")
        try:
            base_evidence, base_snapshots = _evidence_from_evaluator_ledger(
                base_ledger_root,
                result.models[0].model_configuration_digest,
            )
            trained_evidence, trained_snapshots = _evidence_from_evaluator_ledger(
                trained_ledger_root,
                result.models[1].model_configuration_digest,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            raise ValueError(
                "real comparison requires complete sealed evaluator ledgers"
            ) from error
        expected_models = (
            _real_gemma_model(
                "base_gemma",
                base_evidence,
                adapter_identity=None,
                adapter_digest=None,
            ),
            _real_gemma_model(
                "trained_gemma",
                trained_evidence,
                adapter_identity=result.models[1].adapter_identity,
                adapter_digest=result.models[1].adapter_digest,
            ),
        )
        expected_contrast = paired_bootstrap_success(
            base_evidence.scenario_success,
            trained_evidence.scenario_success,
        )
        if (
            not all(
                _gemma_model_matches(observed, expected)
                for observed, expected in zip(result.models[:2], expected_models)
            )
            or result.gemma_contrast != expected_contrast
            or result.training_claim != expected_contrast.conclusion
        ):
            raise ValueError(
                "real comparison does not match its sealed evaluator ledgers"
            )
        payload = result.model_dump_json()
        digest = _digest_bytes(payload.encode())
        replay_sources: tuple[
            tuple[
                Literal["base_gemma", "trained_gemma"],
                dict[str, RunSnapshot],
            ],
            ...,
        ] = (
            ("base_gemma", base_snapshots),
            ("trained_gemma", trained_snapshots),
        )
        replay_rows = tuple(
            _replay_row(result.comparison_id, role, snapshot)
            for role, snapshots in replay_sources
            for snapshot in snapshots.values()
        )
        try:
            with self._lock, closing(self._connect()) as connection:
                existing = connection.execute(
                    "SELECT result_digest FROM real_results WHERE result_id = ?",
                    (result.comparison_id,),
                ).fetchone()
                if existing is not None and existing[0] != digest:
                    raise ValueError("real comparison identity is immutable")
                for row in replay_rows:
                    replay = connection.execute(
                        """
                        SELECT snapshot_digest FROM real_replays
                        WHERE result_id = ? AND model_role = ? AND scenario_id = ?
                        """,
                        row[:3],
                    ).fetchone()
                    if replay is not None and replay[0] != row[4]:
                        raise ValueError("real comparison replay identity is immutable")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO real_results(
                        result_id, result_json, result_digest
                    ) VALUES (?, ?, ?)
                    """,
                    (result.comparison_id, payload, digest),
                )
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO real_replays(
                        result_id, model_role, scenario_id,
                        snapshot_json, snapshot_digest
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    replay_rows,
                )
                connection.execute(
                    """
                    UPDATE comparison_state
                    SET mode = 'real', fixture_state = NULL, real_result_id = ?
                    WHERE singleton = 1
                    """,
                    (result.comparison_id,),
                )
                connection.commit()
            return result
        except sqlite3.Error as error:
            raise ComparisonIndexError(
                "the real model comparison could not be installed",
                code="storage",
            ) from error

    def reset_demo(self) -> ModelComparisonResult:
        return self.select_fixture("successful")

    def real_result_count(self) -> int:
        try:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute("SELECT COUNT(*) FROM real_results").fetchone()
            if row is None:
                raise ValueError("missing real comparison count")
            return int(row[0])
        except (sqlite3.Error, ValueError) as error:
            raise ComparisonIndexError(
                "the model comparison index could not count real results",
                code="storage",
            ) from error

    def replay(self, role: ModelRole, scenario_id: str) -> ComparisonReplay:
        result = self.current()
        model = next((item for item in result.models if item.role == role), None)
        scenario = (
            next(
                (item for item in model.scenarios if item.scenario_id == scenario_id),
                None,
            )
            if model is not None
            else None
        )
        if model is None or scenario is None:
            raise ComparisonIndexError(
                "comparison replay was not found",
                code="not_found",
            )
        canonical_snapshot = (
            self._real_snapshot(result.comparison_id, role, scenario)
            if result.source == "real_evaluation"
            else None
        )
        return ComparisonReplay(
            replay_version="scientist-model-comparison-replay/1",
            source=result.source,
            provenance=result.provenance,
            model_role=role,
            model_configuration_digest=model.model_configuration_digest,
            adapter_digest=model.adapter_digest,
            training_artifact_digest=result.training_artifact_digest,
            scenario=scenario,
            reproducible=canonical_snapshot is not None,
            canonical_snapshot=canonical_snapshot,
        )

    def _real_snapshot(
        self,
        result_id: str,
        role: ModelRole,
        scenario: ScenarioResultLink,
    ) -> RunSnapshot:
        try:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT snapshot_json, snapshot_digest
                    FROM real_replays
                    WHERE result_id = ? AND model_role = ? AND scenario_id = ?
                    """,
                    (result_id, role, scenario.scenario_id),
                ).fetchone()
            if row is None or _digest_bytes(row[0].encode()) != row[1]:
                raise ValueError("missing or altered replay")
            snapshot = RunSnapshot.model_validate_json(row[0])
            validate_completed_run_snapshot(snapshot)
            if (
                snapshot.scenario_id != scenario.scenario_id
                or snapshot.run_id != scenario.run_id
                or snapshot.trace_digest != scenario.runtime_trace_digest
                or snapshot.result_digest != scenario.result_digest
            ):
                raise ValueError("replay does not match comparison")
            return snapshot
        except (sqlite3.Error, ValueError) as error:
            raise ComparisonIndexError(
                "the real comparison replay failed integrity validation",
                code="storage",
            ) from error

    def _prepare(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS real_results(
                    result_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    result_digest TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS real_replays(
                    result_id TEXT NOT NULL,
                    model_role TEXT NOT NULL CHECK(
                        model_role IN ('base_gemma', 'trained_gemma')
                    ),
                    scenario_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    snapshot_digest TEXT NOT NULL,
                    PRIMARY KEY(result_id, model_role, scenario_id),
                    FOREIGN KEY(result_id) REFERENCES real_results(result_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS comparison_state(
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    mode TEXT NOT NULL CHECK(mode IN ('fixture', 'real')),
                    fixture_state TEXT,
                    real_result_id TEXT,
                    CHECK(
                        (mode = 'fixture' AND fixture_state IS NOT NULL AND real_result_id IS NULL)
                        OR (mode = 'real' AND fixture_state IS NULL AND real_result_id IS NOT NULL)
                    )
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO comparison_state(
                    singleton, mode, fixture_state, real_result_id
                ) VALUES (1, 'fixture', 'successful', NULL)
                """
            )
            connection.commit()
        os.chmod(self._database, 0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database, timeout=30.0)


def _gemma_model_matches(
    observed: ComparisonModelResult,
    expected: ComparisonModelResult,
) -> bool:
    if observed.model_dump(exclude={"metrics"}) != expected.model_dump(
        exclude={"metrics"}
    ):
        return False
    observed_metrics = observed.metrics
    expected_metrics = expected.metrics
    if observed_metrics is None or expected_metrics is None:
        return observed_metrics is expected_metrics
    scalar_pairs = (
        (observed_metrics.task_success, expected_metrics.task_success),
        (observed_metrics.verifier_score, expected_metrics.verifier_score),
        (observed_metrics.mean_action_count, expected_metrics.mean_action_count),
        (observed_metrics.abort_precision, expected_metrics.abort_precision),
        (observed_metrics.abort_recall, expected_metrics.abort_recall),
    )
    if (
        observed_metrics.scenario_count != expected_metrics.scenario_count
        or observed_metrics.tool_errors != expected_metrics.tool_errors
        or any(not _optional_float_matches(left, right) for left, right in scalar_pairs)
        or set(observed_metrics.strata) != set(expected_metrics.strata)
    ):
        return False
    return all(
        observed_stratum.count == expected_stratum.count
        and _optional_float_matches(
            observed_stratum.task_success,
            expected_stratum.task_success,
        )
        and _optional_float_matches(
            observed_stratum.verifier_score,
            expected_stratum.verifier_score,
        )
        for name, observed_stratum in observed_metrics.strata.items()
        for expected_stratum in (expected_metrics.strata[name],)
    )


def _optional_float_matches(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def _evidence_from_evaluator_ledger(
    artifact_root: Path,
    model_configuration_digest: str,
) -> tuple[HeldOutEvaluationEvidence, dict[str, RunSnapshot]]:
    from evaluation.eeg.attempts import open_held_out_attempt_ledger

    root = Path(artifact_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("evaluator ledger root is invalid")
    scenario_set = _heldout_scenario_set()
    ledger = open_held_out_attempt_ledger(
        artifact_root=root,
        scenario_set=scenario_set,
        model_configuration_digest=model_configuration_digest,
        rollouts_per_scenario=1,
    )
    report = scenario_set.aggregate(ledger)
    snapshots = {
        scenario_id: ledger.completed_snapshot(scenario_id)
        for scenario_id in scenario_set.scenario_ids
    }
    for snapshot in snapshots.values():
        validate_completed_run_snapshot(snapshot)
    success = {
        scenario_id: bool(snapshot.verifier_result.metrics["exact_terminal_success"])
        for scenario_id, snapshot in snapshots.items()
        if snapshot.verifier_result is not None
    }
    scores = {
        scenario_id: float(snapshot.verifier_result.metrics["reward"])
        for scenario_id, snapshot in snapshots.items()
        if snapshot.verifier_result is not None
    }
    result_digests = {
        scenario_id: snapshot.result_digest
        for scenario_id, snapshot in snapshots.items()
        if snapshot.result_digest is not None
    }
    evidence = HeldOutEvaluationEvidence(
        evidence_version="eeg-heldout-evaluation-evidence/1",
        model_configuration_digest=model_configuration_digest,
        report=report,
        scenario_success=success,
        verifier_scores=scores,
        canonical_run_ids={
            scenario_id: snapshot.run_id
            for scenario_id, snapshot in snapshots.items()
        },
        runtime_trace_digests={
            scenario_id: snapshot.trace_digest
            for scenario_id, snapshot in snapshots.items()
        },
        runtime_result_digests=result_digests,
    )
    return evidence, snapshots


def _replay_row(
    result_id: str,
    role: Literal["base_gemma", "trained_gemma"],
    snapshot: RunSnapshot,
) -> tuple[str, str, str, str, str]:
    payload = snapshot.model_dump_json()
    return (
        result_id,
        role,
        snapshot.scenario_id,
        payload,
        _digest_bytes(payload.encode()),
    )


def real_model_comparison(
    base: HeldOutEvaluationEvidence,
    trained: HeldOutEvaluationEvidence,
    *,
    training_result_id: str,
    training_artifact_digest: str,
    trained_adapter_digest: str,
    openai_credential_ready: bool,
    gemini_credential_ready: bool,
) -> ModelComparisonResult:
    """Build a real Gemma contrast while refusing to fabricate hosted results."""

    contrast = paired_bootstrap_success(
        base.scenario_success,
        trained.scenario_success,
    )
    models = (
        _real_gemma_model(
            "base_gemma",
            base,
            adapter_identity=None,
            adapter_digest=None,
        ),
        _real_gemma_model(
            "trained_gemma",
            trained,
            adapter_identity="eeg-curriculum-final",
            adapter_digest=trained_adapter_digest,
        ),
        _unavailable_reference(
            "openai_reference",
            credential_ready=openai_credential_ready,
        ),
        _unavailable_reference(
            "gemini_reference",
            credential_ready=gemini_credential_ready,
        ),
    )
    comparison_material = (
        base.model_configuration_digest
        + trained.model_configuration_digest
        + contrast.paired_outcomes_digest
        + training_artifact_digest
    )
    return ModelComparisonResult(
        comparison_version="scientist-model-comparison/1",
        comparison_id=(
            "model-comparison-real-"
            + hashlib.sha256(comparison_material.encode()).hexdigest()[:16]
        ),
        source="real_evaluation",
        fixture_state=None,
        fixture_notice=None,
        claim_scope="within_eeg_compositional_generalization",
        training_result_id=training_result_id,
        training_artifact_digest=training_artifact_digest,
        provenance=_provenance(),
        models=models,
        gemma_contrast=contrast,
        training_claim=contrast.conclusion,
        mesoscope=MesoscopeGeneralityTrack(
            claim_scope="platform_generality",
            label="Separate mesoscope platform-generality evidence",
            compiler_route="/api/platform-evidence/mesoscope",
            replay_route="/api/platform-evidence/mesoscope/replay",
            eeg_training_evidence=False,
        ),
    )


def _real_gemma_model(
    role: Literal["base_gemma", "trained_gemma"],
    evidence: HeldOutEvaluationEvidence,
    *,
    adapter_identity: str | None,
    adapter_digest: str | None,
) -> ComparisonModelResult:
    report = evidence.report
    if report.evaluation_id is None:
        raise ValueError("real held-out evidence has no evaluation identity")
    links = tuple(
        ScenarioResultLink(
            scenario_id=scenario_id,
            run_id=evidence.canonical_run_ids[scenario_id],
            runtime_trace_digest=evidence.runtime_trace_digests[scenario_id],
            result_digest=evidence.runtime_result_digests[scenario_id],
            success=evidence.scenario_success[scenario_id],
            verifier_score=evidence.verifier_scores[scenario_id],
            replay_route=(
                f"/api/model-comparison/replays/{role}/{scenario_id}"
            ),
        )
        for scenario_id in _heldout_scenario_set().scenario_ids
    )
    stratum_names: tuple[
        Literal["individual", "ambiguous", "pair", "triple"], ...
    ] = ("individual", "ambiguous", "pair", "triple")
    strata: dict[
        Literal["individual", "ambiguous", "pair", "triple"],
        ComparisonStratum,
    ] = {
        name: ComparisonStratum(
            count=report.by_category[name].count,
            task_success=report.by_category[name].exact_terminal_accuracy,
            verifier_score=report.by_category[name].mean_reward,
        )
        for name in stratum_names
    }
    action_values = report.diagnostics.actions_to_correct_terminal.values
    mean_actions = (
        sum(action_values) / len(action_values) if action_values else 0.0
    )
    metrics = ComparisonMetrics(
        scenario_count=len(links),
        task_success=report.exact_terminal_accuracy or 0.0,
        verifier_score=report.mean_reward or 0.0,
        abort_precision=report.abort.safe_abort_precision,
        abort_recall=report.abort.safe_abort_recall,
        mean_action_count=mean_actions,
        tool_errors=report.harness_errors,
        strata=strata,
    )
    return ComparisonModelResult(
        role=role,
        label=("Base Gemma E4B" if role == "base_gemma" else "Reloaded trained Gemma"),
        reference_model=False,
        requested_model="google/gemma-4-E4B-it",
        returned_model="google/gemma-4-E4B-it",
        adapter_identity=adapter_identity,
        adapter_digest=adapter_digest,
        model_configuration_digest=evidence.model_configuration_digest,
        run_id=report.evaluation_id,
        status="available",
        metrics=metrics,
        failure=None,
        scenarios=links,
    )


def _unavailable_reference(
    role: Literal["openai_reference", "gemini_reference"],
    *,
    credential_ready: bool,
) -> ComparisonModelResult:
    is_openai = role == "openai_reference"
    requested = "gpt-5.6-sol" if is_openai else "gemini-3.7-flash"
    return ComparisonModelResult(
        role=role,
        label="GPT reference" if is_openai else "Gemini reference",
        reference_model=True,
        requested_model=requested,
        returned_model=None,
        adapter_identity=None,
        adapter_digest=None,
        model_configuration_digest=_digest_text(
            f"unavailable-reference:{role}:{requested}:hosted-reference-medium-v1"
        ),
        run_id=f"comparison-run-unavailable-{role.replace('_', '-')}",
        status="provider_failure" if credential_ready else "credential_missing",
        metrics=None,
        failure=ComparisonFailure(
            category="provider" if credential_ready else "credential",
            summary=(
                "Hosted execution evidence is unavailable; no live score was fabricated."
                if credential_ready
                else "Hosted credential is not configured; no live score was fabricated."
            ),
        ),
        scenarios=(),
    )


def seeded_comparison(state: FixtureState) -> ModelComparisonResult:
    scenario_ids = _heldout_scenario_set().scenario_ids
    base, trained = _fixture_outcomes(state, scenario_ids)
    models = (
        _fixture_model("base_gemma", base, scenario_ids),
        _fixture_model(
            "trained_gemma",
            trained,
            scenario_ids,
            adapter_failure=state == "adapter_error",
        ),
        _fixture_model(
            "openai_reference",
            {scenario_id: index % 5 != 0 for index, scenario_id in enumerate(scenario_ids)},
            scenario_ids,
            credential_missing=state == "partially_unavailable",
        ),
        _fixture_model(
            "gemini_reference",
            {scenario_id: index % 4 != 0 for index, scenario_id in enumerate(scenario_ids)},
            scenario_ids,
        ),
    )
    contrast = (
        paired_bootstrap_success(base, trained)
        if models[1].status == "available"
        else None
    )
    return ModelComparisonResult(
        comparison_version="scientist-model-comparison/1",
        comparison_id=f"model-comparison-fixture-{state.replace('_', '-')}",
        source="seeded_offline_fixture",
        fixture_state=state,
        fixture_notice=(
            "Seeded offline demonstration fixture — not a live provider or training result."
        ),
        claim_scope="within_eeg_compositional_generalization",
        training_result_id=None,
        training_artifact_digest=None,
        provenance=_provenance(),
        models=models,
        gemma_contrast=contrast,
        training_claim=contrast.conclusion if contrast is not None else "unavailable",
        mesoscope=MesoscopeGeneralityTrack(
            claim_scope="platform_generality",
            label="Separate mesoscope platform-generality evidence",
            compiler_route="/api/platform-evidence/mesoscope",
            replay_route="/api/platform-evidence/mesoscope/replay",
            eeg_training_evidence=False,
        ),
    )


def _fixture_outcomes(
    state: FixtureState,
    scenario_ids: tuple[str, ...],
) -> tuple[dict[str, bool], dict[str, bool]]:
    base = {
        scenario_id: index < 24
        for index, scenario_id in enumerate(scenario_ids)
    }
    if state in {"successful", "partially_unavailable", "adapter_error"}:
        trained = {
            scenario_id: index < 44
            for index, scenario_id in enumerate(scenario_ids)
        }
    elif state == "regressed":
        trained = {
            scenario_id: index < 8
            for index, scenario_id in enumerate(scenario_ids)
        }
    else:
        trained = dict(base)
        for index in range(8):
            trained[scenario_ids[index]] = False
            trained[scenario_ids[24 + index]] = True
    return base, trained


def _fixture_model(
    role: ModelRole,
    outcomes: dict[str, bool],
    scenario_ids: tuple[str, ...],
    *,
    credential_missing: bool = False,
    adapter_failure: bool = False,
) -> ComparisonModelResult:
    identities = {
        "base_gemma": ("Base Gemma E4B", "google/gemma-4-E4B-it", None),
        "trained_gemma": (
            "Reloaded trained Gemma",
            "google/gemma-4-E4B-it",
            "eeg-curriculum-final",
        ),
        "openai_reference": ("GPT reference", "gpt-5.6-sol", None),
        "gemini_reference": ("Gemini reference", "gemini-3.7-flash", None),
    }
    label, requested, adapter = identities[role]
    status: ModelResultStatus = (
        "credential_missing"
        if credential_missing
        else "adapter_failure" if adapter_failure else "available"
    )
    failure = (
        ComparisonFailure(
            category="credential",
            summary="Hosted credential is not configured; no live score was fabricated.",
        )
        if credential_missing
        else (
            ComparisonFailure(
                category="adapter",
                summary="The trained adapter could not be loaded; base evidence remains separate.",
            )
            if adapter_failure
            else None
        )
    )
    links = (
        tuple(
            _fixture_link(role, scenario_id, index, outcomes[scenario_id])
            for index, scenario_id in enumerate(scenario_ids)
        )
        if status == "available"
        else ()
    )
    metrics = _fixture_metrics(links) if links else None
    return ComparisonModelResult(
        role=role,
        label=label,
        reference_model=role in {"openai_reference", "gemini_reference"},
        requested_model=requested,
        returned_model=requested if status == "available" else None,
        adapter_identity=adapter,
        adapter_digest=(
            _digest_text(f"fixture-adapter:{adapter}")
            if adapter is not None
            else None
        ),
        model_configuration_digest=_digest_text(
            f"fixture-configuration:{role}:{requested}:{adapter or 'none'}"
        ),
        run_id=f"comparison-run-fixture-{role.replace('_', '-')}",
        status=status,
        metrics=metrics,
        failure=failure,
        scenarios=links,
    )


def _fixture_link(
    role: ModelRole,
    scenario_id: str,
    index: int,
    success: bool,
) -> ScenarioResultLink:
    material = f"fixture:{role}:{scenario_id}:{index}"
    return ScenarioResultLink(
        scenario_id=scenario_id,
        run_id=f"comparison-run-fixture-{role.replace('_', '-')}",
        runtime_trace_digest=_digest_text(f"trace:{material}"),
        result_digest=_digest_text(f"result:{material}:{success}"),
        success=success,
        verifier_score=1.0 if success else (index % 5) / 10.0,
        replay_route=f"/api/model-comparison/replays/{role}/{scenario_id}",
    )


def _fixture_metrics(links: tuple[ScenarioResultLink, ...]) -> ComparisonMetrics:
    success = sum(link.success for link in links) / len(links)
    score = sum(link.verifier_score for link in links) / len(links)
    counts: dict[
        Literal["individual", "ambiguous", "pair", "triple"], int
    ] = {"individual": 16, "ambiguous": 16, "pair": 16, "triple": 8}
    strata: dict[
        Literal["individual", "ambiguous", "pair", "triple"],
        ComparisonStratum,
    ] = {
        name: ComparisonStratum(
            count=count,
            task_success=max(0.0, min(1.0, success - offset)),
            verifier_score=max(0.0, min(1.0, score - offset / 2)),
        )
        for (name, count), offset in zip(counts.items(), (0.0, 0.04, 0.08, 0.12))
    }
    return ComparisonMetrics(
        scenario_count=len(links),
        task_success=success,
        verifier_score=score,
        abort_precision=0.75,
        abort_recall=0.5,
        mean_action_count=8.0,
        tool_errors=0,
        strata=strata,
    )


def _provenance() -> ComparisonProvenance:
    return ComparisonProvenance(
        scenario_manifest_id="eeg-curriculum-release-1:held_out",
        scenario_manifest_digest=_heldout_scenario_set().identity.package_digest,
        environment_bundle_id="eeg-curriculum",
        environment_bundle_revision="1.4.0",
        scoring_revision="eeg-curriculum-scorer-1",
    )


def _digest_text(value: str) -> str:
    return _digest_bytes(value.encode())


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "ComparisonIndexError",
    "ComparisonReplay",
    "FixtureState",
    "ModelComparisonRepository",
    "ModelComparisonResult",
    "ModelRole",
    "real_model_comparison",
    "seeded_comparison",
]
