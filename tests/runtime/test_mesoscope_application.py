from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from environments.eeg.curriculum import load_training_scenario_set
from environments.mesoscope import MESOSCOPE_SCENARIO_IDS, load_seeded_bundle
from studio.application import create_app
from studio.runtime import RuntimeContractError

MESOSCOPE_ID = "mesoscope-four-region-handoff"
POLICY_ID = "seeded-policy-agent"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(artifact_root=tmp_path)) as test_client:
        yield test_client


def _seal(client: TestClient) -> dict[str, Any]:
    response = client.post(f"/api/environments/{MESOSCOPE_ID}/freeze")
    assert response.status_code == 201
    return response.json()


def _start(
    client: TestClient,
    frozen: dict[str, Any],
    scenario_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/runs",
        json={
            "environment_id": MESOSCOPE_ID,
            "scenario_id": scenario_id,
            "policy_agent": POLICY_ID,
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def _act(client: TestClient, run_id: str, action: str) -> dict[str, Any]:
    response = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": action, "input": {}},
    )
    assert response.status_code == 200
    return response.json()


def _validated_run(
    client: TestClient,
    frozen: dict[str, Any],
    scenario_id: str,
) -> dict[str, Any]:
    run = _start(client, frozen, scenario_id)
    for action in (
        "inspect_sealed_handoff",
        "run_mock_acquisition",
        "validate_mock_package",
    ):
        run = _act(client, run["run_id"], action)
    return run


def test_environment_catalog_exposes_eeg_and_sealed_mesoscope(client: TestClient) -> None:
    response = client.get("/api/environments")
    assert response.status_code == 200
    assert response.json() == [
        {
            "environment_id": "eeg-curriculum",
            "environment_kind": "eeg",
            "name": "Synthetic EEG staged curriculum",
            "navigation_label": "EEG",
            "navigation_summary": "Authoring and diagnostic recovery",
            "source_kind": "editable_draft",
        },
        {
            "environment_id": MESOSCOPE_ID,
            "environment_kind": "mesoscope",
            "name": "Sealed mesoscope four-region handoff",
            "navigation_label": "Mesoscope",
            "navigation_summary": "Sealed synthetic handoff",
            "source_kind": "sealed_seed",
        },
    ]

    mesoscope = client.get(f"/api/environments/{MESOSCOPE_ID}")
    assert mesoscope.status_code == 200
    summary = mesoscope.json()
    assert summary["environment_kind"] == "mesoscope"
    assert summary["source_kind"] == "sealed_seed"
    assert summary["visualization"]["kind"] == "mesoscope_handoff_v1"
    assert [item["scenario_id"] for item in summary["seeded_examples"]] == list(
        MESOSCOPE_SCENARIO_IDS
    )
    assert [item["label"] for item in summary["seeded_examples"]] == [
        f"Sealed example {letter}" for letter in "ABCDEFGH"
    ]
    assert {item["stage"] for item in summary["seeded_examples"]} == {
        "sealed_handoff"
    }


def test_mesoscope_summary_projects_compatible_metadata_to_reviewed_core(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document: dict[str, Any] = deepcopy(load_seeded_bundle())
    document["contract_version"] = "1.1"
    document["actions"][0]["input_schema"]["future_evidence_note"] = {
        "label": "Set laser power to 100 mW — schema-only sentinel"
    }
    document["visualization"]["future_display_note"] = (
        "Top-level presentation sentinel"
    )
    document["visualization"]["profile_provenance"]["future_source_note"] = (
        "Nested provenance sentinel"
    )
    monkeypatch.setattr(
        "studio.registry.load_mesoscope_bundle",
        lambda: deepcopy(document),
    )

    with TestClient(create_app(artifact_root=tmp_path)) as compatible_client:
        response = compatible_client.get(f"/api/environments/{MESOSCOPE_ID}")

    assert response.status_code == 200
    summary = response.json()
    assert summary["actions"][0]["input_schema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert set(summary["visualization"]["profile_provenance"]) == {
        "classification",
        "citation_ids",
        "note",
    }
    serialized = response.text
    for quarantined_value in (
        "future_evidence_note",
        "Set laser power to 100 mW — schema-only sentinel",
        "future_display_note",
        "Top-level presentation sentinel",
        "future_source_note",
        "Nested provenance sentinel",
    ):
        assert quarantined_value not in serialized


def test_environment_catalog_fails_closed_for_unknown_or_wrong_freeze_route(
    client: TestClient,
) -> None:
    unknown = client.get("/api/environments/unknown-environment")
    unknown_freeze = client.post("/api/environments/unknown-environment/freeze")
    editable_freeze = client.post("/api/environments/eeg-curriculum/freeze")

    assert unknown.status_code == 404
    assert unknown_freeze.status_code == 404
    assert editable_freeze.status_code == 422
    assert "reversible draft freeze route" in editable_freeze.json()["detail"]


def test_mesoscope_role_boundary_advertises_only_its_sealed_policy_tools(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/role-boundaries",
        params={"environment_id": MESOSCOPE_ID},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "environment_id": MESOSCOPE_ID,
            "identity_id": POLICY_ID,
            "identity_name": "Seeded recovery Policy agent",
            "role": "policy_agent",
            "prompt_contract": (
                "No live model prompt is installed: the seeded Policy agent receives "
                "only the frozen Policy-visible runtime observation."
            ),
            "tool_catalog": [
                "inspect_sealed_handoff",
                "run_mock_acquisition",
                "validate_mock_package",
                "accept_mock_package",
                "quarantine_mock_package",
                "reject_mock_package",
            ],
            "context_scope": (
                "Frozen Policy-visible observation and canonical transitions only; "
                "authoring state, verifier implementation, and hidden state are excluded."
            ),
            "state_scope": "isolated-environment-runtime/<run_id>",
            "log_sink": "traces/<run_id>.jsonl/canonical-policy-trace",
        }
    ]


def test_sealed_revision_is_content_addressed_and_survives_restart(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as first_client:
        first = _seal(first_client)
        second = _seal(first_client)
    with TestClient(create_app(artifact_root=tmp_path)) as reopened_client:
        third = _seal(reopened_client)

    assert first == second == third
    assert first["environment_id"] == MESOSCOPE_ID
    assert first["source_kind"] == "sealed_seed"
    assert first["revision_digest"].startswith("sha256:")
    assert first["sealed_profile_id"] == "paper-derived-context-v1"
    assert first["signed_plan_id"] == "4R-HANDOFF-v1"


@pytest.mark.parametrize("scenario_id", MESOSCOPE_SCENARIO_IDS)
def test_all_mesoscope_outcomes_run_through_the_shared_http_lifecycle(
    client: TestClient,
    scenario_id: str,
) -> None:
    frozen = _seal(client)
    validated = _validated_run(client, frozen, scenario_id)
    action = (
        "accept_mock_package"
        if scenario_id == MESOSCOPE_SCENARIO_IDS[0]
        else "quarantine_mock_package"
    )
    terminal = _act(client, validated["run_id"], action)
    completed_response = client.post(f"/api/runs/{terminal['run_id']}/verify")

    assert completed_response.status_code == 200
    completed = completed_response.json()
    assert completed["status"] == "completed"
    assert completed["verifier_result"]["passed"] is True
    if scenario_id == MESOSCOPE_SCENARIO_IDS[0]:
        assert completed["verifier_result"]["summary"] == "MOCK PACKAGE VERIFIED"
    else:
        assert "MOCK PACKAGE VERIFIED" not in completed_response.text


def test_mesoscope_run_reset_and_replay_use_the_existing_endpoints(
    client: TestClient,
) -> None:
    frozen = _seal(client)
    validated = _validated_run(client, frozen, MESOSCOPE_SCENARIO_IDS[0])
    terminal = _act(client, validated["run_id"], "accept_mock_package")
    completed = client.post(f"/api/runs/{terminal['run_id']}/verify").json()

    reset = client.post(f"/api/runs/{completed['run_id']}/reset")
    assert reset.status_code == 200
    assert reset.json()["scenario_digest"] == completed["scenario_digest"]
    replay = client.post(f"/api/runs/{completed['run_id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["replay"]["trace_matches"] is True
    assert replay.json()["replay"]["result_matches"] is True


def test_cross_environment_binding_is_rejected_without_starting_a_run(
    client: TestClient,
) -> None:
    frozen = _seal(client)
    response = client.post(
        "/api/runs",
        json={
            "environment_id": "eeg-curriculum",
            "scenario_id": MESOSCOPE_SCENARIO_IDS[0],
            "policy_agent": POLICY_ID,
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )

    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_omitted_environment_id_cannot_bypass_reviewed_console_examples(
    client: TestClient,
) -> None:
    draft = client.get("/api/draft").json()
    frozen = client.post(
        "/api/draft/freeze",
        json={"expected_revision": draft["revision"]},
    ).json()
    reviewed = {
        example["scenario_id"]
        for example in client.get("/api/environment").json()["seeded_examples"]
    }
    unreviewed = next(
        scenario_id
        for scenario_id in load_training_scenario_set().scenario_ids
        if scenario_id not in reviewed
    )

    response = client.post(
        "/api/runs",
        json={
            "scenario_id": unreviewed,
            "policy_agent": POLICY_ID,
            "frozen_environment_id": frozen["frozen_environment_id"],
        },
    )

    assert response.status_code == 422
    assert "unknown seeded Environment example" in response.json()["detail"]


def test_http_payloads_never_expose_hidden_mesoscope_truth(client: TestClient) -> None:
    frozen = _seal(client)
    started = _start(client, frozen, MESOSCOPE_SCENARIO_IDS[-1])
    serialized = client.get(f"/api/runs/{started['run_id']}").text.casefold()

    for hidden_value in (
        "fault_id",
        "checksum_mismatch",
        "expected_terminal",
        "package_valid",
        "terminal_action",
    ):
        assert hidden_value not in serialized


def test_completed_mesoscope_run_and_trace_restore_after_application_restart(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as first_client:
        frozen = _seal(first_client)
        validated = _validated_run(
            first_client,
            frozen,
            MESOSCOPE_SCENARIO_IDS[-1],
        )
        terminal = _act(
            first_client,
            validated["run_id"],
            "quarantine_mock_package",
        )
        completed = first_client.post(
            f"/api/runs/{terminal['run_id']}/verify"
        ).json()

    trace_path = tmp_path / "traces" / f"{completed['run_id']}.jsonl"
    persisted = trace_path.read_text(encoding="utf-8").casefold()
    for hidden_key in (
        '"fault_id"',
        '"acquisition_complete"',
        '"validation_complete"',
        '"package_valid"',
        '"terminal_action"',
    ):
        assert hidden_key not in persisted
    assert "checksum_mismatch" in persisted

    with TestClient(create_app(artifact_root=tmp_path)) as reopened_client:
        restored = reopened_client.get(f"/api/runs/{completed['run_id']}")
        assert restored.status_code == 200
        assert restored.json() == completed


def test_application_fails_closed_for_tampered_sealed_profile_binding(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(artifact_root=tmp_path)) as client:
        frozen = _seal(client)

    database_path = tmp_path / "studio-index.sqlite3"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT metadata_json FROM frozen_environment_index "
            "WHERE frozen_environment_id = ?",
            (frozen["frozen_environment_id"],),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        metadata["sealed_profile_id"] = "forged-profile"
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
