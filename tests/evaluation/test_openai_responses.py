"""Ticket 08 protocol fixtures for the native OpenAI Responses adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from studio.application import create_app
from studio.policy_evaluation.model_runner import (
    CanonicalModelRunner,
    EvaluationBudgets,
    ModelIdentity,
    ModelMessage,
    ModelProviderFailure,
    ModelRequest,
    ModelTool,
)
from studio.policy_evaluation.openai_responses import (
    OPENAI_RESPONSES_ADAPTER_REVISION,
    OPENAI_RESPONSES_MODEL,
    OPENAI_RESPONSES_SAMPLING,
    OpenAIResponsesProvider,
    openai_credential_ready,
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
        provider="openai-responses",
        requested_model=OPENAI_RESPONSES_MODEL,
        adapter_revision=OPENAI_RESPONSES_ADAPTER_REVISION,
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
        sampling=OPENAI_RESPONSES_SAMPLING,
        budgets=EvaluationBudgets(max_turns=64, max_tool_calls=64),
        transport_timeout_seconds=30.0,
    )


def _response_fixture(*, response_id: str = "resp_001") -> dict[str, object]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1_800_000_000,
        "model": OPENAI_RESPONSES_MODEL,
        "status": "completed",
        "service_tier": "default",
        "output": [
            {
                "type": "reasoning",
                "id": "rs_001",
                "encrypted_content": "opaque-reasoning-ciphertext",
                "summary": [],
            },
            {
                "type": "function_call",
                "id": "fc_001",
                "call_id": "call_001",
                "name": "inspect_onset_route",
                "arguments": "{}",
                "status": "completed",
            },
        ],
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 20},
            "output_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 12},
            "total_tokens": 138,
        },
    }


def test_stateless_responses_replays_every_output_item_and_linked_tool_result() -> None:
    transport = _FixtureTransport(
        [
            (200, {"x-request-id": "req_001"}, _response_fixture()),
            (
                200,
                {"x-request-id": "req_002"},
                {
                    "id": "resp_002",
                    "object": "response",
                    "created_at": 1_800_000_001,
                    "model": OPENAI_RESPONSES_MODEL,
                    "status": "completed",
                    "service_tier": "default",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_002",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "The simulated onset evidence is current.",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 160,
                        "output_tokens": 10,
                        "total_tokens": 170,
                    },
                },
            ),
        ]
    )
    provider = OpenAIResponsesProvider(
        api_key="openai-test-secret-value",
        transport=transport,
        timeout_seconds=60.0,
        sleeper=lambda _seconds: None,
    )
    user = ModelMessage.user({"objective": "Inspect the simulation."})

    first = provider.complete(_request((user,)))
    canonical_assistant = ModelMessage.assistant(
        str(first.message.content),
        tool_calls=first.message.tool_calls,
        provider_state=first.message.provider_state,
        response_id=first.response_id,
        response_turn=1,
    )
    tool_result = ModelMessage.tool(
        {"status": "ok", "observation": {"summary": "Synthetic evidence loaded."}},
        call_id="episode-call-000001",
        provider_call_id="call_001",
        ordinal=1,
        name="inspect_onset_route",
    )
    second = provider.complete(_request((user, canonical_assistant, tool_result), turn=2))

    assert first.returned_model == OPENAI_RESPONSES_MODEL
    assert first.message.tool_calls[0].call_id == "call_001"
    assert first.message.provider_state == tuple(_response_fixture()["output"])
    assert first.usage is not None
    assert first.usage.model_dump() == {
        "input_tokens": 120,
        "output_tokens": 18,
        "total_tokens": 138,
        "cached_input_tokens": 20,
        "reasoning_tokens": 12,
    }
    assert second.message.content == "The simulated onset evidence is current."

    first_payload = transport.requests[0]["payload"]
    assert first_payload["model"] == OPENAI_RESPONSES_MODEL
    assert first_payload["store"] is False
    assert first_payload["stream"] is False
    assert first_payload["reasoning"] == {
        "effort": "medium",
        "mode": "standard",
        "context": "all_turns",
    }
    assert first_payload["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in first_payload
    assert first_payload["tools"] == [
        {
            "type": "function",
            "name": "inspect_onset_route",
            "description": "Inspect only the simulated onset route.",
            "parameters": _tools()[0].input_schema,
            "strict": False,
        }
    ]
    assert all(tool["type"] == "function" for tool in first_payload["tools"])
    serialized_payloads = json.dumps(
        [request["payload"] for request in transport.requests]
    )
    assert "openai-test-secret-value" not in serialized_payloads
    assert "openai-test-secret-value" not in repr(provider)

    second_input = transport.requests[1]["payload"]["input"]
    assert second_input[1:3] == [
        *_response_fixture()["output"],
    ]
    assert second_input[3] == {
        "type": "function_call_output",
        "call_id": "call_001",
        "output": json.dumps(
            tool_result.content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }


def test_output_limits_and_credential_reflection_are_not_scientific_failures() -> None:
    incomplete = _response_fixture()
    incomplete["status"] = "incomplete"
    incomplete["incomplete_details"] = {"reason": "max_output_tokens"}
    provider = OpenAIResponsesProvider(
        api_key="reflection-test-secret",
        transport=_FixtureTransport([(200, {}, incomplete)]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )

    capped = provider.complete(
        _request((ModelMessage.user({"objective": "Inspect."}),))
    )

    assert capped.metadata is not None
    assert capped.metadata.finish_reason == "length"

    reflected = _response_fixture()
    reflected["output"] = [
        {
            "type": "reasoning",
            "id": "rs_reflected",
            "encrypted_content": "reflection-test-secret",
            "summary": [],
        }
    ]
    rejecting_provider = OpenAIResponsesProvider(
        api_key="reflection-test-secret",
        transport=_FixtureTransport([(200, {}, reflected)]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(ModelProviderFailure) as raised:
        rejecting_provider.complete(
            _request((ModelMessage.user({"objective": "Inspect."}),))
        )
    assert raised.value.normalized_error.code == "adapter.invalid_response"
    assert "reflection-test-secret" not in str(raised.value)


def test_parallel_and_malformed_function_calls_are_losslessly_bounded() -> None:
    fixture = _response_fixture()
    fixture["output"] = [
        {
            "type": "function_call",
            "id": "fc_001",
            "call_id": "call_001",
            "name": "inspect_onset_route",
            "arguments": "{}",
            "status": "completed",
        },
        {
            "type": "function_call",
            "id": "fc_002",
            "call_id": "call_002",
            "name": "inspect_onset_route",
            "arguments": "{not-json",
            "status": "completed",
        },
    ]
    provider = OpenAIResponsesProvider(
        api_key="test-secret",
        transport=_FixtureTransport([(200, {}, fixture)]),
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )

    response = provider.complete(_request((ModelMessage.user({"objective": "Inspect."}),)))

    assert [call.call_id for call in response.message.tool_calls] == [
        "call_001",
        "call_002",
    ]
    assert response.message.tool_calls[0].arguments == {}
    assert response.message.tool_calls[1].arguments == {
        "__provider_invalid_arguments__": True
    }
    assert response.metadata is not None
    assert response.metadata.finish_reason == "tool_calls"


@pytest.mark.parametrize(
    ("statuses", "code"),
    (
        ([429, 429, 429], "inference.overloaded"),
        ([500, 500, 500], "inference.unavailable"),
        ([401], "adapter.protocol_error"),
    ),
)
def test_rate_limits_retries_and_provider_errors_are_normalized(
    statuses: list[int],
    code: str,
) -> None:
    transport = _FixtureTransport(
        [
            (status, {"retry-after": "0"}, {"error": {"message": "do not retain"}})
            for status in statuses
        ]
    )
    provider = OpenAIResponsesProvider(
        api_key="test-secret",
        transport=transport,
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(ModelProviderFailure) as raised:
        provider.complete(_request((ModelMessage.user({"objective": "Inspect."}),)))

    assert raised.value.normalized_error.code == code
    assert len(transport.requests) == len(statuses)
    assert "do not retain" not in str(raised.value)


def test_canonical_trace_preserves_reasoning_lineage_and_scientific_parity() -> None:
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
        fixture = _response_fixture(response_id=f"resp_{turn:03d}")
        fixture["output"] = [
            {
                "type": "reasoning",
                "id": f"rs_{turn:03d}",
                "encrypted_content": f"opaque-lineage-{turn}",
                "summary": [],
            },
            {
                "type": "function_call",
                "id": f"fc_{turn:03d}",
                "call_id": f"call_{turn:03d}",
                "name": action,
                "arguments": "{}",
                "status": "completed",
            },
        ]
        fixtures.append((200, {"x-request-id": f"req_{turn:03d}"}, fixture))
    transport = _FixtureTransport(fixtures)
    provider = OpenAIResponsesProvider(
        api_key="trace-test-secret",
        transport=transport,
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=8,
        max_tool_calls=8,
        sampling=OPENAI_RESPONSES_SAMPLING,
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
    assistant_messages = [
        message for message in attempt.trace.messages if message.role == "assistant"
    ]
    assert len(assistant_messages) == 4
    assert all(message.provider_state[0]["type"] == "reasoning" for message in assistant_messages)
    assert [call.provider_call_id for call in attempt.trace.tool_calls] == [
        "call_001",
        "call_002",
        "call_003",
        "call_004",
    ]
    assert [response.returned_model for response in attempt.trace.responses] == [
        OPENAI_RESPONSES_MODEL
    ] * 4
    assert all(
        response.metadata is not None
        and response.metadata.provider_request_id == f"req_{index:03d}"
        for index, response in enumerate(attempt.trace.responses, start=1)
    )
    assert "trace-test-secret" not in attempt.model_dump_json()


def test_console_reports_openai_credential_readiness_without_secret_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(artifact_root=tmp_path / "missing")) as client:
        missing = client.get("/api/provider-readiness").json()
        smoke = client.post("/api/hosted-smokes/openai")
    assert smoke.status_code == 409
    assert smoke.json() == {"detail": "The OpenAI credential is not configured."}
    assert missing["openai"] == {
        "provider": "openai",
        "route": "responses",
        "requested_model": OPENAI_RESPONSES_MODEL,
        "adapter_revision": OPENAI_RESPONSES_ADAPTER_REVISION,
        "credential_configured": False,
        "status": "missing_credential",
    }

    monkeypatch.setenv("OPENAI_API_KEY", "never-return-this-secret")
    with TestClient(create_app(artifact_root=tmp_path / "configured")) as client:
        configured_response = client.get("/api/provider-readiness")
    assert configured_response.status_code == 200
    assert configured_response.json()["openai"]["credential_configured"] is True
    assert "never-return-this-secret" not in configured_response.text


def test_exact_model_and_credential_readiness_are_fail_closed() -> None:
    assert openai_credential_ready({}) is False
    assert openai_credential_ready({"OPENAI_API_KEY": ""}) is False
    assert openai_credential_ready({"OPENAI_API_KEY": "configured-secret"}) is True

    transport = _FixtureTransport([(200, {}, _response_fixture())])
    provider = OpenAIResponsesProvider(
        api_key="test-secret",
        transport=transport,
        timeout_seconds=30.0,
        sleeper=lambda _seconds: None,
    )
    alias_request = _request((ModelMessage.user({"objective": "Inspect."}),)).model_copy(
        update={
            "model": ModelIdentity(
                provider="openai-responses",
                requested_model="gpt-5.6",
                adapter_revision=OPENAI_RESPONSES_ADAPTER_REVISION,
            )
        }
    )

    with pytest.raises(ModelProviderFailure) as raised:
        provider.complete(alias_request)

    assert raised.value.normalized_error.code == "adapter.protocol_error"
    assert transport.requests == []
