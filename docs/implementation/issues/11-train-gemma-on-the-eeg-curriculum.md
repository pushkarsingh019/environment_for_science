# 11: Train Gemma on the EEG curriculum

**What to build:** Train the accepted EEG-specific Gemma adapter on the immutable training split, select and diagnose using development scenarios, reload the final artifact, and evaluate base and trained Gemma identically on the untouched held-out split.

**Blocked by:** 04: Run the complete EEG curriculum and fixed splits; 10: Train, save, reload, and evaluate a bounded Gemma adapter

**Status:** ready-for-agent

- [ ] Training consumes only the 96 approved training scenario identities and records the exact manifest digest.
- [ ] Development decisions consume only the 32 development identities; no held-out outcome influences prompts, rewards, hyperparameters, stopping, or adapter selection.
- [ ] The training job records immutable code, dependency, model, renderer, bundle, manifest, configuration, seed, and artifact identities.
- [ ] Every rollout preserves canonical scientific trace data and the token, mask, log-probability, reward, and training metadata needed for diagnosis.
- [ ] Training status and failures are visible in ordinary language without exposing framework internals or secrets by default.
- [ ] The selected portable adapter is unloaded and reloaded before final evaluation.
- [ ] Base and trained Gemma receive identical prompts, scenarios, tools, hidden state, budgets, sampling policy, and deterministic scoring on all 64 held-out identities.
- [ ] Results report task success, verifier score, abort precision and recall, action count, tool errors, and individual, ambiguous, pair, and triple strata.
- [ ] A paired bootstrap analysis reports the trained-minus-base success difference and 95% confidence interval.
- [ ] The system reports a training win only when the difference is positive and the interval excludes zero; otherwise it reports the observed result without claiming improvement.
- [ ] Every aggregate metric links back to immutable scenario runs and replayable canonical traces.
