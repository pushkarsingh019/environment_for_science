"""Volatile-buffer contract for private proxy traffic."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from deployment import science_local_gemma_private_proxy as private_proxy


class _MemorySocket:
    def __init__(self, incoming: Sequence[bytes]) -> None:
        self._incoming = list(incoming)
        self.sent = bytearray()
        self.recv_called = False
        self.received_buffers: list[bytearray] = []

    def recv(self, _size: int) -> bytes:
        self.recv_called = True
        return self._incoming.pop(0)

    def recv_into(self, buffer: bytearray) -> int:
        payload = self._incoming.pop(0)
        self.received_buffers.append(buffer)
        buffer[: len(payload)] = payload
        return len(payload)

    def sendall(self, payload: Any) -> None:
        self.sent.extend(payload)

    def shutdown(self, _how: int) -> None:
        return None

    def close(self) -> None:
        return None


def test_proxy_relays_private_bytes_only_through_erased_mutable_buffers() -> None:
    request = b"Authorization: Bearer api-key-must-not-remain"
    response = b'{"private":"model-response"}'
    left = _MemorySocket((request, b""))
    right = _MemorySocket((response, b""))

    private_proxy._BoundedRelay._relay(left, right)  # type: ignore[arg-type]

    assert left.recv_called is False
    assert right.recv_called is False
    assert bytes(right.sent) == request
    assert bytes(left.sent) == response
    assert left.received_buffers
    assert right.received_buffers
    assert all(not any(buffer) for buffer in left.received_buffers)
    assert all(not any(buffer) for buffer in right.received_buffers)
