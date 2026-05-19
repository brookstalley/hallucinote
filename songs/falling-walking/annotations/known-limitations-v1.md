---
kind: annotation
scope: song
tags: [limitations, todo, sound-design, vocals]
---

# Known limitations (post-v3 state)

Captures what is intentionally incomplete in the current build, so future iterations don't mistake gaps for deliberate choices.

## Sound design — synth patches at defaults

All synths are at **factory default presets**. The brief calls for:
- Dark supersaw pad with grit
- Plucky synth bass with portamento
- Glassy steel-drum-y pluck
- FM bell
- Square-wave chiptune lead

See `annotations/production-tricks.md` for full per-patch intent. Sound design pass requires Wavetable/Operator parameter editing (now available post-Wave-5).

## Effects chains

No sidechain pump, no saturation, no reverb/delay, no distortion in v1. The "powerful electronic" aesthetic depends on these. v1 mix loaded EQ8 + character shapers but parameters were left at default due to MCP gaps at that time (since closed).

## Vocal chain

No vocoder, no chiptune doubles. Vocals not recorded yet — see `annotations/vocals-intent.md`.

## Automation

v1 added two demonstration envelopes (verse-pad volume swell into chorus + synth-bass kick-synced sidechain duck during chorus). Still missing: filter sweeps, send automation, full chorus-arrival "opens-up" dynamics.

## Tag transition

Currently chorus-style first 2 bars + bossa-foreshadow last 2 bars, but no riser/sweep transition into bridge.

## Master bus

No master glue or limiter — master not addressable as a track index at v1 mix time.
