from copy import deepcopy

import pytest

from environments.eeg import load_seeded_bundle
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


def test_bundle_validation_keeps_visible_and_hidden_scenario_state_separate() -> None:
    bundle = load_seeded_bundle()
    leaky_bundle = deepcopy(bundle)
    leaky_bundle["observation_schema"]["properties"]["refractory_route_repaired"] = {
        "type": "boolean"
    }

    with pytest.raises(BundleValidationError, match="visible and hidden state overlap"):
        validate_environment_bundle(leaky_bundle)
