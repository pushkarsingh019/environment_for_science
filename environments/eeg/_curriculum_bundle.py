"""Compile one purpose-bound EEG curriculum package into Bundle v1."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from environments.eeg._curriculum_contract import (
    CURRICULUM_ACTIONS,
    GENERATOR_REVISION,
    METRIC_DEFINITIONS,
    SCORER_REVISION,
)
from studio.bundle import EnvironmentBundle, validate_environment_bundle


def materialize_curriculum_bundle(package: dict[str, Any]) -> EnvironmentBundle:
    """Return a detached executable bundle containing exactly one package."""

    base = json.loads(files("environments.eeg").joinpath("bundle.json").read_text())
    split = _string(package, "split")
    scenarios = _list(package, "scenarios")
    configuration = deepcopy(base["procedure"]["configuration"])
    montage = deepcopy(configuration["montage"])
    montage["coordinate_note"] = (
        "Schematic scalp positions support spatial comparison; they are not exact cap geometry."
    )
    action_documents = deepcopy(list(CURRICULUM_ACTIONS))
    document: dict[str, Any] = {
        "contract_version": "1.0",
        "bundle_id": "eeg-curriculum",
        "bundle_revision": "1.4.0",
        "generator_revision": GENERATOR_REVISION,
        "title": "Synthetic EEG staged curriculum",
        "description": (
            "A deterministic synthetic EEG curriculum spanning preflight, short "
            "acquisition, runtime recovery, annotation, valid close, and safe abort."
        ),
        "simulation_label": "Synthetic EEG apparatus simulation",
        "apparatus": deepcopy(base["apparatus"]),
        "observation_schema": _observation_schema(),
        "hidden_state_schema": {
            "type": "object",
            "properties": {"case_id": {"type": "string", "minLength": 1}},
            "required": ["case_id"],
            "additionalProperties": True,
        },
        "actions": action_documents,
        "procedure": {
            "configuration": configuration,
            "initial_state": "episode_active",
            "states": [
                {"id": "episode_active", "terminal": False},
                {"id": "episode_terminal", "terminal": True},
            ],
            "transitions": [
                {
                    "id": f"curriculum-{action['type']}",
                    "from_state": "episode_active",
                    "action": action["type"],
                    "to_state": (
                        "episode_terminal"
                        if action["type"]
                        in {"complete_preflight", "close_acquisition", "abort_episode"}
                        else "episode_active"
                    ),
                }
                for action in action_documents
            ],
        },
        "split_identities": [split],
        "scenarios": [
            {
                "id": _string(record, "scenario_id"),
                "split": split,
                "seed": _integer(record, "seed"),
                "manifest_digest": _string(record, "manifest_digest"),
                "initial_state": {
                    "policy_visible": _initial_visible(configuration, montage),
                    "hidden": {"case_id": _string(record, "scenario_id")},
                },
            }
            for record in scenarios
            if isinstance(record, dict)
        ],
        "verifier": {
            "id": "eeg-curriculum-verifier",
            "result_version": SCORER_REVISION,
            "success_state": "episode_terminal",
        },
        "metrics": list(METRIC_DEFINITIONS),
        "visualization": deepcopy(base["visualization"]),
        "curriculum_package_digest": _string(package, "package_digest"),
        "curriculum_contract_digest": _string(package, "contract_digest"),
        "curriculum_fixture": deepcopy(package),
    }
    if len(document["scenarios"]) != len(scenarios):
        raise ValueError("the curriculum package contains a malformed scenario")
    return validate_environment_bundle(document).model_copy(deep=True)


def _initial_visible(
    configuration: dict[str, Any],
    montage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "simulation_label": "Synthetic EEG apparatus simulation",
        "stage": "preflight",
        "summary": "Inspect the current synthetic evidence before making a terminal decision.",
        "montage": deepcopy(montage),
        "procedure_configuration": deepcopy(configuration),
        "configuration_evidence": {},
        "eeg_window": {},
        "frequency_evidence": None,
        "onset_evidence": {},
        "response_evidence": {},
        "recording_evidence": {},
        "participant_evidence": {},
        "environment_evidence": {},
        "evidence_freshness": {},
        "acquisition": {},
        "annotations": [],
    }


def _observation_schema() -> dict[str, Any]:
    object_schema = {"type": "object", "additionalProperties": True}
    properties: dict[str, Any] = {
        "simulation_label": {
            "type": "string",
            "const": "Synthetic EEG apparatus simulation",
        },
        "stage": {
            "type": "string",
            "enum": ["preflight", "recording", "paused", "recording_complete", "terminal"],
        },
        "summary": {"type": "string", "minLength": 1},
        "montage": object_schema,
        "procedure_configuration": object_schema,
        "configuration_evidence": object_schema,
        "eeg_window": object_schema,
        "frequency_evidence": {"type": ["object", "null"]},
        "onset_evidence": object_schema,
        "response_evidence": object_schema,
        "recording_evidence": object_schema,
        "participant_evidence": object_schema,
        "environment_evidence": object_schema,
        "evidence_freshness": object_schema,
        "acquisition": object_schema,
        "annotations": {"type": "array", "items": object_schema},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"curriculum {key} must be a non-empty string")
    return value


def _integer(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"curriculum {key} must be an integer")
    return value


def _list(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key)
    if not isinstance(value, list):
        raise ValueError(f"curriculum {key} must be a list")
    return value


__all__ = ["materialize_curriculum_bundle"]
