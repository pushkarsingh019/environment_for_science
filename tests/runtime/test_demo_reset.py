"""Ticket 13 reset restores demo state without deleting immutable evidence."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from studio.application import create_app
from studio.model_comparison import (
    ModelComparisonRepository,
    ModelComparisonResult,
    seeded_comparison,
)


def test_demo_reset_restores_seeded_state_and_preserves_real_job_rows(
    tmp_path: Path,
) -> None:
    comparison_document = seeded_comparison("successful").model_dump(mode="json")
    comparison_document.update(
        {
            "comparison_id": "model-comparison-real-reset0001",
            "source": "real_evaluation",
            "fixture_state": None,
            "fixture_notice": None,
        }
    )
    real_comparison = ModelComparisonResult.model_validate_json(
        json.dumps(comparison_document)
    )
    ModelComparisonRepository(tmp_path / "comparisons").install_real(real_comparison)

    with TestClient(create_app(artifact_root=tmp_path)) as client:
        seeded = client.get("/api/draft").json()
        edited = client.post(
            "/api/draft/commands",
            json={
                "command": "Add Cz to the Montage",
                "expected_revision": seeded["revision"],
            },
        )
        assert edited.status_code == 200
        assert edited.json()["draft"]["revision_digest"] != seeded["revision_digest"]
        job = client.post("/api/training/acceptance-jobs").json()
        curriculum_job = client.post("/api/training/curriculum-jobs").json()
        client.post("/api/model-comparison/fixtures/regressed")

        response = client.post("/api/demo/reset")

        assert response.status_code == 200
        reset = response.json()
        assert reset == {
            "reset_version": "science-demo-reset/1",
            "status": "reset",
            "draft_revision": reset["draft_revision"],
            "draft_digest": seeded["revision_digest"],
            "comparison_fixture_state": "successful",
            "seeded_scenarios_restored": True,
            "immutable_training_jobs_preserved": 2,
            "immutable_real_comparisons_preserved": 1,
            "immutable_artifacts_deleted": 0,
            "summary": (
                "Seeded draft, scenarios, and offline demonstration state were "
                "restored. Immutable real artifacts were preserved."
            ),
        }
        assert client.get("/api/draft").json()["revision_digest"] == (
            seeded["revision_digest"]
        )
        assert client.get("/api/model-comparison").json()["fixture_state"] == (
            "successful"
        )
        jobs = client.get("/api/training/acceptance-jobs").json()
        assert [item["job_id"] for item in jobs] == [job["job_id"]]
        curriculum_jobs = client.get("/api/training/curriculum-jobs").json()
        assert [item["job_id"] for item in curriculum_jobs] == [
            curriculum_job["job_id"]
        ]
        assert ModelComparisonRepository(
            tmp_path / "comparisons"
        ).real_result_count() == 1


def test_demo_reset_is_repeatable_and_never_reports_artifact_deletion(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        first = client.post("/api/demo/reset").json()
        second = client.post("/api/demo/reset").json()

    assert second["draft_digest"] == first["draft_digest"]
    assert second["draft_revision"] == first["draft_revision"] + 1
    assert second["immutable_artifacts_deleted"] == 0
