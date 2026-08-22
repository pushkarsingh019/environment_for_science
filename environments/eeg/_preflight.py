"""Private reducer for the versioned synthetic EEG diagnostic preflight."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic import ValidationError

from environments.eeg._domain import (
    INSPECTION_ACTIONS,
    RETEST_ACTIONS,
    STATE_CHANGING_ACTIONS,
    EvidenceDomain,
    PreflightCase,
    PreflightFixture,
)
from environments.eeg._signals import build_eeg_window, build_frequency_evidence
from studio.bundle import BundleValidationError, EnvironmentBundle, ScenarioManifest
from studio.runtime import (
    EnvironmentAction,
    EpisodeState,
    EpisodeUpdate,
    RuntimeContractError,
    VerifierOutcome,
)

_PROFILE_DIAGNOSTIC_COMPONENTS_HZ: dict[str, tuple[float, ...]] = {
    "reference_shared": (6.0, 18.0),
    "ground_shared": (2.0,),
    "environment_shared": (26.0,),
    "participant_activity": (26.0,),
}


class EegPreflightRuntime:
    """Deterministic EEG behavior selected by the preflight generator revision."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        fixture_document = (self._bundle.model_extra or {}).get("preflight_fixture")
        try:
            fixture = PreflightFixture.model_validate(fixture_document)
        except ValidationError as error:
            details = "; ".join(item["msg"] for item in error.errors())
            raise BundleValidationError(
                "the EEG bundle has no valid content-bound preflight fixture: "
                f"{details}"
            ) from error
        self._cases = {case.id: case for case in fixture.cases}
        declared_ids = {scenario.id for scenario in bundle.scenarios}
        if declared_ids != set(self._cases):
            raise BundleValidationError(
                "the EEG preflight bundle and pinned case fixture do not agree"
            )
        for scenario in bundle.scenarios:
            if scenario.initial_state.hidden.get("case_id") != scenario.id:
                raise BundleValidationError(
                    "the EEG scenario and fixture case identity do not agree"
                )

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
        case = self._case(scenario.id)
        procedure_configuration = _procedure_configuration(scenario, self._bundle)
        state_revision = 0
        window_sequence = 1
        resolved = _initially_resolved(case, procedure_configuration)
        observation = _initial_observation(
            case,
            scenario=scenario,
            procedure_configuration=procedure_configuration,
            state_revision=state_revision,
            window_sequence=window_sequence,
            resolved=resolved,
        )
        evidence_ids = _current_evidence_ids(observation)
        hidden_state: dict[str, Any] = {
            "case_id": case.id,
            "resolved": resolved,
            "window_sequence": window_sequence,
            "domain_sequences": {domain: 1 for domain in _domains()},
            "inspections": [],
            "state_changes": [],
            "targeted_intervention": False,
            "relevant_attempts": 0,
            "latest_retest_revisions": {domain: None for domain in _domains()},
            "current_evidence_ids": evidence_ids,
            "decision": None,
            "abort_request": None,
        }
        return EpisodeState(
            procedure_state=self._bundle.procedure.initial_state,
            observation=observation,
            hidden_state=hidden_state,
            state_revision=state_revision,
        )

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate:
        if action.type in INSPECTION_ACTIONS:
            return self._inspect(state, action)
        if action.type in STATE_CHANGING_ACTIONS:
            return self._remediate(state, action)
        if action.type in RETEST_ACTIONS:
            return self._retest(state, action)
        if action.type == "complete_preflight":
            return self._complete(state)
        if action.type == "abort_preflight":
            return self._abort(state, action)
        raise RuntimeContractError(
            f"EEG action {action.type!r} is not implemented",
            code="internal",
        )

    def verify(self, state: EpisodeState) -> VerifierOutcome:
        case = self._case(_hidden_string(state, "case_id"))
        decision = state.hidden_state.get("decision")
        if decision == "abort":
            return _verify_abort(case, state)
        return _verify_completion(case, state)

    def _inspect(self, state: EpisodeState, action: EnvironmentAction) -> EpisodeUpdate:
        domain = INSPECTION_ACTIONS[action.type]
        observation = deepcopy(state.observation)
        hidden = deepcopy(state.hidden_state)
        evidence_id = _domain_evidence_id(observation, domain)
        inspections = _hidden_list(hidden, "inspections")
        inspections.append(
            {
                "action": action.type,
                "domain": domain,
                "evidence_id": evidence_id,
                "state_revision": state.state_revision,
            }
        )
        if action.type == "inspect_frequency_evidence":
            observation["frequency_evidence"] = build_frequency_evidence(
                _object(observation, "eeg_window"),
            )
            summary = "Frequency measurements were derived from the current synthetic EEG window."
        else:
            summary = {
                "inspect_eeg_signals": (
                    "The current synthetic multichannel window was inspected comparatively."
                ),
                "inspect_onset_route": (
                    "The simulated flash, marker, and participant-view evidence was inspected."
                ),
                "inspect_response_timeline": (
                    "The simulated press, occurrence, and queried-identity evidence was inspected."
                ),
                "inspect_recording_timeline": (
                    "The simulated recording and aligned event timeline was inspected."
                ),
            }[action.type]
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=state.state_revision,
            summary=summary,
        )

    def _remediate(self, state: EpisodeState, action: EnvironmentAction) -> EpisodeUpdate:
        case = self._case(_hidden_string(state, "case_id"))
        domain = STATE_CHANGING_ACTIONS[action.type]
        observation = deepcopy(state.observation)
        hidden = deepcopy(state.hidden_state)
        next_revision = state.state_revision + 1

        _validate_action_target(action, observation)
        target_matches = _target_matches(case, action)
        blocking_before_action = not _hidden_bool(hidden, "resolved")
        relevant = (
            blocking_before_action
            and action.type in case.relevant_actions
            and target_matches
        )
        targeted = relevant and _has_current_inspection(hidden, observation, case.domain)
        effective = (
            relevant and case.recoverable and action.type in case.effective_actions
        )
        if relevant:
            hidden["relevant_attempts"] = _hidden_integer(
                hidden, "relevant_attempts"
            ) + 1
        if targeted:
            hidden["targeted_intervention"] = True
        if effective:
            hidden["resolved"] = True
        if action.type == "ask_participant_to_relax":
            participant = _object(observation, "participant_evidence")
            participant["recent_instruction"] = "relax and remain still"

        state_changes = _hidden_list(hidden, "state_changes")
        state_changes.append(
            {
                "action": action.type,
                "domain": domain,
                "state_revision": next_revision,
                "relevant": relevant,
                "targeted": targeted,
                "effective": effective,
            }
        )
        _discard_domain_inspections(hidden, domain)
        _mark_domain_stale(observation, domain, next_revision)
        summary = _remediation_summary(action)
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=next_revision,
            summary=summary,
        )

    def _retest(self, state: EpisodeState, action: EnvironmentAction) -> EpisodeUpdate:
        case = self._case(_hidden_string(state, "case_id"))
        domain = RETEST_ACTIONS[action.type]
        observation = deepcopy(state.observation)
        hidden = deepcopy(state.hidden_state)
        sequences = _hidden_object(hidden, "domain_sequences")
        next_sequence = _integer_value(sequences.get(domain), "domain sequence") + 1
        sequences[domain] = next_sequence
        resolved = _hidden_bool(hidden, "resolved")
        seed = _scenario_seed(case.id, self._bundle)

        if domain == "eeg":
            next_window_sequence = _hidden_integer(hidden, "window_sequence") + 1
            hidden["window_sequence"] = next_window_sequence
            observation["eeg_window"] = build_eeg_window(
                case,
                seed=seed,
                procedure_configuration=_object(observation, "procedure_configuration"),
                state_revision=state.state_revision,
                window_sequence=next_window_sequence,
                resolved=resolved,
            )
            observation["frequency_evidence"] = None
            if case.signal_profile == "participant_activity" and resolved:
                _object(observation, "participant_evidence")[
                    "simulated_tension_reported"
                ] = False
        elif domain == "onset":
            observation["onset_evidence"] = _onset_evidence(
                case,
                seed=seed,
                sequence=next_sequence,
                state_revision=state.state_revision,
                resolved=resolved,
            )
        elif domain == "response":
            observation["response_evidence"] = _response_evidence(
                case,
                seed=seed,
                sequence=next_sequence,
                state_revision=state.state_revision,
                resolved=resolved,
            )
        else:
            observation["recording_evidence"] = _recording_evidence(
                case,
                seed=seed,
                sequence=next_sequence,
                state_revision=state.state_revision,
                resolved=resolved,
            )

        evidence_id = _domain_evidence_id(observation, domain)
        _set_current_freshness(observation, domain, evidence_id, state.state_revision)
        current_ids = _hidden_object(hidden, "current_evidence_ids")
        current_ids[domain] = evidence_id
        retest_revisions = _hidden_object(hidden, "latest_retest_revisions")
        retest_revisions[domain] = state.state_revision
        summary = _retest_summary(domain, observation)
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=state.state_revision,
            summary=summary,
        )

    def _complete(self, state: EpisodeState) -> EpisodeUpdate:
        observation = deepcopy(state.observation)
        hidden = deepcopy(state.hidden_state)
        hidden["decision"] = "complete"
        summary = "The Policy agent submitted the current preflight evidence for verification."
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=state.state_revision,
            summary=summary,
        )

    def _abort(self, state: EpisodeState, action: EnvironmentAction) -> EpisodeUpdate:
        observation = deepcopy(state.observation)
        hidden = deepcopy(state.hidden_state)
        path = _action_string(action, "path")
        evidence_id = _action_string(action, "evidence_id")
        hidden["decision"] = "abort"
        hidden["abort_request"] = {"path": path, "evidence_id": evidence_id}
        summary = (
            f"The Policy agent requested a simulated {path} preflight abort using "
            "the cited evidence."
        )
        observation["summary"] = summary
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden,
            state_revision=state.state_revision,
            summary=summary,
        )

    def _case(self, scenario_id: str) -> PreflightCase:
        try:
            return self._cases[scenario_id]
        except KeyError as error:
            raise RuntimeContractError(
                "the selected EEG diagnostic case is unavailable",
                code="internal",
            ) from error


