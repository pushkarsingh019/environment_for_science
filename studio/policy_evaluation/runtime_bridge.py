"""Stateless replay bridge from evaluation callers to the product Runtime."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from studio.bundle import EnvironmentBundle
from studio.registry import EnvironmentRegistry
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    IncompleteTerminationReason,
    PolicyAgentIdentity,
    RunSnapshot,
    RuntimeContractError,
)


class CanonicalCallConflictError(RuntimeContractError):
    """A canonical call identity was reused for different action material."""


class CanonicalActionExecution(BaseModel):
    """Episode-scoped idempotency ledger entry for one accepted Runtime action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(pattern=r"^episode-call-[0-9]{6}$")
    ordinal: int = Field(ge=1)
    execution_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action: EnvironmentAction
    observation: dict[str, Any]
    resulting_status: Literal["active", "awaiting_verification"]
    resulting_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cache_hit: bool = False
    retry_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_ordinal_identity(self) -> CanonicalActionExecution:
        if self.call_id != f"episode-call-{self.ordinal:06d}":
            raise ValueError("canonical call ID does not match its ordinal")
        if self.cache_hit != (self.retry_count > 0):
            raise ValueError("cache-hit evidence must match the retry count")
        return self


class ReplayableRuntimeState(BaseModel):
    """Public evidence sufficient to reconstruct one evaluation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_id: str = Field(min_length=1)
    scenario_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    episode_id: str = Field(min_length=1)
    policy_agent: PolicyAgentIdentity
    accepted_actions: tuple[EnvironmentAction, ...]
    executions: tuple[CanonicalActionExecution, ...] = ()
    snapshot: RunSnapshot

    @model_validator(mode="after")
    def require_execution_ledger_consistency(self) -> ReplayableRuntimeState:
        if self.accepted_actions != tuple(execution.action for execution in self.executions):
            raise ValueError("accepted actions must match the canonical execution ledger")
        ordinals = tuple(execution.ordinal for execution in self.executions)
        if ordinals != tuple(sorted(ordinals)) or len(ordinals) != len(set(ordinals)):
            raise ValueError("canonical execution ordinals must be unique and ordered")
        return self


class IdempotentActionResult(BaseModel):
    """One new or cached application result returned to the model runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: ReplayableRuntimeState
    call_id: str = Field(pattern=r"^episode-call-[0-9]{6}$")
    ordinal: int = Field(ge=1)
    execution_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observation: dict[str, Any]
    resulting_status: Literal["active", "awaiting_verification"]
    cache_hit: bool
    retry_count: int = Field(ge=0)


