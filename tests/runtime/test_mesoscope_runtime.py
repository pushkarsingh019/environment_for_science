from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy

import pytest

from environments.mesoscope import MESOSCOPE_SCENARIO_IDS, load_seeded_bundle
from environments.mesoscope.runtime import MesoscopeEnvironmentModule
from studio.bundle import (
    BundleValidationError,
    ScenarioManifest,
    validate_environment_bundle,
)
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    EpisodeState,
    PolicyAgentIdentity,
    RunSnapshot,
    RuntimeContractError,
)

POLICY = PolicyAgentIdentity(
    id="sealed-handoff-policy",
    name="Sealed handoff Policy agent",
)
SUCCESS_WORDING = "MOCK PACKAGE VERIFIED"

EXPECTED_FAILED_CHECK = {
    "mesoscope-demo-002": "region_agreement",
    "mesoscope-demo-003": "z_assignment",
    "mesoscope-demo-004": "channel_agreement",
    "mesoscope-demo-005": "event_records",
    "mesoscope-demo-006": "event_records",
    "mesoscope-demo-007": "motion_rows",
    "mesoscope-demo-008": "checksums",
}
EXPECTED_FAULT_CODE = {
    "mesoscope-demo-002": "MISSING_REGION",
    "mesoscope-demo-003": "WRONG_Z_ASSIGNMENT",
    "mesoscope-demo-004": "MISSING_CHANNEL",
    "mesoscope-demo-005": "DUPLICATE_EVENT",
    "mesoscope-demo-006": "MISSING_EVENT",
    "mesoscope-demo-007": "MOTION_ROW_MISMATCH",
    "mesoscope-demo-008": "CHECKSUM_MISMATCH",
}


@pytest.fixture
def runtime() -> Iterator[EnvironmentRuntime]:
    yield EnvironmentRuntime(
        MesoscopeEnvironmentModule(
            validate_environment_bundle(load_seeded_bundle()),
        )
    )


def _apply(runtime: EnvironmentRuntime, run: RunSnapshot, action: str) -> RunSnapshot:
    return runtime.apply_action(
        run.run_id,
        EnvironmentAction(type=action, arguments={}),
    )


def _validate_package(
    runtime: EnvironmentRuntime,
    scenario_id: str,
) -> RunSnapshot:
    run = runtime.start(scenario_id, POLICY)
    run = _apply(runtime, run, "inspect_sealed_handoff")
    run = _apply(runtime, run, "run_mock_acquisition")
    return _apply(runtime, run, "validate_mock_package")


def _package_check_statuses(run: RunSnapshot) -> dict[str, str]:
    checks = run.observation["package_checks"]
    assert isinstance(checks, list)
    return {
        str(check["check_id"]): str(check["status"])
        for check in checks
        if isinstance(check, dict)
    }


def test_runtime_validates_against_the_reviewed_schema_projection() -> None:
    document = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    sentinel = "Set laser power to 100 mW — runtime schema sentinel"
    document["future_runtime_note"] = {"label": sentinel}
    document["apparatus"]["future_runtime_note"] = {"label": sentinel}
    document["actions"][0]["future_runtime_note"] = {"label": sentinel}
    document["actions"][0]["input_schema"]["future_evidence_note"] = {
        "label": sentinel
    }
    document["procedure"]["future_runtime_note"] = {"label": sentinel}
    document["scenarios"][0]["future_runtime_note"] = {"label": sentinel}
    document["verifier"]["future_runtime_note"] = {"label": sentinel}
    document["visualization"]["future_runtime_note"] = {"label": sentinel}
    document["observation_schema"]["future_evidence_note"] = {
        "properties": {"fault_id": {"type": "string"}}
    }
    document["hidden_state_schema"]["future_evidence_note"] = {
        "properties": {"terminal_action": {"type": "string"}}
    }
    module = MesoscopeEnvironmentModule(validate_environment_bundle(document))

    assert module.bundle.actions[0].input_schema["future_evidence_note"] == {
        "label": sentinel
    }
    assert sentinel in module.bundle.model_dump_json()
    projected = module.runtime_validation_bundle
    assert projected.actions[0].input_schema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert "future_evidence_note" not in projected.observation_schema
    assert "future_evidence_note" not in projected.hidden_state_schema

    runtime = EnvironmentRuntime(module)
    started = runtime.start(MESOSCOPE_SCENARIO_IDS[0], POLICY)
    inspected = _apply(runtime, started, "inspect_sealed_handoff")
    serialized = started.model_dump_json() + inspected.model_dump_json()

    assert started.permitted_actions == ("inspect_sealed_handoff",)
    assert "future_evidence_note" not in serialized
    assert sentinel not in serialized
    with pytest.raises(RuntimeContractError, match="do not match its schema"):
        runtime.apply_action(
            inspected.run_id,
            EnvironmentAction(
                type="run_mock_acquisition",
                arguments={"future_laser_power": 100},
            ),
        )

    acquired = _apply(runtime, inspected, "run_mock_acquisition")
    validated = _apply(runtime, acquired, "validate_mock_package")
    accepted = _apply(runtime, validated, "accept_mock_package")
    completed = runtime.verify(accepted.run_id)
    completed_payload = completed.model_dump_json()
    assert "future_runtime_note" not in completed_payload
    assert "future_evidence_note" not in completed_payload
    assert sentinel not in completed_payload


