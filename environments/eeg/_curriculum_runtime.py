"""Deterministic staged reducer and scorer for the frozen EEG curriculum."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Literal, cast

from pydantic import ValidationError

from environments.eeg._curriculum_contract import (
    AMBIGUITY_REQUIREMENTS,
    APPLICABLE_DOMAIN_RULES,
    REWARD_SPECIFICATION,
)
from environments.eeg._domain import PreflightCase
from environments.eeg._signals import build_eeg_window, build_frequency_evidence
from environments.eeg.curriculum import (
    _CurriculumPackageDocument,
    _CurriculumScenarioRecord,
    _FaultOccurrence,
)
from studio.bundle import BundleValidationError, EnvironmentBundle, ScenarioManifest
from studio.runtime import (
    EnvironmentAction,
    EpisodeState,
    EpisodeUpdate,
    RuntimeContractError,
    VerifierOutcome,
)

EvidenceDomain = Literal["configuration", "eeg", "onset", "response", "recording"]
AbortPath = Literal["eeg", "onset", "response", "recording"]
_DOMAINS: tuple[EvidenceDomain, ...] = (
    "configuration",
    "eeg",
    "onset",
    "response",
    "recording",
)
_CORE_INSPECTIONS: dict[EvidenceDomain, str] = {
    "configuration": "inspect_configuration",
    "eeg": "inspect_eeg_signals",
    "onset": "inspect_onset_route",
    "response": "inspect_response_timeline",
    "recording": "inspect_recording_timeline",
}
_INSPECTION_DOMAINS: dict[str, EvidenceDomain] = {
    "inspect_configuration": "configuration",
    "inspect_eeg_signals": "eeg",
    "inspect_frequency_evidence": "eeg",
    "inspect_onset_route": "onset",
    "inspect_response_timeline": "response",
    "inspect_recording_timeline": "recording",
    "inspect_participant_state": "eeg",
    "inspect_environment": "eeg",
}
_RETEST_DOMAINS: dict[str, EvidenceDomain] = {
    "collect_fresh_eeg_window": "eeg",
    "present_test_flash": "onset",
    "run_response_preflight": "response",
    "run_recording_preflight": "recording",
    "wait_for_stable_window": "eeg",
}
_REMEDIATION_DOMAINS: dict[str, EvidenceDomain] = {
    "correct_acquisition_configuration": "configuration",
    "reseat_electrode": "eeg",
    "replace_electrode": "eeg",
    "reconnect_electrode_path": "eeg",
    "reconnect_reference": "eeg",
    "reconnect_ground": "eeg",
    "isolate_electrical_source": "eeg",
    "ask_participant_to_relax": "eeg",
    "repair_refractory_route": "onset",
    "repair_onset_route": "onset",
    "correct_trigger_visibility": "onset",
    "restart_response_handshake": "response",
    "correct_response_mapping": "response",
    "restore_recording_state": "recording",
    "realign_timeline": "recording",
}
_SITE_ACTIONS = {"reseat_electrode", "replace_electrode", "reconnect_electrode_path"}
_TERMINAL_ACTIONS = {"complete_preflight", "close_acquisition", "abort_episode"}


class EegCurriculumRuntime:
    """Execute independent fault occurrences through a staged EEG episode."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        fixture_document = (bundle.model_extra or {}).get("curriculum_fixture")
        try:
            package = _CurriculumPackageDocument.model_validate(fixture_document)
        except ValidationError as error:
            details = "; ".join(item["msg"] for item in error.errors())
            raise BundleValidationError(
                f"the EEG curriculum fixture failed validation: {details}"
            ) from error
        package_digest = (bundle.model_extra or {}).get("curriculum_package_digest")
        if package_digest != package.package_digest:
            raise BundleValidationError("the EEG curriculum package digest is not bound")
        self._package = package
        self._cases = {record.scenario_id: record for record in package.scenarios}
        if {scenario.id for scenario in bundle.scenarios} != set(self._cases):
            raise BundleValidationError(
                "the EEG curriculum bundle and fixture scenario identities disagree"
            )
        for scenario in bundle.scenarios:
            if scenario.initial_state.hidden.get("case_id") != scenario.id:
                raise BundleValidationError(
                    "the EEG curriculum scenario and hidden case identity disagree"
                )

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
        case = self._case(scenario.id)
        configuration = _procedure_configuration(scenario, self._bundle)
        occurrence_states = {
            occurrence.occurrence_id: {
                "active": occurrence.activation == "preflight",
                "resolved": False,
                "ladder_index": 0,
                "attempts": 0,
                "targeted_attempts": 0,
                "last_attempt_revision": None,
                "last_retest_revision": None,
                "unavailable_observed": False,
            }
            for occurrence in case.occurrences
        }
        hidden: dict[str, Any] = {
            "case_id": case.scenario_id,
            "seed": case.seed,
            "stage": "preflight",
            "configuration": deepcopy(configuration),
            "occurrences": occurrence_states,
            "domain_sequences": {domain: 1 for domain in _DOMAINS},
            "evidence_revisions": {domain: 0 for domain in _DOMAINS},
            "freshness": {domain: "current" for domain in _DOMAINS},
            "inspections": [],
            "retests": [],
            "state_changes": [],
            "frequency_requested": False,
            "stable_window_count": 0,
            "ambiguity_evidence_complete": False,
            "action_count": 0,
            "accepted_action_count": 0,
            "eeg_quality_decisions": [],
            "completed_trials": 0,
            "invalid_intervals": [],
            "annotations": [],
            "invalid_start_attempts": 0,
            "invalid_resume_attempts": 0,
            "invalid_continuation_attempts": 0,
            "runtime_faults_with_invalid_continuation": [],
            "invalid_visible_action_count": None,
            "pause_latency_logical_events": 0,
            "pause_latency_observed": False,
            "decision": None,
            "terminal_ready": False,
            "abort_request": None,
            "semantic_rejections": 0,
        }
        observation = self._observation(case, hidden, state_revision=0)
        return EpisodeState(
            procedure_state=self._bundle.procedure.initial_state,
            observation=observation,
            hidden_state=hidden,
            state_revision=0,
        )

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate:
        case = self._case(_hidden_string(state.hidden_state, "case_id"))
        hidden = deepcopy(state.hidden_state)
        hidden["action_count"] = _integer(hidden.get("action_count")) + 1
        revision = state.state_revision

        if action.type in _INSPECTION_DOMAINS:
            revision, summary = self._inspect(case, hidden, revision, action)
        elif action.type in _RETEST_DOMAINS:
            revision, summary = self._retest(case, hidden, revision, action.type)
        elif action.type in _REMEDIATION_DOMAINS:
            revision, summary = self._remediate(case, hidden, revision, action)
        elif action.type == "start_acquisition":
            revision, summary = self._start_acquisition(case, hidden, revision)
        elif action.type == "continue_acquisition":
            revision, summary = self._continue_acquisition(case, hidden, revision)
        elif action.type == "pause_acquisition":
            revision, summary = self._pause_acquisition(case, hidden, revision)
        elif action.type == "annotate_invalid_interval":
            revision, summary = self._annotate(hidden, revision, action)
        elif action.type == "resume_acquisition":
            revision, summary = self._resume(case, hidden, revision)
        elif action.type in _TERMINAL_ACTIONS:
            revision, summary = self._terminal(case, hidden, revision, action)
        else:
            raise RuntimeContractError(f"unsupported EEG curriculum action {action.type!r}")

        observation = self._observation(case, hidden, state_revision=revision)
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=revision,
            summary=summary,
        )

    def verify(self, state: EpisodeState) -> VerifierOutcome:
        case = self._case(_hidden_string(state.hidden_state, "case_id"))
        hidden = state.hidden_state
        decision = hidden.get("decision")
        eligible_abort = self._eligible_abort(case, hidden, state.state_revision)
        exact_terminal_success = bool(
            (decision in {"complete", "close"} and hidden.get("terminal_ready") is True)
            or (decision == "abort" and eligible_abort)
        )
        terminal_credit = self._terminal_credit(
            case,
            hidden,
            exact_terminal_success=exact_terminal_success,
        )
        fresh_validation = float(
            exact_terminal_success
            and all(
                _freshness(hidden, domain) == "current"
                for domain in self._required_terminal_domains(case, hidden)
            )
        )
        invalid_attempts = sum(
            _integer(hidden.get(key))
            for key in (
                "invalid_start_attempts",
                "invalid_resume_attempts",
                "invalid_continuation_attempts",
            )
        )
        safety = float(invalid_attempts == 0)
        intervention_relevance = self._first_intervention_relevance(hidden)
        recovery_success = float(self._recoverable_occurrences_resolved(case, hidden))
        targeted = intervention_relevance * recovery_success
        annotation_coverage = self._annotation_coverage(hidden)
        annotation_overreach = self._annotation_overreach(hidden)
        stewardship = max(0.0, annotation_coverage - annotation_overreach)
        excess_actions = self._excess_actions(hidden)
        efficiency = max(0.0, 1.0 - excess_actions / 10.0)
        penalty = self._penalty(hidden, invalid_attempts, annotation_coverage)
        statistics = self._sufficient_statistics(case, hidden, exact_terminal_success)
        weights = cast(dict[str, float], REWARD_SPECIFICATION["components"])
        reward = _clip(
            weights["terminal_correctness"] * terminal_credit
            + weights["safety_compliance"] * safety
            + weights["fresh_validation"] * fresh_validation
            + weights["targeted_intervention"] * targeted
            + weights["data_stewardship"] * stewardship
            + weights["efficiency"] * efficiency
            - penalty
        )
        explicit_abort = float(decision == "abort")
        metrics = {
            "reward": reward,
            "terminal_correctness": terminal_credit,
            "terminal_credit": terminal_credit,
            "exact_terminal_success": float(exact_terminal_success),
            "valid_close": float(decision in {"complete", "close"} and exact_terminal_success),
            "explicit_abort": explicit_abort,
            "eligible_safe_abort": float(eligible_abort),
            "unavailable_scenario": float(case.unavailable),
            "safety_compliance": safety,
            "fresh_validation": fresh_validation,
            "targeted_intervention": targeted,
            "data_stewardship": stewardship,
            "efficiency": efficiency,
            "invalid_start_attempts": float(_integer(hidden.get("invalid_start_attempts"))),
            "invalid_resume_attempts": float(_integer(hidden.get("invalid_resume_attempts"))),
            "invalid_continuation_attempts": float(
                _integer(hidden.get("invalid_continuation_attempts"))
            ),
            "first_intervention_relevance": intervention_relevance,
            "recovery_success": recovery_success,
            "retest_coverage": self._retest_coverage(hidden),
            "trace_frequency_inspection_rate": (self._trace_frequency_inspection_rate(hidden)),
            "annotation_coverage": annotation_coverage,
            "annotation_overreach": annotation_overreach,
            "optional_channel_over_intervention": float(
                case.negative_control_kind == "optional_channel"
                and (bool(_list(hidden, "state_changes")) or decision == "abort")
            ),
            "excess_intervention_count": excess_actions,
            **statistics,
        }
        reasons: list[str] = []
        if not exact_terminal_success:
            reasons.append(
                "The terminal decision was not supported by the current episode evidence."
            )
        if invalid_attempts:
            reasons.append("One or more unsafe lifecycle attempts reduced the safety score.")
        if annotation_coverage < 1.0:
            reasons.append("Not every verifier-known invalid trial interval was annotated.")
        if exact_terminal_success and decision == "abort":
            summary = "Safe abort verified after the required path remained unavailable."
            disposition: Literal["closed", "aborted", "failed"] = "aborted"
        elif exact_terminal_success:
            summary = "Episode closed with current supported evidence and preserved annotations."
            disposition = "closed"
        elif decision == "abort":
            summary = "Abort recorded without full evidence eligibility."
            disposition = "aborted"
        else:
            summary = "Episode terminal state was not scientifically valid."
            disposition = "failed"
        return VerifierOutcome(
            passed=exact_terminal_success,
            terminal_disposition=disposition,
            outcome_category=case.category,
            summary=summary,
            metrics=metrics,
            evidence={
                "curriculum_package_digest": self._package.package_digest,
                "category": case.category,
                "decision": decision,
                "eligible_safe_abort": eligible_abort,
                "invalid_interval_count": len(_list(hidden, "invalid_intervals")),
                "annotation_count": len(_list(hidden, "annotations")),
                "state_revision": state.state_revision,
            },
            reasons=tuple(reasons),
        )

    def _inspect(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
        action: EnvironmentAction,
    ) -> tuple[int, str]:
        domain = _INSPECTION_DOMAINS[action.type]
        if action.type == "inspect_configuration" and _freshness(hidden, domain) == "stale":
            _refresh_domain(hidden, domain, revision)
            self._mark_unavailable_observed_after_retest(case, hidden, domain, revision)
        if action.type == "inspect_frequency_evidence":
            hidden["frequency_requested"] = True
        _list(hidden, "inspections").append(
            {
                "action": action.type,
                "domain": domain,
                "evidence_id": _evidence_id(case, hidden, domain),
                "state_revision": revision,
            }
        )
        _accept_action(hidden)
        self._update_ambiguity_evidence(case, hidden)
        return revision, f"Inspected current {domain} evidence without changing apparatus state."

    def _retest(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
        action_type: str,
    ) -> tuple[int, str]:
        domain = _RETEST_DOMAINS[action_type]
        if action_type == "wait_for_stable_window":
            hidden["stable_window_count"] = _integer(hidden.get("stable_window_count")) + 1
        _refresh_domain(hidden, domain, revision)
        _list(hidden, "retests").append(
            {
                "action": action_type,
                "domain": domain,
                "evidence_id": _evidence_id(case, hidden, domain),
                "state_revision": revision,
            }
        )
        _accept_action(hidden)
        self._mark_unavailable_observed_after_retest(case, hidden, domain, revision)
        self._update_ambiguity_evidence(case, hidden)
        outcome = (
            "remains outside the required evidence envelope"
            if self._domain_fails(case, hidden, domain)
            else "is within the required evidence envelope"
        )
        return revision, f"Fresh {domain} evidence {outcome}."

    def _remediate(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
        action: EnvironmentAction,
    ) -> tuple[int, str]:
        domain = _REMEDIATION_DOMAINS[action.type]
        if domain == "eeg":
            self._record_eeg_quality_decision(case, hidden, revision, "remediation")
        if hidden.get("stage") == "recording" and self._blocking_failure(case, hidden):
            hidden["semantic_rejections"] = _integer(hidden.get("semantic_rejections")) + 1
            return (
                revision,
                "Pause acquisition before remediating current invalid recording evidence.",
            )
        _accept_action(hidden)
        revision += 1
        candidate = self._matching_occurrence(case, hidden, action)
        relevant = candidate is not None
        targeted = bool(
            candidate is not None and self._inspection_supported(case, hidden, candidate)
        )
        effective = False
        occurrence_id: str | None = None
        if candidate is not None:
            occurrence_id = candidate.occurrence_id
            progress = _occurrence_state(hidden, candidate)
            progress["attempts"] = _integer(progress.get("attempts")) + 1
            progress["last_attempt_revision"] = revision
            if targeted:
                progress["targeted_attempts"] = _integer(progress.get("targeted_attempts")) + 1
                ladder_index = _integer(progress.get("ladder_index"))
                if (
                    ladder_index < len(candidate.recovery_ladder)
                    and candidate.recovery_ladder[ladder_index] == action.type
                ):
                    progress["ladder_index"] = ladder_index + 1
                    effective = True
                    if not candidate.unavailable and progress["ladder_index"] == len(
                        candidate.recovery_ladder
                    ):
                        progress["resolved"] = True
        invalidated = (
            tuple(candidate.invalidates) if candidate is not None and effective else (domain,)
        )
        for invalidated_domain in invalidated:
            _mark_stale(hidden, invalidated_domain)
        _list(hidden, "state_changes").append(
            {
                "action": action.type,
                "domain": domain,
                "occurrence_id": occurrence_id,
                "state_revision": revision,
                "relevant": relevant,
                "targeted": targeted,
                "effective": effective,
                "invalidated_domains": list(invalidated),
            }
        )
        if effective:
            summary = "The targeted simulated change was applied; dependent evidence is stale."
        elif relevant:
            summary = "The attempted change lacked current supporting inspection or ladder order."
        else:
            summary = "The attempted change did not match the currently observed path."
        return revision, summary

    def _start_acquisition(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
    ) -> tuple[int, str]:
        self._record_eeg_quality_decision(case, hidden, revision, "start")
        if (
            case.episode_scope != "full"
            or hidden.get("stage") != "preflight"
            or not self._all_gates_supported(case, hidden)
        ):
            hidden["invalid_start_attempts"] = _integer(hidden.get("invalid_start_attempts")) + 1
            return revision, "Acquisition did not start because required gates were unsupported."
        _accept_action(hidden)
        revision += 1
        hidden["stage"] = "recording"
        return revision, "Short deterministic acquisition started with supported gates."

    def _continue_acquisition(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
    ) -> tuple[int, str]:
        if hidden.get("stage") != "recording":
            hidden["invalid_continuation_attempts"] = (
                _integer(hidden.get("invalid_continuation_attempts")) + 1
            )
            return revision, "No trial advanced because acquisition was not in a recording state."
        if _integer(hidden.get("completed_trials")) >= 4:
            hidden["invalid_continuation_attempts"] = (
                _integer(hidden.get("invalid_continuation_attempts")) + 1
            )
            return revision, "No trial advanced beyond the planned four-trial acquisition block."
        self._record_eeg_quality_decision(case, hidden, revision, "continuation")
        _accept_action(hidden)
        active_failure = self._blocking_failure(case, hidden)
        revision += 1
        completed_trials = _integer(hidden.get("completed_trials")) + 1
        hidden["completed_trials"] = completed_trials
        if active_failure:
            hidden["invalid_continuation_attempts"] = (
                _integer(hidden.get("invalid_continuation_attempts")) + 1
            )
            invalidated_faults = _list(hidden, "runtime_faults_with_invalid_continuation")
            known_ids = {item.get("occurrence_id") for item in invalidated_faults}
            for occurrence in self._active_occurrences(case, hidden):
                if occurrence.activation == "runtime" and occurrence.occurrence_id not in known_ids:
                    invalidated_faults.append({"occurrence_id": occurrence.occurrence_id})
            self._extend_invalid_interval(case, hidden, completed_trials)
            return revision, "An unsafe additional trial was recorded while evidence was invalid."

        activated = self._activate_runtime_occurrences(case, hidden, completed_trials, revision)
        if activated:
            self._extend_invalid_interval(case, hidden, completed_trials)
            return (
                revision,
                "The completed trial revealed new invalid evidence; pause before continuing.",
            )
        if completed_trials >= 4:
            hidden["stage"] = "recording_complete"
            return revision, "The planned four-trial acquisition block is complete."
        return revision, f"Completed mock trial {completed_trials} with supported evidence."

    def _pause_acquisition(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
    ) -> tuple[int, str]:
        if hidden.get("stage") != "recording" or not self._blocking_failure(case, hidden):
            hidden["semantic_rejections"] = _integer(hidden.get("semantic_rejections")) + 1
            return revision, "Pause request had no current invalid recording evidence."
        invalid_visible = hidden.get("invalid_visible_action_count")
        if isinstance(invalid_visible, int) and not isinstance(invalid_visible, bool):
            hidden["pause_latency_logical_events"] = max(
                0,
                _integer(hidden.get("action_count")) - invalid_visible - 1,
            )
            hidden["pause_latency_observed"] = True
        _accept_action(hidden)
        revision += 1
        hidden["stage"] = "paused"
        return revision, "Acquisition paused before another mock trial."

    def _annotate(
        self,
        hidden: dict[str, Any],
        revision: int,
        action: EnvironmentAction,
    ) -> tuple[int, str]:
        start = _action_integer(action, "start_trial")
        end = _action_integer(action, "end_trial")
        path = _action_path(action, "path")
        evidence_id = _action_string(action, "evidence_id")
        within_episode = 1 <= start <= end <= _integer(hidden.get("completed_trials")) and bool(
            _list(hidden, "invalid_intervals")
        )
        evidence_matches = evidence_id == _evidence_id_from_path(hidden, path)
        if hidden.get("stage") != "paused" or not within_episode or not evidence_matches:
            hidden["semantic_rejections"] = _integer(hidden.get("semantic_rejections")) + 1
            return revision, "Annotation was rejected because it was outside the current episode."
        _accept_action(hidden)
        revision += 1
        annotation = {
            "start_trial": start,
            "end_trial": end,
            "path": path,
            "evidence_id": evidence_id,
        }
        annotations = _list(hidden, "annotations")
        if annotation not in annotations:
            annotations.append(annotation)
        return revision, "Invalid trial interval was preserved with its visible evidence reference."

    def _resume(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
    ) -> tuple[int, str]:
        self._record_eeg_quality_decision(case, hidden, revision, "resume")
        if (
            hidden.get("stage") != "paused"
            or not self._all_gates_current_and_passing(case, hidden)
            or self._annotation_coverage(hidden) < 1.0
        ):
            hidden["invalid_resume_attempts"] = _integer(hidden.get("invalid_resume_attempts")) + 1
            return (
                revision,
                "Acquisition did not resume because evidence or annotation was incomplete.",
            )
        _accept_action(hidden)
        revision += 1
        hidden["stage"] = (
            "recording_complete" if _integer(hidden.get("completed_trials")) >= 4 else "recording"
        )
        return revision, "Acquisition resumed with current evidence and complete annotation."

    def _terminal(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
        action: EnvironmentAction,
    ) -> tuple[int, str]:
        self._record_eeg_quality_decision(case, hidden, revision, "terminal")
        revision += 1
        stage_before = hidden.get("stage")
        if action.type == "complete_preflight":
            hidden["decision"] = "complete"
            ready = (
                case.episode_scope == "preflight"
                and stage_before == "preflight"
                and self._all_gates_supported(case, hidden)
            )
            summary = "Preflight completion decision recorded."
        elif action.type == "close_acquisition":
            hidden["decision"] = "close"
            ready = (
                case.episode_scope == "full"
                and stage_before == "recording_complete"
                and self._all_gates_current_and_passing(case, hidden)
                and self._annotation_coverage(hidden) == 1.0
            )
            summary = "Acquisition close decision recorded."
        else:
            hidden["decision"] = "abort"
            hidden["abort_request"] = {
                "path": _action_path(action, "path"),
                "evidence_id": _action_string(action, "evidence_id"),
            }
            ready = False
            summary = "Evidence-bound abort decision recorded."
        hidden["terminal_ready"] = ready
        hidden["terminal_stage_before"] = stage_before
        hidden["stage"] = "terminal"
        return revision, summary

    def _observation(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        *,
        state_revision: int,
    ) -> dict[str, Any]:
        configuration = deepcopy(_dict(hidden, "configuration"))
        montage = deepcopy(cast(dict[str, Any], configuration["montage"]))
        montage["coordinate_note"] = (
            "Schematic scalp positions support spatial comparison; they are not exact cap geometry."
        )
        active_eeg = self._active_occurrences(case, hidden, "eeg")
        eeg_window = self._eeg_window(case, hidden, state_revision)
        eeg_window["status"] = _freshness(hidden, "eeg")
        frequency = (
            build_frequency_evidence(eeg_window)
            if hidden.get("frequency_requested") is True
            else None
        )
        if frequency is not None:
            frequency["status"] = _freshness(hidden, "eeg")
        onset = self._onset_evidence(case, hidden)
        response = self._response_evidence(case, hidden)
        recording = self._recording_evidence(case, hidden)
        self._attach_ambiguity_plan(case, eeg_window, onset, response, recording)
        eeg_evidence_id = _evidence_id(case, hidden, "eeg")
        current_eeg_inspections = {
            inspection.get("action")
            for inspection in _list(hidden, "inspections")
            if inspection.get("evidence_id") == eeg_evidence_id
        }
        participant_inspected = "inspect_participant_state" in current_eeg_inspections
        environment_inspected = "inspect_environment" in current_eeg_inspections
        return {
            "simulation_label": "Synthetic EEG apparatus simulation",
            "stage": hidden["stage"],
            "summary": self._measured_summary(case, hidden),
            "montage": montage,
            "procedure_configuration": configuration,
            "configuration_evidence": self._configuration_evidence(case, hidden),
            "eeg_window": eeg_window,
            "frequency_evidence": frequency,
            "onset_evidence": onset,
            "response_evidence": response,
            "recording_evidence": recording,
            "participant_evidence": {
                "simulated_tension_reported": (
                    any(item.family == "participant_artifact" for item in active_eeg)
                    if participant_inspected
                    else None
                ),
                "state_inspected": participant_inspected,
                "recent_instruction": (
                    "stable-posture request"
                    if any(
                        change.get("action") == "ask_participant_to_relax"
                        for change in _list(hidden, "state_changes")
                    )
                    else None
                ),
            },
            "environment_evidence": {
                "shared_source_present": (
                    any(item.family == "environmental_contamination" for item in active_eeg)
                    if environment_inspected
                    else None
                ),
                "source_inspected": environment_inspected,
            },
            "evidence_freshness": {
                domain: {
                    "evidence_id": _evidence_id(case, hidden, domain),
                    "status": _freshness(hidden, domain),
                    "applicable": domain in self._applicable_domains(case),
                    "state_revision": state_revision,
                    "evidence_state_revision": _evidence_revision(hidden, domain),
                }
                for domain in _DOMAINS
            },
            "acquisition": {
                "state": hidden["stage"],
                "completed_trials": _integer(hidden.get("completed_trials")),
                "planned_trials": 4,
                "invalid_intervals": deepcopy(_list(hidden, "invalid_intervals")),
            },
            "annotations": deepcopy(_list(hidden, "annotations")),
        }

    def _eeg_window(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        state_revision: int,
    ) -> dict[str, Any]:
        active = self._active_occurrences(case, hidden, "eeg")
        occurrence = active[0] if active else None
        profile, target = _signal_profile(
            case,
            occurrence,
            stable_window_count=_integer(hidden.get("stable_window_count")),
        )
        synthetic_case = PreflightCase(
            id="eeg-demo-000",
            domain="eeg",
            evidence_variant="signal_window",
            signal_profile=profile,
            target=target,
            recoverable=True,
            starts_resolved=occurrence is None,
            relevant_actions=("reseat_electrode",),
            effective_actions=("reseat_electrode",),
            retest_action="collect_fresh_eeg_window",
            initial_summary="Synthetic comparative EEG evidence is available.",
            optional_site=("Cz" if case.negative_control_kind == "optional_channel" else None),
        )
        window = build_eeg_window(
            synthetic_case,
            seed=case.seed,
            procedure_configuration=_dict(hidden, "configuration"),
            state_revision=state_revision,
            window_sequence=_domain_sequence(hidden, "eeg"),
            resolved=occurrence is None,
        )
        if case.nuisance_family == "reserved":
            channels = window.get("channels")
            if isinstance(channels, list) and channels:
                offset = case.seed % len(channels)
                window["channels"] = [*channels[offset:], *channels[:offset]]
        window["evidence_id"] = _evidence_id(case, hidden, "eeg")
        return window

    def _configuration_evidence(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> dict[str, Any]:
        active = self._active_occurrences(case, hidden, "configuration")
        configuration = _dict(hidden, "configuration")
        acquisition = cast(dict[str, Any], configuration["acquisition_profile"])
        return {
            "evidence_id": _evidence_id(case, hidden, "configuration"),
            "status": _freshness(hidden, "configuration"),
            "selected_sampling_hz": acquisition["sampling_hz"],
            "observed_sampling_hz": 500 if active else acquisition["sampling_hz"],
            "selected_reference": cast(dict[str, Any], configuration["montage"])["reference"],
            "observed_reference": (
                "A2"
                if active and active[0].visible_variant == "montage_role_mismatch"
                else cast(dict[str, Any], configuration["montage"])["reference"]
            ),
        }

    def _onset_evidence(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> dict[str, Any]:
        active = self._active_occurrences(case, hidden, "onset")
        families = {item.family for item in active}
        marker_times: list[float]
        if "missing_onset" in families:
            marker_times = []
        elif "duplicate_onset" in families:
            marker_times = [112.3, 119.1]
        else:
            marker_times = [112.3]
        offset = _event_offset(case)
        return {
            "evidence_id": _evidence_id(case, hidden, "onset"),
            "status": _freshness(hidden, "onset"),
            "flash_sequence": _domain_sequence(hidden, "onset"),
            "location": "lower-right",
            "flash_time_ms": 100.0 + offset,
            "marker_times_ms": [time + offset for time in marker_times],
            "participant_view": {"lower_right_cue_visible": "visible_onset_cue" in families},
        }

    def _response_evidence(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> dict[str, Any]:
        active = self._active_occurrences(case, hidden, "response")
        variant = active[0].visible_variant if active else None
        return {
            "evidence_id": _evidence_id(case, hidden, "response"),
            "status": _freshness(hidden, "response"),
            "simulated_press": "button-1",
            "occurrence_detected": True,
            "queried_identity": (
                None
                if variant == "stale_identity_handshake"
                else "button-2"
                if active
                else "button-1"
            ),
            "event_time_ms": 286.0 + _event_offset(case),
        }

    def _recording_evidence(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> dict[str, Any]:
        active = self._active_occurrences(case, hidden, "recording")
        variant = active[0].visible_variant if active else None
        offset = _event_offset(case)
        marker_ms = 141.0 + offset if variant == "timeline_misalignment" else 112.3 + offset
        return {
            "evidence_id": _evidence_id(case, hidden, "recording"),
            "status": _freshness(hidden, "recording"),
            "recording_active": variant != "inactive_recording",
            "timeline": {
                "stimulus_ms": 100.0 + offset,
                "marker_ms": marker_ms,
                "eeg_anchor_ms": 100.0 + offset,
                "response_ms": 286.0 + offset,
            },
        }

    def _attach_ambiguity_plan(
        self,
        case: _CurriculumScenarioRecord,
        eeg_window: dict[str, Any],
        onset: dict[str, Any],
        response: dict[str, Any],
        recording: dict[str, Any],
    ) -> None:
        requirement = self._ambiguity_requirement(case)
        if requirement is None:
            return
        plan = {
            "instruction": requirement["instruction"],
            "required_observations": list(requirement["required_actions"]),
        }
        panels = {
            "eeg": eeg_window,
            "onset": onset,
            "response": response,
            "recording": recording,
        }
        panel = panels.get(requirement["panel"])
        if panel is None:
            raise RuntimeContractError("ambiguity panel contract is invalid", code="internal")
        panel["comparison_plan"] = plan

    def _measured_summary(self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]) -> str:
        ambiguity_summaries = {
            "widespread_noise": (
                "The current window contains a shared pattern across multiple channels; "
                "compare its trace shape, spectrum, configuration, participant report, "
                "and electrical-source history."
            ),
            "quiet_channel": (
                "The current window contains reduced dynamics at one channel relative to "
                "its neighbors; compare trace and frequency evidence."
            ),
            "unstable_channel": (
                "The current window contains variable dynamics at one channel relative to "
                "its neighbors; compare trace and frequency evidence."
            ),
            "flash_without_marker": (
                "The displayed flash and marker timelines require comparison across onset "
                "and recording evidence."
            ),
            "response_without_identity": (
                "The response occurrence and identity observations require comparison "
                "across the control check and response timeline."
            ),
            "noisy_cap_site": (
                "The current window contains localized activity at the optional site; "
                "compare its montage role, trace, and frequency evidence."
            ),
            "short_shared_transient": (
                "The current window contains a brief shared transient; compare a fresh "
                "stable window with trace, spectrum, participant, and environment evidence."
            ),
        }
        if case.ambiguity_family is not None:
            summary = ambiguity_summaries.get(case.ambiguity_family)
            if summary is None:
                raise RuntimeContractError("ambiguity summary contract is invalid", code="internal")
            return summary
        active = self._active_occurrences(case, hidden)
        if not active:
            return "Current measured evidence is internally coherent for the selected procedure."
        variant = active[0].visible_variant
        summaries = {
            "duplicate_marker_burst": "One test flash has more than one closely spaced marker.",
            "missing_route_event": "A test flash has no corresponding marker event.",
            "participant_visible_flash": "The participant-view panel shows the onset cue.",
            "incorrect_control_mapping": "Response occurrence and queried identity disagree.",
            "stale_identity_handshake": "Response identity is absent after occurrence detection.",
            "inactive_recording": "The latest event occurred while recording was inactive.",
            "timeline_misalignment": "The displayed event timelines do not align.",
            "montage_role_mismatch": "The observed Montage role differs from the selection.",
            "sampling_profile_mismatch": (
                "The observed sampling profile differs from the selection."
            ),
            "flatline": "One required channel is constant across the current window.",
            "rail_clipping": "One required channel repeatedly reaches a display rail.",
            "shared_reference_contamination": (
                "Several independent sites share similar contamination."
            ),
            "shared_ground_contamination": "Several independent sites share slow contamination.",
            "movement_transient": "Time-linked slow transients span the current channel group.",
            "muscle_activity": "Dense higher-frequency activity spans the current channel group.",
            "rhythmic_shared_source": "A rhythmic component is shared across current channels.",
            "broadband_shared_source": "Broadband energy is shared across current channels.",
            "unstable_high_impedance": "One required site is unstable relative to its neighbors.",
            "persistent_local_noise": "One required site has persistent local noise.",
            "intermittent_dropout": "One required site has intermittent dropout.",
            "implausible_neighbor_contrast": (
                "One required site contrasts strongly with its neighbors."
            ),
        }
        return summaries.get(variant, "Current evidence requires further discrimination.")

    def _matching_occurrence(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        action: EnvironmentAction,
    ) -> _FaultOccurrence | None:
        for occurrence in self._active_occurrences(case, hidden):
            progress = _occurrence_state(hidden, occurrence)
            ladder_index = _integer(progress.get("ladder_index"))
            if ladder_index >= len(occurrence.recovery_ladder):
                continue
            if occurrence.recovery_ladder[ladder_index] != action.type:
                continue
            if action.type in _SITE_ACTIONS and _action_string(action, "site") != occurrence.target:
                continue
            return occurrence
        return None

    def _inspection_supported(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        occurrence: _FaultOccurrence,
    ) -> bool:
        if _freshness(hidden, occurrence.domain) != "current":
            return False
        evidence_id = _evidence_id(case, hidden, occurrence.domain)
        inspected_actions = {
            inspection.get("action")
            for inspection in _list(hidden, "inspections")
            if inspection.get("evidence_id") == evidence_id
        }
        return set(occurrence.inspection_actions).issubset(
            inspected_actions
        ) and self._ambiguity_supported(case, hidden)

    def _ambiguity_requirement(
        self,
        case: _CurriculumScenarioRecord,
    ) -> dict[str, Any] | None:
        family = case.ambiguity_family
        if family is None:
            return None
        requirement = AMBIGUITY_REQUIREMENTS.get(family)
        if requirement is None:
            raise RuntimeContractError("ambiguity evidence contract is invalid", code="internal")
        return requirement

    def _ambiguity_evidence_current(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
    ) -> bool:
        requirement = self._ambiguity_requirement(case)
        if requirement is None:
            return True
        for action_type in cast(tuple[str, ...], requirement["required_actions"]):
            if action_type in _INSPECTION_DOMAINS:
                domain = _INSPECTION_DOMAINS[action_type]
                records = _list(hidden, "inspections")
            elif action_type in _RETEST_DOMAINS:
                domain = _RETEST_DOMAINS[action_type]
                records = _list(hidden, "retests")
            else:
                raise RuntimeContractError("ambiguity action contract is invalid", code="internal")
            evidence_id = _evidence_id(case, hidden, domain)
            if not any(
                record.get("action") == action_type and record.get("evidence_id") == evidence_id
                for record in records
            ):
                return False
        return True

    def _update_ambiguity_evidence(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
    ) -> None:
        if self._ambiguity_evidence_current(case, hidden):
            hidden["ambiguity_evidence_complete"] = True

    def _ambiguity_supported(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
    ) -> bool:
        return bool(
            self._ambiguity_requirement(case) is None
            or hidden.get("ambiguity_evidence_complete") is True
            or self._ambiguity_evidence_current(case, hidden)
        )

    def _active_occurrences(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        domain: EvidenceDomain | None = None,
    ) -> tuple[_FaultOccurrence, ...]:
        return tuple(
            occurrence
            for occurrence in case.occurrences
            if (domain is None or occurrence.domain == domain)
            and _occurrence_state(hidden, occurrence).get("active") is True
            and _occurrence_state(hidden, occurrence).get("resolved") is not True
        )

    def _domain_fails(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        domain: EvidenceDomain,
    ) -> bool:
        return any(
            domain in occurrence.invalidates
            for occurrence in self._active_occurrences(case, hidden)
        )

    def _blocking_failure(self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]) -> bool:
        return bool(self._active_occurrences(case, hidden))

    def _all_gates_current_and_passing(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> bool:
        return all(
            _freshness(hidden, domain) == "current" and not self._domain_fails(case, hidden, domain)
            for domain in self._applicable_domains(case)
        )

    def _all_gates_supported(self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]) -> bool:
        if not self._all_gates_current_and_passing(case, hidden):
            return False
        if not self._ambiguity_supported(case, hidden):
            return False
        return all(
            self._domain_has_current_support(case, hidden, domain)
            for domain in self._applicable_domains(case)
        )

    def _domain_has_current_support(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        domain: EvidenceDomain,
    ) -> bool:
        evidence_id = _evidence_id(case, hidden, domain)
        core_action = _CORE_INSPECTIONS[domain]
        if any(
            inspection.get("action") == core_action and inspection.get("evidence_id") == evidence_id
            for inspection in _list(hidden, "inspections")
        ):
            return True
        return any(
            retest.get("domain") == domain and retest.get("evidence_id") == evidence_id
            for retest in _list(hidden, "retests")
        )

    def _applicable_domains(
        self,
        case: _CurriculumScenarioRecord,
    ) -> tuple[EvidenceDomain, ...]:
        rule = "marker_only" if case.stage == "marker_only" else "default"
        return cast(tuple[EvidenceDomain, ...], APPLICABLE_DOMAIN_RULES[rule])

    def _activate_runtime_occurrences(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        completed_trial: int,
        revision: int,
    ) -> bool:
        activated = False
        for occurrence in case.occurrences:
            progress = _occurrence_state(hidden, occurrence)
            if (
                occurrence.activation == "runtime"
                and occurrence.activation_trial == completed_trial
                and progress.get("active") is not True
            ):
                progress["active"] = True
                for domain in occurrence.invalidates:
                    _refresh_domain(hidden, domain, revision)
                if case.ambiguity_family is not None:
                    hidden["ambiguity_evidence_complete"] = False
                activated = True
        if activated and hidden.get("invalid_visible_action_count") is None:
            hidden["invalid_visible_action_count"] = _integer(hidden.get("action_count"))
        return activated

    def _extend_invalid_interval(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        trial: int,
    ) -> None:
        active = self._active_occurrences(case, hidden)
        if not active:
            return
        path = _broad_path(case, active[0])
        intervals = _list(hidden, "invalid_intervals")
        if intervals and intervals[-1].get("path") == path:
            intervals[-1]["end_trial"] = trial
        else:
            intervals.append({"start_trial": trial, "end_trial": trial, "path": path})

    def _mark_unavailable_observed_after_retest(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        domain: EvidenceDomain,
        revision: int,
    ) -> None:
        for occurrence in self._active_occurrences(case, hidden, domain):
            progress = _occurrence_state(hidden, occurrence)
            if progress.get("last_attempt_revision") is not None:
                progress["last_retest_revision"] = revision
            if (
                occurrence.unavailable
                and _integer(progress.get("ladder_index")) == len(occurrence.recovery_ladder)
                and progress.get("last_attempt_revision") is not None
            ):
                progress["unavailable_observed"] = True

    def _eligible_abort(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
    ) -> bool:
        request = hidden.get("abort_request")
        if not isinstance(request, dict) or not case.unavailable:
            return False
        occurrence = next(
            (item for item in case.occurrences if item.unavailable),
            None,
        )
        if occurrence is None:
            return False
        progress = _occurrence_state(hidden, occurrence)
        path = _broad_path(case, occurrence)
        return bool(
            request.get("path") == path
            and request.get("evidence_id") == _evidence_id_from_path(hidden, path)
            and _integer(progress.get("ladder_index")) == len(occurrence.recovery_ladder)
            and progress.get("unavailable_observed") is True
            and _freshness(hidden, occurrence.domain) == "current"
            and _freshness(hidden, path) == "current"
            and self._annotation_coverage(hidden) == 1.0
            and revision >= _integer(progress.get("last_attempt_revision"))
        )

    def _terminal_credit(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        *,
        exact_terminal_success: bool,
    ) -> float:
        if exact_terminal_success:
            return 1.0
        if hidden.get("decision") != "abort":
            return 0.0
        request = hidden.get("abort_request")
        if not isinstance(request, dict):
            return 0.0
        supporting_occurrences = tuple(
            occurrence
            for occurrence in self._active_occurrences(case, hidden)
            if request.get("path") == _broad_path(case, occurrence)
            and request.get("evidence_id")
            == _evidence_id_from_path(hidden, _broad_path(case, occurrence))
            and _freshness(hidden, occurrence.domain) == "current"
            and _freshness(hidden, _broad_path(case, occurrence)) == "current"
        )
        if not supporting_occurrences:
            return 0.0
        for occurrence in supporting_occurrences:
            progress = _occurrence_state(hidden, occurrence)
            last_attempt = progress.get("last_attempt_revision")
            last_retest = progress.get("last_retest_revision")
            if (
                not case.unavailable
                and _integer(progress.get("targeted_attempts")) > 0
                and isinstance(last_attempt, int)
                and not isinstance(last_attempt, bool)
                and isinstance(last_retest, int)
                and not isinstance(last_retest, bool)
                and last_retest >= last_attempt
            ):
                return 0.25
        return 0.10

    def _required_terminal_domains(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
    ) -> tuple[EvidenceDomain, ...]:
        if hidden.get("decision") == "abort":
            occurrence = next((item for item in case.occurrences if item.unavailable), None)
            return (
                (occurrence.domain,) if occurrence is not None else self._applicable_domains(case)
            )
        return self._applicable_domains(case)

    def _recoverable_occurrences_resolved(
        self, case: _CurriculumScenarioRecord, hidden: dict[str, Any]
    ) -> bool:
        return all(
            occurrence.unavailable
            or occurrence.activation == "runtime"
            and _occurrence_state(hidden, occurrence).get("active") is not True
            or _occurrence_state(hidden, occurrence).get("resolved") is True
            for occurrence in case.occurrences
        )

    def _record_eeg_quality_decision(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        revision: int,
        decision: str,
    ) -> None:
        if "eeg" not in self._applicable_domains(case):
            return
        evidence_id = _evidence_id(case, hidden, "eeg")
        inspected_actions = {
            inspection.get("action")
            for inspection in _list(hidden, "inspections")
            if inspection.get("evidence_id") == evidence_id
        }
        _list(hidden, "eeg_quality_decisions").append(
            {
                "decision": decision,
                "state_revision": revision,
                "trace_frequency_supported": {
                    "inspect_eeg_signals",
                    "inspect_frequency_evidence",
                }.issubset(inspected_actions),
            }
        )

    def _trace_frequency_inspection_rate(self, hidden: dict[str, Any]) -> float:
        decisions = _list(hidden, "eeg_quality_decisions")
        if not decisions:
            return 1.0
        return sum(
            decision.get("trace_frequency_supported") is True for decision in decisions
        ) / len(decisions)

    def _first_intervention_relevance(self, hidden: dict[str, Any]) -> float:
        changes = _list(hidden, "state_changes")
        if not changes:
            return 1.0
        first = changes[0]
        return float(first.get("relevant") is True and first.get("targeted") is True)

    def _retest_coverage(self, hidden: dict[str, Any]) -> float:
        changes, covered = self._remediation_retest_counts(hidden)
        if changes == 0:
            return 1.0
        return covered / changes

    def _remediation_retest_counts(self, hidden: dict[str, Any]) -> tuple[int, int]:
        changes = _list(hidden, "state_changes")
        fresh_evidence = [
            *_list(hidden, "retests"),
            *(
                inspection
                for inspection in _list(hidden, "inspections")
                if inspection.get("action") == "inspect_configuration"
            ),
        ]
        covered = 0
        for change in changes:
            revision = _integer(change.get("state_revision"))
            invalidated = change.get("invalidated_domains")
            if not isinstance(invalidated, list):
                raise RuntimeContractError("hidden invalidation state is invalid", code="internal")
            if all(
                any(
                    evidence.get("domain") == domain and evidence.get("state_revision") == revision
                    for evidence in fresh_evidence
                )
                for domain in invalidated
            ):
                covered += 1
        return len(changes), covered

    def _annotation_duration_counts(
        self,
        hidden: dict[str, Any],
    ) -> tuple[int, int, int, int]:
        invalid_duration = _trial_path_cells(_list(hidden, "invalid_intervals"))
        annotated_duration = _trial_path_cells(_list(hidden, "annotations"))
        annotated_invalid = len(invalid_duration.intersection(annotated_duration))
        completed_trials = _integer(hidden.get("completed_trials"))
        episode_duration = {
            (path, trial)
            for path in ("eeg", "onset", "response", "recording")
            for trial in range(1, completed_trials + 1)
        }
        valid_duration = len(episode_duration.difference(invalid_duration))
        overannotated_valid = len(
            annotated_duration.intersection(episode_duration).difference(invalid_duration)
        )
        return (
            len(invalid_duration),
            annotated_invalid,
            valid_duration,
            overannotated_valid,
        )

    def _annotation_coverage(self, hidden: dict[str, Any]) -> float:
        invalid_duration = _trial_path_cells(_list(hidden, "invalid_intervals"))
        if not invalid_duration:
            return 1.0
        annotated_duration = _trial_path_cells(_list(hidden, "annotations"))
        return len(invalid_duration.intersection(annotated_duration)) / len(invalid_duration)

    def _annotation_overreach(self, hidden: dict[str, Any]) -> float:
        invalid_duration = _trial_path_cells(_list(hidden, "invalid_intervals"))
        annotated_duration = _trial_path_cells(_list(hidden, "annotations"))
        if not annotated_duration:
            return 0.0
        return len(annotated_duration.difference(invalid_duration)) / len(annotated_duration)

    def _excess_actions(self, hidden: dict[str, Any]) -> float:
        changes = _list(hidden, "state_changes")
        shortest_path_progress = sum(change.get("effective") is True for change in changes)
        return float(len(changes) - shortest_path_progress)

    def _sufficient_statistics(
        self,
        case: _CurriculumScenarioRecord,
        hidden: dict[str, Any],
        terminal_correct: bool,
    ) -> dict[str, float]:
        changes = _list(hidden, "state_changes")
        first_intervention_count = float(bool(changes))
        first_intervention_relevant = float(
            bool(changes)
            and changes[0].get("relevant") is True
            and changes[0].get("targeted") is True
        )
        recoverable_scenario = bool(case.occurrences and not case.unavailable)
        recovery_success = bool(
            recoverable_scenario
            and terminal_correct
            and self._recoverable_occurrences_resolved(case, hidden)
        )
        runtime_faults = [
            occurrence
            for occurrence in case.occurrences
            if occurrence.activation == "runtime"
            and _occurrence_state(hidden, occurrence).get("active") is True
        ]
        remediation_count, retested_count = self._remediation_retest_counts(hidden)
        decisions = _list(hidden, "eeg_quality_decisions")
        supported_decisions = sum(
            decision.get("trace_frequency_supported") is True for decision in decisions
        )
        invalid_duration, annotated_invalid, valid_duration, overannotated = (
            self._annotation_duration_counts(hidden)
        )
        optional_channel = case.negative_control_kind == "optional_channel"
        optional_over_intervention = bool(
            optional_channel and (changes or hidden.get("decision") == "abort")
        )
        close_decision = hidden.get("decision") in {"complete", "close"}
        return {
            "invalid_start_or_resume_episode": float(
                _integer(hidden.get("invalid_start_attempts")) > 0
                or _integer(hidden.get("invalid_resume_attempts")) > 0
            ),
            "runtime_fault_count": float(len(runtime_faults)),
            "invalid_continuation_fault_count": float(
                len(_list(hidden, "runtime_faults_with_invalid_continuation"))
            ),
            "pause_latency_logical_events": float(
                _integer(hidden.get("pause_latency_logical_events"))
            ),
            "pause_latency_observed": float(hidden.get("pause_latency_observed") is True),
            "first_intervention_count": first_intervention_count,
            "first_intervention_relevant_count": first_intervention_relevant,
            "recoverable_scenario_count": float(recoverable_scenario),
            "recovery_success_count": float(recovery_success),
            "state_changing_remediation_count": float(remediation_count),
            "retested_remediation_count": float(retested_count),
            "eeg_quality_decision_count": float(len(decisions)),
            "trace_frequency_supported_decision_count": float(supported_decisions),
            "invalid_runtime_duration": float(invalid_duration),
            "annotated_invalid_runtime_duration": float(annotated_invalid),
            "valid_runtime_duration": float(valid_duration),
            "overannotated_valid_runtime_duration": float(overannotated),
            "optional_channel_scenario_count": float(optional_channel),
            "optional_channel_over_intervention_count": float(optional_over_intervention),
            "correct_terminal_count": float(terminal_correct),
            "close_decision_count": float(close_decision),
            "valid_close_count": float(close_decision and terminal_correct),
            "actions_to_correct_terminal": float(
                _integer(hidden.get("accepted_action_count")) if terminal_correct else 0
            ),
        }

    def _penalty(
        self,
        hidden: dict[str, Any],
        invalid_attempts: int,
        annotation_coverage: float,
    ) -> float:
        penalties = cast(dict[str, float], REWARD_SPECIFICATION["penalties"])
        invalid_penalty = 0.0
        if invalid_attempts:
            invalid_penalty = min(
                penalties["invalid_start_resume_or_continue_cap"],
                penalties["invalid_start_resume_or_continue_first"]
                + penalties["invalid_start_resume_or_continue_additional"] * (invalid_attempts - 1),
            )
        annotation_penalty = (
            penalties["unannotated_invalid_interval"] if annotation_coverage < 1.0 else 0.0
        )
        changes = _list(hidden, "state_changes")
        unrelated_penalty = (
            penalties["three_unrelated_changes_without_retest"]
            if sum(change.get("relevant") is not True for change in changes) >= 3
            else 0.0
        )
        repeated_no_effect = sum(change.get("effective") is not True for change in changes)
        no_effect_penalty = min(
            penalties["repeated_no_effect_change_cap"],
            penalties["repeated_no_effect_change"] * repeated_no_effect,
        )
        return invalid_penalty + annotation_penalty + unrelated_penalty + no_effect_penalty

    def _case(self, scenario_id: str) -> _CurriculumScenarioRecord:
        try:
            return self._cases[scenario_id]
        except KeyError as error:
            raise RuntimeContractError(
                "unknown EEG curriculum scenario", code="not_found"
            ) from error


def _signal_profile(
    case: _CurriculumScenarioRecord,
    occurrence: _FaultOccurrence | None,
    *,
    stable_window_count: int,
) -> tuple[
    Literal[
        "nominal",
        "quiet_dynamic",
        "local_noise",
        "intermittent",
        "flat",
        "clipped",
        "reference_shared",
        "ground_shared",
        "environment_shared",
        "participant_activity",
        "optional_noise",
    ],
    str | None,
]:
    if occurrence is None:
        ambiguity_profiles = {
            "widespread_noise": ("environment_shared", None),
            "quiet_channel": ("quiet_dynamic", None),
            "noisy_cap_site": ("optional_noise", "Cz"),
            "short_shared_transient": (
                "nominal" if stable_window_count else "participant_activity",
                None,
            ),
        }
        if case.ambiguity_family in ambiguity_profiles:
            profile, target = ambiguity_profiles[case.ambiguity_family]
            return cast(Any, profile), target
        if case.negative_control_kind == "optional_channel":
            return "optional_noise", "Cz"
        if case.category == "ambiguous":
            return "quiet_dynamic", None
        return "nominal", None
    variants = {
        "unstable_high_impedance": "local_noise",
        "persistent_local_noise": "local_noise",
        "intermittent_dropout": "intermittent",
        "implausible_neighbor_contrast": "local_noise",
        "flatline": "flat",
        "rail_clipping": "clipped",
        "shared_reference_contamination": "reference_shared",
        "shared_ground_contamination": "ground_shared",
        "movement_transient": "participant_activity",
        "muscle_activity": "participant_activity",
        "rhythmic_shared_source": "environment_shared",
        "broadband_shared_source": "environment_shared",
    }
    profile = variants.get(occurrence.visible_variant, "nominal")
    return cast(Any, profile), occurrence.target


def _event_offset(case: _CurriculumScenarioRecord) -> float:
    return float(3 * (case.seed % 5)) if case.nuisance_family == "reserved" else 0.0


def _procedure_configuration(
    scenario: ScenarioManifest,
    bundle: EnvironmentBundle,
) -> dict[str, Any]:
    configuration = scenario.initial_state.policy_visible.get("procedure_configuration")
    if not isinstance(configuration, dict):
        configuration = (bundle.procedure.model_extra or {}).get("configuration")
    if not isinstance(configuration, dict):
        raise BundleValidationError("the EEG curriculum has no procedure configuration")
    return deepcopy(configuration)


def _occurrence_state(hidden: dict[str, Any], occurrence: _FaultOccurrence) -> dict[str, Any]:
    occurrences = _dict(hidden, "occurrences")
    value = occurrences.get(occurrence.occurrence_id)
    if not isinstance(value, dict):
        raise RuntimeContractError("hidden occurrence state is invalid", code="internal")
    return value


def _mark_stale(hidden: dict[str, Any], domain: EvidenceDomain) -> None:
    _dict(hidden, "freshness")[domain] = "stale"


def _refresh_domain(hidden: dict[str, Any], domain: EvidenceDomain, revision: int) -> None:
    sequences = _dict(hidden, "domain_sequences")
    sequences[domain] = _integer(sequences.get(domain)) + 1
    _dict(hidden, "evidence_revisions")[domain] = revision
    _dict(hidden, "freshness")[domain] = "current"


def _freshness(hidden: dict[str, Any], domain: EvidenceDomain) -> str:
    value = _dict(hidden, "freshness").get(domain)
    if value not in {"current", "stale"}:
        raise RuntimeContractError("hidden evidence freshness is invalid", code="internal")
    return cast(str, value)


def _domain_sequence(hidden: dict[str, Any], domain: EvidenceDomain) -> int:
    return _integer(_dict(hidden, "domain_sequences").get(domain))


def _evidence_revision(hidden: dict[str, Any], domain: EvidenceDomain) -> int:
    return _integer(_dict(hidden, "evidence_revisions").get(domain))


def _accept_action(hidden: dict[str, Any]) -> None:
    hidden["accepted_action_count"] = _integer(hidden.get("accepted_action_count")) + 1


def _trial_path_cells(records: list[dict[str, Any]]) -> set[tuple[str, int]]:
    cells: set[tuple[str, int]] = set()
    for record in records:
        start = _integer(record.get("start_trial"))
        end = _integer(record.get("end_trial"))
        path = record.get("path")
        if not isinstance(path, str) or start > end:
            raise RuntimeContractError("hidden trial interval is invalid", code="internal")
        cells.update((path, trial) for trial in range(start, end + 1))
    return cells


def _evidence_id(
    case: _CurriculumScenarioRecord,
    hidden: dict[str, Any],
    domain: EvidenceDomain,
) -> str:
    sequence = _domain_sequence(hidden, domain)
    revision = _evidence_revision(hidden, domain)
    token = _opaque_evidence_token(case.scenario_id, domain, sequence, revision)
    return f"{domain}-{token}-s{sequence:03d}-r{revision:03d}"


def _evidence_id_from_path(hidden: dict[str, Any], path: AbortPath) -> str:
    sequence = _domain_sequence(hidden, path)
    revision = _evidence_revision(hidden, path)
    token = _opaque_evidence_token(_hidden_string(hidden, "case_id"), path, sequence, revision)
    return f"{path}-{token}-s{sequence:03d}-r{revision:03d}"


def _opaque_evidence_token(
    case_id: str,
    domain: EvidenceDomain,
    sequence: int,
    revision: int,
) -> str:
    material = f"eeg-evidence-v1\0{case_id}\0{domain}\0{sequence}\0{revision}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def _broad_path(
    case: _CurriculumScenarioRecord,
    occurrence: _FaultOccurrence,
) -> AbortPath:
    if occurrence.unavailable and case.unavailable_path is not None:
        return case.unavailable_path
    if occurrence.domain == "configuration":
        return "recording"
    return occurrence.domain


def _dict(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise RuntimeContractError(f"hidden {key} state is invalid", code="internal")
    return value


def _list(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeContractError(f"hidden {key} state is invalid", code="internal")
    return cast(list[dict[str, Any]], value)


def _hidden_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeContractError(f"hidden {key} state is invalid", code="internal")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeContractError("hidden integer state is invalid", code="internal")
    return value


def _action_string(action: EnvironmentAction, key: str) -> str:
    value = action.arguments.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeContractError(f"action {key} must be a non-empty string")
    return value


def _action_integer(action: EnvironmentAction, key: str) -> int:
    value = action.arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeContractError(f"action {key} must be an integer")
    return value


def _action_path(action: EnvironmentAction, key: str) -> AbortPath:
    value = _action_string(action, key)
    if value not in {"eeg", "onset", "response", "recording"}:
        raise RuntimeContractError("action path is invalid")
    return cast(AbortPath, value)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = ["EegCurriculumRuntime"]
