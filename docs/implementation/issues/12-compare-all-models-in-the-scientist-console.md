# 12: Compare all models in the Scientist Console

**What to build:** Present base Gemma, reloaded trained Gemma, GPT, and Gemini under one scientifically interpretable comparison, with provenance, uncertainty, failure visibility, and replay links, while keeping mesoscope platform evidence separate from the EEG training claim.

**Blocked by:** 07: Prove mesoscope portability through the same compiler; 08: Evaluate GPT through OpenAI Responses; 09: Evaluate Gemini through Interactions; 11: Train Gemma on the EEG curriculum

**Status:** complete — real inconclusive Gemma comparison imported with explicit hosted unavailability

- [x] The results view identifies every requested and returned model, adapter, run, scenario-manifest, Environment Bundle, and scoring revision.
- [x] Base and trained Gemma display the paired EEG success difference and 95% bootstrap interval as the primary evidence.
- [x] The UI claims improvement only when the approved statistical rule passes.
- [x] Task success, verifier score, abort precision/recall, action count, tool errors, and individual/ambiguous/pair/triple strata are visible without overwhelming the default view.
- [x] GPT and Gemini are labeled reference models and are not presented as mandatory targets for trained Gemma to beat.
- [x] Mesoscope results appear as a separate platform-generality track and do not imply cross-Apparatus training.
- [x] Every aggregate result opens the exact constituent scenarios and canonical replays.
- [x] Provider, adapter, inference, and scientific failures remain distinguishable and are not silently converted into zero scientific scores.
- [x] Missing hosted-provider credentials produce an explicit readiness state rather than fabricated live results.
- [x] Seeded offline result fixtures keep the comparison interface demonstrable without external APIs and are unmistakably labeled as fixtures.
- [x] Browser tests cover successful, inconclusive, regressed, partially unavailable, and adapter-error comparison states.

## Implementation readiness

The comparison result contract binds requested and returned model identities, adapter and run
identities, the sealed scenario manifest, Environment Bundle revision, scoring revision, all
constituent scenario receipts, and replay routes. Base and trained Gemma use the paired bootstrap
as primary evidence and cannot claim a win unless its positive interval excludes zero. GPT and
Gemini are visibly reference models; missing credentials or provider evidence remain unavailable
rather than becoming zero scores. Provider, adapter, and scientific failures are distinct.

The console progressively discloses task success, verifier score, abort precision/recall, mean
actions, tool errors, and individual/ambiguous/pair/triple strata. Mesoscope remains a separate
`platform_generality` card. Five clearly labeled offline fixtures and desktop/mobile browser tests
exercise all required states and canonical replay receipts.

The immutable real comparison `model-comparison-real-253e43de7954735b` is now installed and
visibly labeled **Verified real evaluation**. It binds training result
`eeg-training-result-f802244d524f4552`, the training artifact and adapter digests, both model
configuration digests, evaluator run IDs, all 64 per-model scenario receipts, the held-out package,
Bundle `1.4.0`, and scoring revision. The primary card honestly reports 9/64 base successes versus
10/64 trained successes, difference `0.015625`, interval `[0.0, 0.046875]`, and **No supported
training win**. OpenAI and Gemini credentials were absent, so both hosted rows are explicitly
`credential_missing` with no fabricated score. Offline fixtures remain separately and
unmistakably labeled.
