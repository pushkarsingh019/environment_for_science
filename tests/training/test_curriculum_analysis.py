"""Ticket 11 paired-analysis acceptance rule."""

from __future__ import annotations

import pytest

from studio.curriculum_analysis import (
    CurriculumAnalysisError,
    paired_bootstrap_success,
)


def _outcomes(base_value: bool, trained_value: bool, count: int = 64):
    base = {f"eeg-{index:016x}": base_value for index in range(count)}
    trained = {f"eeg-{index:016x}": trained_value for index in range(count)}
    return base, trained


def test_paired_bootstrap_claims_improvement_only_when_interval_excludes_zero() -> None:
    base, trained = _outcomes(False, True)

    analysis = paired_bootstrap_success(base, trained)

    assert analysis.trained_minus_base == 1.0
    assert analysis.interval_low == 1.0
    assert analysis.interval_high == 1.0
    assert analysis.conclusion == "improved"
    assert analysis.replicates == 10_000
    assert analysis.seed == 20_260_823


def test_paired_bootstrap_reports_inconclusive_without_overclaiming() -> None:
    base, trained = _outcomes(False, False)
    for index in range(8):
        trained[f"eeg-{index:016x}"] = True
    for index in range(8, 16):
        base[f"eeg-{index:016x}"] = True

    analysis = paired_bootstrap_success(base, trained)

    assert analysis.trained_minus_base == 0.0
    assert analysis.interval_low < 0.0 < analysis.interval_high
    assert analysis.conclusion == "inconclusive"


def test_paired_bootstrap_can_report_a_clear_regression() -> None:
    base, trained = _outcomes(True, False)

    analysis = paired_bootstrap_success(base, trained)

    assert analysis.trained_minus_base == -1.0
    assert analysis.interval_high == -1.0
    assert analysis.conclusion == "regressed"


def test_paired_bootstrap_is_order_independent_and_replayable() -> None:
    base, trained = _outcomes(False, False)
    for index in range(20):
        trained[f"eeg-{index:016x}"] = True
    reordered_base = dict(reversed(tuple(base.items())))
    reordered_trained = dict(reversed(tuple(trained.items())))

    first = paired_bootstrap_success(base, trained, replicates=1_000)
    second = paired_bootstrap_success(
        reordered_base,
        reordered_trained,
        replicates=1_000,
    )

    assert first == second


def test_paired_bootstrap_rejects_unpaired_or_non_boolean_outcomes() -> None:
    base, trained = _outcomes(False, True)
    trained.pop(next(iter(trained)))

    with pytest.raises(CurriculumAnalysisError, match="incomplete"):
        paired_bootstrap_success(base, trained)
