# 11: Train Gemma on the EEG curriculum

**What to build:** Train the accepted EEG-specific Gemma adapter on the immutable training split, select and diagnose using development scenarios, reload the final artifact, and evaluate base and trained Gemma identically on the untouched held-out split.

**Blocked by:** 04: Run the complete EEG curriculum and fixed splits; 10: Train, save, reload, and evaluate a bounded Gemma adapter

**Status:** complete — verified 96/32/64 workstation evidence imported; observed contrast is inconclusive

- [x] Training consumes only the 96 approved training scenario identities and records the exact manifest digest.
- [x] Development decisions consume only the 32 development identities; no held-out outcome influences prompts, rewards, hyperparameters, stopping, or adapter selection.
- [x] The training job records immutable code, dependency, model, renderer, bundle, manifest, configuration, seed, and artifact identities.
- [x] Every rollout preserves canonical scientific trace data and the token, mask, log-probability, reward, and training metadata needed for diagnosis.
- [x] Training status and failures are visible in ordinary language without exposing framework internals or secrets by default.
- [x] The selected portable adapter is unloaded and reloaded before final evaluation.
- [x] Base and trained Gemma receive identical prompts, scenarios, tools, hidden state, budgets, sampling policy, and deterministic scoring on all 64 held-out identities.
- [x] Results report task success, verifier score, abort precision and recall, action count, tool errors, and individual, ambiguous, pair, and triple strata.
- [x] A paired bootstrap analysis reports the trained-minus-base success difference and 95% confidence interval.
- [x] The system reports a training win only when the difference is positive and the interval excludes zero; otherwise it reports the observed result without claiming improvement.
- [x] Every aggregate metric links back to immutable scenario runs and replayable canonical traces.

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

The verified E4B run completed 96 source-ordered optimizer steps over all 96 training identities.
It retained 418 native rollouts (at least four per identity), 41,564 sampled log-probability tokens,
scientific rewards from 0 to 1, and no provider, adapter, tool, or trace errors. All 96 loss,
gradient-norm, and mismatch-KL records were finite. The final bounded adapter changed all 28
language-layer tensors and wrote two content-bound DCP files.

The predeclared step-96 adapter was unloaded and reloaded as `eeg-curriculum-final`. Base and
trained policies each covered all 32 development and 64 evaluator-held-out identities under the
same fixed evaluation contract. Base succeeded on 9/64; trained succeeded on 10/64. The observed
trained-minus-base difference was `0.015625`, with paired 95% bootstrap interval
`[0.0, 0.046875]`; therefore the approved rule reports **inconclusive**, not a training win.
Artifact digest
`sha256:9b972fa5914da32ef1671c510d97e63004db02e15e6044dd29ab99be759d8b6a`
binds the sanitized imported result. See the
[bounded curriculum operator procedure](../../gemma-curriculum-operations.md).
