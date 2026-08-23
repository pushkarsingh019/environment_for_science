"""Verified, bytecode-isolated entry point for the local Gemma server."""

from __future__ import annotations

from .gemma_attestation import serve_attested_local_gemma

if __name__ == "__main__":
    serve_attested_local_gemma()
