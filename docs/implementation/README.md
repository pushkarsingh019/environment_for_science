# Build the Science Environment Studio

Source specification: [Science Environment Studio executable prototype specification](../specification.md)

## Progress

- Completed: **0 / 13**
- In progress: **01**
- Ready now: **01**
- A ticket counts as complete only after its acceptance criteria, tests, review, and commit pass.

## Current checkpoint

Ticket 01 has a partial Environment Bundle validator, seeded EEG bundle, Scientist Console
shell, and mocked browser test. The runtime, HTTP API, episode transitions, verifier,
canonical trace, reset, and replay behavior remain to be implemented. Treat the mocked
browser response as an interface fixture, not evidence that the runtime behavior works.

## Frontier

- [01: Run and replay one EEG marker-recovery episode](issues/01-run-and-replay-one-eeg-marker-recovery-episode.md) — can start immediately

## Dependency order

1. [Run and replay one EEG marker-recovery episode](issues/01-run-and-replay-one-eeg-marker-recovery-episode.md)
2. [Author and freeze a configurable EEG Montage](issues/02-author-and-freeze-a-configurable-eeg-montage.md) — blocked by 01
3. [Diagnose EEG signal and response failures visually](issues/03-diagnose-eeg-signal-and-response-failures-visually.md) — blocked by 02
4. [Run the complete EEG curriculum and fixed splits](issues/04-run-the-complete-eeg-curriculum-and-fixed-splits.md) — blocked by 03
5. [Run the sealed mesoscope four-region handoff](issues/05-run-the-sealed-mesoscope-four-region-handoff.md) — blocked by 01
6. [Evaluate EEG through Verifiers and local base Gemma](issues/06-evaluate-eeg-through-verifiers-and-local-base-gemma.md) — blocked by 04
7. [Prove mesoscope portability through the same compiler](issues/07-prove-mesoscope-portability-through-the-same-compiler.md) — blocked by 05 and 06
8. [Evaluate GPT through OpenAI Responses](issues/08-evaluate-gpt-through-openai-responses.md) — blocked by 06
9. [Evaluate Gemini through Interactions](issues/09-evaluate-gemini-through-interactions.md) — blocked by 06
10. [Train, save, reload, and evaluate a bounded Gemma adapter](issues/10-train-save-reload-and-evaluate-a-bounded-gemma-adapter.md) — blocked by 06
11. [Train Gemma on the EEG curriculum](issues/11-train-gemma-on-the-eeg-curriculum.md) — blocked by 04 and 10
12. [Compare all models in the Scientist Console](issues/12-compare-all-models-in-the-scientist-console.md) — blocked by 07, 08, 09, and 11
13. [Ship the resettable end-to-end demo](issues/13-ship-the-resettable-end-to-end-demo.md) — blocked by 12
