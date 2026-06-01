# 02 — Key, scale, and core progression

**Date:** 2026-06-01
**Decided by:** user (key/scale), agreed-after-confirm (progression form)
**Status:** locked

## Decision

- **Key/scale:** **E harmonic minor** (E F# G A B C D#).
- **Core progression:** **i – V – iv = Em – B7 – Am**, every chord voiced **rootless**.
- Harmonic minor specifically (raised 7th, **D#**) chosen over natural minor so the
  **V is a real dominant (B7)** with cadential pull, not a weak natural-minor v.

## The rootless surface (what the listener actually hears)

Removing the root from each diatonic 7th chord leaves a phantom triad:

| Intended (rootless) | Notes played | Phantom surface |
|---|---|---|
| EmM7 (i) | G – B – D# | **G augmented** — unstable, searching |
| B7 (V) | D# – F# – A | **D# diminished** — leading-tone loaded, pulls to E |
| Am7 (iv) | C – E – G | **C major** — the one pocket of consonance |

Instability gradient: augmented → diminished → major. The chord that should feel
most like home (i) surfaces as the *least* stable thing. Built-in emotional contour.

## The engine

**D# (the raised 7th) is the motor of the whole song.** It is the leading tone of E.
Every time the V (B7 → rootless D#dim) sounds, D# pulls the ear toward an E that
never comes. The reveal is simply the first time that pull is allowed to land
(B7 → Em, with E finally present). "Found" = the release of a tension wound all song.

## Notes / guardrails

- `--key Em` in the scaffold is informational metadata only; harmonic minor and the
  rootless constraint are not enforced by any tooling — they live here and in tests
  we author against the composed notes.
- Register: keep the rootless 3-5-7 voicings in the mid sweet spot (~C3–C5) so the
  shell (3rd↔7th) parses clearly. Too low = mud, too high = thin.
- Relative-major (G) inversion of this surface is explored deliberately in the break
  (`decisions/05`) and is the basis of a future major-key variation.
