"""Deterministic non-operational runtime for the sealed mesoscope handoff."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from functools import lru_cache
from typing import Any, Literal

from environments.mesoscope import (
    MESOSCOPE_ENVIRONMENT_ID,
    MESOSCOPE_SCENARIO_IDS,
    load_seeded_bundle,
)
from environments.mesoscope.presentation import (
    MesoscopeHandoffVisualization,
    validate_mesoscope_visualization,
)
from studio.bundle import (
    BundleValidationError,
    EnvironmentBundle,
    ScenarioManifest,
    validate_environment_bundle,
)
from studio.runtime import (
    EnvironmentAction,
    EpisodeState,
    EpisodeUpdate,
    RuntimeContractError,
    VerifierOutcome,
)

_ACTION_TYPES = (
    "inspect_sealed_handoff",
    "run_mock_acquisition",
    "validate_mock_package",
    "accept_mock_package",
    "quarantine_mock_package",
    "reject_mock_package",
)
_EMPTY_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_FAULT_IDS = (
    "valid_package",
    "missing_region",
    "wrong_z_assignment",
    "missing_channel",
    "duplicate_event",
    "missing_event",
    "motion_row_mismatch",
    "checksum_mismatch",
)
_FAULT_CODES = {
    "missing_region": "MISSING_REGION",
    "wrong_z_assignment": "WRONG_Z_ASSIGNMENT",
    "missing_channel": "MISSING_CHANNEL",
    "duplicate_event": "DUPLICATE_EVENT",
    "missing_event": "MISSING_EVENT",
    "motion_row_mismatch": "MOTION_ROW_MISMATCH",
    "checksum_mismatch": "CHECKSUM_MISMATCH",
}
_SUCCESS_WORDING = "MOCK PACKAGE VERIFIED"
_QUARANTINE_WORDING = "SYNTHETIC PACKAGE QUARANTINED"
_REJECT_WORDING = "SYNTHETIC PACKAGE REJECTED"
_SIMULATION_NOTICE = (
    "SIMULATED DATA — NO HARDWARE CONNECTION — NOT LASER OR ANIMAL GUIDANCE"
)
_CHECKSUM_ARTIFACT_FIELDS = (
    ("synthetic-tiles", "region_tiles"),
    ("channel-records", "channel_records"),
    ("event-records", "event_records"),
    ("motion-rows", "motion_rows"),
    ("package-manifest", "manifest_records"),
)
_EXTENSION_KEY_PATTERN = re.compile(
    r"^(?:future|x)_[a-z0-9]+(?:_[a-z0-9]+)*$",
    re.ASCII,
)


class MesoscopeEnvironmentModule:
    """Purpose-built sealed module installed behind ``EnvironmentRuntime``."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        if self._bundle.bundle_id != MESOSCOPE_ENVIRONMENT_ID:
            raise BundleValidationError("the sealed mesoscope bundle identity is invalid")
        if self._bundle.generator_revision != "mesoscope-four-region-generator-1":
            raise BundleValidationError("unsupported sealed mesoscope generator revision")
        apparatus_boundary = {
            key: self._bundle.apparatus.get(key)
            for key in (
                "kind",
                "simulation_only",
                "sealed",
                "physical_control_available",
            )
        }
        if (
            self._bundle.simulation_label != _SIMULATION_NOTICE
            or apparatus_boundary != _expected_apparatus_boundary()
        ):
            raise BundleValidationError(
                "the reviewed sealed simulation boundary is invalid"
            )
        if tuple(self._bundle.action_types) != _ACTION_TYPES or any(
            not _has_reviewed_empty_action_surface(action.input_schema)
            for action in self._bundle.actions
        ):
            raise BundleValidationError(
                "the sealed action surface must contain only the approved empty schemas"
            )
        scenario_ids = tuple(scenario.id for scenario in self._bundle.scenarios)
        fault_ids = tuple(
            str(scenario.initial_state.hidden.get("fault_id"))
            for scenario in self._bundle.scenarios
        )
        if scenario_ids != MESOSCOPE_SCENARIO_IDS or fault_ids != _FAULT_IDS:
            raise BundleValidationError("the sealed mesoscope scenario catalog is invalid")
        for scenario in self._bundle.scenarios:
            visible = scenario.initial_state.policy_visible
            profile = visible["sealed_profile"]
            profile_core = {
                key: profile.get(key) for key in _expected_sealed_profile()
            }
            profile_catalog = visible["profile_catalog"]
            profile_catalog_core = [
                {
                    key: entry.get(key)
                    for key in (
                        "profile_id",
                        "provenance_label",
                        "selected",
                        "immutable",
                    )
                }
                for entry in profile_catalog
            ]
            selected_profiles = [
                entry for entry in profile_catalog if entry.get("selected") is True
            ]
            if (
                profile_core != _expected_sealed_profile()
                or profile_catalog_core != _expected_profile_catalog()
                or len(selected_profiles) != 1
                or selected_profiles[0].get("profile_id")
                != profile.get("profile_id")
            ):
                raise BundleValidationError(
                    "the reviewed sealed profile contract is invalid"
                )
            safety_gate = visible["safety_gate"]
            survey = visible["survey"]
            if (
                visible["simulation_notice"] != _SIMULATION_NOTICE
                or safety_gate.get("state") not in {"closed", "open", "unknown"}
                or safety_gate.get("immutable") is not True
                or safety_gate.get("independently_enforced") is not True
                or {
                    key: survey.get(key)
                    for key in ("kind", "synthetic", "watermark")
                }
                != _expected_survey_identity()
                or survey.get("visual_seed")
                != scenario.initial_state.hidden.get("visual_seed")
            ):
                raise BundleValidationError(
                    "the reviewed sealed safety and simulation contract is invalid"
                )
            signed_plan = visible["signed_plan"]
            plan_core = {
                "plan_id": signed_plan["plan_id"],
                "immutable": signed_plan["immutable"],
                "regions": signed_plan["regions"],
            }
            selected_plans = [
                plan for plan in visible["plan_catalog"] if plan["selected"] is True
            ]
            expected_plan_core = _expected_signed_plan_core()
            signed_plan_keys = {*expected_plan_core, "signature_digest"}
            if (
                set(signed_plan) != signed_plan_keys
                or plan_core != expected_plan_core
                or signed_plan["signature_digest"] != _digest(plan_core)
                or len(selected_plans) != 1
                or selected_plans[0]["plan_id"] != signed_plan["plan_id"]
                or selected_plans[0]["signature_digest"]
                != signed_plan["signature_digest"]
                or selected_plans[0]["immutable"] is not True
            ):
                raise BundleValidationError(
                    "the reviewed signed-plan contract is invalid"
                )
        self._visualization = validate_mesoscope_visualization(
            self._bundle.visualization
        )
        _validate_reviewed_sealed_bundle(self._bundle)

    @property
    def bundle(self) -> EnvironmentBundle:
        return self._bundle.model_copy(deep=True)

    @property
    def runtime_validation_bundle(self) -> EnvironmentBundle:
        """Project compatibility metadata away from executable validators."""
        projected = self._bundle.model_copy(deep=True)
        projected.observation_schema = _reviewed_schema_core(
            projected.observation_schema
        )
        projected.hidden_state_schema = _reviewed_schema_core(
            projected.hidden_state_schema
        )
        for action in projected.actions:
            action.input_schema = deepcopy(_EMPTY_ACTION_SCHEMA)
        return projected

    @property
    def visualization(self) -> MesoscopeHandoffVisualization:
        return self._visualization.model_copy(deep=True)

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
        return EpisodeState(
            procedure_state=self._bundle.procedure.initial_state,
            observation=deepcopy(scenario.initial_state.policy_visible),
            hidden_state=deepcopy(scenario.initial_state.hidden),
            state_revision=0,
        )

    def permitted_actions(self, state: EpisodeState) -> tuple[str, ...]:
        actions = tuple(
            transition.action
            for transition in self._bundle.procedure.transitions
            if transition.from_state == state.procedure_state
        )
        if (
            state.procedure_state == "inspection_complete"
            and state.observation["safety_gate"]["state"] != "closed"
        ):
            return ()
        if state.procedure_state != "disposition_ready":
            return actions
        if state.observation["validation_status"] == "valid":
            return ("accept_mock_package",)
        if state.observation["validation_status"] == "invalid":
            return ("quarantine_mock_package", "reject_mock_package")
        return ()

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate:
        if action.arguments:
            raise RuntimeContractError(
                "sealed mesoscope actions do not accept configurable fields"
            )
        if action.type == "inspect_sealed_handoff":
            return self._inspect(state)
        if action.type == "run_mock_acquisition":
            return self._acquire(state)
        if action.type == "validate_mock_package":
            return self._validate_package(state)
        if action.type == "accept_mock_package":
            return self._accept(state)
        if action.type == "quarantine_mock_package":
            return self._quarantine(state)
        if action.type == "reject_mock_package":
            return self._reject(state)
        raise RuntimeContractError(
            f"sealed mesoscope action {action.type!r} is not implemented",
            code="internal",
        )

    def _inspect(self, state: EpisodeState) -> EpisodeUpdate:
        observation = deepcopy(state.observation)
        observation["stage"] = "inspection_complete"
        observation["summary"] = (
            "Sealed synthetic profile, signed plan, and independent safety gate inspected."
        )
        freshness = deepcopy(observation["evidence_freshness"])
        freshness["safety"] = _freshness("meso-safety-001", "current")
        freshness["plan"] = _freshness("meso-plan-001", "current")
        observation["evidence_freshness"] = freshness
        return _updated(
            state,
            observation,
            "Sealed synthetic handoff inspected without changing its immutable profile.",
        )

    def _acquire(self, state: EpisodeState) -> EpisodeUpdate:
        if state.observation["safety_gate"]["state"] != "closed":
            raise RuntimeContractError(
                "the independent sealed safety gate blocks mock acquisition"
            )
        observation = deepcopy(state.observation)
        fault_id = str(state.hidden_state["fault_id"])
        package = _observed_package(
            scenario_id=str(state.hidden_state["scenario_id"]),
            visual_seed=int(state.hidden_state["visual_seed"]),
            fault_id=fault_id,
        )
        observation.update(package)
        observation["stage"] = "package_review"
        observation["summary"] = (
            "Synthetic mock acquisition completed; sealed output awaits package validation."
        )
        freshness = deepcopy(observation["evidence_freshness"])
        freshness["acquisition"] = _freshness("meso-acquisition-001", "current")
        freshness["package"] = _freshness("meso-package-001", "unavailable")
        observation["evidence_freshness"] = freshness
        hidden = deepcopy(state.hidden_state)
        hidden["acquisition_complete"] = True
        return _updated(
            state,
            observation,
            "Synthetic mock acquisition produced a sealed review package.",
            hidden_state=hidden,
        )

    def _validate_package(self, state: EpisodeState) -> EpisodeUpdate:
        if state.hidden_state["acquisition_complete"] is not True:
            raise RuntimeContractError("synthetic acquisition evidence is unavailable")
        observation = deepcopy(state.observation)
        checks = _package_checks(observation)
        mismatches = tuple(
            str(check["check_id"])
            for check in checks
            if check["status"] == "mismatch"
        )
        detected = _detected_faults(observation, mismatches)
        valid = not mismatches
        observation["package_checks"] = checks
        observation["detected_faults"] = list(detected)
        observation["validation_status"] = "valid" if valid else "invalid"
        observation["stage"] = "disposition_ready"
        observation["summary"] = (
            "Synthetic package validation found complete agreement."
            if valid
            else "Synthetic package validation found sealed-contract mismatches."
        )
        freshness = deepcopy(observation["evidence_freshness"])
        freshness["package"] = _freshness("meso-package-001", "current")
        observation["evidence_freshness"] = freshness
        hidden = deepcopy(state.hidden_state)
        hidden["validation_complete"] = True
        hidden["package_valid"] = valid
        return _updated(
            state,
            observation,
            "Synthetic package validation completed against the sealed contract.",
            hidden_state=hidden,
        )

    def _accept(self, state: EpisodeState) -> EpisodeUpdate:
        if (
            state.hidden_state["validation_complete"] is not True
            or state.hidden_state["package_valid"] is not True
        ):
            raise RuntimeContractError(
                "an incomplete or inconsistent synthetic package cannot be accepted"
            )
        observation = deepcopy(state.observation)
        observation["stage"] = "complete"
        observation["terminal_status"] = _SUCCESS_WORDING
        observation["summary"] = _SUCCESS_WORDING
        hidden = deepcopy(state.hidden_state)
        hidden["terminal_action"] = "accepted"
        return _updated(state, observation, _SUCCESS_WORDING, hidden_state=hidden)

    def _quarantine(self, state: EpisodeState) -> EpisodeUpdate:
        self._require_invalid_validated_package(state)
        observation = deepcopy(state.observation)
        observation["stage"] = "complete"
        observation["terminal_status"] = _QUARANTINE_WORDING
        observation["summary"] = (
            "Synthetic invalid package quarantined; sealed artifacts remain non-operational."
        )
        hidden = deepcopy(state.hidden_state)
        hidden["terminal_action"] = "quarantined"
        return _updated(
            state,
            observation,
            "Synthetic invalid package quarantined under the sealed handoff contract.",
            hidden_state=hidden,
        )

    def _reject(self, state: EpisodeState) -> EpisodeUpdate:
        self._require_invalid_validated_package(state)
        observation = deepcopy(state.observation)
        observation["stage"] = "complete"
        observation["terminal_status"] = _REJECT_WORDING
        observation["summary"] = (
            "Synthetic invalid package rejected; no hardware-consumable output exists."
        )
        hidden = deepcopy(state.hidden_state)
        hidden["terminal_action"] = "rejected"
        return _updated(
            state,
            observation,
            "Synthetic invalid package rejected under the sealed handoff contract.",
            hidden_state=hidden,
        )

    @staticmethod
    def _require_invalid_validated_package(state: EpisodeState) -> None:
        if (
            state.hidden_state["validation_complete"] is not True
            or state.hidden_state["package_valid"] is not False
        ):
            raise RuntimeContractError(
                "quarantine or rejection requires a validated invalid synthetic package"
            )

    def verify(self, state: EpisodeState) -> VerifierOutcome:
        fault_id = str(state.hidden_state["fault_id"])
        recomputed_checks = _package_checks(state.observation)
        recorded_checks = state.observation["package_checks"]
        checks_current = recorded_checks == recomputed_checks and len(recorded_checks) == 7
        package_valid = checks_current and all(
            check["status"] == "match" for check in recomputed_checks
        )
        expected_valid = fault_id == "valid_package"
        terminal_action = str(state.hidden_state["terminal_action"])
        terminal_state = {
            "accepted": "mock_package_verified",
            "quarantined": "package_quarantined",
            "rejected": "package_rejected",
        }.get(terminal_action)
        lifecycle_complete = bool(
            checks_current
            and state.hidden_state["acquisition_complete"] is True
            and state.hidden_state["validation_complete"] is True
            and state.hidden_state["package_valid"] is package_valid
            and terminal_state is not None
            and state.procedure_state == terminal_state
        )
        expected_faults = () if expected_valid else (_FAULT_CODES[fault_id],)
        observed_faults = tuple(str(item) for item in state.observation["detected_faults"])
        fault_detection = observed_faults == expected_faults
        package_agreement = package_valid and expected_valid
        safe_disposition = lifecycle_complete and (
            (package_agreement and terminal_action == "accepted")
            or (
                not expected_valid
                and not package_valid
                and terminal_action in {"quarantined", "rejected"}
            )
        )
        expected_terminal = (
            _SUCCESS_WORDING
            if expected_valid
            else (
                _QUARANTINE_WORDING
                if terminal_action == "quarantined"
                else _REJECT_WORDING
            )
        )
        exact_terminal = state.observation["terminal_status"] == expected_terminal
        profile = state.observation["sealed_profile"]
        signed_plan = state.observation["signed_plan"]
        signed_plan_core = {
            "plan_id": signed_plan["plan_id"],
            "immutable": signed_plan["immutable"],
            "regions": signed_plan["regions"],
        }
        survey = state.observation["survey"]
        gate = state.observation["safety_gate"]
        sealed_boundary = bool(
            state.observation["simulation_notice"] == _SIMULATION_NOTICE
            and {key: profile.get(key) for key in _expected_sealed_profile()}
            == _expected_sealed_profile()
            and signed_plan_core == _expected_signed_plan_core()
            and signed_plan["signature_digest"] == _digest(signed_plan_core)
            and gate["immutable"] is True
            and gate["independently_enforced"] is True
            and {
                key: survey.get(key)
                for key in ("kind", "synthetic", "watermark")
            }
            == _expected_survey_identity()
        )
        passed = bool(
            lifecycle_complete
            and checks_current
            and fault_detection
            and safe_disposition
            and exact_terminal
            and sealed_boundary
        )
        reasons: list[str] = []
        if not lifecycle_complete:
            reasons.append("The reviewed sealed action lifecycle was not completed.")
        if not checks_current:
            reasons.append(
                "Package checks were absent, stale, or not independently reproducible."
            )
        if not fault_detection:
            reasons.append("Synthetic package faults were not identified exactly.")
        if not safe_disposition:
            reasons.append("The sealed synthetic package received an unsafe disposition.")
        if not exact_terminal:
            reasons.append("The synthetic terminal did not match the package evidence.")
        if not sealed_boundary:
            reasons.append("The sealed non-operational boundary was not preserved.")

        if passed and expected_valid:
            summary = _SUCCESS_WORDING
            disposition: Literal["closed", "aborted", "failed"] = "closed"
            outcome_category = "mock_package_verified"
        elif passed:
            summary = (
                "Synthetic invalid package was safely quarantined."
                if terminal_action == "quarantined"
                else "Synthetic invalid package was safely rejected."
            )
            disposition = "aborted"
            outcome_category = f"package_{terminal_action}"
        else:
            summary = "Sealed synthetic handoff not verified: " + " ".join(reasons)
            disposition = "failed"
            outcome_category = "incomplete_or_unsafe"

        return VerifierOutcome(
            passed=passed,
            terminal_disposition=disposition,
            outcome_category=outcome_category,
            summary=summary,
            metrics={
                "exact_terminal_match": float(exact_terminal),
                "fault_detection": float(fault_detection),
                "package_agreement": float(package_agreement),
                "safe_disposition": float(safe_disposition),
                "sealed_boundary": float(sealed_boundary),
            },
            evidence={
                "detected_faults": list(observed_faults),
                "package_check_digest": _digest(state.observation["package_checks"]),
                "synthetic": True,
                "sealed": True,
                "terminal_status": state.observation["terminal_status"],
            },
            reasons=tuple(reasons),
        )


