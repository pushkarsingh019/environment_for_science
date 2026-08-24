"""Ticket 12 scientifically constrained comparison fixtures and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from studio.application import create_app
from studio.model_comparison import (
    FixtureState,
    ModelComparisonRepository,
    ModelComparisonResult,
    seeded_comparison,
)


@pytest.mark.parametrize(
    ("state", "claim"),
    (
        ("successful", "improved"),
        ("inconclusive", "inconclusive"),
        ("regressed", "regressed"),
        ("partially_unavailable", "improved"),
        ("adapter_error", "unavailable"),
    ),
)
def test_seeded_comparison_states_are_explicit_and_scientifically_bounded(
    state: FixtureState,
    claim: str,
) -> None:
    result = seeded_comparison(state)

    assert result.source == "seeded_offline_fixture"
    assert result.fixture_state == state
    assert "not a live" in (result.fixture_notice or "")
    assert result.training_claim == claim
    assert result.training_result_id is None
    assert result.training_artifact_digest is None
    assert [model.role for model in result.models] == [
        "base_gemma",
        "trained_gemma",
        "openai_reference",
        "gemini_reference",
    ]
    assert result.models[2].reference_model is True
    assert result.models[3].reference_model is True
    assert result.mesoscope.claim_scope == "platform_generality"
    assert result.mesoscope.eeg_training_evidence is False
    for model in result.models:
        assert model.model_configuration_digest.startswith("sha256:")
        assert (model.adapter_identity is not None) == (
            model.adapter_digest is not None
        )
        if model.status == "available":
            assert model.metrics is not None
            assert len(model.scenarios) == 64
            assert all(link.replay_route for link in model.scenarios)
        else:
            assert model.failure is not None
            assert model.metrics is None


def test_missing_hosted_credential_is_not_converted_to_a_zero_score() -> None:
    result = seeded_comparison("partially_unavailable")
    openai = result.models[2]

    assert openai.status == "credential_missing"
    assert openai.metrics is None
    assert openai.scenarios == ()
    assert openai.failure is not None
    assert "no live score" in openai.failure.summary


def test_claim_validator_rejects_an_improvement_without_approved_interval() -> None:
    result = seeded_comparison("inconclusive")
    document = result.model_dump(mode="json")
    document["training_claim"] = "improved"

    with pytest.raises(ValidationError, match="claim"):
        ModelComparisonResult.model_validate_json(json.dumps(document))


def test_repository_resets_fixture_state_without_deleting_immutable_real_rows(
    tmp_path: Path,
) -> None:
    repository = ModelComparisonRepository(tmp_path)
    assert repository.current().fixture_state == "successful"

    selected = repository.select_fixture("regressed")
    assert selected.training_claim == "regressed"
    reopened = ModelComparisonRepository(tmp_path)
    assert reopened.current() == selected

    reset = reopened.reset_demo()
    assert reset.fixture_state == "successful"
    assert reopened.current() == reset


def test_loopback_comparison_routes_switch_replay_and_reset_fixtures(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        current = client.get("/api/model-comparison")
        assert current.status_code == 200
        assert current.json()["fixture_state"] == "successful"

        partial = client.post(
            "/api/model-comparison/fixtures/partially_unavailable"
        )
        assert partial.status_code == 200
        payload = partial.json()
        assert payload["models"][2]["status"] == "credential_missing"
        assert payload["models"][2]["metrics"] is None
        scenario = payload["models"][0]["scenarios"][0]

        replay = client.get(scenario["replay_route"])
        assert replay.status_code == 200
        assert replay.json()["scenario"]["runtime_trace_digest"] == (
            scenario["runtime_trace_digest"]
        )

        reset = client.post("/api/model-comparison/reset")
        assert reset.status_code == 200
        assert reset.json()["fixture_state"] == "successful"
        assert "/users/" not in reset.text.casefold()
        assert "/home/" not in reset.text.casefold()


def test_reset_preserves_installed_real_comparison_rows(tmp_path: Path) -> None:
    repository = ModelComparisonRepository(tmp_path)
    document = seeded_comparison("successful").model_dump(mode="json")
    document.update(
        {
            "comparison_id": "model-comparison-real-test0001",
            "source": "real_evaluation",
            "fixture_state": None,
            "fixture_notice": None,
            "training_result_id": "eeg-training-result-realtest0001",
            "training_artifact_digest": "sha256:" + "d" * 64,
        }
    )
    real = ModelComparisonResult.model_validate_json(json.dumps(document))

    repository.install_real(real)
    assert repository.current() == real
    assert repository.real_result_count() == 1

    repository.reset_demo()

    assert repository.current().source == "seeded_offline_fixture"
    assert repository.real_result_count() == 1


def test_replay_resolves_exact_model_and_scenario_digests(tmp_path: Path) -> None:
    repository = ModelComparisonRepository(tmp_path)
    result = repository.current()
    scenario = result.models[0].scenarios[0]

    replay = repository.replay("base_gemma", scenario.scenario_id)

    assert replay.source == "seeded_offline_fixture"
    assert replay.model_role == "base_gemma"
    assert replay.scenario == scenario
    assert replay.model_configuration_digest == result.models[0].model_configuration_digest
    assert replay.adapter_digest == result.models[0].adapter_digest
    assert replay.training_artifact_digest == result.training_artifact_digest
    assert replay.provenance == result.provenance
    assert replay.reproducible is True
