"""Wire-contract tests for the private local-Gemma Chat adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib import request as urllib_request

import pytest

from environments.eeg import LEGACY_SCENARIO_ID, load_legacy_bundle
from studio.bundle import validate_environment_bundle
from studio.policy_evaluation import local_gemma
from studio.policy_evaluation.local_gemma import (
    LocalGemmaChatProvider,
    _UrllibJsonTransport,
    validated_private_unix_socket,
)
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
    CanonicalModelRunner,
    ModelIdentity,
    ModelMessage,
    ModelPreflightRequest,
    ModelProviderFailure,
    ModelRequest,
    ModelTool,
    ModelToolCall,
    TokenUsage,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from studio.policy_evaluation.runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    PRODUCTION_RUNTIME_DISTRIBUTION_PINS,
)

_TEST_API_KEY = "local-gemma-test-api-key-material-000000000000"
_TEST_RUNTIME_INSTANCE_ID = "1" * 64
_TEST_PRODUCT_WHEEL_SHA256 = "9" * 64
_TEST_TRUSTED_BOOTSTRAP_SHA256 = "7" * 64


class _RecordingTransport:
    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self.body = body
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], object]:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return (
            self.status,
            {"x-science-runtime-instance": _TEST_RUNTIME_INSTANCE_ID},
            self.body,
        )


class _SequenceTransport(_RecordingTransport):
    def __init__(
        self,
        responses: list[
            tuple[int, object]
            | tuple[int, dict[str, str], object]
            | Exception
        ],
    ) -> None:
        super().__init__(0, {})
        self._responses = iter(responses)

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], object]:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        if len(response) == 2:
            status, body = response
            return (
                status,
                {"x-science-runtime-instance": _TEST_RUNTIME_INSTANCE_ID},
                body,
            )
        return response


@contextmanager
def _loopback_server(
    handler: type[BaseHTTPRequestHandler],
) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def _server_url(server: ThreadingHTTPServer, path: str) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}{path}"


def test_default_transport_refuses_cross_origin_redirects_before_forwarding_auth() -> None:
    redirected_headers: list[dict[str, str]] = []

    class RedirectTarget(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            redirected_headers.append(dict(self.headers.items()))
            body = b'{"redirected":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    with _loopback_server(RedirectTarget) as target:
        target_url = _server_url(target, "/capture")

        class RedirectSource(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = b'{"redirect_refused":true}'
                self.send_response(302)
                self.send_header("Location", target_url)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                del args

        with _loopback_server(RedirectSource) as source:
            status, _headers, body = _UrllibJsonTransport().post_json(
                url=_server_url(source, "/v1/chat/completions"),
                headers={"Authorization": "Bearer should-not-leave-source"},
                payload={"store": False},
                timeout_seconds=2.0,
            )

    assert status == 302
    assert body == b'{"redirect_refused":true}'
    assert redirected_headers == []


def test_default_transport_ignores_environment_proxy_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_requests: list[str] = []
    proxy_requests: list[str] = []

    class Destination(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            destination_requests.append(self.path)
            body = b'{"direct":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    class Proxy(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            proxy_requests.append(self.path)
            body = b'{"proxied":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    with _loopback_server(Proxy) as proxy, _loopback_server(Destination) as destination:
        proxy_url = _server_url(proxy, "")
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setattr(urllib_request, "_opener", None)
        monkeypatch.setattr(urllib_request, "proxy_bypass", lambda _host: False)
        status, _headers, body = _UrllibJsonTransport().post_json(
            url=_server_url(destination, "/v1/chat/completions"),
            headers={"Authorization": "Bearer destination-only"},
            payload={"store": False},
            timeout_seconds=2.0,
        )

    assert status == 200
    assert body == b'{"direct":true}'
    assert destination_requests == ["/v1/chat/completions"]
    assert proxy_requests == []


@pytest.mark.parametrize(
    ("status", "declare_length"),
    (
        (200, True),
        (500, True),
        (200, False),
        (500, False),
    ),
)
def test_default_transport_bounds_success_and_error_bodies_with_or_without_length(
    status: int,
    declare_length: bool,
) -> None:
    payload = b"x" * 129

    class OversizedHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            if declare_length:
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    with (
        _loopback_server(OversizedHandler) as server,
        pytest.raises(ValueError, match="maximum accepted size"),
    ):
        _UrllibJsonTransport(max_response_bytes=128).post_json(
            url=_server_url(server, "/v1/chat/completions"),
            headers={"Authorization": "Bearer bounded-response-test"},
            payload={"store": False},
            timeout_seconds=2.0,
        )


def test_adapter_emits_declared_chat_tools_and_normalizes_usage() -> None:
    body = {
        "id": "chatcmpl-turn-1",
        "object": "chat.completion",
        "created": 1787457601,
        "model": "google/gemma-4-E4B-it",
        "system_fingerprint": "vllm-0.26.0-cu129",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "I will inspect the simulated onset route.",
                    "tool_calls": [
                        {
                            "id": "call-turn-1",
                            "type": "function",
                            "function": {
                                "name": "inspect_onset_route",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 7,
            "total_tokens": 26,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }
    provider, transport = _attested_provider(
        status=200,
        body=body,
        base_url="http://127.0.0.1:8100/v1",
        api_key="test-only-secret-material-00000000000000",
        timeout_seconds=17.0,
    )

    response = provider.complete(_first_request())

    assert response.response_id == "chatcmpl-turn-1"
    assert response.returned_model == "google/gemma-4-E4B-it"
    assert response.message == ModelMessage.assistant(
        "I will inspect the simulated onset route.",
        tool_calls=(
            ModelToolCall(
                call_id="call-turn-1",
                name="inspect_onset_route",
                arguments={},
            ),
        ),
    )
    assert response.usage == TokenUsage(
        input_tokens=19,
        output_tokens=7,
        total_tokens=26,
        cached_input_tokens=3,
        reasoning_tokens=2,
    )
    assert response.metadata is not None
    assert response.metadata.created_unix_seconds == 1787457601
    assert response.metadata.finish_reason == "tool_calls"
    assert response.metadata.system_fingerprint == "vllm-0.26.0-cu129"
    assert response.metadata.runtime_instance_id == _TEST_RUNTIME_INSTANCE_ID
    assert transport.calls == [
        {
            "url": "http://127.0.0.1:8100/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer test-only-secret-material-00000000000000",
                "Content-Type": "application/json",
            },
            "payload": {
                "model": "google/gemma-4-E4B-it",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            '{"objective":"Inspect only visible evidence.",'
                            '"observation":{"summary":"Synthetic observation."}}'
                        ),
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "inspect_onset_route",
                            "description": "Inspect the simulated onset route.",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "temperature": 0.0,
                "max_tokens": 2048,
                "tool_choice": "auto",
                "stream": False,
                "store": False,
            },
            "timeout_seconds": 17.0,
        }
    ]


def test_adapter_caps_chat_timeout_to_remaining_episode_deadline() -> None:
    challenge = "ad" * 32
    attestation_key = "deadline-attestation-test-key-material-000000000000000"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport(
        [
            (200, {"attestation": evidence, "signature": signature}),
            TimeoutError(),
        ]
    )
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        timeout_seconds=120.0,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )
    provider.preflight(_preflight_request())
    request = _first_request().model_copy(
        update={"transport_timeout_seconds": 7.0},
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(request)

    assert captured.value.normalized_error.code == "inference.episode_timeout"
    assert transport.calls[-1]["timeout_seconds"] == 7.0


def test_adapter_caps_preflight_timeout_to_remaining_episode_deadline() -> None:
    transport = _SequenceTransport([TimeoutError()])
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "p" * 32,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        timeout_seconds=120.0,
        nonce_factory=lambda: "ae" * 32,
    )
    request = _preflight_request().model_copy(
        update={"transport_timeout_seconds": 11.0},
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.preflight(request)

    assert captured.value.normalized_error.code == "inference.episode_timeout"
    assert transport.calls[-1]["timeout_seconds"] == 11.0


def test_adapter_preserves_assistant_and_tool_lineage_on_follow_up() -> None:
    provider, transport = _attested_provider(
        status=200,
        body={
            "id": "chatcmpl-turn-2",
            "object": "chat.completion",
            "created": 1787457602,
            "model": "google/gemma-4-E4B-it",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-turn-2",
                                "type": "function",
                                "function": {
                                    "name": "inspect_onset_route",
                                    "arguments": {},
                                },
                            }
                        ],
                    },
                }
            ],
        },
        base_url="http://127.0.0.1:8000/v1",
    )
    first = _first_request()
    request = first.model_copy(
        update={
            "turn": 2,
            "messages": (
                *first.messages,
                ModelMessage.assistant(
                    "Inspecting.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="call-turn-1",
                            name="inspect_onset_route",
                            arguments={},
                        ),
                    ),
                ),
                ModelMessage.tool(
                    {"status": "ok", "observation": {"summary": "Visible result."}},
                    call_id="call-turn-1",
                    name="inspect_onset_route",
                ),
            ),
        }
    )

    provider.complete(request)

    messages = transport.calls[0]["payload"]["messages"]
    assert messages[1] == {
        "role": "assistant",
        "content": "Inspecting.",
        "tool_calls": [
            {
                "id": "call-turn-1",
                "type": "function",
                "function": {
                    "name": "inspect_onset_route",
                    "arguments": "{}",
                },
            }
        ],
    }
    assert messages[2] == {
        "role": "tool",
        "tool_call_id": "call-turn-1",
        "name": "inspect_onset_route",
        "content": ('{"observation":{"summary":"Visible result."},"status":"ok"}'),
    }


def test_adapter_fails_closed_if_response_model_drifts_after_request() -> None:
    provider, _transport = _attested_provider(
        status=200,
        body={
            "id": "chatcmpl-drift",
            "object": "chat.completion",
            "created": 1787457604,
            "model": "google/gemma-4-E2B-it",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "done"},
                }
            ],
        },
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.category == "adapter"
    assert captured.value.normalized_error.code == "adapter.protocol_error"


@pytest.mark.parametrize(
    "base_url",
    (
        "https://models.example.com/v1",
        "http://user:password@127.0.0.1:8000/v1",
        "http://127.0.0.1:8000/v1?token=secret",
        "http://127.0.0.1:8000/private-api",
        "http://10.4.3.2:8000/v1",
        "http://inference-node:8000/v1",
        "http://localhost:8000/v1",
        "http://127.0.0.1.:8000/v1",
        "file:///srv/private/model",
    ),
)
def test_adapter_rejects_public_or_credential_bearing_routes(base_url: str) -> None:
    with pytest.raises(ValueError, match="private inference route"):
        LocalGemmaChatProvider.from_environment(
            {"SCIENCE_LOCAL_GEMMA_BASE_URL": base_url},
            transport=_RecordingTransport(200, {}),
        )


@pytest.mark.parametrize(
    "environment",
    (
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "a" * 32,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": "b" * 32,
        },
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": "short",
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "a" * 32,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": "same-key-material" * 3,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "same-key-material" * 3,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
    ),
)
def test_adapter_requires_distinct_strong_runtime_keys(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="runtime keys"):
        LocalGemmaChatProvider.from_environment(
            environment,
            transport=_RecordingTransport(200, {}),
        )


def test_live_adapter_requires_an_authorized_unix_socket_transport() -> None:
    with pytest.raises(ValueError, match="authorized Unix socket"):
        LocalGemmaChatProvider.from_environment(
            {
                "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1/v1",
                "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
                "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "a" * 32,
                "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": (
                    _TEST_PRODUCT_WHEEL_SHA256
                ),
                "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": (
                    _TEST_TRUSTED_BOOTSTRAP_SHA256
                ),
            }
        )


def test_unix_socket_transport_requires_owner_only_endpoint_and_directory() -> None:
    temporary_parent = "/private/tmp" if sys.platform == "darwin" else None
    with tempfile.TemporaryDirectory(
        prefix="science-local-gemma-",
        dir=temporary_parent,
    ) as temporary_directory:
        directory = Path(temporary_directory)
        directory.chmod(0o700)
        socket_path = directory / "science-local-gemma.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(socket_path))
            socket_path.chmod(0o600)
            approved_path, identity = validated_private_unix_socket(str(socket_path))
            assert approved_path == str(socket_path)
            assert identity == (socket_path.stat().st_dev, socket_path.stat().st_ino)

            socket_path.chmod(0o660)
            with pytest.raises(ValueError, match="authorized Unix socket"):
                validated_private_unix_socket(str(socket_path))
        finally:
            listener.close()


def test_adapter_refuses_chat_before_server_attestation() -> None:
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "a" * 32,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=_RecordingTransport(200, {}),
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.category == "adapter"
    assert captured.value.normalized_error.code == "adapter.protocol_error"


def test_adapter_representation_and_errors_never_retain_endpoint_or_secret() -> None:
    provider, _transport = _attested_provider(
        status=503,
        body={"error": "host 10.4.3.2 unavailable"},
        base_url="http://127.0.0.1:8104/v1",
        api_key="do-not-retain-secret-material-000000000000",
    )

    assert repr(provider) == "LocalGemmaChatProvider(private_route=True)"
    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())
    assert captured.value.normalized_error.category == "inference"
    assert captured.value.normalized_error.code == "inference.unavailable"
    serialized = captured.value.normalized_error.model_dump_json()
    assert "10.4.3.2" not in serialized
    assert "do-not-retain" not in serialized


def test_adapter_rejects_opaque_runtime_secret_reflected_in_a_response() -> None:
    api_key = "opaque-runtime-api-key-material-000000000000000000"
    provider, _transport = _attested_provider(
        status=200,
        body={
            "id": "chatcmpl-reflected-secret",
            "object": "chat.completion",
            "created": 1787457604,
            "model": "google/gemma-4-E4B-it",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": api_key},
                }
            ],
        },
        api_key=api_key,
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.category == "adapter"
    assert captured.value.normalized_error.code == "adapter.invalid_response"
    assert api_key not in str(captured.value)


@pytest.mark.parametrize(
    ("status", "category", "code"),
    (
        (401, "adapter", "adapter.protocol_error"),
        (422, "adapter", "adapter.protocol_error"),
        (408, "inference", "inference.timeout"),
        (429, "inference", "inference.overloaded"),
        (500, "inference", "inference.unavailable"),
    ),
)
def test_http_failures_are_normalized_outside_scientific_scores(
    status: int,
    category: str,
    code: str,
) -> None:
    provider, _transport = _attested_provider(
        status=status,
        body={"error": "unsafe raw provider text"},
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.category == category
    assert captured.value.normalized_error.code == code
    assert "unsafe raw provider text" not in str(captured.value)


@pytest.mark.parametrize(
    "body",
    (
        {},
        {"id": "x", "model": "google/gemma-4-E4B-it", "choices": []},
        {
            "id": "x",
            "model": "google/gemma-4-E4B-it",
            "choices": [{"message": {"role": "assistant", "tool_calls": "bad"}}],
        },
        {
            "id": "x",
            "model": "google/gemma-4-E4B-it",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "c",
                                "type": "function",
                                "function": {
                                    "name": "inspect_onset_route",
                                    "arguments": "[]",
                                },
                            }
                        ],
                    }
                }
            ],
        },
        {
            "id": "x",
            "object": "chat.completion",
            "created": 1787457605,
            "model": "google/gemma-4-E4B-it",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [],
                    },
                }
            ],
        },
        {
            "id": "x",
            "object": "chat.completion",
            "created": 1787457605,
            "model": "google/gemma-4-E4B-it",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c",
                                "type": "function",
                                "function": {
                                    "name": "inspect_onset_route",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                }
            ],
        },
    ),
)
def test_malformed_success_responses_fail_as_adapter_errors(body: object) -> None:
    provider, _transport = _attested_provider(
        status=200,
        body=body,
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())
    assert captured.value.normalized_error.category == "adapter"
    assert captured.value.normalized_error.code == "adapter.invalid_response"


def test_signed_server_preflight_attests_exact_runtime_without_transport_material() -> None:
    challenge = "ab" * 32
    attestation_key = "server-attestation-test-key-material-0000000000000000"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport([(200, {"attestation": evidence, "signature": signature})])
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )

    attestation = provider.preflight(_preflight_request())

    assert attestation.checkpoint_revision == ("ee0ef6023621cff504d758262d4e04895a5af4a2")
    assert attestation.tokenizer_revision == attestation.checkpoint_revision
    assert attestation.renderer_revision == ("f770dcaa362e3a6a13a96f039741b3b84ca4114e")
    assert attestation.vllm_version == "0.26.0+cu129"
    assert attestation.runtime_instance_id == _TEST_RUNTIME_INSTANCE_ID
    assert attestation.python_bytecode_mode == "fresh-private-prefix-no-write"
    assert attestation.python_runtime == APPROVED_RUNTIME_PYTHON
    assert tuple(item.distribution for item in attestation.runtime_distributions) == tuple(
        pin.distribution for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    )
    assert attestation.vllm_config.tool_call_parser == "gemma4"
    assert attestation.sampling_profile == "base-gemma-development-chat-v1"
    assert attestation.verification_method == "hmac-sha256-server-challenge"
    assert attestation.signature == signature
    assert attestation.verify_signature(attestation_key) is True
    assert attestation.verify_signature("wrong-key-material" * 3) is False
    serialized = attestation.model_dump_json()
    for forbidden in (
        "127.0.0.1",
        _TEST_API_KEY,
        attestation_key,
        "/srv/",
    ):
        assert forbidden not in serialized
    assert transport.calls[0]["url"] == ("http://127.0.0.1:8000/v1/science/runtime-attestations")
    assert transport.calls[0]["payload"] == {
        "attestation_version": "science-local-gemma-runtime-attestation/1",
        "challenge_nonce": challenge,
        "expected_product_wheel_sha256": _TEST_PRODUCT_WHEEL_SHA256,
        "expected_trusted_bootstrap_sha256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        "requested_model": "google/gemma-4-E4B-it",
        "adapter_revision": "local-gemma-openai-chat/1",
        "sampling_profile": "base-gemma-development-chat-v1",
        "sampling": _first_request().sampling.model_dump(mode="json"),
        "budgets": _first_request().budgets.model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    "response_headers",
    (
        {},
        {"x-science-runtime-instance": "2" * 64},
    ),
)
def test_chat_rejects_missing_or_process_swapped_runtime_binding(
    response_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = "af" * 32
    attestation_key = "response-binding-attestation-key-material-000000000"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport(
        [
            (200, {"attestation": evidence, "signature": signature}),
            (
                200,
                response_headers,
                b'{"malformed expensive body":',
            ),
        ]
    )
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )
    provider.preflight(_preflight_request())
    decoded = False

    def fail_if_decoded(_body: bytes) -> object:
        nonlocal decoded
        decoded = True
        raise AssertionError("mismatched process body must not be decoded")

    monkeypatch.setattr(local_gemma, "_decoded_json_or_text", fail_if_decoded)

    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.code == "adapter.protocol_error"
    assert decoded is False


def test_failed_fresh_preflight_clears_previously_verified_runtime() -> None:
    challenge = "b1" * 32
    attestation_key = "stale-preflight-attestation-key-material-00000000000"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport(
        [
            (200, {"attestation": evidence, "signature": signature}),
            (200, {"attestation": {}, "signature": "0" * 64}),
            (200, {"must": "not be sent"}),
        ]
    )
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": (
                _TEST_TRUSTED_BOOTSTRAP_SHA256
            ),
        },
        transport=transport,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )
    provider.preflight(_preflight_request())

    with pytest.raises(ModelProviderFailure):
        provider.preflight(_preflight_request())
    with pytest.raises(ModelProviderFailure) as captured:
        provider.complete(_first_request())

    assert captured.value.normalized_error.code == "adapter.protocol_error"
    assert len(transport.calls) == 2


def test_runner_persists_attestation_response_metadata_and_product_defaults() -> None:
    challenge = "ac" * 32
    attestation_key = "runner-attestation-test-key-material-3333333333333333"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport(
        [
            (200, {"attestation": evidence, "signature": signature}),
            (
                200,
                {
                    "id": "chatcmpl-terminal",
                    "object": "chat.completion",
                    "created": 1787457605,
                    "model": "google/gemma-4-E4B-it",
                    "system_fingerprint": "vllm-0.26.0-cu129",
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "Retest now.",
                                "tool_calls": [
                                    {
                                        "id": "call-terminal",
                                        "type": "function",
                                        "function": {
                                            "name": "present_test_flash",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                },
            ),
        ]
    )
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )
    bundle = validate_environment_bundle(load_legacy_bundle())

    attempt = CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=provider,
        max_turns=64,
        max_tool_calls=64,
    ).run(
        scenario_id=LEGACY_SCENARIO_ID,
        objective="Recover trustworthy onset-marker evidence in the simulation.",
        model=_first_request().model,
    )

    assert attempt.completed_run is not None
    assert attempt.trace.budgets.model_dump() == {
        "max_turns": 64,
        "max_tool_calls": 64,
        "max_provider_tool_calls": 64,
        "max_episode_seconds": 900,
    }
    assert attempt.trace.run.local_gemma_attestation is not None
    assert attempt.trace.run.local_gemma_attestation.evidence_digest.startswith("sha256:")
    assert attempt.trace.run.local_gemma_attestation.signature == signature
    assert attempt.trace.run.local_gemma_attestation.verify_signature(attestation_key)
    assert attempt.trace.responses[0].metadata is not None
    assert attempt.trace.responses[0].metadata.created_unix_seconds == 1787457605
    assert (
        attempt.trace.responses[0].metadata.runtime_instance_id
        == attempt.trace.run.local_gemma_attestation.runtime_instance_id
    )
    serialized = attempt.model_dump_json()
    assert "127.0.0.1" not in serialized
    assert attestation_key not in serialized


@pytest.mark.parametrize(
    "mutation",
    (
        "bad_signature",
        "wrong_checkpoint",
        "wrong_tokenizer_manifest",
        "wrong_python_abi",
        "missing_runtime_distribution",
        "runtime_wheel_drift",
        "missing_product_receipt",
        "product_wheel_drift",
        "trusted_bootstrap_drift",
        "writable_serving_roots",
        "bytecode_isolation_drift",
        "noncanonical_receipt_order",
        "noncanonical_timestamp",
        "stale_attestation",
    ),
)
def test_server_preflight_fails_closed_on_unverified_runtime_evidence(
    mutation: str,
) -> None:
    challenge = "cd" * 32
    attestation_key = "server-attestation-test-key-material-1111111111111111"
    evidence = _server_evidence(challenge)
    if mutation == "wrong_checkpoint":
        evidence["checkpoint_revision"] = "0" * 40
    elif mutation == "wrong_tokenizer_manifest":
        evidence["tokenizer_manifest_sha256"] = "0" * 64
    elif mutation == "wrong_python_abi":
        evidence["python_runtime"]["abi_tag"] = "cp311"
    elif mutation == "missing_runtime_distribution":
        evidence["runtime_distributions"].pop()
    elif mutation == "runtime_wheel_drift":
        evidence["runtime_distributions"][3]["wheel_sha256"] = "0" * 64
    elif mutation == "missing_product_receipt":
        evidence.pop("product_distribution")
    elif mutation == "product_wheel_drift":
        evidence["product_distribution"]["wheel_sha256"] = "8" * 64
    elif mutation == "trusted_bootstrap_drift":
        evidence["trusted_bootstrap_sha256"] = "6" * 64
    elif mutation == "writable_serving_roots":
        evidence["serving_root_filesystem_mode"] = "writable-filesystem"
    elif mutation == "bytecode_isolation_drift":
        evidence["python_bytecode_mode"] = "normal-bytecode-cache"
    elif mutation == "noncanonical_receipt_order":
        evidence["runtime_distributions"].reverse()
    elif mutation == "noncanonical_timestamp":
        evidence["generated_at_utc"] = "2026-08-23T04:00:00.000Z"
    elif mutation == "stale_attestation":
        evidence["generated_at_utc"] = "2026-08-23T03:00:00Z"
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if mutation == "bad_signature":
        signature = "0" * 64
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCIENCE_LOCAL_GEMMA_API_KEY": _TEST_API_KEY,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=_RecordingTransport(
            200,
            {"attestation": evidence, "signature": signature},
        ),
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )

    with pytest.raises(ModelProviderFailure) as captured:
        provider.preflight(_preflight_request())

    assert captured.value.normalized_error.category == "adapter"
    assert captured.value.normalized_error.code == "adapter.protocol_error"


def _attested_provider(
    *,
    status: int,
    body: object,
    base_url: str = "http://127.0.0.1:8000/v1",
    api_key: str = _TEST_API_KEY,
    timeout_seconds: float = 120.0,
) -> tuple[LocalGemmaChatProvider, _SequenceTransport]:
    challenge = "ef" * 32
    attestation_key = "adapter-test-attestation-key-material-2222222222222222"
    evidence = _server_evidence(challenge)
    signature = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(evidence).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    transport = _SequenceTransport(
        [
            (200, {"attestation": evidence, "signature": signature}),
            (status, body),
        ]
    )
    provider = LocalGemmaChatProvider.from_environment(
        {
            "SCIENCE_LOCAL_GEMMA_BASE_URL": base_url,
            "SCIENCE_LOCAL_GEMMA_API_KEY": api_key,
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": _TEST_PRODUCT_WHEEL_SHA256,
            "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        },
        transport=transport,
        timeout_seconds=timeout_seconds,
        nonce_factory=lambda: challenge,
        clock=lambda: datetime(2026, 8, 23, 4, 0, 5, tzinfo=timezone.utc),
    )
    provider.preflight(_preflight_request())
    transport.calls.clear()
    return provider, transport


def _first_request() -> ModelRequest:
    return ModelRequest(
        model=ModelIdentity(
            provider="local-openai-compatible",
            requested_model="google/gemma-4-E4B-it",
            adapter_revision="local-gemma-openai-chat/1",
        ),
        turn=1,
        messages=(
            ModelMessage.user(
                {
                    "objective": "Inspect only visible evidence.",
                    "observation": {"summary": "Synthetic observation."},
                }
            ),
        ),
        tools=(
            ModelTool(
                name="inspect_onset_route",
                description="Inspect the simulated onset route.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        ),
    )


def _preflight_request() -> ModelPreflightRequest:
    request = _first_request()
    return ModelPreflightRequest(
        model=request.model,
        profile="base-gemma-development-v1",
        sampling=request.sampling,
        budgets=request.budgets,
    )


def _server_evidence(challenge: str) -> dict[str, Any]:
    return {
        "attestation_version": "science-local-gemma-runtime-attestation/1",
        "attestation_id": "attestation-018f7f6e4a2146df",
        "runtime_instance_id": _TEST_RUNTIME_INSTANCE_ID,
        "trusted_bootstrap_sha256": _TEST_TRUSTED_BOOTSTRAP_SHA256,
        "python_bytecode_mode": "fresh-private-prefix-no-write",
        "challenge_nonce": challenge,
        "generated_at_utc": "2026-08-23T04:00:00Z",
        "runtime_started_at_utc": "2026-08-23T03:55:00Z",
        "served_model": "google/gemma-4-E4B-it",
        "checkpoint_revision": "ee0ef6023621cff504d758262d4e04895a5af4a2",
        "checkpoint_weights_sha256": (
            "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503"
        ),
        "tokenizer_revision": "ee0ef6023621cff504d758262d4e04895a5af4a2",
        "tokenizer_manifest_sha256": BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
        "renderer_revision": "f770dcaa362e3a6a13a96f039741b3b84ca4114e",
        "vllm_version": "0.26.0+cu129",
        "vllm_source_revision": "568afb3a13806beb53bb2e6bd518269357b237c0",
        "vllm_wheel_sha256": ("7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf"),
        "python_runtime": APPROVED_RUNTIME_PYTHON.model_dump(mode="json"),
        "runtime_receipt_id": "science-local-gemma-runtime-cp312-cu129/1",
        "runtime_distributions": _runtime_distribution_receipt(),
        "product_distribution": {
            "distribution": "science-environment-studio",
            "version": "0.1.0",
            "wheel_sha256": _TEST_PRODUCT_WHEEL_SHA256,
            "record_manifest_sha256": "c" * 64,
            "import_module": "studio.policy_evaluation.gemma_server_bootstrap",
            "import_origin": "studio/policy_evaluation/gemma_server_bootstrap.py",
            "import_origin_sha256": "d" * 64,
            "verification": "wheel-record-sha256+import-origin",
        },
        "network_scope": "loopback-only",
        "api_key_authentication": True,
        "serving_root_filesystem_mode": "kernel-read-only-mount",
        "attestation_middleware_revision": ("science-local-gemma-attestation-middleware/1"),
        "vllm_config": {
            "dtype": "bfloat16",
            "max_model_len": 32768,
            "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.35,
            "enforce_eager": True,
            "max_num_seqs": 16,
            "generation_config": "vllm",
            "tool_call_parser": "gemma4",
            "enable_auto_tool_choice": True,
            "enable_lora": False,
            "disable_log_requests": True,
            "limit_mm_per_prompt": {"image": 0, "audio": 0, "video": 0},
        },
        "adapter_revision": "local-gemma-openai-chat/1",
        "served_adapter": "none",
        "sampling_profile": "base-gemma-development-chat-v1",
        "max_episode_seconds": 900,
        "platform": "linux-x86_64",
        "accelerator_architecture": "sm120",
        "accelerator_count": 1,
        "cuda_version": "12.9",
        "driver_version": "610.43.02",
        "serving_image_digest": f"sha256:{'2' * 64}",
        "serving_image_digest_provenance": "operator-supplied",
        "evidence_scope": "server-reported-runtime-state",
    }


def _runtime_distribution_receipt() -> list[dict[str, object]]:
    return [
        {
            "distribution": pin.distribution,
            "version": pin.version,
            "wheel_sha256": pin.wheel_sha256,
            "record_manifest_sha256": "a" * 64,
            "import_module": pin.import_module,
            "import_origin": pin.import_origin,
            "import_origin_sha256": "b" * 64,
            "verification": "wheel-record-sha256+import-origin",
        }
        for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    ]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
