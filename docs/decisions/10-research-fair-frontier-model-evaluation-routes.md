# Research fair frontier-model evaluation routes

Type: research
Status: resolved
Blocked by:

## Question

Which current Gemini and GPT endpoints can run the same multi-turn scientific tool-use tasks through Verifiers v1, and what provider-specific differences require adapters? Establish exact model identifiers, API and tool-call compatibility, pinning strategy, sampling controls, usage reporting, and known comparability limitations from primary sources.

## Answer

Use one provider-neutral episode runner and canonical tool trace, with thin native adapters for OpenAI Responses, Gemini Interactions, and local Gemma. Keep deterministic tools, budgets, hidden state, and scoring identical while preserving each provider's required reasoning and tool-call lineage. The pinned Verifiers checkout needs additional Responses-harness and Gemini-dialect work. See [`docs/research-frontier-model-evaluation.md`](../research-frontier-model-evaluation.md).
