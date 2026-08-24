"""Native, stateless OpenAI Responses adapter for canonical scientific episodes."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Final, Literal

from pydantic import ValidationError

from .artifact_safety import contains_exact_material
from .hosted_transport import (
    HostedJsonTransport,
    HostedRequestExecutor,
    UrllibHostedJsonTransport,
)
from .model_runner import (
    ModelMessage,
    ModelProviderFailure,
    ModelRequest,
    ModelResponse,
    ModelResponseMetadata,
    ModelSamplingSettings,
    ModelToolCall,
    TokenUsage,
)

OPENAI_RESPONSES_MODEL: Final = "gpt-5.6-sol"
OPENAI_RESPONSES_ADAPTER_REVISION: Final = "openai-responses/1"
OPENAI_RESPONSES_SAMPLING: Final = ModelSamplingSettings(
    profile="hosted-reference-medium-v1",
    temperature=None,
)
_OPENAI_API_KEY_ENV: Final = "OPENAI_API_KEY"
_RESPONSES_URL: Final = "https://api.openai.com/v1/responses"
_INVALID_ARGUMENTS_KEY: Final = "__provider_invalid_arguments__"


def openai_credential_ready(environ: Mapping[str, str]) -> bool:
    """Report only whether a non-empty credential is configured."""
    return bool(environ.get(_OPENAI_API_KEY_ENV, ""))


class OpenAIResponsesProvider:
    """Translate canonical turns to storage-disabled OpenAI Responses requests."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: HostedJsonTransport,
        timeout_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key or any(character in api_key for character in "\r\n"):
            raise ValueError("an OpenAI credential is required")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._api_key = api_key
        self._executor = HostedRequestExecutor(
            transport=transport,
            request_timeout_seconds=timeout_seconds,
            sleeper=sleeper,
            monotonic=monotonic,
        )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        *,
        transport: HostedJsonTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> OpenAIResponsesProvider:
        return cls(
            api_key=environ.get(_OPENAI_API_KEY_ENV, ""),
            transport=transport or UrllibHostedJsonTransport(),
            timeout_seconds=timeout_seconds,
        )

    def __repr__(self) -> str:
        return "OpenAIResponsesProvider(credential_configured=True)"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if (
            request.model.provider != "openai-responses"
            or request.model.requested_model != OPENAI_RESPONSES_MODEL
            or request.model.adapter_revision != OPENAI_RESPONSES_ADAPTER_REVISION
            or request.sampling != OPENAI_RESPONSES_SAMPLING
        ):
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            )
        payload = _responses_payload(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            decoded, response_headers = self._executor.execute(
                url=_RESPONSES_URL,
                headers=headers,
                payload=payload,
                episode_timeout_seconds=request.transport_timeout_seconds,
            )
            if contains_exact_material(decoded, (self._api_key,)):
                raise ValueError("provider response reflected credential material")
            return _parse_response(decoded, response_headers=response_headers)
        except ModelProviderFailure:
            raise
        except (KeyError, TypeError, ValueError, ValidationError) as failure:
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.invalid_response",
            ) from failure


def _responses_payload(request: ModelRequest) -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "user":
            input_items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _canonical_json(message.content),
                        }
                    ],
                }
            )
        elif message.role == "assistant":
            if not message.provider_state:
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                )
            input_items.extend(deepcopy(message.provider_state))
        else:
            if message.provider_tool_call_id is None:
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.provider_tool_call_id,
                    "output": _canonical_json(message.content),
                }
            )
    return {
        "model": request.model.requested_model,
        "input": input_items,
        "tools": [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": deepcopy(tool.input_schema),
                # Schema validity remains a canonical-runner responsibility.
                "strict": False,
            }
            for tool in request.tools
        ],
        "tool_choice": request.sampling.tool_choice,
        "parallel_tool_calls": True,
        "reasoning": {
            "effort": "medium",
            "mode": "standard",
            "context": "all_turns",
        },
        "include": ["reasoning.encrypted_content"],
        "max_output_tokens": request.sampling.max_output_tokens,
        "service_tier": "default",
        "store": False,
        "stream": False,
    }


