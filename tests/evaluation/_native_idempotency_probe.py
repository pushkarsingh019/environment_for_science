"""Exact-pinned probe for generated transport idempotency and hidden Context."""

# mypy: ignore-errors

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import tomllib
import verifiers.v1 as vf
from mcp.server.fastmcp import FastMCP
from science_environment_generated._private import transport_adapter
from science_environment_generated._private.transport_adapter import (
    assert_native_compatibility,
    patched_null_program,
)
from science_environment_generated.servers.apparatus import (
    ApparatusState,
    ApparatusToolset,
    finalize_incomplete,
)
from science_environment_generated.taskset import GeneratedTask
from verifiers.v1.harnesses.null.harness import (
    PROGRAM_SOURCE as PINNED_NULL_PROGRAM_SOURCE,
)
from verifiers.v1.utils.loaders import resolve_env_config

from environments.eeg import LEGACY_SCENARIO_ID


class _Copyable:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)

    def model_copy(self, *, update: dict[str, object]) -> _Copyable:
        return _Copyable(**{**self.__dict__, **update})


class _LostResponse(RuntimeError):
    pass


def _trace_for_lineage(
    state: ApparatusState,
    *,
    calls: list[tuple[str, str]],
    linked_results: list[tuple[str, dict[str, object]]],
) -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        info={},
        agent=SimpleNamespace(
            config=_Copyable(
                client="private-live-client",
                timeout=SimpleNamespace(rollout=900),
            ),
            runtime=_Copyable(id="private-live-runtime"),
        ),
        assistant_messages=[
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id=provider_call_id,
                        name=name,
                        arguments="{}",
                    )
                ]
            )
            for provider_call_id, name in calls
        ],
        tool_messages=[
            SimpleNamespace(
                tool_call_id=provider_call_id,
                content=json.dumps(result),
            )
            for provider_call_id, result in linked_results
        ],
    )


def _completed_state(episode_id: str) -> ApparatusState:
    state = ApparatusState(
        scenario_id=LEGACY_SCENARIO_ID,
        episode_id=episode_id,
    )
    toolset = ApparatusToolset(vf.SharedToolsetConfig())
    toolset._inert_state = state
    for index, action in enumerate(
        ("inspect_onset_route", "repair_refractory_route", "present_test_flash"),
        start=1,
    ):
        toolset._invoke(action, {}, SimpleNamespace(request_id=1_001_000 + index))
    assert state.terminal is True
    return state


async def _terminal_error(trace: SimpleNamespace) -> str | None:
    try:
        await GeneratedTask.terminal(None, trace)  # type: ignore[arg-type]
    except RuntimeError as error:
        return str(error)
    return None


async def _probe_transport_program() -> dict[str, object]:
    assert_native_compatibility(PINNED_NULL_PROGRAM_SOURCE)
    patched = patched_null_program(PINNED_NULL_PROGRAM_SOURCE)
    namespace: dict[str, object] = {"__name__": "transport_probe"}
    exec(compile(patched, "generated-null-program.py", "exec"), namespace)

    observed_ids: list[int] = []
    attempt = 0

    class _Session:
        def __init__(self) -> None:
            # The exact pinned ClientSession has consumed request 0 for initialize.
            self._request_id = 1

        async def call_tool(self, _name: str, _arguments: dict[str, object]):
            nonlocal attempt
            observed_ids.append(self._request_id)
            self._request_id += 1
            attempt += 1
            if attempt == 1:
                raise _LostResponse("synthetic response loss after dispatch")
            return SimpleNamespace(content=[], isError=False)

    @asynccontextmanager
    async def fake_session(_spec: dict[str, object]):
        yield _Session()

    async def retry_once(call):
        try:
            return await call()
        except _LostResponse:
            return await call()

    namespace["mcp_session"] = fake_session
    namespace["with_retry"] = retry_once
    call_mcp = namespace["call_mcp"]
    assert callable(call_mcp)
    servers = {"apparatus": {"url": "unused"}}
    dispatch = {"inspect_onset_route": ("apparatus", "inspect_onset_route")}
    await call_mcp(servers, dispatch, "inspect_onset_route", {})
    await call_mcp(servers, dispatch, "inspect_onset_route", {})
    return {
        "observed_request_ids": observed_ids,
        "retry_reused_request_id": observed_ids[0] == observed_ids[1],
        "next_logical_call_is_unique": observed_ids[2] != observed_ids[1],
    }


