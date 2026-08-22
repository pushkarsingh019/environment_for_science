from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from environments.mesoscope import (
    MESOSCOPE_ENVIRONMENT_ID,
    MESOSCOPE_SCENARIO_IDS,
    load_seeded_bundle,
)
from environments.mesoscope.presentation import MesoscopeHandoffVisualization
from environments.mesoscope.runtime import MesoscopeEnvironmentModule
from studio.bundle import BundleValidationError, validate_environment_bundle

EXPECTED_ACTIONS = (
    "inspect_sealed_handoff",
    "run_mock_acquisition",
    "validate_mock_package",
    "accept_mock_package",
    "quarantine_mock_package",
    "reject_mock_package",
)

FORBIDDEN_ACTION_FIELD_TERMS = {
    "alignment",
    "biological",
    "calibration",
    "coordinate",
    "detector",
    "gain",
    "interlock",
    "laser",
    "motion",
    "objective",
    "power",
    "scanner",
    "surgery",
    "voltage",
    "wavelength",
}


def _schema_field_names(value: object) -> set[str]:
    if isinstance(value, dict):
        names = {str(name).casefold() for name in value.get("properties", {})}
        return names.union(*(_schema_field_names(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_schema_field_names(item) for item in value), set())
    return set()


def test_seeded_mesoscope_bundle_is_a_complete_sealed_environment_v1() -> None:
    bundle = validate_environment_bundle(load_seeded_bundle())
    module = MesoscopeEnvironmentModule(bundle)

    assert bundle.bundle_id == MESOSCOPE_ENVIRONMENT_ID
    assert bundle.generator_revision == "mesoscope-four-region-generator-1"
    assert bundle.simulation_label == (
        "SIMULATED DATA — NO HARDWARE CONNECTION — NOT LASER OR ANIMAL GUIDANCE"
    )
    assert tuple(action.type for action in bundle.actions) == EXPECTED_ACTIONS
    assert tuple(scenario.id for scenario in bundle.scenarios) == MESOSCOPE_SCENARIO_IDS
    assert len(bundle.scenarios) == 8
    assert set(bundle.split_identities) == {"demonstration"}
    assert isinstance(module.visualization, MesoscopeHandoffVisualization)
    assert module.visualization.synthetic_label == "SYNTHETIC"
    assert module.visualization.sealed_label == "SEALED — DISCONNECTED FROM HARDWARE"
    assert module.visualization.region_ids == ("R1", "R2", "R3", "R4")
    assert module.visualization.depth_labels == ("Z-A", "Z-B")
    assert module.visualization.profile_provenance.classification == "INSTRUMENT FACT"
    assert module.visualization.profile_provenance.citation_ids == ("P1", "M2")
    assert module.visualization.plan_provenance.classification == "SIMULATION CHOICE"
    assert tuple(
        item.classification for item in module.visualization.package_provenance
    ) == ("SOFTWARE FACT", "SIMULATION CHOICE")

    fault_ids = {
        str(scenario.initial_state.hidden["fault_id"])
        for scenario in bundle.scenarios
    }
    assert fault_ids == {
        "valid_package",
        "missing_region",
        "wrong_z_assignment",
        "missing_channel",
        "duplicate_event",
        "missing_event",
        "motion_row_mismatch",
        "checksum_mismatch",
    }


def test_mesoscope_action_schemas_are_empty_and_non_operational() -> None:
    bundle = validate_environment_bundle(load_seeded_bundle())

    for action in bundle.actions:
        assert action.input_schema == {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        field_names = _schema_field_names(action.input_schema)
        assert not field_names.intersection(FORBIDDEN_ACTION_FIELD_TERMS)


@pytest.mark.parametrize(
    "forbidden_field",
    sorted(FORBIDDEN_ACTION_FIELD_TERMS),
)
def test_mesoscope_module_rejects_any_operational_action_field(
    forbidden_field: str,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    schema = document["actions"][0]["input_schema"]
    schema["properties"][forbidden_field] = {"type": "number"}

    with pytest.raises(BundleValidationError, match="sealed action surface"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_bundle_contains_no_hardware_connector_or_mutable_profile() -> None:
    document = load_seeded_bundle()
    serialized = json.dumps(document, sort_keys=True).casefold()

    assert '"hardware_connector"' not in serialized
    assert '"hardware_address"' not in serialized
    assert '"physical_port"' not in serialized
    for scenario in document["scenarios"]:
        visible = scenario["initial_state"]["policy_visible"]
        assert visible["sealed_profile"]["immutable"] is True
        assert visible["signed_plan"]["immutable"] is True
        assert visible["safety_gate"]["immutable"] is True
        assert [region["region_id"] for region in visible["signed_plan"]["regions"]] == [
            "R1",
            "R2",
            "R3",
            "R4",
        ]


def test_mesoscope_module_accepts_compatible_minor_visualization_extensions() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"]["future_minor_extension"] = {"enabled": True}

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))

    assert module.visualization.kind == "mesoscope_handoff_v1"
    assert module.bundle.visualization["future_minor_extension"] == {"enabled": True}


def test_mesoscope_module_accepts_nested_provenance_minor_metadata() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"]["profile_provenance"]["future_source_link"] = (
        "archival citation metadata"
    )

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))
    profile = module.visualization.profile_provenance

    assert "future_source_link" not in profile.model_dump(mode="json")
    assert module.bundle.visualization["profile_provenance"][
        "future_source_link"
    ] == "archival citation metadata"


