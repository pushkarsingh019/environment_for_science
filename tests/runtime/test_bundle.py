from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from environments.eeg import load_legacy_bundle, load_seeded_bundle
from environments.eeg.authoring import (
    apply_authoring_command,
    compile_frozen_bundle,
    seed_authoring_state,
    stage_descriptive_note,
)
from environments.eeg.runtime import EegEnvironmentModule, EegMarkerRecoveryModule
from studio.bundle import BundleValidationError, validate_environment_bundle
from studio.runtime import EnvironmentRuntime, PolicyAgentIdentity


def test_seeded_eeg_bundle_validates_as_environment_bundle_v1() -> None:
    bundle = load_seeded_bundle()

    validated = validate_environment_bundle(bundle)

    assert validated.contract_version == "1.0"
    assert validated.bundle_id == "eeg-onset-marker-recovery"
    assert validated.simulation_label == "Synthetic EEG apparatus simulation"
    assert len(validated.action_types) == 25
    assert {
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
        "inspect_onset_route",
        "inspect_response_timeline",
        "inspect_recording_timeline",
        "reseat_electrode",
        "repair_refractory_route",
        "present_test_flash",
        "complete_preflight",
        "abort_preflight",
    }.issubset(validated.action_types)
    assert len(validated.scenarios) == 20


def test_preflight_fixture_content_is_bound_into_the_runtime_revision() -> None:
    original = load_seeded_bundle()
    changed = deepcopy(original)
    changed["preflight_fixture"]["cases"][0]["initial_summary"] = (
        "A deliberately changed but valid authored summary."
    )
    policy = PolicyAgentIdentity(id="fixture-policy", name="Fixture policy")

    original_run = EnvironmentRuntime(
        EegEnvironmentModule(validate_environment_bundle(original))
    ).start("eeg-demo-001", policy)
    changed_run = EnvironmentRuntime(
        EegEnvironmentModule(validate_environment_bundle(changed))
    ).start("eeg-demo-001", policy)

    assert original_run.revision_digest != changed_run.revision_digest
    assert original_run.observation["summary"] != changed_run.observation["summary"]


def test_preflight_rejects_disagreement_between_scenario_and_fixture_case_identity() -> None:
    document = load_seeded_bundle()
    document["scenarios"][0]["initial_state"]["hidden"]["case_id"] = "eeg-demo-002"

    with pytest.raises(BundleValidationError, match="case identity"):
        EegEnvironmentModule(validate_environment_bundle(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relevant_actions", ["repair_onset_route"]),
        ("retest_action", "present_test_flash"),
    ],
)
def test_preflight_fixture_actions_must_match_the_declared_evidence_domain(
    field: str,
    value: object,
) -> None:
    document = load_seeded_bundle()
    case = document["preflight_fixture"]["cases"][0]
    case[field] = value
    if field == "relevant_actions":
        case["effective_actions"] = ["repair_onset_route"]

    with pytest.raises(BundleValidationError, match="case domain"):
        EegEnvironmentModule(validate_environment_bundle(document))


def test_seeded_eeg_authoring_state_separates_whole_cap_from_procedure_montage() -> None:
    bundle = validate_environment_bundle(load_seeded_bundle())

    draft = seed_authoring_state(bundle)

    assert bundle.bundle_revision == "1.3.0"
    assert draft.apparatus.recording_input_capacity == 32
    assert len(draft.apparatus.sites) > len(draft.procedure.montage.recording_sites)
    assert "not exact cap geometry" in draft.apparatus.scientific_claim.lower()
    assert draft.procedure.montage.recording_sites == ("FC3", "FC4", "FT7", "FT8")
    assert draft.procedure.montage.reference == "FCz"
    assert draft.procedure.montage.ground == "A1"
    assert draft.procedure.acquisition_profile.sampling_hz == 1017
    assert draft.procedure.acquisition_profile.online_bandpass_hz == (0.1, 30.0)
    assert draft.procedure.acquisition_profile.notch_hz == 50


def test_eeg_authoring_command_adds_a_catalog_site_without_mutating_the_prior_draft() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    result = apply_authoring_command(original, "Add Cz to the Montage")

    assert result.status == "applied"
    assert result.reason == "montage_updated"
    assert "Cz" in result.summary
    assert result.state.procedure.montage.recording_sites == (
        "FC3",
        "FC4",
        "FT7",
        "FT8",
        "Cz",
    )
    assert original.procedure.montage.recording_sites == ("FC3", "FC4", "FT7", "FT8")


