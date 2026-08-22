import json
from copy import deepcopy

import pytest

from environments.eeg import load_seeded_bundle
from environments.eeg.runtime import EegMarkerRecoveryModule
from studio.bundle import validate_environment_bundle
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    EpisodeState,
    EpisodeUpdate,
    PolicyAgentIdentity,
    RuntimeContractError,
)


def _start_seeded_run() -> tuple[EnvironmentRuntime, str]:
    runtime = EnvironmentRuntime(EegMarkerRecoveryModule.from_seed())
    snapshot = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )
    return runtime, snapshot.run_id


def test_start_freezes_seeded_episode_and_exposes_only_policy_visible_state() -> None:
    runtime = EnvironmentRuntime(EegMarkerRecoveryModule.from_seed())

    snapshot = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )

    assert snapshot.status == "active"
    assert snapshot.scenario_id == "eeg-marker-recovery-001"
    assert snapshot.revision_digest.startswith("sha256:")
    assert snapshot.scenario_digest.startswith("sha256:")
    assert snapshot.policy_agent.id == "seeded-policy-agent"
    assert snapshot.observation["onset_timeline"]["marker_count"] == 2
    assert snapshot.observation["freshness"] == {
        "evidence_id": "flash-001",
        "state_revision": 0,
        "status": "current",
    }
    assert "refractory_route_repaired" not in snapshot.model_dump_json()
    assert [event.type for event in snapshot.trace] == ["observation"]
    assert snapshot.trace[0].observation == snapshot.observation


def test_canonical_trace_header_binds_frozen_scenario_and_policy_identity() -> None:
    runtime, run_id = _start_seeded_run()

    snapshot = runtime.current(run_id)

    assert snapshot.trace_header.trace_version == "1.0"
    assert snapshot.trace_header.runtime_revision == "science-environment-runtime/1"
    assert snapshot.trace_header.bundle_id == "eeg-onset-marker-recovery"
    assert snapshot.trace_header.bundle_revision == "1.1.0"
    assert snapshot.trace_header.revision_digest == snapshot.revision_digest
    assert snapshot.trace_header.scenario_id == snapshot.scenario_id
    assert snapshot.trace_header.split == "demonstration"
    assert snapshot.trace_header.seed == 104729
    assert snapshot.trace_header.scenario_digest == snapshot.scenario_digest
    assert snapshot.trace_header.initial_state_digest.startswith("sha256:")
    assert snapshot.trace_header.policy_agent == snapshot.policy_agent
    assert "refractory_route_repaired" not in snapshot.trace_header.model_dump_json()


def test_frozen_run_is_unchanged_by_later_authored_bundle_mutation() -> None:
    authored_bundle = validate_environment_bundle(load_seeded_bundle())
    environment_module = EegMarkerRecoveryModule(authored_bundle)
    runtime = EnvironmentRuntime(environment_module)
    started = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )

    authored_bundle.scenarios[0].initial_state.policy_visible["onset_timeline"][
        "marker_count"
    ] = 99
    detached_module_bundle = environment_module.bundle
    detached_module_bundle.scenarios[0].initial_state.policy_visible[
        "onset_timeline"
    ]["marker_count"] = 98

    unchanged = runtime.current(started.run_id)
    reset = runtime.reset(started.run_id)
    assert unchanged.revision_digest == started.revision_digest
    assert unchanged.observation["onset_timeline"]["marker_count"] == 2
    assert reset.revision_digest == started.revision_digest
    assert reset.observation["onset_timeline"]["marker_count"] == 2


def test_inspect_action_returns_route_evidence_through_runtime() -> None:
    runtime, run_id = _start_seeded_run()

    snapshot = runtime.apply_action(
        run_id,
        EnvironmentAction(type="inspect_onset_route", arguments={}),
    )

    assert snapshot.status == "active"
    assert snapshot.observation["route_inspection"] == {
        "status": "inspected",
        "finding": "Two onset markers follow one simulated lower-right flash.",
    }
    assert [event.type for event in snapshot.trace] == [
        "observation",
        "action",
        "transition",
        "observation",
    ]
    assert snapshot.trace[1].action == {
        "type": "inspect_onset_route",
        "arguments": {},
    }
    assert snapshot.trace[2].transition == {
        "id": "inspect-route",
        "from_state": "onset_recovery",
        "to_state": "onset_recovery",
        "state_revision": 0,
    }
    assert "route_inspected" not in snapshot.model_dump_json()


