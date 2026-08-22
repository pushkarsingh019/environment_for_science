"""Frozen scientific contract shared by EEG curriculum build and execution."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

GENERATOR_REVISION = "eeg-curriculum-generator-1"
RUNTIME_REVISION = "eeg-curriculum-runtime-1"
SCORER_REVISION = "eeg-curriculum-scorer-1"
CANONICAL_OBJECTIVE = (
    "Safely validate the synthetic EEG procedure, recover evidence-supported "
    "faults, preserve invalid-data annotations, and close only with fresh evidence "
    "or make an evidence-eligible abort when a required path is unavailable."
)

_NO_ARGUMENTS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_SITE_ARGUMENT: dict[str, Any] = {
    "type": "object",
    "properties": {"site": {"type": "string", "enum": ["FC3", "FC4", "FT7", "FT8"]}},
    "required": ["site"],
    "additionalProperties": False,
}


def _action(
    action_type: str,
    title: str,
    description: str,
    group: str,
    changes_state: bool,
    input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": action_type,
        "title": title,
        "description": description,
        "input_schema": deepcopy(input_schema or _NO_ARGUMENTS),
        "group": group,
        "changes_state": changes_state,
    }


CURRICULUM_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        "inspect_configuration",
        "Inspect configuration",
        "Compare the selected Montage and acquisition profile with the active setup.",
        "inspect",
        False,
    ),
    _action(
        "inspect_eeg_signals",
        "Inspect EEG signals",
        "Inspect required and optional synthetic traces and their neighbor relationships.",
        "inspect",
        False,
    ),
    _action(
        "inspect_frequency_evidence",
        "Inspect frequency evidence",
        "Inspect deterministic frequency evidence for the current EEG window.",
        "inspect",
        False,
    ),
    _action(
        "inspect_onset_route",
        "Inspect onset route",
        "Inspect the flash, route-component, marker, and cue-visibility evidence.",
        "inspect",
        False,
    ),
    _action(
        "inspect_response_timeline",
        "Inspect response timeline",
        "Compare response occurrence, queried identity, and required-control evidence.",
        "inspect",
        False,
    ),
    _action(
        "inspect_recording_timeline",
        "Inspect recording timeline",
        "Compare EEG, stimulus, marker, response, and recording-state timing.",
        "inspect",
        False,
    ),
    _action(
        "inspect_participant_state",
        "Inspect participant state",
        "Inspect the simulated participant-state history without changing it.",
        "inspect",
        False,
    ),
    _action(
        "inspect_environment",
        "Inspect electrical environment",
        "Inspect simulated shared electrical sources and cable context.",
        "inspect",
        False,
    ),
    _action(
        "correct_acquisition_configuration",
        "Correct acquisition configuration",
        "Restore the selected Montage and acquisition profile.",
        "remediate",
        True,
    ),
    _action(
        "reseat_electrode",
        "Reseat electrode",
        "Reseat one selected simulated recording electrode.",
        "remediate",
        True,
        _SITE_ARGUMENT,
    ),
    _action(
        "replace_electrode",
        "Replace electrode",
        "Replace one selected simulated recording electrode after supported evidence.",
        "remediate",
        True,
        _SITE_ARGUMENT,
    ),
    _action(
        "reconnect_electrode_path",
        "Reconnect electrode path",
        "Reconnect one selected simulated recording path.",
        "remediate",
        True,
        _SITE_ARGUMENT,
    ),
    _action(
        "reconnect_reference",
        "Reconnect reference",
        "Reconnect the simulated reference path.",
        "remediate",
        True,
    ),
    _action(
        "reconnect_ground",
        "Reconnect ground",
        "Reconnect the simulated ground path.",
        "remediate",
        True,
    ),
    _action(
        "isolate_electrical_source",
        "Isolate electrical source",
        "Isolate the best-supported simulated shared electrical source.",
        "remediate",
        True,
    ),
    _action(
        "ask_participant_to_relax",
        "Request stable posture",
        "Give the simulated participant an evidence-supported posture instruction.",
        "remediate",
        True,
    ),
    _action(
        "repair_refractory_route",
        "Repair refractory route",
        "Repair or enable the simulated duplicate-marker refractory path.",
        "remediate",
        True,
    ),
    _action(
        "repair_onset_route",
        "Repair onset route",
        "Repair the implicated simulated onset-event route.",
        "remediate",
        True,
    ),
    _action(
        "correct_trigger_visibility",
        "Correct trigger visibility",
        "Hide the simulated onset cue from the participant view.",
        "remediate",
        True,
    ),
    _action(
        "restart_response_handshake",
        "Restart response handshake",
        "Refresh the simulated response-identity handshake.",
        "remediate",
        True,
    ),
    _action(
        "correct_response_mapping",
        "Correct response mapping",
        "Restore the selected simulated required-control mapping.",
        "remediate",
        True,
    ),
    _action(
        "restore_recording_state",
        "Restore recording state",
        "Restore the simulated EEG recording integration state.",
        "remediate",
        True,
    ),
    _action(
        "realign_timeline",
        "Realign timeline",
        "Realign the simulated EEG, event, and response timelines.",
        "remediate",
        True,
    ),
    _action(
        "collect_fresh_eeg_window",
        "Collect fresh EEG window",
        "Collect deterministic post-change trace and frequency evidence.",
        "collect",
        False,
    ),
    _action(
        "present_test_flash",
        "Present test flash",
        "Present one deterministic test flash and collect fresh onset evidence.",
        "collect",
        False,
    ),
    _action(
        "run_response_preflight",
        "Run response preflight",
        "Test every required simulated response control and identity query.",
        "collect",
        False,
    ),
    _action(
        "run_recording_preflight",
        "Run recording preflight",
        "Collect a deterministic event across all required recording timelines.",
        "collect",
        False,
    ),
    _action(
        "wait_for_stable_window",
        "Wait for stable window",
        "Advance one bounded logical observation window without changing hardware.",
        "collect",
        False,
    ),
    _action(
        "start_acquisition",
        "Start short acquisition",
        "Start the deterministic short mock acquisition after supported gates pass.",
        "decide",
        True,
    ),
    _action(
        "continue_acquisition",
        "Continue acquisition",
        "Advance one logical mock trial only while all blocking gates pass.",
        "decide",
        True,
    ),
    _action(
        "pause_acquisition",
        "Pause acquisition",
        "Pause before another trial when runtime evidence is invalid.",
        "decide",
        True,
    ),
    _action(
        "annotate_invalid_interval",
        "Annotate invalid interval",
        "Attach a broad evidence path and visible evidence reference to invalid trials.",
        "collect",
        True,
        {
            "type": "object",
            "properties": {
                "start_trial": {"type": "integer", "minimum": 1, "maximum": 4},
                "end_trial": {"type": "integer", "minimum": 1, "maximum": 4},
                "path": {
                    "type": "string",
                    "enum": ["eeg", "onset", "response", "recording"],
                },
                "evidence_id": {"type": "string", "minLength": 1},
            },
            "required": ["start_trial", "end_trial", "path", "evidence_id"],
            "additionalProperties": False,
        },
    ),
    _action(
        "resume_acquisition",
        "Resume acquisition",
        "Resume only after current passing evidence and complete invalid-data annotation.",
        "decide",
        True,
    ),
    _action(
        "complete_preflight",
        "Complete preflight",
        "Finish a preflight-scoped episode only with current supported evidence.",
        "decide",
        True,
    ),
    _action(
        "close_acquisition",
        "Close acquisition",
        "Close a completed acquisition only with passing gates and preserved annotations.",
        "decide",
        True,
    ),
    _action(
        "abort_episode",
        "Abort episode",
        "Abort with the current evidence reference when a required path remains unavailable.",
        "decide",
        True,
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "enum": ["eeg", "onset", "response", "recording"],
                },
                "evidence_id": {"type": "string", "minLength": 1},
            },
            "required": ["path", "evidence_id"],
            "additionalProperties": False,
        },
    ),
)

FAULT_SEMANTICS: dict[str, dict[str, Any]] = {
    "local_contact": {
        "domain": "eeg",
        "inspection_actions": ["inspect_eeg_signals", "inspect_frequency_evidence"],
        "retest_action": "collect_fresh_eeg_window",
        "invalidates": ["eeg"],
        "variants": [
            {
                "visible_variant": "unstable_high_impedance",
                "target": "FC3",
                "recovery_ladder": ["reseat_electrode"],
            },
            {
                "visible_variant": "persistent_local_noise",
                "target": "FC4",
                "recovery_ladder": ["reseat_electrode", "replace_electrode"],
            },
            {
                "visible_variant": "intermittent_dropout",
                "target": "FT7",
                "recovery_ladder": ["reseat_electrode"],
            },
            {
                "visible_variant": "implausible_neighbor_contrast",
                "target": "FT8",
                "recovery_ladder": ["reseat_electrode", "replace_electrode"],
            },
        ],
    },
    "flatline_clipping": {
        "domain": "eeg",
        "inspection_actions": ["inspect_eeg_signals", "inspect_frequency_evidence"],
        "retest_action": "collect_fresh_eeg_window",
        "invalidates": ["eeg"],
        "variants": [
            {
                "visible_variant": "flatline",
                "target": "FC4",
                "recovery_ladder": ["reconnect_electrode_path"],
            },
            {
                "visible_variant": "rail_clipping",
                "target": "FT8",
                "recovery_ladder": ["reconnect_electrode_path"],
            },
        ],
    },
    "reference_ground": {
        "domain": "eeg",
        "inspection_actions": ["inspect_eeg_signals", "inspect_frequency_evidence"],
        "retest_action": "collect_fresh_eeg_window",
        "invalidates": ["eeg"],
        "variants": [
            {
                "visible_variant": "shared_reference_contamination",
                "target": "reference",
                "recovery_ladder": ["reconnect_reference"],
            },
            {
                "visible_variant": "shared_ground_contamination",
                "target": "ground",
                "recovery_ladder": ["reconnect_ground"],
            },
        ],
    },
    "participant_artifact": {
        "domain": "eeg",
        "inspection_actions": ["inspect_eeg_signals", "inspect_participant_state"],
        "retest_action": "collect_fresh_eeg_window",
        "invalidates": ["eeg"],
        "variants": [
            {
                "visible_variant": "movement_transient",
                "target": "participant",
                "recovery_ladder": ["ask_participant_to_relax"],
            },
            {
                "visible_variant": "muscle_activity",
                "target": "participant",
                "recovery_ladder": ["ask_participant_to_relax"],
            },
        ],
    },
    "environmental_contamination": {
        "domain": "eeg",
        "inspection_actions": ["inspect_frequency_evidence", "inspect_environment"],
        "retest_action": "collect_fresh_eeg_window",
        "invalidates": ["eeg"],
        "variants": [
            {
                "visible_variant": "rhythmic_shared_source",
                "target": "electrical_source",
                "recovery_ladder": ["isolate_electrical_source"],
            },
            {
                "visible_variant": "broadband_shared_source",
                "target": "electrical_source",
                "recovery_ladder": ["isolate_electrical_source"],
            },
        ],
    },
    "duplicate_onset": {
        "domain": "onset",
        "inspection_actions": ["inspect_onset_route"],
        "retest_action": "present_test_flash",
        "invalidates": ["onset"],
        "variants": [
            {
                "visible_variant": "duplicate_marker_burst",
                "target": "refractory_route",
                "recovery_ladder": ["repair_refractory_route"],
            }
        ],
    },
    "missing_onset": {
        "domain": "onset",
        "inspection_actions": ["inspect_onset_route"],
        "retest_action": "present_test_flash",
        "invalidates": ["onset"],
        "variants": [
            {
                "visible_variant": "missing_route_event",
                "target": "onset_route",
                "recovery_ladder": ["repair_onset_route"],
            }
        ],
    },
    "visible_onset_cue": {
        "domain": "onset",
        "inspection_actions": ["inspect_onset_route"],
        "retest_action": "present_test_flash",
        "invalidates": ["onset", "response"],
        "variants": [
            {
                "visible_variant": "participant_visible_flash",
                "target": "participant_view",
                "recovery_ladder": ["correct_trigger_visibility"],
            }
        ],
    },
    "response_mismatch": {
        "domain": "response",
        "inspection_actions": ["inspect_response_timeline"],
        "retest_action": "run_response_preflight",
        "invalidates": ["response"],
        "variants": [
            {
                "visible_variant": "incorrect_control_mapping",
                "target": "response_mapping",
                "recovery_ladder": ["correct_response_mapping"],
            },
            {
                "visible_variant": "stale_identity_handshake",
                "target": "identity_handshake",
                "recovery_ladder": ["restart_response_handshake"],
            },
        ],
    },
    "recording_mismatch": {
        "domain": "recording",
        "inspection_actions": ["inspect_recording_timeline"],
        "retest_action": "run_recording_preflight",
        "invalidates": ["recording"],
        "variants": [
            {
                "visible_variant": "inactive_recording",
                "target": "recording_state",
                "recovery_ladder": ["restore_recording_state"],
            },
            {
                "visible_variant": "timeline_misalignment",
                "target": "integration_timeline",
                "recovery_ladder": ["realign_timeline"],
            },
        ],
    },
    "configuration_mismatch": {
        "domain": "configuration",
        "inspection_actions": ["inspect_configuration"],
        "retest_action": "inspect_configuration",
        "invalidates": ["configuration", "eeg", "onset", "response", "recording"],
        "variants": [
            {
                "visible_variant": "montage_role_mismatch",
                "target": "procedure_configuration",
                "recovery_ladder": ["correct_acquisition_configuration"],
            },
            {
                "visible_variant": "sampling_profile_mismatch",
                "target": "procedure_configuration",
                "recovery_ladder": ["correct_acquisition_configuration"],
            },
        ],
    },
}

NAMED_RANDOM_STREAMS = (
    "identity",
    "blueprint",
    "nuisance",
    "fault_variant",
    "signal",
    "panel_order",
    "event_offset",
    "runtime_activation",
    "runtime_activation_trial",
)

NUISANCE_FAMILY_RULES: dict[str, Any] = {
    "familiar": {
        "channel_order": "selected procedure order",
        "event_offset_ms": 0.0,
    },
    "reserved": {
        "channel_order": "seeded rotation preserving site labels and roles",
        "event_offset_ms": "three times the seed modulo five",
        "causal_invariance": (
            "Only baseline phase, display order, and aligned event offset change; "
            "fault meaning and recovery remain fixed."
        ),
    },
}

APPLICABLE_DOMAIN_RULES: dict[str, tuple[str, ...]] = {
    "marker_only": ("onset",),
    "default": ("configuration", "eeg", "onset", "response", "recording"),
}

AMBIGUITY_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "widespread_noise": {
        "required_actions": (
            "inspect_configuration",
            "inspect_eeg_signals",
            "inspect_frequency_evidence",
            "inspect_participant_state",
            "inspect_environment",
        ),
        "panel": "eeg",
        "instruction": (
            "Compare the selected reference role, trace and frequency structure, "
            "participant history, and shared electrical-source history before changing state."
        ),
    },
    "quiet_channel": {
        "required_actions": ("inspect_eeg_signals", "inspect_frequency_evidence"),
        "panel": "eeg",
        "instruction": (
            "Compare short-term dynamics, frequency content, dropout history, and neighbors."
        ),
    },
    "unstable_channel": {
        "required_actions": ("inspect_eeg_signals", "inspect_frequency_evidence"),
        "panel": "eeg",
        "instruction": (
            "Compare the unstable site with its neighbors in time and frequency before acting."
        ),
    },
    "flash_without_marker": {
        "required_actions": ("inspect_onset_route", "inspect_recording_timeline"),
        "panel": "onset",
        "instruction": (
            "Compare the route-component and complete recording timelines before repair."
        ),
    },
    "response_without_identity": {
        "required_actions": ("run_response_preflight", "inspect_response_timeline"),
        "panel": "response",
        "instruction": (
            "Test the complete required control set, then compare occurrence and identity events."
        ),
    },
    "noisy_cap_site": {
        "required_actions": (
            "inspect_configuration",
            "inspect_eeg_signals",
            "inspect_frequency_evidence",
        ),
        "panel": "eeg",
        "instruction": (
            "Check the selected Montage role, then compare the site in time and frequency."
        ),
    },
    "short_shared_transient": {
        "required_actions": (
            "wait_for_stable_window",
            "inspect_eeg_signals",
            "inspect_frequency_evidence",
            "inspect_participant_state",
            "inspect_environment",
        ),
        "panel": "eeg",
        "instruction": (
            "Collect a bounded fresh window and compare trace, frequency, participant, "
            "and shared electrical-source history before changing state."
        ),
    },
}

EVIDENCE_REFERENCE_RULES = (
    "Policy-visible evidence references are deterministic opaque tokens.",
    "Evidence references never serialize a scenario seed or causal identifier.",
    "Visible observations expose measured evidence and per-domain applicability, never a "
    "scalar readiness verdict or hidden recoverability state.",
)

NEGATIVE_CONTROL_RULES: dict[str, Any] = {
    "kinds": ("none", "optional_channel", "benign_transient", "benign_mimic"),
    "role_requirement": (
        "Optional-channel controls are optional; real faults and benign required-signal "
        "mimics or transients are required; plain nominal rows are not applicable."
    ),
    "combined_quota_marker": (
        "optional_transient remains a compatibility marker only for optional_channel "
        "or benign_transient controls; benign_mimic does not enter the combined quota."
    ),
    "optional_over_intervention_scope": "optional_channel only",
}

LIFECYCLE_RULES = (
    "All episodes begin in preflight with separately inspectable applicable evidence gates.",
    "A state-changing action invalidates every declared dependent evidence domain.",
    "A gate is supported only by current evidence collected after its latest change.",
    "Invalid start, resume, or continuation attempts remain canonical no-op trace events.",
    "A scheduled runtime fault activates at the end of its pinned completed trial.",
    "Runtime invalidity requires pause before another trial and annotation before resume.",
    "Runtime remediation is rejected until invalid recording evidence has been paused.",
    "The bounded mock acquisition never advances beyond four completed trials.",
    "Preflight-scoped episodes terminate through complete_preflight.",
    "Full episodes terminate through valid close_acquisition or evidence-eligible abort.",
    "Every safe compound recovery order is accepted; no exact action order is scored.",
)

REWARD_SPECIFICATION: dict[str, Any] = {
    "clip": [0.0, 1.0],
    "components": {
        "terminal_correctness": 0.45,
        "safety_compliance": 0.20,
        "fresh_validation": 0.15,
        "targeted_intervention": 0.10,
        "data_stewardship": 0.05,
        "efficiency": 0.05,
    },
    "penalties": {
        "invalid_start_resume_or_continue_first": 0.35,
        "invalid_start_resume_or_continue_additional": 0.15,
        "invalid_start_resume_or_continue_cap": 0.65,
        "unannotated_invalid_interval": 0.20,
        "three_unrelated_changes_without_retest": 0.10,
        "repeated_no_effect_change": 0.05,
        "repeated_no_effect_change_cap": 0.15,
    },
    "eligible_unavailable_abort_terminal_credit": 1.0,
}

METRIC_DEFINITIONS = (
    "reward",
    "terminal_correctness",
    "terminal_credit",
    "exact_terminal_success",
    "valid_close",
    "explicit_abort",
    "eligible_safe_abort",
    "unavailable_scenario",
    "safety_compliance",
    "fresh_validation",
    "targeted_intervention",
    "data_stewardship",
    "efficiency",
    "invalid_start_attempts",
    "invalid_resume_attempts",
    "invalid_continuation_attempts",
    "invalid_start_or_resume_episode",
    "runtime_fault_count",
    "invalid_continuation_fault_count",
    "pause_latency_logical_events",
    "pause_latency_observed",
    "first_intervention_relevance",
    "first_intervention_count",
    "first_intervention_relevant_count",
    "recovery_success",
    "recoverable_scenario_count",
    "recovery_success_count",
    "retest_coverage",
    "state_changing_remediation_count",
    "retested_remediation_count",
    "trace_frequency_inspection_rate",
    "eeg_quality_decision_count",
    "trace_frequency_supported_decision_count",
    "annotation_coverage",
    "invalid_runtime_duration",
    "annotated_invalid_runtime_duration",
    "annotation_overreach",
    "valid_runtime_duration",
    "overannotated_valid_runtime_duration",
    "optional_channel_over_intervention",
    "optional_channel_scenario_count",
    "optional_channel_over_intervention_count",
    "excess_intervention_count",
    "correct_terminal_count",
    "close_decision_count",
    "valid_close_count",
    "actions_to_correct_terminal",
)

METRIC_SEMANTICS: dict[str, str] = {
    "terminal_credit": (
        "One for an exact valid close or eligible unavailable abort, 0.25 for a "
        "recoverable blocking-path abort after a targeted attempt and fresh persistent "
        "retest, 0.10 for an earlier current blocking-path abort, and zero otherwise."
    ),
    "first_intervention_relevance": (
        "Whether the first state-changing remediation targeted a path supported by prior "
        "current evidence; one when no remediation was attempted."
    ),
    "retest_coverage": (
        "Fraction of accepted apparatus-changing remediations followed at that change "
        "revision by fresh evidence for every invalidated domain."
    ),
    "trace_frequency_inspection_rate": (
        "Fraction of EEG remediation, start, continuation, resume, or terminal decisions "
        "preceded by current time-domain and frequency inspection."
    ),
    "annotation_coverage": (
        "Fraction of verifier-known invalid trial-path duration covered by annotations."
    ),
    "annotation_overreach": (
        "Fraction of annotated trial-path duration outside verifier-known invalid duration."
    ),
    "optional_channel_over_intervention": (
        "Whether an optional-channel-only control received a state change or abort."
    ),
    "excess_intervention_count": (
        "Accepted state-changing remediations beyond effective shortest-path progress."
    ),
    "actions_to_correct_terminal": (
        "Accepted actions before a valid close or eligible abort, excluding the terminal "
        "decision and semantic no-op rejections; zero for an incorrect terminal."
    ),
    "conditional_rate_statistics": (
        "Conditional diagnostic rates expose numerator and denominator counts: first "
        "interventions, recoverable scenarios, accepted state-changing remediations, EEG "
        "quality decisions, invalid and valid path-trial duration, optional-channel "
        "scenarios, runtime faults, pause observations, close decisions, valid closes, "
        "and correct terminals."
    ),
}


def curriculum_contract_document() -> dict[str, Any]:
    """Return a detached canonical document covering generator and scorer semantics."""

    return deepcopy(
        {
            "generator_revision": GENERATOR_REVISION,
            "runtime_revision": RUNTIME_REVISION,
            "scorer_revision": SCORER_REVISION,
            "objective": CANONICAL_OBJECTIVE,
            "actions": CURRICULUM_ACTIONS,
            "fault_semantics": FAULT_SEMANTICS,
            "named_random_streams": NAMED_RANDOM_STREAMS,
            "nuisance_families": NUISANCE_FAMILY_RULES,
            "applicable_domains": APPLICABLE_DOMAIN_RULES,
            "ambiguity_requirements": AMBIGUITY_REQUIREMENTS,
            "evidence_references": EVIDENCE_REFERENCE_RULES,
            "negative_controls": NEGATIVE_CONTROL_RULES,
            "lifecycle_rules": LIFECYCLE_RULES,
            "reward": REWARD_SPECIFICATION,
            "metrics": METRIC_DEFINITIONS,
            "metric_semantics": METRIC_SEMANTICS,
        }
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


CURRICULUM_CONTRACT_DIGEST = (
    "sha256:" + hashlib.sha256(_canonical_bytes(curriculum_contract_document())).hexdigest()
)


__all__ = [
    "AMBIGUITY_REQUIREMENTS",
    "APPLICABLE_DOMAIN_RULES",
    "CANONICAL_OBJECTIVE",
    "CURRICULUM_ACTIONS",
    "CURRICULUM_CONTRACT_DIGEST",
    "EVIDENCE_REFERENCE_RULES",
    "FAULT_SEMANTICS",
    "GENERATOR_REVISION",
    "METRIC_DEFINITIONS",
    "METRIC_SEMANTICS",
    "NEGATIVE_CONTROL_RULES",
    "NUISANCE_FAMILY_RULES",
    "REWARD_SPECIFICATION",
    "RUNTIME_REVISION",
    "SCORER_REVISION",
    "curriculum_contract_document",
]