def _updated(
    state: EpisodeState,
    observation: dict[str, Any],
    summary: str,
    *,
    hidden_state: dict[str, Any] | None = None,
) -> EpisodeUpdate:
    return EpisodeUpdate(
        observation=observation,
        hidden_state=hidden_state or deepcopy(state.hidden_state),
        state_revision=state.state_revision + 1,
        summary=summary,
    )


def _freshness(evidence_id: str, status: str) -> dict[str, str]:
    return {"evidence_id": evidence_id, "status": status}


def _observed_package(
    *,
    scenario_id: str,
    visual_seed: int,
    fault_id: str,
) -> dict[str, Any]:
    package_id = f"synthetic-package-{scenario_id.removeprefix('mesoscope-demo-')}"
    regions = _expected_regions()
    outputs = _expected_outputs()
    tiles = [
        {
            "region_id": region["region_id"],
            "z_label": region["z_label"],
            "tile_seed": visual_seed + index * 101,
            "synthetic": True,
            "status": "present",
        }
        for index, region in enumerate(regions)
    ]
    if fault_id == "missing_region":
        tiles = [tile for tile in tiles if tile["region_id"] != "R4"]
    if fault_id == "wrong_z_assignment":
        for tile in tiles:
            if tile["region_id"] == "R3":
                tile["z_label"] = "Z-A"

    channel_records = [
        {
            "region_id": output["region_id"],
            "z_label": output["z_label"],
            "channel_id": output["channel_id"],
            "frame_count": output["frame_count"],
            "package_id": package_id,
            "received": True,
            "saved": True,
        }
        for output in outputs
    ]
    if fault_id == "missing_channel":
        channel_records = [
            record
            for record in channel_records
            if not (
                record["region_id"] == "R4" and record["channel_id"] == "CH-B"
            )
        ]
    event_records = [
        {"event_id": "start", "sequence_index": 1, "package_id": package_id},
        {"event_id": "trial", "sequence_index": 2, "package_id": package_id},
        {"event_id": "reward", "sequence_index": 3, "package_id": package_id},
    ]
    if fault_id == "duplicate_event":
        event_records.insert(
            2,
            {"event_id": "trial", "sequence_index": 3, "package_id": package_id},
        )
        event_records[-1]["sequence_index"] = 4
    if fault_id == "missing_event":
        event_records.pop()

    motion_rows = [
        {
            "row_id": (
                f"motion-{output['region_id'].casefold()}-"
                f"{output['channel_id'].casefold()}"
            ),
            "region_id": output["region_id"],
            "z_label": output["z_label"],
            "channel_id": output["channel_id"],
            "package_id": package_id,
            "quality_status": "within_synthetic_contract",
        }
        for output in outputs
    ]
    if fault_id == "motion_row_mismatch":
        motion_rows[-1]["region_id"] = "R3"

    manifest_records = [
        {"output_id": output["output_id"], "package_id": package_id}
        for output in outputs
        if not (
            fault_id == "missing_region" and output["region_id"] == "R4"
        )
        and not (
            fault_id == "missing_channel"
            and output["region_id"] == "R4"
            and output["channel_id"] == "CH-B"
        )
    ]
    valid_tiles = [
        {
            "region_id": region["region_id"],
            "z_label": region["z_label"],
            "tile_seed": visual_seed + index * 101,
            "synthetic": True,
            "status": "present",
        }
        for index, region in enumerate(regions)
    ]
    valid_channels = [
        {
            "region_id": output["region_id"],
            "z_label": output["z_label"],
            "channel_id": output["channel_id"],
            "frame_count": output["frame_count"],
            "package_id": package_id,
            "received": True,
            "saved": True,
        }
        for output in outputs
    ]
    valid_events = _expected_event_records(package_id)
    valid_motion = _expected_motion_rows(package_id, outputs)
    valid_manifest = _expected_manifest_records(package_id, outputs)
    artifact_payloads = {
        "synthetic-tiles": tiles,
        "channel-records": channel_records,
        "event-records": event_records,
        "motion-rows": motion_rows,
        "package-manifest": manifest_records,
    }
    expected_artifact_payloads = {
        "synthetic-tiles": valid_tiles,
        "channel-records": valid_channels,
        "event-records": valid_events,
        "motion-rows": valid_motion,
        "package-manifest": valid_manifest,
    }
    package_checksums = []
    for artifact_id, payload in artifact_payloads.items():
        computed = _digest(payload)
        recorded = computed
        if fault_id == "checksum_mismatch" and artifact_id == "package-manifest":
            recorded = _digest({"corrupt": computed})
        package_checksums.append(
            {
                "artifact_id": artifact_id,
                "expected_digest": _digest(expected_artifact_payloads[artifact_id]),
                "computed_digest": computed,
                "observed_digest": recorded,
            }
        )

    return {
        "region_tiles": tiles,
        "channel_records": channel_records,
        "event_records": event_records,
        "motion_rows": motion_rows,
        "manifest_records": manifest_records,
        "package_checksums": package_checksums,
    }


