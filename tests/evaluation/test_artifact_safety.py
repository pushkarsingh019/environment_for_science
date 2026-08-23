"""Shared safety boundary for durable and generated evaluation artifacts."""

from __future__ import annotations

import pytest

from studio.policy_evaluation.artifact_safety import (
    ArtifactSafetyError,
    validate_artifact_safe,
)


@pytest.mark.parametrize(
    "document",
    (
        {"token": "opaque-secret"},
        {"future": {"accessToken": "opaque-secret"}},
        {"future": {"oauth_token": "opaque-secret"}},
        {"future": {"hf_token": "opaque-secret"}},
        {"future": {"github_token": "opaque-secret"}},
        {"future": {"id_token": "opaque-secret"}},
        {"future": {"secret_token": "opaque-secret"}},
        {"future": {"session-token": "opaque-secret"}},
        {"future": {"auth": "opaque-secret"}},
        {"future": {"client-secret": "opaque-secret"}},
        {"future": {"authorization": "Bearer opaque-secret"}},
        {"future": {"message": "ghp_" + "a" * 36}},
        {"future": {"message": "github_pat_" + "a" * 40}},
        {"future": {"message": "hf_" + "a" * 34}},
        {"future": {"message": "sk-" + "a" * 32}},
        {"future": {"server_host": "gpu-box"}},
        {"future": {"runtimeHost": "gpu-box"}},
        {"future": {"opaque": "https://gemma-gateway.lab.internal/v1"}},
        {"future": {"opaque": "gemma-gateway.local:8000/v1"}},
        {"future": {"opaque": "gemma.private.example"}},
        {"future": {"opaque": "gemma.private.invalid"}},
        {"future": {"opaque": "gemma.private.test"}},
        {"future": {"opaque": "gemma.private.onion"}},
        {"future": {"opaque": "adapter failed at localhost:8000"}},
        {"future": {"opaque": "adapter failed at gpu-box"}},
        {"future": {"opaque": "connection failed to gemma-worker"}},
        {"future": {"opaque": "adapter failed at 10.23.4.8:8000"}},
        {"future": {"opaque": "adapter failed at [fd00::8]:8000"}},
        {"future": {"opaque": "ssh://scientist@example.org/model"}},
        {"future": {"opaque": "/opt/private-models/gemma"}},
        {"future": {"opaque": r"C:\Users\scientist\model"}},
        {"future": {"opaque": r"\\lab-server\models\gemma"}},
        {"future": {"opaque": "~/private-models/gemma"}},
        {"future": {"opaque": "OPENAI_API_KEY=opaque-secret"}},
        {"future": {"opaque": "token=opaque-secret"}},
        {"future": {"opaque": '\"hf_token\":\"opaque-secret\"'}},
    ),
)
def test_transport_credentials_private_hosts_and_host_paths_are_rejected(
    document: dict[str, object],
) -> None:
    with pytest.raises(ArtifactSafetyError, match="transport material"):
        validate_artifact_safe(document)


def test_scientific_prose_and_public_content_identifiers_remain_valid() -> None:
    validate_artifact_safe(
        {
            "description": (
                "Compare C3/C4 after a 1:2 synthetic gain change; this is ordinary "
                "scientific prose, not an operational endpoint."
            ),
            "normalized_error": "The model server attestation was invalid.",
            "status_explanation": (
                "Run the deterministic runtime on synthetic evidence; the connection "
                "failed to recover a valid marker."
            ),
            "model_id": "google/gemma-4-E4B-it",
            "scenario_id": "eeg-30ddbcb4ceb8016d",
            "doi": "10.1038/s41586-024-00000-0",
            "source_digest": "sha256:" + "a" * 64,
            "prompt_tokens": 128,
            "token_count": 128,
            "ghost": "a benign experimental label",
        }
    )
