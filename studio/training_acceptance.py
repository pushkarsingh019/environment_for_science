"""Fail-closed evidence verifier for the bounded workstation Gemma acceptance run."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickletools
import re
import struct
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from environments.eeg.curriculum import (
    load_development_scenario_set,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    RunSnapshot,
    validate_completed_run_snapshot,
)

PRIMARY_MODEL: Final = "google/gemma-4-E4B-it"
PRIMARY_MODEL_REVISION: Final = "ee0ef6023621cff504d758262d4e04895a5af4a2"
FALLBACK_MODEL: Final = "google/gemma-4-E2B-it"
FALLBACK_MODEL_REVISION: Final = "3e22461f65e89153144f8adb70e3b8c2cc9845a7"
FINAL_SERVED_ADAPTER: Final = "proof-final"
LORA_TARGET_REGEX: Final = (
    r"^model\.language_model\.layers\..*\."
    r"(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
)
STACK_PINS: Final = {
    "prime_rl_revision": "1e756307ae7b29c31fd202e6fac9afd7e23db18b",
    "verifiers_revision": "4bcb48e55a35c199d9d2f9722060fda627306aa3",
    "renderer_revision": "f770dcaa362e3a6a13a96f039741b3b84ca4114e",
    "transformers_version": "5.6.2",
    "pytorch_version": "2.11.0+cu128",
    "vllm_version": "0.26.0+cu129",
    "vllm_router_version": "0.2.0",
    "prime_lock_digest": (
        "44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
    ),
    "compatibility_patch_digest": (
        "5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
    ),
}
_TRAINING_PACKAGE_DIGEST: Final = (
    "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
)
_DEVELOPMENT_PACKAGE_DIGEST: Final = (
    "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^training-acceptance-[a-z0-9]{8,64}$")
_LANGUAGE_TENSOR_PREFIX = "model.language_model.layers."
_ALLOWED_TARGETS = {
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
}
_EXPECTED_ADAPTER_TENSORS = frozenset(
    f"model.language_model.layers.{layer}.{block}.{target}.lora_{side}.weight"
    for layer in (0, 1)
    for block, targets in (
        ("self_attn", ("q_proj", "k_proj", "v_proj", "o_proj")),
        ("mlp", ("gate_proj", "up_proj", "down_proj")),
    )
    for target in targets
    for side in ("A", "B")
)
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_ADAPTER_BYTES = 1024 * 1024 * 1024
_LEGACY_ACCEPTED_JOB_ID = "training-acceptance-a71274e2a3e04d7f865bf6c48b8fa8d3"
_LEGACY_ACCEPTED_ARTIFACT_DIGEST = (
    "sha256:cc16f8e5e6bfe261594ebda73bdd4b25a0d4ce04530fa1e28c7485a6bab26a46"
)


class AcceptanceArtifactError(ValueError):
    """Safe verification failure; never includes a supplied filesystem path."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OptimizationMetrics(_FrozenModel):
    loss: float
    gradient_norm: float
    mismatch_kl: float

    @field_validator("loss", "gradient_norm", "mismatch_kl")
    @classmethod
    def require_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("optimization metrics must be finite")
        return value


