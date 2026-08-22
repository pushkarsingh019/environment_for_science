# EEG scenario curriculum options

> **Status:** Approved design input. Decision 07 records the Environment
> author's choices; implementation Ticket 04 materializes the fixed curriculum.

This proposal turns the resolved
[EEG apparatus model](eeg-apparatus-model.md) into a deterministic curriculum
for evaluation and training of Policy agents. It preserves the role boundary in
[ADR 0001](adr/0001-separate-authoring-assistant-from-policy-agent.md): the
Policy agent can use every simulated apparatus action, but it cannot edit the
Environment, inspect hidden scenario state, or change a verifier.

The recommended design is a staged, full-episode EEG curriculum. It starts
with a partially solvable onset-marker preflight, adds visual trace and
frequency evidence, and ends with runtime recovery and selected compound
faults. A fixed held-out set then measures individual-fault robustness,
ambiguity handling, and generalization to combinations that don't occur in
training or development.

This proposal does not choose a portable serialization format for ticket 06.
Names in this document identify action and state semantics, not API methods or
schema fields. It also does not decide whether ticket 09 trains an EEG-only
policy, a joint policy, or separate apparatus adapters.

## Evidence boundary

This document uses the following labels to prevent synthetic curriculum rules
from being mistaken for laboratory practice.

| Label | Meaning |
|---|---|
| **Apparatus evidence** | An Observed or Confirmed fact inherited from the EEG apparatus model. |
| **Synthetic curriculum choice** | A deterministic rule, threshold, waveform, fault outcome, task split, or score created for this Environment. |
| **Backend fact** | A capability or constraint documented in the Prime Intellect research. It describes execution software, not EEG practice. |

The authentic apparatus evidence includes the following facts:

- The apparatus is configurable human scalp EEG, seeded with FC3, FC4, FT7,
  and FT8; FCz reference; and A1 ground.
- The seeded acquisition profile uses 1,017 Hz sampling, a 0.1-30 Hz online
  bandpass, and a 50 Hz notch.
- The scientist judged live quality visually from trace appearance and
  frequency content rather than from a precise readiness threshold.
- The apparatus had faulty sensors and severe noise, an optical onset-marker
  path with a duplicate-trigger failure, a refractory timer, a partly visible
  lower-right flash, and separate response-occurrence and response-identity
  paths.
- The recording room was sound-shielded but not electrically shielded.

Everything that makes these facts deterministic is a synthetic curriculum
choice. This includes exact waveforms, severity bands, validation windows,
fault-to-remediation outcomes, retry limits, readiness gates, reward weights,
and split sizes. The generator is not a validated EEG simulator, a clinical
quality-control procedure, or guidance for physical equipment.

## Curriculum options

The following options differ in scientific breadth and optimization risk.

| Option | Scope | Base-model difficulty | Main advantage | Main risk |
|---|---|---|---|---|
| A. Marker-only slice | One flash must produce exactly one marker; response preflight is optional. | Lowest | Fastest Verifiers and training smoke test | Demonstrates integration recovery, but not the central visual EEG judgment |
| **B. Staged full episode** | Configuration, EEG inspection, onset and response preflight, a short acquisition, runtime recovery, annotation, and close or abort | Adjustable | Preserves the authentic apparatus story while providing easy and hard levels | Requires more simulator and verifier work than option A |
| C. Compound-first benchmark | Full episode with ambiguous pairs and triples from the start | Highest | Strong compositional benchmark if policies can engage with it | Likely reward floor for base Gemma and weak within-group variation |

**Recommendation:** Choose option B. Keep option A as the first implementation
and curriculum level, not as the final claim. Don't start with option C.

## Recommended episode objective

The Policy agent receives a procedure-selected montage and the complete
simulated apparatus action catalog. It must:

1. Inspect the configuration and apparatus evidence.
2. Judge required EEG channels from recent traces and frequency evidence.
3. Verify one-to-one onset markers and response occurrence and identity.
4. Apply the least disruptive relevant remediation when evidence is invalid.
5. Collect fresh, relevant evidence after every state-changing remediation.
6. Start or resume only when the applicable gates pass.
7. Pause and annotate invalid runtime intervals before continuing.
8. Close a valid mock acquisition or abort with current evidence and a specific
   blocking path.

A preflight-only scenario ends after a valid arm decision or a safe abort. A
runtime scenario adds a short, deterministic mock trial block and ends after a
valid close or a safe abort. The mock block has no biological or diagnostic
meaning.

The simulator never exposes the causal fault label, the expected action, a
privileged readiness score, or the scenario's recoverability class. The Policy
agent receives only evidence that an operator could inspect in the simulated
apparatus and the recorded effects of its own actions.

## Deterministic scenario generator

### Generator inputs and products

A scenario is generated from five conceptual inputs:

