"""Contract tests for the disposable native-Verifiers-v1 compiler target."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError

from environments.eeg.curriculum import load_development_scenario_set
from studio.policy_evaluation.compiler import (
    CompilationContractError,
    VerifiersCompilation,
    compile_verifiers_v1,
)


def _relative_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_compilation_receipt_and_artifacts_are_reproducible_across_destinations(
    tmp_path: Path,
) -> None:
    bundle = load_development_scenario_set().environment_bundle
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first = compile_verifiers_v1(bundle, first_root)
    second = compile_verifiers_v1(bundle, second_root)

    assert first == second
    assert isinstance(first, VerifiersCompilation)
    assert first.compilation_version == "science-environment-verifiers-v1/1"
    assert first.verifiers_revision == "b878d009147876bfd1ba80feec770194f0b567c7"
    assert first.model_id == "google/gemma-4-E4B-it"
    assert first.model_revision == "ee0ef6023621cff504d758262d4e04895a5af4a2"
    assert first.bundle_id == bundle.bundle_id
    assert first.bundle_revision == bundle.bundle_revision
    assert first.source_bundle_digest.startswith("sha256:")
    assert first.artifact_digest.startswith("sha256:")
    with pytest.raises(ValidationError):
        first.bundle_id = "mutated"

    first_files = _relative_files(first_root)
    assert first_files == _relative_files(second_root)
    assert {artifact.path for artifact in first.artifacts} == set(first_files)
    assert {
        artifact.path: artifact.digest for artifact in first.artifacts
    } == {
        path: f"sha256:{hashlib.sha256(contents).hexdigest()}"
        for path, contents in first_files.items()
    }
    assert {
        "source/environment-bundle.json",
        "taskset/task-catalog.json",
        "taskset/pyproject.toml",
        "taskset/science-environment-runtime-dependency-receipt.json",
        "taskset/science_environment_generated/__init__.py",
        "taskset/science_environment_generated/harness.py",
        "taskset/science_environment_generated/_private/__init__.py",
        "taskset/science_environment_generated/_private/model_security_adapter.py",
        "taskset/science_environment_generated/_private/transport_adapter.py",
        "taskset/science_environment_generated/taskset.py",
        "taskset/science_environment_generated/servers/__init__.py",
        "taskset/science_environment_generated/servers/apparatus.py",
        "configs/eval.toml",
        "manifest.json",
    } <= set(first_files)


def test_policy_task_catalog_contains_only_declared_visible_inputs(tmp_path: Path) -> None:
    bundle = load_development_scenario_set().environment_bundle

    compile_verifiers_v1(bundle, tmp_path / "generated")

    catalog = json.loads(
        (tmp_path / "generated/taskset/task-catalog.json").read_text()
    )
    assert catalog["catalog_version"] == "science-environment-task-catalog/1"
    assert len(catalog["tasks"]) == len(bundle.scenarios)
    expected = {
        scenario.id: scenario.initial_state.policy_visible
        for scenario in bundle.scenarios
    }
    assert {
        task["scenario_id"]: task["initial_observation"]
        for task in catalog["tasks"]
    } == expected
    serialized = json.dumps(catalog, sort_keys=True).casefold()
    assert '"hidden"' not in serialized
    assert '"verifier"' not in serialized
    assert "curriculum_fixture" not in serialized
    assert "faults" not in serialized
    assert "occurrences" not in serialized
    assert "authoring" not in serialized


def test_generated_action_catalog_preserves_exact_declared_schemas(tmp_path: Path) -> None:
    bundle = load_development_scenario_set().environment_bundle

    compile_verifiers_v1(bundle, tmp_path / "generated")

    catalog = json.loads(
        (tmp_path / "generated/taskset/task-catalog.json").read_text()
    )
    assert catalog["actions"] == [
        {
            "name": action.type,
            "title": action.title,
            "description": action.description,
            "input_schema": action.input_schema,
        }
        for action in bundle.actions
    ]


def test_generated_native_package_is_syntax_valid_and_endpoint_free(tmp_path: Path) -> None:
    bundle = load_development_scenario_set().environment_bundle
    generated = tmp_path / "generated"

    receipt = compile_verifiers_v1(bundle, generated)

    for artifact in receipt.artifacts:
        if artifact.path.endswith(".py"):
            source = (generated / artifact.path).read_text()
            compile(source, artifact.path, "exec")
    public_integration_artifacts = "\n".join(
        (generated / artifact.path).read_text(errors="replace")
        for artifact in receipt.artifacts
        if "environment-bundle.json" not in artifact.path
        and "task-catalog.json" not in artifact.path
    ).casefold()
    for forbidden in (
        "http://",
        "localhost",
        "127.0.0.1",
        "/users/",
        "/home/",
        "/srv/",
    ):
        assert forbidden not in public_integration_artifacts
    pyproject = (generated / "taskset/pyproject.toml").read_text()
    dependency_line = next(
        line for line in pyproject.splitlines() if "verifiers @ git+" in line
    )
    requirement = re.search(r'"(verifiers @ [^"]+)"', dependency_line)
    assert requirement is not None
    name, separator, direct_reference = requirement.group(1).partition(" @ ")
    assert (name, separator) == ("verifiers", " @ ")
    assert direct_reference.startswith("git+")
    parsed = urlparse(direct_reference.removeprefix("git+"))
    repository_path, separator, revision = parsed.path.rpartition("@")
    assert parsed.scheme == "https"
    assert parsed.netloc == "github.com"
    assert repository_path == "/PrimeIntellect-ai/verifiers.git"
    assert separator == "@"
    assert revision == receipt.verifiers_revision
    assert '"mcp==1.28.1"' in pyproject
    assert "allow-direct-references = true" in pyproject

    dependency_receipt = json.loads(
        (
            generated
            / "taskset/science-environment-runtime-dependency-receipt.json"
        ).read_text()
    )
    assert dependency_receipt["receipt_version"] == (
        "science-environment-native-runtime-dependency-receipt/1"
    )
    assert dependency_receipt["verifiers"]["requirement"] == requirement.group(1)
    assert dependency_receipt["verifiers"]["revision"] == receipt.verifiers_revision
    assert dependency_receipt["product_runtime"] == {
        "distribution": "science-environment-studio",
        "version": "0.1.0",
    }
    assert dependency_receipt["evaluation_profile"] == {
        "adapter_revision": "local-gemma-openai-chat/1",
        "id": "base-gemma-development-chat-v1",
        "max_episode_seconds": 900,
        "max_accepted_tool_calls": 64,
        "max_provider_tool_calls": 64,
        "max_turns": 64,
        "sampling": {
            "max_tokens": 2048,
            "seed": None,
            "store": False,
            "streaming": False,
            "temperature": 0.0,
            "tool_choice": "auto",
            "top_p": None,
        },
    }
    assert dependency_receipt["native_adapter"] == {
        "effective_max_turns": 64,
        "framework_max_turns_sentinel": 65,
        "max_accepted_tool_calls": 64,
        "max_provider_tool_calls": 64,
        "transport_idempotency": {
            "mcp_version": "1.28.1",
            "mcp_source_digests": {
                "BaseSession.send_request": (
                    "sha256:f265e17c157909872b3ea72a6d474e194bf356571c7d3f803dee3a47ceb2e35b"
                ),
                "ClientSession.call_tool": (
                    "sha256:22f4e346e0a84f40bc80f8e1de5948ed22180d4d438efed89a04799f4ab2b538"
                ),
                "Context.request_id": (
                    "sha256:d11024841e75ab41a8ced1cfb0481bf341d8f67491c4d383b3513d67420a2844"
                ),
                "find_context_parameter": (
                    "sha256:0bc2d9953e440d11f39500e1399b562243813985fa8be9dc9ffc1175aea971d6"
                ),
            },
            "protocol": "episode-scoped-jsonrpc-request-id-v1",
            "upstream_null_launch_digest": (
                "sha256:aa23438ce3adc35467f88de3c51482a68c5a82a6df8ff3d4346b4a6d213cc191"
            ),
            "upstream_null_program_digest": (
                "sha256:2daa71fe0fae8a82add30f6bda571fa08902d0d3c05fbc30373c4a41e27cdade"
            ),
            "upstream_null_setup_digest": (
                "sha256:486b9b050758fa6aaf405631b6403699b557455f125f7623577272730f8c633c"
            ),
        },
        "timeout_outcome": "framework_infrastructure_unscored",
    }
    assert dependency_receipt["closure"] == {
        "scope": "development_calibration",
        "status": "open",
        "required_before_heldout": [
            "content-addressed product wheel digest",
            "full resolved environment or container lock",
        ],
    }


def test_generated_config_uses_supported_native_budget_and_timeout_seams(
    tmp_path: Path,
) -> None:
    bundle = load_development_scenario_set().environment_bundle
    generated = tmp_path / "generated"

    compile_verifiers_v1(bundle, generated)

    config = (generated / "configs/eval.toml").read_text()
    apparatus = (
        generated
        / "taskset/science_environment_generated/servers/apparatus.py"
    ).read_text()
    taskset = (
        generated / "taskset/science_environment_generated/taskset.py"
    ).read_text()
    assert "[env.agent]\nmax_turns = 65" in config
    assert "[env.agent.timeout]\nrollout = 900" in config
    assert '[env.agent.harness]\nid = "science-environment-generated"' in config
    assert "temperature = 0.0" in config
    assert "max_tokens = 2048" in config
    assert "_MAX_ACCEPTED_TOOL_CALLS = 64" in apparatus
    assert "len(self.state.accepted_actions) >= _MAX_ACCEPTED_TOOL_CALLS" in apparatus
    assert 'finalize_incomplete(self.state, "tool_call_budget_exhausted")' in apparatus
    assert '"error_code": "tool.budget_exhausted"' in apparatus
    assert "elif len(self.state.accepted_actions) >= _MAX_ACCEPTED_TOOL_CALLS" in apparatus
    assert 'termination_reason="tool_call_budget_exhausted"' in apparatus
    assert "trace.num_turns >= 64" in taskset
    assert 'finalize_incomplete(trace.state, "turn_budget_exhausted")' in taskset
    assert '"max_episode_seconds": 900' in taskset
    assert "trace.agent.config.timeout.rollout != 900" in taskset
    assert 'raise RuntimeError("adapter.evaluation_profile_drift")' in taskset
    assert "timeout" not in taskset.casefold().split("class generatedtask", 1)[1].split(
        "class generatedconfig", 1
    )[0]

    manifest = json.loads((generated / "manifest.json").read_text())
    assert manifest["evaluation_profile"] == {
        "adapter_revision": "local-gemma-openai-chat/1",
        "id": "base-gemma-development-chat-v1",
        "budgets": {
            "max_accepted_tool_calls": 64,
            "max_episode_seconds": 900,
            "max_provider_tool_calls": 64,
            "max_turns": 64,
        },
        "timeout_outcome": "framework_infrastructure_unscored",
    }


def test_generated_v1_adapter_keeps_declared_tool_names_and_persisted_runtime_evidence(
    tmp_path: Path,
) -> None:
    bundle = load_development_scenario_set().environment_bundle
    generated = tmp_path / "generated"

    compile_verifiers_v1(bundle, generated)

    apparatus_source = (
        generated
        / "taskset/science_environment_generated/servers/apparatus.py"
    ).read_text()
    taskset_source = (
        generated / "taskset/science_environment_generated/taskset.py"
    ).read_text()
    harness_source = (
        generated / "taskset/science_environment_generated/harness.py"
    ).read_text()
    adapter_source = (
        generated
        / "taskset/science_environment_generated/_private/transport_adapter.py"
    ).read_text()
    model_security_source = (
        generated
        / "taskset/science_environment_generated/_private/model_security_adapter.py"
    ).read_text()
    # At pinned Verifiers v1, TOOL_PREFIX=None makes the MCP server name empty;
    # the generated null-compatible harness therefore advertises exact action names.
    assert "TOOL_PREFIX = None" in apparatus_source
    for action in bundle.actions:
        assert f"async def {action.type}(" in apparatus_source
        assert f"@vf.tool\n    async def {action.type}(" in apparatus_source
    # Pinned vf.Trace excludes state from disk. The terminal hook must copy the
    # completed product snapshot and both canonical digests into trace.info.
    assert 'trace.info["science_environment_runtime"]' in taskset_source
    assert '"completed_snapshot": trace.state.runtime_snapshot' in taskset_source
    assert '"runtime_trace_digest": trace.state.runtime_trace_digest' in taskset_source
    assert '"runtime_result_digest": trace.state.runtime_result_digest' in taskset_source
    assert "def _remove_live_execution_material(trace: vf.Trace)" in taskset_source
    assert 'model_copy(update={"client": None})' in taskset_source
    assert 'model_copy(update={"id": None})' in taskset_source
    assert taskset_source.count("_remove_live_execution_material(trace)") == 4
    assert "async def incomplete_model_response(" in taskset_source
    assert 'response.finish_reason == "length"' in taskset_source
    assert 'termination_reason = "model_ended_before_terminal"' in taskset_source
    assert (
        "finalize_incomplete(trace.state, termination_reason)\n"
        "        _persist_runtime_evidence(trace)\n"
        "        return True"
    ) in taskset_source
    # Verifiers stores branch-replayed context tool messages alongside sampled
    # branch responses. Reused renderer call IDs must be matched by canonical
    # result semantics; unmatched noncanonical payloads still fail closed.
    assert "matching_result_index = next(" in taskset_source
    assert "if candidate == expected[\"result\"]" in taskset_source
    assert "allowed_tool_results" in taskset_source
    assert "if canonical not in allowed" in taskset_source
    assert '"science_environment_runtime" not in trace.info' in taskset_source
    assert 'if item["accepted"]' in taskset_source
    assert "trace.state.accepted_actions" in taskset_source
    assert '"code": "adapter.action_divergence"' in taskset_source
    assert 'raise RuntimeError("adapter.action_divergence")' in taskset_source
    assert '"call_id": canonical_call_id' in taskset_source
    assert '"provider_call_id_digest": (' in taskset_source
    assert 'hashlib.sha256(call.id.encode()).hexdigest()' in taskset_source
    assert '"ordinal": ordinal' in taskset_source
    assert '"execution_id": expected.get("execution_id")' in taskset_source
    assert '"cache_hit": expected.get("cache_hit", False)' in taskset_source
    assert '"retry_count": expected.get("retry_count", 0)' in taskset_source
    assert '"result_linkage": result_linkage' in taskset_source
    assert 'raise RuntimeError("adapter.tool_result_missing")' in taskset_source
    assert 'raise RuntimeError("adapter.tool_result_malformed")' in taskset_source
    assert '"error_code": "tool.output_budget_exhausted"' in taskset_source
    assert '"accepted": expected["accepted"]' in taskset_source
    assert '"tool_lineage": tool_lineage' in taskset_source
    assert "trace.state.episode_id = trace.id" in taskset_source
    assert "from studio.policy_evaluation.model_runner import ModelIdentity" in (
        apparatus_source
    )
    assert "adapter_revision='local-gemma-openai-chat/1'" in apparatus_source
    assert ").policy_identity()" in apparatus_source
    assert "from mcp.server.fastmcp import Context" in apparatus_source
    assert "context: Context" in apparatus_source
    assert "context.request_id" in apparatus_source
    assert "transport_cache" in apparatus_source
    assert '"adapter.transport_request_conflict"' in apparatus_source
    assert "assert_native_compatibility" in harness_source
    assert "PINNED_NULL_PROGRAM_SOURCE" in harness_source
    assert "_PINNED_NULL_PROGRAM_DIGEST" in adapter_source
    assert "_PINNED_NULL_SETUP_DIGEST" in adapter_source
    assert "_PINNED_NULL_LAUNCH_DIGEST" in adapter_source
    assert "_PINNED_MCP_SOURCE_DIGESTS" in adapter_source
    assert "inspect.getsource(NullHarness.setup)" in adapter_source
    assert "inspect.getsource(NullHarness.launch)" in adapter_source
    assert "session._request_id = transport_request_id" in adapter_source
    assert "distribution_version(\"mcp\")" in adapter_source
    assert "install_attested_eval_client_patch()" in taskset_source
    assert "validated_private_unix_socket" in model_security_source
    assert "_ATTESTED_SESSIONS" in model_security_source
    assert "response.headers.get(_RUNTIME_INSTANCE_HEADER)" in model_security_source
    assert "validate_artifact_safe(document)" in model_security_source


def test_compiler_fails_closed_for_unsupported_action_names_and_schemas(
    tmp_path: Path,
) -> None:
    source = load_development_scenario_set().environment_bundle
    invalid_name = source.model_copy(deep=True)
    invalid_name.actions[0].type = "inspect-signal"
    with pytest.raises(CompilationContractError, match="provider-safe action name"):
        compile_verifiers_v1(invalid_name, tmp_path / "bad-name")

    invalid_schema = source.model_copy(deep=True)
    invalid_schema.actions[0].input_schema = {
        "type": "object",
        "properties": {"payload": {"type": "array", "items": {"type": "string"}}},
        "additionalProperties": False,
    }
    with pytest.raises(CompilationContractError, match="provider-safe action schema"):
        compile_verifiers_v1(invalid_schema, tmp_path / "bad-schema")

    hidden_context_collision = source.model_copy(deep=True)
    hidden_context_collision.actions[0].input_schema = {
        "type": "object",
        "properties": {"context": {"type": "string"}},
        "required": ["context"],
        "additionalProperties": False,
    }
    with pytest.raises(CompilationContractError, match="provider-safe action schema"):
        compile_verifiers_v1(
            hidden_context_collision,
            tmp_path / "hidden-context-collision",
        )


@pytest.mark.parametrize(
    "action_name",
    (
        "config",
        "register",
        "run",
        "server_name",
        "setup",
        "setup_task",
        "state",
    ),
)
def test_compiler_rejects_actions_that_override_the_pinned_toolset_api(
    tmp_path: Path,
    action_name: str,
) -> None:
    bundle = load_development_scenario_set().environment_bundle.model_copy(deep=True)
    bundle.actions[0].type = action_name

    with pytest.raises(CompilationContractError, match="provider-safe action name"):
        compile_verifiers_v1(bundle, tmp_path / f"reserved-{action_name}")


@pytest.mark.parametrize(
    "metrics",
    (
        ["terminal"],
        ["turn_budget"],
        ["setup"],
        ["score"],
        ["class"],
        ["not-provider-safe"],
        ["terminal_correctness", "terminal_correctness"],
    ),
)
def test_compiler_rejects_metrics_that_collide_or_cannot_be_emitted_safely(
    tmp_path: Path,
    metrics: list[str],
) -> None:
    bundle = load_development_scenario_set().environment_bundle.model_copy(deep=True)
    bundle.metrics = metrics

    with pytest.raises(CompilationContractError, match="provider-safe metric names"):
        compile_verifiers_v1(bundle, tmp_path / "unsafe-metrics")


@pytest.mark.parametrize(
    ("constraint", "value"),
    (
        ("enum", float("nan")),
        ("minimum", float("inf")),
        ("maximum", float("-inf")),
    ),
)
def test_compiler_rejects_non_finite_numeric_action_constraints(
    tmp_path: Path,
    constraint: str,
    value: float,
) -> None:
    bundle = load_development_scenario_set().environment_bundle.model_copy(deep=True)
    numeric_constraint: object = [value] if constraint == "enum" else value
    bundle.actions[0].input_schema = {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                constraint: numeric_constraint,
            }
        },
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(CompilationContractError, match="provider-safe action schema"):
        compile_verifiers_v1(bundle, tmp_path / "non-finite-schema")


@pytest.mark.parametrize(
    "unsafe_metadata",
    (
        {"access_token": "opaque-secret"},
        {"accessToken": "opaque-secret"},
        {"hf_token": "opaque-secret"},
        {"message": "ghp_" + "a" * 36},
        {"server_host": "gpu-box"},
        {"opaque": "https://gemma-gateway.lab.internal/v1"},
        {"opaque": "gemma-gateway.local:8000/v1"},
        {"opaque": "adapter failed at gpu-box"},
        {"opaque": "gemma.private.example"},
        {"opaque": "/srv/private-models/gemma"},
    ),
)
def test_compiler_fails_closed_for_transport_material_under_extension_keys(
    tmp_path: Path,
    unsafe_metadata: dict[str, str],
) -> None:
    bundle = load_development_scenario_set().environment_bundle.model_copy(deep=True)
    assert bundle.__pydantic_extra__ is not None
    bundle.__pydantic_extra__["future_release_metadata"] = unsafe_metadata

    with pytest.raises(
        CompilationContractError,
        match="endpoint, credential, private-host, or host-path material",
    ):
        compile_verifiers_v1(bundle, tmp_path / "unsafe")


def test_regeneration_is_exact_and_refuses_unowned_destinations(tmp_path: Path) -> None:
    bundle = load_development_scenario_set().environment_bundle
    generated = tmp_path / "generated"
    initial = compile_verifiers_v1(bundle, generated)

    repeated = compile_verifiers_v1(bundle, generated)

    assert repeated == initial
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "scientist-notes.txt").write_text("preserve me")
    with pytest.raises(CompilationContractError, match="not compiler-owned"):
        compile_verifiers_v1(bundle, unrelated)
    assert (unrelated / "scientist-notes.txt").read_text() == "preserve me"
