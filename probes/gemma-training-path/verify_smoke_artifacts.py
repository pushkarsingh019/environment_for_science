"""Fail closed unless the bounded GPU smoke produced every required artifact."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from safetensors import safe_open


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-traces", type=Path, required=True)
    parser.add_argument("--final-traces", type=Path, required=True)
    parser.add_argument("--baseline-model")
    parser.add_argument("--final-model", default="proof-final")
    parser.add_argument("--expected-eval-episodes", type=int, default=4)
    parser.add_argument("--expected-eval-split", default="eval")
    parser.add_argument("--expected-training-split", default="train")
    parser.add_argument(
        "--expected-scenario-id",
        action="append",
        dest="expected_scenario_ids",
    )
    parser.add_argument("--product-acceptance-root", type=Path)
    return parser.parse_args()


def tensors(path: Path) -> dict:
    with safe_open(path, framework="pt", device="cpu") as handle:
        return {key: handle.get_tensor(key) for key in handle.keys()}  # noqa: SIM118


def inspect_eval(
    path: Path,
    expected_model: str | None,
    expected_episodes: int,
    *,
    expected_split: str = "eval",
    expected_scenario_ids: set[str] | None = None,
) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == expected_episodes, (
        f"expected {expected_episodes} episodes in {path}, found {len(rows)}"
    )
    tool_loops = 0
    rewards: list[float] = []
    scenarios: Counter[str] = Counter()
    for episode in rows:
        assert episode["ok"], f"failed episode in {path}: {episode.get('errors')}"
        assert episode["task"]["data"]["split"] == expected_split
        scenarios[episode["task"]["data"]["name"]] += 1
        assert len(episode["traces"]) == 1, f"unexpected trace count in {path}"
        for trace in episode["traces"]:
            assert trace["ok"], f"failed trace in {path}: {trace.get('errors')}"
            roles = [node["message"]["role"] for node in trace["nodes"]]
            if "tool" in roles and roles.count("assistant") >= 2:
                tool_loops += 1
            calls = trace["calls"]
            assert calls, f"model-call-free trace in {path}"
            if expected_model is not None:
                assert all(call["model"] == expected_model for call in calls)
            rewards.append(
                sum(
                    reward["score"] * reward["weight"]
                    for reward in trace["rewards"].values()
                    if reward is not None
                )
            )
    assert tool_loops == len(rows), (
        f"only {tool_loops}/{len(rows)} episodes completed a tool loop in {path}"
    )
    expected_ids = expected_scenario_ids or {"heldout-00", "heldout-01"}
    assert set(scenarios) == expected_ids, scenarios
    return {
        "episodes": len(rows),
        "tool_loops": tool_loops,
        "scenarios": dict(sorted(scenarios.items())),
        "mean_reward": sum(rewards) / len(rewards),
    }


def inspect_training(path: Path, expected_split: str = "train") -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == 8, (
        f"expected 8 effective training episodes in {path}, found {len(rows)}"
    )
    jitter_scores: list[float] = []
    sampled_tokens = 0
    tool_loops = 0
    for episode in rows:
        assert episode["ok"], f"failed training episode in {path}"
        assert episode["task"]["data"]["split"] == expected_split
        assert len(episode["traces"]) == 1
        trace = episode["traces"][0]
        assert trace["ok"], f"failed training trace in {path}"
        roles = [node["message"]["role"] for node in trace["nodes"]]
        tool_loops += int("tool" in roles and roles.count("assistant") >= 2)
        for node in trace["nodes"]:
            assert len(node["token_ids"]) == len(node["mask"])
            assert len(node["logprobs"]) == sum(node["mask"])
            sampled_tokens += len(node["logprobs"])
        jitter = trace["rewards"]["mechanical_jitter"]
        assert jitter["weight"] == 0.001
        jitter_scores.append(jitter["score"])
    assert tool_loops == len(rows), (
        f"only {tool_loops}/{len(rows)} training episodes completed a tool loop"
    )
    assert len(set(jitter_scores)) > 1, "training group has no reward variation"
    assert sampled_tokens > 0, "training traces contain no sampled tokens"
    return {
        "episodes": len(rows),
        "tool_loops": tool_loops,
        "sampled_tokens": sampled_tokens,
        "distinct_jitter_scores": len(set(jitter_scores)),
    }


def main() -> None:
    args = parse_args()
    startup = args.run_dir / "broadcasts" / "step_0"
    final = args.run_dir / "broadcasts" / "step_1"
    checkpoint = args.run_dir / "checkpoints" / "step_1" / "trainer"
    training_traces = (
        args.run_dir / "rollouts" / "step_1" / "train" / "effective" / "traces.jsonl"
    )

    for directory in (startup, final, checkpoint):
        assert directory.is_dir(), f"missing {directory}"
    for directory in (startup, final):
        assert (directory / "STABLE").is_file(), f"unstable broadcast {directory}"
        assert (directory / "adapter_config.json").is_file()
        assert (directory / "adapter_model.safetensors").is_file()
    assert any(checkpoint.rglob("*")), f"empty DCP checkpoint {checkpoint}"

    initial_tensors = tensors(startup / "adapter_model.safetensors")
    final_tensors = tensors(final / "adapter_model.safetensors")
    assert initial_tensors.keys() == final_tensors.keys()
    assert initial_tensors, "adapter contains no tensors"
    bad_prefixes = [
        key
        for key in final_tensors
        if not key.startswith("model.language_model.layers.")
    ]
    assert not bad_prefixes, f"non-language LoRA tensors: {bad_prefixes[:5]}"
    changed = [
        key
        for key in initial_tensors
        if not initial_tensors[key].equal(final_tensors[key])
    ]
    assert changed, "optimizer step did not change any adapter tensor"

    adapter_config = json.loads((final / "adapter_config.json").read_text())
    expected_targets = {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    }
    actual_targets = set(adapter_config["target_modules"])
    assert actual_targets and actual_targets <= expected_targets
    assert "linear" not in actual_targets

    expected_scenario_ids = (
        set(args.expected_scenario_ids)
        if args.expected_scenario_ids is not None
        else None
    )
    baseline = inspect_eval(
        args.baseline_traces,
        expected_model=args.baseline_model,
        expected_episodes=args.expected_eval_episodes,
        expected_split=args.expected_eval_split,
        expected_scenario_ids=expected_scenario_ids,
    )
    reloaded = inspect_eval(
        args.final_traces,
        expected_model=args.final_model,
        expected_episodes=args.expected_eval_episodes,
        expected_split=args.expected_eval_split,
        expected_scenario_ids=expected_scenario_ids,
    )
    assert baseline["scenarios"] == reloaded["scenarios"]
    report = {
        "adapter_tensors": len(final_tensors),
        "changed_adapter_tensors": len(changed),
        "checkpoint_files": sum(path.is_file() for path in checkpoint.rglob("*")),
        "training": inspect_training(
            training_traces,
            expected_split=args.expected_training_split,
        ),
        "baseline": baseline,
        "reloaded": reloaded,
    }
    if args.product_acceptance_root is not None:
        from studio.training_acceptance import AcceptanceArtifactVerifier

        evidence = AcceptanceArtifactVerifier().verify(
            args.product_acceptance_root
        )
        report["product_acceptance"] = evidence.model_dump(mode="json")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
