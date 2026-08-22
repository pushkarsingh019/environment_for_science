"""Validation for the product-owned Environment Bundle v1 contract."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_SUPPORTED_CONTRACT_MAJOR = 1
_VERSION_PATTERN = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)$")


class BundleValidationError(ValueError):
    """Raised when an authored Environment Bundle cannot be executed safely."""


class _ExtensibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ActionDefinition(_ExtensibleModel):
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class ProcedureState(_ExtensibleModel):
    id: str = Field(min_length=1)
    terminal: bool


class ProcedureTransition(_ExtensibleModel):
    id: str = Field(min_length=1)
    from_state: str = Field(min_length=1)
    action: str = Field(min_length=1)
    to_state: str = Field(min_length=1)


class ProcedureDefinition(_ExtensibleModel):
    initial_state: str = Field(min_length=1)
    states: list[ProcedureState]
    transitions: list[ProcedureTransition]


class ScenarioInitialState(_ExtensibleModel):
    policy_visible: dict[str, Any]
    hidden: dict[str, Any]


class ScenarioManifest(_ExtensibleModel):
    id: str = Field(min_length=1)
    split: str = Field(min_length=1)
    seed: int
    initial_state: ScenarioInitialState


class EnvironmentBundle(_ExtensibleModel):
    """Validated, forward-compatible Environment Bundle v1 document."""

    contract_version: str
    bundle_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    generator_revision: str = Field(min_length=1)
    title: str = Field(min_length=1)
    simulation_label: str = Field(min_length=1)
    apparatus: dict[str, Any]
    observation_schema: dict[str, Any]
    hidden_state_schema: dict[str, Any]
    actions: list[ActionDefinition]
    procedure: ProcedureDefinition
    split_identities: list[str]
    scenarios: list[ScenarioManifest]
    verifier: dict[str, Any]
    metrics: list[str]
    visualization: dict[str, Any]

    @property
    def action_types(self) -> tuple[str, ...]:
        return tuple(action.type for action in self.actions)

    @model_validator(mode="after")
    def validate_contract(self) -> EnvironmentBundle:
        version_match = _VERSION_PATTERN.fullmatch(self.contract_version)
        if version_match is None:
            raise ValueError("contract_version must use major.minor notation")
        major = int(version_match.group("major"))
        if major != _SUPPORTED_CONTRACT_MAJOR:
            raise ValueError(f"unsupported contract major version {major}")

        _validate_json_object_schema(self.observation_schema, "observation_schema")
        _validate_json_object_schema(self.hidden_state_schema, "hidden_state_schema")
        for action in self.actions:
            _validate_json_object_schema(
                action.input_schema, f"action {action.type!r} input_schema"
            )

        visible_fields = _schema_fields(self.observation_schema)
        hidden_fields = _schema_fields(self.hidden_state_schema)
        overlap = sorted(visible_fields.intersection(hidden_fields))
        if overlap:
            raise ValueError(f"visible and hidden state overlap: {', '.join(overlap)}")

        _require_unique("action type", [action.type for action in self.actions])
        _require_unique("procedure state", [state.id for state in self.procedure.states])
        _require_unique("transition", [item.id for item in self.procedure.transitions])
        _require_unique("split identity", self.split_identities)
        _require_unique("scenario", [scenario.id for scenario in self.scenarios])
        _validate_references(self)
        _validate_scenarios(self, visible_fields, hidden_fields)
        return self


def validate_environment_bundle(document: Mapping[str, Any]) -> EnvironmentBundle:
    """Validate an authored document and return its typed Bundle v1 representation."""
    try:
        return EnvironmentBundle.model_validate(document)
    except ValidationError as error:
        messages = "; ".join(item["msg"] for item in error.errors())
        raise BundleValidationError(messages) from error


def _validate_json_object_schema(schema: Mapping[str, Any], label: str) -> None:
    if schema.get("type") != "object":
        raise ValueError(f"{label} must describe an object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"{label} properties must be an object")
    if any(
        not isinstance(name, str) or not isinstance(value, dict)
        for name, value in properties.items()
    ):
        raise ValueError(f"{label} contains a malformed property")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
        raise ValueError(f"{label} required must be a list of property names")
    unknown_required = sorted(set(required).difference(properties))
    if unknown_required:
        raise ValueError(f"{label} requires unknown properties: {', '.join(unknown_required)}")


def _schema_fields(schema: Mapping[str, Any]) -> set[str]:
    properties = schema.get("properties", {})
    return set(properties) if isinstance(properties, dict) else set()


def _require_unique(label: str, values: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label} identities: {', '.join(sorted(duplicates))}")


def _validate_references(bundle: EnvironmentBundle) -> None:
    state_ids = {state.id for state in bundle.procedure.states}
    action_types = set(bundle.action_types)
    if bundle.procedure.initial_state not in state_ids:
        raise ValueError("procedure initial_state does not reference a declared state")

    adjacency: dict[str, set[str]] = {state_id: set() for state_id in state_ids}
    for transition in bundle.procedure.transitions:
        if transition.from_state not in state_ids or transition.to_state not in state_ids:
            raise ValueError(f"transition {transition.id!r} references an unknown state")
        if transition.action not in action_types:
            raise ValueError(f"transition {transition.id!r} references an unknown action")
        adjacency[transition.from_state].add(transition.to_state)

    reachable: set[str] = set()
    pending = deque([bundle.procedure.initial_state])
    while pending:
        state_id = pending.popleft()
        if state_id in reachable:
            continue
        reachable.add(state_id)
        pending.extend(adjacency[state_id].difference(reachable))
    terminal_ids = {state.id for state in bundle.procedure.states if state.terminal}
    if not terminal_ids.intersection(reachable):
        raise ValueError("procedure has no reachable terminal state")

    success_state = bundle.verifier.get("success_state")
    if success_state not in terminal_ids:
        raise ValueError("verifier success_state must reference a terminal procedure state")


def _validate_scenarios(
    bundle: EnvironmentBundle, visible_fields: set[str], hidden_fields: set[str]
) -> None:
    split_ids = set(bundle.split_identities)
    for scenario in bundle.scenarios:
        if scenario.split not in split_ids:
            raise ValueError(f"scenario {scenario.id!r} references an unknown split")
        unknown_visible = set(scenario.initial_state.policy_visible).difference(visible_fields)
        unknown_hidden = set(scenario.initial_state.hidden).difference(hidden_fields)
        if unknown_visible:
            raise ValueError(
                f"scenario {scenario.id!r} has undeclared visible state: "
                f"{', '.join(sorted(unknown_visible))}"
            )
        if unknown_hidden:
            raise ValueError(
                f"scenario {scenario.id!r} has undeclared hidden state: "
                f"{', '.join(sorted(unknown_hidden))}"
            )
