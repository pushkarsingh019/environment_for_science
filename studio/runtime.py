"""Product-owned deterministic Environment Runtime interface."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field

from studio.bundle import EnvironmentBundle, ScenarioManifest

RuntimeErrorCode = Literal["invalid", "not_found", "conflict", "internal"]


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
    terminal_disposition: Literal["recovered", "failed"]
    summary: str = Field(min_length=1)
    metrics: dict[str, float]
    evidence: dict[str, Any]
    reasons: tuple[str, ...]


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
    terminal_disposition: Literal["recovered", "failed"]
    summary: str
    metrics: dict[str, float]
    evidence: dict[str, Any]
    reasons: tuple[str, ...]


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
                {
                    "record_version": "1.0",
                    "record_type": "header",
                    "run_id": run_id,
                    "lineage": lineage.model_dump(mode="json"),
                    "payload": header.model_dump(mode="json"),
                },
                self._event_record(run_id, initial_event),
            ),
            create=True,
        )

    def append_events(self, run_id: str, events: tuple[TraceEvent, ...]) -> None:
        self._write(
            run_id,
            tuple(self._event_record(run_id, event) for event in events),
            create=False,
        )

    def finalize(
        self,
        run_id: str,
        event: TraceEvent,
        trace_digest: str,
        result_digest: str,
    ) -> None:
        self._write(
            run_id,
            (
                self._event_record(run_id, event),
                {
                    "record_version": "1.0",
                    "record_type": "result",
                    "run_id": run_id,
                    "trace_digest": trace_digest,
                    "result_digest": result_digest,
                },
            ),
            create=False,
        )

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
        path = self._directory / f"{run_id}.jsonl"
        flags = os.O_WRONLY | (os.O_CREAT | os.O_EXCL if create else os.O_APPEND)
        serialized = "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in records
        )
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise RuntimeContractError(
                f"canonical trace persistence failed: {error.strerror or error}",
                code="internal",
            ) from error


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
        self._trace_journal = (
            _JsonlTraceJournal(trace_directory) if trace_directory is not None else None
        )

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
        return self._snapshot(run_id)

    def reset(self, run_id: str) -> RunSnapshot:
        """Start a clean attempt while preserving the source run and trace."""
        source = self._run_record(run_id)
        return self._start_scenario(
            source.scenario,
            source.policy_agent,
            RunLineage(operation="reset", source_run_id=run_id),
        )

    def replay(self, run_id: str) -> ReplayReport:
        """Re-execute a finalized attempt from its frozen scenario and actions."""
        source = self._run_record(run_id)
        if source.status != "completed" or source.result_digest is None:
            raise RuntimeContractError(
                "replay requires a completed source run",
                code="conflict",
            )

        replay_start = self._start_scenario(
            source.scenario,
            source.policy_agent,
            RunLineage(operation="replay", source_run_id=run_id),
        )
        for event in source.trace:
            if event.type == "action" and event.action is not None:
                self.apply_action(
                    replay_start.run_id,
                    EnvironmentAction.model_validate(event.action),
                )
        replayed = self.verify(replay_start.run_id)
        if replayed.result_digest is None:
            raise RuntimeContractError(
                "replay did not produce a verifier result",
                code="internal",
            )
        source_snapshot = self._snapshot(run_id)
        return ReplayReport(
            source_run_id=run_id,
            replay_run_id=replayed.run_id,
            trace_matches=source_snapshot.trace_digest == replayed.trace_digest,
            result_matches=source_snapshot.result_digest == replayed.result_digest,
            source_trace_digest=source_snapshot.trace_digest,
            replay_trace_digest=replayed.trace_digest,
            source_result_digest=source.result_digest,
            replay_result_digest=replayed.result_digest,
        )

    def _start_scenario(
        self,
        scenario: ScenarioManifest,
        policy_agent: PolicyAgentIdentity,
        lineage: RunLineage,
    ) -> RunSnapshot:
        frozen_scenario = scenario.model_copy(deep=True)
        observation = deepcopy(frozen_scenario.initial_state.policy_visible)
        hidden_state = deepcopy(frozen_scenario.initial_state.hidden)
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
                frozen_scenario.initial_state.model_dump(mode="json")
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
        run_id = f"run-{uuid4().hex}"
        if self._trace_journal is not None:
            self._trace_journal.start(
                run_id,
                lineage,
                trace_header,
                trace[0],
            )
        self._runs[run_id] = _RunRecord(
            scenario=frozen_scenario,
            policy_agent=policy_agent.model_copy(deep=True),
            state=EpisodeState(
                procedure_state=self._bundle.procedure.initial_state,
                observation=observation,
                hidden_state=hidden_state,
                state_revision=0,
            ),
            trace=trace,
            status="active",
            verifier_result=None,
            result_digest=None,
            lineage=lineage,
            trace_header=trace_header,
        )
        return self._snapshot(run_id)

    def apply_action(self, run_id: str, action: EnvironmentAction) -> RunSnapshot:
        """Validate and apply one declared action, returning its observable effects."""
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

        update = self._environment_module.apply_action(
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
        if self._trace_journal is not None:
            self._trace_journal.append_events(run_id, trace_events)
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

    def verify(self, run_id: str) -> RunSnapshot:
        """Finalize the apparatus verifier against the current canonical evidence."""
        record = self._run_record(run_id)
        if record.status == "completed":
            raise RuntimeContractError(
                "a completed run cannot be verified again",
                code="conflict",
            )

        outcome = self._environment_module.verify(deepcopy(record.state))
        result = VerifierResult(
            verifier_id=str(self._bundle.verifier["id"]),
            result_version=str(self._bundle.verifier["result_version"]),
            passed=outcome.passed,
            terminal_disposition=outcome.terminal_disposition,
            summary=outcome.summary,
            metrics=deepcopy(outcome.metrics),
            evidence=deepcopy(outcome.evidence),
            reasons=outcome.reasons,
        )
        source_trace_digest = self._trace_digest(record)
        result_digest = _digest(
            {
                "result": result.model_dump(mode="json"),
                "source_trace_digest": source_trace_digest,
            }
        )
        verifier_event = TraceEvent(
            sequence=len(record.trace) + 1,
            type="verifier",
            summary=result.summary,
            verifier=result.model_dump(mode="json"),
        )
        final_trace_digest = _trace_digest(record.trace_header, [*record.trace, verifier_event])
        if self._trace_journal is not None:
            self._trace_journal.finalize(
                run_id,
                verifier_event,
                final_trace_digest,
                result_digest,
            )
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
