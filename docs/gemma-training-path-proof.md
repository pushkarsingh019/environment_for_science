# Gemma 4 training-path proof plan

Date: 2026-08-22
Ticket: `03-prove-the-gemma-4-training-path`
Status: **resolved on 2026-08-24.** The exact E4B snapshot completed the disposable
mechanical smoke, a product-owned EEG optimization step, and independent fresh reload/evaluation
on a second approved workstation. The fail-closed product evidence was imported and reverified.

## Decision

Use **`google/gemma-4-E4B-it` as the primary training checkpoint** and
**`google/gemma-4-E2B-it` as the smaller fallback**. Keep
`google/gemma-4-31B-it` as an evaluation/serving stretch target, not as the
first self-managed training run.

The smallest viable stack is not prime-rl's checkout unchanged. The prime-rl
commit pins a `renderers` submodule that predates Gemma 4 support. The training
smoke must override that submodule to the exact later Gemma renderer commit
listed below. With that override, the complete text-first Gemma message → token
→ tool call → tool result → next turn → training-sample path was exercised
locally against a fake token-in server.

The resolution gate required the GPU acceptance sequence in this document to train
an adapter, write both checkpoint forms, prove adapter tensors changed, unload and
reload the saved adapter independently, and complete the disjoint held-out evaluation.
That gate now passes; logs alone were not used as proof.

## Claim ledger

### Proved locally

- Verifiers v1 can run the `null` harness through its env-server path with a
  shared stateful Model Context Protocol (MCP) tool. Two concurrent rollouts
  each produced `user → assistant(tool call) → tool → assistant`, two model-call
  records, reward `1.0`, and serialized `Trace.version == 1` records.
- The exact Verifiers revision pinned by prime-rl produced a Gemma-rendered
  multi-turn trace with token IDs, sampled masks, aligned per-sampled-token
  log probabilities, a structured tool call, tool output, and final answer.
- prime-rl's `trace_to_samples()` accepted that saved trace and produced one
  `TrainingSample`: 180 total tokens, 20 trainable tokens, and 20 non-zero
  inference-logprob entries.
- The Gemma renderer at `f770dcaa...` matches the official E4B chat template for
  a full tool cycle, parses Gemma's compact typed arguments, and bridges the
  tool response into the next turn. The pinned E4B tokenizer snapshot was the
  expected Hugging Face (HF) revision.
- The disposable taskset in `probes/gemma-training-path/taskset/` has disjoint
  train/eval keys and passed setup validation for all 4 train and 2 eval rows.
- The three checked Gemma configs instantiate on the PyTorch meta device under
  Transformers 5.6.2 with prime-rl's expected `model.vision_tower`,
  `model.language_model`, and `lm_head` attributes.
- The supplied inference, RL, and held-out eval configs validate through the
  pinned prime-rl/Verifiers schemas when the Gemma renderer override is active.
- No credential was required or read. Only configs/tokenizers and source were
  downloaded; no model weights were downloaded.

### Supported by inspected source, not executed end to end

- prime-rl recognizes `model_type="gemma4"`, uses Hugging Face
  `AutoModelForImageTextToText` when no custom Prime VLM implementation exists,
  and treats a Gemma checkpoint with `[model.vlm]` absent as text-only data.
- Text-first LoRA freezes non-adapter parameters. Restricting targets to
  `model.language_model.layers.*` excludes Gemma's vision and audio towers.
- Group relative policy optimization (GRPO) is the default orchestrator
  algorithm. The renderer client is the training client and carries exact token
  IDs and log probabilities into traces.
- Filesystem LoRA broadcasts write a Hugging Face parameter-efficient
  fine-tuning (PEFT) adapter as `adapter_model.safetensors`,
  `adapter_config.json`, and `STABLE`. Trainer checkpoints separately write
  resume-capable PyTorch distributed checkpoint (DCP) state.
- prime-rl's inference wrapper forces in-place same-name LoRA reloads, while
  vLLM 0.26.0 registers Gemma 4 model, tool-parser, and LoRA support.
- The default file monitor persists episode/trace JSONL including messages,
  tools, model calls, rewards, timing, token IDs, masks, and log probabilities.

### Proved with CUDA compute

- HF Gemma 4 forward/backward, FSDP2, BF16 reduction, and Flash Attention 2 ran on
  an approved Linux x86_64 SM120 workstation with the pinned E4B snapshot.