def _expected_regions() -> list[dict[str, str]]:
    return [
        {"region_id": "R1", "z_label": "Z-A"},
        {"region_id": "R2", "z_label": "Z-A"},
        {"region_id": "R3", "z_label": "Z-B"},
        {"region_id": "R4", "z_label": "Z-B"},
    ]


def _expected_apparatus_boundary() -> dict[str, Any]:
    return {
        "kind": "sealed_synthetic_mesoscope",
        "simulation_only": True,
        "sealed": True,
        "physical_control_available": False,
    }


def _expected_profile_catalog() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "paper-derived-context-v1",
            "provenance_label": "5 mm diameter research-paper convention",
            "selected": True,
            "immutable": True,
        },
        {
            "profile_id": "commercial-reference-v1",
            "provenance_label": "5 mm × 5 mm current commercial-page convention",
            "selected": False,
            "immutable": True,
        },
    ]


def _expected_sealed_profile() -> dict[str, Any]:
    return {
        "profile_id": "paper-derived-context-v1",
        "source_geometry": "5 mm diameter research-paper convention",
        "immutable": True,
        "simulation_only": True,
        "status": "sealed",
    }


def _expected_survey_identity() -> dict[str, Any]:
    return {
        "kind": "procedural_non_biological_phantom",
        "synthetic": True,
        "watermark": "SYNTHETIC",
    }


