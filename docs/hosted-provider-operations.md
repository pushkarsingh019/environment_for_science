# Hosted reference-provider operations

Science Environment Studio can run hosted models only as separately labeled reference
results. Hosted adapters use the same product-owned Environment Runtime, declared simulated
Apparatus actions, canonical call budgets, and deterministic Verifiers as local Gemma. They do
not receive web search, code execution, remote MCP, or other provider-side tools.

## OpenAI Responses

The scored adapter requests the exact model `gpt-5.6-sol` through
`POST https://api.openai.com/v1/responses` using adapter revision
`openai-responses/1`.

Set the credential only in the process launch environment:

```bash
export OPENAI_API_KEY='...'
.venv/bin/python -m studio
```

Do not put the value in a bundle, command argument, source file, trace, screenshot, or local
note. The console and `GET /api/provider-readiness` expose only `configured` or
`missing_credential`.

A fixed credentialed canary is available through the loopback-only application:

```bash
curl -X POST http://127.0.0.1:8000/api/hosted-smokes/openai
```

The canary uses one fixed EEG development scenario. It is not a held-out score. The returned
canonical attempt records requested and returned model identity, adapter revision, provider
request IDs, usage, storage-disabled stateless reasoning and function-call lineage, canonical
actions, Runtime transitions, and the Verifier result.

Requests always use `store=false`, non-streaming Responses, manual replay of all returned
output items, medium standard reasoning with all-turn context, and only bundle-declared
function tools. The adapter retries rate limits and transient server failures at most twice,
then records a normalized infrastructure error rather than a scientific zero.

If readiness says the credential is missing, restart the Studio from a shell where the variable
is present. If the smoke reports an adapter error, verify model access and the exact identifier;
do not replace `gpt-5.6-sol` with a moving alias.

## Gemini Interactions

The native adapter requests stable `gemini-3.7-flash` through
`POST https://generativelanguage.googleapis.com/v1beta/interactions` using adapter revision
`gemini-interactions/1`. It does not use Google's OpenAI compatibility route.

Set the credential only in the process launch environment:

```bash
export GEMINI_API_KEY='...'
.venv/bin/python -m studio
```

Readiness exposes only whether that variable is configured. Run the fixed, non-held-out canary
through the loopback application:

```bash
curl -X POST http://127.0.0.1:8000/api/hosted-smokes/gemini
```

Requests use `store=false`, non-streaming Interactions, medium thinking, the canonical output,
turn, tool, action, and episode budgets, and bundle-declared function tools only. Every returned
thought and function-call step must retain a non-empty thought signature. The adapter replays the
original input and all signed steps unchanged, then appends a call-ID- and name-linked structured
`function_result`.

Canonical evidence records requested and returned model identity, adapter and request identity,
normalized accounting, the untouched native usage object, signed reasoning lineage, canonical
actions, deterministic Runtime results, and normalized adapter or inference failures. Missing
signatures, usage mismatches, malformed calls, provider blocks, and reflected credential material
fail outside scientific scoring. Do not substitute `gemini-flash-latest` or another moving alias.
