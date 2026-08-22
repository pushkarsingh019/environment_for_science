"""Composition root for installed Environment adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from environments.eeg.curriculum import load_training_scenario_set
from environments.eeg.presentation import (
    EegOnsetRouteVisualization,
    EegPreflightVisualization,
)
from environments.eeg.runtime import EegEnvironmentModule
from environments.mesoscope import load_seeded_bundle as load_mesoscope_bundle
from environments.mesoscope.presentation import MesoscopeHandoffVisualization
from environments.mesoscope.runtime import MesoscopeEnvironmentModule
from studio.bundle import EnvironmentBundle, validate_environment_bundle
from studio.runtime import EnvironmentModule

EnvironmentKind = Literal["eeg", "mesoscope"]
EnvironmentSourceKind = Literal["editable_draft", "sealed_seed"]
EnvironmentVisualization = Union[
    EegOnsetRouteVisualization,
    EegPreflightVisualization,
    MesoscopeHandoffVisualization,
]

_COMPATIBLE_EEG_BUNDLES = {
    ("eeg-onset-marker-recovery", "eeg-marker-generator-1"),
    ("eeg-onset-marker-recovery", "eeg-preflight-generator-1"),
}


class EnvironmentRegistryError(ValueError):
    """Raised when an Environment is absent or registered inconsistently."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConsoleScenarioChoice(_FrozenModel):
    """Neutral scenario identity safe for the Scientist Console catalog."""

    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    stage: str = Field(min_length=1)


class EnvironmentCatalogEntry(_FrozenModel):
    """Compact navigation metadata for one installed Environment."""

    environment_id: str = Field(min_length=1)
    environment_kind: EnvironmentKind
    name: str = Field(min_length=1)
    navigation_label: str = Field(min_length=1)
    navigation_summary: str = Field(min_length=1)
    source_kind: EnvironmentSourceKind


@dataclass(frozen=True)
class _Registration:
    catalog: EnvironmentCatalogEntry
    bundle: EnvironmentBundle
    seeded_scenarios: tuple[ConsoleScenarioChoice, ...]
    module_factory: Callable[[EnvironmentBundle], EnvironmentModule]


class EnvironmentRegistry:
    """Resolve bundles to apparatus modules only at the composition boundary."""

    def __init__(self, registrations: tuple[_Registration, ...]) -> None:
        identities = [item.catalog.environment_id for item in registrations]
        if not registrations or len(identities) != len(set(identities)):
            raise EnvironmentRegistryError(
                "Environment registrations must have unique identities"
            )
        self._registrations = {
            item.catalog.environment_id: item for item in registrations
        }
        self._catalog_order = tuple(identities)

    @classmethod
    def from_seeded_environments(cls) -> EnvironmentRegistry:
        """Install the reviewed EEG and sealed mesoscope adapters."""
        training = load_training_scenario_set()
        eeg_bundle = training.environment_bundle
        eeg_choices = tuple(
            ConsoleScenarioChoice(
                scenario_id=choice.scenario_id,
                label=choice.label,
                stage=choice.stage,
            )
            for choice in training.seeded_examples
        )
        mesoscope_bundle = validate_environment_bundle(load_mesoscope_bundle())
        mesoscope_choices: list[ConsoleScenarioChoice] = []
        for scenario in mesoscope_bundle.scenarios:
            extras = scenario.model_extra or {}
            label = extras.get("console_label")
            stage = extras.get("console_stage")
            if not isinstance(label, str) or not isinstance(stage, str):
                raise EnvironmentRegistryError(
                    "the mesoscope console catalog is incomplete"
                )
            mesoscope_choices.append(
                ConsoleScenarioChoice(
                    scenario_id=scenario.id,
                    label=label,
                    stage=stage,
                )
            )

        return cls(
            (
                _Registration(
                    catalog=EnvironmentCatalogEntry(
                        environment_id=eeg_bundle.bundle_id,
                        environment_kind="eeg",
                        name=eeg_bundle.title,
                        navigation_label="EEG",
                        navigation_summary="Authoring and diagnostic recovery",
                        source_kind="editable_draft",
                    ),
                    bundle=eeg_bundle.model_copy(deep=True),
                    seeded_scenarios=eeg_choices,
                    module_factory=EegEnvironmentModule,
                ),
                _Registration(
                    catalog=EnvironmentCatalogEntry(
                        environment_id=mesoscope_bundle.bundle_id,
                        environment_kind="mesoscope",
                        name=mesoscope_bundle.title,
                        navigation_label="Mesoscope",
                        navigation_summary="Sealed synthetic handoff",
                        source_kind="sealed_seed",
                    ),
                    bundle=mesoscope_bundle.model_copy(deep=True),
                    seeded_scenarios=tuple(mesoscope_choices),
                    module_factory=MesoscopeEnvironmentModule,
                ),
            )
        )

    @property
    def catalog(self) -> tuple[EnvironmentCatalogEntry, ...]:
        return tuple(
            self._registrations[environment_id].catalog.model_copy(deep=True)
            for environment_id in self._catalog_order
        )

    def entry(self, environment_id: str) -> EnvironmentCatalogEntry:
        return self._registration(environment_id).catalog.model_copy(deep=True)

    def bundle(self, environment_id: str) -> EnvironmentBundle:
        return self._registration(environment_id).bundle.model_copy(deep=True)

    def runtime_validation_bundle(self, environment_id: str) -> EnvironmentBundle:
        module = self.module_for_bundle(self.bundle(environment_id))
        return module.runtime_validation_bundle.model_copy(deep=True)

    def seeded_scenarios(
        self,
        environment_id: str,
    ) -> tuple[ConsoleScenarioChoice, ...]:
        return tuple(
            item.model_copy(deep=True)
            for item in self._registration(environment_id).seeded_scenarios
        )

    def visualization(self, environment_id: str) -> EnvironmentVisualization:
        module = self.module_for_bundle(self.bundle(environment_id))
        if isinstance(module, EegEnvironmentModule):
            return module.visualization.model_copy(deep=True)
        if isinstance(module, MesoscopeEnvironmentModule):
            return module.visualization.model_copy(deep=True)
        raise EnvironmentRegistryError("registered Environment has no presentation adapter")

    def module_for_bundle(self, bundle: EnvironmentBundle) -> EnvironmentModule:
        registration = self._registrations.get(bundle.bundle_id)
        if registration is None:
            identity = (bundle.bundle_id, bundle.generator_revision)
            if identity in _COMPATIBLE_EEG_BUNDLES:
                return EegEnvironmentModule(bundle.model_copy(deep=True))
            raise EnvironmentRegistryError(
                f"Environment bundle {bundle.bundle_id!r} is not registered"
            )
        return registration.module_factory(bundle.model_copy(deep=True))

    def _registration(self, environment_id: str) -> _Registration:
        try:
            return self._registrations[environment_id]
        except KeyError as error:
            raise EnvironmentRegistryError(
                f"unknown Environment {environment_id!r}"
            ) from error


__all__ = [
    "ConsoleScenarioChoice",
    "EnvironmentCatalogEntry",
    "EnvironmentKind",
    "EnvironmentRegistry",
    "EnvironmentRegistryError",
    "EnvironmentSourceKind",
    "EnvironmentVisualization",
]
