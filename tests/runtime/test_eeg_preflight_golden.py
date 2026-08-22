"""Reviewed golden Runtime traces for every Ticket 03 singleton scenario."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from environments.eeg.runtime import EegEnvironmentModule
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    RunSnapshot,
)

POLICY = PolicyAgentIdentity(id="policy-golden", name="Golden trace policy")
GOLDEN_PATH = Path(__file__).with_name("eeg_preflight_golden_v1.json")


@lru_cache(maxsize=1)
def _golden_fixture() -> dict[str, Any]:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["fixture_revision"] == "ticket-03-golden-runtime-traces-1"
    return payload


GOLDEN_CASES = _golden_fixture()["scenarios"]
OUTCOME_ROUTES = _golden_fixture()["outcome_routes"]


def _runtime() -> EnvironmentRuntime:
    return EnvironmentRuntime(EegEnvironmentModule.from_seed())


def _apply(
    runtime: EnvironmentRuntime,
    snapshot: RunSnapshot,
    action_payload: dict[str, Any],
) -> tuple[RunSnapshot, dict[str, Any]]:
    action_type = action_payload["type"]
    arguments = action_payload.get("arguments", {})
    assert isinstance(action_type, str)
    assert isinstance(arguments, dict)
    action = EnvironmentAction(type=action_type, arguments=arguments)
    return runtime.apply_action(snapshot.run_id, action), action.model_dump(mode="json")


def _read_pointer(document: object, pointer: str) -> object:
    assert pointer.startswith("/")
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list):
            value = value[int(token)]
        else:
            raise AssertionError(f"golden pointer {pointer!r} crosses a scalar")
    return value


def _assert_fingerprint(
    observation: dict[str, Any],
    fingerprint: dict[str, Any],
) -> None:
    for pointer, expected in fingerprint.items():
        assert _read_pointer(observation, pointer) == expected, pointer


def _decision_action(
    snapshot: RunSnapshot,
    decision: dict[str, Any],
) -> EnvironmentAction:
    decision_type = decision["type"]
    assert isinstance(decision_type, str)
    if decision_type == "complete_preflight":
        return EnvironmentAction(type=decision_type, arguments={})

    assert decision_type == "abort_preflight"
    path = decision["path"]
    assert path in {"eeg", "onset", "response", "recording"}
    evidence_key = "eeg_window" if path == "eeg" else f"{path}_evidence"
    evidence = snapshot.observation[evidence_key]
    assert isinstance(evidence, dict)
    return EnvironmentAction(
        type=decision_type,
        arguments={"path": path, "evidence_id": evidence["evidence_id"]},
    )


def test_reviewed_matrix_names_all_twenty_opaque_singleton_families() -> None:
    scenario_ids = {case["scenario_id"] for case in GOLDEN_CASES}
    families = {case["family"] for case in GOLDEN_CASES}

    assert scenario_ids == {f"eeg-demo-{index:03d}" for index in range(1, 21)}
    assert len(families) == 20
    assert families == {
        "required_site_local_noise",
        "intermittent_required_electrode",
        "flat_required_electrode",
        "clipped_required_electrode",
        "shared_reference_pattern",
        "shared_ground_pattern",
        "shared_environmental_rhythm",
        "duplicated_onset_marker",
        "missing_onset_marker",
        "visible_trigger_confound",
        "missing_response_occurrence",
        "response_identity_mismatch",
        "inactive_recording_state",
        "timeline_misalignment",
        "low_amplitude_dynamic_control",
        "nominal_required_montage_control",
        "unavailable_onset_path",
        "unavailable_electrode_path",
        "participant_activity",
        "optional_site_noise_control",
    }


@pytest.mark.parametrize(
    "golden_case",
    GOLDEN_CASES,
    ids=[case["scenario_id"] for case in GOLDEN_CASES],
)
def test_golden_scenario_trace_reaches_reviewed_judgment_and_replays(
    golden_case: dict[str, Any],
) -> None:
    runtime = _runtime()
    snapshot = runtime.start(golden_case["scenario_id"], POLICY)
    applied_actions: list[dict[str, Any]] = []

    assert snapshot.trace_header.scenario_id == golden_case["scenario_id"]
    assert snapshot.trace_header.split == "demonstration"
    assert snapshot.observation["simulation_label"] == (
        "Synthetic EEG apparatus simulation"
    )
    _assert_fingerprint(snapshot.observation, golden_case["initial_fingerprint"])

    for action_payload in golden_case["inspections"]:
        snapshot, applied = _apply(runtime, snapshot, action_payload)
        applied_actions.append(applied)
    _assert_fingerprint(
        snapshot.observation,
        golden_case.get("post_inspection_fingerprint", {}),
    )

    intervention = golden_case.get("intervention")
    if intervention is not None:
        snapshot, applied = _apply(runtime, snapshot, intervention)
        applied_actions.append(applied)

    retest = golden_case.get("retest")
    if retest is not None:
        snapshot, applied = _apply(runtime, snapshot, retest)
        applied_actions.append(applied)

    decision = _decision_action(snapshot, golden_case["decision"])
    snapshot = runtime.apply_action(snapshot.run_id, decision)
    applied_actions.append(decision.model_dump(mode="json"))
    completed = runtime.verify(snapshot.run_id)
    result = completed.verifier_result
    expected_outcome = golden_case["outcome"]

    assert result is not None
    assert {
        "passed": result.passed,
        "terminal_disposition": result.terminal_disposition,
        "outcome_category": result.outcome_category,
        "state_revision": result.evidence["state_revision"],
    } == expected_outcome
    assert result.metrics == {
        "terminal_correctness": 1.0,
        "fresh_validation": 1.0,
        "targeted_intervention": 1.0 if intervention is not None else 0.0,
    }

    action_events = [event.action for event in completed.trace if event.type == "action"]
    transition_events = [
        event.transition for event in completed.trace if event.type == "transition"
    ]
    assert action_events == applied_actions
    assert [transition["state_revision"] for transition in transition_events] == (
        golden_case["trace"]["transition_revisions"]
    )
    assert len(completed.trace) == golden_case["trace"]["event_count"]
    assert [event.sequence for event in completed.trace] == list(
        range(1, len(completed.trace) + 1)
    )
    assert completed.trace[-1].type == "verifier"
    assert completed.trace[-1].verifier is not None
    assert completed.trace[-1].verifier["outcome_category"] == (
        expected_outcome["outcome_category"]
    )

    replay = runtime.replay(completed.run_id)
    assert replay.trace_matches is True
    assert replay.result_matches is True
    assert replay.source_trace_digest == replay.replay_trace_digest
    assert replay.source_result_digest == replay.replay_result_digest


def test_golden_state_change_marks_bound_eeg_evidence_stale_until_retest() -> None:
    route = _golden_fixture()["stale_evidence_route"]
    runtime = _runtime()
    snapshot = runtime.start(route["scenario_id"], POLICY)

    assert snapshot.observation["eeg_window"]["evidence_id"] == (
        route["initial_evidence_id"]
    )
    for action_payload in route["inspections"]:
        snapshot, _ = _apply(runtime, snapshot, action_payload)

    snapshot, _ = _apply(runtime, snapshot, route["intervention"])
    assert snapshot.observation["eeg_window"]["evidence_id"] == (
        route["initial_evidence_id"]
    )
    assert snapshot.observation["eeg_window"]["status"] == "stale"
    assert snapshot.observation["frequency_evidence"]["status"] == "stale"
    assert snapshot.observation["evidence_freshness"]["eeg"] == {
        "evidence_id": route["initial_evidence_id"],
        "state_revision": 1,
        "status": "stale",
        "evidence_state_revision": 0,
        "reason": "A simulated state change requires fresh evidence for this path.",
    }

    snapshot, _ = _apply(runtime, snapshot, route["retest"])
    assert snapshot.observation["eeg_window"]["evidence_id"] == (
        route["fresh_evidence_id"]
    )
    assert snapshot.observation["eeg_window"]["status"] == "current"
    assert snapshot.observation["frequency_evidence"] is None
    assert snapshot.observation["evidence_freshness"]["eeg"] == {
        "evidence_id": route["fresh_evidence_id"],
        "state_revision": 1,
        "status": "current",
    }


@pytest.mark.parametrize(
    "route",
    OUTCOME_ROUTES,
    ids=[route["name"] for route in OUTCOME_ROUTES],
)
def test_golden_failed_lucky_and_abort_routes_keep_distinct_explanations(
    route: dict[str, Any],
) -> None:
    runtime = _runtime()
    snapshot = runtime.start(route["scenario_id"], POLICY)

    for action_payload in route["actions"]:
        snapshot, _ = _apply(runtime, snapshot, action_payload)
    decision = _decision_action(snapshot, route["decision"])
    snapshot = runtime.apply_action(snapshot.run_id, decision)
    completed = runtime.verify(snapshot.run_id)
    result = completed.verifier_result
    expected = route["outcome"]

    assert result is not None
    assert {
        "passed": result.passed,
        "terminal_disposition": result.terminal_disposition,
        "outcome_category": result.outcome_category,
        "metrics": result.metrics,
    } == expected
    assert result.summary
    if result.passed is False:
        assert result.reasons
