"""Application service joining reversible authoring to isolated frozen runtimes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from environments.eeg.authoring import (
    EegAuthoringState,
    EegCommandResult,
    EegProcedureConfiguration,
    apply_authoring_command,
    compile_frozen_bundle,
    seed_authoring_state,
    stage_descriptive_note,
)
from environments.eeg.curriculum import (
    SeededScenarioChoice,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from studio.authoring import (
    DraftActor,
    DraftRepository,
    DraftRevisionConflict,
    DraftSnapshot,
)
from studio.bundle import EnvironmentBundle, validate_environment_bundle
from studio.index import (
    FrozenEnvironmentRecord,
    RunIndexRecord,
    RunTraceIntent,
    StudioIndex,
    StudioIndexError,
    StudioIndexNotFound,
)
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    PreparedTraceAppend,
    ReplayReport,
    RunSnapshot,
    RuntimeContractError,
    RuntimeErrorCode,
    canonical_trace_header_digest,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthoringAssistantIdentity(_FrozenModel):
    """Scientist-facing identity used only for reversible draft edits."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class RoleBoundaryDescriptor(_FrozenModel):
    """Explicit execution boundary for one isolated Studio agent role."""

    identity_id: str = Field(min_length=1)
    identity_name: str = Field(min_length=1)
    role: Literal["authoring_assistant", "policy_agent"]
    prompt_contract: str = Field(min_length=1)
    tool_catalog: tuple[str, ...] = Field(min_length=1)
    context_scope: str = Field(min_length=1)
    state_scope: str = Field(min_length=1)
    log_sink: str = Field(min_length=1)


class FrozenEnvironment(_FrozenModel):
    """Caller-visible identity of one validated frozen bundle snapshot."""

    frozen_environment_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_id: str = Field(min_length=1)
    scenario_ids: tuple[str, ...] = Field(min_length=1)
    draft_revision: int = Field(ge=1)
    procedure: EegProcedureConfiguration

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_single_scenario_metadata(cls, value: object) -> object:
        """Promote persisted Ticket 02 metadata without rewriting its record."""
        if isinstance(value, dict) and "scenario_ids" not in value:
            promoted = dict(value)
            scenario_id = promoted.get("scenario_id")
            if isinstance(scenario_id, str):
                promoted["scenario_ids"] = [scenario_id]
            return promoted
        return value


class AuthoringCommandOutcome(_FrozenModel):
    """One command interpretation and the resulting persistent draft head."""

    draft: DraftSnapshot
    result: EegCommandResult


AUTHORING_ASSISTANT = DraftActor(
    id="seeded-authoring-assistant",
    name="Seeded Authoring assistant",
    role="authoring_assistant",
)
ENVIRONMENT_AUTHOR = DraftActor(
    id="local-environment-author",
    name="Environment author",
    role="environment_author",
)
SEEDED_POLICY_AGENT = PolicyAgentIdentity(
    id="seeded-policy-agent",
    name="Seeded recovery Policy agent",
)

_AUTHORING_TOOL_CATALOG = (
    "add_montage_site",
    "remove_montage_site",
    "set_sampling_rate",
    "set_online_bandpass",
    "set_notch_filter",
)
_RUN_MUTATION_LOCK_STRIPE_COUNT = 64


