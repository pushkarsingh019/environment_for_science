"""Process-boundary regression for renderer partial-clone configuration."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from studio.policy_evaluation.gemma_attestation import verify_renderer_checkout


def test_renderer_verification_never_invokes_a_promisor_remote_helper(
    tmp_path: Path,
) -> None:
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    subprocess.run(("git", "init", str(renderer)), check=True, capture_output=True)
    (renderer / "renderer.py").write_text("PINNED = True\n")
    subprocess.run(("git", "-C", str(renderer), "add", "renderer.py"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(renderer),
            "-c",
            "user.name=Science Test",
            "-c",
            "user.email=science@example.invalid",
            "commit",
            "-m",
            "pinned renderer",
        ),
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ("git", "-C", str(renderer), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    sentinel = tmp_path / "promisor-helper-executed"
    helper = tmp_path / "promisor-helper"
    helper.write_text(f"#!/bin/sh\ntouch {sentinel!s}\nexit 1\n")
    helper.chmod(0o700)
    subprocess.run(
        ("git", "-C", str(renderer), "remote", "add", "origin", f"ext::{helper!s}"),
        check=True,
    )
    for name, value in (
        ("core.repositoryFormatVersion", "1"),
        ("extensions.partialClone", "origin"),
        ("remote.origin.promisor", "true"),
        ("remote.origin.partialCloneFilter", "blob:none"),
        ("protocol.ext.allow", "always"),
    ):
        subprocess.run(
            ("git", "-C", str(renderer), "config", "--local", name, value),
            check=True,
        )
    commit_object = renderer / ".git" / "objects" / revision[:2] / revision[2:]
    assert commit_object.is_file()
    commit_object.unlink()

    with pytest.raises(subprocess.CalledProcessError):
        verify_renderer_checkout(renderer)

    assert sentinel.exists() is False
