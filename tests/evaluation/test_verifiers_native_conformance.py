"""Opt-in canary against the exact native Verifiers v1 null harness.

The normal Python 3.9 suite does not install Verifiers. Set
``SCIENCE_VERIFIERS_PYTHON`` to an isolated Python 3.11 interpreter whose
``verifiers`` distribution records an audited local source checkout at the
required commit to run this boundary test. Optionally set ``SCIENCE_STUDIO_WHEEL``
to exercise the generated Taskset against the built product wheel instead of
the source checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from uuid import uuid4

import pytest

import studio.policy_evaluation.compiler as compiler_module
from environments.eeg import LEGACY_SCENARIO_ID, load_legacy_bundle
from environments.eeg.curriculum import load_development_scenario_set
from studio.bundle import EnvironmentBundle, validate_environment_bundle
from studio.policy_evaluation.attestation_protocol import canonical_json, hmac_sha256_hex
from studio.policy_evaluation.compiler import compile_verifiers_v1
from studio.policy_evaluation.model_runner import (
    BASE_GEMMA_ADAPTER_REVISION,
    BASE_GEMMA_CHECKPOINT_REVISION,
    BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256,
    BASE_GEMMA_RENDERER_REVISION,
    BASE_GEMMA_TOKENIZER_MANIFEST_SHA256,
    PINNED_VLLM_SOURCE_REVISION,
    PINNED_VLLM_VERSION,
    PINNED_VLLM_WHEEL_SHA256,
    ModelIdentity,
    ToolExecutionResult,
)
from studio.policy_evaluation.runtime_dependencies import APPROVED_RUNTIME_PYTHON
from studio.registry import EnvironmentRegistry
from studio.runtime import (
    EnvironmentAction,
    EnvironmentRuntime,
    IncompleteTerminationReason,
    RunSnapshot,
)
from tests.evaluation.attested_provider_support import runtime_distribution_receipt_for_tests

_VERIFIERS_REVISION = "b878d009147876bfd1ba80feec770194f0b567c7"
_MODEL_ID = "google/gemma-4-E4B-it"
_SECRET = "native-canary-secret-that-must-not-persist"
_ATTESTATION_KEY = "native-canary-attestation-key-that-must-not-persist"
_PRODUCT_WHEEL_SHA256 = "9" * 64
_TRUSTED_BOOTSTRAP_SHA256 = "7" * 64
_RUNTIME_INSTANCE_ID = "1" * 64
_APPARATUS_MODULE = "science_environment_generated.servers.apparatus"
_ACTIONS = (
    "inspect_onset_route",
    "repair_refractory_route",
    "present_test_flash",
)
_DEVELOPMENT_SCENARIO_ID = "eeg-5f9bbaea737603d7"
_DEVELOPMENT_SUCCESS_ACTIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("inspect_configuration", {}),
    ("inspect_eeg_signals", {}),
    ("inspect_onset_route", {}),
    ("inspect_response_timeline", {}),
    ("inspect_recording_timeline", {}),
    ("inspect_eeg_signals", {}),
    ("inspect_frequency_evidence", {}),
    ("reconnect_electrode_path", {"site": "FC4"}),
    ("collect_fresh_eeg_window", {}),
    ("present_test_flash", {}),
    ("run_response_preflight", {}),
    ("run_recording_preflight", {}),
    ("complete_preflight", {}),
)
_DEVELOPMENT_FAILURE_ACTIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("complete_preflight", {}),
)


def _external_python() -> Path:
    configured = os.environ.get("SCIENCE_VERIFIERS_PYTHON")
    if not configured:
        pytest.skip(
            "native Verifiers canary requires SCIENCE_VERIFIERS_PYTHON pointing "
            "to the audited Python 3.11 environment"
        )
    interpreter = Path(configured).expanduser()
    if not interpreter.is_absolute():
        interpreter = Path.cwd() / interpreter
    if not interpreter.is_file():
        pytest.fail(f"SCIENCE_VERIFIERS_PYTHON is not a file: {interpreter}")
    return interpreter


class _ScriptedChatServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    requests: list[dict[str, Any]]
    actions: tuple[str, ...]
    action_arguments: tuple[dict[str, Any], ...]
    refuse_model_calls: bool
    attest_runtime: bool
    reflect_api_key: bool
    provider_tool_call_batch_size: int | None
    response_finish_reason: str | None
    response_delay_seconds: float
    secret_in_process_argv: bool
    attestation_requests: list[dict[str, Any]]

    def __init__(
        self,
        socket_path: Path,
        actions: tuple[str, ...],
        *,
        action_arguments: tuple[dict[str, Any], ...] | None = None,
        refuse_model_calls: bool = False,
        attest_runtime: bool = True,
        reflect_api_key: bool = False,
        provider_tool_call_batch_size: int | None = None,
        response_finish_reason: str | None = None,
        response_delay_seconds: float = 0.0,
    ) -> None:
        super().__init__(str(socket_path), _ScriptedChatHandler)
        socket_path.chmod(0o600)
        self.unix_socket_path = socket_path
        self.requests = []
        self.actions = actions
        self.action_arguments = action_arguments or tuple({} for _ in actions)
        if len(self.action_arguments) != len(actions):
            raise ValueError("scripted action arguments must align with actions")
        self.refuse_model_calls = refuse_model_calls
        self.attest_runtime = attest_runtime
        self.reflect_api_key = reflect_api_key
        self.provider_tool_call_batch_size = provider_tool_call_batch_size
        self.response_finish_reason = response_finish_reason
        self.response_delay_seconds = response_delay_seconds
        self.secret_in_process_argv = False
        self.attestation_requests = []

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1/v1"


class _ScriptedChatHandler(BaseHTTPRequestHandler):
    server: _ScriptedChatServer

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path.endswith("/science/runtime-attestations"):
            self.server.attestation_requests.append(request)
            if not self.server.attest_runtime:
                self._send_json(404, {"error": "runtime attestation unavailable"})
                return
            generated_at = datetime.now(timezone.utc).replace(microsecond=0)
            evidence = {
                "attestation_version": "science-local-gemma-runtime-attestation/1",
                "attestation_id": "native-canary-attestation-018f7f6e",
                "runtime_instance_id": _RUNTIME_INSTANCE_ID,
                "trusted_bootstrap_sha256": _TRUSTED_BOOTSTRAP_SHA256,
                "python_bytecode_mode": "fresh-private-prefix-no-write",
                "challenge_nonce": request["challenge_nonce"],
                "generated_at_utc": generated_at.isoformat().replace("+00:00", "Z"),
                "runtime_started_at_utc": (generated_at - timedelta(minutes=5))
                .isoformat()
                .replace("+00:00", "Z"),
                "served_model": _MODEL_ID,
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
                    "wheel_sha256": _PRODUCT_WHEEL_SHA256,
                    "record_manifest_sha256": "c" * 64,
                    "import_module": "studio.policy_evaluation.gemma_server_bootstrap",
                    "import_origin": "studio/policy_evaluation/gemma_server_bootstrap.py",
                    "import_origin_sha256": "d" * 64,
                    "verification": "wheel-record-sha256+import-origin",
                },
                "serving_root_filesystem_mode": "kernel-read-only-mount",
                "network_scope": "loopback-only",
                "api_key_authentication": True,
                "attestation_middleware_revision": (
                    "science-local-gemma-attestation-middleware/1"
                ),
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
                "sampling_profile": request["sampling_profile"],
                "max_episode_seconds": request["budgets"]["max_episode_seconds"],
                "platform": "linux-x86_64",
                "accelerator_architecture": "sm120",
                "accelerator_count": 1,
                "cuda_version": "12.9",
                "driver_version": "610.43.02",
                "serving_image_digest": f"sha256:{'2' * 64}",
                "serving_image_digest_provenance": "operator-supplied",
                "evidence_scope": "server-reported-runtime-state",
            }
            self._send_json(
                200,
                {
                    "attestation": evidence,
                    "signature": hmac_sha256_hex(
                        key=_ATTESTATION_KEY,
                        canonical_document=canonical_json(evidence),
                    ),
                },
            )
            return
        self.server.requests.append(request)
        process_table = subprocess.run(
            ["ps", "-axo", "command="],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.server.secret_in_process_argv = (
            self.server.secret_in_process_argv
            or any(
                "--api-key=" in row and "--base-url=" in row
                for row in process_table.stdout.splitlines()
            )
        )
        if self.server.response_delay_seconds:
            time.sleep(self.server.response_delay_seconds)
        if self.server.refuse_model_calls:
            self._send_json(
                401,
                {
                    "error": {
                        "message": "synthetic model refusal",
                        "type": "invalid_request_error",
                        "code": "model_refused",
                    }
                },
            )
            return
        if self.server.reflect_api_key:
            self._send_json(
                200,
                {
                    "id": "native-reflected-secret",
                    "object": "chat.completion",
                    "created": 1,
                    "model": _MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": _SECRET},
                            "finish_reason": "stop",
                            "logprobs": None,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 4,
                        "total_tokens": 24,
                    },
                },
                runtime_instance_id=_RUNTIME_INSTANCE_ID,
            )
            return
        if self.server.provider_tool_call_batch_size is not None:
            batch_size = self.server.provider_tool_call_batch_size
            request_ordinal = len(self.server.requests)
            self._send_json(
                200,
                {
                    "id": "native-provider-tool-call-overflow",
                    "object": "chat.completion",
                    "created": 1,
                    "model": _MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": (
                                            f"native-overflow-call-{request_ordinal}-"
                                            f"{ordinal:06d}"
                                        ),
                                        "type": "function",
                                        "function": {
                                            "name": "read_hidden_truth",
                                            "arguments": "{}",
                                        },
                                    }
                                    for ordinal in range(1, batch_size + 1)
                                ],
                            },
                            "finish_reason": "tool_calls",
                            "logprobs": None,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": batch_size,
                        "total_tokens": 20 + batch_size,
                    },
                },
                runtime_instance_id=_RUNTIME_INSTANCE_ID,
            )
            return
        tool_results = [
            message for message in request.get("messages", []) if message["role"] == "tool"
        ]
        turn = len(tool_results)
        if turn < len(self.server.actions):
            action = self.server.actions[turn]
            message: dict[str, Any] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"native-call-{turn + 1}",
                        "type": "function",
                        "function": {
                            "name": action,
                            "arguments": json.dumps(
                                self.server.action_arguments[turn],
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "completed"}
            finish_reason = "stop"
        finish_reason = self.server.response_finish_reason or finish_reason
        response = {
            "id": f"native-response-{turn + 1}",
            "object": "chat.completion",
            "created": turn + 1,
            "model": _MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                    "logprobs": None,
                }
            ],
            "usage": {
                "prompt_tokens": 20 + turn,
                "completion_tokens": 4,
                "total_tokens": 24 + turn,
            },
        }
        self._send_json(200, response, runtime_instance_id=_RUNTIME_INSTANCE_ID)

    def _send_json(
        self,
        status: int,
        response: dict[str, Any],
        *,
        runtime_instance_id: str | None = None,
    ) -> None:
        payload = json.dumps(response, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        if runtime_instance_id is not None:
            self.send_header("X-Science-Runtime-Instance", runtime_instance_id)
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextmanager
def _scripted_chat_server(
    actions: tuple[str, ...] = _ACTIONS,
    *,
    action_arguments: tuple[dict[str, Any], ...] | None = None,
    refuse_model_calls: bool = False,
    attest_runtime: bool = True,
    reflect_api_key: bool = False,
    provider_tool_call_batch_size: int | None = None,
    response_finish_reason: str | None = None,
    response_delay_seconds: float = 0.0,
) -> Iterator[_ScriptedChatServer]:
    temporary_parent = "/private/tmp" if sys.platform == "darwin" else None
    with tempfile.TemporaryDirectory(
        prefix="science-native-gemma-",
        dir=temporary_parent,
    ) as temporary_directory:
        directory = Path(temporary_directory)
        directory.chmod(0o700)
        server = _ScriptedChatServer(
            directory / "science-local-gemma.sock",
            actions,
            action_arguments=action_arguments,
            refuse_model_calls=refuse_model_calls,
            attest_runtime=attest_runtime,
            reflect_api_key=reflect_api_key,
            provider_tool_call_batch_size=provider_tool_call_batch_size,
            response_finish_reason=response_finish_reason,
            response_delay_seconds=response_delay_seconds,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def _assert_exact_verifiers_checkout(interpreter: Path) -> Path:
    probe = subprocess.run(
        [
            str(interpreter),
            "-c",
            (
                "import importlib.metadata, json; "
                "distribution=importlib.metadata.distribution('verifiers'); "
                "direct=distribution.read_text('direct_url.json'); "
                "print(json.dumps({'direct_url': json.loads(direct) if direct "
                "else None}))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metadata = json.loads(probe.stdout)
    direct_url = metadata["direct_url"]
    assert isinstance(direct_url, dict), "Verifiers install has no direct_url.json"
    parsed = urlparse(direct_url["url"])
    assert parsed.scheme == "file", "Verifiers must resolve to an audited local checkout"
    repository = Path(unquote(parsed.path))
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    assert head == _VERIFIERS_REVISION
    checkout_status = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    assert not checkout_status, (
        "Verifiers checkout differs from the audited commit: "
        f"{checkout_status}"
    )
    return repository


def test_native_preflight_rejects_any_dirty_pinned_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "verifiers"
    repository.mkdir()
    responses = iter(
        (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {"direct_url": {"url": repository.as_uri()}}
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{_VERIFIERS_REVISION}\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=" M uv.lock\n",
                stderr="",
            ),
        )
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(AssertionError, match="checkout differs from the audited commit"):
        _assert_exact_verifiers_checkout(Path("/audited/python"))

    assert commands[-1] == [
        "git",
        "-C",
        str(repository),
        "status",
        "--porcelain",
        "--untracked-files=all",
    ]


def _direct_execution() -> tuple[tuple[RunSnapshot, ...], RunSnapshot]:
    bundle = validate_environment_bundle(load_legacy_bundle())
    return _direct_execution_for(
        bundle,
        LEGACY_SCENARIO_ID,
        tuple((action, {}) for action in _ACTIONS),
    )


def _direct_execution_for(
    bundle: EnvironmentBundle,
    scenario_id: str,
    actions: tuple[tuple[str, dict[str, Any]], ...],
) -> tuple[tuple[RunSnapshot, ...], RunSnapshot]:
    registry = EnvironmentRegistry.from_seeded_environments()
    runtime = EnvironmentRuntime(registry.module_for_bundle(bundle))
    snapshot = runtime.start(
        scenario_id,
        ModelIdentity(
            provider="local-openai-compatible",
            requested_model=_MODEL_ID,
            adapter_revision=BASE_GEMMA_ADAPTER_REVISION,
        ).policy_identity(),
    )
    action_snapshots = []
    for action, arguments in actions:
        snapshot = runtime.apply_action(
            snapshot.run_id,
            EnvironmentAction(type=action, arguments=arguments),
        )
        action_snapshots.append(snapshot)
    return tuple(action_snapshots), runtime.verify(snapshot.run_id)


def _direct_incomplete(termination_reason: IncompleteTerminationReason) -> RunSnapshot:
    bundle = validate_environment_bundle(load_legacy_bundle())
    runtime = EnvironmentRuntime(
        EnvironmentRegistry.from_seeded_environments().module_for_bundle(bundle)
    )
    started = runtime.start(
        LEGACY_SCENARIO_ID,
        ModelIdentity(
            provider="local-openai-compatible",
            requested_model=_MODEL_ID,
            adapter_revision=BASE_GEMMA_ADAPTER_REVISION,
        ).policy_identity(),
    )
    return runtime.finalize_incomplete(
        started.run_id,
        termination_reason=termination_reason,
    )


def _development_bundle_with_fixture_first() -> EnvironmentBundle:
    bundle = load_development_scenario_set().environment_bundle.model_copy(deep=True)
    selected = next(
        scenario for scenario in bundle.scenarios if scenario.id == _DEVELOPMENT_SCENARIO_ID
    )
    bundle.scenarios = [
        selected,
        *(scenario for scenario in bundle.scenarios if scenario.id != selected.id),
    ]
    return validate_environment_bundle(bundle)


def _marked_apparatus_pids(marker: str) -> tuple[int, ...]:
    table = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    matches = []
    for row in table.stdout.splitlines():
        fields = row.strip().split(maxsplit=1)
        if len(fields) != 2 or f"-m {_APPARATUS_MODULE}" not in fields[1]:
            continue
        pid = int(fields[0])
        proc_environment = Path(f"/proc/{pid}/environ")
        try:
            if proc_environment.is_file():
                marked = marker.encode() in proc_environment.read_bytes()
            else:
                process = subprocess.run(
                    ["ps", "eww", "-p", str(pid), "-o", "command="],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                marked = process.returncode == 0 and marker in process.stdout
        except (OSError, subprocess.SubprocessError):
            marked = False
        if marked:
            matches.append(pid)
    return tuple(matches)


def _terminate_marked_apparatus(marker: str) -> None:
    """Reap only generated servers belonging to this native canary process."""

    for pid in _marked_apparatus_pids(marker):
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while (survivors := _marked_apparatus_pids(marker)) and time.monotonic() < deadline:
        time.sleep(0.05)
    for pid in survivors:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while (survivors := _marked_apparatus_pids(marker)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not survivors, f"generated apparatus processes survived cleanup: {survivors}"


def _run_native_eval(
    interpreter: Path,
    repository: Path,
    generated: Path,
    output_root: Path,
    base_url: str,
    unix_socket_path: Path,
    run_name: str = "native-conformance",
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    configured_product = environment.get("SCIENCE_STUDIO_WHEEL")
    product_source = (
        Path(configured_product).expanduser().resolve()
        if configured_product
        else Path(__file__).resolve().parents[2]
    )
    if configured_product and not product_source.is_file():
        pytest.fail(f"SCIENCE_STUDIO_WHEEL is not a file: {product_source}")
    python_paths = [
        str(generated / "taskset"),
        str(product_source),
        str(repository),
    ]
    if existing := environment.get("PYTHONPATH"):
        python_paths.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    environment["SCIENCE_CANARY_API_KEY"] = _SECRET
    environment["SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY"] = _ATTESTATION_KEY
    environment["SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256"] = _PRODUCT_WHEEL_SHA256
    environment["SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256"] = (
        _TRUSTED_BOOTSTRAP_SHA256
    )
    environment["SCIENCE_LOCAL_GEMMA_UNIX_SOCKET"] = str(unix_socket_path)
    environment["SCIENCE_CANARY_PRODUCT_SOURCE"] = str(product_source)
    process_marker = f"science-native-canary-{uuid4().hex}"
    environment["SCIENCE_NATIVE_CANARY_PROCESS_MARKER"] = process_marker
    command = [
            str(interpreter),
            "-c",
            (
                "import os; "
                "import studio.policy_evaluation.runtime_bridge as product_bridge; "
                "assert os.environ['SCIENCE_CANARY_PRODUCT_SOURCE'] "
                "in product_bridge.__file__; "
                "from verifiers.v1.cli.eval.main import main; main()"
            ),
            "@",
            str(generated / "configs/eval.toml"),
            "--client.base-url",
            base_url,
            "--client.api-key-var",
            "SCIENCE_CANARY_API_KEY",
            "--output-dir",
            str(output_root),
            "--run.name",
            run_name,
            "--run.dir",
            run_name,
            "--server",
            "False",
            "--rich",
            "False",
            "--push",
            "False",
            "--max-concurrent",
            "1",
            "--num-tasks",
            "1",
            *extra_args,
        ]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=environment,
            cwd=generated / "taskset",
        )
    finally:
        # The pinned runtime normally tears its MCP subprocess down itself.  A
        # timeout or interrupted eval can bypass that async teardown after the
        # server has started a new process session, so the test owns a narrow
        # marker-based backstop instead of leaving an orphan behind.
        _terminate_marked_apparatus(process_marker)


def _run_native_budget_probe(
    interpreter: Path,
    repository: Path,
    generated: Path,
    mode: str,
) -> dict[str, Any]:
    environment = dict(os.environ)
    configured_product = environment.get("SCIENCE_STUDIO_WHEEL")
    product_source = (
        Path(configured_product).expanduser().resolve()
        if configured_product
        else Path(__file__).resolve().parents[2]
    )
    if configured_product and not product_source.is_file():
        pytest.fail(f"SCIENCE_STUDIO_WHEEL is not a file: {product_source}")
    python_paths = [
        str(generated / "taskset"),
        str(product_source),
        str(repository),
    ]
    if existing := environment.get("PYTHONPATH"):
        python_paths.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    completed = subprocess.run(
        [
            str(interpreter),
            str(Path(__file__).with_name("_native_budget_probe.py")),
            mode,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        cwd=generated / "taskset",
    )
    assert completed.returncode == 0, (
        f"native budget probe failed\nstdout:\n{completed.stdout}"
        f"\nstderr:\n{completed.stderr}"
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


def _run_native_idempotency_probe(
    interpreter: Path,
    repository: Path,
    generated: Path,
) -> dict[str, Any]:
    environment = dict(os.environ)
    product_source = Path(__file__).resolve().parents[2]
    python_paths = [
        str(generated / "taskset"),
        str(product_source),
        str(repository),
    ]
    if existing := environment.get("PYTHONPATH"):
        python_paths.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    completed = subprocess.run(
        [
            str(interpreter),
            str(Path(__file__).with_name("_native_idempotency_probe.py")),
            str(generated / "configs/eval.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        cwd=generated / "taskset",
    )
    assert completed.returncode == 0, (
        f"native idempotency probe failed\nstdout:\n{completed.stdout}"
        f"\nstderr:\n{completed.stderr}"
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


def _one_persisted_trace(
    output_root: Path,
    run_name: str = "native-conformance",
) -> tuple[dict[str, Any], str]:
    path = output_root / run_name / "traces.jsonl"
    persisted = path.read_text()
    rows = [json.loads(line) for line in persisted.splitlines() if line.strip()]
    assert len(rows) == 1
    assert len(rows[0]["traces"]) == 1
    return rows[0]["traces"][0], persisted


def _assert_no_live_execution_material(
    trace: dict[str, Any],
    persisted: str,
    model_base_url: str,
) -> None:
    assert trace["agent"]["config"].get("client") is None
    assert trace["agent"]["runtime"].get("id") is None
    lowered = persisted.casefold()
    assert model_base_url.casefold() not in lowered
    assert str(Path.home()).casefold() not in lowered
    assert ".cache/verifiers" not in lowered
    assert "science-native-gemma-" not in lowered
    assert _SECRET.casefold() not in lowered
    assert _ATTESTATION_KEY.casefold() not in lowered


def test_native_null_harness_matches_the_product_runtime(tmp_path: Path) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server() as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    expected_names = [action.type for action in bundle.actions]
    assert model_server.requests
    assert model_server.secret_in_process_argv is False
    observed_tool_names = [
        [tool["function"]["name"] for tool in request["tools"]]
        for request in model_server.requests
    ]
    assert observed_tool_names == [sorted(expected_names)] * len(model_server.requests)
    assert all(
        "hidden" not in json.dumps(request, sort_keys=True).casefold()
        for request in model_server.requests
    )

    trace, persisted = _one_persisted_trace(output_root)
    direct_actions, direct = _direct_execution()
    direct_result = direct.verifier_result
    assert direct_result is not None
    runtime = trace["info"]["science_environment_runtime"]
    native_snapshot = runtime["completed_snapshot"]

    assert trace["task"]["data"]["scenario_id"] == LEGACY_SCENARIO_ID
    assert [tool["name"] for tool in trace["tools"]] == sorted(expected_names)
    assert native_snapshot["status"] == "completed"
    assert native_snapshot["observation"] == direct.observation
    assert native_snapshot["permitted_actions"] == list(direct.permitted_actions)
    assert native_snapshot["trace"] == [
        event.model_dump(mode="json") for event in direct.trace
    ]
    assert native_snapshot["verifier_result"] == direct_result.model_dump(mode="json")
    assert native_snapshot["trace_header"] == direct.trace_header.model_dump(mode="json")
    assert runtime["runtime_trace_digest"] == direct.trace_digest
    assert runtime["runtime_result_digest"] == direct.result_digest
    assert native_snapshot["trace_digest"] == direct.trace_digest
    assert native_snapshot["result_digest"] == direct.result_digest
    assert trace["rewards"]["reward"]["score"] == direct_result.metrics.get(
        "reward", 0.0
    )
    assert {
        name: value for name, value in trace["metrics"].items() if value is not None
    } == {
        name: value
        for name, value in direct_result.metrics.items()
        if name != "reward"
    }

    assistant_calls = [
        call
        for node in trace["nodes"]
        for call in node["message"].get("tool_calls", [])
    ]
    assert [call["name"] for call in assistant_calls] == list(_ACTIONS)
    assert len(trace["calls"]) == len(_ACTIONS)
    assert all(call["usage"]["completion_tokens"] == 4 for call in trace["calls"])
    assert trace["errors"] == []
    assert trace["agent"]["config"]["max_turns"] == 65
    assert trace["agent"]["config"]["timeout"]["rollout"] == 900
    assert runtime["budgets"] == {
        "framework_max_turns_sentinel": 65,
        "max_episode_seconds": 900,
        "max_provider_tool_calls": 64,
        "max_tool_calls": 64,
        "max_turns": 64,
    }
    tool_nodes = [node for node in trace["nodes"] if node["message"]["role"] == "tool"]
    # Pinned Verifiers checks @vf.stop after the terminal MCP state update and
    # before adding that call's tool-result node. Earlier native results remain
    # present; the terminal result is preserved by the completed Runtime snapshot.
    assert [node["message"]["name"] for node in tool_nodes] == list(_ACTIONS[:-1])
    assert all("observation" in json.loads(node["message"]["content"]) for node in tool_nodes)
    expected_policy_payloads = [
        ToolExecutionResult(
            call_id=f"episode-call-{ordinal:06d}",
            provider_call_id=f"native-call-{ordinal}",
            ordinal=ordinal,
            name=action,
            status="ok",
            observation=snapshot.observation,
            execution_id="sha256:" + f"{ordinal:064x}",
            cache_hit=False,
            retry_count=0,
        ).policy_payload()
        for ordinal, (action, snapshot) in enumerate(
            zip(_ACTIONS, direct_actions),
            start=1,
        )
    ]
    observed_policy_payloads = []
    for request in model_server.requests[1:]:
        tool_messages = [
            message for message in request["messages"] if message["role"] == "tool"
        ]
        assert tool_messages
        observed_policy_payloads.append(json.loads(tool_messages[-1]["content"]))
    assert observed_policy_payloads == expected_policy_payloads[:-1]
    assert all("permitted_actions" not in payload for payload in observed_policy_payloads)
    lineage = runtime["tool_lineage"]
    assert [item["call_id"] for item in lineage] == [
        f"episode-call-{index:06d}" for index in range(1, len(_ACTIONS) + 1)
    ]
    assert [item["provider_call_id_digest"] for item in lineage] == [
        "sha256:" + hashlib.sha256(f"native-call-{index}".encode()).hexdigest()
        for index in range(1, len(_ACTIONS) + 1)
    ]
    assert [item["ordinal"] for item in lineage] == list(
        range(1, len(_ACTIONS) + 1)
    )
    assert all(item["execution_id"].startswith("execution-") for item in lineage)
    assert all(item["cache_hit"] is False for item in lineage)
    assert all(item["retry_count"] == 0 for item in lineage)
    assert [item["result_linkage"] for item in lineage] == [
        "linked",
        "linked",
        "framework_stop_suppressed",
    ]
    assert [item["action"]["type"] for item in lineage] == list(_ACTIONS)
    assert len({item["call_id"] for item in lineage}) == len(lineage)
    assert [item["result"] for item in lineage[:-1]] == [
        json.loads(node["message"]["content"]) for node in tool_nodes
    ]
    assert lineage[-1]["result"] == {
        "status": "ok",
        "observation": native_snapshot["observation"],
    }
    native_actions = [
        event["action"]["type"]
        for event in native_snapshot["trace"]
        if event["type"] == "action"
    ]
    assert native_actions == list(_ACTIONS)
    assert native_actions == [call["name"] for call in assistant_calls]

    _assert_no_live_execution_material(trace, persisted, model_server.base_url)
    lowered = persisted.casefold()
    assert '"hidden"' not in lowered
    assert "curriculum_fixture" not in lowered
    assert "authoring" not in lowered


@pytest.mark.parametrize(
    ("actions", "finish_reason", "termination_reason", "expected_tool_error"),
    (
        ((), None, "model_ended_before_terminal", None),
        (
            ("inspect_onset_route",),
            "length",
            "output_budget_exhausted",
            "tool.output_budget_exhausted",
        ),
    ),
)
def test_native_incomplete_model_response_matches_product_runtime(
    tmp_path: Path,
    actions: tuple[str, ...],
    finish_reason: str | None,
    termination_reason: IncompleteTerminationReason,
    expected_tool_error: str | None,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(
        actions,
        response_finish_reason=finish_reason,
    ) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name=f"native-incomplete-{termination_reason}",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name=f"native-incomplete-{termination_reason}",
    )
    direct = _direct_incomplete(termination_reason)
    direct_result = direct.verifier_result
    assert direct_result is not None
    runtime = trace["info"]["science_environment_runtime"]
    native_snapshot = runtime["completed_snapshot"]
    assert native_snapshot["status"] == direct.status
    assert native_snapshot["observation"] == direct.observation
    assert native_snapshot["permitted_actions"] == list(direct.permitted_actions)
    assert native_snapshot["trace"] == [
        event.model_dump(mode="json") for event in direct.trace
    ]
    assert native_snapshot["verifier_result"] == direct_result.model_dump(mode="json")
    assert native_snapshot["trace_digest"] == direct.trace_digest
    assert native_snapshot["result_digest"] == direct.result_digest
    assert runtime["runtime_trace_digest"] == direct.trace_digest
    assert runtime["runtime_result_digest"] == direct.result_digest
    assert trace["rewards"]["reward"]["score"] == 0.0
    lineage = runtime["tool_lineage"]
    if expected_tool_error is None:
        assert lineage == []
    else:
        assert len(lineage) == 1
        assert lineage[0]["accepted"] is False
        assert lineage[0]["result"] == {
            "status": "error",
            "error_code": expected_tool_error,
        }
        assert lineage[0]["result_linkage"] == "framework_stop_suppressed"
    _assert_no_live_execution_material(trace, persisted, model_server.base_url)


def test_native_null_harness_refuses_an_unattested_model_server(tmp_path: Path) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(attest_runtime=False) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-unattested-server",
        )

    assert completed.returncode == 0
    assert model_server.attestation_requests
    assert model_server.requests == []
    trace, persisted = _one_persisted_trace(output_root, "native-unattested-server")
    assert trace["ok"] is False
    assert trace["rewards"].get("reward") is None
    assert _SECRET not in persisted
    assert _ATTESTATION_KEY not in persisted


def test_native_null_harness_rejects_provider_reflection_before_trace_persistence(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(actions=(), reflect_api_key=True) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-provider-reflection",
        )

    assert completed.returncode == 0
    assert model_server.attestation_requests
    assert model_server.requests
    trace, persisted = _one_persisted_trace(output_root, "native-provider-reflection")
    assert trace["ok"] is False
    assert trace["rewards"].get("reward") is None
    assert _SECRET not in persisted
    assert _ATTESTATION_KEY not in persisted
    assert model_server.base_url not in persisted


def test_native_null_harness_rejects_cumulative_provider_tool_call_overflow(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(
        actions=(),
        provider_tool_call_batch_size=33,
    ) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-provider-tool-call-overflow",
        )

    assert completed.returncode == 0
    assert model_server.attestation_requests
    assert len(model_server.requests) == 2
    trace, persisted = _one_persisted_trace(
        output_root,
        "native-provider-tool-call-overflow",
    )
    assert trace["ok"] is False
    assert trace["rewards"].get("reward") is None
    assert "science_environment_runtime" not in trace["info"]
    assert "native-overflow-call-1-" in persisted
    assert "native-overflow-call-2-" not in persisted
    assert _SECRET not in persisted
    assert _ATTESTATION_KEY not in persisted


def test_native_development_parameterized_action_matches_product_runtime(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = _development_bundle_with_fixture_first()
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)
    action_names = tuple(action for action, _arguments in _DEVELOPMENT_SUCCESS_ACTIONS)
    action_arguments = tuple(
        arguments for _action, arguments in _DEVELOPMENT_SUCCESS_ACTIONS
    )

    with _scripted_chat_server(
        action_names,
        action_arguments=action_arguments,
    ) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-development-parameterized",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert model_server.secret_in_process_argv is False
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name="native-development-parameterized",
    )
    _action_snapshots, direct = _direct_execution_for(
        bundle,
        _DEVELOPMENT_SCENARIO_ID,
        _DEVELOPMENT_SUCCESS_ACTIONS,
    )
    direct_result = direct.verifier_result
    assert direct_result is not None and direct_result.passed is True
    runtime = trace["info"]["science_environment_runtime"]
    native_snapshot = runtime["completed_snapshot"]
    assert trace["task"]["data"]["scenario_id"] == _DEVELOPMENT_SCENARIO_ID
    assert native_snapshot["status"] == direct.status
    assert native_snapshot["observation"] == direct.observation
    assert native_snapshot["permitted_actions"] == list(direct.permitted_actions)
    assert native_snapshot["trace"] == [
        event.model_dump(mode="json") for event in direct.trace
    ]
    assert native_snapshot["verifier_result"] == direct_result.model_dump(mode="json")
    assert native_snapshot["trace_header"] == direct.trace_header.model_dump(mode="json")
    assert native_snapshot["trace_digest"] == direct.trace_digest
    assert native_snapshot["result_digest"] == direct.result_digest
    assert runtime["runtime_trace_digest"] == direct.trace_digest
    assert runtime["runtime_result_digest"] == direct.result_digest
    assert trace["rewards"]["reward"]["score"] == direct_result.metrics["reward"]
    assert {
        name: value for name, value in trace["metrics"].items() if value is not None
    } == {
        name: value
        for name, value in direct_result.metrics.items()
        if name != "reward"
    }
    assert any(
        item["action"]
        == {
            "type": "reconnect_electrode_path",
            "arguments": {"site": "FC4"},
        }
        for item in runtime["tool_lineage"]
    )
    assert trace["errors"] == []
    _assert_no_live_execution_material(trace, persisted, model_server.base_url)


def test_native_development_scientific_failure_matches_product_runtime(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = _development_bundle_with_fixture_first()
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(("complete_preflight",)) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-development-scientific-failure",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert model_server.secret_in_process_argv is False
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name="native-development-scientific-failure",
    )
    _action_snapshots, direct = _direct_execution_for(
        bundle,
        _DEVELOPMENT_SCENARIO_ID,
        _DEVELOPMENT_FAILURE_ACTIONS,
    )
    direct_result = direct.verifier_result
    assert direct_result is not None and direct_result.passed is False
    runtime = trace["info"]["science_environment_runtime"]
    native_snapshot = runtime["completed_snapshot"]
    assert native_snapshot["status"] == direct.status
    assert native_snapshot["observation"] == direct.observation
    assert native_snapshot["permitted_actions"] == list(direct.permitted_actions)
    assert native_snapshot["trace"] == [
        event.model_dump(mode="json") for event in direct.trace
    ]
    assert native_snapshot["verifier_result"] == direct_result.model_dump(mode="json")
    assert native_snapshot["trace_header"] == direct.trace_header.model_dump(mode="json")
    assert native_snapshot["trace_digest"] == direct.trace_digest
    assert native_snapshot["result_digest"] == direct.result_digest
    assert runtime["runtime_trace_digest"] == direct.trace_digest
    assert runtime["runtime_result_digest"] == direct.result_digest
    assert trace["rewards"]["reward"]["score"] == direct_result.metrics["reward"]
    assert trace["errors"] == []
    _assert_no_live_execution_material(trace, persisted, model_server.base_url)


def test_native_rejects_a_hostname_client_route_before_model_contact(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server() as model_server:
        hostname_route = model_server.base_url.replace("127.0.0.1", "localhost")
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            hostname_route,
            model_server.unix_socket_path,
            run_name="native-public-route-refusal",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert model_server.requests == []
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name="native-public-route-refusal",
    )
    assert trace["ok"] is False
    assert trace["stop_condition"] == "error"
    assert trace["rewards"] == {}
    assert trace["metrics"] == {}
    assert trace["agent"]["config"].get("client") is None
    assert "science_environment_runtime" not in trace["info"]
    _assert_no_live_execution_material(trace, persisted, hostname_route)


def test_exact_native_transport_retry_is_idempotent_and_context_is_hidden(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    compile_verifiers_v1(bundle, generated)

    probe = _run_native_idempotency_probe(interpreter, repository, generated)
    assert probe["config"] == {
        "harness_id": "science-environment-generated",
        "max_turns": 65,
        "rollout_timeout": 900.0,
    }
    assert probe["cached_exactly"] is True
    assert probe["accepted_action_count"] == 1
    assert probe["tool_execution_count"] == 1
    assert probe["cache_entry_count"] == 1
    assert probe["cache_hit"] is True
    assert probe["retry_count"] == 1
    assert probe["execution_id"].startswith("execution-")
    assert probe["hidden_context"] is True
    assert probe["conflict_code"] == "adapter.transport_request_conflict"
    assert probe["conflict_failed_unscored"] is True
    assert probe["conflicting_result"] == {
        "error_code": "tool.transport_request_conflict",
        "status": "error",
    }
    assert probe["rejected_lineage"] == {
        "accepted": False,
        "action": {"arguments": {}, "type": "repair_refractory_route"},
        "cache_hit": False,
        "call_id": "episode-call-000002",
        "execution_id": probe["rejected_lineage"]["execution_id"],
        "ordinal": 2,
        "provider_call_id_digest": (
            "sha256:" + hashlib.sha256(b"provider-rejected").hexdigest()
        ),
        "result": {"error_code": "tool.action_rejected", "status": "error"},
        "result_linkage": "linked",
        "retry_count": 0,
    }
    assert probe["rejected_lineage"]["execution_id"].startswith("execution-")
    assert probe["unknown_lineage"] == {
        "accepted": False,
        "action": {"arguments": {}, "type": "not_a_declared_action"},
        "cache_hit": False,
        "call_id": "episode-call-000001",
        "execution_id": None,
        "ordinal": 1,
        "provider_call_id_digest": (
            "sha256:" + hashlib.sha256(b"provider-unknown").hexdigest()
        ),
        "result": {"error_code": "tool.unknown_action", "status": "error"},
        "result_linkage": "linked",
        "retry_count": 0,
    }
    assert probe["missing_result_error"] == "adapter.tool_result_missing"
    assert probe["malformed_result_error"] == "adapter.tool_result_malformed"
    assert probe["profile_drift_error"] == "adapter.evaluation_profile_drift"
    assert probe["drift_rejected"] is True
    assert probe["copied_seam_drift_rejected"] is True
    assert probe["transport"] == {
        "next_logical_call_is_unique": True,
        "observed_request_ids": [1_000_001, 1_000_001, 1_000_002],
        "retry_reused_request_id": True,
    }


def test_native_inference_refusal_is_sanitized_and_never_scored(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(refuse_model_calls=True) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-inference-refusal",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert len(model_server.requests) == 1
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name="native-inference-refusal",
    )
    assert trace["ok"] is False
    assert trace["stop_condition"] == "error"
    assert trace["errors"]
    assert trace["errors"][-1]["type"] == "ProviderError"
    assert trace["errors"][-1]["status_code"] == 401
    assert trace["rewards"] == {}
    assert trace["metrics"] == {}
    assert "science_environment_runtime" not in trace["info"]
    assert "science_environment_adapter_error" not in trace["info"]
    _assert_no_live_execution_material(trace, persisted, model_server.base_url)


def test_native_agent_timeout_is_framework_infrastructure_and_never_scored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    output_root = tmp_path / "outputs"
    # Compile a self-consistent one-second profile solely to exercise the exact
    # pinned framework timeout without waiting 900 seconds. Production output
    # is separately asserted to resolve and persist exactly 900.
    monkeypatch.setattr(compiler_module, "_MAX_EPISODE_SECONDS", 1)
    compile_verifiers_v1(bundle, generated)

    with _scripted_chat_server(response_delay_seconds=2.0) as model_server:
        completed = _run_native_eval(
            interpreter,
            repository,
            generated,
            output_root,
            model_server.base_url,
            model_server.unix_socket_path,
            run_name="native-agent-timeout",
        )

    assert completed.returncode == 0, (
        f"native eval failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    # The deadline may expire while the generated uv harness boots or while its
    # first delayed provider request is in flight; both are inside the exact
    # pinned framework's agent stage and must remain infrastructure-only.
    assert len(model_server.requests) <= 1
    trace, persisted = _one_persisted_trace(
        output_root,
        run_name="native-agent-timeout",
    )
    assert trace["ok"] is False
    assert trace["stop_condition"] == "error"
    assert trace["errors"][-1]["type"] == "HarnessError"
    assert "agent timeout" in trace["errors"][-1]["message"]
    assert trace["rewards"] == {}
    assert trace["metrics"] == {}
    assert "science_environment_runtime" not in trace["info"]
    assert "science_environment_adapter_error" not in trace["info"]
    _assert_no_live_execution_material(trace, persisted, model_server.base_url)


def test_native_turn_budget_finalizes_as_a_scientific_incomplete_result(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    compile_verifiers_v1(bundle, generated)

    probe = _run_native_budget_probe(interpreter, repository, generated, "turn")
    runtime = cast(dict[str, Any], probe["runtime"])
    snapshot = runtime["completed_snapshot"]
    assert probe["stopped"] is True
    assert probe["state_terminal"] is True
    assert snapshot["verifier_result"]["outcome_category"] == "incomplete"
    assert snapshot["verifier_result"]["evidence"] == {
        "termination_reason": "turn_budget_exhausted"
    }
    assert len(runtime["tool_lineage"]) == 64
    assert all(item["accepted"] is True for item in runtime["tool_lineage"][:63])
    assert runtime["tool_lineage"][-1] == {
        "accepted": False,
        "action": {
            "arguments": {"unexpected": True},
            "type": "inspect_onset_route",
        },
        "cache_hit": False,
        "call_id": "episode-call-000064",
        "execution_id": None,
        "ordinal": 64,
        "provider_call_id_digest": (
            "sha256:" + hashlib.sha256(b"native-call-64").hexdigest()
        ),
        "result_linkage": "framework_stop_suppressed",
        "retry_count": 0,
        "result": {"error_code": "tool.invalid_arguments", "status": "error"},
    }
    assert runtime["budgets"]["max_turns"] == 64
    assert runtime["budgets"]["framework_max_turns_sentinel"] == 65


def test_native_tool_budget_links_the_unexecuted_65th_same_batch_call(
    tmp_path: Path,
) -> None:
    interpreter = _external_python()
    repository = _assert_exact_verifiers_checkout(interpreter)
    bundle = validate_environment_bundle(load_legacy_bundle())
    generated = tmp_path / "generated"
    compile_verifiers_v1(bundle, generated)

    probe = _run_native_budget_probe(interpreter, repository, generated, "tool")
    runtime = cast(dict[str, Any], probe["runtime"])
    snapshot = runtime["completed_snapshot"]
    assert probe["boundary_result"]["status"] == "ok"
    assert probe["stopped"] is True
    assert probe["state_terminal"] is True
    assert probe["accepted_action_count"] == 64
    assert probe["runtime_execution_count"] == 64
    assert snapshot["verifier_result"]["outcome_category"] == "incomplete"
    assert snapshot["verifier_result"]["evidence"] == {
        "termination_reason": "tool_call_budget_exhausted"
    }
    lineage = runtime["tool_lineage"]
    assert len(lineage) == 65
    assert all(item["accepted"] is True for item in lineage[:64])
    assert lineage[-1] == {
        "accepted": False,
        "action": {"arguments": {}, "type": "inspect_onset_route"},
        "cache_hit": False,
        "call_id": "episode-call-000065",
        "execution_id": None,
        "ordinal": 65,
        "provider_call_id_digest": (
            "sha256:" + hashlib.sha256(b"native-call-65").hexdigest()
        ),
        "result_linkage": "framework_stop_suppressed",
        "retry_count": 0,
        "result": {"error_code": "tool.budget_exhausted", "status": "error"},
    }
