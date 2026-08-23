"""Private OpenAI-compatible Chat transport for local base Gemma."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import stat
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import SplitResult, urlsplit

from pydantic import ValidationError

from .artifact_safety import contains_exact_material
from .attestation_protocol import (
    canonical_json as _canonical_json,
)
from .attestation_protocol import (
    hmac_sha256_hex,
)
from .attestation_protocol import (
    is_sha256_hexdigest as _hex_digest,
)
from .attestation_protocol import (
    validate_runtime_keys as _validated_runtime_keys,
)
from .model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    BASE_GEMMA_MODEL,
    LocalGemmaRuntimeAttestation,
    LocalGemmaServerEvidence,
    ModelMessage,
    ModelPreflightRequest,
    ModelProviderFailure,
    ModelRequest,
    ModelResponse,
    ModelResponseMetadata,
    ModelToolCall,
    TokenUsage,
)

_BASE_URL_ENV = "SCIENCE_LOCAL_GEMMA_BASE_URL"
_API_KEY_ENV = "SCIENCE_LOCAL_GEMMA_API_KEY"
_ATTESTATION_KEY_ENV = "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY"
_PRODUCT_WHEEL_SHA256_ENV = "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256"
_TRUSTED_BOOTSTRAP_SHA256_ENV = "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256"
_UNIX_SOCKET_ENV = "SCIENCE_LOCAL_GEMMA_UNIX_SOCKET"
_ADAPTER_REVISION = BASE_GEMMA_ADAPTER_REVISION
_ATTESTATION_MAX_AGE_SECONDS = 300.0
_RUNTIME_INSTANCE_HEADER = "x-science-runtime-instance"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_UNIX_SOCKET_NAME = "science-local-gemma.sock"
_PORTABLE_UNIX_PATH_BYTES = 103


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
        if max_response_bytes <= 0:
            raise ValueError("maximum response size must be positive")
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
        encoded = _canonical_json(payload).encode("utf-8")
        request = urllib_request.Request(
            url,
            data=encoded,
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                status = response.status
                response_headers = {
                    name.casefold(): value for name, value in response.headers.items()
                }
                body = self._read_bounded_body(response, response_headers)
        except urllib_error.HTTPError as failure:
            status = failure.code
            response_headers = {
                name.casefold(): value for name, value in failure.headers.items()
            }
            body = self._read_bounded_body(failure, response_headers)
        return status, response_headers, body

    def _read_bounded_body(
        self,
        response: Any,
        headers: Mapping[str, str],
    ) -> bytes:
        declared_length = headers.get("content-length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
            except ValueError as error:
                raise ValueError("response Content-Length is invalid") from error
            if parsed_length < 0 or parsed_length > self._max_response_bytes:
                raise ValueError("response exceeds the maximum accepted size")
        body: object = response.read(self._max_response_bytes + 1)
        if not isinstance(body, bytes):
            raise ValueError("response body is not bytes")
        if len(body) > self._max_response_bytes:
            raise ValueError("response exceeds the maximum accepted size")
        return body


def validated_private_unix_socket(value: str) -> tuple[str, tuple[int, int]]:
    """Authorize one fixed, evaluator-owned Unix socket without retaining aliases."""
    if (
        not value
        or "\x00" in value
        or not os.path.isabs(value)
        or value.startswith(os.path.sep * 2)
        or os.path.normpath(value) != value
    ):
        raise ValueError("an authorized Unix socket is required")
    path = Path(value)
    if path.name != _UNIX_SOCKET_NAME or len(os.fsencode(path)) > _PORTABLE_UNIX_PATH_BYTES:
        raise ValueError("an authorized Unix socket is required")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise ValueError("an authorized Unix socket is required")
        directory = os.stat(path.parent, follow_symlinks=False)
        endpoint = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError("an authorized Unix socket is required") from error
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.geteuid()
        or stat.S_IMODE(directory.st_mode) != 0o700
        or not stat.S_ISSOCK(endpoint.st_mode)
        or endpoint.st_uid != os.geteuid()
        or stat.S_IMODE(endpoint.st_mode) != 0o600
    ):
        raise ValueError("an authorized Unix socket is required")
    return str(path), (endpoint.st_dev, endpoint.st_ino)


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout_seconds: float) -> None:
        super().__init__("127.0.0.1", timeout=timeout_seconds)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(self._socket_path)
        except BaseException:
            connection.close()
            raise
        self.sock = connection


class _UnixSocketJsonTransport:
    def __init__(self, socket_path: str, *, max_response_bytes: int = _MAX_RESPONSE_BYTES) -> None:
        if max_response_bytes <= 0:
            raise ValueError("maximum response size must be positive")
        self._socket_path, self._socket_identity = validated_private_unix_socket(
            socket_path
        )
        self._max_response_bytes = max_response_bytes

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], object]:
        current_path, current_identity = validated_private_unix_socket(self._socket_path)
        if current_path != self._socket_path or current_identity != self._socket_identity:
            raise ValueError("authorized Unix socket identity changed")
        parsed = urlsplit(url)
        request_path = parsed.path
        encoded = _canonical_json(payload).encode("utf-8")
        connection = _UnixSocketHTTPConnection(self._socket_path, timeout_seconds)
        try:
            connection.request("POST", request_path, body=encoded, headers=headers)
            response = connection.getresponse()
            response_headers = {
                name.casefold(): value for name, value in response.getheaders()
            }
            declared_length = response_headers.get("content-length")
            if declared_length is not None:
                try:
                    parsed_length = int(declared_length)
                except ValueError as error:
                    raise ValueError("response Content-Length is invalid") from error
                if parsed_length < 0 or parsed_length > self._max_response_bytes:
                    raise ValueError("response exceeds the maximum accepted size")
            body: object = response.read(self._max_response_bytes + 1)
            if not isinstance(body, bytes):
                raise ValueError("response body is not bytes")
            if len(body) > self._max_response_bytes:
                raise ValueError("response exceeds the maximum accepted size")
            _path, final_identity = validated_private_unix_socket(self._socket_path)
            if final_identity != self._socket_identity:
                raise ValueError("authorized Unix socket identity changed")
            return response.status, response_headers, body
        except http.client.HTTPException as error:
            raise ValueError("Unix socket HTTP response is invalid") from error
        finally:
            connection.close()


class LocalGemmaChatProvider:
    """One endpoint-private implementation of the canonical provider seam."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: _JsonTransport,
        timeout_seconds: float,
        attestation_key: str,
        nonce_factory: Callable[[], str],
        clock: Callable[[], datetime],
        expected_product_wheel_sha256: str,
        expected_trusted_bootstrap_sha256: str,
    ) -> None:
        self._base_url = validated_private_inference_route(base_url)
        self._api_key, self._attestation_key = _validated_runtime_keys(
            api_key=api_key,
            attestation_key=attestation_key,
        )
        self._transport = transport
        if timeout_seconds <= 0:
            raise ValueError("inference timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._nonce_factory = nonce_factory
        self._clock = clock
        if not _hex_digest(expected_product_wheel_sha256):
            raise ValueError("an out-of-band expected product wheel digest is required")
        self._expected_product_wheel_sha256 = expected_product_wheel_sha256
        if not _hex_digest(expected_trusted_bootstrap_sha256):
            raise ValueError("an out-of-band trusted bootstrap digest is required")
        self._expected_trusted_bootstrap_sha256 = expected_trusted_bootstrap_sha256
        self._verified_attestation: LocalGemmaRuntimeAttestation | None = None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        *,
        transport: _JsonTransport | None = None,
        timeout_seconds: float = 120.0,
        nonce_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> LocalGemmaChatProvider:
        """Read live-only route material without adding it to model contracts."""
        base_url = environ.get(_BASE_URL_ENV, "")
        if not base_url:
            raise ValueError("a private inference route is required")
        return cls(
            base_url=base_url,
            api_key=environ.get(_API_KEY_ENV, ""),
            transport=(
                transport
                if transport is not None
                else _UnixSocketJsonTransport(environ.get(_UNIX_SOCKET_ENV, ""))
            ),
            timeout_seconds=timeout_seconds,
            attestation_key=environ.get(_ATTESTATION_KEY_ENV, ""),
            nonce_factory=nonce_factory or (lambda: secrets.token_hex(32)),
            clock=clock or (lambda: datetime.now(timezone.utc)),
            expected_product_wheel_sha256=environ.get(_PRODUCT_WHEEL_SHA256_ENV, ""),
            expected_trusted_bootstrap_sha256=environ.get(
                _TRUSTED_BOOTSTRAP_SHA256_ENV,
                "",
            ),
        )

    def __repr__(self) -> str:
        return "LocalGemmaChatProvider(private_route=True)"

    def preflight(
        self,
        request: ModelPreflightRequest,
    ) -> LocalGemmaRuntimeAttestation:
        """Authenticate fresh server-derived runtime evidence before inference."""
        self._verified_attestation = None
        if (
            request.model.provider != "local-openai-compatible"
            or request.model.requested_model != BASE_GEMMA_MODEL
            or request.model.adapter_revision != _ADAPTER_REVISION
            or len(self._attestation_key.encode("utf-8")) < 32
        ):
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            )
        challenge = self._nonce_factory()
        if not isinstance(challenge, str) or not _hex_digest(challenge):
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            )
        payload = {
            "attestation_version": "science-local-gemma-runtime-attestation/1",
            "challenge_nonce": challenge,
            "expected_product_wheel_sha256": self._expected_product_wheel_sha256,
            "expected_trusted_bootstrap_sha256": (
                self._expected_trusted_bootstrap_sha256
            ),
            "requested_model": request.model.requested_model,
            "adapter_revision": request.model.adapter_revision,
            "sampling_profile": request.sampling.profile,
            "sampling": request.sampling.model_dump(mode="json"),
            "budgets": request.budgets.model_dump(mode="json"),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout_seconds = min(
            self._timeout_seconds,
            request.transport_timeout_seconds,
        )
        try:
            status, _response_headers, body = self._transport.post_json(
                url=f"{self._base_url}/science/runtime-attestations",
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
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
        if not 200 <= status < 300:
            raise _http_failure(status)
        try:
            body = _decode_transport_body(body)
            envelope = _mapping(body)
            evidence_document = _mapping(envelope["attestation"])
            signature = envelope["signature"]
            if not isinstance(signature, str) or not _hex_digest(signature):
                raise ValueError("attestation signature is invalid")
            canonical_evidence = _canonical_json(evidence_document)
            evidence = LocalGemmaServerEvidence.model_validate(
                evidence_document,
                strict=False,
            )
            normalized_evidence = _canonical_json(evidence.model_dump(mode="json"))
            if canonical_evidence != normalized_evidence:
                raise ValueError("attestation evidence is not canonically normalized")
            expected_signature = hmac_sha256_hex(
                key=self._attestation_key,
                canonical_document=normalized_evidence,
            )
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("attestation signature does not match")
            now = self._clock()
            if (
                evidence.challenge_nonce != challenge
                or evidence.served_model != request.model.requested_model
                or evidence.adapter_revision != request.model.adapter_revision
                or evidence.sampling_profile != request.sampling.profile
                or evidence.max_episode_seconds != request.budgets.max_episode_seconds
                or evidence.product_distribution.wheel_sha256
                != self._expected_product_wheel_sha256
                or evidence.trusted_bootstrap_sha256
                != self._expected_trusted_bootstrap_sha256
                or now.tzinfo is None
                or abs((now - evidence.generated_at_utc).total_seconds())
                > _ATTESTATION_MAX_AGE_SECONDS
            ):
                raise ValueError("attestation does not bind the scored request")
            attestation = LocalGemmaRuntimeAttestation(
                **evidence.model_dump(),
                signature=signature,
                evidence_digest=(
                    "sha256:" + hashlib.sha256(normalized_evidence.encode("utf-8")).hexdigest()
                ),
                verification_method="hmac-sha256-server-challenge",
            )
        except (KeyError, TypeError, ValueError, ValidationError) as failure:
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            ) from failure
        self._verified_attestation = attestation
        return attestation.model_copy(deep=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Execute one stateless Chat request and retain no transport material."""
        if (
            request.model.provider != "local-openai-compatible"
            or request.model.requested_model != BASE_GEMMA_MODEL
            or request.model.adapter_revision != _ADAPTER_REVISION
            or self._verified_attestation is None
        ):
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            )
        payload = _chat_payload(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout_seconds = min(
            self._timeout_seconds,
            request.transport_timeout_seconds,
        )
        try:
            status, response_headers, body = self._transport.post_json(
                url=f"{self._base_url}/chat/completions",
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except (TimeoutError, socket.timeout) as failure:
            self._verified_attestation = None
            raise ModelProviderFailure(
                category="inference",
                code=(
                    "inference.episode_timeout"
                    if request.transport_timeout_seconds < self._timeout_seconds
                    else "inference.timeout"
                ),
            ) from failure
        except (urllib_error.URLError, OSError) as failure:
            self._verified_attestation = None
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.unavailable",
            ) from failure
        except ValueError as failure:
            self._verified_attestation = None
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.protocol_error",
            ) from failure
        if not 200 <= status < 300:
            self._verified_attestation = None
            raise _http_failure(status)
        try:
            runtime_instance_id = response_headers.get(_RUNTIME_INSTANCE_HEADER)
            if runtime_instance_id != self._verified_attestation.runtime_instance_id:
                self._verified_attestation = None
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                )
            decoded_body = _decode_transport_body(body)
            if contains_exact_material(
                decoded_body,
                (self._api_key, self._attestation_key, self._base_url),
            ):
                raise ValueError("provider response contains private runtime material")
            response = _parse_response(
                decoded_body,
                runtime_instance_id=runtime_instance_id,
            )
            if response.returned_model != request.model.requested_model:
                self._verified_attestation = None
                raise ModelProviderFailure(
                    category="adapter",
                    code="adapter.protocol_error",
                )
            return response
        except (KeyError, TypeError, ValueError, ValidationError) as failure:
            self._verified_attestation = None
            raise ModelProviderFailure(
                category="adapter",
                code="adapter.invalid_response",
            ) from failure


def validated_private_inference_route(value: str) -> str:
    """Return an exact literal-loopback v1 route or fail without retaining it."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as failure:
        raise ValueError("a valid private inference route is required") from failure
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not _loopback_host(parsed.hostname)
        or not _safe_route_path(parsed)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("a valid private inference route is required")
    return value.rstrip("/")


def _loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "::1"}


def _safe_route_path(parsed: SplitResult) -> bool:
    segments = [segment for segment in parsed.path.split("/") if segment]
    return segments == ["v1"]


def _chat_payload(request: ModelRequest) -> dict[str, Any]:
    payload = {
        "model": request.model.requested_model,
        "messages": [_chat_message(message) for message in request.messages],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in request.tools
        ],
        "temperature": request.sampling.temperature,
        "max_tokens": request.sampling.max_output_tokens,
        "tool_choice": request.sampling.tool_choice,
        "stream": request.sampling.streaming,
        "store": request.sampling.store,
    }
    return payload


