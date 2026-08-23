"""One-time operator tool for staging the pinned local-Gemma snapshot."""

from __future__ import annotations

import ctypes
import errno
import getpass
import hashlib
import logging
import os
import resource
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MODEL_REPOSITORY = "google/gemma-4-E4B-it"
MODEL_REVISION = "ee0ef6023621cff504d758262d4e04895a5af4a2"
EXPECTED_SNAPSHOT_FILES = (
    ".gitattributes",
    "README.md",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "generation_config.json",
    "processor_config.json",
    "chat_template.jinja",
)
_PINNED_ARTIFACT_NAMES = frozenset(EXPECTED_SNAPSHOT_FILES[2:])
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4


@dataclass(frozen=True)
class ArtifactPin:
    """Expected size and content identity for one serving artifact."""

    name: str
    size_bytes: int
    sha256: str


PRODUCTION_ARTIFACT_PINS = (
    ArtifactPin(
        name="model.safetensors",
        size_bytes=15_992_595_884,
        sha256="cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503",
    ),
    ArtifactPin(
        name="chat_template.jinja",
        size_bytes=18_569,
        sha256="0a2c8073c878ab1da004bee933a998606537bbb62016310352c7285c3f01c5b5",
    ),
    ArtifactPin(
        name="config.json",
        size_bytes=5_145,
        sha256="33b10c02df3c2e8536cf323d29d53262aaa2f4d11dbe19bc729373fbe90295d4",
    ),
    ArtifactPin(
        name="generation_config.json",
        size_bytes=208,
        sha256="d4226bbe3117d2d253ba4609720ba82c6c4ce4627a9a6ae05387c78983ac03de",
    ),
    ArtifactPin(
        name="processor_config.json",
        size_bytes=1_689,
        sha256="32bdf45d2ad4cc29a0822ddd157a182de76644f0419a6228d151495256e9813c",
    ),
    ArtifactPin(
        name="tokenizer.json",
        size_bytes=32_169_626,
        sha256="cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    ),
    ArtifactPin(
        name="tokenizer_config.json",
        size_bytes=3_082,
        sha256="9f4fec4b1dc6ecddf8f4a92e9caea5971c0e67d81309f3f9066a2bee8c362633",
    ),
)


@dataclass(frozen=True)
class StagingLayout:
    """Filesystem roots used by one isolated staging invocation."""

    final_root: Path
    attempts_root: Path


PRODUCTION_LAYOUT = StagingLayout(
    final_root=Path("/approved/ro/model"),
    attempts_root=Path("/approved/ro/model-attempts"),
)


TokenPrompt = Callable[[str], str]


class SnapshotDownload(Protocol):
    """Minimal installed-Hub operation used by the one-time stager."""

    def __call__(
        self,
        *,
        repo_id: str,
        revision: str,
        endpoint: str,
        local_dir: str,
        cache_dir: str,
        allow_patterns: list[str],
        token: str,
        max_workers: int,
        force_download: bool,
        local_files_only: bool,
    ) -> str: ...


class ManualQuarantineRequired(RuntimeError):
    """A storage failure left artifact locality or durability uncertain."""


def run_operator(
    *,
    argv: Sequence[str],
    prompt_for_token: TokenPrompt,
    snapshot_download: SnapshotDownload,
    layout: StagingLayout,
    artifact_pins: Sequence[ArtifactPin],
) -> int:
    """Run the content-free operator boundary with injected system adapters."""
    if len(argv) != 1:
        print("science-local-gemma-model-stage: FAIL", file=sys.stderr, flush=True)
        return 64
    token = ""
    try:
        token = prompt_for_token("Hugging Face access token: ")
        if not token or "\n" in token or "\r" in token:
            raise ValueError("interactive token is invalid")
        with _silenced_sdk_output():
            stage_model_snapshot(
                token=token,
                layout=layout,
                artifact_pins=artifact_pins,
                snapshot_download=snapshot_download,
            )
    except ManualQuarantineRequired:
        print(
            "science-local-gemma-model-stage: FAIL MANUAL-QUARANTINE-REQUIRED",
            file=sys.stderr,
            flush=True,
        )
        return 70
    except (Exception, KeyboardInterrupt):
        print("science-local-gemma-model-stage: FAIL", file=sys.stderr, flush=True)
        return 1
    finally:
        token = ""
    print("science-local-gemma-model-stage: PASS", flush=True)
    return 0


def main() -> int:
    """Run the no-argument production command against its fixed container root."""
    try:
        _harden_operator_process()
    except Exception:
        print("science-local-gemma-model-stage: FAIL", file=sys.stderr, flush=True)
        return 1
    return run_operator(
        argv=tuple(sys.argv),
        prompt_for_token=_interactive_getpass,
        snapshot_download=_installed_snapshot_download,
        layout=PRODUCTION_LAYOUT,
        artifact_pins=PRODUCTION_ARTIFACT_PINS,
    )


def _harden_operator_process() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
        raise RuntimeError("operator process core dumps remained enabled")
    if sys.platform != "linux":
        return
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
        raise RuntimeError("operator process inspection could not be disabled")
    if prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise RuntimeError("operator process remained dumpable")


def _interactive_getpass(prompt: str) -> str:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise RuntimeError("operator token prompt requires a terminal")
    return getpass.getpass(prompt)


def _installed_snapshot_download(
    *,
    repo_id: str,
    revision: str,
    endpoint: str,
    local_dir: str,
    cache_dir: str,
    allow_patterns: list[str],
    token: str,
    max_workers: int,
    force_download: bool,
    local_files_only: bool,
) -> str:
    from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

    result: object = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        endpoint=endpoint,
        local_dir=local_dir,
        cache_dir=cache_dir,
        allow_patterns=allow_patterns,
        token=token,
        max_workers=max_workers,
        force_download=force_download,
        local_files_only=local_files_only,
    )
    if not isinstance(result, str):
        raise RuntimeError("installed snapshot downloader returned an unexpected result")
    return result