1. A pinned generator revision.
2. A split namespace: training, development, or held-out.
3. An opaque blueprint identifier.
4. A nuisance seed that is unique across splits.
5. The seeded apparatus profile and selected procedure.

These inputs produce the following deterministic episode data:

- The initial apparatus and procedure state.
- The multichannel signal and event timeline.
- Fault activation times, persistence, and causal component state.
- State-dependent action effects and recovery ladders.
- Policy-visible trace, spectrum, status, and timeline evidence.
- Hidden verifier facts, including valid intervals and terminal eligibility.

The exact serialized representation remains a ticket 06 decision.

### Replay rules

The generator must satisfy all of the following rules:

- Use a logical episode clock. Wall-clock timing can't change an outcome.
- Derive baseline signals, artifacts, events, and action effects from separate,
  named pseudorandom streams. Adding one draw to a trace stream must not shift
  a later trigger event.
- Index generated values by absolute logical time rather than by tool-call
  order. Repeating an inspection can't alter the underlying signal.
- Make every remediation outcome deterministic for the scenario. A repeated
  transport retry can't apply a state transition twice.
- Record the generator revision, blueprint identifier, nuisance seed, and
  action sequence in the evaluator trace, but don't show hidden generation
  inputs to the Policy agent.
- Pin numeric dependencies and use golden or quantized visual fixtures so
  platform-level rounding can't change visible evidence or a verifier result.
- Replaying the same initial state and complete canonical action sequence must
  reproduce the same observations, state transitions, terminal result, and
  component scores.

A practical implementation can derive each named stream from a cryptographic
hash of the generator revision, split, opaque blueprint identifier, nuisance
seed, and stream name. That implementation detail doesn't define the portable
Environment contract.

### Signal construction

The simulator composes a deterministic, band-limited baseline with shared and
channel-local components. A fault adds or removes a component at a scheduled
logical time. Every observation window is then derived from the resulting
samples.

The primary evidence is the trace and its frequency representation. Derived
flatline, clipping, drift, dropout, and transient-burden indicators can appear
beside that evidence because the apparatus model permits them. They must be
computed from the displayed samples. They can't read the hidden causal state or
collapse all evidence into one quality score.

The seeded sampling and filter settings are apparatus evidence. The baseline
shape, component mixing, artifact morphology, amplitude ranges, spectral bins,
and pass thresholds are synthetic curriculum choices. Before implementation,
store those choices in a versioned generator fixture and label all generated
signals as synthetic.

### Composition axes

Blueprints compose controlled axes rather than free-form stories.

| Axis | Values used by the curriculum | Leakage control |
|---|---|---|
| Procedure role | Required channel, optional channel, reference, ground, trigger, response, or recording integration | Balance sites and roles across outcomes |
| Fault onset | Initial configuration, preflight, after readiness, during recording, or close | Don't encode onset in the prompt or identifier |
| Fault scope | Channel-local, shared across channels, event-path, response-path, or recording-wide | Cross scope with several visual nuisance seeds |
| Persistence | Transient, persistent until a relevant action, or unavailable after bounded recovery | Keep the class hidden; reveal only action effects |
| Severity | Benign variation, ambiguous, obvious, or blocking | Use overlapping visible ranges for ambiguous cases |
| Recovery depth | Observe only, one targeted action, action plus escalation, or safe abort | Keep every action visible in every episode |
| Combination | Nominal, one fault, selected taught pair, unseen pair, or unseen triple | Split by the exact causal combination, not by random row |
| Nuisance | Baseline mixture, phase, channel assignment, event time, panel order, and neutral prompt wording | Sample independently from the correct outcome |

Random composition alone can create incoherent or causally masked episodes.
Use reviewed blueprints to constrain valid combinations, and then vary only the
nuisance axes with deterministic streams.

## Fault and negative-control catalog

The following catalog covers the resolved apparatus model. The signatures and
outcomes are synthetic even when the apparatus path or historical failure is
authentic.

