---
date: 2026-05-01
kind: decision
scope: song
tags: [arrangement, v3, musicality, drums, bass, pad]
related: [songs/falling-walking/decisions/2026-05-01-chorus-pad-no-stabs.md, songs/falling-walking/decisions/2026-05-01-bass-embellishment-pattern.md]
---

# v3 musicality pass

Strategic move from v2: liveliness was in place but bass parts still felt under-developed and the chorus pad had a hidden synth-envelope problem. v3 added bass embellishment grammar, fixed the pad attack issue, and added drummer flourishes for sectional accents.

## Why

After v2 the song felt alive but the bass was the weakest voice — it had become rhythmically expressive but stayed harmonically static (root-only). Real bass players develop chord-tone phrases. The pad issue was a sound design discovery: the visible MIDI looked correct but the audible result was wrong. Drummer flourishes (open-hat lifts, soft crashes) cheaply add musical intent to the form.

## Manifestations

| Area | Change |
|------|--------|
| Chorus pad / pad twist | Removed re-articulation stabs that were retriggering the slow-attack patch. See `chorus-pad-no-stabs` for the full rationale. |
| Verse bass | Full embellishment pass via plain/embellished/walk-in grammar. See `bass-embellishment-pattern`. |
| Chorus bass | Alternating structure: odd bars plain tresillo on root, even bars chord-tone embellishment. |
| Chorus bass twist (NEW) | C3' variant — bars 7-8 walk B♭1 → D2 → F2 → A1 (matches the B♭maj7 pad twist). Slot 3 track 7. |
| Chorus sub twist (NEW) | C3' variant — bars 7-8 are B♭-1 octave (22) instead of G-1 (31). Slot 3 track 6. |
| Verse drums | Open-hat (46) lifts on bars 4/8/12 beat 3.5 (sectional accents on the mini-fill bars). Soft crash (49 vel 75) on bar 9 beat 1 (Gm arrival). Splash (55 vel 70) on bar 13 beat 1 (B♭ arrival). Ride-bell (53) ghost notes through bar 7 — texture variation deep in the long Dm. |
| Chorus drums | Soft crash (49 vel 88) on bar 1 beat 1 (chorus entry). Snare flick on 31.5/31.75 — pushes into next section. (c3prime_drums inherits these.) |

## Drummer flourish rationale

- **Open hat lifts** mark mini-fill bars (4/8/12) — listener feels the form pulse without changing the basic groove.
- **Soft crashes** (vel 70-88) on chord-change downbeats mark form for the listener; loud crashes would derail the brooding aesthetic.
- **Ride-bell ghosts** add texture variation deep in long single-chord passages — keeps the ear interested without complicating the rhythm.

The general drummer logic: small accents (open hat, ride bell) are *cheap* — they imply intent without cluttering. Soft crashes on chord-change downbeats articulate form. Loud crashes derail the brooding aesthetic.

## What it changes

After v3, every voice has a role: the bass develops chord-tone phrases with directional walks; the pad blooms cleanly; the drummer marks form with soft accents that don't overwhelm. The C3' twist now propagates through bass and sub (not just pad/pluck/bell), so the climax twist is felt across the whole low-end as well.