@contextmanager
def _silenced_sdk_output() -> Iterator[None]:
    previous_logging_threshold = logging.root.manager.disable
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    null_descriptor = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_descriptor, 1)
        os.dup2(null_descriptor, 2)
        with (
            open(os.devnull, "w", encoding="utf-8") as sink,
            redirect_stdout(sink),
            redirect_stderr(sink),
        ):
            logging.disable(logging.CRITICAL)
            yield
    finally:
        logging.disable(previous_logging_threshold)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os.dup2(saved_stdout, 1)
            os.dup2(saved_stderr, 2)
            os.close(null_descriptor)
            os.close(saved_stdout)
            os.close(saved_stderr)


def stage_model_snapshot(
    *,
    token: str,
    layout: StagingLayout,
    artifact_pins: Sequence[ArtifactPin],
    snapshot_download: SnapshotDownload,
) -> None:
    """Download, verify, and atomically publish one exact snapshot tree."""
    if not token:
        raise ValueError("an interactive token is required")
    _validate_layout(layout)
    pins = _validated_pins(artifact_pins)
    if os.path.lexists(layout.final_root):
        raise FileExistsError("the fixed model root already exists")

    try:
        layout.attempts_root.mkdir(mode=0o700, exist_ok=True)
        _require_directory(layout.attempts_root)
        os.chmod(layout.attempts_root, 0o700)
        _fsync_directory(layout.attempts_root)
        _fsync_directory(layout.final_root.parent)
        attempt_root = Path(
            tempfile.mkdtemp(prefix="attempt-", dir=str(layout.attempts_root))
        )
        _fsync_directory(layout.attempts_root)
    except BaseException as error:
        raise ManualQuarantineRequired(
            "failed-attempt root initialization is not durable"
        ) from error
    download_root = attempt_root / "download"
    cache_root = attempt_root / "cache"
    payload_root = layout.final_root.parent / (".model-payload-" + attempt_root.name)
    try:
        downloaded = snapshot_download(
            repo_id=MODEL_REPOSITORY,
            revision=MODEL_REVISION,
            endpoint="https://huggingface.co",
            local_dir=str(download_root),
            cache_dir=str(cache_root),
            allow_patterns=list(EXPECTED_SNAPSHOT_FILES),
            token=token,
            max_workers=1,
            force_download=True,
            local_files_only=False,
        )
        if not isinstance(downloaded, str):
            raise RuntimeError("snapshot downloader returned an unexpected result")
        if Path(downloaded).resolve(strict=True) != download_root.resolve(strict=True):
            raise RuntimeError("snapshot downloader returned an unexpected root")
        _reject_links(attempt_root)
        _require_directory(download_root)
        downloaded_names = {entry.name for entry in download_root.iterdir()}
        allowed_download_entries = {*EXPECTED_SNAPSHOT_FILES, ".cache"}
        if downloaded_names.difference(allowed_download_entries):
            raise RuntimeError("snapshot downloader materialized an unexpected entry")
        if not set(EXPECTED_SNAPSHOT_FILES).issubset(downloaded_names):
            raise RuntimeError("snapshot downloader omitted a required file")

        payload_root.mkdir(mode=0o700)
        for name in EXPECTED_SNAPSHOT_FILES:
            source = download_root / name
            pin = pins.get(name)
            _verify_regular_file(source, None)
            destination = payload_root / name
            os.rename(source, destination)
            os.chmod(destination, 0o444, follow_symlinks=False)
            _verify_regular_file(destination, pin)
            _fsync_file(destination)
        os.chmod(payload_root, 0o555)
        _verify_publication_ready_tree(payload_root)
        _fsync_directory(payload_root)
        _fsync_directory(download_root)
        _fsync_directory(attempt_root)
        _fsync_directory(layout.final_root.parent)

        _publish_prepared_payload(payload_root, layout.final_root)
    except BaseException:
        _preserve_failed_payload(payload_root, attempt_root)
        raise


