# Science Environment Studio — executable prototype specification

Status: ready for implementation
Source: [`product-decision-map.md`](product-decision-map.md) and the resolved tickets in
[`decisions/`](decisions/)

## Problem Statement

Experimental scientists can describe their Apparatus, Procedure, observations, and recovery judgment, but existing agent-training systems require code, framework-specific configuration, and ML terminology. The user needs a working prototype—not another mockup or plan—that lets a non-programming Environment author build and understand simulated EEG and mesoscope Environments, run isolated Policy agents inside them, evaluate multiple models fairly, train Gemma with verifier-driven reinforcement learning, and see whether the trained model improves on held-out EEG scenarios.

The prototype must preserve scientific recognizability without pretending to validate research, medicine, laser operation, or physical Apparatus control. It must own a portable Environment representation rather than making Verifiers or prime-rl the product model.

## Solution

Provide one quiet, visualization-first scientist console backed by one product-owned deterministic Environment runtime.

The Environment author selects EEG or mesoscope, edits a reversible Environment draft visually or conversationally, previews its Apparatus and Procedure, and freezes it into a run. An isolated Policy agent then receives all permitted simulated-Apparatus actions but cannot edit the Environment, inspect hidden scenario truth, or alter verifiers. Every observation, action, state transition, and verifier result becomes a canonical replayable trace.

EEG is the authentic training example. It presents configurable scalp-EEG montages, live-looking traces and frequency evidence, onset markers, responses, staged faults, recovery, and justified aborts. Mesoscope is a sealed synthetic four-region handoff that demonstrates the same platform contract without exposing operational optics controls.

The same Environment Bundle and runtime compile into Verifiers v1 artifacts for local Gemma, GPT, and Gemini evaluation. A self-managed prime-rl run trains an EEG-specific Gemma E4B LoRA adapter on the two RTX PRO 6000 workstations, saves and reloads it, and compares it with base Gemma on a fixed held-out split. GPT and Gemini are reference results under the same canonical scenarios and tools.

## User Stories

