"""Independent stdlib-only private transport for the local Gemma listener."""

from __future__ import annotations

import ctypes
import os
import resource
import signal
import socket
import stat
import sys
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Callable

_PREFIX = "science-local-gemma-private-proxy: "
_USAGE_ERROR = 64
_RUNTIME_ERROR = 70
_SOCKET_NAME = "science-local-gemma.sock"
_LOOPBACK_HOST = "127.0.0.1"
_VLLM_PORT = 8000
_MAX_CONNECTIONS = 16
_LISTEN_BACKLOG = 16
_CONNECT_TIMEOUT_SECONDS = 5.0
_IDLE_TIMEOUT_SECONDS = 900.0
_ACCEPT_POLL_SECONDS = 0.2
_SHUTDOWN_WAIT_SECONDS = 5.0
_COPY_BUFFER_BYTES = 64 * 1024
_ZERO_COPY_BUFFER = bytes(_COPY_BUFFER_BYTES)
_PORTABLE_UNIX_PATH_BYTES = 103
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4
_AUTHORIZED_DIRECTORY_MODE = 0o2710 if sys.platform == "linux" else 0o710

_UpstreamFactory = Callable[[], socket.socket]


def _harden_proxy_process() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
        raise RuntimeError("proxy process core dumps remained enabled")
    if sys.platform != "linux":
        return
    library = ctypes.CDLL(None, use_errno=True)
    prctl = library.prctl
    prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    prctl.restype = ctypes.c_int
    if prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("proxy process inspection could not be disabled")
    if prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("proxy process remained dumpable")


def _fail(message: str, code: int) -> int:
    sys.stderr.write(_PREFIX + message + "\n")
    return code


def _canonical_arguments(arguments: Sequence[str]) -> bool:
    return (
        len(arguments) == 3
        and arguments[0] == "namespace"
        and arguments[1] == "--socket-directory"
    )


def _open_socket_directory(path_text: str) -> tuple[Path, int]:
    if (
        not path_text
        or "\x00" in path_text
        or not os.path.isabs(path_text)
        or path_text.startswith(os.path.sep * 2)
        or os.path.normpath(path_text) != path_text
        or path_text == os.path.sep
    ):
        raise ValueError("unsafe socket directory")
    path = Path(path_text)
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise ValueError("unsafe socket directory")
        before = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != _AUTHORIZED_DIRECTORY_MODE
        ):
            raise ValueError("unsafe socket directory")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_fd = os.open(path, flags)
        after = os.fstat(directory_fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            os.close(directory_fd)
            raise ValueError("unsafe socket directory")
    except (OSError, UnicodeError) as error:
        raise ValueError("unsafe socket directory") from error
    return path, directory_fd


def _directory_is_unchanged(path: Path, directory_fd: int) -> bool:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        descriptor_stat = os.fstat(directory_fd)
    except OSError:
        return False
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and stat.S_ISDIR(descriptor_stat.st_mode)
        and path_stat.st_uid == os.geteuid()
        and descriptor_stat.st_uid == os.geteuid()
        and stat.S_IMODE(path_stat.st_mode) == _AUTHORIZED_DIRECTORY_MODE
        and stat.S_IMODE(descriptor_stat.st_mode) == _AUTHORIZED_DIRECTORY_MODE
        and path_stat.st_gid == descriptor_stat.st_gid
        and (path_stat.st_dev, path_stat.st_ino)
        == (descriptor_stat.st_dev, descriptor_stat.st_ino)
    )


def _socket_metadata(directory_fd: int) -> os.stat_result:
    metadata = os.stat(_SOCKET_NAME, dir_fd=directory_fd, follow_symlinks=False)
    directory_metadata = os.fstat(directory_fd)
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != directory_metadata.st_gid
        or stat.S_IMODE(metadata.st_mode) != 0o660
    ):
        raise OSError("unsafe Unix socket")
    return metadata


def _socket_identity(directory_fd: int) -> tuple[int, int]:
    metadata = _socket_metadata(directory_fd)
    return metadata.st_dev, metadata.st_ino


def _close_socket(connection: socket.socket) -> None:
    with suppress(OSError):
        connection.shutdown(socket.SHUT_RDWR)
    with suppress(OSError):
        connection.close()