def test_valid_four_region_package_is_verified_only_after_exact_agreement(
    runtime: EnvironmentRuntime,
) -> None:
    validated = _validate_package(runtime, "mesoscope-demo-001")

    assert validated.observation["validation_status"] == "valid"
    assert set(_package_check_statuses(validated).values()) == {"match"}
    assert [tile["region_id"] for tile in validated.observation["region_tiles"]] == [
        "R1",
        "R2",
        "R3",
        "R4",
    ]
    assert {tile["z_label"] for tile in validated.observation["region_tiles"]} == {
        "Z-A",
        "Z-B",
    }

    accepted = _apply(runtime, validated, "accept_mock_package")
    assert accepted.status == "awaiting_verification"
    assert accepted.observation["terminal_status"] == SUCCESS_WORDING
    completed = runtime.verify(accepted.run_id)

    assert completed.status == "completed"
    assert completed.verifier_result is not None
    assert completed.verifier_result.passed is True
    assert completed.verifier_result.terminal_disposition == "closed"
    assert completed.verifier_result.summary == SUCCESS_WORDING
    assert completed.verifier_result.metrics == {
        "reward": 1.0,
        "exact_terminal_match": 1.0,
        "fault_detection": 1.0,
        "package_agreement": 1.0,
        "safe_disposition": 1.0,
        "sealed_boundary": 1.0,
    }


def test_runtime_declares_only_state_current_mesoscope_actions(
    runtime: EnvironmentRuntime,
) -> None:
    started = runtime.start(MESOSCOPE_SCENARIO_IDS[0], POLICY)
    assert started.permitted_actions == ("inspect_sealed_handoff",)

    inspected = _apply(runtime, started, "inspect_sealed_handoff")
    assert inspected.permitted_actions == ("run_mock_acquisition",)

    acquired = _apply(runtime, inspected, "run_mock_acquisition")
    assert acquired.permitted_actions == ("validate_mock_package",)

    validated = _apply(runtime, acquired, "validate_mock_package")
    assert validated.permitted_actions == ("accept_mock_package",)

    invalid = _validate_package(runtime, MESOSCOPE_SCENARIO_IDS[1])
    assert invalid.permitted_actions == (
        "quarantine_mock_package",
        "reject_mock_package",
    )


@pytest.mark.parametrize("scenario_id", MESOSCOPE_SCENARIO_IDS[1:])
def test_every_invalid_package_detects_its_primary_fault_and_quarantines(
    runtime: EnvironmentRuntime,
    scenario_id: str,
) -> None:
    validated = _validate_package(runtime, scenario_id)
    statuses = _package_check_statuses(validated)
    failed_check = EXPECTED_FAILED_CHECK[scenario_id]

    assert validated.observation["validation_status"] == "invalid"
    assert statuses[failed_check] == "mismatch"
    assert set(statuses).difference({failed_check})
    assert validated.observation["detected_faults"] == [
        EXPECTED_FAULT_CODE[scenario_id]
    ]
    checksum_rows = validated.observation["package_checksums"]
    checksums_match = all(
        row["computed_digest"] == row["observed_digest"]
        for row in checksum_rows
    )
    assert checksums_match == (scenario_id != "mesoscope-demo-008")

    with pytest.raises(RuntimeContractError, match="cannot be accepted"):
        _apply(runtime, validated, "accept_mock_package")

    quarantined = _apply(runtime, validated, "quarantine_mock_package")
    assert quarantined.status == "awaiting_verification"
    assert quarantined.observation["terminal_status"] == (
        "SYNTHETIC PACKAGE QUARANTINED"
    )
    completed = runtime.verify(quarantined.run_id)

    assert completed.verifier_result is not None
    assert completed.verifier_result.passed is True
    assert completed.verifier_result.terminal_disposition == "aborted"
    assert SUCCESS_WORDING not in completed.model_dump_json()
    assert completed.verifier_result.metrics["package_agreement"] == 0.0
    assert completed.verifier_result.metrics["safe_disposition"] == 1.0


