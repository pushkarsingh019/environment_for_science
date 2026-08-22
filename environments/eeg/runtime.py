"""EEG implementation installed behind the product Runtime interface."""

from __future__ import annotations

from typing import Literal

from environments.eeg import load_legacy_bundle, load_seeded_bundle
from environments.eeg._curriculum_runtime import EegCurriculumRuntime
from environments.eeg._preflight import EegPreflightRuntime
from environments.eeg.presentation import (
    EegOnsetRouteVisualization,
    EegPreflightVisualization,
    validate_eeg_visualization,
)
from studio.bundle import (
    BundleValidationError,
    EnvironmentBundle,
    ScenarioManifest,
    validate_environment_bundle,
)
from studio.runtime import (
    EnvironmentAction,
    EpisodeState,
    EpisodeUpdate,
    RuntimeContractError,
    VerifierOutcome,
)


class _LegacyMarkerRecoveryRuntime:
    """Seeded synthetic marker-recovery Environment implementation."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        visualization = validate_eeg_visualization(self._bundle.visualization)
        if not isinstance(visualization, EegOnsetRouteVisualization):
            raise BundleValidationError(
                "the legacy EEG generator requires an onset-route visualization"
            )
        self._visualization = visualization

    @classmethod
    def from_seed(cls) -> _LegacyMarkerRecoveryRuntime:
        return cls(validate_environment_bundle(load_legacy_bundle()))

    @property
    def bundle(self) -> EnvironmentBundle:
        return self._bundle.model_copy(deep=True)

    @property
    def runtime_validation_bundle(self) -> EnvironmentBundle:
        return self._bundle.model_copy(deep=True)

    @property
    def visualization(self) -> EegOnsetRouteVisualization:
        return self._visualization.model_copy(deep=True)

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
        return EpisodeState(
            procedure_state=self._bundle.procedure.initial_state,
            observation=scenario.initial_state.policy_visible.copy(),
            hidden_state=scenario.initial_state.hidden.copy(),
            state_revision=0,
        )

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate:
        if action.type == "inspect_onset_route":
            return self._inspect_onset_route(state)
        if action.type == "repair_refractory_route":
            return self._repair_refractory_route(state)
        if action.type == "present_test_flash":
            return self._present_test_flash(state)
        if action.type == "restart_response_handshake":
            return self._restart_response_handshake(state)
        raise RuntimeContractError(
            f"EEG action {action.type!r} is not implemented",
            code="internal",
        )

    def _inspect_onset_route(self, state: EpisodeState) -> EpisodeUpdate:
        hidden_state = state.hidden_state.copy()
        hidden_state["route_inspected"] = True
        if hidden_state["refractory_route_repaired"] is False:
            hidden_state["inspected_before_repair"] = True

        observation = state.observation.copy()
        observation["route_inspection"] = {
            "status": "inspected",
            "finding": "Two onset markers follow one simulated lower-right flash.",
        }
        observation["summary"] = (
            "Inspection found two onset markers after one simulated lower-right flash."
        )
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden_state,
            state_revision=state.state_revision,
            summary="The simulated onset route was inspected without changing its state.",
        )

    def _repair_refractory_route(self, state: EpisodeState) -> EpisodeUpdate:
        next_revision = state.state_revision + 1
        hidden_state = state.hidden_state.copy()
        hidden_state["refractory_route_repaired"] = True
        hidden_state["repair_transition"] = next_revision

        observation = state.observation.copy()
        prior_freshness = state.observation["freshness"]
        evidence_state_revision = prior_freshness.get(
            "evidence_state_revision",
            prior_freshness["state_revision"],
        )
        observation["route_inspection"] = {
            "status": "repair_applied",
            "finding": "A fresh simulated test flash is required.",
        }
        observation["freshness"] = {
            "evidence_id": prior_freshness["evidence_id"],
            "evidence_state_revision": evidence_state_revision,
            "state_revision": next_revision,
            "status": "stale",
            "reason": "The simulated onset route changed after this flash.",
        }
        observation["summary"] = (
            "The simulated refractory-route repair invalidated the earlier flash evidence."
        )
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden_state,
            state_revision=next_revision,
            summary="The simulated refractory route changed and prior evidence became stale.",
        )

    def _present_test_flash(self, state: EpisodeState) -> EpisodeUpdate:
        hidden_state = state.hidden_state.copy()
        flash_sequence = int(hidden_state["flash_sequence"]) + 1
        hidden_state["flash_sequence"] = flash_sequence
        marker_count = 1 if hidden_state["refractory_route_repaired"] is True else 2
        evidence_id = f"flash-{flash_sequence:03d}"

        observation = state.observation.copy()
        observation["onset_timeline"] = {
            "flash_sequence": flash_sequence,
            "location": "lower-right",
            "marker_count": marker_count,
            "evidence_id": evidence_id,
        }
        observation["freshness"] = {
            "evidence_id": evidence_id,
            "evidence_state_revision": state.state_revision,
            "state_revision": state.state_revision,
            "status": "current",
        }
        observation["summary"] = (
            f"One lower-right test flash produced {marker_count} onset "
            f"marker{'s' if marker_count != 1 else ''}."
        )
        return EpisodeUpdate(
            observation=observation,
            hidden_state=hidden_state,
            state_revision=state.state_revision,
            summary="A fresh synthetic lower-right test flash was recorded.",
        )

    def _restart_response_handshake(self, state: EpisodeState) -> EpisodeUpdate:
        observation = state.observation.copy()
        observation["summary"] = (
            "The simulated response handshake restarted; onset-marker evidence was unchanged."
        )
        return EpisodeUpdate(
            observation=observation,
            hidden_state=state.hidden_state.copy(),
            state_revision=state.state_revision,
            summary="The response handshake changed no onset-route state or evidence.",
        )

    def verify(self, state: EpisodeState) -> VerifierOutcome:
        timeline = state.observation.get("onset_timeline", {})
        freshness = state.observation.get("freshness", {})
        marker_count = timeline.get("marker_count")
        evidence_id = timeline.get("evidence_id")
        repaired = state.hidden_state["refractory_route_repaired"] is True
        targeted = (
            repaired and state.hidden_state["inspected_before_repair"] is True
        )
        fresh = (
            repaired
            and freshness.get("status") == "current"
            and freshness.get("evidence_id") == evidence_id
            and freshness.get("evidence_state_revision") == state.state_revision
            and freshness.get("state_revision") == state.state_revision
            and state.hidden_state["repair_transition"] == state.state_revision
            and state.hidden_state["flash_sequence"] > 1
        )
        terminal_correct = (
            state.procedure_state == "evidence_ready" and marker_count == 1
        )
        passed = targeted and fresh and terminal_correct

        reasons: list[str] = []
        if not repaired:
            reasons.append("The targeted simulated repair was not applied.")
        elif not targeted:
            reasons.append("The onset route was not inspected before repair.")
        if not fresh:
            reasons.append("No current post-repair test-flash evidence was available.")
        if not terminal_correct:
            reasons.append("The latest test flash did not establish exactly one onset marker.")

        if passed:
            summary = (
                "Recovery verified: one fresh onset marker followed the targeted "
                "simulated repair."
            )
            disposition: Literal["recovered", "failed"] = "recovered"
        else:
            summary = "Recovery not verified: " + " ".join(reasons)
            disposition = "failed"
        return VerifierOutcome(
            passed=passed,
            terminal_disposition=disposition,
            summary=summary,
            metrics={
                "terminal_correctness": float(terminal_correct),
                "fresh_validation": float(fresh),
                "targeted_intervention": float(targeted),
            },
            evidence={
                "evidence_id": evidence_id,
                "marker_count": marker_count,
                "state_revision": state.state_revision,
            },
            reasons=tuple(reasons),
        )


class EegEnvironmentModule:
    """Version-routed EEG module behind the product-owned Runtime seam."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)
        visualization = validate_eeg_visualization(self._bundle.visualization)
        self._visualization = visualization.model_copy(deep=True)
        if bundle.generator_revision == "eeg-marker-generator-1":
            self._implementation: (
                _LegacyMarkerRecoveryRuntime | EegPreflightRuntime | EegCurriculumRuntime
            ) = (
                _LegacyMarkerRecoveryRuntime(self._bundle)
            )
        elif bundle.generator_revision == "eeg-preflight-generator-1":
            self._implementation = EegPreflightRuntime(self._bundle)
        elif bundle.generator_revision == "eeg-curriculum-generator-1":
            self._implementation = EegCurriculumRuntime(self._bundle)
        else:
            raise BundleValidationError("unsupported EEG generator revision")

    @classmethod
    def from_seed(cls) -> EegEnvironmentModule:
        return cls(validate_environment_bundle(load_seeded_bundle()))

    @property
    def bundle(self) -> EnvironmentBundle:
        return self._bundle.model_copy(deep=True)

    @property
    def runtime_validation_bundle(self) -> EnvironmentBundle:
        return self._bundle.model_copy(deep=True)

    @property
    def visualization(
        self,
    ) -> EegOnsetRouteVisualization | EegPreflightVisualization:
        return self._visualization.model_copy(deep=True)

    def initialize(self, scenario: ScenarioManifest) -> EpisodeState:
        return self._implementation.initialize(scenario.model_copy(deep=True))

    def permitted_actions(self, state: EpisodeState) -> tuple[str, ...]:
        return tuple(
            transition.action
            for transition in self._bundle.procedure.transitions
            if transition.from_state == state.procedure_state
        )

    def apply_action(
        self,
        state: EpisodeState,
        action: EnvironmentAction,
    ) -> EpisodeUpdate:
        return self._implementation.apply_action(state, action)

    def verify(self, state: EpisodeState) -> VerifierOutcome:
        return self._implementation.verify(state)


class EegMarkerRecoveryModule(EegEnvironmentModule):
    """Compatibility facade for callers and frozen Ticket 01 EEG bundles."""

    @classmethod
    def from_seed(cls) -> EegMarkerRecoveryModule:
        return cls(validate_environment_bundle(load_legacy_bundle()))