def _expected_signed_plan_core() -> dict[str, Any]:
    return {
        "plan_id": "4R-HANDOFF-v1",
        "immutable": True,
        "regions": [
            {
                "region_id": region["region_id"],
                "z_label": region["z_label"],
                "visit_order": index,
                "tile_seed_offset": (index - 1) * 101,
            }
            for index, region in enumerate(_expected_regions(), start=1)
        ],
    }


def _expected_outputs() -> list[dict[str, Any]]:
    return [
        {
            "region_id": region["region_id"],
            "z_label": region["z_label"],
            "channel_id": channel_id,
            "output_id": (
                f"{region['region_id']}-{region['z_label'].replace('-', '')}-"
                f"{channel_id.replace('-', '')}"
            ),
            "frame_count": 12,
        }
        for region in _expected_regions()
        for channel_id in ("CH-A", "CH-B")
    ]


def _expected_event_records(package_id: str) -> list[dict[str, Any]]:
    return [
        {"event_id": "start", "sequence_index": 1, "package_id": package_id},
        {"event_id": "trial", "sequence_index": 2, "package_id": package_id},
        {"event_id": "reward", "sequence_index": 3, "package_id": package_id},
    ]


def _expected_motion_rows(
    package_id: str,
    outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "row_id": (
                f"motion-{output['region_id'].casefold()}-"
                f"{output['channel_id'].casefold()}"
            ),
            "region_id": output["region_id"],
            "z_label": output["z_label"],
            "channel_id": output["channel_id"],
            "package_id": package_id,
            "quality_status": "within_synthetic_contract",
        }
        for output in outputs
    ]


