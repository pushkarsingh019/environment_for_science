"""Ticket 07 public seams for compiler and mesoscope evaluation portability."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from environments.eeg.curriculum import load_development_scenario_set
from studio.application import create_app
from studio.policy_evaluation.compiler import compile_verifiers_v1
from studio.policy_evaluation.mesoscope_portability import MesoscopePortabilityService
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    BASE_GEMMA_MODEL,
    CanonicalModelRunner,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from studio.registry import EnvironmentRegistry
from tests.evaluation.attested_provider_support import SignedLocalGemmaTestProvider


class _MesoscopePolicy(SignedLocalGemmaTestProvider):
    def __init__(self, actions: Sequence[str]) -> None:
        self._actions = iter(actions)

    def complete(self, request: ModelRequest) -> ModelResponse:
        action = next(self._actions)
        return ModelResponse(
            response_id=f"mesoscope-response-{request.turn}",
            returned_model=BASE_GEMMA_MODEL,
            message=ModelMessage.assistant(
                f"Use the declared mock action {action}.",
                tool_calls=(
                    ModelToolCall(
                        call_id=f"mesoscope-call-{request.turn}",
                        name=action,
                        arguments={},
                    ),
                ),
            ),
        )


def test_eeg_and_mesoscope_compile_through_the_same_public_interface(
    tmp_path: Path,
) -> None:
    registry = EnvironmentRegistry.from_seeded_environments()
    bundles = (
        load_development_scenario_set().environment_bundle,
        registry.bundle("mesoscope-four-region-handoff"),
    )

    receipts = tuple(
        compile_verifiers_v1(bundle, tmp_path / bundle.bundle_id)
        for bundle in bundles
    )

    assert {receipt.bundle_id for receipt in receipts} == {
        "eeg-curriculum",
        "mesoscope-four-region-handoff",
    }
    assert {receipt.compilation_version for receipt in receipts} == {
        "science-environment-verifiers-v1/1"
    }
    mesoscope_root = tmp_path / "mesoscope-four-region-handoff"
    catalog = json.loads((mesoscope_root / "taskset/task-catalog.json").read_text())
    assert {action["name"] for action in catalog["actions"]} == {
        action.type for action in bundles[1].actions
    }
    generated = "\n".join(
        path.read_text(errors="replace")
        for path in mesoscope_root.rglob("*")
        if path.is_file()
    ).casefold()
    for forbidden in (
        "laser_power",
        "detector_gain",
        "alignment_control",
        "motion_control",
        "calibration_control",
    ):
        assert forbidden not in generated


def test_canonical_local_gemma_runner_completes_valid_and_quarantine_handoffs() -> None:
    bundle = EnvironmentRegistry.from_seeded_environments().bundle(
        "mesoscope-four-region-handoff"
    )
    model = ModelIdentity(
        provider="local-openai-compatible",
        requested_model=BASE_GEMMA_MODEL,
        adapter_revision=BASE_GEMMA_ADAPTER_REVISION,
    )
    objective = "Inspect and safely disposition only the sealed synthetic package."
    cases = (
        (
            "mesoscope-demo-001",
            (
                "inspect_sealed_handoff",
                "run_mock_acquisition",
                "validate_mock_package",
                "accept_mock_package",
            ),
            "MOCK PACKAGE VERIFIED",
        ),
        (
            "mesoscope-demo-002",
            (
                "inspect_sealed_handoff",
                "run_mock_acquisition",
                "validate_mock_package",
                "quarantine_mock_package",
            ),
            "Synthetic invalid package was safely quarantined.",
        ),
    )

    for scenario_id, actions, expected_summary in cases:
        attempt = CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_MesoscopePolicy(actions),
            max_turns=8,
            max_tool_calls=8,
        ).run(scenario_id=scenario_id, objective=objective, model=model)

        assert attempt.infrastructure_error is None
        assert attempt.completed_run is not None
        assert attempt.completed_run.verifier_result is not None
        assert attempt.completed_run.verifier_result.passed is True
        assert attempt.completed_run.verifier_result.summary == expected_summary
        assert [action.type for action in attempt.trace.accepted_actions] == list(actions)


def test_mesoscope_portability_report_is_separate_and_every_result_replays(
    tmp_path: Path,
) -> None:
    service = MesoscopePortabilityService(tmp_path)

    report = service.report()

    assert report.track == "platform_generality"
    assert report.training_claim_included is False
    assert report.environment_id == "mesoscope-four-region-handoff"
    assert report.compilation.bundle_id == report.environment_id
    assert {result.terminal_summary for result in report.results} == {
        "MOCK PACKAGE VERIFIED",
        "Synthetic invalid package was safely quarantined.",
    }
    for result in report.results:
        replay = service.replay(result.replay_id)
        assert replay.source_trace_digest == result.runtime_trace_digest
        assert replay.trace_matches is True
        assert replay.result_matches is True
        assert replay.snapshot.verifier_result is not None
        assert replay.snapshot.verifier_result.summary == result.terminal_summary


def test_console_api_exposes_separate_mesoscope_report_and_replay(tmp_path: Path) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        response = client.get("/api/platform-evidence/mesoscope")
        assert response.status_code == 200
        report = response.json()
        assert report["track"] == "platform_generality"
        assert report["training_claim_included"] is False
        assert "Seeded offline protocol fixtures" in report["fixture_notice"]

        replay_id = report["results"][0]["replay_id"]
        replay_response = client.post(
            f"/api/platform-evidence/mesoscope/replays/{replay_id}"
        )
        assert replay_response.status_code == 200
        replay = replay_response.json()
        assert replay["trace_matches"] is True
        assert replay["result_matches"] is True
        assert replay["snapshot"]["trace"][-1]["type"] == "verifier"
