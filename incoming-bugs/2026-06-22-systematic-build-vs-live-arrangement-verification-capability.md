# Capability: systematic build.py ↔ Live ARRANGEMENT verification (drift detector)

**Type:** capability request (not a bug) — but motivated by a cluster of real bugs.
**Severity:** H for the framework's core promise. build.py is the source of truth and
the Live set is a regenerable materialization; we have a durable detector for
**device-param** drift (`/song-snapshot`'s capture-diff) but **nothing** for the
highest-stakes content — the **arrangement notes the render actually plays**. Every
arrangement bug filed so far (stacking, bulk-drop, replace_notes-orphans) was caught
only by hand, by ad-hoc note-count spelunking or a full render+stem-loudness read.

**Engine / server:** `0.1.0+4372b6734f8d`. Surfaced on song `alien`.

## The gap

A user asked, correctly: "do we need a more systematic way to detect slight variance
from our build source?" Today the answer is a manual ritual:

1. Build build.py → temp DB; per arrangement clip, collect the canonical note set.
2. Read each Live arrangement clip's notes.
3. Diff, by hand, per (track, section).

Doing this on `alien` found that 49/50 arrangement clips matched build.py but **one**
(`Drums chorus2`) carried 5 stale orphan notes not in build.py — invisible to every
cheap check. That ritual should be a first-class command.

## What the detector must encode (the non-obvious parts)

A naive "compare note counts" check is WRONG and will cry wolf. Three normalizations
are mandatory:

1. **Live collapses same-(pitch, start).** Live holds one note per (pitch, start);
   build.py legitimately authors stacked notes that share pitch+start but differ in
   duration/velocity (e.g. `add_wildness` at high intensity). So the canonical
   comparison key is the **distinct-(pitch, start) set**, not the raw count. On
   `alien`, Human Riff chorus3 is 332 raw in the DB but 305 in Live — *faithful*, not
   a 27-note loss. Compare the audible (collapsed) sets.
2. **Float round-trip tolerance.** Capture/probe round-trips introduce ~1e-7 noise in
   start/duration (a single `/song-snapshot` device diff on `alien` showed 245 such
   phantom deltas). Compare start/duration with an epsilon (~1e-3 beats), pitch exact,
   velocity within a small tolerance.
3. **Read via the note API, not `ableton_clip list` note_count.** The 2026-06-21
   bulk-drop bug documented note_count reporting the *source session clip's* count,
   masking an empty arrangement clip. Use `get_notes_extended` /
   `ableton_note(action='list', location='arrangement')` for ground truth.

## Proposed shape

Two complementary layers — **prevention** (fix the write path so drift isn't
introduced) and **detection** (this). Detection is the safety net for when prevention
has bugs — which, per the three filed arrangement bugs, it currently does.

- **Audit command** — `hallucinote verify-arrangement --song <slug>`: fresh build →
  per-clip canonical (pitch,start[,dur,vel]) set; read Live arrangement per-clip;
  report per (track, section): `extra` (in Live, not build — the orphan/stale case),
  `missing` (in build, not Live — the dropped case), `mismatch` (vel/dur drift beyond
  tolerance). Exit non-zero on any divergence. Run before trusting a set, before a
  render, and after any recovery/hand-edit.
- **Push-time assertion** — fold the same comparison into `push execute` /
  `push-notes` right after materialization: assert each arrangement clip's audible set
  equals the DB's, HALT+report on mismatch instead of reporting `OK`. (This is the
  "post-materialize integrity assertion" suggested in the 2026-06-21 bugs, with the
  normalization rules above so it doesn't false-positive on wildness clips.)
- **Reuse existing infra.** `push-notes --changed` already computes a per-clip
  **content fingerprint**. A canonical (collapsed, tolerance-rounded) note-set hash
  per (track, section) would give O(clips) verification and a single per-clip
  fingerprint that build.py could even emit as an expected manifest.

## Why this matters

Without it, the source-of-truth guarantee is only as good as the (currently buggy)
write path, and divergence is silent until a render is read by ear. With it, "is the
rendered set faithful to build.py?" becomes one command — and a push that corrupts the
arrangement fails loudly instead of shipping silently.
