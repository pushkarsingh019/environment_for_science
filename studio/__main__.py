"""Start the complete local Science Environment Studio on loopback."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from studio.application import create_app


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args(argv)

    repository_root = Path(__file__).resolve().parent.parent
    console_directory = repository_root / "console"
    subprocess.run(
        ["npm", "run", "build"],
        cwd=console_directory,
        check=True,
    )
    console_dist = console_directory / "dist"
    uvicorn.run(
        create_app(console_dist=console_dist),
        host="127.0.0.1",
        port=arguments.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