- The complete E4B vLLM policy and truncated two-layer trainer co-resided on one
  96 GB card over loopback-only transport.
- Real token-in log probabilities produced finite optimization metrics. The EEG
  acceptance step recorded loss `0.2082010805606842`, gradient norm `0.091796875`,
  and mismatch KL `23.28827476501465`; these are observations, not thresholds.
- DCP state contained two non-empty files. Both PEFT broadcasts contained 28
  language-layer tensors, and 14 tensors changed after the optimizer step.
- A fresh `proof-final` reload completed both disjoint EEG development scenarios;
  their baseline and reloaded runs reached canonical terminals with tool loops,
  Runtime evidence, and no provider, adapter, tool, or trace errors.
- The portable adapter was transferred byte-for-byte to a distinct approved inference
  workstation, loaded into a fresh process, and independently completed those same
  predeclared scenarios with 9 and 10 linked tool-result nodes and no trace errors.
- The product verifier independently re-read the full evidence tree, found 14 changed
  language-layer tensors, parsed the DCP metadata and ZIP64 shard structure, replayed every
  canonical scientific snapshot, checked every model-call identity, and recorded authoritative
  version-2 artifact digest
  `sha256:13839168b5f4e23f37d6f3a89ec50c51bebbd6a4be4fa888fcc5b0839a007620`.

### Still not claimed

- Full-layer E4B training, 31B training, curriculum-level quality, or scientific-task
  improvement. Those remain Ticket 11 concerns.

## Exact stack

Use the prime-rl lockfile rather than resolving fresh package versions.

<!-- markdownlint-disable MD013 -->

