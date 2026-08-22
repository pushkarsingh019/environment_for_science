"""Evaluator-owned loader and release audit for the sealed EEG held-out split."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from importlib.resources import files
from typing import Any

from environments.eeg.curriculum import (
    _EXPECTED_CATEGORY_COUNTS,
    _EXPECTED_CROSS_CUTTING,
    _FAULT_FAMILIES,
    CurriculumContractError,
    CurriculumIntegrityReport,
    CurriculumReport,
    CurriculumSplit,
    DevelopmentScenarioSet,
    FaultFamily,
    TrainingScenarioSet,
    _CurriculumPackageDocument,
    _digest,
    _load_package,
    _ScenarioSet,
)

_APPROVED_HELD_OUT_PACKAGE_DIGEST = (
    "sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7"
)
_TAUGHT_PAIR_ORDER: tuple[tuple[FaultFamily, FaultFamily], ...] = (
    ("local_contact", "duplicate_onset"),
    ("flatline_clipping", "visible_onset_cue"),
    ("participant_artifact", "response_mismatch"),
    ("environmental_contamination", "recording_mismatch"),
    ("reference_ground", "configuration_mismatch"),
)
_TAUGHT_PAIRS = frozenset(frozenset(pair) for pair in _TAUGHT_PAIR_ORDER)
_RESERVED_PAIRS = frozenset(
    {
        frozenset(("local_contact", "response_mismatch")),
        frozenset(("flatline_clipping", "duplicate_onset")),
        frozenset(("reference_ground", "visible_onset_cue")),
        frozenset(("participant_artifact", "missing_onset")),
        frozenset(("environmental_contamination", "configuration_mismatch")),
        frozenset(("duplicate_onset", "recording_mismatch")),
        frozenset(("visible_onset_cue", "response_mismatch")),
        frozenset(("configuration_mismatch", "missing_onset")),
    }
)
_RESERVED_TRIPLES = frozenset(
    {
        frozenset(("local_contact", "duplicate_onset", "recording_mismatch")),
        frozenset(("reference_ground", "missing_onset", "response_mismatch")),
        frozenset(
            ("participant_artifact", "visible_onset_cue", "configuration_mismatch")
        ),
        frozenset(
            ("environmental_contamination", "flatline_clipping", "response_mismatch")
        ),
    }
)


class HeldOutScenarioSet(_ScenarioSet):
    """Only the evaluator-owned 64-row final package."""

    def aggregate(self, attempts: object) -> CurriculumReport:
        """Aggregate only a sealed, persisted evaluator attempt matrix."""

        from evaluation.eeg.attempts import HeldOutAttemptLedger

        if not isinstance(attempts, HeldOutAttemptLedger):
            raise CurriculumContractError(
                "held-out reports require a persistent sealed attempt ledger"
            )
        ledger_attempts, evaluation_id, ledger_digest = attempts._sealed_payload_for(
            self
        )
        return self._aggregate_attempts(
            ledger_attempts,
            evaluation_id=evaluation_id,
            attempt_ledger_digest=ledger_digest,
        )


def load_held_out_scenario_set(
    document: Mapping[str, Any] | bytes | str | None = None,
) -> HeldOutScenarioSet:
    """Load only the byte-for-byte approved final-evaluation package."""

    source = document
    if source is None:
        source = files("environments.eeg").joinpath(
            "curriculum_heldout_v1.json"
        ).read_bytes()
    return HeldOutScenarioSet(
        _load_package(
            "held_out",
            source,
            approved_digest=_APPROVED_HELD_OUT_PACKAGE_DIGEST,
        )
    )


def audit_eeg_curriculum_release(
    training: TrainingScenarioSet,
    development: DevelopmentScenarioSet,
    held_out: HeldOutScenarioSet,
) -> CurriculumIntegrityReport:
    """Validate the trusted whole-release invariants outside the training wheel."""

    packages = (training._package, development._package, held_out._package)
    splits = tuple(package.split for package in packages)
    if splits != ("training", "development", "held_out"):
        raise CurriculumContractError("curriculum packages have incompatible purposes")
    if len({package.release_id for package in packages}) != 1:
        raise CurriculumContractError("curriculum release identities do not agree")
    if len({package.curriculum_revision for package in packages}) != 1:
        raise CurriculumContractError("curriculum revisions do not agree")
    if len({package.contract_digest for package in packages}) != 1:
        raise CurriculumContractError("curriculum contracts do not agree")

    _validate_cross_split_identities(packages)
    category_counts: dict[str, dict[str, int]] = {}
    cross_counts: dict[str, dict[str, int]] = {}
    unavailable_path_counts: dict[str, dict[str, int]] = {}
    for package in packages:
        category_counts[package.split] = {
            category: sum(
                record.category == category for record in package.scenarios
            )
            for category in ("nominal", "individual", "ambiguous", "pair", "triple")
        }
        cross_counts[package.split] = {
            "unavailable": sum(record.unavailable for record in package.scenarios),
            "runtime_onset": sum(record.runtime_onset for record in package.scenarios),
            "optional_transient": sum(
                record.optional_transient for record in package.scenarios
            ),
            "reserved_nuisance": sum(
                record.nuisance_family == "reserved" for record in package.scenarios
            ),
        }
        unavailable_path_counts[package.split] = {
            path: sum(record.unavailable_path == path for record in package.scenarios)
            for path in ("eeg", "onset", "response", "recording")
        }
        if category_counts[package.split] != _EXPECTED_CATEGORY_COUNTS[package.split]:
            raise CurriculumContractError("curriculum category quota mismatch")
        if cross_counts[package.split] != _EXPECTED_CROSS_CUTTING[package.split]:
            raise CurriculumContractError("curriculum cross-cutting quota mismatch")
        expected_per_path = {"training": 3, "development": 1, "held_out": 3}[
            package.split
        ]
        if set(unavailable_path_counts[package.split].values()) != {expected_per_path}:
            raise CurriculumContractError("unavailable paths are not balanced")

    _validate_combination_policy(packages)
    release_id = packages[0].release_id
    curriculum_revision = packages[0].curriculum_revision
    release_digest = _digest(
        {
            "release_id": release_id,
            "curriculum_revision": curriculum_revision,
            "package_digests": [package.package_digest for package in packages],
        }
    )
    return CurriculumIntegrityReport(
        valid=True,
        release_id=release_id,
        curriculum_revision=curriculum_revision,
        release_digest=release_digest,
        split_counts={package.split: len(package.scenarios) for package in packages},
        category_counts=category_counts,
        cross_cutting_counts=cross_counts,
        unavailable_path_counts=unavailable_path_counts,
        identity_families_disjoint=True,
        combination_policy_valid=True,
    )


def _validate_cross_split_identities(
    packages: Sequence[_CurriculumPackageDocument],
) -> None:
    for attribute in ("scenario_id", "blueprint_id", "nuisance_id"):
        identity_sets = [
            {getattr(record, attribute) for record in package.scenarios}
            for package in packages
        ]
        if any(
            identity_sets[left] & identity_sets[right]
            for left in range(len(identity_sets))
            for right in range(left + 1, len(identity_sets))
        ):
            raise CurriculumContractError("curriculum identity families overlap")


def _validate_combination_policy(
    packages: Sequence[_CurriculumPackageDocument],
) -> None:
    by_split = {package.split: package for package in packages}
    expected_individual_counts: dict[CurriculumSplit, dict[FaultFamily, int]] = {
        "training": {fault: 4 for fault in _FAULT_FAMILIES},
        "development": {
            fault: (2 if fault == "response_mismatch" else 1)
            for fault in _FAULT_FAMILIES
        },
        "held_out": {
            "local_contact": 2,
            "flatline_clipping": 1,
            "reference_ground": 1,
            "participant_artifact": 1,
            "environmental_contamination": 1,
            "duplicate_onset": 2,
            "missing_onset": 1,
            "visible_onset_cue": 1,
            "response_mismatch": 2,
            "recording_mismatch": 2,
            "configuration_mismatch": 2,
        },
    }
    for split, package in by_split.items():
        individual_counts = Counter(
            record.faults[0]
            for record in package.scenarios
            if record.category == "individual"
        )
        if dict(individual_counts) != expected_individual_counts[split]:
            raise CurriculumContractError("individual fault multiplicities changed")

    for split in ("training", "development"):
        package = by_split[split]
        pair_counts = Counter(
            frozenset(record.faults)
            for record in package.scenarios
            if record.category == "pair"
        )
        expected_counts = (
            {pair: 4 for pair in _TAUGHT_PAIRS}
            if split == "training"
            else {
                pair: count
                for pair, count in zip(
                    (frozenset(components) for components in _TAUGHT_PAIR_ORDER),
                    (2, 2, 2, 1, 1),
                )
            }
        )
        if dict(pair_counts) != expected_counts:
            raise CurriculumContractError("a non-taught pair entered optimization data")
        if any(record.category == "triple" for record in package.scenarios):
            raise CurriculumContractError("a triple entered optimization data")

    held_package = by_split["held_out"]
    held_pairs = Counter(
        frozenset(record.faults)
        for record in held_package.scenarios
        if record.category == "pair"
    )
    held_triples = Counter(
        frozenset(record.faults)
        for record in held_package.scenarios
        if record.category == "triple"
    )
    if dict(held_pairs) != {pair: 2 for pair in _RESERVED_PAIRS} or dict(
        held_triples
    ) != {triple: 2 for triple in _RESERVED_TRIPLES}:
        raise CurriculumContractError("held-out combinations do not match the freeze")
    for package in packages:
        individual_faults = {
            record.faults[0]
            for record in package.scenarios
            if record.category == "individual"
        }
        if individual_faults != set(_FAULT_FAMILIES):
            raise CurriculumContractError("a primitive is absent from an individual stratum")

    held_reserved_by_category = Counter(
        record.category
        for record in held_package.scenarios
        if record.nuisance_family == "reserved"
    )
    if dict(held_reserved_by_category) != {
        "nominal": 4,
        "individual": 8,
        "ambiguous": 8,
        "pair": 8,
        "triple": 4,
    }:
        raise CurriculumContractError("held-out nuisance balance changed")


__all__ = [
    "HeldOutScenarioSet",
    "audit_eeg_curriculum_release",
    "load_held_out_scenario_set",
]
