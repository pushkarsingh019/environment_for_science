"""Process-seam tests for the SSH-to-namespace local-Gemma Unix proxy."""

from __future__ import annotations

import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

import pytest


@pytest.fixture
def proxy_script() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "deployment"
        / "science_local_gemma_private_proxy.py"
    )


class _FixedUpstreamServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ReplyAfterEofHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        payload = bytearray()
        while True:
            block = self.request.recv(64 * 1024)
            if not block:
                break
            payload.extend(block)
        self.request.sendall(b"fixed-upstream-response:" + bytes(payload))


class _LiveEchoHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            block = self.request.recv(64 * 1024)
            if not block:
                return
            self.request.sendall(block)


@contextmanager
def _fixed_upstream_server(
    handler: type[socketserver.BaseRequestHandler] = _ReplyAfterEofHandler,
) -> Iterator[None]:
    server = _FixedUpstreamServer(("127.0.0.1", 8000), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@contextmanager
def _short_private_directory() -> Iterator[Path]:
    parent = "/private/tmp" if sys.platform == "darwin" else None
    path = Path(tempfile.mkdtemp(prefix="science-proxy-", dir=parent))
    path.chmod(0o2710 if sys.platform == "linux" else 0o710)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _wait_for_unix_socket(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _stdout, stderr = process.communicate()
            pytest.fail(f"namespace proxy exited before readiness: {stderr}")
        try:
            if stat.S_ISSOCK(path.lstat().st_mode):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    pytest.fail("namespace proxy did not create its fixed Unix socket")


def _stop_proxy(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "namespace",
            "--socket-directory",
            "/approved/proxy",
            "--target-host",
            "secret-route-marker",
        ),
        (
            "host",
            "--socket-directory",
            "/approved/proxy",
            "--port",
            "18000",
            "--host",
            "secret-route-marker",
        ),
        (
            "namespace",
            "--socket-directory",
            "/approved/proxy",
            "--idle-timeout",
            "secret-route-marker",
        ),
        (
            "host",
            "--socket-directory",
            "/approved/proxy",
            "--port",
            "18000",
            "--max-connections",
            "secret-route-marker",
        ),
    ),
)
def test_proxy_rejects_every_route_override_without_echoing_values(
    proxy_script: Path,
    arguments: tuple[str, ...],
) -> None:
    completed = subprocess.run(
        (sys.executable, "-I", "-S", "-B", str(proxy_script), *arguments),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == "science-local-gemma-private-proxy: invalid command line\n"
    assert "secret-route-marker" not in completed.stderr


@pytest.mark.parametrize(
    "kind",
    ("relative", "double-root", "traversal", "symlink", "shared"),
)
def test_proxy_rejects_unsafe_socket_directories_without_disclosing_paths(
    proxy_script: Path,
    tmp_path: Path,
    kind: str,
) -> None:
    private_directory = tmp_path / "private"
    private_directory.mkdir(mode=0o700)
    if kind == "relative":
        socket_directory = "secret-relative-directory"
    elif kind == "double-root":
        socket_directory = "/" + str(private_directory)
    elif kind == "traversal":
        socket_directory = str(tmp_path / "private" / ".." / "private")
    elif kind == "symlink":
        symlink = tmp_path / "secret-symlink-directory"
        symlink.symlink_to(private_directory, target_is_directory=True)
        socket_directory = str(symlink)
    else:
        shared_directory = tmp_path / "secret-shared-directory"
        shared_directory.mkdir(mode=0o770)
        socket_directory = str(shared_directory)

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(proxy_script),
            "namespace",
            "--socket-directory",
            socket_directory,
        ),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 70
    assert completed.stdout == ""
    assert completed.stderr == (
        "science-local-gemma-private-proxy: unsafe socket directory\n"
    )
    assert socket_directory not in completed.stderr


def test_proxy_rejects_the_removed_host_tcp_listener_role(
    proxy_script: Path,
    tmp_path: Path,
) -> None:
    socket_directory = tmp_path / "proxy"
    socket_directory.mkdir(mode=0o700)

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(proxy_script),
            "host",
            "--socket-directory",
            str(socket_directory),
            "--port",
            "18000",
        ),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == "science-local-gemma-private-proxy: invalid command line\n"


def test_proxy_rejects_a_symlink_at_the_fixed_socket_without_removing_it(
    proxy_script: Path,
    tmp_path: Path,
) -> None:
    socket_directory = tmp_path / "proxy"
    socket_directory.mkdir(mode=0o2710 if sys.platform == "linux" else 0o710)
    target = tmp_path / "secret-endpoint-target"
    target.write_text("must remain untouched")
    socket_path = socket_directory / "science-local-gemma.sock"
    socket_path.symlink_to(target)

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(proxy_script),
            "namespace",
            "--socket-directory",
            str(socket_directory),
        ),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 70
    assert completed.stdout == ""
    assert completed.stderr == "science-local-gemma-private-proxy: proxy operation failed\n"
    assert socket_path.is_symlink()
    assert target.read_text() == "must remain untouched"
    assert "secret-endpoint-target" not in completed.stderr


