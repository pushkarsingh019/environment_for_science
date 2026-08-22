# Prime Intellect Verifiers and prime-rl fit

Research date: 2026-08-22

Sources inspected at:

- `PrimeIntellect-ai/verifiers` commit [`b878d009`](https://github.com/PrimeIntellect-ai/verifiers/tree/b878d009147876bfd1ba80feec770194f0b567c7)
- `PrimeIntellect-ai/prime-rl` commit [`1e756307`](https://github.com/PrimeIntellect-ai/prime-rl/tree/1e756307ae7b29c31fd202e6fac9afd7e23db18b)

## Bottom line

Prime Intellect is a strong backend fit for the prototype, but it does not provide the visual environment-authoring product being proposed here.

Use the current **Verifiers v1** taskset, harness, toolset, and trace APIs as a generated execution target. Keep a versioned, Prime-independent environment specification as this product's source of truth. Compile that specification into a native Verifiers v1 package and prime-rl configuration.

`verifiers` and `prime-rl` are separate projects maintained by Prime Intellect. They are tightly integrated, but the verifier library does not itself contain a trainer. `prime-rl` supplies the trainer, inference server, and orchestrator. Sources: [Verifiers README](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/README.md), [prime-rl architecture](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/overview.md).

The current Hosted Training model list does not include Gemma, so the Gemma demonstration should target **self-managed prime-rl**, not assume Prime Hosted Training can run it. The exact Gemma 4 training path is plausible but not documented or validated by an official Gemma recipe; it needs an early smoke test before choosing the final checkpoint size. Source: [Verifiers training guide and hosted-model list](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/legacy/training.md).

## What the current Verifiers API provides

Verifiers v1 models work as:

- a **Taskset** loads train and evaluation tasks;
- each **Task** owns lifecycle behavior, tools, metrics, and rewards;
- a **Harness** is the program in which the model acts;
- an **Agent** is harness × model × runtime policy;
- an **Environment** controls one or more agents;
- a **Trace** records the message graph, model calls, rewards, metrics, errors, timing, tokens, and log probabilities.

Sources: [v1 overview](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/v1/overview.md), [taskset guide](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/v1/tasksets.md), [trace implementation](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/trace.py).

New work should target `verifiers.v1`; the older `Environment`, `ToolEnv`, `Rubric`, and `load_environment()` API is deprecated. Sources: [documentation router](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/overview.md), [official environment-authoring skill](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/skills/create-environments/SKILL.md).

## Mapping the proposed product to Verifiers v1

| Product concept | Verifiers target |
| --- | --- |
| One generated failure or procedure scenario | `TaskData` + `Task` |
| EEG or mesoscope scenario family | `Taskset` with deterministic train/eval splits |
| Apparatus observations and actions | `Toolset` exposed to the model through MCP |
| Per-episode simulated apparatus state | Typed `vf.State` isolated per rollout |
| Deterministic checks | `@vf.reward` functions |
| Diagnostic measurements | `@vf.metric` functions |
| Model's tool-using loop | Built-in `null` harness initially |
| Complete episode record | `Trace` |
| Training run | prime-rl orchestrator + inference + trainer |

Verifiers' built-in `null` harness already runs an OpenAI-style tool-use loop, exposes MCP tools to the model, executes tool calls, and continues until the model stops calling tools. This is a direct fit for a simulated apparatus. Sources: [`NullHarness`](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/harness.py), [its tool loop](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/harnesses/null/program.py).

Writable shared tool servers can maintain isolated per-rollout state through typed `vf.State`. Prime's scratchpad example demonstrates one shared server whose concurrent rollouts cannot see each other's state. Source: [scratchpad toolset](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/environments/scratchpad/scratchpad/servers/scratchpad.py).

## Evaluation fit

The v1 evaluation client accepts an OpenAI-compatible `base_url`, API-key environment variable, and headers. The interception server captures model interactions while relaying them to the configured provider. This makes a fixed taskset/harness suitable for comparable runs across hosted and local models, provided each endpoint supports the required tool-calling contract. Sources: [client configuration](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/configs/client.py), [evaluation client](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/verifiers/v1/clients/eval.py), [evaluation guide](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/v1/evaluation.md).

The product should pin identical scenario seeds, harness configuration, tool schemas, sampling parameters, and reward functions across Gemini, GPT, base Gemma, and trained Gemma. Provider-specific adapters must be tested rather than assuming identical tool-call behavior.

## Training fit

prime-rl provides an end-to-end asynchronous stack with:

- vLLM-backed policy inference;
- a Verifiers-aware rollout orchestrator;
- an FSDP2 trainer;
- SFT, GRPO, LoRA, evaluation, checkpointing, and weight updates.

GRPO is the default RL algorithm. Training sources and held-out evaluation sources can use separate taskset splits in one configuration. Sources: [prime-rl README](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/README.md), [training guide](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/training.md), [environment configuration](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/configuration.md), [algorithms](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/algorithms.md).

Prime's maintained Alphabet Sort example demonstrates multi-turn LoRA RL with the `null` harness, a continuous verifier reward, baseline evaluation, and post-training evaluation. That is the nearest first-party pattern for this prototype. Source: [Alphabet Sort example](https://github.com/PrimeIntellect-ai/prime-rl/tree/1e756307ae7b29c31fd202e6fac9afd7e23db18b/examples/basic/alphabet-sort).

The environments must be calibrated before training. Prime recommends avoiding baselines that always fail or already solve nearly everything, using groups of at least eight rollouts, and preserving reward variation within each group. Source: [training rules of thumb](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/training.md).

## Gemma 4 caveat

There is no official Gemma 4 prime-rl example or explicit validated model-support row.

Evidence in favor:

- prime-rl states that generic Hugging Face causal language models can use its HF implementation;
- current source recognizes `gemma4` as a vision-language architecture;
- the generic model loader falls back to Hugging Face `AutoModelForImageTextToText` for a recognized VLM without a Prime custom implementation;
- prime-rl supports generic LoRA target modules and vLLM inference passthrough.

Sources: [model-support statement](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/README.md), [Gemma 4 registry entry](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/utils/vlm.py), [model loader](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/trainer/model.py).

Evidence requiring caution:

- Gemma 4 has no registered Prime custom VLM implementation;
- prime-rl explicitly rejects configured VLM training for architectures without such a custom implementation;
- the documented hand-written renderer families do not include Gemma, so Gemma uses the generic renderer unless support is added;
- Hosted Training's supported-model list does not include Gemma.

Sources: [custom VLM map and loader checks](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/trainer/model.py), [renderer support list](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/docs/algorithms.md), [Hosted Training list](https://github.com/PrimeIntellect-ai/verifiers/blob/b878d009147876bfd1ba80feec770194f0b567c7/docs/legacy/training.md).

Therefore, do not make the demo depend on untested 31B training. First smoke-test a text-only, multi-turn, tool-using LoRA RL run against the selected Gemma 4 checkpoint. Keep a smaller Gemma checkpoint as a fallback while retaining 31B as a stretch target.

## What Prime Intellect does not supply

The inspected projects do not provide:

- a no-code visual authoring canvas;
- manual-to-apparatus extraction;
- a scientific instrument catalog;
- apparatus simulators;
- generation or validation of scientifically correct rewards;
- real-hardware connectors or safety certification.

Those are the proposed product's responsibility and likely its differentiating layer.

## Recommended boundary

1. Store the scientist-authored design in a versioned, Prime-independent `EnvironmentSpec`.
2. Run that spec in this product's deterministic simulator.
3. Compile scenarios into a native Verifiers v1 taskset package.
4. Compile simulated observations and actions into a stateful MCP `Toolset`.
5. Compile success and safety rules into deterministic `@vf.reward` and `@vf.metric` hooks.
6. Use Verifiers for evaluation and traces.
7. Use self-managed prime-rl for Gemma LoRA GRPO.
8. Treat the Prime Environment Hub and Hosted Training as optional publication and execution targets, not the source of truth.

## Required early probes

Before the final model and training plan are locked:

1. Scaffold and validate one native v1 tool-using taskset.
2. Evaluate one fixed episode through the `null` harness.
3. Run the same episode through one hosted frontier model and base Gemma.
4. Smoke-test Gemma tool-call rendering through prime-rl's training client.
5. Dry-run and then execute a minimal Gemma LoRA GRPO job.
6. Verify checkpoint loading and held-out evaluation.
