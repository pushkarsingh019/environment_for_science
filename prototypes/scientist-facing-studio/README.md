# Scientist console — throwaway prototype

A dependency-free prototype of a deliberately simple console for scientists. Its visual system follows the repository’s `DESIGN.md` (Notion-inspired warm canvas, quiet hairlines, one blue action colour, system sans-serif type).

## Run

From the repository root:

```bash
python3 -m http.server 4173 --directory prototypes/scientist-facing-studio
```

Open:

- <http://localhost:4173/?variant=A> — **Selected direction: spatial Apparatus canvas**
- <http://localhost:4173/?variant=B> — Comparison material: procedure table
- <http://localhost:4173/?variant=C> — Comparison material: run console

Use the floating arrows or Left/Right arrow keys to switch. Use the header to switch between seeded EEG and sealed synthetic mesoscope content.

Everything stays in browser memory. Imports, proposed edits and mocked Policy-agent runs can be undone; reloading clears them. There are no APIs, hardware connections or physical control surfaces.

> Throwaway: the user selected Variant A's hierarchy and interaction model. Rewrite it properly when the application architecture is implemented; do not promote this prototype code directly.
