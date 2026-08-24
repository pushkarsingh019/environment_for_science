# Prototype the mesoscope scenario contract

Type: prototype
Status: resolved
Blocked by: 02, 04

## Question

Using the mesoscope research, which acquisition-readiness slice should the demo simulate, and what state, visual observations, actions, transitions, faults, interlocks, and deterministic verifiers make it both credible and visually compelling? Produce a concrete rough simulation for the user to react to while keeping its scientific limitations explicit.

## Progress

The sealed interactive prototype now implements the selected four-region acquisition-readiness
handoff with immutable synthetic profile, signed R1–R4 and Z-A/Z-B plan, independent safety gate,
progressive package evidence, deterministic quarantine/reject/success outcomes, and exact
five-artifact checksums. Eight reviewed scenarios cover complete agreement and every required
fault family. The same public Environment compiler, Runtime, canonical trace, reset, and replay
paths used for EEG execute mesoscope without adding physical controls. Console tests at desktop
and mobile widths preserve the synthetic/sealed/disconnected boundary, while the comparison view
reports this only as separate `platform_generality` evidence and never as EEG or cross-Apparatus
training evidence.