| Scenario family | Apparatus evidence | Synthetic visible evidence | Relevant intent and retest |
|---|---|---|---|
| Local poor contact or faulty electrode | Faulty sensors and severe noisy recordings were observed. | One required channel has large noise, drift, intermittent dropout, or implausible contrast with nearby channels. A reseat-only and a replace-after-reseat variant share initial evidence. | Compare the channel, inspect its spectrum and connection, reseat or re-gel, collect a fresh window, and replace only if the defect persists. |
| Flatline or clipping | The acquisition topology is authentic; this injected failure is not documented. | One required channel is constant, nearly constant, or rail-limited. A benign quiet trace remains dynamic and forms a negative control. | Inspect dynamics and spectrum, reconnect or correct the affected path, and retest. Don't accept silence as quality. |
| Reference or ground fault | Reference and ground roles and connections are authentic. | Similar contamination appears across many channels, including otherwise independent sites. | Compare channels, inspect reference and ground, reconnect the implicated path, and retest before touching every electrode. |
| Participant blink, movement, or muscle activity | Movement minimization was part of the lived procedure. | Time-linked slow transients or dense higher-frequency activity affect relevant channel groups. Some episodes clear after a stable wait; others recur until an instruction. | Pause when recording, give the relevant simulated instruction, wait for a fresh stable window, annotate affected data, and then continue or abort. |
| Environmental electrical contamination | The room was not electrically shielded, and severe noise was observed. | Persistent rhythmic or broadband shared contamination changes with an inspectable simulated power or cable source. | Inspect common sources, isolate the selected source or reroute the simulated cable, and retest. |
| Duplicate onset markers | The duplicate-trigger failure and refractory-timer remedy were observed. | One test flash produces multiple closely spaced onset markers. | Inspect the trigger timeline, enable or repair the refractory route, and repeat the flash test. |
| Missing onset marker | The optical detector, timer, PP24, and RZ6 path is authentic; the injected missing event is synthetic. | A test flash occurs without a corresponding marker, or one route component reports no event. | Inspect the trigger path, repair or reconnect the implicated simulated component, and repeat the flash test. |
| Participant-visible onset cue | The partly visible lower-right flash and possible response bias were observed. | Marker timing is correct, but the participant-view panel shows a visible cue. | Pause, correct the simulated cue visibility, and repeat onset and response preflight. |
| Response occurrence and identity mismatch | The fast occurrence line and later identity query are authentic. | A response is registered, but identity is absent, stale, or mapped to the wrong control. | Test every required control, inspect both response paths, correct the mapping or handshake, and retest all required controls. |
| Recording or timeline mismatch | The recording and integration topology is authentic. | Stimuli occur while recording is off, or EEG, stimulus, marker, and response timelines don't align. | Pause, restore or restart the relevant integration, run a test event, and then resume or abort. |
| Acquisition configuration mismatch | The montage and seeded acquisition profile are authentic. | A required site, reference, ground, sample setting, filter, or notch differs from the selected procedure. | Inspect and correct the acquisition configuration, and then repeat every invalidated preflight. |
| Nominal or benign variation | Visual comparative judgment is Confirmed. The sources don't define a benign envelope or optional-channel rule. | All required evidence is coherent, or only an explicitly optional channel is degraded. A brief transient can clear before the validation window. | Avoid unnecessary remediation. Validate the required montage and proceed. |

## Ambiguous cases

Ambiguity must require additional evidence, not guessing. Each pair below uses
overlapping initial evidence and a deterministic observation or intervention
that separates the causes.

| Initial evidence | Plausible causes | Disambiguating behavior |
|---|---|---|
| Widespread noisy traces | Reference or ground fault, participant muscle activity, or environmental contamination | Compare time and frequency structure, inspect reference and ground, inspect the simulated participant state and common electrical sources, and change only the best-supported path. |
| A very quiet channel | Stable low-amplitude signal or flatline | Inspect short-term dynamics, spectrum, dropout history, and neighbor relationships before acting. |
| One unstable channel | Poor contact or a faulty electrode | Reseat or re-gel and collect a fresh window. Replace only if the defect persists. |
| A flash without a usable marker | Trigger-path failure or recording integration mismatch | Inspect the component and event timelines, repair the implicated path, and repeat one test flash. |
| Response occurrence without correct identity | Mapping error or stale identity handshake | Test the complete required control set and compare occurrence and queried identity events. |
| A noisy cap site | Blocking required channel or irrelevant optional channel | Inspect the procedure's montage roles before deciding whether remediation is required. |
| A short shared transient | Participant artifact or a persistent apparatus fault | Wait for a defined fresh window and compare the history. Don't change hardware for a transient that clears. |

No fault-specific text, color, filename, action ordering, or panel position can
identify the answer. A summary indicator can describe a measured feature, such
as clipping, but it can't name a cause.

## Compound-fault plan

Every causal primitive appears by itself during training. Training includes
only five pair families so that the policy learns to recheck independent gates
without seeing the held-out combinations:

1. Local contact fault plus duplicate onset markers.
2. Flatline or clipping plus a participant-visible onset cue.
3. Participant artifact plus a response mapping mismatch.
4. Environmental contamination plus a recording-state mismatch.
5. Reference or ground contamination plus an acquisition-configuration
   mismatch.

Development can use new nuisance seeds, channel assignments, onset times, and
severity values for these five pair families. It must not introduce a held-out
pair.

The held-out set reserves the following eight pair families:

1. Local contact fault plus a response mismatch.
2. Flatline or clipping plus duplicate onset markers.
3. Reference or ground contamination plus a visible onset cue.
4. Participant artifact plus a missing onset marker.
5. Environmental contamination plus an acquisition-configuration mismatch.
6. Duplicate onset markers plus a recording-state mismatch.
7. A visible onset cue plus a response mismatch.
8. An acquisition-configuration mismatch plus a missing onset marker.