def _chat_message(message: ModelMessage) -> dict[str, Any]:
    if message.role == "user":
        return {"role": "user", "content": _canonical_json(message.content)}
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": (message.provider_tool_call_id or message.tool_call_id),
            "name": message.tool_name,
            "content": _canonical_json(message.content),
        }
    document: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        document["tool_calls"] = [
            {
                "id": call.provider_call_id or call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _canonical_json(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    return document


def _parse_response(value: object, *, runtime_instance_id: str) -> ModelResponse:
    document = _mapping(value)
    if document.get("object") != "chat.completion":
        raise ValueError("response object must be chat.completion")
    created = document.get("created")
    if not isinstance(created, int) or isinstance(created, bool) or created < 0:
        raise ValueError("response creation time must be a Unix timestamp")
    choices = document["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("response must contain one choice")
    choice = _mapping(choices[0])
    finish_reason = choice.get("finish_reason")
    if finish_reason == "content_filter":
        raise ModelProviderFailure(
            category="inference",
            code="inference.cancelled",
        )
    if finish_reason not in {"stop", "tool_calls", "length"}:
        raise ValueError("response finish reason is invalid")
    message = _mapping(choice["message"])
    if message.get("role") != "assistant":
        raise ValueError("response message must be assistant")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("assistant content must be text")
    calls_value = message.get("tool_calls", [])
    if not isinstance(calls_value, list):
        raise ValueError("tool_calls must be a list")
    calls = tuple(_parse_tool_call(item) for item in calls_value)
    if finish_reason == "tool_calls" and not calls:
        raise ValueError("tool_calls finish reason requires at least one tool call")
    if finish_reason == "stop" and calls:
        raise ValueError("stop finish reason cannot include tool calls")
    usage_value = document.get("usage")
    usage = _parse_usage(usage_value) if usage_value is not None else None
    return ModelResponse(
        response_id=document["id"],
        returned_model=document["model"],
        message=ModelMessage.assistant(content, tool_calls=calls),
        usage=usage,
        metadata=ModelResponseMetadata(
            created_unix_seconds=created,
            finish_reason=finish_reason,
            system_fingerprint=document.get("system_fingerprint"),
            runtime_instance_id=runtime_instance_id,
        ),
    )


def _parse_tool_call(value: object) -> ModelToolCall:
    document = _mapping(value)
    if document.get("type", "function") != "function":
        raise ValueError("only function calls are supported")
    function = _mapping(document["function"])
    arguments_value = function.get("arguments", "{}")
    if isinstance(arguments_value, str):
        arguments_value = json.loads(arguments_value)
    if not isinstance(arguments_value, dict):
        raise ValueError("tool arguments must be an object")
    return ModelToolCall(
        call_id=document["id"],
        name=function["name"],
        arguments=arguments_value,
    )


def _parse_usage(value: object) -> TokenUsage:
    usage = _mapping(value)
    prompt_details = _optional_mapping(usage.get("prompt_tokens_details"))
    completion_details = _optional_mapping(usage.get("completion_tokens_details"))
    return TokenUsage(
        input_tokens=_optional_nonnegative_int(usage.get("prompt_tokens")),
        output_tokens=_optional_nonnegative_int(usage.get("completion_tokens")),
        total_tokens=_optional_nonnegative_int(usage.get("total_tokens")),
        cached_input_tokens=_optional_nonnegative_int(prompt_details.get("cached_tokens")),
        reasoning_tokens=_optional_nonnegative_int(completion_details.get("reasoning_tokens")),
    )


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("usage counters must be non-negative integers")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, Any]:
    return {} if value is None else _mapping(value)


def _http_failure(status: int) -> ModelProviderFailure:
    if status in {401, 403}:
        return ModelProviderFailure(
            category="adapter",
            code="adapter.protocol_error",
        )
    if status == 408:
        return ModelProviderFailure(
            category="inference",
            code="inference.timeout",
        )
    if status == 429:
        return ModelProviderFailure(
            category="inference",
            code="inference.overloaded",
        )
    if status >= 500:
        return ModelProviderFailure(
            category="inference",
            code="inference.unavailable",
        )
    return ModelProviderFailure(
        category="adapter",
        code="adapter.protocol_error",
    )


def _decode_transport_body(value: object) -> object:
    return _decoded_json_or_text(value) if isinstance(value, bytes) else value


def _decoded_json_or_text(value: bytes) -> object:
    try:
        return json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return value.decode("utf-8", errors="replace")


__all__ = [
    "LocalGemmaChatProvider",
    "validated_private_inference_route",
    "validated_private_unix_socket",
]
