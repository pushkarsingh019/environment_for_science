# Bounded Gemma acceptance operations

Ticket 10 requires real CUDA evidence. Queuing a job or passing fixture tests does not complete the
ticket. The Mac runs only the Scientist Console, artifact verification, and orchestration; model
loading, inference, forward/backward execution, optimization, save, unload, reload, and held-out
tool loops run on the two approved GPU workstations over private transport.

Follow the exact stack, E4B-first resource gate, model download verification, one-step prime-rl
commands, and E2B-only resource-failure fallback in
[`gemma-training-path-proof.md`](gemma-training-path-proof.md). Do not inspect an SSH inventory or
infer a workstation target. The operator must supply approved key-only connection details through
the secure channel and explicitly approve the pinned E4B download.

## Console lifecycle

1. In **Evaluate → Bounded Gemma acceptance**, queue a job.
2. Record its opaque `training-acceptance-…` identity.
3. Start the remote operation on the approved workstations, then select **Record workstation
   start**. This changes only the durable status; it starts no local compute.
4. Import the sanitized evidence tree at the fixed relative reference displayed by the console:
   `artifacts/training/training-acceptance-imports/<job-id>/`.
5. Select **Verify imported evidence**. Only independent artifact verification can complete the
   job. A failed job remains visible and can be queued again after replacing its evidence.

## Imported evidence tree

The root is closed to the following receipt references. Referenced paths must be normalized,
relative, non-symlink paths beneath the import root.

```text
receipt.json
acceptance-config.json
optimization-metrics.json
evals/baseline.jsonl
evals/reloaded.jsonl
run/broadcasts/step_0/STABLE
run/broadcasts/step_0/adapter_config.json
run/broadcasts/step_0/adapter_model.safetensors
run/broadcasts/step_1/STABLE
run/broadcasts/step_1/adapter_config.json
run/broadcasts/step_1/adapter_model.safetensors
run/checkpoints/step_1/trainer/<non-empty DCP files>
```

`acceptance-config.json` records exact model and revision, BF16 optimization and reduction, one
step, `proof-final`, and the language-layer-only LoRA target regex from the proof document.
`optimization-metrics.json` contains finite numeric `loss`, `gradient_norm`, and `mismatch_kl`.
No acceptance threshold is invented.

Both evaluation JSONL files contain the same two disjoint acceptance scenario identities. Every
row has exactly:

```json
{
  "scenario_id": "acceptance-heldout-001",
  "model": "proof-final",
  "ok": true,
  "tool_calls": 2,
  "trace_error": null,
  "runtime_trace_digest": "sha256:<64 hex>",
  "result_digest": "sha256:<64 hex>"
}
```

The baseline model is the exact selected checkpoint; the post-reload model is `proof-final`.
Digests must come from completed canonical Runtime and Verifier evidence, not log text.

`receipt.json` binds the job, exact stack pins, selected model, fallback decision, two distinct
sanitized hardware-receipt digests, private transport, configuration digest, and relative paths.
For E4B, fallback is `{ "used": false, "reason": null }`. E2B is accepted only with
`{ "used": true, "reason": "e4b_resource_failure" }` after preserving the genuine E4B resource
failure.

## Independent verification

Run before import:

```bash
.venv/bin/python scripts/verify_training_acceptance.py <artifact-root>
```

The verifier parses safetensors directly, requires stable PEFT directories, proves every adapter
key is under `model.language_model.layers.`, compares pre/post tensor bytes, requires at least one
changed tensor, verifies a non-empty DCP checkpoint, reconciles finite metrics, checks exact pins
and configuration, and verifies baseline/reloaded multi-turn trace rows. It emits only sanitized
digests and counts.

The disposable probe verifier also accepts `--product-acceptance-root` so its native mechanical
checks and the product-owned acceptance checks can be required in one invocation.

## Current external gate

The approved training workstation and E4B download are authorized, and the real one-step EEG run
passes. Ticket 10 remains in progress until the second approved workstation is idle, independently
loads the saved adapter under `proof-final`, completes the same disjoint tool loops, and contributes
a distinct sanitized hardware receipt to an imported tree. Existing unrelated GPU work is never
terminated or silently shared around this gate.
