# Build a visual science environment studio

## Destination

Reach a working hackathon prototype where a non-programming experimental scientist visually or conversationally creates mocked EEG and mesoscope environments, evaluates reference and base Gemma policies, launches real Gemma training, and tests—without presuming—whether trained Gemma improves on held-out scenarios.

## Implementation specification

- [Science Environment Studio executable prototype specification](specification.md)

## Notes

- This effort explicitly carries execution through to the working prototype; it does not stop at a build specification.
- Read `CONTEXT.md` for canonical domain language.
- Consult `grilling` and `domain-modeling` for HITL decisions, `prototype` for interaction questions, `research` for external facts, and `codebase-design` before locking module boundaries.
- The environment author understands the apparatus but is not expected to code or know APIs, ML, RL, rewards, or verifiers terminology.
- The primary UI must be visual and conversational. Do not imitate LabVIEW literally and do not make generated code the primary editing surface.
- EEG is the deep, user-informed example. Mesoscope acquisition is the visually compelling, research-led example and must be presented as a simulation rather than validated operating guidance.
- Show dummy catalog cards for additional apparatuses, but implement only EEG and mesoscope.
- Agents have full access to simulated apparatus actions. Guided/Auto/YOLO mode design is intentionally dropped from this prototype.
- Training occurs before the presentation; the product UI must still show the complete route from environment authoring through evaluation and launching/monitoring training.
- Use `docs/research-prime-intellect-verifiers.md` as the current Prime Intellect context. Target native Verifiers v1 and self-managed prime-rl, behind a portable product-owned contract. Managed training or hosting is not required.
- Available self-managed compute is documented outside the repository: a Mac Studio and two workstations with one RTX PRO 6000 96 GB GPU each. Never copy host details or credentials into repository artifacts.
- The hackathon prototype is confirmed simulation-only because the user's apparatuses are not currently connected. Real hardware integration remains a later effort outside this map.

## Decisions so far

<!-- Closed ticket pointers are appended here. -->

- [EEG apparatus: simulate a configurable whole-cap scalp-EEG chain, with visual signal judgment and authentic trigger and response faults.](decisions/01-model-the-eeg-apparatus-from-lived-experience.md)
- [Mesoscope demo: rehearse a sealed, synthetic four-region handoff with immutable plans and no laser-control surface.](decisions/02-research-a-credible-mesoscope-acquisition-workflow.md)
- [Gemma path: E4B is the proved primary checkpoint and E2B is only the bounded resource fallback.](decisions/03-prove-the-gemma-4-training-path.md)
- [Agent roles: isolate the Authoring assistant from the Policy agent, without adding mock-instrument approval machinery.](decisions/04-separate-the-authoring-agent-from-the-policy-agent.md)
- [Scientist-facing visual language: use one simple, visualization-first scientist console with progressive disclosure and a conversational command composer.](decisions/05-prototype-the-scientist-facing-visual-language.md)
- [Portable contract: own an Environment Bundle v1 and compile disposable Verifiers and prime-rl adapters from it.](decisions/06-choose-the-portable-environment-contract.md)
- [EEG curriculum: use staged full episodes, credit justified safe aborts, and reserve unseen fault pairs and triples for held-out evaluation.](decisions/07-specify-the-eeg-scenario-curriculum-and-verifiers.md)
- [Mesoscope contract: use the sealed four-region acquisition-readiness handoff with deterministic package verification.](decisions/08-prototype-the-mesoscope-scenario-contract.md)
- [Training scope: train one EEG-specific Gemma E4B adapter, retain E2B as fallback, and keep mesoscope as a separate platform-generality track.](decisions/09-choose-what-gets-trained-across-apparatuses.md)
- [Frontier routes: use provider-native OpenAI Responses and Gemini Interactions adapters behind one canonical episode runner.](decisions/10-research-fair-frontier-model-evaluation-routes.md)
- [Winning evidence: require a positive paired held-out EEG improvement over base Gemma with a 95% bootstrap interval excluding zero.](decisions/11-define-the-model-comparison-and-winning-evidence.md)
- [Demo story: author, freeze, simulate, verify, evaluate, inspect training, compare honestly, replay, and reset.](decisions/12-prototype-the-end-to-end-demo-story.md)
- [Architecture: one React/TypeScript console and one Python runtime shared by the UI and Verifiers adapter.](decisions/13-choose-the-implementation-architecture.md)

## Implementation

The specification is divided into 13 dependency-ordered implementation tickets. For the
current checkpoint and build order, see the
[implementation plan](implementation/README.md).

## Out of scope

- Connecting to or controlling physical scientific apparatus in this hackathon prototype.
- Medical, research, laser-safety, or operational validation of either simulated apparatus.
- Production-grade arbitrary device drivers, local hardware discovery, and Arduino provisioning.
- A complete commercial instrument catalog or reliable ingestion of arbitrary manuals.
- Autonomy-mode and permission-policy design for real equipment.
- Production deployment, organization management, billing, and compliance.
