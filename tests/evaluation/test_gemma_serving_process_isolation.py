"""Process-isolation checks for authenticated local-Gemma serving."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from studio.policy_evaluation import gemma_attestation


def test_serving_forces_spawn_workers_and_disables_every_optional_vllm_plugin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pycache = tmp_path / "pycache"
    pycache.mkdir()
    environment = {
        "SCIENCE_LOCAL_GEMMA_API_KEY": "a" * 32,
        "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "b" * 32,
        "PYTHONPYCACHEPREFIX": str(pycache),
        "VLLM_WORKER_MULTIPROC_METHOD": "fork",
        "VLLM_PLUGINS": "unreviewed-plugin",
    }
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(tempfile, "tempdir", "/attacker/cached-tmp")

    gemma_attestation._sanitize_serving_environment()

    assert environment["VLLM_WORKER_MULTIPROC_METHOD"] == "spawn"
    assert environment["VLLM_PLUGINS"] == ""
    assert "SCIENCE_LOCAL_GEMMA_API_KEY" not in environment
    assert "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY" not in environment


def test_serving_replaces_inherited_identity_and_cache_roots_with_private_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pycache = tmp_path / "pycache"
    pycache.mkdir(mode=0o700)
    environment = {
        "PYTHONPYCACHEPREFIX": str(pycache),
        "HOME": "/attacker/home",
        "USER": "attacker",
        "LOGNAME": "attacker",
        "TMPDIR": "/attacker/tmp",
        "XDG_CACHE_HOME": "/attacker/xdg",
        "HF_HOME": "/attacker/huggingface",
        "TORCH_HOME": "/attacker/torch",
        "TRITON_CACHE_DIR": "/attacker/triton",
        "TORCHINDUCTOR_CACHE_DIR": "/attacker/torchinductor",
        "VLLM_CACHE_ROOT": "/attacker/vllm",
        "VLLM_CONFIG_ROOT": "/attacker/vllm-config",
        "CUDA_CACHE_PATH": "/attacker/cuda",
    }
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(tempfile, "tempdir", "/attacker/cached-tmp")

    gemma_attestation._sanitize_serving_environment()

    runtime_root = pycache / "runtime"
    expected_paths = {
        "HOME": runtime_root / "home",
        "TMPDIR": runtime_root / "tmp",
        "XDG_CACHE_HOME": runtime_root / "xdg-cache",
        "HF_HOME": runtime_root / "huggingface",
        "TORCH_HOME": runtime_root / "torch",
        "TRITON_CACHE_DIR": runtime_root / "triton",
        "TORCHINDUCTOR_CACHE_DIR": runtime_root / "torchinductor",
        "VLLM_CACHE_ROOT": runtime_root / "vllm-cache",
        "VLLM_CONFIG_ROOT": runtime_root / "vllm-config",
        "CUDA_CACHE_PATH": runtime_root / "cuda-cache",
    }
    assert environment["USER"] == "science-gemma"
    assert environment["LOGNAME"] == "science-gemma"
    assert tempfile.gettempdir() == str(expected_paths["TMPDIR"])
    for name, path in expected_paths.items():
        assert environment[name] == str(path)
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert path.is_relative_to(pycache)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork process seam is unavailable")
def test_any_defensive_fork_clears_preverified_authentication_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gemma_attestation,
        "_PREVERIFIED_PRODUCTION_EVIDENCE",
        object(),
    )
    monkeypatch.setattr(
        gemma_attestation,
        "_PREVERIFIED_RUNTIME_KEYS",
        ("a" * 32, "b" * 32),
    )
    read_descriptor, write_descriptor = os.pipe()
    process_id = os.fork()
    if process_id == 0:
        os.close(read_descriptor)
        cleared = (
            gemma_attestation._PREVERIFIED_PRODUCTION_EVIDENCE is None
            and gemma_attestation._PREVERIFIED_RUNTIME_KEYS is None
        )
        os.write(write_descriptor, b"cleared" if cleared else b"inherited")
        os.close(write_descriptor)
        os._exit(0)

    os.close(write_descriptor)
    try:
        result = os.read(read_descriptor, 32)
    finally:
        os.close(read_descriptor)
    waited_process, status = os.waitpid(process_id, 0)

    assert waited_process == process_id
    assert os.waitstatus_to_exitcode(status) == 0
    assert result == b"cleared"
