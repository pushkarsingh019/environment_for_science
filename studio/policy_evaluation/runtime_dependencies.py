"""Immutable artifact and import provenance for the local inference runtime."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.machinery
import importlib.metadata
import io
import json
import os
import re
import sys
from email.parser import Parser
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovedPythonRuntime(_FrozenModel):
    """Interpreter ABI selected by the approved Linux x86_64 wheel receipt."""

    implementation: Literal["cpython"]
    version: Literal["3.12"]
    abi_tag: Literal["cp312"]
    platform: Literal["linux-x86_64"]


class RuntimeDistributionPin(_FrozenModel):
    """Approved identity of one serving-critical Python wheel."""

    distribution: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    import_module: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
    import_origin: str = Field(pattern=r"^[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$")
    version: str = Field(min_length=1, max_length=128)
    wheel_filename: str = Field(pattern=r"^[a-zA-Z0-9_.+-]+\.whl$")
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_source: str | None = Field(default=None, pattern=r"^https://[^\s]+$")
    wheel_setting: str = Field(pattern=r"^SCIENCE_LOCAL_GEMMA_[A-Z0-9_]+_WHEEL$")

    @field_validator("version")
    @classmethod
    def require_safe_version(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("runtime distribution version is invalid")
        return value


class VerifiedRuntimeDistribution(_FrozenModel):
    """Path-free proof derived from a pinned wheel and its installed files."""

    distribution: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    version: str = Field(min_length=1, max_length=128)
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    import_module: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
    import_origin: str = Field(pattern=r"^[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$")
    import_origin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification: Literal["wheel-record-sha256+import-origin"]


APPROVED_RUNTIME_PYTHON = ApprovedPythonRuntime(
    implementation="cpython",
    version="3.12",
    abi_tag="cp312",
    platform="linux-x86_64",
)
APPROVED_RUNTIME_RECEIPT_ID: Literal["science-local-gemma-runtime-cp312-cu129/1"] = (
    "science-local-gemma-runtime-cp312-cu129/1"
)

# Immutable artifact URLs and SHA-256 values are taken from the vLLM release
# index, PyTorch cu129 wheel index, and PyPI release JSON listed in the operator
# runbook. The lock targets one CPython 3.12 Linux x86_64 serving environment.
PRODUCTION_RUNTIME_DISTRIBUTION_PINS = (
    RuntimeDistributionPin(
        distribution="jinja2",
        import_module="jinja2",
        import_origin="jinja2/__init__.py",
        version="3.1.6",
        wheel_filename="jinja2-3.1.6-py3-none-any.whl",
        wheel_sha256="85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67",
        artifact_source=(
            "https://files.pythonhosted.org/packages/62/a1/"
            "3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/"
            "jinja2-3.1.6-py3-none-any.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL",
    ),
    RuntimeDistributionPin(
        distribution="safetensors",
        import_module="safetensors",
        import_origin="safetensors/__init__.py",
        version="0.7.0",
        wheel_filename=(
            "safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        ),
        wheel_sha256="dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48",
        artifact_source=(
            "https://files.pythonhosted.org/packages/a0/60/"
            "429e9b1cb3fc651937727befe258ea24122d9663e4d5709a48c9cbfceecb/"
            "safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64."
            "manylinux2014_x86_64.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL",
    ),
    RuntimeDistributionPin(
        distribution="tokenizers",
        import_module="tokenizers",
        import_origin="tokenizers/__init__.py",
        version="0.22.2",
        wheel_filename=(
            "tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        ),
        wheel_sha256="369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67",
        artifact_source=(
            "https://files.pythonhosted.org/packages/2e/76/"
            "932be4b50ef6ccedf9d3c6639b056a967a86258c6d9200643f01269211ca/"
            "tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64."
            "manylinux2014_x86_64.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL",
    ),
    RuntimeDistributionPin(
        distribution="torch",
        import_module="torch",
        import_origin="torch/__init__.py",
        version="2.11.0+cu129",
        wheel_filename="torch-2.11.0+cu129-cp312-cp312-manylinux_2_28_x86_64.whl",
        wheel_sha256="68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3",
        artifact_source=(
            "https://download.pytorch.org/whl/cu129/"
            "torch-2.11.0%2Bcu129-cp312-cp312-manylinux_2_28_x86_64.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_TORCH_WHEEL",
    ),
    RuntimeDistributionPin(
        distribution="transformers",
        import_module="transformers",
        import_origin="transformers/__init__.py",
        version="5.6.2",
        wheel_filename="transformers-5.6.2-py3-none-any.whl",
        wheel_sha256="f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f",
        artifact_source=(
            "https://files.pythonhosted.org/packages/5d/95/"
            "0b0218149b0d6f14df35f5b8f676fa83df4f19ed253c3cc447107ef86eca/"
            "transformers-5.6.2-py3-none-any.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL",
    ),
    RuntimeDistributionPin(
        distribution="vllm",
        import_module="vllm",
        import_origin="vllm/__init__.py",
        version="0.26.0+cu129",
        wheel_filename="vllm-0.26.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl",
        wheel_sha256="7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf",
        artifact_source=(
            "https://wheels.vllm.ai/568afb3a13806beb53bb2e6bd518269357b237c0/"
            "vllm-0.26.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl"
        ),
        wheel_setting="SCIENCE_LOCAL_GEMMA_VLLM_WHEEL",
    ),
)


def verify_approved_runtime_python(
    *,
    implementation: str,
    version: tuple[int, int],
    cache_tag: str,
    platform: str,
) -> ApprovedPythonRuntime:
    """Fail closed unless the serving interpreter matches the wheel receipt ABI."""
    if implementation != APPROVED_RUNTIME_PYTHON.implementation:
        raise ValueError("serving Python implementation does not match its pin")
    expected_version = tuple(int(part) for part in APPROVED_RUNTIME_PYTHON.version.split("."))
    if version != expected_version:
        raise ValueError("serving Python version does not match its pin")
    if cache_tag != "cpython-312":
        raise ValueError("serving Python ABI does not match its pin")
    if platform != APPROVED_RUNTIME_PYTHON.platform:
        raise ValueError("serving Python platform does not match its pin")
    return APPROVED_RUNTIME_PYTHON.model_copy(deep=True)


def require_approved_runtime_distribution_receipt(
    receipt: tuple[VerifiedRuntimeDistribution, ...],
) -> tuple[VerifiedRuntimeDistribution, ...]:
    """Require a complete, canonical receipt for every direct serving dependency."""
    expected_names = tuple(pin.distribution for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS)
    actual_names = tuple(item.distribution for item in receipt)
    if actual_names != expected_names:
        raise ValueError("runtime distribution receipt is not in complete approved order")
    for pin, evidence in zip(PRODUCTION_RUNTIME_DISTRIBUTION_PINS, receipt):
        comparisons = (
            ("version", evidence.version, pin.version),
            ("wheel digest", evidence.wheel_sha256, pin.wheel_sha256),
            ("import module", evidence.import_module, pin.import_module),
            ("import origin", evidence.import_origin, pin.import_origin),
        )
        for label, actual, expected in comparisons:
            if actual != expected:
                raise ValueError(f"runtime {pin.distribution} {label} does not match its pin")
    return tuple(item.model_copy(deep=True) for item in receipt)


def verify_installed_runtime_distribution(
    *,
    pin: RuntimeDistributionPin,
    wheel: Path,
    installed_version: str,
    installation_root: Path,
    module_origin: Path,
    additional_package_roots: tuple[str, ...] = (),
) -> VerifiedRuntimeDistribution:
    """Verify one imported distribution against every hashed file in its wheel."""
    wheel_path = _regular_file(wheel, f"{pin.distribution} wheel")
    if wheel_path.name != pin.wheel_filename:
        raise ValueError(f"{pin.distribution} wheel filename does not match its pin")
    if _file_sha256(wheel_path) != pin.wheel_sha256:
        raise ValueError(f"{pin.distribution} wheel digest does not match its pin")
    if installed_version != pin.version:
        raise ValueError(f"installed {pin.distribution} version does not match its pin")

    installed_root = _regular_directory(
        installation_root,
        f"installed {pin.distribution} distribution root",
    )
    imported_module = _regular_file(module_origin, f"imported {pin.distribution} module")
    _require_within_directory(imported_module, installed_root, pin.distribution)
    expected_origin = _regular_file(
        installed_root / pin.import_origin,
        f"installed {pin.distribution} import origin",
    )
    _require_within_directory(expected_origin, installed_root, pin.distribution)
    if imported_module != expected_origin:
        raise ValueError(f"imported {pin.distribution} module is outside the verified distribution")

    try:
        with ZipFile(wheel_path) as archive:
            record_names = tuple(
                name for name in archive.namelist() if name.endswith(".dist-info/RECORD")
            )
            metadata_names = tuple(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            if len(record_names) != 1 or len(metadata_names) != 1:
                raise ValueError(
                    f"{pin.distribution} wheel must contain one METADATA and one RECORD"
                )
            record_name = record_names[0]
            metadata_name = metadata_names[0]
            if record_name.rsplit("/", 1)[0] != metadata_name.rsplit("/", 1)[0]:
                raise ValueError(f"{pin.distribution} wheel metadata directories differ")
            try:
                metadata_text = archive.read(metadata_name).decode("utf-8")
                record_text = archive.read(record_name).decode("utf-8")
            except (KeyError, UnicodeDecodeError) as error:
                raise ValueError(f"{pin.distribution} wheel metadata is unreadable") from error
            metadata = Parser().parsestr(metadata_text)
            if _normalized_distribution_name(metadata.get("Name", "")) != pin.distribution:
                raise ValueError(f"{pin.distribution} wheel metadata name does not match its pin")
            if metadata.get("Version") != pin.version:
                raise ValueError(
                    f"{pin.distribution} wheel metadata version does not match its pin"
                )

            manifest: list[dict[str, object]] = []
            verified_paths: set[Path] = set()
            saw_imported_module = False
            for row in csv.reader(io.StringIO(record_text)):
                if len(row) != 3:
                    raise ValueError(f"{pin.distribution} wheel RECORD row is malformed")
                relative_text, encoded_hash, size_text = row
                relative = _safe_record_path(relative_text, pin.distribution)
                if relative in verified_paths:
                    raise ValueError(f"{pin.distribution} wheel RECORD contains a duplicate path")
                verified_paths.add(relative)
                if not encoded_hash and not size_text and relative_text == record_name:
                    continue
                if not encoded_hash.startswith("sha256=") or not size_text:
                    raise ValueError(
                        f"every {pin.distribution} distribution artifact must be SHA-256 bound"
                    )
                digest_text = encoded_hash.removeprefix("sha256=")
                try:
                    expected_size = int(size_text)
                    expected_digest = base64.urlsafe_b64decode(
                        digest_text + "=" * (-len(digest_text) % 4)
                    ).hex()
                    wheel_payload = archive.read(relative_text)
                except (KeyError, ValueError) as error:
                    raise ValueError(f"{pin.distribution} wheel RECORD hash is invalid") from error
                if (
                    expected_size < 0
                    or len(expected_digest) != 64
                    or len(wheel_payload) != expected_size
                    or hashlib.sha256(wheel_payload).hexdigest() != expected_digest
                ):
                    raise ValueError(f"{pin.distribution} wheel artifact does not match its RECORD")
                installed_file = _regular_file(
                    installed_root / relative,
                    f"installed {pin.distribution} file {relative_text}",
                )
                _require_within_directory(installed_file, installed_root, pin.distribution)
                if (
                    installed_file.stat().st_size != expected_size
                    or _file_sha256(installed_file) != expected_digest
                ):
                    raise ValueError(
                        f"installed {pin.distribution} file {relative_text} "
                        "does not match the pinned wheel"
                    )
                manifest.append(
                    {
                        "path": relative.as_posix(),
                        "sha256": expected_digest,
                        "size_bytes": expected_size,
                    }
                )
                saw_imported_module = saw_imported_module or installed_file == imported_module
    except BadZipFile as error:
        raise ValueError(f"{pin.distribution} wheel is not a valid wheel archive") from error
    if not saw_imported_module:
        raise ValueError(
            f"imported {pin.distribution} module is absent from the pinned wheel RECORD"
        )

    package_root_names = (Path(pin.import_origin).parts[0], *additional_package_roots)
    for package_root_name in package_root_names:
        if len(Path(package_root_name).parts) != 1:
            raise ValueError(f"installed {pin.distribution} package root is invalid")
        package_root = _regular_directory(
            installed_root / package_root_name,
            f"installed {pin.distribution} package {package_root_name}",
        )
        for installed_file in package_root.rglob("*"):
            if installed_file.is_symlink():
                raise ValueError(
                    f"installed {pin.distribution} package must not contain a symlink"
                )
            if installed_file.is_dir():
                continue
            relative = installed_file.relative_to(installed_root)
            if relative not in verified_paths:
                raise ValueError(
                    f"installed {pin.distribution} file {relative.as_posix()} "
                    "is absent from the pinned wheel"
                )

    canonical_manifest = json.dumps(
        sorted(manifest, key=lambda entry: str(entry["path"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return VerifiedRuntimeDistribution(
        distribution=pin.distribution,
        version=pin.version,
        wheel_sha256=pin.wheel_sha256,
        record_manifest_sha256=hashlib.sha256(canonical_manifest).hexdigest(),
        import_module=pin.import_module,
        import_origin=pin.import_origin,
        import_origin_sha256=_file_sha256(imported_module),
        verification="wheel-record-sha256+import-origin",
    )


def resolve_unimported_runtime_distribution(
    *,
    pin: RuntimeDistributionPin,
    distribution: importlib.metadata.Distribution,
) -> tuple[str, Path, Path]:
    """Resolve installed metadata and import origin without executing package code."""
    top_level_module = pin.import_module.partition(".")[0]
    if top_level_module in sys.modules:
        raise ValueError(
            f"{pin.distribution} was imported before its artifact receipt was verified"
        )
    installation_root = _regular_directory(
        Path(distribution.locate_file("")),
        f"installed {pin.distribution} distribution root",
    )
    spec = importlib.machinery.PathFinder.find_spec(pin.import_module)
    if spec is None or not isinstance(spec.origin, str):
        raise ValueError(f"the unimported {pin.distribution} module has no file origin")
    module_origin = _regular_file(
        Path(spec.origin),
        f"unimported {pin.distribution} module origin",
    )
    _require_within_directory(module_origin, installation_root, pin.distribution)
    if module_origin.relative_to(installation_root).as_posix() != pin.import_origin:
        raise ValueError(f"unimported {pin.distribution} module origin does not match its pin")
    return distribution.version, installation_root, module_origin


def verify_installed_product_distribution(
    *,
    wheel: Path,
    expected_wheel_sha256: str,
    distribution: importlib.metadata.Distribution,
    module_origin: Path,
) -> VerifiedRuntimeDistribution:
    """Bind the running product code to an out-of-band expected wheel digest."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_wheel_sha256):
        raise ValueError("expected product wheel digest is invalid")
    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is not None:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError as error:
            raise ValueError("product installation provenance is unreadable") from error
        if not isinstance(direct_url, dict):
            raise ValueError("product installation provenance is invalid")
        raise ValueError("scored serving rejects a direct-url or editable product installation")
    pin = RuntimeDistributionPin(
        distribution="science-environment-studio",
        import_module="studio.policy_evaluation.gemma_server_bootstrap",
        import_origin="studio/policy_evaluation/gemma_server_bootstrap.py",
        version=distribution.version,
        wheel_filename=wheel.name,
        wheel_sha256=expected_wheel_sha256,
        wheel_setting="SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL",
    )
    return verify_installed_runtime_distribution(
        pin=pin,
        wheel=wheel,
        installed_version=distribution.version,
        installation_root=Path(distribution.locate_file("")),
        module_origin=module_origin,
        additional_package_roots=("environments",),
    )


