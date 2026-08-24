"""Fail-closed verifier for full EEG curriculum training and evaluation evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from environments.eeg.curriculum import (
    load_development_scenario_set,
    load_training_scenario_set,
)

from .curriculum_analysis import (
    HeldOutEvaluationEvidence,
    PairedBootstrapAnalysis,
    paired_bootstrap_success,
)
from .training_acceptance import STACK_PINS, _TensorFile

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LANGUAGE_PREFIX = "model.language_model.layers."


class CurriculumEvidenceError(ValueError):
    """Sanitized curriculum evidence failure with no supplied host path."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CurriculumRunConfiguration(_FrozenModel):
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    prime_revision: Literal["1e756307ae7b29c31fd202e6fac9afd7e23db18b"]
    prime_lock_digest: Literal[
        "sha256:44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
    ]
    compatibility_patch_digest: Literal[
        "sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
    ]
    verifiers_revision: Literal["4bcb48e55a35c199d9d2f9722060fda627306aa3"]
    renderer_revision: Literal["f770dcaa362e3a6a13a96f039741b3b84ca4114e"]
    model: Literal["google/gemma-4-E4B-it"]
    model_revision: Literal["ee0ef6023621cff504d758262d4e04895a5af4a2"]
    training_taskset_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    development_taskset_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    heldout_taskset_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    training_package_digest: Literal[
        "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
    ]
    development_package_digest: Literal[
        "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
    ]
    heldout_package_digest: Literal[
        "sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7"
    ]
    max_steps: Literal[96]
    group_size: Literal[4]
    sequence_length: Literal[16384]
    evaluation_context_length: Literal[16384]
    max_completion_tokens: Literal[256]
    optimization_dtype: Literal["bfloat16"]
    reduction_dtype: Literal["bfloat16"]
    lora_target_regex: Literal[
        "^model\\.language_model\\.layers\\..*\\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
    ]
    curriculum_order: Literal["standard-source-order"]
    provider_sampling_seed: None
    adapter_selection: Literal["final-step-predeclared"]


class CurriculumOptimizationEvidence(_FrozenModel):
    steps: Literal[96]
    finite_loss_steps: Literal[96]
    finite_gradient_steps: Literal[96]
    finite_mismatch_kl_steps: Literal[96]
    final_loss: float
    final_gradient_norm: float
    final_mismatch_kl: float

    @model_validator(mode="after")
    def finite_final_metrics(self) -> CurriculumOptimizationEvidence:
        if not all(
            math.isfinite(value)
            for value in (
                self.final_loss,
                self.final_gradient_norm,
                self.final_mismatch_kl,
            )
        ):
            raise ValueError("final optimization metrics must be finite")
        return self


class CurriculumTrainingEvidence(_FrozenModel):
    evidence_version: Literal["eeg-curriculum-training-evidence/1"]
    status: Literal["verified"]
    result_id: str = Field(pattern=r"^eeg-training-result-[a-z0-9]{8,64}$")
    configuration: CurriculumRunConfiguration
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    stack: dict[str, str]
    training_scenario_ids: tuple[str, ...] = Field(min_length=96, max_length=96)
    training_rollouts: int = Field(ge=384)
    training_trace_digests: tuple[str, ...] = Field(min_length=384)
    sampled_tokens: int = Field(ge=1)
    trainable_mask_tokens: int = Field(ge=1)
    aligned_logprob_tokens: int = Field(ge=1)
    reward_records: int = Field(ge=384)
    optimization: CurriculumOptimizationEvidence
    adapter_tensor_count: int = Field(ge=1)
    changed_adapter_tensors: int = Field(ge=1)
    final_adapter_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    checkpoint_files: int = Field(ge=1)
    development_scenario_ids: tuple[str, ...] = Field(min_length=32, max_length=32)
    base_development_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trained_development_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_heldout: HeldOutEvaluationEvidence
    trained_heldout: HeldOutEvaluationEvidence
    paired_bootstrap: PairedBootstrapAnalysis
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_split_and_claim_provenance(self) -> CurriculumTrainingEvidence:
        if (
            len(self.training_trace_digests) != self.training_rollouts
            or self.configuration_digest != _canonical_digest(
                self.configuration.model_dump(mode="json")
            )
            or self.paired_bootstrap.paired_outcomes_digest
            != paired_bootstrap_success(
                self.base_heldout.scenario_success,
                self.trained_heldout.scenario_success,
            ).paired_outcomes_digest
        ):
            raise ValueError("curriculum evidence provenance is inconsistent")
        return self


