# research-4-deployment: single-directory RTX PRO 6000 Blackwell OpenAI-compatible serving

## Recommendation

Use **Docker Compose + NVIDIA Container Toolkit + vLLM OpenAI server**, with an optional small reverse proxy in front of vLLM. Keep everything below one root, for example `/srv/llm-openai`. Bind the only published port to the host's **Tailscale IP**, not to `0.0.0.0`, and keep vLLM itself un-published on the Compose network.

Why vLLM as the default:

- vLLM provides an HTTP server implementing OpenAI-compatible completions, chat completions, responses, embeddings, transcription, and translation endpoints, and can be used with the official OpenAI Python client. Source: vLLM OpenAI-compatible server docs.
- vLLM publishes a Docker image and documents mounting Hugging Face cache and `VLLM_CACHE_ROOT` so model downloads and compile artifacts survive container replacement. Source: vLLM Docker docs.
- vLLM has first-party docs for BF16/FP8/INT quantization choices, FP8 KV cache, security limitations, and benchmarking metrics. Sources: vLLM quantization, KV cache, security, and benchmarking docs.

Keep **NVIDIA NIM** as the enterprise-supported alternative if you need NVIDIA-curated containers, NGC catalog flows, or NVIDIA AI Enterprise support. NIM LLM 2.x exposes OpenAI-compatible endpoints and has model-specific/model-free containers, but adds NGC/HF credential and licensing considerations. Source: NVIDIA NIM LLM docs.

## Single-directory layout

```text
/srv/llm-openai/
  compose.yaml
  .env                         # chmod 600; never commit
  config/
    vllm.yaml
    nginx.conf                  # optional endpoint allowlist proxy
  data/
    huggingface/                # HF_HOME and HF_HUB_CACHE
    vllm/                       # VLLM_CACHE_ROOT and compile cache
    models/                     # optional local or quantized checkpoints
  logs/
    vllm/
    nginx/
  bench/
    datasets/
    results/
```

Docker bind mounts are appropriate here because Docker documents them as a way to persist generated files and share host configuration with containers. Docker also warns that bind mounts are writable by default and let container processes change host files, so mount configs read-only and restrict writeable paths to `data/` and `logs/`. Source: Docker bind mounts docs.

Create the root with restrictive ownership. vLLM documents that the CUDA image runs as root by default but supports the built-in `vllm` user `UID 2000, GID 0`; for non-root containers, mount writable paths under `/home/vllm` and make them writable by group 0. Source: vLLM Docker docs.

## Example Compose shape

```yaml
# /srv/llm-openai/compose.yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    user: "2000:0"
    ipc: host
    env_file: .env
    environment:
      HF_HOME: /home/vllm/.cache/huggingface
      HF_HUB_CACHE: /home/vllm/.cache/huggingface/hub
      VLLM_CACHE_ROOT: /home/vllm/.cache/vllm
      VLLM_MAX_N_SEQUENCES: "128"
    volumes:
      - ./data/huggingface:/home/vllm/.cache/huggingface
      - ./data/vllm:/home/vllm/.cache/vllm
      - ./data/models:/models
      - ./config/vllm.yaml:/etc/vllm/config.yaml:ro
      - ./logs/vllm:/var/log/vllm
    entrypoint: ["/bin/bash", "-lc"]
    command:
      - >-
        exec > >(tee -a /var/log/vllm/server.log) 2>&1;
        exec vllm serve --config /etc/vllm/config.yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ["0"]
              capabilities: [gpu]

  proxy:
    image: nginx:alpine
    depends_on: [vllm]
    ports:
      - "${TAILSCALE_IP}:8000:8000"
    volumes:
      - ./config/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./logs/nginx:/var/log/nginx
```

Docker Compose's GPU support requires `capabilities: [gpu]`; `count` and `device_ids` are mutually exclusive. Source: Docker Compose GPU support docs. NVIDIA Container Toolkit documents Docker configuration with `nvidia-ctk runtime configure --runtime=docker`, and NVIDIA's specialized Docker docs describe using Docker's `--gpus` option or `NVIDIA_VISIBLE_DEVICES` to select accessible GPUs. Sources: NVIDIA Container Toolkit install guide and Docker specialized configuration docs.

