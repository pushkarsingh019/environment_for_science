# 08: Evaluate GPT through OpenAI Responses

**What to build:** Add a provider-native OpenAI Responses adapter that runs the same scientific episodes and tools as local Gemma while preserving stateless multi-turn reasoning and tool lineage in canonical traces.

**Blocked by:** 06: Evaluate EEG through Verifiers and local base Gemma

**Status:** ready-for-agent

- [ ] The adapter uses the configured exact GPT model identifier through OpenAI Responses rather than relying on a moving alias or Chat Completions compatibility.
- [ ] Requests use stateless continuation with storage disabled and replay all required returned output items and function-call outputs.
- [ ] Function-call identities, arguments, results, reasoning lineage, model identity, usage, and errors survive canonical trace conversion.
- [ ] Only the Environment’s declared simulated-Apparatus actions are available; provider web search, code execution, remote MCP, and other built-ins are disabled.
- [ ] Scenario, tool, turn, output, and action budgets match the canonical evaluation policy.
- [ ] Recorded protocol fixtures test multi-turn calls, parallel or malformed calls, retries, rate limits, provider errors, and lossless canonicalization without credentials.
- [ ] When a credential is configured securely, a live smoke run completes a fixed scenario and records requested and returned model identity plus adapter revision.
- [ ] The console reports missing credential readiness without exposing secret values.
- [ ] Reference results use the same deterministic verifier and remain clearly labeled as hosted GPT results.
- [ ] No provider response, trace, log, or UI output contains credentials.
