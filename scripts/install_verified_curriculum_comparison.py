"""Install one sanitized verified curriculum result into the immutable comparison index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.curriculum_training_evidence import CurriculumTrainingEvidence
from studio.model_comparison import ModelComparisonRepository, ModelComparisonResult


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--comparison-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = CurriculumTrainingEvidence.model_validate_json(
            _read_regular(args.evidence)
        )
        comparison = ModelComparisonResult.model_validate_json(
            _read_regular(args.comparison)
        )
        if (
            evidence.status != "verified"
            or comparison.source != "real_evaluation"
            or comparison.training_result_id != evidence.result_id
            or comparison.training_artifact_digest != evidence.artifact_digest
            or comparison.models[0].model_configuration_digest
            != evidence.base_heldout.model_configuration_digest
            or comparison.models[1].model_configuration_digest
            != evidence.trained_heldout.model_configuration_digest
            or comparison.models[1].adapter_digest != evidence.final_adapter_digest
            or comparison.gemma_contrast != evidence.paired_bootstrap
        ):
            raise ValueError(
                "comparison does not match the verified curriculum evidence"
            )
        installed = ModelComparisonRepository(args.comparison_root).install_real(
            comparison,
            base_ledger_root=args.ledger_root / "base-heldout-ledger",
            trained_ledger_root=args.ledger_root / "trained-heldout-ledger",
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "summary": str(error)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "comparison_id": installed.comparison_id,
                "status": "installed",
                "training_claim": installed.training_claim,
            },
            sort_keys=True,
        )
    )
    return 0


def _read_regular(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise OSError("verified comparison input is not a regular file")
    return path.read_text()


if __name__ == "__main__":
    raise SystemExit(main())