def test_targeted_repair_invalidates_pre_repair_marker_evidence() -> None:
    runtime, run_id = _start_seeded_run()
    runtime.apply_action(
        run_id,
        EnvironmentAction(type="inspect_onset_route", arguments={}),
    )

    snapshot = runtime.apply_action(
        run_id,
        EnvironmentAction(type="repair_refractory_route", arguments={}),
    )

    assert snapshot.status == "active"
    assert snapshot.observation["freshness"] == {
        "evidence_id": "flash-001",
        "evidence_state_revision": 0,
        "state_revision": 1,
        "status": "stale",
        "reason": "The simulated onset route changed after this flash.",
    }
    assert snapshot.observation["onset_timeline"]["marker_count"] == 2
    assert snapshot.trace[-2].transition == {
        "id": "repair-route",
        "from_state": "onset_recovery",
        "to_state": "onset_recovery",
        "state_revision": 1,
    }
    assert "refractory_route_repaired" not in snapshot.model_dump_json()


def test_repeated_repair_preserves_the_original_evidence_revision() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "repair_refractory_route",
    ):
        snapshot = runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )

    assert snapshot.observation["freshness"] == {
        "evidence_id": "flash-001",
        "evidence_state_revision": 0,
        "state_revision": 2,
        "status": "stale",
        "reason": "The simulated onset route changed after this flash.",
    }


def test_fresh_post_repair_flash_produces_one_current_marker() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in ("inspect_onset_route", "repair_refractory_route"):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )

    snapshot = runtime.apply_action(
        run_id,
        EnvironmentAction(type="present_test_flash", arguments={}),
    )

    assert snapshot.status == "awaiting_verification"
    assert snapshot.permitted_actions == ()
    assert snapshot.observation["onset_timeline"] == {
        "flash_sequence": 2,
        "location": "lower-right",
        "marker_count": 1,
        "evidence_id": "flash-002",
    }
    assert snapshot.observation["freshness"] == {
        "evidence_id": "flash-002",
        "evidence_state_revision": 1,
        "state_revision": 1,
        "status": "current",
    }
    assert snapshot.trace[-2].transition == {
        "id": "test-flash",
        "from_state": "onset_recovery",
        "to_state": "evidence_ready",
        "state_revision": 1,
    }


def test_verifier_passes_only_the_targeted_fresh_recovery_trace() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )

    snapshot = runtime.verify(run_id)

    assert snapshot.status == "completed"
    assert snapshot.verifier_result is not None
    assert snapshot.verifier_result.passed is True
    assert snapshot.verifier_result.terminal_disposition == "recovered"
    assert snapshot.verifier_result.summary == (
        "Recovery verified: one fresh onset marker followed the targeted simulated repair."
    )
    assert snapshot.verifier_result.metrics == {
        "terminal_correctness": 1.0,
        "fresh_validation": 1.0,
        "targeted_intervention": 1.0,
    }
    assert snapshot.verifier_result.evidence == {
        "evidence_id": "flash-002",
        "marker_count": 1,
        "state_revision": 1,
    }
    assert snapshot.result_digest is not None
    assert snapshot.result_digest.startswith("sha256:")
    assert snapshot.trace[-1].type == "verifier"
    assert snapshot.trace[-1].verifier == snapshot.verifier_result.model_dump(mode="json")


def test_wrong_but_permitted_action_does_not_repair_the_onset_route() -> None:
    runtime, run_id = _start_seeded_run()

    after_action = runtime.apply_action(
        run_id,
        EnvironmentAction(type="restart_response_handshake", arguments={}),
    )

    assert after_action.status == "active"
    assert after_action.observation["onset_timeline"]["marker_count"] == 2
    assert after_action.observation["freshness"]["status"] == "current"
    assert after_action.trace[-2].transition == {
        "id": "restart-response",
        "from_state": "onset_recovery",
        "to_state": "onset_recovery",
        "state_revision": 0,
    }

    result = runtime.verify(run_id)
    assert result.verifier_result is not None
    assert result.verifier_result.passed is False
    assert result.verifier_result.metrics["targeted_intervention"] == 0.0
    assert result.verifier_result.terminal_disposition == "failed"


