"""Validated EEG-specific visualization data from the Environment Bundle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from studio.bundle import BundleValidationError


class RouteNodePresentation(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    emphasis: bool


class EegOnsetRouteVisualization(BaseModel):
    """Presentation contract owned by the EEG Environment adapter."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: Literal["eeg_onset_route"]
    title: str = Field(min_length=1)
    display_label: str = Field(min_length=1)
    flash_label: str = Field(min_length=1)
    route_nodes: tuple[RouteNodePresentation, ...] = Field(
        min_length=2,
        max_length=2,
    )
    marker_lane_label: str = Field(min_length=1)
    freshness_label: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_route_nodes(self) -> EegOnsetRouteVisualization:
        node_ids = [node.id for node in self.route_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("route node identities must be unique")
        if "refractory_route" not in node_ids:
            raise ValueError("the refractory_route node must be present")
        return self


class _LegacyEegVisualization(BaseModel):
    """Exact presentation shape accepted by the original Bundle v1 fixture."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    primary_view: Literal["onset_timeline"]
    labels: tuple[
        Literal["Synthetic data"],
        Literal["Simulated apparatus only"],
    ]


_LEGACY_ONSET_ROUTE_ADAPTER = {
    "kind": "eeg_onset_route",
    "title": "Onset-marker preflight",
    "display_label": "Presentation display",
    "flash_label": "Lower-right test flash",
    "route_nodes": [
        {
            "id": "light_detector",
            "name": "Light detector",
            "detail": "simulated signal",
            "emphasis": False,
        },
        {
            "id": "refractory_route",
            "name": "Refractory route",
            "detail": "not inspected",
            "emphasis": True,
        },
    ],
    "marker_lane_label": "Marker event lane",
    "freshness_label": "Evidence freshness",
}


def validate_eeg_visualization(
    document: Mapping[str, Any],
) -> EegOnsetRouteVisualization:
    """Validate current EEG presentation data or adapt the original v1 shape."""
    try:
        return EegOnsetRouteVisualization.model_validate(document)
    except ValidationError as current_error:
        try:
            _LegacyEegVisualization.model_validate(document)
        except ValidationError:
            messages = "; ".join(
                item["msg"] for item in current_error.errors()
            )
            raise BundleValidationError(
                f"invalid EEG onset-route visualization: {messages}"
            ) from current_error

        return EegOnsetRouteVisualization.model_validate(
            _LEGACY_ONSET_ROUTE_ADAPTER
        )