def _initial_observation(
    case: PreflightCase,
    *,
    scenario: ScenarioManifest,
    procedure_configuration: dict[str, Any],
    state_revision: int,
    window_sequence: int,
    resolved: bool,
) -> dict[str, Any]:
    seed = scenario.seed
    montage_configuration = _object(procedure_configuration, "montage")
    observation: dict[str, Any] = {
        "simulation_label": "Synthetic EEG apparatus simulation",
        "stage": "diagnostic_preflight",
        "summary": _initial_summary(case, procedure_configuration, resolved),
        "montage": {
            "recording_sites": deepcopy(montage_configuration["recording_sites"]),
            "reference": montage_configuration["reference"],
            "ground": montage_configuration["ground"],
            "coordinate_note": (
                "Schematic scalp positions support spatial comparison; they are not exact "
                "cap geometry."
            ),
        },
        "eeg_window": build_eeg_window(
            case,
            seed=seed,
            procedure_configuration=procedure_configuration,
            state_revision=state_revision,
            window_sequence=window_sequence,
            resolved=resolved,
        ),
        "frequency_evidence": None,
        "onset_evidence": _onset_evidence(
            case,
            seed=seed,
            sequence=1,
            state_revision=state_revision,
            resolved=resolved,
        ),
        "response_evidence": _response_evidence(
            case,
            seed=seed,
            sequence=1,
            state_revision=state_revision,
            resolved=resolved,
        ),
        "recording_evidence": _recording_evidence(
            case,
            seed=seed,
            sequence=1,
            state_revision=state_revision,
            resolved=resolved,
        ),
        "participant_evidence": {
            "simulated_tension_reported": (
                case.signal_profile == "participant_activity" and not resolved
            ),
            "recent_instruction": None,
        },
        "procedure_configuration": deepcopy(procedure_configuration),
    }
    observation["evidence_freshness"] = {
        domain: {
            "evidence_id": _domain_evidence_id(observation, domain),
            "state_revision": state_revision,
            "status": "current",
        }
        for domain in _domains()
    }
    return observation


