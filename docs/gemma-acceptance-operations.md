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
evals/training.jsonl
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
step, 16,384-token training/evaluation bounds, exact training/development taskset and package
digests, the mechanics-only `0.001` anti-degeneracy weight, `proof-final`, and the
language-layer-only LoRA target regex from the proof document.
`optimization-metrics.json` contains finite numeric `loss`, `gradient_norm`, and `mismatch_kl`.
No acceptance threshold is invented.

The training JSONL contains eight canonical rollouts from the frozen 96-row training package.
Both evaluation JSONL files contain the same two disjoint identities from the frozen development
package. Every version-2 normalized row contains its scenario/rollout identity, normalized model, accepted
tool-result count, trace and result digests, the complete canonical `RunSnapshot`, and ordered
model-call receipts with served model, finish reason, and native token counters. The verifier
recomputes both canonical digests, validates the terminal Verifier boundary, replays every action
against the frozen split, and requires the model-call lineage to reconcile with accepted actions.

The baseline model is the exact selected checkpoint; the post-reload model is `proof-final`.
Digest-shaped strings or log assertions without the snapshot and call lineage cannot pass. The one
original version-1 artifact is accepted only under its fixed job identity and whole-tree digest;
version 1 is not a general import route.

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

The verifier parses safetensors directly; requires the exact 28 rank-8 BF16 projection tensors;
compares pre/post bytes; uses a code-free whitelist unpickler to validate DCP state/planner/storage
objects, model and optimizer entries, metadata-to-shard paths, contiguous byte ranges, and every
embedded ZIP boundary; reconciles finite metrics; checks exact pins and configuration; validates
model-call lineage; and cryptographically validates and scientifically replays every canonical
snapshot. It emits only sanitized digests and counts.

The disposable probe verifier also accepts `--product-acceptance-root` so its native mechanical
checks and the product-owned acceptance checks can be required in one invocation.

## External gate result

Complete. The approved training workstation produced the bounded E4B adapter and checkpoint; the
second approved workstation independently loaded the byte-identical adapter as `proof-final` and
completed both predeclared tool loops. The authoritative version-2 imported artifact is
`sha256:13839168b5f4e23f37d6f3a89ec50c51bebbd6a4be4fa888fcc5b0839a007620`.
No unrelated GPU work was terminated or silently shared.
