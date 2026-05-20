---
date: 2026-05-20
kind: decision
scope: song
decided_by: user
tags: [instrumentation, tracks, vocal-substitute]
---

# Four tracks: drums, bass, lead guitar, staccato synth

## Question
What does the band consist of?

## Answer
Four MIDI tracks (scaffold currently has `01 Track` … `04 Track` placeholders pending `/song-pick-instruments`):

1. **Drums** — punk kit: kick, snare, hats, optional crash. Driving 8ths on hats, backbeat on 2 and 4.
2. **Bass** — electric bass. Root-driven punk lines; eighth-note pulse in verses, quarter-note anchors in choruses for contrast.
3. **Lead guitar** — electric guitar with overdrive/distortion character. Power chords + the fate motif as the lead figure.
4. **Staccato synth** — *carrying the vocal line* in place of actual vocals. Short, percussive note shape. This is the "singer" — its melody is what a vocalist would sing.

## Rationale
- **User-specified four-part arrangement.** No reduction or expansion.
- **Synth-as-vocal substitution** is deliberate: the user said "vocals on a staccato synth," which means the staccato envelope is the vocal idiom — short notes with consonant-vowel-consonant phrasing implied. This frees us from lyrics while keeping the vocal melodic role.
- **No keys/pads/strings.** Punk rejects ornamentation; the four-piece economy is part of the genre's emotional honesty.

## What this binds
- `/song-pick-instruments` runs next with `portability=strict` (stock Live content). Defaults to look at:
  - Drums: Drum Rack with stock punk-leaning kit (Kit-Live 909-ish, or punk-rock kit if available)
  - Bass: Operator/Analog/Bass preset with electric-bass character; failing that, Drift or Wavetable
  - Lead guitar: Sampler/Drift/Wavetable with grit — pure stock Live can't fully sell distorted electric guitar; we may need to layer a saturator/amp
  - Synth: Operator or Wavetable for the staccato vocal line — sharp envelope, short release
- Mix-time, the lead guitar track likely wants Saturator/Amp/Pedal on the chain for distortion realism