class ScienceStudio:
    """Own one persistent draft and route each run to its frozen Runtime."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root.resolve()
        training = load_training_scenario_set()
        self._source_bundle = training.environment_bundle
        self._seeded_scenarios = training.seeded_examples
        seed_state = seed_authoring_state(self._source_bundle)
        self._drafts = DraftRepository(
            artifact_root=self._artifact_root,
            workspace_id="eeg-marker-recovery-draft",
            seed_state=seed_state.model_dump(mode="json"),
            state_validator=_validated_authoring_state,
        )
        self._index = StudioIndex(self._artifact_root)
        self._trace_directory = self._artifact_root / "traces"
        default_runtime = _runtime_for_bundle(
            self._source_bundle,
            trace_directory=self._trace_directory,
        )
        self._default_runtime = default_runtime
        self._frozen_runtimes: dict[str, EnvironmentRuntime] = {}
        self._frozen_metadata: dict[str, FrozenEnvironment] = {}
        self._run_mutation_lock_stripes = tuple(
            RLock() for _ in range(_RUN_MUTATION_LOCK_STRIPE_COUNT)
        )
        try:
            frozen_records = self._index.list_frozen()
        except StudioIndexError as error:
            raise _index_runtime_error(error) from error
        for record in frozen_records:
            self._install_frozen_record(record)

    @property
    def source_bundle(self) -> EnvironmentBundle:
        return self._source_bundle.model_copy(deep=True)

    @property
    def source_environment(self) -> EegEnvironmentModule:
        return EegEnvironmentModule(self._source_bundle)

    @property
    def seeded_scenarios(self) -> tuple[SeededScenarioChoice, ...]:
        """Return the reviewed neutral examples exposed by the local console."""
        return tuple(choice.model_copy(deep=True) for choice in self._seeded_scenarios)

    @property
    def authoring_assistant(self) -> AuthoringAssistantIdentity:
        return AuthoringAssistantIdentity(
            id=AUTHORING_ASSISTANT.id,
            name=AUTHORING_ASSISTANT.name,
        )

    @property
    def role_boundaries(self) -> tuple[RoleBoundaryDescriptor, RoleBoundaryDescriptor]:
        """Return detached contracts proving the two agent instances are isolated."""
        authoring = RoleBoundaryDescriptor(
            identity_id=AUTHORING_ASSISTANT.id,
            identity_name=AUTHORING_ASSISTANT.name,
            role="authoring_assistant",
            prompt_contract=(
                "No live model prompt is installed: the offline Authoring assistant "
                "interprets one bounded EEG draft change at a time."
            ),
            tool_catalog=_AUTHORING_TOOL_CATALOG,
            context_scope=(
                "Current reversible EEG draft and staged unverified notes only; run "
                "observations, verifier state, and hidden scenario truth are excluded."
            ),
            state_scope="draft-workspace.sqlite3/eeg-marker-recovery-draft",
            log_sink="draft-workspace.sqlite3/append-only-authoring-activity",
        )
        policy = RoleBoundaryDescriptor(
            identity_id=SEEDED_POLICY_AGENT.id,
            identity_name=SEEDED_POLICY_AGENT.name,
            role="policy_agent",
            prompt_contract=(
                "No live model prompt is installed: the seeded Policy agent receives "
                "only the frozen Policy-visible runtime observation."
            ),
            tool_catalog=self._source_bundle.action_types,
            context_scope=(
                "Frozen Policy-visible observation and canonical transitions only; "
                "the authoring draft, notes, Authoring-assistant activity, verifier "
                "implementation, and hidden state are excluded."
            ),
            state_scope="isolated-environment-runtime/<run_id>",
            log_sink="traces/<run_id>.jsonl/canonical-policy-trace",
        )
        return (authoring, policy)

    def current_draft(self) -> DraftSnapshot:
        return self._drafts.current().model_copy(deep=True)

    def apply_authoring_command(
        self,
        *,
        command: str,
        expected_revision: int,
    ) -> AuthoringCommandOutcome:
        current = self._current_at_revision(expected_revision)
        state = _state_from_snapshot(current)
        result = apply_authoring_command(state, command)
        if result.status == "unsupported":
            return AuthoringCommandOutcome(draft=current, result=result)
        updated = self._drafts.apply(
            state=result.state.model_dump(mode="json"),
            expected_revision=expected_revision,
            actor=AUTHORING_ASSISTANT,
            description=result.summary,
        )
        return AuthoringCommandOutcome(draft=updated, result=result)

    def stage_note(
        self,
        *,
        filename: str,
        content: str,
        expected_revision: int,
    ) -> DraftSnapshot:
        current = self._current_at_revision(expected_revision)
        state = stage_descriptive_note(
            _state_from_snapshot(current),
            filename,
            content,
        )
        return self._drafts.apply(
            state=state.model_dump(mode="json"),
            expected_revision=expected_revision,
            actor=ENVIRONMENT_AUTHOR,
            description=f"Staged {filename} as unverified descriptive input",
        )

    def undo(self, *, expected_revision: int) -> DraftSnapshot:
        return self._drafts.undo(
            expected_revision=expected_revision,
            actor=ENVIRONMENT_AUTHOR,
            description="Undid the latest reachable draft change",
        )

    def redo(self, *, expected_revision: int) -> DraftSnapshot:
        return self._drafts.redo(
            expected_revision=expected_revision,
            actor=ENVIRONMENT_AUTHOR,
            description="Redid the next reachable draft change",
        )

    def restore_seed(self, *, expected_revision: int) -> DraftSnapshot:
        return self._drafts.restore_seed(
            expected_revision=expected_revision,
            actor=ENVIRONMENT_AUTHOR,
            description="Restored the seeded EEG draft",
        )

    def freeze(self, *, expected_revision: int) -> FrozenEnvironment:
        draft = self._current_at_revision(expected_revision)
        state = _state_from_snapshot(draft)
        bundle = compile_frozen_bundle(
            self._source_bundle,
            state,
            revision=draft.revision,
        )
        revision_digest = _bundle_digest(bundle)
        frozen_id = _frozen_id(revision_digest)
        metadata = FrozenEnvironment(
            frozen_environment_id=frozen_id,
            bundle_revision=bundle.bundle_revision,
            revision_digest=revision_digest,
            scenario_id=bundle.scenarios[0].id,
            scenario_ids=tuple(scenario.id for scenario in bundle.scenarios),
            draft_revision=draft.revision,
            procedure=state.procedure.model_copy(deep=True),
        )
        if frozen_id not in self._frozen_runtimes:
            try:
                record = self._index.record_frozen(
                    frozen_environment_id=frozen_id,
                    revision_digest=revision_digest,
                    bundle_document=bundle.model_dump(mode="json"),
                    metadata_document=metadata.model_dump(mode="json"),
                )
            except StudioIndexError as error:
                raise _index_runtime_error(error) from error
            self._install_frozen_record(record)
        return self._frozen_metadata[frozen_id].model_copy(deep=True)

    def start_run(
        self,
        *,
        scenario_id: str,
        policy_agent: PolicyAgentIdentity,
        frozen_environment_id: str,
    ) -> RunSnapshot:
        runtime = self._runtime_for_frozen(frozen_environment_id)
        frozen = self._frozen_metadata[frozen_environment_id]
        if scenario_id not in frozen.scenario_ids:
            raise RuntimeContractError(
                "the scenario does not match the frozen Environment identity",
                code="invalid",
            )
        snapshot = runtime.start(scenario_id, policy_agent)
        try:
            self._index.record_run(
                run_id=snapshot.run_id,
                frozen_environment_id=frozen_environment_id,
                trace_header_digest=_trace_header_digest(snapshot),
                trace_digest=snapshot.trace_digest,
            )
        except StudioIndexError as error:
            raise _index_runtime_error(error) from error
        return snapshot

    def current_run(self, run_id: str) -> RunSnapshot:
        with self._serialized_run(run_id):
            route = self._run_route(run_id)
            runtime, _ = self._runtime_for_run(run_id, route)
            return runtime.current(run_id)

    def apply_run_action(
        self,
        run_id: str,
        action: EnvironmentAction,
    ) -> RunSnapshot:
        with self._serialized_run(run_id):
            route = self._run_route(run_id)
            runtime, route = self._runtime_for_run(run_id, route)
            prepared: RunTraceIntent | None = None

            def prepare_checkpoint(plan: PreparedTraceAppend) -> None:
                nonlocal prepared
                prepared = self._prepare_run_trace(route, plan, operation="action")

            snapshot = runtime.apply_action(
                run_id,
                action,
                prepare_checkpoint=prepare_checkpoint,
            )
            self._resolve_run_trace(
                prepared,
                snapshot,
                runtime=runtime,
                route=route,
            )
            return snapshot

    def verify_run(self, run_id: str) -> RunSnapshot:
        with self._serialized_run(run_id):
            route = self._run_route(run_id)
            runtime, route = self._runtime_for_run(run_id, route)
            prepared: RunTraceIntent | None = None

            def prepare_checkpoint(plan: PreparedTraceAppend) -> None:
                nonlocal prepared
                prepared = self._prepare_run_trace(route, plan, operation="verify")

            snapshot = runtime.verify(
                run_id,
                prepare_checkpoint=prepare_checkpoint,
            )
            self._resolve_run_trace(
                prepared,
                snapshot,
                runtime=runtime,
                route=route,
            )
            return snapshot

    def reset_run(self, run_id: str) -> RunSnapshot:
        with self._serialized_run(run_id):
            route = self._run_route(run_id)
            runtime, route = self._runtime_for_run(run_id, route)
            snapshot = runtime.reset(run_id)
            self._record_run_route(snapshot, route.frozen_environment_id)
            return snapshot

    def replay_run(self, run_id: str) -> tuple[RunSnapshot, ReplayReport]:
        with self._serialized_run(run_id):
            route = self._run_route(run_id)
            runtime, route = self._runtime_for_run(run_id, route)
            report = runtime.replay(run_id)
            snapshot = runtime.current(report.replay_run_id)
            self._record_run_route(snapshot, route.frozen_environment_id)
            return snapshot, report

    def _current_at_revision(self, expected_revision: int) -> DraftSnapshot:
        current = self._drafts.current()
        if current.revision != expected_revision:
            raise DraftRevisionConflict(
                expected_revision=expected_revision,
                actual_revision=current.revision,
            )
        return current

    def _run_mutation_lock(self, run_id: str) -> RLock:
        stable_hash = hashlib.sha256(run_id.encode("utf-8")).digest()
        stripe_index = int.from_bytes(stable_hash[:8], "big") % len(
            self._run_mutation_lock_stripes
        )
        return self._run_mutation_lock_stripes[stripe_index]

    @contextmanager
    def _serialized_run(self, run_id: str) -> Iterator[None]:
        with self._run_mutation_lock(run_id):
            try:
                with self._index.lock_run(run_id):
                    yield
            except StudioIndexError as error:
                raise _index_runtime_error(error) from error

    def _runtime_for_run(
        self,
        run_id: str,
        route: RunIndexRecord,
    ) -> tuple[EnvironmentRuntime, RunIndexRecord]:
        runtime = (
            self._default_runtime
            if route.frozen_environment_id is None
            else self._runtime_for_frozen(route.frozen_environment_id)
        )
        if route.trace_header_digest is None or route.trace_digest is None:
            raise RuntimeContractError(
                "the run has no durable trace binding",
                code="internal",
            )
        route = self._recover_run_trace(runtime, route)
        if route.trace_header_digest is None or route.trace_digest is None:
            raise RuntimeContractError(
                "the run recovery removed its durable trace binding",
                code="internal",
            )
        runtime.restore(
            run_id,
            expected_trace_header_digest=route.trace_header_digest,
            expected_trace_digest=route.trace_digest,
            refresh=True,
        )
        return runtime, route

    def _recover_run_trace(
        self,
        runtime: EnvironmentRuntime,
        route: RunIndexRecord,
    ) -> RunIndexRecord:
        intent = self._index.get_run_trace_intent(route.run_id)
        if intent is None:
            return route
        if (
            route.trace_header_digest is None
            or route.trace_digest is None
            or intent.expected_trace_digest != route.trace_digest
        ):
            raise RuntimeContractError(
                "the prepared run mutation does not match its durable checkpoint",
                code="internal",
            )
        plan = PreparedTraceAppend(
            run_id=intent.run_id,
            operation=intent.operation,
            target_trace_digest=intent.target_trace_digest,
            base_journal_bytes=intent.base_journal_bytes,
            append_payload=intent.append_payload,
        )
        snapshot = runtime.recover_prepared_append(
            plan,
            expected_trace_header_digest=route.trace_header_digest,
            expected_trace_digest=route.trace_digest,
        )
        return self._index.resolve_run_trace_intent(
            intent,
            observed_trace_digest=snapshot.trace_digest,
        )

    def _runtime_for_frozen(self, frozen_environment_id: str) -> EnvironmentRuntime:
        cached = self._frozen_runtimes.get(frozen_environment_id)
        if cached is not None:
            return cached
        try:
            record = self._index.get_frozen(frozen_environment_id)
        except StudioIndexNotFound as error:
            raise RuntimeContractError(
                f"unknown frozen Environment {frozen_environment_id!r}",
                code="not_found",
            ) from error
        except StudioIndexError as error:
            raise _index_runtime_error(error) from error
        self._install_frozen_record(record)
        return self._frozen_runtimes[frozen_environment_id]

    def _install_frozen_record(self, record: FrozenEnvironmentRecord) -> None:
        try:
            bundle = validate_environment_bundle(record.bundle_document)
            metadata = FrozenEnvironment.model_validate(record.metadata_document)
            procedure = seed_authoring_state(bundle).procedure
        except ValueError as error:
            raise RuntimeContractError(
                "the frozen Environment index is invalid",
                code="internal",
            ) from error
        if (
            metadata.frozen_environment_id != record.frozen_environment_id
            or record.frozen_environment_id != _frozen_id(record.revision_digest)
            or metadata.revision_digest != record.revision_digest
            or metadata.revision_digest != _bundle_digest(bundle)
            or metadata.bundle_revision != bundle.bundle_revision
            or not _bundle_revision_matches_draft(
                metadata.bundle_revision,
                metadata.draft_revision,
            )
            or metadata.scenario_id != bundle.scenarios[0].id
            or metadata.scenario_ids
            != tuple(scenario.id for scenario in bundle.scenarios)
            or metadata.procedure != procedure
        ):
            raise RuntimeContractError(
                "the frozen Environment index is inconsistent",
                code="internal",
            )
        self._frozen_runtimes[record.frozen_environment_id] = _runtime_for_bundle(
            bundle,
            trace_directory=self._trace_directory,
        )
        self._frozen_metadata[record.frozen_environment_id] = metadata

    def _run_route(self, run_id: str) -> RunIndexRecord:
        try:
            return self._index.get_run(run_id)
        except StudioIndexNotFound as error:
            raise RuntimeContractError(
                f"unknown run {run_id!r}",
                code="not_found",
            ) from error
        except StudioIndexError as error:
            raise _index_runtime_error(error) from error

    def _record_run_route(
        self,
        snapshot: RunSnapshot,
        frozen_environment_id: str | None,
    ) -> None:
        try:
            self._index.record_run(
                run_id=snapshot.run_id,
                frozen_environment_id=frozen_environment_id,
                trace_header_digest=_trace_header_digest(snapshot),
                trace_digest=snapshot.trace_digest,
            )
        except StudioIndexError as error:
            raise _index_runtime_error(error) from error

    def _prepare_run_trace(
        self,
        route: RunIndexRecord,
        plan: PreparedTraceAppend,
        *,
        operation: Literal["action", "verify"],
    ) -> RunTraceIntent:
        if (
            route.trace_digest is None
            or plan.run_id != route.run_id
            or plan.operation != operation
        ):
            raise RuntimeContractError(
                "the prepared trace append does not match its run mutation",
                code="internal",
            )
        return self._index.prepare_run_trace(
            run_id=route.run_id,
            operation=operation,
            expected_trace_digest=route.trace_digest,
            target_trace_digest=plan.target_trace_digest,
            base_journal_bytes=plan.base_journal_bytes,
            append_payload=plan.append_payload,
        )

    def _resolve_run_trace(
        self,
        intent: RunTraceIntent | None,
        snapshot: RunSnapshot,
        *,
        runtime: EnvironmentRuntime,
        route: RunIndexRecord,
    ) -> None:
        if (
            intent is None
            or route.trace_header_digest is None
            or route.trace_digest is None
            or snapshot.run_id != intent.run_id
            or snapshot.trace_digest != intent.target_trace_digest
        ):
            raise RuntimeContractError(
                "the completed trace append does not match its prepared intent",
                code="internal",
            )
        plan = PreparedTraceAppend(
            run_id=intent.run_id,
            operation=intent.operation,
            target_trace_digest=intent.target_trace_digest,
            base_journal_bytes=intent.base_journal_bytes,
            append_payload=intent.append_payload,
        )
        persisted = runtime.recover_prepared_append(
            plan,
            expected_trace_header_digest=route.trace_header_digest,
            expected_trace_digest=route.trace_digest,
        )
        self._index.resolve_run_trace_intent(
            intent,
            observed_trace_digest=persisted.trace_digest,
        )
        if persisted.trace_digest != intent.target_trace_digest:
            raise RuntimeContractError(
                "the prepared trace append was not fully persisted",
                code="internal",
            )


def _index_runtime_error(error: StudioIndexError) -> RuntimeContractError:
    code: RuntimeErrorCode
    if error.code == "invalid":
        code = "invalid"
    elif error.code == "conflict":
        code = "conflict"
    elif error.code == "not_found":
        code = "not_found"
    else:
        code = "internal"
    message = (
        "the durable Studio index could not complete the operation"
        if error.code == "storage"
        else str(error)
    )
    return RuntimeContractError(message, code=code)


def _validated_authoring_state(document: dict[str, object]) -> dict[str, object]:
    return EegAuthoringState.model_validate(document).model_dump(mode="json")


def _state_from_snapshot(snapshot: DraftSnapshot) -> EegAuthoringState:
    return EegAuthoringState.model_validate(snapshot.state).model_copy(deep=True)


def _runtime_for_bundle(
    bundle: EnvironmentBundle,
    *,
    trace_directory: Path,
) -> EnvironmentRuntime:
    return EnvironmentRuntime(
        EegEnvironmentModule(bundle.model_copy(deep=True)),
        trace_directory=trace_directory,
    )


def _bundle_digest(bundle: EnvironmentBundle) -> str:
    canonical = json.dumps(
        bundle.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _frozen_id(revision_digest: str) -> str:
    return f"frozen-{revision_digest.removeprefix('sha256:')[:24]}"


def _bundle_revision_matches_draft(bundle_revision: str, draft_revision: int) -> bool:
    family, separator, revision = bundle_revision.rpartition(".")
    return bool(family and separator and revision == str(draft_revision))


def _trace_header_digest(snapshot: RunSnapshot) -> str:
    return canonical_trace_header_digest(
        run_id=snapshot.run_id,
        lineage=snapshot.lineage,
        header=snapshot.trace_header,
    )


__all__ = [
    "AUTHORING_ASSISTANT",
    "ENVIRONMENT_AUTHOR",
    "SEEDED_POLICY_AGENT",
    "AuthoringAssistantIdentity",
    "AuthoringCommandOutcome",
    "FrozenEnvironment",
    "RoleBoundaryDescriptor",
    "ScienceStudio",
]
