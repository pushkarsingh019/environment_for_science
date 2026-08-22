import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from studio.authoring import (
    DraftActor,
    DraftAuthorizationError,
    DraftOperationUnavailable,
    DraftRepository,
    DraftRevisionConflict,
    DraftSeedConflict,
    DraftStorageError,
    DraftValidationError,
)

AUTHOR = DraftActor(
    id="environment-author",
    name="Environment author",
    role="environment_author",
)


class _WorkspaceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    sections: list[str] = Field(min_length=1)


def _validate_workspace_state(state: dict[str, object]) -> dict[str, object]:
    try:
        return _WorkspaceState.model_validate(state).model_dump(mode="json")
    except ValidationError as error:
        raise ValueError("workspace state is invalid") from error


def _rewrite_state_content(
    repository: DraftRepository,
    *,
    created_revision: int,
    content_json: str,
) -> None:
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE draft_states
            SET content_json = ?
            WHERE workspace_id = 'primary-environment' AND created_revision = ?
            """,
            (content_json, created_revision),
        )


def test_repository_initializes_one_seed_draft_with_stable_digest(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )

    snapshot = repository.current()

    assert snapshot.workspace_id == "primary-environment"
    assert snapshot.revision == 1
    assert snapshot.state == {
        "title": "Seed workspace",
        "sections": ["overview"],
    }
    assert snapshot.content_digest == (
        "sha256:5d3c732584ccaf7df3c8a666a1cd696cf0f739a92dd5f19c627a2a3e44967853"
    )
    assert snapshot.can_undo is False
    assert snapshot.can_redo is False
    assert snapshot.last_change.operation == "initialize"
    assert snapshot.last_change.actor.role == "studio"


def test_authoring_assistant_can_apply_an_attributed_draft_edit(tmp_path: Path) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    assistant = DraftActor(
        id="seeded-authoring-assistant",
        name="Seeded Authoring assistant",
        role="authoring_assistant",
    )

    changed = repository.apply(
        state={"title": "Revised workspace", "sections": ["overview", "methods"]},
        expected_revision=1,
        actor=assistant,
        description="Added a methods section",
    )

    assert changed.revision == 2
    assert changed.state == {
        "title": "Revised workspace",
        "sections": ["overview", "methods"],
    }
    assert changed.can_undo is True
    assert changed.can_redo is False
    assert changed.last_change.operation == "edit"
    assert changed.last_change.actor == assistant
    assert changed.last_change.description == "Added a methods section"
    assert changed.last_change.before_digest != changed.last_change.after_digest
    assert changed.content_digest == changed.last_change.after_digest


def test_stale_expected_revision_is_a_typed_conflict_without_a_partial_edit(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )

    with pytest.raises(DraftRevisionConflict) as raised:
        repository.apply(
            state={"title": "Stale edit", "sections": []},
            expected_revision=1,
            actor=AUTHOR,
            description="Tried to overwrite a newer draft",
        )

    assert raised.value.code == "conflict"
    assert raised.value.expected_revision == 1
    assert raised.value.actual_revision == 2
    unchanged = repository.current()
    assert unchanged.revision == 2
    assert unchanged.state["title"] == "First edit"


def test_invalid_domain_state_is_rejected_before_it_can_change_the_draft(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )

    with pytest.raises(DraftValidationError) as raised:
        repository.apply(
            state={"title": "", "sections": []},
            expected_revision=1,
            actor=AUTHOR,
            description="Submitted an invalid edit",
        )

    assert raised.value.code == "invalid"
    unchanged = repository.current()
    assert unchanged.revision == 1
    assert unchanged.state == {
        "title": "Seed workspace",
        "sections": ["overview"],
    }


def test_undo_returns_to_the_previous_state_as_a_new_attributed_revision(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    edited = repository.apply(
        state={"title": "Edited workspace", "sections": ["overview", "results"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Added results",
    )

    undone = repository.undo(
        expected_revision=edited.revision,
        actor=AUTHOR,
        description="Undid the last draft change",
    )

    assert undone.revision == 3
    assert undone.state == {
        "title": "Seed workspace",
        "sections": ["overview"],
    }
    assert undone.can_undo is False
    assert undone.can_redo is True
    assert undone.last_change.operation == "undo"
    assert undone.last_change.actor == AUTHOR
    assert undone.last_change.before_digest == edited.content_digest
    assert undone.last_change.after_digest == undone.content_digest


def test_redo_restores_the_undone_state_as_an_attributed_revision(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    edited = repository.apply(
        state={"title": "Edited workspace", "sections": ["overview", "results"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Added results",
    )
    undone = repository.undo(
        expected_revision=edited.revision,
        actor=AUTHOR,
        description="Undid the last draft change",
    )

    redone = repository.redo(
        expected_revision=undone.revision,
        actor=AUTHOR,
        description="Redid the last draft change",
    )

    assert redone.revision == 4
    assert redone.state == edited.state
    assert redone.content_digest == edited.content_digest
    assert redone.can_undo is True
    assert redone.can_redo is False
    assert redone.last_change.operation == "redo"
    assert redone.last_change.actor == AUTHOR


def test_restore_seed_creates_a_new_state_that_can_itself_be_undone(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    edited = repository.apply(
        state={"title": "Edited workspace", "sections": ["discussion"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Changed the draft",
    )

    restored = repository.restore_seed(
        expected_revision=edited.revision,
        actor=AUTHOR,
        description="Restored the seeded Environment",
    )

    assert restored.revision == 3
    assert restored.state == {
        "title": "Seed workspace",
        "sections": ["overview"],
    }
    assert restored.can_undo is True
    assert restored.can_redo is False
    assert restored.last_change.operation == "restore_seed"

    undo_restore = repository.undo(
        expected_revision=restored.revision,
        actor=AUTHOR,
        description="Undid the seed restore",
    )
    assert undo_restore.revision == 4
    assert undo_restore.state == edited.state


def test_new_edit_after_undo_clears_redo_without_deleting_activity(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    first = repository.apply(
        state={"title": "First branch", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Started the first branch",
    )
    abandoned = repository.apply(
        state={"title": "Abandoned future", "sections": ["overview"]},
        expected_revision=first.revision,
        actor=AUTHOR,
        description="Created the future that will be abandoned",
    )
    undone = repository.undo(
        expected_revision=abandoned.revision,
        actor=AUTHOR,
        description="Returned to the first branch",
    )

    branched = repository.apply(
        state={"title": "Replacement future", "sections": ["overview", "methods"]},
        expected_revision=undone.revision,
        actor=AUTHOR,
        description="Started a replacement branch",
    )

    assert branched.revision == 5
    assert branched.can_redo is False
    with pytest.raises(DraftOperationUnavailable):
        repository.redo(
            expected_revision=branched.revision,
            actor=AUTHOR,
            description="Tried to redo the abandoned future",
        )

    activity = repository.list_activity()
    assert [change.revision for change in activity] == [1, 2, 3, 4, 5]
    assert [change.operation for change in activity] == [
        "initialize",
        "edit",
        "edit",
        "undo",
        "edit",
    ]
    assert activity[2].after_digest == abandoned.content_digest
    assert activity[2].description == "Created the future that will be abandoned"


def test_draft_and_navigation_history_persist_when_repository_is_reopened(
    tmp_path: Path,
) -> None:
    seed = {"title": "Seed workspace", "sections": ["overview"]}
    first_repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state=seed,
    )
    edited = first_repository.apply(
        state={"title": "Persistent workspace", "sections": ["methods"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Saved a persistent draft edit",
    )

    reopened = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state=seed,
    )
    current = reopened.current()

    assert current == edited
    assert [change.revision for change in reopened.list_activity()] == [1, 2]
    undone = reopened.undo(
        expected_revision=current.revision,
        actor=AUTHOR,
        description="Undid after reopening the workspace",
    )
    assert undone.revision == 3
    assert undone.state == seed


def test_current_rejects_a_valid_but_rewritten_persisted_state(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    forged_document = '{"sections":["overview"],"title":"Forged workspace"}'
    forged_digest = (
        "sha256:86ec6564b6dd542921c08d3ba22a839640ab553f21e4e2910eeb4b15835a3712"
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE draft_states
            SET content_json = ?, content_digest = ?
            WHERE state_id = (
                SELECT current_state_id
                FROM draft_workspaces
                WHERE workspace_id = 'primary-environment'
            )
            """,
            (forged_document, forged_digest),
        )

    with pytest.raises(DraftStorageError) as raised:
        repository.current()

    assert raised.value.code == "storage"
    assert str(raised.value) == "the Environment draft could not be persisted"
    assert "Forged workspace" not in str(raised.value)


