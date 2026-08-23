"""Secret-lifetime checks for the independent local-Gemma bootstrap."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from studio.policy_evaluation import gemma_attestation


def _bootstrap_namespace() -> dict[str, Any]:
    return runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_secret_lifetime_test",
    )


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    (
        (b"a" * 32, None),
        (b"a" * 32 + b"\n", "unambiguous printable ASCII"),
    ),
)
def test_bootstrap_erases_temporary_secret_buffer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    expected_error: str | None,
) -> None:
    namespace = _bootstrap_namespace()
    recorded_buffers: list[bytearray] = []

    class RecordingBytearray(bytearray):
        def __new__(cls, *args: object, **kwargs: object) -> RecordingBytearray:
            instance = super().__new__(cls)
            recorded_buffers.append(instance)
            return instance

    read_runtime_secret = namespace["_read_runtime_secret"]
    monkeypatch.setitem(read_runtime_secret.__globals__, "bytearray", RecordingBytearray)
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir()
    secret = secret_directory / "science-local-gemma-api-key"
    secret.write_bytes(payload)
    secret.chmod(0o400)
    directory_fd = os.open(secret_directory, os.O_RDONLY)
    try:
        if expected_error is None:
            assert read_runtime_secret(
                directory_fd,
                secret.name,
            ) == payload.decode("ascii")
        else:
            with pytest.raises(RuntimeError, match=expected_error):
                read_runtime_secret(directory_fd, secret.name)
    finally:
        os.close(directory_fd)

    assert len(recorded_buffers) == 1
    assert recorded_buffers[0] == b"\x00" * len(payload)


def test_bootstrap_reads_secret_directly_into_the_erasable_buffer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _bootstrap_namespace()
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir()
    secret = secret_directory / "science-local-gemma-api-key"
    secret.write_bytes(b"a" * 32)
    secret.chmod(0o400)
    directory_fd = os.open(secret_directory, os.O_RDONLY)

    def immutable_read_forbidden(_descriptor: int, _size: int) -> bytes:
        raise AssertionError("secret bytes must not be returned in an immutable block")

    monkeypatch.setattr(os, "read", immutable_read_forbidden)
    try:
        assert namespace["_read_runtime_secret"](directory_fd, secret.name) == "a" * 32
    finally:
        os.close(directory_fd)


def test_verified_serving_captures_keys_and_model_before_sanitizing_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    pycache = tmp_path / "pycache"
    pycache.mkdir()
    api_key = "a" * 32
    attestation_key = "b" * 32
    environment = {
        "SCIENCE_LOCAL_GEMMA_API_KEY": api_key,
        "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": attestation_key,
        "SCIENCE_LOCAL_GEMMA_MODEL_ROOT": str(model_root),
        "PYTHONPYCACHEPREFIX": str(pycache),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    class Evidence:
        def model_copy(self, *, deep: bool) -> Evidence:
            assert deep is True
            return self

    evidence: Any = Evidence()
    runner_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "pycache_prefix", str(pycache))
    monkeypatch.setattr(
        gemma_attestation,
        "_load_production_evidence",
        lambda _environ, _argv: evidence,
    )
    monkeypatch.setattr(gemma_attestation, "_PREVERIFIED_PRODUCTION_EVIDENCE", None)
    monkeypatch.setattr(gemma_attestation, "_PREVERIFIED_RUNTIME_KEYS", None)

    def module_runner(
        module: str,
        *,
        run_name: str,
        alter_sys: bool,
    ) -> None:
        assert module == "vllm.entrypoints.cli.main"
        assert run_name == "__main__"
        assert alter_sys is True
        assert "SCIENCE_LOCAL_GEMMA_API_KEY" not in environment
        assert "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY" not in environment
        assert "SCIENCE_LOCAL_GEMMA_MODEL_ROOT" not in environment
        runner_calls.append(tuple(sys.argv))

    gemma_attestation.serve_attested_local_gemma(
        argv=("trusted-bootstrap", "serve", str(model_root)),
        module_runner=module_runner,
    )

    assert len(runner_calls) == 1
    assert runner_calls[0][0] == "vllm.entrypoints.cli.main"
    assert runner_calls[0][2] == str(model_root.resolve())
    assert gemma_attestation._PREVERIFIED_PRODUCTION_EVIDENCE is evidence
    assert (api_key, attestation_key) == gemma_attestation._PREVERIFIED_RUNTIME_KEYS