class TrainingAcceptanceEvidence(_FrozenModel):
    """Sanitized proof derived from artifacts rather than log assertions."""

    evidence_version: Literal["science-gemma-acceptance-evidence/1"]
    job_id: str = Field(pattern=r"^training-acceptance-[a-z0-9]{8,64}$")
    status: Literal["verified"]
    model: Literal["google/gemma-4-E4B-it", "google/gemma-4-E2B-it"]
    model_revision: str = Field(min_length=40, max_length=64)
    fallback_used: bool
    stack: dict[str, str]
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    training_hardware_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    inference_hardware_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    optimization_metrics: OptimizationMetrics
    adapter_tensor_count: int = Field(ge=1)
    changed_adapter_tensors: int = Field(ge=1)
    checkpoint_files: int = Field(ge=1)
    initial_adapter_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    final_adapter_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reloaded_served_identity: Literal["proof-final"]
    training_scenario_ids: tuple[str, ...] = Field(min_length=1)
    training_trace_digests: tuple[str, ...] = Field(min_length=8)
    heldout_scenario_ids: tuple[str, ...] = Field(min_length=2)
    baseline_trace_digests: tuple[str, ...] = Field(min_length=2)
    reloaded_trace_digests: tuple[str, ...] = Field(min_length=2)
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _TensorFile:
    def __init__(self, path: Path) -> None:
        try:
            size = os.stat(path, follow_symlinks=False).st_size
            if size <= 8 or size > _MAX_ADAPTER_BYTES or path.is_symlink():
                raise AcceptanceArtifactError("adapter artifact is missing or invalid")
            raw = path.read_bytes()
            header_length = struct.unpack("<Q", raw[:8])[0]
            if header_length <= 1 or 8 + header_length > len(raw):
                raise AcceptanceArtifactError("adapter tensor header is invalid")
            header = _json_bytes(raw[8 : 8 + header_length])
            if not isinstance(header, dict):
                raise AcceptanceArtifactError("adapter tensor header is invalid")
        except (OSError, struct.error) as error:
            raise AcceptanceArtifactError("adapter artifact could not be read") from error
        self.raw = raw
        self.data_start = 8 + header_length
        self.entries: dict[str, tuple[int, int]] = {}
        data_length = len(raw) - self.data_start
        for key, value in header.items():
            if key == "__metadata__":
                continue
            if not isinstance(key, str) or not isinstance(value, dict):
                raise AcceptanceArtifactError("adapter tensor header is invalid")
            offsets = value.get("data_offsets")
            shape = value.get("shape")
            dtype = value.get("dtype")
            if (
                not isinstance(offsets, list)
                or len(offsets) != 2
                or not all(
                    isinstance(item, int) and not isinstance(item, bool)
                    for item in offsets
                )
                or not isinstance(shape, list)
                or len(shape) != 2
                or not all(
                    isinstance(item, int)
                    and not isinstance(item, bool)
                    and item > 0
                    for item in shape
                )
                or dtype != "BF16"
                or (
                    key.endswith(".lora_A.weight")
                    and shape[0] != 8
                )
                or (
                    key.endswith(".lora_B.weight")
                    and shape[1] != 8
                )
            ):
                raise AcceptanceArtifactError("adapter tensor header is invalid")
            start, end = offsets
            if (
                start < 0
                or start >= end
                or end > data_length
                or end - start != shape[0] * shape[1] * 2
            ):
                raise AcceptanceArtifactError("adapter tensor offsets are invalid")
            self.entries[key] = (start, end)
        spans = sorted(self.entries.values())
        if (
            not self.entries
            or spans[0][0] != 0
            or spans[-1][1] != data_length
            or any(left[1] != right[0] for left, right in zip(spans, spans[1:]))
        ):
            raise AcceptanceArtifactError("adapter tensor data is invalid")

    def tensor_bytes(self, key: str) -> bytes:
        start, end = self.entries[key]
        return self.raw[self.data_start + start : self.data_start + end]


