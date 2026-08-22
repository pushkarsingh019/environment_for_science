# Prototype the scientist-facing visual language

Type: prototype
Status: resolved
Blocked by: 01, 02, 04

## Question

What visual and conversational interaction lets a non-programming environment author create, edit, and understand an apparatus and adaptive procedure without producing LabVIEW-like wiring spaghetti? Build rough alternatives covering apparatus structure, procedure decisions, observations, actions, verifiers, manual import, and agent-proposed edits, then use live user reaction to choose the interaction model.

## Decision

Use one **very simple, visualization-first scientist console**.

- Use a restrained Notion-inspired productivity shell, not a marketing page.
- Make the scientific visualization the dominant surface.
- Keep persistent information and prose minimal; reveal setup details only on demand.
- Provide one conversational command composer for editing the draft and ordinary run controls for the frozen simulation.
- Show EEG and mesoscope as environments in the same console without exposing code, APIs, RL language, editable wiring, or operational mesoscope controls.

The user explicitly rejected all three information-heavy visual variants and requested this simpler console direction. This resolves the interaction-language decision, not the implementation.

## Implementation status

The existing throwaway source in [`prototypes/scientist-facing-studio/`](../../prototypes/scientist-facing-studio/) does **not** yet implement the accepted direction and must be replaced.
