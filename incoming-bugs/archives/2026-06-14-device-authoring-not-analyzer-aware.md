# Authoring devices onto an analyzer-laden set is not analyzer-aware → manual analyzer-stripping required before a scoped device push

**Severity:** M — every iterative mix pass hits this. After a render leaves
`HallucinoteAnalyzer` on all 23 tracks + 5 returns + master, authoring a NEW
device into the chain (or re-pushing device changes) collides with the analyzer
because device matching is **position-based** and `browser.load_item`
**appends** (lands the new device *after* the analyzer). Cost us a detour on the
2026-06-14 swell clarity pass: to add an EQ Eight to Cymbal/Glock/Meter-Hat we
had to hand-delete the analyzer on each of those 3 tracks first, push, then let
the next render re-add them.

**Root cause / mechanism.**
- `handlers/device.py` load path has **no** analyzer awareness — it calls
  `browser.load_item`, which appends to chain end. On a track that already has an
  analyzer, the authored device lands *after* it (under-measured until a render).
- Push device matching is **position equality** (`sync/push/probe.py` "Match
  rule: position equality", DB `devices.position` = Live `device_index`). With an
  analyzer occupying a chain slot, a NEW authored device at DB-position *p* has no
  position-*p* Live match (the analyzer is there), so the push loads it — appended
  after the analyzer — and the chain order diverges from source.
- The only thing that keeps the analyzer last is the **render-time** reposition
  (`analyzer/setup.py` `_reposition_action` → delete+re-add, `was_repositioned`).
  Nothing fixes order at **author/push** time. `analyzer_staleness.py`
  *detects* "authored device after analyzer" but doesn't repair it.

**Two gaps, either of which would remove the manual step:**
1. **No `ableton_render(action='strip')` / remove-analyzers action.** `ensure_loaded`
   adds across 25+ surfaces in one call; there is no inverse. To get a clean set
   (for a deterministic device push, or to save a clean `.als`), you must delete
   ~29 analyzers by hand, one MCP call each. A bulk strip is the obvious symmetric
   primitive.
2. **Device push / load is not analyzer-aware.** Options: (a) the device phase
   strips-then-restores analyzers around itself (cleanest — push always sees a
   bare authored chain); or (b) `load` inserts authored devices *before* a trailing
   analyzer (the "insert before the analyzer" behavior a user expected in
   conversation 2026-06-14, which turns out NOT to exist — load always appends);
   or (c) position-matching ignores analyzer rows so an extra trailing analyzer
   never shifts the match.

**Workaround (until fixed):** before a scoped device push that *adds* devices,
`ableton_device(action='list', track_index=N)` each target, `delete` the
`HallucinoteAnalyzer` row, then push; the next render's `ensure_loaded` restores
them. Param-only changes on tracks that already have the device are fine (the
analyzer is last, positions still match).

**Verifiable signal.** After a render, authoring a new device into any chain via
push lands it in source order (before the trailing analyzer) and needs no manual
analyzer deletion; and a single `render(action='strip')`/equivalent clears all
analyzers for a clean save/push. Surfaced 2026-06-14 dogfooding the swell mix pass.
