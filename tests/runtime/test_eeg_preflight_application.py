"""HTTP acceptance tests for EEG diagnostics inside the staged curriculum."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.application import create_app


def _freeze(client: TestClient) -> dict[str, object]:
    draft = client.get("/api/draft").json()
    response = client.post(
        "/api/draft/freeze",
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 201
    return response.json()


def _start(
    client: TestClient,
    frozen: dict[str, object],
    scenario_id: str,
) -> dict[str, object]:
    response = client.post(
        "/api/runs",
        json={
            "scenario_id": scenario_id,
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_http_exposes_an_opaque_fixed_demo_catalog_and_constant_typed_actions(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))

    environment = client.get("/api/environment").json()
    frozen = _freeze(client)

    assert "scenario_ids" not in environment
    assert "scenario_ids" not in frozen
    assert len(environment["seeded_examples"]) == 6
    assert all(
        example["label"] == f"Seeded example {label}"
        for example, label in zip(
            environment["seeded_examples"],
            "ABCDEF",
        )
    )
    assert environment["hidden_state_exposed"] is False
    assert environment["visualization"]["kind"] == "eeg_preflight_v1"

    actions = {action["type"]: action for action in environment["actions"]}
    assert {
        "inspect_eeg_signals",
        "inspect_frequency_evidence",
        "reseat_electrode",
        "replace_electrode",
        "collect_fresh_eeg_window",
        "inspect_onset_route",
        "present_test_flash",
        "inspect_response_timeline",
        "run_response_preflight",
        "inspect_recording_timeline",
        "complete_preflight",
        "abort_episode",
    }.issubset(actions)
    assert actions["reseat_electrode"]["group"] == "remediate"
    assert actions["reseat_electrode"]["changes_state"] is True
    assert actions["reseat_electrode"]["input_schema"]["properties"]["site"][
        "enum"
    ] == ["FC3", "FC4", "FT7", "FT8"]
    selected_id = environment["seeded_examples"][4]["scenario_id"]
    non_default = _start(client, frozen, selected_id)
    assert non_default["scenario_id"] == selected_id
    assert set(non_default["permitted_actions"]) == set(actions)
    serialized = str(non_default).casefold()
    assert "fault_family" not in serialized
    assert "expected_action" not in serialized
    assert "recoverability" not in serialized


def test_http_rejects_an_invalid_target_without_mutating_the_run_trace(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    environment = client.get("/api/environment").json()
    frozen = _freeze(client)
    started = _start(
        client,
        frozen,
        environment["seeded_examples"][0]["scenario_id"],
    )

    rejected = client.post(
        f"/api/runs/{started['run_id']}/actions",
        json={"type": "reseat_electrode", "input": {"site": "Oz"}},
    )

    assert rejected.status_code == 422
    unchanged = client.get(f"/api/runs/{started['run_id']}").json()
    assert unchanged["trace_digest"] == started["trace_digest"]
    assert unchanged["trace"] == started["trace"]


def test_frozen_authored_montage_drives_the_diagnostic_channels(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    seeded = client.get("/api/draft").json()
    edited = client.post(
        "/api/draft/commands",
        json={
            "command": "Add Cz to the Montage",
            "expected_revision": seeded["revision"],
        },
    ).json()["draft"]
    frozen_response = client.post(
        "/api/draft/freeze",
        json={"expected_revision": edited["revision"]},
    )
    assert frozen_response.status_code == 201
    frozen = frozen_response.json()

    selected_id = client.get("/api/environment").json()["seeded_examples"][1][
        "scenario_id"
    ]
    started = _start(client, frozen, selected_id)

    assert [
        channel["site"] for channel in started["observation"]["eeg_window"]["channels"]
    ] == ["FC3", "FC4", "FT7", "FT8", "Cz"]
    assert started["observation"]["montage"]["recording_sites"] == [
        "FC3",
        "FC4",
        "FT7",
        "FT8",
        "Cz",
    ]
    assert started["observation"]["procedure_configuration"] == frozen["procedure"]
