"""Canonical evaluator-ledger fixtures for real comparison persistence tests."""

from __future__ import annotations

from pathlib import Path

from environments.eeg.curriculum import CurriculumAttempt
from environments.eeg.runtime import EegEnvironmentModule
from evaluation.eeg.attempts import open_held_out_attempt_ledger
from evaluation.eeg.curriculum import load_held_out_scenario_set
from studio.curriculum_analysis import HeldOutEvaluationEvidence
from studio.model_comparison import ModelComparisonResult, real_model_comparison
from studio.runtime import EnvironmentRuntime, PolicyAgentIdentity, RunSnapshot


def real_comparison_with_ledgers(
    root: Path,
) -> tuple[ModelComparisonResult, Path, Path]:
    """Build a small-compute, full-coverage real comparison over canonical failures."""

    base_root = root / "base-ledger"
    trained_root = root / "trained-ledger"
    base = _incomplete_evidence(base_root, "sha256:" + "1" * 64, "base-policy")
    trained = _incomplete_evidence(
        trained_root,
        "sha256:" + "2" * 64,
        "trained-policy",
    )
    result = real_model_comparison(
        base,
        trained,
        training_result_id="eeg-training-result-realtest0001",
        training_artifact_digest="sha256:" + "d" * 64,
        trained_adapter_digest="sha256:" + "e" * 64,
        openai_credential_ready=False,
        gemini_credential_ready=False,
    )
    return result, base_root, trained_root


def _incomplete_evidence(
    root: Path,
    configuration_digest: str,
    policy_id: str,
) -> HeldOutEvaluationEvidence:
    scenario_set = load_held_out_scenario_set()
    ledger = open_held_out_attempt_ledger(
        artifact_root=root,
        scenario_set=scenario_set,
        model_configuration_digest=configuration_digest,
        rollouts_per_scenario=1,
    )
    snapshots: dict[str, RunSnapshot] = {}
    bundle = scenario_set.environment_bundle
    policy = PolicyAgentIdentity(id=policy_id, name=policy_id.replace("-", " ").title())
    for scenario_id in scenario_set.scenario_ids:
        runtime = EnvironmentRuntime(EegEnvironmentModule(bundle.model_copy(deep=True)))
        started = runtime.start(scenario_id, policy)
        completed = runtime.finalize_incomplete(
            started.run_id,
            termination_reason="model_ended_before_terminal",
        )
        snapshots[scenario_id] = completed
        ledger.record(
            CurriculumAttempt(
                scenario_id=scenario_id,
                rollout_index=0,
                model_configuration_digest=configuration_digest,
                run=completed,
            )
        )
    ledger.seal()
    report = scenario_set.aggregate(ledger)
    return HeldOutEvaluationEvidence(
        evidence_version="eeg-heldout-evaluation-evidence/1",
        model_configuration_digest=configuration_digest,
        report=report,
        scenario_success={scenario_id: False for scenario_id in snapshots},
        verifier_scores={scenario_id: 0.0 for scenario_id in snapshots},
        canonical_run_ids={
            scenario_id: snapshot.run_id
            for scenario_id, snapshot in snapshots.items()
        },
        runtime_trace_digests={
            scenario_id: snapshot.trace_digest
            for scenario_id, snapshot in snapshots.items()
        },
        runtime_result_digests={
            scenario_id: snapshot.result_digest or ""
            for scenario_id, snapshot in snapshots.items()
        },
    )
