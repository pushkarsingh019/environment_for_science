"""Import sealed native held-out traces and emit a sanitized real comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.curriculum_analysis import (
    CurriculumAnalysisError,
    import_native_heldout_evaluation,
)
from studio.model_comparison import real_model_comparison
from studio.policy_evaluation.gemini_interactions import gemini_credential_ready
from studio.policy_evaluation.openai_responses import openai_credential_ready


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-traces", type=Path, required=True)
    parser.add_argument("--trained-traces", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-configuration-digest", required=True)
    parser.add_argument("--trained-configuration-digest", required=True)
    parser.add_argument("--base-call-model", required=True)
    parser.add_argument("--trained-call-model", default="eeg-curriculum-final")
    parser.add_argument("--training-result-id", required=True)
    parser.add_argument("--training-artifact-digest", required=True)
    parser.add_argument("--trained-adapter-digest", required=True)
    args = parser.parse_args()
    try:
        base = import_native_heldout_evaluation(
            traces_path=args.base_traces,
            artifact_root=args.artifact_root / "base",
            model_configuration_digest=args.base_configuration_digest,
            expected_call_model=args.base_call_model,
        )
        trained = import_native_heldout_evaluation(
            traces_path=args.trained_traces,
            artifact_root=args.artifact_root / "trained",
            model_configuration_digest=args.trained_configuration_digest,
            expected_call_model=args.trained_call_model,
        )
        comparison = real_model_comparison(
            base,
            trained,
            training_result_id=args.training_result_id,
            training_artifact_digest=args.training_artifact_digest,
            trained_adapter_digest=args.trained_adapter_digest,
            openai_credential_ready=openai_credential_ready(),
            gemini_credential_ready=gemini_credential_ready(),
        )
    except (CurriculumAnalysisError, ValueError) as error:
        print(json.dumps({"status": "failed", "summary": str(error)}, sort_keys=True))
        return 1
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            comparison.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "comparison_id": comparison.comparison_id,
                "status": "verified",
                "training_claim": comparison.training_claim,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
