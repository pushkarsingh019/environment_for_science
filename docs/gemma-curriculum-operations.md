# Operate the bounded EEG curriculum run

This procedure closes implementation Ticket 11 without weakening the training, held-out, or
workstation boundaries. It is an operator handoff, not a claim that a two-language-layer LoRA run
represents full-model training.

## Fixed scope

- Model: `google/gemma-4-E4B-it` at
  `ee0ef6023621cff504d758262d4e04895a5af4a2`.
- prime-rl: `1e756307ae7b29c31fd202e6fac9afd7e23db18b`; Verifiers:
  `4bcb48e55a35c199d9d2f9722060fda627306aa3`; renderer:
  `f770dcaa362e3a6a13a96f039741b3b84ca4114e`.
- Audited compatibility patch digest:
  `sha256:5212b67327cba8bc208432c70e33f56334e0aea702202bee9c2e93decbc016f3`.
- Training: 96 source-ordered optimizer steps, group size 4, GRPO, BF16 optimization and
  reduction, 16,384-token sequence bound, 128 completion tokens, temperature 1, and a
  900-second rollout bound.
- Bounded trainer: two Gemma language layers with rank-8, alpha-16 LoRA over language projection
  modules only. The complete pinned E4B checkpoint remains the inference policy.
- Reward: scientific reward weight 1; trace-ID mechanical jitter weight 0.
- Evaluation: 16,384-token context, 256 completion tokens, temperature 0, 65 turns, at most 64
  accepted/provider tool calls, and a 900-second rollout bound.
- Adapter selection: final step 96, declared before any held-out run. Development or held-out
  outcomes must not change prompts, rewards, hyperparameters, stopping, or selection.

The immutable package digests are:

| Split | Rows | Package digest |
| --- | ---: | --- |
| Training | 96 | `sha256:8b99d39bd0b05ba81c5f36bc463416c9b979c22d96ec9d42101c8d140651986c` |
| Development | 32 | `sha256:1997bf9ff6f2c56a63928ef1392564f7c8cc6b29484b82b2baf43fb31e1d0197` |
| Held-out | 64 | `sha256:fb0a33c80e89143fb1c6da8ff39e56636a1e290fe91ce5e282cc779b9b605fd7` |

## Preflight

1. Complete Ticket 10 and verify its two-workstation evidence through the product verifier.
2. Use only an approved Linux GPU workstation. The local computer may coordinate files and show
   evidence but must not load the model, optimize it, or run inference.
3. Require private, key-only transport and loopback model routes. Do not place credentials,
   workstation names, endpoints, or host paths in receipts or UI records.
4. Confirm the GPU has no unapproved competing workload. Never terminate another user's process.
5. Compile training, development, and evaluator-held-out tasksets separately with
   `compile_prime_training_taskset`. Record each complete generated-tree digest; a package digest
   alone is not a compiled-artifact receipt.
6. Install only the split needed by the current phase. The training wheel must not contain the
   evaluator-owned held-out package, identities, seeds, records, or reserved compositions.

## Execution order

1. Start complete E4B inference on loopback and run all 32 base-development scenarios.
2. Install only the training taskset and execute the fixed 96-step configuration. Preserve every
   `train/all` trace, including replacement groups; there must be at least four rows for every one
   of the 96 identities and no provider, adapter, tool, or trace error.
3. Verify aligned training metadata using the native Verifiers layout:
   `len(token_ids) == len(mask)` and `len(logprobs) == sum(mask)` for every sampled node.
4. Require 96 finite loss, gradient-norm, and mismatch-KL records; a non-empty step-96 DCP tree;
   stable step-0 and step-96 PEFT artifacts; and at least one changed language-layer tensor.
5. Unload the training adapter. The selected step-96 adapter and evaluation configuration are now
   fixed.
6. Install the evaluator-owned held-out taskset and run base E4B over all 64 identities.
7. Load the portable adapter as `eeg-curriculum-final`, run all 32 development identities for
   diagnosis, then run the identical 64-row held-out matrix. Do not tune or rerun selection from
   these outcomes.
8. Stop the inference process cleanly. Do not disturb unrelated processes.

## Verification and import

Run `scripts/verify_curriculum_training.py` with the native run directory, all three compiled
Taskset roots, base/trained development and held-out JSONL files, exact compiled-tree digests,
training code revision, and exact model identities. The verifier independently requires:

- immutable 96/32/64 identity coverage;
- canonical Runtime snapshots and whole-native-trace digests;
- exact stack, package, Taskset, budget, sampling, reward, LoRA, and layer bounds;
- finite optimizer evidence;
- content-bound initial/final adapter and DCP digests;
- evaluator-owned write-once base and trained held-out ledgers; and
- deterministic 10,000-replicate paired bootstrap evidence.

Transfer only the verifier's sanitized evidence and comparison JSON to the product artifact root.
Validate both typed documents again locally, install the real comparison immutably, and complete
the durable curriculum job with the evidence artifact digest. Raw logs and a successful queue state
cannot complete the job.

The claim rule is fixed: report `improved` only when trained-minus-base success is positive and the
95% paired bootstrap interval excludes zero. Otherwise report `inconclusive` or `regressed` exactly
as observed. GPT and Gemini remain separately labeled references; absent hosted evidence remains
unavailable and never becomes a fabricated score.

## Failure handling

- Any missing identity, malformed native trace, infrastructure error, non-finite metric, changed
  Taskset digest, non-language adapter tensor, absent checkpoint, unsafe exported string, or
  held-out ledger mismatch fails the import.
- Preserve the sanitized failure category, leave the job failed or running, and make no scientific
  comparison claim.
- A rerun must use a new run identity. Never overwrite an accepted result or select an adapter after
  seeing held-out outcomes.
