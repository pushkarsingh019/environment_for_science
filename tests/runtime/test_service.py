import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Protocol

import pytest

from studio.index import StudioIndexStorageError
from studio.runtime import EnvironmentAction, RuntimeContractError
from studio.service import SEEDED_POLICY_AGENT, ScienceStudio


class _AppendPlanLike(Protocol):
    append_payload: bytes


def _trace_journal(studio: ScienceStudio, run_id: str) -> object:
    route = studio._index.get_run(run_id)
    assert route.frozen_environment_id is not None
    runtime = studio._runtime_for_frozen(route.frozen_environment_id)
    journal = runtime._trace_journal
    assert journal is not None
    return journal


def _advance_to_verification(studio: ScienceStudio, run_id: str) -> None:
    for action_type in (
        "inspect_onset_route",
        "repair_refractory_route",
        "present_test_flash",
    ):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type=action_type, arguments={}),
        )


def _started_studio_run(tmp_path: Path) -> tuple[ScienceStudio, str]:
    studio = ScienceStudio(tmp_path)
    draft = studio.current_draft()
    frozen = studio.freeze(expected_revision=draft.revision)
    started = studio.start_run(
        scenario_id=frozen.scenario_id,
        policy_agent=SEEDED_POLICY_AGENT,
        frozen_environment_id=frozen.frozen_environment_id,
    )
    return studio, started.run_id


def test_concurrent_run_mutations_advance_one_serial_checkpoint_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)

    instrumentation_lock = Lock()
    first_checkpoint_entered = Event()
    release_first_checkpoint = Event()
    second_mutation_lock_requested = Event()
    mutation_lock_requests = 0
    run_mutation_lock = studio._run_mutation_lock
    resolve_run_trace_intent = studio._index.resolve_run_trace_intent

    def counted_run_mutation_lock(run_id: str) -> object:
        nonlocal mutation_lock_requests
        with instrumentation_lock:
            mutation_lock_requests += 1
            if mutation_lock_requests == 2:
                second_mutation_lock_requested.set()
        return run_mutation_lock(run_id)

    def held_resolve_run_trace_intent(*args: object, **kwargs: object) -> object:
        first_checkpoint_entered.set()
        release_first_checkpoint.wait()
        return resolve_run_trace_intent(*args, **kwargs)

    monkeypatch.setattr(studio, "_run_mutation_lock", counted_run_mutation_lock)
    monkeypatch.setattr(
        studio._index,
        "resolve_run_trace_intent",
        held_resolve_run_trace_intent,
    )

    action = EnvironmentAction(type="inspect_onset_route", arguments={})
    with ThreadPoolExecutor(max_workers=2) as executor:
        mutations = [
            executor.submit(studio.apply_run_action, run_id, action)
        ]
        try:
            assert first_checkpoint_entered.wait(timeout=2)
            mutations.append(
                executor.submit(studio.apply_run_action, run_id, action)
            )
            assert second_mutation_lock_requested.wait(timeout=2)
        finally:
            release_first_checkpoint.set()
        snapshots = [future.result(timeout=2) for future in mutations]

    assert [len(snapshot.trace) for snapshot in snapshots] == [4, 7]
    expected = studio.current_run(run_id)
    assert expected == snapshots[-1]
    assert ScienceStudio(tmp_path).current_run(run_id) == expected


def test_cached_run_reconciles_to_another_studio_checkpoint(tmp_path: Path) -> None:
    first, run_id = _started_studio_run(tmp_path)
    second = ScienceStudio(tmp_path)
    initial = second.current_run(run_id)

    advanced = first.apply_run_action(
        run_id,
        EnvironmentAction(type="inspect_onset_route", arguments={}),
    )

    assert len(initial.trace) == 1
    assert second.current_run(run_id) == advanced


def test_rejected_action_creates_no_durable_intent(tmp_path: Path) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    initial_journal = artifact.read_bytes()

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="undeclared_action", arguments={}),
        )

    assert studio._index.get_run_trace_intent(run_id) is None
    assert artifact.read_bytes() == initial_journal


