"""Separate mesoscope platform-generality evidence over the shared evaluation seams."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from studio.policy_evaluation.compiler import VerifiersCompilation, compile_verifiers_v1
from studio.registry import EnvironmentRegistry
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    RunSnapshot,
    RuntimeContractError,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


ReplayId = Literal["valid-handoff", "quarantine-handoff"]


class MesoscopePortabilityResult(_FrozenModel):
    """One seeded protocol fixture with a canonical Runtime replay identity."""

    replay_id: ReplayId
    scenario_id: str = Field(min_length=1)
    fixture: Literal[True] = True
    terminal_summary: str = Field(min_length=1)
    terminal_disposition: str = Field(min_length=1)
    runtime_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class MesoscopePortabilityReport(_FrozenModel):
    """Compiler and Runtime evidence kept outside the EEG training claim."""

    report_revision: Literal["science-mesoscope-portability-report/1"]
    track: Literal["platform_generality"]
    environment_id: Literal["mesoscope-four-region-handoff"]
    training_claim_included: Literal[False]
    fixture_notice: str = Field(min_length=1)
    compilation: VerifiersCompilation
    results: tuple[MesoscopePortabilityResult, ...] = Field(min_length=2, max_length=2)


class MesoscopePortabilityReplay(_FrozenModel):
    """Read-only deterministic replay of one seeded portability result."""

    replay_id: ReplayId
    source_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    replay_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trace_matches: bool
    source_result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    replay_result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_matches: bool
    snapshot: RunSnapshot


_CASES: dict[ReplayId, tuple[str, tuple[str, ...]]] = {
    "valid-handoff": (
        "mesoscope-demo-001",
        (
            "inspect_sealed_handoff",
            "run_mock_acquisition",
            "validate_mock_package",
            "accept_mock_package",
        ),
    ),
    "quarantine-handoff": (
        "mesoscope-demo-002",
        (
            "inspect_sealed_handoff",
            "run_mock_acquisition",
            "validate_mock_package",
            "quarantine_mock_package",
        ),
    ),
}
_POLICY = PolicyAgentIdentity(
    id="local-gemma-portability-protocol-fixture",
    name="Local Gemma protocol fixture",
)


class MesoscopePortabilityService:
    """Compile and replay mesoscope through product-owned generic interfaces only."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._registry = EnvironmentRegistry.from_seeded_environments()
        self._bundle = self._registry.bundle("mesoscope-four-region-handoff")
        reviewed_bundle = self._registry.module_for_bundle(
            self._bundle.model_copy(deep=True)
        ).runtime_validation_bundle
        self._compilation = compile_verifiers_v1(
            reviewed_bundle,
            self._artifact_root / "mesoscope-verifiers-v1",
        )

    def report(self) -> MesoscopePortabilityReport:
        results = tuple(
            self._result(replay_id, scenario_id, actions)
            for replay_id, (scenario_id, actions) in _CASES.items()
        )
        return MesoscopePortabilityReport(
            report_revision="science-mesoscope-portability-report/1",
            track="platform_generality",
            environment_id="mesoscope-four-region-handoff",
            training_claim_included=False,
            fixture_notice=(
                "Seeded offline protocol fixtures; these are not hosted-model results "
                "or evidence of cross-Apparatus training."
            ),
            compilation=self._compilation.model_copy(deep=True),
            results=results,
        )

    def replay(self, replay_id: str) -> MesoscopePortabilityReplay:
        if replay_id not in _CASES:
            raise RuntimeContractError(
                "mesoscope portability replay was not found",
                code="not_found",
            )
        resolved_replay_id = cast(ReplayId, replay_id)
        scenario_id, actions = _CASES[resolved_replay_id]
        runtime, source = self._execute(scenario_id, actions)
        replay = runtime.replay(source.run_id)
        snapshot = runtime.current(replay.replay_run_id)
        return MesoscopePortabilityReplay(
            replay_id=resolved_replay_id,
            source_trace_digest=replay.source_trace_digest,
            replay_trace_digest=replay.replay_trace_digest,
            trace_matches=replay.trace_matches,
            source_result_digest=replay.source_result_digest,
            replay_result_digest=replay.replay_result_digest,
            result_matches=replay.result_matches,
            snapshot=snapshot,
        )

    def _result(
        self,
        replay_id: ReplayId,
        scenario_id: str,
        actions: tuple[str, ...],
    ) -> MesoscopePortabilityResult:
        _runtime, completed = self._execute(scenario_id, actions)
        verifier = completed.verifier_result
        if verifier is None or completed.result_digest is None or not verifier.passed:
            raise RuntimeContractError(
                "mesoscope portability fixture did not produce a verified result",
                code="internal",
            )
        return MesoscopePortabilityResult(
            replay_id=replay_id,
            scenario_id=scenario_id,
            terminal_summary=verifier.summary,
            terminal_disposition=verifier.terminal_disposition,
            runtime_trace_digest=completed.trace_digest,
            result_digest=completed.result_digest,
        )

    def _execute(
        self,
        scenario_id: str,
        actions: tuple[str, ...],
    ) -> tuple[EnvironmentRuntime, RunSnapshot]:
        runtime = EnvironmentRuntime(
            self._registry.module_for_bundle(self._bundle.model_copy(deep=True))
        )
        current = runtime.start(scenario_id, _POLICY)
        for action in actions:
            current = runtime.apply_action(
                current.run_id,
                EnvironmentAction(type=action, arguments={}),
            )
        return runtime, runtime.verify(current.run_id)


__all__ = [
    "MesoscopePortabilityReplay",
    "MesoscopePortabilityReport",
    "MesoscopePortabilityResult",
    "MesoscopePortabilityService",
]
