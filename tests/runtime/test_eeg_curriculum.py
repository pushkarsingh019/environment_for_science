"""Public-contract tests for the immutable EEG curriculum release."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest

from environments.eeg.curriculum import (
    CurriculumAttempt,
    CurriculumContractError,
    HarnessErrorRecord,
    MetricDistribution,
    Rate,
    TrainingScenarioSet,
    load_development_scenario_set,
    load_training_scenario_set,
)
from environments.eeg.runtime import EegEnvironmentModule
from evaluation.eeg.attempts import open_held_out_attempt_ledger
from evaluation.eeg.curriculum import (
    HeldOutScenarioSet,
    audit_eeg_curriculum_release,
    load_held_out_scenario_set,
)
from scripts.generate_eeg_curriculum import package_document
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
    RunSnapshot,
    TraceEvent,
)

_POLICY = PolicyAgentIdentity(
    id="curriculum-aggregation-auditor",
    name="Curriculum aggregation auditor",
)
_MODEL_CONFIGURATION_DIGEST = "sha256:" + "1" * 64


def test_report_value_objects_reject_impossible_serialized_states() -> None:
    with pytest.raises(ValueError, match="numerator"):
        Rate(numerator=2, denominator=1, value=0.5)
    with pytest.raises(ValueError, match="does not match"):
        Rate(numerator=1, denominator=2, value=0.75)
    with pytest.raises(ValueError, match="distribution"):
        MetricDistribution(
            eligible_count=0,
            count=1,
            minimum=1.0,
            median=1.0,
            maximum=1.0,
            values=(1.0,),
        )


def test_release_materializes_the_approved_fixed_splits() -> None:
    training = load_training_scenario_set()
    development = load_development_scenario_set()
    held_out = load_held_out_scenario_set()

    assert len(training.scenario_ids) == 96
    assert len(development.scenario_ids) == 32
    assert len(held_out.scenario_ids) == 64
    assert not set(training.scenario_ids) & set(development.scenario_ids)
    assert not set(training.scenario_ids) & set(held_out.scenario_ids)
    assert not set(development.scenario_ids) & set(held_out.scenario_ids)

    report = audit_eeg_curriculum_release(training, development, held_out)
    assert report.valid is True
    assert report.split_counts == {
        "training": 96,
        "development": 32,
        "held_out": 64,
    }
    assert report.category_counts == {
        "training": {
            "nominal": 8,
            "individual": 44,
            "ambiguous": 24,
            "pair": 20,
            "triple": 0,
        },
        "development": {
            "nominal": 4,
            "individual": 12,
            "ambiguous": 8,
            "pair": 8,
            "triple": 0,
        },
        "held_out": {
            "nominal": 8,
            "individual": 16,
            "ambiguous": 16,
            "pair": 16,
            "triple": 8,
        },
    }
    assert report.cross_cutting_counts == {
        "training": {
            "unavailable": 12,
            "runtime_onset": 24,
            "optional_transient": 4,
            "reserved_nuisance": 0,
        },
        "development": {
            "unavailable": 4,
            "runtime_onset": 8,
            "optional_transient": 2,
            "reserved_nuisance": 0,
        },
        "held_out": {
            "unavailable": 12,
            "runtime_onset": 16,
            "optional_transient": 8,
            "reserved_nuisance": 32,
        },
    }
    assert report.unavailable_path_counts == {
        "training": {"eeg": 3, "onset": 3, "response": 3, "recording": 3},
        "development": {"eeg": 1, "onset": 1, "response": 1, "recording": 1},
        "held_out": {"eeg": 3, "onset": 3, "response": 3, "recording": 3},
    }
    assert report.identity_families_disjoint is True
    assert report.combination_policy_valid is True


def test_split_packages_are_content_addressed_and_repeatable() -> None:
    first = load_training_scenario_set()
    second = load_training_scenario_set()

    assert first.identity == second.identity
    assert first.scenario_ids == second.scenario_ids
    assert first.catalog == second.catalog
    assert first.identity.package_digest.startswith("sha256:")
    assert len(first.identity.package_digest) == 71
    assert all(ref.manifest_digest.startswith("sha256:") for ref in first.catalog)

    assert first.identity.package_digest == (
        "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
    )
    assert load_development_scenario_set().identity.package_digest == (
        "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
    )
    assert load_held_out_scenario_set().identity.package_digest == (
        "sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7"
    )


@pytest.mark.parametrize(
    ("split", "resource_name"),
    (
        ("training", "curriculum_training_v1.json"),
        ("development", "curriculum_development_v1.json"),
        ("held_out", "curriculum_heldout_v1.json"),
    ),
)
def test_reviewed_packages_equal_a_fresh_deterministic_build(
    split: str,
    resource_name: str,
) -> None:
    frozen = json.loads(files("environments.eeg").joinpath(resource_name).read_text())
    assert frozen == package_document(split)


def test_package_loader_rejects_stale_content_and_duplicate_identities() -> None:
    stale = _package_document("curriculum_training_v1.json")
    stale["scenarios"][0]["seed"] += 1
    with pytest.raises(CurriculumContractError, match="failed integrity validation"):
        load_training_scenario_set(stale)

    fully_rehashed = _package_document("curriculum_training_v1.json")
    fully_rehashed["scenarios"][0]["seed"] += 1
    _refresh_package_digests(fully_rehashed, record_indices=(0,))
    with pytest.raises(CurriculumContractError, match="approved frozen release"):
        load_training_scenario_set(fully_rehashed)

    duplicate = _package_document("curriculum_training_v1.json")
    duplicate["scenarios"][1]["scenario_id"] = duplicate["scenarios"][0][
        "scenario_id"
    ]
    _refresh_package_digests(duplicate, record_indices=(1,))
    with pytest.raises(CurriculumContractError, match="failed integrity validation"):
        load_training_scenario_set(duplicate)


def test_purpose_bound_loaders_and_release_receipts_reject_split_leakage() -> None:
    held_document = _package_document("curriculum_heldout_v1.json")
    with pytest.raises(CurriculumContractError, match="wrong purpose"):
        load_training_scenario_set(held_document)

    training_document = _package_document("curriculum_training_v1.json")
    held_document["scenarios"][0]["blueprint_id"] = training_document["scenarios"][
        0
    ]["blueprint_id"]
    _refresh_package_digests(held_document, record_indices=(0,))

    with pytest.raises(CurriculumContractError, match="approved frozen release"):
        load_held_out_scenario_set(held_document)


def test_release_receipt_rejects_a_reserved_pair_in_training() -> None:
    training_document = _package_document("curriculum_training_v1.json")
    held_document = _package_document("curriculum_heldout_v1.json")
    pair_index = next(
        index
        for index, record in enumerate(training_document["scenarios"])
        if record["category"] == "pair" and not record["unavailable"]
    )
    training_record = training_document["scenarios"][pair_index]
    held_record = next(
        record
        for record in held_document["scenarios"]
        if record["category"] == "pair"
        and record["runtime_onset"] == training_record["runtime_onset"]
        and not record["unavailable"]
    )
    training_record["faults"] = deepcopy(held_record["faults"])
    training_record["occurrences"] = deepcopy(held_record["occurrences"])
    _refresh_package_digests(training_document, record_indices=(pair_index,))

    with pytest.raises(CurriculumContractError, match="approved frozen release"):
        load_training_scenario_set(training_document)


def test_training_inputs_and_artifact_do_not_contain_evaluation_truth() -> None:
    training = load_training_scenario_set()
    held_out = load_held_out_scenario_set()

    inputs = training.training_inputs()
    assert len(inputs) == 96
    assert {item.scenario_id for item in inputs} == set(training.scenario_ids)
    assert all(item.objective == inputs[0].objective for item in inputs)

    artifact = training.training_artifact_bytes()
    document = json.loads(artifact)
    assert document["scenario_count"] == 96
    assert set(document) == {
        "artifact_revision",
        "curriculum_revision",
        "package_digest",
        "scenario_count",
        "scenarios",
    }
    serialized = artifact.decode("utf-8")
    assert all(scenario_id not in serialized for scenario_id in held_out.scenario_ids)
    artifact_keys = _nested_keys(document)
    for forbidden_key in (
        "blueprint_id",
        "nuisance_id",
        "faults",
        "category",
        "availability",
        "expected_action",
        "held_out",
    ):
        assert forbidden_key not in artifact_keys


def test_console_catalog_is_a_neutral_training_only_projection() -> None:
    training = load_training_scenario_set()
    held_out = load_held_out_scenario_set()

    assert 1 <= len(training.seeded_examples) <= 12
    assert {item.scenario_id for item in training.seeded_examples} <= set(
        training.scenario_ids
    )
    assert not {item.scenario_id for item in training.seeded_examples} & set(
        held_out.scenario_ids
    )
    assert all(item.label and item.stage for item in training.seeded_examples)
    payload = json.dumps(
        [item.model_dump(mode="json") for item in training.seeded_examples],
        sort_keys=True,
    )
    payload_document = json.loads(payload)
    payload_keys = _nested_keys(payload_document)
    for forbidden_key in (
        "split",
        "seed",
        "category",
        "fault",
        "recoverable",
        "availability",
        "expected",
    ):
        assert forbidden_key not in payload_keys
    for forbidden_term in (
        "ambiguous",
        "compound",
        "fault",
        "recovery",
    ):
        assert forbidden_term not in payload.casefold()


def test_aggregate_replays_runs_and_rejects_a_forged_verifier_result() -> None:
    training = load_training_scenario_set()
    nominal_id = next(
        record["scenario_id"]
        for record in _package_document("curriculum_training_v1.json")["scenarios"]
        if record["category"] == "nominal"
    )
    completed = _early_abort(training, nominal_id)
    assert completed.verifier_result is not None
    forged_metrics = dict(completed.verifier_result.metrics)
    forged_metrics["terminal_correctness"] = 1.0
    forged_metrics["reward"] = 1.0
    forged_result = completed.verifier_result.model_copy(
        update={"metrics": forged_metrics, "passed": True}
    )
    forged_payload = forged_result.model_dump(mode="json", exclude_none=True)
    forged_events = list(completed.trace)
    forged_events[-1] = forged_events[-1].model_copy(
        update={"verifier": forged_payload, "summary": forged_result.summary}
    )
    source_trace_digest = _test_trace_digest(completed, tuple(forged_events[:-1]))
    forged_result_digest = _test_digest(
        {
            "result": forged_payload,
            "source_trace_digest": source_trace_digest,
        }
    )
    forged = completed.model_copy(
        update={
            "verifier_result": forged_result,
            "trace": tuple(forged_events),
            "trace_digest": _test_trace_digest(completed, tuple(forged_events)),
            "result_digest": forged_result_digest,
        }
    )

    with pytest.raises(CurriculumContractError, match="integrity|replay"):
        training.aggregate((_attempt(forged),))


def test_aggregate_counts_canonical_incomplete_as_a_scientific_failure() -> None:
    training = load_training_scenario_set()
    runtime = EnvironmentRuntime(EegEnvironmentModule(training.environment_bundle))
    started = runtime.start(training.scenario_ids[0], _POLICY)
    completed = runtime.finalize_incomplete(
        started.run_id,
        termination_reason="model_ended_before_terminal",
    )

    report = training.aggregate((_attempt(completed),))

    assert report.completed_runs == 1
    assert report.harness_errors == 0
    assert report.exact_terminal_accuracy == 0.0
    assert report.mean_reward == 0.0


def test_exact_terminal_accuracy_excludes_partial_abort_credit() -> None:
    training = load_training_scenario_set()
    record = next(
        item
        for item in _package_document("curriculum_training_v1.json")["scenarios"]
        if item["faults"] == ["duplicate_onset"]
        and not item["unavailable"]
        and not item["runtime_onset"]
    )
    scenario_id = str(record["scenario_id"])
    runtime = EnvironmentRuntime(EegEnvironmentModule(training.environment_bundle))
    snapshot = runtime.start(scenario_id, _POLICY)
    snapshot = runtime.apply_action(
        snapshot.run_id,
        EnvironmentAction(type="inspect_onset_route", arguments={}),
    )
    evidence_id = snapshot.observation["evidence_freshness"]["onset"]["evidence_id"]
    snapshot = runtime.apply_action(
        snapshot.run_id,
        EnvironmentAction(
            type="abort_episode",
            arguments={"path": "onset", "evidence_id": evidence_id},
        ),
    )
    completed = runtime.verify(snapshot.run_id)

    assert completed.verifier_result is not None
    assert completed.verifier_result.metrics["terminal_correctness"] > 0.0
    assert completed.verifier_result.metrics["exact_terminal_success"] == 0.0
    report = training.aggregate((_attempt(completed),))
    assert report.exact_terminal_accuracy == 0.0
    assert report.by_category["individual"].exact_terminal_accuracy == 0.0


def test_held_out_attempt_ledger_accepts_an_equal_two_rollout_matrix(
    tmp_path: Path,
) -> None:
    held_out = load_held_out_scenario_set()
    ledger = open_held_out_attempt_ledger(
        artifact_root=tmp_path,
        scenario_set=held_out,
        model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
        rollouts_per_scenario=2,
    )
    for scenario_id in held_out.scenario_ids:
        for rollout_index in range(2):
            ledger.record(
                _error_attempt(scenario_id, rollout_index=rollout_index)
            )
    ledger.seal()

    report = held_out.aggregate(ledger)

    assert report.attempted_runs == 128
    assert report.completed_runs == 0
    assert report.attempted_scenario_coverage.value == 1.0
    assert report.scenario_coverage.value == 0.0
    assert report.rollout_success.value == 0.0
    assert report.harness_errors == 128
    assert report.harness_errors_by_category == {"timeout": 128}
    assert report.harness_error_rate.value == 1.0
    assert report.model_configuration_digest == _MODEL_CONFIGURATION_DIGEST
    assert report.evaluation_id == ledger.evaluation_id
    assert report.attempt_ledger_digest == ledger.ledger_digest


def test_held_out_attempt_ledger_refuses_to_seal_an_incomplete_matrix(
    tmp_path: Path,
) -> None:
    held_out = load_held_out_scenario_set()
    ledger = open_held_out_attempt_ledger(
        artifact_root=tmp_path,
        scenario_set=held_out,
        model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
        rollouts_per_scenario=2,
    )
    for scenario_id in held_out.scenario_ids:
        ledger.record(_error_attempt(scenario_id))

    with pytest.raises(CurriculumContractError, match="complete attempt matrix"):
        ledger.seal()


def test_held_out_attempt_slot_cannot_be_replaced_after_reopen(
    tmp_path: Path,
) -> None:
    held_out = load_held_out_scenario_set()
    scenario_id = held_out.scenario_ids[0]
    completed = _early_abort(held_out, scenario_id)
    ledger = open_held_out_attempt_ledger(
        artifact_root=tmp_path,
        scenario_set=held_out,
        model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
        rollouts_per_scenario=1,
    )
    ledger.record(_error_attempt(scenario_id))

    reopened_set = load_held_out_scenario_set()
    reopened = open_held_out_attempt_ledger(
        artifact_root=tmp_path,
        scenario_set=reopened_set,
        model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
        rollouts_per_scenario=1,
    )
    assert reopened.evaluation_id == ledger.evaluation_id
    with pytest.raises(CurriculumContractError, match="already has a terminal outcome"):
        reopened.record(_attempt(completed))

    for remaining_id in held_out.scenario_ids[1:]:
        reopened.record(_error_attempt(remaining_id))
    reopened.seal()
    first_report = reopened_set.aggregate(reopened)
    second_report = load_held_out_scenario_set().aggregate(
        open_held_out_attempt_ledger(
            artifact_root=tmp_path,
            scenario_set=held_out,
            model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
            rollouts_per_scenario=1,
        )
    )
    assert first_report == second_report
    assert first_report.harness_errors == 64
    assert first_report.completed_runs == 0


def test_held_out_aggregate_rejects_a_fresh_in_memory_replacement_ledger() -> None:
    held_out = load_held_out_scenario_set()
    attempts = tuple(
        _error_attempt(scenario_id)
        for scenario_id in held_out.scenario_ids
    )

    with pytest.raises(CurriculumContractError, match="persistent.*attempt ledger"):
        held_out.aggregate(attempts)


def test_sealed_held_out_attempt_ledger_rejects_slot_tampering(
    tmp_path: Path,
) -> None:
    held_out = load_held_out_scenario_set()
    ledger = open_held_out_attempt_ledger(
        artifact_root=tmp_path,
        scenario_set=held_out,
        model_configuration_digest=_MODEL_CONFIGURATION_DIGEST,
        rollouts_per_scenario=1,
    )
    for scenario_id in held_out.scenario_ids:
        ledger.record(_error_attempt(scenario_id))
    ledger.seal()
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            UPDATE attempt_slots
            SET attempt_json = '{}'
            WHERE scenario_id = ? AND rollout_index = 0
            """,
            (held_out.scenario_ids[0],),
        )

    with pytest.raises(CurriculumContractError, match="slot failed integrity"):
        held_out.aggregate(ledger)