It also reserves four triple families:

1. Local contact fault, duplicate onset markers, and a recording-state
   mismatch.
2. Reference or ground contamination, a missing onset marker, and a response
   mismatch.
3. Participant artifact, a visible onset cue, and an
   acquisition-configuration mismatch.
4. Environmental contamination, flatline or clipping, and a response
   mismatch.

The generator must verify that each compound has at least one evidence-valid
recovery order and that one fault doesn't make another impossible to observe.
The verifier doesn't require one exact order when several orders are safe.

## Lifecycle and state transitions

The following state names are conceptual. Ticket 06 can encode them without
preserving these labels.

```text
Procedure loaded -> Configure -> EEG, onset, and response preflight gates
                                      |                 ^
                               failed gate              | fresh retest
                                      v                 |
                                   Recovery ------------+
                                      |
                         all applicable gates pass
                                      v
                                    Ready
                                      |
                                      v
                                  Recording
                                      |
                         runtime evidence becomes invalid
                                      |
                                      v
                         Pause -> annotate -> recovery -> retest
                                      |                       |
                                      +-----------------------+
                                                       |
                                                       v
                                                   Recording
                                                       |
                                                       v
                                                   Valid close

Any nonterminal state -> evidence-backed abort
Budget exhaustion       -> incomplete failure
```

The EEG, onset, and response checks form a gate set. A policy can perform
independent checks in any order, although configuration changes can invalidate
several prior results.

The simulator applies these transition rules:

| Current condition or action | Deterministic transition rule |
|---|---|
| Procedure load | Select the required montage and profile. The Policy agent can inspect but not alter the procedure definition. |
| Configuration change | Invalidate every preflight result that depends on the changed setting. |
| Evidence inspection | Return a view over the current logical window without changing causal state. A wait or explicit retest advances the logical evidence window. |
| State-changing remediation | Apply the scenario-defined effect and mark the affected gate as needing fresh evidence. |
| Preflight | Record the flash, response, or EEG validation attempt and its visible results. A failed result can't become ready without a relevant change or fresh stable window. |
| Start attempt | Enter recording only if every applicable hard gate passes. A blocked attempt remains in the trace and receives an unsafe-attempt penalty. |
| Scheduled runtime fault | Change only the causal apparatus state at the pinned logical event. Don't announce the fault label. |
| Continue while invalid | Advance the invalid interval and record an unsafe-continuation event. |
| Pause | Stop mock trial progression while preserving trace and event history. Evidence collection and remediation remain available. |
| Invalid-interval annotation | Attach a reason category and recent evidence references to a time range. Don't accept a range outside the episode. |
| Resume | Require a relevant fresh retest and acknowledgement of every blocking invalid interval. |
| Close | Succeed only after the planned block finishes, all applicable gates pass, and no invalid interval remains unacknowledged. |
| Abort | Always preserve the trace. Full safe-abort credit depends on the evidence and recovery conditions defined below. |
| Budget exhaustion | End as incomplete. It isn't equivalent to an explicit safe abort. |

All simulated apparatus actions are available to the Policy agent in every
scenario. State preconditions can reject an action, but there is no approval or
permissions framework. Keeping the action catalog constant prevents action
availability from leaking the fault family.

## Policy-visible observations

The Environment must make the following evidence available. Ticket 06 decides
whether each view is transported as pixels, sampled values, structured
summaries, or a consistent combination. That transport choice must preserve the
same scientific content across compared models.

| Observation | Required content | Must not contain |
|---|---|---|
| Procedure card | Required and optional electrodes, reference, ground, seeded acquisition profile, and task stage | Hidden fault, expected action, or outcome label |
| Apparatus overview | Connection, power, recording, trigger-route, response-route, and integration states that the simulated operator can inspect | Scenario blueprint or recoverability class |
| Stimulus and participant context | Lower-right trigger-patch visibility, recent simulated instructions, observable blink or movement events, and simulated participant reports of tension | A hidden participant-artifact state or causal diagnosis |
| Multichannel trace view | All available channels, required-role markers, timestamps, recent history, and comparable scaling | A hidden-quality overlay or auto-diagnosis |
| Focused trace comparison | Selected channels, neighbor or group comparison, and the same underlying samples as the overview | Newly sampled evidence caused by inspection order |
| Frequency view | Spectrum or band summary for a selected recent window, with enough resolution to compare local and shared patterns | A causal fault name |
| Signal-feature indicators | Flatline, clipping, drift, dropout, and transient measurements derived from the visible window | A global pass score sourced from hidden state |
| Onset timeline | Test-flash times, marker times and counts, route status, and refractory-route status | The intended repair |
| Response timeline | Simulated press, occurrence event, queried identity, mapping, and stale-state evidence | The correct answer as a label |
| Acquisition timeline | Recording state, stimuli, markers, responses, pauses, and unacknowledged ranges | Hidden valid-interval truth beyond observable events |
| Intervention log | Accepted and rejected actions, evidence windows, annotations, and retests | Verifier component scores before the terminal action |