def _expected_manifest_records(
    package_id: str,
    outputs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {"output_id": output["output_id"], "package_id": package_id}
        for output in outputs
    ]


def _package_checks(observation: dict[str, Any]) -> list[dict[str, str]]:
    expected_outputs = observation["expected_outputs"]
    signed_regions = observation["signed_plan"]["regions"]
    expected_regions = [
        {
            "region_id": region["region_id"],
            "z_label": region["z_label"],
        }
        for region in signed_regions
    ]
    tiles = observation["region_tiles"]
    expected_region_ids = [item["region_id"] for item in expected_regions]
    observed_regions = [item["region_id"] for item in tiles]
    expected_z = {item["region_id"]: item["z_label"] for item in expected_regions}
    observed_z = {item["region_id"]: item["z_label"] for item in tiles}
    region_agreement = observed_regions == expected_region_ids
    z_assignment = observed_z == expected_z
    package_ids = {
        str(record["package_id"])
        for record in observation["channel_records"]
        + observation["event_records"]
        + observation["motion_rows"]
        + observation["manifest_records"]
    }
    package_identity_agreement = len(package_ids) == 1
    package_id = (
        next(iter(package_ids))
        if package_identity_agreement
        else "invalid-package-identity"
    )
    channel_agreement = package_identity_agreement and observation[
        "channel_records"
    ] == [
        {
            "region_id": output["region_id"],
            "z_label": output["z_label"],
            "channel_id": output["channel_id"],
            "frame_count": output["frame_count"],
            "package_id": package_id,
            "received": True,
            "saved": True,
        }
        for output in expected_outputs
    ]
    event_agreement = package_identity_agreement and observation[
        "event_records"
    ] == _expected_event_records(package_id)
    motion_agreement = package_identity_agreement and observation[
        "motion_rows"
    ] == _expected_motion_rows(package_id, expected_outputs)
    manifest_agreement = package_identity_agreement and observation[
        "manifest_records"
    ] == _expected_manifest_records(package_id, expected_outputs)
    expected_artifact_payloads = {
        "synthetic-tiles": [
            {
                "region_id": region["region_id"],
                "z_label": region["z_label"],
                "tile_seed": (
                    observation["survey"]["visual_seed"]
                    + region["tile_seed_offset"]
                ),
                "synthetic": True,
                "status": "present",
            }
            for region in signed_regions
        ],
        "channel-records": [
            {
                "region_id": output["region_id"],
                "z_label": output["z_label"],
                "channel_id": output["channel_id"],
                "frame_count": output["frame_count"],
                "package_id": package_id,
                "received": True,
                "saved": True,
            }
            for output in expected_outputs
        ],
        "event-records": _expected_event_records(package_id),
        "motion-rows": _expected_motion_rows(package_id, expected_outputs),
        "package-manifest": _expected_manifest_records(package_id, expected_outputs),
    }
    observed_artifact_payloads = {
        artifact_id: observation[field_name]
        for artifact_id, field_name in _CHECKSUM_ARTIFACT_FIELDS
    }
    checksum_rows = observation["package_checksums"]
    checksum_artifact_ids = tuple(
        str(row["artifact_id"]) for row in checksum_rows
    )
    expected_artifact_ids = tuple(
        artifact_id for artifact_id, _field_name in _CHECKSUM_ARTIFACT_FIELDS
    )
    checksum_agreement = (
        checksum_artifact_ids == expected_artifact_ids
        and all(
            row["expected_digest"]
            == _digest(expected_artifact_payloads[str(row["artifact_id"])])
            and row["computed_digest"]
            == _digest(observed_artifact_payloads[str(row["artifact_id"])])
            and row["observed_digest"] == row["computed_digest"]
            for row in checksum_rows
        )
    )
    statuses = (
        ("region_agreement", region_agreement),
        ("z_assignment", z_assignment),
        ("channel_agreement", channel_agreement),
        ("event_records", event_agreement),
        ("motion_rows", motion_agreement),
        ("manifest_membership", manifest_agreement),
        ("checksums", checksum_agreement),
    )
    return [
        {"check_id": check_id, "status": "match" if matches else "mismatch"}
        for check_id, matches in statuses
    ]


