"""Product-owned deterministic Environment Runtime interface."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_module
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
)

from studio.bundle import EnvironmentBundle, ScenarioManifest

RuntimeErrorCode = Literal["invalid", "not_found", "conflict", "internal"]
TraceMutationOperation = Literal["action", "verify"]
TerminalDisposition = Literal["recovered", "closed", "aborted", "failed"]
_RUN_LOCK_STRIPE_COUNT = 64


class RuntimeContractError(ValueError):
    """Raised when a Runtime operation cannot satisfy its public contract."""

    def __init__(
        self,
        message: str,
        *,
        code: RuntimeErrorCode = "invalid",
    ) -> None:
        super().__init__(message)
        self.code = code


class PolicyAgentIdentity(BaseModel):
    """Identity frozen into a scored run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class EnvironmentAction(BaseModel):
    """One Policy-agent invocation of a declared simulated-Apparatus action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(min_length=1)
    arguments: dict[str, Any]


class TraceEvent(BaseModel):
    """One deterministic event in the canonical episode trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    type: Literal["observation", "action", "transition", "verifier"]
    summary: str = Field(min_length=1)
    observation: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    transition: dict[str, Any] | None = None
    verifier: dict[str, Any] | None = None


class VerifierResult(BaseModel):
    """Scientist-readable deterministic terminal judgment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verifier_id: str = Field(min_length=1)
    result_version: str = Field(min_length=1)
    passed: bool
    terminal_disposition: TerminalDisposition
    outcome_category: str | None = Field(default=None, min_length=1)
    summary: str = Field(min_length=1)
    metrics: dict[str, float]
    evidence: dict[str, Any]
    reasons: tuple[str, ...]

    @model_serializer(mode="wrap")
    def serialize_compatibly(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        """Keep the optional category out of legacy canonical result payloads."""
        serialized = cast(dict[str, Any], handler(self))
        if self.outcome_category is None:
            serialized.pop("outcome_category", None)
        return serialized


class RunLineage(BaseModel):
    """Non-canonical relationship between a run and its source attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["start", "reset", "replay"]
    source_run_id: str | None = None


class CanonicalTraceHeader(BaseModel):
    """Stable provenance included in the canonical trace digest domain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_version: Literal["1.0"] = "1.0"
    runtime_revision: Literal["science-environment-runtime/1"] = (
        "science-environment-runtime/1"
    )
    bundle_id: str
    bundle_revision: str
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_id: str
    split: str
    seed: int
    scenario_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    initial_state_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_agent: PolicyAgentIdentity


class RunSnapshot(BaseModel):
    """Caller-visible state returned by every Runtime operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_agent: PolicyAgentIdentity
    status: Literal["active", "awaiting_verification", "completed"]
    observation: dict[str, Any]
    permitted_actions: tuple[str, ...]
    trace: tuple[TraceEvent, ...]
    trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    verifier_result: VerifierResult | None = None
    result_digest: str | None = None
    lineage: RunLineage
    trace_header: CanonicalTraceHeader


