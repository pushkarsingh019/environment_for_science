"""Small proxy-free bounded JSON transport shared by hosted provider adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


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


__all__ = ["HostedJsonTransport", "UrllibHostedJsonTransport"]
