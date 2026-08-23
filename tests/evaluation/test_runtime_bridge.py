"""Conformance tests for replaying evaluations through the product Runtime."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from environments.eeg.curriculum import load_training_scenario_set
from studio.policy_evaluation.runtime_bridge import (
    CanonicalCallConflictError,
    EvaluationRuntimeBridge,
)
from studio.registry import EnvironmentRegistry
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    IncompleteTerminationReason,
    PolicyAgentIdentity,
    RunSnapshot,
    RuntimeContractError,
)

POLICY = PolicyAgentIdentity(
    id="evaluation-conformance-policy",
    name="Evaluation conformance policy",
)
NOMINAL_SCENARIO = "eeg-47d16a3170af262f"
SUCCESSFUL_ACTIONS = (
    EnvironmentAction(type="inspect_configuration", arguments={}),
    EnvironmentAction(type="inspect_eeg_signals", arguments={}),
    EnvironmentAction(type="inspect_onset_route", arguments={}),
    EnvironmentAction(type="inspect_response_timeline", arguments={}),
    EnvironmentAction(type="inspect_recording_timeline", arguments={}),
    EnvironmentAction(type="complete_preflight", arguments={}),
)


def test_bridge_starts_with_direct_runtime_parity_and_public_state_only() -> None:
    bundle = load_training_scenario_set().environment_bundle
    registry = EnvironmentRegistry.from_seeded_environments()
    direct_runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    bridge = EvaluationRuntimeBridge(bundle)

    direct = direct_runtime.start(NOMINAL_SCENARIO, POLICY)
    replayable = bridge.start(NOMINAL_SCENARIO, POLICY)

    _assert_public_parity(direct, replayable.snapshot)
    assert replayable.accepted_actions == ()
    assert set(replayable.model_dump()) == {
        "bundle_id",
        "bundle_revision",
        "revision_digest",
        "scenario_id",
        "scenario_digest",
        "episode_id",
        "policy_agent",
        "accepted_actions",
        "executions",
        "snapshot",
    }
    with pytest.raises(ValidationError):
        replayable.scenario_id = "another-scenario"


def test_apply_replays_prior_actions_and_matches_direct_action_effects() -> None:
    bundle = load_training_scenario_set().environment_bundle
    registry = EnvironmentRegistry.from_seeded_environments()
    direct_runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    bridge = EvaluationRuntimeBridge(bundle)
    direct = direct_runtime.start(NOMINAL_SCENARIO, POLICY)
    replayable = bridge.start(NOMINAL_SCENARIO, POLICY)
    first_action = EnvironmentAction(type="inspect_configuration", arguments={})
    second_action = EnvironmentAction(type="inspect_eeg_signals", arguments={})

    direct = direct_runtime.apply_action(direct.run_id, first_action)
    replayable = bridge.apply(replayable, first_action)
    _assert_public_parity(direct, replayable.snapshot)

    direct = direct_runtime.apply_action(direct.run_id, second_action)
    replayable = bridge.apply(replayable, second_action)

    _assert_public_parity(direct, replayable.snapshot)
    assert replayable.accepted_actions == (first_action, second_action)
    assert [event.type for event in replayable.snapshot.trace] == [
        "observation",
        "action",
        "transition",
        "observation",
        "action",
        "transition",
        "observation",
    ]
    assert replayable.snapshot.trace[-2].transition == direct.trace[-2].transition


def test_canonical_call_retry_returns_cached_execution_without_a_second_transition() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    initial = bridge.start(NOMINAL_SCENARIO, POLICY)
    action = SUCCESSFUL_ACTIONS[0]

    first = bridge.apply_idempotent(
        initial,
        call_id="episode-call-000001",
        ordinal=1,
        action=action,
    )
    retried = bridge.apply_idempotent(
        first.state,
        call_id="episode-call-000001",
        ordinal=1,
        action=action,
    )

    assert first.cache_hit is False
    assert retried.cache_hit is True
    assert first.state.episode_id == initial.episode_id
    assert first.state.snapshot.run_id != initial.snapshot.run_id
    assert retried.observation == first.observation
    assert retried.state.accepted_actions == (action,)
    assert retried.state.snapshot.trace == first.state.snapshot.trace
    assert [event.type for event in retried.state.snapshot.trace].count("action") == 1
    assert retried.state.executions[0].retry_count == 1
    assert retried.state.executions[0].cache_hit is True


def test_canonical_call_conflicting_reuse_fails_closed_without_mutation() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    first = bridge.apply_idempotent(
        bridge.start(NOMINAL_SCENARIO, POLICY),
        call_id="episode-call-000001",
        ordinal=1,
        action=SUCCESSFUL_ACTIONS[0],
    )
    before = first.state.model_dump(mode="json")

    with pytest.raises(CanonicalCallConflictError, match="conflicting reuse"):
        bridge.apply_idempotent(
            first.state,
            call_id="episode-call-000001",
            ordinal=1,
            action=SUCCESSFUL_ACTIONS[1],
        )

    assert first.state.model_dump(mode="json") == before


def test_separate_episodes_produce_distinct_canonical_execution_identities() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    first_episode = bridge.start(NOMINAL_SCENARIO, POLICY)
    second_episode = bridge.start(NOMINAL_SCENARIO, POLICY)

    first = bridge.apply_idempotent(
        first_episode,
        call_id="episode-call-000001",
        ordinal=1,
        action=SUCCESSFUL_ACTIONS[0],
    )
    second = bridge.apply_idempotent(
        second_episode,
        call_id="episode-call-000001",
        ordinal=1,
        action=SUCCESSFUL_ACTIONS[0],
    )

    assert first_episode.episode_id != second_episode.episode_id
    assert first.execution_id != second.execution_id


def test_tampered_execution_identity_cannot_be_returned_from_the_cache() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    first = bridge.apply_idempotent(
        bridge.start(NOMINAL_SCENARIO, POLICY),
        call_id="episode-call-000001",
        ordinal=1,
        action=SUCCESSFUL_ACTIONS[0],
    )
    document = first.state.model_dump(mode="json")
    document["executions"][0]["execution_id"] = f"sha256:{'0' * 64}"
    tampered = type(first.state).model_validate(document)

    with pytest.raises(RuntimeContractError, match="execution identity"):
        bridge.apply_idempotent(
            tampered,
            call_id="episode-call-000001",
            ordinal=1,
            action=SUCCESSFUL_ACTIONS[0],
        )

    tampered_episode_document = first.state.model_dump(mode="json")
    tampered_episode_document["episode_id"] = "forged-episode-id"
    tampered_episode = type(first.state).model_validate(tampered_episode_document)
    with pytest.raises(RuntimeContractError, match="execution identity"):
        bridge.apply_idempotent(
            tampered_episode,
            call_id="episode-call-000001",
            ordinal=1,
            action=SUCCESSFUL_ACTIONS[0],
        )


def test_finalize_matches_direct_verifier_metrics_results_and_digests() -> None:
    bundle = load_training_scenario_set().environment_bundle
    registry = EnvironmentRegistry.from_seeded_environments()
    direct_runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    bridge = EvaluationRuntimeBridge(bundle)
    direct = direct_runtime.start(NOMINAL_SCENARIO, POLICY)
    replayable = bridge.start(NOMINAL_SCENARIO, POLICY)
    for action in SUCCESSFUL_ACTIONS:
        direct = direct_runtime.apply_action(direct.run_id, action)
        replayable = bridge.apply(replayable, action)

    direct_result = direct_runtime.verify(direct.run_id)
    bridge_result = bridge.finalize(replayable)

    _assert_public_parity(direct_result, bridge_result)
    assert bridge_result.verifier_result == direct_result.verifier_result
    assert bridge_result.verifier_result is not None
    assert bridge_result.verifier_result.metrics == direct_result.verifier_result.metrics
    assert bridge_result.result_digest == direct_result.result_digest
    assert bridge_result.trace_digest == direct_result.trace_digest


@pytest.mark.parametrize(
    "termination_reason",
    (
        "model_ended_before_terminal",
        "output_budget_exhausted",
        "turn_budget_exhausted",
        "tool_call_budget_exhausted",
    ),
)
def test_finalize_incomplete_matches_direct_runtime_and_is_replayable(
    termination_reason: IncompleteTerminationReason,
) -> None:
    bundle = load_training_scenario_set().environment_bundle
    registry = EnvironmentRegistry.from_seeded_environments()
    direct_runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    bridge = EvaluationRuntimeBridge(bundle)
    direct = direct_runtime.start(NOMINAL_SCENARIO, POLICY)
    replayable = bridge.start(NOMINAL_SCENARIO, POLICY)
    action = SUCCESSFUL_ACTIONS[0]
    direct = direct_runtime.apply_action(direct.run_id, action)
    replayable = bridge.apply(replayable, action)

    direct_result = direct_runtime.finalize_incomplete(
        direct.run_id,
        termination_reason=termination_reason,
    )
    bridge_result = bridge.finalize_incomplete(
        replayable,
        termination_reason=termination_reason,
    )

    _assert_public_parity(direct_result, bridge_result)
    assert bridge_result.verifier_result is not None
    assert bridge_result.verifier_result.metrics["reward"] == 0.0
    assert bridge_result.verifier_result.evidence == {"termination_reason": termination_reason}


def test_invalid_action_does_not_mutate_replayable_state() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    state = bridge.start(NOMINAL_SCENARIO, POLICY)
    before = state.model_dump(mode="json")

    with pytest.raises(RuntimeContractError, match="unknown action"):
        bridge.apply(
            state,
            EnvironmentAction(type="read_hidden_truth", arguments={}),
        )

    assert state.model_dump(mode="json") == before
    assert state.accepted_actions == ()


def test_states_are_isolated_and_reconstruct_from_only_accepted_actions() -> None:
    bundle = load_training_scenario_set().environment_bundle
    bridge = EvaluationRuntimeBridge(bundle)
    first = bridge.start(NOMINAL_SCENARIO, POLICY)
    second = bridge.start(NOMINAL_SCENARIO, POLICY)
    second_before = second.model_dump(mode="json")

    advanced = bridge.apply(first, SUCCESSFUL_ACTIONS[0])

    assert first.accepted_actions == ()
    assert len(first.snapshot.trace) == 1
    assert advanced.accepted_actions == (SUCCESSFUL_ACTIONS[0],)
    assert [event.type for event in advanced.snapshot.trace] == [
        "observation",
        "action",
        "transition",
        "observation",
    ]
    assert second.model_dump(mode="json") == second_before
    assert second.snapshot.trace_digest == first.snapshot.trace_digest
    assert advanced.snapshot.trace_digest != first.snapshot.trace_digest


def _assert_public_parity(direct: RunSnapshot, bridged: RunSnapshot) -> None:
    assert bridged.scenario_id == direct.scenario_id
    assert bridged.revision_digest == direct.revision_digest
    assert bridged.scenario_digest == direct.scenario_digest
    assert bridged.policy_agent == direct.policy_agent
    assert bridged.status == direct.status
    assert bridged.observation == direct.observation
    assert bridged.permitted_actions == direct.permitted_actions
    assert bridged.trace == direct.trace
    assert bridged.trace_digest == direct.trace_digest
    assert bridged.verifier_result == direct.verifier_result
    assert bridged.result_digest == direct.result_digest
    assert bridged.trace_header == direct.trace_header
