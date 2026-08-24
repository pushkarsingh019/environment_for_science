"""Small proxy-free bounded JSON transport shared by hosted provider adapters."""

from __future__ import annotations

import json
import math
import socket
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from .model_runner import ModelProviderFailure

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_ATTEMPTS = 3


class HostedJsonTransport(Protocol):
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


class HostedRequestExecutor:
    """Apply one bounded retry, deadline, and safe failure policy to hosted JSON."""

    def __init__(
        self,
        *,
        transport: HostedJsonTransport,
        request_timeout_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._transport = transport
        self._request_timeout_seconds = request_timeout_seconds
        self._sleeper = sleeper
        self._monotonic = monotonic

    def execute(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        episode_timeout_seconds: float,
    ) -> tuple[object, Mapping[str, str]]:
        started = self._monotonic()
        status = 0
        response_headers: Mapping[str, str] = {}
        body: object = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            remaining = episode_timeout_seconds - (self._monotonic() - started)
            if remaining <= 0:
                raise ModelProviderFailure(
                    category="inference",
                    code="inference.episode_timeout",
                )
            try:
                status, response_headers, body = self._transport.post_json(
                    url=url,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=min(self._request_timeout_seconds, remaining),
                )
            except (TimeoutError, socket.timeout) as failure:
                raise ModelProviderFailure(
                    category="inference",
                    code=(
                        "inference.episode_timeout"
                        if episode_timeout_seconds < self._request_timeout_seconds
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
            if status != 429 and status < 500:
                break
            if attempt == _MAX_ATTEMPTS:
                break
            self._sleeper(_retry_delay(response_headers))
        if not 200 <= status < 300:
            raise _http_failure(status)
        return _decode_body(body), response_headers


class UrllibHostedJsonTransport:
    """POST canonical JSON without ambient proxies, redirects, or unbounded bodies."""

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
        request = urllib_request.Request(
            url,
            data=json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
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
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError as error:
                raise ValueError("provider Content-Length is invalid") from error
            if length < 0 or length > self._max_response_bytes:
                raise ValueError("provider response exceeds the accepted size")
        body: object = response.read(self._max_response_bytes + 1)
        if not isinstance(body, bytes) or len(body) > self._max_response_bytes:
            raise ValueError("provider response exceeds the accepted size")
        return body


def _retry_delay(headers: Mapping[str, str]) -> float:
    value = next(
        (value for key, value in headers.items() if key.casefold() == "retry-after"),
        None,
    )
    if value is None:
        return 0.25
    try:
        parsed = float(value)
    except ValueError:
        return 0.25
    return parsed if math.isfinite(parsed) and 0.0 <= parsed <= 2.0 else 0.25


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


__all__ = [
    "HostedJsonTransport",
    "HostedRequestExecutor",
    "UrllibHostedJsonTransport",
]