def test_attempt_ledger_rejects_retrying_a_failed_slot() -> None:
    training = load_training_scenario_set()
    completed = _early_abort(training, training.scenario_ids[0])

    with pytest.raises(CurriculumContractError, match="slots must be unique"):
        training.aggregate(
            (
                _error_attempt(completed.scenario_id),
                _attempt(completed),
            )
        )


def test_attempt_ledger_rejects_mixed_model_configurations() -> None:
    training = load_training_scenario_set()
    with pytest.raises(CurriculumContractError, match="model configuration"):
        training.aggregate(
            (
                _error_attempt(training.scenario_ids[0]),
                _error_attempt(
                    training.scenario_ids[1],
                    model_configuration_digest="sha256:" + "2" * 64,
                ),
            )
        )


def test_aggregate_reports_decision07_strata_and_abort_denominators() -> None:
    training = load_training_scenario_set()
    records = _package_document("curriculum_training_v1.json")["scenarios"]
    nominal_id = next(
        record["scenario_id"]
        for record in records
        if record["category"] == "nominal"
        and record["role_requirement"] == "not_applicable"
    )
    nominal_abort = _early_abort(training, nominal_id)

    unavailable_id = "eeg-0f9dc08c4a74a4f4"
    runtime = EnvironmentRuntime(EegEnvironmentModule(training.environment_bundle))
    unavailable = runtime.start(unavailable_id, _POLICY)
    for action_type in (
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
        "reconnect_ground",
        "collect_fresh_eeg_window",
    ):
        unavailable = runtime.apply_action(
            unavailable.run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )
    evidence_id = unavailable.observation["evidence_freshness"]["eeg"]["evidence_id"]
    unavailable = runtime.apply_action(
        unavailable.run_id,
        EnvironmentAction(
            type="abort_episode",
            arguments={"path": "eeg", "evidence_id": evidence_id},
        ),
    )
    unavailable = runtime.verify(unavailable.run_id)

    error_scenario_id = next(
        scenario_id
        for scenario_id in training.scenario_ids
        if scenario_id not in {nominal_id, unavailable_id}
    )
    report = training.aggregate(
        (
            _attempt(nominal_abort),
            _attempt(unavailable),
            _error_attempt(error_scenario_id),
        )
    )
    intervention_only = training.aggregate((_attempt(unavailable),))

    assert report.claim_scope == "within_eeg_compositional_generalization"
    assert report.replay_conformance.value == 1.0
    assert report.valid_close_precision.value is None
    assert report.abort.explicit_aborts == 2
    assert report.abort.eligible_aborts == 1
    assert report.abort.non_unavailable_attempts == 1
    assert report.abort.unnecessary_aborts == 1
    assert report.abort.unnecessary_abort_rate == 1.0
    assert report.by_category["nominal"].count == 1
    assert report.by_category["individual"].count == 1
    assert report.by_category["nominal"].abort.unnecessary_abort_rate == 1.0
    assert report.by_fault_family["reference_ground"].count == 1
    assert report.by_lifecycle_onset["preflight"].count == 2
    assert report.by_role_requirement["required"].count == 1
    assert report.by_role_requirement["not_applicable"].count == 1
    assert report.by_nuisance_family["familiar"].count == 2
    assert report.by_combination_order["0"].count == 1
    assert report.by_combination_order["1"].count == 1
    assert report.harness_errors == 1
    assert report.harness_errors_by_category == {"timeout": 1}
    assert report.harness_error_rate.value == pytest.approx(1 / 3)
    assert report.rollout_success.value == pytest.approx(2 / 3)
    assert report.attempted_scenario_coverage.numerator == 3
    terminal_actions = sorted(
        float(run.verifier_result.metrics["actions_to_correct_terminal"])
        for run in (nominal_abort, unavailable)
        if run.verifier_result is not None
        and run.verifier_result.metrics["correct_terminal_count"] == 1.0
    )
    actions = report.diagnostics.actions_to_correct_terminal
    assert actions.eligible_count == 1
    assert actions.count == 1
    assert actions.values == tuple(terminal_actions)
    assert actions.minimum == terminal_actions[0]
    assert actions.maximum == terminal_actions[-1]
    assert actions.median == terminal_actions[0]
    assert report.diagnostics.first_intervention_relevance.denominator == 1
    assert report.diagnostics.retest_coverage.denominator == 1
    assert report.diagnostics.first_intervention_relevance == (
        intervention_only.diagnostics.first_intervention_relevance
    )
    assert report.diagnostics.retest_coverage == (
        intervention_only.diagnostics.retest_coverage
    )
    assert report.diagnostics.trace_frequency_inspection_rate.denominator >= 1
    assert set(report.mean_reward_components) == {
        "terminal_correctness",
        "safety_compliance",
        "fresh_validation",
        "targeted_intervention",
        "data_stewardship",
        "efficiency",
    }
    assert report.by_category["individual"].diagnostics.recovery_success.denominator == (
        0
    )


