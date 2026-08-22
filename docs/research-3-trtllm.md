# research-3-trtllm: TensorRT-LLM/Dynamo for Gemma 4 31B-class on RTX PRO 6000 Blackwell

## Bottom line

TensorRT-LLM is the most plausible NVIDIA-first fast stack for this target, but the support is **not cleanly productized in the stable path**.

- Current TensorRT-LLM `main` docs/source list `google/gemma-4-31B-it` under `Gemma4ForConditionalGeneration` and list a separate `google/gemma-4-31B-it-assistant` under `Gemma4AssistantForCausalLM` for Gemma 4 MTP assistant support.
- Stable TensorRT-LLM 1.2 docs do not list Gemma 4; `v1.3.0rc22/rc23` list Gemma 4 target support but show Gemma4 MTP as `No`; current `main` changes that to `Yes` and adds assistant models.
- Dynamo stable 1.4.0 pins TRT-LLM `v1.3.0rc22`, CUDA 13.1, driver 580+, so Dynamo is likely behind the current Gemma 4 MTP support shown on TensorRT-LLM `main`.
- Raw `trtllm-serve` is likely the fastest viable OpenAI-compatible path if you can use the latest TRT-LLM release/RC or build matching `main`. Dynamo adds routing/disaggregation/KV features, but more operational complexity and less-documented TensorRT-LLM speculative decoding.

## Primary-source facts

### Exact model support

TensorRT-LLM `main` supported-models source lists:

- `Gemma4ForConditionalGeneration`: `google/gemma-4-E2B-it`, `google/gemma-4-E4B-it`, `google/gemma-4-26B-A4B-it`, `google/gemma-4-31B-it`.
- `Gemma4UnifiedForConditionalGeneration`: `google/gemma-4-12B`, `google/gemma-4-12B-it`.
- `Gemma4AssistantForCausalLM`: `google/gemma-4-E2B-it-assistant`, `google/gemma-4-E4B-it-assistant`, `google/gemma-4-26B-A4B-it-assistant`, `google/gemma-4-31B-it-assistant`.

Source: https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/models/supported-models.md

### MTP/speculative decoding

TensorRT-LLM speculative decoding docs say speculation creates a fixed draft sequence for every request and cannot be dynamically disabled, so speedups are only observable at low batch sizes. They document MTP configuration (`max_draft_len`, `num_nextn_predict_layers`, relaxed acceptance) and say `trtllm-serve`/`trtllm-bench` speculative options must be supplied via `--config config.yaml`.

Sources:
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/features/speculative-decoding.md
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/tensorrt_llm/_torch/models/modeling_gemma4.py#L1608-L1612

Important caveat: the same doc contains a note that “the PyTorch backend supports only Eagle3” in the `trtllm-serve`/`trtllm-bench` YAML section, while the model matrix marks `Gemma4ForConditionalGeneration` MTP as `Yes` on `main`. Treat Gemma 4 MTP as current/edge support that needs a smoke test on the exact container.

### Precision/quantization

TensorRT-LLM 1.2 release notes say the TensorRT backend and `trtllm-build`/`convert_checkpoint.py` path are removed; PyTorch is now the sole execution backend. The quantization docs say the default PyTorch backend supports FP4 and FP8 quantization on latest Blackwell and Hopper GPUs. The hardware matrix lists Blackwell `sm120` as supporting NVFP4, MXFP4, FP8 per-tensor, and FP8 KV cache, but not FP8 block scaling, NVFP4 KV cache, AWQ, or GPTQ. Gemma 4 is not listed in the model quantization matrix, so the directly documented exact path is native checkpoint dtype plus generic/pre-quantized ModelOpt paths, not a Gemma-4-31B-specific validated quantized checkpoint.

Sources:
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/release-notes.md
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/features/quantization.md

### RTX PRO 6000 Blackwell support

The public supported-hardware page lists Blackwell B200/GB200/B300/GB300/DGX Spark, but not RTX PRO 6000. TensorRT-LLM source explicitly recognizes “SM120/121 (RTX PRO 6000 Blackwell)” and disables MNNVL-class all-to-all kernels because those SKUs lack NVSwitch fabric. This means the code has RTX PRO 6000-specific behavior, but the docs’ official supported-hardware list is narrower.

Sources:
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/supported-hardware.md
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/tensorrt_llm/_mnnvl_utils.py#L480-L484

### OpenAI-compatible serving

`trtllm-serve` starts an OpenAI-compatible server with `/v1/models`, `/v1/completions`, `/v1/chat/completions`, plus health/metrics/version. The docs also describe Chat, Completions, and Responses API examples. For multimodal models, TensorRT-LLM docs state `kv_cache_reuse` is not compatible and only Chat API is supported because multimodal models require a chat template.

Source: https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/commands/trtllm-serve/trtllm-serve.rst

### Containers and drivers

TensorRT-LLM’s simplest install path is the NGC release container `nvcr.io/nvidia/tensorrt-llm/release:x.y.z`. Pip install docs currently require CUDA Toolkit 13.2 and may require `cuda-compat-13-2` depending on host driver. Dynamo stable 1.4.0 publishes `nvcr.io/nvidia/ai-dynamo/tensorrtllm-runtime:1.4.0`, pins TRT-LLM `v1.3.0rc22`, uses CUDA 13.1, and requires NVIDIA driver `580+`.

Sources:
- https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/installation/installation-guide.md
- https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tensorrt-llm/containers/release/tags
- https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/reference/general/release-artifacts.mdx
- https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/reference/general/compatibility.mdx

### Dynamo fit

Dynamo TensorRT-LLM integrates TRT-LLM into a distributed runtime with disaggregated serving, KV-aware routing, multi-node, request cancellation, speculative decoding, and attention data parallelism. Its TensorRT-LLM backend config is not just a drop-in `trtllm-serve`: model, served name, TP/PP/EP, KV sizing, disaggregation mode, and low-level engine passthrough are configured through `DYN_TRTLLM_*` flags, YAML files, and/or Kubernetes specs. Dynamo’s speculative-decoding overview marks TensorRT-LLM as “not yet documented.”

Sources:
- https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/developer-guide/knowledge-base/modular-components/backends/tensorrt-llm/overview.md
- https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/reference/backends/tensorrt-llm-configuration.mdx
- https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/developer-guide/additional-resources/speculative-decoding/overview.md

## Recommendation

Use **raw TensorRT-LLM `trtllm-serve` first** for the exact Gemma 4 31B target. Pin the newest NGC TensorRT-LLM release/RC that contains `Gemma4AssistantForCausalLM`, run `google/gemma-4-31B-it`, and only enable MTP via YAML after a baseline text-only run works. Treat Dynamo as a second phase if you need KV-aware routing, disaggregated serving, or Kubernetes orchestration; do not assume Dynamo stable 1.4.0 has the same Gemma 4 MTP capability as TensorRT-LLM `main`.
