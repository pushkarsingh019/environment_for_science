"""Deterministic compiler from Environment Bundle v1 to Verifiers v1 artifacts.

The authored bundle remains authoritative.  Everything emitted here is a
content-addressed, disposable integration target for the separately installed
and pinned Verifiers runtime.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import math
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from studio.bundle import EnvironmentBundle, validate_environment_bundle

from .artifact_safety import ArtifactSafetyError, validate_artifact_safe

_COMPILATION_VERSION: Final = "science-environment-verifiers-v1/1"
_VERIFIERS_REVISION: Final = "b878d009147876bfd1ba80feec770194f0b567c7"
_VERIFIERS_REPOSITORY: Final = "https://github.com/PrimeIntellect-ai/verifiers.git"
_VERIFIERS_REQUIREMENT: Final = (
    f"verifiers @ git+{_VERIFIERS_REPOSITORY}@{_VERIFIERS_REVISION}"
)
_PRODUCT_VERSION: Final = "0.1.0"
_MODEL_ID: Final = "google/gemma-4-E4B-it"
_MODEL_REVISION: Final = "ee0ef6023621cff504d758262d4e04895a5af4a2"
_MODEL_ADAPTER_REVISION: Final = "local-gemma-openai-chat/1"
_EVALUATION_PROFILE: Final = "base-gemma-development-chat-v1"
_MAX_TURNS: Final = 64
_MAX_ACCEPTED_TOOL_CALLS: Final = 64
_MAX_PROVIDER_TOOL_CALLS: Final = 64
_MAX_EPISODE_SECONDS: Final = 900
_FRAMEWORK_MAX_TURNS_SENTINEL: Final = _MAX_TURNS + 1
_MCP_VERSION: Final = "1.28.1"
_VERIFIERS_DISTRIBUTION_VERSION: Final = "0.3.1.dev60"
_PINNED_NULL_PROGRAM_DIGEST: Final = (
    "2daa71fe0fae8a82add30f6bda571fa08902d0d3c05fbc30373c4a41e27cdade"
)
_PINNED_NULL_SETUP_DIGEST: Final = (
    "486b9b050758fa6aaf405631b6403699b557455f125f7623577272730f8c633c"
)
_PINNED_NULL_LAUNCH_DIGEST: Final = (
    "aa23438ce3adc35467f88de3c51482a68c5a82a6df8ff3d4346b4a6d213cc191"
)
_PINNED_MCP_SOURCE_DIGESTS: Final = {
    "BaseSession.send_request": (
        "f265e17c157909872b3ea72a6d474e194bf356571c7d3f803dee3a47ceb2e35b"
    ),
    "ClientSession.call_tool": (
        "22f4e346e0a84f40bc80f8e1de5948ed22180d4d438efed89a04799f4ab2b538"
    ),
    "Context.request_id": (
        "d11024841e75ab41a8ced1cfb0481bf341d8f67491c4d383b3513d67420a2844"
    ),
    "find_context_parameter": (
        "0bc2d9953e440d11f39500e1399b562243813985fa8be9dc9ffc1175aea971d6"
    ),
}
_PINNED_EVAL_CLIENT_SOURCE_DIGESTS: Final = {
    "EvalClient.__init__": (
        "06b8c9598bb5037a0f3ea59404e030f5bcd87ac42d6df20bd5b7dc0e761ff4eb"
    ),
    "EvalClient._request": (
        "28f6fb95c68cecd143cd9afa1934288d20b64261f18275946e3d8fabc22adb54"
    ),
    "EvalClient.get_response": (
        "f724416d6a8015a1d0f27e1c059070a587e551b7d89d5e07c9db5ceaa712396b"
    ),
}
_MARKER_PATH = ".science-environment-compilation"
_MARKER_BYTES = b"science-environment-verifiers-v1/1\n"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Public instance/class surface of ``vf.Toolset`` at the pinned Verifiers
# revision. ``config`` is assigned by ``ServerBase.__init__``; the remaining
# names are inherited descriptors that generated action methods must not mask.
_RESERVED_ACTION_NAMES = {
    "config",
    "register",
    "run",
    "server_name",
    "setup",
    "setup_task",
    "state",
}
_RESERVED_METRIC_NAMES = {
    "config",
    "config_type",
    "data",
    "data_type",
    "finalize",
    "hash",
    "hooks",
    "key",
    "plugged_judges",
    "reward",
    "runtime_env",
    "score",
    "setup",
    "terminal",
    "toolsets",
    "turn_budget",
    "validate",
    "with_system_prompt",
}
_ALLOWED_PROPERTY_KEYS = {
    "description",
    "enum",
    "maximum",
    "maxLength",
    "minimum",
    "minLength",
    "type",
}
_SCALAR_TYPES = {"boolean", "integer", "number", "string"}


class CompilationContractError(ValueError):
    """Raised when a bundle cannot be emitted as a safe disposable target."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompilationArtifact(_FrozenModel):
    """One relative, content-addressed file in a generated compilation."""

    path: str = Field(min_length=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("artifact path must be a normalized relative path")
        return value


class VerifiersCompilation(_FrozenModel):
    """Path-independent receipt for one deterministic generated tree."""

    compilation_version: Literal["science-environment-verifiers-v1/1"]
    verifiers_revision: Literal["b878d009147876bfd1ba80feec770194f0b567c7"]
    model_id: Literal["google/gemma-4-E4B-it"]
    model_revision: Literal["ee0ef6023621cff504d758262d4e04895a5af4a2"]
    bundle_id: str = Field(min_length=1)
    bundle_revision: str = Field(min_length=1)
    source_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifacts: tuple[CompilationArtifact, ...]


def compile_verifiers_v1(
    bundle: EnvironmentBundle,
    destination: str | Path,
) -> VerifiersCompilation:
    """Compile ``bundle`` into an exact, endpoint-free Verifiers v1 target."""

    if not isinstance(bundle, EnvironmentBundle):
        raise CompilationContractError("compiler input must be a validated Environment Bundle")
    # Reject unsafe provider surfaces before the defensive whole-bundle pass so
    # callers get the compiler-boundary error even if a mutable Bundle object
    # was changed in a way that also breaks procedure references.
    _validate_provider_safe_actions(bundle)
    _validate_provider_safe_metrics(bundle)
    # Revalidate a defensive copy because the product Bundle model deliberately
    # permits compatible minor-version metadata and is not itself frozen.
    validated = validate_environment_bundle(bundle.model_dump(mode="json"))
    _validate_provider_safe_actions(validated)
    _validate_provider_safe_metrics(validated)
    source_document = validated.model_dump(mode="json", exclude_none=True)
    try:
        validate_artifact_safe(source_document)
    except ArtifactSafetyError:
        raise CompilationContractError(
            "Environment Bundle contains endpoint, credential, private-host, or "
            "host-path material"
        ) from None

    target = Path(destination)
    if target.is_symlink():
        raise CompilationContractError("generated destination cannot be a symbolic link")
    _validate_existing_destination(target)

    source_bytes = _canonical_json_bytes(source_document)
    source_digest = _digest(source_bytes)
    files = _render_files(validated, source_bytes, source_digest)
    _write_generated_tree(target, files)
    return _receipt(validated, source_digest, files)


def _validate_provider_safe_actions(bundle: EnvironmentBundle) -> None:
    for action in bundle.actions:
        if (
            _IDENTIFIER_PATTERN.fullmatch(action.type) is None
            or keyword.iskeyword(action.type)
            or action.type in _RESERVED_ACTION_NAMES
        ):
            raise CompilationContractError(
                f"{action.type!r} is not a provider-safe action name"
            )
        schema = action.input_schema
        if not _is_provider_safe_object_schema(schema):
            raise CompilationContractError(
                f"action {action.type!r} does not use a provider-safe action schema"
            )


def _validate_provider_safe_metrics(bundle: EnvironmentBundle) -> None:
    metrics = bundle.metrics
    if len(metrics) != len(set(metrics)) or any(
        _IDENTIFIER_PATTERN.fullmatch(metric) is None
        or keyword.iskeyword(metric)
        or (metric != "reward" and metric in _RESERVED_METRIC_NAMES)
        for metric in metrics
    ):
        raise CompilationContractError(
            "Environment metrics must use unique provider-safe metric names"
        )


def _is_provider_safe_object_schema(schema: Mapping[str, Any]) -> bool:
    if (
        set(schema).difference(
            {"type", "properties", "required", "additionalProperties"}
        )
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        return False
    properties = schema.get("properties")
    required = schema.get("required", [])
    if (
        not isinstance(properties, dict)
        or not isinstance(required, list)
        or len(required) != len(set(required))
        or any(not isinstance(name, str) for name in required)
        or not set(required).issubset(properties)
    ):
        return False
    for name, definition in properties.items():
        if (
            not isinstance(name, str)
            or _IDENTIFIER_PATTERN.fullmatch(name) is None
            or keyword.iskeyword(name)
            or name in {"self", "context"}
            or not isinstance(definition, dict)
            or set(definition).difference(_ALLOWED_PROPERTY_KEYS)
            or definition.get("type") not in _SCALAR_TYPES
            or not _valid_scalar_constraints(definition)
        ):
            return False
    return True


def _valid_scalar_constraints(definition: Mapping[str, Any]) -> bool:
    scalar_type = definition.get("type")
    enum = definition.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum or len(enum) != len({_json_key(v) for v in enum}):
            return False
        if any(not _value_matches_type(value, scalar_type) for value in enum):
            return False
    for key in ("minimum", "maximum"):
        if key in definition and (
            scalar_type not in {"integer", "number"}
            or not _value_matches_type(definition[key], scalar_type)
        ):
            return False
    for key in ("minLength", "maxLength"):
        value = definition.get(key)
        if value is not None and (
            scalar_type != "string" or not isinstance(value, int) or value < 0
        ):
            return False
    minimum = definition.get("minimum")
    maximum = definition.get("maximum")
    min_length = definition.get("minLength")
    max_length = definition.get("maxLength")
    return not (
        minimum is not None and maximum is not None and minimum > maximum
    ) and not (
        min_length is not None and max_length is not None and min_length > max_length
    )


def _value_matches_type(value: object, scalar_type: object) -> bool:
    if scalar_type == "boolean":
        return isinstance(value, bool)
    if scalar_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if scalar_type == "number":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            or isinstance(value, float)
            and math.isfinite(value)
        )
    return scalar_type == "string" and isinstance(value, str)


def _json_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _render_files(
    bundle: EnvironmentBundle,
    source_bytes: bytes,
    source_digest: str,
) -> dict[str, bytes]:
    catalog_document = _task_catalog(bundle)
    catalog_bytes = _canonical_json_bytes(catalog_document)
    paths = (
        _MARKER_PATH,
        "configs/eval.toml",
        "manifest.json",
        "source/environment-bundle.json",
        "taskset/pyproject.toml",
        "taskset/science-environment-runtime-dependency-receipt.json",
        "taskset/science_environment_generated/__init__.py",
        "taskset/science_environment_generated/harness.py",
        "taskset/science_environment_generated/_private/__init__.py",
        "taskset/science_environment_generated/_private/environment-bundle.json",
        "taskset/science_environment_generated/_private/task-catalog.json",
        "taskset/science_environment_generated/_private/model_security_adapter.py",
        "taskset/science_environment_generated/_private/transport_adapter.py",
        "taskset/science_environment_generated/servers/__init__.py",
        "taskset/science_environment_generated/servers/apparatus.py",
        "taskset/science_environment_generated/taskset.py",
        "taskset/task-catalog.json",
    )
    manifest = {
        "manifest_version": _COMPILATION_VERSION,
        "authored_source": "Environment Bundle v1",
        "disposition": "generated_disposable",
        "bundle_id": bundle.bundle_id,
        "bundle_revision": bundle.bundle_revision,
        "source_bundle_digest": source_digest,
        "verifiers_revision": _VERIFIERS_REVISION,
        "model": {
            "id": _MODEL_ID,
            "revision": _MODEL_REVISION,
            "adapter_revision": _MODEL_ADAPTER_REVISION,
        },
        "evaluation_profile": {
            "id": _EVALUATION_PROFILE,
            "adapter_revision": _MODEL_ADAPTER_REVISION,
            "budgets": {
                "max_turns": _MAX_TURNS,
                "max_accepted_tool_calls": _MAX_ACCEPTED_TOOL_CALLS,
                "max_provider_tool_calls": _MAX_PROVIDER_TOOL_CALLS,
                "max_episode_seconds": _MAX_EPISODE_SECONDS,
            },
            "timeout_outcome": "framework_infrastructure_unscored",
        },
        "runtime_dependency_receipt": (
            "taskset/science-environment-runtime-dependency-receipt.json"
        ),
        "artifact_paths": list(paths),
    }
    files = {
        _MARKER_PATH: _MARKER_BYTES,
        "configs/eval.toml": _eval_toml(bundle).encode(),
        "manifest.json": _canonical_json_bytes(manifest),
        "source/environment-bundle.json": source_bytes,
        "taskset/pyproject.toml": _taskset_pyproject().encode(),
        "taskset/science-environment-runtime-dependency-receipt.json": (
            _canonical_json_bytes(_runtime_dependency_receipt())
        ),
        "taskset/science_environment_generated/__init__.py": (
            b"from science_environment_generated.harness import GeneratedNullHarness\n"
            b"from science_environment_generated.taskset import "
            b"GeneratedEnvironmentTaskset\n\n"
            b'__all__ = ["GeneratedEnvironmentTaskset", "GeneratedNullHarness"]\n'
        ),
        "taskset/science_environment_generated/harness.py": _harness_module().encode(),
        "taskset/science_environment_generated/_private/__init__.py": (
            b'"""Private generated native-adapter resources."""\n'
        ),
        "taskset/science_environment_generated/_private/environment-bundle.json": (
            source_bytes
        ),
        "taskset/science_environment_generated/_private/task-catalog.json": catalog_bytes,
        "taskset/science_environment_generated/_private/model_security_adapter.py": (
            _model_security_adapter_module().encode()
        ),
        "taskset/science_environment_generated/_private/transport_adapter.py": (
            _transport_adapter_module().encode()
        ),
        "taskset/science_environment_generated/servers/__init__.py": (
            b"from science_environment_generated.servers.apparatus import "
            b"ApparatusState, ApparatusToolset\n\n"
            b'__all__ = ["ApparatusState", "ApparatusToolset"]\n'
        ),
        "taskset/science_environment_generated/servers/apparatus.py": (
            _apparatus_module(bundle).encode()
        ),
        "taskset/science_environment_generated/taskset.py": _taskset_module(bundle).encode(),
        "taskset/task-catalog.json": catalog_bytes,
    }
    if tuple(sorted(files)) != tuple(sorted(paths)):
        raise CompilationContractError("internal generated manifest path mismatch")
    return files


def _task_catalog(bundle: EnvironmentBundle) -> dict[str, Any]:
    objective = (
        f"Work only inside {bundle.simulation_label}. "
        "Use the declared simulated-Apparatus actions to inspect visible evidence and "
        "reach an evidence-supported terminal decision."
    )
    tasks = []
    for index, scenario in enumerate(bundle.scenarios):
        observation = scenario.initial_state.policy_visible
        prompt = (
            f"{objective}\nScenario: {scenario.id}\n"
            f"Initial declared observation: {_canonical_json_text(observation)}"
        )
        tasks.append(
            {
                "idx": index,
                "name": scenario.id,
                "scenario_id": scenario.id,
                "split": scenario.split,
                "prompt": prompt,
                "initial_observation": observation,
            }
        )
    return {
        "catalog_version": "science-environment-task-catalog/1",
        "bundle_id": bundle.bundle_id,
        "bundle_revision": bundle.bundle_revision,
        "actions": [
            {
                "name": action.type,
                "title": action.title,
                "description": action.description,
                "input_schema": action.input_schema,
            }
            for action in bundle.actions
        ],
        "tasks": tasks,
    }


def _taskset_pyproject() -> str:
    return f'''[project]
name = "science-environment-generated"
version = "0.1.0"
description = "Disposable native Verifiers v1 target generated from Environment Bundle v1."
requires-python = ">=3.11,<3.14"
dependencies = [
  "{_VERIFIERS_REQUIREMENT}",
  "mcp=={_MCP_VERSION}",
  "science-environment-studio=={_PRODUCT_VERSION}",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.metadata]
allow-direct-references = true

[tool.hatch.build.targets.wheel]
packages = ["science_environment_generated"]

[tool.science-environment.target]
verifiers-revision = "{_VERIFIERS_REVISION}"
runtime-dependency-receipt = "science-environment-runtime-dependency-receipt.json"
'''


def _runtime_dependency_receipt() -> dict[str, Any]:
    """Honest direct-dependency receipt for development calibration.

    This is deliberately not described as a closed transitive lock.  Held-out
    execution remains gated on a content-addressed product wheel and a fully
    resolved environment/container lock.
    """

    return {
        "receipt_version": "science-environment-native-runtime-dependency-receipt/1",
        "python": {"requires": ">=3.11,<3.14"},
        "verifiers": {
            "repository": _VERIFIERS_REPOSITORY,
            "requirement": _VERIFIERS_REQUIREMENT,
            "revision": _VERIFIERS_REVISION,
        },
        "product_runtime": {
            "distribution": "science-environment-studio",
            "version": _PRODUCT_VERSION,
        },
        "evaluation_profile": {
            "id": _EVALUATION_PROFILE,
            "adapter_revision": _MODEL_ADAPTER_REVISION,
            "max_turns": _MAX_TURNS,
            "max_accepted_tool_calls": _MAX_ACCEPTED_TOOL_CALLS,
            "max_provider_tool_calls": _MAX_PROVIDER_TOOL_CALLS,
            "max_episode_seconds": _MAX_EPISODE_SECONDS,
            "sampling": {
                "temperature": 0.0,
                "max_tokens": 2048,
                "tool_choice": "auto",
                "top_p": None,
                "seed": None,
                "streaming": False,
                "store": False,
            },
        },
        "native_adapter": {
            "effective_max_turns": _MAX_TURNS,
            "framework_max_turns_sentinel": _FRAMEWORK_MAX_TURNS_SENTINEL,
            "max_accepted_tool_calls": _MAX_ACCEPTED_TOOL_CALLS,
            "max_provider_tool_calls": _MAX_PROVIDER_TOOL_CALLS,
            "timeout_outcome": "framework_infrastructure_unscored",
            "transport_idempotency": {
                "protocol": "episode-scoped-jsonrpc-request-id-v1",
                "mcp_version": _MCP_VERSION,
                "upstream_null_program_digest": (
                    f"sha256:{_PINNED_NULL_PROGRAM_DIGEST}"
                ),
                "upstream_null_setup_digest": f"sha256:{_PINNED_NULL_SETUP_DIGEST}",
                "upstream_null_launch_digest": f"sha256:{_PINNED_NULL_LAUNCH_DIGEST}",
                "mcp_source_digests": {
                    name: f"sha256:{digest}"
                    for name, digest in _PINNED_MCP_SOURCE_DIGESTS.items()
                },
            },
        },
        "closure": {
            "scope": "development_calibration",
            "status": "open",
            "required_before_heldout": [
                "content-addressed product wheel digest",
                "full resolved environment or container lock",
            ],
        },
    }


def _eval_toml(bundle: EnvironmentBundle) -> str:
    split = bundle.split_identities[0]
    return f'''# Generated and disposable. Supply the private inference route at launch time.
model = "{_MODEL_ID}"
num_tasks = {len(bundle.scenarios)}
num_rollouts = 1
max_concurrent = 4
server = true
rich = false
push = false

[run]
name = "base-gemma-{_toml_fragment(split)}-calibration"

[client]
type = "eval"

[sampling]
temperature = 0.0
max_tokens = 2048

[env.taskset]
id = "science-environment-generated"
split = "{_toml_fragment(split)}"

[env.agent]
max_turns = {_FRAMEWORK_MAX_TURNS_SENTINEL}

[env.agent.timeout]
rollout = {_MAX_EPISODE_SECONDS}

[env.agent.harness]
id = "science-environment-generated"
forward_env = [
    "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY",
    "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256",
    "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256",
    "SCIENCE_LOCAL_GEMMA_UNIX_SOCKET",
]

[env.agent.runtime]
type = "subprocess"
'''


def _model_security_adapter_module() -> str:
    return f'''"""Pinned native Verifiers provider-response security adapter.

The native null harness talks to a loopback interception server.  This module
guards the actual EvalClient provider seam so signed runtime identity and
artifact-safety checks happen before provider bytes can enter a trace.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os

import httpx
from pydantic_core import to_json
from verifiers.v1.clients.client import SESSION_ID_HEADER
from verifiers.v1.clients.base import DEFAULT_LIMITS, DEFAULT_TIMEOUT
from verifiers.v1.clients.eval import EvalClient
from verifiers.v1.configs.client import BaseClientConfig, resolve_api_key
from verifiers.v1.errors import model_error

from studio.policy_evaluation.artifact_safety import (
    ArtifactSafetyError,
    validate_artifact_safe,
)
from studio.policy_evaluation.local_gemma import validated_private_unix_socket

_EXPECTED_VERIFIERS_VERSION = {_VERIFIERS_DISTRIBUTION_VERSION!r}
_PINNED_SOURCES = {_PINNED_EVAL_CLIENT_SOURCE_DIGESTS!r}
_RUNTIME_INSTANCE_HEADER = "x-science-runtime-instance"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_PROVIDER_TOOL_CALLS = {_MAX_PROVIDER_TOOL_CALLS}
_ATTESTED_SESSIONS: dict[str, str] = {{}}
_PROVIDER_TOOL_CALL_COUNTS: dict[str, int] = {{}}


def _source_digest(value) -> str:
    return hashlib.sha256(inspect.getsource(value).encode()).hexdigest()


def _assert_compatible() -> None:
    from importlib.metadata import version as distribution_version

    if distribution_version("verifiers") != _EXPECTED_VERIFIERS_VERSION:
        raise RuntimeError("generated model adapter Verifiers compatibility drift")
    actual = {{
        "EvalClient.__init__": _source_digest(EvalClient.__init__),
        "EvalClient._request": _source_digest(EvalClient._request),
        "EvalClient.get_response": _source_digest(EvalClient.get_response),
    }}
    if actual != _PINNED_SOURCES:
        raise RuntimeError("generated model adapter source compatibility drift")


def register_attested_session(session_id: str, runtime_instance_id: str) -> None:
    if not session_id or len(runtime_instance_id) != 64:
        raise RuntimeError("attested model session registration is invalid")
    if session_id in _ATTESTED_SESSIONS:
        raise RuntimeError("attested model session is already registered")
    _ATTESTED_SESSIONS[session_id] = runtime_instance_id
    _PROVIDER_TOOL_CALL_COUNTS[session_id] = 0


def unregister_attested_session(session_id: str) -> None:
    _ATTESTED_SESSIONS.pop(session_id, None)
    _PROVIDER_TOOL_CALL_COUNTS.pop(session_id, None)


def _secured_init(self: EvalClient, config: BaseClientConfig) -> None:
    self.base_url = config.base_url
    self.api_key = resolve_api_key(config)
    self.headers = dict(config.headers or {{}})
    socket_path, socket_identity = validated_private_unix_socket(
        os.environ.get("SCIENCE_LOCAL_GEMMA_UNIX_SOCKET", "")
    )
    self._science_socket_path = socket_path
    self._science_socket_identity = socket_identity
    self.client = httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.AsyncHTTPTransport(
            uds=socket_path,
            limits=DEFAULT_LIMITS,
        ),
    )


def _contains_forbidden_material(value, forbidden: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_forbidden_material(key, forbidden)
            or _contains_forbidden_material(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_material(child, forbidden) for child in value)
    if not isinstance(value, str):
        return False
    return any(material and material in value for material in forbidden)


def _provider_tool_call_count(document: object) -> int:
    if not isinstance(document, dict):
        return 0
    choices = document.get("choices")
    if not isinstance(choices, list):
        return 0
    count = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            continue
        if not isinstance(tool_calls, list):
            raise ValueError("provider tool_calls value is invalid")
        count += len(tool_calls)
    return count


async def _read_bounded(response: httpx.Response) -> bytes:
    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise ValueError("provider response length is invalid") from error
        if parsed_length < 0 or parsed_length > _MAX_RESPONSE_BYTES:
            raise ValueError("provider response length is invalid")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("provider response length is invalid")
    return bytes(body)


async def _secured_request(
    self: EvalClient,
    url: str,
    body: dict,
    headers: httpx.Headers,
    *,
    stream: bool = False,
) -> httpx.Response:
    if stream or not url.endswith("/chat/completions"):
        raise model_error("unapproved local Gemma provider route", status_code=400)
    _path, socket_identity = validated_private_unix_socket(
        self._science_socket_path
    )
    if socket_identity != self._science_socket_identity:
        raise model_error("authorized Unix socket identity changed", status_code=503)
    headers.setdefault("content-type", "application/json")
    request = self.client.build_request(
        "POST",
        url,
        content=to_json(body, inf_nan_mode="null"),
        headers=headers,
    )
    try:
        response = await self.client.send(request, stream=True)
    except httpx.TimeoutException as error:
        raise model_error("local Gemma provider timed out", status_code=504) from error
    except (httpx.HTTPError, ConnectionResetError) as error:
        raise model_error("local Gemma provider unavailable", status_code=503) from error
    try:
        content = await _read_bounded(response)
    except ValueError as error:
        raise model_error("unsafe local Gemma response rejected", status_code=502) from error
    finally:
        await response.aclose()
    if response.status_code >= 400:
        raise model_error(
            f"local Gemma provider returned HTTP {{response.status_code}}",
            status_code=response.status_code,
        )
    session_id = headers.get(SESSION_ID_HEADER)
    expected_runtime_instance = _ATTESTED_SESSIONS.get(session_id or "")
    if (
        expected_runtime_instance is None
        or response.headers.get(_RUNTIME_INSTANCE_HEADER)
        != expected_runtime_instance
    ):
        raise model_error(
            "attested local Gemma runtime response binding failed",
            status_code=502,
        )
    try:
        document = json.loads(content)
        validate_artifact_safe(document)
    except (ArtifactSafetyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise model_error("unsafe local Gemma response rejected", status_code=502) from error
    if _contains_forbidden_material(document, (self.api_key, self.base_url)):
        raise model_error("unsafe local Gemma response rejected", status_code=502)
    provider_tool_call_count = _PROVIDER_TOOL_CALL_COUNTS.get(session_id or "")
    if provider_tool_call_count is None:
        raise model_error(
            "attested local Gemma runtime response binding failed",
            status_code=502,
        )
    try:
        next_provider_tool_call_count = (
            provider_tool_call_count + _provider_tool_call_count(document)
        )
    except ValueError as error:
        raise model_error("unsafe local Gemma response rejected", status_code=502) from error
    if next_provider_tool_call_count > _MAX_PROVIDER_TOOL_CALLS:
        raise model_error(
            "local Gemma provider tool-call budget exceeded",
            status_code=502,
        )
    _path, final_socket_identity = validated_private_unix_socket(
        self._science_socket_path
    )
    if final_socket_identity != self._science_socket_identity:
        raise model_error("authorized Unix socket identity changed", status_code=503)
    _PROVIDER_TOOL_CALL_COUNTS[session_id or ""] = next_provider_tool_call_count
    return httpx.Response(
        status_code=response.status_code,
        headers=response.headers,
        content=content,
        request=request,
    )


def install_attested_eval_client_patch() -> None:
    if EvalClient.__init__ is _secured_init and EvalClient._request is _secured_request:
        return
    _assert_compatible()
    EvalClient.__init__ = _secured_init
    EvalClient._request = _secured_request
'''


def _transport_adapter_module() -> str:
    original_dependency = (
        'dependencies = ["openai", "mcp>=1.24.0,<2", "httpx", "tenacity"]'
    )
    pinned_dependency = (
        f'dependencies = ["openai", "mcp=={_MCP_VERSION}", "httpx", "tenacity"]'
    )
    original_call = '''async def call_mcp(
    servers: dict, dispatch: dict, name: str, arguments: dict
) -> str | list[dict]:
    """Call a tool on a fresh session per attempt — see `with_retry` for the replay semantics.
    The result is converted outside the retry so a conversion failure fails once."""
    server_name, raw = dispatch[name]

    async def call():
        async with mcp_session(servers[server_name]) as session:
            return await session.call_tool(raw, arguments)

    result = await with_retry(call)
    return mcp_content_to_chat_content(result.content)
'''
    patched_call = f'''_LOGICAL_CALL_ORDINAL = 0
_TRANSPORT_REQUEST_ID_BASE = 1_000_000
_EXPECTED_MCP_VERSION = {_MCP_VERSION!r}


def _canonical_tool_error(error_code: str) -> str:
    return json.dumps(
        {{"status": "error", "error_code": error_code}},
        sort_keys=True,
        separators=(",", ":"),
    )


def _assert_transport_session(session) -> None:
    from importlib.metadata import version as distribution_version

    if distribution_version("mcp") != _EXPECTED_MCP_VERSION:
        raise RuntimeError("generated transport adapter MCP compatibility drift")
    # The pinned client consumes integer request 0 during initialize().  This
    # adapter owns the next ID so a retry can replay one logical call under the
    # same transport identity.  No public request-ID seam exists at this pin.
    if type(session._request_id) is not int or session._request_id != 1:
        raise RuntimeError("generated transport adapter request-ID compatibility drift")


async def call_mcp(
    servers: dict, dispatch: dict, name: str, arguments: dict
) -> str | list[dict]:
    """Dispatch one logical call under a stable provider-independent request ID."""
    global _LOGICAL_CALL_ORDINAL

    server_name, raw = dispatch[name]
    _LOGICAL_CALL_ORDINAL += 1
    transport_request_id = _TRANSPORT_REQUEST_ID_BASE + _LOGICAL_CALL_ORDINAL

    async def call():
        async with mcp_session(servers[server_name]) as session:
            _assert_transport_session(session)
            session._request_id = transport_request_id
            return await session.call_tool(raw, arguments)

    result = await with_retry(call)
    if result.isError:
        return _canonical_tool_error("tool.invalid_arguments")
    return mcp_content_to_chat_content(result.content)
'''
    error_replacements = (
        (
            'f"error: invalid JSON in tool arguments ({e}); resend the call with valid JSON"',
            '_canonical_tool_error("tool.invalid_arguments")',
        ),
        (
            'f"error: tool arguments must be a JSON object, got '
            '{type(tool_args).__name__}; resend as an object"',
            '_canonical_tool_error("tool.invalid_arguments")',
        ),
        (
            'f"error: unknown tool {name!r}"',
            '_canonical_tool_error("tool.unknown_action")',
        ),
    )
    secret_replacements = (
        (
            '"""The interception endpoint and secret arrive through argv rather '
            'than the environment."""',
            '"""The interception endpoint arrives through argv; its secret arrives '
            'through the environment."""',
        ),
        (
            "import json\nfrom contextlib",
            "import json\nimport os\nfrom contextlib",
        ),
        (
            "from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter\n",
            "from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter\n\n"
            "from studio.policy_evaluation.artifact_safety import (\n"
            "    ArtifactSafetyError,\n"
            "    validate_artifact_safe,\n"
            ")\n",
        ),
        ('    parser.add_argument("--api-key", required=True)\n', ""),
        (
            "        api_key=args.api_key,\n",
            '        api_key=os.environ.pop("SCIENCE_MODEL_API_KEY"),\n',
        ),
        (
            '''    client = AsyncOpenAI(
        base_url=args.base_url,
        api_key=os.environ.pop("SCIENCE_MODEL_API_KEY"),
        timeout=httpx.Timeout(None, connect=5.0),
    )
''',
            '''    api_key = os.environ.pop("SCIENCE_MODEL_API_KEY")
    forbidden_response_material = (api_key, args.base_url)

    def contains_forbidden_material(value) -> bool:
        if isinstance(value, dict):
            return any(
                contains_forbidden_material(key)
                or contains_forbidden_material(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return any(contains_forbidden_material(child) for child in value)
        if not isinstance(value, str):
            return False
        return any(material and material in value for material in forbidden_response_material)

    async def verify_attested_response(response: httpx.Response) -> None:
        if not response.request.url.path.endswith("/chat/completions"):
            raise httpx.ProtocolError("unexpected model response route")
        declared_length = response.headers.get("content-length")
        if declared_length is not None:
            try:
                length = int(declared_length)
            except ValueError as error:
                raise httpx.ProtocolError("invalid model response length") from error
            if length < 0 or length > 4 * 1024 * 1024:
                raise httpx.ProtocolError("invalid model response length")
        body = await response.aread()
        if len(body) > 4 * 1024 * 1024:
            raise httpx.ProtocolError("invalid model response length")
        try:
            document = json.loads(body)
            validate_artifact_safe(document)
        except (ArtifactSafetyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise httpx.ProtocolError("unsafe model response rejected") from error
        if contains_forbidden_material(document):
            raise httpx.ProtocolError("unsafe model response rejected")

    http_client = httpx.AsyncClient(
        event_hooks={"response": [verify_attested_response]},
        follow_redirects=False,
        timeout=httpx.Timeout(None, connect=5.0),
        trust_env=False,
    )
    client = AsyncOpenAI(
        base_url=args.base_url,
        api_key=api_key,
        http_client=http_client,
        max_retries=0,
    )
''',
        ),
    )
    return f'''"""Pinned compatibility shim for the disposable generated null harness.

The exact Verifiers null harness reconnects for every MCP call and retry, so
its ClientSession restarts JSON-RPC numbering and every tool request otherwise
arrives as request 1.  That cannot distinguish a retry from a later scientific
action.  This module verifies the exact audited sources, then patches only the
logical-call dispatch seam.  Drift fails closed before the harness launches.
"""

from __future__ import annotations

import hashlib
import inspect
from importlib.metadata import version as distribution_version

_EXPECTED_VERIFIERS_VERSION = {_VERIFIERS_DISTRIBUTION_VERSION!r}
_EXPECTED_MCP_VERSION = {_MCP_VERSION!r}
_PINNED_NULL_PROGRAM_DIGEST = {_PINNED_NULL_PROGRAM_DIGEST!r}
_PINNED_NULL_SETUP_DIGEST = {_PINNED_NULL_SETUP_DIGEST!r}
_PINNED_NULL_LAUNCH_DIGEST = {_PINNED_NULL_LAUNCH_DIGEST!r}
_PINNED_MCP_SOURCE_DIGESTS = {_PINNED_MCP_SOURCE_DIGESTS!r}
_ORIGINAL_DEPENDENCY = {original_dependency!r}
_PINNED_DEPENDENCY = {pinned_dependency!r}
_ORIGINAL_CALL = {original_call!r}
_PATCHED_CALL = {patched_call!r}
_ERROR_REPLACEMENTS = {error_replacements!r}
_SECRET_REPLACEMENTS = {secret_replacements!r}


def assert_native_compatibility(program_source: str) -> None:
    if distribution_version("verifiers") != _EXPECTED_VERIFIERS_VERSION:
        raise RuntimeError("generated transport adapter Verifiers compatibility drift")
    if distribution_version("mcp") != _EXPECTED_MCP_VERSION:
        raise RuntimeError("generated transport adapter MCP compatibility drift")
    digest = hashlib.sha256(program_source.encode()).hexdigest()
    if digest != _PINNED_NULL_PROGRAM_DIGEST:
        raise RuntimeError("generated transport adapter null-program compatibility drift")
    from mcp.client.session import ClientSession
    from mcp.server.fastmcp.server import Context
    from mcp.server.fastmcp.utilities.context_injection import find_context_parameter
    from mcp.shared.session import BaseSession
    from verifiers.v1.harnesses.null.harness import NullHarness

    guarded_sources = {{
        "NullHarness.setup": inspect.getsource(NullHarness.setup),
        "NullHarness.launch": inspect.getsource(NullHarness.launch),
        "BaseSession.send_request": inspect.getsource(BaseSession.send_request),
        "ClientSession.call_tool": inspect.getsource(ClientSession.call_tool),
        "Context.request_id": inspect.getsource(Context.request_id.fget),
        "find_context_parameter": inspect.getsource(find_context_parameter),
    }}
    expected = {{
        "NullHarness.setup": _PINNED_NULL_SETUP_DIGEST,
        "NullHarness.launch": _PINNED_NULL_LAUNCH_DIGEST,
        **_PINNED_MCP_SOURCE_DIGESTS,
    }}
    actual = {{
        name: hashlib.sha256(source.encode()).hexdigest()
        for name, source in guarded_sources.items()
    }}
    if actual != expected:
        raise RuntimeError("generated transport adapter source compatibility drift")


def patched_null_program(program_source: str) -> str:
    assert_native_compatibility(program_source)
    if program_source.count(_ORIGINAL_DEPENDENCY) != 1:
        raise RuntimeError("generated transport adapter dependency seam drift")
    if program_source.count(_ORIGINAL_CALL) != 1:
        raise RuntimeError("generated transport adapter dispatch seam drift")
    patched = program_source.replace(
        _ORIGINAL_DEPENDENCY, _PINNED_DEPENDENCY
    ).replace(_ORIGINAL_CALL, _PATCHED_CALL)
    for original, replacement in _ERROR_REPLACEMENTS:
        if patched.count(original) != 1:
            raise RuntimeError("generated transport adapter tool-error seam drift")
        patched = patched.replace(original, replacement)
    for original, replacement in _SECRET_REPLACEMENTS:
        if patched.count(original) != 1:
            raise RuntimeError("generated transport adapter secret seam drift")
        patched = patched.replace(original, replacement)
    return patched
'''


def _harness_module() -> str:
    return '''"""Generated pinned-compatible null harness; do not edit."""

from __future__ import annotations

import asyncio
import json

from verifiers.v1.clients import ModelContext
from verifiers.v1.configs.client import resolve_api_key
from verifiers.v1.dialects.chat import message_to_wire
from verifiers.v1.errors import ProviderError
from verifiers.v1.harnesses.null.harness import (
    PROGRAM_SOURCE as PINNED_NULL_PROGRAM_SOURCE,
    NullHarness,
)
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.task import TaskData
from verifiers.v1.trace import Trace

from studio.policy_evaluation.local_gemma import (
    LocalGemmaChatProvider,
    validated_private_inference_route,
)
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    EvaluationBudgets,
    ModelIdentity,
    ModelPreflightRequest,
    ModelProviderFailure,
    ModelSamplingSettings,
)

from science_environment_generated._private.model_security_adapter import (
    register_attested_session,
    unregister_attested_session,
)
from science_environment_generated._private.transport_adapter import (
    assert_native_compatibility,
    patched_null_program,
)

assert_native_compatibility(PINNED_NULL_PROGRAM_SOURCE)
PROGRAM_SOURCE = patched_null_program(PINNED_NULL_PROGRAM_SOURCE)


class GeneratedNullHarness(NullHarness):
    """Null harness with stable provider-independent MCP retry identities."""

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
        env["SCIENCE_MODEL_API_KEY"] = secret
        try:
            interception_endpoint = validated_private_inference_route(endpoint)
            provider_endpoint = validated_private_inference_route(ctx.client.base_url)
            provider_api_key = resolve_api_key(ctx.client)
        except ValueError:
            raise ProviderError(
                "model interception route is not an approved private literal route",
                status_code=400,
            ) from None
        try:
            provider = LocalGemmaChatProvider.from_environment(
                {
                    "SCIENCE_LOCAL_GEMMA_BASE_URL": provider_endpoint,
                    "SCIENCE_LOCAL_GEMMA_API_KEY": provider_api_key,
                    "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY": env.get(
                        "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY", ""
                    ),
                    "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256": env.get(
                        "SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256", ""
                    ),
                    "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256": env.get(
                        "SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256", ""
                    ),
                    "SCIENCE_LOCAL_GEMMA_UNIX_SOCKET": env.get(
                        "SCIENCE_LOCAL_GEMMA_UNIX_SOCKET", ""
                    ),
                },
                timeout_seconds=900.0,
            )
            attestation = await asyncio.to_thread(
                provider.preflight,
                ModelPreflightRequest(
                    model=ModelIdentity(
                        provider="local-openai-compatible",
                        requested_model=ctx.model,
                        adapter_revision=BASE_GEMMA_ADAPTER_REVISION,
                    ),
                    profile="base-gemma-development-v1",
                    sampling=ModelSamplingSettings(),
                    budgets=EvaluationBudgets(
                        max_turns=64,
                        max_tool_calls=64,
                    ),
                ),
            )
        except (ModelProviderFailure, ValueError):
            raise ProviderError(
                "local Gemma runtime attestation failed",
                status_code=503,
            ) from None
        trace.info["science_environment_local_gemma_attestation"] = (
            attestation.model_dump(mode="json")
        )
        env["SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY"] = ""
        args = [
            f"--base-url={interception_endpoint}",
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
                            name: {"url": url, "timeout": self.config.tool_timeout}
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
            PROGRAM_SOURCE, self.config.resolved_env
        )
        register_attested_session(trace.id, attestation.runtime_instance_id)
        try:
            return await runtime.run_program([*program, *args], env)
        finally:
            unregister_attested_session(trace.id)
'''


def _taskset_module(bundle: EnvironmentBundle) -> str:
    splits = ", ".join(repr(split) for split in bundle.split_identities)
    metric_methods = "\n".join(
        _metric_method(metric) for metric in bundle.metrics if metric != "reward"
    )
    return f'''"""Generated native Verifiers v1 Taskset; do not edit."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any, Literal

import verifiers.v1 as vf
from jsonschema import Draft202012Validator

from studio.policy_evaluation.local_gemma import validated_private_inference_route

from science_environment_generated._private.model_security_adapter import (
    install_attested_eval_client_patch,
)
from science_environment_generated.servers.apparatus import (
    ApparatusState,
    ApparatusToolset,
    finalize_incomplete,
)

install_attested_eval_client_patch()

_CATALOG = json.loads(
    files("science_environment_generated")
    .joinpath("_private/task-catalog.json")
    .read_text(encoding="utf-8")
)
_ACTION_NAMES = frozenset(action["name"] for action in _CATALOG["actions"])
_ACTION_SCHEMAS = {{action["name"]: action["input_schema"] for action in _CATALOG["actions"]}}


def _remove_live_execution_material(trace: vf.Trace) -> None:
    # AgentInfo retains the live AgentConfig and RuntimeInfo instances supplied
    # by Verifiers. Replace them with trace-only copies so sanitization cannot
    # alter the active ModelContext or runtime lifecycle.
    trace.agent.config = trace.agent.config.model_copy(update={{"client": None}})
    if trace.agent.runtime is not None:
        trace.agent.runtime = trace.agent.runtime.model_copy(update={{"id": None}})


def _require_evaluation_profile(trace: vf.Trace) -> None:
    if trace.agent.config.timeout.rollout != {_MAX_EPISODE_SECONDS}:
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": "adapter.evaluation_profile_drift",
        }}
        raise RuntimeError("adapter.evaluation_profile_drift")


def _persist_runtime_evidence(trace: vf.Trace) -> None:
    _require_evaluation_profile(trace)
    if trace.state.adapter_error is not None:
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": trace.state.adapter_error,
        }}
        raise RuntimeError(trace.state.adapter_error)
    if len(trace.state.accepted_tool_results) != len(trace.state.accepted_actions):
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": "adapter.tool_lineage_divergence",
        }}
        raise RuntimeError("adapter.tool_lineage_divergence")
    accepted_executions = [
        item for item in trace.state.tool_executions if item["accepted"]
    ]
    if (
        [item["action"] for item in accepted_executions]
        != trace.state.accepted_actions
        or [item["result"] for item in accepted_executions]
        != trace.state.accepted_tool_results
    ):
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": "adapter.action_divergence",
        }}
        raise RuntimeError("adapter.action_divergence")
    tool_lineage = []
    execution_index = 0
    accepted_count = 0
    ordinal = 0
    tool_results: dict[str, list[dict[str, Any]]] = {{}}
    for tool_message in trace.tool_messages:
        if not isinstance(tool_message.content, str):
            trace.info["science_environment_adapter_error"] = {{
                "category": "adapter",
                "code": "adapter.tool_result_malformed",
            }}
            raise RuntimeError("adapter.tool_result_malformed")
        try:
            payload = json.loads(tool_message.content)
        except json.JSONDecodeError:
            trace.info["science_environment_adapter_error"] = {{
                "category": "adapter",
                "code": "adapter.tool_result_malformed",
            }}
            raise RuntimeError("adapter.tool_result_malformed") from None
        if not isinstance(payload, dict):
            trace.info["science_environment_adapter_error"] = {{
                "category": "adapter",
                "code": "adapter.tool_result_malformed",
            }}
            raise RuntimeError("adapter.tool_result_malformed")
        tool_results.setdefault(tool_message.tool_call_id, []).append(payload)
    # Pinned Verifiers persists prompt-replayed branch context alongside sampled
    # responses. Gemma's pinned renderer can reuse call_0 on each response, so
    # correlate by the canonical Runtime result as well as the provider call ID.
    # Any unmatched payload must still equal a result proven for that ID below.
    allowed_tool_results: dict[str, set[str]] = {{}}
    assistant_messages = trace.assistant_messages
    for message_index, message in enumerate(assistant_messages):
        for call in message.tool_calls or []:
            ordinal += 1
            canonical_call_id = f"episode-call-{{ordinal:06d}}"
            try:
                arguments = json.loads(call.arguments or "{{}}")
            except json.JSONDecodeError:
                arguments = None
            persisted_result = None
            action = {{"type": call.name, "arguments": arguments}}
            schema_error = (
                next(
                    Draft202012Validator(_ACTION_SCHEMAS[call.name]).iter_errors(
                        arguments
                    ),
                    None,
                )
                if isinstance(arguments, dict) and call.name in _ACTION_NAMES
                else None
            )
            budget_overflow = (
                trace.state.terminal_reason == "tool_call_budget_exhausted"
                and accepted_count >= {_MAX_ACCEPTED_TOOL_CALLS}
            )
            output_budget_exhausted = (
                trace.state.terminal_reason == "output_budget_exhausted"
                and message_index == len(assistant_messages) - 1
            )
            dispatched_execution = False
            if output_budget_exhausted:
                expected = {{
                    "accepted": False,
                    "action": action,
                    "result": {{
                        "status": "error",
                        "error_code": "tool.output_budget_exhausted",
                    }},
                }}
            elif budget_overflow:
                if (
                    isinstance(arguments, dict)
                    and call.name in _ACTION_NAMES
                    and schema_error is None
                    and execution_index < len(trace.state.tool_executions)
                ):
                    expected = trace.state.tool_executions[execution_index]
                    execution_index += 1
                    dispatched_execution = True
                    if expected["action"] != action or expected["accepted"]:
                        trace.info["science_environment_adapter_error"] = {{
                            "category": "adapter",
                            "code": "adapter.action_divergence",
                        }}
                        raise RuntimeError("adapter.action_divergence")
                else:
                    # Pinned Verifiers runs @stop while intercepting the 64th
                    # accepted result, so later calls in that assistant message
                    # remain visible but are never dispatched to the Toolset.
                    # Retain a call-ID-linked product-equivalent budget result.
                    expected = {{
                        "accepted": False,
                        "action": action,
                        "result": {{
                            "status": "error",
                            "error_code": "tool.budget_exhausted",
                        }},
                    }}
            elif not isinstance(arguments, dict):
                expected = {{
                    "accepted": False,
                    "action": action,
                    "result": {{
                        "status": "error",
                        "error_code": "tool.invalid_arguments",
                    }},
                }}
            elif call.name not in _ACTION_NAMES:
                expected = {{
                    "accepted": False,
                    "action": action,
                    "result": {{
                        "status": "error",
                        "error_code": "tool.unknown_action",
                    }},
                }}
            elif schema_error is not None:
                expected = {{
                    "accepted": False,
                    "action": action,
                    "result": {{
                        "status": "error",
                        "error_code": "tool.invalid_arguments",
                    }},
                }}
            else:
                if execution_index >= len(trace.state.tool_executions):
                    trace.info["science_environment_adapter_error"] = {{
                        "category": "adapter",
                        "code": "adapter.tool_lineage_divergence",
                    }}
                    raise RuntimeError("adapter.tool_lineage_divergence")
                expected = trace.state.tool_executions[execution_index]
                execution_index += 1
                dispatched_execution = True
                if expected["action"] != action:
                    trace.info["science_environment_adapter_error"] = {{
                        "category": "adapter",
                        "code": "adapter.action_divergence",
                    }}
                    raise RuntimeError("adapter.action_divergence")
            if expected["accepted"]:
                accepted_count += 1
            suppressed_by_framework_stop = (
                output_budget_exhausted
                or budget_overflow
                or (
                    trace.state.terminal_reason == "turn_budget_exhausted"
                    and message_index == len(assistant_messages) - 1
                )
                or (
                    dispatched_execution
                    and expected.get("terminal_after_execution", False)
                )
            )
            canonical_expected_result = json.dumps(
                expected["result"],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            allowed_tool_results.setdefault(call.id, set()).add(
                canonical_expected_result
            )
            if not suppressed_by_framework_stop:
                result_queue = tool_results.get(call.id, [])
                matching_result_index = next(
                    (
                        index
                        for index, candidate in enumerate(result_queue)
                        if candidate == expected["result"]
                    ),
                    None,
                )
                if matching_result_index is None:
                    if not result_queue:
                        trace.info["science_environment_adapter_error"] = {{
                            "category": "adapter",
                            "code": "adapter.tool_result_missing",
                        }}
                        raise RuntimeError("adapter.tool_result_missing")
                    trace.info["science_environment_adapter_error"] = {{
                        "category": "adapter",
                        "code": "adapter.tool_result_divergence",
                    }}
                    raise RuntimeError("adapter.tool_result_divergence")
                persisted_result = result_queue.pop(matching_result_index)
            result_linkage = (
                "linked" if persisted_result is not None else "framework_stop_suppressed"
            )
            tool_lineage.append(
                {{
                    "call_id": canonical_call_id,
                    "provider_call_id_digest": (
                        "sha256:" + hashlib.sha256(call.id.encode()).hexdigest()
                    ),
                    "ordinal": ordinal,
                    "execution_id": expected.get("execution_id"),
                    "cache_hit": expected.get("cache_hit", False),
                    "retry_count": expected.get("retry_count", 0),
                    "result_linkage": result_linkage,
                    "accepted": expected["accepted"],
                    "action": expected["action"],
                    "result": expected["result"],
                }}
            )
    if execution_index != len(trace.state.tool_executions):
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": "adapter.tool_lineage_divergence",
            "model_action_count": len(tool_lineage),
            "runtime_action_count": len(trace.state.accepted_actions),
        }}
        raise RuntimeError("adapter.tool_lineage_divergence")
    for provider_call_id, remaining_results in tool_results.items():
        allowed = allowed_tool_results.get(provider_call_id, set())
        for remaining_result in remaining_results:
            canonical = json.dumps(
                remaining_result,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if canonical not in allowed:
                trace.info["science_environment_adapter_error"] = {{
                    "category": "adapter",
                    "code": "adapter.tool_lineage_divergence",
                }}
                raise RuntimeError("adapter.tool_lineage_divergence")
    if [item["action"] for item in tool_lineage if item["accepted"]] != (
        trace.state.accepted_actions
    ):
        trace.info["science_environment_adapter_error"] = {{
            "category": "adapter",
            "code": "adapter.action_divergence",
        }}
        # Fail before task reward/metric hooks run. In particular, an MCP
        # lost-response retry must never become an unmarked scientific score.
        raise RuntimeError("adapter.action_divergence")
    # ``vf.State`` is deliberately excluded from persisted traces. Keep the
    # completed product Runtime evidence in the JSON-safe info map.
    trace.info["science_environment_runtime"] = {{
        "evidence_version": "science-environment-runtime-trace/1",
        "bundle_id": {bundle.bundle_id!r},
        "bundle_revision": {bundle.bundle_revision!r},
        "scenario_id": trace.state.scenario_id,
        "completed_snapshot": trace.state.runtime_snapshot,
        "runtime_trace_digest": trace.state.runtime_trace_digest,
        "runtime_result_digest": trace.state.runtime_result_digest,
        "budgets": {{
            "max_turns": {_MAX_TURNS},
            "max_tool_calls": {_MAX_ACCEPTED_TOOL_CALLS},
            "max_provider_tool_calls": {_MAX_PROVIDER_TOOL_CALLS},
            "max_episode_seconds": {_MAX_EPISODE_SECONDS},
            "framework_max_turns_sentinel": {_FRAMEWORK_MAX_TURNS_SENTINEL},
        }},
        "tool_lineage": tool_lineage,
    }}


class GeneratedData(vf.TaskData):
    split: Literal[{splits}]
    scenario_id: str
    initial_observation: dict[str, Any]


class GeneratedTask(vf.Task[GeneratedData, ApparatusState]):
    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        client = trace.agent.config.client
        client_route = client.base_url if client is not None else None
        _remove_live_execution_material(trace)
        if not isinstance(client_route, str):
            raise RuntimeError("generated evaluation client route is missing")
        try:
            validated_private_inference_route(client_route)
        except ValueError:
            raise vf.ProviderError(
                "model client route is not an approved private literal route",
                status_code=400,
            ) from None
        trace.state.scenario_id = self.data.scenario_id
        trace.state.episode_id = trace.id

    async def finalize(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        del runtime
        _remove_live_execution_material(trace)
        if (
            trace.state.terminal
            and "science_environment_runtime" not in trace.info
        ):
            _persist_runtime_evidence(trace)

    @vf.stop(priority=20)
    async def incomplete_model_response(
        self,
        response: vf.Response,
        trace: vf.Trace,
    ) -> bool:
        if trace.state.terminal:
            return False
        if response.finish_reason == "length":
            termination_reason = "output_budget_exhausted"
        elif response.finish_reason == "stop" and not response.message.tool_calls:
            termination_reason = "model_ended_before_terminal"
        else:
            return False
        finalize_incomplete(trace.state, termination_reason)
        _persist_runtime_evidence(trace)
        return True

    @vf.stop(priority=10)
    async def terminal(self, trace: vf.Trace) -> bool:
        _remove_live_execution_material(trace)
        _require_evaluation_profile(trace)
        if trace.state.adapter_error is not None:
            trace.info["science_environment_adapter_error"] = {{
                "category": "adapter",
                "code": trace.state.adapter_error,
            }}
            raise RuntimeError(trace.state.adapter_error)
        if trace.state.terminal:
            _persist_runtime_evidence(trace)
        return trace.state.terminal

    @vf.stop
    async def turn_budget(self, trace: vf.Trace) -> bool:
        _remove_live_execution_material(trace)
        _require_evaluation_profile(trace)
        if not trace.state.terminal and trace.num_turns >= {_MAX_TURNS}:
            finalize_incomplete(trace.state, "turn_budget_exhausted")
            _persist_runtime_evidence(trace)
            return True
        return False

    @vf.reward(weight=1.0)
    async def reward(self, trace: vf.Trace) -> float:
        _require_evaluation_profile(trace)
        return float(trace.state.metrics.get("reward", 0.0))
{metric_methods}


class GeneratedConfig(vf.TasksetConfig):
    split: Literal[{splits}] = {bundle.split_identities[0]!r}


class GeneratedEnvironmentTaskset(vf.Taskset[GeneratedTask, GeneratedConfig]):
    @classmethod
    def toolsets(cls, config: GeneratedConfig) -> list[vf.Toolset]:
        return [ApparatusToolset(vf.SharedToolsetConfig())]

    def load(self) -> list[GeneratedTask]:
        rows = [row for row in _CATALOG["tasks"] if row["split"] == self.config.split]
        return [
            GeneratedTask(
                GeneratedData(
                    idx=row["idx"],
                    name=row["name"],
                    split=row["split"],
                    scenario_id=row["scenario_id"],
                    initial_observation=row["initial_observation"],
                    prompt=row["prompt"],
                ),
                self.config.task,
            )
            for row in rows
        ]
'''


def _metric_method(metric: str) -> str:
    return f'''\n    @vf.metric
    async def {metric}(self, trace: vf.Trace) -> float:
        _require_evaluation_profile(trace)
        return float(trace.state.metrics.get({metric!r}, 0.0))'''


def _apparatus_module(bundle: EnvironmentBundle) -> str:
    methods = "\n\n".join(
        _action_method(action.type, action.description, action.input_schema)
        for action in bundle.actions
    )
    return f'''"""Generated stateful Toolset backed by the product-owned Runtime bridge."""

import hashlib
import json
from importlib.resources import files
from typing import Annotated, Any, Literal, Optional

import verifiers.v1 as vf
from mcp.server.fastmcp import Context
from pydantic import Field

from studio.bundle import validate_environment_bundle
from studio.policy_evaluation.model_runner import ModelIdentity
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from studio.runtime import EnvironmentAction, RuntimeContractError


class ApparatusState(vf.State):
    scenario_id: str = ""
    episode_id: str = ""
    accepted_actions: list[dict[str, Any]] = Field(default_factory=list)
    accepted_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_executions: list[dict[str, Any]] = Field(default_factory=list)
    transport_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)
    adapter_error: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    terminal: bool = False
    terminal_reason: str | None = None
    runtime_snapshot: dict[str, Any] = Field(default_factory=dict)
    runtime_trace_digest: str = ""
    runtime_result_digest: str | None = None


_MAX_ACCEPTED_TOOL_CALLS = {_MAX_ACCEPTED_TOOL_CALLS}


def _load_bridge() -> EvaluationRuntimeBridge:
    document = json.loads(
        files("science_environment_generated")
        .joinpath("_private/environment-bundle.json")
        .read_text(encoding="utf-8")
    )
    return EvaluationRuntimeBridge(validate_environment_bundle(document))


def _replay(state: ApparatusState):
    bridge = _load_bridge()
    policy = ModelIdentity(
        provider="local-openai-compatible",
        requested_model={_MODEL_ID!r},
        adapter_revision={_MODEL_ADAPTER_REVISION!r},
    ).policy_identity()
    replayable = bridge.start(state.scenario_id, policy)
    for accepted in state.accepted_actions:
        replayable = bridge.apply(
            replayable,
            EnvironmentAction.model_validate(accepted),
        )
    return bridge, replayable


def _record_snapshot(
    state: ApparatusState,
    snapshot,
    *,
    terminal_reason: str | None = None,
) -> None:
    verifier_result = snapshot.verifier_result
    if verifier_result is not None:
        state.metrics = dict(verifier_result.metrics)
    state.terminal = snapshot.status == "completed"
    state.terminal_reason = terminal_reason if state.terminal else None
    state.runtime_snapshot = snapshot.model_dump(mode="json")
    state.runtime_trace_digest = snapshot.trace_digest
    state.runtime_result_digest = snapshot.result_digest


def finalize_incomplete(
    state: ApparatusState,
    termination_reason: Literal[
        "model_ended_before_terminal",
        "turn_budget_exhausted",
        "tool_call_budget_exhausted",
        "output_budget_exhausted",
    ],
) -> None:
    bridge, replayable = _replay(state)
    snapshot = bridge.finalize_incomplete(
        replayable,
        termination_reason=termination_reason,
    )
    _record_snapshot(state, snapshot, terminal_reason=termination_reason)


class ApparatusToolset(vf.Toolset[vf.SharedToolsetConfig, ApparatusState]):
    # The null harness prefixes tools with the MCP server name. ``None`` gives
    # the Policy the exact bundle-declared action names without an adapter alias.
    TOOL_PREFIX = None

    def _execute_once(
        self,
        action: EnvironmentAction,
        action_document: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        if self.state.terminal:
            error_code = (
                "tool.budget_exhausted"
                if self.state.terminal_reason == "tool_call_budget_exhausted"
                else "tool.episode_terminal"
            )
            result = {{"status": "error", "error_code": error_code}}
            return False, result
        if len(self.state.accepted_actions) >= _MAX_ACCEPTED_TOOL_CALLS:
            finalize_incomplete(self.state, "tool_call_budget_exhausted")
            result = {{"status": "error", "error_code": "tool.budget_exhausted"}}
            return False, result
        bridge, replayable = _replay(self.state)
        try:
            replayable = bridge.apply(replayable, action)
        except RuntimeContractError:
            result = {{"status": "error", "error_code": "tool.action_rejected"}}
            return False, result
        self.state.accepted_actions.append(action_document)
        action_snapshot = replayable.snapshot
        result = {{
            "status": "ok",
            "observation": action_snapshot.observation,
        }}
        self.state.accepted_tool_results.append(result)
        if action_snapshot.status == "awaiting_verification":
            _record_snapshot(self.state, bridge.finalize(replayable))
        elif len(self.state.accepted_actions) >= _MAX_ACCEPTED_TOOL_CALLS:
            completed = bridge.finalize_incomplete(
                replayable,
                termination_reason="tool_call_budget_exhausted",
            )
            _record_snapshot(
                self.state,
                completed,
                terminal_reason="tool_call_budget_exhausted",
            )
        else:
            _record_snapshot(self.state, action_snapshot)
        return True, result

    def _invoke(
        self,
        action_type: str,
        arguments: dict[str, Any],
        context: Context,
    ) -> dict[str, Any]:
        action = EnvironmentAction(type=action_type, arguments=arguments)
        action_document = action.model_dump(mode="json")
        if not self.state.episode_id:
            self.state.adapter_error = "adapter.missing_episode_identity"
            return {{
                "status": "error",
                "error_code": "tool.missing_episode_identity",
            }}
        request_id = context.request_id
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            self.state.adapter_error = "adapter.invalid_transport_request_id"
            return {{
                "status": "error",
                "error_code": "tool.invalid_transport_request_id",
            }}
        cache_key = hashlib.sha256(
            f"science-environment-transport-v1\\0{{self.state.episode_id}}\\0{{request_id}}".encode()
        ).hexdigest()
        cached = self.state.transport_cache.get(cache_key)
        if cached is not None:
            if cached["action"] != action_document:
                self.state.adapter_error = "adapter.transport_request_conflict"
                return {{
                    "status": "error",
                    "error_code": "tool.transport_request_conflict",
                }}
            cached["cache_hit"] = True
            cached["retry_count"] += 1
            matches = [
                item
                for item in self.state.tool_executions
                if item["execution_id"] == cached["execution_id"]
            ]
            if len(matches) != 1:
                self.state.adapter_error = "adapter.transport_cache_divergence"
                return {{
                    "status": "error",
                    "error_code": "tool.transport_cache_divergence",
                }}
            matches[0]["cache_hit"] = True
            matches[0]["retry_count"] = cached["retry_count"]
            return cached["result"]

        execution_id = "execution-" + hashlib.sha256(
            f"science-environment-execution-v1\\0{{self.state.episode_id}}\\0{{request_id}}".encode()
        ).hexdigest()
        accepted, result = self._execute_once(action, action_document)
        execution = {{
            "execution_id": execution_id,
            "cache_hit": False,
            "retry_count": 0,
            "terminal_after_execution": self.state.terminal,
            "accepted": accepted,
            "action": action_document,
            "result": result,
        }}
        self.state.tool_executions.append(execution)
        self.state.transport_cache[cache_key] = dict(execution)
        return result

{methods}


if __name__ == "__main__":
    ApparatusToolset.run()
'''


def _action_method(name: str, description: str, schema: Mapping[str, Any]) -> str:
    properties = schema["properties"]
    required = set(schema.get("required", []))
    ordered = [item for item in properties.items() if item[0] in required]
    ordered.extend(item for item in properties.items() if item[0] not in required)
    parameters = []
    arguments = []
    for parameter, definition in ordered:
        annotation = _python_annotation(definition)
        if parameter not in required:
            annotation = f"Optional[{annotation}]"
            parameters.append(f"{parameter}: {annotation} = None")
        else:
            parameters.append(f"{parameter}: {annotation}")
        arguments.append(f"{parameter!r}: {parameter}")
    # ``context`` is reserved at provider-schema validation above. FastMCP
    # resolves its Context annotation and removes it from the advertised JSON
    # schema while still injecting it at dispatch.
    signature = ", ".join(["self", "context: Context", *parameters])
    argument_map = "{" + ", ".join(arguments) + "}"
    return f'''    @vf.tool
    async def {name}({signature}) -> dict[str, Any]:
        {description!r}
        return self._invoke({name!r}, {argument_map}, context)'''


def _python_annotation(definition: Mapping[str, Any]) -> str:
    enum = definition.get("enum")
    base = (
        "Literal[" + ", ".join(repr(item) for item in enum) + "]"
        if isinstance(enum, list)
        else {
            "boolean": "bool",
            "integer": "int",
            "number": "float",
            "string": "str",
        }[str(definition["type"])]
    )
    constraints = []
    for source, target in (
        ("minimum", "ge"),
        ("maximum", "le"),
        ("minLength", "min_length"),
        ("maxLength", "max_length"),
    ):
        if source in definition:
            constraints.append(f"{target}={definition[source]!r}")
    return f"Annotated[{base}, Field({', '.join(constraints)})]" if constraints else base


def _validate_existing_destination(destination: Path) -> None:
    if not destination.exists():
        return
    if not destination.is_dir():
        raise CompilationContractError("generated destination must be a directory")
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if not actual:
        return
    marker = destination / _MARKER_PATH
    manifest_path = destination / "manifest.json"
    if not marker.is_file() or marker.read_bytes() != _MARKER_BYTES or not manifest_path.is_file():
        raise CompilationContractError("generated destination is not compiler-owned")
    try:
        manifest = json.loads(manifest_path.read_bytes())
        declared = set(manifest["artifact_paths"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CompilationContractError(
            "generated destination has an invalid ownership receipt"
        ) from error
    if manifest.get("manifest_version") != _COMPILATION_VERSION or actual != declared:
        raise CompilationContractError(
            "generated destination contains files not covered by its ownership receipt"
        )


def _write_generated_tree(destination: Path, files: Mapping[str, bytes]) -> None:
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=parent))
    backup: Path | None = None
    try:
        for relative, contents in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.previous-", dir=parent))
            backup.rmdir()
            os.replace(destination, backup)
        os.replace(staging, destination)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)