class AcceptanceArtifactVerifier:
    """Verify one imported, relative-path-only acceptance artifact tree."""

    def verify(self, artifact_root: Path) -> TrainingAcceptanceEvidence:
        root = Path(artifact_root).expanduser().resolve()
        receipt = self._json_file(root, "receipt.json")
        _exact_keys(
            receipt,
            {
                "receipt_version",
                "job_id",
                "stack",
                "model",
                "model_revision",
                "fallback",
                "compute_scope",
                "platform",
                "private_transport",
                "training_hardware_id",
                "inference_hardware_id",
                "configuration_digest",
                "paths",
            },
            "acceptance receipt",
        )
        receipt_version = receipt["receipt_version"]
        if receipt_version not in {
            "science-gemma-acceptance-receipt/1",
            "science-gemma-acceptance-receipt/2",
        }:
            raise AcceptanceArtifactError("acceptance receipt version is unsupported")
        canonical_traces = receipt_version == "science-gemma-acceptance-receipt/2"
        job_id = receipt["job_id"]
        if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
            raise AcceptanceArtifactError("acceptance job identity is invalid")
        if receipt["stack"] != STACK_PINS:
            raise AcceptanceArtifactError("training stack pins do not match")
        model, model_revision, fallback_used = _verified_model_fallback(receipt)
        if (
            receipt["compute_scope"] != "approved-workstations-only"
            or receipt["platform"] != "linux-x86_64"
            or receipt["private_transport"] is not True
        ):
            raise AcceptanceArtifactError("training compute boundary is invalid")
        training_hardware_id = _required_digest(receipt["training_hardware_id"], "hardware")
        inference_hardware_id = _required_digest(receipt["inference_hardware_id"], "hardware")
        if training_hardware_id == inference_hardware_id:
            raise AcceptanceArtifactError("two distinct workstation receipts are required")

        paths = receipt["paths"]
        if not isinstance(paths, dict):
            raise AcceptanceArtifactError("acceptance artifact references are invalid")
        _exact_keys(
            paths,
            {
                "run",
                "metrics",
                "configuration",
                "training_traces",
                "baseline_traces",
                "reloaded_traces",
            },
            "acceptance artifact references",
        )
        run = self._relative(root, paths["run"], directory=True)
        metrics_document = self._json_path(
            self._relative(root, paths["metrics"])
        )
        _exact_keys(
            metrics_document,
            {"loss", "gradient_norm", "mismatch_kl"},
            "optimization metrics",
        )
        try:
            metrics = OptimizationMetrics.model_validate(metrics_document)
        except ValueError as error:
            raise AcceptanceArtifactError("optimization metrics must be finite") from error

        configuration_path = self._relative(root, paths["configuration"])
        configuration = self._json_path(configuration_path)
        _exact_keys(
            configuration,
            {
                "model",
                "model_revision",
                "optimization_dtype",
                "reduction_dtype",
                "lora_target_regex",
                "max_steps",
                "training_sequence_length",
                "evaluation_context_length",
                "training_taskset_digest",
                "development_taskset_digest",
                "training_package_digest",
                "development_package_digest",
                "mechanical_jitter_weight",
                "served_adapter",
            },
            "acceptance configuration",
        )
        configuration_digest = _canonical_digest(configuration)
        if configuration_digest != _required_digest(
            receipt["configuration_digest"], "configuration"
        ):
            raise AcceptanceArtifactError("configuration digest does not match")
        _required_digest(
            configuration["training_taskset_digest"],
            "training taskset",
        )
        _required_digest(
            configuration["development_taskset_digest"],
            "development taskset",
        )
        if (
            configuration["model"] != model
            or configuration["model_revision"] != model_revision
            or configuration["optimization_dtype"] != "bfloat16"
            or configuration["reduction_dtype"] != "bfloat16"
            or configuration["lora_target_regex"] != LORA_TARGET_REGEX
            or configuration["max_steps"] != 1
            or configuration["training_sequence_length"] != 16_384
            or configuration["evaluation_context_length"] != 16_384
            or configuration["training_package_digest"]
            != _TRAINING_PACKAGE_DIGEST
            or configuration["development_package_digest"]
            != _DEVELOPMENT_PACKAGE_DIGEST
            or configuration["mechanical_jitter_weight"] != 0.001
            or configuration["served_adapter"] != FINAL_SERVED_ADAPTER
        ):
            raise AcceptanceArtifactError("acceptance configuration is not approved")

        initial_directory = run / "broadcasts/step_0"
        final_directory = run / "broadcasts/step_1"
        initial = self._adapter(initial_directory)
        final = self._adapter(final_directory)
        if any(
            not key.startswith(_LANGUAGE_TENSOR_PREFIX)
            for key in (*initial.entries, *final.entries)
        ):
            raise AcceptanceArtifactError("adapter contains a non-language-layer tensor")
        if (
            set(initial.entries) != _EXPECTED_ADAPTER_TENSORS
            or set(final.entries) != _EXPECTED_ADAPTER_TENSORS
        ):
            raise AcceptanceArtifactError(
                "adapter tensor architecture does not match the bounded LoRA"
            )
        changed = sum(
            initial.tensor_bytes(key) != final.tensor_bytes(key)
            for key in initial.entries
        )
        if changed == 0:
            raise AcceptanceArtifactError("optimizer step did not change an adapter tensor")

        checkpoint = run / "checkpoints/step_1/trainer"
        checkpoint_files = self._dcp_files(checkpoint)
        if not checkpoint_files:
            raise AcceptanceArtifactError("resumable trainer checkpoint is missing")

        training = self._trace_rows(
            self._relative(root, paths["training_traces"]),
            expected_model=model,
            label="training rollout",
            minimum_rows=8,
            require_canonical=canonical_traces,
        )
        if len(training) != 8:
            raise AcceptanceArtifactError("training rollout traces are incomplete")
        training_ids = tuple(dict.fromkeys(row["scenario_id"] for row in training))
        approved_training = load_training_scenario_set()
        if (
            not set(training_ids).issubset(approved_training.scenario_ids)
            or approved_training.identity.package_digest
            != configuration["training_package_digest"]
        ):
            raise AcceptanceArtifactError("training traces are outside the frozen split")

        baseline = self._trace_rows(
            self._relative(root, paths["baseline_traces"]),
            expected_model=model,
            label="baseline evaluation",
            require_canonical=canonical_traces,
        )
        reloaded = self._trace_rows(
            self._relative(root, paths["reloaded_traces"]),
            expected_model=FINAL_SERVED_ADAPTER,
            label="reloaded evaluation",
            require_canonical=canonical_traces,
        )
        baseline_ids = tuple(row["scenario_id"] for row in baseline)
        reloaded_ids = tuple(row["scenario_id"] for row in reloaded)
        development = load_development_scenario_set()
        if (
            baseline_ids != reloaded_ids
            or len(set(baseline_ids)) != len(baseline_ids)
            or not set(baseline_ids).issubset(development.scenario_ids)
            or development.identity.package_digest
            != configuration["development_package_digest"]
        ):
            raise AcceptanceArtifactError("held-out acceptance scenarios do not match")

        artifact_digest = _tree_digest(root)
        if (
            not canonical_traces
            and (
                job_id != _LEGACY_ACCEPTED_JOB_ID
                or artifact_digest != _LEGACY_ACCEPTED_ARTIFACT_DIGEST
            )
        ):
            raise AcceptanceArtifactError(
                "legacy acceptance evidence is not the immutable accepted artifact"
            )

        return TrainingAcceptanceEvidence(
            evidence_version="science-gemma-acceptance-evidence/1",
            job_id=job_id,
            status="verified",
            model=model,
            model_revision=model_revision,
            fallback_used=fallback_used,
            stack=dict(STACK_PINS),
            configuration_digest=configuration_digest,
            training_hardware_id=training_hardware_id,
            inference_hardware_id=inference_hardware_id,
            optimization_metrics=metrics,
            adapter_tensor_count=len(final.entries),
            changed_adapter_tensors=changed,
            checkpoint_files=len(checkpoint_files),
            initial_adapter_digest=_file_digest(
                initial_directory / "adapter_model.safetensors"
            ),
            final_adapter_digest=_file_digest(
                final_directory / "adapter_model.safetensors"
            ),
            reloaded_served_identity=FINAL_SERVED_ADAPTER,
            training_scenario_ids=training_ids,
            training_trace_digests=tuple(
                row["runtime_trace_digest"] for row in training
            ),
            heldout_scenario_ids=baseline_ids,
            baseline_trace_digests=tuple(
                row["runtime_trace_digest"] for row in baseline
            ),
            reloaded_trace_digests=tuple(
                row["runtime_trace_digest"] for row in reloaded
            ),
            artifact_digest=artifact_digest,
        )

    def _adapter(self, directory: Path) -> _TensorFile:
        try:
            if directory.is_symlink() or not directory.is_dir():
                raise AcceptanceArtifactError("stable PEFT adapter is missing")
            stable = directory / "STABLE"
            if not stable.is_file() or stable.is_symlink():
                raise AcceptanceArtifactError("stable PEFT adapter marker is missing")
            config = self._json_path(directory / "adapter_config.json")
            targets = config.get("target_modules") if isinstance(config, dict) else None
            if (
                not isinstance(targets, list)
                or not targets
                or any(not isinstance(target, str) for target in targets)
                or not set(targets).issubset(_ALLOWED_TARGETS)
                or "linear" in targets
            ):
                raise AcceptanceArtifactError("PEFT adapter target modules are invalid")
            return _TensorFile(directory / "adapter_model.safetensors")
        except OSError as error:
            raise AcceptanceArtifactError("stable PEFT adapter could not be read") from error

    def _trace_rows(
        self,
        path: Path,
        *,
        expected_model: str,
        label: str,
        minimum_rows: int = 2,
        require_canonical: bool,
    ) -> tuple[dict[str, Any], ...]:
        try:
            rows = tuple(
                _json_text(line)
                for line in path.read_text().splitlines()
                if line.strip()
            )
        except OSError as error:
            raise AcceptanceArtifactError(f"{label} traces are missing") from error
        if len(rows) < minimum_rows or any(not isinstance(row, dict) for row in rows):
            raise AcceptanceArtifactError(f"{label} traces are incomplete")
        required = {
            "scenario_id",
            "rollout_index",
            "model",
            "ok",
            "tool_calls",
            "trace_error",
            "runtime_trace_digest",
            "result_digest",
        }
        if require_canonical:
            required.update({"snapshot", "model_calls"})
        for row in rows:
            _exact_keys(row, required, f"{label} trace")
            if (
                not isinstance(row["scenario_id"], str)
                or re.fullmatch(r"eeg-[0-9a-f]{16}", row["scenario_id"])
                is None
                or not isinstance(row["rollout_index"], int)
                or isinstance(row["rollout_index"], bool)
                or row["rollout_index"] < 0
                or row["model"] != expected_model
                or row["ok"] is not True
                or not isinstance(row["tool_calls"], int)
                or isinstance(row["tool_calls"], bool)
                or row["tool_calls"] < 1
                or row["trace_error"] is not None
            ):
                raise AcceptanceArtifactError(f"{label} did not complete tool loops")
            _required_digest(row["runtime_trace_digest"], label)
            _required_digest(row["result_digest"], label)
            if require_canonical:
                _validate_canonical_trace_row(
                    row,
                    expected_model=expected_model,
                    label=label,
                )
        slots = {(row["scenario_id"], row["rollout_index"]) for row in rows}
        if len(slots) != len(rows):
            raise AcceptanceArtifactError(f"{label} trace slots are duplicated")
        return rows

    def _dcp_files(self, directory: Path) -> tuple[Path, ...]:
        try:
            if directory.is_symlink() or not directory.is_dir():
                return ()
            files = tuple(path for path in directory.rglob("*") if path.is_file())
            metadata = directory / ".metadata"
            shards = tuple(path for path in files if path.suffix == ".distcp")
            if (
                len(files) != len(shards) + 1
                or metadata not in files
                or not shards
                or any(path.is_symlink() or path.stat().st_size <= 8 for path in files)
                or not _valid_dcp_metadata(metadata)
                or any(not _valid_dcp_shard(shard) for shard in shards)
            ):
                return ()
            return files
        except OSError:
            return ()

    def _json_file(self, root: Path, reference: str) -> dict[str, Any]:
        value = self._json_path(self._relative(root, reference))
        if not isinstance(value, dict):
            raise AcceptanceArtifactError("acceptance receipt is invalid")
        return value

    @staticmethod
    def _json_path(path: Path) -> Any:
        try:
            if path.is_symlink() or os.stat(path, follow_symlinks=False).st_size > _MAX_JSON_BYTES:
                raise AcceptanceArtifactError("JSON artifact is invalid")
            return _json_bytes(path.read_bytes())
        except OSError as error:
            raise AcceptanceArtifactError("JSON artifact could not be read") from error

    @staticmethod
    def _relative(root: Path, reference: object, *, directory: bool = False) -> Path:
        if not isinstance(reference, str):
            raise AcceptanceArtifactError("acceptance artifact reference is invalid")
        relative = Path(reference)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != reference
            or not reference
        ):
            raise AcceptanceArtifactError("acceptance artifact reference is invalid")
        candidate = root / relative
        try:
            candidate.resolve().relative_to(root)
            if candidate.is_symlink() or (directory and not candidate.is_dir()):
                raise AcceptanceArtifactError("acceptance artifact reference is invalid")
        except (OSError, ValueError) as error:
            raise AcceptanceArtifactError("acceptance artifact reference is invalid") from error
        return candidate


