"""Ticket 13 reset restores demo state without deleting immutable evidence."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.application import create_app
from studio.curriculum_jobs import CurriculumTrainingJobRepository
from studio.model_comparison import ModelComparisonRepository
from tests.evaluation.model_comparison_support import real_comparison_with_ledgers


def test_demo_reset_restores_seeded_state_and_preserves_real_job_rows(
    tmp_path: Path,
) -> None:
    real_comparison, base_ledger, trained_ledger = real_comparison_with_ledgers(
        tmp_path
    )
    ModelComparisonRepository(tmp_path / "comparisons").install_real(
        real_comparison,
        base_ledger_root=base_ledger,
        trained_ledger_root=trained_ledger,
    )
    curriculum_repository = CurriculumTrainingJobRepository(
        tmp_path / "training/curriculum"
    )
    immutable_job = curriculum_repository.launch()
    curriculum_repository.begin(immutable_job.job_id)
    curriculum_repository.complete(
        immutable_job.job_id,
        result_id="eeg-training-result-resettest0001",
        result_digest="sha256:" + "a" * 64,
    )

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
            "immutable_training_jobs_preserved": 1,
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
        assert jobs == []
        assert job["job_id"] not in response.text
        curriculum_jobs = client.get("/api/training/curriculum-jobs").json()
        assert [item["job_id"] for item in curriculum_jobs] == [
            immutable_job.job_id
        ]
        assert curriculum_job["job_id"] not in response.text
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
