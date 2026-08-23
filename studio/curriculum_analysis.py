"""Immutable held-out import and paired EEG training analysis."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from environments.eeg.curriculum import CurriculumAttempt, CurriculumReport
from evaluation.eeg.attempts import open_held_out_attempt_ledger
from evaluation.eeg.curriculum import load_held_out_scenario_set
from studio.runtime import RunSnapshot

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCENARIO_ID = re.compile(r"^eeg-[0-9a-f]{16}$")


class CurriculumAnalysisError(ValueError):
    """Sanitized failure to import or compare curriculum evidence."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PairedBootstrapAnalysis(_FrozenModel):
    """Deterministic trained-minus-base success contrast."""

    analysis_version: Literal["eeg-paired-bootstrap/1"]
    seed: int
    replicates: int = Field(ge=1)
    scenario_count: int = Field(ge=2)
    base_successes: int = Field(ge=0)
    trained_successes: int = Field(ge=0)
    trained_minus_base: float = Field(ge=-1.0, le=1.0)
    confidence_level: float = Field(ge=0.95, le=0.95)
    interval_low: float = Field(ge=-1.0, le=1.0)
    interval_high: float = Field(ge=-1.0, le=1.0)
    conclusion: Literal["improved", "inconclusive", "regressed"]
    paired_outcomes_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_claim_rule(self) -> PairedBootstrapAnalysis:
        if (
            self.base_successes > self.scenario_count
            or self.trained_successes > self.scenario_count
            or self.interval_low > self.interval_high
        ):
            raise ValueError("paired bootstrap counts or interval are invalid")
        expected = (
            "improved"
            if self.trained_minus_base > 0.0 and self.interval_low > 0.0
            else (
                "regressed"
                if self.trained_minus_base < 0.0 and self.interval_high < 0.0
                else "inconclusive"
            )
        )
        if self.conclusion != expected:
            raise ValueError("paired bootstrap conclusion overstates its interval")
        return self


class HeldOutEvaluationEvidence(_FrozenModel):
    """Evaluator-owned report plus replay identities for every sealed slot."""

    evidence_version: Literal["eeg-heldout-evaluation-evidence/1"]
    model_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report: CurriculumReport
    scenario_success: dict[str, bool]
    verifier_scores: dict[str, float]
    canonical_run_ids: dict[str, str]
    runtime_trace_digests: dict[str, str]
    runtime_result_digests: dict[str, str]

    @model_validator(mode="after")
    def validate_coverage(self) -> HeldOutEvaluationEvidence:
        expected = set(load_held_out_scenario_set().scenario_ids)
        if (
            set(self.scenario_success) != expected
            or set(self.verifier_scores) != expected
            or set(self.canonical_run_ids) != expected
            or set(self.runtime_trace_digests) != expected
            or set(self.runtime_result_digests) != expected
            or any(
                _DIGEST.fullmatch(value) is None
                for value in self.runtime_trace_digests.values()
            )
            or any(
                _DIGEST.fullmatch(value) is None
                for value in self.runtime_result_digests.values()
            )
            or any(not value for value in self.canonical_run_ids.values())
            or any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0
                for value in self.verifier_scores.values()
            )
            or self.report.scenario_coverage.numerator != len(expected)
            or self.report.replay_conformance.numerator != len(expected)
        ):
            raise ValueError("held-out evidence does not cover the sealed split")
        return self


def paired_bootstrap_success(
    base: dict[str, bool],
    trained: dict[str, bool],
    *,
    seed: int = 20_260_823,
    replicates: int = 10_000,
) -> PairedBootstrapAnalysis:
    """Compare paired success outcomes without an unpaired approximation."""

    if (
        set(base) != set(trained)
        or len(base) < 2
        or any(_SCENARIO_ID.fullmatch(key) is None for key in base)
        or isinstance(seed, bool)
        or not isinstance(seed, int)
        or isinstance(replicates, bool)
        or not isinstance(replicates, int)
        or replicates < 1
        or any(type(value) is not bool for value in (*base.values(), *trained.values()))
    ):
        raise CurriculumAnalysisError("paired outcomes are incomplete or invalid")
    scenario_ids = tuple(sorted(base))
    differences = tuple(
        int(trained[scenario_id]) - int(base[scenario_id])
        for scenario_id in scenario_ids
    )
    observed = sum(differences) / len(differences)
    generator = random.Random(seed)
    bootstrap = sorted(
        sum(
            differences[generator.randrange(len(differences))]
            for _ in differences
        )
        / len(differences)
        for _ in range(replicates)
    )
    low = _quantile(bootstrap, 0.025)
    high = _quantile(bootstrap, 0.975)
    conclusion: Literal["improved", "inconclusive", "regressed"] = (
        "improved"
        if observed > 0.0 and low > 0.0
        else "regressed" if observed < 0.0 and high < 0.0 else "inconclusive"
    )
    paired_document = [
        {
            "scenario_id": scenario_id,
            "base": base[scenario_id],
            "trained": trained[scenario_id],
        }
        for scenario_id in scenario_ids
    ]
    return PairedBootstrapAnalysis(
        analysis_version="eeg-paired-bootstrap/1",
        seed=seed,
        replicates=replicates,
        scenario_count=len(differences),
        base_successes=sum(base.values()),
        trained_successes=sum(trained.values()),
        trained_minus_base=observed,
        confidence_level=0.95,
        interval_low=low,
        interval_high=high,
        conclusion=conclusion,
        paired_outcomes_digest=_digest(paired_document),
    )