def test_mesoscope_module_preserves_compatible_namespaced_minor_additions() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["future_release_metadata"] = {
        "label": "Evidence-only compatibility note"
    }
    document["apparatus"]["future_display_metadata"] = {
        "label": "Package quality control evidence"
    }
    document["actions"][0]["future_evidence_note"] = {
        "label": "Inspection evidence note"
    }
    document["actions"][0]["input_schema"]["future_evidence_note"] = {
        "label": "Schema compatibility note"
    }
    document["procedure"]["future_evidence_note"] = {"label": "Procedure note"}
    document["procedure"]["states"][0]["future_evidence_note"] = {
        "label": "State note"
    }
    document["procedure"]["transitions"][0]["future_evidence_note"] = {
        "label": "Transition note"
    }
    document["scenarios"][0]["future_evidence_note"] = {"label": "Scenario note"}
    document["visualization"]["future_motion_row_annotation"] = {
        "label": "Motion row integrity evidence"
    }

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))
    preserved = module.bundle

    assert preserved.model_extra == {
        "future_release_metadata": {
            "label": "Evidence-only compatibility note"
        }
    }
    assert preserved.apparatus["future_display_metadata"] == {
        "label": "Package quality control evidence"
    }
    action_extras = preserved.actions[0].model_extra
    assert action_extras is not None
    assert action_extras["future_evidence_note"] == {
        "label": "Inspection evidence note"
    }
    assert preserved.actions[0].input_schema["future_evidence_note"] == {
        "label": "Schema compatibility note"
    }
    assert preserved.visualization["future_motion_row_annotation"] == {
        "label": "Motion row integrity evidence"
    }
    preserved_document = preserved.model_dump(mode="json")
    assert preserved_document["procedure"]["future_evidence_note"] == {
        "label": "Procedure note"
    }
    assert preserved_document["procedure"]["states"][0]["future_evidence_note"] == {
        "label": "State note"
    }
    assert preserved_document["procedure"]["transitions"][0][
        "future_evidence_note"
    ] == {"label": "Transition note"}
    assert preserved_document["scenarios"][0]["future_evidence_note"] == {
        "label": "Scenario note"
    }