The scientist-facing view must keep raw traces and frequency evidence primary.
A derived feature can support inspection, but the policy can't complete an EEG
scenario by reading one scalar readiness field.

## Portable intent-level actions

The following action groups define behavior, not an API. Each action returns its
observable effect and a stable evidence reference. Vendor names, electrical
parameters, and physical calibration controls stay outside the portable
semantics.

| Intent group | Semantic actions |
|---|---|
| Inspect EEG | View all traces; focus on one channel; compare a group; view frequency evidence for a recent window; inspect quality history. |
| Inspect context | View observable simulated participant events and the stimulus display, including the lower-right trigger patch. |
| Inspect configuration | View the montage, reference, ground, sample setting, filters, notch, connections, recording state, and integration state. |
| Test integrations | Run an EEG validation window; present one test flash; test one or all response controls; inspect aligned timelines. |
| Remediate electrodes | Reseat or re-gel a selected electrode; replace a selected faulty electrode; reconnect reference or ground. |
| Remediate participant artifacts | Ask the simulated participant to relax, remain still, or pause blinking; wait for a fresh stable window. |
| Remediate shared noise | Inspect a candidate common source; isolate a simulated electrical source; reroute a simulated cable. |
| Remediate onset markers | Enable or repair the refractory route; reconnect or repair the simulated detector or event route; replace a simulated battery; correct cue visibility. |
| Remediate responses | Correct a button mapping; refresh or repair the response handshake; retest every required control. |
| Remediate integration | Correct the acquisition configuration; restart a failed software or instrument integration while paused. |
| Control acquisition | Start, pause, continue, resume, or close the mock acquisition. |
| Preserve validity | Mark an interval invalid with a reason and evidence references; save the trace and intervention log. |
| Stop safely | Abort with the blocking apparatus path and current evidence references. |

A remediation action must target a named simulated component or role. Broad
commands such as "fix EEG," vendor-specific commands, free-form shell access,
and direct edits to generated state aren't portable actions.

## Deterministic verifiers and reward

### Verifier principles

Verifiers score state and behavior, not writing style. They use the hidden state
only to establish causal truth and valid terminal conditions. They don't reward
the Policy agent for stating a hidden fault label.

The verifier checks the following facts directly:

- Whether required gates actually pass at start, resume, and close.
- Whether a runtime pause occurs before additional invalid trials.
- Whether an intervention targets a path supported by prior visible evidence.
- Whether each state-changing intervention is followed by a relevant fresh
  retest.
- Whether invalid intervals are covered by annotations and preserved in the
  final trace.
- Whether an abort cites recent evidence for the observable blocking path.
- Whether accepted state transitions and artifacts replay deterministically.

Don't use a language-model judge. A free-text explanation can remain in the
trace for scientists, but reward uses state, action categories, evidence
references, and timestamps.

### Recommended reward formula

Use a bounded continuous reward so partially correct rollouts retain training
signal:

```text
reward = clip(
    0.45 * terminal_correctness
  + 0.20 * safety_compliance
  + 0.15 * fresh_validation
  + 0.10 * targeted_intervention
  + 0.05 * data_stewardship
  + 0.05 * efficiency
  - unsafe_penalties,
  0,
  1)
```

Each positive component ranges from `0` to `1`:

| Component | Full credit |
|---|---|
| Terminal correctness | Close a genuinely valid episode, or make an eligible safe abort in an unavailable scenario. |
| Safety compliance | Never attempt to start, resume, or continue through a failed blocking gate; pause promptly after runtime evidence becomes invalid. |
| Fresh validation | Follow every state-changing remediation with a relevant new window or preflight before proceeding. |
| Targeted intervention | Inspect relevant evidence before changing state and remediate only an evidence-supported apparatus path. |
| Data stewardship | Annotate every invalid runtime interval and preserve the observation and intervention trace at close or abort. |
| Efficiency | Complete essential checks and recovery within the blueprint's shortest evidence-valid path plus two actions. Legitimate disambiguation is part of that path. |

Apply the following event penalties in addition to component loss:

- Subtract `0.35` for the first invalid start, resume, or continuation attempt
  and `0.15` for each later attempt, capped at `0.65`.
- Subtract `0.20` when the agent closes or aborts with an observed invalid
  interval that it didn't annotate.
- Subtract `0.10` when the agent changes three unrelated components without an
  intervening relevant retest.
- Subtract `0.05` for repeated state-changing actions that have no new evidence
  or effect, capped at `0.15`.

