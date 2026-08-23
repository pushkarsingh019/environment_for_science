"""Process-seam tests for the independent local-Gemma service launcher."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_API_SECRET = "api-key-material-for-launcher-tests-000000000000"
_ATTESTATION_SECRET = "attestation-key-for-launcher-tests-111111111111"
_REQUIRED_CHILD_ENVIRONMENT = frozenset(
    {
        "LC_ALL",
        "SCIENCE_LOCAL_GEMMA_CUDA_VERSION",
        "SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL",
        "SCIENCE_LOCAL_GEMMA_MODEL_ROOT",
        "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH",
        "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256",
        "SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT",
        "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL",
        "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256",
        "SCIENCE_LOCAL_GEMMA_RENDERER_ROOT",
        "SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL",
        "SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST",
        "SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL",
        "SCIENCE_LOCAL_GEMMA_TORCH_WHEEL",
        "SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL",
        "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256",
        "SCIENCE_LOCAL_GEMMA_VLLM_WHEEL",
    }
)


def _c_string_literal(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


@pytest.fixture
def launcher_identity_validator(tmp_path: Path) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a C compiler is required for the launcher identity contract")

    repository = Path(__file__).resolve().parents[2]
    launcher_source = repository / "deployment" / "science_local_gemma_launcher.c"
    harness_source = tmp_path / "launcher_identity_validator.c"
    harness = tmp_path / "launcher-identity-validator"
    harness_source.write_text(
        "#define SCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING 1\n"
        "#define main science_local_gemma_embedded_main\n"
        f"#include {_c_string_literal(launcher_source)}\n"
        "#undef main\n"
        "int main(int argc, char **argv) {\n"
        "  gid_t groups[16];\n"
        "  int index;\n"
        "  if (argc < 6 || argc > 20) return 90;\n"
        "  for (index = 5; index < argc; ++index) {\n"
        "    groups[index - 5] = (gid_t)strtoul(argv[index], NULL, 10);\n"
        "  }\n"
        "  return runtime_identity_is_approved(\n"
        "    (uid_t)strtoul(argv[1], NULL, 10),\n"
        "    (uid_t)strtoul(argv[2], NULL, 10),\n"
        "    (gid_t)strtoul(argv[3], NULL, 10),\n"
        "    (gid_t)strtoul(argv[4], NULL, 10),\n"
        "    groups,\n"
        "    (size_t)(argc - 5)\n"
        "  ) ? 0 : 1;\n"
        "}\n"
    )
    subprocess.run(
        (
            compiler,
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness_source),
            "-o",
            str(harness),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    return harness


@pytest.mark.parametrize(
    ("identity", "approved"),
    (
        ((65532, 65532, 65532, 65532, 65532), True),
        ((65532, 65532, 65532, 65532), False),
        ((65532, 65532, 65532, 65532, 44, 65532), False),
        ((65532, 65532, 65532, 65532, 992, 65532), False),
        ((65532, 65532, 65532, 65532, 0, 65532), False),
        ((65532, 65532, 65532, 65532, 6, 65532), False),
        ((65532, 65532, 65532, 65532, 42, 65532), False),
        ((1000, 1000, 65532, 65532, 65532), False),
        ((65532, 65532, 1000, 1000, 65532), False),
    ),
)
def test_launcher_accepts_only_the_exact_approved_runtime_identity(
    launcher_identity_validator: Path,
    identity: tuple[int, ...],
    approved: bool,
) -> None:
    completed = subprocess.run(
        (str(launcher_identity_validator), *(str(value) for value in identity)),
        capture_output=True,
        text=True,
        check=False,
    )

    assert (completed.returncode == 0) is approved


@pytest.fixture
def launcher_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a C compiler is required for the launcher process-seam contract")

    repository = Path(__file__).resolve().parents[2]
    source = repository / "deployment" / "science_local_gemma_launcher.c"
    launcher = tmp_path / "science-local-gemma-launcher"
    fake_python = tmp_path / "python3.12"
    fake_python_source = tmp_path / "record_exec.c"
    bootstrap = tmp_path / "science_local_gemma_bootstrap.py"
    secret_directory = tmp_path / "run" / "secrets"
    output_directory = tmp_path / "output"
    secret_directory.mkdir(parents=True)
    output_directory.mkdir()
    bootstrap.write_text("# independently pinned test bootstrap\n" * 17)
    bootstrap.chmod(0o444)

    api_secret = secret_directory / "science-local-gemma-api-key"
    attestation_secret = secret_directory / "science-local-gemma-attestation-key"
    api_secret.write_text(_API_SECRET)
    attestation_secret.write_text(_ATTESTATION_SECRET)
    api_secret.chmod(0o400)
    attestation_secret.chmod(0o400)

    fake_python_source.write_text(
        "#include <errno.h>\n"
        "#include <fcntl.h>\n"
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <string.h>\n"
        "extern char **environ;\n"
        "int main(int argc, char **argv) {\n"
        "  for (int descriptor = 3; descriptor < 64; ++descriptor) {\n"
        "    errno = 0;\n"
        "    if (fcntl(descriptor, F_GETFD) != -1 || errno != EBADF) return 80;\n"
        "  }\n"
        '  const char *root = getenv("SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT");\n'
        '  const char *api = getenv("SCIENCE_LOCAL_GEMMA_API_KEY");\n'
        '  const char *attestation = getenv("SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY");\n'
        '  const char *locale = getenv("LC_ALL");\n'
        '  if (!locale || strcmp(locale, "C") != 0) return 79;\n'
        "  if (!root || api || attestation) return 81;\n"
        "  size_t root_length = strlen(root);\n"
        "  char *argv_path = malloc(root_length + 10);\n"
        "  char *env_path = malloc(root_length + 24);\n"
        "  if (!argv_path || !env_path) return 83;\n"
        '  sprintf(argv_path, "%s/argv.txt", root);\n'
        '  sprintf(env_path, "%s/environment-names.txt", root);\n'
        '  FILE *arguments = fopen(argv_path, "w");\n'
        '  FILE *environment = fopen(env_path, "w");\n'
        "  if (!arguments || !environment) return 84;\n"
        "  for (int index = 1; index < argc; ++index) "
        'fprintf(arguments, "%s\\n", argv[index]);\n'
        "  for (char **entry = environ; *entry; ++entry) {\n"
        "    const char *equals = strchr(*entry, '=');\n"
        "    if (!equals) return 85;\n"
        '    fprintf(environment, "%.*s\\n", (int)(equals - *entry), *entry);\n'
        "  }\n"
        "  return fclose(arguments) != 0 || fclose(environment) != 0;\n"
        "}\n"
    )
    subprocess.run(
        (
            compiler,
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(fake_python_source),
            "-o",
            str(fake_python),
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        (
            compiler,
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DSCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING=1",
            "-DSCIENCE_LOCAL_GEMMA_PYTHON_PATH=" + _c_string_literal(fake_python),
            "-DSCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH=" + _c_string_literal(bootstrap),
            "-DSCIENCE_LOCAL_GEMMA_SECRET_DIRECTORY=" + _c_string_literal(secret_directory),
            str(source),
            "-o",
            str(launcher),
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    digest = hashlib.sha256(bootstrap.read_bytes()).hexdigest()
    environment = {
        "HOME": "/must/not/survive",
        "LANG": "attacker_LOCALE.UTF-8",
        "LC_ALL": "attacker_LOCALE.UTF-8",
        "LC_CTYPE": "attacker_LOCALE.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "SCIENCE_LOCAL_GEMMA_CUDA_VERSION": "12.9",
        "SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL": "/approved/ro/wheels/jinja2.whl",
        "SCIENCE_LOCAL_GEMMA_MODEL_ROOT": "/approved/ro/model",
        "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH": "/usr/bin/nvidia-smi",
        "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256": "a" * 64,
        "SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT": str(output_directory),
        "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL": "/approved/ro/release/product.whl",
        "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": "b" * 64,
        "SCIENCE_LOCAL_GEMMA_RENDERER_ROOT": "/approved/ro/renderer",
        "SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL": "/approved/ro/wheels/safe.whl",
        "SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST": "sha256:" + "c" * 64,
        "SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL": "/approved/ro/wheels/token.whl",
        "SCIENCE_LOCAL_GEMMA_TORCH_WHEEL": "/approved/ro/wheels/torch.whl",
        "SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL": "/approved/ro/wheels/transformers.whl",
        "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": digest,
        "SCIENCE_LOCAL_GEMMA_VLLM_WHEEL": "/approved/ro/wheels/vllm.whl",
    }
    return launcher, environment, bootstrap, output_directory


def test_launcher_execs_only_the_canonical_command_and_allowlisted_environment(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, bootstrap, output_directory = launcher_fixture

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    arguments = (output_directory / "argv.txt").read_text().splitlines()
    assert arguments == [
        "-I",
        "-S",
        "-B",
        str(bootstrap),
        "serve",
        "/approved/ro/model",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--served-model-name",
        "google/gemma-4-E4B-it",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "32768",
        "--tensor-parallel-size",
        "1",
        "--gpu-memory-utilization",
        "0.35",
        "--enforce-eager",
        "--max-num-seqs",
        "16",
        "--generation-config",
        "vllm",
        "--tool-call-parser",
        "gemma4",
        "--enable-auto-tool-choice",
        "--disable-log-requests",
        "--limit-mm-per-prompt",
        '{"image":0,"audio":0,"video":0}',
        "--middleware",
        "studio.policy_evaluation.gemma_attestation:local_gemma_attestation_middleware",
    ]
    serialized_arguments = "\n".join(arguments)
    assert _API_SECRET not in serialized_arguments
    assert _ATTESTATION_SECRET not in serialized_arguments
    assert "science-local-gemma-api-key" not in serialized_arguments
    assert "science-local-gemma-attestation-key" not in serialized_arguments
    child_environment = frozenset(
        (output_directory / "environment-names.txt").read_text().splitlines()
    )
    assert child_environment == _REQUIRED_CHILD_ENVIRONMENT


def test_launcher_rejects_bootstrap_drift_before_exec(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, bootstrap, output_directory = launcher_fixture
    bootstrap.chmod(0o644)
    bootstrap.write_text("# changed after the operator recorded its digest\n")
    bootstrap.chmod(0o444)

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "digest does not match" in completed.stderr
    assert (output_directory / "argv.txt").exists() is False
    assert _API_SECRET not in completed.stderr
    assert _ATTESTATION_SECRET not in completed.stderr


@pytest.mark.parametrize(
    "invalid_secret",
    (
        "symlink",
        "directory",
        "mode",
        "setuid_mode",
        "setgid_mode",
        "sticky_mode",
        "newline",
        "non_ascii",
        "short",
        "oversize",
        "same",
    ),
)
def test_launcher_rejects_ambiguous_or_weak_secret_files_without_disclosure(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
    invalid_secret: str,
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture
    secret_directory = launcher.parent / "run" / "secrets"
    api_secret = secret_directory / "science-local-gemma-api-key"
    attestation_secret = secret_directory / "science-local-gemma-attestation-key"
    if invalid_secret == "symlink":
        api_secret.unlink()
        target = launcher.parent / "secret-target"
        target.write_text(_API_SECRET)
        target.chmod(0o400)
        api_secret.symlink_to(target)
    elif invalid_secret == "directory":
        api_secret.unlink()
        api_secret.mkdir(mode=0o400)
    elif invalid_secret == "mode":
        api_secret.chmod(0o600)
    elif invalid_secret == "setuid_mode":
        api_secret.chmod(0o4400)
    elif invalid_secret == "setgid_mode":
        api_secret.chmod(0o2400)
    elif invalid_secret == "sticky_mode":
        api_secret.chmod(0o1400)
    elif invalid_secret == "newline":
        api_secret.chmod(0o600)
        api_secret.write_text(_API_SECRET + "\n")
        api_secret.chmod(0o400)
    elif invalid_secret == "non_ascii":
        api_secret.chmod(0o600)
        api_secret.write_bytes(b"a" * 32 + b"\xff")
        api_secret.chmod(0o400)
    elif invalid_secret == "short":
        api_secret.chmod(0o600)
        api_secret.write_text("too-short")
        api_secret.chmod(0o400)
    elif invalid_secret == "oversize":
        api_secret.chmod(0o600)
        api_secret.write_text("a" * 4097)
        api_secret.chmod(0o400)
    elif invalid_secret == "same":
        attestation_secret.chmod(0o600)
        attestation_secret.write_text(_API_SECRET)
        attestation_secret.chmod(0o400)

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert (output_directory / "argv.txt").exists() is False
    assert _API_SECRET not in completed.stderr
    assert _ATTESTATION_SECRET not in completed.stderr


def test_launcher_forwards_only_validated_optional_cuda_settings(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture
    environment.update(
        {
            "CUDA_HOME": "/usr/local/cuda",
            "CUDA_PATH": "/usr/local/cuda",
            "CUDA_VISIBLE_DEVICES": "0",
            "NVIDIA_VISIBLE_DEVICES": "all",
            "NVIDIA_DRIVER_CAPABILITIES": "compute,utility",
        }
    )

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    child_environment = frozenset(
        (output_directory / "environment-names.txt").read_text().splitlines()
    )
    assert child_environment == _REQUIRED_CHILD_ENVIRONMENT | {
        "CUDA_HOME",
        "CUDA_PATH",
        "CUDA_VISIBLE_DEVICES",
    }


def test_launcher_closes_inherited_non_stdio_descriptors_before_exec(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture
    inherited = os.open(launcher.parent / "must-not-be-inherited", os.O_CREAT | os.O_RDWR)
    try:
        completed = subprocess.run(
            (str(launcher),),
            env=environment,
            pass_fds=(inherited,),
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        os.close(inherited)

    assert completed.returncode == 0, completed.stderr
    assert (output_directory / "argv.txt").exists()


@pytest.mark.parametrize(
    ("environment_change", "expected_error"),
    (
        ({"SCIENCE_LOCAL_GEMMA_MODEL_ROOT": None}, "required serving environment"),
        ({"SCIENCE_LOCAL_GEMMA_MODEL_ROOT": "relative/model"}, "setting is invalid"),
        ({"SCIENCE_LOCAL_GEMMA_CUDA_VERSION": "12.8"}, "setting is invalid"),
        ({"SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256": "A" * 64}, "setting is invalid"),
        ({"SCIENCE_LOCAL_GEMMA_UNREVIEWED": "enabled"}, "undeclared serving"),
        ({"GLIBC_TUNABLES": "glibc.malloc.check=3"}, "undeclared launcher"),
        ({"UNRELATED_CONTAINER_SETTING": "enabled"}, "undeclared launcher"),
        ({"PYTHONHASHSEED": "0"}, "injection environment"),
        ({"LD_LIBRARY_PATH": "/attacker/library-path"}, "injection environment"),
        ({"SCIENCE_LOCAL_GEMMA_API_KEY": _API_SECRET}, "fixed secret files"),
    ),
)
def test_launcher_rejects_missing_malformed_or_injected_environment(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
    environment_change: dict[str, str | None],
    expected_error: str,
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture
    for name, value in environment_change.items():
        if value is None:
            environment.pop(name)
        else:
            environment[name] = value

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert (output_directory / "argv.txt").exists() is False
    assert _API_SECRET not in completed.stderr
    assert _ATTESTATION_SECRET not in completed.stderr


def test_launcher_rejects_every_command_line_argument(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture

    completed = subprocess.run(
        (str(launcher), "--api-key", _API_SECRET),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "accepts no command-line arguments" in completed.stderr
    assert _API_SECRET not in completed.stderr
    assert (output_directory / "argv.txt").exists() is False


def test_launcher_exec_failure_does_not_disclose_loaded_secrets(
    launcher_fixture: tuple[Path, dict[str, str], Path, Path],
) -> None:
    launcher, environment, _bootstrap, output_directory = launcher_fixture
    fake_python = launcher.parent / "python3.12"
    fake_python.write_bytes(b"not-an-executable-format")
    fake_python.chmod(0o755)

    completed = subprocess.run(
        (str(launcher),),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "could not be executed" in completed.stderr
    assert _API_SECRET not in completed.stderr
    assert _ATTESTATION_SECRET not in completed.stderr
    assert (output_directory / "argv.txt").exists() is False


@pytest.mark.skipif(sys.platform != "linux", reason="production launcher is Linux-only")
def test_production_launcher_build_has_no_dynamic_interpreter(tmp_path: Path) -> None:
    compiler = shutil.which("cc")
    readelf = shutil.which("readelf")
    if compiler is None or readelf is None:
        pytest.skip("Linux C compiler and readelf are required for the static-launcher proof")
    repository = Path(__file__).resolve().parents[2]
    source = repository / "deployment" / "science_local_gemma_launcher.c"
    launcher = tmp_path / "science-local-gemma-launcher"

    subprocess.run(
        (
            compiler,
            "-std=c17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-static-pie",
            "-fstack-protector-strong",
            "-D_FORTIFY_SOURCE=3",
            str(source),
            "-Wl,-z,relro,-z,now,-z,noexecstack",
            "-o",
            str(launcher),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    program_headers = subprocess.run(
        (readelf, "-lW", str(launcher)),
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "INTERP" not in program_headers
