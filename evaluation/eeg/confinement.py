"""Trusted scanner proving held-out EEG material is absent from training wheels."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from itertools import permutations
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field


class TrainingDistributionLeakageError(ValueError):
    """Raised when a purported training wheel contains evaluator-only material."""


class TrainingDistributionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    archive_name: str = Field(min_length=1)
    files_scanned: int = Field(ge=1)
    held_out_values_scanned: int = Field(ge=1)


def audit_training_wheel(path: Path) -> TrainingDistributionAudit:
    """Fail closed if a wheel contains the held-out resource or its opaque truth."""

    archive = Path(path)
    held_out = json.loads(
        files("environments.eeg")
        .joinpath("curriculum_heldout_v1.json")
        .read_text(encoding="utf-8")
    )
    scenarios = held_out["scenarios"]
    forbidden_values = {
        held_out["package_digest"],
        json.dumps(held_out, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        *(
            value
            for scenario in scenarios
            for key, value in scenario.items()
            if key
            in {"scenario_id", "blueprint_id", "nuisance_id", "manifest_digest"}
        ),
        *(str(scenario["seed"]) for scenario in scenarios),
        *(
            occurrence["occurrence_id"]
            for scenario in scenarios
            for occurrence in scenario["occurrences"]
        ),
        *(
            json.dumps(
                scenario,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            for scenario in scenarios
        ),
    }
    reserved_combinations = {
        ordering
        for scenario in scenarios
        if len(scenario["faults"]) >= 2
        for ordering in permutations(scenario["faults"])
    }
    try:
        with ZipFile(archive) as wheel:
            names = wheel.namelist()
            normalized_paths = tuple(
                PurePosixPath(name.replace("\\", "/")).parts for name in names
            )
            if not names or any(
                "evaluation" in parts
                or (parts and parts[-1] == "curriculum_heldout_v1.json")
                for parts in normalized_paths
            ):
                raise TrainingDistributionLeakageError(
                    "the training wheel contains an evaluator-owned path"
                )
            contents = b"\n".join(wheel.read(name) for name in names)
    except (BadZipFile, OSError, KeyError) as error:
        raise TrainingDistributionLeakageError(
            "the training wheel could not be audited"
        ) from error
    leaked = next(
        (value for value in forbidden_values if value.encode("utf-8") in contents),
        None,
    )
    if leaked is not None:
        raise TrainingDistributionLeakageError(
            "the training wheel contains evaluator-owned opaque material"
        )
    if any(
        _combination_pattern(combination).search(contents)
        for combination in reserved_combinations
    ):
        raise TrainingDistributionLeakageError(
            "the training wheel contains evaluator-owned composition material"
        )
    return TrainingDistributionAudit(
        valid=True,
        archive_name=archive.name,
        files_scanned=len(names),
        held_out_values_scanned=len(forbidden_values),
    )


def _combination_pattern(combination: tuple[str, ...]) -> re.Pattern[bytes]:
    separator = rb"[\"']\s*,\s*[\"']"
    body = separator.join(re.escape(item.encode("utf-8")) for item in combination)
    quoted_body = rb"[\"']" + body + rb"[\"']"
    container_end = rb"\s*,?\s*"
    return re.compile(
        rb"(?:\[\s*"
        + quoted_body
        + container_end
        + rb"\]|\(\s*"
        + quoted_body
        + container_end
        + rb"\)|\{\s*"
        + quoted_body
        + container_end
        + rb"\})"
    )


__all__ = [
    "TrainingDistributionAudit",
    "TrainingDistributionLeakageError",
    "audit_training_wheel",
]