def test_eeg_authoring_command_removes_only_a_recording_site() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    result = apply_authoring_command(original, "Remove FT8 from the Montage")

    assert result.status == "applied"
    assert result.reason == "montage_updated"
    assert result.state.procedure.montage.recording_sites == ("FC3", "FC4", "FT7")

    reference_result = apply_authoring_command(original, "Remove FCz from the Montage")
    assert reference_result.status == "unsupported"
    assert reference_result.reason == "invalid_request"
    assert reference_result.state == original
    assert "reference" in reference_result.summary.lower()


def test_eeg_authoring_command_changes_a_supported_sampling_rate() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    result = apply_authoring_command(original, "Set the sampling rate to 512 Hz")

    assert result.status == "applied"
    assert result.reason == "acquisition_updated"
    assert result.state.procedure.acquisition_profile.sampling_hz == 512
    assert original.procedure.acquisition_profile.sampling_hz == 1017


def test_eeg_authoring_commands_change_bounded_notch_and_bandpass_settings() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    notch = apply_authoring_command(original, "Set the notch to 60 Hz")
    assert notch.status == "applied"
    assert notch.state.procedure.acquisition_profile.notch_hz == 60

    bandpass = apply_authoring_command(notch.state, "Set the bandpass to 1–40 Hz")
    assert bandpass.status == "applied"
    assert bandpass.state.procedure.acquisition_profile.online_bandpass_hz == (1.0, 40.0)

    unsafe = apply_authoring_command(original, "Set the bandpass to 30-600 Hz")
    assert unsafe.status == "unsupported"
    assert unsafe.reason == "invalid_request"
    assert unsafe.state == original
    assert "supported" in unsafe.summary.lower()

    unchanged = apply_authoring_command(original, "Set the notch to 50 Hz")
    assert unchanged.status == "unsupported"
    assert unchanged.reason == "invalid_request"
    assert unchanged.state == original
    assert "already" in unchanged.summary.lower()


def test_eeg_authoring_rejects_ambiguous_or_unsupported_requests_without_mutation() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    ambiguous = apply_authoring_command(
        original,
        "Add Cz to the Montage and set the notch to 60 Hz",
    )
    unsupported = apply_authoring_command(original, "Connect to the EEG amplifier")

    assert ambiguous.status == "unsupported"
    assert ambiguous.reason == "ambiguous_request"
    assert ambiguous.state == original
    assert unsupported.status == "unsupported"
    assert unsupported.reason == "unsupported_request"
    assert unsupported.state == original
    for result in (ambiguous, unsupported):
        explanation = result.summary.lower()
        assert "schema" not in explanation
        assert "json" not in explanation
        assert "code" not in explanation


def test_eeg_authoring_stages_a_deterministic_unverified_noncontrolling_note() -> None:
    original = seed_authoring_state(validate_environment_bundle(load_seeded_bundle()))

    staged = stage_descriptive_note(
        original,
        filename="preflight-observation.txt",
        content="Confirm the participant-facing onset cue before a session.",
    )
    repeated = stage_descriptive_note(
        original,
        filename="preflight-observation.txt",
        content="Confirm the participant-facing onset cue before a session.",
    )

    assert original.notes == ()
    assert len(staged.notes) == 1
    assert staged.notes[0].id == repeated.notes[0].id
    assert staged.notes[0].filename == "preflight-observation.txt"
    assert staged.notes[0].verification_status == "unverified_descriptive_input"
    assert staged.notes[0].run_control is False


def test_eeg_authoring_compiles_a_validated_revision_without_note_content() -> None:
    source = validate_environment_bundle(load_seeded_bundle())
    draft = seed_authoring_state(source)
    draft = apply_authoring_command(draft, "Add Cz to the Montage").state
    note_text = "Treat this local description as context, never as run control."
    draft = stage_descriptive_note(draft, "local-note.txt", note_text)

    frozen = compile_frozen_bundle(source, draft, revision=7)

    assert frozen.bundle_revision == "1.3.7"
    configuration = frozen.procedure.model_extra["configuration"]
    assert configuration["montage"]["recording_sites"] == [
        "FC3",
        "FC4",
        "FT7",
        "FT8",
        "Cz",
    ]
    observation = frozen.scenarios[0].initial_state.policy_visible
    assert observation["procedure_configuration"] == configuration
    assert note_text not in frozen.model_dump_json()
    assert "notes" not in observation
    assert frozen.model_extra is not None
    assert frozen.model_extra["preflight_fixture"] == source.model_extra[
        "preflight_fixture"
    ]
    assert compile_frozen_bundle(source, draft, revision=7) == frozen