class ReplayReport(BaseModel):
    """Digest comparison from re-executing a finalized source attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_run_id: str
    replay_run_id: str
    trace_matches: bool
    result_matches: bool
    source_trace_digest: str
    replay_trace_digest: str
    source_result_digest: str
    replay_result_digest: str


class EnvironmentModule(Protocol):
    """Apparatus-specific implementation installed behind the Runtime seam."""

    @property
    def bundle(self) -> EnvironmentBundle: ...

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState: ...

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate: ...

    def verify(self, state: EpisodeState) -> VerifierOutcome: ...


@dataclass
class EpisodeState:
    """Apparatus-specific episode state held behind the Runtime interface."""

    procedure_state: str
    observation: dict[str, Any]
    hidden_state: dict[str, Any]
    state_revision: int


@dataclass(frozen=True)
class EpisodeUpdate:
    """Apparatus result returned to the Runtime after one valid action."""

    observation: dict[str, Any]
    hidden_state: dict[str, Any]
    state_revision: int
    summary: str


@dataclass(frozen=True)
class VerifierOutcome:
    """Apparatus-specific judgment before Runtime provenance is attached."""

    passed: bool
    terminal_disposition: TerminalDisposition
    summary: str
    metrics: dict[str, float]
    evidence: dict[str, Any]
    reasons: tuple[str, ...]
    outcome_category: str | None = None


@dataclass
class _RunRecord:
    scenario: ScenarioManifest
    policy_agent: PolicyAgentIdentity
    state: EpisodeState
    trace: list[TraceEvent]
    status: Literal["active", "awaiting_verification", "completed"]
    verifier_result: VerifierResult | None
    result_digest: str | None
    lineage: RunLineage
    trace_header: CanonicalTraceHeader


@dataclass(frozen=True)
class _JournalContents:
    """Validated caller-visible records used to reconstruct one run."""

    lineage: RunLineage
    header: CanonicalTraceHeader
    events: tuple[TraceEvent, ...]
    trace_digest: str
    result_digest: str | None


@dataclass(frozen=True)
class PreparedTraceAppend:
    """Exact canonical bytes planned before a durable trace mutation."""

    run_id: str
    operation: TraceMutationOperation
    target_trace_digest: str
    base_journal_bytes: int
    append_payload: bytes


@dataclass(frozen=True)
class _PreparedJournalRecovery:
    disposition: Literal["base", "target", "partial"]
    journal: _JournalContents
    observed_base: bytes
    observed_tail: bytes


class _JournalHeaderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_version: Literal["1.0"]
    record_type: Literal["header"]
    run_id: str
    lineage: RunLineage
    payload: CanonicalTraceHeader


class _JournalEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_version: Literal["1.0"]
    record_type: Literal["event"]
    run_id: str
    payload: TraceEvent


class _JournalResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_version: Literal["1.0"]
    record_type: Literal["result"]
    run_id: str
    trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _JsonlTraceJournal:
    """Durable append-only export of one caller-visible canonical trace per run."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def start(
        self,
        run_id: str,
        lineage: RunLineage,
        header: CanonicalTraceHeader,
        initial_event: TraceEvent,
    ) -> None:
        self._write(
            run_id,
            (
                _canonical_journal_header(run_id, lineage, header),
                self._event_record(run_id, initial_event),
            ),
            create=True,
        )

    def plan_events(
        self,
        run_id: str,
        events: tuple[TraceEvent, ...],
        target_trace_digest: str,
    ) -> PreparedTraceAppend:
        return self._plan_append(
            run_id=run_id,
            operation="action",
            target_trace_digest=target_trace_digest,
            records=tuple(self._event_record(run_id, event) for event in events),
        )

    def plan_finalize(
        self,
        run_id: str,
        event: TraceEvent,
        trace_digest: str,
        result_digest: str,
    ) -> PreparedTraceAppend:
        return self._plan_append(
            run_id=run_id,
            operation="verify",
            target_trace_digest=trace_digest,
            records=(
                self._event_record(run_id, event),
                {
                    "record_version": "1.0",
                    "record_type": "result",
                    "run_id": run_id,
                    "trace_digest": trace_digest,
                    "result_digest": result_digest,
                },
            ),
        )

    def append(self, plan: PreparedTraceAppend) -> None:
        """Append exactly one prepared payload at its validated byte boundary."""
        descriptor: int | None = None
        try:
            _validate_prepared_trace_append(plan)
            path = self._path(plan.run_id)
            descriptor = os.open(
                path,
                os.O_WRONLY
                | os.O_APPEND
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            file_status = os.fstat(descriptor)
            if (
                not stat_module.S_ISREG(file_status.st_mode)
                or file_status.st_size != plan.base_journal_bytes
            ):
                raise OSError("canonical journal changed before its prepared append")
            _write_all(descriptor, plan.append_payload)
            os.fsync(descriptor)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            ValidationError,
        ) as error:
            raise RuntimeContractError(
                f"canonical trace persistence failed: {getattr(error, 'strerror', None) or error}",
                code="internal",
            ) from error
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)

    def load(self, run_id: str) -> _JournalContents:
        """Read and structurally validate one append-only canonical journal."""
        try:
            return _validated_journal_payload(run_id, self._read(run_id))
        except RuntimeContractError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, ValidationError):
            raise RuntimeContractError(
                "canonical trace could not be restored",
                code="internal",
            ) from None

    def inspect_prepared_append(
        self,
        plan: PreparedTraceAppend,
    ) -> _PreparedJournalRecovery:
        """Classify only the exact base/full/partial bytes bound by an intent."""
        try:
            _validate_prepared_trace_append(plan)
            payload = self._read(plan.run_id)
            if len(payload) < plan.base_journal_bytes:
                raise ValueError("canonical journal is shorter than its prepared base")
            base = payload[: plan.base_journal_bytes]
            tail = payload[plan.base_journal_bytes :]
            if not tail:
                disposition: Literal["base", "target", "partial"] = "base"
                validated_payload = base
            elif tail == plan.append_payload:
                disposition = "target"
                validated_payload = payload
            elif len(tail) < len(plan.append_payload) and plan.append_payload.startswith(tail):
                disposition = "partial"
                validated_payload = base
            else:
                raise ValueError("canonical journal has an unrelated prepared tail")
            journal = _validated_journal_payload(plan.run_id, validated_payload)
            return _PreparedJournalRecovery(
                disposition=disposition,
                journal=journal,
                observed_base=base,
                observed_tail=tail,
            )
        except RuntimeContractError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, ValidationError):
            raise RuntimeContractError(
                "canonical trace could not be recovered from its prepared append",
                code="internal",
            ) from None

    def truncate_prepared_prefix(
        self,
        plan: PreparedTraceAppend,
        observed_base: bytes,
        observed_tail: bytes,
    ) -> None:
        """Remove only a still-exact strict prefix after its base was validated."""
        if (
            not observed_tail
            or len(observed_tail) >= len(plan.append_payload)
            or not plan.append_payload.startswith(observed_tail)
        ):
            raise RuntimeContractError(
                "canonical trace prepared prefix is invalid",
                code="internal",
            )
        path = self._path(plan.run_id)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            file_status = os.fstat(descriptor)
            if (
                not stat_module.S_ISREG(file_status.st_mode)
                or file_status.st_size
                != plan.base_journal_bytes + len(observed_tail)
                or os.pread(
                    descriptor,
                    len(observed_base),
                    0,
                )
                != observed_base
                or os.pread(
                    descriptor,
                    len(observed_tail),
                    plan.base_journal_bytes,
                )
                != observed_tail
            ):
                raise OSError("canonical journal changed before prepared-prefix recovery")
            os.ftruncate(descriptor, plan.base_journal_bytes)
            os.fsync(descriptor)
        except OSError as error:
            raise RuntimeContractError(
                f"canonical trace recovery failed: {error.strerror or error}",
                code="internal",
            ) from error
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)

    @staticmethod
    def _event_record(run_id: str, event: TraceEvent) -> dict[str, Any]:
        return {
            "record_version": "1.0",
            "record_type": "event",
            "run_id": run_id,
            "payload": event.model_dump(mode="json", exclude_none=True),
        }

    def _write(
        self,
        run_id: str,
        records: tuple[dict[str, Any], ...],
        *,
        create: bool,
    ) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(run_id)
        flags = (
            os.O_WRONLY
            | (os.O_CREAT | os.O_EXCL if create else os.O_APPEND)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        serialized = _serialized_journal_records(records)
        try:
            descriptor = os.open(path, flags, 0o600)
            try:
                _write_all(descriptor, serialized)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise RuntimeContractError(
                f"canonical trace persistence failed: {error.strerror or error}",
                code="internal",
            ) from error

    def _plan_append(
        self,
        *,
        run_id: str,
        operation: TraceMutationOperation,
        target_trace_digest: str,
        records: tuple[dict[str, Any], ...],
    ) -> PreparedTraceAppend:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._path(run_id),
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            file_status = os.fstat(descriptor)
            if not stat_module.S_ISREG(file_status.st_mode):
                raise OSError("canonical journal is not a regular file")
            return PreparedTraceAppend(
                run_id=run_id,
                operation=operation,
                target_trace_digest=target_trace_digest,
                base_journal_bytes=file_status.st_size,
                append_payload=_serialized_journal_records(records),
            )
        except OSError as error:
            raise RuntimeContractError(
                f"canonical trace persistence failed: {error.strerror or error}",
                code="internal",
            ) from error
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)

    def _read(self, run_id: str) -> bytes:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._path(run_id),
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            file_status = os.fstat(descriptor)
            if not stat_module.S_ISREG(file_status.st_mode):
                raise OSError("canonical journal is not a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        except OSError as error:
            raise RuntimeContractError(
                f"canonical trace persistence failed: {error.strerror or error}",
                code="internal",
            ) from error
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)

    def _path(self, run_id: str) -> Path:
        if re.fullmatch(r"run-[0-9a-f]{32}", run_id) is None:
            raise RuntimeContractError(
                "canonical trace identity is invalid",
                code="internal",
            )
        return self._directory / f"{run_id}.jsonl"


