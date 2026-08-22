# vLLM Gemma 4 31B-class + MTP on one RTX PRO 6000 Blackwell 96GB

Research date: 2026-08-22. Sources restricted to official vLLM docs/source/releases/issues/PRs and NVIDIA compatibility pages.

## Bottom line

- **Official support exists for Gemma 4 and Gemma 4 assistant MTP.** Current vLLM docs list `Gemma4ForCausalLM` and `Gemma4ForConditionalGeneration` as supported, and the MTP docs say the **31B Gemma 4 IT assistant checkpoint is supported** through the Gemma 4 MTP path, not generic draft-model speculation. Sources: [`supported_models.md`](https://github.com/vllm-project/vllm/blob/main/docs/models/supported_models.md#L394), [`supported_models.md` multimodal row](https://github.com/vllm-project/vllm/blob/main/docs/models/supported_models.md#L543), [`mtp.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/mtp.md#L12-L31).
- **Newest stable release to prefer from the primary sources found:** `v0.27.1` is the newest non-rc GitHub release found, but the latest release notes are not a Gemma-4-specific validation. Gemma 4 MTP first appeared in `v0.21.0` release notes. Sources: [`v0.27.1`](https://github.com/vllm-project/vllm/releases/tag/v0.27.1), [`v0.21.0`](https://github.com/vllm-project/vllm/releases/tag/v0.21.0).
- **No primary source found proves the full exact combination** `google/gemma-4-31B-it` + `google/gemma-4-31B-it-assistant` + MTP on **one RTX PRO 6000 96GB**. Primary-source evidence is split: 31B+MTP was reported working on one B300 in PR discussion, while RTX PRO 6000 evidence covers 31B without MTP and 26B-A4B with MTP. Do not treat this as an official benchmark for the exact machine.

## Hardware / CUDA / driver constraints

- NVIDIA’s CUDA GPU table lists NVIDIA RTX PRO 6000 Blackwell Server Edition and Workstation Edition under **compute capability 12.0** (SM120): <https://developer.nvidia.com/cuda-gpus>.
- NVIDIA CUDA compatibility docs list **CUDA 13.x minimum driver `>= 580`** and CUDA 12.x minimum driver `>= 525`: <https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html#minor-version-compatibility>.
- Current vLLM install docs say precompiled binaries are CUDA **12.9** by default, require compute capability **7.5+**, recommend a fresh env due CUDA/PyTorch binary compatibility, and provide CUDA 12.8/13.0 wheel variants. Source: [`gpu.cuda.inc.md`](https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.cuda.inc.md#L4-L39), [`nightly/wheel variants`](https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.cuda.inc.md#L51-L62).
- vLLM source tests skip Gemma4 assistant MTP if `transformers < 5.8.0`. Source: [`test_mtp.py`](https://github.com/vllm-project/vllm/blob/main/tests/v1/e2e/spec_decode/mtp/test_mtp.py#L81-L89).

## Model / dtype / quantization findings

- **BF16/base:** `google/gemma-4-31b-it` was shown in issue #40677 on RTX PRO 6000 with `dtype="bfloat16"`; forcing FlashInfer attention failed, but “without the override, the same model loads and runs correctly with `TRITON_ATTN`.” Source: <https://github.com/vllm-project/vllm/issues/40677>.
- **Online FP8:** issue #48238 says the workaround for `nvidia/Gemma-4-31B-IT-NVFP4` failing on v0.24.0 was “online FP8 (`--quantization fp8 --kv-cache-dtype fp8`) on the bf16 checkpoint works fine on the same setup.” Source: <https://github.com/vllm-project/vllm/issues/48238>.
- **ModelOpt/NVFP4:** vLLM ModelOpt docs say vLLM detects ModelOpt checkpoints via `hf_quant_config.json`; supports `NVFP4`; and serves ModelOpt checkpoints with `--quantization modelopt`. Sources: [`modelopt.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/modelopt.md#L11-L20), [`server example`](https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/modelopt.md#L116-L122).
- For NVFP4 checkpoints, vLLM docs say GEMM kernel selection is automatic across available platform backends, and documented override values include `cutlass`, `flashinfer_cutlass`, `flashinfer_trtllm`, `flashinfer_cudnn`, and `marlin`; use `--linear-backend`, not deprecated env vars. Source: [`modelopt.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/modelopt.md#L22-L34).
- **FP8 KV cache:** vLLM docs say `kv_cache_dtype="fp8"` defaults scales to 1.0 unless calibrated; `fp8_e4m3` and `fp8_e5m2` are supported options on CUDA 11.8+. Source: [`quantized_kvcache.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/quantized_kvcache.md#L1-L41).

## MTP/speculative decoding flags

Use Gemma 4 assistant checkpoints through `--speculative-config` with `method: "mtp"`:

```bash
--speculative-config '{"method":"mtp","model":"google/gemma-4-31B-it-assistant","num_speculative_tokens":1}'
```

Primary sources:

- vLLM MTP docs: Gemma 4 assistants are passed through `model` in `--speculative-config`, but are not generic draft models; use `"method":"mtp"`; 31B IT assistants are supported. Source: [`mtp.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/mtp.md#L14-L31).
- The CLI registers `--speculative-config` plus shorthand `--spec-method`, `--spec-model`, and `--spec-tokens`. Source: [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L1634-L1645).
- vLLM rewrites `model_type in ("gemma4_assistant", "gemma4_unified_assistant")` to `gemma4_mtp` / `Gemma4MTPModel` and sets `n_predict=1`. Source: [`speculative.py`](https://github.com/vllm-project/vllm/blob/main/vllm/config/speculative.py#L652-L661).
- If `num_speculative_tokens > 1`, vLLM source warns that most MTP model types run multiple forwards on the same MTP layer and may get lower acceptance rate. Source: [`speculative.py`](https://github.com/vllm-project/vllm/blob/main/vllm/config/speculative.py#L978-L991).

## OpenAI-compatible server flags found in official sources

Supported server/engine flags relevant to this setup include:

- `--host`, `--port`: OpenAI frontend args. Source: [`cli_args.py`](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/cli_args.py#L243-L249).
- `--dtype`, `--trust-remote-code`, `--max-model-len`, `--quantization`, `--served-model-name`, `--generation-config`: model args. Sources: [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L850-L858), [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L871-L918).
- `--gpu-memory-utilization`, `--kv-cache-dtype`, `--enable-prefix-caching`: cache args. Source: [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L1221-L1238).
- `--max-num-batched-tokens`, `--max-num-seqs`, `--async-scheduling`, `--stream-interval`: scheduler args. Source: [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L1528-L1589).
- `--moe-backend`, `--linear-backend`: kernel args. Source: [`arg_utils.py`](https://github.com/vllm-project/vllm/blob/main/vllm/engine/arg_utils.py#L1606-L1626).
- `--enable-auto-tool-choice` requires `--tool-call-parser`; `gemma4` is registered as a built-in parser. Sources: [`cli_args.py`](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/cli_args.py#L105-L115), [`tool_parsers/__init__.py`](https://github.com/vllm-project/vllm/blob/main/vllm/tool_parsers/__init__.py#L205-L213).
- `--reasoning-parser gemma4`: Gemma 4 is listed in reasoning docs with parser name `gemma4`. Source: [`reasoning_outputs.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/reasoning_outputs.md#L13-L35).
- `--per-request-spec-decode-metrics summary|detailed` reports acceptance metrics under `metrics.speculative_decoding`. Source: [`acceptance_metrics.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/acceptance_metrics.md#L1-L22).

## Backends

- **Attention:** Do not force `FLASHINFER` for Gemma 4 31B on SM120 based on issue #40677: it fails with `head_size not supported`; default loaded with `TRITON_ATTN`. Source: <https://github.com/vllm-project/vllm/issues/40677>.
- vLLM Gemma4 config source says Gemma4 has heterogeneous head dimensions; vLLM uses FA4 for all layers when FA4 is available and max head dim <=512, otherwise falls back to `TRITON_ATTN`. Source: [`config.py`](https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/models/config.py#L209-L255).
- **NVFP4 linear:** Let auto-select choose unless you are working around a specific issue; documented overrides are through `--linear-backend`. Source: [`modelopt.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/modelopt.md#L22-L34).
- **MoE backend:** 31B dense is not a MoE backend case. The RTX PRO 6000 MoE+MTP backend data in issue #47047 is for `nvidia/Gemma-4-26B-A4B-NVFP4`, not the exact 31B dense model. Source: <https://github.com/vllm-project/vllm/issues/47047>.

## Known blockers / regressions

1. **v0.24.0 + `RedHatAI/gemma-4-31B-it-FP8-block` + RTX PRO 6000 SM120:** DeepGEMM block-scaled path crashed during load with “Unknown SF transformation”; `VLLM_USE_DEEP_GEMM=0` made vLLM select Cutlass and serve cleanly. Source: <https://github.com/vllm-project/vllm/issues/47436>.
2. **v0.24.0 + `nvidia/Gemma-4-31B-IT-NVFP4`:** issue #48238 reports init failure in `quant_method.tie_weights`; a comment says fixed on main by #45544 but not in v0.24.0; online FP8 on BF16 was the workaround. Sources: <https://github.com/vllm-project/vllm/issues/48238>, <https://github.com/vllm-project/vllm/pull/45544>.
3. **Gemma4 MTP embedding sharing regression in v0.25/v0.26 line:** #47953 fixed Gemma4 MTP init shape mismatch caused by an embedding-width guard; a comment on #48848 says the fix missed v0.26.0 and users needed nightly/main or `VLLM_USE_V2_MODEL_RUNNER=1`. The fix is merged before current v0.27.1. Sources: <https://github.com/vllm-project/vllm/pull/47953>, <https://github.com/vllm-project/vllm/issues/48848#issuecomment-5093827023>.
4. **Calibrated FP8 KV scales + Gemma4 MTP:** open PR #49262 says Gemma4 MTP draft layers can read shared target KV cache with wrong scales for calibrated FP8 KV targets such as `unsloth/gemma-4-31b-it-nvfp4`, collapsing acceptance and costing ~30% decode throughput; PR was still open/conflicted in the fetched GitHub metadata. Source: <https://github.com/vllm-project/vllm/pull/49262>.
5. **Forcing FlashInfer attention:** issue #40677 shows `google/gemma-4-31b-it` on RTX PRO 6000 fails when `FLASHINFER` attention is forced; default `TRITON_ATTN` worked. Source: <https://github.com/vllm-project/vllm/issues/40677>.

## Performance-relevant settings to verify, not infer

- Track acceptance using `--per-request-spec-decode-metrics summary` or Prometheus metrics before deciding `num_speculative_tokens`. Source: [`acceptance_metrics.md`](https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/acceptance_metrics.md#L1-L22).
- Watch `max_num_batched_tokens` when enabling MTP. In issue #47047, vLLM nightly warned: “max_num_scheduled_tokens is set to 4096 based on the speculative decoding settings… Consider increasing max_num_batched_tokens to accommodate the additional draft token slots, or decrease num_speculative_tokens or max_num_seqs.” Source: <https://github.com/vllm-project/vllm/issues/47047#issuecomment-4842116893>.
- For text-only Gemma 4 runs, vLLM’s Gemma4 MTP test path sets `limit_mm_per_prompt={"image":0,"audio":0}` for Gemma 4 models. Source: [`test_mtp.py`](https://github.com/vllm-project/vllm/blob/main/tests/v1/e2e/spec_decode/mtp/test_mtp.py#L74-L80).

## Safe starting command shape

This command shape uses only supported flags from vLLM docs/source. Numeric capacity knobs must be benchmarked on the target RTX PRO 6000 and context length.

```bash
vllm serve google/gemma-4-31B-it \
  --served-model-name gemma4-31b-mtp \
  --host 0.0.0.0 --port 8000 \
  --dtype bfloat16 \
  --max-model-len <choose> \
  --gpu-memory-utilization <choose> \
  --max-num-batched-tokens <choose> \
  --max-num-seqs <choose> \
  --kv-cache-dtype fp8 \
  --limit-mm-per-prompt '{"image":0,"audio":0}' \
  --generation-config vllm \
  --speculative-config '{"method":"mtp","model":"google/gemma-4-31B-it-assistant","num_speculative_tokens":1}' \
  --reasoning-parser gemma4 \
  --enable-auto-tool-choice --tool-call-parser gemma4 \
  --per-request-spec-decode-metrics summary
```

For ModelOpt/NVFP4 checkpoints, replace the model path and add `--quantization modelopt` if auto-detection is not sufficient; use `--linear-backend ...` only as a documented override for a measured backend issue.
