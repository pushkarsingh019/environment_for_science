"""HTTP boundaries for the training-only EEG curriculum console."""

from __future__ import annotations

import json
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from environments.eeg.curriculum import load_training_scenario_set
from studio.application import create_app

_FORBIDDEN_PUBLIC_KEYS = {
    "blueprint_id",
    "category",
    "contract_digest",
    "faults",
    "manifest_digest",
    "nuisance_id",
    "package_digest",
    "recoverability",
    "seed",
    "split",
    "unavailable",
}


def _package_document(name: str) -> dict[str, Any]:
    return json.loads(
        files("environments.eeg").joinpath(name).read_text(encoding="utf-8")
    )


def _freeze(client: TestClient) -> dict[str, Any]:
    draft = client.get("/api/draft").json()
    response = client.post(
        "/api/draft/freeze",
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 201
    return response.json()


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested_key
            for nested in value.values()
            for nested_key in _all_keys(nested)
        }
    if isinstance(value, list):
        return {
            nested_key for nested in value for nested_key in _all_keys(nested)
        }
    return set()


def test_environment_exposes_only_neutral_training_examples(tmp_path: Path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    response = client.get("/api/environment")

    assert response.status_code == 200
    document = response.json()
    training = load_training_scenario_set()
    assert document["seeded_examples"] == [
        choice.model_dump(mode="json") for choice in training.seeded_examples
    ]
    assert len(document["seeded_examples"]) == 6
    assert "scenario_id" not in document
    assert "scenario_ids" not in document
    assert not (_all_keys(document) & _FORBIDDEN_PUBLIC_KEYS)

    serialized = response.text
    held_out = _package_document("curriculum_heldout_v1.json")
    development = _package_document("curriculum_development_v1.json")
    forbidden_values = {
        held_out["package_digest"],
        development["package_digest"],
        *(
            value
            for package in (held_out, development)
            for scenario in package["scenarios"]
            for key, value in scenario.items()
            if key in {"scenario_id", "blueprint_id", "nuisance_id", "manifest_digest"}
        ),
    }
    assert all(value not in serialized for value in forbidden_values)


def test_freeze_response_and_artifact_contain_training_only(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    frozen = _freeze(client)

    assert "scenario_id" not in frozen
    assert "scenario_ids" not in frozen
    assert frozen["frozen_environment_id"].startswith("frozen-")

    with sqlite3.connect(tmp_path / "studio-index.sqlite3") as connection:
        stored_json = connection.execute(
            "SELECT bundle_json FROM frozen_environment_index"
        ).fetchone()[0]
    stored = json.loads(stored_json)
    training = _package_document("curriculum_training_v1.json")
    held_out = _package_document("curriculum_heldout_v1.json")
    development = _package_document("curriculum_development_v1.json")

    assert stored["split_identities"] == ["training"]
    assert {scenario["id"] for scenario in stored["scenarios"]} == {
        scenario["scenario_id"] for scenario in training["scenarios"]
    }
    stored_text = json.dumps(stored, sort_keys=True)
    forbidden_values = {
        package["package_digest"]
        for package in (development, held_out)
    } | {
        value
        for package in (development, held_out)
        for scenario in package["scenarios"]
        for key, value in scenario.items()
        if key in {"scenario_id", "blueprint_id", "nuisance_id", "manifest_digest"}
    }
    assert all(value not in stored_text for value in forbidden_values)


def test_console_route_rejects_heldout_identity_without_creating_a_run(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    environment = client.get("/api/environment").json()
    frozen = _freeze(client)
    held_out_id = _package_document("curriculum_heldout_v1.json")["scenarios"][0][
        "scenario_id"
    ]

    rejected = client.post(
        "/api/runs",
        json={
            "scenario_id": held_out_id,
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )

    assert rejected.status_code == 422
    assert not list((tmp_path / "traces").glob("*.jsonl"))
    with sqlite3.connect(tmp_path / "studio-index.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_index").fetchone()[0] == 0

    accepted = client.post(
        "/api/runs",
        json={
            "scenario_id": environment["seeded_examples"][0]["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert accepted.status_code == 201


def test_run_surface_preserves_stage_freshness_disposition_metrics_and_replay(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    environment = client.get("/api/environment").json()
    frozen = _freeze(client)
    selected = environment["seeded_examples"][1]
    started_response = client.post(
        "/api/runs",
        json={
            "scenario_id": selected["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert started_response.status_code == 201
    current = started_response.json()
    assert current["observation"]["stage"] == "preflight"
    assert set(current["observation"]["evidence_freshness"]) == {
        "configuration",
        "eeg",
        "onset",
        "response",
        "recording",
    }

    for action_type in (
        "inspect_configuration",
        "inspect_eeg_signals",
        "inspect_onset_route",
        "inspect_response_timeline",
        "inspect_recording_timeline",
        "correct_trigger_visibility",
    ):
        response = client.post(
            f"/api/runs/{current['run_id']}/actions",
            json={"type": action_type, "input": {}},
        )
        assert response.status_code == 200
        current = response.json()
    assert current["observation"]["evidence_freshness"]["onset"]["status"] == "stale"

    for action_type in (
        "present_test_flash",
        "run_response_preflight",
        "complete_preflight",
    ):
        response = client.post(
            f"/api/runs/{current['run_id']}/actions",
            json={"type": action_type, "input": {}},
        )
        assert response.status_code == 200
        current = response.json()
    assert current["observation"]["stage"] == "terminal"

    verified_response = client.post(f"/api/runs/{current['run_id']}/verify")
    assert verified_response.status_code == 200
    verified = verified_response.json()
    result = verified["verifier_result"]
    assert result["passed"] is True
    assert result["terminal_disposition"] == "closed"
    assert result["outcome_category"] == "individual"
    assert result["metrics"]["terminal_correctness"] == 1.0
    assert result["metrics"]["fresh_validation"] == 1.0
    assert _all_keys(verified) & {
        "faults",
        "blueprint_id",
        "nuisance_id",
        "unavailable_fault",
    } == set()

    replay = client.post(f"/api/runs/{current['run_id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["replay"]["trace_matches"] is True
    assert replay.json()["replay"]["result_matches"] is True
