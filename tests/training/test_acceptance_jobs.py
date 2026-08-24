"""Ticket 10 durable job lifecycle and loopback application seams."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from studio.application import create_app
from studio.training_jobs import TrainingAcceptanceJobService
from tests.training.test_acceptance_artifacts import _acceptance_tree, _canonical


def _bind_job(root: Path, job_id: str) -> None:
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["job_id"] = job_id
    _canonical(receipt_path, receipt)


def test_job_lifecycle_is_durable_and_completes_only_after_artifact_verification(
    tmp_path: Path,
) -> None:
    service = TrainingAcceptanceJobService(tmp_path)

    queued = service.launch()
    assert queued.status == "queued"
    assert "workstation" in queued.message.casefold()
    running = service.begin(queued.job_id)
    assert running.status == "running"
    artifacts = service.import_directory(queued.job_id)
    _acceptance_tree(artifacts)
    _bind_job(artifacts, queued.job_id)

    completed = service.verify(queued.job_id)

    assert completed.status == "completed"
    assert completed.evidence is not None
    assert completed.evidence.job_id == queued.job_id
    assert completed.artifact_reference == (
        f"training-acceptance-imports/{queued.job_id}"
    )
    reopened = TrainingAcceptanceJobService(tmp_path)
    assert reopened.load(queued.job_id) == completed
    assert reopened.list() == (completed,)


def test_failed_artifact_verification_is_visible_and_retryable(tmp_path: Path) -> None:
    service = TrainingAcceptanceJobService(tmp_path)
    queued = service.launch()
    service.begin(queued.job_id)
    artifacts = service.import_directory(queued.job_id)
    _acceptance_tree(artifacts)
    _bind_job(artifacts, queued.job_id)
    final = artifacts / "run/broadcasts/step_1/adapter_model.safetensors"
    initial = artifacts / "run/broadcasts/step_0/adapter_model.safetensors"
    final.write_bytes(initial.read_bytes())

    failed = service.verify(queued.job_id)

    assert failed.status == "failed"
    assert failed.evidence is None
    assert "change an adapter" in failed.message.casefold()
    retried = service.retry(queued.job_id)
    assert retried.status == "queued"
    assert retried.evidence is None


def test_loopback_api_exposes_queued_running_failed_and_completed_states(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        launch = client.post("/api/training/acceptance-jobs")
        assert launch.status_code == 202
        queued = launch.json()
        job_id = queued["job_id"]
        assert queued["status"] == "queued"

        running_response = client.post(
            f"/api/training/acceptance-jobs/{job_id}/begin"
        )
        assert running_response.status_code == 200
        assert running_response.json()["status"] == "running"

        artifacts = (
            tmp_path
            / "training/training-acceptance-imports"
            / job_id
        )
        _acceptance_tree(artifacts)
        _bind_job(artifacts, job_id)
        completed_response = client.post(
            f"/api/training/acceptance-jobs/{job_id}/verify"
        )
        assert completed_response.status_code == 200
        completed = completed_response.json()
        assert completed["status"] == "completed"
        assert completed["evidence"]["changed_adapter_tensors"] == 28

        listed = client.get("/api/training/acceptance-jobs")
        assert listed.status_code == 200
        assert listed.json()[0]["job_id"] == job_id
        serialized = listed.text.casefold()
        assert "/users/" not in serialized
        assert "/home/" not in serialized
        assert "private host" not in serialized
