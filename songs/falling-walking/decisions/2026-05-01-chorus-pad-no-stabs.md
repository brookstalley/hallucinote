---
date: 2026-05-01
kind: decision
scope: track
track: 04 Verse Pad
tags: [chorus, pad, synth-envelope, gotcha]
---

# Chorus pad: drop the per-bar re-articulation stabs

Earlier draft had chord stabs on every bar of the chorus pad to re-articulate the harmonic motion. v3 removes them — each chord now holds 7.5 of 8 beats (short breath at chord change, long bloom in between).

## Why

The Verse Pad patch has a **slow attack envelope** (intentional — that's how it "blooms"). The chord stabs were the same pitch as the sustained chord, so Live retriggered the synth's slow-attack envelope on each stab. The MIDI showed an 8-beat sustain but the audible note effectively ended at the first stab — the bloom never reached its peak.

The visual MIDI is misleading: it looked correct, but the audible result was the pad continuously re-attacking quietly instead of opening into the chord.

## What it changes

- **Each chord block** now holds 7.5 beats with a 0.5-beat silence at the chord change. The bloom has room to develop.
- This applies to the chorus pad clip and inherits into the C3' twist variant (same patch, same problem).

## Reusable lesson

Any synth with a slow attack will retrigger on same-pitch repeated notes. When the patch is designed to bloom (slow attack, slow filter open, etc.), let it bloom — don't re-articulate the same pitch within the envelope's natural duration. If re-articulation is genuinely needed for musical reasons, use a percussive companion layer (a pluck, a stab patch with fast attack) rather than re-triggering the bloom patch.
