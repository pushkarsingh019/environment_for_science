"""Ticket 09 protocol fixtures for the native Gemini Interactions adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from studio.application import create_app
from studio.policy_evaluation.gemini_interactions import (
    GEMINI_INTERACTIONS_ADAPTER_REVISION,
    GEMINI_INTERACTIONS_MODEL,
    GEMINI_INTERACTIONS_SAMPLING,
    GeminiInteractionsProvider,
    gemini_credential_ready,
)
from studio.policy_evaluation.model_runner import (
    CanonicalModelRunner,
    EvaluationBudgets,
    ModelIdentity,
    ModelMessage,
    ModelProviderFailure,
    ModelRequest,
    ModelTool,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from studio.registry import EnvironmentRegistry


class _FixtureTransport:
    def __init__(
        self,
        responses: list[tuple[int, Mapping[str, str], object]],
    ) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, Any]] = []

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], object]:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return next(self.responses)


def _identity() -> ModelIdentity:
    return ModelIdentity(
        provider="gemini-interactions",
        requested_model=GEMINI_INTERACTIONS_MODEL,
        adapter_revision=GEMINI_INTERACTIONS_ADAPTER_REVISION,
    )


def _tools() -> tuple[ModelTool, ...]:
    return (
        ModelTool(
            name="inspect_onset_route",
            description="Inspect only the simulated onset route.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    )


def _request(messages: tuple[ModelMessage, ...], *, turn: int = 1) -> ModelRequest:
    return ModelRequest(
        model=_identity(),
        turn=turn,
        messages=messages,
        tools=_tools(),
        sampling=GEMINI_INTERACTIONS_SAMPLING,
        budgets=EvaluationBudgets(max_turns=64, max_tool_calls=64),
        transport_timeout_seconds=30.0,
    )


def _interaction_fixture(*, interaction_id: str = "interaction-001") -> dict[str, object]:
    return {
        "id": interaction_id,
        "object": "interaction",
        "created_at": 1_800_000_100,
        "model": GEMINI_INTERACTIONS_MODEL,
        "status": "completed",
        "steps": [
            {
                "type": "thought",
                "id": "thought-001",
                "thought_signature": "signed-thought-001",
                "content": "opaque-provider-reasoning",
            },
            {
                "type": "function_call",
                "id": "function-001",
                "call_id": "gemini-call-001",
                "name": "inspect_onset_route",
                "arguments": {},
                "thought_signature": "signed-call-001",
            },
        ],
        "usage": {
            "total_input_tokens": 100,
            "total_cached_tokens": 10,
            "total_output_tokens": 20,
            "total_thought_tokens": 30,
            "total_tool_use_tokens": 4,
            "total_tokens": 150,
            "input_token_details": [{"modality": "TEXT", "tokens": 100}],
        },
    }


def test_stateless_interactions_replays_signed_steps_and_linked_function_result() -> None:
    transport = _FixtureTransport(
        [
            (200, {"x-request-id": "google-request-001"}, _interaction_fixture()),
            (
                200,
                {"x-request-id": "google-request-002"},
                {
                    "id": "interaction-002",
                    "object": "interaction",
                    "created_at": 1_800_000_101,
                    "model": GEMINI_INTERACTIONS_MODEL,
                    "status": "completed",
                    "steps": [
                        {
                            "type": "message",
                            "id": "message-002",
                            "role": "assistant",
                            "content": "The simulated onset evidence is current.",
                        }
                    ],
                    "usage": {
                        "total_input_tokens": 140,
                        "total_cached_tokens": 20,
                        "total_output_tokens": 12,
                        "total_thought_tokens": 0,
                        "total_tool_use_tokens": 2,
                        "total_tokens": 152,
                    },
                },
            ),
        ]
    )
    provider = GeminiInteractionsProvider(
        api_key="gemini-test-secret-value",
        transport=transport,
        timeout_seconds=60.0,
        sleeper=lambda _seconds: None,
    )
    user = ModelMessage.user({"objective": "Inspect the simulation."})

    first = provider.complete(_request((user,)))
    assistant = ModelMessage.assistant(
        str(first.message.content),
        tool_calls=first.message.tool_calls,
        provider_state=first.message.provider_state,
        response_id=first.response_id,
        response_turn=1,
    )
    result = ModelMessage.tool(
        {"status": "ok", "observation": {"summary": "Synthetic evidence loaded."}},
        call_id="episode-call-000001",
        provider_call_id="gemini-call-001",
        ordinal=1,
        name="inspect_onset_route",
    )
    second = provider.complete(_request((user, assistant, result), turn=2))

    assert first.message.provider_state == tuple(_interaction_fixture()["steps"])
    assert first.message.tool_calls[0].call_id == "gemini-call-001"
    assert first.usage is not None
    assert first.usage.model_dump() == {
        "input_tokens": 90,
        "output_tokens": 50,
        "total_tokens": 150,
        "cached_input_tokens": 10,
        "reasoning_tokens": 30,
    }
    assert first.metadata is not None
    assert first.metadata.provider_usage == _interaction_fixture()["usage"]
    assert second.message.content == "The simulated onset evidence is current."

    payload = transport.requests[0]["payload"]
    assert payload["model"] == GEMINI_INTERACTIONS_MODEL
    assert payload["store"] is False
    assert payload["stream"] is False
    assert payload["generation_config"] == {
        "thinking_level": "medium",
        "max_output_tokens": 2048,
    }
    assert payload["tool_choice"] == "auto"
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "inspect_onset_route",
            "description": "Inspect only the simulated onset route.",
            "parameters": _tools()[0].input_schema,
        }
    ]
    assert all(tool["type"] == "function" for tool in payload["tools"])
    assert "previous_interaction_id" not in payload
    second_input = transport.requests[1]["payload"]["input"]
    assert second_input[1:3] == [*_interaction_fixture()["steps"]]
    assert second_input[3] == {
        "type": "function_result",
        "call_id": "gemini-call-001",
        "name": "inspect_onset_route",
        "result": result.content,
    }
    serialized_payloads = json.dumps(
        [request["payload"] for request in transport.requests]
    )
    assert "gemini-test-secret-value" not in serialized_payloads
    assert "gemini-test-secret-value" not in repr(provider)


def test_missing_thought_signature_and_malformed_call_fail_safely() -> None:
    missing_signature = _interaction_fixture()
    del missing_signature["steps"][0]["thought_signature"]  # type: ignore[index]
    provider = GeminiInteractionsProvider(
        api_key="test-secret",
        transport=_FixtureTransport([(200, {}, missing_signature)]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(ModelProviderFailure) as raised:
        provider.complete(_request((ModelMessage.user({"objective": "Inspect."}),)))
    assert raised.value.normalized_error.code == "adapter.invalid_response"

    malformed = _interaction_fixture()
    malformed["steps"] = [
        {
            "type": "function_call",
            "id": "function-001",
            "call_id": "gemini-call-001",
            "name": "inspect_onset_route",
            "arguments": "not-an-object",
            "thought_signature": "signed-call-001",
        }
    ]
    malformed_provider = GeminiInteractionsProvider(
        api_key="test-secret",
        transport=_FixtureTransport([(200, {}, malformed)]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    response = malformed_provider.complete(
        _request((ModelMessage.user({"objective": "Inspect."}),))
    )
    assert response.message.tool_calls[0].arguments == {
        "__provider_invalid_arguments__": True
    }


@pytest.mark.parametrize(
    ("statuses", "code"),
    (
        ([429, 429, 429], "inference.overloaded"),
        ([503, 503, 503], "inference.unavailable"),
        ([403], "adapter.protocol_error"),
    ),
)
def test_retries_rate_limits_and_provider_failures_are_normalized(
    statuses: list[int],
    code: str,
) -> None:
    transport = _FixtureTransport(
        [
            (status, {"retry-after": "0"}, {"error": {"message": "private detail"}})
            for status in statuses
        ]
    )
    provider = GeminiInteractionsProvider(
        api_key="test-secret",
        transport=transport,
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(ModelProviderFailure) as raised:
        provider.complete(_request((ModelMessage.user({"objective": "Inspect."}),)))
    assert raised.value.normalized_error.code == code
    assert len(transport.requests) == len(statuses)
    assert "private detail" not in str(raised.value)


def test_canonical_runner_preserves_signed_lineage_and_runtime_parity() -> None:
    bundle = EnvironmentRegistry.from_seeded_environments().bundle(
        "mesoscope-four-region-handoff"
    )
    actions = (
        "inspect_sealed_handoff",
        "run_mock_acquisition",
        "validate_mock_package",
        "accept_mock_package",
    )
    fixtures: list[tuple[int, Mapping[str, str], object]] = []
    for turn, action in enumerate(actions, start=1):
        fixture = _interaction_fixture(interaction_id=f"interaction-{turn:03d}")
        fixture["steps"] = [
            {
                "type": "thought",
                "id": f"thought-{turn:03d}",
                "thought_signature": f"signed-thought-{turn:03d}",
                "content": f"opaque-lineage-{turn}",
            },
            {
                "type": "function_call",
                "id": f"function-{turn:03d}",
                "call_id": f"gemini-call-{turn:03d}",
                "name": action,
                "arguments": {},
                "thought_signature": f"signed-call-{turn:03d}",
            },
        ]
        fixtures.append((200, {"x-request-id": f"google-request-{turn:03d}"}, fixture))
    provider = GeminiInteractionsProvider(
        api_key="trace-test-secret",
        transport=_FixtureTransport(fixtures),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=8,
        max_tool_calls=8,
        sampling=GEMINI_INTERACTIONS_SAMPLING,
        profile="hosted-reference-smoke-v1",
    ).run(
        scenario_id="mesoscope-demo-001",
        objective="Inspect and disposition only the sealed synthetic package.",
        model=_identity(),
    )

    assert attempt.infrastructure_error is None
    assert attempt.completed_run is not None
    assert attempt.completed_run.verifier_result is not None
    assert attempt.completed_run.verifier_result.summary == "MOCK PACKAGE VERIFIED"
    assistants = [message for message in attempt.trace.messages if message.role == "assistant"]
    assert all(
        message.provider_state[0]["thought_signature"].startswith("signed-thought-")
        for message in assistants
    )
    assert [call.provider_call_id for call in attempt.trace.tool_calls] == [
        f"gemini-call-{turn:03d}" for turn in range(1, 5)
    ]
    assert "trace-test-secret" not in attempt.model_dump_json()


def test_readiness_exact_model_and_console_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert gemini_credential_ready({}) is False
    assert gemini_credential_ready({"GEMINI_API_KEY": "configured"}) is True

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(create_app(artifact_root=tmp_path / "missing")) as client:
        readiness = client.get("/api/provider-readiness")
        smoke = client.post("/api/hosted-smokes/gemini")
    assert readiness.status_code == 200
    assert readiness.json()["gemini"] == {
        "provider": "gemini",
        "route": "interactions",
        "requested_model": GEMINI_INTERACTIONS_MODEL,
        "adapter_revision": GEMINI_INTERACTIONS_ADAPTER_REVISION,
        "credential_configured": False,
        "status": "missing_credential",
    }
    assert smoke.status_code == 409

    provider = GeminiInteractionsProvider(
        api_key="test-secret",
        transport=_FixtureTransport([(200, {}, _interaction_fixture())]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    alias = _request((ModelMessage.user({"objective": "Inspect."}),)).model_copy(
        update={
            "model": ModelIdentity(
                provider="gemini-interactions",
                requested_model="gemini-flash-latest",
                adapter_revision=GEMINI_INTERACTIONS_ADAPTER_REVISION,
            )
        }
    )
    with pytest.raises(ModelProviderFailure) as raised:
        provider.complete(alias)
    assert raised.value.normalized_error.code == "adapter.protocol_error"
