"""Read-only runtime proof and signed ASGI route for pinned local Gemma serving."""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import platform as platform_module
import runpy
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attestation_protocol import (
    canonical_json as _canonical_json,
)
from .attestation_protocol import (
    hmac_sha256_hex,
    validate_runtime_keys,
)
from .model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    BASE_GEMMA_CHECKPOINT_REVISION,
    BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256,
    BASE_GEMMA_MODEL,
    BASE_GEMMA_RENDERER_REVISION,
    PINNED_VLLM_SOURCE_REVISION,
    PINNED_VLLM_VERSION,
    PINNED_VLLM_WHEEL_SHA256,
    EvaluationBudgets,
    ModelSamplingSettings,
    VllmRuntimeConfig,
)
from .runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    APPROVED_RUNTIME_RECEIPT_ID,
    PRODUCTION_RUNTIME_DISTRIBUTION_PINS,
    ApprovedPythonRuntime,
    VerifiedRuntimeDistribution,
    require_approved_runtime_distribution_receipt,
    require_read_only_filesystem,
    resolve_unimported_runtime_distribution,
    verify_approved_runtime_python,
    verify_installed_product_distribution,
    verify_installed_runtime_distribution,
)

_PROCESS_STARTED_AT_UTC = datetime.now(timezone.utc)
_RUNTIME_INSTANCE_ID = secrets.token_hex(32)
_ATTESTATION_PATH = "/v1/science/runtime-attestations"
_RUNTIME_INSTANCE_HEADER = "X-Science-Runtime-Instance"
_PREVERIFIED_PRODUCTION_EVIDENCE: VerifiedLocalGemmaRuntime | None = None
_PREVERIFIED_RUNTIME_KEYS: tuple[str, str] | None = None
_PREVERIFIED_PROCESS_ID: int | None = None
_PREVERIFIED_MIDDLEWARE: Callable[..., Any] | None = None
_ATTESTATION_MIDDLEWARE = (
    "studio.policy_evaluation.gemma_attestation:local_gemma_attestation_middleware"
)
_SERVING_CRITICAL_FILES = (
    "chat_template.jinja",
    "config.json",
    "generation_config.json",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
_INERT_SNAPSHOT_FILES = (".gitattributes", "README.md")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LocalGemmaSnapshotFilePin(_FrozenModel):
    """Exact content identity for one serving-critical checkpoint file."""

    name: Literal[
        "chat_template.jinja",
        "config.json",
        "generation_config.json",
        "processor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ]
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LocalGemmaArtifactPins(_FrozenModel):
    """Artifact identities against which read-only server preflight is checked."""

    checkpoint_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_weight_bytes: int = Field(ge=1)
    checkpoint_weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    serving_files: tuple[LocalGemmaSnapshotFilePin, ...]
    renderer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    vllm_version: str = Field(min_length=1)
    vllm_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    vllm_wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_complete_serving_snapshot(self) -> LocalGemmaArtifactPins:
        names = tuple(pin.name for pin in self.serving_files)
        if len(set(names)) != len(names) or set(names) != set(_SERVING_CRITICAL_FILES):
            raise ValueError("serving snapshot pins must cover the exact critical file set")
        return self

    @property
    def serving_manifest_sha256(self) -> str:
        manifest = {
            pin.name: {"sha256": pin.sha256, "size_bytes": pin.size_bytes}
            for pin in self.serving_files
        }
        canonical = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# Source snapshot: https://huggingface.co/google/gemma-4-E4B-it/tree/
# ee0ef6023621cff504d758262d4e04895a5af4a2. Sizes and SHA-256 values were
# measured from that immutable revision, not from a moving branch.
PRODUCTION_ARTIFACT_PINS = LocalGemmaArtifactPins(
    checkpoint_revision=BASE_GEMMA_CHECKPOINT_REVISION,
    checkpoint_weight_bytes=15_992_595_884,
    checkpoint_weights_sha256=BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256,
    serving_files=(
        LocalGemmaSnapshotFilePin(
            name="chat_template.jinja",
            size_bytes=18_569,
            sha256=("0a2c8073c878ab1da004bee933a998606537bbb62016310352c7285c3f01c5b5"),
        ),
        LocalGemmaSnapshotFilePin(
            name="config.json",
            size_bytes=5_145,
            sha256=("33b10c02df3c2e8536cf323d29d53262aaa2f4d11dbe19bc729373fbe90295d4"),
        ),
        LocalGemmaSnapshotFilePin(
            name="generation_config.json",
            size_bytes=208,
            sha256=("d4226bbe3117d2d253ba4609720ba82c6c4ce4627a9a6ae05387c78983ac03de"),
        ),
        LocalGemmaSnapshotFilePin(
            name="processor_config.json",
            size_bytes=1_689,
            sha256=("32bdf45d2ad4cc29a0822ddd157a182de76644f0419a6228d151495256e9813c"),
        ),
        LocalGemmaSnapshotFilePin(
            name="tokenizer.json",
            size_bytes=32_169_626,
            sha256=("cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"),
        ),
        LocalGemmaSnapshotFilePin(
            name="tokenizer_config.json",
            size_bytes=3_082,
            sha256=("9f4fec4b1dc6ecddf8f4a92e9caea5971c0e67d81309f3f9066a2bee8c362633"),
        ),
    ),
    renderer_revision=BASE_GEMMA_RENDERER_REVISION,
    vllm_version=PINNED_VLLM_VERSION,
    vllm_source_revision=PINNED_VLLM_SOURCE_REVISION,
    vllm_wheel_sha256=PINNED_VLLM_WHEEL_SHA256,
)


class RuntimeHostEvidence(_FrozenModel):
    """Non-routing host facts measured inside the serving process."""

    platform: Literal["linux-x86_64"]
    accelerator_architecture: str = Field(pattern=r"^sm[0-9]{2,3}$")
    accelerator_count: int = Field(ge=1)
    cuda_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    driver_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)+$")
    serving_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    serving_image_digest_provenance: Literal["operator-supplied"] = "operator-supplied"


class VllmLaunchEvidence(_FrozenModel):
    """Path-free critical configuration parsed from the actual vLLM command."""

    served_model: Literal["google/gemma-4-E4B-it"]
    network_scope: Literal["loopback-only"]
    api_key_authentication: Literal[True]
    attestation_middleware_revision: Literal["science-local-gemma-attestation-middleware/1"]
    config: VllmRuntimeConfig

    @classmethod
    def from_argv(
        cls,
        argv: Sequence[str],
        *,
        model_root: Path,
    ) -> VllmLaunchEvidence:
        arguments = tuple(argv)
        approved_arguments = _approved_vllm_arguments(model_root)
        approved_outer_command = build_attested_vllm_command(model_root)
        if arguments not in {
            approved_outer_command,
            ("trusted-bootstrap", *approved_arguments),
        }:
            raise ValueError("vLLM launch arguments are not the exact approved command")
        launched_model = Path(approved_arguments[1]).expanduser().resolve()
        if launched_model != model_root.expanduser().resolve():
            raise ValueError("vLLM launch does not use the verified model snapshot")
        arguments = approved_arguments
        if _has_flag(arguments, "--enable-lora"):
            raise ValueError("base calibration must not enable a model adapter")
        routing = (
            _flag_value(arguments, "--host"),
            _flag_value(arguments, "--port"),
            _flag_value(arguments, "--middleware"),
        )
        if routing != ("127.0.0.1", "8000", _ATTESTATION_MIDDLEWARE):
            raise ValueError("vLLM routing and authentication do not match the approved boundary")
        for required_switch in (
            "--enforce-eager",
            "--enable-auto-tool-choice",
            "--disable-log-requests",
        ):
            if not _has_flag(arguments, required_switch):
                raise ValueError(f"vLLM launch is missing required flag {required_switch}")
        try:
            limits = json.loads(_flag_value(arguments, "--limit-mm-per-prompt"))
        except json.JSONDecodeError as error:
            raise ValueError("vLLM multimodal limits are invalid") from error
        return cls.model_validate(
            {
                "served_model": _flag_value(arguments, "--served-model-name"),
                "network_scope": "loopback-only",
                "api_key_authentication": True,
                "attestation_middleware_revision": ("science-local-gemma-attestation-middleware/1"),
                "config": {
                    "dtype": _flag_value(arguments, "--dtype"),
                    "max_model_len": int(_flag_value(arguments, "--max-model-len")),
                    "tensor_parallel_size": int(_flag_value(arguments, "--tensor-parallel-size")),
                    "gpu_memory_utilization": float(
                        _flag_value(arguments, "--gpu-memory-utilization")
                    ),
                    "enforce_eager": True,
                    "max_num_seqs": int(_flag_value(arguments, "--max-num-seqs")),
                    "generation_config": _flag_value(
                        arguments,
                        "--generation-config",
                    ),
                    "tool_call_parser": _flag_value(arguments, "--tool-call-parser"),
                    "enable_auto_tool_choice": True,
                    "enable_lora": False,
                    "disable_log_requests": True,
                    "limit_mm_per_prompt": limits,
                },
            }
        )


class VerifiedLocalGemmaRuntime(_FrozenModel):
    """Path-free facts independently derived before the scored server is used."""

    runtime_started_at_utc: datetime
    runtime_instance_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    trusted_bootstrap_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    tokenizer_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    vllm_version: str = Field(min_length=1)
    vllm_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    vllm_wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    python_runtime: ApprovedPythonRuntime
    runtime_receipt_id: Literal["science-local-gemma-runtime-cp312-cu129/1"]
    runtime_distributions: tuple[VerifiedRuntimeDistribution, ...]
    product_distribution: VerifiedRuntimeDistribution
    python_bytecode_mode: Literal["fresh-private-prefix-no-write"]
    serving_root_filesystem_mode: Literal["kernel-read-only-mount"]
    network_scope: Literal["loopback-only"]
    api_key_authentication: Literal[True]
    attestation_middleware_revision: Literal["science-local-gemma-attestation-middleware/1"]
    vllm_config: VllmRuntimeConfig
    host: RuntimeHostEvidence

    @model_validator(mode="after")
    def require_utc_start(self) -> VerifiedLocalGemmaRuntime:
        if (
            self.runtime_started_at_utc.tzinfo is None
            or self.runtime_started_at_utc.utcoffset()
            != timezone.utc.utcoffset(self.runtime_started_at_utc)
        ):
            raise ValueError("runtime start time must be UTC")
        if self.python_runtime != APPROVED_RUNTIME_PYTHON:
            raise ValueError("serving Python runtime does not match the approved receipt")
        require_approved_runtime_distribution_receipt(self.runtime_distributions)
        if self.product_distribution.distribution != "science-environment-studio":
            raise ValueError("product wheel receipt is not science-environment-studio")
        return self


class _AttestationChallenge(_FrozenModel):
    attestation_version: Literal["science-local-gemma-runtime-attestation/1"]
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_product_wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_trusted_bootstrap_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_model: Literal["google/gemma-4-E4B-it"]
    adapter_revision: Literal["local-gemma-openai-chat/1"]
    sampling_profile: Literal["base-gemma-development-chat-v1"]
    sampling: ModelSamplingSettings
    budgets: EvaluationBudgets

    @model_validator(mode="after")
    def require_product_defaults(self) -> _AttestationChallenge:
        if self.sampling_profile != self.sampling.profile or self.budgets != (
            EvaluationBudgets(max_turns=64, max_tool_calls=64)
        ):
            raise ValueError("attestation request does not use product defaults")
        return self


def verify_local_gemma_runtime(
    *,
    model_root: Path,
    renderer_root: Path,
    pins: LocalGemmaArtifactPins,
    launch: VllmLaunchEvidence,
    runtime_python: ApprovedPythonRuntime,
    runtime_distributions: tuple[VerifiedRuntimeDistribution, ...],
    product_distribution: VerifiedRuntimeDistribution,
    runtime_instance_id: str,
    trusted_bootstrap_sha256: str,
    renderer_revision_reader: Callable[[Path], str],
    runtime_started_at_utc: datetime,
    host: RuntimeHostEvidence,
) -> VerifiedLocalGemmaRuntime:
    """Hash and validate local artifacts without downloading or mutating them."""
    model_directory = _regular_directory(model_root, "model snapshot")
    renderer_directory = _regular_directory(renderer_root, "renderer checkout")
    approved_model_files = {
        "model.safetensors",
        *_SERVING_CRITICAL_FILES,
        *_INERT_SNAPSHOT_FILES,
    }
    actual_model_files = {entry.name for entry in model_directory.iterdir()}
    if actual_model_files != approved_model_files:
        raise ValueError("model snapshot does not contain the exact approved file set")
    for inert_name in _INERT_SNAPSHOT_FILES:
        _regular_file(
            model_directory / inert_name,
            f"inert checkpoint repository artifact {inert_name}",
        )
    weight_path = _regular_file(
        model_directory / "model.safetensors",
        "checkpoint weight",
    )
    if weight_path.stat().st_size != pins.checkpoint_weight_bytes:
        raise ValueError("checkpoint weight size does not match its pin")
    if _file_sha256(weight_path) != pins.checkpoint_weights_sha256:
        raise ValueError("checkpoint weight digest does not match its pin")
    for pin in pins.serving_files:
        artifact = _regular_file(
            model_directory / pin.name,
            f"serving-critical checkpoint artifact {pin.name}",
        )
        if artifact.stat().st_size != pin.size_bytes:
            raise ValueError(f"{pin.name} size does not match its pin")
        if _file_sha256(artifact) != pin.sha256:
            raise ValueError(f"{pin.name} digest does not match its pin")
    renderer_revision = renderer_revision_reader(renderer_directory).strip()
    if renderer_revision != pins.renderer_revision:
        raise ValueError("renderer revision does not match its pin")
    if launch.served_model != BASE_GEMMA_MODEL:
        raise ValueError("vLLM served-model identity does not match base Gemma")
    return VerifiedLocalGemmaRuntime(
        runtime_started_at_utc=runtime_started_at_utc,
        runtime_instance_id=runtime_instance_id,
        trusted_bootstrap_sha256=trusted_bootstrap_sha256,
        checkpoint_revision=pins.checkpoint_revision,
        checkpoint_weights_sha256=pins.checkpoint_weights_sha256,
        tokenizer_revision=pins.checkpoint_revision,
        tokenizer_manifest_sha256=pins.serving_manifest_sha256,
        renderer_revision=renderer_revision,
        vllm_version=pins.vllm_version,
        vllm_source_revision=pins.vllm_source_revision,
        vllm_wheel_sha256=pins.vllm_wheel_sha256,
        python_runtime=runtime_python.model_copy(deep=True),
        runtime_receipt_id=APPROVED_RUNTIME_RECEIPT_ID,
        runtime_distributions=tuple(item.model_copy(deep=True) for item in runtime_distributions),
        product_distribution=product_distribution.model_copy(deep=True),
        python_bytecode_mode="fresh-private-prefix-no-write",
        serving_root_filesystem_mode="kernel-read-only-mount",
        network_scope=launch.network_scope,
        api_key_authentication=launch.api_key_authentication,
        attestation_middleware_revision=launch.attestation_middleware_revision,
        vllm_config=launch.config.model_copy(deep=True),
        host=host.model_copy(deep=True),
    )


def _approved_vllm_arguments(model_root: Path) -> tuple[str, ...]:
    return (
        "serve",
        str(model_root.expanduser().resolve()),
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--served-model-name",
        BASE_GEMMA_MODEL,
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
        _ATTESTATION_MIDDLEWARE,
    )


def build_attested_vllm_command(
    model_root: Path,
    *,
    trusted_bootstrap: Path | None = None,
) -> tuple[str, ...]:
    """Build the fixed loopback-only base-calibration server command."""
    bootstrap = trusted_bootstrap or (
        Path(__file__).resolve().parents[2]
        / "deployment"
        / "science_local_gemma_bootstrap.py"
    )
    return (
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(bootstrap.expanduser().resolve()),
        *_approved_vllm_arguments(model_root),
    )


def launch_attested_local_gemma(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Reject circular package-owned launch; use the independent bootstrap."""
    del environ
    raise RuntimeError(
        "scored serving must start with the independently pinned stdlib bootstrap"
    )


def serve_attested_local_gemma(
    environ: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
    *,
    module_runner: Callable[..., Any] = runpy.run_module,
) -> None:
    """Verify in the isolated serving interpreter before importing vLLM."""
    resolved_environ = os.environ if environ is None else environ
    arguments = tuple(sys.argv if argv is None else argv)
    pycache_prefix = _regular_directory(
        Path(_required_env(resolved_environ, "PYTHONPYCACHEPREFIX")),
        "serving bytecode cache",
    )
    if (
        resolved_environ.get("PYTHONDONTWRITEBYTECODE") != "1"
        or not sys.dont_write_bytecode
        or sys.pycache_prefix != str(pycache_prefix)
        or any(pycache_prefix.iterdir())
    ):
        raise ValueError("serving Python bytecode isolation is not active")
    model_root = Path(_required_env(resolved_environ, "SCIENCE_LOCAL_GEMMA_MODEL_ROOT"))
    runtime_keys = _runtime_secrets(resolved_environ)
    evidence = _load_production_evidence(resolved_environ, arguments)
    global _PREVERIFIED_MIDDLEWARE, _PREVERIFIED_PROCESS_ID
    global _PREVERIFIED_PRODUCTION_EVIDENCE, _PREVERIFIED_RUNTIME_KEYS
    _PREVERIFIED_PRODUCTION_EVIDENCE = evidence.model_copy(deep=True)
    _PREVERIFIED_RUNTIME_KEYS = runtime_keys
    _PREVERIFIED_PROCESS_ID = os.getpid()
    _PREVERIFIED_MIDDLEWARE = None
    if environ is None:
        _sanitize_serving_environment()
    previous_argv = sys.argv
    approved_arguments = _approved_vllm_arguments(model_root)
    sys.argv = ["vllm.entrypoints.cli.main", *approved_arguments]
    try:
        module_runner(
            "vllm.entrypoints.cli.main",
            run_name="__main__",
            alter_sys=True,
        )
    finally:
        sys.argv = previous_argv


def _sanitize_serving_environment() -> None:
    pycache_prefix = _regular_directory(
        Path(_required_env(os.environ, "PYTHONPYCACHEPREFIX")),
        "serving bytecode cache",
    )
    runtime_cache_root = pycache_prefix / "runtime"
    runtime_cache_root.mkdir(mode=0o700)
    cache_paths = {
        "HOME": runtime_cache_root / "home",
        "TMPDIR": runtime_cache_root / "tmp",
        "XDG_CACHE_HOME": runtime_cache_root / "xdg-cache",
        "HF_HOME": runtime_cache_root / "huggingface",
        "TORCH_HOME": runtime_cache_root / "torch",
        "TRITON_CACHE_DIR": runtime_cache_root / "triton",
        "TORCHINDUCTOR_CACHE_DIR": runtime_cache_root / "torchinductor",
        "VLLM_CACHE_ROOT": runtime_cache_root / "vllm-cache",
        "VLLM_CONFIG_ROOT": runtime_cache_root / "vllm-config",
        "CUDA_CACHE_PATH": runtime_cache_root / "cuda-cache",
    }
    for cache_path in cache_paths.values():
        cache_path.mkdir(mode=0o700)

    retained = {
        name: os.environ[name]
        for name in (
            "PYTHONPYCACHEPREFIX",
            "PYTHONDONTWRITEBYTECODE",
            "CUDA_HOME",
            "CUDA_PATH",
            "CUDA_VISIBLE_DEVICES",
            "NVIDIA_VISIBLE_DEVICES",
            "NVIDIA_DRIVER_CAPABILITIES",
        )
        if name in os.environ
    }
    retained.update(
        {
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "VLLM_NO_USAGE_STATS": "1",
            "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
            "VLLM_PLUGINS": "",
            "DO_NOT_TRACK": "1",
            "USER": "science-gemma",
            "LOGNAME": "science-gemma",
            **{name: str(path) for name, path in cache_paths.items()},
        }
    )
    os.environ.clear()
    os.environ.update(retained)
    tempfile.tempdir = None
    if Path(tempfile.gettempdir()).resolve() != cache_paths["TMPDIR"].resolve():
        raise RuntimeError("serving temporary directory isolation is not active")


def create_attestation_middleware(
    *,
    evidence: VerifiedLocalGemmaRuntime,
    attestation_key: str,
    api_key: str,
    clock: Callable[[], datetime],
    attestation_id_factory: Callable[[], str],
) -> Callable[[Request, Callable[[Request], Any]], Any]:
    """Create vLLM HTTP middleware that signs only fresh strict challenges."""
    validate_runtime_keys(api_key=api_key, attestation_key=attestation_key)

    async def middleware(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        authorization = request.headers.get("authorization", "").encode("utf-8")
        expected = f"Bearer {api_key}".encode()
        if not hmac.compare_digest(authorization, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        if request.url.path != _ATTESTATION_PATH:
            response = cast(Response, await call_next(request))
            if request.url.path == "/v1/chat/completions":
                response.headers[_RUNTIME_INSTANCE_HEADER] = evidence.runtime_instance_id
            return response
        try:
            challenge = _AttestationChallenge.model_validate(await request.json())
            generated_at = clock()
            if generated_at.tzinfo is None or generated_at.utcoffset() != timezone.utc.utcoffset(
                generated_at
            ):
                raise ValueError("attestation clock is not UTC")
            document = _attestation_document(
                evidence=evidence,
                challenge=challenge,
                generated_at_utc=generated_at,
                attestation_id=attestation_id_factory(),
            )
            canonical = _canonical_json(document)
            signature = hmac_sha256_hex(
                key=attestation_key,
                canonical_document=canonical,
            )
        except Exception:
            return JSONResponse(
                status_code=422,
                content={"detail": "The runtime attestation request is invalid."},
            )
        return JSONResponse(
            status_code=200,
            content={"attestation": document, "signature": signature},
        )

    return middleware


def _attestation_document(
    *,
    evidence: VerifiedLocalGemmaRuntime,
    challenge: _AttestationChallenge,
    generated_at_utc: datetime,
    attestation_id: str,
) -> dict[str, Any]:
    if not attestation_id or any(character.isspace() for character in attestation_id):
        raise ValueError("attestation identity is invalid")
    if (
        challenge.expected_product_wheel_sha256
        != evidence.product_distribution.wheel_sha256
    ):
        raise ValueError("attestation challenge expects a different product wheel")
    if challenge.expected_trusted_bootstrap_sha256 != evidence.trusted_bootstrap_sha256:
        raise ValueError("attestation challenge expects a different trusted bootstrap")
    return {
        "attestation_version": challenge.attestation_version,
        "attestation_id": attestation_id,
        "runtime_instance_id": evidence.runtime_instance_id,
        "trusted_bootstrap_sha256": evidence.trusted_bootstrap_sha256,
        "challenge_nonce": challenge.challenge_nonce,
        "generated_at_utc": _utc_text(generated_at_utc),
        "runtime_started_at_utc": _utc_text(evidence.runtime_started_at_utc),
        "served_model": BASE_GEMMA_MODEL,
        "checkpoint_revision": evidence.checkpoint_revision,
        "checkpoint_weights_sha256": evidence.checkpoint_weights_sha256,
        "tokenizer_revision": evidence.tokenizer_revision,
        "tokenizer_manifest_sha256": evidence.tokenizer_manifest_sha256,
        "renderer_revision": evidence.renderer_revision,
        "vllm_version": evidence.vllm_version,
        "vllm_source_revision": evidence.vllm_source_revision,
        "vllm_wheel_sha256": evidence.vllm_wheel_sha256,
        "python_runtime": evidence.python_runtime.model_dump(mode="json"),
        "runtime_receipt_id": evidence.runtime_receipt_id,
        "runtime_distributions": [
            item.model_dump(mode="json") for item in evidence.runtime_distributions
        ],
        "product_distribution": evidence.product_distribution.model_dump(mode="json"),
        "python_bytecode_mode": evidence.python_bytecode_mode,
        "serving_root_filesystem_mode": evidence.serving_root_filesystem_mode,
        "network_scope": evidence.network_scope,
        "api_key_authentication": evidence.api_key_authentication,
        "attestation_middleware_revision": evidence.attestation_middleware_revision,
        "vllm_config": evidence.vllm_config.model_dump(mode="json"),
        "adapter_revision": BASE_GEMMA_ADAPTER_REVISION,
        "served_adapter": "none",
        "sampling_profile": challenge.sampling_profile,
        "max_episode_seconds": challenge.budgets.max_episode_seconds,
        "platform": evidence.host.platform,
        "accelerator_architecture": evidence.host.accelerator_architecture,
        "accelerator_count": evidence.host.accelerator_count,
        "cuda_version": evidence.host.cuda_version,
        "driver_version": evidence.host.driver_version,
        "serving_image_digest": evidence.host.serving_image_digest,
        "serving_image_digest_provenance": (evidence.host.serving_image_digest_provenance),
        "evidence_scope": "server-reported-runtime-state",
    }


def _production_middleware() -> Callable[[Request, Callable[[Request], Any]], Any]:
    global _PREVERIFIED_MIDDLEWARE
    if (
        _PREVERIFIED_PRODUCTION_EVIDENCE is None
        or _PREVERIFIED_RUNTIME_KEYS is None
        or os.getpid() != _PREVERIFIED_PROCESS_ID
    ):
        raise RuntimeError("local Gemma middleware was not started by the verified bootstrap")
    if _PREVERIFIED_MIDDLEWARE is not None:
        return _PREVERIFIED_MIDDLEWARE
    api_key, attestation_key = _PREVERIFIED_RUNTIME_KEYS
    evidence = _PREVERIFIED_PRODUCTION_EVIDENCE.model_copy(deep=True)
    _PREVERIFIED_MIDDLEWARE = create_attestation_middleware(
        evidence=evidence,
        attestation_key=attestation_key,
        api_key=api_key,
        clock=lambda: datetime.now(timezone.utc),
        attestation_id_factory=lambda: f"attestation-{secrets.token_hex(16)}",
    )
    return _PREVERIFIED_MIDDLEWARE


def _clear_preverified_state_after_fork() -> None:
    global _PREVERIFIED_MIDDLEWARE, _PREVERIFIED_PROCESS_ID
    global _PREVERIFIED_PRODUCTION_EVIDENCE, _PREVERIFIED_RUNTIME_KEYS
    _PREVERIFIED_PRODUCTION_EVIDENCE = None
    _PREVERIFIED_RUNTIME_KEYS = None
    _PREVERIFIED_PROCESS_ID = None
    _PREVERIFIED_MIDDLEWARE = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_clear_preverified_state_after_fork)


async def local_gemma_attestation_middleware(
    request: Request,
    call_next: Callable[[Request], Any],
) -> Response:
    """Import path supplied to vLLM ``--middleware`` on the approved host."""
    middleware = _production_middleware()
    return cast(Response, await middleware(request, call_next))


def _load_production_evidence(
    environ: Mapping[str, str],
    argv: Sequence[str],
) -> VerifiedLocalGemmaRuntime:
    model_root = Path(_required_env(environ, "SCIENCE_LOCAL_GEMMA_MODEL_ROOT"))
    renderer_root = Path(_required_env(environ, "SCIENCE_LOCAL_GEMMA_RENDERER_ROOT"))
    require_read_only_filesystem(model_root, "model snapshot root")
    require_read_only_filesystem(renderer_root, "renderer checkout root")
    launch = VllmLaunchEvidence.from_argv(argv, model_root=model_root)
    runtime_python = verify_approved_runtime_python(
        implementation=sys.implementation.name,
        version=(sys.version_info.major, sys.version_info.minor),
        cache_tag=sys.implementation.cache_tag,
        platform=_runtime_platform(),
    )
    runtime_distributions = _verify_production_runtime_distributions(environ)
    product_distribution = _verify_production_product_distribution(environ)
    trusted_bootstrap_sha256 = _required_env(
        environ,
        "SCIENCE_LOCAL_GEMMA_VERIFIED_BOOTSTRAP_SHA256",
    )
    if trusted_bootstrap_sha256 != _required_env(
        environ,
        "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256",
    ):
        raise ValueError("trusted bootstrap digest does not match its external pin")
    return verify_local_gemma_runtime(
        model_root=model_root,
        renderer_root=renderer_root,
        pins=PRODUCTION_ARTIFACT_PINS,
        launch=launch,
        runtime_python=runtime_python,
        runtime_distributions=runtime_distributions,
        product_distribution=product_distribution,
        runtime_instance_id=_RUNTIME_INSTANCE_ID,
        trusted_bootstrap_sha256=trusted_bootstrap_sha256,
        renderer_revision_reader=verify_renderer_checkout,
        runtime_started_at_utc=_PROCESS_STARTED_AT_UTC,
        host=_host_evidence(environ),
    )


def _host_evidence(environ: Mapping[str, str]) -> RuntimeHostEvidence:
    if platform_module.system() != "Linux" or platform_module.machine() != "x86_64":
        raise ValueError("local Gemma serving requires Linux x86_64")
    nvidia_smi = _trusted_root_executable(
        Path(_required_env(environ, "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH")),
        "NVIDIA management executable",
    )
    require_read_only_filesystem(nvidia_smi, "NVIDIA management executable")
    if _file_sha256(nvidia_smi) != _required_env(
        environ,
        "SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256",
    ):
        raise ValueError("NVIDIA management executable digest does not match its pin")
    probe = subprocess.run(
        (
            str(nvidia_smi),
            "--query-gpu=compute_cap,driver_version",
            "--format=csv,noheader,nounits",
        ),
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        text=True,
        timeout=10,
    )
    rows = tuple(line.strip() for line in probe.stdout.splitlines() if line.strip())
    if not rows:
        raise ValueError("no CUDA accelerator was reported")
    parsed = tuple(tuple(part.strip() for part in row.split(",")) for row in rows)
    if any(len(row) != 2 for row in parsed):
        raise ValueError("CUDA accelerator evidence is malformed")
    compute_capabilities = {row[0] for row in parsed}
    driver_versions = {row[1] for row in parsed}
    if len(compute_capabilities) != 1 or len(driver_versions) != 1:
        raise ValueError("CUDA accelerator evidence is not homogeneous")
    capability = next(iter(compute_capabilities)).replace(".", "")
    cuda_version = _required_env(environ, "SCIENCE_LOCAL_GEMMA_CUDA_VERSION")
    if cuda_version != "12.9":
        raise ValueError("local Gemma CUDA runtime does not match the cu129 receipt")
    return RuntimeHostEvidence(
        platform="linux-x86_64",
        accelerator_architecture=f"sm{capability}",
        accelerator_count=len(rows),
        cuda_version=cuda_version,
        driver_version=next(iter(driver_versions)),
        serving_image_digest=_required_env(
            environ,
            "SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST",
        ),
    )


def _runtime_platform() -> str:
    return f"{platform_module.system().lower()}-{platform_module.machine()}"


def _verify_production_runtime_distributions(
    environ: Mapping[str, str],
) -> tuple[VerifiedRuntimeDistribution, ...]:
    receipt = []
    for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS:
        distribution = importlib.metadata.distribution(pin.distribution)
        installed_version, installation_root, module_origin = (
            resolve_unimported_runtime_distribution(
                pin=pin,
                distribution=distribution,
            )
        )
        wheel = Path(_required_env(environ, pin.wheel_setting))
        require_read_only_filesystem(
            installation_root,
            f"installed {pin.distribution} distribution root",
        )
        require_read_only_filesystem(wheel, f"staged {pin.distribution} wheel")
        receipt.append(
            verify_installed_runtime_distribution(
                pin=pin,
                wheel=wheel,
                installed_version=installed_version,
                installation_root=installation_root,
                module_origin=module_origin,
            )
        )
    return require_approved_runtime_distribution_receipt(tuple(receipt))


def _verify_production_product_distribution(
    environ: Mapping[str, str],
) -> VerifiedRuntimeDistribution:
    distribution = importlib.metadata.distribution("science-environment-studio")
    installation_root = Path(distribution.locate_file(""))
    wheel = Path(_required_env(environ, "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL"))
    require_read_only_filesystem(installation_root, "installed product distribution root")
    require_read_only_filesystem(wheel, "staged product wheel")
    return verify_installed_product_distribution(
        wheel=wheel,
        expected_wheel_sha256=_required_env(
            environ,
            "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256",
        ),
        distribution=distribution,
        module_origin=Path(__file__).with_name("gemma_server_bootstrap.py"),
    )


def verify_renderer_checkout(path: Path) -> str:
    """Return a renderer revision only for a clean, non-symlink checkout."""
    checkout = _regular_directory(path, "renderer checkout")
    git_directory = _regular_directory(checkout / ".git", "renderer Git directory")
    git_executable = _trusted_root_executable(Path("/usr/bin/git"), "Git executable")
    git_options = (
        str(git_executable),
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        "diff.external=",
    )
    git_discovery_command = (
        *git_options,
        "-C",
        str(checkout),
    )
    git_environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    identity = subprocess.run(
        (
            *git_discovery_command,
            "rev-parse",
            "--absolute-git-dir",
            "--show-toplevel",
        ),
        check=True,
        capture_output=True,
        env=git_environment,
        text=True,
        timeout=10,
    )
    identity_lines = identity.stdout.splitlines()
    if len(identity_lines) != 2:
        raise ValueError("renderer Git repository identity is malformed")
    reported_git_directory = Path(identity_lines[0])
    reported_worktree = Path(identity_lines[1])
    if reported_git_directory != git_directory or reported_worktree != checkout:
        raise ValueError("renderer Git repository identity does not match its checkout")
    git_command = (
        *git_options,
        f"--git-dir={git_directory}",
        f"--work-tree={checkout}",
    )
    revision = subprocess.run(
        (*git_command, "rev-parse", "--verify", "HEAD^{commit}"),
        check=True,
        capture_output=True,
        env=git_environment,
        text=True,
        timeout=10,
    )
    committed_tree = subprocess.run(
        (*git_command, "ls-tree", "-r", "-z", "--full-tree", "HEAD"),
        check=True,
        capture_output=True,
        env=git_environment,
        timeout=10,
    )
    staged_tree = subprocess.run(
        (*git_command, "ls-files", "--stage", "-z"),
        check=True,
        capture_output=True,
        env=git_environment,
        timeout=10,
    )
    index_flags = subprocess.run(
        (*git_command, "ls-files", "-v", "-z"),
        check=True,
        capture_output=True,
        env=git_environment,
        timeout=10,
    )
    committed_entries = _parse_renderer_tree(committed_tree.stdout)
    staged_entries = _parse_renderer_index(staged_tree.stdout)
    hidden_tracked_state = any(
        record and not record.startswith(b"H ")
        for record in index_flags.stdout.split(b"\0")
    )
    if (
        hidden_tracked_state
        or committed_entries != staged_entries
        or not _renderer_filesystem_matches(checkout, committed_entries)
    ):
        raise ValueError("renderer checkout must be clean, including untracked files")
    return revision.stdout.strip()


def _parse_renderer_tree(output: bytes) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode_bytes, object_type, object_id = metadata.split(b" ")
        except ValueError as error:
            raise ValueError("renderer commit tree is malformed") from error
        if object_type != b"blob" or mode_bytes not in {b"100644", b"100755", b"120000"}:
            raise ValueError("renderer commit tree contains an unsupported entry")
        path = _renderer_relative_path(path_bytes)
        object_id_text = object_id.decode("ascii")
        if (
            len(object_id_text) != 40
            or any(character not in "0123456789abcdef" for character in object_id_text)
            or path in entries
        ):
            raise ValueError("renderer commit tree is malformed")
        entries[path] = (mode_bytes.decode("ascii"), object_id_text)
    return entries


def _parse_renderer_index(output: bytes) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode_bytes, object_id, stage = metadata.split(b" ")
        except ValueError as error:
            raise ValueError("renderer index is malformed") from error
        path = _renderer_relative_path(path_bytes)
        object_id_text = object_id.decode("ascii")
        if (
            stage != b"0"
            or mode_bytes not in {b"100644", b"100755", b"120000"}
            or len(object_id_text) != 40
            or any(character not in "0123456789abcdef" for character in object_id_text)
            or path in entries
        ):
            raise ValueError("renderer index is malformed")
        entries[path] = (mode_bytes.decode("ascii"), object_id_text)
    return entries


def _renderer_relative_path(path_bytes: bytes) -> str:
    parts = path_bytes.split(b"/")
    if (
        not path_bytes
        or path_bytes.startswith(b"/")
        or any(part in {b"", b".", b"..", b".git"} for part in parts)
    ):
        raise ValueError("renderer tree path is unsafe")
    return os.fsdecode(path_bytes)


def _renderer_filesystem_matches(
    checkout: Path,
    committed_entries: Mapping[str, tuple[str, str]],
) -> bool:
    actual_files: dict[str, Path] = {}
    actual_directories: set[str] = set()
    pending = [(checkout, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                if not prefix and child.name == ".git":
                    continue
                relative = f"{prefix}/{child.name}" if prefix else child.name
                metadata = child.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    actual_directories.add(relative)
                    pending.append((Path(child.path), relative))
                elif stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    actual_files[relative] = Path(child.path)
                else:
                    return False
    expected_directories = {
        "/".join(path.split("/")[:index])
        for path in committed_entries
        for index in range(1, len(path.split("/")))
    }
    if set(actual_files) != set(committed_entries) or actual_directories != expected_directories:
        return False
    return all(
        _renderer_file_matches(actual_files[path], mode=mode, object_id=object_id)
        for path, (mode, object_id) in committed_entries.items()
    )


def _renderer_file_matches(path: Path, *, mode: str, object_id: str) -> bool:
    metadata = path.lstat()
    if mode == "120000":
        if not stat.S_ISLNK(metadata.st_mode):
            return False
        payload = os.fsencode(os.readlink(path))
        return _git_blob_sha1(payload) == object_id
    if not stat.S_ISREG(metadata.st_mode):
        return False
    expected_executable = mode == "100755"
    if bool(stat.S_IMODE(metadata.st_mode) & 0o111) != expected_executable:
        return False
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_mode != metadata.st_mode
            or opened.st_size != metadata.st_size
        ):
            return False
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {opened.st_size}\0".encode("ascii"))
        total = 0
        while block := os.read(descriptor, 1024 * 1024):
            total += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return (
        total == opened.st_size
        and opened.st_dev == after.st_dev
        and opened.st_ino == after.st_ino
        and opened.st_mode == after.st_mode
        and opened.st_size == after.st_size
        and digest.hexdigest() == object_id
    )


def _git_blob_sha1(payload: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest()


def _required_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise ValueError(f"required Gemma runtime setting {name} is missing")
    return value


def _runtime_secrets(environ: Mapping[str, str]) -> tuple[str, str]:
    api_key = _required_env(environ, "SCIENCE_LOCAL_GEMMA_API_KEY")
    attestation_key = _required_env(environ, "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY")
    return validate_runtime_keys(api_key=api_key, attestation_key=attestation_key)


def _regular_directory(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError(f"{label} must be a non-symlink directory")
    return candidate.resolve(strict=True)


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a non-symlink regular file")
    return path.resolve(strict=True)


def _trusted_root_executable(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    executable = _regular_file(path, label)
    metadata = executable.stat()
    if (
        metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise ValueError(f"{label} must be root-owned and not group/world writable")
    return executable


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _has_flag(arguments: Sequence[str], name: str) -> bool:
    return any(argument == name or argument.startswith(f"{name}=") for argument in arguments)


def _flag_value(arguments: Sequence[str], name: str) -> str:
    for index, argument in enumerate(arguments):
        if argument.startswith(f"{name}="):
            return argument.split("=", 1)[1]
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
    raise ValueError(f"vLLM launch is missing required flag {name}")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "build_attested_vllm_command",
    "LocalGemmaArtifactPins",
    "LocalGemmaSnapshotFilePin",
    "PRODUCTION_ARTIFACT_PINS",
    "RuntimeHostEvidence",
    "VerifiedLocalGemmaRuntime",
    "VllmLaunchEvidence",
    "create_attestation_middleware",
    "launch_attested_local_gemma",
    "local_gemma_attestation_middleware",
    "serve_attested_local_gemma",
    "verify_local_gemma_runtime",
    "verify_renderer_checkout",
]


if __name__ == "__main__":
    launch_attested_local_gemma()
