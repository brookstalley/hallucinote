---
kind: decision
scope: song
date: 2026-06-01
tags: [intro, harmony, missing-root]
---

# 12 — Intro: the phantom root you just missed

**Date:** 2026-06-01
**Decided by:** user
**Status:** concept locked; implementation deferred to the Live sound-design pass

## The idea

The song opens on the **decaying tail of a chord that was struck before the music
started.** A strong **E power chord (E5: root + 5th, ± octave)** — the most
root-defining sonority there is — is hit roughly **two beats before bar 1**. We never
hear the attack; only the room still ringing as it dies, low and filtered, drowned in
reverb. **A hint, not an event.**

- **First listen:** a small wash of ambient noise before the pad enters — easy to read
  as a tape artifact / random room tone / "nothing."
- **Once you know the song:** that's the **root** — the very thing the whole song
  withholds — and it was *right here, two beats ago.* **You just missed it.**

## Why it's the keystone of the theme

It reframes the entire premise. The root isn't merely *absent* — **it was present, and
you arrived two beats too late.** "Lost" becomes "lost it; you were almost in time."
The whole song is then the ache of trying to get back to a downbeat you missed at the
very start.

**It bookends the song.** The E whose tail is dying in the intro is the same E that
swells up in the coda (`decisions/03`). Present-but-vanishing (intro) → absent (whole
song) → present-and-arriving (coda). The root brackets the piece; in between, nothing.
The dying-tail and the swelling-sub are the two halves of one gesture — consider
reusing the **same reverb space** at both ends so they rhyme sonically.

## Why a power chord specifically

A power chord (root + 5th, no 3rd) is maximum fundamental, minimum harmonic
commitment — the purest statement of *root* available. The one moment of pure
rootedness in the song is the part you didn't quite catch. (It also leaves the
3rd uncommitted, consistent with the rootless world that follows.)

## Implementation notes (for the Live pass — no Ableton in this container yet)

- The **attack is off-screen** (before t=0): author as a rendered audio one-shot whose
  transient is trimmed, OR a synth hit with dry signal automated to silence and only
  the reverb-return (wet) audible, swelling down. Audio clip is the cleaner route.
- **Heavy, long reverb**; low-pass the tail (the bright transient is already gone). Sits
  just at/below conscious perception on first listen — "a hint."
- Let the tail **bleed under the pad's first notes**, then evaporate — so the rootless
  pad is briefly bedded on the ghost of the root before it's left floating.
- Keep it OUT of the reserved sub octave's "first real energy" claim (`decisions/03`):
  this is a *filtered, dying tail*, not a grounded sub event. It implies the root; it
  doesn't deliver the floor. The coda still owns the first true bottom-octave arrival.

## Candidate (not committed)

- Strike the phantom chord on the *beat-3* of an imaginary pre-bar, tying the
  harmonic-missed to the rhythmic-missed (the missing beat-3 floor, `decisions/08`).
  Possibly too clever; decide by ear.