def _verified_model_fallback(
    receipt: Mapping[str, Any],
) -> tuple[Literal["google/gemma-4-E4B-it", "google/gemma-4-E2B-it"], str, bool]:
    fallback = receipt["fallback"]
    if not isinstance(fallback, dict):
        raise AcceptanceArtifactError("fallback evidence is invalid")
    _exact_keys(fallback, {"used", "reason"}, "fallback evidence")
    model = receipt["model"]
    revision = receipt["model_revision"]
    if model == PRIMARY_MODEL and revision == PRIMARY_MODEL_REVISION:
        if fallback != {"used": False, "reason": None}:
            raise AcceptanceArtifactError("primary model fallback evidence is invalid")
        return PRIMARY_MODEL, PRIMARY_MODEL_REVISION, False
    if model == FALLBACK_MODEL and revision == FALLBACK_MODEL_REVISION:
        if fallback != {"used": True, "reason": "e4b_resource_failure"}:
            raise AcceptanceArtifactError(
                "Gemma fallback requires a genuine E4B resource failure"
            )
        return FALLBACK_MODEL, FALLBACK_MODEL_REVISION, True
    raise AcceptanceArtifactError("acceptance model identity is not approved")


def _validate_canonical_trace_row(
    row: dict[str, Any],
    *,
    expected_model: str,
    label: str,
) -> None:
    try:
        snapshot = RunSnapshot.model_validate(row["snapshot"])
        validate_completed_run_snapshot(snapshot)
        model_calls = row["model_calls"]
        if not isinstance(model_calls, list) or len(model_calls) < 2:
            raise ValueError("model call lineage is incomplete")
        for ordinal, call in enumerate(model_calls, start=1):
            if not isinstance(call, dict):
                raise ValueError("model call lineage is malformed")
            _exact_keys(
                call,
                {
                    "ordinal",
                    "model",
                    "finish_reason",
                    "input_tokens",
                    "output_tokens",
                },
                f"{label} model call",
            )
            if (
                call["ordinal"] != ordinal
                or not _acceptance_call_model_matches(
                    call["model"],
                    expected_model=expected_model,
                    label=label,
                )
                or not isinstance(call["finish_reason"], str)
                or not call["finish_reason"]
                or any(
                    not isinstance(call[name], int)
                    or isinstance(call[name], bool)
                    or call[name] < 0
                    for name in ("input_tokens", "output_tokens")
                )
            ):
                raise ValueError("model call lineage is invalid")
        action_count = sum(event.type == "action" for event in snapshot.trace)
        if (
            snapshot.scenario_id != row["scenario_id"]
            or snapshot.trace_digest != row["runtime_trace_digest"]
            or snapshot.result_digest != row["result_digest"]
            or len(model_calls) != action_count
            or action_count not in {row["tool_calls"], row["tool_calls"] + 1}
        ):
            raise ValueError("canonical snapshot does not match its native trace")
        scenario_set = (
            load_training_scenario_set()
            if label == "training rollout"
            else load_development_scenario_set()
        )
        if snapshot.scenario_id not in scenario_set.scenario_ids:
            raise ValueError("canonical snapshot is outside the frozen split")
        runtime = EnvironmentRuntime(
            EegEnvironmentModule(scenario_set.environment_bundle)
        )
        current = runtime.start(snapshot.scenario_id, snapshot.policy_agent)
        for event in snapshot.trace:
            if event.type == "action" and event.action is not None:
                current = runtime.apply_action(
                    current.run_id,
                    EnvironmentAction.model_validate(event.action),
                )
        result = snapshot.verifier_result
        if result is None:
            raise ValueError("canonical snapshot has no verifier result")
        if result.outcome_category == "incomplete":
            reason = result.evidence.get("termination_reason")
            if reason not in {
                "model_ended_before_terminal",
                "output_budget_exhausted",
                "turn_budget_exhausted",
                "tool_call_budget_exhausted",
            }:
                raise ValueError("canonical incomplete reason is invalid")
            replayed = runtime.finalize_incomplete(
                current.run_id,
                termination_reason=cast(Any, reason),
            )
        else:
            replayed = runtime.verify(current.run_id)
        if replayed.model_dump(exclude={"run_id"}) != snapshot.model_dump(
            exclude={"run_id"}
        ):
            raise ValueError("canonical snapshot does not replay")
    except (KeyError, TypeError, ValueError) as error:
        raise AcceptanceArtifactError(
            f"{label} canonical evidence is invalid"
        ) from error