class EnvironmentRuntime:
    """Run a frozen Environment without exposing apparatus-specific state logic."""

    def __init__(
        self,
        environment_module: EnvironmentModule,
        *,
        trace_directory: Path | None = None,
    ) -> None:
        self._environment_module = environment_module
        self._bundle = environment_module.bundle.model_copy(deep=True)
        self._revision_digest = _digest(self._bundle.model_dump(mode="json"))
        self._runs: dict[str, _RunRecord] = {}
        self._run_lock_stripes = tuple(
            RLock() for _ in range(_RUN_LOCK_STRIPE_COUNT)
        )
        self._trace_journal = (
            _JsonlTraceJournal(trace_directory) if trace_directory is not None else None
        )

    def _run_lock(self, run_id: str) -> RLock:
        """Return the stable synchronization boundary for one run identifier."""
        stable_hash = hashlib.sha256(run_id.encode("utf-8")).digest()
        stripe_index = int.from_bytes(stable_hash[:8], "big") % len(
            self._run_lock_stripes
        )
        return self._run_lock_stripes[stripe_index]

    def start(
        self,
        scenario_id: str,
        policy_agent: PolicyAgentIdentity,
    ) -> RunSnapshot:
        """Freeze one bundle revision and start its named scenario."""
        scenario = next(
            (item for item in self._bundle.scenarios if item.id == scenario_id),
            None,
        )
        if scenario is None:
            raise RuntimeContractError(
                f"unknown scenario {scenario_id!r}",
                code="not_found",
            )

        return self._start_scenario(
            scenario,
            policy_agent,
            RunLineage(operation="start"),
        )

    def current(self, run_id: str) -> RunSnapshot:
        """Return current caller-visible state without changing the trace."""
        with self._run_lock(run_id):
            return self._snapshot(run_id)

    def restore(
        self,
        run_id: str,
        *,
        expected_trace_header_digest: str,
        expected_trace_digest: str,
        refresh: bool = False,
    ) -> RunSnapshot:
        """Reconstruct one indexed run from its canonical append-only journal."""
        with self._run_lock(run_id):
            return self._restore(
                run_id,
                expected_trace_header_digest=expected_trace_header_digest,
                expected_trace_digest=expected_trace_digest,
                refresh=refresh,
            )

    def recover_prepared_append(
        self,
        plan: PreparedTraceAppend,
        *,
        expected_trace_header_digest: str,
        expected_trace_digest: str,
    ) -> RunSnapshot:
        """Validate and deterministically resolve one prepared journal tail."""
        with self._run_lock(plan.run_id):
            if self._trace_journal is None:
                raise RuntimeContractError(
                    "canonical trace recovery requires a durable journal",
                    code="internal",
                )
            recovery = self._trace_journal.inspect_prepared_append(plan)
            resolved_digest = (
                plan.target_trace_digest
                if recovery.disposition == "target"
                else expected_trace_digest
            )
            snapshot = self._restore(
                plan.run_id,
                expected_trace_header_digest=expected_trace_header_digest,
                expected_trace_digest=resolved_digest,
                refresh=True,
                journal_override=recovery.journal,
            )
            if recovery.disposition == "partial":
                self._trace_journal.truncate_prepared_prefix(
                    plan,
                    recovery.observed_base,
                    recovery.observed_tail,
                )
            return snapshot

    def _restore(
        self,
        run_id: str,
        *,
        expected_trace_header_digest: str,
        expected_trace_digest: str,
        refresh: bool,
        journal_override: _JournalContents | None = None,
    ) -> RunSnapshot:
        """Restore one run while its per-run synchronization boundary is held."""
        previous_record = self._runs.get(run_id)
        loaded: RunSnapshot | None = None
        header_matches = False
        trace_matches = False
        if previous_record is not None:
            loaded = self._snapshot(run_id)
            header_matches = (
                canonical_trace_header_digest(
                    run_id=loaded.run_id,
                    lineage=loaded.lineage,
                    header=loaded.trace_header,
                )
                == expected_trace_header_digest
            )
            trace_matches = loaded.trace_digest == expected_trace_digest
            if header_matches and trace_matches and not refresh:
                return loaded
        if self._trace_journal is None:
            if previous_record is not None:
                raise RuntimeContractError(
                    "the loaded run does not match its durable trace binding",
                    code="internal",
                )
            raise RuntimeContractError(
                f"unknown run {run_id!r}",
                code="not_found",
            )

        try:
            journal = journal_override or self._trace_journal.load(run_id)
            if (
                canonical_trace_header_digest(
                    run_id=run_id,
                    lineage=journal.lineage,
                    header=journal.header,
                )
                != expected_trace_header_digest
            ):
                raise RuntimeContractError(
                    "canonical trace header does not match its durable binding",
                    code="internal",
                )
            if journal.trace_digest != expected_trace_digest:
                raise RuntimeContractError(
                    "canonical trace does not match its durable checkpoint",
                    code="internal",
                )
            if (
                journal.header.bundle_id != self._bundle.bundle_id
                or journal.header.bundle_revision != self._bundle.bundle_revision
                or journal.header.revision_digest != self._revision_digest
            ):
                raise RuntimeContractError(
                    "canonical trace does not belong to this frozen Environment",
                    code="internal",
                )
            scenario = next(
                (
                    item
                    for item in self._bundle.scenarios
                    if item.id == journal.header.scenario_id
                ),
                None,
            )
            if scenario is None:
                raise RuntimeContractError(
                    "canonical trace names an unknown scenario",
                    code="internal",
                )
            if (
                loaded is not None
                and header_matches
                and trace_matches
                and loaded.trace_header == journal.header
                and loaded.lineage == journal.lineage
                and loaded.trace == journal.events
                and loaded.result_digest == journal.result_digest
            ):
                return loaded
            if previous_record is not None:
                self._runs.pop(run_id)
            self._start_scenario(
                scenario,
                journal.header.policy_agent,
                journal.lineage,
                run_id=run_id,
                persist=False,
            )
            for event in journal.events:
                if event.type == "action" and event.action is not None:
                    self._apply_action(
                        run_id,
                        EnvironmentAction.model_validate(event.action),
                        persist=False,
                    )
            if journal.result_digest is not None:
                self._verify(run_id, persist=False)
            restored = self._snapshot(run_id)
            if (
                restored.trace_header != journal.header
                or restored.lineage != journal.lineage
                or restored.trace != journal.events
                or restored.trace_digest != journal.trace_digest
                or restored.result_digest != journal.result_digest
            ):
                raise RuntimeContractError(
                    "canonical trace reconstruction did not match its journal",
                    code="internal",
                )
            return restored
        except Exception as error:
            current_record = self._runs.get(run_id)
            if current_record is not None and current_record is not previous_record:
                self._runs.pop(run_id)
            if previous_record is not None and run_id not in self._runs:
                self._runs[run_id] = previous_record
            raise RuntimeContractError(
                "canonical trace could not be restored",
                code="internal",
            ) from error

    def reset(self, run_id: str) -> RunSnapshot:
        """Start a clean attempt while preserving the source run and trace."""
        with self._run_lock(run_id):
            source = self._run_record(run_id)
            source_scenario = source.scenario.model_copy(deep=True)
            source_policy_agent = source.policy_agent.model_copy(deep=True)
        return self._start_scenario(
            source_scenario,
            source_policy_agent,
            RunLineage(operation="reset", source_run_id=run_id),
        )

    def replay(self, run_id: str) -> ReplayReport:
        """Re-execute a finalized attempt from its frozen scenario and actions."""
        with self._run_lock(run_id):
            source = self._run_record(run_id)
            if source.status != "completed" or source.result_digest is None:
                raise RuntimeContractError(
                    "replay requires a completed source run",
                    code="conflict",
                )
            source_scenario = source.scenario.model_copy(deep=True)
            source_policy_agent = source.policy_agent.model_copy(deep=True)
            source_actions = tuple(
                EnvironmentAction.model_validate(event.action)
                for event in source.trace
                if event.type == "action" and event.action is not None
            )
            source_snapshot = self._snapshot(run_id)
            source_result_digest = source.result_digest

        replay_start = self._start_scenario(
            source_scenario,
            source_policy_agent,
            RunLineage(operation="replay", source_run_id=run_id),
        )
        for action in source_actions:
            self.apply_action(replay_start.run_id, action)
        replayed = self.verify(replay_start.run_id)
        if replayed.result_digest is None:
            raise RuntimeContractError(
                "replay did not produce a verifier result",
                code="internal",
            )
        return ReplayReport(
            source_run_id=run_id,
            replay_run_id=replayed.run_id,
            trace_matches=source_snapshot.trace_digest == replayed.trace_digest,
            result_matches=source_snapshot.result_digest == replayed.result_digest,
            source_trace_digest=source_snapshot.trace_digest,
            replay_trace_digest=replayed.trace_digest,
            source_result_digest=source_result_digest,
            replay_result_digest=replayed.result_digest,
        )

    def _start_scenario(
        self,
        scenario: ScenarioManifest,
        policy_agent: PolicyAgentIdentity,
        lineage: RunLineage,
        *,
        run_id: str | None = None,
        persist: bool = True,
    ) -> RunSnapshot:
        frozen_scenario = scenario.model_copy(deep=True)
        initial_state = deepcopy(self._environment_module).initialize(
            frozen_scenario.model_copy(deep=True)
        )
        if (
            initial_state.procedure_state != self._bundle.procedure.initial_state
            or initial_state.state_revision != 0
        ):
            raise RuntimeContractError(
                "the Environment module returned an invalid initial episode state",
                code="internal",
            )
        observation = deepcopy(initial_state.observation)
        hidden_state = deepcopy(initial_state.hidden_state)
        _validate_runtime_payload(
            "Policy-visible observation",
            observation,
            self._bundle.observation_schema,
        )
        _validate_runtime_payload(
            "hidden Environment state",
            hidden_state,
            self._bundle.hidden_state_schema,
            expose_details=False,
        )
        scenario_digest = self._scenario_digest(frozen_scenario)
        trace_header = CanonicalTraceHeader(
            bundle_id=self._bundle.bundle_id,
            bundle_revision=self._bundle.bundle_revision,
            revision_digest=self._revision_digest,
            scenario_id=frozen_scenario.id,
            split=frozen_scenario.split,
            seed=frozen_scenario.seed,
            scenario_digest=scenario_digest,
            initial_state_digest=_digest(
                {"policy_visible": observation, "hidden": hidden_state}
            ),
            policy_agent=policy_agent.model_copy(deep=True),
        )
        trace = [
            TraceEvent(
                sequence=1,
                type="observation",
                summary=str(observation["summary"]),
                observation=deepcopy(observation),
            )
        ]
        resolved_run_id = run_id or f"run-{uuid4().hex}"
        with self._run_lock(resolved_run_id):
            if resolved_run_id in self._runs:
                raise RuntimeContractError(
                    f"run {resolved_run_id!r} is already loaded",
                    code="conflict",
                )
            if persist and self._trace_journal is not None:
                self._trace_journal.start(
                    resolved_run_id,
                    lineage,
                    trace_header,
                    trace[0],
                )
            self._runs[resolved_run_id] = _RunRecord(
                scenario=frozen_scenario,
                policy_agent=policy_agent.model_copy(deep=True),
                state=EpisodeState(
                    procedure_state=initial_state.procedure_state,
                    observation=observation,
                    hidden_state=hidden_state,
                    state_revision=initial_state.state_revision,
                ),
                trace=trace,
                status="active",
                verifier_result=None,
                result_digest=None,
                lineage=lineage,
                trace_header=trace_header,
            )
            return self._snapshot(resolved_run_id)

    def apply_action(
        self,
        run_id: str,
        action: EnvironmentAction,
        *,
        prepare_checkpoint: Callable[[PreparedTraceAppend], None] | None = None,
    ) -> RunSnapshot:
        """Validate and apply one declared action, returning its observable effects."""
        with self._run_lock(run_id):
            return self._apply_action(
                run_id,
                action,
                persist=True,
                prepare_checkpoint=prepare_checkpoint,
            )

    def _apply_action(
        self,
        run_id: str,
        action: EnvironmentAction,
        *,
        persist: bool,
        prepare_checkpoint: Callable[[PreparedTraceAppend], None] | None = None,
    ) -> RunSnapshot:
        record = self._run_record(run_id)
        if record.status != "active":
            raise RuntimeContractError(
                "actions are accepted only while a run is active",
                code="conflict",
            )

        action_definition = next(
            (item for item in self._bundle.actions if item.type == action.type),
            None,
        )
        if action_definition is None:
            raise RuntimeContractError(f"unknown action {action.type!r}")
        _validate_action_arguments(action.arguments, action_definition.input_schema)

        transition = next(
            (
                item
                for item in self._bundle.procedure.transitions
                if item.from_state == record.state.procedure_state
                and item.action == action.type
            ),
            None,
        )
        if transition is None:
            raise RuntimeContractError(
                f"action {action.type!r} is not permitted from "
                f"state {record.state.procedure_state!r}"
            )

        if prepare_checkpoint is not None and (
            not persist or self._trace_journal is None
        ):
            raise RuntimeContractError(
                "a durable trace checkpoint requires a canonical journal",
                code="internal",
            )

        update = deepcopy(self._environment_module).apply_action(
            deepcopy(record.state),
            action.model_copy(deep=True),
        )
        _validate_runtime_payload(
            "Policy-visible observation",
            update.observation,
            self._bundle.observation_schema,
        )
        _validate_runtime_payload(
            "hidden Environment state",
            update.hidden_state,
            self._bundle.hidden_state_schema,
            expose_details=False,
        )
        action_sequence = len(record.trace) + 1
        trace_events = (
            TraceEvent(
                sequence=action_sequence,
                type="action",
                summary=action_definition.title,
                action=action.model_dump(mode="json"),
            ),
            TraceEvent(
                sequence=action_sequence + 1,
                type="transition",
                summary=update.summary,
                transition={
                    "id": transition.id,
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "state_revision": update.state_revision,
                },
            ),
            TraceEvent(
                sequence=action_sequence + 2,
                type="observation",
                summary=str(update.observation["summary"]),
                observation=deepcopy(update.observation),
            ),
        )
        target_trace_digest = _trace_digest(
            record.trace_header,
            [*record.trace, *trace_events],
        )
        if persist and self._trace_journal is not None:
            plan = self._trace_journal.plan_events(
                run_id,
                trace_events,
                target_trace_digest,
            )
            if prepare_checkpoint is not None:
                prepare_checkpoint(plan)
            self._trace_journal.append(plan)
        record.trace.extend(trace_events)
        record.state = EpisodeState(
            procedure_state=transition.to_state,
            observation=deepcopy(update.observation),
            hidden_state=deepcopy(update.hidden_state),
            state_revision=update.state_revision,
        )
        terminal_states = {
            item.id for item in self._bundle.procedure.states if item.terminal
        }
        if transition.to_state in terminal_states:
            record.status = "awaiting_verification"
        return self._snapshot(run_id)

    def verify(
        self,
        run_id: str,
        *,
        prepare_checkpoint: Callable[[PreparedTraceAppend], None] | None = None,
    ) -> RunSnapshot:
        """Finalize the apparatus verifier against the current canonical evidence."""
        with self._run_lock(run_id):
            return self._verify(
                run_id,
                persist=True,
                prepare_checkpoint=prepare_checkpoint,
            )

    def _verify(
        self,
        run_id: str,
        *,
        persist: bool,
        prepare_checkpoint: Callable[[PreparedTraceAppend], None] | None = None,
    ) -> RunSnapshot:
        record = self._run_record(run_id)
        if record.status == "completed":
            raise RuntimeContractError(
                "a completed run cannot be verified again",
                code="conflict",
            )

        if prepare_checkpoint is not None and (
            not persist or self._trace_journal is None
        ):
            raise RuntimeContractError(
                "a durable trace checkpoint requires a canonical journal",
                code="internal",
            )

        outcome = deepcopy(self._environment_module).verify(deepcopy(record.state))
        result = VerifierResult(
            verifier_id=str(self._bundle.verifier["id"]),
            result_version=str(self._bundle.verifier["result_version"]),
            passed=outcome.passed,
            terminal_disposition=outcome.terminal_disposition,
            outcome_category=outcome.outcome_category,
            summary=outcome.summary,
            metrics=deepcopy(outcome.metrics),
            evidence=deepcopy(outcome.evidence),
            reasons=outcome.reasons,
        )
        result_payload = result.model_dump(mode="json", exclude_none=True)
        source_trace_digest = self._trace_digest(record)
        result_digest = _digest(
            {
                "result": result_payload,
                "source_trace_digest": source_trace_digest,
            }
        )
        verifier_event = TraceEvent(
            sequence=len(record.trace) + 1,
            type="verifier",
            summary=result.summary,
            verifier=result_payload,
        )
        final_trace_digest = _trace_digest(record.trace_header, [*record.trace, verifier_event])
        if persist and self._trace_journal is not None:
            plan = self._trace_journal.plan_finalize(
                run_id,
                verifier_event,
                final_trace_digest,
                result_digest,
            )
            if prepare_checkpoint is not None:
                prepare_checkpoint(plan)
            self._trace_journal.append(plan)
        record.result_digest = result_digest
        record.trace.append(verifier_event)
        record.verifier_result = result
        record.status = "completed"
        return self._snapshot(run_id)

    def _snapshot(self, run_id: str) -> RunSnapshot:
        record = self._run_record(run_id)
        return RunSnapshot(
            run_id=run_id,
            scenario_id=record.scenario.id,
            revision_digest=self._revision_digest,
            scenario_digest=record.trace_header.scenario_digest,
            policy_agent=record.policy_agent.model_copy(deep=True),
            status=record.status,
            observation=deepcopy(record.state.observation),
            permitted_actions=(
                self._bundle.action_types if record.status == "active" else ()
            ),
            trace=tuple(event.model_copy(deep=True) for event in record.trace),
            trace_digest=self._trace_digest(record),
            verifier_result=(
                record.verifier_result.model_copy(deep=True)
                if record.verifier_result is not None
                else None
            ),
            result_digest=record.result_digest,
            lineage=record.lineage.model_copy(deep=True),
            trace_header=record.trace_header.model_copy(deep=True),
        )

    def _run_record(self, run_id: str) -> _RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise RuntimeContractError(
                f"unknown run {run_id!r}",
                code="not_found",
            ) from error

    def _scenario_digest(self, scenario: ScenarioManifest) -> str:
        return _digest(
            {
                "revision_digest": self._revision_digest,
                "scenario": scenario.model_dump(mode="json"),
            }
        )

    def _trace_digest(self, record: _RunRecord) -> str:
        return _trace_digest(record.trace_header, record.trace)


