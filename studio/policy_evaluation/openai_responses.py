"""Native, stateless OpenAI Responses adapter for canonical scientific episodes."""

from __future__ import annotations

import json
import math
import socket
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Final, Literal, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import ValidationError

from .artifact_safety import contains_exact_material
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
_MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
_MAX_ATTEMPTS: Final = 3
_INVALID_ARGUMENTS_KEY: Final = "__provider_invalid_arguments__"


class _JsonTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], object]: ...


class _RejectRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib_request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class _UrllibJsonTransport:
    def __init__(self, *, max_response_bytes: int = _MAX_RESPONSE_BYTES) -> None:
        self._max_response_bytes = max_response_bytes
        self._opener = urllib_request.build_opener(
            urllib_request.ProxyHandler({}),
            _RejectRedirectHandler(),
        )

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], object]:
        request = urllib_request.Request(
            url,
            data=_canonical_json(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                return (
                    response.status,
                    {name.casefold(): value for name, value in response.headers.items()},
                    self._read_bounded(response),
                )
        except urllib_error.HTTPError as failure:
            return (
                failure.code,
                {name.casefold(): value for name, value in failure.headers.items()},
                self._read_bounded(failure),
            )

    def _read_bounded(self, response: Any) -> bytes:
        body: object = response.read(self._max_response_bytes + 1)
        if not isinstance(body, bytes) or len(body) > self._max_response_bytes:
            raise ValueError("provider response exceeds the accepted size")
        return body


def openai_credential_ready(environ: Mapping[str, str]) -> bool:
    """Report only whether a non-empty credential is configured."""
    return bool(environ.get(_OPENAI_API_KEY_ENV, ""))


class OpenAIResponsesProvider:
    """Translate canonical turns to storage-disabled OpenAI Responses requests."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: _JsonTransport,
        timeout_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key or any(character in api_key for character in "\r\n"):
            raise ValueError("an OpenAI credential is required")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._api_key = api_key
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._sleeper = sleeper
        self._monotonic = monotonic

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        *,
        transport: _JsonTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> OpenAIResponsesProvider:
        return cls(
            api_key=environ.get(_OPENAI_API_KEY_ENV, ""),
            transport=transport or _UrllibJsonTransport(),
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
        started = self._monotonic()
        status = 0
        response_headers: Mapping[str, str] = {}
        body: object = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            remaining = request.transport_timeout_seconds - (
                self._monotonic() - started
            )
            if remaining <= 0:
                raise ModelProviderFailure(
                    category="inference",
                    code="inference.episode_timeout",
                )
            timeout = min(self._timeout_seconds, remaining)
            try:
                status, response_headers, body = self._transport.post_json(
                    url=_RESPONSES_URL,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=timeout,
                )
            except (TimeoutError, socket.timeout) as failure:
                raise ModelProviderFailure(
                    category="inference",
                    code=(
                        "inference.episode_timeout"
                        if request.transport_timeout_seconds < self._timeout_seconds
                        else "inference.timeout"
                    ),
                ) from failure
            except (urllib_error.URLError, OSError) as failure:
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.unavailable",
                ) from failure
            except ValueError as failure:
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                ) from failure
            if status not in {429} and status < 500:
                break
            if attempt == _MAX_ATTEMPTS:
                break
            self._sleeper(_retry_delay(response_headers))
        if not 200 <= status < 300:
            raise _http_failure(status)
        try:
            decoded = _decode_body(body)
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


def _retry_delay(headers: Mapping[str, str]) -> float:
    value = _header(headers, "retry-after")
    if value is None:
        return 0.25
    try:
        parsed = float(value)
    except ValueError:
        return 0.25
    return parsed if math.isfinite(parsed) and 0.0 <= parsed <= 2.0 else 0.25


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.casefold() == name:
            return value
    return None


def _http_failure(status: int) -> ModelProviderFailure:
    if status in {401, 403}:
        return ModelProviderFailure(category="adapter", code="adapter.protocol_error")
    if status == 408:
        return ModelProviderFailure(category="inference", code="inference.timeout")
    if status == 429:
        return ModelProviderFailure(category="inference", code="inference.overloaded")
    if status >= 500:
        return ModelProviderFailure(category="inference", code="inference.unavailable")
    return ModelProviderFailure(category="adapter", code="adapter.protocol_error")


def _decode_body(value: object) -> object:
    if not isinstance(value, bytes):
        return value
    try:
        return json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return value.decode("utf-8", errors="replace")


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
