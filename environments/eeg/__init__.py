"""Seeded synthetic EEG Environment."""

import json
from importlib.resources import files
from typing import Any, cast


def load_seeded_bundle() -> dict[str, Any]:
    """Load a fresh copy of the authored seeded EEG Environment Bundle."""
    bundle_path = files(__package__).joinpath("bundle.json")
    return cast(dict[str, Any], json.loads(bundle_path.read_text(encoding="utf-8")))


SEEDED_SCENARIO_ID = "eeg-marker-recovery-001"

__all__ = ["SEEDED_SCENARIO_ID", "load_seeded_bundle"]