def test_cached_run_still_validates_its_durable_journal(tmp_path: Path) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    cached = studio.current_run(run_id)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    records = [
        json.loads(line)
        for line in artifact.read_text(encoding="utf-8").splitlines()
    ]
    records[1]["payload"]["summary"] = "Tampered cached observation"
    artifact.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeContractError, match="could not be restored"):
        studio.current_run(run_id)

    assert len(cached.trace) == 1


def test_two_studios_serialize_mutation_through_one_durable_checkpoint_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, run_id = _started_studio_run(tmp_path)
    second = ScienceStudio(tmp_path)
    assert second.current_run(run_id).trace == first.current_run(run_id).trace

    first_lock_entered = Event()
    release_first_lock = Event()
    second_lock_requested = Event()
    callers_ready = Barrier(2)
    first_lock = first._index.lock_run
    second_lock = second._index.lock_run

    @contextmanager
    def held_first_lock(locked_run_id: str) -> Iterator[None]:
        with first_lock(locked_run_id):
            first_lock_entered.set()
            release_first_lock.wait()
            yield

    @contextmanager
    def observed_second_lock(locked_run_id: str) -> Iterator[None]:
        second_lock_requested.set()
        with second_lock(locked_run_id):
            yield

    monkeypatch.setattr(first._index, "lock_run", held_first_lock)
    monkeypatch.setattr(second._index, "lock_run", observed_second_lock)

    action = EnvironmentAction(type="inspect_onset_route", arguments={})

    def mutate(studio: ScienceStudio) -> object:
        callers_ready.wait()
        return studio.apply_run_action(run_id, action)

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutations = [executor.submit(mutate, first), executor.submit(mutate, second)]
        try:
            assert first_lock_entered.wait(timeout=2)
            assert second_lock_requested.wait(timeout=2)
        finally:
            release_first_lock.set()
        snapshots = [future.result(timeout=2) for future in mutations]

    ordered = sorted(snapshots, key=lambda snapshot: len(snapshot.trace))
    assert [len(snapshot.trace) for snapshot in ordered] == [4, 7]
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    assert len(artifact.read_text(encoding="utf-8").splitlines()) == 8
    assert ScienceStudio(tmp_path).current_run(run_id) == ordered[-1]


def test_action_recovers_a_full_prepared_append_after_checkpoint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    initial_route = studio._index.get_run(run_id)

    def fail_finalize(*args: object, **kwargs: object) -> object:
        raise StudioIndexStorageError()

    monkeypatch.setattr(studio._index, "resolve_run_trace_intent", fail_finalize)

    with pytest.raises(RuntimeContractError) as raised:
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert raised.value.code == "internal"
    assert studio._index.get_run(run_id) == initial_route
    assert studio._index.get_run_trace_intent(run_id) is not None
    recovered = ScienceStudio(tmp_path).current_run(run_id)
    assert len(recovered.trace) == 4
    assert ScienceStudio(tmp_path)._index.get_run_trace_intent(run_id) is None
    assert ScienceStudio(tmp_path)._index.get_run(run_id).trace_digest == recovered.trace_digest


def test_verify_recovers_a_full_prepared_append_after_checkpoint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    _advance_to_verification(studio, run_id)
    source_route = studio._index.get_run(run_id)

    def fail_finalize(*args: object, **kwargs: object) -> object:
        raise StudioIndexStorageError()

    monkeypatch.setattr(studio._index, "resolve_run_trace_intent", fail_finalize)

    with pytest.raises(RuntimeContractError) as raised:
        studio.verify_run(run_id)

    assert raised.value.code == "internal"
    assert studio._index.get_run(run_id) == source_route
    recovered = ScienceStudio(tmp_path).current_run(run_id)
    assert recovered.status == "completed"
    assert recovered.verifier_result is not None
    assert ScienceStudio(tmp_path)._index.get_run(run_id).trace_digest == recovered.trace_digest
    assert ScienceStudio(tmp_path)._index.get_run_trace_intent(run_id) is None


