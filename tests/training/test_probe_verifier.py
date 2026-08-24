"""Disposable probe accepts the formal Ticket 10 development identities explicitly."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _probe(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    safetensors = ModuleType("safetensors")
    safetensors.safe_open = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "safetensors", safetensors)
    path = Path("probes/gemma-training-path/verify_smoke_artifacts.py").resolve()
    spec = importlib.util.spec_from_file_location("gemma_probe_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(scenario_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "task": {"data": {"name": scenario_id, "split": "development"}},
        "traces": [
            {
                "ok": True,
                "errors": [],
                "nodes": [
                    {"message": {"role": "assistant"}},
                    {"message": {"role": "tool"}},
                    {"message": {"role": "assistant"}},
                ],
                "calls": [{"model": "proof-final"}],
                "rewards": {"reward": {"score": 0.5, "weight": 1.0}},
            }
        ],
    }


def test_probe_requires_explicit_formal_split_and_scenario_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _probe(monkeypatch)
    scenarios = {"eeg-0ba779dfa73fc9db", "eeg-0553f1f24a3a64fa"}
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        "".join(json.dumps(_row(scenario)) + "\n" for scenario in sorted(scenarios))
    )

    report = probe.inspect_eval(
        traces,
        expected_model="proof-final",
        expected_episodes=2,
        expected_split="development",
        expected_scenario_ids=scenarios,
    )

    assert report["episodes"] == 2
    assert set(report["scenarios"]) == scenarios
    with pytest.raises(AssertionError):
        probe.inspect_eval(
            traces,
            expected_model="proof-final",
            expected_episodes=2,
        )
