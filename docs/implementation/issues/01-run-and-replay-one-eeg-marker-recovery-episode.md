# 01: Run and replay one EEG marker-recovery episode

**What to build:** A narrow but complete first slice of the Scientist Console in which an Environment author opens the seeded EEG Environment, freezes it, runs a duplicate-onset-marker scenario, applies the targeted simulated repair, collects fresh evidence, receives a deterministic verifier result, and resets or replays the trace.

**Blocked by:** None (can start immediately)

**Status:** complete

- [x] One documented local command starts the console and product runtime from a clean checkout.
- [x] The console uses the accepted quiet, visualization-first shell rather than the rejected marketing-style prototype.
- [x] The seeded Environment Bundle validates before the run and exposes Policy-visible state separately from hidden scenario truth.
- [x] Starting the run freezes an immutable Environment revision and identifies the active Policy agent.
- [x] One simulated lower-right display flash produces two onset markers in the seeded failing scenario.
- [x] The permitted actions allow inspection of the onset route, the targeted simulated refractory-route repair, and a fresh test flash.
- [x] The verifier fails stale or pre-repair evidence and passes only when the fresh post-repair flash produces exactly one marker.
- [x] The console shows the ordered observations, actions, transitions, freshness evidence, and scientist-readable verifier result.
- [x] Reset restores the identical initial scenario; replay reproduces the same trace and result digest.
- [x] Runtime-level and browser-level tests cover the successful recovery, an incorrect action, stale evidence, reset, and replay.
- [x] No physical connector, credential, code editor, RL terminology, or operational control is exposed.
