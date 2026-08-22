# Research: SGLang support for Gemma 4 31B + native MTP on 1x RTX PRO 6000 Blackwell 96GB

Date: 2026-08-22
Task label: `research-2-sglang`

## Bottom line

- Exact target model: `google/gemma-4-31B-it` (SGLang cookbook lists it as dense, 31B) and draft/MTP model: `google/gemma-4-31B-it-assistant`.
  - SGLang model table: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L55-L64
  - MTP commands: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L182-L245
- One RTX PRO 6000 Blackwell Workstation Edition has 96 GB GDDR7 ECC memory (NVIDIA product page) and is CUDA compute capability 12.0 / SM120 (NVIDIA CUDA GPU table).
  - Product page: https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/
  - CUDA GPUs table: https://developer.nvidia.com/cuda-gpus
- SGLang has Blackwell/SM120 code paths gated on CUDA >= 12.8. Use an SGLang build with CUDA 12.8+; the Gemma 4 docs' Docker path uses `lmsysorg/sglang:latest` with CUDA 13.0.
  - SGLang Blackwell gates: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/utils/common.py#L279-L294
  - Docker note: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L80-L91
- The model should fit at TP=1 on a 96 GB card for moderate context: Hugging Face metadata reports 31.27B BF16 parameters for the target (~62.5 GB weights) and 0.47B BF16 parameters for the assistant (~0.94 GB). That leaves roughly 30+ GB before runtime/KV/workspace overhead, but this is an estimate; SGLang does not publish a Gemma 4 31B benchmark/recipe specifically for RTX PRO 6000.
  - Target model metadata: https://huggingface.co/api/models/google/gemma-4-31B-it
  - Assistant metadata: https://huggingface.co/api/models/google/gemma-4-31B-it-assistant
- Use BF16. The SGLang selector labels the standard checkpoint as BF16; QAT `q4_0-unquantized` releases keep BF16 weights and therefore do not reduce memory/TP requirements.
  - Selector checkpoint labels: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/src/snippets/autoregressive/gemma4-deployment.jsx#L14-L20
  - QAT note: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L110-L111

## Recommended server commands for 1x RTX PRO 6000 Blackwell 96GB

### Baseline text/image server

```bash
sglang serve \
  --model-path google/gemma-4-31B-it \
  --dtype bfloat16 \
  --attention-backend triton \
  --mem-fraction-static 0.80 \
  --host 0.0.0.0 --port 30000
```

Rationale:

- SGLang's Gemma 4 override uses `trtllm_mha` only on SM100; otherwise it defaults Gemma 4 to `triton`, so explicit `--attention-backend triton` is the safest RTX PRO 6000/SM120 setting.
  - Override source: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/overrides.py#L1058-L1084
- SGLang also warns that `trtllm_mha` prefill is only SM100, while decode supports SM90/SM100/SM120; avoid `trtllm_mha` for a full Gemma 4 prefill+decode backend on RTX PRO 6000.
  - Backend validation: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L6014-L6025
- For image workloads on Blackwell B200/SM100, SGLang docs say `trtllm_mha` applies causal attention to image tokens and recommend `--attention-backend triton` to restore bidirectional image-token attention. RTX PRO 6000's Gemma 4 default is already triton, but explicit triton avoids ambiguity.
  - Gemma 4 config tips: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L104-L110

### Native Gemma 4 MTP / NEXTN server

```bash
sglang serve \
  --model-path google/gemma-4-31B-it \
  --dtype bfloat16 \
  --attention-backend triton \
  --speculative-algorithm NEXTN \
  --speculative-draft-model-path google/gemma-4-31B-it-assistant \
  --speculative-num-steps 5 \
  --speculative-num-draft-tokens 6 \
  --speculative-eagle-topk 1 \
  --mem-fraction-static 0.80 \
  --host 0.0.0.0 --port 30000
```

Notes:

