"""Validated presentation vocabulary for the sealed mesoscope handoff."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from studio.bundle import BundleValidationError


class MesoscopeProvenance(BaseModel):
    """Environment-owned epistemic classification with source identity."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    classification: Literal[
        "INSTRUMENT FACT", "SOFTWARE FACT", "SIMULATION CHOICE"
    ]
    citation_ids: tuple[str, ...] = Field(min_length=1)
    note: str = Field(min_length=1)


class MesoscopeHandoffVisualization(BaseModel):
    """Static labels for the synthetic survey-to-four-region presentation."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: Literal["mesoscope_handoff_v1"]
    title: str = Field(min_length=1)
    synthetic_label: Literal["SYNTHETIC"]
    sealed_label: Literal["SEALED — DISCONNECTED FROM HARDWARE"]
    survey_label: str = Field(min_length=1)
    raw_view_label: str = Field(min_length=1)
    spatial_view_label: str = Field(min_length=1)
    details_toggle_label: str = Field(min_length=1)
    profile_provenance: MesoscopeProvenance
    plan_provenance: MesoscopeProvenance
    package_provenance: tuple[MesoscopeProvenance, ...] = Field(min_length=2)
    region_ids: tuple[str, ...] = Field(min_length=4, max_length=4)
    depth_labels: tuple[str, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_handoff_vocabulary(self) -> MesoscopeHandoffVisualization:
        if self.region_ids != ("R1", "R2", "R3", "R4"):
            raise ValueError("the sealed handoff must present R1 through R4 in order")
        if self.depth_labels != ("Z-A", "Z-B"):
            raise ValueError("the sealed handoff must use categorical Z-A and Z-B")
        return self


def validate_mesoscope_visualization(
    document: Mapping[str, Any],
) -> MesoscopeHandoffVisualization:
    """Validate required sealed vocabulary while ignoring compatible additions."""
    try:
        return MesoscopeHandoffVisualization.model_validate(document)
    except ValidationError as error:
        messages = "; ".join(item["msg"] for item in error.errors())
        raise BundleValidationError(
            f"invalid sealed mesoscope visualization: {messages}"
        ) from error


__all__ = [
    "MesoscopeHandoffVisualization",
    "MesoscopeProvenance",
    "validate_mesoscope_visualization",
]
