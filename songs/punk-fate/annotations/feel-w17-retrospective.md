---
kind: annotation
scope: song
tags: [feel, w17, retrospective, per-part]
---

# Per-part feel — what punk-fate would have used (W17-E retrospective)

punk-fate's `build.py` was hand-authored before W17 shipped: every drum hit
is a raw `_note(...)` call (see `build.py:56` and the per-section drum loops
around lines 90-105). The library generators with the `feel` parameter
didn't exist yet, so there was no per-part microtiming knob — the punk
"push hard" feel had to be either baked in by hand or skipped entirely.

The retrospective: had W17-E been in place, the verse drums would have
used `drums.kick_stumble(...)` with a forward-push feel, and the chorus
would have switched to a different feel without touching the canonical
positions. Sketch:

```python
# Verse — push hard (punk forward-leaning kick)
verse_feel = {2.75: -0.025, 2.0: -0.02}
verse_kicks = drums.kick_stumble(bars=8, feel=verse_feel)

# Chorus — locked-down straight (pocket tightens for the hook)
chorus_kicks = drums.kick_stumble(bars=8, feel=None)
```

Other parts in punk-fate would have used independent feels per the
"per-part, per-helper-call" principle (see `docs/song-authoring-conventions.md`
"Per-part feel"). The guitar comp could have dragged slightly behind the
beat for tension against the punching drums — different feel, same section,
different intent.

This annotation is a marker. A future refactor that ports punk-fate's
hand-authored drum/bass/guitar parts onto the library generators would
turn this sketch into actual feel-driven code. Until then, falling-walking
is the worked example of `feel=` usage (see `songs/falling-walking/build.py`
verse drums, around line 233).
