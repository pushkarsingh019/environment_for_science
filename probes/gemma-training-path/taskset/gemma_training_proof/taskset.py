"""Disposable, non-benchmark taskset for the Gemma training-path smoke test.

The zero-weight ``mechanical_jitter`` reward exists only to make one-step GRPO
non-degenerate even when every rollout follows the tiny task perfectly. The
training smoke config gives it a very small non-zero weight. Held-out evaluation
does not. Never use this taskset to claim model quality or scientific capability.
"""

from __future__ import annotations

import json
from typing import Literal

import verifiers.v1 as vf

from gemma_training_proof.servers.proof import ProofState, ProofToolset

_SPLITS = {
    "train": (
        (
            "train-00",
            {"amber": "TA-17", "blue": "TB-29", "green": "TG-31", "violet": "TV-43"},
        ),
        (
            "train-01",
            {"amber": "QA-05", "blue": "QB-11", "green": "QG-23", "violet": "QV-47"},
        ),
        (
            "train-02",
            {"amber": "MA-13", "blue": "MB-19", "green": "MG-37", "violet": "MV-41"},
        ),
        (
            "train-03",
            {"amber": "RA-07", "blue": "RB-17", "green": "RG-29", "violet": "RV-53"},
        ),
    ),
    "eval": (
        (
            "heldout-00",
            {"amber": "HA-59", "blue": "HB-61", "green": "HG-67", "violet": "HV-71"},
        ),
        (
            "heldout-01",
            {"amber": "ZA-73", "blue": "ZB-79", "green": "ZG-83", "violet": "ZV-89"},
        ),
    ),
}

_PROMPT = """This is a mechanical tool-loop test, not a knowledge question.
Choose one route unpredictably from amber, blue, green, or violet. Call
`proof_choose_route` exactly once with that route. Then reply with only the token
returned by the tool. Do not invent a token and do not explain the choice.
Scenario: {scenario}.
"""


class ProofData(vf.TaskData):
    split: Literal["train", "eval"]
    scenario: str
    route_tokens: dict[str, str]


class ProofTask(vf.Task[ProofData, ProofState]):
    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        trace.state.route_tokens = dict(self.data.route_tokens)

    @vf.stop
    async def bounded(self, trace: vf.Trace) -> bool:
        return trace.num_turns >= 4

    @vf.reward(weight=1.0)
    async def protocol(self, trace: vf.Trace) -> float:
        calls = [
            call
            for message in trace.assistant_messages
            for call in (message.tool_calls or [])
        ]
        if len(calls) != 1 or calls[0].name != "proof_choose_route":
            return 0.0
        try:
            arguments = json.loads(calls[0].arguments or "{}")
        except json.JSONDecodeError:
            return 0.0
        route = arguments.get("route")
        expected = self.data.route_tokens.get(route)
        if expected is None:
            return 0.0
        if len(trace.tool_messages) != 1:
            return 0.0
        tool_output = str(trace.tool_messages[0].content or "").strip()
        return float(tool_output == expected and trace.last_reply == expected)

    @vf.reward(weight=0.0)
    async def mechanical_jitter(self, trace: vf.Trace) -> float:
        """Anti-degeneracy signal for the one-step training mechanics probe only."""
        return int(trace.id[:12], 16) / float(16**12 - 1)

    @vf.metric
    async def tool_loop_complete(self, trace: vf.Trace) -> float:
        return float(bool(trace.tool_messages) and trace.num_turns >= 2)


class ProofConfig(vf.TasksetConfig):
    split: Literal["train", "eval"] = "train"


class GemmaTrainingProofTaskset(vf.Taskset[ProofTask, ProofConfig]):
    @classmethod
    def toolsets(cls, config: ProofConfig) -> list[vf.Toolset]:
        return [ProofToolset(vf.SharedToolsetConfig())]

    def load(self) -> list[ProofTask]:
        rows = _SPLITS[self.config.split]
        return [
            ProofTask(
                ProofData(
                    idx=index,
                    name=scenario,
                    split=self.config.split,
                    scenario=scenario,
                    route_tokens=dict(route_tokens),
                    prompt=_PROMPT.format(scenario=scenario),
                ),
                self.config.task,
            )
            for index, (scenario, route_tokens) in enumerate(rows)
        ]
