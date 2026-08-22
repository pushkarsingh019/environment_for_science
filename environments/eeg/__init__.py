"""Seeded synthetic EEG Environment."""

import json
from importlib.resources import files
from typing import Any, cast


def load_seeded_bundle() -> dict[str, Any]:
    """Load the authored EEG bundle with its generator fixture content-bound."""
    bundle_path = files(__package__).joinpath("bundle.json")
    document = cast(
        dict[str, Any],
        json.loads(bundle_path.read_text(encoding="utf-8")),
    )
    if document.get("generator_revision") == "eeg-preflight-generator-1":
        fixture_path = files(__package__).joinpath("preflight_v1.json")
        document["preflight_fixture"] = cast(
            dict[str, Any],
            json.loads(fixture_path.read_text(encoding="utf-8")),
        )
    return document


def load_legacy_bundle() -> dict[str, Any]:
    """Load the Ticket 01 marker bundle for frozen-revision compatibility."""
    bundle_path = files(__package__).joinpath("legacy_bundle.json")
    return cast(dict[str, Any], json.loads(bundle_path.read_text(encoding="utf-8")))


SEEDED_SCENARIO_ID = "eeg-demo-001"
LEGACY_SCENARIO_ID = "eeg-marker-recovery-001"

__all__ = [
    "LEGACY_SCENARIO_ID",
    "SEEDED_SCENARIO_ID",
    "load_legacy_bundle",
    "load_seeded_bundle",
]