The numeric weights and action slack are synthetic curriculum choices. Freeze
and hash them before held-out evaluation. Development results can tune them
only before that freeze.

### Safe-abort scoring

A correct abort is a successful episode terminal, not a consolation prize,
when the simulated required path is genuinely unavailable. Full safe-abort
eligibility requires all of the following observable behavior:

1. The newest relevant evidence still shows a blocking required path.
2. The Policy agent completes the available targeted recovery ladder, with a
   fresh retest after each step, or observes that the simulated replacement or
   integration is unavailable.
3. The abort identifies the blocking apparatus path and references current
   evidence. It doesn't need to guess the hidden fault label.
4. The agent annotates any invalid runtime interval and preserves the trace.

Prior invalid start, resume, or continuation attempts don't erase a correct
terminal decision. They reduce the safety component and apply event penalties,
so an unsafe route to the correct abort can't receive a perfect total reward.

Use the following terminal-credit schedule:

| Abort situation | Terminal-correctness value | Interpretation |
|---|---:|---|
| Hidden scenario is unavailable and the four eligibility conditions pass | `1.00` | Equivalent terminal credit to valid recovery and close |
| Fault is recoverable, but the agent aborts after relevant inspection and at least one failed targeted attempt | `0.25` | Safe but scientifically inefficient; other components can still give partial credit |
| Blocking evidence exists, but the agent aborts before a relevant recovery and retest | `0.10` | Cautious but unsupported early stop |
| The apparatus is valid, or only an optional channel is degraded | `0.00` | Unnecessary abort |
| Episode ends by budget exhaustion without an explicit abort | `0.00` | Incomplete failure, not safe abort |

This schedule makes an evidence-backed abort better than unsafe continuation
while preserving an incentive to recover a recoverable apparatus. Report safe
abort separately so aggregate reward can't hide over-aborting.

## Diagnostic metrics

Report reward and the following metrics independently. Break every outcome down
by fault family, lifecycle onset, required or optional role, ambiguity class,
combination order, and split stratum.

| Metric | Definition |
|---|---|
| Exact terminal accuracy | Fraction of episodes ending in valid close or eligible safe abort, as appropriate to scenario truth |
| Valid-close precision | Fraction of close decisions for which every required gate and annotation condition passes |
| Safe-abort precision | Fraction of aborts that are fully eligible unavailable-scenario aborts |
| Safe-abort recall | Fraction of unavailable scenarios that end in a fully eligible abort |
| Unnecessary-abort rate | Fraction of nominal or recoverable scenarios that end in abort |
| Invalid start or resume rate | Fraction of episodes with at least one blocked or invalid start or resume attempt |
| Invalid-continuation rate | Fraction of runtime faults followed by another mock trial before pause |
| Pause latency | Number of logical events between first policy-visible invalid evidence and pause |
| First-intervention relevance | Fraction of first state-changing remediations that target a path supported by prior evidence |
| Recovery success | Fraction of recoverable scenarios returned to valid state and completed |
| Retest coverage | Fraction of state-changing remediations followed by a relevant fresh retest before proceed, resume, close, or abort |
| Trace-and-frequency inspection rate | Fraction of EEG quality decisions preceded by both time-domain and frequency evidence |
| Annotation coverage | Fraction of verifier-known invalid runtime duration covered by a policy annotation |
| Annotation overreach | Valid runtime duration incorrectly marked invalid |
| Optional-channel over-intervention | Fraction of optional-only degradation scenarios in which the Policy agent changes an unrelated required path or aborts |
| Excess intervention count | State-changing actions beyond the shortest evidence-valid path |
| Actions to correct terminal | Accepted actions before a valid close or eligible abort; report median and distribution |
| Combination generalization gap | Exact terminal accuracy on held-out individual faults minus accuracy on held-out unseen combinations; lower is better |
| Replay conformance | Fraction of traces that reproduce identical observations, transitions, component scores, and terminal state |
| Harness or adapter error rate | Protocol, schema, timeout, and tool-execution failures, reported separately from scientific task failures |

Turns, tokens, latency, and cost are useful efficiency diagnostics, but they
aren't substitutes for success and safety. Ticket 11 can choose rollout counts,
uncertainty intervals, and model-winning thresholds.

## Training, development, and held-out split

### Recommended size and composition

Use a finite, versioned split for the first claim. The generator can create
more training data later, but no generated row can cross a frozen split
boundary.

| Split | Blueprint instances | Composition | Use |
|---|---:|---|---|
| Training | 96 | 8 nominal or benign; 44 individual faults, with 4 per fault family; 24 ambiguous cases; 20 instances from the five taught pair families | Optimization only |
| Development | 32 | 4 nominal or benign; 12 individual faults; 8 ambiguous cases; 8 new variants of taught pairs | Reward, difficulty, and curriculum tuning; no gradient updates |
| Held-out | 64 | 8 nominal or negative controls; 16 individual faults; 16 ambiguous or benign mimics; 16 unseen pairs; 8 unseen triples | One frozen final evaluation after conformance checks |

