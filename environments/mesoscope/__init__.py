"""Sealed synthetic four-region mesoscope Environment."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast

MESOSCOPE_ENVIRONMENT_ID = "mesoscope-four-region-handoff"
MESOSCOPE_SCENARIO_IDS = (
    "mesoscope-demo-001",
    "mesoscope-demo-002",
    "mesoscope-demo-003",
    "mesoscope-demo-004",
    "mesoscope-demo-005",
    "mesoscope-demo-006",
    "mesoscope-demo-007",
    "mesoscope-demo-008",
)


def load_seeded_bundle() -> dict[str, Any]:
    """Load the immutable sealed-handoff Environment Bundle document."""
    bundle_path = files(__package__).joinpath("bundle.json")
    return cast(dict[str, Any], json.loads(bundle_path.read_text(encoding="utf-8")))


__all__ = [
    "MESOSCOPE_ENVIRONMENT_ID",
    "MESOSCOPE_SCENARIO_IDS",
    "load_seeded_bundle",
]
