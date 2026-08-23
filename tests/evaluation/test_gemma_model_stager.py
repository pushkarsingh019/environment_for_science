"""Operator-seam tests for the one-time pinned Gemma snapshot stager."""

from __future__ import annotations

import hashlib
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from deployment import science_local_gemma_model_stager as model_stager
from deployment.science_local_gemma_model_stager import (
    EXPECTED_SNAPSHOT_FILES,
    PRODUCTION_ARTIFACT_PINS,
    ArtifactPin,
    StagingLayout,
    run_operator,
    stage_model_snapshot,
)

_TEST_TOKEN = "hf_test_token_must_remain_ephemeral_0123456789"
_TEST_CONTENTS = {
    ".gitattributes": b"attrs",
    "README.md": b"readme",
    "model.safetensors": b"weights",
    "chat_template.jinja": b"chat",
    "config.json": b"config",
    "generation_config.json": b"generation",
    "processor_config.json": b"processor",
    "tokenizer.json": b"tokenizer",
    "tokenizer_config.json": b"tokenizer_config",
}
_TEST_PINS = (
    ArtifactPin(
        name="model.safetensors",
        size_bytes=7,
        sha256="9a129038d9a00aed0cf6a7ea059ca50a813449061ab87848cf1a13eafdf33b2c",
    ),
    ArtifactPin(
        name="chat_template.jinja",
        size_bytes=4,
        sha256="31e06f7d89feb99a0e6c0affe198748c3bb5bef5e3cc92d95cb9e996197d3fc3",
    ),
    ArtifactPin(
        name="config.json",
        size_bytes=6,
        sha256="b79606fb3afea5bd1609ed40b622142f1c98125abcfe89a76a661b0e8e343910",
    ),
    ArtifactPin(
        name="generation_config.json",
        size_bytes=10,
        sha256="e661f4c935e8a5a83349afb5e347695c2e972e967b50efcd618f93b0b7b4c24b",
    ),
    ArtifactPin(
        name="processor_config.json",
        size_bytes=9,
        sha256="d825be6ffd4c9a27a8cc2f26e4a3b95bc87a8f43289ca467d064d544c509f8eb",
    ),
    ArtifactPin(
        name="tokenizer.json",
        size_bytes=9,
        sha256="5f97e3774c51edd1d63706c2ec3826c564a067794770cdab0f8c4797971cacf9",
    ),
    ArtifactPin(
        name="tokenizer_config.json",
        size_bytes=16,
        sha256="22a7af41e1c23c5e481b86e7e6eb70332e6ba613d6d3e66a3f3af9bd29281459",
    ),
)


@pytest.fixture
def stager_script() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "deployment"
        / "science_local_gemma_model_stager.py"
    )


def test_production_manifest_pins_the_weight_and_six_serving_files() -> None:
    assert {
        pin.name: (pin.size_bytes, pin.sha256) for pin in PRODUCTION_ARTIFACT_PINS
    } == {
        "model.safetensors": (
            15_992_595_884,
            "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503",
        ),
        "chat_template.jinja": (
            18_569,
            "0a2c8073c878ab1da004bee933a998606537bbb62016310352c7285c3f01c5b5",
        ),
        "config.json": (
            5_145,
            "33b10c02df3c2e8536cf323d29d53262aaa2f4d11dbe19bc729373fbe90295d4",
        ),
        "generation_config.json": (
            208,
            "d4226bbe3117d2d253ba4609720ba82c6c4ce4627a9a6ae05387c78983ac03de",
        ),
        "processor_config.json": (
            1_689,
            "32bdf45d2ad4cc29a0822ddd157a182de76644f0419a6228d151495256e9813c",
        ),
        "tokenizer.json": (
            32_169_626,
            "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
        ),
        "tokenizer_config.json": (
            3_082,
            "9f4fec4b1dc6ecddf8f4a92e9caea5971c0e67d81309f3f9066a2bee8c362633",
        ),
    }


