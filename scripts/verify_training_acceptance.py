"""Verify an imported bounded-Gemma acceptance tree without printing host paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.training_acceptance import AcceptanceArtifactError, AcceptanceArtifactVerifier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    try:
        evidence = AcceptanceArtifactVerifier().verify(args.artifact_root)
    except AcceptanceArtifactError as error:
        print(json.dumps({"status": "failed", "summary": str(error)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            evidence.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
