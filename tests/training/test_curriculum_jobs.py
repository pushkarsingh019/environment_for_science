"""Ticket 11 durable full-curriculum training job status."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.application import create_app
from studio.curriculum_jobs import CurriculumTrainingJobRepository


def test_curriculum_job_lifecycle_is_durable_and_binds_frozen_split_counts(
    tmp_path: Path,
) -> None:
    repository = CurriculumTrainingJobRepository(tmp_path)

    queued = repository.launch()
    running = repository.begin(queued.job_id)
    completed = repository.complete(
        queued.job_id,
        result_id="eeg-training-result-real0001",
        result_digest="sha256:" + "a" * 64,
    )

    assert queued.status == "queued"
    assert running.status == "running"
    assert completed.status == "completed"
    assert completed.training_scenarios == 96
    assert completed.development_scenarios == 32
    assert completed.heldout_scenarios == 64
    assert completed.training_package_digest == (
        "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
    )
    assert CurriculumTrainingJobRepository(tmp_path).load(queued.job_id) == completed


def test_curriculum_failure_remains_visible_without_framework_or_host_details(
    tmp_path: Path,
) -> None:
    repository = CurriculumTrainingJobRepository(tmp_path)
    job = repository.begin(repository.launch().job_id)

    failed = repository.fail(job.job_id, reason="artifact_verification")

    assert failed.status == "failed"
    assert failed.result_id is None
    assert "evidence verification" in failed.message.casefold()
    serialized = failed.model_dump_json().casefold()
    assert "/home/" not in serialized
    assert "/users/" not in serialized
    assert "traceback" not in serialized


def test_loopback_api_queues_and_starts_workstation_only_curriculum_jobs(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        queued = client.post("/api/training/curriculum-jobs")
        assert queued.status_code == 202
        payload = queued.json()
        assert payload["status"] == "queued"
        assert payload["training_scenarios"] == 96

        running = client.post(
            f"/api/training/curriculum-jobs/{payload['job_id']}/begin"
        )
        assert running.status_code == 200
        assert running.json()["status"] == "running"

        listed = client.get("/api/training/curriculum-jobs")
        assert listed.status_code == 200
        assert listed.json()[0]["job_id"] == payload["job_id"]
        assert "no model compute" in queued.text.casefold()