Apply the following cross-cutting quotas within those totals. The rows can
overlap; they don't add blueprint instances.

| Cross-cutting case | Training | Development | Held-out |
|---|---:|---:|---:|
| Required path remains unavailable after its evidence-valid recovery ladder | 12 | 4 | 12 |
| Fault activates only after a valid start | 24 | 8 | 16 |
| Optional-only degradation or a benign transient | 4 | 2 | 8 |
| Reserved signal nuisance family | 0 | 0 | 32 |

Distribute unavailable cases across EEG, onset, response, and recording paths
rather than associating abort with one fault family. A nominal or optional-only
case is never unavailable. The remaining blocking cases must have at least one
deterministic recovery path.

An instance is a reviewed blueprint plus one nuisance seed. Don't create this
split by randomly dividing a flat table. Allocate causal families first, then
assign unique nuisance seeds.

Every fault primitive appears individually in all three splits. Therefore,
held-out pairs and triples test composition of learned evidence and recovery behaviors,
not recognition of a completely unseen fault. The held-out individual and
ambiguity rows test whether gains survive new nuisance values without requiring
composition.

Stratify half of each held-out category across familiar signal-construction
families with unseen seeds and half across a reserved nuisance family. The
reserved family can change baseline mixtures, phase, transient shape, panel
order, and event offsets, but it can't change the causal meaning of visible
evidence. Report familiar-nuisance and reserved-nuisance results separately so
a rendering shift isn't confused with a reasoning failure.

### Split and leakage controls

Apply all of the following controls:

- Use opaque run identifiers. Don't encode the split, fault, expected action,
  recoverability, or severity in task IDs, prompts, filenames, evidence IDs,
  colors, or panel order.
- Keep the complete action catalog and action descriptions identical across all
  scenarios and splits.
- Use one canonical task objective across splits. Vary only neutral wording that
  is independently balanced against the outcome.
- Assign channel sites, required or optional roles, baseline amplitudes, event
  times, and visual nuisance values independently of the correct terminal.
- Keep every held-out pair and triple absent from training examples,
  development examples, demonstrations, reward tests, prompt examples, and
  authored troubleshooting text shown to the Policy agent.
- Don't put this design document, the split manifest, generator source,
  generator seeds, hidden state, verifier source, verifier diagnostics, or
  component rewards in the Policy agent's context or tool results. Preserve
  run metadata only in the evaluator trace.
- Don't expose a global quality or readiness score. Compute every visible
  feature from the samples or event history that the Policy agent can inspect.
- Freeze the generator revision, split manifest, Environment package, action
  semantics, prompt, sampling profile, budgets, reward code, and metric code
  before opening held-out evaluation.
- Hash and archive the split manifest and scorer. Don't replace failed held-out
  rows, tune on held-out traces, or report only successful rollouts.
- Keep canary and adapter-conformance tasks outside all three scientific splits.
- Separate protocol, provider, and tool errors from scientific failures.
- Use identical scenario seeds and canonical observations for compared models,
  while acknowledging that provider serialization and tokenization can differ.
- Keep base and trained Gemma serving, rendering, sampling, task order, and
  hardware constant. Change only the trained weights or adapter for the
  within-family comparison.

These controls implement the evaluation boundary described in
[Frontier model evaluation research](research-frontier-model-evaluation.md)
without choosing ticket 11's models or acceptance threshold.

## Base-difficulty ramp

A measurable training run needs nonzero baseline success, remaining headroom,
and reward variation within a rollout group. Use the following ramp rather than
sampling all scenarios uniformly from the start.

| Level | Scenario content | New required behavior |
|---|---|---|
| 0. Nominal orientation | Valid configuration, EEG, marker, and response paths | Inspect essential evidence and proceed without unnecessary changes |
| 1. Observable integration fault | Duplicate or missing marker, or one response mismatch | Localize from an event timeline, apply one intent-level fix, and retest |
| 2. Obvious individual EEG fault | Local noise, flatline or clipping, participant transient, reference or ground fault, or environmental contamination | Use traces and frequency evidence, target one path, and collect a fresh window |
| 3. Ambiguity and negative controls | Quiet-versus-flatline, contact-versus-faulty-electrode, widespread-noise alternatives, transient recovery, and optional-channel degradation | Gather discriminating evidence and avoid broad or unnecessary remediation |
| 4. Runtime validity | One learned fault activates after a valid start | Pause, annotate, remediate, retest, resume, and close |
| 5. Taught compounds | One of the five training pair families | Preserve gate ordering and recheck both affected paths |
| Held-out challenge | Reserved pairs and triples | Compose individually learned behaviors without a taught combination |

