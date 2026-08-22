"""Trusted evaluator proof that every frozen EEG scenario has a valid witness."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Union

import pytest

from environments.eeg.curriculum import (
    CurriculumAttempt,
    DevelopmentScenarioSet,
    TrainingScenarioSet,
    load_development_scenario_set,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from evaluation.eeg.attempts import open_held_out_attempt_ledger
from evaluation.eeg.curriculum import (
    HeldOutScenarioSet,
    load_held_out_scenario_set,
)
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    RunSnapshot,
)

ScenarioSet = Union[
    TrainingScenarioSet,
    DevelopmentScenarioSet,
    HeldOutScenarioSet,
]
Loader = Callable[[], ScenarioSet]
POLICY = PolicyAgentIdentity(id="reachability-auditor", name="Reachability auditor")
MODEL_CONFIGURATION_DIGEST = "sha256:" + "3" * 64
_CORE_INSPECTIONS = (
    "inspect_configuration",
    "inspect_eeg_signals",
    "inspect_onset_route",
    "inspect_response_timeline",
    "inspect_recording_timeline",
)
_AMBIGUITY_ACTIONS = {
    "widespread_noise": (
        "inspect_configuration",
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
        "inspect_participant_state",
        "inspect_environment",
    ),
    "quiet_channel": ("inspect_eeg_signals", "inspect_frequency_evidence"),
    "unstable_channel": ("inspect_eeg_signals", "inspect_frequency_evidence"),
    "flash_without_marker": (
        "inspect_onset_route",
        "inspect_recording_timeline",
    ),
    "response_without_identity": (
        "run_response_preflight",
        "inspect_response_timeline",
    ),
    "noisy_cap_site": (
        "inspect_configuration",
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
    ),
    "short_shared_transient": (
        "wait_for_stable_window",
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
        "inspect_participant_state",
        "inspect_environment",
    ),
}
_RETEST = {
    "configuration": "inspect_configuration",
    "eeg": "collect_fresh_eeg_window",
    "onset": "present_test_flash",
    "response": "run_response_preflight",
    "recording": "run_recording_preflight",
}
_SITE_ACTIONS = {"reseat_electrode", "replace_electrode", "reconnect_electrode_path"}


@pytest.mark.parametrize(
    ("loader", "resource_name"),
    (
        (load_training_scenario_set, "curriculum_training_v1.json"),
        (load_development_scenario_set, "curriculum_development_v1.json"),
        (load_held_out_scenario_set, "curriculum_heldout_v1.json"),
    ),
)
def test_every_frozen_scenario_has_a_deterministic_valid_terminal_witness(
    loader: Loader,
    resource_name: str,
    tmp_path: Path,
) -> None:
    package = loader()
    document = json.loads(files("environments.eeg").joinpath(resource_name).read_text())
    records = {record["scenario_id"]: record for record in document["scenarios"]}
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    completed: list[RunSnapshot] = []
    replayed_strata: set[tuple[str, bool, bool, str, str, str]] = set()

    for scenario_id in package.scenario_ids:
        record = records[scenario_id]
        started = runtime.start(scenario_id, POLICY)
        assert _forbidden_policy_keys(started.observation) == set()
        terminal = _execute_witness(runtime, started, record)
        verified = runtime.verify(terminal.run_id)

        assert verified.verifier_result is not None
        assert verified.verifier_result.passed is True, scenario_id
        assert verified.verifier_result.metrics["terminal_correctness"] == 1.0
        assert verified.verifier_result.outcome_category == record["category"]
        assert _forbidden_policy_keys(verified.observation) == set()
        completed.append(verified)

        stratum = (
            record["category"],
            record["unavailable"],
            record["runtime_onset"],
            record["nuisance_family"],
            record["stage"],
            record["negative_control_kind"],
        )
        if stratum not in replayed_strata:
            replay = runtime.replay(verified.run_id)
            assert replay.trace_matches and replay.result_matches
            replayed_strata.add(stratum)

    attempts = tuple(
        CurriculumAttempt(
            scenario_id=run.scenario_id,
            rollout_index=0,
            model_configuration_digest=MODEL_CONFIGURATION_DIGEST,
            run=run,
        )
        for run in completed
    )
    if isinstance(package, HeldOutScenarioSet):
        ledger = open_held_out_attempt_ledger(
            artifact_root=tmp_path,
            scenario_set=package,
            model_configuration_digest=MODEL_CONFIGURATION_DIGEST,
            rollouts_per_scenario=1,
        )
        for attempt in attempts:
            ledger.record(attempt)
        ledger.seal()
        report = package.aggregate(ledger)
    else:
        report = package.aggregate(attempts)
    assert report.completed_runs == len(package.scenario_ids)
    assert report.scenario_coverage.value == 1.0
    assert report.exact_terminal_accuracy == 1.0
    assert report.abort.eligible_aborts == report.abort.unavailable_attempts
    assert report.abort.safe_abort_precision == 1.0
    assert report.abort.safe_abort_recall == 1.0


def _execute_witness(
    runtime: EnvironmentRuntime,
    started: RunSnapshot,
    record: dict[str, Any],
) -> RunSnapshot:
    core_inspections = (
        ("inspect_onset_route",) if record["stage"] == "marker_only" else _CORE_INSPECTIONS
    )
    current = _apply_actions(runtime, started, core_inspections)
    current = _apply_ambiguity_actions(runtime, current, record)
    preflight = sorted(
        (
            occurrence
            for occurrence in record["occurrences"]
            if occurrence["activation"] == "preflight"
        ),
        key=lambda occurrence: occurrence["unavailable"],
    )
    for occurrence in preflight:
        current = _recover_occurrence(runtime, current, record, occurrence)
        if occurrence["unavailable"]:
            current = _refresh_domain(runtime, current, record["unavailable_path"])
            return _abort(runtime, current, record["unavailable_path"])

    current = _refresh_all_stale(runtime, current)
    if record["episode_scope"] == "preflight":
        return _act(runtime, current, "complete_preflight")

    current = _act(runtime, current, "start_acquisition")
    while current.observation["stage"] == "recording":
        current = _act(runtime, current, "continue_acquisition")
        invalid = current.observation["acquisition"]["invalid_intervals"]
        if not invalid or current.observation["stage"] != "recording":
            continue
        current = _act(runtime, current, "pause_acquisition")
        interval = invalid[-1]
        path = interval["path"]
        evidence_id = current.observation["evidence_freshness"][path]["evidence_id"]
        current = _act(
            runtime,
            current,
            "annotate_invalid_interval",
            {
                "start_trial": interval["start_trial"],
                "end_trial": interval["end_trial"],
                "path": path,
                "evidence_id": evidence_id,
            },
        )
        occurrence = next(item for item in record["occurrences"] if item["activation"] == "runtime")
        current = _recover_occurrence(runtime, current, record, occurrence)
        current = _refresh_all_stale(runtime, current)
        if occurrence["unavailable"]:
            return _abort(runtime, current, record["unavailable_path"])
        current = _act(runtime, current, "resume_acquisition")

    assert current.observation["stage"] == "recording_complete"
    return _act(runtime, current, "close_acquisition")


def _recover_occurrence(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    record: dict[str, Any],
    occurrence: dict[str, Any],
) -> RunSnapshot:
    current = snapshot
    for action_type in occurrence["recovery_ladder"]:
        current = _refresh_domain(runtime, current, occurrence["domain"])
        current = _apply_actions(runtime, current, tuple(occurrence["inspection_actions"]))
        current = _apply_ambiguity_actions(runtime, current, record)
        arguments = {"site": occurrence["target"]} if action_type in _SITE_ACTIONS else {}
        current = _act(runtime, current, action_type, arguments)
        current = _act(runtime, current, occurrence["retest_action"])
    return current


def _apply_ambiguity_actions(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    record: dict[str, Any],
) -> RunSnapshot:
    family = record["ambiguity_family"]
    if family is None:
        return snapshot
    return _apply_actions(runtime, snapshot, _AMBIGUITY_ACTIONS[family])


def _refresh_all_stale(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
) -> RunSnapshot:
    current = snapshot
    for domain in _RETEST:
        current = _refresh_domain(runtime, current, domain)
    return current


def _refresh_domain(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    domain: str,
) -> RunSnapshot:
    freshness = snapshot.observation["evidence_freshness"][domain]
    if freshness["status"] == "current":
        return snapshot
    return _act(runtime, snapshot, _RETEST[domain])


def _abort(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    path: str,
) -> RunSnapshot:
    evidence_id = snapshot.observation["evidence_freshness"][path]["evidence_id"]
    return _act(
        runtime,
        snapshot,
        "abort_episode",
        {"path": path, "evidence_id": evidence_id},
    )


def _apply_actions(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    actions: tuple[str, ...],
) -> RunSnapshot:
    current = snapshot
    for action_type in actions:
        current = _act(runtime, current, action_type)
    return current


def _act(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    action_type: str,
    arguments: dict[str, object] | None = None,
) -> RunSnapshot:
    return runtime.apply_action(
        snapshot.run_id,
        EnvironmentAction(type=action_type, arguments=arguments or {}),
    )


def _forbidden_policy_keys(value: Any) -> set[str]:
    forbidden = {
        "split",
        "blueprint_id",
        "nuisance_id",
        "fault",
        "faults",
        "occurrences",
        "category",
        "availability",
        "ambiguity_family",
        "negative_control_kind",
        "role_requirement",
        "unavailable",
        "expected_action",
        "verifier_truth",
        "manifest_digest",
        "package_digest",
    }
    if isinstance(value, dict):
        return forbidden.intersection(value).union(
            *(_forbidden_policy_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_forbidden_policy_keys(item) for item in value))
    return set()
