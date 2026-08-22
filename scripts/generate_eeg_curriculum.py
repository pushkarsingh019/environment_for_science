#!/usr/bin/env python3
"""Regenerate the reviewed, immutable EEG curriculum split packages.

The builder ordinals below are compiler-local allocation coordinates.  They are
domain-separated before becoming opaque public identities and are never written
to a package or Policy-visible observation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from environments.eeg._curriculum_contract import (  # noqa: E402
    CANONICAL_OBJECTIVE,
    CURRICULUM_CONTRACT_DIGEST,
    FAULT_SEMANTICS,
)

RELEASE_ID = "eeg-curriculum-release-1"
CURRICULUM_REVISION = "1.0"
PACKAGE_REVISION = "eeg-curriculum-package-1"
OBJECTIVE = CANONICAL_OBJECTIVE
OUTPUT_DIRECTORY = ROOT / "environments" / "eeg"

FAULTS = (
    "local_contact",
    "flatline_clipping",
    "reference_ground",
    "participant_artifact",
    "environmental_contamination",
    "duplicate_onset",
    "missing_onset",
    "visible_onset_cue",
    "response_mismatch",
    "recording_mismatch",
    "configuration_mismatch",
)
TAUGHT_PAIRS = (
    ("local_contact", "duplicate_onset"),
    ("flatline_clipping", "visible_onset_cue"),
    ("participant_artifact", "response_mismatch"),
    ("environmental_contamination", "recording_mismatch"),
    ("reference_ground", "configuration_mismatch"),
)
HELD_PAIRS = (
    ("local_contact", "response_mismatch"),
    ("flatline_clipping", "duplicate_onset"),
    ("reference_ground", "visible_onset_cue"),
    ("participant_artifact", "missing_onset"),
    ("environmental_contamination", "configuration_mismatch"),
    ("duplicate_onset", "recording_mismatch"),
    ("visible_onset_cue", "response_mismatch"),
    ("configuration_mismatch", "missing_onset"),
)
HELD_TRIPLES = (
    ("local_contact", "duplicate_onset", "recording_mismatch"),
    ("reference_ground", "missing_onset", "response_mismatch"),
    ("participant_artifact", "visible_onset_cue", "configuration_mismatch"),
    ("environmental_contamination", "flatline_clipping", "response_mismatch"),
)
AMBIGUITIES: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    (
        "widespread_noise",
        (
            ("reference_ground",),
            ("participant_artifact",),
            ("environmental_contamination",),
        ),
    ),
    ("quiet_channel", (("flatline_clipping",), ())),
    ("unstable_channel", (("local_contact",),)),
    ("flash_without_marker", (("missing_onset",), ("recording_mismatch",))),
    ("response_without_identity", (("response_mismatch",),)),
    ("noisy_cap_site", (("local_contact",), ())),
    (
        "short_shared_transient",
        (("participant_artifact",), ("environmental_contamination",)),
    ),
)

RUNTIME_ORDINALS = {
    "training": {
        10,
        11,
        15,
        19,
        22,
        23,
        26,
        27,
        31,
        35,
        39,
        43,
        46,
        47,
        50,
        51,
        55,
        66,
        75,
        79,
        83,
        87,
        91,
        95,
    },
    "development": {7, 9, 13, 15, 25, 27, 29, 30},
    "held_out": {9, 11, 12, 13, 15, 18, 20, 22, 40, 45, 50, 55, 56, 59, 60, 63},
}

UNAVAILABLE_FAULTS: dict[str, dict[int, str]] = {
    "training": {
        9: "local_contact",
        17: "reference_ground",
        92: "configuration_mismatch",
        29: "duplicate_onset",
        33: "missing_onset",
        76: "duplicate_onset",
        40: "response_mismatch",
        41: "response_mismatch",
        84: "response_mismatch",
        44: "recording_mismatch",
        48: "configuration_mismatch",
        88: "recording_mismatch",
    },
    "development": {
        6: "reference_ground",
        10: "missing_onset",
        12: "response_mismatch",
        13: "recording_mismatch",
    },
    "held_out": {
        8: "local_contact",
        12: "participant_artifact",
        45: "reference_ground",
        14: "duplicate_onset",
        16: "missing_onset",
        46: "missing_onset",
        18: "response_mismatch",
        19: "response_mismatch",
        41: "response_mismatch",
        20: "recording_mismatch",
        22: "configuration_mismatch",
        50: "recording_mismatch",
    },
}

UNAVAILABLE_PATHS: dict[str, dict[int, str]] = {
    "training": {
        9: "eeg",
        17: "eeg",
        92: "eeg",
        29: "onset",
        33: "onset",
        76: "onset",
        40: "response",
        41: "response",
        84: "response",
        44: "recording",
        48: "recording",
        88: "recording",
    },
    "development": {
        6: "eeg",
        10: "onset",
        12: "response",
        13: "recording",
    },
    "held_out": {
        8: "eeg",
        12: "eeg",
        45: "eeg",
        14: "onset",
        16: "onset",
        46: "onset",
        18: "response",
        19: "response",
        41: "response",
        20: "recording",
        22: "recording",
        50: "recording",
    },
}

RESERVED_NUISANCE_ORDINALS = {
    1,
    3,
    5,
    7,
    9,
    10,
    12,
    15,
    16,
    19,
    20,
    23,
    25,
    26,
    29,
    30,
    33,
    35,
    37,
    39,
    41,
    43,
    45,
    47,
    49,
    51,
    53,
    55,
    57,
    59,
    61,
    63,
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def opaque_id(kind: str, split: str, ordinal: int) -> str:
    material = f"{RELEASE_ID}\0{kind}\0{split}\0{ordinal}".encode()
    token = hashlib.sha256(material).hexdigest()[:16]
    prefix = {"scenario": "eeg", "blueprint": "bp", "nuisance": "nz"}[kind]
    return f"{prefix}-{token}"


def seed_for(split: str, ordinal: int) -> int:
    material = f"{RELEASE_ID}\0seed\0{split}\0{ordinal}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & ((1 << 63) - 1)


def derived_index(seed: int, stream: str, position: int, size: int) -> int:
    material = f"{seed}\0{stream}\0{position}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % size


def occurrence_id(split: str, ordinal: int, position: int) -> str:
    material = f"{RELEASE_ID}\0occurrence\0{split}\0{ordinal}\0{position}".encode()
    return "oc-" + hashlib.sha256(material).hexdigest()[:16]


def nominal_specs(count: int) -> list[dict[str, Any]]:
    return [{"category": "nominal", "faults": (), "ambiguity_family": None} for _ in range(count)]


def individual_specs(multiplicities: tuple[int, ...]) -> list[dict[str, Any]]:
    if len(multiplicities) != len(FAULTS):
        raise AssertionError("individual multiplicities must cover every fault")
    specs: list[dict[str, Any]] = []
    for fault, count in zip(FAULTS, multiplicities):
        specs.extend(
            {"category": "individual", "faults": (fault,), "ambiguity_family": None}
            for _ in range(count)
        )
    return specs


def individual_sequence(faults: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {"category": "individual", "faults": (fault,), "ambiguity_family": None} for fault in faults
    ]


def ambiguity_specs(counts: tuple[int, ...]) -> list[dict[str, Any]]:
    if len(counts) != len(AMBIGUITIES):
        raise AssertionError("ambiguity multiplicities must cover every family")
    specs: list[dict[str, Any]] = []
    for (family, causes), count in zip(AMBIGUITIES, counts):
        for index in range(count):
            specs.append(
                {
                    "category": "ambiguous",
                    "faults": causes[index % len(causes)],
                    "ambiguity_family": family,
                }
            )
    return specs


def combination_specs(
    combinations: tuple[tuple[str, ...], ...],
    multiplicities: tuple[int, ...],
) -> list[dict[str, Any]]:
    if len(combinations) != len(multiplicities):
        raise AssertionError("combination multiplicities must cover every family")
    specs: list[dict[str, Any]] = []
    for combination, count in zip(combinations, multiplicities):
        category = "pair" if len(combination) == 2 else "triple"
        specs.extend(
            {
                "category": category,
                "faults": combination,
                "ambiguity_family": None,
            }
            for _ in range(count)
        )
    return specs


def split_specs(split: str) -> list[dict[str, Any]]:
    if split == "training":
        return [
            *nominal_specs(8),
            *individual_specs((4,) * 11),
            *ambiguity_specs((4, 4, 4, 3, 3, 3, 3)),
            *combination_specs(TAUGHT_PAIRS, (4, 4, 4, 4, 4)),
        ]
    if split == "development":
        return [
            *nominal_specs(4),
            *individual_sequence((*FAULTS, "response_mismatch")),
            *ambiguity_specs((2, 1, 1, 1, 1, 1, 1)),
            *combination_specs(TAUGHT_PAIRS, (2, 2, 2, 1, 1)),
        ]
    held_ambiguities = ambiguity_specs((2, 2, 2, 2, 2, 1, 1))
    held_ambiguities.extend(
        {
            "category": "ambiguous",
            "faults": (),
            "ambiguity_family": family,
        }
        for family in (
            "quiet_channel",
            "noisy_cap_site",
            "short_shared_transient",
            "widespread_noise",
        )
    )
    return [
        *nominal_specs(8),
        *individual_specs((2, 1, 1, 1, 1, 2, 1, 1, 2, 2, 2)),
        *held_ambiguities,
        *combination_specs(HELD_PAIRS, (2,) * 8),
        *combination_specs(HELD_TRIPLES, (2,) * 4),
    ]


def stage_for(spec: dict[str, Any], runtime_onset: bool) -> str:
    if runtime_onset:
        return "runtime_recovery"
    category = spec["category"]
    faults = spec["faults"]
    if category == "nominal":
        return "nominal_orientation"
    if category == "ambiguous":
        return "ambiguity"
    if category in {"pair", "triple"}:
        return "compound_recovery"
    if faults[0] in {"duplicate_onset", "missing_onset"}:
        return "marker_only"
    if faults[0] in {
        "visible_onset_cue",
        "response_mismatch",
        "recording_mismatch",
        "configuration_mismatch",
    }:
        return "integration_preflight"
    return "eeg_preflight"


def build_records(split: str) -> list[dict[str, Any]]:
    specs = split_specs(split)
    records: list[dict[str, Any]] = []
    for ordinal, spec in enumerate(specs):
        unavailable_fault = UNAVAILABLE_FAULTS[split].get(ordinal)
        unavailable_path = UNAVAILABLE_PATHS[split].get(ordinal)
        runtime_onset = ordinal in RUNTIME_ORDINALS[split]
        faults = list(spec["faults"])
        nominal_optional = (
            (split == "training" and ordinal in {4, 5, 6})
            or (split == "development" and ordinal in {2, 3})
            or (split == "held_out" and ordinal in {2, 3, 4, 5, 6, 7})
        )
        ambiguity_family = spec["ambiguity_family"]
        if nominal_optional or (not faults and ambiguity_family == "noisy_cap_site"):
            negative_control_kind = "optional_channel"
        elif not faults and ambiguity_family == "short_shared_transient":
            negative_control_kind = "benign_transient"
        elif not faults and ambiguity_family in {"quiet_channel", "widespread_noise"}:
            negative_control_kind = "benign_mimic"
        else:
            negative_control_kind = "none"
        optional_transient = negative_control_kind in {
            "optional_channel",
            "benign_transient",
        }
        if optional_transient:
            if faults:
                raise AssertionError("a negative control cannot carry a blocking fault")
            unavailable_fault = None
            unavailable_path = None
            runtime_onset = False
        seed = seed_for(split, ordinal)
        occurrences = build_occurrences(
            split=split,
            ordinal=ordinal,
            seed=seed,
            faults=faults,
            runtime_onset=runtime_onset,
            unavailable_fault=unavailable_fault,
        )
        if negative_control_kind == "optional_channel":
            role_requirement = "optional"
        elif faults or negative_control_kind in {"benign_transient", "benign_mimic"}:
            role_requirement = "required"
        else:
            role_requirement = "not_applicable"
        record: dict[str, Any] = {
            "scenario_id": opaque_id("scenario", split, ordinal),
            "blueprint_id": opaque_id("blueprint", split, ordinal),
            "nuisance_id": opaque_id("nuisance", split, ordinal),
            "seed": seed,
            "stage": stage_for(spec, runtime_onset),
            "category": spec["category"],
            "faults": faults,
            "occurrences": occurrences,
            "ambiguity_family": spec["ambiguity_family"],
            "unavailable": unavailable_fault is not None,
            "unavailable_fault": unavailable_fault,
            "unavailable_path": unavailable_path,
            "runtime_onset": runtime_onset,
            "optional_transient": optional_transient,
            "negative_control_kind": negative_control_kind,
            "role_requirement": role_requirement,
            "nuisance_family": (
                "reserved"
                if split == "held_out" and ordinal in RESERVED_NUISANCE_ORDINALS
                else "familiar"
            ),
            "episode_scope": (
                "full" if runtime_onset or spec["category"] in {"pair", "triple"} else "preflight"
            ),
        }
        if optional_transient:
            record["stage"] = (
                "ambiguity" if record["category"] == "ambiguous" else "nominal_orientation"
            )
        if unavailable_fault is not None and unavailable_fault not in record["faults"]:
            raise AssertionError(f"unavailable fault absent at {split} ordinal {ordinal}")
        if (unavailable_fault is None) != (unavailable_path is None):
            raise AssertionError(f"unavailable path mismatch at {split} ordinal {ordinal}")
        record["manifest_digest"] = digest(record)
        records.append(record)
    return sorted(records, key=lambda item: item["scenario_id"])


def build_occurrences(
    *,
    split: str,
    ordinal: int,
    seed: int,
    faults: list[str],
    runtime_onset: bool,
    unavailable_fault: str | None,
) -> list[dict[str, Any]]:
    runtime_position: int | None = None
    if runtime_onset:
        runtime_position = (
            faults.index(unavailable_fault)
            if unavailable_fault in faults
            else derived_index(seed, "runtime_activation", 0, len(faults))
        )
    occurrences: list[dict[str, Any]] = []
    for position, fault in enumerate(faults):
        semantics = FAULT_SEMANTICS[fault]
        variants = semantics["variants"]
        variant = variants[derived_index(seed, "fault_variant", position, len(variants))]
        runtime = position == runtime_position
        occurrences.append(
            {
                "occurrence_id": occurrence_id(split, ordinal, position),
                "family": fault,
                "domain": semantics["domain"],
                "activation": "runtime" if runtime else "preflight",
                "activation_trial": (
                    1 + derived_index(seed, "runtime_activation_trial", position, 2)
                    if runtime
                    else None
                ),
                "visible_variant": variant["visible_variant"],
                "target": variant["target"],
                "inspection_actions": semantics["inspection_actions"],
                "recovery_ladder": variant["recovery_ladder"],
                "retest_action": semantics["retest_action"],
                "invalidates": semantics["invalidates"],
                "unavailable": fault == unavailable_fault,
            }
        )
    return occurrences


def contract_digest() -> str:
    return digest(
        {
            "curriculum_revision": CURRICULUM_REVISION,
            "runtime_contract_digest": CURRICULUM_CONTRACT_DIGEST,
            "objective": OBJECTIVE,
            "faults": FAULTS,
            "taught_pairs": sorted(sorted(pair) for pair in TAUGHT_PAIRS),
            "held_pairs": sorted(sorted(pair) for pair in HELD_PAIRS),
            "held_triples": sorted(sorted(triple) for triple in HELD_TRIPLES),
            "ambiguity_families": [family for family, _causes in AMBIGUITIES],
        }
    )


def seeded_examples(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    labels = {
        "nominal_orientation": ("Seeded example A", "preflight"),
        "integration_preflight": ("Seeded example B", "preflight"),
        "eeg_preflight": ("Seeded example C", "preflight"),
        "ambiguity": ("Seeded example D", "preflight"),
        "runtime_recovery": ("Seeded example E", "short_acquisition"),
        "compound_recovery": ("Seeded example F", "short_acquisition"),
    }
    examples: list[dict[str, str]] = []
    for private_stage, (label, public_stage) in labels.items():
        record = next(item for item in records if item["stage"] == private_stage)
        examples.append(
            {
                "scenario_id": record["scenario_id"],
                "label": label,
                "stage": public_stage,
            }
        )
    return examples


def package_document(split: str) -> dict[str, Any]:
    records = build_records(split)
    payload: dict[str, Any] = {
        "package_revision": PACKAGE_REVISION,
        "release_id": RELEASE_ID,
        "curriculum_revision": CURRICULUM_REVISION,
        "split": split,
        "canonical_objective": OBJECTIVE,
        "contract_digest": contract_digest(),
        "scenarios": records,
        "seeded_examples": seeded_examples(records) if split == "training" else [],
    }
    payload["package_digest"] = digest(payload)
    return payload


def main() -> None:
    outputs = {
        "training": "curriculum_training_v1.json",
        "development": "curriculum_development_v1.json",
        "held_out": "curriculum_heldout_v1.json",
    }
    for split, filename in outputs.items():
        document = package_document(split)
        destination = OUTPUT_DIRECTORY / filename
        destination.write_bytes(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
            + b"\n"
        )


if __name__ == "__main__":
    main()