def _onset_evidence(
    case: PreflightCase,
    *,
    seed: int,
    sequence: int,
    state_revision: int,
    resolved: bool,
) -> dict[str, Any]:
    marker_count = 1
    cue_visible = False
    if case.evidence_variant == "duplicate_onset" and not resolved:
        marker_count = 2
    elif case.evidence_variant == "missing_onset" and not resolved:
        marker_count = 0
    elif case.evidence_variant == "visible_trigger" and not resolved:
        cue_visible = True
    marker_times = [112.3 + (sequence - 1) * 500.0]
    if marker_count == 0:
        marker_times = []
    elif marker_count == 2:
        marker_times.append(marker_times[0] + 6.8)
    return {
        "evidence_id": f"onset-{seed:x}-p{sequence:03d}-r{state_revision:03d}",
        "status": "current",
        "flash_sequence": sequence,
        "location": "lower-right",
        "flash_time_ms": round(100.0 + (sequence - 1) * 500.0, 3),
        "marker_times_ms": marker_times,
        "participant_view": {"lower_right_cue_visible": cue_visible},
    }


def _response_evidence(
    case: PreflightCase,
    *,
    seed: int,
    sequence: int,
    state_revision: int,
    resolved: bool,
) -> dict[str, Any]:
    occurrence_detected = True
    queried_identity: str | None = "button-1"
    if case.evidence_variant == "missing_response_occurrence" and not resolved:
        occurrence_detected = False
        queried_identity = None
    elif case.evidence_variant == "response_identity_mismatch" and not resolved:
        queried_identity = "button-2"
    return {
        "evidence_id": f"response-{seed:x}-p{sequence:03d}-r{state_revision:03d}",
        "status": "current",
        "simulated_press": "button-1",
        "occurrence_detected": occurrence_detected,
        "queried_identity": queried_identity,
        "event_time_ms": round(286.0 + (sequence - 1) * 500.0, 3),
    }


