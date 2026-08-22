"""Scientific authoring domain for configurable synthetic EEG Environments."""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from studio.bundle import (
    BundleValidationError,
    EnvironmentBundle,
    validate_environment_bundle,
)


class _FrozenExtensibleModel(BaseModel):
    """Immutable authoring value that retains compatible minor additions."""

    model_config = ConfigDict(extra="allow", frozen=True)


class EegSite(_FrozenExtensibleModel):
    """One named site in the schematic whole-cap catalog."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    kind: Literal["scalp", "auxiliary"]


class EegApparatusCapability(_FrozenExtensibleModel):
    """What the simulated EEG Apparatus can record, independent of a Montage."""

    kind: Literal["eeg"]
    label: str = Field(min_length=1)
    recording_input_capacity: int = Field(ge=1)
    coordinate_system: str = Field(min_length=1)
    scientific_claim: str = Field(min_length=1)
    sites: tuple[EegSite, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> EegApparatusCapability:
        site_ids = [site.id.casefold() for site in self.sites]
        if len(site_ids) != len(set(site_ids)):
            raise ValueError("the EEG site catalog contains duplicate identities")
        return self


class EegMontage(_FrozenExtensibleModel):
    """Procedure-selected recording, reference, and ground sites."""

    recording_sites: tuple[str, ...] = Field(min_length=1)
    reference: str = Field(min_length=1)
    ground: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roles(self) -> EegMontage:
        recording_ids = [site_id.casefold() for site_id in self.recording_sites]
        if len(recording_ids) != len(set(recording_ids)):
            raise ValueError("the Montage contains duplicate recording sites")
        roles = (
            *recording_ids,
            self.reference.casefold(),
            self.ground.casefold(),
        )
        if len(roles) != len(set(roles)):
            raise ValueError("recording, reference, and ground roles must be disjoint")
        return self


class EegAcquisitionProfile(_FrozenExtensibleModel):
    """Bounded acquisition settings for the synthetic EEG Procedure."""

    sampling_hz: int = Field(ge=128, le=4096)
    online_bandpass_hz: tuple[float, float]
    notch_hz: Literal[50, 60]

    @model_validator(mode="after")
    def validate_bandpass(self) -> EegAcquisitionProfile:
        low_hz, high_hz = self.online_bandpass_hz
        if not math.isfinite(low_hz) or not math.isfinite(high_hz):
            raise ValueError("the online bandpass must use finite values")
        if low_hz < 0.01 or high_hz > 250 or low_hz >= high_hz:
            raise ValueError(
                "the online bandpass must increase from at least 0.01 Hz to at most 250 Hz"
            )
        if high_hz >= self.sampling_hz / 2:
            raise ValueError("the online bandpass must remain below the Nyquist frequency")
        return self


class EegProcedureConfiguration(_FrozenExtensibleModel):
    """The author-selected Montage and acquisition settings for one Procedure."""

    name: str = Field(min_length=1)
    montage: EegMontage
    acquisition_profile: EegAcquisitionProfile


class EegDescriptiveNote(_FrozenExtensibleModel):
    """Reversible descriptive input that is never executable run control."""

    id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content: str = Field(min_length=1)
    verification_status: Literal["unverified_descriptive_input"] = (
        "unverified_descriptive_input"
    )
    run_control: Literal[False] = False


class EegAuthoringState(_FrozenExtensibleModel):
    """One immutable EEG draft value at the apparatus-specific seam."""

    apparatus: EegApparatusCapability
    procedure: EegProcedureConfiguration
    notes: tuple[EegDescriptiveNote, ...] = ()

    @model_validator(mode="after")
    def validate_configuration_against_capability(self) -> EegAuthoringState:
        catalog = {site.id: site for site in self.apparatus.sites}
        montage = self.procedure.montage
        selected = (*montage.recording_sites, montage.reference, montage.ground)
        missing = sorted(set(selected).difference(catalog))
        if missing:
            raise ValueError(
                "the Procedure selects sites absent from the Apparatus catalog: "
                + ", ".join(missing)
            )
        if len(montage.recording_sites) > self.apparatus.recording_input_capacity:
            raise ValueError("the Montage exceeds the Apparatus recording-input capacity")
        non_scalp = [
            site_id
            for site_id in montage.recording_sites
            if catalog[site_id].kind != "scalp"
        ]
        if non_scalp:
            raise ValueError(
                "recording sites must use scalp catalog positions: "
                + ", ".join(non_scalp)
            )
        return self


class EegCommandResult(_FrozenExtensibleModel):
    """Typed interpretation of one bounded ordinary-language draft request."""

    status: Literal["applied", "unsupported"]
    reason: Literal[
        "montage_updated",
        "acquisition_updated",
        "ambiguous_request",
        "unsupported_request",
        "invalid_request",
    ]
    summary: str = Field(min_length=1)
    state: EegAuthoringState


class EegAuthoringValidationError(ValueError):
    """Raised when direct descriptive authoring input is not safe to stage."""


_ADD_SITE_PATTERN = re.compile(
    r"^\s*add\s+(?:site\s+)?(?P<site>[A-Za-z][A-Za-z0-9]*)\s+"
    r"to\s+(?:the\s+)?montage[.!]?\s*$",
    flags=re.IGNORECASE,
)
_REMOVE_SITE_PATTERN = re.compile(
    r"^\s*remove\s+(?:site\s+)?(?P<site>[A-Za-z][A-Za-z0-9]*)\s+"
    r"from\s+(?:the\s+)?montage[.!]?\s*$",
    flags=re.IGNORECASE,
)
_SAMPLING_PATTERN = re.compile(
    r"^\s*(?:set|change)\s+(?:the\s+)?sampling(?:\s+rate)?\s+to\s+"
    r"(?P<hz>[0-9]+)\s*hz[.!]?\s*$",
    flags=re.IGNORECASE,
)
_NOTCH_PATTERN = re.compile(
    r"^\s*(?:set|change)\s+(?:the\s+)?notch(?:\s+filter)?\s+to\s+"
    r"(?P<hz>[0-9]+)\s*hz[.!]?\s*$",
    flags=re.IGNORECASE,
)
_BANDPASS_PATTERN = re.compile(
    r"^\s*(?:set|change)\s+(?:the\s+)?(?:online\s+)?bandpass\s+to\s+"
    r"(?P<low>[0-9]+(?:\.[0-9]+)?)\s*(?:-|–|—|to)\s*"
    r"(?P<high>[0-9]+(?:\.[0-9]+)?)\s*hz[.!]?\s*$",
    flags=re.IGNORECASE,
)
_COMMAND_CUES = (
    re.compile(r"\badd\b.*\bmontage\b", flags=re.IGNORECASE),
    re.compile(r"\bremove\b.*\bmontage\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:set|change)\b.*\bsampling\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:set|change)\b.*\bnotch\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:set|change)\b.*\bbandpass\b", flags=re.IGNORECASE),
)


def seed_authoring_state(bundle: EnvironmentBundle) -> EegAuthoringState:
    """Return a detached immutable EEG authoring state from a validated bundle."""

    configuration: Any = (bundle.procedure.model_extra or {}).get("configuration")
    if configuration is None:
        raise BundleValidationError("the EEG bundle has no Procedure configuration")
    try:
        return EegAuthoringState.model_validate(
            {
                "apparatus": bundle.apparatus,
                "procedure": configuration,
                "notes": (),
            }
        ).model_copy(deep=True)
    except ValidationError as error:
        messages = "; ".join(item["msg"] for item in error.errors())
        raise BundleValidationError(
            f"invalid EEG authoring configuration: {messages}"
        ) from error


def apply_authoring_command(
    state: EegAuthoringState, command: str
) -> EegCommandResult:
    """Interpret one bounded draft request without mutating the supplied state."""

    if len(command) > 240:
        return _unsupported_result(
            state,
            "unsupported_request",
            "Please describe one short Montage or acquisition change at a time.",
        )
    operation_count = sum(pattern.search(command) is not None for pattern in _COMMAND_CUES)
    has_conjunction = re.search(r"\b(?:and|or)\b", command, re.IGNORECASE) is not None
    if operation_count > 1 or (operation_count == 1 and has_conjunction):
        return _unsupported_result(
            state,
            "ambiguous_request",
            "I found more than one change. Please request one change at a time.",
        )

    notch_match = _NOTCH_PATTERN.fullmatch(command)
    if notch_match is not None:
        return _apply_notch_command(state, notch_match)

    bandpass_match = _BANDPASS_PATTERN.fullmatch(command)
    if bandpass_match is not None:
        return _apply_bandpass_command(state, bandpass_match)

    sampling_match = _SAMPLING_PATTERN.fullmatch(command)
    if sampling_match is not None:
        return _apply_sampling_command(state, sampling_match)

    remove_match = _REMOVE_SITE_PATTERN.fullmatch(command)
    if remove_match is not None:
        return _apply_remove_site_command(state, remove_match)

    add_match = _ADD_SITE_PATTERN.fullmatch(command)
    if add_match is not None:
        return _apply_add_site_command(state, add_match)

    return _unsupported_result(
        state,
        "unsupported_request",
        (
            "I could not apply that request. I can revise Montage sites or "
            "supported acquisition settings."
        ),
    )


def _apply_notch_command(
    state: EegAuthoringState,
    match: re.Match[str],
) -> EegCommandResult:
    notch_hz = int(match.group("hz"))
    acquisition = _updated_acquisition(state, notch_hz=notch_hz)
    if acquisition is None:
        return _unsupported_result(
            state,
            "invalid_request",
            "The supported notch settings are 50 Hz and 60 Hz.",
        )
    return _acquisition_result(
        state,
        acquisition,
        f"Set the notch to {notch_hz} Hz.",
    )


def _apply_bandpass_command(
    state: EegAuthoringState,
    match: re.Match[str],
) -> EegCommandResult:
    low_hz = float(match.group("low"))
    high_hz = float(match.group("high"))
    acquisition = _updated_acquisition(
        state,
        online_bandpass_hz=(low_hz, high_hz),
    )
    if acquisition is None:
        return _unsupported_result(
            state,
            "invalid_request",
            "That bandpass is outside the supported range or reaches the sampling limit.",
        )
    return _acquisition_result(
        state,
        acquisition,
        f"Set the online bandpass to {low_hz:g}–{high_hz:g} Hz.",
    )


def _apply_sampling_command(
    state: EegAuthoringState,
    match: re.Match[str],
) -> EegCommandResult:
    sampling_hz = int(match.group("hz"))
    acquisition = _updated_acquisition(state, sampling_hz=sampling_hz)
    if acquisition is None:
        return _unsupported_result(
            state,
            "invalid_request",
            (
                "That sampling rate is outside the supported 128–4096 Hz range "
                "or would place the current bandpass at the sampling limit."
            ),
        )
    return _acquisition_result(
        state,
        acquisition,
        f"Set the sampling rate to {sampling_hz} Hz.",
    )


def _apply_remove_site_command(
    state: EegAuthoringState,
    match: re.Match[str],
) -> EegCommandResult:
    requested_site = match.group("site")
    montage = state.procedure.montage
    role_ids = {
        montage.reference.casefold(): "reference",
        montage.ground.casefold(): "ground",
    }
    selected_role = role_ids.get(requested_site.casefold())
    if selected_role is not None:
        return _unsupported_result(
            state,
            "invalid_request",
            (
                f"{requested_site} is the Montage {selected_role}; this request "
                "only removes recording sites."
            ),
        )
    recording_by_case = {
        site_id.casefold(): site_id for site_id in montage.recording_sites
    }
    site_id = recording_by_case.get(requested_site.casefold())
    if site_id is None:
        return _unsupported_result(
            state,
            "invalid_request",
            f"{requested_site} is not a recording site in this Montage.",
        )
    if len(montage.recording_sites) == 1:
        return _unsupported_result(
            state,
            "invalid_request",
            "A Montage must retain at least one recording site.",
        )
    recording_sites = tuple(
        selected for selected in montage.recording_sites if selected != site_id
    )
    return _montage_result(
        state,
        recording_sites,
        f"Removed {site_id} from the Montage recording sites.",
    )


def _apply_add_site_command(
    state: EegAuthoringState,
    match: re.Match[str],
) -> EegCommandResult:
    requested_site = match.group("site")
    catalog = {site.id.casefold(): site for site in state.apparatus.sites}
    site = catalog.get(requested_site.casefold())
    if site is None:
        return _unsupported_result(
            state,
            "invalid_request",
            f"{requested_site} is not in this Apparatus site catalog.",
        )
    montage = state.procedure.montage
    if site.kind != "scalp":
        return _unsupported_result(
            state,
            "invalid_request",
            f"{site.id} is not available as a scalp recording site.",
        )
    roles = {
        selected.casefold()
        for selected in (*montage.recording_sites, montage.reference, montage.ground)
    }
    if site.id.casefold() in roles:
        return _unsupported_result(
            state,
            "invalid_request",
            f"{site.id} already has a role in this Montage.",
        )
    if len(montage.recording_sites) >= state.apparatus.recording_input_capacity:
        return _unsupported_result(
            state,
            "invalid_request",
            "The Montage already uses all available recording inputs.",
        )
    return _montage_result(
        state,
        (*montage.recording_sites, site.id),
        f"Added {site.id} as a Montage recording site.",
    )


def _montage_result(
    state: EegAuthoringState,
    recording_sites: tuple[str, ...],
    summary: str,
) -> EegCommandResult:
    montage_document = state.procedure.montage.model_dump(
        mode="python", round_trip=True
    )
    montage_document["recording_sites"] = recording_sites
    next_state = _state_with_procedure_update(state, montage=montage_document)
    return EegCommandResult(
        status="applied",
        reason="montage_updated",
        summary=summary,
        state=next_state,
    )


def stage_descriptive_note(
    state: EegAuthoringState,
    filename: str,
    content: str,
) -> EegAuthoringState:
    """Stage bounded note text as unverified, noncontrolling descriptive input."""

    if (
        not filename.strip()
        or len(filename) > 255
        or "/" in filename
        or "\\" in filename
    ):
        raise EegAuthoringValidationError(
            "Use a non-empty local filename without directory segments."
        )
    if not content.strip() or len(content) > 100_000:
        raise EegAuthoringValidationError(
            "Descriptive note text must contain 1 to 100000 characters."
        )
    note_digest = hashlib.sha256(
        filename.encode("utf-8") + b"\0" + content.encode("utf-8")
    ).hexdigest()
    note = EegDescriptiveNote(
        id=f"note-{note_digest[:16]}",
        filename=filename,
        content=content,
    )
    if any(existing.id == note.id for existing in state.notes):
        return state.model_copy(deep=True)
    return EegAuthoringState.model_validate(
        {
            **state.model_dump(mode="python", round_trip=True),
            "notes": (*state.notes, note),
        }
    )


def compile_frozen_bundle(
    source_bundle: EnvironmentBundle,
    state: EegAuthoringState,
    revision: int,
) -> EnvironmentBundle:
    """Compile a detached, validated EEG bundle for one immutable run revision."""

    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise EegAuthoringValidationError(
            "A frozen revision must be a non-negative whole number."
        )

    document = deepcopy(
        source_bundle.model_dump(mode="python", round_trip=True)
    )
    apparatus_document = state.apparatus.model_dump(mode="json", round_trip=True)
    configuration_document = state.procedure.model_dump(mode="json", round_trip=True)
    document["bundle_revision"] = f"1.2.{revision}"
    document["apparatus"] = apparatus_document
    document["procedure"]["configuration"] = deepcopy(configuration_document)

    observation_schema = document["observation_schema"]
    if "procedure_configuration" not in observation_schema["properties"]:
        raise BundleValidationError(
            "the EEG observation contract has no Procedure configuration"
        )
    required_observations = observation_schema.setdefault("required", [])
    if "procedure_configuration" not in required_observations:
        required_observations.append("procedure_configuration")

    for scenario in document["scenarios"]:
        scenario["initial_state"]["policy_visible"]["procedure_configuration"] = (
            deepcopy(configuration_document)
        )

    return validate_environment_bundle(document).model_copy(deep=True)


def _unsupported_result(
    state: EegAuthoringState,
    reason: Literal[
        "ambiguous_request",
        "unsupported_request",
        "invalid_request",
    ],
    summary: str,
) -> EegCommandResult:
    return EegCommandResult(
        status="unsupported",
        reason=reason,
        summary=summary,
        state=state.model_copy(deep=True),
    )


def _updated_acquisition(
    state: EegAuthoringState,
    *,
    sampling_hz: int | None = None,
    online_bandpass_hz: tuple[float, float] | None = None,
    notch_hz: int | None = None,
) -> EegAcquisitionProfile | None:
    document = state.procedure.acquisition_profile.model_dump(
        mode="python", round_trip=True
    )
    if sampling_hz is not None:
        document["sampling_hz"] = sampling_hz
    if online_bandpass_hz is not None:
        document["online_bandpass_hz"] = online_bandpass_hz
    if notch_hz is not None:
        document["notch_hz"] = notch_hz
    try:
        return EegAcquisitionProfile.model_validate(document)
    except ValidationError:
        return None


def _state_with_procedure_update(
    state: EegAuthoringState,
    **updates: Any,
) -> EegAuthoringState:
    procedure_document = state.procedure.model_dump(mode="python", round_trip=True)
    procedure_document.update(updates)
    return EegAuthoringState.model_validate(
        {
            **state.model_dump(mode="python", round_trip=True),
            "procedure": procedure_document,
        }
    )


def _acquisition_result(
    state: EegAuthoringState,
    acquisition: EegAcquisitionProfile,
    summary: str,
) -> EegCommandResult:
    if acquisition == state.procedure.acquisition_profile:
        return EegCommandResult(
            status="unsupported",
            reason="invalid_request",
            summary="Those acquisition settings are already active in this draft.",
            state=state.model_copy(deep=True),
        )
    next_state = _state_with_procedure_update(
        state,
        acquisition_profile=acquisition.model_dump(mode="python", round_trip=True),
    )
    return EegCommandResult(
        status="applied",
        reason="acquisition_updated",
        summary=summary,
        state=next_state,
    )


__all__ = [
    "EegAcquisitionProfile",
    "EegApparatusCapability",
    "EegAuthoringState",
    "EegAuthoringValidationError",
    "EegCommandResult",
    "EegDescriptiveNote",
    "EegMontage",
    "EegProcedureConfiguration",
    "EegSite",
    "apply_authoring_command",
    "compile_frozen_bundle",
    "seed_authoring_state",
    "stage_descriptive_note",
]