Example vLLM config:

```yaml
# /srv/llm-openai/config/vllm.yaml
model: meta-llama/Llama-3.1-8B-Instruct
host: 0.0.0.0
port: 8000
dtype: auto
# Use VLLM_API_KEY from .env rather than writing the secret into this file.
generation-config: vllm
max-model-len: 32768
gpu-memory-utilization: 0.90
```

vLLM documents that CLI arguments can be loaded from a YAML config file with long-form argument names, and command-line values override config-file values. Source: vLLM server arguments docs.

Example proxy allowlist:

```nginx
server {
  listen 8000;
  access_log /var/log/nginx/access.log;
  error_log  /var/log/nginx/error.log warn;

  client_max_body_size 8m;

  location /v1/ {
    proxy_pass http://vllm:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 1h;
  }

  location = /health { proxy_pass http://vllm:8000/health; }
  location / { return 404; }
}
```

The proxy is not just cosmetic: vLLM documents that `--api-key` protects `/v1`, `/v2`, and `/inference` path prefixes but does **not** protect other endpoints such as `/invocations`, operational endpoints, `/health`, `/version`, and others. vLLM recommends a reverse proxy that explicitly allowlists exposed endpoints. Source: vLLM security docs.

## Tailscale-only exposure

- Publish `TAILSCALE_IP:8000:8000`, not `8000:8000`. Docker documents that published ports listen on all host interfaces by default (`0.0.0.0`/`::`) and that `HOST_IP:HOST_PORT:CONTAINER_PORT` binds a specific interface. Source: Docker port publishing docs.
- Use Tailscale ACLs/tailnet policy to allow only intended users or groups to reach `tag:llm-server:8000`. Tailscale documents that, without access control policies, the default policy is allow-all; to deny all traffic, use an empty `acls` section. Source: Tailscale ACL docs.
- Use a tagged auth key or interactive `tailscale up` for unattended servers. Tailscale documents one-off and reusable auth keys, warns reusable keys can be dangerous if stolen, and supports tagged devices. Source: Tailscale auth key docs.
- Keep `VLLM_API_KEY` enabled anyway, but do not rely on it as the sole boundary because of vLLM's unprotected endpoints. Source: vLLM security docs.
- Also keep host firewall rules: allow inbound TCP 8000 only on the Tailscale interface/IP, deny public NICs.

## Credentials, licenses, and prerequisites

Required for the recommended vLLM path:

1. **NVIDIA driver on the host** and an RTX PRO 6000 Blackwell visible in `nvidia-smi`.
2. **Docker Engine and Compose**.
3. **NVIDIA Container Toolkit** configured for Docker. NVIDIA documents `sudo nvidia-ctk runtime configure --runtime=docker` followed by restarting Docker. Source: NVIDIA Container Toolkit install guide.
4. **Hugging Face token** if the selected model is private or gated. Hugging Face documents `HF_TOKEN`, `HF_HOME`, and `HF_HUB_CACHE`; gated model access requests are granted to individual users, and users must share contact information with model authors when access requests are enabled. Sources: Hugging Face Hub environment variables and gated model docs.
5. **Model license acceptance** for gated/commercial models, such as Llama-family checkpoints. The token alone is not enough if the account has not been granted model access.
6. **Generated service API key** for `VLLM_API_KEY`; store in `.env` with `chmod 600`.
7. **Tailscale account/tailnet permissions** to register the host, tag it, and edit ACLs.

Optional if using NVIDIA NIM instead:

- NIM current public-catalog model-specific containers can be eligible for keyless access, but NIM documents that an NGC API key is required for Production Branch models or NIMs released before NIM LLM 2.0.10. Model-source credentials such as `HF_TOKEN` may still be required. Source: NVIDIA NIM quickstart.
- NVIDIA NIM docs mention NVIDIA AI Enterprise licensing and free evaluation licensing for production/support paths. Source: NVIDIA NIM prerequisites.

## BF16, FP8, and lower-bit quantization choices

Treat BF16 as the quality baseline and benchmark everything else against it.

