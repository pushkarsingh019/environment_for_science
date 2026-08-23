"""Evaluator-owned checks for physical held-out confinement."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest

from evaluation.eeg.confinement import (
    TrainingDistributionLeakageError,
    audit_training_wheel,
)


def test_training_module_has_no_heldout_loader() -> None:
    from environments.eeg import curriculum

    assert not hasattr(curriculum, "load_held_out_scenario_set")
    assert "HeldOutScenarioSet" not in curriculum.__all__
    assert "load_held_out_scenario_set" not in curriculum.__all__


def test_training_wheel_audit_accepts_an_allowlisted_training_payload(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "training.whl"
    with ZipFile(archive, "w") as wheel:
        wheel.writestr(
            "environments/eeg/curriculum_training_v1.json",
            files("environments.eeg")
            .joinpath("curriculum_training_v1.json")
            .read_bytes(),
        )

    report = audit_training_wheel(archive)

    assert report.valid is True
    assert report.files_scanned == 1
    assert report.held_out_values_scanned > 64


def test_training_wheel_audit_rejects_a_hidden_identity_or_resource(
    tmp_path: Path,
) -> None:
    held_out = json.loads(
        files("environments.eeg")
        .joinpath("curriculum_heldout_v1.json")
        .read_text(encoding="utf-8")
    )
    identity_leak = tmp_path / "identity-leak.whl"
    with ZipFile(identity_leak, "w") as wheel:
        wheel.writestr(
            "environments/eeg/training.py",
            held_out["scenarios"][0]["scenario_id"],
        )
    with pytest.raises(TrainingDistributionLeakageError, match="opaque material"):
        audit_training_wheel(identity_leak)

    resource_leak = tmp_path / "resource-leak.whl"
    with ZipFile(resource_leak, "w") as wheel:
        wheel.writestr("environments/eeg/curriculum_heldout_v1.json", b"{}")
    with pytest.raises(TrainingDistributionLeakageError, match="evaluator-owned path"):
        audit_training_wheel(resource_leak)


def test_training_wheel_audit_rejects_nested_evaluator_truth(tmp_path: Path) -> None:
    held_out = json.loads(
        files("environments.eeg")
        .joinpath("curriculum_heldout_v1.json")
        .read_text(encoding="utf-8")
    )
    occurrence_id = next(
        occurrence["occurrence_id"]
        for scenario in held_out["scenarios"]
        for occurrence in scenario["occurrences"]
    )
    occurrence_leak = tmp_path / "occurrence-leak.whl"
    with ZipFile(occurrence_leak, "w") as wheel:
        wheel.writestr("environments/eeg/training.py", occurrence_id)
    with pytest.raises(TrainingDistributionLeakageError, match="opaque material"):
        audit_training_wheel(occurrence_leak)

    combination = next(
        scenario["faults"]
        for scenario in held_out["scenarios"]
        if len(scenario["faults"]) == 2
    )
    composition_leak = tmp_path / "composition-leak.whl"
    with ZipFile(composition_leak, "w") as wheel:
        wheel.writestr(
            "environments/eeg/training.py",
            repr(tuple(combination)),
        )
    with pytest.raises(TrainingDistributionLeakageError, match="composition material"):
        audit_training_wheel(composition_leak)

    reversed_composition_leak = tmp_path / "reversed-composition-leak.whl"
    with ZipFile(reversed_composition_leak, "w") as wheel:
        wheel.writestr(
            "environments/eeg/training.py",
            repr(tuple(reversed(combination))),
        )
    with pytest.raises(TrainingDistributionLeakageError, match="composition material"):
        audit_training_wheel(reversed_composition_leak)

    evaluator_path_leak = tmp_path / "evaluator-path-leak.whl"
    with ZipFile(evaluator_path_leak, "w") as wheel:
        wheel.writestr(
            "science_studio.data/purelib/evaluation/eeg/answers.py",
            "",
        )
    with pytest.raises(TrainingDistributionLeakageError, match="evaluator-owned path"):
        audit_training_wheel(evaluator_path_leak)


def test_actual_training_wheel_excludes_and_survives_evaluator_audit(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output_directory = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(output_directory),
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(output_directory.glob("*.whl"))
    assert len(wheels) == 1

    audit = audit_training_wheel(wheels[0])

    assert audit.valid is True
    with ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        mesoscope_bundle = json.loads(
            wheel.read("environments/mesoscope/bundle.json")
        )
    assert not any("evaluation" in PurePosixPath(name).parts for name in names)
    assert not any(name.endswith("curriculum_heldout_v1.json") for name in names)
    assert {
        "environments/mesoscope/__init__.py",
        "environments/mesoscope/bundle.json",
        "environments/mesoscope/presentation.py",
        "environments/mesoscope/runtime.py",
        "studio/policy_evaluation/__init__.py",
        "studio/policy_evaluation/artifact_safety.py",
        "studio/policy_evaluation/compiler.py",
        "studio/policy_evaluation/coordinator.py",
        "studio/policy_evaluation/local_gemma.py",
        "studio/policy_evaluation/model_runner.py",
        "studio/policy_evaluation/repository.py",
        "studio/policy_evaluation/runtime_bridge.py",
    }.issubset(names)
    assert all(
        action["input_schema"]
        == {"type": "object", "properties": {}, "additionalProperties": False}
        for action in mesoscope_bundle["actions"]
    )

    project_root = project_root.resolve()
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import pathlib, sys; "
                "wheel=pathlib.Path(sys.argv[1]).resolve(); "
                "source=pathlib.Path(sys.argv[2]).resolve(); "
                "sys.path[:]=[str(wheel)]+[entry for entry in sys.path "
                "if entry and pathlib.Path(entry).resolve()!=source]; "
                "import studio.application as application; "
                "from studio.policy_evaluation.compiler import compile_verifiers_v1; "
                "from studio.policy_evaluation.coordinator import EvaluationCoordinator; "
                "from studio.policy_evaluation.model_runner import CanonicalModelRunner; "
                "modules=(application, sys.modules[compile_verifiers_v1.__module__], "
                "sys.modules[EvaluationCoordinator.__module__], "
                "sys.modules[CanonicalModelRunner.__module__]); "
                "assert all(str(wheel) in str(module.__file__) for module in modules); "
                "print('wheel-import-ok')"
            ),
            str(wheels[0]),
            str(project_root),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert imported.stdout.strip() == "wheel-import-ok"