def test_eeg_authoring_freeze_preserves_v1_minor_extensions_and_detaches_values() -> None:
    document = load_seeded_bundle()
    document["contract_version"] = "1.8"
    document["future_bundle_extension"] = {"enabled": True}
    document["apparatus"]["future_capability_extension"] = {"layout": "future"}
    document["procedure"]["future_procedure_extension"] = "kept"
    document["procedure"]["configuration"]["future_configuration_extension"] = {
        "enabled": True
    }
    document["observation_schema"]["properties"]["procedure_configuration"][
        "future_schema_extension"
    ] = {"enabled": True}
    source = validate_environment_bundle(document)
    draft = seed_authoring_state(source)

    frozen = compile_frozen_bundle(source, draft, revision=3)
    source.apparatus["label"] = "Mutated after freezing"
    document["procedure"]["configuration"]["name"] = "Mutated source document"

    assert frozen.model_extra["future_bundle_extension"] == {"enabled": True}
    assert frozen.apparatus["future_capability_extension"] == {"layout": "future"}
    assert frozen.procedure.model_extra["future_procedure_extension"] == "kept"
    configuration = frozen.procedure.model_extra["configuration"]
    assert configuration["future_configuration_extension"] == {"enabled": True}
    assert frozen.observation_schema["properties"]["procedure_configuration"][
        "future_schema_extension"
    ] == {"enabled": True}
    assert frozen.apparatus["label"] == "Configurable whole-cap scalp EEG chain"
    assert draft.procedure.name == "EEG onset-marker preflight"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda document: document["procedure"]["configuration"]["montage"].update(
                {"reference": "FC3"}
            ),
            "roles must be disjoint",
        ),
        (
            lambda document: document["procedure"]["configuration"]["montage"].update(
                {"recording_sites": ["FC3", "FC3"]}
            ),
            "duplicate recording sites",
        ),
        (
            lambda document: document["procedure"]["configuration"]["montage"].update(
                {"recording_sites": ["FC3", "missing-site"]}
            ),
            "absent from the Apparatus catalog",
        ),
        (
            lambda document: document["apparatus"].update(
                {"recording_input_capacity": 2}
            ),
            "exceeds the Apparatus recording-input capacity",
        ),
    ],
)
def test_eeg_authoring_rejects_invalid_site_roles_and_capability(
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    document = load_seeded_bundle()
    mutate(document)
    bundle = validate_environment_bundle(document)

    with pytest.raises(BundleValidationError, match=message):
        seed_authoring_state(bundle)


def test_eeg_authoring_rejects_site_positions_outside_the_schematic_plane() -> None:
    document = load_seeded_bundle()
    document["apparatus"]["sites"][0]["x"] = 120
    bundle = validate_environment_bundle(document)

    with pytest.raises(BundleValidationError, match="less than or equal to 100"):
        seed_authoring_state(bundle)


def test_eeg_authoring_rejects_nonfinite_acquisition_values() -> None:
    document = load_seeded_bundle()
    document["procedure"]["configuration"]["acquisition_profile"][
        "online_bandpass_hz"
    ] = [float("nan"), 30.0]
    bundle = validate_environment_bundle(document)

    with pytest.raises(BundleValidationError, match="finite values"):
        seed_authoring_state(bundle)


def test_eeg_authoring_rejects_case_ambiguous_site_identities() -> None:
    document = load_seeded_bundle()
    duplicate = deepcopy(document["apparatus"]["sites"][9])
    duplicate["id"] = "fc3"
    duplicate["label"] = "fc3"
    document["apparatus"]["sites"].append(duplicate)
    bundle = validate_environment_bundle(document)

    with pytest.raises(BundleValidationError, match="duplicate identities"):
        seed_authoring_state(bundle)


def test_bundle_validation_rejects_unknown_major_versions() -> None:
    bundle = load_seeded_bundle()
    bundle["contract_version"] = "2.0"

    with pytest.raises(BundleValidationError, match="unsupported contract major version 2"):
        validate_environment_bundle(bundle)


def test_bundle_validation_accepts_supported_minor_versions_and_extensions() -> None:
    bundle = load_seeded_bundle()
    bundle["contract_version"] = "1.7"
    bundle["future_minor_extension"] = {"enabled": True}

    validated = validate_environment_bundle(bundle)

    assert validated.contract_version == "1.7"
    assert validated.model_extra is not None
    assert validated.model_extra["future_minor_extension"] == {"enabled": True}
    assert validated.model_extra["preflight_fixture"] == bundle["preflight_fixture"]


def test_eeg_module_adapts_the_prior_v1_presentation_shape() -> None:
    document = load_legacy_bundle()
    del document["description"]
    document["visualization"] = {
        "primary_view": "onset_timeline",
        "labels": ["Synthetic data", "Simulated apparatus only"],
    }

    validated = validate_environment_bundle(document)
    environment = EegMarkerRecoveryModule(validated)

    assert validated.description is None
    assert environment.visualization.kind == "eeg_onset_route"
    assert [node.id for node in environment.visualization.route_nodes] == [
        "light_detector",
        "refractory_route",
    ]


def test_eeg_module_accepts_nested_minor_visualization_extensions() -> None:
    document = load_legacy_bundle()
    document["contract_version"] = "1.7"
    document["visualization"]["future_minor_extension"] = {"enabled": True}
    document["visualization"]["route_nodes"][0]["future_node_extension"] = "kept"

    environment = EegMarkerRecoveryModule(
        validate_environment_bundle(document)
    )

    assert environment.visualization.kind == "eeg_onset_route"
    assert environment.bundle.visualization["future_minor_extension"] == {
        "enabled": True
    }
    assert environment.bundle.visualization["route_nodes"][0][
        "future_node_extension"
    ] == "kept"


def test_bundle_validation_keeps_visible_and_hidden_scenario_state_separate() -> None:
    bundle = load_seeded_bundle()
    leaky_bundle = deepcopy(bundle)
    leaky_bundle["observation_schema"]["properties"]["case_id"] = {
        "type": "boolean"
    }

    with pytest.raises(BundleValidationError, match="visible and hidden state overlap"):
        validate_environment_bundle(leaky_bundle)


def test_bundle_validation_rejects_missing_required_scenario_observation() -> None:
    bundle = load_seeded_bundle()
    del bundle["scenarios"][0]["initial_state"]["policy_visible"]["stage"]

    with pytest.raises(
        BundleValidationError,
        match="missing required visible state: stage",
    ):
        validate_environment_bundle(bundle)


def test_bundle_validation_rejects_invalid_nested_observation_values() -> None:
    bundle = load_seeded_bundle()
    bundle["scenarios"][0]["initial_state"]["policy_visible"][
        "procedure_configuration"
    ]["acquisition_profile"]["sampling_hz"] = "fast"

    with pytest.raises(
        BundleValidationError,
        match="visible state does not match its schema",
    ):
        validate_environment_bundle(bundle)


def test_bundle_validation_rejects_an_unreachable_terminal_state() -> None:
    bundle = load_seeded_bundle()
    bundle["procedure"]["states"].append(
        {"id": "orphan_terminal", "terminal": True}
    )

    with pytest.raises(
        BundleValidationError,
        match="unreachable terminal states: orphan_terminal",
    ):
        validate_environment_bundle(bundle)


def test_bundle_validation_rejects_malformed_action_and_observation_schemas() -> None:
    malformed_action = load_seeded_bundle()
    malformed_action["actions"][0]["input_schema"]["required"] = ["undeclared"]
    with pytest.raises(
        BundleValidationError,
        match="requires unknown properties: undeclared",
    ):
        validate_environment_bundle(malformed_action)

    malformed_observation = load_seeded_bundle()
    malformed_observation["observation_schema"]["properties"]["summary"] = "string"
    with pytest.raises(
        BundleValidationError,
        match="observation_schema contains a malformed property",
    ):
        validate_environment_bundle(malformed_observation)


def test_bundle_validation_rejects_invalid_references_and_duplicate_identities() -> None:
    invalid_reference = load_seeded_bundle()
    invalid_reference["procedure"]["transitions"][0]["action"] = "missing_action"
    with pytest.raises(
        BundleValidationError,
        match="references an unknown action",
    ):
        validate_environment_bundle(invalid_reference)

    duplicate_action = load_seeded_bundle()
    duplicate_action["actions"].append(deepcopy(duplicate_action["actions"][0]))
    with pytest.raises(
        BundleValidationError,
        match="duplicate action type identities: inspect_eeg_signals",
    ):
        validate_environment_bundle(duplicate_action)


def test_bundle_validation_rejects_invalid_split_membership() -> None:
    bundle = load_seeded_bundle()
    bundle["scenarios"][0]["split"] = "held-out"

    with pytest.raises(
        BundleValidationError,
        match="references an unknown split",
    ):
        validate_environment_bundle(bundle)


def test_eeg_module_rejects_malformed_apparatus_visualization_data() -> None:
    document = load_seeded_bundle()
    del document["visualization"]["scalp_sites"]
    bundle = validate_environment_bundle(document)

    with pytest.raises(
        BundleValidationError,
        match="invalid EEG preflight visualization",
    ):
        EegEnvironmentModule(bundle)