| Choice | Use when | Throughput expectation | Quality risk | Notes |
| --- | --- | --- | --- | --- |
| BF16 / `dtype: auto` | Model fits in 96 GB with target context/concurrency | Baseline | Lowest | Best first boot and correctness baseline. More GPU memory goes to weights, leaving less for KV cache/concurrency. |
| Online FP8 weights (`--quantization fp8`) | Need quick memory reduction without producing a new checkpoint | Can improve throughput, but vLLM says latency gains are limited in dynamic mode because activation scales are computed each forward pass | Low-to-medium; must eval | vLLM documents online dynamic FP8 for BF16/FP16 checkpoints. |
| Static/calibrated FP8 checkpoint | Need better throughput/memory tradeoff while preserving quality | vLLM docs state FP8 quantization can reduce model memory 2x and improve throughput up to 1.6x with minimal accuracy impact, but verify on the exact model/workload | Low-to-medium after eval | Prefer llm-compressor or vendor-provided FP8 checkpoints. |
| FP8 KV cache | Need longer context or higher concurrency | Can improve throughput by fitting more tokens in memory | Medium unless calibrated | vLLM documents FP8 KV cache to reduce KV memory and improve throughput/long contexts; recommended calibration uses llm-compressor. |
| INT4/GPTQ/AWQ/Marlin/bitsandbytes | Model otherwise does not fit, or low-QPS latency/memory is more important than exact quality | Highly model/kernel dependent | Highest | vLLM supports many formats; TGI notes bitsandbytes can be slower than GPTQ or FP16, and pre-quantized formats often require matching checkpoints. |

Do not report generic speed numbers for the RTX PRO 6000. Report only measurements from the exact GPU, driver, container tag, model revision, sequence lengths, quantization recipe, and concurrency settings.

## Latency versus throughput

- **Latency** is per-request experience: time to first token (TTFT), inter-token latency (ITL), time per output token (TPOT), and end-to-end latency. vLLM defines these in its benchmarking docs.
- **Throughput** is aggregate service capacity: requests/sec, output tokens/sec, and total tokens/sec. vLLM `bench serve` reports these separately from latency.
- These can trade off. Larger batching and higher request rate can increase tokens/sec while worsening p95/p99 TTFT or ITL. vLLM's chunked-prefill docs explicitly discuss tuning `max_num_batched_tokens`: smaller values can improve ITL; higher values can improve TTFT; larger values are recommended for optimal throughput on smaller models on large GPUs. Source: vLLM optimization docs.

## Benchmark methodology

1. **Record the immutable run sheet**: GPU model, driver, CUDA runtime, Docker image digest, vLLM/SGLang/TGI/NIM version, model repo and commit, quantization config, context length, `gpu-memory-utilization`, `max-num-seqs`, `max-num-batched-tokens`, and cache warm/cold state.
2. **Warm up**: start once to download weights and compile kernels; restart and use warm `HF_HOME` and `VLLM_CACHE_ROOT` for steady-state runs. vLLM documents compile cache reuse under `VLLM_CACHE_ROOT` and what can invalidate it. Source: vLLM optimization docs.
3. **Quality gate**: run BF16 baseline on domain prompts and a public harness such as `lm_eval` for relevant tasks. vLLM's FP8 docs show evaluating quantized models with `lm_eval` and warn about BOS-token sensitivity.
4. **Latency test**: use `vllm bench latency` for controlled single-batch latency, then `vllm bench serve` against the online API for TTFT/TPOT/ITL under realistic request shapes. vLLM documents `bench {latency, serve, throughput}` and the metrics emitted by `bench serve`.
5. **Throughput sweep**: run `vllm bench serve` with a representative dataset such as ShareGPT or a controlled random input/output length, then ramp request rate or concurrency until a defined latency SLO fails. vLLM documents ramp-up strategies for stress testing and finding maximum throughput under a latency budget.
6. **Compare variants**: BF16, online FP8, static FP8, FP8 KV cache, and one lower-bit candidate. Use the same prompts, output limits, sampling parameters, and request-rate schedule.
7. **Report distributions, not anecdotes**: p50/p95/p99 TTFT, TPOT/ITL, end-to-end latency, successful request count, error count, output tokens/sec, total tokens/sec, GPU memory, and vLLM preemption warnings.

