# Build the Science Environment Studio

Source specification: [Science Environment Studio executable prototype specification](../specification.md)

## Progress

- Completed: **7 / 13**
- In progress: **None**
- Ready now: **08, 09, 10**
- A ticket counts as complete only after its acceptance criteria, tests, review, and commit pass.

## Current checkpoint

Tickets 01 through 07 are complete. One local command builds and serves the Scientist Console
with the loopback-only deterministic Environment Runtime. The console runs and replays the
targeted EEG recovery episodes and now provides a scientifically recognizable EEG
diagnostic preflight over a configurable schematic whole-cap Apparatus and distinct
Procedure-selected Montage.

The run view presents deterministic aligned synthetic traces, a compact Montage, on-demand
frequency measurements, and separate onset, response, and recording timelines. Twenty opaque
singleton cases cover the Ticket 03 evidence families and controls through one constant typed
action catalog. State-changing simulated remediation invalidates relevant evidence until a
fresh retest, and deterministic Verifiers distinguish targeted recovery, ineffective or lucky
terminal behavior, restraint, justified abort, and blanket caution without exposing causal
scenario truth.

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

The EEG Environment now implements the frozen staged curriculum from marker-only preflight
through short acquisition, runtime recovery, annotation, valid close, and evidence-based
abort. Content-addressed manifests materialize exactly 96 training, 32 development, and 64
held-out scenarios with disjoint opaque identities and evaluator-only reserved pairs and
triples. Every frozen row has a deterministic terminal witness and replay proof.

Reports recompute exact terminal success, bounded reward components, abort precision and
recall, sufficient-statistic diagnostics, and private scientific strata from canonical
traces. A persistent write-once scenario/rollout/model-configuration ledger predeclares the
held-out matrix, preserves harness failures across restarts, and binds its sealed digest into
each report. The console exposes only six neutral training examples;
the actual training wheel excludes evaluator code, held-out manifests, identities, records,
seeds, and reserved compositions and passes an evaluator-owned confinement scan.

The same catalog-driven console and shared Environment Runtime now run a second, sealed
mesoscope handoff without apparatus controls. Its immutable synthetic profile, signed R1–R4
and Z-A/Z-B plan, and independent safety gate stay visible while deterministic procedural
tiles and progressive package evidence expose region, channel, frame, event, motion, manifest,
and checksum agreement. Eight reviewed scenarios cover complete agreement and every required
fault family; invalid packages can only be quarantined or rejected, and exact success is
emitted only as `MOCK PACKAGE VERIFIED`.

The Environment catalog, bundle freeze, persistence, canonical trace, reset, replay, and
Verifier result paths are shared across EEG and mesoscope. Runtime contract tests exercise
both modules, while adversarial tests bind visible expected outputs and the rehashed signed
plan to independently observed package evidence. They also authenticate the permanent
simulation labels, sealed profile, independent gate, and exact five-artifact checksum set;
missing, duplicate, or self-forged checksum rows cannot pass. The browser suite verifies the
synthetic/sealed/disconnected boundary at desktop and mobile widths.

Minor-version `future_*` and `x_*` metadata is treated as opaque compatibility material, not
as trusted scientific or operational content. Finite JSON additions are accepted only at an
explicit set of inert authored locations and remain preserved in the raw content-addressed
bundle; action-schema annotations are further limited to a non-empty label envelope. Reviewed
projections remove them before runtime schema validation and before Policy,
API, trace, Verifier, or console consumption; executable schemas, scenario state, signed data,
and canonical list semantics remain closed.

The validated EEG development Bundle now compiles reproducibly into a disposable native
Verifiers v1 Taskset, Toolset, null-harness adapter, and evaluation configuration while the
authored Bundle remains authoritative. Exact native canaries cover declared-tool setup,
parameterized actions, retry idempotency, scientific success and failure, turn, tool, output,
and early-stop budgets, error normalization, runtime-result parity, and canonical trace-digest
parity against the product-owned Runtime.

A provider-neutral canonical runner executes the fixed 32-scenario base-Gemma development
matrix through an attested, text-only, loopback logical route carried over an owner-only Unix
socket. It preserves model, response, message, tool-call/result, accounting, action, transition,
Verifier, runtime-distribution, and infrastructure-error evidence without persisting model
coordinates, credentials, host paths, or opaque reflected runtime secrets. Calibration readiness
requires a bounded mix of successes and failures, no infrastructure errors, and authenticated
local-runtime evidence for every row.

The Scientist Console can launch, resume, list, inspect, and replay the durable write-once local
evaluation in ordinary language. A separately staged fixed launcher, bootstrap, model stager,
namespace proxy, immutable model/runtime receipts, and operator procedure define the sole
supported local-Gemma serving boundary without adding physical Apparatus controls or exposing
provider-side tools.

Mesoscope now compiles through the exact public compiler used by EEG and executes valid and
quarantine multi-turn Policy traces through the unchanged canonical runner and Runtime bridge.
The console keeps its seeded replayable compiler and handoff evidence in a separate
platform-generality track, with no EEG-training or cross-Apparatus claim. Shared conformance and
artifact scans keep generated and model-visible tools inside the sealed mock-action boundary.

## Frontier

- [08: Evaluate GPT through OpenAI Responses](issues/08-evaluate-gpt-through-openai-responses.md) — can start immediately
- [09: Evaluate Gemini through Interactions](issues/09-evaluate-gemini-through-interactions.md) — can start immediately
- [10: Train, save, reload, and evaluate a bounded Gemma adapter](issues/10-train-save-reload-and-evaluate-a-bounded-gemma-adapter.md) — can start immediately

## Dependency order

1. [Run and replay one EEG marker-recovery episode](issues/01-run-and-replay-one-eeg-marker-recovery-episode.md) — complete
2. [Author and freeze a configurable EEG Montage](issues/02-author-and-freeze-a-configurable-eeg-montage.md) — complete
3. [Diagnose EEG signal and response failures visually](issues/03-diagnose-eeg-signal-and-response-failures-visually.md) — complete
4. [Run the complete EEG curriculum and fixed splits](issues/04-run-the-complete-eeg-curriculum-and-fixed-splits.md) — complete
5. [Run the sealed mesoscope four-region handoff](issues/05-run-the-sealed-mesoscope-four-region-handoff.md) — complete
6. [Evaluate EEG through Verifiers and local base Gemma](issues/06-evaluate-eeg-through-verifiers-and-local-base-gemma.md) — complete
7. [Prove mesoscope portability through the same compiler](issues/07-prove-mesoscope-portability-through-the-same-compiler.md) — complete
8. [Evaluate GPT through OpenAI Responses](issues/08-evaluate-gpt-through-openai-responses.md) — ready
9. [Evaluate Gemini through Interactions](issues/09-evaluate-gemini-through-interactions.md) — ready
10. [Train, save, reload, and evaluate a bounded Gemma adapter](issues/10-train-save-reload-and-evaluate-a-bounded-gemma-adapter.md) — ready
11. [Train Gemma on the EEG curriculum](issues/11-train-gemma-on-the-eeg-curriculum.md) — blocked by 10
12. [Compare all models in the Scientist Console](issues/12-compare-all-models-in-the-scientist-console.md) — blocked by 07, 08, 09, and 11
13. [Ship the resettable end-to-end demo](issues/13-ship-the-resettable-end-to-end-demo.md) — blocked by 12
