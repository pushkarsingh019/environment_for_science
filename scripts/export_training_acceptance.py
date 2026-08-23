"""Export native prime-rl evidence without serializing supplied host paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.training_acceptance import AcceptanceArtifactError
from studio.training_export import NativeAcceptanceExporter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-traces", type=Path, required=True)
    parser.add_argument("--reloaded-traces", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--training-hardware-id", required=True)
    parser.add_argument("--inference-hardware-id", required=True)
    parser.add_argument("--training-taskset-digest", required=True)
    parser.add_argument("--development-taskset-digest", required=True)
    args = parser.parse_args()
    try:
        evidence = NativeAcceptanceExporter().export(
            job_id=args.job_id,
            run_directory=args.run_dir,
            baseline_traces=args.baseline_traces,
            reloaded_traces=args.reloaded_traces,
            destination=args.destination,
            training_hardware_id=args.training_hardware_id,
            inference_hardware_id=args.inference_hardware_id,
            training_taskset_digest=args.training_taskset_digest,
            development_taskset_digest=args.development_taskset_digest,
        )
    except AcceptanceArtifactError as error:
        print(json.dumps({"status": "failed", "summary": str(error)}, sort_keys=True))
        return 1
    print(evidence.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
