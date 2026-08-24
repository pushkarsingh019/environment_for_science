"""Thin local HTTP adapter for the Science Environment Studio services."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from environments.eeg._curriculum_contract import CANONICAL_OBJECTIVE
from environments.eeg.authoring import (
    EegApparatusCapability,
    EegAuthoringState,
    EegAuthoringValidationError,
    EegDescriptiveNote,
    EegProcedureConfiguration,
)
from environments.eeg.curriculum import load_development_scenario_set
from environments.eeg.presentation import (
    EegOnsetRouteVisualization,
    EegPreflightVisualization,
)
from environments.mesoscope.presentation import MesoscopeHandoffVisualization
from studio.authoring import DraftRepositoryError, DraftSnapshot
from studio.bundle import EnvironmentBundle
from studio.curriculum_jobs import (
    CurriculumJobError,
    CurriculumTrainingJob,
    CurriculumTrainingJobRepository,
)
from studio.model_comparison import (
    ComparisonIndexError,
    ComparisonReplay,
    FixtureState,
    ModelComparisonRepository,
    ModelComparisonResult,
    ModelRole,
)
from studio.policy_evaluation.coordinator import (
    EvaluationCoordinator,
    EvaluationCoordinatorError,
    EvaluationReplay,
    EvaluationRunner,
    EvaluationRunnerFactory,
    EvaluationSnapshot,
    EvaluationSummary,
)
from studio.policy_evaluation.gemini_interactions import (
    GEMINI_INTERACTIONS_ADAPTER_REVISION,
    GEMINI_INTERACTIONS_MODEL,
    GEMINI_INTERACTIONS_SAMPLING,
    GeminiInteractionsProvider,
    gemini_credential_ready,
)
from studio.policy_evaluation.local_gemma import LocalGemmaChatProvider
from studio.policy_evaluation.mesoscope_portability import (
    MesoscopePortabilityReplay,
    MesoscopePortabilityReport,
    MesoscopePortabilityService,
)
from studio.policy_evaluation.model_runner import (
    CanonicalModelRunner,
    EvaluationAttempt,
    ModelIdentity,
)
from studio.policy_evaluation.openai_responses import (
    OPENAI_RESPONSES_ADAPTER_REVISION,
    OPENAI_RESPONSES_MODEL,
    OPENAI_RESPONSES_SAMPLING,
    OpenAIResponsesProvider,
    openai_credential_ready,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
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
from studio.training_jobs import (
    TrainingAcceptanceJob,
    TrainingAcceptanceJobService,
    TrainingJobError,
)

PublicDraftOperation = Literal["seed", "edit", "undo", "redo", "restore_seed"]
_EVALUATION_MAX_TURNS = 64
_EVALUATION_MAX_TOOL_CALLS = 64
_LOCAL_SESSION_COOKIE = "science_studio_session"
_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
_TRUSTED_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_IN_PROCESS_TEST_HOST = "testserver"
_IN_PROCESS_TEST_CLIENT = "testclient"


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
        EegOnsetRouteVisualization | EegPreflightVisualization | MesoscopeHandoffVisualization
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


class DemoResetSummary(_StrictModel):
    reset_version: Literal["science-demo-reset/1"]
    status: Literal["reset"]
    draft_revision: int = Field(ge=1)
    draft_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    comparison_fixture_state: Literal["successful"]
    seeded_scenarios_restored: Literal[True]
    immutable_training_jobs_preserved: int = Field(ge=0)
    immutable_real_comparisons_preserved: int = Field(ge=0)
    immutable_artifacts_deleted: Literal[0]
    summary: str = Field(min_length=1)


class OpenAIProviderReadiness(_StrictModel):
    provider: Literal["openai"]
    route: Literal["responses"]
    requested_model: Literal["gpt-5.6-sol"]
    adapter_revision: Literal["openai-responses/1"]
    credential_configured: bool
    status: Literal["configured", "missing_credential"]


class GeminiProviderReadiness(_StrictModel):
    provider: Literal["gemini"]
    route: Literal["interactions"]
    requested_model: Literal["gemini-3.7-flash"]
    adapter_revision: Literal["gemini-interactions/1"]
    credential_configured: bool
    status: Literal["configured", "missing_credential"]


class ProviderReadinessSummary(_StrictModel):
    openai: OpenAIProviderReadiness
    gemini: GeminiProviderReadiness


class LaunchEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: Literal["base-gemma-development-v1"]


def _production_evaluation_runner(bundle: EnvironmentBundle) -> EvaluationRunner:
    """Compose local inference without putting its private route in app state DTOs."""
    return CanonicalModelRunner(
        bundle=bundle,
        runtime_bridge=EvaluationRuntimeBridge(bundle),
        provider=LocalGemmaChatProvider.from_environment(os.environ),
        max_turns=_EVALUATION_MAX_TURNS,
        max_tool_calls=_EVALUATION_MAX_TOOL_CALLS,
    )


def _execute_evaluation_safely(
    coordinator: EvaluationCoordinator,
    evaluation_id: str,
) -> None:
    """Leave durable interrupted progress instead of leaking a background failure."""
    with suppress(EvaluationCoordinatorError):
        coordinator.execute(evaluation_id)


def create_app(
    console_dist: Path | None = None,
    artifact_root: Path | None = None,
    evaluation_runner_factory: EvaluationRunnerFactory | None = None,
) -> FastAPI:
    """Create a local application with persistent drafts and isolated runtimes."""
    resolved_artifact_root = artifact_root or (Path(__file__).resolve().parent.parent / "artifacts")
    studio = ScienceStudio(resolved_artifact_root)
    evaluation_coordinator = EvaluationCoordinator(
        artifact_root=resolved_artifact_root / "evaluations",
        runner_factory=(
            evaluation_runner_factory
            if evaluation_runner_factory is not None
            else _production_evaluation_runner
        ),
    )
    mesoscope_portability = MesoscopePortabilityService(
        resolved_artifact_root / "platform-evidence"
    )
    training_jobs = TrainingAcceptanceJobService(
        resolved_artifact_root / "training"
    )
    curriculum_jobs = CurriculumTrainingJobRepository(
        resolved_artifact_root / "training/curriculum"
    )
    model_comparisons = ModelComparisonRepository(
        resolved_artifact_root / "comparisons"
    )
    studio_lock = RLock()
    bundle = studio.source_bundle

    app = FastAPI(
        title="Science Environment Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    local_session_token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_request_boundary(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        host_values = request.headers.getlist("host")
        client_host = request.client.host if request.client is not None else None
        if len(host_values) != 1 or not _trusted_local_host_header(
            host_values[0],
            client_host=client_host,
        ):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "The local request host is invalid."},
            )

        is_api = request.url.path == "/api" or request.url.path.startswith("/api/")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        normalized_fetch_site = fetch_site.casefold() if fetch_site is not None else None
        if is_api and (
            (origin is not None and not _same_local_origin(origin, host_values[0]))
            or normalized_fetch_site in {"cross-site", "same-site"}
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "The local request origin is invalid."},
            )

        browser_mutation = (
            is_api
            and request.method not in _SAFE_HTTP_METHODS
            and (origin is not None or normalized_fetch_site is not None)
        )
        if browser_mutation and (
            normalized_fetch_site not in {None, "same-origin"}
            or not secrets.compare_digest(
                request.cookies.get(_LOCAL_SESSION_COOKIE, ""),
                local_session_token,
            )
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "The local browser session is invalid."},
            )

        response = await call_next(request)
        if is_api:
            response.headers.setdefault("Cache-Control", "no-store")
            if (
                request.method in _SAFE_HTTP_METHODS
                and not secrets.compare_digest(
                    request.cookies.get(_LOCAL_SESSION_COOKIE, ""),
                    local_session_token,
                )
            ):
                response.set_cookie(
                    key=_LOCAL_SESSION_COOKIE,
                    value=local_session_token,
                    httponly=True,
                    samesite="strict",
                    secure=False,
                    path="/",
                )
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        if request.url.path == "/api/evaluations":
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"detail": "The evaluation request is invalid."},
            )
        return await request_validation_exception_handler(request, error)

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

    @app.exception_handler(CurriculumJobError)
    async def curriculum_job_error(
        _request: Request,
        error: CurriculumJobError,
    ) -> JSONResponse:
        status_code = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "conflict": status.HTTP_409_CONFLICT,
            "storage": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }[error.code]
        detail = (
            "The curriculum training index could not complete the operation."
            if error.code == "storage"
            else str(error)
        )
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.exception_handler(ComparisonIndexError)
    async def comparison_index_error(
        _request: Request,
        error: ComparisonIndexError,
    ) -> JSONResponse:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code == "not_found"
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        detail = (
            str(error)
            if error.code == "not_found"
            else "The model comparison index could not complete the operation."
        )
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.exception_handler(TrainingJobError)
    async def training_job_error(
        _request: Request,
        error: TrainingJobError,
    ) -> JSONResponse:
        status_code = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "conflict": status.HTTP_409_CONFLICT,
            "storage": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }[error.code]
        detail = (
            "The training acceptance index could not complete the operation."
            if error.code == "storage"
            else str(error)
        )
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

    @app.exception_handler(EvaluationCoordinatorError)
    async def evaluation_coordinator_error(
        _request: Request,
        error: EvaluationCoordinatorError,
    ) -> JSONResponse:
        status_code = {
            "invalid": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "not_found": status.HTTP_404_NOT_FOUND,
            "conflict": status.HTTP_409_CONFLICT,
            "internal": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }[error.code]
        detail = (
            "The local evaluation could not complete the operation."
            if error.code == "internal"
            else str(error)
        )
        return JSONResponse(status_code=status_code, content={"detail": detail})

    @app.get("/api/environment", response_model=EnvironmentSummary)
    def get_environment() -> EnvironmentSummary:
        return _environment_summary(studio, bundle.bundle_id)

    @app.post(
        "/api/evaluations",
        response_model=EvaluationSnapshot,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def launch_evaluation(
        request: LaunchEvaluationRequest,
        background_tasks: BackgroundTasks,
    ) -> EvaluationSnapshot:
        snapshot = evaluation_coordinator.launch(profile=request.profile)
        background_tasks.add_task(
            _execute_evaluation_safely,
            evaluation_coordinator,
            snapshot.evaluation_id,
        )
        return snapshot

    @app.get(
        "/api/evaluations",
        response_model=tuple[EvaluationSummary, ...],
    )
    def list_evaluations() -> tuple[EvaluationSummary, ...]:
        return evaluation_coordinator.list()

    @app.get(
        "/api/evaluations/{evaluation_id}",
        response_model=EvaluationSnapshot,
    )
    def load_evaluation(evaluation_id: str) -> EvaluationSnapshot:
        return evaluation_coordinator.load(evaluation_id)

    @app.post(
        "/api/evaluations/{evaluation_id}/resume",
        response_model=EvaluationSnapshot,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def resume_evaluation(
        evaluation_id: str,
        background_tasks: BackgroundTasks,
    ) -> EvaluationSnapshot:
        snapshot = evaluation_coordinator.load(evaluation_id)
        if snapshot.status in ("queued", "interrupted"):
            background_tasks.add_task(
                _execute_evaluation_safely,
                evaluation_coordinator,
                snapshot.evaluation_id,
            )
        return snapshot

    @app.post(
        "/api/evaluations/{evaluation_id}/attempts/{attempt_id}/replay",
        response_model=EvaluationReplay,
    )
    def replay_evaluation_attempt(
        evaluation_id: str,
        attempt_id: str,
    ) -> EvaluationReplay:
        return evaluation_coordinator.replay(evaluation_id, attempt_id)

    @app.post(
        "/api/demo/reset",
        response_model=DemoResetSummary,
    )
    def reset_demo() -> DemoResetSummary:
        with studio_lock:
            current = studio.current_draft()
            draft = studio.restore_seed(expected_revision=current.revision)
            model_comparisons.reset_demo()
            jobs_preserved = training_jobs.reset_demo() + curriculum_jobs.reset_demo()
            real_comparisons_preserved = model_comparisons.real_result_count()
        return DemoResetSummary(
            reset_version="science-demo-reset/1",
            status="reset",
            draft_revision=draft.revision,
            draft_digest=draft.content_digest,
            comparison_fixture_state="successful",
            seeded_scenarios_restored=True,
            immutable_training_jobs_preserved=jobs_preserved,
            immutable_real_comparisons_preserved=real_comparisons_preserved,
            immutable_artifacts_deleted=0,
            summary=(
                "Seeded draft, scenarios, and offline demonstration state were "
                "restored. Immutable real artifacts were preserved."
            ),
        )

    @app.get(
        "/api/model-comparison",
        response_model=ModelComparisonResult,
    )
    def current_model_comparison() -> ModelComparisonResult:
        return model_comparisons.current()

    @app.post(
        "/api/model-comparison/fixtures/{fixture_state}",
        response_model=ModelComparisonResult,
    )
    def select_model_comparison_fixture(
        fixture_state: FixtureState,
    ) -> ModelComparisonResult:
        return model_comparisons.select_fixture(fixture_state)

    @app.post(
        "/api/model-comparison/reset",
        response_model=ModelComparisonResult,
    )
    def reset_model_comparison_demo() -> ModelComparisonResult:
        return model_comparisons.reset_demo()

    @app.get(
        "/api/model-comparison/replays/{model_role}/{scenario_id}",
        response_model=ComparisonReplay,
    )
    def replay_model_comparison(
        model_role: ModelRole,
        scenario_id: str,
    ) -> ComparisonReplay:
        return model_comparisons.replay(model_role, scenario_id)

    @app.post(
        "/api/training/curriculum-jobs",
        response_model=CurriculumTrainingJob,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def launch_curriculum_training_job() -> CurriculumTrainingJob:
        return curriculum_jobs.launch()

    @app.get(
        "/api/training/curriculum-jobs",
        response_model=tuple[CurriculumTrainingJob, ...],
    )
    def list_curriculum_training_jobs() -> tuple[CurriculumTrainingJob, ...]:
        return curriculum_jobs.list()

    @app.post(
        "/api/training/curriculum-jobs/{job_id}/begin",
        response_model=CurriculumTrainingJob,
    )
    def begin_curriculum_training_job(job_id: str) -> CurriculumTrainingJob:
        return curriculum_jobs.begin(job_id)

    @app.post(
        "/api/training/acceptance-jobs",
        response_model=TrainingAcceptanceJob,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def launch_training_acceptance_job() -> TrainingAcceptanceJob:
        return training_jobs.launch()

    @app.get(
        "/api/training/acceptance-jobs",
        response_model=tuple[TrainingAcceptanceJob, ...],
    )
    def list_training_acceptance_jobs() -> tuple[TrainingAcceptanceJob, ...]:
        return training_jobs.list()

    @app.get(
        "/api/training/acceptance-jobs/{job_id}",
        response_model=TrainingAcceptanceJob,
    )
    def load_training_acceptance_job(job_id: str) -> TrainingAcceptanceJob:
        return training_jobs.load(job_id)

    @app.post(
        "/api/training/acceptance-jobs/{job_id}/begin",
        response_model=TrainingAcceptanceJob,
    )
    def begin_training_acceptance_job(job_id: str) -> TrainingAcceptanceJob:
        return training_jobs.begin(job_id)

    @app.post(
        "/api/training/acceptance-jobs/{job_id}/verify",
        response_model=TrainingAcceptanceJob,
    )
    def verify_training_acceptance_job(job_id: str) -> TrainingAcceptanceJob:
        return training_jobs.verify(job_id)

    @app.post(
        "/api/training/acceptance-jobs/{job_id}/retry",
        response_model=TrainingAcceptanceJob,
    )
    def retry_training_acceptance_job(job_id: str) -> TrainingAcceptanceJob:
        return training_jobs.retry(job_id)

    @app.post(
        "/api/hosted-smokes/gemini",
        response_model=EvaluationAttempt,
    )
    def run_gemini_smoke() -> EvaluationAttempt:
        if not gemini_credential_ready(os.environ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Gemini credential is not configured.",
            )
        scenario_set = load_development_scenario_set()
        smoke_bundle = scenario_set.environment_bundle
        runner = CanonicalModelRunner(
            bundle=smoke_bundle,
            runtime_bridge=EvaluationRuntimeBridge(smoke_bundle),
            provider=GeminiInteractionsProvider.from_environment(os.environ),
            max_turns=_EVALUATION_MAX_TURNS,
            max_tool_calls=_EVALUATION_MAX_TOOL_CALLS,
            sampling=GEMINI_INTERACTIONS_SAMPLING,
            profile="hosted-reference-smoke-v1",
        )
        return runner.run(
            scenario_id=scenario_set.scenario_ids[0],
            objective=CANONICAL_OBJECTIVE,
            model=ModelIdentity(
                provider="gemini-interactions",
                requested_model=GEMINI_INTERACTIONS_MODEL,
                adapter_revision=GEMINI_INTERACTIONS_ADAPTER_REVISION,
            ),
        )

    @app.post(
        "/api/hosted-smokes/openai",
        response_model=EvaluationAttempt,
    )
    def run_openai_smoke() -> EvaluationAttempt:
        if not openai_credential_ready(os.environ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The OpenAI credential is not configured.",
            )
        scenario_set = load_development_scenario_set()
        smoke_bundle = scenario_set.environment_bundle
        runner = CanonicalModelRunner(
            bundle=smoke_bundle,
            runtime_bridge=EvaluationRuntimeBridge(smoke_bundle),
            provider=OpenAIResponsesProvider.from_environment(os.environ),
            max_turns=_EVALUATION_MAX_TURNS,
            max_tool_calls=_EVALUATION_MAX_TOOL_CALLS,
            sampling=OPENAI_RESPONSES_SAMPLING,
            profile="hosted-reference-smoke-v1",
        )
        return runner.run(
            scenario_id=scenario_set.scenario_ids[0],
            objective=CANONICAL_OBJECTIVE,
            model=ModelIdentity(
                provider="openai-responses",
                requested_model=OPENAI_RESPONSES_MODEL,
                adapter_revision=OPENAI_RESPONSES_ADAPTER_REVISION,
            ),
        )

    @app.get(
        "/api/provider-readiness",
        response_model=ProviderReadinessSummary,
    )
    def get_provider_readiness() -> ProviderReadinessSummary:
        configured = openai_credential_ready(os.environ)
        gemini_configured = gemini_credential_ready(os.environ)
        return ProviderReadinessSummary(
            openai=OpenAIProviderReadiness(
                provider="openai",
                route="responses",
                requested_model=OPENAI_RESPONSES_MODEL,
                adapter_revision=OPENAI_RESPONSES_ADAPTER_REVISION,
                credential_configured=configured,
                status="configured" if configured else "missing_credential",
            ),
            gemini=GeminiProviderReadiness(
                provider="gemini",
                route="interactions",
                requested_model=GEMINI_INTERACTIONS_MODEL,
                adapter_revision=GEMINI_INTERACTIONS_ADAPTER_REVISION,
                credential_configured=gemini_configured,
                status=(
                    "configured" if gemini_configured else "missing_credential"
                ),
            ),
        )

    @app.get(
        "/api/platform-evidence/mesoscope",
        response_model=MesoscopePortabilityReport,
    )
    def get_mesoscope_portability_report() -> MesoscopePortabilityReport:
        return mesoscope_portability.report()

    @app.post(
        "/api/platform-evidence/mesoscope/replays/{replay_id}",
        response_model=MesoscopePortabilityReplay,
    )
    def replay_mesoscope_portability_result(
        replay_id: str,
    ) -> MesoscopePortabilityReplay:
        return mesoscope_portability.replay(replay_id)

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
            return _sealed_environment_summary(studio.freeze_seeded_environment(environment_id))

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


def _trusted_local_host_header(value: str, *, client_host: str | None) -> bool:
    if not value or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname.casefold() if parsed.hostname is not None else None
    trusted_in_process_test = (
        hostname == _IN_PROCESS_TEST_HOST and client_host == _IN_PROCESS_TEST_CLIENT
    )
    return bool(
        hostname is not None
        and (hostname in _TRUSTED_LOCAL_HOSTS or trusted_in_process_test)
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )


def _same_local_origin(origin: str, host: str) -> bool:
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.netloc.casefold() == host.casefold()
        and parsed.hostname is not None
        and parsed.hostname.casefold() in _TRUSTED_LOCAL_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )


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