def require_read_only_filesystem(path: Path, label: str) -> Path:
    """Require a kernel-enforced read-only mount for a serving-critical path."""
    resolved = path.expanduser().resolve(strict=True)
    if os.statvfs(resolved).f_flag & os.ST_RDONLY == 0:
        raise ValueError(f"{label} must be on a read-only filesystem")
    return resolved


def _normalized_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _safe_record_path(value: str, distribution: str) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"{distribution} wheel RECORD contains an unsafe path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{distribution} wheel RECORD contains an unsafe path")
    return path


def _regular_directory(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError(f"{label} must be a non-symlink directory")
    return candidate.resolve(strict=True)


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a non-symlink regular file")
    return path.resolve(strict=True)


def _require_within_directory(path: Path, root: Path, distribution: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"{distribution} artifact is outside the verified distribution"
        ) from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "APPROVED_RUNTIME_PYTHON",
    "APPROVED_RUNTIME_RECEIPT_ID",
    "ApprovedPythonRuntime",
    "PRODUCTION_RUNTIME_DISTRIBUTION_PINS",
    "RuntimeDistributionPin",
    "VerifiedRuntimeDistribution",
    "require_approved_runtime_distribution_receipt",
    "require_read_only_filesystem",
    "resolve_unimported_runtime_distribution",
    "verify_approved_runtime_python",
    "verify_installed_runtime_distribution",
    "verify_installed_product_distribution",
]
