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


def console_startup_commands(
    *,
    node_modules_present: bool,
) -> tuple[tuple[str, ...], ...]:
    """Return the lockfile-bound Console setup/build sequence."""

    install = (() if node_modules_present else (("npm", "ci", "--ignore-scripts"),))
    return (*install, ("npm", "run", "build"))


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
    for command in console_startup_commands(
        node_modules_present=(console_directory / "node_modules").is_dir(),
    ):
        if command[1] == "ci":
            print("Installing lockfile-bound Console dependencies…", flush=True)
        subprocess.run(command, cwd=console_directory, check=True)
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