def _validated_journal_records(
    run_id: str,
    records: list[Any],
) -> _JournalContents:
    if len(records) < 2:
        raise ValueError("canonical journal is incomplete")
    header_record = _JournalHeaderRecord.model_validate(records[0])
    if header_record.run_id != run_id:
        raise ValueError("canonical journal header has another run identity")

    events: list[TraceEvent] = []
    result: _JournalResultRecord | None = None
    for index, document in enumerate(records[1:], start=1):
        if not isinstance(document, dict):
            raise ValueError("canonical journal records must be objects")
        record_type = document.get("record_type")
        if record_type == "event" and result is None:
            event_record = _JournalEventRecord.model_validate(document)
            if event_record.run_id != run_id:
                raise ValueError("canonical journal event has another run identity")
            events.append(event_record.payload)
            continue
        if record_type == "result" and index == len(records) - 1 and result is None:
            result = _JournalResultRecord.model_validate(document)
            if result.run_id != run_id:
                raise ValueError("canonical journal result has another run identity")
            continue
        raise ValueError("canonical journal ordering is invalid")

    if not events or any(
        event.sequence != sequence
        for sequence, event in enumerate(events, start=1)
    ):
        raise ValueError("canonical journal event sequence is invalid")
    has_verifier = any(event.type == "verifier" for event in events)
    if (result is None and has_verifier) or (
        result is not None and events[-1].type != "verifier"
    ):
        raise ValueError("canonical journal result boundary is invalid")

    trace_digest = _trace_digest(header_record.payload, events)
    result_digest: str | None = None
    if result is not None:
        if trace_digest != result.trace_digest:
            raise ValueError("canonical journal trace digest does not match")
        verifier_document = events[-1].verifier
        if verifier_document is None:
            raise ValueError("canonical journal has no verifier result")
        verifier = VerifierResult.model_validate(verifier_document)
        source_trace_digest = _trace_digest(header_record.payload, events[:-1])
        result_digest = _digest(
            {
                "result": verifier.model_dump(mode="json"),
                "source_trace_digest": source_trace_digest,
            }
        )
        if result_digest != result.result_digest:
            raise ValueError("canonical journal result digest does not match")

    return _JournalContents(
        lineage=header_record.lineage,
        header=header_record.payload,
        events=tuple(events),
        trace_digest=trace_digest,
        result_digest=result_digest,
    )


