"""Ticket 11 immutable run-configuration evidence contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from studio.curriculum_training_evidence import CurriculumRunConfiguration


def _configuration() -> dict[str, object]:
    return {
        "code_revision": "c6e0c9c000000000000000000000000000000000",
        "prime_revision": "1e756307ae7b29c31fd202e6fac9afd7e23db18b",
        "prime_lock_digest": (
            "sha256:44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
        ),
        "compatibility_patch_digest": (
            "sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
        ),
        "verifiers_revision": "4bcb48e55a35c199d9d2f9722060fda627306aa3",
        "renderer_revision": "f770dcaa362e3a6a13a96f039741b3b84ca4114e",
        "model": "google/gemma-4-E4B-it",
        "model_revision": "ee0ef6023621cff504d758262d4e04895a5af4a2",
        "training_taskset_digest": "sha256:" + "1" * 64,
        "development_taskset_digest": "sha256:" + "2" * 64,
        "heldout_taskset_digest": "sha256:" + "3" * 64,
        "training_package_digest": (
            "sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c"
        ),
        "development_package_digest": (
            "sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197"
        ),
        "heldout_package_digest": (
            "sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7"
        ),
        "max_steps": 96,
        "group_size": 4,
        "sequence_length": 16_384,
        "evaluation_context_length": 16_384,
        "max_completion_tokens": 256,
        "optimization_dtype": "bfloat16",
        "reduction_dtype": "bfloat16",
        "lora_target_regex": (
            "^model\\.language_model\\.layers\\..*\\."
            "(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
        ),
        "curriculum_order": "standard-source-order",
        "provider_sampling_seed": None,
        "adapter_selection": "final-step-predeclared",
    }


def test_configuration_records_exact_splits_stack_seed_policy_and_selection() -> None:
    configuration = CurriculumRunConfiguration.model_validate(_configuration())

    assert configuration.max_steps == 96
    assert configuration.group_size == 4
    assert configuration.provider_sampling_seed is None
    assert configuration.adapter_selection == "final-step-predeclared"
    assert configuration.training_package_digest != configuration.heldout_package_digest


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("max_steps", 95),
        ("group_size", 8),
        ("provider_sampling_seed", 7),
        ("adapter_selection", "selected-after-heldout"),
        ("heldout_package_digest", "sha256:" + "f" * 64),
    ),
)
def test_configuration_rejects_scope_or_leakage_drift(
    field: str,
    value: object,
) -> None:
    document = _configuration()
    document[field] = value

    with pytest.raises(ValidationError):
        CurriculumRunConfiguration.model_validate(document)
