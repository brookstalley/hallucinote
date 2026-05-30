---
date: 2026-05-20
kind: decision
scope: song
tags: [aesthetic, production, energy, no-precious-moments]
---

**Decided by:** user

# Real punk energy — fast, raw, driving, no precious moments

## Question
What does "real punk energy" mean in concrete compose-time and mix-time choices?

## Answer
Punk-energy heuristics, in order of authority:

1. **Drums never coast.** Hats drive constant 8ths (or 16ths in the chorus lift); kick and snare hold the backbeat without fills, except a 1-bar tom-fill before each chorus and the final outro hit. No "interesting" drum-programming flourishes; the energy comes from relentlessness, not invention.
2. **Bass plays roots, on the beat.** No walking, no chromatic passing tones, no slap. Eighth-note pulse in verses; quarter-note thump in choruses for the felt contrast.
3. **Lead guitar uses power chords for the rhythm bed and the fate motif for the lead figure.** Distorted/saturated tone. Bends and slides are allowed; tapping and sweeps are not.
4. **Staccato synth ("vocals") is short and percussive.** Release time tight; no legato; no portamento. Each "syllable" is a clipped event. This is the punk-sneer translated to MIDI.
5. **Velocity layering, sparingly.** Punk is loud, but not robotically loud. ±10–15 velocity wobble on drum hits and synth notes keeps it human. The bass and guitar can be more uniform.
6. **No reverb-soaked ambience.** Short room/plate at most. A reverb-throne on the synth voice is OK as a single tasteful effect — *one* precious moment is allowed, ironically.
7. **No fade-outs, no synth swells, no dramatic ritardandos.** The outro cuts. The bridge dynamic dip is the only quiet moment; even there, the bass should still pulse.
8. **Mix loud-and-flat first.** EQ for clarity (HP everything that isn't bass/kick, surgical mid-cut on guitar to make room for the synth). Compression to taste; saturation on the guitar bus is mandatory. Sidechain compression is *not* a punk move — skip it.

## Rationale
The user explicitly asked for "real punk energy." That phrase rules out:
- electronic-music habits (sidechain pumping, big builds, drops, polished mix)
- prog/metal habits (odd meter — already ruled out — complex drum fills, virtuosic playing)
- pop habits (lead-vocal-as-centerpiece polish, multi-stack vocal harmonies, chorus stadium-reverb)

Punk energy comes from **economy of means + commitment**. Four players, no doubles, no overdubs of consequence, every choice as direct as possible. The Beethoven source material gives us harmonic ambition; the punk idiom is what keeps that ambition from going precious.

## What this binds
- `/song-pick-instruments`: prefer presets that read "garage rock" or "electric" over "warm/lush/cinematic"
- Mix devices: Drum Buss + Saturator on the lead guitar are mandatory; Echo/Reverb/Chorus are budget-limited (max one ambience-creating device on the synth, none on bass or drums)
- Compose-time: when in doubt, pick the simpler/faster/louder option. "Is this too obvious?" → keep it. "Is this too clever?" → cut it.
