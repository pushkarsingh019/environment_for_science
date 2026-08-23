"""Start the complete local Science Environment Studio on loopback."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from studio.application import create_app


def external_prerequisite_summary(
    environ: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Describe optional integrations without reading or printing credential values."""

    source = dict(os.environ) if environ is None else environ
    return (
        "OpenAI hosted reference: "
        + (
            "configured"
            if source.get("OPENAI_API_KEY", "").strip()
            else "missing (offline fixture available)"
        ),
        "Gemini hosted reference: "
        + (
            "configured"
            if source.get("GEMINI_API_KEY", "").strip()
            else "missing (offline fixture available)"
        ),
        "Gemma compute: approved GPU workstations only; no local model compute",
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="directory for local draft and trace artifacts",
    )
    arguments = parser.parse_args(argv)

    for prerequisite in external_prerequisite_summary():
        print(prerequisite, flush=True)

    repository_root = Path(__file__).resolve().parent.parent
    console_directory = repository_root / "console"
    subprocess.run(
        ["npm", "run", "build"],
        cwd=console_directory,
        check=True,
    )
    console_dist = console_directory / "dist"
    uvicorn.run(
        create_app(
            console_dist=console_dist,
            artifact_root=arguments.artifact_root,
        ),
        host="127.0.0.1",
        port=arguments.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