def _recording_evidence(
    case: PreflightCase,
    *,
    seed: int,
    sequence: int,
    state_revision: int,
    resolved: bool,
) -> dict[str, Any]:
    recording_active = not (
        case.evidence_variant == "inactive_recording" and not resolved
    )
    aligned = not (
        case.evidence_variant == "timeline_misalignment" and not resolved
    )
    offset = (sequence - 1) * 500.0
    return {
        "evidence_id": f"recording-{seed:x}-p{sequence:03d}-r{state_revision:03d}",
        "status": "current",
        "recording_active": recording_active,
        "timeline": {
            "stimulus_ms": round(100.0 + offset, 3),
            "marker_ms": round((112.3 if aligned else 162.3) + offset, 3),
            "eeg_anchor_ms": round((100.0 if aligned else 148.0) + offset, 3),
            "response_ms": round(286.0 + offset, 3),
        },
    }


def _verify_completion(case: PreflightCase, state: EpisodeState) -> VerifierOutcome:
    resolved = _hidden_bool(state.hidden_state, "resolved")
    stale_domains = _stale_evidence_domains(state.observation)
    fresh = (
        _fresh_after_latest_change(state, case.domain)
        and not stale_domains
    )
    changed = bool(_hidden_list(state.hidden_state, "state_changes"))
    targeted = _hidden_bool(state.hidden_state, "targeted_intervention")
    inspected = _has_current_inspection(state.hidden_state, state.observation, case.domain)
    decision_supported = targeted if changed else inspected
    terminal_correct = resolved
    passed = terminal_correct and fresh and decision_supported

    reasons: list[str] = []
    if state.hidden_state.get("decision") != "complete":
        reasons.append("The preflight was not explicitly submitted for completion.")
        passed = False
    if not terminal_correct:
        reasons.append("Current evidence still shows a blocking required path.")
    if not fresh:
        if stale_domains:
            reasons.append(
                "Fresh evidence is still required for the following simulated path(s): "
                + ", ".join(stale_domains)
                + "."
            )
        else:
            reasons.append("No fresh relevant evidence followed the latest simulated change.")
    if not decision_supported:
        reasons.append("The terminal decision was not supported by prior relevant inspection.")

    if passed and changed:
        outcome_category = "targeted_recovery"
        summary = "Preflight verified after targeted simulated recovery and fresh evidence."
    elif passed and _has_optional_eeg_site(state.observation):
        outcome_category = "restrained_validation"
        summary = (
            "Preflight verified from coherent required-site evidence without "
            "unnecessary change."
        )
    elif passed:
        outcome_category = "validated_preflight"
        summary = "Preflight verified from current inspected evidence."
    elif resolved and changed and (not fresh or not targeted):
        outcome_category = "lucky_terminal"
        summary = (
            "Preflight not verified: the terminal state lacked a targeted fresh "
            "evidence route."
        )
    elif not resolved and changed and fresh:
        outcome_category = "ineffective_action"
        summary = (
            "Preflight not verified: fresh evidence remains blocking after the "
            "simulated change."
        )
    else:
        outcome_category = "incomplete_evidence"
        summary = "Preflight not verified from the current evidence route."

    return VerifierOutcome(
        passed=passed,
        terminal_disposition="recovered" if passed else "failed",
        outcome_category=outcome_category,
        summary=summary,
        metrics={
            "terminal_correctness": float(terminal_correct),
            "fresh_validation": float(fresh),
            "targeted_intervention": float(targeted),
        },
        evidence={
            "domain": case.domain,
            "evidence_id": _domain_evidence_id(state.observation, case.domain),
            "state_revision": state.state_revision,
        },
        reasons=tuple(reasons),
    )


