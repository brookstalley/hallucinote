---
kind: decision
scope: song
date: 2026-06-01
tags: [sound-design, lfo, filter, automation]
---

# 10 — Notch-filter LFO: keep v1 simple

**Date:** 2026-06-01
**Decided by:** user
**Status:** locked (for v1)

## Decision

For this first version, the "root presence" timbral system is **one simple notch
filter** on the pad's missing-root frequency, with **one slow LFO** rate. No
per-chord differentiation, no Q-modulation-as-second-axis, no accelerating rate yet.

Across the song, the only large-scale move is coarse:
- **Intro:** notch wide open (maximum root absence).
- **Verse/chorus 2:** notch **Q narrows a hair** so root overtones bleed through
  subliminally — a sense of coalescing the listener can't consciously name.
- **Coda:** the system gets out of the way; the sub-osc root supplies the floor.

## Rationale

Get the fundamental feel down simply first, then play with the fancier ideas in later
variations. Stacking per-chord LFO differentiation and Q-axis modulation on top of an
already-unfamiliar technique risks burying the concept before it's internalized.

## Deferred (future variations)

- Per-chord LFO differentiation (tonic most suppressed — "home most denied").
- Notch width (Q) as an independent second axis of root presence.
- Accelerating LFO across the song so the reveal becomes a gradual process.
- Sub-oscillator *ghost root* buried below perception throughout (vs. the current
  fully-reserved-then-revealed approach).
See `decisions/09-variation-roadmap.md`.
