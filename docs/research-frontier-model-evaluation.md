# Fair frontier-model evaluation routes

Research date: 2026-08-22

Verifiers source inspected at Prime Intellect commit
[`b878d009`](https://github.com/PrimeIntellect-ai/verifiers/tree/b878d009147876bfd1ba80feec770194f0b567c7).
Provider documentation was read on the research date. No credentials were used and no
model endpoint was called.

## Recommendation

Use one provider-neutral episode runner and deterministic Model Context Protocol (MCP)
tool server. Add thin adapters that translate canonical turns to each provider's wire
format:

- **GPT:** Request the exact model ID `gpt-5.6-sol` through OpenAI
  `POST /v1/responses`, with standard mode, `reasoning.effort="medium"`,
  `reasoning.context="all_turns"`, `store=false`, and complete manual replay of every
  returned output item.
- **Gemini:** Request the stable model ID `gemini-3.7-flash` through Google
  `POST /v1beta/interactions`, with `thinking_level="medium"`, `store=false`, and
  complete manual replay of every returned step, including thought signatures.
- **Gemma:** Keep the local OpenAI-compatible Chat Completions and renderer route, but
  put its messages, calls, and results through the same canonical runner before
  rendering.

This is the closest defensible *same-task* comparison: the task, simulated state,
tools, results, limits, and scoring can be identical, while each provider receives the
state format its reasoning model is designed to consume. OpenAI recommends Responses
for reasoning, tool calling, and multi-turn work, and says Chat Completions tool calling
is unavailable at reasoning efforts other than `none` starting with GPT-5.4. Google says
Gemini 3 reasoning cannot be disabled and `gemini-3.7-flash` supports only `low`,
`medium`, and `high`. A common Chat Completions route therefore forces materially
different reasoning settings before the task even begins. Sources: [OpenAI Responses
migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses#additional-differences),
[OpenAI GPT-5.6 guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters),
[Google OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai#thinking), and
[Gemini 3.7 Flash model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash).

The pinned Verifiers tree does **not** provide this complete route. It includes
an OpenAI Responses dialect, but its built-in `null` harness speaks only Chat
Completions. It has no Gemini `Interactions` or `generateContent` dialect. The required
work is therefore:

1. Add a minimal Responses-speaking version of the null tool loop.
2. Add a Gemini Interactions dialect and adapter.
3. Share tool execution, canonical validation, budgets, and trace metadata across both.
4. Retain the Chat route only for local Gemma and interoperability tests.

Do not publish a score from the common Chat compatibility route as the final
frontier comparison.

## Exact model identifiers

The following table separates the primary model IDs from fallback and supplementary
model IDs.

| Use | Exact identifier | Status and decision |
| --- | --- | --- |
| Recommended current GPT run | `gpt-5.6-sol` | OpenAI identifies this as the frontier GPT-5.6 tier; `gpt-5.6` is an alias that routes to it. Use the tier ID, never the alias. It supports Responses, Chat Completions, function calling, and structured outputs, with a 1,050,000-token context window and 128,000-token output limit. [Model reference](https://developers.openai.com/api/docs/models/gpt-5.6-sol) |
| Stronger documentary GPT freeze fallback | `gpt-5.5-2026-04-23` | This is a dated snapshot explicitly listed on the GPT-5.5 model page. Use it if an audit requires a dated OpenAI snapshot more than it requires the latest GPT family. [Model reference, "Snapshots"](https://developers.openai.com/api/docs/models/gpt-5.5#snapshots) |
| Recommended current stable Gemini run | `gemini-3.7-flash` | Google lists this as stable, with function calling, structured output, and low/medium/high thinking. It has a 1,048,576-token input limit and 65,536-token output limit. [Model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash) |
| Supplementary Gemini capability track | `gemini-3.1-pro-preview` | Google describes this as the current Pro preview and documents function calling, but it is a preview rather than a stable pin. Run it as a separately labeled sensitivity track, not as the frozen primary result. [Model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview) |
| Do not use for the primary comparison | `gemini-3.1-pro-preview-customtools` | This variant is explicitly optimized to prefer custom tools and Google warns of quality fluctuations outside those use cases. Choosing it would change the intervention being compared. [Model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview#gemini-31-pro-preview-customtools) |
| Do not use | `gpt-5.6`, `gemini-flash-latest`, `gemini-pro-latest` | These are moving aliases. OpenAI says `gpt-5.6` routes to Sol; Google says `latest` aliases are hot-swapped on new releases. [OpenAI guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters), [Google version-name patterns](https://ai.google.dev/gemini-api/docs/models#model-version-name-patterns) |

There is no perfectly symmetric provider pin. At inspection time, the GPT-5.6 Sol page
listed `gpt-5.6-sol` but no dated GPT-5.6 snapshot, while Google says a stable identifier
*usually* does not change rather than promising immutable weights. OpenAI separately
recommends dated snapshots such as `gpt-5.5-2026-04-23` for consistent behavior.
Therefore, "frozen" must mean **requested identifier + provider response metadata + run
window + adapter version**, not proven bit-identical weights. Sources: [GPT-5.6 Sol
snapshots section](https://developers.openai.com/api/docs/models/gpt-5.6-sol#snapshots),
[OpenAI snapshot recommendation](https://developers.openai.com/api/docs/guides/text-generation#prompt-engineering),
and [Google model-version policy](https://ai.google.dev/gemini-api/docs/models#model-version-name-patterns).

The recommended stable pair is not a claim that "Sol" and "Flash" have equal size, cost,
or provider rank. No primary source defines a cross-provider tier equivalence. Label the
rows by exact model ID rather than "equally sized frontier models." If the product must
show each provider's highest advertised capability, add the regular
`gemini-3.1-pro-preview` result as a supplementary sensitivity result and preserve the
stable
`gemini-3.7-flash` result.

## Provider API and tool-call routes

### OpenAI

The preferred route is:

```text
POST https://api.openai.com/v1/responses
model = gpt-5.6-sol
```

OpenAI recommends Responses for new projects and reports better multi-turn tool behavior
for reasoning models than Chat Completions. Responses represents messages,
reasoning, function calls, and function outputs as separate items. A function result is
linked with `call_id`; state can be chained with `previous_response_id` or carried
manually by replaying prior output items. [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses#about-the-responses-api)

For this evaluation, use **manual stateless continuation**:

- Send `store=false`.
- Keep every returned output item, including encrypted reasoning and assistant phase.
- Append `function_call_output` with the matching `call_id`.
- Resend the complete history on the next model turn.
- Repeat stable system instructions explicitly.

OpenAI documents this stateless pattern and says encrypted reasoning items are returned
for replay. It also notes that earlier context remains billable even when
`previous_response_id` is used. [Conversation-state guide](https://developers.openai.com/api/docs/guides/conversation-state#manually-manage-conversation-state),
[reasoning-state guide](https://developers.openai.com/api/docs/guides/reasoning#preserve-reasoning-without-stored-responses)

`POST /v1/chat/completions` remains usable for a connectivity test. It is not the recommended
frontier route because the application must manage message history manually and GPT
Chat tool calling must use `reasoning_effort="none"`. [OpenAI migration differences](https://developers.openai.com/api/docs/guides/migrate-to-responses#additional-differences)

### Google Gemini

Three Google routes are relevant:

| Route | Native shape | Role here |
| --- | --- | --- |
| `POST https://generativelanguage.googleapis.com/v1beta/interactions` | `input` and ordered `steps` such as `thought`, `function_call`, and `function_result` | Recommended adapter target. Google's current function-calling examples use this route. [Function-calling flow](https://ai.google.dev/gemini-api/docs/function-calling#how-function-calling-works) |
| `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` | `contents`, `parts`, `functionCall`, `functionResponse`, and `thoughtSignature` | Supported by Google, but not by pinned Verifiers and not needed if Interactions is implemented. [REST reference](https://ai.google.dev/api/generate-content#method:-modelsgeneratecontent) |
| `POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` | OpenAI Chat Completions compatibility | Can use the Verifiers null path in principle; use only for a small connectivity test. Google labels OpenAI-library support beta. [Compatibility guide](https://ai.google.dev/gemini-api/docs/openai), [current limitations](https://ai.google.dev/gemini-api/docs/openai#current-limitations) |

Configure the Interactions adapter to be stateless:

- Send `store=false`.
- Send the full prior user input and every model step exactly as returned.
- Retain all `thought` steps and signatures.
- Append a `function_result` that contains `name`, the provider `call_id`, and the
  canonical tool result.
- Do not use `previous_interaction_id` in the scored route.

Google's stateless function-calling example requires the initial input, all model steps
(including thought and function-call steps), and the function result to be replayed.
Google separately says thought blocks must not be removed or modified because their
signatures maintain reasoning continuity. [Stateless function calling](https://ai.google.dev/gemini-api/docs/function-calling#stateless-function-calling),
[thought signatures](https://ai.google.dev/gemini-api/docs/thinking#thought-signatures)

Although Google calls stateful Interactions the recommended convenience mode, stateless
mode is preferable for this benchmark because the complete model-visible lineage is in
the evaluation artifact rather than hidden behind a provider conversation ID.

Do not give either hosted model provider-side web search, code execution, remote MCP, or
other built-in tools. The scientific environment's client-executed MCP tools are the
only actions under test.

## What pinned Verifiers v1 actually supports

### Implemented behavior

The v1 client config describes a `base_url`, an API-key environment variable, and extra
headers. `EvalClient` relays the intercepted native JSON to the upstream path selected
by the dialect and parses a copy for the trace. [Client config](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/configs/client.py#L1-L35),
[eval client](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/clients/eval.py#L58-L97)

The interception server registers three dialects: OpenAI Chat Completions, OpenAI
Responses, and Anthropic Messages. It does not register a Gemini native dialect.
[Dialect registry](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/__init__.py#L1-L14)
The following table shows which provider routes the null harness can emit.

| Provider route | Dialect in pinned source | Built-in `null` harness emits it | Status for this project |
| --- | --- | --- | --- |
| OpenAI `/chat/completions` | Yes | Yes | Implemented, but GPT tool use is restricted to reasoning `none`. |
| Google OpenAI-compatible `/chat/completions` | Generic Chat dialect | Yes | Unverified connectivity route; no Gemini-specific conformance test or trace handling was found. |
| OpenAI `/responses` | Yes | No | Relay and parsing are implemented; a Responses-speaking tool-loop harness is still needed. |
| Google `/v1beta/interactions` | No | No | Requires a dialect, authentication, parser, streamer, usage mapper, and harness adapter. |
| Google `:generateContent` | No | No | Requires another adapter; do not add it in addition to Interactions. |

The Responses dialect is explicitly "relay-only." It parses `reasoning`, assistant
messages, and function calls into one Verifiers assistant message, retains the native
output list as opaque `provider_state`, maps Responses usage, and can request encrypted
reasoning for GPT reasoning models. It does not create calls by itself, and
`previous_response_id` remains provider-owned state. [Responses dialect overview](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/responses.py#L1-L8),
[response and usage parsing](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/responses.py#L360-L395),
[GPT override handling](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/responses.py#L754-L786)

The current null harness:

1. Calls `client.chat.completions.create`, not `client.responses.create`.
2. Converts each MCP input schema to an OpenAI Chat function tool.
3. Appends the complete assistant message and `role="tool"` results to an in-memory
   message list.
4. Runs multiple emitted calls sequentially in response order.
5. Ends when the assistant emits no tool calls.
6. Reconnects to MCP for each call and might replay a call after a lost response. Tools
   must tolerate at-least-once delivery.

Sources: [null Chat call and tool conversion](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py#L21-L27),
[MCP retry contract](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py#L61-L71),
[tool schema construction](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py#L74-L107),
[tool loop](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py#L183-L218).

The Chat dialect records a broad sampling-key whitelist and overlays the run's model and
sampling configuration onto the intercepted request. Its canonical `max_tokens` field
is not converted to OpenAI's `max_completion_tokens` on the outbound Chat path. Do not
assume the current null route enforces a valid per-call GPT-5 output cap without an
adapter probe. [Chat dialect sampling and route](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/chat.py#L330-L357),
[Chat overrides](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/chat.py#L547-L556),
[OpenAI Chat `max_completion_tokens`](https://developers.openai.com/api/docs/api-reference/chat/create)

### Unsupported and unverified behavior

The following must not be represented as current Verifiers support:

- Native Gemini Interactions or `generateContent` requests.
- Gemini `x-goog-api-key` authentication on a native dialect.
- Explicit parsing and persisted tracing of Gemini thought signatures.
- Native Gemini safety, finish, and usage metadata.
- A built-in Responses null harness.
- A provider-neutral strict-schema validator.
- A guarantee that Google OpenAI compatibility preserves all signature fields through
  the OpenAI software development kit (SDK) and the serialized Verifiers trace.
- A provider-resolved model or build ID in each persisted call record.

The last point matters for pinning. `ModelCall.model` stores the requested model, while
the full native response is marked `exclude=True`; the typed response's provider model
is not a persisted `ModelCall` field. [ModelCall schema](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/trace.py#L153-L173),
[excluded raw response](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/types.py#L226-L235)

There is also a dependency-pin gap: the repository lock resolves `openai==2.45.0`, but
the null harness's inline script declares unbounded `openai`, `httpx`, and `tenacity`
dependencies and only a range for MCP. Pin the actual script environment and container, not
only the Verifiers git commit. [Null script metadata](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py#L1-L4),
[repository OpenAI lock](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/uv.lock#L2903-L2919)

## Structured tool-schema differences

The following table compares each provider's function-call representation.

| Concern | OpenAI Chat Completions | OpenAI Responses | Gemini OpenAI compatibility | Gemini Interactions and `generateContent` |
| --- | --- | --- | --- | --- |
| Declaration envelope | `{type:"function", function:{name, description, parameters, strict}}` | `{type:"function", name, description, parameters, strict}` | Accepts the OpenAI Chat envelope in Google's documented example | Interactions uses top-level `{type:"function", name, description, parameters}`; `generateContent` groups `functionDeclarations` inside a tool |
| Call arguments | JSON-encoded string in `tool_calls[].function.arguments` | JSON-encoded string in a `function_call` item | OpenAI-compatible Chat shape | Object in `function_call.arguments` or `functionCall.args` |
| Result | `role:"tool"`, linked by `tool_call_id` | `function_call_output`, linked by `call_id` | OpenAI-compatible Chat shape | `function_result` or `functionResponse`, linked by call ID or function name, with structured result content |
| Strictness | Chat is non-strict by default; `strict:true` requires all object properties required and `additionalProperties:false` | Responses attempts strict normalization by default unless `strict:false` | The compatibility page documents function calling but does not promise OpenAI strict-mode equivalence | Interactions offers `validated` tool choice; native function schemas support a documented subset rather than all JSON Schema and OpenAPI features |
| Multiple calls | May emit multiple; `parallel_tool_calls:false` limits to zero or one | May emit multiple | Gemini supports parallel calls, but the compatibility page does not document parity for every OpenAI control | Gemini documents parallel and compositional calls; Interactions has no documented `parallel_tool_calls` Boolean in its current generation config |
| Reasoning continuity | Full Chat messages; current GPT tool calls require effort `none` | Replay reasoning, function, and message items, or use provider state | Google says Chat compatibility supports Gemini 3 thought signatures, but the pinned trace has no explicit Gemini carrier | Replay every signed thought step or part exactly, or use provider-managed state |

Sources: [OpenAI function definitions and handling](https://developers.openai.com/api/docs/guides/function-calling#defining-functions),
[OpenAI strict mode](https://developers.openai.com/api/docs/guides/function-calling#strict-mode),
[OpenAI parallel calls](https://developers.openai.com/api/docs/guides/function-calling#parallel-function-calling),
[Google OpenAI-compatible function example](https://ai.google.dev/gemini-api/docs/openai#function-calling),
[Google function declarations](https://ai.google.dev/gemini-api/docs/function-calling#function-declarations),
[Google modes](https://ai.google.dev/gemini-api/docs/function-calling#function-calling-modes), and
[Google schema limitations](https://ai.google.dev/gemini-api/docs/function-calling#notes-and-limitations).

Compile every scientific tool from one canonical schema restricted to the shared safe
subset:

- Names matching `[A-Za-z0-9_-]{1,64}`.
- A root object with explicitly listed properties.
- String, number, integer, Boolean, array, and nested object values.
- Only `description`, `enum`, `required`, `items`, and simple minimum and maximum bounds.
- No `$ref`, recursive schema, unions, defaults with behavioral meaning, arbitrary extra
  properties, or provider-only fields.
- At most 10 active tools unless a measured scenario requires more.

OpenAI permits names up to 64 characters, while Google's native declaration permits up
to 128 and additional punctuation; the smaller grammar is the common contract.
[OpenAI function schema](https://developers.openai.com/api/docs/guides/function-calling#defining-functions),
[Google FunctionDeclaration reference](https://ai.google.dev/api/generate-content#FunctionDeclaration)

Do not rely on provider constrained decoding to make a call valid. Validate every emitted
argument object against the same canonical schema in the episode runner, record an
`invalid_tool_arguments` event, and return the same deterministic error observation to
every model. Provider strict and validated modes can be a separate ablation. This preserves
schema compliance as something the evaluation can measure rather than silently giving
one provider a different decoder.

Allow a model to emit more than one call in a turn, but execute accepted calls in emitted
order against the simulator and return results in that order. This matches the built-in
null loop and avoids assuming that provider "parallel" controls have identical
semantics. Apply the same per-episode call budget.

## Context and state handling

Keep three kinds of state separate:

1. **Scientific environment state** is the typed per-rollout Verifiers state behind the
   MCP server. It is authoritative and must be initialized from the same held-out seed.
2. **Canonical transcript state** is the provider-neutral sequence of user observations,
   accepted tool calls, tool results, and final answer used for scoring and audit.
3. **Provider reasoning state** is opaque OpenAI reasoning and output items or Gemini
   thought steps and signatures. It is required for model quality but must never become simulator
   state or scoring evidence.

For OpenAI, replay all output items and use `reasoning.context="all_turns"`. For Gemini,
replay all steps unchanged. Don't translate encrypted or signed reasoning between providers,
inspect it as ground truth, or expose it to reward code. Only the canonical visible call,
result, and answer enter scoring.

The pinned Verifiers `AssistantMessage.provider_state` is capable of carrying a list of
opaque native items, and the Responses dialect populates it. That is useful plumbing for
OpenAI; it is not, by itself, a Gemini adapter. [Provider-state type](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/types.py#L73-L80),
[Responses population](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/dialects/responses.py#L383-L394)

Side-effecting simulator tools must be idempotent under an episode-scoped canonical call
ID because the current MCP loop explicitly permits at-least-once delivery after transport
failure. A provider call ID is only a continuation link; it must not be the sole
idempotency key.

## Sampling controls

### Recommended scored profile

The following table defines the sampling profile for scored runs.

| Control | GPT Responses | Gemini Interactions | Fair-comparison treatment |
| --- | --- | --- | --- |
| Reasoning | `reasoning.effort="medium"`, `reasoning.mode="standard"`, `reasoning.context="all_turns"` | `generation_config.thinking_level="medium"` | Same named qualitative level, not the same hidden token budget. Record reasoning and thought usage. |
| Temperature | Omit | Not exposed in the current Interactions `GenerationConfig`; Gemini 3 guidance recommends its default 1.0 | Do not force a numeric value through a compatibility layer. |
| Top-p and top-k | Omit | Omit | Provider defaults; numeric values do not define the same distribution across tokenizers. |
| Seed | Do not set | Do not set, although Interactions exposes one | OpenAI Responses has no matching documented seed. Use repeated rollouts and deterministic *environment* seeds instead. |
| Output cap | Set a high, pre-piloted `max_output_tokens` unlikely to bind | Set the same numeric high cap | The fields need not count hidden reasoning identically. Mark any capped response and report it separately. |
| Tool choice | `auto` | `auto` | Same decision freedom. No provider built-ins. |
| Storage | `false` | `false` | Complete client-side replay. |
| Service tier | default | standard | Pin and record; do not mix flex and priority in one comparison. |
| Streaming | off for scored runs | off for scored runs | Simplifies complete usage and terminal-state capture. |

OpenAI documents GPT-5.6 efforts `none`, `low`, `medium`, `high`, `xhigh`, and `max`, with
medium as the default. Google documents `gemini-3.7-flash` as medium by default with
low/medium/high support. [OpenAI reasoning controls](https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort),
[Google thinking levels](https://ai.google.dev/gemini-api/docs/thinking#controlling-thinking)

Google strongly recommends keeping Gemini 3 temperature at its default 1.0 and warns
that reducing it can cause looping or degraded reasoning. OpenAI describes temperature
and top-p as alternatives and recommends changing at most one. The same numeric
`temperature=0` is therefore neither a fair nor a reliable "deterministic" setting.
[Gemini 3 temperature guidance](https://ai.google.dev/gemini-api/docs/gemini-3#temperature),
[OpenAI Chat sampling reference](https://developers.openai.com/api/docs/api-reference/chat/create)

Model sampling remains nondeterministic. Fix scenario seeds, not model randomness; use a
predeclared number of independent rollouts per task and report confidence intervals or
the full score distribution. A model seed, where available, is not a substitute for a
model and version pin or repetitions.

## Usage accounting

Provider-native accounting is not directly interchangeable.

| Source | Native fields relevant here | Interpretation |
| --- | --- | --- |
| OpenAI Responses | `input_tokens`, `input_tokens_details.cached_tokens`, `output_tokens`, `output_tokens_details.reasoning_tokens`, `total_tokens` | Reasoning tokens are a subset of output tokens and must not be added twice. [Reasoning usage example](https://developers.openai.com/api/docs/guides/reasoning#managing-the-context-window) |
| OpenAI Chat | `prompt_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens`, `completion_tokens_details.reasoning_tokens`, `total_tokens` | Same subset rule; the names differ from Responses. [Chat usage object](https://developers.openai.com/api/docs/api-reference/chat/create) |
| Gemini Interactions | `total_input_tokens`, `total_cached_tokens`, `total_output_tokens`, `total_thought_tokens`, `total_tool_use_tokens`, modality breakdowns, `total_tokens` | The API reports thought tokens separately; Google's example total equals input + visible output + thought tokens. Tool-use tokens are a separate reported bucket and should be preserved, not guessed into an OpenAI field. [Interactions API `Usage`](https://ai.google.dev/api/interactions-api#resource:-usage), [thinking pricing](https://ai.google.dev/gemini-api/docs/thinking#pricing) |
| Gemini `generateContent` | `promptTokenCount`, `cachedContentTokenCount`, `candidatesTokenCount`, `toolUsePromptTokenCount`, `thoughtsTokenCount`, `totalTokenCount`, modality details | Available only on a native adapter. [GenerateContent `UsageMetadata`](https://ai.google.dev/api/generate-content#UsageMetadata) |

The pinned Verifiers `Usage` type stores uncached prompt tokens, completion tokens, optional
cached-input tokens, optional reasoning tokens, and optional cost. Its OpenAI conversion
subtracts cache hits from prompt tokens and treats reasoning as a subset of completion;
`Trace.usage` then sums provider-reported usage once per actual model call. [Usage type
and conversion](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/types.py#L114-L142),
[trace aggregation](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/trace.py#L445-L448)

Map Gemini usage as follows:

```text
prompt_tokens        = total_input_tokens - total_cached_tokens
cached_input_tokens = total_cached_tokens
completion_tokens   = total_output_tokens + total_thought_tokens
reasoning_tokens    = total_thought_tokens
```

Preserve `total_tool_use_tokens`, modality breakdowns, native `total_tokens`, and the raw
usage object in additional trace metadata. Assert the mapped total against the native
total in fixture tests rather than silently coercing a mismatch. Do not infer dollar
cost from token counts in the core trace; calculate cost later from a versioned pricing
table and preserve the provider invoice units.

Use task success and safety-rule compliance as the primary cross-model measures. Report
provider tokens, cached tokens, reasoning and thought tokens, latency, and dollars in
provider-specific columns. Do not rank models by "tokens used" across different
tokenizers or by Verifiers' normalized token total alone.

## Meaning of identical held-out scenarios

### Properties that can be identical

- Task IDs, the held-out split, the simulator seed, the initial apparatus state, and the
  fault schedule.
- Canonical system and user text content.
- Tool names, descriptions, canonical schemas, and tool result JSON.
- Client-side schema validation and deterministic error observations.
- The environment transition function and artifact checksums.
- Maximum model turns, accepted tool calls, state transitions, and the wall-clock
  deadline.
- No provider-native tools or external network access.
- Reward and metric code, success thresholds, and treatment of invalid, blocked, and
  truncated episodes.
- The number of rollouts per task and run-order randomization.
- Canonical transcript and scorer inputs.

### Properties that cannot be identical

- Serialized HTTP bodies, role wrappers, tool envelopes, or call IDs.
- Prompt templates, token IDs, tokenizer counts, or context-cache behavior.
- Hidden reasoning representation, token budget, or meaning of "medium" effort.
- Constrained-decoding implementation or safety filters.
- Sampling distribution, even at the same numeric temperature.
- Provider model size, training data, knowledge cutoff, or model tier.
- Backend hardware, batching, service latency, or rate-limit behavior.
- Provider updates behind an undated or stable identifier.
- Exact output-token cap semantics or dollar price.
- Local Gemma rendering compared with hosted-provider preprocessing.

The base-Gemma versus trained-Gemma comparison can be more controlled than the hosted
comparison. Hold the base checkpoint revision, tokenizer, renderer, vLLM configuration,
hardware, sampler, task order, and adapter stack constant. Change only the trained
weights or low-rank adaptation (LoRA) checkpoint. Report this within-family contrast
separately from the cross-provider ranking.

Thus, the defensible cross-provider claim is:

> Each model acts in the same deterministic held-out scientific environment, with the
> same canonical observations, action schemas, transition rules, budgets, and scoring.
> Provider-specific codecs preserve each API's required reasoning state. Model-visible
> serialization, tokenization, hidden reasoning, safety layers, and serving systems are
> not identical.

Always show adapter and protocol errors separately from scientific task failures. Otherwise
a broken Gemini adapter can be misreported as weak scientific reasoning.

## Pinning and run manifest

Pin and archive all of the following before opening the held-out split:

1. Verifiers commit `b878d009147876bfd1ba80feec770194f0b567c7`.
2. The new canonical runner and provider-adapter commit.
3. Exact harness dependency lock and container digest, including OpenAI SDK, Google SDK
   if used, MCP, HTTP client, and JSON-schema validator.
4. Exact requested model ID and route. Never use a `latest` or family alias.
5. Provider-returned model name or build where available, response and request IDs, OpenAI
   `system_fingerprint` where returned, service tier, and run UTC time.
6. Canonical prompt bytes, tool-schema hash, taskset hash, environment package hash,
   held-out split hash, and scorer hash.
7. Sampling profile, storage mode, context strategy, turn, tool, and time budgets, and rollout
   count.
8. Local Gemma checkpoint revision, tokenizer and renderer revision, vLLM and prime-rl
   versions, adapter checkpoint hash, and serving image and hardware metadata.
9. Provider documentation or model-card snapshot or content hash used to approve the run.

Use the following fields in a minimal per-run manifest:

```json
{
  "requested_model": "gpt-5.6-sol",
  "resolved_model": null,
  "provider": "openai",
  "route": "/v1/responses",
  "model_status": "exact-undated-id",
  "adapter_commit": "<sha>",
  "verifiers_commit": "b878d009147876bfd1ba80feec770194f0b567c7",
  "taskset_hash": "<sha256>",
  "tool_schema_hash": "<sha256>",
  "sampling_profile": "medium-default-sampling-v1",
  "store": false,
  "run_started_utc": "<timestamp>"
}
```

Populate `resolved_model` from the actual response and abort the run if a preflight
canary no longer matches the approved identifier policy. Run all hosted models in a
short, randomized, interleaved window to reduce time drift. Don't overwrite a prior run
when an alias or adapter changes.

## Concrete implementation route

### Run a non-scored Chat connectivity test

A *canary* is a small connectivity test that runs before the scored evaluation. The
following Verifiers configuration fragments exercise the null path without claiming
final comparability:

```toml
# OpenAI canary
model = "gpt-5.6-sol"
push = false

[client]
type = "eval"
base_url = "https://api.openai.com/v1"
api_key_var = "OPENAI_API_KEY"

[sampling]
reasoning_effort = "none" # required for current GPT Chat tool calling

[env.agent.harness]
id = "null"
```

```toml
# Gemini OpenAI-compatibility canary
model = "gemini-3.7-flash"
push = false

[client]
type = "eval"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
api_key_var = "GEMINI_API_KEY"

[sampling]
reasoning_effort = "low" # Gemini 3.7 cannot use none or minimal

[env.agent.harness]
id = "null"
```

Omit temperature, top-p, seed, and Verifiers `sampling.max_tokens` in this canary. Put
identical external turn, tool, and time limits in the shared environment configuration.
Before using
the Gemini compatibility result even as a diagnostic, verify with a credentialed
one-task probe that assistant thought-signature fields survive two tool turns and that
reported usage includes the expected thought bucket. That probe was intentionally not
run during this research.

### Add the scored provider adapters

Implement a shared `ScientificToolHarness` with the following transport adapters:

- `openai_responses`
  - Use the registered `ResponsesDialect`.
  - Add a minimal loop that emits Responses input items and consumes function-call items.
  - Set `store=false`, preserve every output item, and send function outputs by `call_id`.
  - Record the provider response model ID and full usage before `Response.raw` is
    discarded.
- `gemini_interactions`
  - Add a dialect for the local interception route `/v1/interactions` and the upstream
    route `/v1beta/interactions`.
  - Override both the local secret carrier and upstream authentication to use
    `x-goog-api-key`.
  - Parse and serialize user input, model output, thought, function-call, and
    function-result steps without modifying signed thought blocks.
  - Map Gemini status, safety, and usage into normalized fields while retaining native
    metadata.
  - Support non-streaming requests first. Add streaming only after the non-streaming
    conformance tests pass.
- `openai_chat`
  - Retain this adapter for local vLLM and Gemma.
  - Use the same canonical tools, validator, result serializer, and budget controller.

The canonical runner, not the provider SDK, must execute MCP tools. It assigns canonical
call ordinals, validates arguments, implements idempotency, applies stop limits, and
writes the provider-neutral transcript.

### Gate the held-out run on conformance fixtures

No paid calls are needed for adapter unit tests. Use recorded synthetic wire fixtures to
prove:

- One and multiple function calls round-trip in order.
- Invalid JSON or object arguments receive the same canonical error.
- OpenAI encrypted reasoning items and Gemini signed thought steps are byte-for-byte
  present on the next turn.
- Tool results retain the correct provider call link.
- Native and normalized usage totals reconcile.
- Blocked, incomplete, context-limit, and malformed responses are distinct.
- Resolved model and provider request metadata persist in traces.
- An MCP retry does not duplicate a simulator transition.

After those pass, run a credentialed one-scenario canary per hosted provider, inspect the
full trace manually, and only then open the frozen held-out evaluation. The canary must
not be part of the held-out score.

## Bottom line

`gpt-5.6-sol` and stable `gemini-3.7-flash` are the exact current identifiers recommended
for the main current-model comparison. Use OpenAI Responses and Gemini Interactions,
not a supposedly neutral Chat route, because the providers' reasoning and continuation
requirements are materially different. The pinned Verifiers commit supplies most of the
OpenAI Responses relay and parser and the deterministic environment boundary, but it does
does not supply the two scored harness adapters or native Gemini support. Until that adapter
work and conformance testing exist, Verifiers' null harness can demonstrate endpoint
connectivity, not a fair frozen frontier benchmark.
