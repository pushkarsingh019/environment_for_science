"""Public-seam acceptance tests for the synthetic EEG diagnostic preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from environments.eeg import load_seeded_bundle
from environments.eeg.authoring import (
    apply_authoring_command,
    compile_frozen_bundle,
    seed_authoring_state,
)
from environments.eeg.runtime import EegEnvironmentModule
from studio.bundle import validate_environment_bundle
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
)

POLICY = PolicyAgentIdentity(id="policy-test", name="Policy test agent")


def _runtime() -> EnvironmentRuntime:
    return EnvironmentRuntime(EegEnvironmentModule.from_seed())


def _act(
    runtime: EnvironmentRuntime,
    run_id: str,
    action_type: str,
    **arguments: object,
):
    return runtime.apply_action(
        run_id,
        EnvironmentAction(type=action_type, arguments=dict(arguments)),
    )


def _assert_no_hidden_diagnostic_truth(value: object) -> None:
    forbidden = {
        "fault",
        "fault_family",
        "fault_target",
        "expected_action",
        "outcome_category",
        "recoverability",
        "recovery_depth",
        "quality_score",
    }

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                assert str(key).casefold() not in forbidden
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for nested in item:
                visit(nested)

    visit(value)


def test_seeded_preflight_starts_with_deterministic_visible_multichannel_evidence() -> None:
    first = _runtime().start("eeg-demo-001", POLICY)
    second = _runtime().start("eeg-demo-001", POLICY)

    assert first.observation == second.observation
    assert first.trace[0].observation == first.observation
    assert first.observation["simulation_label"] == "Synthetic EEG apparatus simulation"
    assert first.observation["stage"] == "diagnostic_preflight"

    montage = first.observation["montage"]
    assert montage["recording_sites"] == ["FC3", "FC4", "FT7", "FT8"]
    assert montage["reference"] == "FCz"
    assert montage["ground"] == "A1"
    assert montage["coordinate_note"].startswith("Schematic")

    window = first.observation["eeg_window"]
    assert window["status"] == "current"
    assert window["signal_stage"] == "synthetic post-online-bandpass display window"
    assert window["source_sampling_hz"] == 1017
    assert [channel["site"] for channel in window["channels"]] == [
        "FC3",
        "FC4",
        "FT7",
        "FT8",
    ]
    assert {len(channel["samples"]) for channel in window["channels"]} == {96}
    assert first.observation["frequency_evidence"] is None
    _assert_no_hidden_diagnostic_truth(first.observation)


def test_every_policy_visible_signal_sample_is_quantized_to_three_decimals() -> None:
    snapshot = _runtime().start("eeg-demo-005", POLICY)
    window = snapshot.observation["eeg_window"]
    sample_sets = [
        *(channel["samples"] for channel in window["channels"]),
        window["reference_comparison"]["samples"],
    ]

    assert all(
        sample == round(sample, 3)
        for samples in sample_sets
        for sample in samples
    )


def test_frequency_evidence_is_on_demand_and_binds_the_displayed_window() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)

    inspected = _act(runtime, started.run_id, "inspect_frequency_evidence")

    frequency = inspected.observation["frequency_evidence"]
    assert frequency["source_window_id"] == inspected.observation["eeg_window"][
        "evidence_id"
    ]
    assert frequency["signal_stage"] == inspected.observation["eeg_window"][
        "signal_stage"
    ]
    assert frequency["bins_hz"] == [2.0, 6.0, 10.0, 18.0, 26.0]
    assert [channel["site"] for channel in frequency["channels"]] == [
        "FC3",
        "FC4",
        "FT7",
        "FT8",
    ]
    assert all(len(channel["magnitudes"]) == 5 for channel in frequency["channels"])
    assert frequency["reference_comparison"]["site"] == "FCz"
    assert len(frequency["reference_comparison"]["magnitudes"]) == 5
    assert started.observation["eeg_window"]["reference_comparison"]["site"] == "FCz"
    assert len(
        started.observation["eeg_window"]["reference_comparison"]["samples"]
    ) == 96
    _assert_no_hidden_diagnostic_truth(frequency)


def test_frequency_relationships_use_the_bound_visible_window_after_a_change() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-005", POLICY)
    inspected = _act(runtime, started.run_id, "inspect_frequency_evidence")
    original_window = inspected.observation["eeg_window"]
    original_frequency = inspected.observation["frequency_evidence"]

    changed = _act(runtime, inspected.run_id, "reconnect_reference")
    remeasured = _act(runtime, changed.run_id, "inspect_frequency_evidence")

    assert remeasured.observation["eeg_window"]["evidence_id"] == original_window[
        "evidence_id"
    ]
    assert remeasured.observation["eeg_window"]["channels"] == original_window[
        "channels"
    ]
    assert remeasured.observation["eeg_window"]["reference_comparison"] == (
        original_window["reference_comparison"]
    )
    assert remeasured.observation["frequency_evidence"]["relationships"] == (
        original_frequency["relationships"]
    )
    assert remeasured.observation["frequency_evidence"]["status"] == "stale"


def test_targeted_change_invalidates_eeg_evidence_until_a_fresh_window() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)
    inspected = _act(runtime, started.run_id, "inspect_eeg_signals")
    inspected = _act(runtime, inspected.run_id, "inspect_frequency_evidence")
    original_window_id = inspected.observation["eeg_window"]["evidence_id"]

    changed = _act(
        runtime,
        inspected.run_id,
        "reseat_electrode",
        site="FC3",
    )

    assert changed.observation["eeg_window"]["evidence_id"] == original_window_id
    assert changed.observation["eeg_window"]["status"] == "stale"
    assert changed.observation["frequency_evidence"]["status"] == "stale"
    assert changed.observation["evidence_freshness"]["eeg"]["status"] == "stale"

    refreshed = _act(runtime, changed.run_id, "collect_fresh_eeg_window")
    assert refreshed.observation["eeg_window"]["evidence_id"] != original_window_id
    assert refreshed.observation["eeg_window"]["status"] == "current"
    assert refreshed.observation["frequency_evidence"] is None
    assert refreshed.observation["evidence_freshness"]["eeg"]["status"] == "current"

    terminal = _act(runtime, refreshed.run_id, "complete_preflight")
    verified = runtime.verify(terminal.run_id)
    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.terminal_disposition == "recovered"
    assert verified.verifier_result.outcome_category == "targeted_recovery"
    assert verified.verifier_result.metrics["fresh_validation"] == 1.0
    assert verified.verifier_result.metrics["targeted_intervention"] == 1.0


def test_terminal_without_fresh_post_change_evidence_is_classified_as_lucky() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)
    changed = _act(
        runtime,
        started.run_id,
        "reseat_electrode",
        site="FC3",
    )
    terminal = _act(runtime, changed.run_id, "complete_preflight")

    verified = runtime.verify(terminal.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is False
    assert verified.verifier_result.terminal_disposition == "failed"
    assert verified.verifier_result.outcome_category == "lucky_terminal"
    assert verified.verifier_result.metrics["fresh_validation"] == 0.0
    assert verified.verifier_result.metrics["targeted_intervention"] == 0.0
    assert any("fresh" in reason.casefold() for reason in verified.verifier_result.reasons)


def test_completion_cannot_pass_while_another_preflight_gate_is_stale() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)
    inspected = _act(runtime, started.run_id, "inspect_eeg_signals")
    inspected = _act(runtime, inspected.run_id, "inspect_frequency_evidence")
    repaired = _act(runtime, inspected.run_id, "reseat_electrode", site="FC3")
    refreshed = _act(runtime, repaired.run_id, "collect_fresh_eeg_window")
    unrelated_change = _act(runtime, refreshed.run_id, "repair_onset_route")
    assert unrelated_change.observation["evidence_freshness"]["onset"]["status"] == (
        "stale"
    )
    eeg_only_retest = _act(
        runtime,
        unrelated_change.run_id,
        "collect_fresh_eeg_window",
    )
    terminal = _act(runtime, eeg_only_retest.run_id, "complete_preflight")

    verified = runtime.verify(terminal.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is False
    assert verified.verifier_result.outcome_category == "lucky_terminal"
    assert verified.verifier_result.metrics["fresh_validation"] == 0.0
    assert any(
        "onset" in reason.casefold()
        for reason in verified.verifier_result.reasons
    )


def test_domain_local_retest_remains_fresh_after_another_domain_is_changed_and_retested() -> None:
    runtime = _runtime()
    snapshot = runtime.start("eeg-demo-001", POLICY)
    snapshot = _act(runtime, snapshot.run_id, "inspect_eeg_signals")
    snapshot = _act(runtime, snapshot.run_id, "inspect_frequency_evidence")
    snapshot = _act(runtime, snapshot.run_id, "reseat_electrode", site="FC3")
    snapshot = _act(runtime, snapshot.run_id, "collect_fresh_eeg_window")
    snapshot = _act(runtime, snapshot.run_id, "repair_onset_route")
    snapshot = _act(runtime, snapshot.run_id, "present_test_flash")
    assert {
        domain: details["status"]
        for domain, details in snapshot.observation["evidence_freshness"].items()
    } == {
        "eeg": "current",
        "onset": "current",
        "response": "current",
        "recording": "current",
    }
    snapshot = _act(runtime, snapshot.run_id, "complete_preflight")

    verified = runtime.verify(snapshot.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.metrics["fresh_validation"] == 1.0


def test_domain_retest_after_later_other_domain_change_is_still_fresh() -> None:
    runtime = _runtime()
    snapshot = runtime.start("eeg-demo-001", POLICY)
    snapshot = _act(runtime, snapshot.run_id, "inspect_eeg_signals")
    snapshot = _act(runtime, snapshot.run_id, "inspect_frequency_evidence")
    snapshot = _act(runtime, snapshot.run_id, "reseat_electrode", site="FC3")
    snapshot = _act(runtime, snapshot.run_id, "repair_onset_route")
    snapshot = _act(runtime, snapshot.run_id, "collect_fresh_eeg_window")
    snapshot = _act(runtime, snapshot.run_id, "present_test_flash")
    assert all(
        details["status"] == "current"
        for details in snapshot.observation["evidence_freshness"].values()
    )
    snapshot = _act(runtime, snapshot.run_id, "complete_preflight")

    verified = runtime.verify(snapshot.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.metrics["fresh_validation"] == 1.0


def test_wrong_path_with_fresh_evidence_is_classified_as_ineffective() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)
    inspected = _act(runtime, started.run_id, "inspect_eeg_signals")
    changed = _act(runtime, inspected.run_id, "reconnect_ground")
    refreshed = _act(runtime, changed.run_id, "collect_fresh_eeg_window")
    terminal = _act(runtime, refreshed.run_id, "complete_preflight")

    verified = runtime.verify(terminal.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is False
    assert verified.verifier_result.outcome_category == "ineffective_action"
    assert verified.verifier_result.metrics["terminal_correctness"] == 0.0


def test_unavailable_path_supports_evidence_bound_abort_but_nominal_abort_does_not() -> None:
    runtime = _runtime()
    unavailable = runtime.start("eeg-demo-018", POLICY)
    inspected = _act(runtime, unavailable.run_id, "inspect_eeg_signals")
    inspected = _act(runtime, inspected.run_id, "inspect_frequency_evidence")
    attempted = _act(
        runtime,
        inspected.run_id,
        "replace_electrode",
        site="FC3",
    )
    refreshed = _act(runtime, attempted.run_id, "collect_fresh_eeg_window")
    evidence_id = refreshed.observation["eeg_window"]["evidence_id"]
    aborted = _act(
        runtime,
        refreshed.run_id,
        "abort_preflight",
        path="eeg",
        evidence_id=evidence_id,
    )
    justified = runtime.verify(aborted.run_id)

    assert justified.verifier_result is not None
    assert justified.verifier_result.passed is True
    assert justified.verifier_result.terminal_disposition == "aborted"
    assert justified.verifier_result.outcome_category == "justified_abort"
    assert justified.verifier_result.evidence["evidence_id"] == evidence_id

    nominal = runtime.start("eeg-demo-016", POLICY)
    blanket = _act(
        runtime,
        nominal.run_id,
        "abort_preflight",
        path="eeg",
        evidence_id=nominal.observation["eeg_window"]["evidence_id"],
    )
    unjustified = runtime.verify(blanket.run_id)

    assert unjustified.verifier_result is not None
    assert unjustified.verifier_result.passed is False
    assert unjustified.verifier_result.terminal_disposition == "aborted"
    assert unjustified.verifier_result.outcome_category == "blanket_caution"


def test_reset_and_replay_preserve_preflight_visual_evidence_and_judgment() -> None:
    runtime = _runtime()
    started = runtime.start("eeg-demo-001", POLICY)
    inspected = _act(runtime, started.run_id, "inspect_eeg_signals")
    inspected = _act(runtime, inspected.run_id, "inspect_frequency_evidence")
    changed = _act(runtime, inspected.run_id, "reseat_electrode", site="FC3")
    refreshed = _act(runtime, changed.run_id, "collect_fresh_eeg_window")
    terminal = _act(runtime, refreshed.run_id, "complete_preflight")
    completed = runtime.verify(terminal.run_id)

    reset = runtime.reset(completed.run_id)
    replay = runtime.replay(completed.run_id)

    assert reset.observation == started.observation
    assert replay.trace_matches is True
    assert replay.result_matches is True


def test_authored_sampling_rate_is_reported_without_a_seeded_literal() -> None:
    source = validate_environment_bundle(load_seeded_bundle())
    authored = apply_authoring_command(
        seed_authoring_state(source),
        "Set sampling to 512 Hz",
    ).state
    frozen = compile_frozen_bundle(source, authored, revision=9)
    runtime = EnvironmentRuntime(EegEnvironmentModule(frozen))

    started = runtime.start("eeg-demo-001", POLICY)

    assert started.observation["eeg_window"]["source_sampling_hz"] == 512
    assert started.observation["eeg_window"]["display_representation"] == (
        "Synthetic downsampled display window; acquisition metadata remains 512 Hz."
    )


def test_authored_online_bandpass_controls_visible_synthetic_frequency_components() -> None:
    broad_runtime = _runtime()
    broad = broad_runtime.start("eeg-demo-007", POLICY)
    broad = _act(broad_runtime, broad.run_id, "inspect_frequency_evidence")
    broad_26_hz = broad.observation["frequency_evidence"]["channels"][0][
        "magnitudes"
    ][4]

    source = validate_environment_bundle(load_seeded_bundle())
    authored = apply_authoring_command(
        seed_authoring_state(source),
        "Set online bandpass to 0.1-12 Hz",
    ).state
    frozen = compile_frozen_bundle(source, authored, revision=12)
    narrow_runtime = EnvironmentRuntime(EegEnvironmentModule(frozen))
    narrow = narrow_runtime.start("eeg-demo-007", POLICY)
    assert "no blocking" in narrow.observation["summary"].casefold()
    assert "online bandpass" in narrow.observation["summary"].casefold()
    narrow = _act(narrow_runtime, narrow.run_id, "inspect_eeg_signals")
    narrow = _act(narrow_runtime, narrow.run_id, "inspect_frequency_evidence")
    narrow_26_hz = narrow.observation["frequency_evidence"]["channels"][0][
        "magnitudes"
    ][4]

    assert narrow.observation["procedure_configuration"]["acquisition_profile"][
        "online_bandpass_hz"
    ] == [0.1, 12.0]
    assert narrow_26_hz < broad_26_hz / 10
    narrow = _act(narrow_runtime, narrow.run_id, "complete_preflight")
    verified = narrow_runtime.verify(narrow.run_id)
    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.outcome_category == "validated_preflight"
    assert verified.verifier_result.metrics["targeted_intervention"] == 0.0

    unnecessary = narrow_runtime.start("eeg-demo-007", POLICY)
    unnecessary = _act(narrow_runtime, unnecessary.run_id, "inspect_eeg_signals")
    unnecessary = _act(
        narrow_runtime,
        unnecessary.run_id,
        "inspect_frequency_evidence",
    )
    unnecessary = _act(
        narrow_runtime,
        unnecessary.run_id,
        "isolate_electrical_source",
    )
    unnecessary = _act(
        narrow_runtime,
        unnecessary.run_id,
        "collect_fresh_eeg_window",
    )
    unnecessary = _act(
        narrow_runtime,
        unnecessary.run_id,
        "complete_preflight",
    )
    unnecessary_result = narrow_runtime.verify(
        unnecessary.run_id
    ).verifier_result
    assert unnecessary_result is not None
    assert unnecessary_result.passed is False
    assert unnecessary_result.outcome_category == "lucky_terminal"
    assert unnecessary_result.metrics["targeted_intervention"] == 0.0


@pytest.mark.parametrize(
    ("scenario_id", "bandpass_command"),
    [
        ("eeg-demo-005", "Set online bandpass to 20-30 Hz"),
        ("eeg-demo-006", "Set online bandpass to 5-30 Hz"),
        ("eeg-demo-007", "Set online bandpass to 0.1-12 Hz"),
        ("eeg-demo-019", "Set online bandpass to 0.1-12 Hz"),
    ],
)
def test_filter_masked_diagnostic_components_do_not_create_hidden_blockers(
    scenario_id: str,
    bandpass_command: str,
) -> None:
    source = validate_environment_bundle(load_seeded_bundle())
    authored = apply_authoring_command(
        seed_authoring_state(source),
        bandpass_command,
    ).state
    frozen = compile_frozen_bundle(source, authored, revision=13)
    runtime = EnvironmentRuntime(EegEnvironmentModule(frozen))
    snapshot = runtime.start(scenario_id, POLICY)
    assert "no blocking" in snapshot.observation["summary"].casefold()
    snapshot = _act(runtime, snapshot.run_id, "inspect_eeg_signals")
    snapshot = _act(runtime, snapshot.run_id, "inspect_frequency_evidence")
    snapshot = _act(runtime, snapshot.run_id, "complete_preflight")

    verified = runtime.verify(snapshot.run_id)

    assert verified.verifier_result is not None
    assert verified.verifier_result.passed is True
    assert verified.verifier_result.outcome_category == "validated_preflight"
    assert verified.verifier_result.metrics["targeted_intervention"] == 0.0


def test_authored_montage_roles_adapt_cases_without_inventing_a_missing_fault() -> None:
    source = validate_environment_bundle(load_seeded_bundle())

    without_fc3 = apply_authoring_command(
        seed_authoring_state(source),
        "Remove FC3 from the Montage",
    ).state
    frozen_without_fc3 = compile_frozen_bundle(source, without_fc3, revision=10)
    runtime_without_fc3 = EnvironmentRuntime(EegEnvironmentModule(frozen_without_fc3))
    absent = runtime_without_fc3.start("eeg-demo-001", POLICY)
    assert "FC3" not in {
        channel["site"] for channel in absent.observation["eeg_window"]["channels"]
    }
    assert "does not include FC3" in absent.observation["summary"]
    absent = _act(runtime_without_fc3, absent.run_id, "inspect_eeg_signals")
    absent = _act(runtime_without_fc3, absent.run_id, "inspect_frequency_evidence")
    absent = _act(runtime_without_fc3, absent.run_id, "complete_preflight")
    absent_result = runtime_without_fc3.verify(absent.run_id).verifier_result
    assert absent_result is not None
    assert absent_result.passed is True
    assert absent_result.outcome_category == "validated_preflight"

    with_c3 = apply_authoring_command(
        seed_authoring_state(source),
        "Add C3 to the Montage",
    ).state
    frozen_with_c3 = compile_frozen_bundle(source, with_c3, revision=11)
    runtime_with_c3 = EnvironmentRuntime(EegEnvironmentModule(frozen_with_c3))
    required = runtime_with_c3.start("eeg-demo-020", POLICY)
    c3 = next(
        channel
        for channel in required.observation["eeg_window"]["channels"]
        if channel["site"] == "C3"
    )
    assert c3["role"] == "required"
    assert c3["measurements"]["range_uv"] < 30
    assert "C3 is required" in required.observation["summary"]
    required = _act(runtime_with_c3, required.run_id, "inspect_eeg_signals")
    required = _act(runtime_with_c3, required.run_id, "inspect_frequency_evidence")
    required = _act(runtime_with_c3, required.run_id, "complete_preflight")
    required_result = runtime_with_c3.verify(required.run_id).verifier_result
    assert required_result is not None
    assert required_result.passed is True
    assert required_result.outcome_category == "validated_preflight"
    assert required_result.metrics["targeted_intervention"] == 0.0