def test_invalid_package_may_be_rejected_but_never_repaired(
    runtime: EnvironmentRuntime,
) -> None:
    validated = _validate_package(runtime, "mesoscope-demo-008")
    rejected = _apply(runtime, validated, "reject_mock_package")
    completed = runtime.verify(rejected.run_id)

    assert completed.observation["terminal_status"] == "SYNTHETIC PACKAGE REJECTED"
    assert completed.verifier_result is not None
    assert completed.verifier_result.passed is True
    assert not any(
        term in action.casefold()
        for action in completed.trace_header.model_dump_json().split()
        for term in ("repair", "calibrate", "align", "tune")
    )


def test_profiles_plans_and_safety_gate_remain_immutable_across_the_episode(
    runtime: EnvironmentRuntime,
) -> None:
    started = runtime.start("mesoscope-demo-001", POLICY)
    profile = started.observation["sealed_profile"]
    plan = started.observation["signed_plan"]
    gate = started.observation["safety_gate"]

    run = _apply(runtime, started, "inspect_sealed_handoff")
    run = _apply(runtime, run, "run_mock_acquisition")
    run = _apply(runtime, run, "validate_mock_package")
    run = _apply(runtime, run, "accept_mock_package")

    assert run.observation["sealed_profile"] == profile
    assert run.observation["signed_plan"] == plan
    assert run.observation["safety_gate"] == gate


def test_reset_and_replay_preserve_the_sealed_scenario_and_canonical_result(
    runtime: EnvironmentRuntime,
) -> None:
    validated = _validate_package(runtime, "mesoscope-demo-001")
    accepted = _apply(runtime, validated, "accept_mock_package")
    completed = runtime.verify(accepted.run_id)
    reset = runtime.reset(completed.run_id)

    assert reset.scenario_id == completed.scenario_id
    assert reset.scenario_digest == completed.scenario_digest
    assert reset.revision_digest == completed.revision_digest
    assert reset.observation == completed.trace[0].observation
    assert reset.lineage.operation == "reset"
    assert reset.lineage.source_run_id == completed.run_id

    report = runtime.replay(completed.run_id)
    replayed = runtime.current(report.replay_run_id)
    assert report.trace_matches is True
    assert report.result_matches is True
    assert replayed.observation == completed.observation
    assert replayed.verifier_result == completed.verifier_result


def test_every_trace_summary_stays_explicitly_synthetic_or_sealed() -> None:
    for scenario_id in MESOSCOPE_SCENARIO_IDS:
        runtime = EnvironmentRuntime(
            MesoscopeEnvironmentModule(validate_environment_bundle(load_seeded_bundle()))
        )
        validated = _validate_package(runtime, scenario_id)
        terminal = _apply(
            runtime,
            validated,
            "accept_mock_package"
            if scenario_id == "mesoscope-demo-001"
            else "quarantine_mock_package",
        )
        completed = runtime.verify(terminal.run_id)

        for event in completed.trace:
            lowered = event.summary.casefold()
            assert (
                "synthetic" in lowered
                or "sealed" in lowered
                or event.summary == SUCCESS_WORDING
            )


