"""Process hardening for deployment helpers that handle private bytes."""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_HARDENING_PROBE = r"""
import ctypes
import resource
import runpy
import sys

namespace = runpy.run_path(sys.argv[1], run_name="deployment_hardening_probe")
namespace[sys.argv[2]]()
if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
    raise SystemExit("core limit was not disabled")
if sys.platform == "linux":
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
    if prctl(3, 0, 0, 0, 0) != 0:
        raise SystemExit("process remained dumpable")
print("hardened")
"""


@pytest.mark.parametrize(
    ("script_name", "function_name"),
    (
        ("science_local_gemma_model_stager.py", "_harden_operator_process"),
        ("science_local_gemma_private_proxy.py", "_harden_proxy_process"),
    ),
)
def test_private_deployment_helpers_disable_core_dumps_and_peer_inspection(
    script_name: str,
    function_name: str,
) -> None:
    script = Path(__file__).resolve().parents[2] / "deployment" / script_name

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _HARDENING_PROBE,
            str(script),
            function_name,
        ),
        env={"LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "hardened\n"
    assert completed.stderr == ""


def test_model_stager_hardens_before_the_interactive_token_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "deployment"
        / "science_local_gemma_model_stager.py"
    )
    namespace = runpy.run_path(str(script), run_name="stager_hardening_order_test")
    function_globals = namespace["main"].__globals__
    events: list[str] = []

    def harden() -> None:
        events.append("harden")

    def run_operator(**_kwargs: Any) -> int:
        events.append("prompt-and-stage")
        return 23

    monkeypatch.setattr(function_globals["sys"], "argv", [str(script)])
    monkeypatch.setitem(function_globals, "_harden_operator_process", harden)
    monkeypatch.setitem(function_globals, "run_operator", run_operator)

    assert namespace["main"]() == 23
    assert events == ["harden", "prompt-and-stage"]


def test_proxy_hardens_before_opening_its_private_socket_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "deployment"
        / "science_local_gemma_private_proxy.py"
    )
    namespace = runpy.run_path(str(script), run_name="proxy_hardening_order_test")
    function_globals = namespace["main"].__globals__
    events: list[str] = []

    def harden() -> None:
        events.append("harden")

    def reject_directory(_path: str) -> tuple[Path, int]:
        events.append("open-socket-directory")
        raise ValueError("test stop")

    monkeypatch.setitem(function_globals, "_harden_proxy_process", harden)
    monkeypatch.setitem(function_globals, "_open_socket_directory", reject_directory)

    result = namespace["main"](
        ("namespace", "--socket-directory", "/private/proxy")
    )

    assert result == 70
    assert events == ["harden", "open-socket-directory"]
    assert capsys.readouterr().err == (
        "science-local-gemma-private-proxy: unsafe socket directory\n"
    )
