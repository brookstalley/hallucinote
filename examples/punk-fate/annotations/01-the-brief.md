---
kind: annotation
scope: song
date: 2026-08-10
tags: [intent, origin, brief]
---

# The brief

## The prompt, verbatim

> Make a 2-minute punk song that crams the chord progression of Beethoven's 5th
> into those two minutes. Drums, bass, lead guitar, and vocals on a staccato
> synth. Call it punk-fate.

## What is decided

| Dimension | State | Value / mechanism | Decided by |
|---|---|---|---|
| Slug / title | DECIDED | `punk-fate` / "Punk Fate" | user |
| Duration | DECIDED | ~2:00 — 96 bars at 200 BPM = 115.2 s | user (duration) + arithmetic |
| Tempo | DECIDED | 200 BPM | agreed-after-confirm |
| Meter | DECIDED | 4/4 throughout. The mvt-I fermata is realized as a **full-band hole** (one bar of total silence), not a meter change — a stronger punk gesture *and* it sidesteps the engine's no-mid-song-meter-change limit, so nothing is left open here | inferred |
| Harmony — scope | DECIDED | The **whole four-movement arc**, not just mvt I: Cm → Eb → Ab (+ C-major foreshadow) → Cm → dominant transition → C MAJOR | agreed-after-confirm |
| Harmony — key | DECIDED | C minor → C major. Sections: intro Cm · verse Cm (i–♭VI–♭III–V) · chorus Eb (I–V–vi–IV) · break Ab (I–IV–V–I + a 2-bar C-major blaze) · scherzo Cm (Cm–Ab–G, slow harmonic rhythm) · bridge C pedal under Ab→G→G7 · finale C (I–IV–V–I) · coda C | inferred from the arc choice |
| Instrumentation | DECIDED | Exactly four: drums, bass, lead guitar, staccato mono-synth as the "vocal" | user |
| Lyrics | NOT-APPLICABLE | The vocal part is a synth *playing* the vocal line — there is no voice, so there are no words. Recorded, not asked about | inferred |
| Production stance | DECIDED | Raw and blown-out basement punk — saturated drum bus, distorted bass doubling the guitar, one short room send. No crossover-symphonic polish | inferred, stated to user |
| Drum style | DECIDED | Straight punk backbeat (kick 1+3, snare 2+4, 8th hats); half-time under the Ab break; **hardcore skank** (kick on quarters, snare on every off-beat) for the scherzo, so it reads twice as fast without a tempo change | inferred |
| Microtiming feel | DECIDED | Baked per part at generation time: guitar downstrokes ~10 ticks **ahead**, bass ~6 ticks **behind** (the band pulling against its own anchor), snare backbeat ~12 ticks ahead, synth leaning in ~14 ticks on phrase starts | inferred |
| Alternate tuning | NOT-APPLICABLE | — | inferred |
| Vocal synthesis | NOT-APPLICABLE | No sung voice is required (see *Lyrics*) — the thin capability is never on the critical path here | inferred |

## Named gestures, and the mechanism behind each

| Gesture | Mechanism |
|---|---|
| **The fate motif** (short-short-short-LONG) | Not an ornament — it is *the riff*. Guitar + bass in unison power chords (G5 ×3 → Eb5), kick locked to the three shorts, crash on the long. It returns as the chorus hook, the scherzo horn theme, the finale theme, and the last thing you hear |
| **The fermata / grand pause** | Bars 2 and 4 of the intro are a full-band hole — every part writes silence. No meter change, no automation |
| **The great transition** (mvt III → IV) | 8 bars: bass pedals low C throughout while the guitar alternates Ab5 → G5 → G7; drums hammer floor tom + kick, quarters → 8ths → 16ths with a velocity ramp; synth climbs Ab4→C5→D5→Eb5→F5→G5. Bar 8 beat 4 is a **one-beat total hole**, then C major |
| **Beethoven's own foreshadow** | Bars 9–10 of the Ab break are a 2-bar **C-major blaze** (Beethoven puts C-major trumpet fanfares inside the A-flat andante) — the finale arriving early, then snuffed back to Ab |
| **Darkness → light, in one semitone** | The intro's cell is G-G-G-**E♭**. The song's final gesture is the identical rhythm on G-G-G-**E♮**. One note is the whole symphony |

## Still open

| Dimension | Owner | Closes at |
|---|---|---|
| Mix balance — send levels, per-device params, whether the guitar needs a third gain stage | agent | `/mix-review` → `/song-snapshot` |

**Closed since this brief was written:**

- *Instrument chains* — DECIDED at `/song-pick-instruments`; see
  [[../decisions/05-signal-chains]]. All 12 devices stock Live, `compat check
  --probe` clean.
- *Energy arc* — the first pass put verse and chorus at identical density,
  contradicting this brief's own "the chorus is the lift" row. Closed at
  `/compose-review`; see [[../decisions/06-the-chorus-has-to-arrive]].

## Section time budget

96 bars of 4/4 at 200 BPM. One bar = 1.20 s.

| Section | Bars | Count | Seconds | Running |
|---|---|---|---|---|
| `intro-fate` | 1–8 | 8 | 9.6 | 0:10 |
| `verse-cm` | 9–24 | 16 | 19.2 | 0:29 |
| `chorus-eb` | 25–36 | 12 | 14.4 | 0:43 |
| `break-ab` | 37–48 | 12 | 14.4 | 0:58 |
| `scherzo-cm` | 49–64 | 16 | 19.2 | 1:17 |
| `bridge-pedal` | 65–72 | 8 | 9.6 | 1:26 |
| `finale-cmaj` | 73–88 | 16 | 19.2 | 1:46 |
| `coda` | 89–96 | 8 | 9.6 | **1:55** |

The two 16-bar sections (verse, finale) and the 12-bar chorus are deliberate: at
1.2 s a bar, a 16-bar verse is only 19 s, and the C-major finale needs to be at
least as long as the verse or the payoff reads as a tag rather than a
destination.