- SGLang docs say each Gemma 4 variant ships a paired `*-assistant` draft model for NEXTN MTP and gives the canonical flags: `--speculative-algorithm NEXTN`, assistant path, 5 steps, 6 draft tokens, topk 1.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L182-L245
- The cookbook's static 31B MTP example includes `--tp-size 2`, matching SGLang's H200/2-GPU validation. On one RTX PRO 6000, do not pass TP=2; TP=1 is the only single-GPU shape. This TP=1+MTP shape is plausible from memory but not explicitly benchmarked in SGLang docs.
  - Static 31B MTP example: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L222-L233
  - SGLang interactive selector uses TP=1 for 31B on B200/B300: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/src/snippets/autoregressive/gemma4-deployment.jsx#L73-L85
- Internally, when the draft config architecture is `Gemma4AssistantForCausalLM`, SGLang promotes `NEXTN`/`EAGLE` to `FROZEN_KV_MTP`. `EAGLE3` is rejected for Gemma4 assistant drafts.
  - Alias/promotion source: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L24-L61

### If VRAM is tight

Try these one at a time:

```bash
  --mem-fraction-static 0.75
  --max-running-requests 8
  --context-length 8192
  --speculative-draft-kv-cache-dtype fp8_e4m3
```

SGLang documents `--speculative-draft-kv-cache-dtype fp8_e4m3` as halving the draft KV pool for small draft models and freeing device memory.
- Source: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L2187-L2200

## API compatibility

Use OpenAI-compatible chat completions at `http://localhost:30000/v1`.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:30000/v1", api_key="EMPTY")