async def _main() -> None:
    config_document = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    resolved = resolve_env_config(config_document["env"])
    assert resolved.agent.timeout.rollout == 900
    assert resolved.agent.max_turns == 65
    assert resolved.agent.harness is not None
    assert resolved.agent.harness.id == "science-environment-generated"

    state = ApparatusState(
        scenario_id=LEGACY_SCENARIO_ID,
        episode_id="exact-native-episode",
    )
    toolset = ApparatusToolset(vf.SharedToolsetConfig())
    toolset._inert_state = state
    context = SimpleNamespace(request_id=1_000_001)
    first = toolset._invoke("inspect_onset_route", {}, context)
    replayed = toolset._invoke("inspect_onset_route", {}, context)

    mcp = FastMCP("generated-hidden-context-probe")
    toolset.register(mcp)
    schemas = {tool.name: tool.inputSchema for tool in await mcp.list_tools()}
    assert "inspect_onset_route" in schemas
    assert "context" not in schemas["inspect_onset_route"].get("properties", {})

    conflicting = toolset._invoke("repair_refractory_route", {}, context)
    conflict_code = state.adapter_error
    assert conflict_code == "adapter.transport_request_conflict"
    trace = SimpleNamespace(
        state=state,
        info={},
        agent=SimpleNamespace(
            config=_Copyable(
                client="private-live-client",
                timeout=SimpleNamespace(rollout=900),
            ),
            runtime=_Copyable(id="private-live-runtime"),
        ),
    )
    conflict_failed_unscored = False
    try:
        await GeneratedTask.terminal(None, trace)  # type: ignore[arg-type]
    except RuntimeError as error:
        conflict_failed_unscored = str(error) == conflict_code
    assert "science_environment_runtime" not in trace.info

    rejected_state = ApparatusState(
        scenario_id=LEGACY_SCENARIO_ID,
        episode_id="rejected-lineage-episode",
    )
    rejected_toolset = ApparatusToolset(vf.SharedToolsetConfig())
    rejected_toolset._inert_state = rejected_state
    terminal_result = rejected_toolset._invoke(
        "present_test_flash",
        {},
        SimpleNamespace(request_id=1_000_009),
    )
    assert rejected_state.terminal is True
    # Exercise the rejected-execution lineage branch directly. Pinned Verifiers
    # would stop after the preceding awaiting-verification action, so reopen only
    # this exact probe state before replaying the product transition.
    rejected_state.terminal = False
    rejected_state.terminal_reason = None
    rejected_result = rejected_toolset._invoke(
        "repair_refractory_route",
        {},
        SimpleNamespace(request_id=1_000_010),
    )
    assert rejected_result == {
        "status": "error",
        "error_code": "tool.action_rejected",
    }
    finalize_incomplete(rejected_state, "turn_budget_exhausted")
    rejected_trace = _trace_for_lineage(
        rejected_state,
        calls=[
            ("provider-terminal", "present_test_flash"),
            ("provider-rejected", "repair_refractory_route"),
        ],
        linked_results=[
            ("provider-terminal", terminal_result),
            ("provider-rejected", rejected_result),
        ],
    )
    assert await GeneratedTask.terminal(None, rejected_trace) is True  # type: ignore[arg-type]

    unknown_state = ApparatusState(
        scenario_id=LEGACY_SCENARIO_ID,
        episode_id="unknown-lineage-episode",
    )
    finalize_incomplete(unknown_state, "turn_budget_exhausted")
    unknown_trace = _trace_for_lineage(
        unknown_state,
        calls=[("provider-unknown", "not_a_declared_action")],
        linked_results=[
            (
                "provider-unknown",
                {"status": "error", "error_code": "tool.unknown_action"},
            )
        ],
    )
    assert await GeneratedTask.terminal(None, unknown_trace) is True  # type: ignore[arg-type]

    completed_calls = [
        ("provider-complete-1", "inspect_onset_route"),
        ("provider-complete-2", "repair_refractory_route"),
        ("provider-complete-3", "present_test_flash"),
    ]
    missing_state = _completed_state("missing-result-episode")
    missing_trace = _trace_for_lineage(
        missing_state,
        calls=completed_calls,
        linked_results=[
            ("provider-complete-2", missing_state.tool_executions[1]["result"]),
        ],
    )
    missing_result_error = await _terminal_error(missing_trace)

    malformed_state = _completed_state("malformed-result-episode")
    malformed_trace = _trace_for_lineage(
        malformed_state,
        calls=completed_calls,
        linked_results=[
            ("provider-complete-1", malformed_state.tool_executions[0]["result"]),
            ("provider-complete-2", malformed_state.tool_executions[1]["result"]),
        ],
    )
    malformed_trace.tool_messages[0].content = "not-json"
    malformed_result_error = await _terminal_error(malformed_trace)

    drift_state = _completed_state("profile-drift-episode")
    drift_trace = _trace_for_lineage(
        drift_state,
        calls=completed_calls,
        linked_results=[
            ("provider-complete-1", drift_state.tool_executions[0]["result"]),
            ("provider-complete-2", drift_state.tool_executions[1]["result"]),
        ],
    )
    drift_trace.agent.config.timeout.rollout = 600
    profile_drift_error = await _terminal_error(drift_trace)

    drift_rejected = False
    try:
        patched_null_program(PINNED_NULL_PROGRAM_SOURCE + "\n# drift")
    except RuntimeError:
        drift_rejected = True

    copied_seam_drift_rejected = False
    original_getsource = transport_adapter.inspect.getsource
    transport_adapter.inspect.getsource = lambda obj: original_getsource(obj) + "\n# drift"
    try:
        assert_native_compatibility(PINNED_NULL_PROGRAM_SOURCE)
    except RuntimeError:
        copied_seam_drift_rejected = True
    finally:
        transport_adapter.inspect.getsource = original_getsource

    transport = await _probe_transport_program()
    result = {
        "config": {
            "max_turns": resolved.agent.max_turns,
            "rollout_timeout": resolved.agent.timeout.rollout,
            "harness_id": resolved.agent.harness.id,
        },
        "first_result": first,
        "replayed_result": replayed,
        "cached_exactly": first == replayed,
        "accepted_action_count": len(state.accepted_actions),
        "tool_execution_count": len(state.tool_executions),
        "cache_entry_count": len(state.transport_cache),
        "cache_hit": state.tool_executions[0]["cache_hit"],
        "retry_count": state.tool_executions[0]["retry_count"],
        "execution_id": state.tool_executions[0]["execution_id"],
        "conflicting_result": conflicting,
        "conflict_code": conflict_code,
        "conflict_failed_unscored": conflict_failed_unscored,
        "rejected_lineage": rejected_trace.info["science_environment_runtime"][
            "tool_lineage"
        ][1],
        "unknown_lineage": unknown_trace.info["science_environment_runtime"][
            "tool_lineage"
        ][0],
        "missing_result_error": missing_result_error,
        "malformed_result_error": malformed_result_error,
        "profile_drift_error": profile_drift_error,
        "drift_rejected": drift_rejected,
        "copied_seam_drift_rejected": copied_seam_drift_rejected,
        "hidden_context": "context"
        not in schemas["inspect_onset_route"].get("properties", {}),
        "transport": transport,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    asyncio.run(_main())
