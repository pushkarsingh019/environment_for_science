# 03: Diagnose EEG signal and response failures visually

**What to build:** Give the Environment author and Policy agent a scientifically recognizable EEG preflight in which visual traces, frequency evidence, Montage context, onset evidence, and response evidence support targeted diagnosis, recovery, retesting, or justified abort.

**Blocked by:** 02: Author and freeze a configurable EEG Montage

**Status:** complete

- [x] The console visualizes deterministic live-looking multichannel traces with channel identities and a compact scalp Montage.
- [x] Frequency evidence is available on demand and can distinguish channel-local, shared environmental, and reference-related noise.
- [x] Scenarios cover noisy, faulty, flat, and clipped electrodes without using a fabricated universal signal-quality threshold.
- [x] Scenarios cover faulty reference or ground, environmental noise, missing onset markers, visible-trigger confounds, response occurrence/identity mismatches, and recording-state/timeline mismatches.
- [x] Policy-visible observations never expose the causal fault label or hidden state.
- [x] Permitted actions support inspection, targeted simulated remediation, fresh evidence collection, and evidence-based abort without exposing physical-hardware controls.
- [x] Every state-changing action invalidates relevant stale evidence.
- [x] Verifiers distinguish targeted recovery, ineffective action, lucky terminal action, justified abort, and blanket caution.
- [x] Visual output is deterministic for a given scenario seed and is labeled synthetic.
- [x] Golden runtime traces cover each fault family, successful and failed recovery, justified abort, unjustified abort, and deterministic replay.
- [x] Browser tests verify that visualization, details, actions, and verifier explanations remain usable without information-heavy cards.
