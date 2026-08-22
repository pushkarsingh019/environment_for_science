from fastapi.testclient import TestClient

from studio.application import create_app

_HIDDEN_STATE_KEYS = (
    "refractory_route_repaired",
    "route_inspected",
    "inspected_before_repair",
    "repair_transition",
)


def test_http_environment_and_start_run_use_the_real_runtime_contract() -> None:
    client = TestClient(create_app())

    environment_response = client.get("/api/environment")
    assert environment_response.status_code == 200
    environment = environment_response.json()
    assert environment == {
        "environment_id": "eeg-onset-marker-recovery",
        "scenario_id": "eeg-marker-recovery-001",
        "name": "EEG onset-marker preflight",
        "description": "A deterministic synthetic preflight for the onset-marker route.",
        "simulation_label": "Synthetic EEG apparatus simulation",
        "actions": [
            {
                "type": "inspect_onset_route",
                "title": "Inspect simulated onset route",
                "description": (
                    "Inspect current evidence from the simulated lower-right onset route."
                ),
            },
            {
                "type": "repair_refractory_route",
                "title": "Apply targeted simulated repair",
                "description": (
                    "Apply the targeted repair to the simulated refractory route."
                ),
            },
            {
                "type": "present_test_flash",
                "title": "Present fresh synthetic test flash",
                "description": (
                    "Present a fresh synthetic lower-right test flash and observe onset "
                    "markers."
                ),
            },
            {
                "type": "restart_response_handshake",
                "title": "Restart simulated response handshake",
                "description": (
                    "Restart the simulated response handshake; this does not alter the "
                    "onset route."
                ),
            },
        ],
        "visualization": {
            "kind": "eeg_onset_route",
            "title": "Onset-marker preflight",
            "display_label": "Presentation display",
            "flash_label": "Lower-right test flash",
            "route_nodes": [
                {
                    "id": "light_detector",
                    "name": "Light detector",
                    "detail": "simulated signal",
                    "emphasis": False,
                },
                {
                    "id": "refractory_route",
                    "name": "Refractory route",
                    "detail": "not inspected",
                    "emphasis": True,
                },
            ],
            "marker_lane_label": "Marker event lane",
            "freshness_label": "Evidence freshness",
        },
        "validation": {
            "status": "valid",
            "summary": "Environment Bundle v1 validated",
            "checks": [
                "Contract version supported",
                "Action and observation schemas validated",
                "Policy-visible observations separated from hidden scenario truth",
            ],
        },
        "hidden_state_exposed": False,
        "policy_agents": [
            {
                "id": "seeded-policy-agent",
                "name": "Seeded recovery Policy agent",
            }
        ],
    }

    start_response = client.post(
        "/api/runs",
        json={
            "scenario_id": environment["scenario_id"],
            "policy_agent": "seeded-policy-agent",
        },
    )
    assert start_response.status_code == 201
    snapshot = start_response.json()
    assert snapshot["scenario_id"] == "eeg-marker-recovery-001"
    assert snapshot["policy_agent"] == environment["policy_agents"][0]
    assert snapshot["observation"]["onset_timeline"]["marker_count"] == 2
    assert snapshot["status"] == "active"
    serialized = start_response.text
    for hidden_key in _HIDDEN_STATE_KEYS:
        assert hidden_key not in serialized
    assert '"hidden"' not in serialized


def test_http_runs_actions_verification_reset_and_true_replay() -> None:
    client = TestClient(create_app())
    started = client.post(
        "/api/runs",
        json={
            "scenario_id": "eeg-marker-recovery-001",
            "policy_agent": "seeded-policy-agent",
        },
    ).json()
    run_id = started["run_id"]

    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        response = client.post(
            f"/api/runs/{run_id}/actions",
            json={"type": action_type, "input": {}},
        )
        assert response.status_code == 200

    verify_response = client.post(f"/api/runs/{run_id}/verify")
    assert verify_response.status_code == 200
    completed = verify_response.json()
    assert completed["verifier_result"]["passed"] is True
    for hidden_key in _HIDDEN_STATE_KEYS:
        assert hidden_key not in verify_response.text

    get_response = client.get(f"/api/runs/{run_id}")
    assert get_response.status_code == 200
    assert get_response.json() == completed

    replay_response = client.post(f"/api/runs/{run_id}/replay")
    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert replay["replay"]["trace_matches"] is True
    assert replay["replay"]["result_matches"] is True
    assert replay["snapshot"]["trace_digest"] == completed["trace_digest"]
    assert replay["snapshot"]["result_digest"] == completed["result_digest"]

    reset_response = client.post(f"/api/runs/{run_id}/reset")
    assert reset_response.status_code == 200
    reset = reset_response.json()
    assert reset["run_id"] != run_id
    assert reset["lineage"] == {"operation": "reset", "source_run_id": run_id}
    assert reset["observation"]["onset_timeline"]["marker_count"] == 2
    assert client.get(f"/api/runs/{run_id}").json() == completed


def test_local_application_serves_built_console_without_shadowing_api(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>Science Environment Studio</title>",
        encoding="utf-8",
    )
    client = TestClient(create_app(console_dist=tmp_path))

    console_response = client.get("/")
    assert console_response.status_code == 200
    assert "Science Environment Studio" in console_response.text
    assert client.get("/api/environment").status_code == 200


def test_local_application_persists_each_started_trace_under_artifacts(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))

    response = client.post(
        "/api/runs",
        json={
            "scenario_id": "eeg-marker-recovery-001",
            "policy_agent": "seeded-policy-agent",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run_id"]
    assert (tmp_path / "traces" / f"{run_id}.jsonl").is_file()


def test_http_rejects_unknown_identity_scenario_run_action_and_extra_input() -> None:
    client = TestClient(create_app())

    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "unknown-scenario",
                "policy_agent": "seeded-policy-agent",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "eeg-marker-recovery-001",
                "policy_agent": "unknown-policy-agent",
            },
        ).status_code
        == 422
    )
    started = client.post(
        "/api/runs",
        json={
            "scenario_id": "eeg-marker-recovery-001",
            "policy_agent": "seeded-policy-agent",
        },
    ).json()
    assert client.get("/api/runs/unknown-run").status_code == 404
    assert (
        client.post(
            f"/api/runs/{started['run_id']}/actions",
            json={"type": "unknown-action", "input": {}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/runs/{started['run_id']}/actions",
            json={
                "type": "inspect_onset_route",
                "input": {},
                "unexpected": "must-not-be-accepted",
            },
        ).status_code
        == 422
    )
