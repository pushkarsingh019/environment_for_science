# 04: Run the complete EEG curriculum and fixed splits

**What to build:** Turn the EEG Environment into the approved staged curriculum with immutable training, development, and held-out manifests, compound faults, safe-abort behavior, and diagnostic metrics suitable for evaluation and training.

**Blocked by:** 03: Diagnose EEG signal and response failures visually

**Status:** complete

- [x] The curriculum progresses from marker-only through configuration, signal inspection, onset and response preflight, short acquisition, runtime recovery, annotation, and valid close or abort.
- [x] Exactly 96 training, 32 development, and 64 held-out scenario identities are materialized as deterministic manifests.
- [x] Blueprint, nuisance, and scenario identifiers are disjoint according to the approved split policy.
- [x] The documented fault pairs and triples occur only in held-out evaluation.
- [x] Individual, ambiguous, pair, and triple scenario categories are encoded explicitly and can be reported separately.
- [x] A genuinely unavailable recovery path permits an eligible safe abort with equal terminal credit.
- [x] Abort precision and recall expose blanket-abort behavior and prevent it from scoring well.
- [x] Scenario setup, observation order, action order, reset, and replay remain deterministic from manifest and seed.
- [x] The console can select seeded curriculum examples and display stage, evidence freshness, terminal disposition, and metrics.
- [x] Automated integrity tests fail on split leakage, duplicate identities, unstable manifest digests, hidden-state leakage, or unreachable terminal states.
- [x] Full held-out manifests remain unavailable to training inputs and training artifact generation.
