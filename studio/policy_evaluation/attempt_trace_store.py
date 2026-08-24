"""Content-addressed, write-once JSONL storage for evaluation attempts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from pydantic import ValidationError

from .artifact_safety import validate_artifact_safe
from .model_runner import EvaluationAttempt

_FORMAT_VERSION: Final = "science-evaluation-attempt-trace/1"
_STORE_DIRECTORY: Final = "evaluation-attempt-traces"
_DIGEST_DIRECTORY: Final = "sha256"
_PENDING_DIRECTORY: Final = ".pending"
_MAX_TRACE_BYTES: Final = 64 * 1024 * 1024
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_REFERENCE = re.compile(
    rf"^{_STORE_DIRECTORY}/{_DIGEST_DIRECTORY}/"
    r"([0-9a-f]{2})/([0-9a-f]{64})\.jsonl$"
)
_PENDING_NAME = re.compile(r"^pending-[0-9a-f]{32}\.tmp$")
_RECORD_TYPES: Final = (
    "trace",
    "message",
    "response",
    "tool_call",
    "tool_result",
    "accepted_action",
    "runtime_execution",
    "runtime_event",
    "outcome",
)
_TRACE_COLLECTIONS: Final = (
    "messages",
    "responses",
    "tool_calls",
    "tool_results",
    "accepted_actions",
    "runtime_executions",
    "runtime_events",
)


@dataclass(frozen=True)
class StoredTraceArtifact:
    """Path-safe content identity persisted in the SQLite index."""

    reference: str
    digest: str


class AttemptTraceStoreError(ValueError):
    """An attempt artifact could not be persisted or validated safely."""


class AttemptTraceStore:
    """A private JSONL object store rooted below one evaluation artifact root."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = Path(artifact_root)
        try:
            with self._open_artifact_root() as artifact_root_fd:
                self._ensure_child_directory(
                    artifact_root_fd,
                    _STORE_DIRECTORY,
                )
            with self._open_store() as store_fd:
                self._ensure_child_directory(store_fd, _DIGEST_DIRECTORY)
                self._ensure_child_directory(store_fd, _PENDING_DIRECTORY)
        except (OSError, ValueError) as error:
            raise AttemptTraceStoreError(
                "the evaluation attempt trace store could not be opened"
            ) from error

    def persist(
        self,
        *,
        evaluation_id: str,
        attempt_id: str,
        attempt: EvaluationAttempt,
    ) -> StoredTraceArtifact:
        """Durably create one canonical object without replacing an existing file."""
        payload = serialize_attempt_trace(
            evaluation_id=evaluation_id,
            attempt_id=attempt_id,
            attempt=attempt,
        )
        digest_hex = hashlib.sha256(payload).hexdigest()
        digest = f"sha256:{digest_hex}"
        reference = _reference(digest_hex)
        pending_name = f"pending-{uuid4().hex}.tmp"
        pending_fd: int | None = None
        try:
            with (
                self._open_store() as store_fd,
                self._open_child_directory(store_fd, _PENDING_DIRECTORY) as pending_directory_fd,
            ):
                pending_fd = os.open(
                    pending_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=pending_directory_fd,
                )
                os.fchmod(pending_fd, 0o600)
                _write_all(pending_fd, payload)
                os.fsync(pending_fd)
                os.close(pending_fd)
                pending_fd = None
                with self._open_child_directory(store_fd, _DIGEST_DIRECTORY) as digest_directory_fd:
                    shard = digest_hex[:2]
                    self._ensure_child_directory(digest_directory_fd, shard)
                    with self._open_child_directory(digest_directory_fd, shard) as shard_fd:
                        final_name = f"{digest_hex}.jsonl"
                        try:
                            os.link(
                                pending_name,
                                final_name,
                                src_dir_fd=pending_directory_fd,
                                dst_dir_fd=shard_fd,
                                follow_symlinks=False,
                            )
                            os.fsync(shard_fd)
                        except FileExistsError:
                            existing = self._read_file_at(shard_fd, final_name)
                            if existing != payload:
                                raise AttemptTraceStoreError(
                                    "the evaluation attempt trace identity is occupied"
                                ) from None
                        os.unlink(pending_name, dir_fd=pending_directory_fd)
                        os.fsync(pending_directory_fd)
                        self._validate_file_at(shard_fd, final_name, payload)
            return StoredTraceArtifact(reference=reference, digest=digest)
        except AttemptTraceStoreError:
            raise
        except OSError as error:
            raise AttemptTraceStoreError(
                "the evaluation attempt trace could not be persisted"
            ) from error
        finally:
            if pending_fd is not None:
                with suppress(OSError):
                    os.close(pending_fd)
            with (
                suppress(OSError, AttemptTraceStoreError),
                self._open_store() as store_fd,
                self._open_child_directory(store_fd, _PENDING_DIRECTORY) as pending_directory_fd,
            ):
                os.unlink(pending_name, dir_fd=pending_directory_fd)
                os.fsync(pending_directory_fd)

    def load(
        self,
        *,
        reference: str,
        digest: str,
        evaluation_id: str,
        attempt_id: str,
        scenario_id: str,
    ) -> EvaluationAttempt:
        """Load a complete canonical object and revalidate its semantic model."""
        shard, filename = _validated_reference(reference, digest)
        try:
            with (
                self._open_store() as store_fd,
                self._open_child_directory(store_fd, _DIGEST_DIRECTORY) as digest_directory_fd,
                self._open_child_directory(digest_directory_fd, shard) as shard_fd,
            ):
                payload = self._read_file_at(shard_fd, filename)
            observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            if observed_digest != digest:
                raise ValueError("evaluation attempt trace digest does not match")
            return deserialize_attempt_trace(
                payload,
                evaluation_id=evaluation_id,
                attempt_id=attempt_id,
                scenario_id=scenario_id,
            )
        except AttemptTraceStoreError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as error:
            raise AttemptTraceStoreError(
                "the evaluation attempt trace failed integrity validation"
            ) from error

    def cleanup_unreferenced(self, referenced: set[str]) -> None:
        """Remove crash residue while a repository-wide SQLite write lock is held."""
        for reference in referenced:
            _validated_reference_from_path(reference)
        try:
            with self._open_store() as store_fd:
                with self._open_child_directory(store_fd, _PENDING_DIRECTORY) as pending_fd:
                    for name in os.listdir(pending_fd):
                        if _PENDING_NAME.fullmatch(name) is None:
                            raise ValueError("unexpected pending trace artifact")
                        status = os.stat(name, dir_fd=pending_fd, follow_symlinks=False)
                        if not stat.S_ISREG(status.st_mode):
                            raise ValueError("pending trace artifact is not a regular file")
                        os.unlink(name, dir_fd=pending_fd)
                    os.fsync(pending_fd)
                with self._open_child_directory(store_fd, _DIGEST_DIRECTORY) as digest_fd:
                    for shard in os.listdir(digest_fd):
                        if re.fullmatch(r"[0-9a-f]{2}", shard) is None:
                            raise ValueError("unexpected evaluation trace shard")
                        with self._open_child_directory(digest_fd, shard) as shard_fd:
                            removed = False
                            for filename in os.listdir(shard_fd):
                                if re.fullmatch(r"[0-9a-f]{64}\.jsonl", filename) is None:
                                    raise ValueError("unexpected evaluation trace artifact")
                                reference = (
                                    f"{_STORE_DIRECTORY}/{_DIGEST_DIRECTORY}/{shard}/{filename}"
                                )
                                if reference not in referenced:
                                    status = os.stat(
                                        filename,
                                        dir_fd=shard_fd,
                                        follow_symlinks=False,
                                    )
                                    if not stat.S_ISREG(status.st_mode):
                                        raise ValueError(
                                            "evaluation trace artifact is not a regular file"
                                        )
                                    os.unlink(filename, dir_fd=shard_fd)
                                    removed = True
                            if removed:
                                os.fsync(shard_fd)
        except (OSError, ValueError) as error:
            raise AttemptTraceStoreError(
                "the evaluation attempt trace store could not recover crash residue"
            ) from error

    @contextmanager
    def _open_store(self) -> Iterator[int]:
        with (
            self._open_artifact_root() as artifact_root_fd,
            self._open_child_directory(
                artifact_root_fd,
                _STORE_DIRECTORY,
            ) as store_fd,
        ):
            yield store_fd

    @contextmanager
    def _open_artifact_root(self) -> Iterator[int]:
        descriptor = os.open(
            self._artifact_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            self._validate_directory(descriptor)
            yield descriptor
        finally:
            os.close(descriptor)

    @contextmanager
    def _open_child_directory(self, parent_fd: int, name: str) -> Iterator[int]:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            self._validate_directory(descriptor)
            yield descriptor
        finally:
            os.close(descriptor)

    def _ensure_child_directory(self, parent_fd: int, name: str) -> None:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        with self._open_child_directory(parent_fd, name):
            pass

    @staticmethod
    def _validate_directory(descriptor: int) -> None:
        status = os.fstat(descriptor)
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
            raise OSError("evaluation trace store component is not a directory")
        os.fchmod(descriptor, 0o700)

    @staticmethod
    def _read_file_at(parent_fd: int, name: str) -> bytes:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o600
                or status.st_nlink != 1
                or status.st_size > _MAX_TRACE_BYTES
            ):
                raise OSError("evaluation trace artifact metadata is invalid")
            chunks: list[bytes] = []
            remaining = status.st_size
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    raise OSError("evaluation trace artifact ended early")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise OSError("evaluation trace artifact grew while reading")
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @classmethod
    def _validate_file_at(cls, parent_fd: int, name: str, expected: bytes) -> None:
        if cls._read_file_at(parent_fd, name) != expected:
            raise AttemptTraceStoreError("the evaluation attempt trace changed during persistence")


