"""Thin local HTTP adapter for the product-owned Environment Runtime."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from environments.eeg.presentation import EegOnsetRouteVisualization
from environments.eeg.runtime import EegMarkerRecoveryModule
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    ReplayReport,
    RunSnapshot,
    RuntimeContractError,
)


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


class EnvironmentSummary(_StrictModel):
    environment_id: str
    scenario_id: str
    name: str
    description: str
    simulation_label: str
    actions: tuple[ActionPresentation, ...]
    visualization: EegOnsetRouteVisualization
    validation: EnvironmentValidationSummary
    hidden_state_exposed: Literal[False]
    policy_agents: tuple[PolicyAgentIdentity, ...]


class StartRunRequest(_StrictModel):
    scenario_id: str
    policy_agent: str


class ActionRequest(_StrictModel):
    type: str = Field(min_length=1)
    input: dict[str, object]


class ReplayResponse(_StrictModel):
    snapshot: RunSnapshot
    replay: ReplayReport


_SEEDED_POLICY_AGENT = PolicyAgentIdentity(
    id="seeded-policy-agent",
    name="Seeded recovery Policy agent",
)


def create_app(
    console_dist: Path | None = None,
    artifact_root: Path | None = None,
) -> FastAPI:
    """Create an isolated local application with a fresh seeded Runtime."""
    environment_module = EegMarkerRecoveryModule.from_seed()
    resolved_artifact_root = artifact_root or (
        Path(__file__).resolve().parent.parent / "artifacts"
    )
    runtime = EnvironmentRuntime(
        environment_module,
        trace_directory=resolved_artifact_root / "traces",
    )
    runtime_lock = RLock()
    bundle = environment_module.bundle
    scenario_id = bundle.scenarios[0].id

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

    @app.get("/api/environment", response_model=EnvironmentSummary)
    def get_environment() -> EnvironmentSummary:
        return EnvironmentSummary(
            environment_id=bundle.bundle_id,
            scenario_id=scenario_id,
            name=bundle.title,
            description=bundle.description or bundle.simulation_label,
            simulation_label=bundle.simulation_label,
            actions=tuple(
                ActionPresentation(
                    type=action.type,
                    title=action.title,
                    description=action.description,
                )
                for action in bundle.actions
            ),
            visualization=environment_module.visualization,
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
            policy_agents=(_SEEDED_POLICY_AGENT,),
        )

    @app.post(
        "/api/runs",
        response_model=RunSnapshot,
        status_code=status.HTTP_201_CREATED,
    )
    def start_run(request: StartRunRequest) -> RunSnapshot:
        if request.policy_agent != _SEEDED_POLICY_AGENT.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown Policy agent identity.",
            )
        with runtime_lock:
            return runtime.start(
                scenario_id=request.scenario_id,
                policy_agent=_SEEDED_POLICY_AGENT,
            )

    @app.get("/api/runs/{run_id}", response_model=RunSnapshot)
    def get_run(run_id: str) -> RunSnapshot:
        with runtime_lock:
            return runtime.current(run_id)

    @app.post("/api/runs/{run_id}/actions", response_model=RunSnapshot)
    def apply_action(run_id: str, request: ActionRequest) -> RunSnapshot:
        with runtime_lock:
            return runtime.apply_action(
                run_id,
                EnvironmentAction(type=request.type, arguments=request.input),
            )

    @app.post("/api/runs/{run_id}/verify", response_model=RunSnapshot)
    def verify_run(run_id: str) -> RunSnapshot:
        with runtime_lock:
            return runtime.verify(run_id)

    @app.post("/api/runs/{run_id}/reset", response_model=RunSnapshot)
    def reset_run(run_id: str) -> RunSnapshot:
        with runtime_lock:
            return runtime.reset(run_id)

    @app.post("/api/runs/{run_id}/replay", response_model=ReplayResponse)
    def replay_run(run_id: str) -> ReplayResponse:
        with runtime_lock:
            report = runtime.replay(run_id)
            return ReplayResponse(
                snapshot=runtime.current(report.replay_run_id),
                replay=report,
            )

    if console_dist is not None:
        app.mount(
            "/",
            StaticFiles(directory=str(console_dist), html=True),
            name="scientist-console",
        )

    return app


app = create_app()
