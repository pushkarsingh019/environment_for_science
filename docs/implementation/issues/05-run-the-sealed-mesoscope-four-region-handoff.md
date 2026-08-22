# 05: Run the sealed mesoscope four-region handoff

**What to build:** Add a second complete Environment in which the user visually runs and verifies a sealed synthetic R1–R4 handoff, detects package faults, quarantines invalid output, and resets or replays the scenario without receiving operational mesoscope controls.

**Blocked by:** 01: Run and replay one EEG marker-recovery episode

**Status:** complete

- [x] The console switches between EEG and mesoscope using the same compact Environment navigation and run lifecycle.
- [x] Every mesoscope view and trace is clearly labeled synthetic, sealed, and disconnected from hardware.
- [x] The visualization shows R1–R4, Z-A/Z-B, synthetic image tiles, expected outputs, event records, motion rows, and package checksums with progressive disclosure.
- [x] Profiles, plans, and safety-gate states are visible but immutable.
- [x] Permitted actions are limited to inspection, mock acquisition, package validation, quarantine, reset, and replay.
- [x] Action schemas contain no laser, detector, alignment, calibration, surgery, biological, or motion-control fields.
- [x] Compatible v1.x namespaced metadata is retained only in the raw authored bundle; reviewed runtime-validation and Policy/API/UI projections exclude it.
- [x] Deterministic scenarios cover a valid package, missing region, wrong Z assignment, missing channel, duplicate or missing event, motion-row mismatch, and checksum mismatch.
- [x] Invalid packages can only be quarantined or rejected; they cannot be repaired through operational controls.
- [x] Success is emitted only after complete agreement and uses the exact terminal wording `MOCK PACKAGE VERIFIED`.
- [x] The Environment uses the shared bundle envelope, run lifecycle, canonical trace shape, verifier result shape, reset, and replay behavior.
- [x] Runtime and browser tests cover all package outcomes and enforce the sealed safety boundary.