def serialize_attempt_trace(
    *,
    evaluation_id: str,
    attempt_id: str,
    attempt: EvaluationAttempt,
) -> bytes:
    """Return the only accepted canonical JSONL representation."""
    if not isinstance(attempt, EvaluationAttempt):
        raise TypeError("attempt trace serialization requires a typed attempt")
    trace = attempt.trace.model_dump(
        mode="json",
        exclude=set(_TRACE_COLLECTIONS),
        exclude_none=True,
    )
    records: list[dict[str, Any]] = [
        {
            "attempt_id": attempt_id,
            "evaluation_id": evaluation_id,
            "format_version": _FORMAT_VERSION,
            "record_type": "header",
            "scenario_id": attempt.scenario_id,
        },
        _payload_record("trace", trace),
    ]
    for collection, record_type in zip(
        _TRACE_COLLECTIONS,
        _RECORD_TYPES[1:-1],
    ):
        records.extend(
            _payload_record(
                record_type,
                item.model_dump(mode="json", exclude_none=True),
            )
            for item in getattr(attempt.trace, collection)
        )
    outcome: dict[str, Any]
    if attempt.completed_run is not None:
        outcome = {
            "completed_run": attempt.completed_run.model_dump(
                mode="json",
                exclude={"trace"},
                exclude_none=True,
            )
        }
    else:
        assert attempt.infrastructure_error is not None
        outcome = {
            "infrastructure_error": attempt.infrastructure_error.model_dump(
                mode="json", exclude_none=True
            )
        }
    records.append(_payload_record("outcome", outcome))
    validate_artifact_safe(records)
    return _serialize_records(records)


