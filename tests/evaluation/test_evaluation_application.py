"""HTTP contract tests for durable local model evaluations."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response

from studio.application import create_app
from studio.bundle import EnvironmentBundle
from studio.policy_evaluation.coordinator import EvaluationRunner
from studio.policy_evaluation.model_runner import (
    CanonicalModelRunner,
    EvaluationAttempt,
    ModelIdentity,
    ModelMessage,
    ModelProviderFailure,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from studio.policy_evaluation.runtime_bridge import EvaluationRuntimeBridge
from tests.evaluation.attested_provider_support import (
    TEST_ATTESTATION_KEY,
    SignedLocalGemmaTestProvider,
)


class _UnavailableProvider(SignedLocalGemmaTestProvider):
    def complete(self, request: ModelRequest) -> ModelResponse:
        del request
        raise ModelProviderFailure(
            category="inference",
            code="inference.unavailable",
        )


class _UnavailableRunnerFactory:
    def __init__(self) -> None:
        self.created = 0

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        self.created += 1
        return CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_UnavailableProvider(),
            max_turns=2,
            max_tool_calls=2,
        )


_SUCCESS_SCENARIO = "eeg-30ddbcb4ceb8016d"
_FAILURE_SCENARIO = "eeg-414eb6bd4efed5b8"
_SUCCESS_ACTIONS = (
    "inspect_configuration",
    "inspect_eeg_signals",
    "inspect_onset_route",
    "inspect_response_timeline",
    "inspect_recording_timeline",
    "complete_preflight",
)


class _ScriptedProvider(SignedLocalGemmaTestProvider):
    def __init__(self, actions: Sequence[str] | None) -> None:
        self._actions = None if actions is None else iter(actions)

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self._actions is None:
            raise ModelProviderFailure(
                category="inference",
                code="inference.unavailable",
            )
        action = next(self._actions)
        return ModelResponse(
            response_id=f"response-{request.turn}",
            returned_model="google/gemma-4-E4B-it",
            message=ModelMessage.assistant(
                f"Apply {action}.",
                tool_calls=(
                    ModelToolCall(
                        call_id=f"call-{request.turn}",
                        name=action,
                        arguments={},
                    ),
                ),
            ),
        )


class _MixedRunner:
    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._bundle = bundle.model_copy(deep=True)

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        actions: Sequence[str] | None
        if scenario_id == _SUCCESS_SCENARIO:
            actions = _SUCCESS_ACTIONS
        elif scenario_id == _FAILURE_SCENARIO:
            actions = ("complete_preflight",)
        else:
            actions = None
        return CanonicalModelRunner(
            bundle=self._bundle,
            runtime_bridge=EvaluationRuntimeBridge(self._bundle),
            provider=_ScriptedProvider(actions),
            max_turns=8,
            max_tool_calls=8,
        ).run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _MixedRunnerFactory:
    def __init__(self) -> None:
        self.created = 0

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        self.created += 1
        return _MixedRunner(bundle)


class _BlockingRunner:
    def __init__(
        self,
        bundle: EnvironmentBundle,
        started: threading.Event,
        release: threading.Event,
    ) -> None:
        self._delegate = CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_UnavailableProvider(),
            max_turns=2,
            max_tool_calls=2,
        )
        self._started = started
        self._release = release
        self._blocked = False

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        if not self._blocked:
            self._blocked = True
            self._started.set()
            if not self._release.wait(timeout=10):
                raise RuntimeError("test evaluation was not released")
        return self._delegate.run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _BlockingRunnerFactory:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        return _BlockingRunner(bundle, self.started, self.release)


class _InterruptingRunner:
    def __init__(self, bundle: EnvironmentBundle) -> None:
        self._delegate = CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_UnavailableProvider(),
            max_turns=2,
            max_tool_calls=2,
        )
        self._completed = 0

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        if self._completed == 1:
            raise RuntimeError("simulated local process interruption")
        self._completed += 1
        return self._delegate.run(
            scenario_id=scenario_id,
            objective=objective,
            model=model,
        )


class _InterruptOnceRunnerFactory:
    def __init__(self) -> None:
        self.created = 0

    def __call__(self, bundle: EnvironmentBundle) -> EvaluationRunner:
        self.created += 1
        if self.created == 1:
            return _InterruptingRunner(bundle)
        return CanonicalModelRunner(
            bundle=bundle,
            runtime_bridge=EvaluationRuntimeBridge(bundle),
            provider=_UnavailableProvider(),
            max_turns=2,
            max_tool_calls=2,
        )


def test_launch_accepts_only_the_fixed_profile_envelope_and_schedules_execution(
    tmp_path: Path,
) -> None:
    factory = _UnavailableRunnerFactory()
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            evaluation_runner_factory=factory,
        )
    )

    assert client.post("/api/evaluations", json={}).status_code == 422
    rejected_transport = client.post(
        "/api/evaluations",
        json={
            "profile": "base-gemma-development-v1",
            "endpoint": "https://private.invalid?token=do-not-return",
        },
    )
    assert rejected_transport.status_code == 422
    assert "private.invalid" not in rejected_transport.text
    assert "do-not-return" not in rejected_transport.text
    assert (
        client.post(
            "/api/evaluations",
            json={"profile": "anything-else"},
        ).status_code
        == 422
    )

    response = client.post(
        "/api/evaluations",
        json={"profile": "base-gemma-development-v1"},
    )

    assert response.status_code == 202
    launched = response.json()
    assert set(launched) == {
        "evaluation_id",
        "status",
        "plan",
        "progress",
        "calibration",
        "attempts",
    }
    assert launched["status"] == "queued"
    assert launched["plan"]["profile"] == "base-gemma-development-v1"
    assert launched["plan"]["split"] == "development"
    assert len(launched["plan"]["scenario_ids"]) == 32
    assert launched["attempts"] == []
    assert launched["calibration"]["status"] == "pending"
    assert launched["calibration"]["scientific_accuracy"] is None
    assert factory.created == 1

    completed = client.get(f"/api/evaluations/{launched['evaluation_id']}").json()
    assert completed["progress"]["message"] == (
        "Completed all 32 development scenarios: 0 scientific successes, "
        "0 scientific failures, and 32 infrastructure errors."
    )

    with sqlite3.connect(tmp_path / "evaluations" / "evaluations.sqlite3") as connection:
        connection.execute(
            "UPDATE evaluation_plans SET plan_json = ? WHERE evaluation_id = ?",
            (
                '{"endpoint":"https://private.invalid","secret":"do-not-return"}',
                launched["evaluation_id"],
            ),
        )
    internal_error = client.get(f"/api/evaluations/{launched['evaluation_id']}")
    assert internal_error.status_code == 500
    assert internal_error.json() == {
        "detail": "The local evaluation could not complete the operation."
    }
    assert "private.invalid" not in internal_error.text
    assert "do-not-return" not in internal_error.text


def test_local_request_boundary_rejects_rebinding_and_cross_site_mutation(
    tmp_path: Path,
) -> None:
    app = create_app(
        artifact_root=tmp_path,
        evaluation_runner_factory=_UnavailableRunnerFactory(),
    )
    rebound = TestClient(app, base_url="http://attacker.example:8000")
    assert rebound.get("/api/evaluations").status_code == 400
    network_testserver = TestClient(
        app,
        base_url="http://testserver:8000",
        client=("127.0.0.1", 50_000),
    )
    assert network_testserver.get("/api/evaluations").status_code == 400

    local = TestClient(app, base_url="http://127.0.0.1:8000")
    for hostile_headers in (
        {"Origin": "http://attacker.example:9000"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        cross_site = local.post(
            "/api/evaluations",
            json={"profile": "base-gemma-development-v1"},
            headers=hostile_headers,
        )
        assert cross_site.status_code == 403

    same_origin_headers = {
        "Origin": "http://127.0.0.1:8000",
        "Sec-Fetch-Site": "same-origin",
    }
    missing_session = local.post(
        "/api/evaluations",
        json={"profile": "base-gemma-development-v1"},
        headers=same_origin_headers,
    )
    assert missing_session.status_code == 403

    session_response = local.get(
        "/api/evaluations",
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert session_response.status_code == 200
    set_cookie = session_response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    session_cookie = local.cookies.get("science_studio_session")
    assert session_cookie is not None
    assert len(session_cookie) >= 43

    accepted = local.post(
        "/api/evaluations",
        json={"profile": "base-gemma-development-v1"},
        headers=same_origin_headers,
    )
    assert accepted.status_code == 202


def test_list_load_persist_and_replay_keep_outcomes_and_transport_data_separate(
    tmp_path: Path,
) -> None:
    factory = _MixedRunnerFactory()
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            evaluation_runner_factory=factory,
        )
    )
    launched = client.post(
        "/api/evaluations",
        json={"profile": "base-gemma-development-v1"},
    ).json()
    evaluation_id = launched["evaluation_id"]

    loaded_response = client.get(f"/api/evaluations/{evaluation_id}")
    assert loaded_response.status_code == 200
    loaded = loaded_response.json()
    assert loaded["status"] == "completed"
    assert loaded["attempts"][0]["attempt_id"] == "attempt-0001"
    assert loaded["attempts"][0]["ordinal"] == 0
    assert loaded["progress"] == {
        "phase": "completed",
        "message": (
            "Completed all 32 development scenarios: 1 scientific success, "
            "1 scientific failure, and 30 infrastructure errors."
        ),
        "completed_scenarios": 32,
        "total_scenarios": 32,
        "scientific_successes": 1,
        "scientific_failures": 1,
        "infrastructure_errors": 30,
    }
    dispositions = {item["disposition"] for item in loaded["attempts"]}
    assert dispositions == {
        "scientific_success",
        "scientific_failure",
        "infrastructure_error",
    }
    assessment = loaded["calibration"]
    assert assessment["status"] == "not_ready"
    assert assessment["scientific_accuracy"] == 0.5
    assert assessment["overall_accuracy_in_target"] is True
    assert assessment["levels_1_and_2_mixed"] is False
    assert assessment["no_infrastructure_errors"] is False
    assert assessment["authenticated_local_runtime"] is True
    assert [level["total_scenarios"] for level in assessment["levels"]] == [
        4,
        4,
        4,
        8,
        8,
        4,
    ]
    assert sum(level["completed_scenarios"] for level in assessment["levels"]) == 32
    assert "fault" not in json.dumps(assessment).casefold()

    listed_response = client.get("/api/evaluations")
    assert listed_response.status_code == 200
    assert listed_response.json()[0]["evaluation_id"] == evaluation_id
    assert listed_response.json()[0]["progress"] == loaded["progress"]

    reopened = TestClient(create_app(artifact_root=tmp_path))
    assert reopened.get(f"/api/evaluations/{evaluation_id}").json() == loaded

    attempts_by_disposition = {item["disposition"]: item for item in loaded["attempts"]}
    success_attempt = attempts_by_disposition["scientific_success"]
    first_replay = reopened.post(
        f"/api/evaluations/{evaluation_id}/attempts/{success_attempt['attempt_id']}/replay"
    )
    assert first_replay.status_code == 200
    first_replay_body = first_replay.json()
    assert first_replay_body["snapshot"]["status"] == "completed"
    assert first_replay_body["report"]["trace_matches"] is True
    assert first_replay_body["report"]["result_matches"] is True
    interaction = first_replay_body["interaction"]
    assert interaction["runtime_trace_digest"] == success_attempt["runtime_trace_digest"]
    assert interaction["budgets"] == {
        "max_turns": 8,
        "max_tool_calls": 8,
        "max_provider_tool_calls": 64,
        "max_episode_seconds": 900,
    }
    assert interaction["run"]["local_gemma_attestation"]["max_episode_seconds"] == 900
    assert (
        interaction["run"]["local_gemma_attestation"]["serving_image_digest_provenance"]
        == "operator-supplied"
    )
    assert {event["type"] for event in interaction["runtime_events"]} == {
        "observation",
        "action",
        "transition",
        "verifier",
    }
    assert [action["type"] for action in interaction["accepted_actions"]] == list(_SUCCESS_ACTIONS)
    assistant_messages = [
        message for message in interaction["messages"] if message["role"] == "assistant"
    ]
    assert [
        (message["response_turn"], message["response_id"]) for message in assistant_messages
    ] == [(response["turn"], response["response_id"]) for response in interaction["responses"]]
    assistant_calls = [
        call
        for message in interaction["messages"]
        if message["role"] == "assistant"
        for call in message["tool_calls"]
    ]
    tool_messages = [message for message in interaction["messages"] if message["role"] == "tool"]
    assert [call["call_id"] for call in assistant_calls] == [
        f"episode-call-{ordinal:06d}" for ordinal in range(1, 7)
    ]
    assert [call["provider_call_id"] for call in assistant_calls] == [
        f"call-{ordinal}" for ordinal in range(1, 7)
    ]
    assert [call["ordinal"] for call in assistant_calls] == list(range(1, 7))
    assert [
        (
            result["call_id"],
            result["provider_call_id"],
            result["ordinal"],
            result["name"],
        )
        for result in interaction["tool_results"]
    ] == [
        (call["call_id"], call["provider_call_id"], call["ordinal"], call["name"])
        for call in assistant_calls
    ]
    assert [
        (
            message["tool_call_id"],
            message["provider_tool_call_id"],
            message["tool_call_ordinal"],
            message["tool_name"],
        )
        for message in tool_messages
    ] == [
        (call["call_id"], call["provider_call_id"], call["ordinal"], call["name"])
        for call in assistant_calls
    ]
    assert len(interaction["runtime_executions"]) == len(_SUCCESS_ACTIONS)
    for call, result, execution in zip(
        assistant_calls,
        interaction["tool_results"],
        interaction["runtime_executions"],
    ):
        assert execution["call_id"] == call["call_id"] == result["call_id"]
        assert execution["ordinal"] == call["ordinal"] == result["ordinal"]
        assert execution["action"] == {
            "type": call["name"],
            "arguments": call["arguments"],
        }
        assert execution["execution_id"] == result["execution_id"]
        assert execution["observation"] == result["observation"]
        assert execution["cache_hit"] is result["cache_hit"] is False
        assert execution["retry_count"] == result["retry_count"] == 0
    assert interaction["accepted_actions"] == [
        execution["action"] for execution in interaction["runtime_executions"]
    ]
    second_replay_body = reopened.post(
        f"/api/evaluations/{evaluation_id}/attempts/{success_attempt['attempt_id']}/replay"
    ).json()
    assert second_replay_body["report"] == first_replay_body["report"]
    assert (
        second_replay_body["snapshot"]["trace_digest"]
        == first_replay_body["snapshot"]["trace_digest"]
    )

    infrastructure_attempt = attempts_by_disposition["infrastructure_error"]
    infrastructure_replay = reopened.post(
        f"/api/evaluations/{evaluation_id}/attempts/{infrastructure_attempt['attempt_id']}/replay"
    )
    assert infrastructure_replay.status_code == 200
    assert infrastructure_replay.json()["snapshot"] is None
    assert infrastructure_replay.json()["report"] is None
    assert infrastructure_replay.json()["interaction"]["runtime_events"]
    assert infrastructure_replay.json()["infrastructure_error"] == {
        "category": "inference",
        "code": "inference.unavailable",
        "summary": "The inference service failed.",
    }

    public_responses = json.dumps(
        {
            "launch": launched,
            "loaded": loaded,
            "listed": listed_response.json(),
            "scientific_replay": first_replay_body,
            "infrastructure_replay": infrastructure_replay.json(),
        }
    ).casefold()
    for forbidden in (
        "base_url",
        "endpoint",
        "password",
        "secret",
        "http://",
        "https://",
        "127.0.0.1",
        "10.0.0.7",
    ):
        assert forbidden not in public_responses
    assert TEST_ATTESTATION_KEY.casefold() not in public_responses
    assert factory.created == 1

    unknown_evaluation = "evaluation-" + "f" * 32
    missing_evaluation = reopened.get(f"/api/evaluations/{unknown_evaluation}")
    assert missing_evaluation.status_code == 404
    missing_attempt = reopened.post(
        f"/api/evaluations/{evaluation_id}/attempts/attempt-9999/replay"
    )
    assert missing_attempt.status_code == 404


def test_background_evaluation_does_not_monopolize_the_environment_endpoint(
    tmp_path: Path,
) -> None:
    factory = _BlockingRunnerFactory()
    app = create_app(
        artifact_root=tmp_path,
        evaluation_runner_factory=factory,
    )
    launch_client = TestClient(app)
    ordinary_client = TestClient(app)
    launch_result: dict[str, Response] = {}

    def launch() -> None:
        launch_result["response"] = launch_client.post(
            "/api/evaluations",
            json={"profile": "base-gemma-development-v1"},
        )

    launch_thread = threading.Thread(target=launch, daemon=True)
    launch_thread.start()
    assert factory.started.wait(timeout=5)

    running = ordinary_client.get("/api/evaluations")
    assert running.status_code == 200
    assert running.json()[0]["status"] == "running"
    running_resume = ordinary_client.post(
        f"/api/evaluations/{running.json()[0]['evaluation_id']}/resume"
    )
    assert running_resume.status_code == 202
    assert running_resume.json()["status"] == "running"
    pending_replay = ordinary_client.post(
        f"/api/evaluations/{running.json()[0]['evaluation_id']}/attempts/attempt-0001/replay"
    )
    assert pending_replay.status_code == 409

    environment_result: dict[str, Response] = {}

    def load_environment() -> None:
        environment_result["response"] = ordinary_client.get("/api/environment")

    environment_thread = threading.Thread(target=load_environment, daemon=True)
    environment_thread.start()
    environment_thread.join(timeout=2)
    environment_was_responsive = not environment_thread.is_alive()

    factory.release.set()
    launch_thread.join(timeout=20)
    environment_thread.join(timeout=5)

    assert environment_was_responsive
    environment_response = environment_result["response"]
    assert environment_response.status_code == 200
    launch_response = launch_result["response"]
    assert launch_response.status_code == 202


def test_interrupted_evaluation_resumes_in_background_without_replacing_evidence(
    tmp_path: Path,
) -> None:
    factory = _InterruptOnceRunnerFactory()
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            evaluation_runner_factory=factory,
        )
    )

    launched = client.post(
        "/api/evaluations",
        json={"profile": "base-gemma-development-v1"},
    ).json()
    evaluation_id = launched["evaluation_id"]
    interrupted = client.get(f"/api/evaluations/{evaluation_id}").json()

    assert interrupted["status"] == "interrupted"
    assert interrupted["progress"]["completed_scenarios"] == 1
    preserved_attempt = interrupted["attempts"][0]

    resumed_response = client.post(f"/api/evaluations/{evaluation_id}/resume")

    assert resumed_response.status_code == 202
    assert resumed_response.json() == interrupted
    completed = client.get(f"/api/evaluations/{evaluation_id}").json()
    assert completed["status"] == "completed"
    assert completed["progress"]["completed_scenarios"] == 32
    assert completed["attempts"][0] == preserved_attempt
    assert factory.created == 2

    repeated = client.post(f"/api/evaluations/{evaluation_id}/resume")

    assert repeated.status_code == 202
    assert repeated.json() == completed
    assert factory.created == 2