def test_stager_fetches_only_the_pinned_revision_and_materializes_real_files(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def download_snapshot(**kwargs: Any) -> str:
        calls.append(kwargs)
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        (local_dir / ".cache" / "huggingface" / "download").mkdir(parents=True)
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    stage_model_snapshot(
        token=_TEST_TOKEN,
        layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
        artifact_pins=_TEST_PINS,
        snapshot_download=download_snapshot,
    )

    assert len(calls) == 1
    assert calls[0]["repo_id"] == "google/gemma-4-E4B-it"
    assert calls[0]["revision"] == "ee0ef6023621cff504d758262d4e04895a5af4a2"
    assert calls[0]["endpoint"] == "https://huggingface.co"
    assert calls[0]["allow_patterns"] == list(EXPECTED_SNAPSHOT_FILES)
    assert calls[0]["token"] == _TEST_TOKEN
    assert calls[0]["max_workers"] == 1
    assert set(entry.name for entry in final_root.iterdir()) == set(EXPECTED_SNAPSHOT_FILES)
    for name, contents in _TEST_CONTENTS.items():
        artifact = final_root / name
        assert artifact.read_bytes() == contents
        assert artifact.is_symlink() is False
        assert stat.S_ISREG(artifact.stat().st_mode)
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o444
    for entry in attempts_root.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            assert _TEST_TOKEN.encode() not in entry.read_bytes()


def test_operator_prompts_privately_and_emits_only_content_free_success(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    prompts: list[str] = []

    def prompt_for_token(prompt: str) -> str:
        prompts.append(prompt)
        return _TEST_TOKEN

    def noisy_download(**kwargs: Any) -> str:
        print("SDK accidentally wrote " + _TEST_TOKEN)
        print("SDK accidentally wrote a private path", file=sys.stderr)
        os.write(1, b"native SDK stdout disclosure")
        os.write(2, b"native SDK stderr disclosure")
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    exit_code = run_operator(
        argv=("science-local-gemma-model-stager",),
        prompt_for_token=prompt_for_token,
        snapshot_download=noisy_download,
        layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
        artifact_pins=_TEST_PINS,
    )

    captured = capfd.readouterr()
    assert exit_code == 0
    assert prompts == ["Hugging Face access token: "]
    assert captured.out == "science-local-gemma-model-stage: PASS\n"
    assert captured.err == ""
    assert _TEST_TOKEN not in captured.out + captured.err


def test_executable_rejects_token_arguments_without_echoing_them(
    stager_script: Path,
) -> None:
    completed = subprocess.run(
        (sys.executable, str(stager_script), _TEST_TOKEN),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == "science-local-gemma-model-stage: FAIL\n"
    assert _TEST_TOKEN not in completed.stdout + completed.stderr


def test_executable_refuses_noninteractive_or_environment_credentials(
    stager_script: Path,
) -> None:
    completed = subprocess.run(
        (sys.executable, str(stager_script)),
        env={"HF_TOKEN": _TEST_TOKEN},
        input=_TEST_TOKEN + "\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == "science-local-gemma-model-stage: FAIL\n"
    assert _TEST_TOKEN not in completed.stdout + completed.stderr


def test_documented_bind_mount_keeps_the_immutable_stager_visible(
    tmp_path: Path,
    stager_script: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    operations = (repository / "docs" / "local-gemma-runtime-operations.md").read_text()
    normalized_operations = " ".join(operations.split())
    command_start = operations.index("docker run --rm -it")
    command_end = operations.index("```", command_start)
    command = operations[command_start:command_end].replace("\\\n", " ")
    arguments = shlex.split(command)
    mount_specs = [
        arguments[index + 1]
        for index, argument in enumerate(arguments[:-1])
        if argument == "--mount"
    ]
    writable_mount = next(spec for spec in mount_specs if "dst=/approved/ro" in spec)
    assert "src=/operator/private/science-gemma-model-stage" in writable_mount

    immutable_stager = Path("/usr/local/libexec/science_local_gemma_model_stager.py")
    legacy_shadowed_stager = Path(
        "/approved/ro/release/science_local_gemma_model_stager.py"
    )
    assert arguments[-1] == str(immutable_stager)
    assert "--read-only" in arguments
    assert (
        "COPY --chown=0:0 --chmod=0444 science_local_gemma_model_stager.py "
        "/usr/local/libexec/science_local_gemma_model_stager.py"
    ) in operations
    assert hashlib.sha256(stager_script.read_bytes()).hexdigest() in operations
    assert "<candidate-image-by-digest>" in arguments
    assert (
        "science-local-gemma-model-stage: FAIL MANUAL-QUARANTINE-REQUIRED"
        in operations
    )
    assert "exits 70" in operations
    assert "pre-attempt validation failures create no attempt" in normalized_operations
    assert (
        "Once a unique attempt has been durably created" in normalized_operations
    )
    assert "download or verification failure" in normalized_operations
    assert (
        "any storage durability step, rollback, or failed-payload preservation"
        in normalized_operations
    )

    image_root = tmp_path / "candidate-image"
    host_mount = tmp_path / "private-host-stage"
    host_mount.mkdir()
    image_stager = image_root / immutable_stager.relative_to("/")
    image_stager.parent.mkdir(parents=True)
    image_stager.write_bytes(stager_script.read_bytes())
    image_stager.chmod(0o444)
    legacy_image_stager = image_root / legacy_shadowed_stager.relative_to("/")
    legacy_image_stager.parent.mkdir(parents=True)
    legacy_image_stager.write_bytes(stager_script.read_bytes())

    def resolve_with_documented_mount(container_path: Path) -> Path:
        try:
            relative = container_path.relative_to("/approved/ro")
        except ValueError:
            return image_root / container_path.relative_to("/")
        return host_mount / relative

    visible_stager = resolve_with_documented_mount(immutable_stager)
    assert visible_stager.is_file()
    assert stat.S_IMODE(visible_stager.stat().st_mode) == 0o444
    assert resolve_with_documented_mount(legacy_shadowed_stager).exists() is False
    smoke = subprocess.run(
        (sys.executable, str(visible_stager), _TEST_TOKEN),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 64
    assert smoke.stdout == ""
    assert smoke.stderr == "science-local-gemma-model-stage: FAIL\n"


def test_stager_rejects_a_symlinked_layout_ancestor_before_download(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    fixed_parent = real_parent / "ro"
    fixed_parent.mkdir(parents=True)
    alias = tmp_path / "private-route-marker"
    alias.symlink_to(real_parent, target_is_directory=True)
    download_called = False

    def download_snapshot(**_kwargs: Any) -> str:
        nonlocal download_called
        download_called = True
        return "unreachable"

    with pytest.raises(RuntimeError, match="non-symlink directory chain"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(
                final_root=alias / "ro" / "model",
                attempts_root=alias / "ro" / "model-attempts",
            ),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert download_called is False
    assert list(fixed_parent.iterdir()) == []


def test_stager_rejects_download_links_and_preserves_the_unique_failed_attempt(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        (local_dir / ".cache").symlink_to(outside, target_is_directory=True)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="must not contain links"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    assert attempts[0].name.startswith("attempt-")
    assert (attempts[0] / "download" / ".cache").is_symlink()
    assert final_root.exists() is False


def test_stager_rejects_a_cache_hardlink_before_atomic_publication(
    tmp_path: Path,
) -> None:
    alias_holder: list[Path] = []

    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        cache_dir = Path(kwargs["cache_dir"])
        local_dir.mkdir()
        cache_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        alias = cache_dir / "mutable-config-alias"
        os.link(local_dir / "config.json", alias)
        alias_holder.append(alias)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="single-link"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert final_root.exists() is False
    assert len(alias_holder) == 1
    assert alias_holder[0].is_file()


@pytest.mark.parametrize("mutation", ("drift", "extra", "missing", "file-link"))
def test_stager_rejects_every_noncanonical_download_tree(
    tmp_path: Path,
    mutation: str,
) -> None:
    outside = tmp_path / "outside-file"
    outside.write_bytes(b"config")

    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        if mutation == "drift":
            (local_dir / "config.json").write_bytes(b"drift!")
        elif mutation == "extra":
            (local_dir / "private-extra-marker").write_bytes(b"extra")
        elif mutation == "missing":
            (local_dir / "README.md").unlink()
        else:
            (local_dir / "config.json").unlink()
            (local_dir / "config.json").symlink_to(outside)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    with pytest.raises(RuntimeError):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert final_root.exists() is False
    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    assert attempts[0].is_dir()


def test_stager_never_downloads_over_an_existing_final_root(tmp_path: Path) -> None:
    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.mkdir(parents=True)
    sentinel = final_root / "operator-owned-sentinel"
    sentinel.write_bytes(b"must survive unchanged")
    download_called = False

    def download_snapshot(**_kwargs: Any) -> str:
        nonlocal download_called
        download_called = True
        return "unreachable"

    with pytest.raises(FileExistsError):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert download_called is False
    assert sentinel.read_bytes() == b"must survive unchanged"
    assert attempts_root.exists() is False


def test_mode_finalization_fault_cannot_publish_a_failed_model_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)
    real_chmod = os.chmod
    real_fsync_directory = model_stager._fsync_directory
    fsynced_directories: list[Path] = []

    def fail_final_mode(path: os.PathLike[str] | str, mode: int, **kwargs: Any) -> None:
        if mode == 0o555:
            raise OSError("injected directory-mode failure")
        real_chmod(path, mode, **kwargs)

    def record_fsync(path: Path) -> None:
        fsynced_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(os, "chmod", fail_final_mode)
    monkeypatch.setattr(model_stager, "_fsync_directory", record_fsync)

    with pytest.raises(OSError, match="injected directory-mode failure"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert final_root.exists() is False
    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    assert set((attempts[0] / "payload").iterdir()) == {
        attempts[0] / "payload" / name for name in EXPECTED_SNAPSHOT_FILES
    }
    assert fsynced_directories[0] == attempts_root
    assert fsynced_directories[-3:] == [
        attempts[0],
        final_root.parent,
        attempts_root,
    ]


def test_post_rename_fsync_fault_rolls_back_into_the_unique_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)
    real_fsync_directory = model_stager._fsync_directory
    injected = False

    def fail_after_publication(path: Path) -> None:
        nonlocal injected
        if path == final_root.parent and final_root.exists() and not injected:
            injected = True
            raise OSError("injected post-rename fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(model_stager, "_fsync_directory", fail_after_publication)

    with pytest.raises(OSError, match="injected post-rename fsync failure"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=download_snapshot,
        )

    assert injected is True
    assert final_root.exists() is False
    assert list(final_root.parent.glob(".model-payload-*")) == []
    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    preserved_payload = attempts[0] / "payload"
    assert stat.S_IMODE(preserved_payload.stat().st_mode) == 0o700
    assert {entry.name for entry in preserved_payload.iterdir()} == set(
        EXPECTED_SNAPSHOT_FILES
    )


def test_rollback_failure_emits_content_free_manual_quarantine_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)
    real_rename = model_stager._rename_no_replace
    real_fsync_directory = model_stager._fsync_directory
    rename_calls = 0
    post_rename_fsync_failed = False

    def fail_rollback(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("injected rollback rename failure")
        real_rename(source, destination)

    def fail_post_rename_fsync(path: Path) -> None:
        nonlocal post_rename_fsync_failed
        if path == final_root.parent and final_root.exists() and not post_rename_fsync_failed:
            post_rename_fsync_failed = True
            raise OSError("injected post-rename fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(model_stager, "_rename_no_replace", fail_rollback)
    monkeypatch.setattr(model_stager, "_fsync_directory", fail_post_rename_fsync)

    exit_code = run_operator(
        argv=("science-local-gemma-model-stager",),
        prompt_for_token=lambda _prompt: _TEST_TOKEN,
        snapshot_download=download_snapshot,
        layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
        artifact_pins=_TEST_PINS,
    )

    captured = capfd.readouterr()
    assert exit_code == 70
    assert captured.out == ""
    assert captured.err == (
        "science-local-gemma-model-stage: FAIL MANUAL-QUARANTINE-REQUIRED\n"
    )
    assert rename_calls == 2
    assert post_rename_fsync_failed is True
    assert final_root.is_dir()


def test_preservation_fsync_failure_emits_manual_quarantine_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    def download_snapshot(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        for name, contents in _TEST_CONTENTS.items():
            (local_dir / name).write_bytes(contents)
        return str(local_dir)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)
    real_chmod = os.chmod
    real_fsync_directory = model_stager._fsync_directory
    preservation_fsync_failed = False

    def fail_final_mode(path: os.PathLike[str] | str, mode: int, **kwargs: Any) -> None:
        if mode == 0o555:
            raise OSError("injected pre-publication failure")
        real_chmod(path, mode, **kwargs)

    def fail_preservation_fsync(path: Path) -> None:
        nonlocal preservation_fsync_failed
        preserved_payloads = list(attempts_root.glob("attempt-*/payload"))
        if path == final_root.parent and preserved_payloads and not preservation_fsync_failed:
            preservation_fsync_failed = True
            raise OSError("injected preservation fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(os, "chmod", fail_final_mode)
    monkeypatch.setattr(model_stager, "_fsync_directory", fail_preservation_fsync)

    exit_code = run_operator(
        argv=("science-local-gemma-model-stager",),
        prompt_for_token=lambda _prompt: _TEST_TOKEN,
        snapshot_download=download_snapshot,
        layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
        artifact_pins=_TEST_PINS,
    )

    captured = capfd.readouterr()
    assert exit_code == 70
    assert captured.out == ""
    assert captured.err == (
        "science-local-gemma-model-stage: FAIL MANUAL-QUARANTINE-REQUIRED\n"
    )
    assert preservation_fsync_failed is True
    assert final_root.exists() is False
    assert len(list(attempts_root.glob("attempt-*/payload"))) == 1


def test_operator_reports_sdk_failure_without_disclosure_and_keeps_attempt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_error = "private SDK failure with route and credential material"

    def failed_download(**kwargs: Any) -> str:
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir()
        (local_dir / "partial-download").write_bytes(b"preserved partial evidence")
        print(private_error, file=sys.stderr)
        raise RuntimeError(private_error)

    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)

    exit_code = run_operator(
        argv=("science-local-gemma-model-stager",),
        prompt_for_token=lambda _prompt: _TEST_TOKEN,
        snapshot_download=failed_download,
        layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
        artifact_pins=_TEST_PINS,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "science-local-gemma-model-stage: FAIL\n"
    assert private_error not in captured.out + captured.err
    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    assert (attempts[0] / "download" / "partial-download").read_bytes() == (
        b"preserved partial evidence"
    )
    assert final_root.exists() is False


def test_fresh_attempt_roots_are_durable_before_the_sdk_is_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_root = tmp_path / "approved" / "ro" / "model"
    attempts_root = tmp_path / "approved" / "ro" / "model-attempts"
    final_root.parent.mkdir(parents=True)
    real_fsync_directory = model_stager._fsync_directory
    fsynced_directories: list[Path] = []
    fsyncs_observed_by_sdk: list[Path] = []

    def record_fsync(path: Path) -> None:
        fsynced_directories.append(path)
        real_fsync_directory(path)

    def failed_download(**_kwargs: Any) -> str:
        fsyncs_observed_by_sdk.extend(fsynced_directories)
        raise RuntimeError("injected SDK failure")

    monkeypatch.setattr(model_stager, "_fsync_directory", record_fsync)

    with pytest.raises(RuntimeError, match="injected SDK failure"):
        stage_model_snapshot(
            token=_TEST_TOKEN,
            layout=StagingLayout(final_root=final_root, attempts_root=attempts_root),
            artifact_pins=_TEST_PINS,
            snapshot_download=failed_download,
        )

    expected_order = [attempts_root, final_root.parent, attempts_root]
    assert fsyncs_observed_by_sdk == expected_order
    assert fsynced_directories == expected_order
    attempts = list(attempts_root.iterdir())
    assert len(attempts) == 1
    assert attempts[0].name.startswith("attempt-")