def verify_curriculum_training_evidence(
    *,
    result_id: str,
    run_directory: Path,
    base_development_traces: Path,
    trained_development_traces: Path,
    base_heldout: HeldOutEvaluationEvidence,
    trained_heldout: HeldOutEvaluationEvidence,
    configuration: CurriculumRunConfiguration,
    base_call_model: str,
    trained_call_model: str = "eeg-curriculum-final",
) -> CurriculumTrainingEvidence:
    """Independently derive one full training result from native artifacts."""

    run = _directory(run_directory, "curriculum training run")
    training_rows = _training_rows(
        run,
        expected_call_model=base_call_model,
    )
    approved_training = load_training_scenario_set()
    scenario_counts = Counter(row["scenario_id"] for row in training_rows)
    if (
        set(scenario_counts) != set(approved_training.scenario_ids)
        or min(scenario_counts.values(), default=0) < 4
        or approved_training.identity.package_digest
        != configuration.training_package_digest
    ):
        raise CurriculumEvidenceError(
            "training traces do not cover the immutable 96-scenario split"
        )

    base_development = _evaluation_rows(
        base_development_traces,
        expected_call_model=base_call_model,
        expected_ids=load_development_scenario_set().scenario_ids,
        label="base development",
    )
    trained_development = _evaluation_rows(
        trained_development_traces,
        expected_call_model=trained_call_model,
        expected_ids=load_development_scenario_set().scenario_ids,
        label="trained development",
    )
    if [row["scenario_id"] for row in base_development] != [
        row["scenario_id"] for row in trained_development
    ]:
        raise CurriculumEvidenceError("development evaluation scenarios do not match")

    initial_path = run / "broadcasts/step_0/adapter_model.safetensors"
    final_path = run / "broadcasts/step_96/adapter_model.safetensors"
    initial = _TensorFile(initial_path)
    final = _TensorFile(final_path)
    if set(initial.entries) != set(final.entries) or any(
        not key.startswith(_LANGUAGE_PREFIX) for key in final.entries
    ):
        raise CurriculumEvidenceError("final adapter tensor structure is invalid")
    changed = sum(
        initial.tensor_bytes(key) != final.tensor_bytes(key)
        for key in initial.entries
    )
    if changed < 1:
        raise CurriculumEvidenceError("curriculum training did not change the adapter")
    _stable_adapter(run / "broadcasts/step_96")
    checkpoint_files = _checkpoint_files(run / "checkpoints/step_96/trainer")
    optimization = _optimization(run / "metrics.jsonl")
    paired = paired_bootstrap_success(
        base_heldout.scenario_success,
        trained_heldout.scenario_success,
    )
    configuration_digest = _canonical_digest(configuration.model_dump(mode="json"))
    artifact_document = {
        "configuration_digest": configuration_digest,
        "training_trace_digests": [row["trace_digest"] for row in training_rows],
        "base_development": [row["trace_digest"] for row in base_development],
        "trained_development": [row["trace_digest"] for row in trained_development],
        "base_heldout_ledger": base_heldout.report.attempt_ledger_digest,
        "trained_heldout_ledger": trained_heldout.report.attempt_ledger_digest,
        "adapter_digest": _file_digest(final_path),
        "paired_outcomes_digest": paired.paired_outcomes_digest,
    }
    return CurriculumTrainingEvidence(
        evidence_version="eeg-curriculum-training-evidence/1",
        status="verified",
        result_id=result_id,
        configuration=configuration,
        configuration_digest=configuration_digest,
        stack=dict(STACK_PINS),
        training_scenario_ids=tuple(sorted(scenario_counts)),
        training_rollouts=len(training_rows),
        training_trace_digests=tuple(
            row["trace_digest"] for row in training_rows
        ),
        sampled_tokens=sum(row["sampled_tokens"] for row in training_rows),
        trainable_mask_tokens=sum(row["mask_tokens"] for row in training_rows),
        aligned_logprob_tokens=sum(row["logprob_tokens"] for row in training_rows),
        reward_records=sum(row["reward_records"] for row in training_rows),
        optimization=optimization,
        adapter_tensor_count=len(final.entries),
        changed_adapter_tensors=changed,
        final_adapter_digest=_file_digest(final_path),
        checkpoint_files=len(checkpoint_files),
        development_scenario_ids=tuple(
            row["scenario_id"] for row in base_development
        ),
        base_development_trace_digest=_rows_digest(base_development),
        trained_development_trace_digest=_rows_digest(trained_development),
        base_heldout=base_heldout,
        trained_heldout=trained_heldout,
        paired_bootstrap=paired,
        artifact_digest=_canonical_digest(artifact_document),
    )


