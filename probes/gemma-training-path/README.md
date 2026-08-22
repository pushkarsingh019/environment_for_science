# Disposable Gemma training-path probes

These files test framework mechanics only. They are not a scientific Environment,
a benchmark, or evidence that training improved a model.

- `taskset/`: disjoint four-row train and two-row held-out Verifiers v1 tasksets
  with one stateful MCP tool.
- `fake_vllm_token_server.py`: CPU-only token-in endpoint that emits canonical
  Gemma 4 tool-call tokens and aligned fake log probabilities.
- `configs/`: bounded E4B inference, one-step LoRA GRPO, and held-out eval configs.
- `verify_smoke_artifacts.py`: fail-closed check for changed adapter tensors, a
  DCP checkpoint, stable PEFT broadcast, and successful baseline/reloaded traces.

The training task's `mechanical_jitter` reward has weight `0` by default. The
one-step RL config gives it weight `0.001` solely to prevent an all-equal GRPO
group. It must stay disabled in held-out evaluation.

## Run the local token-plumbing probe

From the `probes/gemma-training-path` directory, create a Python 3.12 virtual
environment that contains the package versions in the proof document. Set
`PRIME`, `RENDERERS`, and `VENV` to the exact source checkouts and virtual
environment. This probe downloads only the pinned E4B tokenizer, not model
weights.

```bash
export HF_HOME=/tmp/gemma-training-proof-hf
uv pip install --python "$VENV/bin/python" --no-deps -e "$PWD/taskset"

PYTHONPATH="$RENDERERS" HF_HOME="$HF_HOME" \
  "$VENV/bin/python" fake_vllm_token_server.py \
  --port 18081 --model fake-gemma-policy --log /tmp/gemma-proof-requests.jsonl &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 300); do
  curl -fsS http://127.0.0.1:18081/v1/models >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:18081/v1/models >/dev/null

PATH="$(dirname "$(command -v uv)"):$VENV/bin:$PATH" \
PYTHONPATH="$RENDERERS:$PRIME/deps/verifiers" HF_HOME="$HF_HOME" \
  "$VENV/bin/eval" gemma-training-proof \
  --env.taskset.split eval -m fake-gemma-policy -n 2 -r 1 -c 2 \
  --client.type train --client.base-url http://127.0.0.1:18081/v1 \
  --client.renderer.name gemma4 \
  --client.renderer-model-name google/gemma-4-E4B-it \
  --sampling.temperature 1 --sampling.max-tokens 128 \
  --env.agent.harness.id null --env.agent.runtime.type subprocess \
  --server --no-rich --no-push --clean \
  --output-dir /tmp/gemma-proof-local --run.name train-client
```

The run passes when both traces have the roles
`user, assistant, tool, assistant`, a `protocol` reward of `1.0`, and aligned
sampled masks and log probabilities.

See [`docs/gemma-training-path-proof.md`](../../docs/gemma-training-path-proof.md)
for exact source pins, recorded results, and the secure GPU handoff.
