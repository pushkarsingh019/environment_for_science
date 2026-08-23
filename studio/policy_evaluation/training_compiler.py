"""Prime-rl training target derived from the authoritative Environment compiler."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from studio.bundle import EnvironmentBundle

from .compiler import (
    CompilationArtifact,
    CompilationContractError,
    _canonical_json_bytes,
    _digest,
    _validate_existing_destination,
    _write_generated_tree,
    compile_verifiers_v1,
)

_TRAINING_COMPILATION_VERSION: Final = "science-prime-training-taskset/1"
_PRIME_REVISION: Final = "1e756307ae7b29c31fd202e6fac9afd7e23db18b"
_PRIME_LOCK_DIGEST: Final = (
    "sha256:44e72f78397f38e5165ed948042818b87b11f79a6cb8037ac0fd7ff92334e535"
)
_VERIFIERS_REVISION: Final = "4bcb48e55a35c199d9d2f9722060fda627306aa3"
_VERIFIERS_VERSION: Final = "0.3.1.dev59"
_RENDERER_REVISION: Final = "f770dcaa362e3a6a13a96f039741b3b84ca4114e"
_MCP_VERSION: Final = "1.27.1"
_COMPATIBILITY_PATCH_DIGEST: Final = (
    "sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3"
)
_FIND_CONTEXT_DIGEST_1_27_1: Final = (
    "bd3b1b1e92e79c56cd5b16e3c26d6306389bd701502b8297b3a9bdb8915e8d58"
)
_FIND_CONTEXT_DIGEST_1_28_1: Final = (
    "0bc2d9953e440d11f39500e1399b562243813985fa8be9dc9ffc1175aea971d6"
)
_MARKER_PATH = ".science-environment-compilation"
_MANIFEST_PATH = "manifest.json"
_RECEIPT_PATH = (
    "taskset/science-environment-runtime-dependency-receipt.json"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrimeTrainingCompilation(_FrozenModel):
    """Path-independent receipt for one prime-rl-compatible generated target."""

    compilation_version: Literal["science-prime-training-taskset/1"]
    prime_revision: Literal["1e756307ae7b29c31fd202e6fac9afd7e23db18b"]
    prime_lock_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    verifiers_revision: Literal["4bcb48e55a35c199d9d2f9722060fda627306aa3"]
    renderer_revision: Literal["f770dcaa362e3a6a13a96f039741b3b84ca4114e"]
    compatibility_patch_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bundle_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    source_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifacts: tuple[CompilationArtifact, ...]


def compile_prime_training_taskset(
    bundle: EnvironmentBundle,
    destination: str | Path,
) -> PrimeTrainingCompilation:
    """Emit a deterministic prime-rl target without weakening Runtime evidence."""

    target = Path(destination)
    if target.is_symlink():
        raise CompilationContractError(
            "generated destination cannot be a symbolic link"
        )
    _validate_existing_destination(target)
    with tempfile.TemporaryDirectory(prefix="science-prime-training-") as temporary:
        staging = Path(temporary) / "compiled"
        base_receipt = compile_verifiers_v1(bundle, staging)
        files = {
            artifact.path: (staging / artifact.path).read_bytes()
            for artifact in base_receipt.artifacts
        }
    transformed = _transform_files(files)
    _write_generated_tree(target, transformed)
    artifacts = tuple(
        CompilationArtifact(
            path=path,
            digest=_digest(contents),
            size_bytes=len(contents),
        )
        for path, contents in sorted(transformed.items())
    )
    artifact_digest = _digest(
        _canonical_json_bytes(
            [artifact.model_dump(mode="json") for artifact in artifacts]
        )
    )
    return PrimeTrainingCompilation(
        compilation_version=_TRAINING_COMPILATION_VERSION,
        prime_revision=_PRIME_REVISION,
        prime_lock_digest=_PRIME_LOCK_DIGEST,
        verifiers_revision=_VERIFIERS_REVISION,
        renderer_revision=_RENDERER_REVISION,
        compatibility_patch_digest=_COMPATIBILITY_PATCH_DIGEST,
        bundle_id=base_receipt.bundle_id,
        bundle_revision=base_receipt.bundle_revision,
        source_bundle_digest=base_receipt.source_bundle_digest,
        artifact_digest=artifact_digest,
        artifacts=artifacts,
    )


def _transform_files(files: dict[str, bytes]) -> dict[str, bytes]:
    transformed = dict(files)
    transformed["taskset/pyproject.toml"] = _training_pyproject(
        transformed["taskset/pyproject.toml"].decode()
    ).encode()
    transformed[
        "taskset/science_environment_generated/__init__.py"
    ] = _training_init().encode()
    transformed[
        "taskset/science_environment_generated/harness.py"
    ] = _training_harness().encode()
    taskset_path = "taskset/science_environment_generated/taskset.py"
    transformed[taskset_path] = _training_taskset(
        transformed[taskset_path].decode()
    ).encode()
    apparatus_path = (
        "taskset/science_environment_generated/servers/apparatus.py"
    )
    transformed[apparatus_path] = _delta_apparatus(
        transformed[apparatus_path].decode()
    ).encode()
    transport_path = (
        "taskset/science_environment_generated/_private/transport_adapter.py"
    )
    transformed[transport_path] = _training_transport(
        transformed[transport_path].decode()
    ).encode()
    transformed[_RECEIPT_PATH] = _training_dependency_receipt(
        transformed[_RECEIPT_PATH]
    )
    transformed[_MANIFEST_PATH] = _training_manifest(
        transformed[_MANIFEST_PATH]
    )
    if transformed.get(_MARKER_PATH) is None:
        raise CompilationContractError("generated training marker is missing")
    return transformed


def _training_pyproject(value: str) -> str:
    result = value.replace(
        "b878d009147876bfd1ba80feec770194f0b567c7",
        _VERIFIERS_REVISION,
    ).replace("mcp==1.28.1", f"mcp=={_MCP_VERSION}")
    if "allow-direct-references = true" not in result:
        raise CompilationContractError(
            "generated training package cannot bind direct revisions"
        )
    return result


def _training_init() -> str:
    return '''from science_environment_generated.harness import GeneratedTrainingHarness
from science_environment_generated.taskset import GeneratedEnvironmentTaskset

__all__ = ["GeneratedEnvironmentTaskset", "GeneratedTrainingHarness"]
'''


def _training_taskset(value: str) -> str:
    model_import = '''from science_environment_generated._private.model_security_adapter import (
    install_attested_eval_client_patch,
)
'''
    if value.count(model_import) != 1 or value.count(
        "install_attested_eval_client_patch()\n"
    ) != 1:
        raise CompilationContractError("generated training taskset seam drift")
    result = value.replace(model_import, "").replace(
        "install_attested_eval_client_patch()\n",
        "",
    )
    reward = '''    @vf.reward(weight=1.0)
    async def reward(self, trace: vf.Trace) -> float:
        _require_evaluation_profile(trace)
        return float(trace.state.metrics.get("reward", 0.0))
'''
    anti_degeneracy = reward + '''
    @vf.reward(weight=0.0)
    async def mechanical_jitter(self, trace: vf.Trace) -> float:
        """Disabled unless the one-step mechanics configuration opts in."""
        return int(trace.id[:12], 16) / float(16**12 - 1)
'''
    if result.count(reward) != 1:
        raise CompilationContractError("generated training reward seam drift")
    return result.replace(reward, anti_degeneracy)


def _delta_apparatus(value: str) -> str:
    replay = '''        bridge, replayable = _replay(self.state)
        try:
            replayable = bridge.apply(replayable, action)
'''
    replay_with_prior = '''        bridge, replayable = _replay(self.state)
        prior_observation = replayable.snapshot.observation
        try:
            replayable = bridge.apply(replayable, action)
'''
    full_result = '''        result = {
            "status": "ok",
            "observation": action_snapshot.observation,
        }
'''
    delta_result = '''        result = {
            "status": "ok",
            "observation_scope": "changed_fields",
            "observation": {
                key: child
                for key, child in action_snapshot.observation.items()
                if prior_observation.get(key) != child
            },
        }
'''
    if value.count(replay) != 1 or value.count(full_result) != 1:
        raise CompilationContractError("generated observation transport seam drift")
    return value.replace(replay, replay_with_prior).replace(
        full_result,
        delta_result,
    )


def _training_transport(value: str) -> str:
    result = (
        value.replace("0.3.1.dev60", _VERIFIERS_VERSION)
        .replace("1.28.1", _MCP_VERSION)
        .replace(
            _FIND_CONTEXT_DIGEST_1_28_1,
            _FIND_CONTEXT_DIGEST_1_27_1,
        )
    )
    if _VERIFIERS_VERSION not in result or _MCP_VERSION not in result:
        raise CompilationContractError("generated training transport pin drift")
    return result


def _training_harness() -> str:
    return '''"""Prime-locked null harness with stable logical MCP call identities."""

from __future__ import annotations

import json

from verifiers.v1.clients import ModelContext
from verifiers.v1.dialects.chat import message_to_wire
from verifiers.v1.harnesses.null.harness import (
    PROGRAM_SOURCE as PINNED_NULL_PROGRAM_SOURCE,
    NullHarness,
)
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.task import TaskData
from verifiers.v1.trace import Trace

import science_environment_generated._private.transport_adapter as _transport

_transport.assert_native_compatibility(PINNED_NULL_PROGRAM_SOURCE)
# The isolated remote harness uses Verifiers' opaque ephemeral loopback secret.
# It is never persisted; product imports and host material remain unavailable.
_transport._SECRET_REPLACEMENTS = ()
PROGRAM_SOURCE = _transport.patched_null_program(PINNED_NULL_PROGRAM_SOURCE)


class GeneratedTrainingHarness(NullHarness):
    async def setup(self, runtime: Runtime) -> None:
        await runtime.prepare_uv_script(PROGRAM_SOURCE, self.config.resolved_env)

    async def launch(
        self,
        ctx: ModelContext,
        trace: Trace,
        runtime: Runtime,
        endpoint: str,
        secret: str,
        mcp_urls: dict[str, str],
        data: TaskData,
    ) -> ProgramResult:
        system_prompt, prompt = self.resolve_prompt(data)
        env = {**self.config.resolved_env}
        args = [
            f"--base-url={endpoint}",
            f"--api-key={secret}",
            f"--model={ctx.model}",
        ]
        if system_prompt:
            args.append(f"--system-prompt={system_prompt}")
        if mcp_urls:
            args.append(
                "--mcp-config="
                + json.dumps(
                    {
                        "mcpServers": {
                            name: {
                                "url": url,
                                "timeout": self.config.tool_timeout,
                            }
                            for name, url in mcp_urls.items()
                        }
                    }
                )
            )
        if isinstance(prompt, str):
            args.append(f"--prompt={prompt}")
        elif prompt is not None:
            path = f".vf-initial-messages-{trace.id}.json"
            await runtime.write(
                path,
                json.dumps([message_to_wire(message) for message in prompt]).encode(),
            )
            args.append(f"--initial-messages-file={path}")
        program = await runtime.prepare_uv_script(
            PROGRAM_SOURCE,
            self.config.resolved_env,
        )
        return await runtime.run_program([*program, *args], env)
'''


def _training_dependency_receipt(value: bytes) -> bytes:
    document = json.loads(value)
    document["receipt_version"] = (
        "science-environment-prime-training-dependency-receipt/1"
    )
    document["verifiers"] = {
        "repository": "https://github.com/PrimeIntellect-ai/verifiers.git",
        "requirement": (
            "verifiers @ git+https://github.com/PrimeIntellect-ai/"
            f"verifiers.git@{_VERIFIERS_REVISION}"
        ),
        "revision": _VERIFIERS_REVISION,
        "distribution_version": _VERIFIERS_VERSION,
    }
    document["native_adapter"]["transport_idempotency"][
        "mcp_version"
    ] = _MCP_VERSION
    document["native_adapter"]["transport_idempotency"][
        "mcp_source_digests"
    ]["find_context_parameter"] = f"sha256:{_FIND_CONTEXT_DIGEST_1_27_1}"
    document["training_profile"] = {
        "prime_revision": _PRIME_REVISION,
        "prime_lock_digest": _PRIME_LOCK_DIGEST,
        "renderer_revision": _RENDERER_REVISION,
        "compatibility_patch_digest": _COMPATIBILITY_PATCH_DIGEST,
        "observation_transport": "changed-top-level-fields-v1",
        "mechanical_jitter_default_weight": 0.0,
    }
    document["closure"] = {
        "scope": "prime-locked-workstation-training",
        "status": "closed-by-prime-lock",
    }
    return _canonical_json_bytes(document)


def _training_manifest(value: bytes) -> bytes:
    document = json.loads(value)
    document["disposition"] = "generated_disposable_training_target"
    document["verifiers_revision"] = _VERIFIERS_REVISION
    document["integration_profile"] = {
        "id": _TRAINING_COMPILATION_VERSION,
        "prime_revision": _PRIME_REVISION,
        "prime_lock_digest": _PRIME_LOCK_DIGEST,
        "renderer_revision": _RENDERER_REVISION,
        "compatibility_patch_digest": _COMPATIBILITY_PATCH_DIGEST,
    }
    return _canonical_json_bytes(document)


__all__ = [
    "PrimeTrainingCompilation",
    "compile_prime_training_taskset",
]