def _validate_layout(layout: StagingLayout) -> None:
    if not layout.final_root.is_absolute() or not layout.attempts_root.is_absolute():
        raise ValueError("staging roots must be absolute")
    if ".." in layout.final_root.parts or ".." in layout.attempts_root.parts:
        raise ValueError("staging roots must be lexically canonical")
    if layout.final_root.parent != layout.attempts_root.parent:
        raise ValueError("staging roots must share one atomic filesystem parent")
    _require_directory_chain(layout.final_root.parent)


def _validated_pins(artifact_pins: Sequence[ArtifactPin]) -> dict[str, ArtifactPin]:
    pins = {pin.name: pin for pin in artifact_pins}
    if len(pins) != len(artifact_pins) or set(pins) != _PINNED_ARTIFACT_NAMES:
        raise ValueError("artifact pins must cover the exact serving file set")
    for pin in pins.values():
        if pin.size_bytes < 1:
            raise ValueError("artifact pin size is invalid")
        if len(pin.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in pin.sha256
        ):
            raise ValueError("artifact pin digest is invalid")
    return pins


def _require_directory(path: Path) -> None:
    status = path.lstat()
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise RuntimeError("staging path must be a non-symlink directory")


def _require_directory_chain(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        status = current.lstat()
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise RuntimeError("staging path must be a non-symlink directory chain")


def _reject_links(root: Path) -> None:
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in (*directory_names, *file_names):
            if (current / name).is_symlink():
                raise RuntimeError("staging attempt must not contain links")


def _verify_regular_file(path: Path, pin: ArtifactPin | None) -> None:
    status = path.lstat()
    if (
        stat.S_ISLNK(status.st_mode)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
    ):
        raise RuntimeError("snapshot member must be a single-link regular file")
    if pin is None:
        return
    if status.st_size != pin.size_bytes or _sha256(path) != pin.sha256:
        raise RuntimeError("snapshot member does not match its immutable pin")


def _verify_tree_shape(root: Path) -> None:
    _require_directory(root)
    if {entry.name for entry in root.iterdir()} != set(EXPECTED_SNAPSHOT_FILES):
        raise RuntimeError("model snapshot does not contain the exact file set")
    for name in EXPECTED_SNAPSHOT_FILES:
        _verify_regular_file(root / name, None)


def _verify_publication_ready_tree(root: Path) -> None:
    _verify_tree_shape(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o555:
        raise RuntimeError("prepared model snapshot directory mode is invalid")
    for name in EXPECTED_SNAPSHOT_FILES:
        if stat.S_IMODE((root / name).stat().st_mode) != 0o444:
            raise RuntimeError("prepared model snapshot file mode is invalid")


def _publish_prepared_payload(payload: Path, final_root: Path) -> None:
    _rename_no_replace(payload, final_root)
    try:
        _fsync_directory(final_root.parent)
    except BaseException:
        try:
            _rename_no_replace(final_root, payload)
            _fsync_directory(final_root.parent)
        except BaseException as rollback_error:
            raise ManualQuarantineRequired(
                "model-root publication rollback failed"
            ) from rollback_error
        raise


def _preserve_failed_payload(payload: Path, attempt_root: Path) -> None:
    if not os.path.lexists(payload):
        return
    source_parent = payload.parent
    try:
        _require_directory(payload)
        preserved_payload = attempt_root / "payload"
        if os.path.lexists(preserved_payload):
            raise RuntimeError("failed attempt already contains a payload")
        os.chmod(payload, 0o700)
        os.rename(payload, preserved_payload)
        _fsync_directory(attempt_root)
        _fsync_directory(source_parent)
        _fsync_directory(attempt_root.parent)
    except BaseException as error:
        raise ManualQuarantineRequired(
            "failed payload could not be durably preserved"
        ) from error


def _rename_no_replace(source: Path, destination: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "linux":
        rename = library.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(-100, source_bytes, -100, destination_bytes, 1)
    elif sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(source_bytes, destination_bytes, 4)
    else:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, "the fixed model root already exists")
    raise OSError(error_number, "atomic model-root publication failed")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