def test_verifier_rejects_stale_pre_repair_evidence() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in ("inspect_onset_route", "repair_refractory_route"):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )

    snapshot = runtime.verify(run_id)

    assert snapshot.verifier_result is not None
    assert snapshot.verifier_result.passed is False
    assert snapshot.verifier_result.metrics == {
        "terminal_correctness": 0.0,
        "fresh_validation": 0.0,
        "targeted_intervention": 1.0,
    }
    assert snapshot.verifier_result.evidence == {
        "evidence_id": "flash-001",
        "marker_count": 2,
        "state_revision": 1,
    }
    assert "No current post-repair test-flash evidence was available." in (
        snapshot.verifier_result.reasons
    )


def test_fresh_duplicate_flash_before_repair_still_fails_recovery() -> None:
    runtime, run_id = _start_seeded_run()
    runtime.apply_action(
        run_id,
        EnvironmentAction(type="present_test_flash", arguments={}),
    )

    snapshot = runtime.verify(run_id)

    assert snapshot.verifier_result is not None
    assert snapshot.verifier_result.passed is False
    assert snapshot.verifier_result.metrics == {
        "terminal_correctness": 0.0,
        "fresh_validation": 0.0,
        "targeted_intervention": 0.0,
    }
    assert snapshot.verifier_result.evidence["marker_count"] == 2
    assert "The targeted simulated repair was not applied." in (
        snapshot.verifier_result.reasons
    )


def test_repair_without_route_inspection_is_not_a_targeted_recovery() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in ("repair_refractory_route", "present_test_flash"):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )

    snapshot = runtime.verify(run_id)

    assert snapshot.verifier_result is not None
    assert snapshot.verifier_result.passed is False
    assert snapshot.verifier_result.metrics == {
        "terminal_correctness": 1.0,
        "fresh_validation": 1.0,
        "targeted_intervention": 0.0,
    }
    assert "The onset route was not inspected before repair." in (
        snapshot.verifier_result.reasons
    )


def test_reset_starts_identical_scenario_without_erasing_source_attempt() -> None:
    runtime, run_id = _start_seeded_run()
    runtime.apply_action(
        run_id,
        EnvironmentAction(type="inspect_onset_route", arguments={}),
    )
    source = runtime.current(run_id)

    reset = runtime.reset(run_id)

    assert reset.run_id != source.run_id
    assert reset.lineage.operation == "reset"
    assert reset.lineage.source_run_id == source.run_id
    assert reset.status == "active"
    assert reset.revision_digest == source.revision_digest
    assert reset.scenario_digest == source.scenario_digest
    assert reset.observation["onset_timeline"]["marker_count"] == 2
    assert reset.observation["freshness"]["status"] == "current"
    assert [event.type for event in reset.trace] == ["observation"]
    assert runtime.current(run_id) == source


def test_replay_reexecutes_actions_and_reproduces_trace_and_result_digests() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )
    source = runtime.verify(run_id)

    report = runtime.replay(run_id)
    replayed = runtime.current(report.replay_run_id)

    assert report.source_run_id == run_id
    assert report.trace_matches is True
    assert report.result_matches is True
    assert report.source_trace_digest == report.replay_trace_digest
    assert report.source_result_digest == report.replay_result_digest
    assert replayed.lineage.operation == "replay"
    assert replayed.lineage.source_run_id == run_id
    assert replayed.trace_digest == source.trace_digest
    assert replayed.result_digest == source.result_digest
    assert replayed.verifier_result == source.verifier_result
    assert runtime.current(run_id) == source


def test_completed_snapshot_cannot_mutate_runtime_result_or_replay_evidence() -> None:
    runtime, run_id = _start_seeded_run()
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        runtime.apply_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )
    returned = runtime.verify(run_id)
    assert returned.verifier_result is not None
    canonical = runtime.current(run_id)

    returned.verifier_result.metrics["terminal_correctness"] = 0.0
    returned.verifier_result.evidence["marker_count"] = 99

    unchanged = runtime.current(run_id)
    assert unchanged == canonical
    report = runtime.replay(run_id)
    assert report.trace_matches is True
    assert report.result_matches is True
    assert runtime.current(report.replay_run_id).verifier_result == canonical.verifier_result


