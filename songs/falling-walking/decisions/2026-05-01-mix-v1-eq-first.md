---
date: 2026-05-01
kind: decision
scope: song
tags: [mix, eq, device-chain-order, mcp-gap]
---

# Mix v1: EQ8 first on every track, character shapers second

Mix v1 (2026-05-01) loads devices onto every track. The deliberate order: **EQ8 first** (HP filter pass + corrective bell cuts), **character shapers second** (Drum Buss, Saturator, Chorus-Ensemble), then sends/sidechain/master would follow once MCP gaps land.

## Why this order

- **EQ8 first = biggest perceived clarity gain for the least effort.** Even at default settings, just having the HP slot present is harmless; once the HP frequencies are dialed, low-end mud disappears across the song.
- **Character shapers go after EQ** so they color the cleaned-up signal, not the muddy pre-cleanup version. Drum Buss / Saturator / Chorus-Ensemble produce wildly different results depending on what's hitting them — feed them a HP'd, surgically-EQ'd source.
- **Sidechain is the largest single missing "powerful electronic" element** but is strictly blocked on MCP gap #17 at v1 mix time. Comps are deferred until that lands.

## Intended settings (per track)

Parameters intentionally left at default in v1 mix because `set_device_parameter` was throwing internal errors (MCP req #17b at the time). Values below applied either manually in Live's UI or programmatically once the MCP gap is fixed.

| Track | Devices loaded | Intended settings |
|-------|---------------|-------------------|
| 5 — 01 Drums | EQ8 → Drum Buss | EQ8: HP 30Hz brick, dip -2dB @ 350Hz Q 1.0, +1.5dB shelf @ 10kHz. Drum Buss: drive 6dB, crunch 30%, boom 60Hz/0.3s, transients +25%, comp ~2dB GR |
| 6 — 02 Sub Bass | EQ8 → Utility | EQ8: HP 28Hz @ 48dB/oct, LP 120Hz @ 24dB/oct. Utility: Bass Mono 150Hz |
| 7 — 03 Synth Bass | EQ8 → Saturator | EQ8: HP 60Hz, -3dB bell @ 250Hz Q 1.5 (mud), +1.5dB bell @ 1.2kHz Q 1.0 (presence). Saturator: drive 4dB, Soft Sine, output -2dB |
| 8 — 04 Verse Pad | EQ8 → Chorus-Ensemble | EQ8: HP 200Hz @ 24dB/oct, -2dB bell @ 350Hz Q 1.0. Chorus: Ensemble mode, amount 30%, rate 0.3Hz, width 100% |
| 9 — 05 Chorus Pluck | EQ8 | EQ8: HP 300Hz @ 24dB/oct |
| 10 — 06 Bell | EQ8 | EQ8: HP 500Hz @ 24dB/oct |
| 11 — 07 Bridge EP | EQ8 → Chorus-Ensemble | EQ8: HP 100Hz @ 24dB/oct. Chorus: Classic mode, amount 15% (subtle), rate 0.4Hz, width 70% |
| 12 — 08 Chiptune Lead | EQ8 → Chorus-Ensemble | EQ8: HP 200Hz @ 24dB/oct. Chorus: Ensemble mode, amount 25%, rate 0.5Hz, width 100% |

## Deferred (blocked on MCP gaps at v1 mix time)

| Block | Plan |
|-------|------|
| Hybrid Reverb on Return A | Hall, decay 3.5s, predelay 30ms, dry/wet 100% |
| Echo on Return B | 1/8 dotted ping-pong, feedback 35%, HP filter 250Hz, dry/wet 100% |
| Send levels per track | T8 Pad → A -10dB, T10 Bell → A -8dB / B -14dB, T9 Pluck → A -16dB / B -18dB, others lighter |
| Sidechain Comp on T7 Synth Bass | Keyed to T5 kick, ratio 4:1, ~3dB GR, attack 5ms, release 150ms |
| Sidechain Comp on T8 Verse Pad | Keyed to T5 kick, ratio 6:1, ~4dB GR, attack 1ms, release 200ms |
| Master glue + limiter | Glue 2:1, ~1.5dB GR. Limiter ceiling -1.0dB, lookahead 1.5ms |

## Reusable principle

When the device chain order matters, **corrective filtering before character shaping** is the safe default. Apply this to any track: HP/notch out the problem first, then color what's left.