class _BoundedRelay:
    def __init__(self, listener: socket.socket, upstream_factory: _UpstreamFactory) -> None:
        self._listener = listener
        self._upstream_factory = upstream_factory
        self._stopping = threading.Event()
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        # Signal handlers run on the main thread and may interrupt an outer
        # critical section before calling stop().  Re-entry must not deadlock.
        self._lock = threading.RLock()
        self._connections: set[socket.socket] = set()
        self._workers: set[threading.Thread] = set()

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        _close_socket(self._listener)
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            _close_socket(connection)

    def serve(self) -> None:
        self._listener.settimeout(_ACCEPT_POLL_SECONDS)
        try:
            while not self._stopping.is_set():
                try:
                    client, _address = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stopping.is_set():
                        break
                    raise
                if not self._slots.acquire(blocking=False):
                    _close_socket(client)
                    continue
                with self._lock:
                    self._connections.add(client)
                worker = threading.Thread(
                    target=self._handle,
                    args=(client,),
                    daemon=True,
                )
                with self._lock:
                    self._workers.add(worker)
                try:
                    worker.start()
                except RuntimeError:
                    with self._lock:
                        self._workers.discard(worker)
                        self._connections.discard(client)
                    self._slots.release()
                    _close_socket(client)
                    raise
        finally:
            self.stop()
            self._join_workers()

    def _handle(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            if self._stopping.is_set():
                return
            upstream = self._upstream_factory()
            if self._stopping.is_set():
                return
            with self._lock:
                self._connections.add(upstream)
            client.settimeout(_IDLE_TIMEOUT_SECONDS)
            upstream.settimeout(_IDLE_TIMEOUT_SECONDS)
            self._relay(client, upstream)
        except OSError:
            pass
        finally:
            _close_socket(client)
            if upstream is not None:
                _close_socket(upstream)
            with self._lock:
                self._connections.discard(client)
                if upstream is not None:
                    self._connections.discard(upstream)
                self._workers.discard(threading.current_thread())
            self._slots.release()

    @staticmethod
    def _relay(left: socket.socket, right: socket.socket) -> None:
        aborted = threading.Event()

        def copy(source: socket.socket, destination: socket.socket) -> None:
            buffer = bytearray(_COPY_BUFFER_BYTES)
            try:
                while not aborted.is_set():
                    received = source.recv_into(buffer)
                    if received <= 0:
                        with suppress(OSError):
                            destination.shutdown(socket.SHUT_WR)
                        return
                    payload = memoryview(buffer)[:received]
                    try:
                        destination.sendall(payload)
                    finally:
                        payload.release()
                        buffer[:received] = _ZERO_COPY_BUFFER[:received]
            except OSError:
                aborted.set()
                _close_socket(source)
                _close_socket(destination)
            finally:
                buffer[:] = _ZERO_COPY_BUFFER

        left_to_right = threading.Thread(target=copy, args=(left, right), daemon=True)
        right_to_left = threading.Thread(target=copy, args=(right, left), daemon=True)
        left_to_right.start()
        right_to_left.start()
        left_to_right.join()
        right_to_left.join()

    def _join_workers(self) -> None:
        deadline = time.monotonic() + _SHUTDOWN_WAIT_SECONDS
        while True:
            with self._lock:
                workers = tuple(self._workers)
            if not workers:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            for worker in workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                worker.join(timeout=remaining)


def _run_relay(relay: _BoundedRelay) -> int:
    def stop(_signum: int, _frame: FrameType | None) -> None:
        relay.stop()

    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_int = signal.signal(signal.SIGINT, stop)
    try:
        relay.serve()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
    return 0


def _run_namespace(path: Path, directory_fd: int) -> int:
    socket_path = path / _SOCKET_NAME
    if len(os.fsencode(socket_path)) > _PORTABLE_UNIX_PATH_BYTES:
        raise OSError("Unix socket path is too long")
    try:
        os.stat(_SOCKET_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise OSError("Unix socket path already exists")

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_identity: tuple[int, int] | None = None
    old_umask = os.umask(0o117)
    try:
        listener.bind(str(socket_path))
    finally:
        os.umask(old_umask)
    try:
        os.chmod(socket_path, 0o660)
        metadata = _socket_metadata(directory_fd)
        if not _directory_is_unchanged(path, directory_fd):
            raise OSError("socket directory changed")
        socket_identity = (metadata.st_dev, metadata.st_ino)
        listener.listen(_LISTEN_BACKLOG)

        def connect_to_vllm() -> socket.socket:
            connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            connection.settimeout(_CONNECT_TIMEOUT_SECONDS)
            try:
                connection.connect((_LOOPBACK_HOST, _VLLM_PORT))
            except BaseException:
                connection.close()
                raise
            return connection

        return _run_relay(_BoundedRelay(listener, connect_to_vllm))
    finally:
        _close_socket(listener)
        if socket_identity is not None and _directory_is_unchanged(path, directory_fd):
            try:
                current = _socket_metadata(directory_fd)
                if (current.st_dev, current.st_ino) == socket_identity:
                    os.unlink(_SOCKET_NAME, dir_fd=directory_fd)
            except OSError:
                pass


def main(arguments: Sequence[str] | None = None) -> int:
    actual_arguments = sys.argv[1:] if arguments is None else arguments
    if not _canonical_arguments(actual_arguments):
        return _fail("invalid command line", _USAGE_ERROR)
    try:
        _harden_proxy_process()
    except Exception:
        return _fail("proxy hardening failed", _RUNTIME_ERROR)
    try:
        path, directory_fd = _open_socket_directory(actual_arguments[2])
    except ValueError:
        return _fail("unsafe socket directory", _RUNTIME_ERROR)
    try:
        return _run_namespace(path, directory_fd)
    except OSError:
        return _fail("proxy operation failed", _RUNTIME_ERROR)
    finally:
        os.close(directory_fd)


if __name__ == "__main__":
    raise SystemExit(main())