def _attempt(
    run: RunSnapshot,
    *,
    rollout_index: int = 0,
    model_configuration_digest: str = _MODEL_CONFIGURATION_DIGEST,
) -> CurriculumAttempt:
    return CurriculumAttempt(
        scenario_id=run.scenario_id,
        rollout_index=rollout_index,
        model_configuration_digest=model_configuration_digest,
        run=run,
    )


def _error_attempt(
    scenario_id: str,
    *,
    rollout_index: int = 0,
    model_configuration_digest: str = _MODEL_CONFIGURATION_DIGEST,
) -> CurriculumAttempt:
    return CurriculumAttempt(
        scenario_id=scenario_id,
        rollout_index=rollout_index,
        model_configuration_digest=model_configuration_digest,
        error=HarnessErrorRecord(category="timeout", code="worker_timeout"),
    )


def _early_abort(
    training: TrainingScenarioSet | HeldOutScenarioSet,
    scenario_id: str,
) -> RunSnapshot:
    runtime = EnvironmentRuntime(EegEnvironmentModule(training.environment_bundle))
    snapshot = runtime.start(scenario_id, _POLICY)
    evidence_id = snapshot.observation["evidence_freshness"]["eeg"]["evidence_id"]
    snapshot = runtime.apply_action(
        snapshot.run_id,
        EnvironmentAction(
            type="abort_episode",
            arguments={"path": "eeg", "evidence_id": evidence_id},
        ),
    )
    return runtime.verify(snapshot.run_id)


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value))
    return set()


def _package_document(resource_name: str) -> dict[str, object]:
    document = json.loads(files("environments.eeg").joinpath(resource_name).read_text())
    assert isinstance(document, dict)
    return deepcopy(document)


def _refresh_package_digests(
    document: dict[str, object],
    *,
    record_indices: tuple[int, ...],
) -> None:
    scenarios = document["scenarios"]
    assert isinstance(scenarios, list)
    for index in record_indices:
        record = scenarios[index]
        assert isinstance(record, dict)
        record_payload = {key: value for key, value in record.items() if key != "manifest_digest"}
        record["manifest_digest"] = _test_digest(record_payload)
    package_payload = {
        key: value for key, value in document.items() if key != "package_digest"
    }
    document["package_digest"] = _test_digest(package_payload)


def _test_digest(value: object) -> str:
    import hashlib

    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _test_trace_digest(snapshot: RunSnapshot, events: tuple[TraceEvent, ...]) -> str:
    return _test_digest(
        {
            "header": snapshot.trace_header.model_dump(mode="json"),
            "events": [
                event.model_dump(mode="json", exclude_none=True)
                for event in events
            ],
        }
    )
