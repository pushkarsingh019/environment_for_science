"""Thin local HTTP adapter for the Science Environment Studio services."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from environments.eeg.authoring import (
    EegApparatusCapability,
    EegAuthoringState,
    EegAuthoringValidationError,
    EegDescriptiveNote,
    EegProcedureConfiguration,
)
from environments.eeg.presentation import (
    EegOnsetRouteVisualization,
    EegPreflightVisualization,
)
from environments.mesoscope.presentation import MesoscopeHandoffVisualization
from studio.authoring import DraftRepositoryError, DraftSnapshot
from studio.runtime import (
    EnvironmentAction,
    PolicyAgentIdentity,
    ReplayReport,
    RunSnapshot,
    RuntimeContractError,
)
from studio.service import (
    SEEDED_POLICY_AGENT,
    AuthoringAssistantIdentity,
    FrozenEnvironment,
    RoleBoundaryDescriptor,
    ScienceStudio,
    SealedEnvironment,
)

PublicDraftOperation = Literal["seed", "edit", "undo", "redo", "restore_seed"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentValidationSummary(_StrictModel):
    status: Literal["valid"]
    summary: str
    checks: tuple[str, ...]


class ActionPresentation(_StrictModel):
    type: str
    title: str
    description: str
    input_schema: dict[str, object]
    group: Literal["inspect", "collect", "remediate", "decide"]
    changes_state: bool


class SeededScenarioSummary(_StrictModel):
    scenario_id: str
    label: str
    stage: str = Field(min_length=1)


class EnvironmentCatalogSummary(_StrictModel):
    environment_id: str
    environment_kind: Literal["eeg", "mesoscope"]
    name: str
    navigation_label: str
    navigation_summary: str
    source_kind: Literal["editable_draft", "sealed_seed"]


class EnvironmentSummary(_StrictModel):
    environment_id: str
    environment_kind: Literal["eeg", "mesoscope"]
    source_kind: Literal["editable_draft", "sealed_seed"]
    seeded_examples: tuple[SeededScenarioSummary, ...]
    name: str
    description: str
    simulation_label: str
    actions: tuple[ActionPresentation, ...]
    visualization: (
        EegOnsetRouteVisualization
        | EegPreflightVisualization
        | MesoscopeHandoffVisualization
    )
    validation: EnvironmentValidationSummary
    hidden_state_exposed: Literal[False]
    policy_agents: tuple[PolicyAgentIdentity, ...]


class DraftHistorySummary(_StrictModel):
    can_undo: bool
    can_redo: bool


class DraftActorSummary(_StrictModel):
    id: str
    name: str
    role: Literal["authoring_assistant", "environment_author", "system"]


class DraftChangeSummary(_StrictModel):
    operation: PublicDraftOperation
    summary: str
    actor: DraftActorSummary


class DraftSummary(_StrictModel):
    draft_id: str
    revision: int = Field(ge=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    environment_id: str
    title: str
    apparatus: EegApparatusCapability
    procedure: EegProcedureConfiguration
    notes: tuple[EegDescriptiveNote, ...]
    history: DraftHistorySummary
    last_change: DraftChangeSummary
    authoring_assistant: AuthoringAssistantIdentity


class FrozenEnvironmentSummary(_StrictModel):
    frozen_environment_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    draft_revision: int = Field(ge=1)
    procedure: EegProcedureConfiguration


class SealedEnvironmentSummary(_StrictModel):
    frozen_environment_id: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    source_kind: Literal["sealed_seed"]
    bundle_revision: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sealed_profile_id: str = Field(min_length=1)
    signed_plan_id: str = Field(min_length=1)


class StartRunRequest(_StrictModel):
    environment_id: str | None = Field(default=None, min_length=1)
    scenario_id: str
    policy_agent: str
    frozen_environment_id: str = Field(min_length=1)


class ActionRequest(_StrictModel):
    type: str = Field(min_length=1)
    input: dict[str, object]


class ExpectedRevisionRequest(_StrictModel):
    expected_revision: int = Field(ge=1)


class CommandRequest(ExpectedRevisionRequest):
    command: str = Field(min_length=1, max_length=240)

    @field_validator("command")
    @classmethod
    def validate_command(cls, command: str) -> str:
        if not command.strip():
            raise ValueError("command must contain visible text")
        return command


class StageNoteRequest(ExpectedRevisionRequest):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, filename: str) -> str:
        if (
            filename != filename.strip()
            or "/" in filename
            or "\\" in filename
            or not filename.casefold().endswith(".txt")
        ):
            raise ValueError("filename must be one local .txt filename")
        return filename

    @field_validator("content")
    @classmethod
    def validate_content(cls, content: str) -> str:
        if not content.strip() or "\x00" in content:
            raise ValueError("note must contain plain text")
        return content


class CommandResultSummary(_StrictModel):
    status: Literal["applied", "unsupported"]
    summary: str


class CommandResponse(_StrictModel):
    draft: DraftSummary
    result: CommandResultSummary


class ReplayResponse(_StrictModel):
    snapshot: RunSnapshot
    replay: ReplayReport


def create_app(
    console_dist: Path | None = None,
    artifact_root: Path | None = None,
) -> FastAPI:
    """Create a local application with persistent drafts and isolated runtimes."""
    resolved_artifact_root = artifact_root or (
        Path(__file__).resolve().parent.parent / "artifacts"
    )
    studio = ScienceStudio(resolved_artifact_root)
    studio_lock = RLock()
    bundle = studio.source_bundle

    app = FastAPI(
        title="Science Environment Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RuntimeContractError)
    async def runtime_contract_error(
        _request: Request,
        error: RuntimeContractError,
    ) -> JSONResponse:
        status_code = {
            "invalid": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "not_found": status.HTTP_404_NOT_FOUND,
            "conflict": status.HTTP_409_CONFLICT,
            "internal": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }[error.code]
        detail = (
            "The Environment Runtime could not complete the operation."
            if error.code == "internal"
            else str(error)
        )
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.exception_handler(DraftRepositoryError)
    async def draft_repository_error(
        _request: Request,
        error: DraftRepositoryError,
    ) -> JSONResponse:
        error_code = str(error.code)
        detail = (
            "The Environment draft could not be persisted."
            if error_code == "storage"
            else str(error)
        )
        status_codes: dict[str, int] = {
            "invalid": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "conflict": status.HTTP_409_CONFLICT,
            "forbidden": status.HTTP_403_FORBIDDEN,
            "storage": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }
        status_code = status_codes[error_code]
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.exception_handler(EegAuthoringValidationError)
    async def eeg_authoring_validation_error(
        _request: Request,
        error: EegAuthoringValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(error)},
        )

    @app.get("/api/environment", response_model=EnvironmentSummary)
    def get_environment() -> EnvironmentSummary:
        return _environment_summary(studio, bundle.bundle_id)

    @app.get(
        "/api/environments",
        response_model=tuple[EnvironmentCatalogSummary, ...],
    )
    def get_environment_catalog() -> tuple[EnvironmentCatalogSummary, ...]:
        return tuple(
            EnvironmentCatalogSummary.model_validate(entry.model_dump(mode="json"))
            for entry in studio.environment_catalog
        )

    @app.get(
        "/api/environments/{environment_id}",
        response_model=EnvironmentSummary,
    )
    def get_environment_by_id(environment_id: str) -> EnvironmentSummary:
        return _environment_summary(studio, environment_id)

    @app.post(
        "/api/environments/{environment_id}/freeze",
        response_model=SealedEnvironmentSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def freeze_seeded_environment(environment_id: str) -> SealedEnvironmentSummary:
        with studio_lock:
            return _sealed_environment_summary(
                studio.freeze_seeded_environment(environment_id)
            )

    @app.get("/api/draft", response_model=DraftSummary)
    def get_draft() -> DraftSummary:
        with studio_lock:
            return _draft_summary(studio.current_draft(), studio)

    @app.get(
        "/api/role-boundaries",
        response_model=tuple[RoleBoundaryDescriptor, ...],
    )
    def get_role_boundaries(
        environment_id: str | None = None,
    ) -> tuple[RoleBoundaryDescriptor, ...]:
        resolved_environment_id = environment_id or bundle.bundle_id
        return studio.role_boundaries_for(resolved_environment_id)

    @app.post("/api/draft/commands", response_model=CommandResponse)
    def apply_draft_command(request: CommandRequest) -> CommandResponse:
        with studio_lock:
            outcome = studio.apply_authoring_command(
                command=request.command,
                expected_revision=request.expected_revision,
            )
            return CommandResponse(
                draft=_draft_summary(outcome.draft, studio),
                result=CommandResultSummary(
                    status=outcome.result.status,
                    summary=outcome.result.summary,
                ),
            )

    @app.post("/api/draft/notes", response_model=DraftSummary)
    def stage_draft_note(request: StageNoteRequest) -> DraftSummary:
        with studio_lock:
            snapshot = studio.stage_note(
                filename=request.filename,
                content=request.content,
                expected_revision=request.expected_revision,
            )
            return _draft_summary(snapshot, studio)

    @app.post("/api/draft/undo", response_model=DraftSummary)
    def undo_draft(request: ExpectedRevisionRequest) -> DraftSummary:
        with studio_lock:
            return _draft_summary(
                studio.undo(expected_revision=request.expected_revision),
                studio,
            )

    @app.post("/api/draft/redo", response_model=DraftSummary)
    def redo_draft(request: ExpectedRevisionRequest) -> DraftSummary:
        with studio_lock:
            return _draft_summary(
                studio.redo(expected_revision=request.expected_revision),
                studio,
            )

    @app.post("/api/draft/restore", response_model=DraftSummary)
    def restore_draft(request: ExpectedRevisionRequest) -> DraftSummary:
        with studio_lock:
            return _draft_summary(
                studio.restore_seed(expected_revision=request.expected_revision),
                studio,
            )

    @app.post(
        "/api/draft/freeze",
        response_model=FrozenEnvironmentSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def freeze_draft(request: ExpectedRevisionRequest) -> FrozenEnvironmentSummary:
        with studio_lock:
            frozen = studio.freeze(expected_revision=request.expected_revision)
            return _frozen_environment_summary(frozen)

    @app.post(
        "/api/runs",
        response_model=RunSnapshot,
        status_code=status.HTTP_201_CREATED,
    )
    def start_run(request: StartRunRequest) -> RunSnapshot:
        if request.policy_agent != SEEDED_POLICY_AGENT.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown Policy agent identity.",
            )
        with studio_lock:
            return studio.start_run(
                scenario_id=request.scenario_id,
                policy_agent=SEEDED_POLICY_AGENT,
                frozen_environment_id=request.frozen_environment_id,
                environment_id=request.environment_id,
            )

    @app.get("/api/runs/{run_id}", response_model=RunSnapshot)
    def get_run(run_id: str) -> RunSnapshot:
        with studio_lock:
            return studio.current_run(run_id)

    @app.post("/api/runs/{run_id}/actions", response_model=RunSnapshot)
    def apply_action(run_id: str, request: ActionRequest) -> RunSnapshot:
        with studio_lock:
            return studio.apply_run_action(
                run_id,
                EnvironmentAction(type=request.type, arguments=request.input),
            )

    @app.post("/api/runs/{run_id}/verify", response_model=RunSnapshot)
    def verify_run(run_id: str) -> RunSnapshot:
        with studio_lock:
            return studio.verify_run(run_id)

    @app.post("/api/runs/{run_id}/reset", response_model=RunSnapshot)
    def reset_run(run_id: str) -> RunSnapshot:
        with studio_lock:
            return studio.reset_run(run_id)

    @app.post("/api/runs/{run_id}/replay", response_model=ReplayResponse)
    def replay_run(run_id: str) -> ReplayResponse:
        with studio_lock:
            snapshot, report = studio.replay_run(run_id)
            return ReplayResponse(snapshot=snapshot, replay=report)

    if console_dist is not None:
        app.mount(
            "/",
            StaticFiles(directory=str(console_dist), html=True),
            name="scientist-console",
        )

    return app


def _draft_summary(snapshot: DraftSnapshot, studio: ScienceStudio) -> DraftSummary:
    state = EegAuthoringState.model_validate(snapshot.state)
    source = studio.source_bundle
    actor = snapshot.last_change.actor
    public_role: Literal["authoring_assistant", "environment_author", "system"]
    if actor.role == "studio":
        public_role = "system"
    elif actor.role == "authoring_assistant":
        public_role = "authoring_assistant"
    elif actor.role == "environment_author":
        public_role = "environment_author"
    else:
        raise RuntimeError("a Policy agent was recorded in authoring activity")
    operation = _public_draft_operation(snapshot.last_change.operation)
    return DraftSummary(
        draft_id=snapshot.workspace_id,
        revision=snapshot.revision,
        revision_digest=snapshot.content_digest,
        environment_id=source.bundle_id,
        title=source.title,
        apparatus=state.apparatus,
        procedure=state.procedure,
        notes=state.notes,
        history=DraftHistorySummary(
            can_undo=snapshot.can_undo,
            can_redo=snapshot.can_redo,
        ),
        last_change=DraftChangeSummary(
            operation=operation,
            summary=snapshot.last_change.description,
            actor=DraftActorSummary(
                id=actor.id,
                name=actor.name,
                role=public_role,
            ),
        ),
        authoring_assistant=studio.authoring_assistant,
    )


def _environment_summary(
    studio: ScienceStudio,
    environment_id: str,
) -> EnvironmentSummary:
    bundle = studio.environment_bundle(environment_id)
    validation_bundle = studio.environment_runtime_validation_bundle(environment_id)
    entry = studio.environment_entry(environment_id)
    seeded_scenarios = studio.seeded_scenarios_for(environment_id)
    return EnvironmentSummary(
        environment_id=bundle.bundle_id,
        environment_kind=entry.environment_kind,
        source_kind=entry.source_kind,
        seeded_examples=tuple(
            SeededScenarioSummary(
                scenario_id=choice.scenario_id,
                label=choice.label,
                stage=choice.stage,
            )
            for choice in seeded_scenarios
        ),
        name=bundle.title,
        description=bundle.description or bundle.simulation_label,
        simulation_label=bundle.simulation_label,
        actions=tuple(
            ActionPresentation(
                type=action.type,
                title=action.title,
                description=action.description,
                input_schema=action.input_schema,
                group=action.presentation_group,
                changes_state=action.presentation_changes_state,
            )
            for action in validation_bundle.actions
        ),
        visualization=studio.environment_visualization(environment_id),
        validation=EnvironmentValidationSummary(
            status="valid",
            summary="Environment Bundle v1 validated",
            checks=(
                "Contract version supported",
                "Action and observation schemas validated",
                "Policy-visible observations separated from hidden scenario truth",
            ),
        ),
        hidden_state_exposed=False,
        policy_agents=(SEEDED_POLICY_AGENT,),
    )


def _frozen_environment_summary(
    frozen: FrozenEnvironment,
) -> FrozenEnvironmentSummary:
    return FrozenEnvironmentSummary(
        frozen_environment_id=frozen.frozen_environment_id,
        bundle_revision=frozen.bundle_revision,
        revision_digest=frozen.revision_digest,
        draft_revision=frozen.draft_revision,
        procedure=frozen.procedure.model_copy(deep=True),
    )


def _sealed_environment_summary(
    frozen: SealedEnvironment,
) -> SealedEnvironmentSummary:
    return SealedEnvironmentSummary(
        frozen_environment_id=frozen.frozen_environment_id,
        environment_id=frozen.environment_id,
        source_kind=frozen.source_kind,
        bundle_revision=frozen.bundle_revision,
        revision_digest=frozen.revision_digest,
        sealed_profile_id=frozen.sealed_profile_id,
        signed_plan_id=frozen.signed_plan_id,
    )


def _public_draft_operation(operation: str) -> PublicDraftOperation:
    if operation == "initialize":
        return "seed"
    if operation == "edit":
        return "edit"
    if operation == "undo":
        return "undo"
    if operation == "redo":
        return "redo"
    if operation == "restore_seed":
        return "restore_seed"
    raise RuntimeError("draft activity used an unknown operation")