def _training_rows(run: Path, *, expected_call_model: str) -> list[dict[str, Any]]:
    paths = tuple(run.glob("rollouts/step_*/train/all/traces.jsonl"))
    documents: list[dict[str, Any]] = []
    for path in paths:
        documents.extend(_jsonl(path, "training"))
    if len(paths) != 96 or len(documents) < 384:
        raise CurriculumEvidenceError("training rollout artifacts are incomplete")
    return [
        _native_row(
            document,
            expected_call_model=expected_call_model,
            label="training",
            require_terminal=False,
            require_token_metadata=True,
        )
        for document in documents
    ]


def _evaluation_rows(
    path: Path,
    *,
    expected_call_model: str,
    expected_ids: tuple[str, ...],
    label: str,
) -> list[dict[str, Any]]:
    rows = [
        _native_row(
            document,
            expected_call_model=expected_call_model,
            label=label,
            require_terminal=True,
            require_token_metadata=False,
        )
        for document in _jsonl(path, label)
    ]
    rows.sort(key=lambda row: row["scenario_id"])
    if len(rows) != len(expected_ids) or {row["scenario_id"] for row in rows} != set(
        expected_ids
    ):
        raise CurriculumEvidenceError(f"{label} traces changed the frozen split")
    return rows


def _native_row(
    document: dict[str, Any],
    *,
    expected_call_model: str,
    label: str,
    require_terminal: bool,
    require_token_metadata: bool,
) -> dict[str, Any]:
    try:
        trace = document["traces"][0]
        scenario_id = document["task"]["data"]["name"]
        calls = trace["calls"]
        runtime = trace["info"]["science_environment_runtime"]
        sampled_nodes = [node for node in trace["nodes"] if node["sampled"]]
        sampled_tokens = sum(len(node["token_ids"]) for node in sampled_nodes)
        mask_tokens = sum(sum(bool(value) for value in node["mask"]) for node in sampled_nodes)
        logprob_tokens = sum(len(node["logprobs"]) for node in sampled_nodes)
        aligned = all(_aligned_training_node(node) for node in sampled_nodes)
        if (
            document["ok"] is not True
            or trace["ok"] is not True
            or trace["is_completed"] is not True
            or document["errors"]
            or trace["errors"]
            or (
                require_terminal
                and trace["stop_condition"]
                not in {"terminal", "incomplete_model_response"}
            )
            or len(calls) < 1
            or any(call.get("error") is not None for call in calls)
            or {call["model"] for call in calls} != {expected_call_model}
            or runtime["scenario_id"] != scenario_id
            or (require_token_metadata and (not sampled_nodes or not aligned))
        ):
            raise ValueError("incomplete trace")
        trace_digest = runtime["runtime_trace_digest"]
        result_digest = runtime["runtime_result_digest"]
        reward_records = len(trace["rewards"])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise CurriculumEvidenceError(
            f"{label} trace failed canonical validation"
        ) from error
    if (
        not isinstance(scenario_id, str)
        or re.fullmatch(r"eeg-[0-9a-f]{16}", scenario_id) is None
        or not isinstance(trace_digest, str)
        or _DIGEST.fullmatch(trace_digest) is None
        or not isinstance(result_digest, str)
        or _DIGEST.fullmatch(result_digest) is None
        or (require_token_metadata and (sampled_tokens < 1 or logprob_tokens < 1))
        or reward_records < 1
    ):
        raise CurriculumEvidenceError(f"{label} trace evidence is incomplete")
    return {
        "scenario_id": scenario_id,
        "trace_digest": trace_digest,
        "result_digest": result_digest,
        "sampled_tokens": sampled_tokens,
        "mask_tokens": mask_tokens,
        "logprob_tokens": logprob_tokens,
        "reward_records": reward_records,
    }


