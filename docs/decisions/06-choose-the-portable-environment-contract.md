# Choose the portable environment contract

Type: grilling
Status: resolved
Blocked by:

## Question

What versioned, vendor-neutral contract should be the product's source of truth, and how should it compile into a deterministic simulator, native Verifiers v1 Tasksets and Toolsets, reward and metric hooks, evaluation configs, and prime-rl training configs without binding the authoring product to Prime Intellect? Define ownership, validation, versioning, and generated-artifact boundaries.

## Decision

Use a product-owned **Environment Bundle v1** as the portable source of truth: versioned JSON documents plus assets defining Apparatus structure, action and observation schemas, Procedure state transitions, deterministic scenario manifests, verifier declarations, metrics, and split identities.

The product runtime validates and executes bundles through one deep run interface. The Environment author may inspect the complete bundle; the Policy agent receives only declared observations and action results. Thin generated adapters compile bundles into Verifiers v1 Tasksets and Toolsets plus evaluation and prime-rl configurations. Generated artifacts are disposable and never become authoritative.

Reject unknown major versions; allow backward-compatible minor additions. Every trace records bundle, scenario, split, seed, initial-state digest, ordered observations, actions, transitions, verifier results, and terminal outcome. EEG and mesoscope use the same envelope with apparatus-specific state and visualization assets; the contract is not an editable wiring format or third-party framework configuration.