def test_intent_without_an_append_is_aborted_on_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    initial = studio.current_run(run_id)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    base = artifact.read_bytes()
    journal = _trace_journal(studio, run_id)

    def fail_before_append(plan: object) -> None:
        raise RuntimeContractError("injected append failure", code="internal")

    monkeypatch.setattr(journal, "append", fail_before_append)

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert studio._index.get_run_trace_intent(run_id) is not None
    assert artifact.read_bytes() == base
    assert ScienceStudio(tmp_path).current_run(run_id) == initial
    assert ScienceStudio(tmp_path)._index.get_run_trace_intent(run_id) is None


def test_partial_prepared_append_is_truncated_to_its_validated_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    initial = studio.current_run(run_id)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    base = artifact.read_bytes()
    journal = _trace_journal(studio, run_id)

    def append_prefix(plan: _AppendPlanLike) -> None:
        prefix = plan.append_payload[: max(1, len(plan.append_payload) // 2)]
        with artifact.open("ab", buffering=0) as stream:
            stream.write(prefix)
            os.fsync(stream.fileno())
        raise RuntimeContractError("injected partial append", code="internal")

    monkeypatch.setattr(journal, "append", append_prefix)

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert ScienceStudio(tmp_path).current_run(run_id) == initial
    assert artifact.read_bytes() == base
    assert ScienceStudio(tmp_path)._index.get_run_trace_intent(run_id) is None


def test_unrelated_tail_is_not_mistaken_for_a_prepared_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    journal = _trace_journal(studio, run_id)

    def append_unrelated_tail(plan: object) -> None:
        with artifact.open("ab", buffering=0) as stream:
            stream.write(b'{"unrelated":true}\n')
            os.fsync(stream.fileno())
        raise RuntimeContractError("injected unrelated append", code="internal")

    monkeypatch.setattr(journal, "append", append_unrelated_tail)

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    with pytest.raises(RuntimeContractError):
        ScienceStudio(tmp_path).current_run(run_id)
    assert ScienceStudio(tmp_path)._index.get_run_trace_intent(run_id) is not None


def test_wrong_append_that_returns_is_not_blessed_from_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    initial_route = studio._index.get_run(run_id)
    artifact = tmp_path / "traces" / f"{run_id}.jsonl"
    journal = _trace_journal(studio, run_id)

    def append_wrong_payload(plan: object) -> None:
        with artifact.open("ab", buffering=0) as stream:
            stream.write(b'{"wrong_but_returned":true}\n')
            os.fsync(stream.fileno())

    monkeypatch.setattr(journal, "append", append_wrong_payload)

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert studio._index.get_run(run_id) == initial_route
    assert studio._index.get_run_trace_intent(run_id) is not None
    with pytest.raises(RuntimeContractError):
        ScienceStudio(tmp_path).current_run(run_id)


def test_commit_that_reports_failure_is_resolved_on_the_next_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, run_id = _started_studio_run(tmp_path)
    resolve = studio._index.resolve_run_trace_intent

    def commit_then_fail(*args: object, **kwargs: object) -> object:
        resolve(*args, **kwargs)
        raise StudioIndexStorageError()

    monkeypatch.setattr(
        studio._index,
        "resolve_run_trace_intent",
        commit_then_fail,
    )

    with pytest.raises(RuntimeContractError):
        studio.apply_run_action(
            run_id,
            EnvironmentAction(type="inspect_onset_route", arguments={}),
        )

    assert studio._index.get_run_trace_intent(run_id) is None
    recovered = ScienceStudio(tmp_path).current_run(run_id)
    assert len(recovered.trace) == 4
    assert ScienceStudio(tmp_path)._index.get_run(run_id).trace_digest == recovered.trace_digest
