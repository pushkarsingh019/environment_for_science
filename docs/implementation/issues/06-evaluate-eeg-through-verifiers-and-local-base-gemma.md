# 06: Evaluate EEG through Verifiers and local base Gemma

**What to build:** Compile the authored EEG Environment into native Verifiers v1 behavior and run a local base-Gemma Policy agent through the same deterministic runtime, tools, scoring, and canonical traces used by the Scientist Console.

**Blocked by:** 04: Run the complete EEG curriculum and fixed splits

**Status:** ready-for-agent

- [ ] A validated Environment Bundle compiles into a native Verifiers v1 Taskset and Toolset plus generated evaluation configuration.
- [ ] Generated framework artifacts are reproducible, disposable, and never become the authored source of truth.
- [ ] Direct runtime execution and Verifiers execution produce equivalent observations, action effects, terminal results, metrics, and canonical trace digests for fixture scenarios.
- [ ] A canonical model runner executes a multi-turn local Gemma tool loop using only declared simulated-Apparatus actions.
- [ ] The Policy agent cannot access hidden scenario truth, authoring tools, verifier implementation, or provider-side tools.
- [ ] Canonical traces preserve model identity, messages, tool calls and results, token/accounting metadata when available, actions, transitions, verifier results, and errors.
- [ ] Base calibration runs against development scenarios and demonstrates both successes and failures before training.
- [ ] Adapter and inference errors are reported separately from scientific scores.
- [ ] The console can launch or load the local evaluation, show ordinary-language progress, and open replayable results.
- [ ] Conformance tests cover task setup, tool execution, trace compilation, scoring parity, error normalization, and replay.
- [ ] Evaluation and model endpoints remain private; no secret or private host information enters generated artifacts or traces.