def import_native_heldout_evaluation(
    *,
    traces_path: Path,
    artifact_root: Path,
    model_configuration_digest: str,
    expected_call_model: str,
) -> HeldOutEvaluationEvidence:
    """Seal native traces into the existing evaluator-owned attempt ledger."""

    if _DIGEST.fullmatch(model_configuration_digest) is None:
        raise CurriculumAnalysisError("model configuration digest is invalid")
    scenario_set = load_held_out_scenario_set()
    documents = _native_documents(traces_path)
    if len(documents) != len(scenario_set.scenario_ids):
        raise CurriculumAnalysisError("held-out native traces are incomplete")
    by_scenario: dict[str, tuple[RunSnapshot, str]] = {}
    for document in documents:
        scenario_id, snapshot, trace_digest = _native_snapshot(
            document,
            expected_call_model=expected_call_model,
        )
        if scenario_id in by_scenario:
            raise CurriculumAnalysisError("held-out native trace slot is duplicated")
        by_scenario[scenario_id] = (snapshot, trace_digest)
    if set(by_scenario) != set(scenario_set.scenario_ids):
        raise CurriculumAnalysisError("held-out native traces changed the sealed split")

    ledger = open_held_out_attempt_ledger(
        artifact_root=artifact_root,
        scenario_set=scenario_set,
        model_configuration_digest=model_configuration_digest,
        rollouts_per_scenario=1,
    )
    for scenario_id in scenario_set.scenario_ids:
        snapshot, _trace_digest = by_scenario[scenario_id]
        ledger.record(
            CurriculumAttempt(
                scenario_id=scenario_id,
                rollout_index=0,
                model_configuration_digest=model_configuration_digest,
                run=snapshot,
            )
        )
    ledger.seal()
    report = scenario_set.aggregate(ledger)
    success: dict[str, bool] = {}
    scores: dict[str, float] = {}
    result_digests: dict[str, str] = {}
    for scenario_id in scenario_set.scenario_ids:
        snapshot = by_scenario[scenario_id][0]
        result = snapshot.verifier_result
        if result is None or snapshot.result_digest is None:
            raise CurriculumAnalysisError(
                "held-out native trace has no verifier result"
            )
        success[scenario_id] = bool(result.metrics["exact_terminal_success"])
        scores[scenario_id] = float(result.metrics["reward"])
        result_digests[scenario_id] = snapshot.result_digest
    return HeldOutEvaluationEvidence(
        evidence_version="eeg-heldout-evaluation-evidence/1",
        model_configuration_digest=model_configuration_digest,
        report=report,
        scenario_success=success,
        verifier_scores=scores,
        canonical_run_ids={
            scenario_id: by_scenario[scenario_id][0].run_id
            for scenario_id in scenario_set.scenario_ids
        },
        runtime_trace_digests={
            scenario_id: by_scenario[scenario_id][1]
            for scenario_id in scenario_set.scenario_ids
        },
        runtime_result_digests=result_digests,
    )


def _native_documents(path: Path) -> list[dict[str, Any]]:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("invalid native traces")
        documents = [
            json.loads(line)
            for line in path.read_text().splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise CurriculumAnalysisError("held-out native traces could not be read") from error
    if any(not isinstance(document, dict) for document in documents):
        raise CurriculumAnalysisError("held-out native traces are malformed")
    return documents


def _native_snapshot(
    document: dict[str, Any],
    *,
    expected_call_model: str,
) -> tuple[str, RunSnapshot, str]:
    try:
        trace = document["traces"][0]
        scenario_id = document["task"]["data"]["name"]
        runtime = trace["info"]["science_environment_runtime"]
        calls = trace["calls"]
        snapshot = RunSnapshot.model_validate(runtime["completed_snapshot"])
        if (
            document["ok"] is not True
            or trace["ok"] is not True
            or trace["is_completed"] is not True
            or document["errors"]
            or trace["errors"]
            or trace["stop_condition"]
            not in {"terminal", "incomplete_model_response"}
            or len(calls) < 1
            or any(call.get("error") is not None for call in calls)
            or {call["model"] for call in calls} != {expected_call_model}
            or runtime["scenario_id"] != scenario_id
            or runtime["runtime_trace_digest"] != snapshot.trace_digest
            or runtime["runtime_result_digest"] != snapshot.result_digest
            or snapshot.status != "completed"
            or snapshot.verifier_result is None
        ):
            raise ValueError("incomplete native run")
        trace_digest = runtime["runtime_trace_digest"]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise CurriculumAnalysisError(
            "held-out native trace failed canonical validation"
        ) from error
    if (
        not isinstance(scenario_id, str)
        or _SCENARIO_ID.fullmatch(scenario_id) is None
        or not isinstance(trace_digest, str)
        or _DIGEST.fullmatch(trace_digest) is None
    ):
        raise CurriculumAnalysisError(
            "held-out native trace identity is invalid"
        )
    return scenario_id, snapshot, trace_digest


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise CurriculumAnalysisError("bootstrap produced no samples")
    position = (len(values) - 1) * probability
    low_index = math.floor(position)
    high_index = math.ceil(position)
    if low_index == high_index:
        return values[low_index]
    fraction = position - low_index
    return values[low_index] + (values[high_index] - values[low_index]) * fraction


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


__all__ = [
    "CurriculumAnalysisError",
    "HeldOutEvaluationEvidence",
    "PairedBootstrapAnalysis",
    "import_native_heldout_evaluation",
    "paired_bootstrap_success",
]
