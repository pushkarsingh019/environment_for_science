from copy import deepcopy

import pytest

from environments.eeg import load_seeded_bundle
from environments.eeg.runtime import EegMarkerRecoveryModule
from studio.bundle import BundleValidationError, validate_environment_bundle


def test_seeded_eeg_bundle_validates_as_environment_bundle_v1() -> None:
    bundle = load_seeded_bundle()

    validated = validate_environment_bundle(bundle)

    assert validated.contract_version == "1.0"
    assert validated.bundle_id == "eeg-onset-marker-recovery"
    assert validated.simulation_label == "Synthetic EEG apparatus simulation"
    assert validated.action_types == (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
        "restart_response_handshake",
    )


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
    assert validated.model_extra == {
        "future_minor_extension": {"enabled": True}
    }


def test_eeg_module_adapts_the_prior_v1_presentation_shape() -> None:
    document = load_seeded_bundle()
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
    document = load_seeded_bundle()
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
    leaky_bundle["observation_schema"]["properties"]["refractory_route_repaired"] = {
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
    bundle["scenarios"][0]["initial_state"]["policy_visible"]["onset_timeline"][
        "marker_count"
    ] = "two"

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
        match="duplicate action type identities: inspect_onset_route",
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
    del document["visualization"]["route_nodes"]
    bundle = validate_environment_bundle(document)

    with pytest.raises(
        BundleValidationError,
        match="invalid EEG onset-route visualization",
    ):
        EegMarkerRecoveryModule(bundle)