def _parse_response(
    value: object,
    *,
    response_headers: Mapping[str, str],
) -> ModelResponse:
    document = _mapping(value)
    if document.get("object") != "response":
        raise ValueError("OpenAI response object is invalid")
    status = document.get("status")
    if status == "failed":
        raise ModelProviderFailure(category="inference", code="inference.unavailable")
    if status not in {"completed", "incomplete"}:
        raise ValueError("OpenAI response status is invalid")
    output = document.get("output")
    if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
        raise ValueError("OpenAI response output must be an item list")
    if len(output) > 64:
        raise ValueError("OpenAI response output exceeds the item budget")

    calls: list[ModelToolCall] = []
    text_parts: list[str] = []
    for item_value in output:
        item = _mapping(item_value)
        item_type = item.get("type")
        if item_type == "function_call":
            arguments = _parse_arguments(item.get("arguments"))
            calls.append(
                ModelToolCall(
                    call_id=item["call_id"],
                    name=item["name"],
                    arguments=arguments,
                )
            )
        elif item_type == "message":
            if item.get("role") != "assistant":
                raise ValueError("OpenAI output message must be assistant")
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("OpenAI output message content must be a list")
            for part_value in content:
                part = _mapping(part_value)
                if part.get("type") == "output_text":
                    text = part.get("text")
                    if not isinstance(text, str):
                        raise ValueError("OpenAI output text is invalid")
                    text_parts.append(text)
                elif part.get("type") == "refusal":
                    raise ModelProviderFailure(
                        category="inference",
                        code="inference.cancelled",
                    )
        elif item_type != "reasoning":
            raise ValueError("OpenAI output contains an unsupported item")

    finish_reason: Literal["stop", "tool_calls", "length"]
    if status == "incomplete":
        details = _optional_mapping(document.get("incomplete_details"))
        if details.get("reason") == "max_output_tokens":
            finish_reason = "length"
        else:
            raise ModelProviderFailure(
                category="inference",
                code="inference.cancelled",
            )
    else:
        finish_reason = "tool_calls" if calls else "stop"
    usage_value = document.get("usage")
    usage = _parse_usage(usage_value) if usage_value is not None else None
    created = document.get("created_at")
    if not isinstance(created, int) or isinstance(created, bool) or created < 0:
        raise ValueError("OpenAI response timestamp is invalid")
    request_id = _header(response_headers, "x-request-id")
    service_tier = document.get("service_tier")
    if service_tier is not None and not isinstance(service_tier, str):
        raise ValueError("OpenAI service tier is invalid")
    return ModelResponse(
        response_id=document["id"],
        returned_model=document["model"],
        message=ModelMessage.assistant(
            "\n".join(text_parts),
            tool_calls=tuple(calls),
            provider_state=tuple(deepcopy(output)),
        ),
        usage=usage,
        metadata=ModelResponseMetadata(
            created_unix_seconds=created,
            finish_reason=finish_reason,
            provider_request_id=request_id,
            service_tier=service_tier,
        ),
    )


def _parse_arguments(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {_INVALID_ARGUMENTS_KEY: True}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {_INVALID_ARGUMENTS_KEY: True}
    return parsed if isinstance(parsed, dict) else {_INVALID_ARGUMENTS_KEY: True}


def _parse_usage(value: object) -> TokenUsage:
    usage = _mapping(value)
    input_details = _optional_mapping(usage.get("input_tokens_details"))
    output_details = _optional_mapping(usage.get("output_tokens_details"))
    return TokenUsage(
        input_tokens=_optional_nonnegative_int(usage.get("input_tokens")),
        output_tokens=_optional_nonnegative_int(usage.get("output_tokens")),
        total_tokens=_optional_nonnegative_int(usage.get("total_tokens")),
        cached_input_tokens=_optional_nonnegative_int(input_details.get("cached_tokens")),
        reasoning_tokens=_optional_nonnegative_int(output_details.get("reasoning_tokens")),
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.casefold() == name:
            return value
    return None


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, Any]:
    return {} if value is None else _mapping(value)


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("usage counters must be non-negative integers")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "OPENAI_RESPONSES_ADAPTER_REVISION",
    "OPENAI_RESPONSES_MODEL",
    "OPENAI_RESPONSES_SAMPLING",
    "OpenAIResponsesProvider",
    "openai_credential_ready",
]