1. As an Environment author, I want to open one scientist console, so that I do not need to navigate a marketing-style application.
2. As an Environment author, I want scientific visualization to dominate the workspace, so that the Apparatus state is immediately legible.
3. As an Environment author, I want setup details hidden until requested, so that the console remains calm and usable.
4. As an Environment author, I want to select EEG or mesoscope from a compact Environment list, so that both examples use one interaction language.
5. As an Environment author, I want other Apparatus types shown only as unavailable catalog entries, so that the platform direction is visible without fake implementations.
6. As an Environment author, I want to describe a change conversationally, so that I do not need to edit code or schemas.
7. As an Environment author, I want common conversational changes to update the visible draft immediately, so that I can verify what the Authoring assistant understood.
8. As an Environment author, I want every draft change to be reversible, so that experimentation is low risk.
9. As an Environment author, I want to restore the seeded Environment, so that I can always return to a known state.
10. As an Environment author, I want to import a local descriptive note into the draft, so that existing lab knowledge can seed authoring without controlling hardware.
11. As an Environment author, I want imported content clearly labeled as unverified descriptive input, so that it is not mistaken for operational truth.
12. As an Environment author, I want to see which changes came from the Authoring assistant, so that authorship is understandable.
13. As an Environment author, I want to freeze a draft before a run, so that evaluation cannot silently change beneath the Policy agent.
14. As an Environment author, I want ordinary start, pause, stop, reset, and replay controls, so that I do not need RL terminology.
15. As an Environment author, I want the console to distinguish Edit and Run states, so that draft changes and scored actions cannot be confused.
16. As an Environment author, I want the Authoring assistant absent from a scored run, so that it cannot help the Policy agent.
17. As an Environment author, I want the Policy agent’s model identity visible in the run trace, so that results remain attributable.
18. As an Environment author, I want the Policy agent to receive all simulated-Apparatus actions, so that the benchmark tests decision quality rather than arbitrary permissions.
19. As an Environment author, I want hidden scenario truth concealed from the Policy agent, so that diagnosis must follow observable evidence.
20. As an Environment author, I want verifier results written in scientist-readable language, so that I can understand why a run passed or failed.
21. As an Environment author, I want complete observation, action, transition, and verifier traces, so that I can audit a result.
22. As an Environment author, I want traces to replay deterministically, so that a demonstration can be repeated exactly.
23. As an Environment author, I want a run reset to restore its original scenario, so that repeated comparisons are fair.
24. As an EEG scientist, I want the Apparatus represented as a configurable whole-cap scalp-EEG chain, so that the prototype is not limited to four electrodes.
25. As an EEG scientist, I want each Procedure to select its Montage, so that Apparatus capability and experimental selection remain distinct.
26. As an EEG scientist, I want the seed Montage to include FC3, FC4, FT7, FT8, FCz reference, and A1 ground, so that the initial example reflects the source apparatus.
27. As an EEG scientist, I want to add or remove Montage sites conversationally, so that I can explore different procedures without code.
28. As an EEG scientist, I want the seeded 1017 Hz sampling, 0.1–30 Hz bandpass, and 50 Hz notch visible on demand, so that authentic acquisition details are preserved without clutter.
29. As an EEG scientist, I want animated multichannel traces, so that signal quality is judged visually rather than through a fabricated universal threshold.
30. As an EEG scientist, I want frequency evidence alongside traces when requested, so that shared and channel-local noise can be distinguished.
31. As an EEG scientist, I want a compact scalp Montage visualization, so that channel location, reference, and ground are understandable spatially.
32. As an EEG scientist, I want to simulate a faulty, noisy, flat, or clipped electrode, so that the Policy agent must diagnose authentic signal failures.
33. As an EEG scientist, I want environmental and reference-related noise scenarios, so that the agent cannot solve every failure by replacing one electrode.
34. As an EEG scientist, I want the lower-right optical trigger represented as an onset route, so that marker behavior matches the source Apparatus.
35. As an EEG scientist, I want duplicate and missing onset-marker scenarios, so that the agent must inspect and retest timing evidence.
36. As an EEG scientist, I want a visible-trigger confound scenario, so that a technically recorded marker cannot automatically count as valid evidence.
37. As an EEG scientist, I want response occurrence and identity tested separately, so that partial response-box failures are observable.
38. As an EEG scientist, I want recording-state and timeline mismatches represented, so that the agent must reason about the newest valid evidence.
39. As an EEG scientist, I want every state-changing repair to invalidate stale evidence, so that a pass requires a fresh post-change observation.
40. As an EEG scientist, I want a correct repair followed by a targeted retest, so that lucky terminal actions do not receive full credit.
41. As an EEG scientist, I want a justified safe abort to receive terminal credit when recovery is genuinely unavailable, so that the benchmark does not reward unsafe persistence.
42. As an EEG scientist, I want blanket abort behavior measured and penalized, so that caution cannot game the benchmark.
43. As an EEG scientist, I want the curriculum to begin with one-flash/one-marker scenarios, so that the first engineering slice is tight and debuggable.
44. As an EEG scientist, I want the curriculum to progress through configuration, signal inspection, onset and response preflight, acquisition, recovery, annotation, and close or abort, so that the trained behavior covers a full episode.
45. As an evaluator, I want deterministic scenario generation from recorded seeds and manifests, so that model comparisons use identical scientific conditions.
46. As an evaluator, I want 96 training, 32 development, and 64 held-out EEG manifests, so that data roles are explicit.
47. As an evaluator, I want blueprint and nuisance identifiers disjoint across splits, so that scenario leakage is detectable.
48. As an evaluator, I want exact fault pairs and triples reserved for held-out evaluation, so that improvement can support a within-EEG compositional-generalization claim.
49. As an evaluator, I want individual, ambiguous, pair, and triple results reported separately, so that aggregate scores cannot hide brittle behavior.
50. As a mesoscope user, I want every image and state clearly labeled synthetic and sealed, so that the prototype cannot be mistaken for operating guidance.
51. As a mesoscope user, I want a visual four-region handoff showing R1–R4 and Z-A/Z-B, so that the scenario is spatially understandable.
52. As a mesoscope user, I want immutable profile, plan, and safety-gate states visible but not editable, so that operational optics are never exposed.
53. As a mesoscope user, I want synthetic tiles, event records, motion rows, and package checksums visualized, so that handoff completeness can be inspected.
54. As a mesoscope user, I want duplicate, missing, mismatched, and incomplete package scenarios, so that visual completeness alone cannot pass verification.
55. As a mesoscope user, I want the terminal success wording to be exactly “MOCK PACKAGE VERIFIED,” so that synthetic success is unambiguous.
56. As a mesoscope user, I want incorrect packages quarantined rather than repaired through optics controls, so that the safety boundary remains sealed.
57. As an evaluator, I want EEG and mesoscope to share the same Environment envelope, run lifecycle, trace format, and verifier result shape, so that platform generality is real.
58. As an evaluator, I want apparatus-specific state and visualization to remain inside each Environment module, so that a generic contract does not erase scientific meaning.
59. As a developer, I want authored Environment Bundles to be vendor-neutral, so that Prime Intellect is an adapter rather than the product model.
60. As a developer, I want unknown contract major versions rejected, so that incompatible semantics fail loudly.
61. As a developer, I want backward-compatible minor contract additions accepted, so that bundles can evolve safely.
62. As a developer, I want action and observation payloads validated before execution, so that malformed model calls cannot corrupt run state.
63. As a developer, I want one product runtime to own state transitions and traces, so that UI and Verifiers behavior cannot drift.
64. As a developer, I want generated Verifiers and prime-rl artifacts to be disposable, so that they can always be rebuilt from the Environment Bundle.
65. As a developer, I want canonical traces stored independently of provider response formats, so that evaluations remain comparable.
66. As an evaluator, I want GPT, Gemini, base Gemma, and trained Gemma to receive the same scenarios, tools, hidden state, budgets, and deterministic scoring, so that the comparison is fair.
67. As an evaluator, I want provider-native reasoning and tool-call lineage preserved by thin adapters, so that a common compatibility format does not handicap one model.
68. As an evaluator, I want OpenAI evaluation to use the recorded Responses route and Gemini evaluation to use the recorded Interactions route, so that multi-turn tool state is preserved.
69. As an evaluator, I want local Gemma to use the same canonical runner, so that local and hosted traces have the same product semantics.
70. As an evaluator, I want provider identifiers, response metadata, adapter versions, and run settings recorded, so that results are reproducible despite moving hosted models.
71. As an evaluator, I want provider tools restricted to the Environment’s simulated actions, so that web search or provider-side tools cannot change the task.
72. As a model trainer, I want Gemma E4B to be the primary trainable checkpoint and E2B the bounded fallback, so that the first proof fits the available hardware.
73. As a model trainer, I want LoRA targets restricted to Gemma’s language layers, so that vision and audio towers are not accidentally trained.
74. As a model trainer, I want the Gemma-compatible renderer revision pinned, so that tool calls and tool results compile correctly into training samples.
75. As a model trainer, I want BF16 optimization configured explicitly, so that default FP32 loading does not exceed hardware capacity.
76. As a model trainer, I want the training run to consume only the approved EEG training split, so that held-out scenarios remain untouched.
77. As a model trainer, I want every training trace to preserve token IDs, masks, log probabilities, actions, rewards, and verifier results, so that failures can be diagnosed.
78. As a model trainer, I want a bounded GPU acceptance run before full training, so that save/reload and adapter compatibility are proved cheaply.
79. As a model trainer, I want both resumable trainer state and a portable PEFT adapter saved, so that training and serving use the appropriate artifact.
80. As a model trainer, I want adapter tensors compared before and after optimization, so that a nominally successful run proves weights changed.
81. As a model trainer, I want the saved adapter unloaded and reloaded into inference, so that evaluation does not rely on in-memory state.
82. As an evaluator, I want trained and base Gemma evaluated on paired held-out scenarios, so that their difference is measured per scenario.
83. As an evaluator, I want the primary win to require a positive held-out task-success difference whose 95% paired-bootstrap interval excludes zero, so that improvement is not asserted from noise.
84. As an evaluator, I want abort precision and recall, verifier score, action count, tool errors, and category results reported alongside success, so that the win remains interpretable.
85. As an evaluator, I want GPT and Gemini labeled as reference models rather than mandatory targets to beat, so that the core claim remains trained-versus-base improvement.
86. As an evaluator, I want mesoscope results reported separately from the EEG training claim, so that platform generality is not confused with cross-apparatus learning.
87. As an Environment author, I want evaluation and training progress visible in ordinary scientific language, so that I can follow the route without understanding prime-rl.
88. As an Environment author, I want failed evaluation or training steps to display actionable status without exposing secrets, so that recovery is possible.
89. As an Environment author, I want the final results view to connect model scores back to replayable scenarios, so that aggregate numbers remain grounded in behavior.
90. As a demonstrator, I want the complete authoring, run, evaluation, training, reload, and comparison path available from one console, so that the prototype proves execution rather than specification.
91. As a demonstrator, I want seeded successful and failing runs available without external APIs, so that the scientific console remains inspectable when hosted-model credentials are absent.
92. As a demonstrator, I want the full demo to reset to known data, so that it can be presented repeatedly.
93. As an operator, I want all model training and inference to run on the two approved RTX workstations, so that the Mac remains an orchestration and UI host only.
94. As an operator, I want inference endpoints bound to private or loopback interfaces, so that models are not exposed publicly.
95. As an operator, I want credentials read only from environment configuration, so that tokens never enter source, traces, or UI output.
96. As an operator, I want workstation revisions, model revisions, package versions, and artifacts recorded, so that a run can be reproduced.

