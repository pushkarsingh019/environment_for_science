"""Ticket 10 acceptance-artifact verification at the durable evidence seam."""

from __future__ import annotations

import hashlib
import io
import json
import pickle
import struct
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from environments.eeg.curriculum import (
    DevelopmentScenarioSet,
    TrainingScenarioSet,
    load_development_scenario_set,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from studio.runtime import EnvironmentAction, EnvironmentRuntime, PolicyAgentIdentity
from studio.training_acceptance import (
    STACK_PINS,
    AcceptanceArtifactError,
    AcceptanceArtifactVerifier,
    TrainingAcceptanceEvidence,
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _adapter_keys() -> tuple[str, ...]:
    return tuple(
        f"model.language_model.layers.{layer}.{block}.{target}.lora_{side}.weight"
        for layer in (0, 1)
        for block, targets in (
            ("self_attn", ("q_proj", "k_proj", "v_proj", "o_proj")),
            ("mlp", ("gate_proj", "up_proj", "down_proj")),
        )
        for target in targets
        for side in ("A", "B")
    )


def _write_safetensors(
    path: Path,
    value: bytes,
    *,
    keys: tuple[str, ...] | None = None,
) -> None:
    if len(value) != 4:
        raise ValueError("test tensor marker must contain four bytes")
    offset = 0
    header: dict[str, object] = {"__metadata__": {"format": "pt"}}
    for key in keys or _adapter_keys():
        contents = value * 4
        shape = [8, 1] if key.endswith(".lora_A.weight") else [1, 8]
        header[key] = {
            "dtype": "BF16",
            "shape": shape,
            "data_offsets": [offset, offset + len(contents)],
        }
        offset += len(contents)
    encoded = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data = b"".join(value * 4 for _key in keys or _adapter_keys())
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + data)


def _canonical_trace_row(
    scenario_set: TrainingScenarioSet | DevelopmentScenarioSet,
    scenario_id: str,
    *,
    rollout_index: int,
    model: str,
    incomplete: bool = True,
) -> dict[str, object]:
    runtime = EnvironmentRuntime(
        EegEnvironmentModule(scenario_set.environment_bundle)
    )
    current = runtime.start(
        scenario_id,
        PolicyAgentIdentity(id="acceptance-test-policy", name="Acceptance test policy"),
    )
    for _ in range(2):
        action = current.permitted_actions[0]
        current = runtime.apply_action(
            current.run_id,
            EnvironmentAction(type=action, arguments={}),
        )
    completed = (
        runtime.finalize_incomplete(
            current.run_id,
            termination_reason="model_ended_before_terminal",
        )
        if incomplete
        else runtime.verify(current.run_id)
    )
    return {
        "scenario_id": scenario_id,
        "rollout_index": rollout_index,
        "model": model,
        "ok": True,
        "tool_calls": 2,
        "trace_error": None,
        "runtime_trace_digest": completed.trace_digest,
        "result_digest": completed.result_digest,
        "snapshot": completed.model_dump(mode="json"),
        "model_calls": [
            {
                "ordinal": ordinal,
                "model": (
                    "r8-a16.0"
                    if (
                        model == "google/gemma-4-E4B-it"
                        and scenario_set.identity.split == "training"
                    )
                    else model
                ),
                "finish_reason": "tool_calls",
                "input_tokens": 100 + ordinal,
                "output_tokens": 4,
            }
            for ordinal in (1, 2)
        ],
    }


def _zip_segment(payload: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("archive/data.pkl", pickle.dumps({"state": payload}))
        archive.writestr("archive/.format_version", "1")
        archive.writestr("archive/byteorder", "little")
        archive.writestr("archive/version", "1")
        archive.writestr("archive/data/0", payload)
    return output.getvalue()


def _write_test_dcp(
    checkpoint: Path,
    *,
    impersonate_types: bool = False,
    duplicate_storage_fqn: bool = False,
) -> None:
    module_names = (
        "torch",
        "torch.distributed",
        "torch.distributed.checkpoint",
        "torch.distributed.checkpoint.metadata",
        "torch.distributed.checkpoint.filesystem",
    )
    previous = {name: sys.modules.get(name) for name in module_names}
    modules = {name: ModuleType(name) for name in module_names}
    try:
        sys.modules.update(modules)
        modules["torch"].distributed = modules["torch.distributed"]
        modules["torch.distributed"].checkpoint = modules[
            "torch.distributed.checkpoint"
        ]
        modules["torch.distributed.checkpoint"].metadata = modules[
            "torch.distributed.checkpoint.metadata"
        ]
        modules["torch.distributed.checkpoint"].filesystem = modules[
            "torch.distributed.checkpoint.filesystem"
        ]

        def dcp_class(name: str, module: str) -> type[object]:
            result = type(name, (), {})
            result.__module__ = module
            setattr(modules[module], name, result)
            return result

        metadata_type = dcp_class(
            "Metadata",
            "torch.distributed.checkpoint.metadata",
        )
        tensor_type = dcp_class(
            "TensorStorageMetadata",
            "torch.distributed.checkpoint.metadata",
        )
        index_type = dcp_class(
            "MetadataIndex",
            "torch.distributed.checkpoint.metadata",
        )
        storage_meta_type = dcp_class(
            "StorageMeta",
            "torch.distributed.checkpoint.metadata",
        )
        storage_info_type = dcp_class(
            "_StorageInfo",
            "torch.distributed.checkpoint.filesystem",
        )
        def instance(target: type[object], claimed_name: str) -> object:
            value = (tensor_type if impersonate_types else target)()
            if impersonate_types and target is not tensor_type:
                value._dcp_name = claimed_name
            return value

        names = ("app.model.weight", "app.optimizers.state")
        segments = (_zip_segment(b"model"), _zip_segment(b"optimizer"))
        offsets = (0, len(segments[0]))
        state = {name: tensor_type() for name in names}
        storage: dict[object, object] = {}
        for position, (name, offset, segment) in enumerate(
            zip(names, offsets, segments)
        ):
            index = instance(index_type, "MetadataIndex")
            index.fqn = names[0] if duplicate_storage_fqn and position else name
            index.index = None
            information = instance(storage_info_type, "_StorageInfo")
            information.relative_path = "__0_0.distcp"
            information.offset = offset
            information.length = len(segment)
            storage[index] = information
        storage_meta = instance(storage_meta_type, "StorageMeta")
        storage_meta.checkpoint_id = None
        storage_meta.save_id = "test-save"
        storage_meta.load_id = None
        storage_meta.modules = []
        metadata = instance(metadata_type, "Metadata")
        metadata.state_dict_metadata = state
        metadata.planner_data = {name: ("app", name) for name in names}
        metadata.storage_data = storage
        metadata.storage_meta = storage_meta
        metadata.version = "1.0.0"
        (checkpoint / ".metadata").write_bytes(
            pickle.dumps(metadata, protocol=4)
        )
        (checkpoint / "__0_0.distcp").write_bytes(b"".join(segments))
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


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
    _write_test_dcp(checkpoint)
    _canonical(
        root / "optimization-metrics.json",
        {"loss": 1.25, "gradient_norm": 0.75, "mismatch_kl": 0.02},
    )
    training_scenario_id = "eeg-04b947fbdffb3768"
    training_rows = [
        _canonical_trace_row(
            load_training_scenario_set(),
            training_scenario_id,
            rollout_index=rollout_index,
            model="google/gemma-4-E4B-it",
        )
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
            _canonical_trace_row(
                load_development_scenario_set(),
                scenario_id,
                rollout_index=0,
                model=model,
            )
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
            "receipt_version": "science-gemma-acceptance-receipt/2",
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
    assert evidence.changed_adapter_tensors == 28
    assert evidence.adapter_tensor_count == 28
    assert evidence.checkpoint_files == 2
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
        ("malformed_checkpoint", "checkpoint"),
        ("trailing_checkpoint_metadata", "checkpoint"),
        ("impersonated_checkpoint_types", "checkpoint"),
        ("duplicate_checkpoint_storage", "checkpoint"),
        ("signature_only_checkpoint", "checkpoint"),
        ("unlinked_checkpoint", "checkpoint"),
        ("failed_reload", "reloaded evaluation"),
        ("nonfinite_metric", "finite"),
        ("vision_tensor", "language-layer"),
        ("single_tensor", "architecture"),
        ("forged_snapshot", "canonical"),
        ("wrong_model_lineage", "canonical"),
        ("terminal_call_order", "canonical"),
        ("legacy_relabel", "legacy"),
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
        (root / "run/checkpoints/step_1/trainer/.metadata").unlink()
    elif mutation == "malformed_checkpoint":
        (root / "run/checkpoints/step_1/trainer/.metadata").write_bytes(
            pickle.dumps(
                {
                    "markers": (
                        "torch.distributed.checkpoint.metadata",
                        "Metadata",
                        "TensorStorageMetadata",
                        "StorageInfo",
                    )
                },
                protocol=4,
            )
        )
    elif mutation == "trailing_checkpoint_metadata":
        metadata = root / "run/checkpoints/step_1/trainer/.metadata"
        metadata.write_bytes(metadata.read_bytes() + b"trailing junk")
    elif mutation == "impersonated_checkpoint_types":
        _write_test_dcp(
            root / "run/checkpoints/step_1/trainer",
            impersonate_types=True,
        )
    elif mutation == "duplicate_checkpoint_storage":
        _write_test_dcp(
            root / "run/checkpoints/step_1/trainer",
            duplicate_storage_fqn=True,
        )
    elif mutation == "signature_only_checkpoint":
        segments = (_zip_segment(b"model"), _zip_segment(b"optimizer"))
        forged = bytearray()
        for segment in segments:
            replacement = bytearray(len(segment))
            replacement[:4] = b"PK\x03\x04"
            replacement[-22:-18] = b"PK\x05\x06"
            forged.extend(replacement)
        shard = root / "run/checkpoints/step_1/trainer/__0_0.distcp"
        shard.write_bytes(forged)
    elif mutation == "unlinked_checkpoint":
        shard = root / "run/checkpoints/step_1/trainer/__0_0.distcp"
        shard.write_bytes(shard.read_bytes() + b"unlinked bytes")
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
            keys=("model.vision_tower.q_proj.lora_A.weight",),
        )
    elif mutation == "single_tensor":
        _write_safetensors(
            root / "run/broadcasts/step_1/adapter_model.safetensors",
            b"\x00\x00\x80?",
            keys=(
                "model.language_model.layers.0.self_attn.q_proj.lora_A.weight",
            ),
        )
    elif mutation in {
        "forged_snapshot",
        "wrong_model_lineage",
        "terminal_call_order",
    }:
        trace_path = root / "evals/reloaded.jsonl"
        rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
        if mutation == "forged_snapshot":
            rows[0]["runtime_trace_digest"] = _digest(b"forged snapshot")
        elif mutation == "wrong_model_lineage":
            rows[0]["model_calls"][0]["model"] = "unloaded-adapter"
        else:
            calls = rows[0]["model_calls"]
            terminal = {
                **calls[-1],
                "ordinal": 1,
                "finish_reason": "stop",
            }
            rows[0]["model_calls"] = [
                terminal,
                {**calls[0], "ordinal": 2},
                {**calls[1], "ordinal": 3},
            ]
        trace_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )
    elif mutation == "legacy_relabel":
        for trace_path in (root / "evals").glob("*.jsonl"):
            rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
            for row in rows:
                row.pop("snapshot")
                row.pop("model_calls")
            trace_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
            )
        receipt_path = root / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["receipt_version"] = "science-gemma-acceptance-receipt/1"
        _canonical(receipt_path, receipt)
    else:
        receipt_path = root / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["model"] = "google/gemma-4-E2B-it"
        receipt["model_revision"] = "3e22461f65e89153144f8adb70e3b8c2cc9845a7"
        receipt["fallback"] = {"used": True, "reason": "operator_preference"}
        _canonical(receipt_path, receipt)

    with pytest.raises(AcceptanceArtifactError, match=message):
        AcceptanceArtifactVerifier().verify(root)