response = client.chat.completions.create(
    model="google/gemma-4-31B-it",
    messages=[{"role": "user", "content": "Summarize CRISPR-Cas9 in 3 bullets."}],
    max_tokens=512,
)
print(response.choices[0].message.content)
```

- SGLang Gemma 4 basic OpenAI usage: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L248-L267
- Vision uses OpenAI `image_url` content parts; Gemma 4 31B has image benchmark entries in the SGLang docs. Vision API shape: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L306-L341
- Thinking mode is not enabled by default; pass `extra_body={"chat_template_kwargs": {"enable_thinking": True}}` and serve with `--reasoning-parser gemma4` if you want separated `reasoning_content`.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L361-L407
- Tool calling requires serving with `--tool-call-parser gemma4`.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L446-L519
- Audio is not supported for 31B; SGLang docs list only E2B/E4B/12B as audio-capable and mark 31B ASR/FLEUR as not supported.
  - Audio-capable note: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L532-L560
  - ASR support table: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L1574-L1584
  - FLEUR support table: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L1625-L1635

## Versions and install compatibility

- Latest SGLang release checked: `v0.5.18` (GitHub release, published 2026-08-22): https://github.com/sgl-project/sglang/releases/tag/v0.5.18
- SGLang Gemma 4 docs still say to install SGLang from `main` and install Transformers at commit `1423d22f7a3b62e8c70ad67b58ec25cd9b675897`.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L68-L78
- Docker route: `lmsysorg/sglang:latest` with CUDA 13.0 is documented for Hopper and Blackwell B200/GB200/GB300.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L80-L91

Recommended install paths:

```bash
# Source install per SGLang Gemma 4 docs
pip install 'git+https://github.com/sgl-project/sglang.git#subdirectory=python'
pip install 'git+https://github.com/huggingface/transformers.git@1423d22f7a3b62e8c70ad67b58ec25cd9b675897'
```

or, if using the current release wheel and it includes the same Gemma 4 code paths in your environment:

```bash
pip install 'sglang[all]==0.5.18'
pip install 'git+https://github.com/huggingface/transformers.git@1423d22f7a3b62e8c70ad67b58ec25cd9b675897'
```

## Speculative decoding option matrix

| Option | Gemma 4 31B status | Command flags | Evidence |
|---|---|---|---|
| Native assistant MTP / NEXTN | Documented in cookbook; internally becomes `FROZEN_KV_MTP` for Gemma4 assistant drafts | `--speculative-algorithm NEXTN --speculative-draft-model-path google/gemma-4-31B-it-assistant --speculative-num-steps 5 --speculative-num-draft-tokens 6 --speculative-eagle-topk 1` | Docs: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L182-L245; source: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L24-L61 |
| MTP topk=3 | Source-tested in extra CI for 31B with `--speculative-eagle-topk 3` and 12 draft tokens, but use topk=1 first on RTX because topk=3 costs more KV/compute | `--speculative-eagle-topk 3 --speculative-num-draft-tokens 12` | Test: https://github.com/sgl-project/sglang/blob/v0.5.18/test/registered/spec/test_gemma4_mtp_31b_extra.py#L21-L94 |
| DFlash | Source-tested in extra CI with non-Google draft `z-lab/gemma-4-31B-it-DFlash`, but not the main Gemma4 cookbook path | `--speculative-algorithm DFLASH --speculative-draft-model-path z-lab/gemma-4-31B-it-DFlash --speculative-num-draft-tokens 16 --speculative-draft-attention-backend flashinfer --trust-remote-code` | Test: https://github.com/sgl-project/sglang/blob/v0.5.18/test/registered/spec/test_gemma4_dflash_31b_extra.py#L21-L93 |
| DSPARK | SGLang has generic DSPARK flags, but I found no SGLang Gemma 4 31B DSPARK recipe/test in v0.5.18 | `--speculative-algorithm DSPARK --speculative-dspark-block-size ...` | Generic flags: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L2115-L2142 |
| EAGLE3 | Not supported for Gemma4 assistant drafts | Do not use | Source raises `ValueError`: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L45-L50 |
| Rejection sampling with native Gemma4 MTP | Do not use with Gemma4 assistant MTP: after alias resolution the algorithm is `FROZEN_KV_MTP`, and rejection sampling only supports `EAGLE`/`EAGLE3` | Do not pass `--speculative-use-rejection-sampling` | Source: https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/speculative_hook.py#L627-L650 |

## Known issues / caveats

1. **No first-party RTX PRO 6000 Gemma 4 31B benchmark.** SGLang Gemma 4 docs validate 31B on 2x H200, 1x MI300X, and list 1x B200/B300 support. They do not publish RTX PRO 6000-specific Gemma 4 31B results.
   - Hardware requirements table: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L112-L154
   - H200 31B benchmark: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L807-L898
   - MI300X 31B note: https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L995-L1003
2. **Backend difference on RTX PRO 6000 / SM120.** SGLang's Gemma 4 override chooses `triton` unless SM100; generic `trtllm_mha` prefill validation only permits SM100. Use triton.
   - https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/arg_groups/overrides.py#L1058-L1084
   - https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/server_args.py#L6014-L6025
3. **Blackwell requires CUDA >= 12.8 in SGLang detection.** CUDA 13 Docker satisfies this.
   - https://github.com/sgl-project/sglang/blob/v0.5.18/python/sglang/srt/utils/common.py#L279-L294
4. **QAT is not memory compression in the documented SGLang Gemma4 path.** The docs say QAT `q4_0-unquantized` keeps BF16 weights and memory/TP match standard checkpoints.
   - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L110-L111
5. **Audio is not supported on Gemma 4 31B.** Use text and image only.
   - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L1574-L1584

## Performance settings to try

- Start with `--attention-backend triton`, `--dtype bfloat16`, `--mem-fraction-static 0.80` on RTX PRO 6000.
- For latency, enable native MTP/NEXTN with topk=1, 5 steps, 6 draft tokens.
- For high-concurrency throughput, SGLang reports that raising `--scheduler-recv-interval` to 16 improved B200 text throughput by ~3% for Gemma 4 12B. This is not 31B/RTX-specific, but is low-risk to benchmark.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/docs/cookbook/autoregressive/Google/Gemma4.mdx#L1312-L1312
- If using DFlash, follow the source-tested command and include `--trust-remote-code` and `--speculative-draft-attention-backend flashinfer`; treat it as experimental compared with native NEXTN.
  - https://github.com/sgl-project/sglang/blob/v0.5.18/test/registered/spec/test_gemma4_dflash_31b_extra.py#L61-L93
