# Gemma 4 31B fast serving on workstation 2

Date: August 22, 2026

## Recommendation

Deploy the instruction-tuned checkpoint `google/gemma-4-31B-it` with its
separate MTP drafter, `google/gemma-4-31B-it-assistant`, **after the user
confirms that they want the instruction-tuned model rather than the base
checkpoint**. These are official Google repositories in the
[Gemma 4 collection](https://huggingface.co/collections/google/gemma-4).

Use **SGLang v0.5.18 as the primary candidate**. It has the clearest
version-pinned, model-specific Gemma 4 31B MTP recipe, an OpenAI-compatible
API, a CUDA 13.0 container, and an explicit Triton attention path for this
SM120 GPU
([SGLang Gemma 4 cookbook](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx)).
Use **vLLM v0.27.1 as the fallback candidate**. It also documents Gemma 4 31B
assistant MTP and has evidence that the BF16 target runs on an RTX PRO 6000
when vLLM selects its default Triton attention backend
([vLLM MTP documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/features/speculative_decoding/mtp.md#L12-L31),
[RTX PRO 6000 report](https://github.com/vllm-project/vllm/issues/40677)).

Do not make TensorRT-LLM the initial deployment. Its `main` branch lists the
target and assistant, but the research did not identify a released,
versioned container that includes Gemma 4 MTP. The available stable/RC path
also contains contradictory speculative-decoding documentation. Supplying a
TensorRT-LLM tag or Gemma 4 MTP command would therefore require guesswork.

Start both candidates in BF16 with BF16 KV cache. Do not begin with NVFP4,
online FP8, or FP8 KV cache: the ledger contains no validated quantized
Gemma 4 31B plus MTP result for this exact card, and vLLM has an open
Gemma 4 MTP issue involving calibrated FP8 KV scales
([vLLM PR #49262](https://github.com/vllm-project/vllm/pull/49262)).

This recommendation does **not** claim that SGLang is already proven fastest
on this workstation. No source in the ledger provides a head-to-head
benchmark for this exact model, drafter, GPU, driver, and workload. Run the
short benchmark in this report before selecting the permanent engine.

## Exact model identity

"Gemma 4 31B" is an official size label, but it is not one exact checkpoint.
The 31B model is the dense Gemma 4 model, not the `26B-A4B` mixture-of-experts
model
([Google Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)).

| Official model ID | Role | Deployment decision |
| --- | --- | --- |
| [`google/gemma-4-31B`](https://huggingface.co/google/gemma-4-31B) | Pretrained/base model | Do not substitute this model for the chat model. Use it only if the user explicitly confirms that they want the base checkpoint. |
| [`google/gemma-4-31B-it`](https://huggingface.co/google/gemma-4-31B-it) | Instruction-tuned target model | Recommended target for chat and an OpenAI-compatible API. |
| [`google/gemma-4-31B-it-assistant`](https://huggingface.co/google/gemma-4-31B-it-assistant) | Official MTP/speculative drafter for the instruction-tuned target | Load beside the target; do not serve it as the user-facing model. |

Google DeepMind links its Gemma 4 31B AI Studio experience to
`model=gemma-4-31b-it`, which supports choosing the instruction-tuned model
for chat, but it does not remove the need to confirm the user's intent
([Google DeepMind Gemma 4 page](https://deepmind.google/models/gemma/gemma-4/)).

The official repositories are public, not gated, and licensed under Apache
2.0
([Google license](https://ai.google.dev/gemma/apache_2),
[target API record](https://huggingface.co/api/models/google/gemma-4-31B-it),
[assistant API record](https://huggingface.co/api/models/google/gemma-4-31B-it-assistant)).
No gated-model approval or Hugging Face token is required for these three
repositories.

## What MTP means for this model

Gemma 4 31B has official multi-token prediction (MTP) support, but the main
`google/gemma-4-31B-it` checkpoint does not contain an embedded assistant
architecture. Google ships a separate, smaller drafter checkpoint. The
target configuration declares `Gemma4ForConditionalGeneration`, while the
assistant declares `Gemma4AssistantForCausalLM`
([target configuration](https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json),
[assistant configuration](https://huggingface.co/google/gemma-4-31B-it-assistant/raw/main/config.json)).
Google's MTP guide pairs the 31B IT target with the `-assistant` repository
([Gemma MTP guide](https://ai.google.dev/gemma/docs/mtp/mtp)).

As of the pinned versions in this report:

- **SGLang v0.5.18 supports the pair.** Its Gemma 4 cookbook provides the
  target, assistant, and `NEXTN` MTP flags
  ([SGLang Gemma 4 MTP recipe](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L182-L245)).
  For a Gemma 4 assistant, SGLang internally promotes `NEXTN` to
  `FROZEN_KV_MTP`; it rejects EAGLE3 for this assistant architecture
  ([SGLang speculative hook](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L24-L61)).
- **vLLM v0.27.1 supports the pair.** Its MTP documentation explicitly lists
  the 31B IT assistant checkpoints and requires `"method":"mtp"`
  ([vLLM MTP documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/features/speculative_decoding/mtp.md#L12-L31)).
- **TensorRT-LLM support is only substantiated on the edge path.** The
  `main` support matrix lists both exact repositories and marks Gemma 4 MTP
  supported
  ([TensorRT-LLM model matrix](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/models/supported-models.md)).
  TensorRT-LLM v1.2 does not list Gemma 4, and v1.3.0rc22/rc23 list the target
  but mark Gemma 4 MTP unsupported
  ([v1.2.0 matrix](https://github.com/NVIDIA/TensorRT-LLM/blob/v1.2.0/docs/source/models/supported-models.md),
  [v1.3.0rc23 matrix](https://github.com/NVIDIA/TensorRT-LLM/blob/v1.3.0rc23/docs/source/models/supported-models.md)).
  Dynamo 1.4.0 pins v1.3.0rc22
  ([Dynamo release artifacts](https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/reference/general/release-artifacts.mdx)).

## Engine comparison

The following comparison contains only capabilities and limitations supported
by the research ledger. It does not infer performance rankings.

| Engine | Exact model and MTP evidence | OpenAI-compatible API | RTX PRO 6000 / SM120 evidence | Decision |
| --- | --- | --- | --- | --- |
| **SGLang v0.5.18** | The tagged cookbook documents `google/gemma-4-31B-it` with its assistant and `NEXTN`; tagged source contains the Gemma 4 assistant conversion to `FROZEN_KV_MTP` ([cookbook](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L182-L245), [source](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L24-L61)). | Yes; the cookbook uses the OpenAI client against `/v1` ([API example](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L248-L267)). | SGLang detects Blackwell with CUDA 12.8 or later. Its Gemma 4 override uses Triton except on SM100, and `trtllm_mha` prefill validation is SM100-only ([Blackwell gate](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/utils/common.py#L279-L294), [override](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/overrides.py#L1058-L1084), [backend validation](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L6014-L6025)). No first-party 31B MTP benchmark exists for this RTX card. | **Primary candidate.** Best-supported version-pinned MTP path in the ledger, subject to a one-GPU fit and speed test. |
| **vLLM v0.27.1** | The tagged MTP documentation explicitly includes 31B assistants and maps them through the Gemma 4 MTP path ([MTP documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/features/speculative_decoding/mtp.md#L12-L31)). v0.27.1 includes the earlier Gemma 4 embedding-sharing fix ([PR #47953](https://github.com/vllm-project/vllm/pull/47953), [v0.27.1 release](https://github.com/vllm-project/vllm/releases/tag/v0.27.1)). | Yes; vLLM provides an OpenAI-compatible server ([server documentation](https://github.com/vllm-project/vllm/blob/main/docs/serving/online_serving/openai_compatible_server.md)). | An issue report shows the exact BF16 31B target running on an RTX PRO 6000 with default `TRITON_ATTN`; forcing FlashInfer failed. The report did not include the assistant/MTP pair ([issue #40677](https://github.com/vllm-project/vllm/issues/40677)). No source proves the full exact combination on one 96 GB card. | **Fallback candidate.** Do not force FlashInfer, and do not use calibrated FP8 KV cache for the first MTP test. |
| **TensorRT-LLM `main`** | `main` lists both exact repositories and MTP, but no released tag containing that support was identified. Its speculative-decoding documentation also says that the PyTorch serving YAML path supports only Eagle3, conflicting with the model matrix ([speculative-decoding documentation](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/features/speculative-decoding.md)). | Yes; `trtllm-serve` exposes `/v1/models`, `/v1/completions`, and `/v1/chat/completions` ([server documentation](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/commands/trtllm-serve/trtllm-serve.rst)). | Source code recognizes `SM120/121 (RTX PRO 6000 Blackwell)`, but the public supported-hardware page does not list this card ([source](https://github.com/NVIDIA/TensorRT-LLM/blob/main/tensorrt_llm/_mnnvl_utils.py#L480-L484), [hardware page](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/supported-hardware.md)). | **Do not deploy yet.** Reconsider after NVIDIA publishes a pin with the assistant path and an unambiguous Gemma 4 MTP YAML example. |

### Missing or null research

No primary source in the ledger establishes any of the following:

- A head-to-head SGLang, vLLM, and TensorRT-LLM result for this exact
  workstation.
- A first-party SGLang Gemma 4 31B MTP run on one RTX PRO 6000.
- A full vLLM 31B target-plus-assistant MTP run on one RTX PRO 6000.
- A released TensorRT-LLM container tag with demonstrated Gemma 4 31B
  assistant MTP, or an exact noncontradictory YAML command for it.
- A quantized Gemma 4 31B MTP configuration that is both faster and
  quality-equivalent on this GPU.
- The best context length, concurrency, batch-token limit, or MTP acceptance
  rate for the user's workload.

The ledger's statement that TensorRT-LLM is "likely" the fastest NVIDIA stack
is a hypothesis, not a benchmark result. Do not use it as a measured claim.

## Primary configuration: SGLang v0.5.18

### Pins

Use the following immutable inputs:

| Component | Pin |
| --- | --- |
| Engine | SGLang `v0.5.18` ([release](https://github.com/sgl-project/sglang/releases/tag/v0.5.18)) |
| Container | `lmsysorg/sglang:v0.5.18@sha256:9e148f5ac788e856a06166bd6347a831831eb9fcfab4d1770874823a7c29a1a1` ([Docker Hub tag record](https://hub.docker.com/v2/repositories/lmsysorg/sglang/tags/v0.5.18)) |
| Target | `google/gemma-4-31B-it` at revision `842da3794eaa0b77d5f08bae87a17459d91ff475` ([Hugging Face commit](https://huggingface.co/google/gemma-4-31B-it/commit/842da3794eaa0b77d5f08bae87a17459d91ff475)) |
| Drafter | `google/gemma-4-31B-it-assistant` at revision `627c5ec1458b9086b841a91e0512fd31fd2fbbf1` ([Hugging Face commit](https://huggingface.co/google/gemma-4-31B-it-assistant/commit/627c5ec1458b9086b841a91e0512fd31fd2fbbf1)) |
| Precision | BF16 target, assistant, and KV cache |
| Attention | Triton |
| MTP | `NEXTN`, five steps, six draft tokens, top-k 1 |
| Parallelism | TP=1, implied by omitting the two-GPU `--tp-size 2` flag |
| Initial context cap | 8,192 tokens; this is a conservative test cap, not the model's 262,144-token architectural maximum ([target configuration](https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json)) |
| Initial static-memory fraction | `0.80`; benchmark before raising it |
| API | OpenAI-compatible HTTP API on host loopback port `30000` |

The image tag and manifest-list digest were present in the official registry on
August 22, 2026. SGLang documents its corresponding image path as CUDA 13.0,
which meets SGLang's CUDA 12.8-or-later Blackwell gate
([container recipe](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L80-L91)).
The installed driver `610.43.02` exceeds NVIDIA's documented minimum driver
for CUDA 13.x, which is 580
([NVIDIA CUDA compatibility table](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html#minor-version-compatibility)).

**Uncertainty:** SGLang's published 31B MTP example uses two H200 GPUs. Removing
`--tp-size 2` is necessary on a single GPU. Hugging Face metadata suggests that
the BF16 target and assistant fit in 96 GB at moderate context
([target metadata](https://huggingface.co/api/models/google/gemma-4-31B-it),
[assistant metadata](https://huggingface.co/api/models/google/gemma-4-31B-it-assistant),
[NVIDIA GPU specification](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/)).
SGLang has not published this exact one-GPU run. Treat startup as a required
fit test, not a guarantee.

### Single-root layout

Keep every persistent, service-owned file below `/srv/gemma4-31b`:

```text
/srv/gemma4-31b/
  config/
    run-sglang.sh
    run-vllm.sh
  data/
    huggingface/
    home-sglang/
    home-vllm/
    vllm/
  logs/
    sglang/
    vllm/
  bench/
    datasets/
    results/
  locks/
    images.txt
    models.txt
```

Set `HF_HOME`, `HF_HUB_CACHE`, `HOME`, and, for vLLM,
`VLLM_CACHE_ROOT` to these bind-mounted paths. Hugging Face documents
`HF_HOME` and `HF_HUB_CACHE`
([Hub environment variables](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables)),
and vLLM documents that a mounted `VLLM_CACHE_ROOT` preserves its Inductor,
Triton, and AOT compile cache
([vLLM Docker documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/deployment/docker.md#L11-L29)).
Write server output to `logs/` and benchmark inputs/results to `bench/`.

**Docker boundary:** bind mounts keep all model, mutable cache, configuration,
and application-log artifacts under this root. Docker still stores immutable
image layers, writable-layer metadata, and daemon state in Docker's global
`data-root`
([Docker daemon data-directory documentation](https://docs.docker.com/engine/daemon/#daemon-data-directory)).
Changing that global root affects every container on the host and must not be
done without the user's approval. If "all deployment artifacts"
includes Docker's own layers, request approval for a dedicated Docker data
root or use a root-local Python environment after separately pinning its full
CUDA/PyTorch dependency set. The ledger does not contain that complete wheel
pin, so this report does not fabricate one.

### Launch command

Create the directories, record the pins, and save the launch script under the
single root:

```bash
export ROOT=/srv/gemma4-31b
sudo install -d -m 0750 -o "$(id -un)" -g "$(id -gn)" "$ROOT"
mkdir -p \
    "$ROOT"/{config,data/huggingface,data/home-sglang,logs/sglang} \
    "$ROOT"/{data/home-vllm,data/vllm,logs/vllm} \
    "$ROOT"/{bench/datasets,bench/results,locks}

cat >"$ROOT/locks/images.txt" <<'EOF'
lmsysorg/sglang:v0.5.18@sha256:9e148f5ac788e856a06166bd6347a831831eb9fcfab4d1770874823a7c29a1a1
vllm/vllm-openai:v0.27.1@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
EOF

cat >"$ROOT/locks/models.txt" <<'EOF'
google/gemma-4-31B-it@842da3794eaa0b77d5f08bae87a17459d91ff475
google/gemma-4-31B-it-assistant@627c5ec1458b9086b841a91e0512fd31fd2fbbf1
EOF
```

Save this supported SGLang command as `$ROOT/config/run-sglang.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec > >(tee -a /state/logs/server.log) 2>&1

exec sglang serve \
    --model-path google/gemma-4-31B-it \
    --revision 842da3794eaa0b77d5f08bae87a17459d91ff475 \
    --served-model-name google/gemma-4-31B-it \
    --dtype bfloat16 \
    --kv-cache-dtype bfloat16 \
    --attention-backend triton \
    --context-length 8192 \
    --speculative-algorithm NEXTN \
    --speculative-draft-model-path google/gemma-4-31B-it-assistant \
    --speculative-draft-model-revision \
        627c5ec1458b9086b841a91e0512fd31fd2fbbf1 \
    --speculative-draft-kv-cache-dtype bfloat16 \
    --speculative-num-steps 5 \
    --speculative-num-draft-tokens 6 \
    --speculative-eagle-topk 1 \
    --mem-fraction-static 0.80 \
    --host 0.0.0.0 \
    --port 30000
```

SGLang v0.5.18 defines both model-revision flags and the explicit BF16 KV
cache values in its server arguments
([target revision](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L581-L602),
[KV cache](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L680-L705),
[draft settings](https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L2079-L2200)).
The remaining MTP values come from the tagged Gemma 4 recipe.

Launch the pinned image. The port is published only on loopback:

```bash
export ROOT=/srv/gemma4-31b
chmod 0750 "$ROOT/config/run-sglang.sh"

docker pull \
    lmsysorg/sglang:v0.5.18@sha256:9e148f5ac788e856a06166bd6347a831831eb9fcfab4d1770874823a7c29a1a1

docker run --rm --name gemma4-31b-sglang \
    --log-driver none \
    --gpus all \
    --ipc=host \
    --shm-size 32g \
    -p 127.0.0.1:30000:30000 \
    -e HOME=/state/data/home-sglang \
    -e HF_HOME=/state/data/huggingface \
    -e HF_HUB_CACHE=/state/data/huggingface/hub \
    -v "$ROOT/data:/state/data" \
    -v "$ROOT/logs/sglang:/state/logs" \
    -v "$ROOT/config/run-sglang.sh:/state/run.sh:ro" \
    --entrypoint /bin/bash \
    lmsysorg/sglang:v0.5.18@sha256:9e148f5ac788e856a06166bd6347a831831eb9fcfab4d1770874823a7c29a1a1 \
    /state/run.sh
```

The GPU, IPC, shared-memory, cache-mount, and server-command shape follows the
[tagged SGLang Docker recipe](https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L80-L91).
The `none` logging driver prevents Docker from retaining a second copy of the
server log outside the root; the launch script writes the durable copy to
`logs/sglang/`
([Docker logging-driver documentation](https://docs.docker.com/engine/logging/configure/#supported-logging-drivers)).

After startup, verify the OpenAI-compatible chat endpoint:

```bash
curl --no-buffer http://127.0.0.1:30000/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{
      "model": "google/gemma-4-31B-it",
      "messages": [{"role": "user", "content": "Reply with READY."}],
      "temperature": 0,
      "max_tokens": 16,
      "stream": true
    }'
```

Do not publish this unauthenticated benchmark server on a LAN or public
interface. Decide the authentication and network boundary before changing the
loopback bind.

## Fallback configuration: vLLM v0.27.1

Use the fallback only after testing it with the same model revisions and
workload. Pin the official image as follows:

```text
vllm/vllm-openai:v0.27.1@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
```

The tag and digest come from the
[official Docker Hub tag record](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.27.1).
Do not set `VLLM_ATTENTION_BACKEND=FLASHINFER`; allow vLLM to choose its
default backend. Do not add `--kv-cache-dtype fp8` to this first MTP test.

Save the following script as `$ROOT/config/run-vllm.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec > >(tee -a /state/logs/server.log) 2>&1

exec vllm serve google/gemma-4-31B-it \
    --revision 842da3794eaa0b77d5f08bae87a17459d91ff475 \
    --served-model-name google/gemma-4-31B-it \
    --host 0.0.0.0 \
    --port 8000 \
    --dtype bfloat16 \
    --kv-cache-dtype auto \
    --max-model-len 8192 \
    --limit-mm-per-prompt '{"image":0,"audio":0}' \
    --generation-config vllm \
    --speculative-config \
        '{"method":"mtp","model":"google/gemma-4-31B-it-assistant","revision":"627c5ec1458b9086b841a91e0512fd31fd2fbbf1","num_speculative_tokens":1}' \
    --per-request-spec-decode-metrics summary
```

The tagged vLLM documentation supports the Gemma 4 MTP configuration and says
that 31B assistants are supported
([vLLM MTP documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/features/speculative_decoding/mtp.md#L12-L31)).
The tagged source defines the target `--revision` flag and the drafter's
`revision` field
([target arguments](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/engine/arg_utils.py#L848-L855),
[drafter configuration](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/config/speculative.py#L124-L136)).
vLLM source warns that requesting more than one speculative token for most MTP
model types repeats the same MTP layer and might reduce acceptance, so begin
with one
([speculative configuration](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/config/speculative.py#L903-L916)).
The multimodal limit makes this a text-only benchmark; remove it for a
separate image-input validation.

Launch the fallback:

```bash
export ROOT=/srv/gemma4-31b
chmod 0750 "$ROOT/config/run-vllm.sh"

docker pull \
    vllm/vllm-openai:v0.27.1@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967

docker run --rm --name gemma4-31b-vllm \
    --log-driver none \
    --gpus all \
    --ipc=host \
    -p 127.0.0.1:8000:8000 \
    -e HOME=/state/data/home-vllm \
    -e HF_HOME=/state/data/huggingface \
    -e HF_HUB_CACHE=/state/data/huggingface/hub \
    -e VLLM_CACHE_ROOT=/state/data/vllm \
    -v "$ROOT/data:/state/data" \
    -v "$ROOT/logs/vllm:/state/logs" \
    -v "$ROOT/config/run-vllm.sh:/state/run.sh:ro" \
    --entrypoint /bin/bash \
    vllm/vllm-openai:v0.27.1@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967 \
    /state/run.sh
```

The image invocation and persistent Hugging Face/vLLM cache mounts follow the
[tagged vLLM Docker documentation](https://github.com/vllm-project/vllm/blob/v0.27.1/docs/deployment/docker.md#L11-L29).

## Benchmark plan

Use one load generator and identical request payloads for every server. vLLM's
benchmark CLI reports time to first token (TTFT), inter-token latency (ITL),
time per output token, request throughput, and token throughput
([vLLM benchmark documentation](https://github.com/vllm-project/vllm/blob/main/docs/benchmarking/cli.md)).
It can target an online OpenAI-compatible server, so use it for both engines
rather than comparing different clients.

1. **Freeze the run sheet.** Record the GPU power mode, driver, image digest,
   target and assistant revisions, complete server command, context cap,
   prompt/output lengths, sampling settings, and concurrency in
   `bench/results/`. Keep the context cap and precision identical.
2. **Run four configurations.** Test SGLang without MTP, SGLang with MTP,
   vLLM without MTP, and vLLM with MTP. The no-MTP cases are controls, not
   deployment candidates. They establish whether MTP helps this workload.
3. **Separate cold and warm behavior.** Measure the first request after
   startup, then warm the model and compile caches before steady-state runs.
   Repeat steady-state runs rather than reporting one request.
4. **Measure latency and saturation.** At concurrency 1, compare p50, p95, and
   p99 TTFT and ITL. Then sweep the workload's expected concurrency and report
   successful requests per second, output tokens per second, total tokens per
   second, error count, and peak VRAM. Use at least one short-prompt shape and
   one representative long-prompt shape supplied by the user.
5. **Apply gates before selecting.** Reject a configuration that produces an
   out-of-memory error, request failure, unacceptable output regression, or
   inactive/low-acceptance speculation. Among the remaining MTP runs, select
   the engine with the lower p95 TTFT and ITL at the expected concurrency. If
   latency is within the predeclared tolerance, select the higher sustained
   output-token throughput.

Also capture vLLM's per-request speculative-decoding summary
([acceptance metrics](https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/acceptance_metrics.md)).
For SGLang, retain the startup configuration and check whether the server
reports the resolved `FROZEN_KV_MTP` path. The ledger did not identify a
comparable stable per-request acceptance-metric interface, so label both the
resolved-path and acceptance metrics missing if the server does not expose
them.

Do not include TensorRT-LLM in the acceptance benchmark until an exact release
pin and supported Gemma 4 MTP serving configuration exist. A benchmark of an
unversioned `main` build would not satisfy the deployment pin requirement.

## Information to request before downloading

Request the following blocking decisions from the user:

1. **Checkpoint confirmation:** confirm `google/gemma-4-31B-it`. If they mean
   `google/gemma-4-31B`, stop; do not silently substitute the IT model or pair
   the IT assistant with the base checkpoint.
2. **Storage location and quota:** approve `/srv/gemma4-31b` or provide another
   single root, and confirm enough free local disk for both model snapshots,
   container images, caches, and benchmark results. The ledger does not
   establish an exact disk requirement.
3. **Workload definition:** provide representative prompts, input/output token
   lengths, target context length, expected concurrency, and whether image
   input is required. These values determine which "fastest" metric matters.
4. **Network and authentication policy:** choose loopback-only, LAN, or a
   private overlay such as Tailscale, and provide or authorize generation of a
   service API key before any non-loopback exposure.
5. **Host-change approval:** confirm that NVIDIA Container Toolkit already
   works with Docker, or authorize its installation/configuration. NVIDIA's
   documented setup uses `nvidia-ctk runtime configure --runtime=docker` and a
   Docker restart
   ([NVIDIA Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)).
6. **Docker-root interpretation:** state whether the single-directory rule
   includes Docker's global image/daemon storage. If it does, approve a
   dedicated Docker data-root design or a separately researched root-local
   runtime.

Do **not** request gated-model approval, Gemma license acceptance, an NGC key,
or a Hugging Face token for the recommended public Google repositories. A
Hugging Face token is needed only if the user's network policy or a different,
private model requires one. An NGC credential becomes relevant only if the
user later chooses an NVIDIA container path that requires it.

## Final decision rule

Proceed with the pinned SGLang configuration after the user confirms the IT
checkpoint and the Docker GPU smoke test succeeds. Keep vLLM v0.27.1 ready as
the exact fallback. Promote vLLM only if the controlled benchmark beats
SGLang for the user's declared latency/throughput priority or SGLang fails the
one-GPU fit/correctness gate. Revisit TensorRT-LLM only after NVIDIA publishes
a versioned Gemma 4 assistant-MTP serving path.