## Serving-engine options checked

| Engine | OpenAI-compatible API | Docker/runtime posture | Quantization posture | Fit for this task |
| --- | --- | --- | --- | --- |
| vLLM | Yes: OpenAI completions/chat/responses and clients | Official Docker docs, non-root guidance, cache guidance | Broad quantization docs: FP8, INT8/INT4, AWQ, GPTQ, bitsandbytes, FP8 KV cache | **Best default** for clean single-GPU research deployment. |
| SGLang | Yes: OpenAI-compatible API docs and OpenAI client examples | Has official launch/server docs and Docker development docs | Server args include `--dtype`, `--quantization`, and FP8 KV cache; docs include Blackwell/SM120 notes for some DSA backends | Strong alternative for specific models/backends; test if it beats vLLM for your chosen model. |
| Hugging Face TGI | Yes: `/v1/chat/completions` and OpenAI client docs | Official Docker `--gpus all`, `/data` volume examples | Supports GPTQ, AWQ, bitsandbytes, EETQ, Marlin, EXL2, fp8; some are on-the-fly, others need pre-quantized weights | Good HF ecosystem option; less central here than vLLM for cache/security/benchmark controls. |
| NVIDIA NIM LLM | Yes: docs describe OpenAI-compatible endpoints | NVIDIA-curated containers; local cache mounted at `/opt/nim/.cache` | Model-specific curated profiles or model-free backend images based on vLLM/SGLang | Best if enterprise support/licensing and NGC workflow matter more than maximum transparency. |

## Primary sources

- Docker bind mounts: <https://docs.docker.com/engine/storage/bind-mounts/>
- Docker port publishing: <https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/>
- Docker Compose GPU support: <https://docs.docker.com/compose/how-tos/gpu-support/>
- NVIDIA Container Toolkit install guide: <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>
- NVIDIA Container Toolkit Docker specialized configuration: <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html>
- vLLM OpenAI server docs: <https://github.com/vllm-project/vllm/blob/main/docs/serving/online_serving/openai_compatible_server.md>
- vLLM Docker docs: <https://github.com/vllm-project/vllm/blob/main/docs/deployment/docker.md>
- vLLM server/config docs: <https://github.com/vllm-project/vllm/blob/main/docs/configuration/serve_args.md>
- vLLM optimization docs: <https://github.com/vllm-project/vllm/blob/main/docs/configuration/optimization.md>
- vLLM quantization docs: <https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/README.md>
- vLLM FP8 docs: <https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/llm_compressor/fp8.md>
- vLLM FP8 KV cache docs: <https://github.com/vllm-project/vllm/blob/main/docs/features/quantization/quantized_kvcache.md>
- vLLM security docs: <https://github.com/vllm-project/vllm/blob/main/docs/usage/security.md>
- vLLM benchmarking docs: <https://github.com/vllm-project/vllm/blob/main/docs/benchmarking/cli.md>
- SGLang OpenAI API docs: <https://github.com/sgl-project/sglang/blob/main/docs/docs/basic_usage/openai_api.mdx>
- SGLang server arguments: <https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/server_arguments.mdx>
- Hugging Face TGI consuming/OpenAI docs: <https://github.com/huggingface/text-generation-inference/blob/main/docs/source/basic_tutorials/consuming_tgi.md>
- Hugging Face TGI quantization docs: <https://github.com/huggingface/text-generation-inference/blob/main/docs/source/conceptual/quantization.md>
- NVIDIA NIM LLM overview: <https://docs.nvidia.com/nim/large-language-models/latest/about-nim-llm/overview.html>
- NVIDIA NIM LLM prerequisites: <https://docs.nvidia.com/nim/large-language-models/latest/get-started/prerequisites.html>
- NVIDIA NIM LLM quickstart: <https://docs.nvidia.com/nim/large-language-models/latest/get-started/quickstart.html>
- Hugging Face Hub environment variables: <https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables>
- Hugging Face gated models: <https://huggingface.co/docs/hub/en/models-gated>
- Tailscale ACL docs: <https://tailscale.com/kb/1018/acls>
- Tailscale auth keys: <https://tailscale.com/kb/1085/auth-keys>
