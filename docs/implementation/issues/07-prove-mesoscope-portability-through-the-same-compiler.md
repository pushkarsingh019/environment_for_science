# 07: Prove mesoscope portability through the same compiler

**What to build:** Evaluate mesoscope through the existing Environment Runtime, compiler, Verifiers adapter, and canonical model runner without introducing a second framework-specific scientific implementation.

**Blocked by:** 05: Run the sealed mesoscope four-region handoff; 06: Evaluate EEG through Verifiers and local base Gemma

**Status:** complete

- [x] The mesoscope bundle compiles through the same public compiler interface used by EEG.
- [x] No mesoscope-specific branch is added to the canonical runner, trace store, or Verifiers integration seam.
- [x] Direct runtime and Verifiers executions agree on observations, action effects, terminal disposition, verifier metrics, and trace digest.
- [x] A local Gemma Policy agent can complete a multi-turn valid or quarantine handoff using only declared mesoscope mock actions.
- [x] The exact `MOCK PACKAGE VERIFIED` terminal rule remains enforced through generated Verifiers behavior.
- [x] Mesoscope evaluation is reported separately from the EEG training claim.
- [x] A platform-conformance test runs both Environment modules through the same lifecycle, validation, visibility, reset, replay, and error contract.
- [x] The console displays the mesoscope evaluation and links each result to its canonical replay.
- [x] No generated or model-visible artifact exposes operational mesoscope controls.
