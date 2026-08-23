"""Server-side proof contract for attested local Gemma inference."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import py_compile
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.policy_evaluation import gemma_attestation
from studio.policy_evaluation.gemma_attestation import (
    PRODUCTION_ARTIFACT_PINS,
    LocalGemmaArtifactPins,
    LocalGemmaSnapshotFilePin,
    RuntimeHostEvidence,
    VllmLaunchEvidence,
    build_attested_vllm_command,
    create_attestation_middleware,
    launch_attested_local_gemma,
    verify_local_gemma_runtime,
    verify_renderer_checkout,
)
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
)
from studio.policy_evaluation.runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    PRODUCTION_RUNTIME_DISTRIBUTION_PINS,
    VerifiedRuntimeDistribution,
)


def test_launch_command_is_loopback_only_fixed_and_attested(tmp_path: Path) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()

    command = build_attested_vllm_command(model_root)
    launch = VllmLaunchEvidence.from_argv(command, model_root=model_root)

    assert command[:4] == (sys.executable, "-I", "-S", "-B")
    assert Path(command[4]).name == "science_local_gemma_bootstrap.py"
    assert command[5] == "serve"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--middleware") + 1] == (
        "studio.policy_evaluation.gemma_attestation:local_gemma_attestation_middleware"
    )
    assert "--disable-log-requests" in command
    assert "--enable-lora" not in command
    assert launch.config.gpu_memory_utilization == 0.35
    assert launch.config.enable_auto_tool_choice is True
    assert PRODUCTION_ARTIFACT_PINS.serving_manifest_sha256 == BASE_GEMMA_TOKENIZER_MANIFEST_SHA256


def test_launcher_rejects_missing_runtime_keys_before_exec(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="independently pinned stdlib bootstrap"):
        launch_attested_local_gemma({"SCIENCE_LOCAL_GEMMA_MODEL_ROOT": str(tmp_path)})


def test_fresh_private_pycache_prefix_ignores_forged_normal_timestamp_pyc(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "packages"
    package = package_root / "forged_runtime"
    package.mkdir(parents=True)
    sentinel = tmp_path / "forged-pyc-executed"
    source = package / "__init__.py"
    malicious = f"from pathlib import Path;Path({str(sentinel)!r}).write_text('pyc')\n"
    benign_prefix = "VALUE = 'verified-source'\n"
    benign = benign_prefix + "#" * (len(malicious) - len(benign_prefix) - 1) + "\n"
    assert len(benign) == len(malicious)
    source.write_text(malicious)
    fixed_time = 1_787_457_600
    os.utime(source, (fixed_time, fixed_time))
    py_compile.compile(source, doraise=True)
    source.write_text(benign)
    os.utime(source, (fixed_time, fixed_time))
    private_cache = tmp_path / "private-pycache"
    private_cache.mkdir(mode=0o700)
    child_environ = {
        "PYTHONPATH": str(package_root),
        "PYTHONPYCACHEPREFIX": str(private_cache),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    subprocess.run(
        (sys.executable, "-B", "-c", "import forged_runtime; assert forged_runtime.VALUE"),
        check=True,
        env=child_environ,
        capture_output=True,
        text=True,
    )

    assert sentinel.exists() is False
    assert tuple(private_cache.iterdir()) == ()


def test_isolated_no_site_startup_does_not_execute_pth_or_sitecustomize(
    tmp_path: Path,
) -> None:
    injected_site = tmp_path / "injected-site"
    injected_site.mkdir()
    sitecustomize_sentinel = tmp_path / "sitecustomize-executed"
    pth_sentinel = tmp_path / "pth-executed"
    (injected_site / "sitecustomize.py").write_text(
        f"from pathlib import Path; Path({str(sitecustomize_sentinel)!r}).touch()\n"
    )
    (injected_site / "malicious.pth").write_text(
        f"import pathlib; pathlib.Path({str(pth_sentinel)!r}).touch()\n"
    )

    subprocess.run(
        (sys.executable, "-I", "-S", "-B", "-c", "assert __import__('sys').flags.no_site"),
        check=True,
        env={"PYTHONPATH": str(injected_site)},
        capture_output=True,
        text=True,
    )

    assert sitecustomize_sentinel.exists() is False
    assert pth_sentinel.exists() is False


def test_independent_bootstrap_rejects_modified_product_before_import_side_effect(
    tmp_path: Path,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    verify_product_wheel = bootstrap_namespace["_verify_product_wheel"]
    product_root = tmp_path / "product-root"
    attestation_path = "studio/policy_evaluation/gemma_attestation.py"
    server_bootstrap_path = "studio/policy_evaluation/gemma_server_bootstrap.py"
    environments_path = "environments/__init__.py"
    metadata_path = "science_environment_studio-0.1.0.dist-info/METADATA"
    record_path = "science_environment_studio-0.1.0.dist-info/RECORD"
    sentinel = tmp_path / "modified-product-executed"
    payloads = {
        attestation_path: b"VERIFIED = True\n",
        server_bootstrap_path: b"VERIFIED_BOOTSTRAP = True\n",
        environments_path: b"VERIFIED_ENVIRONMENTS = True\n",
        metadata_path: b"Name: science-environment-studio\nVersion: 0.1.0\n",
    }
    rows = []
    for relative, payload in payloads.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
        rows.append((relative, f"sha256={encoded}", str(len(payload))))
    record_stream = io.StringIO()
    csv.writer(record_stream, lineterminator="\n").writerows(
        (*rows, (record_path, "", ""))
    )
    payloads[record_path] = record_stream.getvalue().encode()
    wheel = tmp_path / "science_environment_studio-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
        for relative, payload in payloads.items():
            archive.writestr(relative, payload)
    for relative, payload in payloads.items():
        installed = product_root / relative
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_bytes(payload)
    unrecorded_bytecode = product_root / "studio" / "unrecorded.pyc"
    unrecorded_bytecode.write_bytes(b"unverified product bytecode")

    with pytest.raises(RuntimeError, match="absent from its wheel RECORD"):
        verify_product_wheel(
            product_root.resolve(),
            wheel.resolve(),
            hashlib.sha256(wheel.read_bytes()).hexdigest(),
        )

    unrecorded_bytecode.unlink()
    (product_root / attestation_path).write_text(
        f"from pathlib import Path; Path({str(sentinel)!r}).touch()\n"
    )

    with pytest.raises(RuntimeError, match="does not match its wheel RECORD"):
        verify_product_wheel(
            product_root.resolve(),
            wheel.resolve(),
            hashlib.sha256(wheel.read_bytes()).hexdigest(),
        )

    assert sentinel.exists() is False


@pytest.mark.parametrize(
    "injection_name",
    (
        "LD_PRELOAD",
        "LD_AUDIT",
        "LD_DEBUG",
        "DYLD_INSERT_LIBRARIES",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONHASHSEED",
    ),
)
def test_independent_bootstrap_rejects_loader_and_python_injection_environment(
    monkeypatch: pytest.MonkeyPatch,
    injection_name: str,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    monkeypatch.setenv(injection_name, "/attacker/injection")

    with pytest.raises(RuntimeError, match="rejects interpreter or dynamic-loader"):
        bootstrap_namespace["main"]()


def test_independent_bootstrap_requires_an_explicit_preexec_environment_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    monkeypatch.setattr(
        bootstrap_namespace["os"],
        "environ",
        {"UNREVIEWED_PROCESS_SETTING": "must-not-be-inherited"},
    )

    with pytest.raises(RuntimeError, match="explicit pre-exec environment allowlist"):
        bootstrap_namespace["main"]()


@pytest.mark.parametrize("locale", (None, "C.UTF-8", "en_US.UTF-8"))
def test_independent_bootstrap_requires_the_fixed_c_locale(
    monkeypatch: pytest.MonkeyPatch,
    locale: str | None,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    environment = {} if locale is None else {"LC_ALL": locale}
    monkeypatch.setattr(bootstrap_namespace["os"], "environ", environment)

    with pytest.raises(RuntimeError, match="fixed C locale"):
        bootstrap_namespace["_validate_preexec_environment"]()


def test_independent_bootstrap_accepts_only_the_fixed_c_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    monkeypatch.setattr(bootstrap_namespace["os"], "environ", {"LC_ALL": "C"})

    bootstrap_namespace["_validate_preexec_environment"]()


def test_independent_bootstrap_loads_secrets_only_from_fixed_files(
    tmp_path: Path,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir(mode=0o700)
    api_key = "a" * 32
    attestation_key = "b" * 32
    api_path = secret_directory / "science-local-gemma-api-key"
    attestation_path = secret_directory / "science-local-gemma-attestation-key"
    api_path.write_text(api_key)
    attestation_path.write_text(attestation_key)
    api_path.chmod(0o400)
    attestation_path.chmod(0o400)

    loaded = bootstrap_namespace["_load_runtime_secrets_from_fixed_files"](
        secret_directory,
        expected_directory_uid=os.geteuid(),
    )

    assert loaded == (api_key, attestation_key)


@pytest.mark.parametrize("mode", (0o600, 0o4400, 0o2400, 0o1400))
def test_independent_bootstrap_rejects_nonexact_secret_permissions(
    tmp_path: Path,
    mode: int,
) -> None:
    bootstrap_namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "deployment"
            / "science_local_gemma_bootstrap.py"
        ),
        run_name="trusted_bootstrap_test",
    )
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir(mode=0o700)
    api_path = secret_directory / "science-local-gemma-api-key"
    attestation_path = secret_directory / "science-local-gemma-attestation-key"
    api_path.write_text("a" * 32)
    attestation_path.write_text("b" * 32)
    api_path.chmod(mode)
    attestation_path.chmod(0o400)

    with pytest.raises(RuntimeError, match="identity or permissions"):
        bootstrap_namespace["_load_runtime_secrets_from_fixed_files"](
            secret_directory,
            expected_directory_uid=os.geteuid(),
        )


def test_serving_environment_replaces_every_inherited_locale_with_c(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pycache = tmp_path / "pycache"
    pycache.mkdir()
    environment = {
        "SCIENCE_LOCAL_GEMMA_API_KEY": "a" * 32,
        "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "b" * 32,
        "PYTHONPYCACHEPREFIX": str(pycache),
        "LC_ALL": "attacker_LOCALE.UTF-8",
        "LC_CTYPE": "attacker_LOCALE.UTF-8",
        "LANG": "attacker_LOCALE.UTF-8",
    }
    monkeypatch.setattr(os, "environ", environment)

    gemma_attestation._sanitize_serving_environment()

    assert environment["LC_ALL"] == "C"
    assert "SCIENCE_LOCAL_GEMMA_API_KEY" not in environment
    assert "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY" not in environment
    assert "LC_CTYPE" not in environment
    assert "LANG" not in environment


def test_renderer_checkout_must_be_at_a_clean_exact_revision(tmp_path: Path) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    (renderer / ".gitignore").write_text("*.ignored\n")
    subprocess.run(
        ("git", "-C", str(renderer), "add", "renderer.py", ".gitignore"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    expected = subprocess.run(
        ("git", "-C", str(renderer), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert verify_renderer_checkout(renderer) == expected
    ignored = renderer / "hidden.ignored"
    ignored.write_text("IGNORED_DRIFT = True\n")

    with pytest.raises(ValueError, match="must be clean"):
        verify_renderer_checkout(renderer)

    ignored.unlink()
    (renderer / "untracked.py").write_text("DRIFT = True\n")

    with pytest.raises(ValueError, match="must be clean"):
        verify_renderer_checkout(renderer)


@pytest.mark.parametrize("index_flag", ("--skip-worktree", "--assume-unchanged"))
def test_renderer_checkout_rejects_index_flags_that_hide_tracked_drift(
    tmp_path: Path,
    index_flag: str,
) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(
        ("git", "-C", str(renderer), "add", "renderer.py"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "-C", str(renderer), "update-index", index_flag, "renderer.py"),
        check=True,
        capture_output=True,
    )
    (renderer / "renderer.py").write_text("MALICIOUS = True\n")

    with pytest.raises(ValueError, match="must be clean"):
        verify_renderer_checkout(renderer)


def test_renderer_checkout_disables_git_replacement_objects(tmp_path: Path) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(
        ("git", "-C", str(renderer), "add", "renderer.py"),
        check=True,
        capture_output=True,
    )
    commit = (
        "git",
        "-C",
        str(renderer),
        "-c",
        "user.name=Science Test",
        "-c",
        "user.email=science@example.invalid",
        "commit",
    )
    subprocess.run((*commit, "-m", "pinned renderer"), check=True, capture_output=True)
    pinned_revision = subprocess.run(
        ("git", "-C", str(renderer), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (renderer / "renderer.py").write_text("MALICIOUS = True\n")
    subprocess.run(
        ("git", "-C", str(renderer), "add", "renderer.py"),
        check=True,
        capture_output=True,
    )
    subprocess.run((*commit, "-m", "replacement renderer"), check=True, capture_output=True)
    replacement_revision = subprocess.run(
        ("git", "-C", str(renderer), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "-C", str(renderer), "replace", pinned_revision, replacement_revision),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "-C", str(renderer), "checkout", "--detach", pinned_revision),
        check=True,
        capture_output=True,
    )
    assert (renderer / "renderer.py").read_text() == "MALICIOUS = True\n"

    with pytest.raises(ValueError, match="must be clean"):
        verify_renderer_checkout(renderer)


def test_renderer_verification_neutralizes_repo_fsmonitor_code_execution(
    tmp_path: Path,
) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(("git", "-C", str(renderer), "add", "renderer.py"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    sentinel = tmp_path / "fsmonitor-executed"
    hook = renderer / ".git" / "malicious-fsmonitor"
    hook.write_text(f"#!/bin/sh\ntouch {sentinel!s}\n")
    hook.chmod(0o700)
    subprocess.run(
        ("git", "-C", str(renderer), "config", "core.fsmonitor", str(hook)),
        check=True,
    )

    revision = verify_renderer_checkout(renderer)

    assert len(revision) == 40
    assert sentinel.exists() is False


def test_renderer_checkout_rejects_filter_masked_drift_without_executing_filter(
    tmp_path: Path,
) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    tracked = renderer / "renderer.py"
    tracked.write_text("PINNED = True\n")
    subprocess.run(("git", "-C", str(renderer), "add", "renderer.py"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    sentinel = tmp_path / "clean-filter-executed"
    clean_filter = renderer / ".git" / "malicious-clean-filter"
    clean_filter.write_text(
        "#!/bin/sh\n"
        f"touch {sentinel!s}\n"
        "printf 'PINNED = True\\n'\n"
    )
    clean_filter.chmod(0o700)
    (renderer / ".git" / "info" / "attributes").write_text(
        "renderer.py filter=malicious\n"
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "config",
            "filter.malicious.clean",
            str(clean_filter),
        ),
        check=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "config",
            "filter.malicious.required",
            "true",
        ),
        check=True,
    )
    tracked.write_text("EVIL__ = True\n")

    with pytest.raises(ValueError, match="must be clean"):
        verify_renderer_checkout(renderer)

    assert sentinel.exists() is False


def test_renderer_checkout_rejects_local_core_worktree_redirection(
    tmp_path: Path,
) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(("git", "-C", str(renderer), "add", "renderer.py"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    redirected_worktree = tmp_path / "redirected-worktree"
    redirected_worktree.mkdir()
    (redirected_worktree / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "config",
            "core.worktree",
            str(redirected_worktree),
        ),
        check=True,
    )
    (renderer / "renderer.py").write_text("MALICIOUS = True\n")

    with pytest.raises(ValueError, match="repository identity"):
        verify_renderer_checkout(renderer)


def test_host_probe_ignores_shadow_path_and_receives_no_signer_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = tmp_path / "shadow-nvidia-smi-executed"
    shadow = tmp_path / "nvidia-smi"
    shadow.write_text(f"#!/bin/sh\ntouch {sentinel!s}\n")
    shadow.chmod(0o700)
    trusted = Path("/trusted/root-owned/nvidia-smi")
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
    monkeypatch.setattr(gemma_attestation.platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(gemma_attestation.platform_module, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        gemma_attestation,
        "_trusted_root_executable",
        lambda _path, _label: trusted,
    )
    monkeypatch.setattr(
        gemma_attestation,
        "require_read_only_filesystem",
        lambda path, _label: path,
    )
    monkeypatch.setattr(gemma_attestation, "_file_sha256", lambda _path: "a" * 64)

    def fake_run(
        argv: tuple[str, ...],
        *,
        env: dict[str, str],
        **_kwargs: object,
    ) -> SimpleNamespace:
        calls.append((argv, env))
        return SimpleNamespace(stdout="12.0, 610.43.02\n")

    monkeypatch.setattr(gemma_attestation.subprocess, "run", fake_run)
    evidence = gemma_attestation._host_evidence(
        {
            "PATH": str(tmp_path),
            "SCIENCE_LOCAL_GEMMA_API_KEY": "must-not-reach-probe",
            "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": "must-not-reach-probe",
            "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH": str(trusted),
            "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256": "a" * 64,
            "SCIENCE_LOCAL_GEMMA_CUDA_VERSION": "12.9",
            "SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST": f"sha256:{'2' * 64}",
        }
    )

    assert evidence.accelerator_architecture == "sm120"
    assert calls == [
        (
            (
                str(trusted),
                "--query-gpu=compute_cap,driver_version",
                "--format=csv,noheader,nounits",
            ),
            {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    ]
    assert sentinel.exists() is False


def test_launch_evidence_rejects_critical_vllm_config_drift(tmp_path: Path) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    command = list(build_attested_vllm_command(model_root))
    command[command.index("--max-model-len") + 1] = "4096"

    with pytest.raises(ValueError, match="exact approved command"):
        VllmLaunchEvidence.from_argv(command, model_root=model_root)


@pytest.mark.parametrize(
    ("flag", "drifted_value"),
    (
        ("--host", "0.0.0.0"),
        ("--port", "8100"),
        ("--middleware", "untrusted.module:middleware"),
    ),
)
def test_launch_evidence_rejects_routing_security_drift(
    tmp_path: Path,
    flag: str,
    drifted_value: str,
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    command = list(build_attested_vllm_command(model_root))
    command[command.index(flag) + 1] = drifted_value

    with pytest.raises(ValueError, match="exact approved command"):
        VllmLaunchEvidence.from_argv(command, model_root=model_root)


@pytest.mark.parametrize(
    "extra_arguments",
    (
        ("--host", "0.0.0.0"),
        ("--middleware", "attacker.module:middleware"),
        ("--served-model-name", "substituted/model"),
        ("--dtype", "float16"),
        ("--api-key", "different-secret"),
        ("--ssl-keyfile", "/tmp/attacker-key.pem"),
        ("--trust-remote-code",),
    ),
)
def test_launch_evidence_rejects_duplicate_and_undeclared_arguments(
    tmp_path: Path,
    extra_arguments: tuple[str, ...],
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    command = (*build_attested_vllm_command(model_root), *extra_arguments)

    with pytest.raises(ValueError, match="exact approved command"):
        VllmLaunchEvidence.from_argv(command, model_root=model_root)


@pytest.mark.parametrize("runtime_shape", (False, True))
def test_launch_evidence_rejects_unmeasured_global_arguments_before_serve(
    tmp_path: Path,
    runtime_shape: bool,
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    outer_command = build_attested_vllm_command(model_root)
    if runtime_shape:
        command = ("trusted-bootstrap", "--config", "attacker.py", *outer_command[5:])
    else:
        command_parts = list(outer_command)
        command_parts[5:5] = ["--config", "attacker.py"]
        command = tuple(command_parts)

    with pytest.raises(ValueError, match="exact approved command"):
        VllmLaunchEvidence.from_argv(command, model_root=model_root)


def test_read_only_preflight_derives_runtime_evidence_from_tiny_artifacts(
    tmp_path: Path,
) -> None:
    model_root, renderer_root, wheel = _tiny_artifacts(tmp_path)
    before = {
        path: path.read_bytes()
        for path in (
            model_root / "model.safetensors",
            model_root / "tokenizer.json",
            wheel,
        )
    }
    pins = LocalGemmaArtifactPins(
        checkpoint_revision="e" * 40,
        checkpoint_weight_bytes=len(b"tiny-weights"),
        checkpoint_weights_sha256=hashlib.sha256(b"tiny-weights").hexdigest(),
        serving_files=_tiny_serving_file_pins(),
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256=hashlib.sha256(b"tiny-wheel").hexdigest(),
    )
    launch = VllmLaunchEvidence.from_argv(
        build_attested_vllm_command(model_root),
        model_root=model_root,
    )

    evidence = verify_local_gemma_runtime(
        model_root=model_root,
        renderer_root=renderer_root,
        pins=pins,
        launch=launch,
        runtime_python=APPROVED_RUNTIME_PYTHON,
        runtime_distributions=_runtime_dependency_receipt(),
        product_distribution=_product_dependency_receipt(),
        runtime_instance_id="1" * 64,
        trusted_bootstrap_sha256="7" * 64,
        renderer_revision_reader=lambda _path: "f" * 40,
        runtime_started_at_utc=datetime(
            2026,
            8,
            23,
            3,
            55,
            tzinfo=timezone.utc,
        ),
        host=RuntimeHostEvidence(
            platform="linux-x86_64",
            accelerator_architecture="sm120",
            accelerator_count=1,
            cuda_version="12.9",
            driver_version="610.43.02",
            serving_image_digest=f"sha256:{'2' * 64}",
        ),
    )

    assert evidence.checkpoint_revision == "e" * 40
    assert evidence.checkpoint_weights_sha256 == hashlib.sha256(b"tiny-weights").hexdigest()
    assert len(evidence.tokenizer_manifest_sha256) == 64
    assert evidence.renderer_revision == "f" * 40
    assert evidence.vllm_config.max_model_len == 32768
    assert evidence.vllm_config.enable_lora is False
    assert evidence.vllm_config.limit_mm_per_prompt.model_dump() == {
        "image": 0,
        "audio": 0,
        "video": 0,
    }
    assert all(path.read_bytes() == payload for path, payload in before.items())
    serialized = evidence.model_dump_json()
    assert str(model_root) not in serialized
    assert str(renderer_root) not in serialized
    assert str(wheel) not in serialized


def test_preflight_fails_before_serving_when_artifact_or_launch_pin_drifts(
    tmp_path: Path,
) -> None:
    model_root, renderer_root, wheel = _tiny_artifacts(tmp_path)
    pins = LocalGemmaArtifactPins(
        checkpoint_revision="e" * 40,
        checkpoint_weight_bytes=len(b"tiny-weights"),
        checkpoint_weights_sha256="0" * 64,
        serving_files=_tiny_serving_file_pins(),
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256=hashlib.sha256(b"tiny-wheel").hexdigest(),
    )
    launch = VllmLaunchEvidence.from_argv(
        build_attested_vllm_command(model_root),
        model_root=model_root,
    )

    with pytest.raises(ValueError, match="checkpoint weight"):
        verify_local_gemma_runtime(
            model_root=model_root,
            renderer_root=renderer_root,
            pins=pins,
            launch=launch,
            runtime_python=APPROVED_RUNTIME_PYTHON,
            runtime_distributions=_runtime_dependency_receipt(),
            product_distribution=_product_dependency_receipt(),
            runtime_instance_id="1" * 64,
            trusted_bootstrap_sha256="7" * 64,
            renderer_revision_reader=lambda _path: "f" * 40,
            runtime_started_at_utc=datetime.now(timezone.utc),
            host=_host(),
        )


def test_preflight_fails_when_a_tokenizer_configuration_file_drifts(
    tmp_path: Path,
) -> None:
    model_root, renderer_root, wheel = _tiny_artifacts(tmp_path)
    pins = LocalGemmaArtifactPins(
        checkpoint_revision="e" * 40,
        checkpoint_weight_bytes=len(b"tiny-weights"),
        checkpoint_weights_sha256=hashlib.sha256(b"tiny-weights").hexdigest(),
        serving_files=_tiny_serving_file_pins(),
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256=hashlib.sha256(b"tiny-wheel").hexdigest(),
    )
    (model_root / "tokenizer_config.json").write_bytes(b'{"drifted":true}')
    launch = VllmLaunchEvidence.from_argv(
        build_attested_vllm_command(model_root),
        model_root=model_root,
    )

    with pytest.raises(ValueError, match="tokenizer_config.json"):
        verify_local_gemma_runtime(
            model_root=model_root,
            renderer_root=renderer_root,
            pins=pins,
            launch=launch,
            runtime_python=APPROVED_RUNTIME_PYTHON,
            runtime_distributions=_runtime_dependency_receipt(),
            product_distribution=_product_dependency_receipt(),
            runtime_instance_id="1" * 64,
            trusted_bootstrap_sha256="7" * 64,
            renderer_revision_reader=lambda _path: pins.renderer_revision,
            runtime_started_at_utc=datetime.now(timezone.utc),
            host=_host(),
        )


def test_preflight_rejects_additional_auto_discoverable_model_files(tmp_path: Path) -> None:
    model_root, renderer_root, wheel = _tiny_artifacts(tmp_path)
    (model_root / "special_tokens_map.json").write_text('{"additional_special_tokens":[]}')
    pins = LocalGemmaArtifactPins(
        checkpoint_revision="e" * 40,
        checkpoint_weight_bytes=len(b"tiny-weights"),
        checkpoint_weights_sha256=hashlib.sha256(b"tiny-weights").hexdigest(),
        serving_files=_tiny_serving_file_pins(),
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256=hashlib.sha256(b"tiny-wheel").hexdigest(),
    )
    launch = VllmLaunchEvidence.from_argv(
        build_attested_vllm_command(model_root),
        model_root=model_root,
    )

    with pytest.raises(ValueError, match="exact approved file set"):
        verify_local_gemma_runtime(
            model_root=model_root,
            renderer_root=renderer_root,
            pins=pins,
            launch=launch,
            runtime_python=APPROVED_RUNTIME_PYTHON,
            runtime_distributions=_runtime_dependency_receipt(),
            product_distribution=_product_dependency_receipt(),
            runtime_instance_id="1" * 64,
            trusted_bootstrap_sha256="7" * 64,
            renderer_revision_reader=lambda _path: pins.renderer_revision,
            runtime_started_at_utc=datetime.now(timezone.utc),
            host=_host(),
        )


def test_middleware_signs_fresh_challenge_and_passes_chat_through(
    tmp_path: Path,
) -> None:
    evidence = _verified_tiny_runtime(tmp_path)
    attestation_key = "middleware-test-attestation-key-material-00000000000"
    api_key = "middleware-test-api-key-material-0000000000000000000"
    middleware = create_attestation_middleware(
        evidence=evidence,
        attestation_key=attestation_key,
        api_key=api_key,
        clock=lambda: datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc),
        attestation_id_factory=lambda: "attestation-server-test",
    )
    app = FastAPI()
    app.middleware("http")(middleware)

    @app.post("/v1/chat/completions")
    async def chat() -> dict[str, bool]:
        return {"upstream": True}

    challenge = _challenge("ab" * 32)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = client.post(
            "/v1/science/runtime-attestations",
            json=challenge,
            headers=headers,
        )
        passthrough = client.post(
            "/v1/chat/completions",
            json={},
            headers=headers,
        )

    assert response.status_code == 200
    envelope = response.json()
    attestation = envelope["attestation"]
    assert attestation["challenge_nonce"] == challenge["challenge_nonce"]
    assert attestation["runtime_instance_id"] == "1" * 64
    assert attestation["python_bytecode_mode"] == "fresh-private-prefix-no-write"
    assert attestation["product_distribution"]["wheel_sha256"] == "9" * 64
    assert attestation["serving_root_filesystem_mode"] == "kernel-read-only-mount"
    assert attestation["generated_at_utc"] == "2026-08-23T04:00:00Z"
    assert attestation["runtime_started_at_utc"] == "2026-08-23T03:55:00Z"
    assert attestation["max_episode_seconds"] == 900
    assert attestation["serving_image_digest_provenance"] == "operator-supplied"
    assert attestation["python_runtime"] == APPROVED_RUNTIME_PYTHON.model_dump(mode="json")
    assert attestation["runtime_receipt_id"] == ("science-local-gemma-runtime-cp312-cu129/1")
    assert [item["distribution"] for item in attestation["runtime_distributions"]] == [
        "jinja2",
        "safetensors",
        "tokenizers",
        "torch",
        "transformers",
        "vllm",
    ]
    expected = hmac.new(
        attestation_key.encode("utf-8"),
        _canonical_json(attestation).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(envelope["signature"], expected)
    assert passthrough.json() == {"upstream": True}
    assert passthrough.headers["x-science-runtime-instance"] == "1" * 64
    serialized = response.text
    assert str(tmp_path) not in serialized
    assert attestation_key not in serialized


def test_middleware_requires_api_authentication_before_any_route() -> None:
    api_key = "middleware-test-api-key-material-2222222222222222222"
    middleware = create_attestation_middleware(
        evidence=_minimal_evidence(),
        attestation_key="middleware-test-attestation-key-material-22222222222",
        api_key=api_key,
        clock=lambda: datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc),
        attestation_id_factory=lambda: "attestation-server-test",
    )
    app = FastAPI()
    app.middleware("http")(middleware)
    upstream_calls: list[bool] = []

    @app.post("/v1/chat/completions")
    async def chat() -> dict[str, bool]:
        upstream_calls.append(True)
        return {"upstream": True}

    with TestClient(app) as client:
        missing = client.post("/v1/chat/completions", json={})
        wrong = client.post(
            "/v1/chat/completions",
            json={},
            headers={"Authorization": "Bearer wrong-key"},
        )

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"detail": "Unauthorized"}
    assert upstream_calls == []


def test_middleware_rejects_reused_api_and_attestation_keys() -> None:
    reused_key = "middleware-reused-key-material-333333333333333333333"

    with pytest.raises(ValueError, match="must be distinct"):
        create_attestation_middleware(
            evidence=_minimal_evidence(),
            attestation_key=reused_key,
            api_key=reused_key,
            clock=lambda: datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc),
            attestation_id_factory=lambda: "attestation-server-test",
        )


def test_middleware_rejects_noncanonical_profile_or_budget() -> None:
    api_key = "middleware-test-api-key-material-1111111111111111111"
    middleware = create_attestation_middleware(
        evidence=_minimal_evidence(),
        attestation_key="middleware-test-attestation-key-material-11111111111",
        api_key=api_key,
        clock=lambda: datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc),
        attestation_id_factory=lambda: "attestation-server-test",
    )
    app = FastAPI()
    app.middleware("http")(middleware)
    invalid = _challenge("cd" * 32)
    invalid["budgets"]["max_turns"] = 63

    with TestClient(app) as client:
        response = client.post(
            "/v1/science/runtime-attestations",
            json=invalid,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "The runtime attestation request is invalid."}


_TINY_SERVING_ARTIFACTS = {
    "chat_template.jinja": b"{{ messages }}",
    "config.json": b'{"model_type":"gemma4"}',
    "generation_config.json": b'{"do_sample":false}',
    "processor_config.json": b'{"processor_class":"Gemma4Processor"}',
    "tokenizer.json": b'{"version":"1.0"}',
    "tokenizer_config.json": b'{"model_max_length":32768}',
}


def _tiny_serving_file_pins() -> tuple[LocalGemmaSnapshotFilePin, ...]:
    return tuple(
        LocalGemmaSnapshotFilePin(
            name=name,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        for name, payload in _TINY_SERVING_ARTIFACTS.items()
    )


def _tiny_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    model_root = tmp_path / "model"
    renderer_root = tmp_path / "renderer"
    model_root.mkdir()
    renderer_root.mkdir()
    (model_root / "model.safetensors").write_bytes(b"tiny-weights")
    (model_root / ".gitattributes").write_text("*.safetensors filter=lfs\n")
    (model_root / "README.md").write_text("tiny inert model card\n")
    for name, content in _TINY_SERVING_ARTIFACTS.items():
        (model_root / name).write_bytes(content)
    wheel = tmp_path / "vllm.whl"
    wheel.write_bytes(b"tiny-wheel")
    return model_root, renderer_root, wheel


def _verified_tiny_runtime(tmp_path: Path):
    model_root, renderer_root, wheel = _tiny_artifacts(tmp_path)
    pins = LocalGemmaArtifactPins(
        checkpoint_revision="e" * 40,
        checkpoint_weight_bytes=len(b"tiny-weights"),
        checkpoint_weights_sha256=hashlib.sha256(b"tiny-weights").hexdigest(),
        serving_files=_tiny_serving_file_pins(),
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256=hashlib.sha256(b"tiny-wheel").hexdigest(),
    )
    launch = VllmLaunchEvidence.from_argv(
        build_attested_vllm_command(model_root),
        model_root=model_root,
    )
    return verify_local_gemma_runtime(
        model_root=model_root,
        renderer_root=renderer_root,
        pins=pins,
        launch=launch,
        runtime_python=APPROVED_RUNTIME_PYTHON,
        runtime_distributions=_runtime_dependency_receipt(),
        product_distribution=_product_dependency_receipt(),
        runtime_instance_id="1" * 64,
        trusted_bootstrap_sha256="7" * 64,
        renderer_revision_reader=lambda _path: pins.renderer_revision,
        runtime_started_at_utc=datetime(
            2026,
            8,
            23,
            3,
            55,
            tzinfo=timezone.utc,
        ),
        host=_host(),
    )


def _minimal_evidence():
    from studio.policy_evaluation.gemma_attestation import VerifiedLocalGemmaRuntime
    from studio.policy_evaluation.model_runner import (
        MultimodalPromptLimits,
        VllmRuntimeConfig,
    )

    return VerifiedLocalGemmaRuntime(
        runtime_started_at_utc=datetime(
            2026,
            8,
            23,
            3,
            55,
            tzinfo=timezone.utc,
        ),
        runtime_instance_id="1" * 64,
        trusted_bootstrap_sha256="7" * 64,
        checkpoint_revision="e" * 40,
        checkpoint_weights_sha256="1" * 64,
        tokenizer_revision="e" * 40,
        tokenizer_manifest_sha256="2" * 64,
        renderer_revision="f" * 40,
        vllm_version="0.26.0+cu129",
        vllm_source_revision="5" * 40,
        vllm_wheel_sha256="3" * 64,
        python_runtime=APPROVED_RUNTIME_PYTHON,
        runtime_receipt_id="science-local-gemma-runtime-cp312-cu129/1",
        runtime_distributions=_runtime_dependency_receipt(),
        product_distribution=_product_dependency_receipt(),
        python_bytecode_mode="fresh-private-prefix-no-write",
        serving_root_filesystem_mode="kernel-read-only-mount",
        network_scope="loopback-only",
        api_key_authentication=True,
        attestation_middleware_revision=("science-local-gemma-attestation-middleware/1"),
        vllm_config=VllmRuntimeConfig(
            dtype="bfloat16",
            max_model_len=32768,
            tensor_parallel_size=1,
            gpu_memory_utilization=0.35,
            enforce_eager=True,
            max_num_seqs=16,
            generation_config="vllm",
            tool_call_parser="gemma4",
            enable_auto_tool_choice=True,
            enable_lora=False,
            disable_log_requests=True,
            limit_mm_per_prompt=MultimodalPromptLimits(
                image=0,
                audio=0,
                video=0,
            ),
        ),
        host=_host(),
    )


def _host() -> RuntimeHostEvidence:
    return RuntimeHostEvidence(
        platform="linux-x86_64",
        accelerator_architecture="sm120",
        accelerator_count=1,
        cuda_version="12.9",
        driver_version="610.43.02",
        serving_image_digest=f"sha256:{'2' * 64}",
    )


def _runtime_dependency_receipt() -> tuple[VerifiedRuntimeDistribution, ...]:
    return tuple(
        VerifiedRuntimeDistribution(
            distribution=pin.distribution,
            version=pin.version,
            wheel_sha256=pin.wheel_sha256,
            record_manifest_sha256="a" * 64,
            import_module=pin.import_module,
            import_origin=pin.import_origin,
            import_origin_sha256="b" * 64,
            verification="wheel-record-sha256+import-origin",
        )
        for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    )


def _product_dependency_receipt() -> VerifiedRuntimeDistribution:
    return VerifiedRuntimeDistribution(
        distribution="science-environment-studio",
        version="0.1.0",
        wheel_sha256="9" * 64,
        record_manifest_sha256="c" * 64,
        import_module="studio.policy_evaluation.gemma_server_bootstrap",
        import_origin="studio/policy_evaluation/gemma_server_bootstrap.py",
        import_origin_sha256="d" * 64,
        verification="wheel-record-sha256+import-origin",
    )


def _challenge(nonce: str) -> dict[str, object]:
    return {
        "attestation_version": "science-local-gemma-runtime-attestation/1",
        "challenge_nonce": nonce,
        "expected_product_wheel_sha256": "9" * 64,
        "expected_trusted_bootstrap_sha256": "7" * 64,
        "requested_model": "google/gemma-4-E4B-it",
        "adapter_revision": "local-gemma-openai-chat/1",
        "sampling_profile": "base-gemma-development-chat-v1",
        "sampling": {
            "profile": "base-gemma-development-chat-v1",
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "tool_choice": "auto",
            "top_p": None,
            "seed": None,
            "streaming": False,
            "store": False,
        },
        "budgets": {
            "max_turns": 64,
            "max_tool_calls": 64,
            "max_provider_tool_calls": 64,
            "max_episode_seconds": 900,
        },
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