def _aligned_training_node(node: dict[str, Any]) -> bool:
    """Validate Verifiers' token/mask/logprob layout for one sampled node."""

    token_ids = node.get("token_ids")
    mask = node.get("mask")
    logprobs = node.get("logprobs")
    return (
        isinstance(token_ids, list)
        and isinstance(mask, list)
        and isinstance(logprobs, list)
        and len(token_ids) == len(mask)
        and len(logprobs) == sum(value is True for value in mask)
    )


def _optimization(path: Path) -> CurriculumOptimizationEvidence:
    rows = _jsonl(path, "optimization metrics")
    losses = [row["loss/mean"] for row in rows if "loss/mean" in row]
    gradients = [row["optim/grad_norm"] for row in rows if "optim/grad_norm" in row]
    mismatch = [
        row["mismatch_kl/all/mean"]
        for row in rows
        if "mismatch_kl/all/mean" in row
    ]
    if (
        len(losses) != 96
        or len(gradients) != 96
        or len(mismatch) != 96
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in (*losses, *gradients, *mismatch)
        )
    ):
        raise CurriculumEvidenceError("optimization metrics are incomplete or non-finite")
    return CurriculumOptimizationEvidence(
        steps=96,
        finite_loss_steps=96,
        finite_gradient_steps=96,
        finite_mismatch_kl_steps=96,
        final_loss=float(losses[-1]),
        final_gradient_norm=float(gradients[-1]),
        final_mismatch_kl=float(mismatch[-1]),
    )


def _stable_adapter(directory: Path) -> None:
    try:
        if (
            directory.is_symlink()
            or not (directory / "STABLE").is_file()
            or not (directory / "adapter_config.json").is_file()
            or not (directory / "adapter_model.safetensors").is_file()
        ):
            raise OSError("incomplete adapter")
    except OSError as error:
        raise CurriculumEvidenceError("final PEFT adapter is incomplete") from error


def _checkpoint_files(directory: Path) -> tuple[Path, ...]:
    try:
        files = tuple(path for path in directory.rglob("*") if path.is_file())
        if not files or any(path.is_symlink() or path.stat().st_size < 1 for path in files):
            raise OSError("incomplete checkpoint")
        return files
    except OSError as error:
        raise CurriculumEvidenceError("final resumable checkpoint is incomplete") from error


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("missing evidence")
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise CurriculumEvidenceError(f"{label} could not be read") from error
    if any(not isinstance(row, dict) for row in rows):
        raise CurriculumEvidenceError(f"{label} is malformed")
    return rows


def _directory(path: Path, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if path.is_symlink() or not resolved.is_dir():
        raise CurriculumEvidenceError(f"{label} is missing")
    return resolved


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _file_digest(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as error:
        raise CurriculumEvidenceError("adapter artifact could not be read") from error


def _rows_digest(rows: list[dict[str, Any]]) -> str:
    return _canonical_digest(rows)


__all__ = [
    "CurriculumEvidenceError",
    "CurriculumOptimizationEvidence",
    "CurriculumRunConfiguration",
    "CurriculumTrainingEvidence",
    "verify_curriculum_training_evidence",
]