def deserialize_attempt_trace(
    payload: bytes,
    *,
    evaluation_id: str,
    attempt_id: str,
    scenario_id: str,
) -> EvaluationAttempt:
    """Reconstruct a typed attempt only from complete canonical record framing."""
    if not payload or len(payload) > _MAX_TRACE_BYTES or not payload.endswith(b"\n"):
        raise ValueError("evaluation attempt trace has no complete record boundary")
    raw_lines = payload[:-1].split(b"\n")
    if not raw_lines or any(not line for line in raw_lines):
        raise ValueError("evaluation attempt trace contains an empty record")
    records = [json.loads(line.decode("utf-8")) for line in raw_lines]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("evaluation attempt trace records must be objects")
    validate_artifact_safe(records)
    header = records[0]
    expected_header = {
        "attempt_id": attempt_id,
        "evaluation_id": evaluation_id,
        "format_version": _FORMAT_VERSION,
        "record_type": "header",
        "scenario_id": scenario_id,
    }
    if header != expected_header or len(records) < 3:
        raise ValueError("evaluation attempt trace header is invalid")
    grouped: dict[str, list[dict[str, Any]]] = {record_type: [] for record_type in _RECORD_TYPES}
    previous = -1
    for record in records[1:]:
        if set(record) != {"format_version", "record_type", "payload"}:
            raise ValueError("evaluation attempt trace record shape is invalid")
        if record["format_version"] != _FORMAT_VERSION:
            raise ValueError("evaluation attempt trace record version is invalid")
        record_type = record["record_type"]
        if record_type not in grouped or not isinstance(record["payload"], dict):
            raise ValueError("evaluation attempt trace record type is invalid")
        position = _RECORD_TYPES.index(record_type)
        if position < previous:
            raise ValueError("evaluation attempt trace record order is invalid")
        previous = position
        grouped[record_type].append(record["payload"])
    if (
        len(grouped["trace"]) != 1
        or len(grouped["outcome"]) != 1
        or records[-1]["record_type"] != "outcome"
    ):
        raise ValueError("evaluation attempt trace terminal framing is invalid")
    trace_document = dict(grouped["trace"][0])
    for collection, record_type in zip(
        _TRACE_COLLECTIONS,
        _RECORD_TYPES[1:-1],
    ):
        trace_document[collection] = grouped[record_type]
    outcome = grouped["outcome"][0]
    if set(outcome) == {"completed_run"} and isinstance(outcome["completed_run"], dict):
        completed_run = dict(outcome["completed_run"])
        completed_run["trace"] = grouped["runtime_event"]
        attempt_document: dict[str, Any] = {
            "scenario_id": scenario_id,
            "completed_run": completed_run,
            "trace": trace_document,
        }
    elif set(outcome) == {"infrastructure_error"} and isinstance(
        outcome["infrastructure_error"], dict
    ):
        attempt_document = {
            "scenario_id": scenario_id,
            "infrastructure_error": outcome["infrastructure_error"],
            "trace": trace_document,
        }
    else:
        raise ValueError("evaluation attempt trace outcome is invalid")
    attempt = EvaluationAttempt.model_validate_json(
        json.dumps(
            attempt_document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if (
        serialize_attempt_trace(
            evaluation_id=evaluation_id,
            attempt_id=attempt_id,
            attempt=attempt,
        )
        != payload
    ):
        raise ValueError("evaluation attempt trace is not canonical")
    return attempt


def _payload_record(record_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "format_version": _FORMAT_VERSION,
        "record_type": record_type,
        "payload": dict(payload),
    }


def _serialize_records(records: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(
            dict(record),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
        for record in records
    )


def _reference(digest_hex: str) -> str:
    return f"{_STORE_DIRECTORY}/{_DIGEST_DIRECTORY}/{digest_hex[:2]}/{digest_hex}.jsonl"


def _validated_reference(reference: str, digest: str) -> tuple[str, str]:
    digest_match = _DIGEST.fullmatch(digest)
    reference_match = _REFERENCE.fullmatch(reference)
    if digest_match is None or reference_match is None:
        raise AttemptTraceStoreError("the evaluation attempt trace reference is invalid")
    digest_hex = digest_match.group(1)
    shard, reference_hex = reference_match.groups()
    if reference_hex != digest_hex or shard != digest_hex[:2]:
        raise AttemptTraceStoreError(
            "the evaluation attempt trace reference does not match its digest"
        )
    return shard, f"{digest_hex}.jsonl"


def validate_trace_artifact_identity(reference: str, digest: str) -> None:
    """Validate a SQLite-safe trace reference without opening the artifact."""
    _validated_reference(reference, digest)


def _validated_reference_from_path(reference: str) -> None:
    match = _REFERENCE.fullmatch(reference)
    if match is None or match.group(1) != match.group(2)[:2]:
        raise AttemptTraceStoreError("the evaluation attempt trace reference is invalid")


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("evaluation attempt trace write made no progress")
        offset += written


__all__ = [
    "AttemptTraceStore",
    "AttemptTraceStoreError",
    "StoredTraceArtifact",
    "deserialize_attempt_trace",
    "serialize_attempt_trace",
    "validate_trace_artifact_identity",
]