| Component | Exact pin / assumption | Reason |
| --- | --- | --- |
| prime-rl | [`1e756307ae7b29c31fd202e6fac9afd7e23db18b`](https://github.com/PrimeIntellect-ai/prime-rl/tree/1e756307ae7b29c31fd202e6fac9afd7e23db18b), source package `0.8.0` (`git describe`: `v0.8.1.dev66`) | Inspected trainer, orchestrator, inference, checkpoint, and monitor source. |
| Verifiers used by training | prime-rl submodule [`4bcb48e55a35c199d9d2f9722060fda627306aa3`](https://github.com/PrimeIntellect-ai/verifiers/tree/4bcb48e55a35c199d9d2f9722060fda627306aa3) | This is the revision the prime-rl lock and source tree actually consume. |
| Separately audited Verifiers head | [`b878d009147876bfd1ba80feec770194f0b567c7`](https://github.com/PrimeIntellect-ai/verifiers/tree/b878d009147876bfd1ba80feec770194f0b567c7) | One commit ahead of `4bcb48e`; the only `verifiers/v1` change is `runtimes/prime.py`. Local subprocess behavior is unchanged. Do not substitute it into the remote locked run. |
| renderers | override submodule to [`f770dcaa362e3a6a13a96f039741b3b84ca4114e`](https://github.com/PrimeIntellect-ai/renderers/commit/f770dcaa362e3a6a13a96f039741b3b84ca4114e) (`0.1.10.dev11`) | First descendant inspected that adds the typed Gemma 4 renderer, parser, bridge, mappings, and tests. |
| prime-pydantic-config | submodule [`65b15dffba82d4be19efdaf8b2b9705cc1756be8`](https://github.com/PrimeIntellect-ai/pydantic-config/tree/65b15dffba82d4be19efdaf8b2b9705cc1756be8), `0.4.3` | prime-rl config dependency. |
| Python | CPython `3.12.*`; local probe used `3.12.13` | prime-rl requires `~=3.12.0`; its lock is Python 3.12 only. |
| uv | `0.11.1` for the handoff (`>=0.11.1` required) | Reads the repository lock and its supply-chain cutoff syntax. |
| Transformers | `5.6.2` | Exact prime-rl dependency; local tokenizer/meta-model probes used it. |
| PyTorch | lock: `2.11.0+cu128`; local structure probe: CPU `2.11.0` | Exact trainer ABI in `uv.lock`. |
| vLLM | lock: `0.26.0+cu129`, x86 wheel SHA-256 `7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf`; tag source commit [`568afb3a13806beb53bb2e6bd518269357b237c0`](https://github.com/vllm-project/vllm/tree/568afb3a13806beb53bb2e6bd518269357b237c0) | This exact tag contains `Gemma4ForConditionalGeneration`, `Gemma4EngineToolParser`, and Gemma LoRA mappings. |
| Flash Attention | `2.8.3+cu128torch2.11`, x86 wheel SHA-256 `a16162f436286cc03ebbfb174c0853343ed98ae13c37abf1042947668ec40549` | prime-rl resolves `attn="auto"` to FA2 on SM120. Install only the `flash-attn` extra for this smoke. |
| Other key locked packages | pydantic `2.13.4`, numpy `2.3.5`, OpenAI `2.38.0`, MCP `1.27.1`, tokenizers `0.22.2`, safetensors `0.7.0`, msgspec `0.21.1` | Used by config, harness, renderer, trace, and transport paths. |
| Target platform | Linux `x86_64`, NVIDIA CUDA GPU; no macOS training | prime-rl's lock declares Linux x86_64/aarch64 environments only. |

<!-- markdownlint-enable MD013 -->

### Hardware and runtime assumptions

The primary smoke assumes one NVIDIA RTX PRO 6000 Blackwell 96 GB GPU
(compute capability SM120), at least 64 GiB available host RAM, and at least
100 GiB free disk. The serving research records driver `610.43.02`; the remote
run must record the actual driver rather than silently treating that value as
verified in this lane. prime-rl's container source uses CUDA 12.8.1, its locked
PyTorch wheels use CUDA 12.8, and its locked vLLM wheel uses CUDA 12.9. The
preflight stops before the model download if the GPU, memory, disk, or platform
assumptions don't hold.

The one-card arrangement is deliberately non-default: start standalone
inference first, and then run `rl` with only one trainer GPU and no managed
inference block. Both processes use GPU 0 and communicate over loopback. The
source accepts this arrangement, but the memory fit remains a GPU-smoke result,
not a source-backed guarantee.

### Source anchors

- Gemma detection, generic HF loading, text-only tower freezing, LoRA setup, and
  the Gemma-3-only buffer allowlist:
  [`trainer/model.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/trainer/model.py)
  and [`utils/vlm.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/utils/vlm.py).
- LoRA targeting/config emission and PEFT filesystem broadcast:
  [`trainer/lora.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/trainer/lora.py)
  and [`transports/weights/filesystem.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/transports/weights/filesystem.py).
- DCP resume state, inference adapter reload, and local trace persistence:
  [`trainer/ckpt.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/trainer/ckpt.py),
  [`inference/vllm/server.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/inference/vllm/server.py),
  and [`monitors/file.py`](https://github.com/PrimeIntellect-ai/prime-rl/blob/1e756307ae7b29c31fd202e6fac9afd7e23db18b/src/prime_rl/monitors/file.py).
- Training-native trace schema/client:
  [`trace.py`](https://github.com/PrimeIntellect-ai/verifiers/blob/4bcb48e55a35c199d9d2f9722060fda627306aa3/verifiers/v1/trace.py)
  and [`clients/train.py`](https://github.com/PrimeIntellect-ai/verifiers/blob/4bcb48e55a35c199d9d2f9722060fda627306aa3/verifiers/v1/clients/train.py).
- Typed Gemma rendering/parsing/bridging:
  [`renderers/gemma4.py`](https://github.com/PrimeIntellect-ai/renderers/blob/f770dcaa362e3a6a13a96f039741b3b84ca4114e/renderers/gemma4.py)
  and its [focused tests](https://github.com/PrimeIntellect-ai/renderers/blob/f770dcaa362e3a6a13a96f039741b3b84ca4114e/tests/test_gemma4.py).
- Exact vLLM model, parser, and LoRA declarations:
  [`gemma4_mm.py`](https://github.com/vllm-project/vllm/blob/568afb3a13806beb53bb2e6bd518269357b237c0/vllm/model_executor/models/gemma4_mm.py),
  [`gemma4_engine_tool_parser.py`](https://github.com/vllm-project/vllm/blob/568afb3a13806beb53bb2e6bd518269357b237c0/vllm/tool_parsers/gemma4_engine_tool_parser.py),
  and [`lora/model_manager.py`](https://github.com/vllm-project/vllm/blob/568afb3a13806beb53bb2e6bd518269357b237c0/vllm/lora/model_manager.py).

### Why the renderer override is mandatory

prime-rl's recorded renderer submodule is
`2846a3dcd29318c1fc98de3498bab4190997af9e`. Its model map has no Gemma ID,
its renderer union has no `name="gemma4"`, and it has no Gemma parser. An exact
config probe against that revision failed validation. The same config against
`f770dcaa...` resolved `google/gemma-4-E4B-it → gemma4` and passed.

This matters specifically for training. The vLLM `--tool-call-parser gemma4`
handles chat-completions evaluation, but prime-rl training calls the token-in
endpoint and parses completion tokens client-side through `renderers`. An
engine parser cannot repair a missing training renderer.

### Audited bounded compatibility patch

The first real GPU run exposed two deterministic prime-rl seams that the earlier
meta-model probe could not execute. Dense Gemma 4 declares nullable MoE fields;
the eager packing-cost expression multiplied `None` even though the model has zero
MoE layers. The two-layer debug load also needed Transformers' existing
`ignore_mismatched_sizes` path because Gemma 4 sizes two per-layer coupling tensors
from the configured layer count. The checked patch fixes only those bounded seams,
is stored at
`probes/gemma-training-path/patches/prime-rl-gemma4-bounded-compatibility.patch`,
and has SHA-256
`5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3`.
The prime-rl base revision remains unchanged and is recorded alongside the patch.

## Checkpoint choice

<!-- markdownlint-disable MD013 -->

| Role | Checkpoint and revision | Weight bytes | Transformers 5.6.2 meta-model parameters | Decision |
| --- | --- | ---: | ---: | --- |
| Primary training | [`google/gemma-4-E4B-it@ee0ef6023621cff504d758262d4e04895a5af4a2`](https://huggingface.co/google/gemma-4-E4B-it/commit/ee0ef6023621cff504d758262d4e04895a5af4a2) | 15,992,595,884; Xet/SHA-256 `cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503` | 7,941,100,832 | First GPU smoke and intended hackathon training size. |
| Smaller fallback | [`google/gemma-4-E2B-it@3e22461f65e89153144f8adb70e3b8c2cc9845a7`](https://huggingface.co/google/gemma-4-E2B-it/commit/3e22461f65e89153144f8adb70e3b8c2cc9845a7) | 10,246,621,918; Xet/SHA-256 `2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550` | 5,104,297,504 | One bounded retry only if E4B fails a memory gate. |
| Stretch, not first training run | [`google/gemma-4-31B-it@842da3794eaa0b77d5f08bae87a17459d91ff475`](https://huggingface.co/google/gemma-4-31B-it/commit/842da3794eaa0b77d5f08bae87a17459d91ff475) | 62,546,338,248 | 31,273,086,512 | Retain for serving/evaluation; do not make the training demo depend on it. |

<!-- markdownlint-enable MD013 -->

The meta-model count is `sum(model.parameters())` after config-only construction;
it is not the model-card active-parameter label or safetensors-index count.

E4B is the smallest reasonable primary rather than merely a fallback. prime-rl
runs inference and training concurrently. Two raw BF16 E4B checkpoint copies
are about 32.0 GB before KV cache, activations, kernels, and workspaces. Two raw
31B copies are about 125.1 GB, already larger than one 96 GB card before any
runtime allocation. prime-rl's normal local launcher also assigns inference and
trainer distinct local GPU IDs. The available cards are reported as being on
separate workstations; no shared filesystem or supported non-SLURM cross-host
LoRA broadcast has been proved. This plan therefore tests manual same-card E4B
co-location and does not assume an unproved two-host topology.

Do not substitute 12B as the fallback. Its `gemma4_unified` architecture is
supported by vLLM 0.26, but it is absent from the inspected prime-rl VLM
registry and from the pinned Gemma renderer's exact model map.

## Required configuration details

### Text-first, not configured VLM training

Leave `[model.vlm]` **unset**. Setting it asks for multimodal training and
prime-rl rejects Gemma because there is no registered custom Prime VLM class.
With it unset, source recognizes the composite `gemma4` architecture, uses the
HF image-text model, freezes non-adapter parameters, and trains text tokens.
The smoke also sets vLLM's per-prompt image/audio/video limits to zero.

### No speculative decoding

Don't load a Gemma assistant or enable multi-token prediction (MTP) in this
training proof. The smoke needs the smallest memory footprint and exact sampled
token log probabilities from the live policy. MTP serving performance is a
separate concern and doesn't help prove LoRA GRPO compatibility.

### Language-only LoRA target

Use the exact regex in
`probes/gemma-training-path/configs/e4b-one-step-rl.toml`:

```toml
target_modules = ['^model\.language_model\.layers\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$']
```

The generic prime-rl defaults match nested tower linears too. Config-only
inspection at rank 8 found:

<!-- markdownlint-disable MD013 -->

| Checkpoint | Language targets / adapter params | Vision targets / adapter params | Audio targets / adapter params |
| --- | ---: | ---: | ---: |
| E4B | 258 / 17,440,768 | 112 / 2,260,992 | 36 / 589,824 |
| E2B | 205 / 12,079,104 | 112 / 2,260,992 | 36 / 589,824 |
| 31B | 410 / 61,214,720 | 189 / 5,526,144 | none |

<!-- markdownlint-enable MD013 -->

Tower targets can produce keys ending in nested `.linear` that the text LoRA
loader does not expect. The regex removes them instead of relying on vLLM to
ignore unused tensors.

### BF16 must be explicit

`TrainerModelConfig.optimization_dtype` defaults to float32. The VLM BF16
validator only activates when `[model.vlm]` is set, which this text-first path
intentionally does not do. Set both optimization and reduction dtype to BF16 as
in the checked config.

### Pin a local model snapshot

prime-rl's model config has no HF `revision` field. Passing only a repository ID
would follow whatever `main` means at execution time. Download the exact
revision into an immutable local directory, verify the weight size/hash, and
point trainer, inference, tokenizer, and evaluation at that directory. Because
the local path cannot hit the renderer's exact-ID map, explicitly select
`[orchestrator.renderer] name="gemma4"` and explicitly set vLLM
`tool_call_parser="gemma4"`.

### Two checkpoint forms have different jobs

- `checkpoints/step_1/trainer/` is a sharded PyTorch DCP checkpoint for training
  resume. It is not the artifact to hand directly to vLLM.
- `broadcasts/step_1/` is the HF-compatible PEFT adapter with a `STABLE`
  marker. This is the artifact to unload/reload for held-out evaluation.

The verifier script checks both, validates the eight effective training traces,
and compares `broadcasts/step_0` with `step_1` to prove an optimizer step
changed at least one tensor.

## Local probe record

Local host: macOS arm64 with no NVIDIA GPU or Docker. Disposable CPython
3.12.13 and CPU PyTorch 2.11.0 were used. The prime-rl CUDA trainer itself could
not be imported/executed safely on this platform.

<!-- markdownlint-disable MD013 -->

| Probe | Result |
| --- | --- |
| Source heads | prime-rl `1e756307...`; its Verifiers `4bcb48e...`; audited Verifiers `b878d009...`; renderer override `f770dcaa...`. |
| Verifiers env-server + `null` + shared MCP against fake chat endpoint | 2/2 concurrent episodes passed; each had 2 calls, 4 nodes, one advertised tool, and reward 1.0. |
| Gemma renderer focused tests | `14 passed, 5 deselected` (text/tool tests only; image tests intentionally excluded). |
| Direct E4B template/parser/bridge | 83-token tool-cycle render equaled HF `apply_chat_template`; parsed `inspect(slot="A")`; bridge returned 80 tokens. Snapshot directory was `ee0ef602...`. |
| Exact pinned Verifiers train client + fake Gemma token endpoint | 1/1 held-out episode passed under `4bcb48e...`; roles were `user, assistant, tool, assistant`; 20 sampled tokens had 20 logprobs. |
| prime-rl trace compilation | 1 training sample, 180 tokens, 20 trainable, 20 non-zero logprobs. |
| Disposable taskset setup | Train 4/4 valid; held-out 2/2 valid; task keys disjoint. |
| Full disposable train-client probe | 2/2 held-out episodes passed with canonical Gemma tokens, protocol reward 1.0, aligned masks/logprobs, and 4 token-in requests. |
| Configuration parsing | Inference, one-step RL, and held-out eval configurations passed with renderer `f770dcaa...`; the recorded renderer pin failed. |
| Meta architecture | E4B, E2B, and 31B exposed the expected Gemma module seams and non-empty language LoRA targets. The configured two-layer E4B trainer shape instantiated with 1,470,856,224 parameters and 951 buffers. |

<!-- markdownlint-enable MD013 -->

A notable source risk surfaced: `can_reinit_empty_buffers()` allowlists Gemma 3
buffer layouts, not Gemma 4. The local meta probe found 991 buffers for E4B,
984 for E2B, and 67 for 31B, so all miss that allowlist. The configured
two-layer E4B shape still has 951 buffers and also misses it. prime-rl will fall
back to CPU model materialization before FSDP instead of the cheaper meta-device
load. This is why the remote handoff requires ample host RAM and tries E4B
before any 31B training attempt.

## Smallest decisive GPU acceptance test

Use the disposable taskset only to answer compatibility. One step, two trainer
layers, rank-8 LoRA, group size 8, 1024-token context, and separate baseline and
post-reload held-out evals are sufficient. The trace-ID-derived reward has
weight `0.001` only in training to provide per-trace GRPO reward variation; it remains
weight `0` in eval. It is deliberately invalid as benchmark evidence.

All of the following must pass:

1. Inference starts with the exact E4B snapshot and reports the Gemma parser and
   LoRA enabled.
2. Baseline held-out eval completes both disjoint scenarios; every episode has
   a real tool loop and no trace error.
3. All eight effective training traces complete a tool loop, retain aligned
   token masks and log probabilities, and contain more than one jitter score.
4. One GRPO step completes with finite loss, finite grad norm, and finite
   mismatch KL (record the value; do not invent a threshold in this ticket).
5. `broadcasts/step_0` and `broadcasts/step_1` are stable PEFT adapters, and at
   least one tensor differs.
6. `checkpoints/step_1/trainer/` is a non-empty DCP checkpoint.
7. The training adapter is unloaded; `broadcasts/step_1` is loaded under the
   fresh served name `proof-final`.
8. Held-out eval against `proof-final` completes both scenarios with tool loops
   and no trace error.
9. `verify_smoke_artifacts.py` exits 0.

Reward improvement is not an acceptance criterion for this compatibility
smoke and must not be claimed from two mechanical scenarios.

## Bounded secure remote handoff

Run this only later, through an approved SSH-key session. Do not use password
authentication, inspect unrelated host files, change system packages, expose a
port beyond loopback, or copy any credential into logs. The commands below do
not need a Hugging Face token because the selected Google repositories are
public.

### Connect with key-only authentication

The executor must provide `SSH_KEY_PATH`, `REMOTE_USER`, and `REMOTE_HOST`
through the approved secure channel. Verify the host fingerprint out of band.
Don't write these values to this repository or the run logs.

```bash
ssh \
  -o BatchMode=yes \
  -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -i "$SSH_KEY_PATH" \
  "$REMOTE_USER@$REMOTE_HOST"
```

The remaining commands run inside that key-authenticated shell. They don't
read or modify an SSH host inventory.

### 0. Read-only gate — stop before downloads

Assumptions for the primary attempt:

- Linux x86_64;
- one idle RTX PRO 6000-class 96 GB CUDA GPU;
- at least 64 GiB `MemAvailable`;
- at least 100 GiB free in the chosen root;
- existing `git`, `curl`, `sha256sum`, `timeout`, and uv `>=0.11.1`;
- no system installation or daemon change is needed.

```bash
set -euo pipefail
ROOT="$HOME/gemma-training-proof"
mkdir -p "$ROOT"

uname -srm
command -v git curl sha256sum timeout uv nvidia-smi
uv --version
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
awk '/MemAvailable/ {print $2}' /proc/meminfo
df -Pk "$ROOT"
```

Stop if the platform or GPU differs, any compute process is active, available RAM
is below `67108864` KiB, or free disk is below `104857600` KiB. Save this output
as the run sheet. Obtain an explicit go-ahead before the 16 GB model download.

### 1. Materialize exact source without remote mutation

`PROJECT` must be a securely transferred copy of this repository containing
`probes/gemma-training-path/`; these files may not yet exist in its remote Git
branch.

```bash
export ROOT="$HOME/gemma-training-proof"
export PROJECT="$ROOT/src/environments_for_science"
export PRIME="$ROOT/src/prime-rl"
mkdir -p "$ROOT/src" "$ROOT/cache/hf" "$ROOT/logs" "$ROOT/models"

if [ ! -d "$PRIME/.git" ]; then
  timeout 10m git clone https://github.com/PrimeIntellect-ai/prime-rl.git "$PRIME"
fi
git -C "$PRIME" checkout --detach 1e756307ae7b29c31fd202e6fac9afd7e23db18b
timeout 15m git -C "$PRIME" \
  -c url.https://github.com/.insteadOf=git@github.com: \
  submodule update --init --recursive
RENDERERS_URL=https://github.com/PrimeIntellect-ai/renderers.git
timeout 5m git -C "$PRIME/deps/renderers" fetch "$RENDERERS_URL" \
  f770dcaa362e3a6a13a96f039741b3b84ca4114e
git -C "$PRIME/deps/renderers" checkout --detach \
  f770dcaa362e3a6a13a96f039741b3b84ca4114e

test "$(git -C "$PRIME" rev-parse HEAD)" = 1e756307ae7b29c31fd202e6fac9afd7e23db18b
test "$(git -C "$PRIME/deps/verifiers" rev-parse HEAD)" = 4bcb48e55a35c199d9d2f9722060fda627306aa3
test "$(git -C "$PRIME/deps/renderers" rev-parse HEAD)" = f770dcaa362e3a6a13a96f039741b3b84ca4114e
```

### 2. Sync the locked Linux environment

Do not run the repository installer: it performs apt/sudo and unrelated host
changes. Use the existing uv directly.

```bash
cd "$PRIME"
timeout 30m uv sync --locked --package prime-rl --extra flash-attn
# Standalone inference requires the router already pinned in uv.lock, while the
# disaggregated extra would install unrelated transport packages.
timeout 5m uv pip install --no-deps \
  'vllm-router @ https://github.com/PrimeIntellect-ai/router/releases/download/v0.2.0/vllm_router-0.2.0-cp38-abi3-manylinux_2_28_x86_64.whl'
git -C "$PRIME" apply \
  "$PROJECT/probes/gemma-training-path/patches/prime-rl-gemma4-bounded-compatibility.patch"
test "$(git -C "$PRIME" diff -- src/prime_rl/trainer/batch.py src/prime_rl/trainer/model.py | sha256sum | cut -d' ' -f1)" = \
  5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3
timeout 5m uv pip install --no-deps \
  -e "$PROJECT/probes/gemma-training-path/taskset"
uv run --no-sync python - <<'PY'
from importlib.metadata import version
from renderers.base import MODEL_RENDERER_MAP
for name in ("transformers", "torch", "vllm", "pydantic", "openai", "mcp"):
    print(name, version(name))
assert MODEL_RENDERER_MAP["google/gemma-4-E4B-it"] == "gemma4"
PY
```

If `uv sync --locked` says the lock is stale after the renderer checkout, stop
and record it. Do not regenerate the lock during this proof.

### 3. Download and verify only the pinned E4B snapshot

```bash
export HF_HOME="$ROOT/cache/hf"
export MODEL="$ROOT/models/gemma-4-E4B-it-ee0ef6023621cff504d758262d4e04895a5af4a2"
cd "$PRIME"

timeout 45m uv run --no-sync python - "$MODEL" <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
import sys
path = Path(sys.argv[1])
snapshot_download(
    repo_id="google/gemma-4-E4B-it",
    revision="ee0ef6023621cff504d758262d4e04895a5af4a2",
    local_dir=path,
)
weight = path / "model.safetensors"
assert weight.stat().st_size == 15_992_595_884
for required in ("config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
    assert (path / required).is_file(), required
print(path)
PY

test "$(timeout 10m sha256sum "$MODEL/model.safetensors" | cut -d' ' -f1)" = \
  cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503
```

### 4. Start loopback-only inference and baseline eval

Run the server with a 75-minute hard bound; the cleanup trap stops it on every
exit. The standalone inference process and trainer intentionally share GPU 0
for this E4B smoke.

```bash
export PROBE="$PROJECT/probes/gemma-training-path"
cd "$PRIME"

CUDA_VISIBLE_DEVICES=0 HF_HOME="$HF_HOME" \
  timeout 75m uv run --no-sync inference @ "$PROBE/configs/e4b-inference.toml" \
  --vllm.model "$MODEL" --output-dir "$ROOT/inference" \
  >"$ROOT/logs/inference.log" 2>&1 &
INFERENCE_PID=$!
cleanup_inference() {
  kill "$INFERENCE_PID" 2>/dev/null || true
  wait "$INFERENCE_PID" 2>/dev/null || true
}
trap cleanup_inference EXIT

for _ in $(seq 1 1200); do
  if curl -fsS --connect-timeout 2 --max-time 5 \
       http://127.0.0.1:8100/health >/dev/null && \
     curl -fsS --connect-timeout 2 --max-time 5 \
       http://127.0.0.1:8000/v1/models >/dev/null; then break; fi
  sleep 1
done
curl -fsS --connect-timeout 5 --max-time 30 \
  http://127.0.0.1:8000/v1/models | tee "$ROOT/logs/models-before.json"

timeout 10m uv run --no-sync eval @ "$PROBE/configs/heldout-eval.toml" \
  --model "$MODEL" --output-dir "$ROOT/evals" \
  --run.name baseline-heldout --clean
```

Stop immediately on startup OOM, parser error, or any baseline trace error. Do
not continue a training run that has not demonstrated a real tool loop.

### 5. One bounded LoRA GRPO step

```bash
CUDA_VISIBLE_DEVICES=0 HF_HOME="$HF_HOME" \
  timeout 35m uv run --no-sync rl @ "$PROBE/configs/e4b-one-step-rl.toml" \
  --model.name "$MODEL" --output-dir "$ROOT/runs" \
  --run.name e4b-one-step --clean \
  2>&1 | tee "$ROOT/logs/rl.log"
```

Do not extend `max_steps`, context, batch, or layer count in this ticket. If the
trainer OOMs, preserve logs and use the one fallback below. A renderer, adapter,
or checkpoint-format error is a software failure; changing model size does not
clear it.

### 6. Explicit fresh-name adapter reload and held-out eval

```bash
export RUN="$ROOT/runs/e4b-one-step"
export ADAPTER="$RUN/broadcasts/step_1"
test -f "$ADAPTER/STABLE"
test -f "$ADAPTER/adapter_model.safetensors"
test -f "$ADAPTER/adapter_config.json"
test -d "$RUN/checkpoints/step_1/trainer"

# Remove the training-time adapter if present. A 404 is harmless.
# Retain every other error response.
curl -sS --connect-timeout 5 --max-time 120 \
  -X POST http://127.0.0.1:8100/v1/unload_lora_adapter \
  -H 'Content-Type: application/json' \
  -d '{"lora_name":"r8-a16.0"}' | tee "$ROOT/logs/unload.json"

uv run --no-sync python - "$ADAPTER" >"$ROOT/load-final.json" <<'PY'
import json, sys
print(json.dumps({"lora_name": "proof-final", "lora_path": sys.argv[1]}))
PY
curl -fsS --connect-timeout 5 --max-time 120 \
  -X POST http://127.0.0.1:8100/load_lora_adapter \
  -H 'Content-Type: application/json' \
  --data-binary @"$ROOT/load-final.json" | tee "$ROOT/logs/load-final.json"
curl -fsS --connect-timeout 5 --max-time 30 \
  http://127.0.0.1:8000/v1/models | tee "$ROOT/logs/models-after.json"

timeout 10m uv run --no-sync eval @ "$PROBE/configs/heldout-eval.toml" \
  --model proof-final --output-dir "$ROOT/evals" \
  --run.name final-heldout --clean

timeout 5m uv run --no-sync python "$PROBE/verify_smoke_artifacts.py" \
  --run-dir "$RUN" \
  --baseline-traces "$ROOT/evals/baseline-heldout/traces.jsonl" \
  --baseline-model "$MODEL" \
  --final-traces "$ROOT/evals/final-heldout/traces.jsonl" \
  --final-model proof-final \
  | tee "$ROOT/logs/verification.json"
```

Only an exit code 0 from the final verifier completes the proof.

### One fallback, then stop

If and only if E4B fails a memory gate, repeat once with:

- repository `google/gemma-4-E2B-it`;
- revision `3e22461f65e89153144f8adb70e3b8c2cc9845a7`;
- expected `model.safetensors` size `10,246,621,918`;
- SHA-256 `2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550`;
- vLLM `gpu_memory_utilization=0.30`;
- otherwise identical taskset, renderer, LoRA regex, one step, reload, and
  acceptance checks.

Do not attempt 31B training as an automatic fallback and do not start a long
run from this ticket.

## What a successful smoke would and would not prove

A passing smoke would prove that this pinned, self-managed stack can execute a
text-first multi-turn Gemma tool policy through Verifiers v1, convert its trace
to GRPO data, update and save a LoRA adapter, reload it in vLLM, and evaluate it
on disjoint tasks. It would not prove that full E4B training fits, that 31B
training fits, that a scientific curriculum is sound, or that the trained model
improves fairly over a baseline. Those claims belong to later environment and
evaluation tickets.
