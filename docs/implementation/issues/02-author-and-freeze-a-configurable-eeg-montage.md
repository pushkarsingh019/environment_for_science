# 02: Author and freeze a configurable EEG Montage

**What to build:** Extend the first slice so an Environment author can visually and conversationally revise the EEG draft, inspect a configurable whole-cap Apparatus and Procedure-selected Montage, reverse changes, import a descriptive note, and prove that a frozen run cannot be changed by later authoring.

**Blocked by:** 01: Run and replay one EEG marker-recovery episode

**Status:** complete

- [x] The EEG Apparatus is represented as a configurable whole cap rather than a fixed four-channel device.
- [x] The seeded Montage contains FC3, FC4, FT7, FT8, FCz reference, and A1 ground while remaining distinct from the Apparatus.
- [x] Setup details reveal 1017 Hz sampling, 0.1–30 Hz bandpass, and 50 Hz notch only on demand.
- [x] Conversational commands can add or remove a Montage site, change a supported draft setting, and explain an unsupported request without exposing schemas or code.
- [x] The console shows the changed scientific state immediately and attributes the draft edit to the Authoring assistant.
- [x] Undo, redo, and restore-seed behavior work entirely on the draft.
- [x] A local note can be staged as reversible, explicitly unverified descriptive input and cannot directly control a run.
- [x] Freezing records an immutable bundle revision and scenario identity.
- [x] Draft changes made after freezing cannot alter the active run, its trace, or its replay.
- [x] Tests exercise authoring through the application seam, including validation failures and Authoring-assistant/Policy-agent isolation.
