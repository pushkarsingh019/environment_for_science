# 11: Train Gemma on the EEG curriculum

**What to build:** Train the accepted EEG-specific Gemma adapter on the immutable training split, select and diagnose using development scenarios, reload the final artifact, and evaluate base and trained Gemma identically on the untouched held-out split.

**Blocked by:** 04: Run the complete EEG curriculum and fixed splits; 10: Train, save, reload, and evaluate a bounded Gemma adapter

**Status:** in-progress — immutable-split software passes; the real workstation curriculum run and evidence import are active

- [ ] Training consumes only the 96 approved training scenario identities and records the exact manifest digest.
- [ ] Development decisions consume only the 32 development identities; no held-out outcome influences prompts, rewards, hyperparameters, stopping, or adapter selection.
- [ ] The training job records immutable code, dependency, model, renderer, bundle, manifest, configuration, seed, and artifact identities.
- [ ] Every rollout preserves canonical scientific trace data and the token, mask, log-probability, reward, and training metadata needed for diagnosis.
- [x] Training status and failures are visible in ordinary language without exposing framework internals or secrets by default.
- [ ] The selected portable adapter is unloaded and reloaded before final evaluation.
- [ ] Base and trained Gemma receive identical prompts, scenarios, tools, hidden state, budgets, sampling policy, and deterministic scoring on all 64 held-out identities.
- [ ] Results report task success, verifier score, abort precision and recall, action count, tool errors, and individual, ambiguous, pair, and triple strata.
- [x] A paired bootstrap analysis reports the trained-minus-base success difference and 95% confidence interval.
- [x] The system reports a training win only when the difference is positive and the interval excludes zero; otherwise it reports the observed result without claiming improvement.
- [ ] Every aggregate metric links back to immutable scenario runs and replayable canonical traces.

## Implementation readiness

The prime-locked training compiler now emits separate content-addressed training, development,
and evaluator-held-out targets with stable MCP retry identities and changed-field observations.
Durable curriculum jobs bind the 96/32/64 counts and package digests in ordinary language. A
fail-closed verifier requires all 96 training identities with at least four rollouts each, preserves
replacement groups explicitly, and verifies aligned token/mask/log-probability metadata, canonical
Runtime evidence, 96 finite optimizer steps, changed
language-only LoRA tensors, resumable state, predeclared final-step selection, all 32 development
identities, and matched 64-row sealed held-out ledgers. The paired bootstrap is deterministic and
can report only improved, inconclusive, or regressed under the approved interval rule.

The real E4B workstation run uses 96 source-ordered steps and groups of four, retaining any
replacement rollouts. It uses BF16, a 16,384-token bound, no mechanical reward, and a final-step
adapter selected before any
held-out evaluation. Completion remains unchecked until native artifacts pass the product verifier
and the fresh adapter reload and sealed base/trained evaluations are imported. See the
[bounded curriculum operator procedure](../../gemma-curriculum-operations.md).
