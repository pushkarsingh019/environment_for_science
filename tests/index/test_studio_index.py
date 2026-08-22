from __future__ import annotations

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from threading import Event
from typing import Protocol

import pytest
from pydantic import ValidationError

from studio.index import (
    RunIndexRecord,
    RunTraceIntent,
    StudioIndex,
    StudioIndexConflict,
    StudioIndexNotFound,
    StudioIndexStorageError,
    StudioIndexValidationError,
)

BUNDLE_DOCUMENT = {
    "bundle_id": "example",
    "bundle_revision": "1.2.2",
}
BUNDLE_DIGEST = "sha256:7b68b51f0d9585ef892bfeffe5bc0c11404e5d8123e4e965c5aa7211cb8c63da"
METADATA_DOCUMENT = {
    "scenario_id": "scenario-001",
    "draft_revision": 2,
}
TRACE_HEADER_DIGEST = "sha256:" + ("1" * 64)
TRACE_DIGEST = "sha256:" + ("2" * 64)


class _EventLike(Protocol):
    def set(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def _hold_run_lock(
    artifact_root: Path,
    run_id: str,
    acquired: _EventLike,
    release: _EventLike,
) -> None:
    with StudioIndex(artifact_root).lock_run(run_id):
        acquired.set()
        if not release.wait(timeout=5):
            raise TimeoutError("parent did not release the run lock")


def test_records_and_reads_one_canonical_frozen_environment(tmp_path: Path) -> None:
    index = StudioIndex(tmp_path)

    recorded = index.record_frozen(
        frozen_environment_id="frozen-example",
        revision_digest=BUNDLE_DIGEST,
        bundle_document=BUNDLE_DOCUMENT,
        metadata_document=METADATA_DOCUMENT,
    )

    assert recorded.frozen_environment_id == "frozen-example"
    assert recorded.revision_digest == BUNDLE_DIGEST
    assert recorded.bundle_document == BUNDLE_DOCUMENT
    assert recorded.metadata_document == METADATA_DOCUMENT
    assert index.get_frozen("frozen-example") == recorded
    assert index.list_frozen() == (recorded,)


def test_records_and_reopens_a_run_routed_to_the_seeded_source(tmp_path: Path) -> None:
    index = StudioIndex(tmp_path)

    recorded = index.record_run(
        run_id="run-seeded",
        frozen_environment_id=None,
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )

    assert recorded == RunIndexRecord(
        run_id="run-seeded",
        frozen_environment_id=None,
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )
    reopened = StudioIndex(tmp_path)
    assert reopened.get_run("run-seeded") == recorded


def test_frozen_record_is_idempotent_but_rejects_digest_or_content_conflicts(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)
    first = index.record_frozen(
        frozen_environment_id="frozen-example",
        revision_digest=BUNDLE_DIGEST,
        bundle_document=BUNDLE_DOCUMENT,
        metadata_document=METADATA_DOCUMENT,
    )

    repeated = index.record_frozen(
        frozen_environment_id="frozen-example",
        revision_digest=BUNDLE_DIGEST,
        bundle_document={
            "bundle_revision": "1.2.2",
            "bundle_id": "example",
        },
        metadata_document={"draft_revision": 2, "scenario_id": "scenario-001"},
    )
    assert repeated == first

    with pytest.raises(StudioIndexConflict) as conflict:
        index.record_frozen(
            frozen_environment_id="frozen-example",
            revision_digest=BUNDLE_DIGEST,
            bundle_document=BUNDLE_DOCUMENT,
            metadata_document={"scenario_id": "scenario-002", "draft_revision": 2},
        )
    assert conflict.value.code == "conflict"

    with pytest.raises(StudioIndexValidationError) as invalid:
        index.record_frozen(
            frozen_environment_id="frozen-other",
            revision_digest="sha256:" + ("0" * 64),
            bundle_document=BUNDLE_DOCUMENT,
            metadata_document=METADATA_DOCUMENT,
        )
    assert invalid.value.code == "invalid"
    assert index.list_frozen() == (first,)


def test_run_routing_requires_a_known_frozen_environment_and_never_rebinds(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)

    with pytest.raises(StudioIndexNotFound) as missing_frozen:
        index.record_run(
            run_id="run-frozen",
            frozen_environment_id="frozen-example",
            trace_header_digest=TRACE_HEADER_DIGEST,
            trace_digest=TRACE_DIGEST,
        )
    assert missing_frozen.value.code == "not_found"

    index.record_frozen(
        frozen_environment_id="frozen-example",
        revision_digest=BUNDLE_DIGEST,
        bundle_document=BUNDLE_DOCUMENT,
        metadata_document=METADATA_DOCUMENT,
    )
    routed = index.record_run(
        run_id="run-frozen",
        frozen_environment_id="frozen-example",
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )
    assert index.record_run(
        run_id="run-frozen",
        frozen_environment_id="frozen-example",
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    ) == routed

    with pytest.raises(StudioIndexConflict):
        index.record_run(
            run_id="run-frozen",
            frozen_environment_id=None,
            trace_header_digest=TRACE_HEADER_DIGEST,
            trace_digest=TRACE_DIGEST,
        )
    with pytest.raises(StudioIndexConflict):
        index.record_run(
            run_id="run-frozen",
            frozen_environment_id="frozen-example",
            trace_header_digest="sha256:" + ("2" * 64),
            trace_digest=TRACE_DIGEST,
        )

    reopened = StudioIndex(tmp_path)
    assert reopened.get_run("run-frozen") == routed
    with pytest.raises(StudioIndexNotFound):
        reopened.get_run("run-unknown")


def test_legacy_run_index_migrates_without_blessing_unbound_provenance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "studio-index.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE run_index (
                run_id TEXT PRIMARY KEY,
                frozen_environment_id TEXT
            );
            INSERT INTO run_index (run_id, frozen_environment_id)
            VALUES ('run-legacy', NULL);
            """
        )

    index = StudioIndex(tmp_path)

    assert index.get_run("run-legacy") == RunIndexRecord(
        run_id="run-legacy",
        frozen_environment_id=None,
        trace_header_digest=None,
        trace_digest=None,
    )
    assert index.get_run_trace_intent("run-legacy") is None
    with pytest.raises(StudioIndexConflict):
        index.record_run(
            run_id="run-legacy",
            frozen_environment_id=None,
            trace_header_digest=TRACE_HEADER_DIGEST,
            trace_digest=TRACE_DIGEST,
        )


def test_invalid_trace_header_digest_leaves_no_partial_run_route(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)

    with pytest.raises(StudioIndexValidationError):
        index.record_run(
            run_id="run-invalid",
            frozen_environment_id=None,
            trace_header_digest="not-a-digest",
            trace_digest=TRACE_DIGEST,
        )

    with pytest.raises(StudioIndexNotFound):
        index.get_run("run-invalid")


def test_run_trace_intent_resolves_only_the_exact_prepared_append(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)
    index.record_run(
        run_id="run-prepared",
        frozen_environment_id=None,
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )
    target_digest = "sha256:" + ("3" * 64)
    append_payload = b'{"record_type":"event"}\n'

    prepared = index.prepare_run_trace(
        run_id="run-prepared",
        operation="action",
        expected_trace_digest=TRACE_DIGEST,
        target_trace_digest=target_digest,
        base_journal_bytes=127,
        append_payload=append_payload,
    )

    assert index.get_run_trace_intent("run-prepared") == prepared
    assert prepared.append_payload == append_payload
    assert index.resolve_run_trace_intent(
        prepared,
        observed_trace_digest=TRACE_DIGEST,
    ).trace_digest == TRACE_DIGEST
    assert index.get_run_trace_intent("run-prepared") is None

    prepared = index.prepare_run_trace(
        run_id="run-prepared",
        operation="verify",
        expected_trace_digest=TRACE_DIGEST,
        target_trace_digest=target_digest,
        base_journal_bytes=127,
        append_payload=append_payload,
    )
    assert index.resolve_run_trace_intent(
        prepared,
        observed_trace_digest=target_digest,
    ).trace_digest == target_digest
    assert index.get_run_trace_intent("run-prepared") is None

    with pytest.raises(StudioIndexConflict):
        index.resolve_run_trace_intent(
            prepared,
            observed_trace_digest="sha256:" + ("4" * 64),
        )


def test_corrupt_stored_trace_intent_payload_fails_closed(tmp_path: Path) -> None:
    index = StudioIndex(tmp_path)
    index.record_run(
        run_id="run-corrupt-intent",
        frozen_environment_id=None,
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )
    index.prepare_run_trace(
        run_id="run-corrupt-intent",
        operation="action",
        expected_trace_digest=TRACE_DIGEST,
        target_trace_digest="sha256:" + ("3" * 64),
        base_journal_bytes=127,
        append_payload=b'{"record_type":"event"}\n',
    )
    with sqlite3.connect(index.database_path) as connection:
        connection.execute(
            "UPDATE run_trace_intent SET append_payload = ? WHERE run_id = ?",
            (b'{"record_type": "event"}\n', "run-corrupt-intent"),
        )

    with pytest.raises(StudioIndexStorageError):
        StudioIndex(tmp_path).get_run_trace_intent("run-corrupt-intent")


def test_competing_trace_intent_writers_cannot_prepare_different_appends(
    tmp_path: Path,
) -> None:
    first_index = StudioIndex(tmp_path)
    second_index = StudioIndex(tmp_path)
    first_index.record_run(
        run_id="run-shared-checkpoint",
        frozen_environment_id=None,
        trace_header_digest=TRACE_HEADER_DIGEST,
        trace_digest=TRACE_DIGEST,
    )

    def prepare(index: StudioIndex, suffix: str) -> object:
        try:
            return index.prepare_run_trace(
                run_id="run-shared-checkpoint",
                operation="action",
                expected_trace_digest=TRACE_DIGEST,
                target_trace_digest="sha256:" + (suffix * 64),
                base_journal_bytes=127,
                append_payload=(f'{{"writer":"{suffix}"}}\n').encode(),
            )
        except StudioIndexConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(prepare, (first_index, second_index), ("3", "4"))
        )

    assert len([item for item in outcomes if isinstance(item, RunTraceIntent)]) == 1
    assert len([item for item in outcomes if isinstance(item, StudioIndexConflict)]) == 1


def test_run_lock_serializes_a_separate_studio_process(tmp_path: Path) -> None:
    context = get_context("spawn")
    holder_acquired = context.Event()
    release_holder = context.Event()
    holder = context.Process(
        target=_hold_run_lock,
        args=(tmp_path, "run-process-shared", holder_acquired, release_holder),
    )
    holder.start()
    contender_started = Event()
    contender_acquired = Event()

    def contend() -> None:
        contender_started.set()
        with StudioIndex(tmp_path).lock_run("run-process-shared"):
            contender_acquired.set()

    try:
        assert holder_acquired.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=1) as executor:
            contender = executor.submit(contend)
            assert contender_started.wait(timeout=2)
            assert not contender_acquired.wait(timeout=0.2)
            release_holder.set()
            assert contender_acquired.wait(timeout=5)
            contender.result(timeout=2)
    finally:
        release_holder.set()
        holder.join(timeout=5)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=5)

    assert holder.exitcode == 0
    lock_files = tuple((tmp_path / ".run-locks").glob("stripe-*.lock"))
    assert len(lock_files) == 1
    assert stat.S_IMODE(lock_files[0].stat().st_mode) == 0o600


def test_frozen_records_are_frozen_detached_and_listed_deterministically(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)
    bundle = {
        "bundle_id": "nested",
        "settings": {"sites": ["A", "B"]},
    }
    nested_digest = "sha256:380c3879372265d4142a2f3965b1e9a63470c78570d7bb571cdb89db44e2d2f5"
    metadata = {"scenario_ids": ["scenario-001"]}
    later = index.record_frozen(
        frozen_environment_id="frozen-z",
        revision_digest=nested_digest,
        bundle_document=bundle,
        metadata_document=metadata,
    )
    index.record_frozen(
        frozen_environment_id="frozen-a",
        revision_digest=BUNDLE_DIGEST,
        bundle_document=BUNDLE_DOCUMENT,
        metadata_document=METADATA_DOCUMENT,
    )

    bundle["settings"]["sites"].append("caller mutation")
    metadata["scenario_ids"].append("caller mutation")
    later.bundle_document["settings"]["sites"].append("returned mutation")
    later.metadata_document["scenario_ids"].append("returned mutation")
    with pytest.raises(ValidationError):
        later.revision_digest = "sha256:" + ("0" * 64)

    reopened = StudioIndex(tmp_path)
    unchanged = reopened.get_frozen("frozen-z")
    assert unchanged.bundle_document["settings"] == {"sites": ["A", "B"]}
    assert unchanged.metadata_document == {"scenario_ids": ["scenario-001"]}
    assert [record.frozen_environment_id for record in reopened.list_frozen()] == [
        "frozen-a",
        "frozen-z",
    ]


def test_index_file_is_owner_only_and_unusable_storage_is_typed(tmp_path: Path) -> None:
    index = StudioIndex(tmp_path)

    assert index.database_path.parent == tmp_path.resolve()
    assert index.database_path.name == "studio-index.sqlite3"
    assert stat.S_IMODE(index.database_path.stat().st_mode) == 0o600

    occupied_path = tmp_path / "not-a-directory"
    occupied_path.write_text("occupied", encoding="utf-8")
    with pytest.raises(StudioIndexStorageError) as raised:
        StudioIndex(occupied_path)
    assert raised.value.code == "storage"


def test_non_json_frozen_documents_are_rejected_without_a_partial_record(
    tmp_path: Path,
) -> None:
    index = StudioIndex(tmp_path)

    with pytest.raises(StudioIndexValidationError):
        index.record_frozen(
            frozen_environment_id="frozen-invalid",
            revision_digest="sha256:" + ("0" * 64),
            bundle_document={"invalid": float("nan")},
            metadata_document=METADATA_DOCUMENT,
        )

    assert index.list_frozen() == ()


def test_competing_writers_cannot_rebind_one_frozen_identity(tmp_path: Path) -> None:
    first_index = StudioIndex(tmp_path)
    second_index = StudioIndex(tmp_path)

    def record(index: StudioIndex, scenario_id: str) -> object:
        try:
            return index.record_frozen(
                frozen_environment_id="frozen-shared",
                revision_digest=BUNDLE_DIGEST,
                bundle_document=BUNDLE_DOCUMENT,
                metadata_document={"scenario_id": scenario_id},
            )
        except StudioIndexConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                record,
                (first_index, second_index),
                ("scenario-001", "scenario-002"),
            )
        )

    assert len([item for item in outcomes if isinstance(item, StudioIndexConflict)]) == 1
    assert len(first_index.list_frozen()) == 1
