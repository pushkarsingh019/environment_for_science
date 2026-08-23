"""Shared cryptographic boundary for local model runtime attestation."""

from __future__ import annotations

import hashlib
import hmac
import json


def canonical_json(value: object) -> str:
    """Encode the one canonical JSON form used for signatures and digests."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hmac_sha256_hex(*, key: str, canonical_document: str) -> str:
    """Sign an already-canonical document without retaining key material."""
    return hmac.new(
        key.encode("utf-8"),
        canonical_document.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def is_sha256_hexdigest(value: object) -> bool:
    """Return whether a value is one lowercase SHA-256 hexadecimal digest."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_runtime_keys(*, api_key: str, attestation_key: str) -> tuple[str, str]:
    """Fail closed unless runtime authorization and signing keys are strong/distinct."""
    if (
        len(api_key.encode("utf-8")) < 32
        or len(attestation_key.encode("utf-8")) < 32
        or hmac.compare_digest(
            api_key.encode("utf-8"),
            attestation_key.encode("utf-8"),
        )
    ):
        raise ValueError("local Gemma runtime keys must be distinct and at least 32 bytes")
    return api_key, attestation_key


__all__ = [
    "canonical_json",
    "hmac_sha256_hex",
    "is_sha256_hexdigest",
    "validate_runtime_keys",
]
