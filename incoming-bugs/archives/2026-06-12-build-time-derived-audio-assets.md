# Feature request — build-time derived audio assets (reverse / trim / normalize), deterministic + registered (2026-06-12)

Context: hallucinote-songs `swell`. Engine 0.9.0. Design:
`songs/swell/decisions/17-buried-we-centerpiece.md`. Complements the reverse/fold
request (`2026-06-12-audio-clip-reverse-and-fold.md`) — that one is about the
*playback* reverse; this is about the *asset pipeline*.

## The need
swell's fold uses a **time-reversed copy** of the source sample (the mirror half
plays `…-rev.wav`). Today that means hand-rendering a reversed WAV and committing
a **mystery binary** — opaque, off-source-of-truth, and re-rendered by hand
whenever the source or the fold changes. The repo ethos is *"build.py is the
source of truth"* (CLAUDE.md): a derived asset should be **declared as a
transform in code**, produced at build time, cached, and registered under
`assets/`.

## Concrete shape requested
A build-time asset-derivation step: from a declared **source + transform**, the
engine renders + content-hashes + registers a derived asset that the
sample-instrument (or `create_audio_clip()`) references by path.

Transforms that would immediately help swell, and are generally useful:
- **reverse** — the fold's mirror asset;
- **trim** to a region — pre-window a long source;
- **normalize / gain-stage** — consistent level across a sample set;
- (later) **fades**, **mono-fold**.

Properties:
- **Deterministic + content-addressed** — same source+transform → same output;
  re-runs are no-ops, consistent with the state-converger build.
- **Declared in `build.py`** — no checked-in derived binaries; only the source
  asset + the transform live in the repo.

## Why not just commit the reversed file
A committed `…-rev.wav` is invisible to the build graph: change the source and
the reverse silently goes stale; change the fold and you re-render by hand.
Declaring the transform keeps the centerpiece **fully reproducible from
`build.py` + the one source asset** — the same property every other part of the
song already has.

## Acceptance
swell declares something like `reverse("assets/we-all.wav")` in `build.py` and
the engine produces/registers the reversed asset deterministically — **no
hand-rendered binary in the repo**.