def _detected_faults(
    observation: dict[str, Any],
    mismatches: tuple[str, ...],
) -> tuple[str, ...]:
    if not mismatches:
        return ()
    if "region_agreement" in mismatches:
        return ("MISSING_REGION",)
    if "z_assignment" in mismatches:
        return ("WRONG_Z_ASSIGNMENT",)
    if "channel_agreement" in mismatches:
        return ("MISSING_CHANNEL",)
    if "event_records" in mismatches:
        events = observation["event_records"]
        event_ids = [record["event_id"] for record in events]
        return (
            "DUPLICATE_EVENT"
            if len(event_ids) != len(set(event_ids))
            else "MISSING_EVENT",
        )
    if "motion_rows" in mismatches:
        return ("MOTION_ROW_MISMATCH",)
    return ("CHECKSUM_MISMATCH",)


@lru_cache(maxsize=1)
def _reviewed_bundle_contract() -> str:
    reviewed = validate_environment_bundle(load_seeded_bundle())
    document = reviewed.model_dump(mode="json")
    document.pop("contract_version", None)
    return _canonical_json(document)


def _validate_reviewed_sealed_bundle(bundle: EnvironmentBundle) -> None:
    try:
        candidate = bundle.model_dump(mode="python")
    except ValueError as error:
        raise BundleValidationError(
            "the bundle differs from the reviewed sealed bundle contract"
        ) from error
    contract_version = candidate.pop("contract_version", None)
    reviewed = json.loads(_reviewed_bundle_contract())
    if not isinstance(contract_version, str):
        raise BundleValidationError(
            "the bundle differs from the reviewed sealed bundle contract"
        )
    allow_additions = _supports_namespaced_additions(contract_version)
    if not _matches_reviewed_contract(
        reviewed,
        candidate,
        allow_additions=allow_additions,
    ):
        raise BundleValidationError(
            "the bundle differs from the reviewed sealed bundle contract"
        )


