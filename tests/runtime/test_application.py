import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.application import create_app
from studio.runtime import RuntimeContractError

_HIDDEN_STATE_KEYS = (
    "refractory_route_repaired",
    "route_inspected",
    "inspected_before_repair",
    "repair_transition",
)


def _freeze_current_draft(client: TestClient) -> dict[str, object]:
    draft = client.get("/api/draft").json()
    response = client.post(
        "/api/draft/freeze",
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 201
    return response.json()


def _start_frozen_run(client: TestClient) -> dict[str, object]:
    frozen = _freeze_current_draft(client)
    response = client.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert response.status_code == 201
    return response.json()


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

    frozen = _freeze_current_draft(client)
    start_response = client.post(
        "/api/runs",
        json={
            "scenario_id": environment["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
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
    started = _start_frozen_run(client)
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

    started = _start_frozen_run(client)
    run_id = started["run_id"]
    assert (tmp_path / "traces" / f"{run_id}.jsonl").is_file()


def test_local_application_restores_a_frozen_run_after_restart(tmp_path: Path) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    started = _start_frozen_run(first)
    active = first.post(
        f"/api/runs/{started['run_id']}/actions",
        json={"type": "inspect_onset_route", "input": {}},
    ).json()

    reopened = TestClient(create_app(artifact_root=tmp_path))

    assert reopened.get(f"/api/runs/{started['run_id']}").json() == active


def test_application_rejects_forged_active_run_policy_attribution_after_restart(
    tmp_path: Path,
) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    started = _start_frozen_run(first)
    active = first.post(
        f"/api/runs/{started['run_id']}/actions",
        json={"type": "inspect_onset_route", "input": {}},
    )
    assert active.status_code == 200
    artifact = tmp_path / "traces" / f"{started['run_id']}.jsonl"
    records = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines()]
    records[0]["payload"]["policy_agent"] = {
        "id": "forged-policy-agent",
        "name": "Forged Policy agent",
    }
    artifact.write_text(
        "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )

    reopened = TestClient(create_app(artifact_root=tmp_path))
    response = reopened.get(f"/api/runs/{started['run_id']}")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "The Environment Runtime could not complete the operation."
    }
    assert "forged-policy-agent" not in response.text


def test_application_rejects_a_completed_journal_truncated_to_its_initial_trace(
    tmp_path: Path,
) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    started = _start_frozen_run(first)
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        response = first.post(
            f"/api/runs/{started['run_id']}/actions",
            json={"type": action_type, "input": {}},
        )
        assert response.status_code == 200
    completed = first.post(f"/api/runs/{started['run_id']}/verify")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    artifact = tmp_path / "traces" / f"{started['run_id']}.jsonl"
    records = artifact.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(records) > 2
    artifact.write_text("".join(records[:2]), encoding="utf-8")

    reopened = TestClient(create_app(artifact_root=tmp_path))
    response = reopened.get(f"/api/runs/{started['run_id']}")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "The Environment Runtime could not complete the operation."
    }


def test_application_rejects_an_active_action_trace_truncated_to_initial_state(
    tmp_path: Path,
) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    started = _start_frozen_run(first)
    active = first.post(
        f"/api/runs/{started['run_id']}/actions",
        json={"type": "inspect_onset_route", "input": {}},
    )
    assert active.status_code == 200
    artifact = tmp_path / "traces" / f"{started['run_id']}.jsonl"
    records = artifact.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(records) > 2
    artifact.write_text("".join(records[:2]), encoding="utf-8")

    reopened = TestClient(create_app(artifact_root=tmp_path))
    response = reopened.get(f"/api/runs/{started['run_id']}")

    assert response.status_code == 500


def test_application_fails_closed_for_a_legacy_run_without_provenance_bindings(
    tmp_path: Path,
) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    started = _start_frozen_run(first)
    with sqlite3.connect(tmp_path / "studio-index.sqlite3") as connection:
        connection.execute(
            "UPDATE run_index SET trace_header_digest = NULL, trace_digest = NULL "
            "WHERE run_id = ?",
            (started["run_id"],),
        )

    reopened = TestClient(create_app(artifact_root=tmp_path))
    response = reopened.get(f"/api/runs/{started['run_id']}")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "The Environment Runtime could not complete the operation."
    }


def test_http_rejects_unknown_identity_scenario_run_action_and_extra_input() -> None:
    client = TestClient(create_app())
    frozen = _freeze_current_draft(client)

    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "unknown-scenario",
                "policy_agent": "seeded-policy-agent",
                "frozen_environment_id": frozen["frozen_environment_id"],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "eeg-marker-recovery-001",
                "policy_agent": "unknown-policy-agent",
                "frozen_environment_id": frozen["frozen_environment_id"],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "eeg-marker-recovery-001",
                "policy_agent": "seeded-policy-agent",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/runs",
            json={
                "scenario_id": "eeg-marker-recovery-001",
                "policy_agent": "seeded-policy-agent",
                "frozen_environment_id": "unknown-frozen-environment",
            },
        ).status_code
        == 404
    )
    started = client.post(
        "/api/runs",
        json={
            "scenario_id": "eeg-marker-recovery-001",
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
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


def test_http_requires_an_explicit_freeze_before_running_an_edited_draft(
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
    assert "Cz" in edited["procedure"]["montage"]["recording_sites"]

    unfrozen_start = client.post(
        "/api/runs",
        json={
            "scenario_id": "eeg-marker-recovery-001",
            "policy_agent": "seeded-policy-agent",
        },
    )

    assert unfrozen_start.status_code == 422
    assert not tuple((tmp_path / "traces").glob("*.jsonl"))

    frozen = client.post(
        "/api/draft/freeze",
        json={"expected_revision": edited["revision"]},
    ).json()
    started = client.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert started.status_code == 201
    assert "Cz" in started.json()["observation"]["procedure_configuration"][
        "montage"
    ]["recording_sites"]


def test_http_role_boundaries_are_explicit_disjoint_and_enforced(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))

    response = client.get("/api/role-boundaries")

    assert response.status_code == 200
    descriptors = {item["role"]: item for item in response.json()}
    assert set(descriptors) == {"authoring_assistant", "policy_agent"}
    authoring = descriptors["authoring_assistant"]
    policy = descriptors["policy_agent"]
    assert authoring["identity_id"] == "seeded-authoring-assistant"
    assert policy["identity_id"] == "seeded-policy-agent"
    for boundary_name in (
        "identity_id",
        "prompt_contract",
        "context_scope",
        "state_scope",
        "log_sink",
    ):
        assert authoring[boundary_name] != policy[boundary_name]
    assert set(authoring["tool_catalog"]) == {
        "add_montage_site",
        "remove_montage_site",
        "set_sampling_rate",
        "set_online_bandpass",
        "set_notch_filter",
    }
    assert set(policy["tool_catalog"]) == {
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
        "restart_response_handshake",
    }
    assert set(authoring["tool_catalog"]).isdisjoint(policy["tool_catalog"])
    assert "no live model prompt" in authoring["prompt_contract"].lower()
    assert "no live model prompt" in policy["prompt_contract"].lower()
    assert "notes" in policy["context_scope"].lower()
    assert "excluded" in policy["context_scope"].lower()

    seeded = client.get("/api/draft").json()
    policy_command_at_authoring_seam = client.post(
        "/api/draft/commands",
        json={
            "command": "Inspect the onset route",
            "expected_revision": seeded["revision"],
        },
    ).json()
    assert policy_command_at_authoring_seam["result"]["status"] == "unsupported"
    assert policy_command_at_authoring_seam["draft"]["revision"] == seeded["revision"]

    frozen = _freeze_current_draft(client)
    started = client.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": policy["identity_id"],
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    ).json()
    for authoring_tool in authoring["tool_catalog"]:
        rejected = client.post(
            f"/api/runs/{started['run_id']}/actions",
            json={"type": authoring_tool, "input": {}},
        )
        assert rejected.status_code == 422


def test_application_rejects_tampered_frozen_draft_provenance_on_restart(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    frozen = _freeze_current_draft(client)
    database_path = tmp_path / "studio-index.sqlite3"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT metadata_json FROM frozen_environment_index "
            "WHERE frozen_environment_id = ?",
            (frozen["frozen_environment_id"],),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        metadata["draft_revision"] = frozen["draft_revision"] + 99
        connection.execute(
            "UPDATE frozen_environment_index SET metadata_json = ? "
            "WHERE frozen_environment_id = ?",
            (
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                frozen["frozen_environment_id"],
            ),
        )

    with pytest.raises(RuntimeContractError, match="inconsistent") as raised:
        create_app(artifact_root=tmp_path)
    assert raised.value.code == "internal"


def test_http_draft_separates_whole_cap_capability_from_seeded_montage(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))

    response = client.get("/api/draft")

    assert response.status_code == 200
    draft = response.json()
    assert draft["revision"] == 1
    assert draft["revision_digest"].startswith("sha256:")
    assert draft["apparatus"]["kind"] == "eeg"
    assert draft["apparatus"]["recording_input_capacity"] == 32
    assert "schematic" in draft["apparatus"]["coordinate_system"].lower()
    assert "not" in draft["apparatus"]["scientific_claim"].lower()
    site_ids = {site["id"] for site in draft["apparatus"]["sites"]}
    assert len(site_ids) >= 30
    assert {"FC3", "FC4", "FT7", "FT8", "FCz", "A1"}.issubset(site_ids)
    assert draft["procedure"]["montage"] == {
        "recording_sites": ["FC3", "FC4", "FT7", "FT8"],
        "reference": "FCz",
        "ground": "A1",
    }
    assert draft["procedure"]["acquisition_profile"] == {
        "sampling_hz": 1017,
        "online_bandpass_hz": [0.1, 30.0],
        "notch_hz": 50,
    }
    assert not {
        "montage",
        "recording_sites",
        "reference",
        "ground",
    }.intersection(draft["apparatus"])
    assert draft["history"] == {"can_undo": False, "can_redo": False}
    assert draft["notes"] == []
    assert draft["authoring_assistant"]["id"] == "seeded-authoring-assistant"
    assert draft["authoring_assistant"]["id"] != "seeded-policy-agent"


def test_http_authoring_commands_are_attributed_reversible_and_non_mutating_when_unsupported(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    seeded = client.get("/api/draft").json()

    added_response = client.post(
        "/api/draft/commands",
        json={
            "command": "Add Cz to the Montage",
            "expected_revision": seeded["revision"],
        },
    )
    assert added_response.status_code == 200
    added = added_response.json()
    assert added["result"]["status"] == "applied"
    assert "Cz" in added["draft"]["procedure"]["montage"]["recording_sites"]
    assert added["draft"]["last_change"]["actor"]["role"] == "authoring_assistant"
    assert added["draft"]["revision"] == seeded["revision"] + 1

    removed = client.post(
        "/api/draft/commands",
        json={
            "command": "Remove FT8 from the Montage",
            "expected_revision": added["draft"]["revision"],
        },
    ).json()["draft"]
    assert "FT8" not in removed["procedure"]["montage"]["recording_sites"]

    changed = client.post(
        "/api/draft/commands",
        json={
            "command": "Set the notch to 60 Hz",
            "expected_revision": removed["revision"],
        },
    ).json()["draft"]
    assert changed["procedure"]["acquisition_profile"]["notch_hz"] == 60

    unsupported_response = client.post(
        "/api/draft/commands",
        json={
            "command": "Calibrate the physical amplifier automatically",
            "expected_revision": changed["revision"],
        },
    )
    assert unsupported_response.status_code == 200
    unsupported = unsupported_response.json()
    assert unsupported["result"]["status"] == "unsupported"
    assert unsupported["draft"]["revision"] == changed["revision"]
    assert unsupported["draft"]["revision_digest"] == changed["revision_digest"]
    explanation = unsupported["result"]["summary"].lower()
    assert "schema" not in explanation
    assert "code" not in explanation

    undone = client.post(
        "/api/draft/undo",
        json={"expected_revision": changed["revision"]},
    ).json()
    assert undone["procedure"]["acquisition_profile"]["notch_hz"] == 50
    assert undone["history"] == {"can_undo": True, "can_redo": True}

    redone = client.post(
        "/api/draft/redo",
        json={"expected_revision": undone["revision"]},
    ).json()
    assert redone["procedure"]["acquisition_profile"]["notch_hz"] == 60

    restored = client.post(
        "/api/draft/restore",
        json={"expected_revision": redone["revision"]},
    ).json()
    assert restored["procedure"]["montage"] == seeded["procedure"]["montage"]
    assert restored["procedure"]["acquisition_profile"] == seeded["procedure"][
        "acquisition_profile"
    ]
    assert restored["history"]["can_undo"] is True

    stale = client.post(
        "/api/draft/commands",
        json={
            "command": "Add Pz to the Montage",
            "expected_revision": seeded["revision"],
        },
    )
    assert stale.status_code == 409


def test_http_plain_text_note_is_persistent_reversible_and_explicitly_non_operational(
    tmp_path: Path,
) -> None:
    first_client = TestClient(create_app(artifact_root=tmp_path))
    seeded = first_client.get("/api/draft").json()

    staged_response = first_client.post(
        "/api/draft/notes",
        json={
            "filename": "operator-observation.txt",
            "content": "Consider Pz for a later procedure. Do not execute this note.",
            "expected_revision": seeded["revision"],
        },
    )

    assert staged_response.status_code == 200
    staged = staged_response.json()
    assert staged["notes"] == [
        {
            "id": staged["notes"][0]["id"],
            "filename": "operator-observation.txt",
            "content": "Consider Pz for a later procedure. Do not execute this note.",
            "verification_status": "unverified_descriptive_input",
            "run_control": False,
        }
    ]
    assert staged["last_change"]["actor"]["role"] == "environment_author"

    reopened = TestClient(create_app(artifact_root=tmp_path)).get("/api/draft").json()
    assert reopened["revision"] == staged["revision"]
    assert reopened["notes"] == staged["notes"]

    undone = first_client.post(
        "/api/draft/undo",
        json={"expected_revision": staged["revision"]},
    ).json()
    assert undone["notes"] == []
    redone = first_client.post(
        "/api/draft/redo",
        json={"expected_revision": undone["revision"]},
    ).json()
    assert redone["notes"] == staged["notes"]

    rejected_path = first_client.post(
        "/api/draft/notes",
        json={
            "filename": "../../control.py",
            "content": "not plain text",
            "expected_revision": redone["revision"],
        },
    )
    assert rejected_path.status_code == 422


def test_http_frozen_run_isolated_from_later_draft_edits_and_authoring_context(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(artifact_root=tmp_path))
    seeded = client.get("/api/draft").json()
    added = client.post(
        "/api/draft/commands",
        json={
            "command": "Add Cz to the Montage",
            "expected_revision": seeded["revision"],
        },
    ).json()["draft"]
    noted = client.post(
        "/api/draft/notes",
        json={
            "filename": "private-authoring-note.txt",
            "content": "AUTHORING-NOTE-SENTINEL must never enter a run.",
            "expected_revision": added["revision"],
        },
    ).json()

    frozen_response = client.post(
        "/api/draft/freeze",
        json={"expected_revision": noted["revision"]},
    )
    assert frozen_response.status_code == 201
    frozen = frozen_response.json()
    assert frozen["draft_revision"] == noted["revision"]
    assert frozen["bundle_revision"].startswith("1.2.")
    assert "Cz" in frozen["procedure"]["montage"]["recording_sites"]

    start_response = client.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert start_response.status_code == 201
    started = start_response.json()
    run_id = started["run_id"]
    frozen_configuration = started["observation"]["procedure_configuration"]
    assert "Cz" in frozen_configuration["montage"]["recording_sites"]
    assert "AUTHORING-NOTE-SENTINEL" not in start_response.text
    assert "private-authoring-note.txt" not in start_response.text
    assert "seeded-authoring-assistant" not in start_response.text

    later_draft = client.post(
        "/api/draft/commands",
        json={
            "command": "Remove Cz from the Montage",
            "expected_revision": noted["revision"],
        },
    ).json()["draft"]
    assert "Cz" not in later_draft["procedure"]["montage"]["recording_sites"]

    unchanged = client.get(f"/api/runs/{run_id}").json()
    assert unchanged["revision_digest"] == started["revision_digest"]
    assert unchanged["trace_digest"] == started["trace_digest"]
    assert unchanged["observation"]["procedure_configuration"] == frozen_configuration

    rejected_authoring_action = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "add_montage_site", "input": {"site": "Pz"}},
    )
    assert rejected_authoring_action.status_code == 422
    assert client.get("/api/draft").json()["revision"] == later_draft["revision"]

    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        assert (
            client.post(
                f"/api/runs/{run_id}/actions",
                json={"type": action_type, "input": {}},
            ).status_code
            == 200
        )
    completed = client.post(f"/api/runs/{run_id}/verify").json()
    assert completed["verifier_result"]["passed"] is True
    serialized_completed = str(completed)
    assert "AUTHORING-NOTE-SENTINEL" not in serialized_completed
    assert "seeded-authoring-assistant" not in serialized_completed

    replay = client.post(f"/api/runs/{run_id}/replay").json()
    assert replay["replay"]["trace_matches"] is True
    assert replay["replay"]["result_matches"] is True
    assert replay["snapshot"]["observation"]["procedure_configuration"] == (
        frozen_configuration
    )

    reset = client.post(f"/api/runs/{run_id}/reset").json()
    assert reset["observation"]["procedure_configuration"] == frozen_configuration
    trace_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "traces").glob("*.jsonl")
    )
    assert "AUTHORING-NOTE-SENTINEL" not in trace_text
    assert "seeded-authoring-assistant" not in trace_text