class EvaluationRuntimeBridge:
    """Reconstruct evaluation calls through the registered product Runtime."""

    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)

    def start(
        self,
        scenario_id: str,
        policy: PolicyAgentIdentity,
    ) -> ReplayableRuntimeState:
        """Start one scenario and retain only its public replay evidence."""
        snapshot = self._runtime().start(
            scenario_id,
            policy.model_copy(deep=True),
        )
        return self._state(snapshot, (), (), episode_id=snapshot.run_id)

    def apply(
        self,
        state: ReplayableRuntimeState,
        action: EnvironmentAction,
    ) -> ReplayableRuntimeState:
        """Rebuild the attempt, apply one accepted action, and discard the Runtime."""
        ordinal = (
            max(
                (execution.ordinal for execution in state.executions),
                default=0,
            )
            + 1
        )
        return self.apply_idempotent(
            state,
            call_id=f"episode-call-{ordinal:06d}",
            ordinal=ordinal,
            action=action,
        ).state

    def apply_idempotent(
        self,
        state: ReplayableRuntimeState,
        *,
        call_id: str,
        ordinal: int,
        action: EnvironmentAction,
    ) -> IdempotentActionResult:
        """Apply once per canonical ID; identical retries return cached evidence."""
        expected_call_id = f"episode-call-{ordinal:06d}"
        if call_id != expected_call_id:
            raise CanonicalCallConflictError("canonical call identity does not match its ordinal")
        runtime, current = self._reconstruct(state)
        for index, execution in enumerate(state.executions):
            if execution.call_id != call_id and execution.ordinal != ordinal:
                continue
            if (
                execution.call_id != call_id
                or execution.ordinal != ordinal
                or execution.action != action
            ):
                raise CanonicalCallConflictError(
                    "conflicting reuse of an episode-scoped canonical call"
                )
            cached = CanonicalActionExecution(
                **execution.model_dump(
                    exclude={"cache_hit", "retry_count"},
                ),
                cache_hit=True,
                retry_count=execution.retry_count + 1,
            )
            executions = (
                *state.executions[:index],
                cached,
                *state.executions[index + 1 :],
            )
            cached_state = ReplayableRuntimeState(
                **state.model_dump(exclude={"executions"}),
                executions=executions,
            )
            return IdempotentActionResult(
                state=cached_state,
                call_id=cached.call_id,
                ordinal=cached.ordinal,
                execution_id=cached.execution_id,
                observation=deepcopy(cached.observation),
                resulting_status=cached.resulting_status,
                cache_hit=True,
                retry_count=cached.retry_count,
            )

        accepted_action = action.model_copy(deep=True)
        updated = runtime.apply_action(
            current.run_id,
            accepted_action,
        )
        if updated.status == "completed":
            raise RuntimeContractError("an action cannot directly complete a Runtime run")
        execution = CanonicalActionExecution(
            call_id=call_id,
            ordinal=ordinal,
            execution_id=_execution_id(
                state=state,
                call_id=call_id,
                ordinal=ordinal,
                action=accepted_action,
            ),
            action=accepted_action,
            observation=deepcopy(updated.observation),
            resulting_status=updated.status,
            resulting_trace_digest=updated.trace_digest,
        )
        updated_state = self._state(
            updated,
            (*state.accepted_actions, accepted_action),
            (*state.executions, execution),
            episode_id=state.episode_id,
        )
        return IdempotentActionResult(
            state=updated_state,
            call_id=call_id,
            ordinal=ordinal,
            execution_id=execution.execution_id,
            observation=deepcopy(execution.observation),
            resulting_status=execution.resulting_status,
            cache_hit=False,
            retry_count=0,
        )

    def finalize(self, state: ReplayableRuntimeState) -> RunSnapshot:
        """Rebuild and score one attempt through the apparatus verifier."""
        runtime, current = self._reconstruct(state)
        return runtime.verify(current.run_id).model_copy(deep=True)

    def finalize_incomplete(
        self,
        state: ReplayableRuntimeState,
        *,
        termination_reason: IncompleteTerminationReason,
    ) -> RunSnapshot:
        """Rebuild and canonically score one bounded, nonterminal attempt."""
        runtime, current = self._reconstruct(state)
        return runtime.finalize_incomplete(
            current.run_id,
            termination_reason=termination_reason,
        ).model_copy(deep=True)

    def _state(
        self,
        snapshot: RunSnapshot,
        accepted_actions: tuple[EnvironmentAction, ...],
        executions: tuple[CanonicalActionExecution, ...],
        *,
        episode_id: str,
    ) -> ReplayableRuntimeState:
        return ReplayableRuntimeState(
            bundle_id=self._bundle.bundle_id,
            bundle_revision=self._bundle.bundle_revision,
            revision_digest=snapshot.revision_digest,
            scenario_id=snapshot.scenario_id,
            scenario_digest=snapshot.scenario_digest,
            episode_id=episode_id,
            policy_agent=snapshot.policy_agent.model_copy(deep=True),
            accepted_actions=tuple(action.model_copy(deep=True) for action in accepted_actions),
            executions=tuple(execution.model_copy(deep=True) for execution in executions),
            snapshot=snapshot.model_copy(deep=True),
        )

    def _reconstruct(
        self,
        state: ReplayableRuntimeState,
    ) -> tuple[EnvironmentRuntime, RunSnapshot]:
        if (
            state.bundle_id != self._bundle.bundle_id
            or state.bundle_revision != self._bundle.bundle_revision
        ):
            raise RuntimeContractError("replay state belongs to another Environment bundle")
        runtime = self._runtime()
        current = runtime.start(
            state.scenario_id,
            state.policy_agent.model_copy(deep=True),
        )
        for accepted_action, execution in zip(
            state.accepted_actions,
            state.executions,
        ):
            if execution.execution_id != _execution_id(
                state=state,
                call_id=execution.call_id,
                ordinal=execution.ordinal,
                action=accepted_action,
            ):
                raise RuntimeContractError(
                    "canonical execution identity does not match replay evidence"
                )
            current = runtime.apply_action(
                current.run_id,
                accepted_action.model_copy(deep=True),
            )
            if (
                current.observation != execution.observation
                or current.status != execution.resulting_status
                or current.trace_digest != execution.resulting_trace_digest
            ):
                raise RuntimeContractError(
                    "canonical execution ledger does not match Runtime replay"
                )
        if not self._same_public_attempt(state, current):
            raise RuntimeContractError(
                "replay state does not match its reconstructed public evidence"
            )
        return runtime, current

    @staticmethod
    def _same_public_attempt(
        state: ReplayableRuntimeState,
        reconstructed: RunSnapshot,
    ) -> bool:
        supplied = state.snapshot
        return (
            state.revision_digest == reconstructed.revision_digest
            and state.scenario_digest == reconstructed.scenario_digest
            and state.policy_agent == reconstructed.policy_agent
            and supplied.scenario_id == reconstructed.scenario_id
            and supplied.revision_digest == reconstructed.revision_digest
            and supplied.scenario_digest == reconstructed.scenario_digest
            and supplied.policy_agent == reconstructed.policy_agent
            and supplied.status == reconstructed.status
            and supplied.observation == reconstructed.observation
            and supplied.permitted_actions == reconstructed.permitted_actions
            and supplied.trace == reconstructed.trace
            and supplied.trace_digest == reconstructed.trace_digest
            and supplied.verifier_result == reconstructed.verifier_result
            and supplied.result_digest == reconstructed.result_digest
            and supplied.trace_header == reconstructed.trace_header
        )

    def _runtime(self) -> EnvironmentRuntime:
        registry = EnvironmentRegistry.from_seeded_environments()
        return EnvironmentRuntime(registry.module_for_bundle(self._bundle.model_copy(deep=True)))


def _execution_id(
    *,
    state: ReplayableRuntimeState,
    call_id: str,
    ordinal: int,
    action: EnvironmentAction,
) -> str:
    document = {
        "episode_id": state.episode_id,
        "scenario_digest": state.scenario_digest,
        "policy_agent_id": state.policy_agent.id,
        "call_id": call_id,
        "ordinal": ordinal,
        "action": action.model_dump(mode="json"),
    }
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


__all__ = [
    "CanonicalActionExecution",
    "CanonicalCallConflictError",
    "EvaluationRuntimeBridge",
    "IdempotentActionResult",
    "ReplayableRuntimeState",
]
