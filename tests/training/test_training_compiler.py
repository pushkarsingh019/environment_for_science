"""Prime training compilation contract for Tickets 10 and 11."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from environments.eeg.curriculum import (
    load_development_scenario_set,
    load_training_scenario_set,
)
from studio.policy_evaluation.training_compiler import (
    PrimeTrainingCompilation,
    compile_prime_training_taskset,
)


def test_training_compiler_is_deterministic_and_binds_the_prime_stack(
    tmp_path: Path,
) -> None:
    bundle = load_training_scenario_set().environment_bundle

    first = compile_prime_training_taskset(bundle, tmp_path / "first")
    second = compile_prime_training_taskset(bundle, tmp_path / "second")

    assert isinstance(first, PrimeTrainingCompilation)
    assert first == second
    assert first.prime_revision == "1e756307ae7b29c31fd202e6fac9afd7e23db18b"
    assert first.verifiers_revision == "4bcb48e55a35c199d9d2f9722060fda627306aa3"
    assert first.renderer_revision == "f770dcaa362e3a6a13a96f039741b3b84ca4114e"
    assert first.prime_lock_digest == (
        "sha256:44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
    )
    assert first.compatibility_patch_digest == (
        "sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
    )
    assert len(bundle.scenarios) == 96


def test_training_target_has_buildable_metadata_stable_transport_and_delta_results(
    tmp_path: Path,
) -> None:
    root = tmp_path / "training"
    compile_prime_training_taskset(
        load_training_scenario_set().environment_bundle,
        root,
    )

    pyproject = (root / "taskset/pyproject.toml").read_text()
    taskset = (
        root / "taskset/science_environment_generated/taskset.py"
    ).read_text()
    harness = (
        root / "taskset/science_environment_generated/harness.py"
    ).read_text()
    transport = (
        root
        / "taskset/science_environment_generated/_private/transport_adapter.py"
    ).read_text()
    apparatus = (
        root / "taskset/science_environment_generated/servers/apparatus.py"
    ).read_text()
    manifest = json.loads((root / "manifest.json").read_text())
    dependencies = json.loads(
        (
            root
            / "taskset/science-environment-runtime-dependency-receipt.json"
        ).read_text()
    )

    assert "allow-direct-references = true" in pyproject
    assert "4bcb48e55a35c199d9d2f9722060fda627306aa3" in pyproject
    assert '"mcp==1.27.1"' in pyproject
    assert "install_attested_eval_client_patch" not in taskset
    assert "async def mechanical_jitter" in taskset
    assert "@vf.reward(weight=0.0)" in taskset
    assert "GeneratedTrainingHarness" in harness
    assert "patched_null_program" in harness
    assert "SCIENCE_MODEL_API_KEY" not in harness
    assert "0.3.1.dev59" in transport
    assert "1.27.1" in transport
    assert '"observation_scope": "changed_fields"' in apparatus
    assert "prior_observation.get(key) != child" in apparatus
    assert manifest["integration_profile"]["prime_revision"] == (
        "1e756307ae7b29c31fd202e6fac9afd7e23db18b"
    )
    assert dependencies["closure"] == {
        "scope": "prime-locked-workstation-training",
        "status": "closed-by-prime-lock",
    }


def test_development_target_is_disjoint_and_recompilation_is_stable(
    tmp_path: Path,
) -> None:
    training = compile_prime_training_taskset(
        load_training_scenario_set().environment_bundle,
        tmp_path / "training",
    )
    development_root = tmp_path / "development"
    development = compile_prime_training_taskset(
        load_development_scenario_set().environment_bundle,
        development_root,
    )

    assert training.source_bundle_digest != development.source_bundle_digest
    assert training.artifact_digest != development.artifact_digest
    assert compile_prime_training_taskset(
        load_development_scenario_set().environment_bundle,
        development_root,
    ) == development


def test_audited_prime_compatibility_patch_has_the_recorded_digest() -> None:
    patch = Path(
        "probes/gemma-training-path/patches/"
        "prime-rl-gemma4-bounded-compatibility.patch"
    ).read_bytes()

    assert hashlib.sha256(patch).hexdigest() == (
        "5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
    )
    assert b"ignore_mismatched_sizes=config.debug.num_layers is not None" in patch
    assert b"if moe_ffn is None" in patch