def _verify_abort(case: PreflightCase, state: EpisodeState) -> VerifierOutcome:
    abort_request = state.hidden_state.get("abort_request")
    request = abort_request if isinstance(abort_request, dict) else {}
    path = request.get("path")
    evidence_id = request.get("evidence_id")
    current_evidence_id = _domain_evidence_id(state.observation, case.domain)
    matching_evidence = path == case.domain and evidence_id == current_evidence_id
    fresh = _fresh_after_latest_change(state, case.domain)
    attempted = _hidden_integer(state.hidden_state, "relevant_attempts") > 0
    targeted = _hidden_bool(state.hidden_state, "targeted_intervention")
    resolved = _hidden_bool(state.hidden_state, "resolved")
    justified = (
        not case.recoverable
        and not resolved
        and attempted
        and targeted
        and fresh
        and matching_evidence
    )

    reasons: list[str] = []
    if justified:
        category = "justified_abort"
        summary = "Evidence-bound abort verified after the available simulated recovery route."
    elif resolved:
        category = "blanket_caution"
        summary = "Abort not justified: current required-path evidence is not blocking."
        reasons.append("Current required-path evidence did not support abort.")
    elif case.recoverable:
        category = "unjustified_abort"
        summary = "Abort not justified while a simulated recovery route remains available."
        reasons.append("A relevant simulated recovery route remained available.")
    else:
        category = "unsupported_abort"
        summary = "Abort not verified from a complete current evidence route."
        if not attempted:
            reasons.append("The available targeted recovery route was not attempted.")
        if not targeted:
            reasons.append("The recovery attempt was not supported by prior inspection.")
        if not fresh:
            reasons.append("Current evidence did not follow the latest simulated change.")
        if not matching_evidence:
            reasons.append("The abort did not cite current evidence for the blocking path.")

    return VerifierOutcome(
        passed=justified,
        terminal_disposition="aborted",
        outcome_category=category,
        summary=summary,
        metrics={
            "terminal_correctness": float(justified),
            "fresh_validation": float(fresh),
            "targeted_intervention": float(targeted),
        },
        evidence={
            "domain": case.domain,
            "evidence_id": evidence_id,
            "state_revision": state.state_revision,
        },
        reasons=tuple(reasons),
    )


def _fresh_after_latest_change(state: EpisodeState, domain: EvidenceDomain) -> bool:
    freshness = _object(_object(state.observation, "evidence_freshness"), domain)
    if freshness.get("status") != "current":
        return False
    changes = _hidden_list(state.hidden_state, "state_changes")
    relevant_changes = [change for change in changes if change.get("domain") == domain]
    if not relevant_changes:
        return True
    retest_revisions = _hidden_object(state.hidden_state, "latest_retest_revisions")
    latest_change_revision = _integer_value(
        relevant_changes[-1].get("state_revision"),
        "relevant state-change revision",
    )
    retest_revision = retest_revisions.get(domain)
    if retest_revision is None:
        return False
    return (
        _integer_value(retest_revision, "domain retest revision")
        >= latest_change_revision
    )


def _stale_evidence_domains(observation: dict[str, Any]) -> tuple[str, ...]:
    freshness = _object(observation, "evidence_freshness")
    return tuple(
        domain
        for domain in _domains()
        if _object(freshness, domain).get("status") != "current"
    )


def _has_current_inspection(
    hidden: dict[str, Any], observation: dict[str, Any], domain: EvidenceDomain
) -> bool:
    evidence_id = _domain_evidence_id(observation, domain)
    inspections = _hidden_list(hidden, "inspections")
    matching_actions = {
        str(item.get("action"))
        for item in inspections
        if item.get("domain") == domain and item.get("evidence_id") == evidence_id
    }
    if domain == "eeg":
        return {
            "inspect_eeg_signals",
            "inspect_frequency_evidence",
        }.issubset(matching_actions)
    required = {
        "onset": "inspect_onset_route",
        "response": "inspect_response_timeline",
        "recording": "inspect_recording_timeline",
    }[domain]
    return required in matching_actions


