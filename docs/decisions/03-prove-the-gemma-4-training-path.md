# Prove the Gemma 4 training path

Type: task
Status: open
Blocked by:

## Question

Can a pinned self-managed Verifiers v1 and prime-rl stack evaluate and train
a text-first, multi-turn, tool-calling Gemma 4 policy with LoRA GRPO, preserve
usable traces, save a checkpoint, and reload it for held-out evaluation? Run
the smallest decisive probes, then choose a primary Gemma checkpoint and a
fallback size while recording exact versions, configuration, hardware
assumptions, and blockers.

## Progress

The CPU/source probes pass with E4B as the primary training checkpoint and E2B
as the fallback. The pinned prime-rl checkout requires an exact later
`renderers` commit for Gemma tool calls. The ticket remains open until the
bounded GPU test trains, saves, reloads, and evaluates an adapter. See
[the proof plan and local results](../gemma-training-path-proof.md).
