# 09: Evaluate Gemini through Interactions

**What to build:** Add a provider-native Gemini Interactions adapter that runs the same scientific episodes and tools as local Gemma while preserving stateless reasoning steps, thought signatures, and tool lineage in canonical traces.

**Blocked by:** 06: Evaluate EEG through Verifiers and local base Gemma

**Status:** complete

- [x] The adapter uses the configured stable Gemini model identifier through Gemini Interactions rather than the OpenAI compatibility route or a moving latest alias.
- [x] Requests use storage-disabled stateless continuation and replay the original input, all returned steps, required thought signatures, function calls, and function results.
- [x] Function-call identities, arguments, results, reasoning lineage, model identity, usage, and errors survive canonical trace conversion.
- [x] Only the Environment’s declared simulated-Apparatus actions are available; provider search, code execution, and other built-ins are disabled.
- [x] Scenario, tool, turn, output, and action budgets match the canonical evaluation policy.
- [x] Recorded protocol fixtures test multi-turn calls, malformed calls, missing signatures, retries, rate limits, provider errors, and lossless canonicalization without credentials.
- [x] When a credential is configured securely, a live smoke run completes a fixed scenario and records requested and returned model identity plus adapter revision.
- [x] The console reports missing credential readiness without exposing secret values.
- [x] Reference results use the same deterministic verifier and remain clearly labeled as hosted Gemini results.
- [x] No provider response, trace, log, or UI output contains credentials.

Operator procedure: [run the signed-step hosted-provider canary](../../hosted-provider-operations.md).
