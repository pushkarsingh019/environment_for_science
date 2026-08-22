# Build the Science Environment Studio

Source specification: [Science Environment Studio executable prototype specification](../specification.md)

## Progress

- Completed: **1 / 13**
- In progress: **None**
- Ready now: **02, 05**
- A ticket counts as complete only after its acceptance criteria, tests, review, and commit pass.

## Current checkpoint

Ticket 01 is complete. One local command builds and serves the Scientist Console with the
loopback-only deterministic Environment Runtime. The seeded EEG bundle validates before a
run; Policy-visible observations remain separate from hidden scenario truth. The console
freezes the Environment revision and Policy-agent identity, runs the targeted marker-recovery
sequence, displays ordered canonical evidence, persists caller-visible traces as append-only
JSONL, verifies fresh post-repair evidence, resets to the identical initial scenario, and
replays a completed run with matching trace and result digests.

Runtime, HTTP, and real-backend browser tests cover successful recovery, a
wrong-but-permitted action, stale evidence, reset, and replay.

## Frontier

- [02: Author and freeze a configurable EEG Montage](issues/02-author-and-freeze-a-configurable-eeg-montage.md) — can start immediately
- [05: Run the sealed mesoscope four-region handoff](issues/05-run-the-sealed-mesoscope-four-region-handoff.md) — can start immediately

## Dependency order

1. [Run and replay one EEG marker-recovery episode](issues/01-run-and-replay-one-eeg-marker-recovery-episode.md) — complete
2. [Author and freeze a configurable EEG Montage](issues/02-author-and-freeze-a-configurable-eeg-montage.md) — ready
3. [Diagnose EEG signal and response failures visually](issues/03-diagnose-eeg-signal-and-response-failures-visually.md) — blocked by 02
4. [Run the complete EEG curriculum and fixed splits](issues/04-run-the-complete-eeg-curriculum-and-fixed-splits.md) — blocked by 03
5. [Run the sealed mesoscope four-region handoff](issues/05-run-the-sealed-mesoscope-four-region-handoff.md) — ready
6. [Evaluate EEG through Verifiers and local base Gemma](issues/06-evaluate-eeg-through-verifiers-and-local-base-gemma.md) — blocked by 04
7. [Prove mesoscope portability through the same compiler](issues/07-prove-mesoscope-portability-through-the-same-compiler.md) — blocked by 05 and 06
8. [Evaluate GPT through OpenAI Responses](issues/08-evaluate-gpt-through-openai-responses.md) — blocked by 06
9. [Evaluate Gemini through Interactions](issues/09-evaluate-gemini-through-interactions.md) — blocked by 06
10. [Train, save, reload, and evaluate a bounded Gemma adapter](issues/10-train-save-reload-and-evaluate-a-bounded-gemma-adapter.md) — blocked by 06
11. [Train Gemma on the EEG curriculum](issues/11-train-gemma-on-the-eeg-curriculum.md) — blocked by 04 and 10
12. [Compare all models in the Scientist Console](issues/12-compare-all-models-in-the-scientist-console.md) — blocked by 07, 08, 09, and 11
13. [Ship the resettable end-to-end demo](issues/13-ship-the-resettable-end-to-end-demo.md) — blocked by 12