## Implementation Decisions

- Build one repository containing a React/TypeScript Scientist Console and a local Python application. The console is a restrained Notion-inspired productivity shell: warm canvas, white work surfaces, hairlines, compact typography, one blue action color, no marketing layout, and progressive disclosure.
- Use the product-owned **Environment Bundle v1** as the authoritative contract. A bundle contains version metadata, Apparatus presentation data, action and observation schemas, Procedure state transitions, scenario manifests, hidden-state definitions, verifier declarations, metrics, split identities, and visualization assets.
- Use JSON-compatible authored documents and JSON Schema/Pydantic validation. Reject unknown major versions and preserve backward compatibility for minor additions.
- Place the highest behavioral seam at one deep Environment Runtime interface. It starts a bundle and scenario, returns the current Policy-visible observation, applies one validated action, returns the resulting transition, finalizes a verifier result, and replays a canonical trace. Callers never implement scientific transitions themselves.
- The Scientist Console and Verifiers adapter call the same Environment Runtime interface. UI preview behavior must not duplicate or approximate runtime semantics.
- Keep the Environment Contract validator, runtime, canonical trace construction, compiler, and local persistence inside the Python application. Keep apparatus-specific transitions and visualization data in separate EEG and mesoscope Environment modules behind the runtime interface.
- Represent authoring as a reversible Environment draft. Freezing a run creates an immutable bundle revision and scenario identity. Draft edits cannot mutate an active or completed run.
- Isolate Authoring assistant and Policy agent prompts, tools, context, state, and logs. The same underlying model may fill both roles only through separate instances.
- Implement deterministic seeded authoring behavior for the offline demo. A live Authoring assistant may be added through an adapter, but the product must remain usable without it.
- Implement EEG as a configurable whole-cap Apparatus with Procedure-selected Montages. Seed FC3, FC4, FT7, FT8, FCz reference, A1 ground, 1017 Hz sampling, 0.1–30 Hz bandpass, 50 Hz notch, the lower-right optical onset route, and separate response occurrence and identity.
- Generate synthetic EEG traces and frequency evidence deterministically from scenario seed, channel configuration, causal faults, and nuisance parameters. Do not encode a universal “good signal” threshold; verifiers score evidence gathering, diagnosis, targeted action, fresh retesting, and terminal disposition.
- Implement the approved staged EEG curriculum. Begin implementation with the marker-only level, then add configuration, signal, onset, response, short acquisition, runtime recovery, annotation, and close or abort stages.
- Materialize fixed 96/32/64 train/development/held-out EEG manifests. Keep blueprint and nuisance identifiers disjoint, reserve documented fault pairs and triples for held-out, and never generate scored held-out scenarios dynamically at evaluation time.
- Give an eligible safe abort equal terminal credit when a required recovery path is unavailable. Report abort precision and recall and prevent blanket aborts from receiving high aggregate reward.
- Implement mesoscope as a sealed synthetic Four-region handoff with immutable profiles and plans. Expose only inspection, mock acquisition, package validation, quarantine, reset, and replay actions. Do not expose laser, detector, alignment, calibration, motion, or biological controls.
- Require exact region, channel, event, motion-row, manifest, and checksum agreement before emitting `MOCK PACKAGE VERIFIED`.
- Compile Environment Bundles into native Verifiers v1 Tasksets and Toolsets through a thin adapter. Compile evaluation and prime-rl configurations as generated artifacts. Never require the authoring product to ingest framework-specific configuration as source.
- Store canonical traces in an append-only JSONL form suitable for replay and artifact export. Use local SQLite for draft, run, evaluation, training-job, and result indexes; large traces and model artifacts remain files referenced by digest.
- Define a canonical model-runner interface over messages, tools, token/accounting metadata, model settings, and trace events. Implement provider adapters at this seam for OpenAI Responses, Gemini Interactions, and local OpenAI-compatible Gemma.
- Preserve provider-native reasoning and function-call lineage inside adapter-private metadata while converting observations, actions, and results into the canonical trace. Never compare provider-native token counts as though they were equivalent.
- Pin and record the requested model identifier, response model identifier, provider metadata, adapter revision, sampling/reasoning settings, and evaluation window for every hosted run.
- Use Gemma E4B as the primary trainable checkpoint and E2B as the one bounded fallback. Keep 31B as a serving/evaluation stretch target rather than the first training dependency.
- Pin prime-rl, Verifiers, Transformers, PyTorch, vLLM, and the exact later Gemma-compatible renderer revision recorded by the training-path proof. Apply LoRA only to language-layer projection modules and set BF16 optimization and reduction explicitly.
- Use one approved GPU workstation for training and orchestration and the other for inference when capacity permits. Use private transport for inference and filesystem adapter broadcasts. Do not perform model training on the Mac.
- Gate full training on a bounded acceptance run proving forward/backward execution, finite optimization metrics, changed adapter tensors, resumable trainer state, stable PEFT output, inference unload/reload, and held-out tool-loop completion.
- Compare base and trained Gemma with paired held-out EEG scenarios. Compute the primary success-rate difference and a paired bootstrap confidence interval. Show GPT and Gemini as separately labeled references under the same Environment semantics.
- Keep credentials outside bundles, generated artifacts, traces, source, and logs. The UI reports only whether a required credential is configured.
- Keep all physical Apparatus connectors absent. Future hardware integration must satisfy a new seam and safety decision rather than extending mock actions directly.