def test_completed_trace_is_persisted_as_append_only_policy_visible_jsonl(
    tmp_path,
) -> None:
    runtime = EnvironmentRuntime(
        EegMarkerRecoveryModule.from_seed(),
        trace_directory=tmp_path,
    )
    started = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )
    artifact = tmp_path / f"{started.run_id}.jsonl"
    initial_bytes = artifact.read_bytes()

    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        runtime.apply_action(
            started.run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )
    completed = runtime.verify(started.run_id)

    serialized = artifact.read_bytes()
    assert serialized.startswith(initial_bytes)
    records = [json.loads(line) for line in serialized.splitlines()]
    assert [record["record_type"] for record in records] == [
        "header",
        *(["event"] * len(completed.trace)),
        "result",
    ]
    assert records[0] == {
        "record_version": "1.0",
        "record_type": "header",
        "run_id": completed.run_id,
        "lineage": {"operation": "start", "source_run_id": None},
        "payload": completed.trace_header.model_dump(mode="json"),
    }
    assert [record["payload"] for record in records[1:-1]] == [
        event.model_dump(mode="json", exclude_none=True) for event in completed.trace
    ]
    assert records[-1] == {
        "record_version": "1.0",
        "record_type": "result",
        "run_id": completed.run_id,
        "trace_digest": completed.trace_digest,
        "result_digest": completed.result_digest,
    }
    visible_artifact = serialized.decode("utf-8")
    for hidden_key in (
        "refractory_route_repaired",
        "route_inspected",
        "inspected_before_repair",
        "repair_transition",
    ):
        assert hidden_key not in visible_artifact


def test_action_arguments_are_json_schema_validated_before_state_changes() -> None:
    document = load_seeded_bundle()
    inspect_action = next(
        action for action in document["actions"] if action["type"] == "inspect_onset_route"
    )
    inspect_action["input_schema"] = {
        "type": "object",
        "properties": {"include_timing": {"type": "boolean"}},
        "additionalProperties": False,
    }
    runtime = EnvironmentRuntime(
        EegMarkerRecoveryModule(validate_environment_bundle(deepcopy(document)))
    )
    started = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )
    before = runtime.current(started.run_id)

    with pytest.raises(RuntimeContractError, match="arguments do not match its schema"):
        runtime.apply_action(
            started.run_id,
            EnvironmentAction(
                type="inspect_onset_route",
                arguments={"include_timing": "yes"},
            ),
        )

    assert runtime.current(started.run_id) == before


def test_runtime_rejects_environment_module_output_that_leaks_hidden_state() -> None:
    class LeakyEegModule(EegMarkerRecoveryModule):
        def apply_action(
            self,
            state: EpisodeState,
            action: EnvironmentAction,
        ) -> EpisodeUpdate:
            update = super().apply_action(state, action)
            observation = update.observation.copy()
            observation["refractory_route_repaired"] = True
            return EpisodeUpdate(
                observation=observation,
                hidden_state=update.hidden_state,
                state_revision=update.state_revision,
                summary=update.summary,
            )

    seeded = EegMarkerRecoveryModule.from_seed()
    runtime = EnvironmentRuntime(LeakyEegModule(seeded.bundle))
    started = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )
    before = runtime.current(started.run_id)

    with pytest.raises(RuntimeContractError, match="Policy-visible observation"):
        runtime.apply_action(
            started.run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert runtime.current(started.run_id) == before


def test_hidden_state_validation_error_does_not_disclose_hidden_values() -> None:
    class InvalidHiddenEegModule(EegMarkerRecoveryModule):
        def apply_action(
            self,
            state: EpisodeState,
            action: EnvironmentAction,
        ) -> EpisodeUpdate:
            update = super().apply_action(state, action)
            hidden_state = update.hidden_state.copy()
            hidden_state["repair_transition"] = "private-hidden-sentinel"
            return EpisodeUpdate(
                observation=update.observation,
                hidden_state=hidden_state,
                state_revision=update.state_revision,
                summary=update.summary,
            )

    seeded = EegMarkerRecoveryModule.from_seed()
    runtime = EnvironmentRuntime(InvalidHiddenEegModule(seeded.bundle))
    started = runtime.start(
        scenario_id="eeg-marker-recovery-001",
        policy_agent=PolicyAgentIdentity(
            id="seeded-policy-agent",
            name="Seeded recovery Policy agent",
        ),
    )

    with pytest.raises(RuntimeContractError) as captured:
        runtime.apply_action(
            started.run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert str(captured.value) == (
        "hidden Environment state does not match the frozen bundle schema"
    )
    assert "private-hidden-sentinel" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
