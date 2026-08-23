# 10: Train, save, reload, and evaluate a bounded Gemma adapter

**What to build:** Run the smallest real two-workstation Gemma E4B acceptance path from an EEG Environment trace through LoRA optimization, resumable and portable checkpoint output, inference reload, held-out tool use, and visible job status.

**Blocked by:** 06: Evaluate EEG through Verifiers and local base Gemma

**Status:** in-progress — software and fail-closed artifact verification are ready; real approved-workstation evidence is required

- [ ] The run uses the pinned prime-rl, Verifiers, Transformers, PyTorch, vLLM, and audited Gemma-compatible renderer revisions.
- [ ] The exact Gemma E4B checkpoint revision is used; E2B is attempted only as the recorded bounded fallback after a genuine E4B resource failure.
- [ ] Training and inference run only on the approved workstations, using private transport and without model compute on the Mac.
- [ ] LoRA targets only language-layer projection modules and explicitly uses BF16 optimization and reduction.
- [ ] At least one real optimizer step completes with finite loss, gradient norm, and mismatch KL recorded without inventing an acceptance threshold.
- [ ] The run writes non-empty resumable trainer state and a stable PEFT-compatible adapter artifact.
- [ ] Artifact verification proves at least one adapter tensor changed between pre-step and post-step broadcasts.
- [ ] The adapter is unloaded, reloaded into inference under a fresh served identity, and completes disjoint held-out multi-turn tool scenarios without trace errors.
- [ ] The existing artifact verifier is extended or reused to fail on missing checkpoints, unchanged tensors, incomplete adapters, or failed reload evaluation.
- [ ] The Scientist Console shows queued, running, failed, and completed acceptance-job states in ordinary language and links to sanitized artifacts and traces.
- [ ] Revisions, model identity, configuration digest, hardware identity, and artifact digests are recorded without credentials or private host details.
- [ ] Passing evidence is sufficient to resolve decision ticket 03; logs alone are not accepted as proof.

## Implementation readiness

The console now persists queued, running, failed, retried, and completed acceptance jobs without
starting local compute. The product verifier independently checks exact stack and model pins,
E4B-first fallback evidence, BF16 and language-only LoRA configuration, finite optimization
metrics, non-empty DCP state, stable PEFT artifacts, changed safetensor bytes, distinct sanitized
workstation receipts, fresh `proof-final` reload identity, and matched held-out multi-turn Runtime
trace rows. The disposable probe can require this product evidence in the same verification pass.

The remaining gate is intentionally external: supply approved key-only workstation connection
details and explicit approval for the pinned E4B download, run the bounded CUDA sequence, and
import evidence that passes the verifier. See
[the bounded acceptance operator procedure](../../gemma-acceptance-operations.md).
