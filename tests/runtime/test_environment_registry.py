from __future__ import annotations

import pytest

from environments.eeg import load_legacy_bundle
from environments.eeg.runtime import EegEnvironmentModule
from environments.mesoscope.runtime import MesoscopeEnvironmentModule
from studio.bundle import validate_environment_bundle
from studio.registry import EnvironmentRegistry, EnvironmentRegistryError
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
)

POLICY = PolicyAgentIdentity(id="conformance-policy", name="Conformance policy")


def test_registry_installs_two_environment_adapters_behind_one_module_seam() -> None:
    registry = EnvironmentRegistry.from_seeded_environments()

    assert [entry.environment_id for entry in registry.catalog] == [
        "eeg-curriculum",
        "mesoscope-four-region-handoff",
    ]
    assert [entry.environment_kind for entry in registry.catalog] == [
        "eeg",
        "mesoscope",
    ]
    assert [entry.source_kind for entry in registry.catalog] == [
        "editable_draft",
        "sealed_seed",
    ]
    assert isinstance(
        registry.module_for_bundle(registry.bundle("eeg-curriculum")),
        EegEnvironmentModule,
    )
    assert isinstance(
        registry.module_for_bundle(registry.bundle("mesoscope-four-region-handoff")),
        MesoscopeEnvironmentModule,
    )


def test_registry_returns_detached_bundles_and_neutral_console_examples() -> None:
    registry = EnvironmentRegistry.from_seeded_environments()
    first = registry.bundle("mesoscope-four-region-handoff")
    second = registry.bundle("mesoscope-four-region-handoff")
    first.title = "mutated caller copy"

    assert second.title == "Sealed mesoscope four-region handoff"
    choices = registry.seeded_scenarios("mesoscope-four-region-handoff")
    assert [choice.label for choice in choices] == [
        "Sealed example A",
        "Sealed example B",
        "Sealed example C",
        "Sealed example D",
        "Sealed example E",
        "Sealed example F",
        "Sealed example G",
        "Sealed example H",
    ]
    assert {choice.stage for choice in choices} == {"sealed_handoff"}
    serialized = " ".join(
        f"{choice.scenario_id} {choice.label}" for choice in choices
    ).casefold()
    for hidden_term in (
        "valid",
        "missing",
        "wrong",
        "duplicate",
        "motion",
        "checksum",
    ):
        assert hidden_term not in serialized


def test_registry_rejects_unknown_environment_and_bundle_identities() -> None:
    registry = EnvironmentRegistry.from_seeded_environments()

    with pytest.raises(EnvironmentRegistryError, match="unknown Environment"):
        registry.bundle("unknown-environment")

    forged = registry.bundle("mesoscope-four-region-handoff")
    forged.bundle_id = "forged-environment"
    with pytest.raises(EnvironmentRegistryError, match="not registered"):
        registry.module_for_bundle(forged)


def test_registry_restores_only_the_known_historical_eeg_identity() -> None:
    registry = EnvironmentRegistry.from_seeded_environments()
    legacy = validate_environment_bundle(load_legacy_bundle())

    assert isinstance(registry.module_for_bundle(legacy), EegEnvironmentModule)

    legacy.bundle_id = "forged-environment"
    with pytest.raises(EnvironmentRegistryError, match="not registered"):
        registry.module_for_bundle(legacy)


@pytest.mark.parametrize(
    ("environment_id", "actions"),
    (
        (
            "eeg-curriculum",
            (
                "inspect_configuration",
                "inspect_eeg_signals",
                "inspect_onset_route",
                "inspect_response_timeline",
                "inspect_recording_timeline",
                "complete_preflight",
            ),
        ),
        (
            "mesoscope-four-region-handoff",
            (
                "inspect_sealed_handoff",
                "run_mock_acquisition",
                "validate_mock_package",
                "accept_mock_package",
            ),
        ),
    ),
)
def test_registered_adapters_share_the_canonical_lifecycle_and_result_shape(
    environment_id: str,
    actions: tuple[str, ...],
) -> None:
    registry = EnvironmentRegistry.from_seeded_environments()
    bundle = registry.bundle(environment_id)
    runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    scenario_id = registry.seeded_scenarios(environment_id)[0].scenario_id

    current = runtime.start(scenario_id, POLICY)
    for action_type in actions:
        current = runtime.apply_action(
            current.run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )
    completed = runtime.verify(current.run_id)

    assert completed.status == "completed"
    assert completed.verifier_result is not None
    assert completed.verifier_result.passed is True
    assert completed.trace_header.bundle_id == bundle.bundle_id
    assert completed.trace[0].type == "observation"
    assert completed.trace[-1].type == "verifier"
    assert completed.trace_digest.startswith("sha256:")
    assert completed.result_digest is not None
    assert completed.result_digest.startswith("sha256:")

    reset = runtime.reset(completed.run_id)
    replay = runtime.replay(completed.run_id)
    assert reset.lineage.operation == "reset"
    assert reset.scenario_digest == completed.scenario_digest
    assert replay.trace_matches is True
    assert replay.result_matches is True