@pytest.mark.parametrize("gate_state", ("open", "unknown"))
def test_unavailable_independent_gate_is_not_advertised_and_blocks_acquisition(
    gate_state: str,
) -> None:
    class UnavailableGateModule(MesoscopeEnvironmentModule):
        def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
            state = super().initialize(scenario)
            state.observation["safety_gate"]["state"] = gate_state
            return state

    runtime = EnvironmentRuntime(
        UnavailableGateModule(validate_environment_bundle(load_seeded_bundle()))
    )
    started = runtime.start(MESOSCOPE_SCENARIO_IDS[0], POLICY)
    inspected = _apply(runtime, started, "inspect_sealed_handoff")

    assert inspected.permitted_actions == ()

    with pytest.raises(RuntimeContractError, match="safety gate blocks"):
        runtime.apply_action(
            inspected.run_id,
            EnvironmentAction(type="run_mock_acquisition", arguments={}),
        )

    unchanged = runtime.current(inspected.run_id)
    assert unchanged.trace == inspected.trace
    assert unchanged.trace_digest == inspected.trace_digest
    assert unchanged.permitted_actions == ()


@pytest.mark.parametrize("checksum_tamper", ("missing", "duplicate", "forged"))
def test_checksum_evidence_must_be_complete_unique_and_payload_bound(
    checksum_tamper: str,
) -> None:
    module = MesoscopeEnvironmentModule(
        validate_environment_bundle(load_seeded_bundle())
    )
    state = module.initialize(module.bundle.scenarios[0])
    for action_type, next_state in (
        ("inspect_sealed_handoff", "inspection_complete"),
        ("run_mock_acquisition", "package_review"),
    ):
        update = module.apply_action(
            state,
            EnvironmentAction(type=action_type, arguments={}),
        )
        state = EpisodeState(
            procedure_state=next_state,
            observation=update.observation,
            hidden_state=update.hidden_state,
            state_revision=update.state_revision,
        )

    checksum_rows = state.observation["package_checksums"]
    assert isinstance(checksum_rows, list)
    if checksum_tamper == "missing":
        checksum_rows.clear()
    elif checksum_tamper == "duplicate":
        checksum_rows[-1] = deepcopy(checksum_rows[0])
    else:
        forged_digest = "sha256:" + "0" * 64
        checksum_rows[0] = {
            **checksum_rows[0],
            "expected_digest": forged_digest,
            "computed_digest": forged_digest,
            "observed_digest": forged_digest,
        }

    validated_update = module.apply_action(
        state,
        EnvironmentAction(type="validate_mock_package", arguments={}),
    )
    validated = EpisodeState(
        procedure_state="disposition_ready",
        observation=validated_update.observation,
        hidden_state=validated_update.hidden_state,
        state_revision=validated_update.state_revision,
    )

    assert validated.observation["validation_status"] == "invalid"
    assert {
        check["check_id"]: check["status"]
        for check in validated.observation["package_checks"]
    }["checksums"] == "mismatch"
    assert validated.observation["detected_faults"] == ["CHECKSUM_MISMATCH"]
    with pytest.raises(RuntimeContractError, match="cannot be accepted"):
        module.apply_action(
            validated,
            EnvironmentAction(type="accept_mock_package", arguments={}),
        )
    assert SUCCESS_WORDING not in str(validated.observation)


def test_forged_operational_action_is_rejected_before_any_trace_mutation(
    runtime: EnvironmentRuntime,
) -> None:
    started = runtime.start(MESOSCOPE_SCENARIO_IDS[0], POLICY)

    with pytest.raises(RuntimeContractError, match="unknown action"):
        runtime.apply_action(
            started.run_id,
            EnvironmentAction(type="set_laser_power", arguments={"value": 1}),
        )

    unchanged = runtime.current(started.run_id)
    assert unchanged.trace == started.trace
    assert unchanged.trace_digest == started.trace_digest


def test_valid_package_cannot_be_quarantined_and_premature_verification_fails(
    runtime: EnvironmentRuntime,
) -> None:
    premature = runtime.start(MESOSCOPE_SCENARIO_IDS[0], POLICY)
    premature = runtime.verify(premature.run_id)
    assert premature.verifier_result is not None
    assert premature.verifier_result.passed is False
    assert premature.verifier_result.outcome_category == "incomplete_or_unsafe"

    validated = _validate_package(runtime, MESOSCOPE_SCENARIO_IDS[0])
    with pytest.raises(RuntimeContractError, match="validated invalid"):
        _apply(runtime, validated, "quarantine_mock_package")
    assert runtime.current(validated.run_id).trace_digest == validated.trace_digest