def _mark_domain_stale(
    observation: dict[str, Any], domain: EvidenceDomain, next_revision: int
) -> None:
    if domain == "eeg":
        _object(observation, "eeg_window")["status"] = "stale"
        frequency = observation.get("frequency_evidence")
        if isinstance(frequency, dict):
            frequency["status"] = "stale"
    else:
        _object(observation, f"{domain}_evidence")["status"] = "stale"
    freshness = _object(_object(observation, "evidence_freshness"), domain)
    freshness["status"] = "stale"
    freshness["evidence_state_revision"] = freshness["state_revision"]
    freshness["state_revision"] = next_revision
    freshness["reason"] = (
        "A simulated state change requires fresh evidence for this path."
    )


def _set_current_freshness(
    observation: dict[str, Any],
    domain: EvidenceDomain,
    evidence_id: str,
    state_revision: int,
) -> None:
    freshness = _object(observation, "evidence_freshness")
    freshness[domain] = {
        "evidence_id": evidence_id,
        "state_revision": state_revision,
        "status": "current",
    }


def _discard_domain_inspections(hidden: dict[str, Any], domain: EvidenceDomain) -> None:
    inspections = _hidden_list(hidden, "inspections")
    hidden["inspections"] = [
        item for item in inspections if item.get("domain") != domain
    ]


def _target_matches(case: PreflightCase, action: EnvironmentAction) -> bool:
    if action.type in {"reseat_electrode", "replace_electrode", "reconnect_electrode_path"}:
        return action.arguments.get("site") == case.target
    return True


def _validate_action_target(
    action: EnvironmentAction, observation: dict[str, Any]
) -> None:
    if action.type not in {
        "reseat_electrode",
        "replace_electrode",
        "reconnect_electrode_path",
    }:
        return
    site = _action_string(action, "site")
    channels = _object(observation, "eeg_window").get("channels")
    if not isinstance(channels, list):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    available_sites = {
        str(channel.get("site"))
        for channel in channels
        if isinstance(channel, dict)
    }
    if site not in available_sites:
        raise RuntimeContractError(
            "the selected site is not present in the current simulated evidence"
        )


def _remediation_summary(action: EnvironmentAction) -> str:
    labels = {
        "reseat_electrode": "The selected simulated electrode was reseated.",
        "replace_electrode": "The selected simulated electrode was replaced.",
        "reconnect_electrode_path": "The selected simulated electrode path was reconnected.",
        "reconnect_reference": "The simulated reference connection was re-established.",
        "reconnect_ground": "The simulated ground connection was re-established.",
        "isolate_electrical_source": "The selected simulated electrical source was isolated.",
        "ask_participant_to_relax": (
            "The simulated participant was asked to relax and remain still."
        ),
        "repair_refractory_route": "The simulated refractory route was repaired.",
        "repair_onset_route": "The simulated onset event route was reconnected.",
        "correct_trigger_visibility": "The simulated lower-right cue visibility was corrected.",
        "restart_response_handshake": "The simulated response handshake was restarted.",
        "correct_response_mapping": "The simulated response identity mapping was corrected.",
        "restore_recording_state": "The simulated recording state was restored.",
        "realign_timeline": "The simulated event integration was restarted for alignment.",
    }
    return labels[action.type] + " Relevant prior evidence is now stale."


def _retest_summary(domain: EvidenceDomain, observation: dict[str, Any]) -> str:
    if domain == "eeg":
        return "A fresh synthetic multichannel EEG window was collected."
    if domain == "onset":
        markers = len(_object(observation, "onset_evidence")["marker_times_ms"])
        return f"A fresh lower-right test flash produced {markers} onset marker(s)."
    if domain == "response":
        return "A fresh simulated response-path preflight was recorded."
    return "A fresh simulated recording and event-timeline preflight was recorded."


def _current_evidence_ids(observation: dict[str, Any]) -> dict[str, str]:
    return {domain: _domain_evidence_id(observation, domain) for domain in _domains()}


def _domain_evidence_id(observation: dict[str, Any], domain: EvidenceDomain) -> str:
    key = "eeg_window" if domain == "eeg" else f"{domain}_evidence"
    return str(_object(observation, key)["evidence_id"])