## Testing Decisions

- Test external behavior at the highest available seam. Most scientific behavior tests start an Environment Bundle through the Environment Runtime, apply Policy-visible actions, and assert observations, canonical trace events, and verifier results. Do not test private reducer helpers or visualization implementation details.
- Treat the Environment Runtime interface as the primary contract test surface. Every EEG and mesoscope scenario adapter must pass the same lifecycle, visibility, validation, terminal, reset, and replay conformance suite.
- Test Environment Bundle validation with valid versions, unknown major versions, malformed action and observation schemas, invalid references, unreachable terminal states, visible/hidden-state leakage, duplicate identities, and invalid split membership.
- Test deterministic replay by running the same bundle, scenario, seed, and action sequence multiple times and asserting identical canonical state and verifier digests.
- Test that changing inspection order does not change hidden state or generated evidence unless the declared action semantics require it.
- Test that every state-changing action invalidates stale evidence and that only a fresh post-change observation can satisfy freshness verifiers.
- Test authoring/run isolation through the application seam: draft edits are reversible, freezing records a revision, and later draft changes cannot alter existing run traces.
- Test Authoring assistant and Policy agent isolation by asserting separate tool catalogs, prompts, context, state, and logs and by proving the Policy agent cannot invoke authoring actions.
- Test EEG behavior with golden scenario traces covering configuration faults, local and shared noise, faulty reference or ground, flatline, clipping, duplicate and missing onset markers, visible-trigger confounds, response occurrence and identity mismatches, recording-state mismatches, successful targeted recovery, failed recovery, justified abort, and unjustified blanket abort.
- Test EEG visual outputs by asserting stable channel identities, sample windows, event positions, frequency summaries, and accessibility labels rather than pixel-perfect screenshots. Add a small browser screenshot regression set only for the primary console layouts.
- Test split integrity by asserting exact counts, disjoint scenario and nuisance identifiers, reserved combinations only in held-out, deterministic manifest digests, and no held-out IDs in training artifacts.
- Test mesoscope behavior with golden traces for valid four-region handoff, missing region, duplicate event, wrong Z assignment, missing channel, motion-row mismatch, checksum mismatch, quarantine, reset, replay, and exact success wording.
- Test that no mesoscope action schema contains operational laser, detector, alignment, calibration, or motion-control fields.
- Test the Scientist Console with browser-level journeys for selecting an Environment, conversationally changing a draft, undoing, freezing, running, visualizing evidence, injecting a mock fault, receiving a verifier result, resetting, and replaying.
- Test responsive usability and keyboard focus for the console, details drawer, command composer, run controls, traces, and result comparison.
- Test generated Verifiers adapters with contract fixtures proving that task setup, tool execution, trace compilation, reward, metrics, and errors match direct Environment Runtime execution.
- Test provider adapters with recorded protocol fixtures before using credentials. Assert lossless function-call identity, complete tool-result replay, canonical action equivalence, `store=false`, disabled provider tools, budget handling, and error normalization.
- Keep live GPT and Gemini tests as explicit credentialed smoke tests, separate from deterministic unit and integration suites.
- Use the existing Gemma training-path probe as prior art for renderer, token/log-probability, adapter-artifact, and config validation. Extend its verifier rather than replacing artifact checks with log-string assertions.
- Test the bounded GPU acceptance run by requiring finite loss, gradient norm, and mismatch KL; non-empty trainer checkpoint state; stable PEFT adapter directories; at least one changed adapter tensor; successful unload/reload; and completed held-out tool loops.
- Test comparison analysis with synthetic paired outcomes whose expected success difference and bootstrap behavior are known. Assert that a win cannot be reported when the confidence interval includes zero.
- Test result provenance by tracing every aggregate metric back to immutable run and scenario identities.
- Run standards and specification review over every implementation ticket before closing it. A ticket is complete only when its externally visible acceptance behavior and artifact checks pass.
- There is no existing production test suite in this repository. The reusable prior art is the disposable Gemma training-path probe, the approved scenario documents, and deterministic trace requirements; the implementation must establish the project’s first test harnesses.