def test_restore_seed_rejects_a_valid_but_rewritten_persisted_seed(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    edited = repository.apply(
        state={"title": "Edited workspace", "sections": ["methods"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Changed the draft before restoring it",
    )
    forged_document = '{"sections":["forged"],"title":"Forged seed"}'
    forged_digest = (
        "sha256:196200e773f7d0418519fdfff258a160c2530aef12f1c80b0aa422e61372a51c"
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE draft_workspaces
            SET seed_state_json = ?, seed_digest = ?
            WHERE workspace_id = 'primary-environment'
            """,
            (forged_document, forged_digest),
        )
        connection.execute(
            """
            UPDATE draft_states
            SET content_json = ?, content_digest = ?
            WHERE workspace_id = 'primary-environment' AND created_revision = 1
            """,
            (forged_document, forged_digest),
        )
        connection.execute(
            """
            UPDATE draft_activity
            SET after_digest = ?
            WHERE workspace_id = 'primary-environment' AND revision = 1
            """,
            (forged_digest,),
        )

    with pytest.raises(DraftStorageError) as raised:
        repository.restore_seed(
            expected_revision=edited.revision,
            actor=AUTHOR,
            description="Restored the seeded Environment",
        )

    assert raised.value.code == "storage"
    assert str(raised.value) == "the Environment draft could not be persisted"
    assert "Forged seed" not in str(raised.value)


def test_activity_read_rejects_a_broken_persisted_digest_chain(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    first_edit = repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )
    repository.apply(
        state={"title": "Second edit", "sections": ["methods"]},
        expected_revision=first_edit.revision,
        actor=AUTHOR,
        description="Made the second edit",
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE draft_activity
            SET before_digest = (
                SELECT seed_digest
                FROM draft_workspaces
                WHERE workspace_id = 'primary-environment'
            )
            WHERE workspace_id = 'primary-environment' AND revision = 3
            """
        )

    with pytest.raises(DraftStorageError) as raised:
        repository.list_activity()

    assert raised.value.code == "storage"
    assert str(raised.value) == "the Environment draft could not be persisted"


def test_undo_rejects_a_rewritten_state_that_no_longer_matches_its_origin(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    first_edit = repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )
    second_edit = repository.apply(
        state={"title": "Second edit", "sections": ["methods"]},
        expected_revision=first_edit.revision,
        actor=AUTHOR,
        description="Made the second edit",
    )
    forged_document = '{"sections":["overview"],"title":"Forged prior state"}'
    forged_digest = (
        "sha256:5ec39c38930ea5b0a8676e6a1de3035208cef575b765b3df6667d5baf9c4aca6"
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE draft_states
            SET content_json = ?, content_digest = ?
            WHERE workspace_id = 'primary-environment' AND created_revision = 2
            """,
            (forged_document, forged_digest),
        )

    with pytest.raises(DraftStorageError) as raised:
        repository.undo(
            expected_revision=second_edit.revision,
            actor=AUTHOR,
            description="Undid the second edit",
        )

    assert raised.value.code == "storage"
    assert repository.current().revision == second_edit.revision


def test_apply_cannot_bury_a_rewritten_current_state_in_undo_history(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    edited = repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )
    original_document = '{"sections":["overview"],"title":"First edit"}'
    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json='{"sections":["overview"],"title":"Forged head"}',
    )

    with pytest.raises(DraftStorageError):
        repository.apply(
            state={"title": "Second edit", "sections": ["methods"]},
            expected_revision=edited.revision,
            actor=AUTHOR,
            description="Tried to write on a rewritten head",
        )

    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json=original_document,
    )
    unchanged = repository.current()
    assert unchanged.revision == edited.revision
    assert unchanged.state["title"] == "First edit"
    assert [change.revision for change in repository.list_activity()] == [1, 2]


def test_undo_cannot_bury_a_rewritten_current_state_in_redo_history(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    edited = repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )
    original_document = '{"sections":["overview"],"title":"First edit"}'
    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json='{"sections":["overview"],"title":"Forged head"}',
    )

    with pytest.raises(DraftStorageError):
        repository.undo(
            expected_revision=edited.revision,
            actor=AUTHOR,
            description="Tried to undo from a rewritten head",
        )

    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json=original_document,
    )
    unchanged = repository.current()
    assert unchanged.revision == edited.revision
    assert unchanged.can_undo is True
    assert unchanged.can_redo is False
    assert [change.revision for change in repository.list_activity()] == [1, 2]


def test_redo_cannot_bury_a_rewritten_current_state_in_undo_history(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
        state_validator=_validate_workspace_state,
    )
    first_edit = repository.apply(
        state={"title": "First edit", "sections": ["overview"]},
        expected_revision=1,
        actor=AUTHOR,
        description="Made the first edit",
    )
    second_edit = repository.apply(
        state={"title": "Second edit", "sections": ["methods"]},
        expected_revision=first_edit.revision,
        actor=AUTHOR,
        description="Made the second edit",
    )
    undone = repository.undo(
        expected_revision=second_edit.revision,
        actor=AUTHOR,
        description="Undid the second edit",
    )
    original_document = '{"sections":["overview"],"title":"First edit"}'
    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json='{"sections":["overview"],"title":"Forged head"}',
    )

    with pytest.raises(DraftStorageError):
        repository.redo(
            expected_revision=undone.revision,
            actor=AUTHOR,
            description="Tried to redo from a rewritten head",
        )

    _rewrite_state_content(
        repository,
        created_revision=2,
        content_json=original_document,
    )
    unchanged = repository.current()
    assert unchanged.revision == undone.revision
    assert unchanged.can_undo is True
    assert unchanged.can_redo is True
    assert [change.revision for change in repository.list_activity()] == [1, 2, 3, 4]


def test_reopen_rejects_a_different_seed_instead_of_silently_replacing_it(
    tmp_path: Path,
) -> None:
    DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Original seed", "sections": ["overview"]},
    )

    with pytest.raises(DraftSeedConflict) as raised:
        DraftRepository(
            artifact_root=tmp_path,
            workspace_id="primary-environment",
            seed_state={"title": "Different seed", "sections": ["overview"]},
        )

    assert raised.value.code == "conflict"


def test_policy_agent_cannot_change_the_authoring_workspace(tmp_path: Path) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )
    policy_agent = DraftActor(
        id="seeded-policy-agent",
        name="Seeded Policy agent",
        role="policy_agent",
    )

    with pytest.raises(DraftAuthorizationError) as raised:
        repository.apply(
            state={"title": "Policy-owned edit", "sections": []},
            expected_revision=1,
            actor=policy_agent,
            description="Attempted a run-side draft edit",
        )

    assert raised.value.code == "forbidden"
    assert repository.current().revision == 1
    assert len(repository.list_activity()) == 1


def test_public_snapshots_are_frozen_and_detached_from_persisted_state(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={
            "title": "Seed workspace",
            "sections": ["overview"],
            "preferences": {"mode": "calm"},
        },
    )
    snapshot = repository.current()

    with pytest.raises(ValidationError):
        snapshot.revision = 99
    snapshot.state["sections"].append("caller mutation")
    snapshot.state["preferences"]["mode"] = "caller mutation"

    unchanged = repository.current()
    assert unchanged.revision == 1
    assert unchanged.state["sections"] == ["overview"]
    assert unchanged.state["preferences"] == {"mode": "calm"}


def test_database_is_created_under_artifact_root_with_owner_only_permissions(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )

    assert repository.database_path.parent == tmp_path.resolve()
    assert repository.database_path.name == "draft-workspace.sqlite3"
    assert stat.S_IMODE(repository.database_path.stat().st_mode) == 0o600


def test_boolean_expected_revision_is_rejected_instead_of_matching_revision_one(
    tmp_path: Path,
) -> None:
    repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state={"title": "Seed workspace", "sections": ["overview"]},
    )

    with pytest.raises(DraftValidationError):
        repository.apply(
            state={"title": "Unexpected edit", "sections": ["overview"]},
            expected_revision=True,
            actor=AUTHOR,
            description="Used a non-integer revision",
        )

    assert repository.current().revision == 1


def test_blank_workspace_identity_is_a_typed_validation_error(tmp_path: Path) -> None:
    with pytest.raises(DraftValidationError):
        DraftRepository(
            artifact_root=tmp_path,
            workspace_id="   ",
            seed_state={"title": "Seed workspace", "sections": ["overview"]},
        )

    assert not (tmp_path / "draft-workspace.sqlite3").exists()


def test_competing_writers_cannot_commit_the_same_expected_revision(
    tmp_path: Path,
) -> None:
    seed = {"title": "Seed workspace", "sections": ["overview"]}
    first_repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state=seed,
    )
    second_repository = DraftRepository(
        artifact_root=tmp_path,
        workspace_id="primary-environment",
        seed_state=seed,
    )

    def apply_title(repository: DraftRepository, title: str) -> object:
        try:
            return repository.apply(
                state={"title": title, "sections": ["overview"]},
                expected_revision=1,
                actor=AUTHOR,
                description=f"Changed the title to {title}",
            )
        except DraftRevisionConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                apply_title,
                (first_repository, second_repository),
                ("First writer", "Second writer"),
            )
        )

    conflicts = [item for item in outcomes if isinstance(item, DraftRevisionConflict)]
    assert len(conflicts) == 1
    assert conflicts[0].actual_revision == 2
    assert first_repository.current().revision == 2
    assert len(first_repository.list_activity()) == 2


def test_unusable_artifact_root_is_reported_as_a_typed_storage_error(
    tmp_path: Path,
) -> None:
    occupied_path = tmp_path / "not-a-directory"
    occupied_path.write_text("occupied", encoding="utf-8")

    with pytest.raises(DraftStorageError) as raised:
        DraftRepository(
            artifact_root=occupied_path,
            workspace_id="primary-environment",
            seed_state={"title": "Seed workspace", "sections": ["overview"]},
        )

    assert raised.value.code == "storage"
