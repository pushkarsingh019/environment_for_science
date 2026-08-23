"""Focused exact-Verifiers probe for generated native budget semantics."""

# mypy: ignore-errors

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import verifiers.v1 as vf
from science_environment_generated.servers.apparatus import (
    ApparatusState,
    ApparatusToolset,
)
from science_environment_generated.taskset import GeneratedTask
from verifiers.v1.session import RolloutLimits

from environments.eeg import LEGACY_SCENARIO_ID, load_legacy_bundle
from studio.bundle import validate_environment_bundle
from studio.registry import EnvironmentRegistry
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    PolicyAgentIdentity,
)

_ACTION = "inspect_onset_route"
_MODEL_ID = "google/gemma-4-E4B-it"


class _Copyable:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)

    def model_copy(self, *, update: dict[str, object]) -> _Copyable:
        return _Copyable(**{**self.__dict__, **update})


class _Trace:
    def __init__(
        self,
        state: ApparatusState,
        *,
        calls: list[tuple[str, dict[str, object]]],
        turns: int,
        final_batch_size: int = 1,
        linked_execution_count: int = 0,
    ) -> None:
        self.state = state
        self.num_turns = turns
        self.info: dict[str, object] = {}
        self.agent = SimpleNamespace(
            config=_Copyable(
                client="private-live-client",
                timeout=SimpleNamespace(rollout=900),
            ),
            runtime=_Copyable(id="private-live-runtime"),
        )
        prefix = [
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id=f"native-call-{index + 1}",
                        name=name,
                        arguments=json.dumps(arguments),
                    )
                ]
            )
            for index, (name, arguments) in enumerate(calls[:-final_batch_size])
        ]
        final_start = len(calls) - final_batch_size
        self.assistant_messages = [
            *prefix,
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id=f"native-call-{index + 1}",
                        name=name,
                        arguments=json.dumps(arguments),
                    )
                    for index, (name, arguments) in enumerate(
                        calls[final_start:], start=final_start
                    )
                ]
            ),
        ]
        self.tool_messages = [
            SimpleNamespace(
                tool_call_id=f"native-call-{index + 1}",
                content=json.dumps(state.tool_executions[index]["result"]),
            )
            for index in range(linked_execution_count)
        ]


def _state_after(action_count: int) -> ApparatusState:
    bundle = validate_environment_bundle(load_legacy_bundle())
    runtime = EnvironmentRuntime(
        EnvironmentRegistry.from_seeded_environments().module_for_bundle(bundle)
    )
    snapshot = runtime.start(
        LEGACY_SCENARIO_ID,
        PolicyAgentIdentity(
            id=f"local-openai-compatible:{_MODEL_ID}",
            name=_MODEL_ID,
        ),
    )
    accepted_actions = []
    accepted_results = []
    tool_executions = []
    for _ in range(action_count):
        action = EnvironmentAction(type=_ACTION, arguments={})
        snapshot = runtime.apply_action(snapshot.run_id, action)
        accepted_actions.append(action.model_dump(mode="json"))
        result = {
            "status": "ok",
            "observation": snapshot.observation,
        }
        accepted_results.append(result)
        tool_executions.append(
            {
                "execution_id": f"execution-probe-{len(tool_executions) + 1}",
                "cache_hit": False,
                "retry_count": 0,
                "terminal_after_execution": False,
                "accepted": True,
                "action": action.model_dump(mode="json"),
                "result": result,
            }
        )
    return ApparatusState(
        scenario_id=LEGACY_SCENARIO_ID,
        episode_id="native-budget-probe",
        accepted_actions=accepted_actions,
        accepted_tool_results=accepted_results,
        tool_executions=tool_executions,
        runtime_snapshot=snapshot.model_dump(mode="json"),
        runtime_trace_digest=snapshot.trace_digest,
        runtime_result_digest=snapshot.result_digest,
    )


async def _turn_budget() -> dict[str, object]:
    state = _state_after(63)
    calls = [(_ACTION, {}) for _ in range(63)]
    calls.append((_ACTION, {"unexpected": True}))
    trace = _Trace(
        state,
        calls=calls,
        turns=64,
        linked_execution_count=63,
    )
    assert RolloutLimits(max_turns=65).reached(trace) is None  # type: ignore[arg-type]
    trace.num_turns = 65
    assert RolloutLimits(max_turns=65).reached(trace) == "max_turns"  # type: ignore[arg-type]
    trace.num_turns = 64
    stopped = await GeneratedTask.turn_budget(None, trace)  # type: ignore[arg-type]
    return {
        "stopped": stopped,
        "state_terminal": state.terminal,
        "runtime": trace.info["science_environment_runtime"],
    }


async def _tool_budget() -> dict[str, object]:
    state = _state_after(63)
    toolset = ApparatusToolset(vf.SharedToolsetConfig())
    toolset._inert_state = state
    boundary_result = toolset._invoke(
        _ACTION,
        {},
        SimpleNamespace(request_id=1_000_064),
    )
    # Pinned Verifiers runs the generated terminal @stop while intercepting the
    # boundary result, before its null harness can dispatch later calls from the
    # same assistant message.  Keep that 65th call in the assistant lineage but
    # deliberately do not invoke the Toolset for it.
    trace = _Trace(
        state,
        calls=[(_ACTION, {}) for _ in range(65)],
        turns=1,
        final_batch_size=2,
        linked_execution_count=63,
    )
    stopped = await GeneratedTask.terminal(None, trace)  # type: ignore[arg-type]
    return {
        "boundary_result": boundary_result,
        "stopped": stopped,
        "state_terminal": state.terminal,
        "accepted_action_count": len(state.accepted_actions),
        "runtime_execution_count": len(state.tool_executions),
        "runtime": trace.info["science_environment_runtime"],
    }


async def _main() -> None:
    mode = sys.argv[1]
    if mode == "turn":
        result = await _turn_budget()
    elif mode == "tool":
        result = await _tool_budget()
    else:
        raise ValueError("unknown probe mode")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    asyncio.run(_main())