def _supports_namespaced_additions(contract_version: str) -> bool:
    major_text, minor_text = contract_version.split(".", maxsplit=1)
    return int(major_text) == 1 and int(minor_text) > 0


def _matches_reviewed_contract(
    reviewed: Any,
    candidate: Any,
    *,
    allow_additions: bool,
    path: tuple[str, ...] = (),
) -> bool:
    """Match reviewed semantics while retaining inert v1.x namespaced fields."""
    if isinstance(reviewed, dict):
        if not isinstance(candidate, dict):
            return False
        if any(key not in candidate for key in reviewed):
            return False
        if not all(
            _matches_reviewed_contract(
                value,
                candidate[key],
                allow_additions=allow_additions,
                path=(*path, key),
            )
            for key, value in reviewed.items()
        ):
            return False
        additions = {
            key: value for key, value in candidate.items() if key not in reviewed
        }
        return all(
            allow_additions
            and _extension_location_is_inert(path)
            and isinstance(key, str)
            and _EXTENSION_KEY_PATTERN.fullmatch(key) is not None
            and _compatible_extension_value(path, value)
            for key, value in additions.items()
        )
    if isinstance(reviewed, list):
        return (
            isinstance(candidate, list)
            and len(candidate) == len(reviewed)
            and all(
                _matches_reviewed_contract(
                    reviewed_item,
                    candidate_item,
                    allow_additions=allow_additions,
                    path=(*path, "[]"),
                )
                for reviewed_item, candidate_item in zip(reviewed, candidate)
            )
        )
    return _canonical_json(candidate) == _canonical_json(reviewed)


