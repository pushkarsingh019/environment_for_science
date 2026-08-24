# 13: Ship the resettable end-to-end demo

**What to build:** Deliver one runnable, reviewable prototype journey from scientist-facing authoring through EEG and mesoscope simulation, deterministic verification, model evaluation, Gemma training evidence, held-out comparison, replay, and complete reset.

**Blocked by:** 12: Compare all models in the Scientist Console

**Status:** complete — resettable journey, real evidence, complete suites, and final review pass

- [x] One documented command starts the complete local product from a clean checkout and reports missing external prerequisites clearly.
- [x] The primary journey lets an Environment author edit and freeze EEG, run and verify a fault scenario, inspect base evaluation, launch or inspect real training, and compare the reloaded trained result.
- [x] The secondary journey runs the sealed mesoscope handoff and shows separate platform-generality evidence.
- [x] The console remains visualization-first, progressively disclosed, responsive, keyboard accessible, and free of rejected marketing-style layouts.
- [x] Authoring assistant, Policy agent, hidden state, verifier, provider adapter, and training-job roles remain visibly and technically isolated.
- [x] Offline seeded runs demonstrate all screens when hosted credentials are absent, while real and fixture results cannot be confused.
- [x] Reset restores seeded drafts, scenarios, fixture results, and demonstration state without deleting immutable real artifacts.
- [x] Replays reproduce canonical results and every displayed aggregate retains provenance.
- [x] End-to-end browser tests cover authoring, freeze, run, fault recovery, verification, mesoscope quarantine/success, evaluation, training status, comparison, replay, and reset.
- [x] Runtime, adapter, split-integrity, artifact, statistical, security, and browser suites all pass from documented commands.
- [x] Documentation records simulation limits, exact supported Apparatuses, model and dependency pins, workstation-only compute, credential setup boundaries, and recovery from common failures.
- [x] No physical hardware controls, credentials, private keys, private host details, or contents of private SSH material appear in source, logs, traces, generated artifacts, screenshots, or UI.
- [x] Standards and specification review find no unresolved blocking issue before the demo ticket is closed.
- [x] Passing evidence is sufficient to resolve decision tickets 08 and 12; partial mock screens are not accepted as completion.

## Implementation readiness

`.venv/bin/python -m studio` builds and starts the complete loopback product and reports only
configured/missing provider readiness, never secret values. The browser journey now authors and
freezes EEG, recovers and verifies a fault, replays canonical evidence, exercises mesoscope
success and quarantine evidence, inspects workstation-only training status, opens the four-model
comparison and scenario replay, then resets to seeded state. A central reset restores the draft
and offline fixture selection while deleting mutable demonstration queues and retaining completed
acceptance jobs, the completed curriculum job, sealed evaluator ledgers, and real comparison rows.

The final clean run collected 923 Python tests (907 passed and 16 explicit opt-in dependency/
credential canaries skipped), passed Ruff and mypy across 54 source files, built and typechecked
the console, and passed all 45 Chromium journeys. The installed real comparison opens validated
canonical evaluator snapshots before fixture-reset journeys run. Repository scans found no private
host, credential, key, or SSH material. The two-axis review found no remaining documented-standard
violation; its mesoscope-reward and Ticket 10 evidence findings were fixed with native reward
parity, DCP object/shard linkage, exact LoRA structure, canonical snapshot replay, and model-call
lineage. The remaining durable-store duplication and scenario-map data clumps are non-blocking
refactoring judgements, not acceptance defects.