## Out of Scope

- Connecting to, discovering, configuring, or controlling physical scientific Apparatus.
- Medical, clinical, animal, research-validity, laser-safety, or operational certification.
- Operational mesoscope optics, detector, motion, alignment, calibration, surgery, or biological controls.
- Arbitrary instrument-driver plugins, LabVIEW-style editable wiring, or reliable ingestion of arbitrary manuals.
- More than EEG and mesoscope as implemented Environments; additional catalog entries remain nonfunctional examples.
- Managed cloud training, public model hosting, production autoscaling, or multi-region deployment.
- Production authentication, organizations, billing, compliance, audit administration, or collaboration.
- Training GPT or Gemini.
- Joint EEG/mesoscope training or a mesoscope-specific adapter in the first evidence run.
- Claiming cross-apparatus generalization from EEG training.
- Claiming trained Gemma beats GPT or Gemini; they are reference comparisons.
- Treating the rejected throwaway visual prototype as production code.
- Real-time guarantees or production-grade signal-processing performance.

## Further Notes

- The current throwaway UI was rejected for marketing-like presentation and excessive information density. It is a decision record only and must not be promoted into the application.
- `DESIGN.md` supplies visual tokens, not page structure. Use its warm canvas, quiet hairlines, compact Inter typography, and single blue action color while avoiding its marketing patterns.
- EEG authenticity comes from the apparatus model and source thesis; synthetic waveform parameters, thresholds, fault outcomes, and verifier rewards remain demo constructions and must be labeled accordingly.
- Mesoscope credibility comes from the sealed handoff and package-verification boundary, not from simulated operational control.
- The renderer commit pinned by prime-rl lacks Gemma 4 tool support. The implementation must use and record the audited later renderer revision before any GPU training acceptance claim.
- Hosted model identifiers can change or disappear. Validate availability when credentialed evaluation begins, record exact requested and returned identities, and preserve the provider-neutral comparison contract if a documented fallback is required.
- Ticket 10 closes only after a real GPU adapter is trained, saved, reloaded, and evaluated. Ticket 05 closes only after the mesoscope state machine and verifier run interactively. Ticket 13 closes only after the entire authoring-to-comparison path is runnable and replayable.
- No credential, token, private key, host address, or private SSH material may be written to the repository or surfaced in UI artifacts.
