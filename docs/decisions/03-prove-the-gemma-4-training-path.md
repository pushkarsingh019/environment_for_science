# Prove the Gemma 4 training path

Type: task
Status: resolved
Blocked by:

## Question

Can a pinned self-managed Verifiers v1 and prime-rl stack evaluate and train
a text-first, multi-turn, tool-calling Gemma 4 policy with LoRA GRPO, preserve
usable traces, save a checkpoint, and reload it for held-out evaluation? Run
the smallest decisive probes, then choose a primary Gemma checkpoint and a
fallback size while recording exact versions, configuration, hardware
assumptions, and blockers.

## Progress

E4B is the proved primary checkpoint and E2B remains only the bounded fallback.
The exact prime-rl stack plus the audited Gemma renderer and compatibility patch
completed real BF16 LoRA optimization, wrote resumable DCP and portable PEFT
artifacts, changed 14 language-layer tensors, and produced finite metrics. A
second approved workstation then loaded the transferred adapter in a fresh
process and completed both predeclared EEG tool-loop scenarios. The product
verifier imported and independently re-read the full two-workstation tree. Its strengthened
version-2 acceptance binds the DCP object graph and shard ranges, exact LoRA tensors, complete canonical Runtime
snapshots, deterministic scientific replay, and model-call lineage; artifact digest
`sha256:13839168b5f4e23f37d6f3a89ec50c51bebbd6a4be4fa888fcc5b0839a007620`
binds the authoritative accepted result. See
[the resolved proof](../gemma-training-path-proof.md).