@pytest.mark.parametrize(
    ("extension_key", "extension_value"),
    (
        (
            "future_calibration_limitation",
            {"label": "Calibration is outside this simulation"},
        ),
        (
            "future_alignment_limitation",
            {"label": "Alignment is outside this simulation"},
        ),
        (
            "future_detector_annotation",
            {
                "label": "Detector response is not validated",
                "statistics": {"value": 4},
            },
        ),
        (
            "future_information_gain_note",
            "Apply information gain scoring to package evidence",
        ),
        (
            "future_safety_note",
            "No laser safety assurance and no hardware connection",
        ),
        ("future_pmt_annotation", "PMT readiness evidence"),
        ("future_detector_status_note", "Detector status evidence"),
        ("future_package_note", "Mock package ready for validation"),
        ("future_system_note", "Package validation system is ready"),
        (
            "future_package_export",
            {"filename": "package-evidence.json", "kind": "evidence"},
        ),
        ("future_color", "#fff"),
        ("future_color_metadata", {"opacity": 0.5}),
        ("future_citation", {"year": 2016}),
        ("future_release_metadata", {"revision": 2}),
        ("x_layout", "compact"),
        ("x_layout", {"columns": 2}),
        ("future_help", "Open evidence details"),
        ("future_help", "Read-only explanatory text"),
    ),
)
def test_mesoscope_module_accepts_non_operational_minor_evidence(
    extension_key: str,
    extension_value: object,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"][extension_key] = extension_value

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))

    assert module.bundle.visualization[extension_key] == extension_value


@pytest.mark.parametrize(
    ("extension_key", "extension_value"),
    (
        (
            "future_operator_tip",
            "Set PMT bias to 900 and adjust scan phase; safe to image",
        ),
        (
            "future_operator_tip",
            "Set PMT-bias to 900 and adjust scanPhase; safe-to-image",
        ),
        ("future_operator_note", "Use the photomultiplier at 900 V"),
        ("future_operator_note", "Prepare the animal before imaging"),
        ("future_readiness_note", "PMT is ready"),
        ("future_readiness_note", "PMT status: ready"),
        ("future_readiness_note", "Imaging ready"),
        ("future_pulse_width_fs", 100),
        ("future_pmt_offset_metric", 5),
        ("future_pulse_energy_metric", 100),
        ("future_beam_duty_cycle_metric", 50),
        ("future_laser_power_watts", 100),
        ("future_settings", {"pmt": {"bias": 900}}),
        (
            "future_handoff_note",
            {"target": "PMT bias", "value": 900, "unit": "volts"},
        ),
        ("future_readiness_note", "The apparatus is ready for imaging"),
        (
            "future_export",
            {"filename": "machine.ini", "contents": "load into ScanImage"},
        ),
        ("future_export", "ScanImage machine configuration file"),
        ("future_operator_note", "Do not set PMT bias"),
        (
            "future_handoff_note",
            "Remove the SYNTHETIC watermark before export",
        ),
        (
            "future_handoff_note",
            "Export this configuration to the microscope",
        ),
        (
            "future_evidence_note",
            "Operator should dial the laser to 920 nm before imaging.",
        ),
        ("future_evidence_note", "Animal prep: anesthetize, mount, and image."),
        (
            "future_evidence_note",
            "Evidence note: use laser according to cited source.",
        ),
        (
            "future_annotation",
            {"pmt": {"statistics": {"offset": "900 V"}}},
        ),
        (
            "future_annotation",
            {
                "properties": {"laser_power": 100},
                "fault_id": "checksum_mismatch",
            },
        ),
    ),
)
def test_mesoscope_module_quarantines_arbitrary_json_minor_additions(
    extension_key: str,
    extension_value: object,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"][extension_key] = extension_value

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))

    assert module.bundle.visualization[extension_key] == extension_value
    assert extension_key not in module.visualization.model_dump(mode="json")


