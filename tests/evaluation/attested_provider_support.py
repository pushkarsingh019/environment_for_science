"""Signed local-Gemma attestation support for injected unit-test providers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from studio.policy_evaluation.attestation_protocol import canonical_json, hmac_sha256_hex
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    BASE_GEMMA_CHECKPOINT_REVISION,
    BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256,
    BASE_GEMMA_MODEL,
    BASE_GEMMA_RENDERER_REVISION,
    BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
    PINNED_VLLM_SOURCE_REVISION,
    PINNED_VLLM_VERSION,
    PINNED_VLLM_WHEEL_SHA256,
    LocalGemmaRuntimeAttestation,
    ModelPreflightRequest,
    ModelSamplingSettings,
)
from studio.policy_evaluation.runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    PRODUCTION_RUNTIME_DISTRIBUTION_PINS,
)

TEST_ATTESTATION_KEY = "test-only-local-gemma-attestation-signing-key-2026"


class SignedLocalGemmaTestProvider:
    """Mixin giving an injected provider a real, signed preflight response."""

    def preflight(
        self,
        request: ModelPreflightRequest,
    ) -> LocalGemmaRuntimeAttestation:
        if (
            request.model.provider != "local-openai-compatible"
            or request.model.requested_model != BASE_GEMMA_MODEL
            or request.model.adapter_revision != BASE_GEMMA_ADAPTER_REVISION
            or request.profile != "base-gemma-development-v1"
            or request.sampling != ModelSamplingSettings()
            or request.budgets.max_episode_seconds != 900
            or not 0 < request.transport_timeout_seconds <= 900
        ):
            raise AssertionError("test provider received an invalid preflight contract")

        challenge = secrets.token_hex(32)
        generated_at = datetime.now(timezone.utc).replace(microsecond=0)
        evidence = {
            "attestation_version": "science-local-gemma-runtime-attestation/1",
            "attestation_id": f"test-attestation-{challenge[:16]}",
            "runtime_instance_id": "1" * 64,
            "trusted_bootstrap_sha256": "7" * 64,
            "python_bytecode_mode": "fresh-private-prefix-no-write",
            "challenge_nonce": challenge,
            "generated_at_utc": generated_at.isoformat().replace("+00:00", "Z"),
            "runtime_started_at_utc": (generated_at - timedelta(minutes=5))
            .isoformat()
            .replace("+00:00", "Z"),
            "served_model": BASE_GEMMA_MODEL,
            "checkpoint_revision": BASE_GEMMA_CHECKPOINT_REVISION,
            "checkpoint_weights_sha256": BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256,
            "tokenizer_revision": BASE_GEMMA_CHECKPOINT_REVISION,
            "tokenizer_manifest_sha256": BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
            "renderer_revision": BASE_GEMMA_RENDERER_REVISION,
            "vllm_version": PINNED_VLLM_VERSION,
            "vllm_source_revision": PINNED_VLLM_SOURCE_REVISION,
            "vllm_wheel_sha256": PINNED_VLLM_WHEEL_SHA256,
            "python_runtime": APPROVED_RUNTIME_PYTHON.model_dump(mode="json"),
            "runtime_receipt_id": "science-local-gemma-runtime-cp312-cu129/1",
            "runtime_distributions": runtime_distribution_receipt_for_tests(),
            "product_distribution": {
                "distribution": "science-environment-studio",
                "version": "0.1.0",
                "wheel_sha256": "9" * 64,
                "record_manifest_sha256": "c" * 64,
                "import_module": "studio.policy_evaluation.gemma_server_bootstrap",
                "import_origin": "studio/policy_evaluation/gemma_server_bootstrap.py",
                "import_origin_sha256": "d" * 64,
                "verification": "wheel-record-sha256+import-origin",
            },
            "serving_root_filesystem_mode": "kernel-read-only-mount",
            "network_scope": "loopback-only",
            "api_key_authentication": True,
            "attestation_middleware_revision": ("science-local-gemma-attestation-middleware/1"),
            "vllm_config": {
                "dtype": "bfloat16",
                "max_model_len": 32768,
                "tensor_parallel_size": 1,
                "gpu_memory_utilization": 0.35,
                "enforce_eager": True,
                "max_num_seqs": 16,
                "generation_config": "vllm",
                "tool_call_parser": "gemma4",
                "enable_auto_tool_choice": True,
                "enable_lora": False,
                "disable_log_requests": True,
                "limit_mm_per_prompt": {"image": 0, "audio": 0, "video": 0},
            },
            "adapter_revision": BASE_GEMMA_ADAPTER_REVISION,
            "served_adapter": "none",
            "sampling_profile": request.sampling.profile,
            "max_episode_seconds": request.budgets.max_episode_seconds,
            "platform": "linux-x86_64",
            "accelerator_architecture": "sm120",
            "accelerator_count": 1,
            "cuda_version": "12.9",
            "driver_version": "610.43.02",
            "serving_image_digest": f"sha256:{'2' * 64}",
            "serving_image_digest_provenance": "operator-supplied",
            "evidence_scope": "server-reported-runtime-state",
        }
        document = canonical_json(evidence)
        attestation = LocalGemmaRuntimeAttestation.model_validate_json(
            canonical_json(
                {
                    **evidence,
                    "signature": hmac_sha256_hex(
                        key=TEST_ATTESTATION_KEY,
                        canonical_document=document,
                    ),
                    "evidence_digest": (
                        "sha256:" + hashlib.sha256(document.encode("utf-8")).hexdigest()
                    ),
                    "verification_method": "hmac-sha256-server-challenge",
                }
            )
        )
        if not attestation.verify_signature(TEST_ATTESTATION_KEY):
            raise AssertionError("test attestation signature did not verify")
        return attestation


def runtime_distribution_receipt_for_tests() -> list[dict[str, object]]:
    """Structurally valid test receipt carrying the immutable production lock."""
    return [
        {
            "distribution": pin.distribution,
            "version": pin.version,
            "wheel_sha256": pin.wheel_sha256,
            "record_manifest_sha256": "a" * 64,
            "import_module": pin.import_module,
            "import_origin": pin.import_origin,
            "import_origin_sha256": "b" * 64,
            "verification": "wheel-record-sha256+import-origin",
        }
        for pin in PRODUCTION_RUNTIME_DISTRIBUTION_PINS
    ]


__all__ = [
    "SignedLocalGemmaTestProvider",
    "TEST_ATTESTATION_KEY",
    "runtime_distribution_receipt_for_tests",
]
