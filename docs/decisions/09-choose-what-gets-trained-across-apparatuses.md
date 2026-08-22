# Choose what gets trained across apparatuses

Type: grilling
Status: resolved
Blocked by: 07

## Question

Should the demonstrated Gemma policy be trained only for EEG, jointly across EEG and mesoscope scenarios, or as separate apparatus-specific adapters? Choose the option that best proves task specialization and platform generality without weakening the authenticity or measurability of the hackathon result.

## Decision

Train one **EEG-specific Gemma E4B LoRA adapter**, with E2B as the bounded technical fallback. Measure training improvement on the approved EEG held-out split. Implement mesoscope as the second Environment and evaluate it separately as platform-generality evidence; do not mix mesoscope episodes into the first training run or claim cross-apparatus learning.