def _validated_journal_payload(run_id: str, payload: bytes) -> _JournalContents:
    if not payload or not payload.endswith(b"\n"):
        raise ValueError("canonical journal does not end at a record boundary")
    lines = payload.decode("utf-8").splitlines()
    if not lines or any(not line for line in lines):
        raise ValueError("canonical journal contains an empty record")
    return _validated_journal_records(run_id, [json.loads(line) for line in lines])


def _validate_prepared_trace_append(plan: PreparedTraceAppend) -> None:
    if (
        plan.base_journal_bytes < 0
        or re.fullmatch(r"sha256:[0-9a-f]{64}", plan.target_trace_digest) is None
        or not plan.append_payload
        or not plan.append_payload.endswith(b"\n")
    ):
        raise ValueError("prepared trace append metadata is invalid")
    raw_records = [
        json.loads(line)
        for line in plan.append_payload.decode("utf-8").splitlines()
    ]
    if any(not isinstance(record, dict) for record in raw_records):
        raise ValueError("prepared trace append records must be objects")
    records = tuple(cast(dict[str, Any], record) for record in raw_records)
    if _serialized_journal_records(records) != plan.append_payload:
        raise ValueError("prepared trace append records are not canonical")
    if plan.operation == "action":
        if len(records) != 3:
            raise ValueError("prepared action append must contain three events")
        events = tuple(_JournalEventRecord.model_validate(record) for record in records)
        if any(event.run_id != plan.run_id for event in events) or tuple(
            event.payload.type for event in events
        ) != ("action", "transition", "observation"):
            raise ValueError("prepared action append has invalid semantics")
        return
    if plan.operation == "verify":
        if len(records) != 2:
            raise ValueError("prepared verifier append must contain an event and result")
        event = _JournalEventRecord.model_validate(records[0])
        result = _JournalResultRecord.model_validate(records[1])
        if (
            event.run_id != plan.run_id
            or event.payload.type != "verifier"
            or result.run_id != plan.run_id
            or result.trace_digest != plan.target_trace_digest
        ):
            raise ValueError("prepared verifier append has invalid semantics")
        return
    raise ValueError("prepared trace append operation is invalid")


