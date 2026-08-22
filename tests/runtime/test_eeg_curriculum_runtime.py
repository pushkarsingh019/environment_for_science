"""Public Runtime journeys through the staged EEG curriculum."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest

from environments.eeg._curriculum_contract import CURRICULUM_ACTIONS
from environments.eeg.curriculum import (
    CurriculumAttempt,
    CurriculumContractError,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from evaluation.eeg import load_held_out_scenario_set
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    RunSnapshot,
)

POLICY = PolicyAgentIdentity(id="curriculum-test-policy", name="Curriculum test policy")
DUPLICATE_ONSET_SCENARIO = "eeg-4ba7d214edaabdeb"
CONFIGURATION_SCENARIO = "eeg-82c0fa2005a34723"
RUNTIME_ENVIRONMENT_SCENARIO = "eeg-53910d639f133d60"
UNAVAILABLE_EEG_SCENARIO = "eeg-0f9dc08c4a74a4f4"
SECOND_UNAVAILABLE_EEG_SCENARIO = "eeg-6f84fdf4cbff0feb"
TAUGHT_PAIR_SCENARIO = "eeg-04b947fbdffb3768"
NOMINAL_SCENARIO = "eeg-47d16a3170af262f"
MODEL_CONFIGURATION_DIGEST = "sha256:" + "4" * 64


def test_training_package_materializes_one_split_scoped_executable_bundle() -> None:
    package = load_training_scenario_set()
    bundle = package.environment_bundle

    assert bundle.generator_revision == "eeg-curriculum-generator-1"
    assert bundle.split_identities == ["training"]
    assert len(bundle.scenarios) == 96
    assert {scenario.id for scenario in bundle.scenarios} == set(package.scenario_ids)
    assert [action.type for action in bundle.actions] == [
        action["type"] for action in CURRICULUM_ACTIONS
    ]
    assert bundle.model_extra is not None
    assert bundle.model_extra["curriculum_package_digest"] == (package.identity.package_digest)


def test_policy_visible_evidence_ids_are_opaque_without_hidden_readiness_overlays() -> None:
    package = load_training_scenario_set()
    scenario = next(
        item for item in package.environment_bundle.scenarios if item.id == NOMINAL_SCENARIO
    )
    started = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle)).start(
        NOMINAL_SCENARIO, POLICY
    )

    evidence_ids = _values_for_key(started.observation, "evidence_id")
    assert evidence_ids
    assert all(evidence_id.split("-", 1)[0] in _EVIDENCE_DOMAINS for evidence_id in evidence_ids)
    assert all(f"{scenario.seed:x}" not in evidence_id for evidence_id in evidence_ids)
    assert _values_for_key(started.observation, "path_status") == []


def test_marker_fault_requires_supported_repair_and_fresh_evidence_then_replays() -> None:
    runtime = _training_runtime()
    started = runtime.start(DUPLICATE_ONSET_SCENARIO, POLICY)

    assert started.status == "active"
    assert started.observation["stage"] == "preflight"
    assert set(started.observation["evidence_freshness"]) == {
        "configuration",
        "eeg",
        "onset",
        "response",
        "recording",
    }
    assert _forbidden_policy_keys(started.observation) == set()

    current = _apply_sequence(
        runtime,
        started,
        (
            ("inspect_configuration", {}),
            ("inspect_eeg_signals", {}),
            ("inspect_onset_route", {}),
            ("inspect_response_timeline", {}),
            ("inspect_recording_timeline", {}),
            ("repair_refractory_route", {}),
        ),
    )
    onset_freshness = current.observation["evidence_freshness"]["onset"]
    assert onset_freshness["status"] == "stale"

    current = _act(runtime, current, "present_test_flash")
    assert current.observation["evidence_freshness"]["onset"]["status"] == "current"
    assert len(current.observation["onset_evidence"]["marker_times_ms"]) == 1

    terminal = _act(runtime, current, "complete_preflight")
    assert terminal.status == "awaiting_verification"
    verified = runtime.verify(terminal.run_id)
    assert verified.status == "completed"
    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.terminal_disposition == "closed"
    assert verified.verifier_result.metrics["terminal_correctness"] == 1.0
    assert verified.verifier_result.metrics["fresh_validation"] == 1.0
    assert verified.verifier_result.outcome_category == "individual"

    replay = runtime.replay(verified.run_id)
    assert replay.trace_matches is True
    assert replay.result_matches is True


def test_marker_only_level_uses_only_the_applicable_onset_gate() -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["stage"] == "marker_only" and not item["unavailable"]
    )
    occurrence = record["occurrences"][0]
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = runtime.start(record["scenario_id"], POLICY)

    assert {
        domain: evidence["applicable"]
        for domain, evidence in current.observation["evidence_freshness"].items()
    } == {
        "configuration": False,
        "eeg": False,
        "onset": True,
        "response": False,
        "recording": False,
    }
    current = _act(runtime, current, "inspect_onset_route")
    for action_type in occurrence["recovery_ladder"]:
        current = _act(runtime, current, action_type)
        current = _act(runtime, current, occurrence["retest_action"])
    terminal = _act(runtime, current, "complete_preflight")
    verified = runtime.verify(terminal.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True


@pytest.mark.parametrize(
    ("family", "disambiguating_actions"),
    (
        (
            "widespread_noise",
            (
                "inspect_frequency_evidence",
                "inspect_participant_state",
                "inspect_environment",
            ),
        ),
        ("quiet_channel", ("inspect_frequency_evidence",)),
        (
            "noisy_cap_site",
            ("inspect_frequency_evidence",),
        ),
        (
            "short_shared_transient",
            (
                "wait_for_stable_window",
                "inspect_eeg_signals",
                "inspect_frequency_evidence",
                "inspect_participant_state",
                "inspect_environment",
            ),
        ),
    ),
)
def test_ambiguous_negative_controls_require_observable_family_specific_evidence(
    family: str,
    disambiguating_actions: tuple[str, ...],
) -> None:
    package = load_held_out_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_heldout_v1.json")
        if item["ambiguity_family"] == family and not item["occurrences"]
    )

    incomplete_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    incomplete = incomplete_runtime.start(record["scenario_id"], POLICY)
    assert "comparison_plan" in _recursive_keys(incomplete.observation)
    assert family not in json.dumps(incomplete.observation, sort_keys=True)
    incomplete = _inspect_core(incomplete_runtime, incomplete)
    incomplete = _act(incomplete_runtime, incomplete, "complete_preflight")
    incomplete = incomplete_runtime.verify(incomplete.run_id)
    assert incomplete.verifier_result is not None
    assert incomplete.verifier_result.passed is False

    supported_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    supported = _inspect_core(
        supported_runtime,
        supported_runtime.start(record["scenario_id"], POLICY),
    )
    supported = _apply_sequence(
        supported_runtime,
        supported,
        tuple((action_type, {}) for action_type in disambiguating_actions),
    )
    supported = _act(supported_runtime, supported, "complete_preflight")
    supported = supported_runtime.verify(supported.run_id)
    assert supported.verifier_result is not None
    assert supported.verifier_result.passed is True


@pytest.mark.parametrize(
    "family",
    (
        "widespread_noise",
        "quiet_channel",
        "noisy_cap_site",
        "short_shared_transient",
    ),
)
def test_ambiguity_summary_does_not_reveal_benign_or_causal_branch(
    family: str,
) -> None:
    package = load_held_out_scenario_set()
    records = [
        item
        for item in _resource_records("curriculum_heldout_v1.json")
        if item["ambiguity_family"] == family
    ]
    benign = next(item for item in records if not item["occurrences"])
    causal = next(item for item in records if item["occurrences"])
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))

    benign_started = runtime.start(benign["scenario_id"], POLICY)
    causal_started = runtime.start(causal["scenario_id"], POLICY)

    assert benign_started.observation["summary"] == causal_started.observation["summary"]
    assert "internally coherent" not in benign_started.observation["summary"]


@pytest.mark.parametrize(
    ("fault", "field", "inspection_action"),
    (
        ("participant_artifact", "simulated_tension_reported", "inspect_participant_state"),
        (
            "environmental_contamination",
            "shared_source_present",
            "inspect_environment",
        ),
    ),
)
def test_context_observables_remain_uninspected_until_their_own_action(
    fault: str,
    field: str,
    inspection_action: str,
) -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["ambiguity_family"] == "widespread_noise" and item["faults"] == [fault]
    )
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = runtime.start(record["scenario_id"], POLICY)

    assert current.observation["participant_evidence"]["simulated_tension_reported"] is None
    assert current.observation["environment_evidence"]["shared_source_present"] is None

    current = _act(runtime, current, inspection_action)

    evidence_group = (
        "participant_evidence"
        if inspection_action == "inspect_participant_state"
        else "environment_evidence"
    )
    other_group = (
        "environment_evidence"
        if evidence_group == "participant_evidence"
        else "participant_evidence"
    )
    other_field = (
        "shared_source_present"
        if other_group == "environment_evidence"
        else "simulated_tension_reported"
    )
    assert current.observation[evidence_group][field] is True
    assert current.observation[other_group][other_field] is None


def test_configuration_correction_invalidates_every_dependent_gate() -> None:
    runtime = _training_runtime()
    current = _inspect_core(
        runtime,
        runtime.start(CONFIGURATION_SCENARIO, POLICY),
    )
    current = _act(runtime, current, "correct_acquisition_configuration")

    assert {
        domain: evidence["status"]
        for domain, evidence in current.observation["evidence_freshness"].items()
    } == {
        "configuration": "stale",
        "eeg": "stale",
        "onset": "stale",
        "response": "stale",
        "recording": "stale",
    }

    current = _act(runtime, current, "collect_fresh_eeg_window")
    assert current.observation["evidence_freshness"]["eeg"]["status"] == "current"
    assert current.observation["evidence_freshness"]["onset"]["status"] == "stale"
    current = _apply_sequence(
        runtime,
        current,
        (
            ("inspect_configuration", {}),
            ("present_test_flash", {}),
            ("run_response_preflight", {}),
            ("run_recording_preflight", {}),
            ("complete_preflight", {}),
        ),
    )
    verified = runtime.verify(current.run_id)
    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True


def test_runtime_fault_can_be_paused_annotated_recovered_and_validly_closed() -> None:
    runtime = _training_runtime()
    current = _inspect_core(
        runtime,
        runtime.start(RUNTIME_ENVIRONMENT_SCENARIO, POLICY),
    )
    current = _act(runtime, current, "start_acquisition")
    assert current.observation["stage"] == "recording"
    current = _act(runtime, current, "continue_acquisition")
    current = _act(runtime, current, "continue_acquisition")

    assert current.observation["acquisition"]["completed_trials"] == 2
    assert current.observation["acquisition"]["invalid_intervals"] == [
        {"start_trial": 2, "end_trial": 2, "path": "eeg"}
    ]
    current = _act(runtime, current, "pause_acquisition")
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    current = _act(
        runtime,
        current,
        "annotate_invalid_interval",
        {
            "start_trial": 2,
            "end_trial": 2,
            "path": "eeg",
            "evidence_id": evidence_id,
        },
    )
    current = _apply_sequence(
        runtime,
        current,
        (
            ("inspect_frequency_evidence", {}),
            ("inspect_environment", {}),
            ("isolate_electrical_source", {}),
            ("collect_fresh_eeg_window", {}),
            ("resume_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("close_acquisition", {}),
        ),
    )
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.terminal_disposition == "closed"
    assert verified.verifier_result.metrics["invalid_continuation_attempts"] == 0.0
    assert verified.verifier_result.metrics["runtime_fault_count"] == 1.0
    assert verified.verifier_result.metrics["invalid_continuation_fault_count"] == 0.0
    assert verified.verifier_result.metrics["pause_latency_logical_events"] == 0.0
    assert verified.verifier_result.metrics["pause_latency_observed"] == 1.0
    assert verified.verifier_result.metrics["annotation_coverage"] == 1.0
    assert verified.verifier_result.metrics["safety_compliance"] == 1.0
    replay = runtime.replay(verified.run_id)
    assert replay.trace_matches and replay.result_matches


def test_runtime_remediation_is_rejected_until_recording_is_paused() -> None:
    runtime = _training_runtime()
    current = _inspect_core(runtime, runtime.start(RUNTIME_ENVIRONMENT_SCENARIO, POLICY))
    current = _act(runtime, current, "start_acquisition")
    current = _act(runtime, current, "continue_acquisition")
    current = _act(runtime, current, "continue_acquisition")
    current = _apply_sequence(
        runtime,
        current,
        (("inspect_frequency_evidence", {}), ("inspect_environment", {})),
    )
    revision_before = _state_revision(current)

    rejected = _act(runtime, current, "isolate_electrical_source")

    assert _state_revision(rejected) == revision_before
    assert rejected.observation["stage"] == "recording"
    assert "pause" in rejected.observation["summary"].lower()
    paused = _act(runtime, rejected, "pause_acquisition")
    assert paused.observation["stage"] == "paused"


def test_runtime_ambiguity_requires_new_context_observations_after_activation() -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["runtime_onset"]
        and item["ambiguity_family"] == "widespread_noise"
        and not item["unavailable"]
    )
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = _inspect_core(runtime, runtime.start(record["scenario_id"], POLICY))
    current = _apply_sequence(
        runtime,
        current,
        (
            ("inspect_frequency_evidence", {}),
            ("inspect_participant_state", {}),
            ("inspect_environment", {}),
            ("start_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("pause_acquisition", {}),
            ("inspect_eeg_signals", {}),
            ("inspect_frequency_evidence", {}),
            ("reconnect_ground", {}),
        ),
    )

    assert current.observation["summary"] == (
        "The attempted change lacked current supporting inspection or ladder order."
    )

    current = _apply_sequence(
        runtime,
        current,
        (
            ("collect_fresh_eeg_window", {}),
            ("inspect_eeg_signals", {}),
            ("inspect_frequency_evidence", {}),
            ("inspect_participant_state", {}),
            ("inspect_environment", {}),
            ("reconnect_ground", {}),
        ),
    )
    assert current.observation["summary"] == (
        "The targeted simulated change was applied; dependent evidence is stale."
    )


def test_recording_never_advances_past_the_four_trial_annotation_bound() -> None:
    runtime = _training_runtime()
    current = _inspect_core(runtime, runtime.start(RUNTIME_ENVIRONMENT_SCENARIO, POLICY))
    current = _act(runtime, current, "start_acquisition")
    for _ in range(4):
        current = _act(runtime, current, "continue_acquisition")

    assert current.observation["acquisition"]["completed_trials"] == 4
    assert current.observation["acquisition"]["invalid_intervals"] == [
        {"start_trial": 2, "end_trial": 4, "path": "eeg"}
    ]
    revision_before = _state_revision(current)
    rejected = _act(runtime, current, "continue_acquisition")
    assert _state_revision(rejected) == revision_before
    assert rejected.observation["acquisition"]["completed_trials"] == 4
    assert rejected.observation["acquisition"]["invalid_intervals"] == [
        {"start_trial": 2, "end_trial": 4, "path": "eeg"}
    ]


def test_unsafe_extra_trial_reduces_reward_without_erasing_correct_terminal() -> None:
    safe_runtime = _training_runtime()
    safe = _run_environment_recovery(safe_runtime, unsafe_extra_trial=False)
    unsafe_runtime = _training_runtime()
    unsafe = _run_environment_recovery(unsafe_runtime, unsafe_extra_trial=True)

    assert safe.verifier_result is not None
    assert unsafe.verifier_result is not None
    assert safe.verifier_result.passed is True
    assert unsafe.verifier_result.passed is True
    assert unsafe.verifier_result.metrics["terminal_correctness"] == 1.0
    assert unsafe.verifier_result.metrics["invalid_continuation_attempts"] == 1.0
    assert unsafe.verifier_result.metrics["safety_compliance"] == 0.0
    assert unsafe.verifier_result.metrics["reward"] < safe.verifier_result.metrics["reward"]


def test_first_intervention_and_excess_count_do_not_average_or_double_count() -> None:
    runtime = _training_runtime()
    current = runtime.start(DUPLICATE_ONSET_SCENARIO, POLICY)
    current = _act(
        runtime,
        current,
        "reseat_electrode",
        {"site": "FC3"},
    )
    current = _apply_sequence(
        runtime,
        current,
        (
            ("inspect_onset_route", {}),
            ("repair_refractory_route", {}),
            ("present_test_flash", {}),
            ("complete_preflight", {}),
        ),
    )
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.metrics["first_intervention_relevance"] == 0.0
    assert verified.verifier_result.metrics["first_intervention_count"] == 1.0
    assert verified.verifier_result.metrics["first_intervention_relevant_count"] == 0.0
    assert verified.verifier_result.metrics["excess_intervention_count"] == 1.0
    assert verified.verifier_result.metrics["correct_terminal_count"] == 1.0
    assert verified.verifier_result.metrics["close_decision_count"] == 1.0
    assert verified.verifier_result.metrics["valid_close_count"] == 1.0
    assert verified.verifier_result.metrics["actions_to_correct_terminal"] == 4.0


def test_retest_coverage_scores_each_effective_change_independently() -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["faults"] == ["local_contact"]
        and item["episode_scope"] == "preflight"
        and not item["unavailable"]
        and len(item["occurrences"][0]["recovery_ladder"]) == 2
    )
    occurrence = record["occurrences"][0]
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = _inspect_core(runtime, runtime.start(record["scenario_id"], POLICY))
    current = _act(runtime, current, "inspect_frequency_evidence")
    first_action, second_action = occurrence["recovery_ladder"]
    current = _act(runtime, current, first_action, {"site": occurrence["target"]})
    current = _act(runtime, current, occurrence["retest_action"])
    current = _apply_sequence(
        runtime,
        current,
        (("inspect_eeg_signals", {}), ("inspect_frequency_evidence", {})),
    )
    current = _act(runtime, current, second_action, {"site": occurrence["target"]})
    current = _act(runtime, current, "complete_preflight")
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.metrics["retest_coverage"] == pytest.approx(0.5)
    assert verified.verifier_result.metrics["state_changing_remediation_count"] == 2.0
    assert verified.verifier_result.metrics["retested_remediation_count"] == 1.0


def test_trace_frequency_rate_scores_eeg_decisions_from_current_evidence() -> None:
    without_frequency_runtime = _training_runtime()
    without_frequency = _inspect_core(
        without_frequency_runtime,
        without_frequency_runtime.start(NOMINAL_SCENARIO, POLICY),
    )
    without_frequency = _act(without_frequency_runtime, without_frequency, "complete_preflight")
    without_frequency = without_frequency_runtime.verify(without_frequency.run_id)

    with_frequency_runtime = _training_runtime()
    with_frequency = _inspect_core(
        with_frequency_runtime,
        with_frequency_runtime.start(NOMINAL_SCENARIO, POLICY),
    )
    with_frequency = _act(with_frequency_runtime, with_frequency, "inspect_frequency_evidence")
    with_frequency = _act(with_frequency_runtime, with_frequency, "complete_preflight")
    with_frequency = with_frequency_runtime.verify(with_frequency.run_id)

    assert without_frequency.verifier_result is not None
    assert with_frequency.verifier_result is not None
    assert without_frequency.verifier_result.metrics["trace_frequency_inspection_rate"] == 0.0
    assert without_frequency.verifier_result.metrics["eeg_quality_decision_count"] == 1.0
    assert (
        without_frequency.verifier_result.metrics["trace_frequency_supported_decision_count"] == 0.0
    )
    assert with_frequency.verifier_result.metrics["trace_frequency_inspection_rate"] == 1.0
    assert with_frequency.verifier_result.metrics["eeg_quality_decision_count"] == 1.0
    assert with_frequency.verifier_result.metrics["trace_frequency_supported_decision_count"] == 1.0


def test_annotation_coverage_is_weighted_by_invalid_trial_duration() -> None:
    runtime = _training_runtime()
    current = _inspect_core(runtime, runtime.start(RUNTIME_ENVIRONMENT_SCENARIO, POLICY))
    current = _act(runtime, current, "start_acquisition")
    for _ in range(4):
        current = _act(runtime, current, "continue_acquisition")
    current = _act(runtime, current, "pause_acquisition")
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    current = _act(
        runtime,
        current,
        "annotate_invalid_interval",
        {
            "start_trial": 2,
            "end_trial": 2,
            "path": "eeg",
            "evidence_id": evidence_id,
        },
    )
    assert current.observation["annotations"] == [
        {
            "start_trial": 2,
            "end_trial": 2,
            "path": "eeg",
            "evidence_id": evidence_id,
        }
    ]
    current = _act(
        runtime,
        current,
        "abort_episode",
        {"path": "eeg", "evidence_id": evidence_id},
    )
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.metrics["annotation_coverage"] == pytest.approx(1 / 3)
    assert verified.verifier_result.metrics["invalid_runtime_duration"] == 3.0
    assert verified.verifier_result.metrics["annotated_invalid_runtime_duration"] == 1.0
    assert verified.verifier_result.metrics["valid_runtime_duration"] == 13.0
    assert verified.verifier_result.metrics["overannotated_valid_runtime_duration"] == 0.0


def test_benign_mimic_is_not_scored_as_optional_channel_over_intervention() -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["negative_control_kind"] == "benign_mimic"
    )
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = runtime.start(record["scenario_id"], POLICY)
    current = _act(runtime, current, "reseat_electrode", {"site": "FC3"})
    current = _act(runtime, current, "collect_fresh_eeg_window")
    current = _inspect_core(runtime, current)
    current = _act(runtime, current, "inspect_frequency_evidence")
    if record["ambiguity_family"] == "widespread_noise":
        current = _apply_sequence(
            runtime,
            current,
            (("inspect_participant_state", {}), ("inspect_environment", {})),
        )
    current = _act(runtime, current, "complete_preflight")
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.metrics["optional_channel_over_intervention"] == 0.0
    assert verified.verifier_result.metrics["optional_channel_scenario_count"] == 0.0
    assert verified.verifier_result.metrics["optional_channel_over_intervention_count"] == 0.0


def test_evidence_valid_unavailable_abort_receives_equal_terminal_credit() -> None:
    runtime = _training_runtime()
    started = runtime.start(UNAVAILABLE_EEG_SCENARIO, POLICY)
    current = _apply_sequence(
        runtime,
        started,
        (
            ("inspect_eeg_signals", {}),
            ("inspect_frequency_evidence", {}),
            ("reconnect_ground", {}),
            ("collect_fresh_eeg_window", {}),
        ),
    )
    assert _values_for_key(current.observation, "path_status") == []
    assert current.observation["eeg_window"]["status"] == "current"
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    terminal = _act(
        runtime,
        current,
        "abort_episode",
        {"path": "eeg", "evidence_id": evidence_id},
    )
    verified = runtime.verify(terminal.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.terminal_disposition == "aborted"
    assert verified.verifier_result.metrics["terminal_correctness"] == 1.0
    assert verified.verifier_result.metrics["terminal_credit"] == 1.0
    assert verified.verifier_result.metrics["exact_terminal_success"] == 1.0
    assert verified.verifier_result.metrics["eligible_safe_abort"] == 1.0
    assert verified.verifier_result.metrics["unavailable_scenario"] == 1.0

    early_runtime = _training_runtime()
    early = early_runtime.start(UNAVAILABLE_EEG_SCENARIO, POLICY)
    early_evidence = early.observation["evidence_freshness"]["eeg"]["evidence_id"]
    early = _act(
        early_runtime,
        early,
        "abort_episode",
        {"path": "eeg", "evidence_id": early_evidence},
    )
    early = early_runtime.verify(early.run_id)
    assert early.verifier_result is not None
    assert early.verifier_result.passed is False
    assert early.verifier_result.metrics["eligible_safe_abort"] == 0.0


def test_ineligible_unavailable_abort_cannot_earn_recoverable_partial_credit() -> None:
    package = load_held_out_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_heldout_v1.json")
        if item["unavailable"]
        and item["runtime_onset"]
        and item["unavailable_path"] == "eeg"
        and len(item["occurrences"]) == 1
    )
    occurrence = record["occurrences"][0]
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    current = _inspect_core(runtime, runtime.start(record["scenario_id"], POLICY))
    current = _apply_sequence(
        runtime,
        current,
        (
            ("start_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("pause_acquisition", {}),
            *((action_type, {}) for action_type in occurrence["inspection_actions"]),
            *((action_type, {}) for action_type in occurrence["recovery_ladder"]),
            (occurrence["retest_action"], {}),
        ),
    )
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    current = _act(
        runtime,
        current,
        "abort_episode",
        {"path": "eeg", "evidence_id": evidence_id},
    )
    verified = runtime.verify(current.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is False
    assert verified.verifier_result.metrics["eligible_safe_abort"] == 0.0
    assert verified.verifier_result.metrics["annotation_coverage"] == 0.0
    assert verified.verifier_result.metrics["terminal_credit"] == 0.10
    assert verified.verifier_result.metrics["terminal_correctness"] == 0.10
    assert verified.verifier_result.metrics["exact_terminal_success"] == 0.0


def test_recoverable_and_early_blocking_aborts_receive_partial_not_exact_credit() -> None:
    package = load_training_scenario_set()
    record = next(
        item
        for item in _resource_records("curriculum_training_v1.json")
        if item["faults"] == ["local_contact"]
        and item["episode_scope"] == "preflight"
        and not item["unavailable"]
        and len(item["occurrences"][0]["recovery_ladder"]) == 2
    )
    occurrence = record["occurrences"][0]
    attempted_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    attempted = attempted_runtime.start(record["scenario_id"], POLICY)
    attempted = _apply_sequence(
        attempted_runtime,
        attempted,
        (("inspect_eeg_signals", {}), ("inspect_frequency_evidence", {})),
    )
    attempted = _act(
        attempted_runtime,
        attempted,
        occurrence["recovery_ladder"][0],
        {"site": occurrence["target"]},
    )
    attempted = _act(attempted_runtime, attempted, occurrence["retest_action"])
    attempted_evidence = attempted.observation["evidence_freshness"]["eeg"]["evidence_id"]
    attempted = _act(
        attempted_runtime,
        attempted,
        "abort_episode",
        {"path": "eeg", "evidence_id": attempted_evidence},
    )
    attempted = attempted_runtime.verify(attempted.run_id)

    assert attempted.verifier_result is not None
    assert attempted.verifier_result.passed is False
    assert attempted.verifier_result.metrics["terminal_credit"] == 0.25
    assert attempted.verifier_result.metrics["terminal_correctness"] == 0.25
    assert attempted.verifier_result.metrics["exact_terminal_success"] == 0.0

    early_runtime = _training_runtime()
    early = early_runtime.start(DUPLICATE_ONSET_SCENARIO, POLICY)
    early_evidence = early.observation["evidence_freshness"]["onset"]["evidence_id"]
    early = _act(
        early_runtime,
        early,
        "abort_episode",
        {"path": "onset", "evidence_id": early_evidence},
    )
    early = early_runtime.verify(early.run_id)

    assert early.verifier_result is not None
    assert early.verifier_result.passed is False
    assert early.verifier_result.metrics["terminal_credit"] == 0.10
    assert early.verifier_result.metrics["terminal_correctness"] == 0.10
    assert early.verifier_result.metrics["exact_terminal_success"] == 0.0


def test_compound_recovery_accepts_both_safe_orders_and_each_trace_replays() -> None:
    first_runtime = _training_runtime()
    first = _run_taught_pair(first_runtime, environment_first=True)
    second_runtime = _training_runtime()
    second = _run_taught_pair(second_runtime, environment_first=False)

    assert first.verifier_result is not None
    assert second.verifier_result is not None
    assert first.verifier_result.passed is True
    assert second.verifier_result.passed is True
    assert first.verifier_result.metrics["targeted_intervention"] == 1.0
    assert second.verifier_result.metrics["targeted_intervention"] == 1.0
    assert first.trace_digest != second.trace_digest
    assert first_runtime.replay(first.run_id).result_matches is True
    assert second_runtime.replay(second.run_id).result_matches is True


def test_reset_recreates_the_exact_initial_observation_and_trace() -> None:
    runtime = _training_runtime()
    started = runtime.start(DUPLICATE_ONSET_SCENARIO, POLICY)
    reset = runtime.reset(started.run_id)

    assert reset.observation == started.observation
    assert reset.trace_digest == started.trace_digest
    assert reset.scenario_digest == started.scenario_digest
    assert reset.lineage.operation == "reset"
    assert reset.lineage.source_run_id == started.run_id


def test_cohort_report_exposes_abort_precision_recall_and_private_strata() -> None:
    package = load_training_scenario_set()
    eligible_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    eligible = _run_unavailable_abort(eligible_runtime, complete_ladder=True)
    early_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    early = _run_unavailable_abort(
        early_runtime,
        complete_ladder=False,
        scenario_id=SECOND_UNAVAILABLE_EEG_SCENARIO,
    )
    nominal_runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    nominal = nominal_runtime.start(NOMINAL_SCENARIO, POLICY)
    nominal_evidence = nominal.observation["evidence_freshness"]["eeg"]["evidence_id"]
    nominal = _act(
        nominal_runtime,
        nominal,
        "abort_episode",
        {"path": "eeg", "evidence_id": nominal_evidence},
    )
    nominal = nominal_runtime.verify(nominal.run_id)

    report = package.aggregate(tuple(_attempt(run) for run in (eligible, early, nominal)))

    assert report.completed_runs == 3
    assert report.scenario_coverage.numerator == 3
    assert report.scenario_coverage.denominator == 96
    assert report.abort.explicit_aborts == 3
    assert report.abort.eligible_aborts == 1
    assert report.abort.unavailable_attempts == 2
    assert report.abort.safe_abort_precision == pytest.approx(1 / 3)
    assert report.abort.safe_abort_recall == pytest.approx(1 / 2)
    assert report.abort.unnecessary_abort_rate == 1.0
    assert report.by_category["individual"].count == 2
    assert report.by_category["nominal"].count == 1


def test_held_out_report_refuses_an_unsealed_in_memory_attempt_sequence() -> None:
    package = load_held_out_scenario_set()
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    scenario_id = package.scenario_ids[0]
    snapshot = runtime.start(scenario_id, POLICY)
    evidence_id = snapshot.observation["evidence_freshness"]["eeg"]["evidence_id"]
    snapshot = _act(
        runtime,
        snapshot,
        "abort_episode",
        {"path": "eeg", "evidence_id": evidence_id},
    )
    snapshot = runtime.verify(snapshot.run_id)

    with pytest.raises(CurriculumContractError, match="persistent sealed attempt ledger"):
        package.aggregate((_attempt(snapshot),))


def test_literal_abort_all_policy_has_zero_precision_recall_and_success() -> None:
    package = load_training_scenario_set()
    runtime = EnvironmentRuntime(EegEnvironmentModule(package.environment_bundle))
    completed: list[RunSnapshot] = []
    for scenario_id in package.scenario_ids:
        snapshot = runtime.start(scenario_id, POLICY)
        evidence_id = snapshot.observation["evidence_freshness"]["eeg"]["evidence_id"]
        snapshot = _act(
            runtime,
            snapshot,
            "abort_episode",
            {"path": "eeg", "evidence_id": evidence_id},
        )
        completed.append(runtime.verify(snapshot.run_id))

    report = package.aggregate(tuple(_attempt(run) for run in completed))
    assert report.abort.explicit_aborts == 96
    assert report.abort.eligible_aborts == 0
    assert report.abort.unavailable_attempts == 12
    assert report.abort.safe_abort_precision == 0.0
    assert report.abort.safe_abort_recall == 0.0
    assert report.exact_terminal_accuracy == 0.0


def _training_runtime() -> EnvironmentRuntime:
    bundle = load_training_scenario_set().environment_bundle
    return EnvironmentRuntime(EegEnvironmentModule(bundle))


def _inspect_core(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
) -> RunSnapshot:
    return _apply_sequence(
        runtime,
        snapshot,
        (
            ("inspect_configuration", {}),
            ("inspect_eeg_signals", {}),
            ("inspect_onset_route", {}),
            ("inspect_response_timeline", {}),
            ("inspect_recording_timeline", {}),
        ),
    )


def _run_environment_recovery(
    runtime: EnvironmentRuntime,
    *,
    unsafe_extra_trial: bool,
) -> RunSnapshot:
    current = _inspect_core(
        runtime,
        runtime.start(RUNTIME_ENVIRONMENT_SCENARIO, POLICY),
    )
    current = _act(runtime, current, "start_acquisition")
    current = _act(runtime, current, "continue_acquisition")
    current = _act(runtime, current, "continue_acquisition")
    end_trial = 2
    if unsafe_extra_trial:
        current = _act(runtime, current, "continue_acquisition")
        end_trial = 3
    current = _act(runtime, current, "pause_acquisition")
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    current = _act(
        runtime,
        current,
        "annotate_invalid_interval",
        {
            "start_trial": 2,
            "end_trial": end_trial,
            "path": "eeg",
            "evidence_id": evidence_id,
        },
    )
    current = _apply_sequence(
        runtime,
        current,
        (
            ("inspect_frequency_evidence", {}),
            ("inspect_environment", {}),
            ("isolate_electrical_source", {}),
            ("collect_fresh_eeg_window", {}),
            ("resume_acquisition", {}),
        ),
    )
    while current.observation["acquisition"]["completed_trials"] < 4:
        current = _act(runtime, current, "continue_acquisition")
    current = _act(runtime, current, "close_acquisition")
    return runtime.verify(current.run_id)


def _run_taught_pair(
    runtime: EnvironmentRuntime,
    *,
    environment_first: bool,
) -> RunSnapshot:
    current = _inspect_core(runtime, runtime.start(TAUGHT_PAIR_SCENARIO, POLICY))
    current = _apply_sequence(
        runtime,
        current,
        (("inspect_frequency_evidence", {}), ("inspect_environment", {})),
    )
    environment_actions: tuple[tuple[str, dict[str, object]], ...] = (
        ("isolate_electrical_source", {}),
        ("collect_fresh_eeg_window", {}),
    )
    recording_actions: tuple[tuple[str, dict[str, object]], ...] = (
        ("restore_recording_state", {}),
        ("run_recording_preflight", {}),
    )
    current = _apply_sequence(
        runtime,
        current,
        (
            *(environment_actions if environment_first else recording_actions),
            *(recording_actions if environment_first else environment_actions),
            ("start_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("continue_acquisition", {}),
            ("close_acquisition", {}),
        ),
    )
    return runtime.verify(current.run_id)


def _run_unavailable_abort(
    runtime: EnvironmentRuntime,
    *,
    complete_ladder: bool,
    scenario_id: str = UNAVAILABLE_EEG_SCENARIO,
) -> RunSnapshot:
    current = runtime.start(scenario_id, POLICY)
    if complete_ladder:
        current = _apply_sequence(
            runtime,
            current,
            (
                ("inspect_eeg_signals", {}),
                ("inspect_frequency_evidence", {}),
                ("reconnect_ground", {}),
                ("collect_fresh_eeg_window", {}),
            ),
        )
    evidence_id = current.observation["evidence_freshness"]["eeg"]["evidence_id"]
    current = _act(
        runtime,
        current,
        "abort_episode",
        {"path": "eeg", "evidence_id": evidence_id},
    )
    return runtime.verify(current.run_id)


def _attempt(run: RunSnapshot) -> CurriculumAttempt:
    return CurriculumAttempt(
        scenario_id=run.scenario_id,
        rollout_index=0,
        model_configuration_digest=MODEL_CONFIGURATION_DIGEST,
        run=run,
    )


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


def _apply_sequence(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    actions: tuple[tuple[str, dict[str, object]], ...],
) -> RunSnapshot:
    current = snapshot
    for action_type, arguments in actions:
        current = _act(runtime, current, action_type, arguments)
    return current


def _forbidden_policy_keys(value: Any) -> set[str]:
    forbidden = {
        "split",
        "blueprint_id",
        "nuisance_id",
        "fault",
        "faults",
        "category",
        "availability",
        "ambiguity_family",
        "unavailable",
        "expected_action",
        "verifier_truth",
        "package_digest",
    }
    if isinstance(value, dict):
        keys = forbidden.intersection(value)
        return keys.union(*(_forbidden_policy_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_forbidden_policy_keys(item) for item in value))
    return set()


def _values_for_key(value: Any, target: str) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == target and isinstance(item, str):
                values.append(item)
            values.extend(_values_for_key(item, target))
    elif isinstance(value, list):
        for item in value:
            values.extend(_values_for_key(item, target))
    return values


_EVIDENCE_DOMAINS = {"configuration", "eeg", "onset", "response", "recording"}


def _state_revision(snapshot: RunSnapshot) -> int:
    value = snapshot.observation["evidence_freshness"]["eeg"]["state_revision"]
    assert isinstance(value, int)
    return value


def _resource_records(resource_name: str) -> list[dict[str, Any]]:
    document = json.loads(files("environments.eeg").joinpath(resource_name).read_text())
    records = document["scenarios"]
    assert isinstance(records, list)
    return records


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_recursive_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value))
    return set()
