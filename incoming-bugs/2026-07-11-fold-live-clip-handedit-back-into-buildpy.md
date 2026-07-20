# Capability: fold a Live clip hand-edit back INTO build.py (reconcile, not just detect)

**Type:** capability request (not a bug).
**Severity:** M–H. This is the inverse of the already-filed drift *detector*
([[archives/2026-06-22-systematic-build-vs-live-arrangement-verification-capability]]).
Detection answers "is Live faithful to build.py?" This answers the workflow that
actually happens when the answer is "no, and **Live is the version we want**": get the
user's by-ear Live edit back into the source of truth without hand-transcribing notes.

**Engine / server:** `2f9d648a60aa`-era. Surfaced on song `alien` (again).

## The gap

`build.py` is the source of truth; parts are authored as **generator code**
(`add_wildness(...)`, degree loops, seeds). When a user hand-edits a clip in Live and
says "sync it back here," there is no primitive that reconciles a Live clip's notes
INTO build.py. `/ableton-pull` stages Live→DB mutations, but the DB is a regenerable
artifact — the next `build.py --reset` overwrites it. Nothing helps re-author the
**code** so a rebuild reproduces the edit.

So the operation is a fully manual ritual, done at least twice now (2026-06-22
"the live set won" whole-song; 2026-07-11 single-clip Human Riff bridge tail):

1. Read the Live clip's notes (`ableton_note action='list'`).
2. Dump the DB clip's notes; diff to isolate the user's change.
3. Reverse-map MIDI ints → the song's authoring idiom (here `d(deg, oct)` in 22-EDO).
4. Hand-write literals into build.py, deciding **where** they belong relative to the
   generator + seeded transforms (the crux: an edit that lands *after* `add_wildness`
   must be appended POST-wildness, or the rebuild re-fragments exactly what the user
   just cleaned up).
5. Rebuild, then hand-diff DB-vs-Live to confirm exact reproduction.

Steps 1–2 and 5 are mechanizable today; 3–4 are where the real friction (and the risk
of silently mis-transcribing the art) lives.

## Two concrete sub-gaps worth fixing independently

1. **A note-MATCHING clip diff (shared with the detector).** The naive
   distinct-`(pitch, start)` diff reports a *moved* note as one `missing` + one `extra`.
   On the bridge tail today that turned a ~3-note delete + a re-timed/re-lengthened
   figure into a scary **"17 removed / 12 added"** — the user immediately (correctly)
   pushed back: "nowhere near 17 removed, maybe 3, and durations/start times changed."
   A nearest-note pairing (match same-pitch by nearest start, then classify
   start/dur/vel deltas) reports it honestly as "3 removed, N moved/retimed." The
   detector filing's `extra/missing/mismatch` model should gain this `moved` class so
   it doesn't cry wolf on hand-nudged material.

2. **A round-trip helper for the reconcile itself.** Even a low-tech
   `hallucinote reconcile-clip --song <slug> --track "Human Riff" --section bridge`
   that emits the Live clip as ready-to-paste authoring literals (in the song's
   `d(deg, oct)` idiom where a mapping exists, raw MIDI + a comment where it doesn't —
   e.g. non-scale `add_wildness` flourish pitches) would remove the transcription-error
   surface. It can't decide *where* in the generator the literals belong (that's the
   authorial call), but it can hand the author an exact, idiom-correct block to place.

## Why this matters

The "great art, not software" norm means the Live set is where a composer edits by ear,
and build.py must be able to *learn* those edits, not just police them. Right now the
learn-back path is entirely manual and transcription-error-prone — the one place a
silent wrong note could enter the source of truth. Detection (filed) + reconcile (this)
together close the loop in both directions.
