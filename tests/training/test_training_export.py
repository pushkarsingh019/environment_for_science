"""Native prime artifact sanitization into the Ticket 10 evidence tree."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from studio.training_acceptance import AcceptanceArtifactError
from studio.training_export import NativeAcceptanceExporter
from tests.training.test_acceptance_artifacts import _acceptance_tree


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _native_row(scenario_id: str, model: str, ordinal: int) -> dict[str, object]:
    return {
        "ok": True,
        "errors": [],
        "task": {"data": {"name": scenario_id}},
        "traces": [
            {
                "ok": True,
                "is_completed": True,
                "errors": [],
                "stop_condition": "terminal",
                "calls": [
                    {"model": model, "error": None},
                    {"model": model, "error": None},
                ],
                "nodes": [
                    {"message": {"role": "user"}},
                    {"message": {"role": "assistant"}},
                    {"message": {"role": "tool"}},
                    {"message": {"role": "assistant"}},
                ],
                "info": {
                    "science_environment_runtime": {
                        "scenario_id": scenario_id,
                        "runtime_trace_digest": _digest(
                            f"trace-{scenario_id}-{model}-{ordinal}"
                        ),
                        "runtime_result_digest": _digest(
                            f"result-{scenario_id}-{model}-{ordinal}"
                        ),
                    }
                },
            }
        ],
    }


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _native_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = _acceptance_tree(tmp_path / "source")
    run = source / "run"
    (run / "metrics.jsonl").write_text(
        "".join(
            (
                '{"loss/mean":0.25}\n',
                '{"optim/grad_norm":0.5}\n',
                '{"mismatch_kl/all/mean":0.75}\n',
            )
        )
    )
    training_scenario = "eeg-04b947fbdffb3768"
    training = [
        _native_row(
            training_scenario,
            "r8-a16.0",
            index,
        )
        for index in range(8)
    ]
    _write_rows(
        run / "rollouts/step_1/train/effective/traces.jsonl",
        training,
    )
    scenarios = ("eeg-0ba779dfa73fc9db", "eeg-0553f1f24a3a64fa")
    baseline = tmp_path / "native-baseline.jsonl"
    reloaded = tmp_path / "native-reloaded.jsonl"
    _write_rows(
        baseline,
        [
            _native_row(scenario, "google/gemma-4-E4B-it", index)
            for index, scenario in enumerate(scenarios)
        ],
    )
    _write_rows(
        reloaded,
        [
            _native_row(scenario, "proof-final", index)
            for index, scenario in enumerate(scenarios)
        ],
    )
    return run, baseline, reloaded


def test_exporter_derives_sanitized_verified_evidence_from_native_artifacts(
    tmp_path: Path,
) -> None:
    run, baseline, reloaded = _native_tree(tmp_path)

    evidence = NativeAcceptanceExporter().export(
        job_id="training-acceptance-export001",
        run_directory=run,
        baseline_traces=baseline,
        reloaded_traces=reloaded,
        destination=tmp_path / "export",
        training_hardware_id=_digest("training-hardware"),
        inference_hardware_id=_digest("inference-hardware"),
        training_taskset_digest=_digest("training-taskset"),
        development_taskset_digest=_digest("development-taskset"),
    )

    assert evidence.status == "verified"
    assert evidence.training_scenario_ids == ("eeg-04b947fbdffb3768",)
    assert len(evidence.training_trace_digests) == 8
    assert evidence.optimization_metrics.loss == 0.25
    receipt_text = (tmp_path / "export/receipt.json").read_text().casefold()
    assert str(tmp_path).casefold() not in receipt_text
    assert "/home/" not in receipt_text
    assert "/users/" not in receipt_text


def test_exporter_rejects_unpinned_training_adapter_identity(tmp_path: Path) -> None:
    run, baseline, reloaded = _native_tree(tmp_path)
    training = run / "rollouts/step_1/train/effective/traces.jsonl"
    rows = [json.loads(line) for line in training.read_text().splitlines()]
    rows[0]["traces"][0]["calls"][0]["model"] = "unapproved-adapter"
    _write_rows(training, rows)

    with pytest.raises(AcceptanceArtifactError, match="tool loops"):
        NativeAcceptanceExporter().export(
            job_id="training-acceptance-export003",
            run_directory=run,
            baseline_traces=baseline,
            reloaded_traces=reloaded,
            destination=tmp_path / "rejected-training-identity",
            training_hardware_id=_digest("training-hardware"),
            inference_hardware_id=_digest("inference-hardware"),
            training_taskset_digest=_digest("training-taskset"),
            development_taskset_digest=_digest("development-taskset"),
        )


def test_exporter_rejects_native_provider_errors_before_copying(
    tmp_path: Path,
) -> None:
    run, baseline, reloaded = _native_tree(tmp_path)
    rows = [json.loads(line) for line in reloaded.read_text().splitlines()]
    rows[0]["traces"][0]["calls"][1]["error"] = {"type": "provider"}
    _write_rows(reloaded, rows)

    with pytest.raises(AcceptanceArtifactError, match="tool loops"):
        NativeAcceptanceExporter().export(
            job_id="training-acceptance-export002",
            run_directory=run,
            baseline_traces=baseline,
            reloaded_traces=reloaded,
            destination=tmp_path / "rejected",
            training_hardware_id=_digest("training-hardware"),
            inference_hardware_id=_digest("inference-hardware"),
            training_taskset_digest=_digest("training-taskset"),
            development_taskset_digest=_digest("development-taskset"),
        )
