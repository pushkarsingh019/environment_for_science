# Build the Science Environment Studio

Source specification: [Science Environment Studio executable prototype specification](../specification.md)

## Progress

- Completed: **2 / 13**
- In progress: **None**
- Ready now: **03, 05**
- A ticket counts as complete only after its acceptance criteria, tests, review, and commit pass.

## Current checkpoint

Tickets 01 and 02 are complete. One local command builds and serves the Scientist Console
with the loopback-only deterministic Environment Runtime. The console runs and replays the
targeted EEG marker-recovery episode and now provides a configurable schematic whole-cap
Apparatus with a distinct Procedure-selected Montage.

An Environment author can make bounded conversational edits, inspect changes immediately,
undo, redo, restore the seed, and stage explicitly unverified descriptive notes. The draft is
transactional and persistent; freezing creates a content-addressed Environment revision that
later draft edits cannot change. Authoring-assistant and Policy-agent prompts, tools, context,
state, and logs remain explicitly isolated.

Frozen Environment and run indexes persist in SQLite. Canonical JSONL traces are bound to
their immutable headers and latest full-trace digests, serialized across Studio processes,
and protected by a recoverable prepared-intent protocol for action and verifier writes.
Runtime, HTTP, persistence, concurrency, and real-backend browser tests cover positive,
negative, restart, tamper, partial-write, reset, and replay paths.

## Frontier

- [03: Diagnose EEG signal and response failures visually](issues/03-diagnose-eeg-signal-and-response-failures-visually.md) — can start immediately
- [05: Run the sealed mesoscope four-region handoff](issues/05-run-the-sealed-mesoscope-four-region-handoff.md) — can start immediately

## Dependency order

1. [Run and replay one EEG marker-recovery episode](issues/01-run-and-replay-one-eeg-marker-recovery-episode.md) — complete
2. [Author and freeze a configurable EEG Montage](issues/02-author-and-freeze-a-configurable-eeg-montage.md) — complete
3. [Diagnose EEG signal and response failures visually](issues/03-diagnose-eeg-signal-and-response-failures-visually.md) — ready
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
