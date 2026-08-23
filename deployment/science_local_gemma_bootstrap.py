"""Independent stdlib-only trust bootstrap for scored local Gemma serving.

This file is staged separately from the product wheel.  The service manager must
pin and verify its SHA-256 before invoking ``python -I -S -B`` on it.
"""

from __future__ import annotations

import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile

_ALLOWED_PREEXEC_ENVIRONMENT = frozenset(
    {
        "CUDA_HOME",
        "CUDA_PATH",
        "CUDA_VISIBLE_DEVICES",
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
_SECRET_DIRECTORY = Path("/run/secrets")
_API_SECRET_NAME = "science-local-gemma-api-key"
_ATTESTATION_SECRET_NAME = "science-local-gemma-attestation-key"
_SECRET_MIN_BYTES = 32
_SECRET_MAX_BYTES = 4096
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4


def _validate_preexec_environment() -> None:
    names = set(os.environ)
    injection_names = {
        name
        for name in names
        if name.startswith(("LD_", "DYLD_", "PYTHON"))
    }
    if injection_names:
        raise RuntimeError(
            "trusted bootstrap rejects interpreter or dynamic-loader injection settings"
        )
    if names.difference(_ALLOWED_PREEXEC_ENVIRONMENT):
        raise RuntimeError(
            "trusted bootstrap requires an explicit pre-exec environment allowlist"
        )
    if os.environ.get("LC_ALL") != "C":
        raise RuntimeError("trusted bootstrap requires the fixed C locale")


def _disable_process_dumping() -> None:
    if sys.platform != "linux":
        raise RuntimeError("trusted bootstrap process hardening requires Linux")
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
        raise RuntimeError("trusted bootstrap could not disable process dumping")
    if prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("trusted bootstrap process dumping remained enabled")


def _secret_metadata_unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _read_runtime_secret(directory_fd: int, name: str) -> str:
    path_metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    payload = bytearray()
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=directory_fd,
    )
    try:
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(path_metadata.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (before.st_dev, before.st_ino)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != stat.S_IRUSR
                or before.st_nlink != 1
                or not _SECRET_MIN_BYTES <= before.st_size <= _SECRET_MAX_BYTES
            ):
                raise RuntimeError(
                    "runtime secret file identity or permissions are invalid"
                )
            payload.extend(b"\x00" * before.st_size)
            payload_view = memoryview(payload)
            offset = 0
            try:
                while offset < before.st_size:
                    read_count = os.readv(descriptor, [payload_view[offset:]])
                    if read_count <= 0:
                        raise RuntimeError("runtime secret file changed while being read")
                    offset += read_count
            finally:
                payload_view.release()
            if not _secret_metadata_unchanged(before, os.fstat(descriptor)):
                raise RuntimeError("runtime secret file changed while being read")
        finally:
            os.close(descriptor)
        if any(byte < 0x21 or byte > 0x7E for byte in payload):
            raise RuntimeError(
                "runtime secret must be one unambiguous printable ASCII value"
            )
        return payload.decode("ascii")
    finally:
        for index in range(len(payload)):
            payload[index] = 0


def _load_runtime_secrets_from_fixed_files(
    directory: Path = _SECRET_DIRECTORY,
    *,
    expected_directory_uid: int = 0,
) -> tuple[str, str]:
    path_metadata = directory.lstat()
    descriptor = os.open(
        directory,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(path_metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or (path_metadata.st_dev, path_metadata.st_ino)
            != (metadata.st_dev, metadata.st_ino)
            or metadata.st_uid != expected_directory_uid
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RuntimeError("fixed secret directory is unsafe")
        api_key = _read_runtime_secret(descriptor, _API_SECRET_NAME)
        attestation_key = _read_runtime_secret(descriptor, _ATTESTATION_SECRET_NAME)
    finally:
        os.close(descriptor)
    if api_key == attestation_key:
        raise RuntimeError("runtime API and attestation secrets must be distinct")
    return api_key, attestation_key


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError("required trusted-bootstrap setting is missing: " + name)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(label + " must be a non-symlink regular file")
    return path.resolve(strict=True)


def _regular_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(label + " must be a non-symlink directory")
    return path.resolve(strict=True)


def _read_only(path: Path, label: str) -> None:
    if os.statvfs(path).f_flag & os.ST_RDONLY == 0:
        raise RuntimeError(label + " must be on a read-only filesystem")


def _contained_file(root: Path, relative_text: str) -> Path:
    if not relative_text or "\\" in relative_text:
        raise RuntimeError("product wheel RECORD contains an unsafe path")
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("product wheel RECORD contains an unsafe path")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("installed product artifact must not traverse a symlink")
    resolved = _regular_file(candidate, "installed product artifact")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RuntimeError("installed product artifact escaped its verified root") from error
    return resolved


def _verify_product_wheel(root: Path, wheel: Path, expected_sha256: str) -> None:
    if len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
        raise RuntimeError("expected product wheel digest is invalid")
    if _sha256(wheel) != expected_sha256:
        raise RuntimeError("product wheel digest does not match its out-of-band pin")
    try:
        with ZipFile(wheel) as archive:
            record_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/RECORD")
            ]
            if len(record_names) != 1:
                raise RuntimeError("product wheel must contain exactly one RECORD")
            record_name = record_names[0]
            record_text = archive.read(record_name).decode("utf-8")
            verified = set()
            for row in csv.reader(io.StringIO(record_text)):
                if len(row) != 3:
                    raise RuntimeError("product wheel RECORD row is malformed")
                relative_text, encoded_hash, size_text = row
                if relative_text in verified:
                    raise RuntimeError("product wheel RECORD contains a duplicate path")
                verified.add(relative_text)
                if relative_text == record_name and not encoded_hash and not size_text:
                    continue
                if not encoded_hash.startswith("sha256=") or not size_text:
                    raise RuntimeError("every product artifact must be SHA-256 bound")
                expected_size = int(size_text)
                encoded = encoded_hash.removeprefix("sha256=")
                expected_digest = base64.urlsafe_b64decode(
                    encoded + "=" * (-len(encoded) % 4)
                ).hex()
                wheel_payload = archive.read(relative_text)
                installed = _contained_file(root, relative_text)
                if (
                    expected_size < 0
                    or len(expected_digest) != 64
                    or len(wheel_payload) != expected_size
                    or hashlib.sha256(wheel_payload).hexdigest() != expected_digest
                    or installed.stat().st_size != expected_size
                    or _sha256(installed) != expected_digest
                ):
                    raise RuntimeError("installed product file does not match its wheel RECORD")
            required = {
                "studio/policy_evaluation/gemma_attestation.py",
                "studio/policy_evaluation/gemma_server_bootstrap.py",
                "environments/__init__.py",
            }
            if not required.issubset(verified):
                raise RuntimeError("product wheel omits required serving entry points")
            for package_name in ("studio", "environments"):
                package_root = _regular_directory(
                    root / package_name,
                    "installed product package " + package_name,
                )
                for installed in package_root.rglob("*"):
                    if installed.is_symlink():
                        raise RuntimeError("installed product package contains a symlink")
                    if installed.is_dir():
                        continue
                    relative = installed.relative_to(root).as_posix()
                    if relative not in verified:
                        raise RuntimeError(
                            "installed product artifact is absent from its wheel RECORD"
                        )
            dist_info = root / record_name.rsplit("/", 1)[0]
            direct_url_path = dist_info / "direct_url.json"
            if direct_url_path.exists():
                json.loads(_regular_file(direct_url_path, "product direct URL").read_text())
                raise RuntimeError("trusted bootstrap rejects a direct-url product install")
    except (BadZipFile, KeyError, UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("product wheel receipt is unreadable") from error


def _run_verified_bootstrap() -> None:
    bootstrap = _regular_file(Path(__file__), "trusted bootstrap")
    expected_bootstrap_sha256 = _required("SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256")
    if _sha256(bootstrap) != expected_bootstrap_sha256:
        raise RuntimeError("trusted bootstrap digest does not match its external pin")
    product_root = _regular_directory(
        Path(_required("SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT")),
        "installed product root",
    )
    product_wheel = _regular_file(
        Path(_required("SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL")),
        "staged product wheel",
    )
    _read_only(bootstrap, "trusted bootstrap")
    _read_only(product_root, "installed product root")
    _read_only(product_wheel, "staged product wheel")
    _verify_product_wheel(
        product_root,
        product_wheel,
        _required("SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256"),
    )
    private_cache = Path(tempfile.mkdtemp(prefix="science-local-gemma-pycache-"))
    private_cache.chmod(stat.S_IRWXU)
    sys.pycache_prefix = str(private_cache)
    sys.dont_write_bytecode = True
    os.environ["PYTHONPYCACHEPREFIX"] = str(private_cache)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["SCIENCE_LOCAL_GEMMA_VERIFIED_BOOTSTRAP_SHA256"] = (
        expected_bootstrap_sha256
    )
    bootstrap_directory = str(bootstrap.parent)
    safe_stdlib_paths = [
        entry
        for entry in sys.path
        if entry
        and str(Path(entry).resolve()) != bootstrap_directory
        and "site-packages" not in Path(entry).parts
        and "dist-packages" not in Path(entry).parts
    ]
    sys.path[:] = [*safe_stdlib_paths, str(product_root)]
    from studio.policy_evaluation.gemma_attestation import serve_attested_local_gemma

    serve_attested_local_gemma(argv=("trusted-bootstrap", *sys.argv[1:]))


def main() -> None:
    _validate_preexec_environment()
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise RuntimeError("trusted bootstrap requires python -I -S -B")
    _disable_process_dumping()
    api_key, attestation_key = _load_runtime_secrets_from_fixed_files()
    os.environ["SCIENCE_LOCAL_GEMMA_API_KEY"] = api_key
    os.environ["SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY"] = attestation_key
    try:
        _run_verified_bootstrap()
    finally:
        os.environ.pop("SCIENCE_LOCAL_GEMMA_API_KEY", None)
        os.environ.pop("SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY", None)


if __name__ == "__main__":
    main()