def _serialized_journal_records(records: tuple[dict[str, Any], ...]) -> bytes:
    return "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        for record in records
    ).encode("utf-8")


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("canonical journal write made no progress")
        remaining = remaining[written:]


def _trace_digest(
    header: CanonicalTraceHeader,
    events: list[TraceEvent],
) -> str:
    return _digest(
        {
            "header": header.model_dump(mode="json"),
            "events": [
                event.model_dump(mode="json", exclude_none=True) for event in events
            ],
        }
    )


def canonical_trace_header_digest(
    *,
    run_id: str,
    lineage: RunLineage,
    header: CanonicalTraceHeader,
) -> str:
    """Digest the complete immutable first record of a canonical run journal."""
    return _digest(_canonical_journal_header(run_id, lineage, header))


def _canonical_journal_header(
    run_id: str,
    lineage: RunLineage,
    header: CanonicalTraceHeader,
) -> dict[str, Any]:
    return {
        "record_version": "1.0",
        "record_type": "header",
        "run_id": run_id,
        "lineage": lineage.model_dump(mode="json"),
        "payload": header.model_dump(mode="json"),
    }


def _digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _validate_action_arguments(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    try:
        Draft202012Validator(schema).validate(arguments)
    except JsonSchemaValidationError as error:
        raise RuntimeContractError(
            f"action arguments do not match its schema: {error.message}"
        ) from error


def _validate_runtime_payload(
    label: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    *,
    expose_details: bool = True,
) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except JsonSchemaValidationError as error:
        message = f"{label} does not match the frozen bundle schema"
        if expose_details:
            raise RuntimeContractError(
                f"{message}: {error.message}",
                code="internal",
            ) from error
    else:
        return
    raise RuntimeContractError(message, code="internal")