def test_http_frozen_environment_and_run_survive_application_restart(
    tmp_path: Path,
) -> None:
    first = TestClient(create_app(artifact_root=tmp_path))
    seeded = first.get("/api/draft").json()
    configured = first.post(
        "/api/draft/commands",
        json={
            "command": "Add Cz to the Montage",
            "expected_revision": seeded["revision"],
        },
    ).json()["draft"]
    frozen = first.post(
        "/api/draft/freeze",
        json={"expected_revision": configured["revision"]},
    ).json()
    mismatched_scenario = first.post(
        "/api/runs",
        json={
            "scenario_id": "another-scenario",
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert mismatched_scenario.status_code == 422
    started = first.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    ).json()
    active = first.post(
        f"/api/runs/{started['run_id']}/actions",
        json={"type": "inspect_onset_route", "input": {}},
    ).json()

    second = TestClient(create_app(artifact_root=tmp_path))
    resumed = second.get(f"/api/runs/{started['run_id']}")
    assert resumed.status_code == 200
    assert resumed.json() == active
    restarted_from_frozen = second.post(
        "/api/runs",
        json={
            "scenario_id": frozen["scenario_id"],
            "policy_agent": "seeded-policy-agent",
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert restarted_from_frozen.status_code == 201
    assert "Cz" in restarted_from_frozen.json()["observation"][
        "procedure_configuration"
    ]["montage"]["recording_sites"]

    for action_type in ("repair_refractory_route", "present_test_flash"):
        assert second.post(
            f"/api/runs/{started['run_id']}/actions",
            json={"type": action_type, "input": {}},
        ).status_code == 200
    completed = second.post(f"/api/runs/{started['run_id']}/verify").json()
    assert completed["verifier_result"]["passed"] is True

    third = TestClient(create_app(artifact_root=tmp_path))
    assert third.get(f"/api/runs/{started['run_id']}").json() == completed
    replay = third.post(f"/api/runs/{started['run_id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["replay"]["trace_matches"] is True
    replay_run_id = replay.json()["snapshot"]["run_id"]
    reset = third.post(f"/api/runs/{started['run_id']}/reset")
    assert reset.status_code == 200
    reset_run_id = reset.json()["run_id"]

    fourth = TestClient(create_app(artifact_root=tmp_path))
    assert fourth.get(f"/api/runs/{replay_run_id}").status_code == 200
    assert fourth.get(f"/api/runs/{reset_run_id}").status_code == 200
