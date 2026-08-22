"""Private typed domain vocabulary for the synthetic EEG preflight."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceDomain = Literal["eeg", "onset", "response", "recording"]
EvidenceVariant = Literal[
    "signal_window",
    "duplicate_onset",
    "missing_onset",
    "visible_trigger",
    "missing_response_occurrence",
    "response_identity_mismatch",
    "inactive_recording",
    "timeline_misalignment",
]
SignalProfile = Literal[
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
]


class PreflightCase(BaseModel):
    """One pinned hidden case selected by an opaque public scenario identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^eeg-demo-[0-9]{3}$")
    domain: EvidenceDomain
    evidence_variant: EvidenceVariant
    signal_profile: SignalProfile
    target: str | None
    recoverable: bool
    starts_resolved: bool
    relevant_actions: tuple[str, ...]
    effective_actions: tuple[str, ...]
    retest_action: str
    initial_summary: str = Field(min_length=1)
    optional_site: str | None

    @model_validator(mode="after")
    def validate_actions(self) -> PreflightCase:
        variants_by_domain: dict[EvidenceDomain, set[EvidenceVariant]] = {
            "eeg": {"signal_window"},
            "onset": {"duplicate_onset", "missing_onset", "visible_trigger"},
            "response": {
                "missing_response_occurrence",
                "response_identity_mismatch",
            },
            "recording": {"inactive_recording", "timeline_misalignment"},
        }
        if self.evidence_variant not in variants_by_domain[self.domain]:
            raise ValueError("the evidence variant does not match the case domain")
        unknown_relevant = set(self.relevant_actions).difference(STATE_CHANGING_ACTIONS)
        if unknown_relevant:
            raise ValueError("a case references an unknown remediation action")
        if any(
            STATE_CHANGING_ACTIONS[action] != self.domain
            for action in self.relevant_actions
        ):
            raise ValueError("remediation actions must match the case domain")
        if not set(self.effective_actions).issubset(self.relevant_actions):
            raise ValueError("effective actions must be relevant remediation actions")
        if self.retest_action not in RETEST_ACTIONS:
            raise ValueError("a case references an unknown retest action")
        if RETEST_ACTIONS[self.retest_action] != self.domain:
            raise ValueError("the retest action must match the case domain")
        if not self.recoverable and self.effective_actions:
            raise ValueError("an unavailable case cannot declare an effective action")
        return self


class PreflightFixture(BaseModel):
    """Validated content of the pinned synthetic case fixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_revision: Literal["eeg-preflight-fixture-1"]
    cases: tuple[PreflightCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> PreflightFixture:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("preflight case identities must be unique")
        return self


INSPECTION_ACTIONS: dict[str, EvidenceDomain] = {
    "inspect_eeg_signals": "eeg",
    "inspect_frequency_evidence": "eeg",
    "inspect_onset_route": "onset",
    "inspect_response_timeline": "response",
    "inspect_recording_timeline": "recording",
}

STATE_CHANGING_ACTIONS: dict[str, EvidenceDomain] = {
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

RETEST_ACTIONS: dict[str, EvidenceDomain] = {
    "collect_fresh_eeg_window": "eeg",
    "present_test_flash": "onset",
    "run_response_preflight": "response",
    "run_recording_preflight": "recording",
}

DECISION_ACTIONS = ("complete_preflight", "abort_preflight")

# One constant catalog is exposed in every case. Its order is also the compact UI order.
PREFLIGHT_ACTION_TYPES = (
    *INSPECTION_ACTIONS,
    *STATE_CHANGING_ACTIONS,
    *RETEST_ACTIONS,
    *DECISION_ACTIONS,
)