def test_valid_package_has_reviewed_golden_package_and_canonical_digests(
    runtime: EnvironmentRuntime,
) -> None:
    validated = _validate_package(runtime, MESOSCOPE_SCENARIO_IDS[0])
    accepted = _apply(runtime, validated, "accept_mock_package")
    completed = runtime.verify(accepted.run_id)

    assert completed.revision_digest == (
        "sha256:9c9e20d9bd2fe2513d22cfaaf72fdb35631473fa1cdc8ed7c8df577e728f4677"
    )
    assert completed.scenario_digest == (
        "sha256:e889bd5d0918f8699b5f4e36273373cbf35fe23a19185708cc12d7a59955e866"
    )
    assert completed.trace_digest == (
        "sha256:e95d89f1dc5556c02af6cd6730936084812c7615eabc012382564261eac77f1b"
    )
    assert completed.result_digest == (
        "sha256:6c416816d7d0421da8ac8a9c16305902dc00f4f5564893dc59214e7d7685bfba"
    )
    assert {
        row["artifact_id"]: row["expected_digest"]
        for row in completed.observation["package_checksums"]
    } == {
        "synthetic-tiles": (
            "sha256:06c33c33e7b733ff230713a373ba3ae5bde58b9b0cab74b5b2807d27dbdac534"
        ),
        "channel-records": (
            "sha256:afc666ed8b744f8b04f1ed3549ff242fb44925b9d48cdf081c2a129d91382694"
        ),
        "event-records": (
            "sha256:759d8329cd1ad05d7122ed30001252468ffd525c2db3de86732fe4f40932dbec"
        ),
        "motion-rows": (
            "sha256:a4808e726f8aa1647ef12474d7d0205a0dffca8e2f544b9407fbaef46903305d"
        ),
        "package-manifest": (
            "sha256:1dc1491d19fcad4d9cc0e4c56b6b82c262e7ca63de96d7bf07abd19fd25f05dc"
        ),
    }


def test_visible_expected_frame_contract_must_match_observed_package() -> None:
    document = deepcopy(load_seeded_bundle())
    document["scenarios"][0]["initial_state"]["policy_visible"][
        "expected_outputs"
    ][0]["frame_count"] = 13

    with pytest.raises(BundleValidationError, match="reviewed sealed bundle"):
        MesoscopeEnvironmentModule(validate_environment_bundle(document))


def test_verifier_recomputes_package_and_lifecycle_instead_of_trusting_flags() -> None:
    module = MesoscopeEnvironmentModule(
        validate_environment_bundle(load_seeded_bundle())
    )
    scenario = module.bundle.scenarios[0]
    state = module.initialize(scenario)
    state.procedure_state = "mock_package_verified"
    state.observation["stage"] = "complete"
    state.observation["summary"] = SUCCESS_WORDING
    state.observation["validation_status"] = "valid"
    state.observation["terminal_status"] = SUCCESS_WORDING
    state.hidden_state["acquisition_complete"] = True
    state.hidden_state["validation_complete"] = True
    state.hidden_state["package_valid"] = True
    state.hidden_state["terminal_action"] = "accepted"

    outcome = module.verify(state)

    assert outcome.passed is False
    assert outcome.outcome_category == "incomplete_or_unsafe"
    assert outcome.metrics["package_agreement"] == 0.0
    assert outcome.metrics["safe_disposition"] == 0.0


@pytest.mark.parametrize("scenario_id", MESOSCOPE_SCENARIO_IDS)
def test_fresh_runtime_instances_reproduce_every_observation_and_digest(
    scenario_id: str,
) -> None:
    completed: list[RunSnapshot] = []
    for _ in range(2):
        runtime = EnvironmentRuntime(
            MesoscopeEnvironmentModule(validate_environment_bundle(load_seeded_bundle()))
        )
        validated = _validate_package(runtime, scenario_id)
        terminal = _apply(
            runtime,
            validated,
            "accept_mock_package"
            if scenario_id == MESOSCOPE_SCENARIO_IDS[0]
            else "quarantine_mock_package",
        )
        completed.append(runtime.verify(terminal.run_id))

    assert completed[0].observation == completed[1].observation
    assert completed[0].trace == completed[1].trace
    assert completed[0].trace_digest == completed[1].trace_digest
    assert completed[0].verifier_result == completed[1].verifier_result
    assert completed[0].result_digest == completed[1].result_digest
