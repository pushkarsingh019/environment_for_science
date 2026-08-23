"""Artifact-to-import provenance for the local Gemma inference stack."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from studio.policy_evaluation import runtime_dependencies
from studio.policy_evaluation.runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    PRODUCTION_RUNTIME_DISTRIBUTION_PINS,
    RuntimeDistributionPin,
    VerifiedRuntimeDistribution,
    require_approved_runtime_distribution_receipt,
    require_read_only_filesystem,
    resolve_unimported_runtime_distribution,
    verify_approved_runtime_python,
    verify_installed_product_distribution,
    verify_installed_runtime_distribution,
)


def test_production_receipt_locks_complete_direct_inference_stack_and_python_abi() -> None:
    assert APPROVED_RUNTIME_PYTHON.model_dump(mode="json") == {
        "implementation": "cpython",
        "version": "3.12",
        "abi_tag": "cp312",
        "platform": "linux-x86_64",
    }
    assert {
        pin.distribution: (pin.version, pin.wheel_sha256)
        for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    } == {
        "jinja2": (
            "3.1.6",
            "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67",
        ),
        "safetensors": (
            "0.7.0",
            "dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48",
        ),
        "tokenizers": (
            "0.22.2",
            "369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67",
        ),
        "torch": (
            "2.11.0+cu129",
            "68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3",
        ),
        "transformers": (
            "5.6.2",
            "f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f",
        ),
        "vllm": (
            "0.26.0+cu129",
            "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf",
        ),
    }
    assert all(
        pin.artifact_source.startswith("https://") for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    )
    assert {
        pin.distribution: pin.wheel_setting for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    } == {
        "jinja2": "SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL",
        "safetensors": "SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL",
        "tokenizers": "SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL",
        "torch": "SCIENCE_LOCAL_GEMMA_TORCH_WHEEL",
        "transformers": "SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL",
        "vllm": "SCIENCE_LOCAL_GEMMA_VLLM_WHEEL",
    }


@pytest.mark.parametrize(
    ("implementation", "version", "cache_tag", "message"),
    (
        ("pypy", (3, 12), "pypy312-pp73", "implementation"),
        ("cpython", (3, 11), "cpython-311", "version"),
        ("cpython", (3, 12), "cpython-312d", "ABI"),
    ),
)
def test_runtime_python_rejects_implementation_version_and_abi_drift(
    implementation: str,
    version: tuple[int, int],
    cache_tag: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        verify_approved_runtime_python(
            implementation=implementation,
            version=version,
            cache_tag=cache_tag,
            platform="linux-x86_64",
        )


def test_runtime_receipt_rejects_missing_or_drifted_direct_dependency() -> None:
    receipt = _production_like_receipt()
    with pytest.raises(ValueError, match="complete approved order"):
        require_approved_runtime_distribution_receipt(receipt[:-1])

    drifted_transformers = receipt[4].model_copy(update={"version": "5.6.1"})
    with pytest.raises(ValueError, match="transformers version"):
        require_approved_runtime_distribution_receipt(
            (*receipt[:4], drifted_transformers, receipt[5])
        )


def test_verified_distribution_binds_wheel_record_installed_files_and_import(
    tmp_path: Path,
) -> None:
    pin, wheel, installation_root, module_origin = _installed_tiny_distribution(tmp_path)

    evidence = verify_installed_runtime_distribution(
        pin=pin,
        wheel=wheel,
        installed_version=pin.version,
        installation_root=installation_root,
        module_origin=module_origin,
    )

    assert evidence.distribution == "tiny-runtime"
    assert evidence.version == "1.2.3+cu129"
    assert evidence.wheel_sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert evidence.record_manifest_sha256 == (
        "6a0af61f8711ae7e644ae7cfcb1973a221a732e0fc614ee62fedfc6d9a4fe862"
    )
    assert evidence.import_origin == "tiny_runtime/__init__.py"
    assert evidence.import_origin_sha256 == hashlib.sha256(module_origin.read_bytes()).hexdigest()
    assert evidence.verification == "wheel-record-sha256+import-origin"


def test_distribution_origin_resolution_does_not_execute_unverified_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = tmp_path / "unverified-import-executed"
    package_payload = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "__version__ = '1.2.3+cu129'\n"
    ).encode()
    pin, wheel, installation_root, _module_origin = _installed_tiny_distribution(
        tmp_path,
        package_payload=package_payload,
    )
    monkeypatch.syspath_prepend(str(installation_root))
    sys.modules.pop(pin.import_module, None)
    distribution = importlib.metadata.Distribution.at(
        installation_root / "tiny_runtime-1.2.3+cu129.dist-info"
    )

    installed_version, resolved_root, resolved_origin = (
        resolve_unimported_runtime_distribution(
            pin=pin,
            distribution=distribution,
        )
    )
    evidence = verify_installed_runtime_distribution(
        pin=pin,
        wheel=wheel,
        installed_version=installed_version,
        installation_root=resolved_root,
        module_origin=resolved_origin,
    )

    assert evidence.import_origin == "tiny_runtime/__init__.py"
    assert sentinel.exists() is False
    assert pin.import_module not in sys.modules


def test_product_receipt_rejects_current_editable_source_install(tmp_path: Path) -> None:
    distribution = importlib.metadata.distribution("science-environment-studio")

    with pytest.raises(ValueError, match="direct-url or editable"):
        verify_installed_product_distribution(
            wheel=tmp_path / "unused.whl",
            expected_wheel_sha256="9" * 64,
            distribution=distribution,
            module_origin=Path(__file__),
        )


@pytest.mark.parametrize(
    "direct_url",
    (
        {"url": "file:///srv/source", "dir_info": {"editable": False}},
        {"url": "git+https://example.invalid/repository.git", "vcs_info": {"vcs": "git"}},
    ),
)
def test_product_receipt_rejects_noneditable_local_and_vcs_direct_urls(
    tmp_path: Path,
    direct_url: dict[str, object],
) -> None:
    class DirectUrlDistribution:
        version = "0.1.0"

        def read_text(self, filename: str) -> str | None:
            return json.dumps(direct_url) if filename == "direct_url.json" else None

    with pytest.raises(ValueError, match="direct-url or editable"):
        verify_installed_product_distribution(
            wheel=tmp_path / "unused.whl",
            expected_wheel_sha256="9" * 64,
            distribution=DirectUrlDistribution(),  # type: ignore[arg-type]
            module_origin=Path(__file__),
        )


def test_serving_root_must_be_on_a_kernel_read_only_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_dependencies.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_flag=0),
    )

    with pytest.raises(ValueError, match="read-only filesystem"):
        require_read_only_filesystem(tmp_path, "mutable serving root")

    monkeypatch.setattr(
        runtime_dependencies.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_flag=os.ST_RDONLY),
    )
    assert require_read_only_filesystem(tmp_path, "sealed serving root") == tmp_path.resolve()


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("version", "version"),
        ("wheel", "wheel digest"),
        ("installed-file", "installed tiny-runtime file"),
        ("import-origin", "outside the verified distribution"),
    ),
)
def test_verified_distribution_rejects_version_artifact_install_and_import_drift(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    pin, wheel, installation_root, module_origin = _installed_tiny_distribution(tmp_path)
    installed_version = pin.version
    if mutation == "version":
        installed_version = "1.2.4+cu129"
    elif mutation == "wheel":
        wheel.write_bytes(wheel.read_bytes() + b"drift")
    elif mutation == "installed-file":
        module_origin.write_bytes(b"drifted installed module\n")
    else:
        shadow = tmp_path / "shadow" / "tiny_runtime" / "__init__.py"
        shadow.parent.mkdir(parents=True)
        shadow.write_bytes(module_origin.read_bytes())
        module_origin = shadow

    with pytest.raises(ValueError, match=message):
        verify_installed_runtime_distribution(
            pin=pin,
            wheel=wheel,
            installed_version=installed_version,
            installation_root=installation_root,
            module_origin=module_origin,
        )


@pytest.mark.parametrize(
    "relative_pyc",
    (
        Path("tiny_runtime") / "unrecorded.pyc",
        Path("tiny_runtime") / "__pycache__" / "unrecorded.cpython-312.pyc",
    ),
)
def test_verified_distribution_rejects_unrecorded_executable_bytecode(
    tmp_path: Path,
    relative_pyc: Path,
) -> None:
    pin, wheel, installation_root, module_origin = _installed_tiny_distribution(tmp_path)
    bytecode = installation_root / relative_pyc
    bytecode.parent.mkdir(parents=True, exist_ok=True)
    bytecode.write_bytes(b"unverified executable bytecode")

    with pytest.raises(ValueError, match="absent from the pinned wheel"):
        verify_installed_runtime_distribution(
            pin=pin,
            wheel=wheel,
            installed_version=pin.version,
            installation_root=installation_root,
            module_origin=module_origin,
        )


def _installed_tiny_distribution(
    tmp_path: Path,
    *,
    package_payload: bytes = b'__version__ = "1.2.3+cu129"\n',
) -> tuple[RuntimeDistributionPin, Path, Path, Path]:
    distribution = "tiny-runtime"
    version = "1.2.3+cu129"
    package_path = "tiny_runtime/__init__.py"
    metadata_path = "tiny_runtime-1.2.3+cu129.dist-info/METADATA"
    wheel_metadata_path = "tiny_runtime-1.2.3+cu129.dist-info/WHEEL"
    record_path = "tiny_runtime-1.2.3+cu129.dist-info/RECORD"
    payloads = {
        package_path: package_payload,
        metadata_path: b"Metadata-Version: 2.4\nName: tiny_runtime\nVersion: 1.2.3+cu129\n",
        wheel_metadata_path: (b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
    }
    rows = []
    for relative, payload in payloads.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
        rows.append((relative, f"sha256={encoded}", str(len(payload))))
    record_stream = io.StringIO()
    writer = csv.writer(record_stream, lineterminator="\n")
    writer.writerows((*rows, (record_path, "", "")))
    payloads[record_path] = record_stream.getvalue().encode()
    wheel = tmp_path / "tiny_runtime-1.2.3+cu129-py3-none-any.whl"
    with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
        for relative, payload in payloads.items():
            archive.writestr(relative, payload)
    installation_root = tmp_path / "site-packages"
    for relative, payload in payloads.items():
        target = installation_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    module_origin = installation_root / package_path
    pin = RuntimeDistributionPin(
        distribution=distribution,
        import_module="tiny_runtime",
        import_origin=package_path,
        version=version,
        wheel_filename=wheel.name,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        artifact_source=f"https://example.invalid/{wheel.name}",
        wheel_setting="SCIENCE_LOCAL_GEMMA_TINY_RUNTIME_WHEEL",
    )
    return pin, wheel, installation_root, module_origin


def _production_like_receipt() -> tuple[VerifiedRuntimeDistribution, ...]:
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
