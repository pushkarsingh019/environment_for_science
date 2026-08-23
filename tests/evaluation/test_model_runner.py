"""Public-contract tests for the provider-neutral scientific model loop."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

import pytest
from pydantic import ValidationError

from environments.eeg import LEGACY_SCENARIO_ID, load_legacy_bundle
from studio.bundle import EnvironmentBundle, validate_environment_bundle
from studio.policy_evaluation.model_runner import (
    CanonicalEvaluationTrace,
    CanonicalModelRunner,
    EvaluationAttempt,
    EvaluationBudgets,
    ModelIdentity,
    ModelMessage,
    ModelProviderFailure,
    ModelRequest,
    ModelResponse,
    ModelResponseMetadata,
    ModelToolCall,
    TokenUsage,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge


class _ScriptedProvider:
    def __init__(self, responses: Sequence[ModelResponse | Exception]) -> None:
        self._responses = iter(responses)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _MalformedProvider:
    def complete(self, request: ModelRequest) -> ModelResponse:
        del request
        return cast(ModelResponse, {"endpoint": "https://10.0.0.7/v1"})


class _FailingPreflightProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.complete_called = False

    def preflight(self, request: object) -> object:
        del request
        raise self._error

    def complete(self, request: ModelRequest) -> ModelResponse:
        del request
        self.complete_called = True
        raise AssertionError("Chat must not run after a failed preflight")


class _ManualMonotonic:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_runner_completes_a_multi_turn_scientific_tool_loop() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider(
        (
            _response("turn-1", "inspect", "inspect_onset_route"),
            _response("turn-2", "repair", "repair_refractory_route"),
            _response("turn-3", "retest", "present_test_flash"),
        )
    )
    runner = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    )

    attempt = runner.run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=ModelIdentity(
            provider="openai-responses",
            requested_model="google/gemma-4-E4B-it",
            adapter_revision="local-gemma-adapter/1",
        ),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.passed is True
    assert [action.type for action in attempt.trace.accepted_actions] == [
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ]
    assert attempt.trace.runtime_trace_digest == attempt.completed_run.trace_digest
    assert attempt.trace.interaction_digest.startswith("sha256:")

    declared_actions = tuple(action.type for action in bundle.actions)
    assert len(provider.requests) == 3
    assert all(
        tuple(tool.name for tool in request.tools) == declared_actions
        for request in provider.requests
    )
    assert provider.requests[0].messages == (
        ModelMessage.user(
            {
                "objective": "Recover trustworthy onset-marker evidence in the simulation.",
                "observation": bundle.scenarios[0].initial_state.policy_visible,
            }
        ),
    )
    assert provider.requests[0].sampling.model_dump(mode="json") == {
        "profile": "base-gemma-development-chat-v1",
        "temperature": 0.0,
        "max_output_tokens": 2048,
        "tool_choice": "auto",
        "top_p": None,
        "seed": None,
        "streaming": False,
        "store": False,
    }
    assert provider.requests[0].budgets.model_dump(mode="json") == {
        "max_turns": 4,
        "max_tool_calls": 4,
        "max_provider_tool_calls": 64,
        "max_episode_seconds": 900,
    }
    assert attempt.trace.sampling == provider.requests[0].sampling
    assert attempt.trace.budgets == provider.requests[0].budgets


def test_terminal_scientific_failure_is_scored_not_reported_as_infrastructure() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider((_response("turn-1", "finish too early", "present_test_flash"),))

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.passed is False
    assert attempt.trace.runtime_events[-1].type == "verifier"
    assert attempt.trace.runtime_trace_digest == attempt.completed_run.trace_digest


def test_unknown_and_malformed_calls_return_safe_results_then_allow_recovery() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider(
        (
            _response("turn-1", "wrong tool", "read_hidden_truth"),
            _response(
                "turn-2",
                "wrong arguments",
                "inspect_onset_route",
                {"include_verifier": True},
            ),
            _response("turn-3", "inspect", "inspect_onset_route"),
            _response("turn-4", "repair", "repair_refractory_route"),
            _response("turn-5", "retest", "present_test_flash"),
        )
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=6,
        max_tool_calls=6,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.completed_run is not None
    assert [result.error_code for result in attempt.trace.tool_results[:2]] == [
        "tool.unknown_action",
        "tool.invalid_arguments",
    ]
    assert [result.status for result in attempt.trace.tool_results] == [
        "error",
        "error",
        "ok",
        "ok",
        "ok",
    ]
    assert [action.type for action in attempt.trace.accepted_actions] == [
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ]
    assert provider.requests[1].messages[-1] == ModelMessage.tool(
        {"status": "error", "error_code": "tool.unknown_action"},
        call_id="episode-call-000001",
        provider_call_id="call-turn-1",
        ordinal=1,
        name="read_hidden_truth",
    )


def test_early_final_reply_is_a_scientific_incomplete_failure() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider(
        (
            ModelResponse(
                response_id="turn-1",
                returned_model="google/gemma-4-E4B-it",
                message=ModelMessage.assistant("I am done."),
            ),
        )
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.passed is False
    assert attempt.completed_run.verifier_result.metrics["reward"] == 0.0
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "model_ended_before_terminal"
    }
    assert attempt.trace.runtime_events[-1].type == "verifier"


def test_local_gemma_identity_requires_runtime_attestation_before_chat() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider((_response("turn-1", "inspect", "inspect_onset_route"),))

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=ModelIdentity(
            provider="local-openai-compatible",
            requested_model="google/gemma-4-E4B-it",
            adapter_revision="local-gemma-openai-chat/1",
        ),
    )

    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.code == "adapter.invalid_attestation"
    assert provider.requests == []


@pytest.mark.parametrize(
    ("preflight_error", "category", "code"),
    (
        (
            TimeoutError("private attestation route timed out with secret-token"),
            "inference",
            "inference.timeout",
        ),
        (
            RuntimeError(
                "https://private-attestation.invalid?token=secret-token"
            ),
            "adapter",
            "adapter.provider_exception",
        ),
    ),
)
def test_preflight_exceptions_are_sanitized_into_durable_infrastructure_attempts(
    preflight_error: Exception,
    category: str,
    code: str,
) -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _FailingPreflightProvider(preflight_error)

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=ModelIdentity(
            provider="local-openai-compatible",
            requested_model="google/gemma-4-E4B-it",
            adapter_revision="local-gemma-openai-chat/1",
        ),
    )

    assert provider.complete_called is False
    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.category == category
    assert attempt.infrastructure_error.code == code
    serialized = attempt.model_dump_json()
    assert "private-attestation.invalid" not in serialized
    assert "secret-token" not in serialized


@pytest.mark.parametrize(
    ("provider_error", "category", "code"),
    (
        (TimeoutError("private endpoint timed out"), "inference", "inference.timeout"),
        (
            RuntimeError("https://private-model.invalid?token=do-not-retain"),
            "adapter",
            "adapter.provider_exception",
        ),
    ),
)
def test_provider_failures_are_safe_and_separate_from_scientific_scores(
    provider_error: Exception,
    category: str,
    code: str,
) -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((provider_error,)),
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.category == category
    assert attempt.infrastructure_error.code == code
    serialized = attempt.model_dump_json()
    assert "private-model.invalid" not in serialized
    assert "do-not-retain" not in serialized


def test_explicit_provider_failure_preserves_only_normalized_safe_identity() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    failure = ModelProviderFailure(
        category="inference",
        code="inference.unavailable",
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((failure,)),
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.category == "inference"
    assert attempt.infrastructure_error.code == "inference.unavailable"
    assert attempt.infrastructure_error.summary == "The inference service failed."


def test_malformed_provider_response_is_normalized_without_retaining_payload() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_MalformedProvider(),
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.category == "adapter"
    assert attempt.infrastructure_error.code == "adapter.invalid_response"
    assert "10.0.0.7" not in attempt.model_dump_json()


@pytest.mark.parametrize(
    "unsafe_identity",
    (
        "https://10.0.0.7/v1/models/gemma",
        "10.0.0.7:8000/v1/models/gemma",
        "/srv/private/models/gemma",
        "model?token=do-not-retain",
    ),
)
def test_model_and_response_identities_reject_endpoints_credentials_and_paths(
    unsafe_identity: str,
) -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        ModelIdentity(
            provider="local-openai-compatible",
            requested_model=unsafe_identity,
            adapter_revision="local-gemma-adapter/1",
        )
    with pytest.raises(ValueError, match="safe identifier"):
        ModelResponse(
            response_id="response-1",
            returned_model=unsafe_identity,
            message=ModelMessage.assistant("done"),
        )
    with pytest.raises(ValueError, match="safe identifier"):
        ModelResponse(
            response_id=unsafe_identity,
            returned_model="google/gemma-4-E4B-it",
            message=ModelMessage.assistant("done"),
        )


def test_turn_budget_exhaustion_is_a_scientific_incomplete_failure() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((_response("turn-1", "inspect", "inspect_onset_route"),)),
        max_turns=1,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.metrics["reward"] == 0.0
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "turn_budget_exhausted"
    }
    assert [action.type for action in attempt.trace.accepted_actions] == ["inspect_onset_route"]


def test_tool_call_budget_preserves_rejected_call_without_executing_it() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    response = ModelResponse(
        response_id="turn-1",
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant(
            "inspect and repair",
            tool_calls=(
                ModelToolCall(
                    call_id="call-inspect",
                    name="inspect_onset_route",
                    arguments={},
                ),
                ModelToolCall(
                    call_id="call-repair",
                    name="repair_refractory_route",
                    arguments={},
                ),
                ModelToolCall(
                    call_id="call-retest",
                    name="present_test_flash",
                    arguments={},
                ),
            ),
        ),
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((response,)),
        max_turns=2,
        max_tool_calls=1,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.metrics["reward"] == 0.0
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "tool_call_budget_exhausted"
    }
    assert [call.name for call in attempt.trace.tool_calls] == [
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ]
    assert [result.status for result in attempt.trace.tool_results] == [
        "ok",
        "error",
        "error",
    ]
    assert [result.error_code for result in attempt.trace.tool_results[1:]] == [
        "tool.budget_exhausted",
        "tool.budget_exhausted",
    ]
    assert [action.type for action in attempt.trace.accepted_actions] == ["inspect_onset_route"]


def test_exact_tool_call_cap_finalizes_without_an_extra_provider_turn() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider((_response("turn-1", "inspect", "inspect_onset_route"),))

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=1,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert len(provider.requests) == 1
    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "tool_call_budget_exhausted"
    }
    assert attempt.completed_run.verifier_result.metrics["reward"] == 0.0
    assert len(attempt.trace.tool_calls) == len(attempt.trace.tool_results) == 1


def test_rejected_calls_do_not_consume_the_accepted_action_budget() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider(
        (
            _response("turn-1", "unknown", "read_hidden_truth"),
            _response("turn-2", "inspect", "inspect_onset_route"),
        )
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=1,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert len(provider.requests) == 2
    assert [result.error_code for result in attempt.trace.tool_results] == [
        "tool.unknown_action",
        None,
    ]
    assert [action.type for action in attempt.trace.accepted_actions] == ["inspect_onset_route"]
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "tool_call_budget_exhausted"
    }


def test_provider_tool_call_batch_is_rejected_before_trace_amplification() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    response = ModelResponse(
        response_id="turn-oversized-tool-batch",
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant(
            "oversized invalid batch",
            tool_calls=tuple(
                ModelToolCall(
                    call_id=f"provider-call-{ordinal}",
                    name="read_hidden_truth",
                    arguments={},
                )
                for ordinal in range(1, 66)
            ),
        ),
    )
    provider = _ScriptedProvider((response,))

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert len(provider.requests) == 1
    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.category == "protocol"
    assert attempt.infrastructure_error.code == "protocol.provider_tool_call_budget_exceeded"
    assert attempt.trace.tool_calls == ()
    assert attempt.trace.tool_results == ()
    assert len(attempt.trace.messages) == 1


def test_provider_tool_call_budget_is_cumulative_across_turns() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())

    def invalid_batch(response_id: str, start: int, size: int) -> ModelResponse:
        return ModelResponse(
            response_id=response_id,
            returned_model="google/gemma-4-E4B-it",
            message=ModelMessage.assistant(
                "bounded invalid batch",
                tool_calls=tuple(
                    ModelToolCall(
                        call_id=f"provider-call-{ordinal}",
                        name="read_hidden_truth",
                        arguments={},
                    )
                    for ordinal in range(start, start + size)
                ),
            ),
        )

    provider = _ScriptedProvider(
        (
            invalid_batch("turn-first-batch", 1, 32),
            invalid_batch("turn-overflow-batch", 33, 33),
        )
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert len(provider.requests) == 2
    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.code == "protocol.provider_tool_call_budget_exceeded"
    assert len(attempt.trace.tool_calls) == 32
    assert len(attempt.trace.tool_results) == 32
    assert all(call.ordinal <= 32 for call in attempt.trace.tool_calls)
    assert "provider-call-33" not in attempt.trace.model_dump_json()


def test_valid_capped_response_is_a_traced_scientific_incomplete_failure() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    response = ModelResponse(
        response_id="turn-capped",
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant(
            "partial call",
            tool_calls=(
                ModelToolCall(
                    call_id="call-capped",
                    name="inspect_onset_route",
                    arguments={},
                ),
            ),
        ),
        metadata=ModelResponseMetadata(
            created_unix_seconds=1787457603,
            finish_reason="length",
            system_fingerprint="vllm-0.26.0-cu129",
        ),
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((response,)),
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.evidence == {
        "termination_reason": "output_budget_exhausted"
    }
    assert attempt.trace.responses[0].metadata == response.metadata
    assert attempt.trace.tool_results[0].error_code == ("tool.output_budget_exhausted")
    assert attempt.trace.accepted_actions == ()


def test_batched_calls_after_terminal_are_preserved_but_never_executed() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    calls = tuple(
        ModelToolCall(call_id=f"call-{index}", name=name, arguments={})
        for index, name in enumerate(
            (
                "inspect_onset_route",
                "repair_refractory_route",
                "present_test_flash",
                "restart_response_handshake",
            ),
            start=1,
        )
    )
    response = ModelResponse(
        response_id="turn-1",
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant("complete the episode", tool_calls=calls),
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((response,)),
        max_turns=2,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.passed is True
    assert [call.call_id for call in attempt.trace.tool_calls] == [
        "episode-call-000001",
        "episode-call-000002",
        "episode-call-000003",
        "episode-call-000004",
    ]
    assert [call.provider_call_id for call in attempt.trace.tool_calls] == [
        call.call_id for call in calls
    ]
    assert [result.status for result in attempt.trace.tool_results] == [
        "ok",
        "ok",
        "ok",
        "error",
    ]
    assert attempt.trace.tool_results[-1].error_code == "tool.episode_terminal"
    assert [action.type for action in attempt.trace.accepted_actions] == [
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ]


def test_duplicate_provider_call_ids_never_become_canonical_idempotency_keys() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    calls = (
        ModelToolCall(call_id="call-duplicate", name="inspect_onset_route", arguments={}),
        ModelToolCall(call_id="call-duplicate", name="repair_refractory_route", arguments={}),
    )
    response = ModelResponse(
        response_id="turn-1",
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant("ambiguous lineage", tool_calls=calls),
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=_ScriptedProvider((response,)),
        max_turns=2,
        max_tool_calls=2,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert [call.provider_call_id for call in attempt.trace.tool_calls] == [
        "call-duplicate",
        "call-duplicate",
    ]
    assert [call.call_id for call in attempt.trace.tool_calls] == [
        "episode-call-000001",
        "episode-call-000002",
    ]
    assert [execution.call_id for execution in attempt.trace.runtime_executions] == [
        "episode-call-000001",
        "episode-call-000002",
    ]


def test_trace_preserves_accounting_and_keeps_interaction_digest_separate() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())

    first = _successful_attempt(bundle, content_prefix="first", with_usage=True)
    second = _successful_attempt(bundle, content_prefix="second", with_usage=False)

    assert first.completed_run is not None
    assert second.completed_run is not None
    assert first.trace.runtime_trace_digest == second.trace.runtime_trace_digest
    assert first.trace.interaction_digest != second.trace.interaction_digest
    assert first.trace.responses[0].returned_model == "google/gemma-4-E4B-it"
    assert first.trace.responses[0].usage == TokenUsage(
        input_tokens=17,
        output_tokens=3,
        total_tokens=20,
        cached_input_tokens=2,
    )
    assert [event.type for event in first.trace.runtime_events] == [
        "observation",
        "action",
        "transition",
        "observation",
        "action",
        "transition",
        "observation",
        "action",
        "transition",
        "observation",
        "verifier",
    ]


def test_terminal_tool_result_has_exact_call_lineage_and_is_digest_bound() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    attempt = _successful_attempt(bundle, content_prefix="lineage", with_usage=True)

    terminal_call = attempt.trace.tool_calls[-1]
    terminal_result = attempt.trace.tool_results[-1]
    terminal_message = next(
        message
        for message in attempt.trace.messages
        if message.role == "tool" and message.tool_call_id == terminal_call.call_id
    )
    assert terminal_result.call_id == terminal_call.call_id
    assert terminal_result.name == terminal_call.name
    assert terminal_result.status == "ok"
    assert terminal_message.tool_name == terminal_call.name
    assert terminal_message.content == terminal_result.policy_payload()

    tampered = attempt.trace.model_dump(mode="json")
    tampered["tool_results"][-1]["observation"]["summary"] = "tampered result"
    tampered["messages"][-1]["content"]["observation"]["summary"] = "tampered result"
    tampered["runtime_executions"][-1]["observation"]["summary"] = "tampered result"
    with pytest.raises(ValidationError, match="interaction digest"):
        CanonicalEvaluationTrace.model_validate_json(json.dumps(tampered))

    tampered_runtime = attempt.trace.model_dump(mode="json")
    tampered_runtime["runtime_events"][0]["summary"] = "tampered runtime evidence"
    with pytest.raises(ValidationError, match="interaction digest"):
        CanonicalEvaluationTrace.model_validate_json(json.dumps(tampered_runtime))


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("passed",), False),
        (("terminal_disposition",), "failed"),
        (("outcome_category",), "tampered-category"),
        (("summary",), "Tampered verifier summary."),
        (("metrics", "reward"), 0.25),
        (("evidence",), {"tampered": True}),
        (("reasons",), ["Tampered verifier reason."]),
        (("verifier_id",), "tampered-verifier"),
        (("result_version",), "tampered-result-version"),
    ),
)
def test_attempt_result_must_match_every_canonical_verifier_event_field(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    attempt = _successful_attempt(bundle, content_prefix="result-binding", with_usage=True)
    document = attempt.model_dump(mode="json")
    verifier_result = document["completed_run"]["verifier_result"]
    target = verifier_result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValidationError, match="does not match its canonical trace"):
        EvaluationAttempt.model_validate_json(json.dumps(document))


def test_attempt_result_digest_is_recomputed_from_the_canonical_verifier_event() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    attempt = _successful_attempt(bundle, content_prefix="result-digest", with_usage=True)
    document = attempt.model_dump(mode="json")
    document["completed_run"]["result_digest"] = "sha256:" + "0" * 64

    with pytest.raises(ValidationError, match="result digest does not match"):
        EvaluationAttempt.model_validate_json(json.dumps(document))


def test_trace_rejects_reordered_messages_and_unlinked_response_records() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    attempt = _successful_attempt(bundle, content_prefix="ordering", with_usage=True)
    document = attempt.trace.model_dump(mode="json")
    first_tool_index = next(
        index for index, message in enumerate(document["messages"]) if message["role"] == "tool"
    )
    first_tool = document["messages"].pop(first_tool_index)
    next_assistant_index = next(
        index
        for index, message in enumerate(document["messages"])
        if index > first_tool_index and message["role"] == "assistant"
    )
    document["messages"].insert(next_assistant_index + 1, first_tool)

    with pytest.raises(ValidationError, match="immediately linked tool messages"):
        CanonicalEvaluationTrace.model_validate_json(json.dumps(document))

    unlinked = attempt.trace.model_dump(mode="json")
    unlinked["responses"][0]["response_id"] = "different-safe-response-id"
    with pytest.raises(ValidationError, match="one-to-one"):
        CanonicalEvaluationTrace.model_validate_json(json.dumps(unlinked))


def test_episode_deadline_caps_transport_and_fails_unscored_with_complete_lineage() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    clock = _ManualMonotonic()

    class _DeadlineProvider(_ScriptedProvider):
        def complete(self, request: ModelRequest) -> ModelResponse:
            response = super().complete(request)
            clock.now = 901.0
            return response

    provider = _DeadlineProvider((_response("turn-1", "inspect", "inspect_onset_route"),))

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=64,
        max_tool_calls=64,
        monotonic=clock,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert provider.requests[0].transport_timeout_seconds == 900.0
    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.code == "inference.episode_timeout"
    assert attempt.trace.budgets == EvaluationBudgets(
        max_turns=64,
        max_tool_calls=64,
        max_episode_seconds=900,
    )
    assert attempt.trace.tool_calls[0].call_id == "episode-call-000001"
    assert attempt.trace.tool_calls[0].provider_call_id == "call-turn-1"
    assert attempt.trace.tool_results[0].error_code == "tool.episode_timeout"
    assert attempt.trace.accepted_actions == ()
    assert attempt.trace.runtime_executions == ()


def test_episode_deadline_expiring_during_verification_stays_unscored() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    clock = _ManualMonotonic()

    class _DeadlineOnFinalizeBridge(EvaluationRuntimeBridge):
        def finalize(self, state):  # type: ignore[no-untyped-def]
            completed = super().finalize(state)
            clock.now = 901.0
            return completed

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=_DeadlineOnFinalizeBridge(bundle),
        provider=_ScriptedProvider((_response("turn-1", "finish", "present_test_flash"),)),
        max_turns=4,
        max_tool_calls=4,
        monotonic=clock,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.completed_run is None
    assert attempt.infrastructure_error is not None
    assert attempt.infrastructure_error.code == "inference.episode_timeout"
    assert attempt.trace.tool_results[0].status == "ok"
    assert attempt.trace.runtime_events[-1].type == "observation"


def test_provider_requests_exclude_hidden_authoring_and_verifier_material() -> None:
    bundle = validate_environment_bundle(load_legacy_bundle())
    provider = _ScriptedProvider(
        (
            _response("turn-1", "inspect", "inspect_onset_route"),
            _response("turn-2", "repair", "repair_refractory_route"),
            _response("turn-3", "retest", "present_test_flash"),
        )
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )

    assert attempt.completed_run is not None
    provider_view = "\n".join(request.model_dump_json() for request in provider.requests)
    for forbidden in (
        "refractory_route_repaired",
        "inspected_before_repair",
        "repair_transition",
        "one-fresh-marker-after-targeted-repair",
        "success_state",
        "authoring",
    ):
        assert forbidden not in provider_view
    assert all(
        tuple(tool.name for tool in request.tools) == bundle.action_types
        for request in provider.requests
    )


def _response(
    response_id: str,
    content: str,
    action: str,
    arguments: dict[str, object] | None = None,
) -> ModelResponse:
    return ModelResponse(
        response_id=response_id,
        returned_model="google/gemma-4-E4B-it",
        message=ModelMessage.assistant(
            content,
            tool_calls=(
                ModelToolCall(
                    call_id=f"call-{response_id}",
                    name=action,
                    arguments=arguments or {},
                ),
            ),
        ),
    )


def _model() -> ModelIdentity:
    return ModelIdentity(
        provider="openai-responses",
        requested_model="google/gemma-4-E4B-it",
        adapter_revision="local-gemma-adapter/1",
    )


def _successful_attempt(
    bundle: EnvironmentBundle,
    *,
    content_prefix: str,
    with_usage: bool,
) -> EvaluationAttempt:
    first_response = _response(
        f"{content_prefix}-1", f"{content_prefix} inspect", "inspect_onset_route"
    )
    if with_usage:
        first_response = first_response.model_copy(
            update={
                "usage": TokenUsage(
                    input_tokens=17,
                    output_tokens=3,
                    total_tokens=20,
                    cached_input_tokens=2,
                )
            }
        )
    provider = _ScriptedProvider(
        (
            first_response,
            _response(
                f"{content_prefix}-2",
                f"{content_prefix} repair",
                "repair_refractory_route",
            ),
            _response(
                f"{content_prefix}-3",
                f"{content_prefix} retest",
                "present_test_flash",
            ),
        )
    )
    return CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=4,
        max_tool_calls=4,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_model(),
    )
