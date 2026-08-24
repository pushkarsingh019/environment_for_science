"""Verify the real EEG curriculum run and emit sanitized evidence/comparison JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from studio.curriculum_analysis import (
    CurriculumAnalysisError,
    import_native_heldout_evaluation,
)
from studio.curriculum_training_evidence import (
    CurriculumEvidenceError,
    CurriculumRunConfiguration,
    verify_curriculum_training_evidence,
)
from studio.model_comparison import real_model_comparison
from studio.policy_evaluation.gemini_interactions import gemini_credential_ready
from studio.policy_evaluation.openai_responses import openai_credential_ready
from studio.training_acceptance import AcceptanceArtifactError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--base-development", type=Path, required=True)
    parser.add_argument("--trained-development", type=Path, required=True)
    parser.add_argument("--base-heldout", type=Path, required=True)
    parser.add_argument("--trained-heldout", type=Path, required=True)
    parser.add_argument("--base-call-model", required=True)
    parser.add_argument("--training-call-model", default="r8-a16.0")
    parser.add_argument("--trained-call-model", default="eeg-curriculum-final")
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--training-taskset-digest", required=True)
    parser.add_argument("--development-taskset-digest", required=True)
    parser.add_argument("--heldout-taskset-digest", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--comparison-output", type=Path, required=True)
    args = parser.parse_args()
    configuration = CurriculumRunConfiguration(
        code_revision=args.code_revision,
        prime_revision="1e756307ae7b29c31fd202e6fac9afd7e23db18b",
        prime_lock_digest=(
            "sha256:44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
        ),
        compatibility_patch_digest=(
            "sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
        ),
        verifiers_revision="4bcb48e55a35c199d9d2f9722060fda627306aa3",
        renderer_revision="f770dcaa362e3a6a13a96f039741b3b84ca4114e",
        model="google/gemma-4-E4B-it",
        model_revision="ee0ef6023621cff504d758262d4e04895a5af4a2",
        training_taskset_digest=args.training_taskset_digest,
        development_taskset_digest=args.development_taskset_digest,
        heldout_taskset_digest=args.heldout_taskset_digest,
        training_package_digest=(
            "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
        ),
        development_package_digest=(
            "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
        ),
        heldout_package_digest=(
            "sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7"
        ),
        max_steps=96,
        group_size=4,
        sequence_length=16_384,
        evaluation_context_length=16_384,
        training_max_completion_tokens=128,
        training_max_turns=65,
        training_rollout_timeout_seconds=900,
        training_temperature=1.0,
        evaluation_max_completion_tokens=256,
        evaluation_max_turns=65,
        evaluation_max_accepted_tool_calls=64,
        evaluation_max_provider_tool_calls=64,
        evaluation_rollout_timeout_seconds=900,
        evaluation_temperature=0.0,
        trainer_language_layers=2,
        optimization_dtype="bfloat16",
        reduction_dtype="bfloat16",
        lora_target_regex=(
            "^model\\.language_model\\.layers\\..*\\."
            "(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
        ),
        curriculum_order="standard-source-order",
        provider_sampling_seed=None,
        adapter_selection="final-step-predeclared",
    )
    base_configuration_digest = _digest(
        {
            "evaluation": "held_out",
            "model": "google/gemma-4-E4B-it",
            "adapter": None,
            "taskset": args.heldout_taskset_digest,
            "context": 16_384,
            "max_completion_tokens": 256,
            "max_turns": 65,
            "max_accepted_tool_calls": 64,
            "max_provider_tool_calls": 64,
            "rollout_timeout_seconds": 900,
            "temperature": 0.0,
        }
    )
    trained_configuration_digest = _digest(
        {
            "evaluation": "held_out",
            "model": "google/gemma-4-E4B-it",
            "adapter": "eeg-curriculum-final",
            "taskset": args.heldout_taskset_digest,
            "context": 16_384,
            "max_completion_tokens": 256,
            "max_turns": 65,
            "max_accepted_tool_calls": 64,
            "max_provider_tool_calls": 64,
            "rollout_timeout_seconds": 900,
            "temperature": 0.0,
        }
    )
    try:
        base = import_native_heldout_evaluation(
            traces_path=args.base_heldout,
            artifact_root=args.artifact_root / "base-heldout-ledger",
            model_configuration_digest=base_configuration_digest,
            expected_call_model=args.base_call_model,
        )
        trained = import_native_heldout_evaluation(
            traces_path=args.trained_heldout,
            artifact_root=args.artifact_root / "trained-heldout-ledger",
            model_configuration_digest=trained_configuration_digest,
            expected_call_model=args.trained_call_model,
        )
        evidence = verify_curriculum_training_evidence(
            result_id=args.result_id,
            run_directory=args.run_dir,
            base_development_traces=args.base_development,
            trained_development_traces=args.trained_development,
            base_heldout=base,
            trained_heldout=trained,
            configuration=configuration,
            base_call_model=args.base_call_model,
            training_call_model=args.training_call_model,
            trained_call_model=args.trained_call_model,
        )
        comparison = real_model_comparison(
            base,
            trained,
            openai_credential_ready=openai_credential_ready(),
            gemini_credential_ready=gemini_credential_ready(),
        )
    except (
        AcceptanceArtifactError,
        CurriculumAnalysisError,
        CurriculumEvidenceError,
        ValueError,
    ) as error:
        print(json.dumps({"status": "failed", "summary": str(error)}, sort_keys=True))
        return 1
    _write(args.evidence_output, evidence.model_dump(mode="json"))
    _write(args.comparison_output, comparison.model_dump(mode="json"))
    print(
        json.dumps(
            {
                "artifact_digest": evidence.artifact_digest,
                "comparison_id": comparison.comparison_id,
                "result_id": evidence.result_id,
                "status": "verified",
                "training_claim": comparison.training_claim,
            },
            sort_keys=True,
        )
    )
    return 0


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
