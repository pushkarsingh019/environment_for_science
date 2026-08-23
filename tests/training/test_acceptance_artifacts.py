"""Ticket 10 acceptance-artifact verification at the durable evidence seam."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from studio.training_acceptance import (
    STACK_PINS,
    AcceptanceArtifactError,
    AcceptanceArtifactVerifier,
    TrainingAcceptanceEvidence,
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_safetensors(path: Path, value: bytes) -> None:
    key = "model.language_model.layers.0.self_attn.q_proj.lora_A.weight"
    header = json.dumps(
        {
            key: {
                "dtype": "F32",
                "shape": [1],
                "data_offsets": [0, len(value)],
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + value)


def _canonical(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    )


def _acceptance_tree(root: Path) -> Path:
    run = root / "run"
    initial = run / "broadcasts/step_0"
    final = run / "broadcasts/step_1"
    checkpoint = run / "checkpoints/step_1/trainer"
    traces = root / "evals"
    for directory in (initial, final, checkpoint, traces):
        directory.mkdir(parents=True, exist_ok=True)
    for directory, tensor in ((initial, b"\x00\x00\x00\x00"), (final, b"\x00\x00\x80?")):
        (directory / "STABLE").write_text("stable\n")
        _canonical(
            directory / "adapter_config.json",
            {
                "peft_type": "LORA",
                "r": 8,
                "lora_alpha": 16,
                "target_modules": [
                    "q_proj",
                    "k_proj",
                    "v_proj",
                    "o_proj",
                    "gate_proj",
                    "up_proj",
                    "down_proj",
                ],
            },
        )
        _write_safetensors(directory / "adapter_model.safetensors", tensor)
    (checkpoint / "state.distcp").write_bytes(b"non-empty-resumable-state")
    _canonical(
        root / "optimization-metrics.json",
        {"loss": 1.25, "gradient_norm": 0.75, "mismatch_kl": 0.02},
    )
    training_scenario_id = "eeg-04b947fbdffb3768"
    training_rows = [
        {
            "scenario_id": training_scenario_id,
            "rollout_index": rollout_index,
            "model": "google/gemma-4-E4B-it",
            "ok": True,
            "tool_calls": 2,
            "trace_error": None,
            "runtime_trace_digest": _digest(
                f"training-{training_scenario_id}-{rollout_index}".encode()
            ),
            "result_digest": _digest(
                f"training-result-{training_scenario_id}-{rollout_index}".encode()
            ),
        }
        for rollout_index in range(8)
    ]
    (traces / "training.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in training_rows
        )
    )
    scenario_ids = ("eeg-0ba779dfa73fc9db", "eeg-0553f1f24a3a64fa")
    for name, model in (
        ("baseline", "google/gemma-4-E4B-it"),
        ("reloaded", "proof-final"),
    ):
        rows = [
            {
                "scenario_id": scenario_id,
                "rollout_index": 0,
                "model": model,
                "ok": True,
                "tool_calls": 2,
                "trace_error": None,
                "runtime_trace_digest": _digest(f"{name}-{scenario_id}".encode()),
                "result_digest": _digest(f"result-{name}-{scenario_id}".encode()),
            }
            for scenario_id in scenario_ids
        ]
        (traces / f"{name}.jsonl").write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in rows
            )
        )
    config = {
        "model": "google/gemma-4-E4B-it",
        "model_revision": "ee0ef6023621cff504d758262d4e04895a5af4a2",
        "optimization_dtype": "bfloat16",
        "reduction_dtype": "bfloat16",
        "lora_target_regex": (
            "^model\\.language_model\\.layers\\..*\\."
            "(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
        ),
        "max_steps": 1,
        "training_sequence_length": 16_384,
        "evaluation_context_length": 16_384,
        "training_taskset_digest": _digest(b"training-taskset"),
        "development_taskset_digest": _digest(b"development-taskset"),
        "training_package_digest": (
            "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
        ),
        "development_package_digest": (
            "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
        ),
        "mechanical_jitter_weight": 0.001,
        "served_adapter": "proof-final",
    }
    config_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    _canonical(root / "acceptance-config.json", config)
    _canonical(
        root / "receipt.json",
        {
            "receipt_version": "science-gemma-acceptance-receipt/1",
            "job_id": "training-acceptance-test0001",
            "stack": dict(STACK_PINS),
            "model": "google/gemma-4-E4B-it",
            "model_revision": "ee0ef6023621cff504d758262d4e04895a5af4a2",
            "fallback": {"used": False, "reason": None},
            "compute_scope": "approved-workstations-only",
            "platform": "linux-x86_64",
            "private_transport": True,
            "training_hardware_id": _digest(b"training-workstation-receipt"),
            "inference_hardware_id": _digest(b"inference-workstation-receipt"),
            "configuration_digest": _digest(config_bytes),
            "paths": {
                "run": "run",
                "metrics": "optimization-metrics.json",
                "configuration": "acceptance-config.json",
                "training_traces": "evals/training.jsonl",
                "baseline_traces": "evals/baseline.jsonl",
                "reloaded_traces": "evals/reloaded.jsonl",
            },
        },
    )
    return root


def test_verifier_proves_step_checkpoint_changed_adapter_reload_and_tool_loops(
    tmp_path: Path,
) -> None:
    evidence = AcceptanceArtifactVerifier().verify(_acceptance_tree(tmp_path))

    assert isinstance(evidence, TrainingAcceptanceEvidence)
    assert evidence.status == "verified"
    assert evidence.model == "google/gemma-4-E4B-it"
    assert evidence.fallback_used is False
    assert evidence.optimization_metrics.model_dump() == {
        "loss": 1.25,
        "gradient_norm": 0.75,
        "mismatch_kl": 0.02,
    }
    assert evidence.changed_adapter_tensors == 1
    assert evidence.adapter_tensor_count == 1
    assert evidence.checkpoint_files == 1
    assert evidence.reloaded_served_identity == "proof-final"
    assert evidence.training_scenario_ids == ("eeg-04b947fbdffb3768",)
    assert len(evidence.training_trace_digests) == 8
    assert evidence.heldout_scenario_ids == (
        "eeg-0ba779dfa73fc9db",
        "eeg-0553f1f24a3a64fa",
    )
    assert evidence.artifact_digest.startswith("sha256:")
    assert "/" not in evidence.training_hardware_id.removeprefix("sha256:")


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unchanged", "did not change"),
        ("missing_checkpoint", "checkpoint"),
        ("failed_reload", "reloaded evaluation"),
        ("nonfinite_metric", "finite"),
        ("vision_tensor", "language-layer"),
        ("fallback_without_resource_failure", "fallback"),
    ),
)
def test_verifier_fails_closed_for_incomplete_or_nominal_evidence(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    root = _acceptance_tree(tmp_path)
    if mutation == "unchanged":
        final = root / "run/broadcasts/step_1/adapter_model.safetensors"
        initial = root / "run/broadcasts/step_0/adapter_model.safetensors"
        final.write_bytes(initial.read_bytes())
    elif mutation == "missing_checkpoint":
        (root / "run/checkpoints/step_1/trainer/state.distcp").unlink()
    elif mutation == "failed_reload":
        path = root / "evals/reloaded.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["trace_error"] = "adapter failed"
        rows[0]["ok"] = False
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    elif mutation == "nonfinite_metric":
        (root / "optimization-metrics.json").write_text(
            '{"loss":1.0,"gradient_norm":NaN,"mismatch_kl":0.1}\n'
        )
    elif mutation == "vision_tensor":
        _write_safetensors(
            root / "run/broadcasts/step_1/adapter_model.safetensors",
            b"\x00\x00\x80?",
        )
        payload = root / "run/broadcasts/step_1/adapter_model.safetensors"
        raw = payload.read_bytes()
        length = struct.unpack("<Q", raw[:8])[0]
        header = json.loads(raw[8 : 8 + length])
        value = next(iter(header.values()))
        rewritten = json.dumps(
            {"model.vision_tower.q_proj.lora_A.weight": value},
            separators=(",", ":"),
        ).encode()
        payload.write_bytes(struct.pack("<Q", len(rewritten)) + rewritten + raw[8 + length :])
    else:
        receipt_path = root / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["model"] = "google/gemma-4-E2B-it"
        receipt["model_revision"] = "3e22461f65e89153144f8adb70e3b8c2cc9845a7"
        receipt["fallback"] = {"used": True, "reason": "operator_preference"}
        _canonical(receipt_path, receipt)

    with pytest.raises(AcceptanceArtifactError, match=message):
        AcceptanceArtifactVerifier().verify(root)