def _acceptance_call_model_matches(
    value: object,
    *,
    expected_model: str,
    label: str,
) -> bool:
    if not isinstance(value, str):
        return False
    if label == "training rollout":
        return value == "r8-a16.0"
    if expected_model == FINAL_SERVED_ADAPTER:
        return value == FINAL_SERVED_ADAPTER
    revision = (
        PRIMARY_MODEL_REVISION
        if expected_model == PRIMARY_MODEL
        else FALLBACK_MODEL_REVISION
    )
    suffix = f"{expected_model.rsplit('/', 1)[-1]}-{revision}"
    return value == expected_model or value.endswith(suffix)


def _valid_dcp_metadata(path: Path) -> bool:
    try:
        contents = path.read_bytes()
        operations = tuple(pickletools.genops(contents))
    except (OSError, ValueError):
        return False
    required = (
        b"torch.distributed.checkpoint.metadata",
        b"Metadata",
        b"TensorStorageMetadata",
        b"StorageInfo",
    )
    return (
        bool(operations)
        and operations[-1][0].name == "STOP"
        and all(token in contents for token in required)
    )


def _valid_dcp_shard(path: Path) -> bool:
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as archive:
            names = {item.filename for item in archive.infolist()}
            required = {
                "archive/data.pkl",
                "archive/.format_version",
                "archive/byteorder",
                "archive/version",
            }
            if (
                not required.issubset(names)
                or not any(name.startswith("archive/data/") for name in names)
                or any(
                    name.startswith("/") or ".." in Path(name).parts
                    for name in names
                )
            ):
                return False
            data_pickle = archive.read("archive/data.pkl")
            operations = tuple(pickletools.genops(data_pickle))
            return bool(operations) and operations[-1][0].name == "STOP"
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AcceptanceArtifactError(f"{label} fields are invalid")


