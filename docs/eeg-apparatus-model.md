# EEG apparatus model

## Decision

The prototype represents a **configurable human scalp-EEG apparatus**, not Pushkar's auditory-localization experiment frozen in software.

- Show a whole EEG cap and acquisition chain.
- Let each procedure choose its required montage. The seeded auditory-localization procedure may select FC3, FC4, FT7, and FT8, with FCz as reference and A1 as ground, but those sites do not define the apparatus.
- Seed the simulator with the user's real TDT-based topology and failure history.
- Treat the stimulus paradigm, trial conditions, and response labels as procedure configuration rather than apparatus identity.
- Use a 0.1–30 Hz online bandpass in the seeded profile.
- Put the optical trigger patch and detector at the lower-right of the simulated display.
- Make live signal-quality judgment visual and comparative. Do not pretend the user followed a precise numerical readiness threshold that did not exist.

This is a simulation contract for agent evaluation and training. It is not medical guidance, a validated EEG quality-control procedure, or a driver for physical equipment.

## Provenance

The model uses three evidence labels:

- **Observed**: documented in the thesis or experiment code.
- **Confirmed**: clarified by the apparatus operator in the project interview.
- **Simulated**: a deliberate product choice needed to make deterministic episodes and verifiers.

Primary local evidence is the signed thesis, especially physical PDF pages 56–66, 83–88, and 96–100. Code evidence comes from [`pushkarsingh019/pushkar-undergrad-thesis`](https://github.com/pushkarsingh019/pushkar-undergrad-thesis) at commit `145202d5fd8eb1c2015bfefcbf988a54e25c0544`. The local signed PDF is reference material and is not a repository artifact.

## Boundary: apparatus versus paradigm

The **apparatus** is the connected cap, acquisition instruments, stimulus and response components, room, and software integrations. A **paradigm** supplies stimuli, trial conditions, required electrodes, response meanings, and timing.

The seeded auditory-localization paradigm is useful because it exercises every apparatus path. Its ±20° and ±60° response locations can remain as an example, but neither those locations nor the original four-channel analysis should constrain other authored procedures.

## Seeded apparatus topology

```text
Participant
  ├─ scalp electrodes ─> 32-channel S-Box ─> PZ5 ──optical──> RZ6 ─> EEG stream
  ├─ headphones <─ HX3 amplifier <─ presentation computer / PsychoPy
  └─ four-button box ─> PP24 / RZ6
                              ├─ response-present line ─> serial carrier detect ─> PsychoPy
                              └─ button identity ─> Synapse API ─> PsychoPy

Display lower-right flash ─> LM393 light detector ─> NE555 refractory timer
                           ─> PP24 / RZ6 onset marker
```

| Component or path | Seeded representation | Provenance |
|---|---|---|
| Participant and scalp cap | Human scalp EEG with a visually complete configurable cap | Scalp EEG and EasyCap are **Observed**; exposing a whole selectable cap is **Confirmed/Simulated** |
| Original montage | FC3, FC4, FT7, FT8; FCz reference; A1 ground | **Observed/Confirmed** as the seeded example, not a limit |
| Acquisition chain | 32-channel S-Box → PZ5 neurodigitizer → optical fiber → RZ6 processor | **Observed** |
| Acquisition profile | 1017 Hz sampling, 0.1–30 Hz online bandpass, 50 Hz notch | Sampling/notch are **Observed**; bandpass is **Confirmed** |
| Presentation | PsychoPy computer, DC-powered monitor, DT-770 Pro headphones, HX3 amplifier | **Observed** |
| Onset marker | Lower-right display flash → LM393 → NE555 refractory timer → PP24/RZ6 | Hardware is **Observed**; corner is **Confirmed** |
| Response path | Four-button box → PP24/RZ6; fast response-present signal plus later button-identity query | **Observed** |
| Recording room | Sound-shielded but not electrically shielded; AC supplies kept outside where possible | **Observed** |
| Synthetic EEG source | Deterministic multi-channel signals, artifacts, and instrument faults | **Simulated** |

The simulator should preserve the recognizable topology without copying vendor APIs into its portable environment contract. A later physical connector may translate portable actions to vendor-specific operations.

## Recommended episode boundary

The first complete EEG episode begins after a procedure has selected its montage and ends when the agent either:

1. validates the apparatus and starts a scientifically usable acquisition, or
2. aborts safely with a defensible reason and preserves the diagnostic trace.

Recommended stages:

1. **Configure** — load the procedure's required montage and acquisition profile.
2. **Prepare** — establish electrode contact and participant readiness in simulation.
3. **Inspect EEG** — inspect live traces, spectra, and channel relationships.
4. **Verify onset markers** — present test flashes and check marker count and timing.
5. **Verify responses** — press each simulated button and check occurrence, identity, and mapping.
6. **Arm acquisition** — enter the correct recording state only after successful checks.
7. **Monitor** — observe quality while trials run; pause when evidence becomes invalid.
8. **Recover or abort** — take a targeted action, retest, then continue or stop.
9. **Close** — preserve data, event logs, interventions, and validity annotations.

A smaller first training task can isolate stages 4–5: **one flash must produce one onset marker before acquisition unlocks**.

## What the agent can observe

### EEG evidence

- Rolling raw trace for every available channel
- Procedure-required versus optional channels
- Per-channel spectrum or band-power summary
- Relative amplitude and texture across channels
- Flatline, clipping, drift, transient burden, and dropout indicators
- Shared/common-mode versus channel-local contamination
- Recent quality history, not only an instantaneous score

The user's real decision rule was qualitative: visually reject “absurd noise” by considering the signal's appearance and frequency content. Therefore the primary UI should show traces and frequency evidence. A synthetic scalar quality score may help authoring or debugging, but it must not replace the evidence presented to the policy.

The thesis's offline `>100 µV` epoch rejection rule is not a documented live readiness threshold and must not be presented as one.

### Integration evidence

- Instrument connection, power, and recording states
- Selected montage, reference, ground, sample rate, filter, and notch configuration
- Test-flash times and resulting RZ6 onset markers
- Refractory-timer route, power, and status
- Response-present line and queried button identity
- Stimulus code, onset marker, response, and EEG timeline alignment
- Unacknowledged or invalid trial ranges

The policy sees effects and inspectable apparatus state, not the hidden scenario fault label.

## Permitted simulated actions

Actions should be intent-level and portable. They can compile to vendor-specific calls later.

### Inspect

- View all live EEG traces
- Focus on a channel or compare a group
- View spectral evidence over a selected recent window
- Inspect montage, reference, ground, filters, connections, and recording state
- Inspect trigger and response timelines
- Run a trigger or response preflight

### Remediate

- Reseat or re-gel a selected electrode
- Check or reconnect reference and ground
- Ask the simulated participant to relax, remain still, or pause blinking
- Isolate a simulated electrical-noise source or reroute a cable
- Replace a faulty electrode or simulated battery
- Enable or repair the refractory-timer route
- Correct a button mapping or response handshake
- Correct acquisition configuration
- Restart a failed software/instrument integration while acquisition is safely paused

### Control the procedure

- Mark an interval invalid with a reason
- Pause, repeat a preflight, resume, or abort
- Start acquisition only when preflight requirements pass
- Save the trace and intervention log

The UI must state that these actions affect a simulated apparatus only.

## Fault curriculum

| Scenario | Observable signature | Credible response | Provenance |
|---|---|---|---|
| Poor contact or faulty electrode | One channel has extreme noise, dropout, drift, or implausible contrast with neighbors | Inspect that channel, reseat/re-gel or replace it, then retest | Faulty sensors and large/noisy recordings are **Observed**; deterministic signatures and fixes are **Simulated** |
| Reference or ground problem | Similar large contamination appears across many channels | Inspect reference/ground before disturbing every electrode; reconnect and retest | Topology is **Observed**; exact signature/remediation mapping is **Simulated** |
| Participant movement, blink, or muscle activity | Transient slow deflections or dense higher-frequency activity linked across relevant channels | Pause/instruct participant, wait for a stable window, then continue or invalidate the interval | Movement minimization is **Observed**; episode mechanics are **Simulated** |
| Environmental electrical contamination | Persistent rhythmic or broadband pattern shared across channels and associated with a powered component | Inspect common sources, isolate simulated power/cable source, then retest | Unshielded room and high-frequency noise are **Observed**; root-cause cases are **Simulated** |
| Flatline or clipping | Constant channel or rail-limited waveform | Inspect connection/gain path; do not accept a deceptively “quiet” flatline | **Simulated** from the real acquisition topology |
| Duplicate onset markers | One test flash produces multiple closely spaced RZ6 markers | Route through/repair the refractory timer and repeat the test | Failure and timer remedy are **Observed** |
| Missing onset marker | Flash occurs but no marker arrives | Inspect detector, timer, PP24 route, and power; retest or abort | **Simulated** counterpart to the observed trigger path |
| Visible trigger cue | Marker path works, but the lower-right flash remains visible to the participant | Pause and remove the visual confound in simulation; rerun preflight before proceeding | Partly visible flash and suspected response bias are **Observed**; remediation is **Simulated** |
| Response occurrence/identity mismatch | Carrier-detect says a response occurred but identity is absent, stale, or mapped incorrectly | Test all buttons, inspect both response paths, correct mapping, and retest | Dual-path design is **Observed**; injected failures are **Simulated** |
| Recording-state mismatch | Stimuli run while the acquisition is not recording, or event and EEG clocks do not align | Pause, restore correct state, validate with a test event, then resume or abort | Integration topology is **Observed**; scenario is **Simulated** |

Scenarios should include ambiguous evidence. For example, widespread noise may result from reference/ground, participant muscle tension, or an electrical source. The policy should inspect before acting rather than memorize a one-signature/one-fix lookup table.

## Signal-quality judgment

The simulator needs deterministic ground truth, but the scientist-facing experience should match the user's visual judgment. Internally, synthetic scenarios may track independent quality facets:

- amplitude plausibility
- spectral plausibility within the configured acquisition band
- channel-to-channel consistency
- common-mode contamination
- clipping or dropout
- transient-artifact burden
- stability over a validation window

Readiness is a procedure-authored combination of those facets for its required montage. The exact synthetic thresholds are **demo fiction** and must be labeled as such. Optional channels can remain degraded without blocking a procedure when the environment author explicitly marks them optional.

A correct policy should:

1. notice abnormal evidence,
2. localize whether it is channel-specific or shared,
3. inspect likely causes,
4. apply the least disruptive relevant action,
5. collect a fresh validation window, and
6. proceed, invalidate data, or abort based on the new evidence.

## Success and abort conditions

### Ready or continue

A verifier may mark the apparatus ready when:

- every procedure-required channel is stable for the configured validation window;
- no required channel is flatlined or clipped;
- each test stimulus produces exactly one usable onset marker;
- response occurrence and identity agree for every required control;
- EEG, stimulus, onset-marker, and response timelines are coherent;
- acquisition is in the intended recording state; and
- every remediation was followed by a relevant retest.

### Safe abort

Abort is correct when a required channel, reference/ground path, onset marker, response mapping, or recording integration remains invalid after bounded recovery attempts. The policy must preserve observations and state a specific reason. A safe, evidence-based abort scores better than starting or continuing a scientifically invalid run.

### Reward principles

Reward verifiable behavior rather than polished explanation:

- strong reward for valid readiness or correct recovery;
- strong reward for retesting after a change;
- reward efficient evidence gathering and targeted intervention;
- reward correct invalid-interval annotation and safe abort;
- penalize starting with a failed preflight;
- penalize changing many components without inspection;
- penalize hiding, deleting, or silently accepting invalid data;
- do not reward access to hidden fault labels or a privileged quality score.

## Authenticity boundary

### Authentic core

- Human scalp EEG and the recognizable TDT acquisition topology
- Configurable montage seeded from the user's four recording sites
- 0.1–30 Hz online bandpass in the seeded profile
- Visual inspection of signal appearance and frequency content
- Real history of faulty sensors and severe noise
- Optical onset trigger, duplicate-trigger failure, and refractory timer
- Lower-right visible flash and potential experimental confound
- Custom response box and split response-detection/identity path
- Sound-shielded but electrically unshielded room

### Deliberate demo fiction

- Full-cap synthetic signal generation
- Exact signal thresholds, hidden fault parameters, and remediation outcomes
- Procedure-independent intent-level actions
- Deterministic participant artifacts and electrical sources
- Readiness lock, bounded recovery attempts, and reward weights
- Any new diagnosis not supported by the thesis or interview

This boundary lets the prototype feel true to lived apparatus work without claiming that synthetic thresholds or agent behavior are validated laboratory practice.
