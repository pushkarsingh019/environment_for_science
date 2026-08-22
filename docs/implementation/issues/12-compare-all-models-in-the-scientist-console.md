# 12: Compare all models in the Scientist Console

**What to build:** Present base Gemma, reloaded trained Gemma, GPT, and Gemini under one scientifically interpretable comparison, with provenance, uncertainty, failure visibility, and replay links, while keeping mesoscope platform evidence separate from the EEG training claim.

**Blocked by:** 07: Prove mesoscope portability through the same compiler; 08: Evaluate GPT through OpenAI Responses; 09: Evaluate Gemini through Interactions; 11: Train Gemma on the EEG curriculum

**Status:** ready-for-agent

- [ ] The results view identifies every requested and returned model, adapter, run, scenario-manifest, Environment Bundle, and scoring revision.
- [ ] Base and trained Gemma display the paired EEG success difference and 95% bootstrap interval as the primary evidence.
- [ ] The UI claims improvement only when the approved statistical rule passes.
- [ ] Task success, verifier score, abort precision/recall, action count, tool errors, and individual/ambiguous/pair/triple strata are visible without overwhelming the default view.
- [ ] GPT and Gemini are labeled reference models and are not presented as mandatory targets for trained Gemma to beat.
- [ ] Mesoscope results appear as a separate platform-generality track and do not imply cross-Apparatus training.
- [ ] Every aggregate result opens the exact constituent scenarios and canonical replays.
- [ ] Provider, adapter, inference, and scientific failures remain distinguishable and are not silently converted into zero scientific scores.
- [ ] Missing hosted-provider credentials produce an explicit readiness state rather than fabricated live results.
- [ ] Seeded offline result fixtures keep the comparison interface demonstrable without external APIs and are unmistakably labeled as fixtures.
- [ ] Browser tests cover successful, inconclusive, regressed, partially unavailable, and adapter-error comparison states.