Implement level 1 first as the engineering and training smoke test. It provides
a short tool loop and deterministic reward while level 2 is being built. The
final demonstration must include levels 2-5 so the claim includes visual EEG
evidence.

Before training, run base Gemma on the development calibration rows. We
recommend proceeding when exact terminal accuracy is between `20%` and `70%`
overall, and
when levels 1 and 2 each have both successes and failures. If the base model is
below that range, reduce simultaneous ambiguity or add clearer derived evidence
that remains trace-backed. If it is above that range, introduce runtime onset
and taught pairs earlier. Don't alter held-out rows after the freeze.

During curriculum training:

1. Begin with levels 0-2 so useful rollouts are possible.
2. Add level 3 after recent development evaluations reach `70%` exact terminal
   accuracy with no more than `5%` invalid starts or resumes.
3. Add levels 4 and 5 under the same gate.
4. Retain at least `25%` sampling from earlier levels to detect regression and
   avoid forgetting preflight behavior.
5. Use groups of at least eight rollouts per prompt, as recommended by the
   inspected Prime training guidance, and verify that reward varies within
   groups.

The target ranges and advancement gates are synthetic optimization choices,
not expected properties of Gemma or EEG practice. They make improvement
plausible but don't guarantee it. If baseline calibration still produces a
floor or ceiling, revise only the training and development difficulty before
freezing the held-out evaluation.

## Prime Intellect execution mapping

The recommended semantics fit the researched Verifiers v1 boundary without
making Verifiers the source of truth:

| Curriculum concept | Verifiers v1 target |
|---|---|
| Generated scenario instance | `TaskData` and `Task` |
| Isolated episode state | Typed `vf.State` |
| Intent-level apparatus actions | Stateful Model Context Protocol (MCP) `Toolset` |
| Policy tool loop | The built-in null harness for the first probe |
| Reward components | Separate deterministic `@vf.reward` functions |
| Diagnostic measures | Separate `@vf.metric` functions |
| Complete episode record | `Trace` |
| Training and held-out sources | Distinct taskset splits in self-managed prime-rl |

Prime's guidance recommends avoiding tasks that every baseline rollout fails or
solves and preserving reward variation within groups. It also recommends groups
of at least eight rollouts. The staged ramp, partial component reward, and
calibration gate directly address those constraints. For the supporting backend
research, see
[Prime Intellect Verifiers and prime-rl fit](research-prime-intellect-verifiers.md).

The portable Environment specification, its ownership, schema, validation, and
generated-artifact boundaries remain ticket 06 decisions. Whether prime-rl
samples only this EEG taskset or combines it with another apparatus remains a
ticket 09 decision.

## Acceptance checks before held-out evaluation

The implementation is ready to freeze only when all of the following checks
pass:

- The same scenario and action sequence replay to identical observations,
  transitions, reward components, and terminal state.
- Every individual fault has at least one evidence-valid recovery trace and
  every unavailable variant has an evidence-valid safe-abort trace.
- Every nominal and optional-channel negative control has a valid no-remediation
  trace.
- Every compound blueprint exposes both faults and accepts every safe recovery
  order.
- Visible indicators recompute from displayed trace or event data and never
  inspect a hidden fault label.
- All actions are present in every scenario, and rejected actions return a
  deterministic state reason.
- Reward unit fixtures cover valid close, unsafe start, missing retest,
  scattershot remediation, correct annotation, full safe abort, premature
  abort, unnecessary abort, and budget exhaustion.
- Training, development, and held-out manifests have disjoint blueprint and
  nuisance identifiers. Reserved combinations occur only in held-out.
- A Verifiers v1 tool-using canary completes through the null harness, and
  adapter errors are reported outside scientific scores.
- Base calibration shows both success and failure before reinforcement learning
  begins.

## User decisions

Only the following product-value choices need the Environment author's input.
The remaining details are implementation and calibration choices that can
follow the recommendations above.

| Decision | Options | Recommendation |
|---|---|---|
| **Demonstration scope** | A marker-only final task, the staged full EEG episode, or a compound-first benchmark | Choose the staged full EEG episode. Keep marker-only as level 1 and the first engineering probe. |
| **Status of a correct safe abort** | Give it lower terminal credit than recovery, or equal terminal credit when a required path is genuinely unavailable | Give an eligible unavailable-scenario abort equal terminal credit. Report abort precision and recall so this choice can't reward blanket caution. |
| **Strength of the generalization claim** | Evaluate only new seeds of individual faults, or reserve exact pairs and triples under the 96/32/64 split | Reserve the listed pairs and triples. Claim only within-EEG compositional generalization, and report individual, ambiguous, pair, and triple results separately. |

These choices were approved in Decision 07. Ticket 04 implements the fixed
curriculum and split controls; this document remains the detailed rationale.
