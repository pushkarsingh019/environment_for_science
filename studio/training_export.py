"""Sanitize native prime-rl artifacts into the Ticket 10 acceptance contract."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from .training_acceptance import (
    FALLBACK_MODEL,
    FALLBACK_MODEL_REVISION,
    FINAL_SERVED_ADAPTER,
    LORA_TARGET_REGEX,
    PRIMARY_MODEL,
    PRIMARY_MODEL_REVISION,
    STACK_PINS,
    AcceptanceArtifactError,
    AcceptanceArtifactVerifier,
    TrainingAcceptanceEvidence,
    _canonical_digest,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^training-acceptance-[a-z0-9]{8,64}$")
_TRAINING_PACKAGE_DIGEST = (
    "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
)
_DEVELOPMENT_PACKAGE_DIGEST = (
    "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
)
_TRAINING_SERVED_ADAPTER = "r8-a16.0"


class NativeAcceptanceExporter:
    """One deep export seam: inspect native evidence, copy artifacts, then verify."""

    def export(
        self,
        *,
        job_id: str,
        run_directory: Path,
        baseline_traces: Path,
        reloaded_traces: Path,
        destination: Path,
        training_hardware_id: str,
        inference_hardware_id: str,
        training_taskset_digest: str,
        development_taskset_digest: str,
        model: Literal[
            "google/gemma-4-E4B-it", "google/gemma-4-E2B-it"
        ] = PRIMARY_MODEL,
    ) -> TrainingAcceptanceEvidence:
        if _JOB_ID.fullmatch(job_id) is None:
            raise AcceptanceArtifactError("acceptance job identity is invalid")
        for value in (
            training_hardware_id,
            inference_hardware_id,
            training_taskset_digest,
            development_taskset_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise AcceptanceArtifactError("export receipt digest is invalid")
        if training_hardware_id == inference_hardware_id:
            raise AcceptanceArtifactError(
                "two distinct workstation receipts are required"
            )
        model_revision, fallback = _model_configuration(model)
        run = _safe_directory(run_directory, "native training run")
        destination = Path(destination).expanduser().resolve()
        _prepare_destination(destination)

        training_rows = _native_rows(
            run / "rollouts/step_1/train/effective/traces.jsonl",
            expected_model=_TRAINING_SERVED_ADAPTER,
            normalized_model=model,
            expected_count=8,
            label="training rollout",
            require_terminal=False,
        )
        baseline_rows = _native_rows(
            baseline_traces,
            expected_model=model,
            normalized_model=model,
            expected_count=2,
            label="baseline evaluation",
        )
        reloaded_rows = _native_rows(
            reloaded_traces,
            expected_model=FINAL_SERVED_ADAPTER,
            normalized_model=FINAL_SERVED_ADAPTER,
            expected_count=2,
            label="reloaded evaluation",
        )
        if [row["scenario_id"] for row in baseline_rows] != [
            row["scenario_id"] for row in reloaded_rows
        ]:
            raise AcceptanceArtifactError(
                "held-out acceptance scenarios do not match"
            )
        metrics = _optimization_metrics(run / "metrics.jsonl")

        exported_run = destination / "run"
        for step in ("step_0", "step_1"):
            _copy_adapter(
                run / f"broadcasts/{step}",
                exported_run / f"broadcasts/{step}",
            )
        _copy_checkpoint(
            run / "checkpoints/step_1/trainer",
            exported_run / "checkpoints/step_1/trainer",
        )
        evaluations = destination / "evals"
        evaluations.mkdir(mode=0o700)
        _write_jsonl(evaluations / "training.jsonl", training_rows)
        _write_jsonl(evaluations / "baseline.jsonl", baseline_rows)
        _write_jsonl(evaluations / "reloaded.jsonl", reloaded_rows)
        _write_json(destination / "optimization-metrics.json", metrics)

        configuration = {
            "model": model,
            "model_revision": model_revision,
            "optimization_dtype": "bfloat16",
            "reduction_dtype": "bfloat16",
            "lora_target_regex": LORA_TARGET_REGEX,
            "max_steps": 1,
            "training_sequence_length": 16_384,
            "evaluation_context_length": 16_384,
            "training_taskset_digest": training_taskset_digest,
            "development_taskset_digest": development_taskset_digest,
            "training_package_digest": _TRAINING_PACKAGE_DIGEST,
            "development_package_digest": _DEVELOPMENT_PACKAGE_DIGEST,
            "mechanical_jitter_weight": 0.001,
            "served_adapter": FINAL_SERVED_ADAPTER,
        }
        _write_json(destination / "acceptance-config.json", configuration)
        receipt = {
            "receipt_version": "science-gemma-acceptance-receipt/1",
            "job_id": job_id,
            "stack": dict(STACK_PINS),
            "model": model,
            "model_revision": model_revision,
            "fallback": fallback,
            "compute_scope": "approved-workstations-only",
            "platform": "linux-x86_64",
            "private_transport": True,
            "training_hardware_id": training_hardware_id,
            "inference_hardware_id": inference_hardware_id,
            "configuration_digest": _canonical_digest(configuration),
            "paths": {
                "run": "run",
                "metrics": "optimization-metrics.json",
                "configuration": "acceptance-config.json",
                "training_traces": "evals/training.jsonl",
                "baseline_traces": "evals/baseline.jsonl",
                "reloaded_traces": "evals/reloaded.jsonl",
            },
        }
        _write_json(destination / "receipt.json", receipt)
        return AcceptanceArtifactVerifier().verify(destination)


def _native_rows(
    path: Path,
    *,
    expected_model: str,
    normalized_model: str,
    expected_count: int,
    label: str,
    require_terminal: bool = True,
) -> list[dict[str, Any]]:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("invalid native trace")
        documents = [
            json.loads(line)
            for line in path.read_text().splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceArtifactError(f"{label} traces are missing") from error
    if len(documents) != expected_count:
        raise AcceptanceArtifactError(f"{label} traces are incomplete")
    rollout_indices: defaultdict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    for document in documents:
        try:
            traces = document["traces"]
            trace = traces[0]
            scenario_id = document["task"]["data"]["name"]
            calls = trace["calls"]
            nodes = trace["nodes"]
            runtime = trace["info"]["science_environment_runtime"]
            roles = [node["message"]["role"] for node in nodes]
            call_models = {call["model"] for call in calls}
            trace_error = None
            if (
                document["ok"] is not True
                or trace["ok"] is not True
                or trace["is_completed"] is not True
                or document["errors"]
                or trace["errors"]
                or (
                    require_terminal
                    and trace["stop_condition"] != "terminal"
                )
                or len(calls) < 2
                or any(call.get("error") is not None for call in calls)
                or roles.count("tool") < 1
                or runtime["scenario_id"] != scenario_id
            ):
                trace_error = "native trace did not complete a canonical tool loop"
            if not _native_model_matches(call_models, expected_model):
                trace_error = "native trace model identity does not match"
            runtime_trace_digest = runtime["runtime_trace_digest"]
            result_digest = runtime["runtime_result_digest"]
        except (KeyError, IndexError, TypeError) as error:
            raise AcceptanceArtifactError(
                f"{label} traces are malformed"
            ) from error
        if (
            not isinstance(scenario_id, str)
            or re.fullmatch(r"eeg-[0-9a-f]{16}", scenario_id) is None
            or trace_error is not None
            or not isinstance(runtime_trace_digest, str)
            or _DIGEST.fullmatch(runtime_trace_digest) is None
            or not isinstance(result_digest, str)
            or _DIGEST.fullmatch(result_digest) is None
        ):
            raise AcceptanceArtifactError(
                f"{label} did not complete tool loops"
            )
        rollout_index = rollout_indices[scenario_id]
        rollout_indices[scenario_id] += 1
        rows.append(
            {
                "scenario_id": scenario_id,
                "rollout_index": rollout_index,
                "model": normalized_model,
                "ok": True,
                "tool_calls": roles.count("tool"),
                "trace_error": None,
                "runtime_trace_digest": runtime_trace_digest,
                "result_digest": result_digest,
            }
        )
    return sorted(rows, key=lambda row: (row["scenario_id"], row["rollout_index"]))


def _native_model_matches(call_models: set[object], expected: str) -> bool:
    if not call_models:
        return False
    if expected in {FINAL_SERVED_ADAPTER, _TRAINING_SERVED_ADAPTER}:
        return call_models == {expected}
    revision = (
        PRIMARY_MODEL_REVISION if expected == PRIMARY_MODEL else FALLBACK_MODEL_REVISION
    )
    suffix = f"{expected.rsplit('/', 1)[1]}-{revision}"
    return all(
        isinstance(item, str)
        and (item == expected or item.endswith(suffix))
        for item in call_models
    )


def _optimization_metrics(path: Path) -> dict[str, float]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text().splitlines()
            if line.strip()
        ]
        values = {
            "loss": next(row["loss/mean"] for row in rows if "loss/mean" in row),
            "gradient_norm": next(
                row["optim/grad_norm"]
                for row in rows
                if "optim/grad_norm" in row
            ),
            "mismatch_kl": next(
                row["mismatch_kl/all/mean"]
                for row in rows
                if "mismatch_kl/all/mean" in row
            ),
        }
    except (OSError, json.JSONDecodeError, KeyError, StopIteration) as error:
        raise AcceptanceArtifactError(
            "native optimization metrics are incomplete"
        ) from error
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        for value in values.values()
    ):
        raise AcceptanceArtifactError("optimization metrics must be finite")
    return {key: float(value) for key, value in values.items()}


def _copy_adapter(source: Path, destination: Path) -> None:
    source = _safe_directory(source, "native adapter")
    destination.mkdir(mode=0o700, parents=True)
    for name in ("STABLE", "adapter_config.json", "adapter_model.safetensors"):
        item = source / name
        if item.is_symlink() or not item.is_file():
            raise AcceptanceArtifactError("native adapter is incomplete")
        shutil.copyfile(item, destination / name)


def _copy_checkpoint(source: Path, destination: Path) -> None:
    source = _safe_directory(source, "native checkpoint")
    files = [path for path in source.rglob("*") if path.is_file()]
    if not files or any(path.is_symlink() or path.stat().st_size <= 0 for path in files):
        raise AcceptanceArtifactError("native checkpoint is incomplete")
    for item in files:
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(item, target)


def _safe_directory(path: Path, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if path.is_symlink() or not resolved.is_dir():
        raise AcceptanceArtifactError(f"{label} is missing")
    return resolved


def _prepare_destination(destination: Path) -> None:
    if destination.is_symlink() or destination.exists():
        raise AcceptanceArtifactError("acceptance export destination must be new")
    try:
        destination.mkdir(mode=0o700, parents=True)
        os.chmod(destination, 0o700)
    except OSError as error:
        raise AcceptanceArtifactError(
            "acceptance export destination could not be created"
        ) from error


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
            for row in rows
        )
    )


def _model_configuration(
    model: str,
) -> tuple[str, dict[str, object]]:
    if model == PRIMARY_MODEL:
        return PRIMARY_MODEL_REVISION, {"used": False, "reason": None}
    if model == FALLBACK_MODEL:
        return FALLBACK_MODEL_REVISION, {
            "used": True,
            "reason": "e4b_resource_failure",
        }
    raise AcceptanceArtifactError("acceptance model identity is not approved")


__all__ = ["NativeAcceptanceExporter"]