def test_namespace_proxy_exposes_only_the_group_authorized_unix_socket(
    proxy_script: Path,
) -> None:
    payload = b"payload-marker-must-never-be-logged"
    with _short_private_directory() as socket_directory, _fixed_upstream_server():
        socket_path = socket_directory / "science-local-gemma.sock"
        namespace_process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(proxy_script),
                "namespace",
                "--socket-directory",
                str(socket_directory),
            ),
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_unix_socket(socket_path, namespace_process)
            socket_metadata = socket_path.lstat()
            directory_metadata = socket_directory.stat()
            assert stat.S_IMODE(socket_metadata.st_mode) == 0o660
            assert socket_metadata.st_gid == directory_metadata.st_gid
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                client.connect(str(socket_path))
                client.sendall(payload)
                client.shutdown(socket.SHUT_WR)
                response = bytearray()
                while True:
                    block = client.recv(64 * 1024)
                    if not block:
                        break
                    response.extend(block)
            assert bytes(response) == b"fixed-upstream-response:" + payload
        finally:
            namespace_output = _stop_proxy(namespace_process)

        assert socket_path.exists() is False
        assert namespace_output == ("", "")


def test_sigterm_during_an_active_relay_exits_cleanly_without_a_stale_socket(
    proxy_script: Path,
) -> None:
    with _short_private_directory() as socket_directory, _fixed_upstream_server():
        socket_path = socket_directory / "science-local-gemma.sock"
        namespace_process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(proxy_script),
                "namespace",
                "--socket-directory",
                str(socket_directory),
            ),
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_unix_socket(socket_path, namespace_process)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(socket_path))
        try:
            client.sendall(b"active-connection-marker")
            namespace_output = _stop_proxy(namespace_process)
        finally:
            client.close()
            if namespace_process.poll() is None:
                _stop_proxy(namespace_process)

        assert namespace_output == ("", "")
        assert socket_path.exists() is False


def test_proxy_closes_connections_beyond_its_fixed_sixteen_connection_limit(
    proxy_script: Path,
) -> None:
    with _short_private_directory() as socket_directory, _fixed_upstream_server(
        _LiveEchoHandler
    ):
        socket_path = socket_directory / "science-local-gemma.sock"
        namespace_process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(proxy_script),
                "namespace",
                "--socket-directory",
                str(socket_directory),
            ),
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_unix_socket(socket_path, namespace_process)
        clients: list[socket.socket] = []
        overflow: socket.socket | None = None
        try:
            for connection_number in range(16):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(2)
                client.connect(str(socket_path))
                marker = bytes((connection_number,))
                client.sendall(marker)
                assert client.recv(1) == marker
                clients.append(client)

            overflow = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            overflow.settimeout(2)
            overflow.connect(str(socket_path))
            rejected = False
            try:
                overflow.sendall(b"overflow")
                rejected = overflow.recv(1) == b""
            except (BrokenPipeError, ConnectionResetError):
                rejected = True
            assert rejected is True
        finally:
            if overflow is not None:
                overflow.close()
            for client in clients:
                client.close()
            namespace_output = _stop_proxy(namespace_process)

        assert namespace_output == ("", "")
        assert socket_path.exists() is False


def test_namespace_proxy_restarts_cleanly_after_removing_its_socket(
    proxy_script: Path,
) -> None:
    with _short_private_directory() as socket_directory, _fixed_upstream_server(
        _LiveEchoHandler
    ):
        socket_path = socket_directory / "science-local-gemma.sock"
        arguments = (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(proxy_script),
            "namespace",
            "--socket-directory",
            str(socket_directory),
        )
        first_namespace = subprocess.Popen(
            arguments,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_unix_socket(socket_path, first_namespace)
        first_output = _stop_proxy(first_namespace)
        assert socket_path.exists() is False

        second_namespace = subprocess.Popen(
            arguments,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_unix_socket(socket_path, second_namespace)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(socket_path))
                client.sendall(b"second")
                assert client.recv(6) == b"second"
                client.shutdown(socket.SHUT_RDWR)
            time.sleep(0.1)
        finally:
            second_output = _stop_proxy(second_namespace)

        assert first_output == ("", "")
        assert second_output == ("", "")
        assert socket_path.exists() is False


def test_namespace_proxy_rejects_a_directory_without_group_only_traversal(
    proxy_script: Path,
    tmp_path: Path,
) -> None:
    socket_directory = tmp_path / "proxy"
    socket_directory.mkdir(mode=0o700)

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(proxy_script),
            "namespace",
            "--socket-directory",
            str(socket_directory),
        ),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 70
    assert completed.stdout == ""
    assert completed.stderr == (
        "science-local-gemma-private-proxy: unsafe socket directory\n"
    )


def test_namespace_proxy_preserves_the_long_upstream_response_window(
    proxy_script: Path,
) -> None:
    class DelayedEchoHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            payload = self.request.recv(64 * 1024)
            time.sleep(6)
            self.request.sendall(payload)

    with _short_private_directory() as socket_directory, _fixed_upstream_server(
        DelayedEchoHandler
    ):
        socket_path = socket_directory / "science-local-gemma.sock"
        namespace_process = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(proxy_script),
                "namespace",
                "--socket-directory",
                str(socket_directory),
            ),
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_unix_socket(socket_path, namespace_process)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(8)
                client.connect(str(socket_path))
                client.sendall(b"delayed-response")
                assert client.recv(16) == b"delayed-response"
        finally:
            namespace_output = _stop_proxy(namespace_process)

        assert namespace_output == ("", "")
        assert socket_path.exists() is False