def _procedure_configuration(
    scenario: ScenarioManifest, bundle: EnvironmentBundle
) -> dict[str, Any]:
    visible_configuration = scenario.initial_state.policy_visible.get(
        "procedure_configuration"
    )
    if isinstance(visible_configuration, dict):
        return deepcopy(visible_configuration)
    bundle_configuration = (bundle.procedure.model_extra or {}).get("configuration")
    if not isinstance(bundle_configuration, dict):
        raise BundleValidationError("the EEG preflight has no Procedure configuration")
    return deepcopy(bundle_configuration)


def _initially_resolved(
    case: PreflightCase,
    procedure_configuration: dict[str, Any],
) -> bool:
    if case.starts_resolved:
        return True
    if _authored_filter_masks_diagnostic_component(case, procedure_configuration):
        return True
    if case.signal_profile not in {"local_noise", "intermittent", "flat", "clipped"}:
        return False
    montage = _object(procedure_configuration, "montage")
    recording_sites = montage.get("recording_sites")
    return isinstance(recording_sites, list) and case.target not in recording_sites


def _initial_summary(
    case: PreflightCase,
    procedure_configuration: dict[str, Any],
    resolved: bool,
) -> str:
    montage = _object(procedure_configuration, "montage")
    recording_sites = montage.get("recording_sites")
    if not isinstance(recording_sites, list):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    if resolved and not case.starts_resolved:
        if _authored_filter_masks_diagnostic_component(
            case,
            procedure_configuration,
        ):
            low_hz, high_hz = _authored_online_bandpass(procedure_configuration)
            return (
                f"Within the authored {low_hz:g}–{high_hz:g} Hz online bandpass, "
                "the required recording sites show no blocking shared pattern."
            )
        return (
            f"The configured Montage does not include {case.target}; its present "
            "required recording sites remain dynamic and mutually coherent."
        )
    if case.optional_site is not None and case.optional_site in recording_sites:
        return (
            f"{case.optional_site} is required by this configured Montage and remains "
            "dynamic and coherent with the other required recording sites."
        )
    return case.initial_summary


def _authored_filter_masks_diagnostic_component(
    case: PreflightCase,
    procedure_configuration: dict[str, Any],
) -> bool:
    component_frequencies = _PROFILE_DIAGNOSTIC_COMPONENTS_HZ.get(
        case.signal_profile
    )
    if component_frequencies is None:
        return False
    low_hz, high_hz = _authored_online_bandpass(procedure_configuration)
    return not any(
        low_hz <= frequency_hz <= high_hz
        for frequency_hz in component_frequencies
    )


def _authored_online_bandpass(
    procedure_configuration: dict[str, Any],
) -> tuple[float, float]:
    acquisition_profile = _object(
        procedure_configuration,
        "acquisition_profile",
    )
    bandpass = acquisition_profile.get("online_bandpass_hz")
    if (
        not isinstance(bandpass, list)
        or len(bandpass) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in bandpass
        )
    ):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    low_hz, high_hz = (float(value) for value in bandpass)
    if low_hz < 0 or high_hz <= low_hz:
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return low_hz, high_hz


def _has_optional_eeg_site(observation: dict[str, Any]) -> bool:
    channels = _object(observation, "eeg_window").get("channels")
    return isinstance(channels, list) and any(
        isinstance(channel, dict) and channel.get("role") == "optional"
        for channel in channels
    )


def _scenario_seed(scenario_id: str, bundle: EnvironmentBundle) -> int:
    for scenario in bundle.scenarios:
        if scenario.id == scenario_id:
            return scenario.seed
    raise RuntimeContractError(
        "the selected EEG diagnostic seed is unavailable",
        code="internal",
    )


def _domains() -> tuple[EvidenceDomain, ...]:
    return ("eeg", "onset", "response", "recording")


def _object(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return value


def _hidden_object(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    return _object(mapping, key)


def _hidden_list(mapping: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return cast(list[dict[str, Any]], value)


def _hidden_string(state: EpisodeState, key: str) -> str:
    value = state.hidden_state.get(key)
    if not isinstance(value, str):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return value


def _hidden_bool(mapping: dict[str, Any], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return value


def _hidden_integer(mapping: dict[str, Any], key: str) -> int:
    return _integer_value(mapping.get(key), key)


def _integer_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeContractError(
            "the EEG preflight state is invalid",
            code="internal",
        )
    return value


def _action_string(action: EnvironmentAction, key: str) -> str:
    value = action.arguments.get(key)
    if not isinstance(value, str):
        raise RuntimeContractError(f"action input {key!r} must be a string")
    return value