@pytest.mark.parametrize(
    "extension_value",
    (
        object(),
        float("nan"),
        float("inf"),
        float("-inf"),
        {"nested": [float("nan")]},
        {1: "non-string key"},
        ("tuple",),
    ),
)
def test_mesoscope_module_rejects_non_json_minor_extension_values(
    extension_value: object,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"]["future_evidence_note"] = extension_value

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_unnamespaced_minor_additions() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["apparatus"]["display_metadata"] = {
        "label": "Evidence-only compatibility note"
    }

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


@pytest.mark.parametrize(
    "extension_key",
    (
        "Future_note",
        "future_",
        "future__note",
        "future_note_",
        "future_nötë",
    ),
)
def test_mesoscope_module_rejects_malformed_extension_namespaces(
    extension_key: str,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document[extension_key] = {"label": "Evidence-only compatibility note"}

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_additions_without_a_minor_version_bump() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["future_release_metadata"] = {
        "label": "Evidence-only compatibility note"
    }

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_minor_fields_that_disclose_hidden_truth() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["observation_schema"]["properties"]["future_fault_id"] = {
        "type": "string"
    }
    for scenario in document["scenarios"]:
        initial_state = scenario["initial_state"]
        initial_state["policy_visible"]["future_fault_id"] = initial_state["hidden"][
            "fault_id"
        ]

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_hidden_truth_in_action_schema_metadata() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["actions"][0]["input_schema"]["future_evidence_note"] = {
        "scenario_faults": {
            scenario["id"]: scenario["initial_state"]["hidden"]["fault_id"]
            for scenario in document["scenarios"]
        }
    }

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


@pytest.mark.parametrize(
    "location",
    (
        "observation_property",
        "hidden_property",
        "action_property",
        "scenario_initial_state",
    ),
)
def test_mesoscope_module_rejects_namespaced_additions_below_closed_paths(
    location: str,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    annotation = {"label": "must remain unreachable"}
    if location == "observation_property":
        document["observation_schema"]["properties"]["stage"][
            "future_evidence_note"
        ] = annotation
    elif location == "hidden_property":
        document["hidden_state_schema"]["properties"]["fault_id"][
            "future_evidence_note"
        ] = annotation
    elif location == "action_property":
        document["actions"][0]["input_schema"]["properties"][
            "future_evidence_note"
        ] = {"type": "string"}
    else:
        document["scenarios"][0]["initial_state"]["future_evidence_note"] = annotation

    with pytest.raises(BundleValidationError, match="sealed action|reviewed sealed"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_quarantines_operational_nested_provenance_copy() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["visualization"]["profile_provenance"]["future_evidence_note"] = (
        "Evidence note: use laser at 920 nm and PMT at 900 V."
    )

    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))

    assert module.bundle.visualization["profile_provenance"][
        "future_evidence_note"
    ] == "Evidence note: use laser at 920 nm and PMT at 900 V."
    assert (
        "future_evidence_note"
        not in module.visualization.profile_provenance.model_dump(mode="json")
    )


def test_mesoscope_module_rejects_a_rehashed_or_unsigned_plan_mutation() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    signed_plan = document["scenarios"][0]["initial_state"]["policy_visible"][
        "signed_plan"
    ]
    signed_plan["regions"][0]["z_label"] = "Z-B"
    signed_plan["signature_digest"] = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "plan_id": signed_plan["plan_id"],
                "immutable": signed_plan["immutable"],
                "regions": signed_plan["regions"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(BundleValidationError, match="reviewed signed-plan contract"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_an_unsigned_minor_addition_to_the_signed_plan(
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    signed_plan = document["scenarios"][0]["initial_state"]["policy_visible"][
        "signed_plan"
    ]
    signed_plan_schema = document["observation_schema"]["properties"]["signed_plan"]
    signed_plan_schema["properties"]["future_annotation"] = {"type": "object"}
    signed_plan["future_annotation"] = {"label": "Unsigned plan annotation"}

    with pytest.raises(BundleValidationError, match="reviewed signed-plan contract"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


@pytest.mark.parametrize(
    "tamper_kind",
    (
        "simulation_label",
        "apparatus_boundary",
        "simulation_notice",
        "sealed_profile",
        "survey_identity",
        "safety_gate",
    ),
)
def test_mesoscope_module_rejects_a_rehashed_safety_boundary_mutation(
    tamper_kind: str,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    properties = document["observation_schema"]["properties"]

    if tamper_kind == "simulation_label":
        document["simulation_label"] = "REAL APPARATUS READY"
    elif tamper_kind == "apparatus_boundary":
        document["apparatus"]["simulation_only"] = False
        document["apparatus"]["sealed"] = False
        document["apparatus"]["physical_control_available"] = True
    elif tamper_kind == "simulation_notice":
        properties["simulation_notice"]["const"] = "REAL APPARATUS READY"
        for scenario in document["scenarios"]:
            scenario["initial_state"]["policy_visible"]["simulation_notice"] = (
                "REAL APPARATUS READY"
            )
    elif tamper_kind == "sealed_profile":
        properties["sealed_profile"]["properties"]["simulation_only"][
            "const"
        ] = False
        properties["sealed_profile"]["properties"]["status"]["const"] = "live"
        for scenario in document["scenarios"]:
            profile = scenario["initial_state"]["policy_visible"]["sealed_profile"]
            profile["simulation_only"] = False
            profile["status"] = "live"
    elif tamper_kind == "survey_identity":
        survey_schema = properties["survey"]["properties"]
        survey_schema["synthetic"]["const"] = False
        survey_schema["watermark"]["const"] = "LIVE"
        for scenario in document["scenarios"]:
            survey = scenario["initial_state"]["policy_visible"]["survey"]
            survey["synthetic"] = False
            survey["watermark"] = "LIVE"
    else:
        gate_schema = properties["safety_gate"]["properties"]
        gate_schema["immutable"]["const"] = False
        gate_schema["independently_enforced"]["const"] = False
        for scenario in document["scenarios"]:
            gate = scenario["initial_state"]["policy_visible"]["safety_gate"]
            gate["immutable"] = False
            gate["independently_enforced"] = False

    with pytest.raises(BundleValidationError, match="sealed|simulation|safety"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_a_profile_selection_that_contradicts_the_seal(
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    profile_catalog = document["scenarios"][0]["initial_state"]["policy_visible"][
        "profile_catalog"
    ]
    profile_catalog[0]["selected"] = False
    profile_catalog[1]["selected"] = True

    with pytest.raises(BundleValidationError, match="sealed profile"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


@pytest.mark.parametrize(
    "tamper_kind",
    (
        "apparatus_field",
        "visible_field",
        "action_copy",
        "presentation_copy",
    ),
)
def test_mesoscope_module_rejects_operational_fields_or_copy_anywhere(
    tamper_kind: str,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    if tamper_kind == "apparatus_field":
        document["apparatus"]["laser_power_watts"] = 100
    elif tamper_kind == "visible_field":
        document["observation_schema"]["properties"]["hardware_connector"] = {
            "type": "string"
        }
        document["observation_schema"]["required"].append("hardware_connector")
        for scenario in document["scenarios"]:
            scenario["initial_state"]["policy_visible"]["hardware_connector"] = (
                "connected"
            )
    elif tamper_kind == "action_copy":
        document["actions"][0]["title"] = "Set laser power to 100 mW"
    elif tamper_kind == "presentation_copy":
        document["visualization"]["title"] = "LASER READY — SET 100 mW"
    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_mesoscope_module_rejects_a_preloaded_terminal_success_lifecycle() -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    initial_state = document["scenarios"][0]["initial_state"]
    visible = initial_state["policy_visible"]
    visible["stage"] = "complete"
    visible["summary"] = "MOCK PACKAGE VERIFIED"
    visible["validation_status"] = "valid"
    visible["terminal_status"] = "MOCK PACKAGE VERIFIED"
    hidden = initial_state["hidden"]
    hidden["acquisition_complete"] = True
    hidden["validation_complete"] = True
    hidden["package_valid"] = True
    hidden["terminal_action"] = "accepted"

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))