def _receipt(
    bundle: EnvironmentBundle,
    source_digest: str,
    files: Mapping[str, bytes],
) -> VerifiersCompilation:
    artifacts = tuple(
        CompilationArtifact(path=path, digest=_digest(contents), size_bytes=len(contents))
        for path, contents in sorted(files.items())
    )
    artifact_digest = _digest(
        _canonical_json_bytes(
            [artifact.model_dump(mode="json") for artifact in artifacts]
        )
    )
    return VerifiersCompilation(
        compilation_version=_COMPILATION_VERSION,
        verifiers_revision=_VERIFIERS_REVISION,
        model_id=_MODEL_ID,
        model_revision=_MODEL_REVISION,
        bundle_id=bundle.bundle_id,
        bundle_revision=bundle.bundle_revision,
        source_bundle_digest=source_digest,
        artifact_digest=artifact_digest,
        artifacts=artifacts,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (_canonical_json_text(value) + "\n").encode()


def _canonical_json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _toml_fragment(value: str) -> str:
    if _IDENTIFIER_PATTERN.fullmatch(value.replace("-", "_")) is None:
        raise CompilationContractError("split identity cannot be rendered safely in TOML")
    return value


__all__ = [
    "CompilationArtifact",
    "CompilationContractError",
    "VerifiersCompilation",
    "compile_verifiers_v1",
]