def _required_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AcceptanceArtifactError(f"{label} digest is invalid")
    return value


def _json_bytes(value: bytes) -> Any:
    try:
        return json.loads(
            value,
            parse_constant=lambda _constant: (_raise_nonfinite()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceArtifactError("JSON artifact is invalid") from error


def _json_text(value: str) -> Any:
    try:
        return json.loads(
            value,
            parse_constant=lambda _constant: (_raise_nonfinite()),
        )
    except json.JSONDecodeError as error:
        raise AcceptanceArtifactError("JSONL artifact is invalid") from error


def _raise_nonfinite() -> None:
    raise AcceptanceArtifactError("numeric evidence must be finite")


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _file_digest(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as error:
        raise AcceptanceArtifactError("artifact digest could not be computed") from error


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    try:
        files = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
        if not files or any(path.is_symlink() for path in files):
            raise AcceptanceArtifactError("acceptance artifact tree is incomplete")
        for path in files:
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(struct.pack("<Q", len(relative)))
            digest.update(relative)
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
    except OSError as error:
        raise AcceptanceArtifactError("acceptance artifact digest could not be computed") from error
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "AcceptanceArtifactError",
    "AcceptanceArtifactVerifier",
    "FALLBACK_MODEL",
    "FALLBACK_MODEL_REVISION",
    "FINAL_SERVED_ADAPTER",
    "LORA_TARGET_REGEX",
    "OptimizationMetrics",
    "PRIMARY_MODEL",
    "PRIMARY_MODEL_REVISION",
    "STACK_PINS",
    "TrainingAcceptanceEvidence",
]
