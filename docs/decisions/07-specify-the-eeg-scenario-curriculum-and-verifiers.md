# Specify the EEG scenario curriculum and verifiers

Type: grilling
Status: resolved
Blocked by: 01, 04

## Question

Given the authentic EEG apparatus model, what deterministic scenario generator, state transitions, observations, tool actions, rewards, diagnostic metrics, and train versus held-out splits make the base task partially solvable while rewarding safe and efficient recovery? Decide which individual faults, compound faults, and unseen combinations support a defensible training-improvement claim.

## Decision

Adopt the staged full EEG episode proposed in [`docs/eeg-scenario-curriculum-options.md`](../eeg-scenario-curriculum-options.md).

- Use the marker-only one-flash/one-marker task as curriculum level 1 and the first engineering probe, but not as the final EEG demonstration.
- Progress through configuration, visual trace and frequency inspection, onset and response preflight, short mock acquisition, runtime recovery, annotation, and valid close or evidence-based abort.
- Give a correct safe abort equal terminal credit when a required path is genuinely unavailable. Report abort precision and recall separately so blanket caution cannot score well.
- Use disjoint 96/32/64 training/development/held-out manifests and reserve exact fault pairs and triples for held-out evaluation.
- Limit the claim to within-EEG compositional generalization. Report individual, ambiguous, pair, and triple results separately.
- Keep scenario generation deterministic, hide causal truth from the Policy agent, require fresh evidence after state-changing actions, and score behavior from the trace rather than polished explanations.

The Environment author approved all three recommended product-value choices. Exact serialization remains the portable-contract decision in ticket 06.
