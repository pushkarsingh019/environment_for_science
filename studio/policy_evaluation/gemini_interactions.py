"""Native, stateless Gemini Interactions adapter for scientific episodes."""

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

GEMINI_INTERACTIONS_MODEL: Final = "gemini-3.7-flash"
GEMINI_INTERACTIONS_ADAPTER_REVISION: Final = "gemini-interactions/1"
GEMINI_INTERACTIONS_SAMPLING: Final = ModelSamplingSettings(
    profile="hosted-reference-medium-v1",
    temperature=None,
)
_GEMINI_API_KEY_ENV: Final = "GEMINI_API_KEY"
_INTERACTIONS_URL: Final = (
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)
_INVALID_ARGUMENTS_KEY: Final = "__provider_invalid_arguments__"


def gemini_credential_ready(environ: Mapping[str, str]) -> bool:
    """Report credential presence without reading it into a public model."""
    return bool(environ.get(_GEMINI_API_KEY_ENV, ""))


class GeminiInteractionsProvider:
    """Translate canonical turns to storage-disabled Gemini Interactions."""

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
            raise ValueError("a Gemini credential is required")
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
    ) -> GeminiInteractionsProvider:
        return cls(
            api_key=environ.get(_GEMINI_API_KEY_ENV, ""),
            transport=transport or UrllibHostedJsonTransport(),
            timeout_seconds=timeout_seconds,
        )

    def __repr__(self) -> str:
        return "GeminiInteractionsProvider(credential_configured=True)"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if (
            request.model.provider != "gemini-interactions"
            or request.model.requested_model != GEMINI_INTERACTIONS_MODEL
            or request.model.adapter_revision != GEMINI_INTERACTIONS_ADAPTER_REVISION
            or request.sampling != GEMINI_INTERACTIONS_SAMPLING
        ):
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            )
        payload = _interactions_payload(request)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        try:
            decoded, response_headers = self._executor.execute(
                url=_INTERACTIONS_URL,
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


def _interactions_payload(request: ModelRequest) -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "user":
            input_items.append(
                {
                    "role": "user",
                    "content": _canonical_json(message.content),
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
            if message.provider_tool_call_id is None or message.tool_name is None:
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                )
            input_items.append(
                {
                    "type": "function_result",
                    "call_id": message.provider_tool_call_id,
                    "name": message.tool_name,
                    "result": deepcopy(message.content),
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
            }
            for tool in request.tools
        ],
        "tool_choice": "auto",
        "generation_config": {
            "thinking_level": "medium",
            "max_output_tokens": request.sampling.max_output_tokens,
        },
        "service_tier": "standard",
        "store": False,
        "stream": False,
    }


def _parse_response(
    value: object,
    *,
    response_headers: Mapping[str, str],
) -> ModelResponse:
    document = _mapping(value)
    if document.get("object") != "interaction":
        raise ValueError("Gemini interaction object is invalid")
    status = document.get("status")
    if status in {"failed", "blocked", "cancelled"}:
        raise ModelProviderFailure(category="inference", code="inference.cancelled")
    if status not in {"completed", "incomplete"}:
        raise ValueError("Gemini interaction status is invalid")
    steps = document.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ValueError("Gemini interaction steps must be an object list")
    if len(steps) > 64:
        raise ValueError("Gemini interaction exceeds the step budget")

    calls: list[ModelToolCall] = []
    text_parts: list[str] = []
    for step_value in steps:
        step = _mapping(step_value)
        step_type = step.get("type")
        if step_type in {"thought", "function_call"}:
            signature = step.get("thought_signature")
            if not isinstance(signature, str) or not signature:
                raise ValueError("Gemini reasoning step is missing its signature")
        if step_type == "thought":
            continue
        if step_type == "function_call":
            arguments_value = step.get("arguments")
            arguments = (
                deepcopy(arguments_value)
                if isinstance(arguments_value, dict)
                else {_INVALID_ARGUMENTS_KEY: True}
            )
            calls.append(
                ModelToolCall(
                    call_id=step["call_id"],
                    name=step["name"],
                    arguments=arguments,
                )
            )
        elif step_type == "message":
            if step.get("role") != "assistant":
                raise ValueError("Gemini output message must be assistant")
            content = step.get("content")
            if not isinstance(content, str):
                raise ValueError("Gemini output message content is invalid")
            text_parts.append(content)
        elif step_type != "thought":
            raise ValueError("Gemini interaction contains an unsupported step")

    finish_reason: Literal["stop", "tool_calls", "length"]
    if status == "incomplete":
        details = _optional_mapping(document.get("incomplete_details"))
        if details.get("reason") == "max_output_tokens":
            finish_reason = "length"
        else:
            raise ModelProviderFailure(category="inference", code="inference.cancelled")
    else:
        finish_reason = "tool_calls" if calls else "stop"
    usage_value = document.get("usage")
    usage, native_usage = (
        _parse_usage(usage_value) if usage_value is not None else (None, None)
    )
    created = document.get("created_at")
    if not isinstance(created, int) or isinstance(created, bool) or created < 0:
        raise ValueError("Gemini interaction timestamp is invalid")
    return ModelResponse(
        response_id=document["id"],
        returned_model=document["model"],
        message=ModelMessage.assistant(
            "\n".join(text_parts),
            tool_calls=tuple(calls),
            provider_state=tuple(deepcopy(steps)),
        ),
        usage=usage,
        metadata=ModelResponseMetadata(
            created_unix_seconds=created,
            finish_reason=finish_reason,
            provider_request_id=_header(response_headers, "x-request-id"),
            service_tier="standard",
            provider_usage=native_usage,
        ),
    )


def _parse_usage(value: object) -> tuple[TokenUsage, dict[str, Any]]:
    usage = _mapping(value)
    total_input = _required_nonnegative_int(usage.get("total_input_tokens"))
    cached = _required_nonnegative_int(usage.get("total_cached_tokens"))
    visible_output = _required_nonnegative_int(usage.get("total_output_tokens"))
    thought = _required_nonnegative_int(usage.get("total_thought_tokens"))
    _required_nonnegative_int(usage.get("total_tool_use_tokens"))
    total = _required_nonnegative_int(usage.get("total_tokens"))
    if cached > total_input or total != total_input + visible_output + thought:
        raise ValueError("Gemini usage counters do not reconcile")
    return (
        TokenUsage(
            input_tokens=total_input - cached,
            output_tokens=visible_output + thought,
            total_tokens=total,
            cached_input_tokens=cached,
            reasoning_tokens=thought,
        ),
        deepcopy(dict(usage)),
    )


def _required_nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Gemini usage counters must be non-negative integers")
    return value


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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "GEMINI_INTERACTIONS_ADAPTER_REVISION",
    "GEMINI_INTERACTIONS_MODEL",
    "GEMINI_INTERACTIONS_SAMPLING",
    "GeminiInteractionsProvider",
    "gemini_credential_ready",
]