def _extension_location_is_inert(path: tuple[str, ...]) -> bool:
    """Positively allow only authored metadata that a reviewed projector drops."""
    return path in {
        (),
        ("apparatus",),
        ("apparatus", "source_profiles", "[]"),
        ("observation_schema",),
        ("hidden_state_schema",),
        ("actions", "[]"),
        ("actions", "[]", "input_schema"),
        ("procedure",),
        ("procedure", "states", "[]"),
        ("procedure", "transitions", "[]"),
        ("scenarios", "[]"),
        ("verifier",),
        ("visualization",),
        ("visualization", "profile_provenance"),
        ("visualization", "plan_provenance"),
        ("visualization", "package_provenance", "[]"),
    }


def _compatible_extension_value(path: tuple[str, ...], value: Any) -> bool:
    if path == ("actions", "[]", "input_schema"):
        return (
            isinstance(value, dict)
            and set(value) == {"label"}
            and isinstance(value["label"], str)
            and bool(value["label"].strip())
        )
    return _json_compatible_extension(value)


def _json_compatible_extension(value: Any) -> bool:
    """Accept opaque finite JSON without attempting to classify its semantics."""
    if isinstance(value, dict):
        return all(
            isinstance(child_key, str) and _json_compatible_extension(child_value)
            for child_key, child_value in value.items()
        )
    if isinstance(value, list):
        return all(_json_compatible_extension(child) for child in value)
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _has_reviewed_empty_action_surface(input_schema: dict[str, Any]) -> bool:
    return all(
        input_schema.get(key) == value for key, value in _EMPTY_ACTION_SCHEMA.items()
    )


def _reviewed_schema_core(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in schema.items()
        if _EXTENSION_KEY_PATTERN.fullmatch(key) is None
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    canonical = _canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


__all__ = ["MesoscopeEnvironmentModule"]
