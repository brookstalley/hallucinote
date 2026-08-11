# Punk Fate

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

Beethoven's Fifth Symphony crammed into two minutes of basement punk. The whole four-movement harmonic arc — C minor fate riff, the E-flat relative-major lift, the A-flat andante as a half-time breakdown, the C minor scherzo, the great dominant-pedal transition, and the C MAJOR finale with its hammering coda — played by drums, bass, lead guitar, and a staccato mono-synth singing the vocal line. Raw and blown-out: darkness to triumph in 115 seconds.

## Core specs

- **Slug:** `punk-fate`
- **Title:** Punk Fate
- **Key:** Cm → Cmaj
- **Tempo:** 200.0 BPM
- **Time signature:** 4/4

## Structure

96 bars of 4/4 at 200 BPM — one bar = 1.20 s, total 1:55. The bar budget and
why each section got its share: `decisions/02-tempo-and-the-section-budget.md`.

| Section | Bars | Feel |
|---------|------|------|
| `intro-fate` | 1–8 | The fate cell twice, each answered by a full-band hole (the fermata as one bar of silence), then the band arrives |
| `verse-cm` | 9–24 | i–♭VI–♭III–V churn; guitar plays quarters through the first half so the bass carries the engine |
| `chorus-eb` | 25–36 | The relative-major lift — the motif re-harmonized as the hook, vocal doubled at the octave |
| `break-ab` | 37–48 | Half-time A-flat andante; the one section the synth *sings* — with Beethoven's own 2-bar C-major blaze inside it |
| `scherzo-cm` | 49–64 | Hardcore skank (kick on quarters, snare on every off-beat) — twice as fast without a tempo change |
| `bridge-pedal` | 65–72 | Bass pedals low C under Ab→G→G7; drums ramp quarters→8ths→16ths; one-beat hole, then daylight |
| `finale-cmaj` | 73–88 | C MAJOR I–IV–V–I, gang-vocal doubling — the destination, just above the chorus's peak |
| `coda` | 89–96 | Hammered cadence; the last gesture is the fate rhythm on G-G-G-**E♮** — one semitone from the intro's E♭ |

## Build

```bash
python examples/punk-fate/build.py            # state-converger — re-run is no-op if nothing changed
python examples/punk-fate/build.py --reset    # drop + rebuild from scratch
pytest examples/punk-fate/tests/ -v           # shape tests (also in the repo's default suite)
```

The build is headless — no Live required. Pushing it into a running Ableton
Live set and rendering audio are the parts that need Live; the walkthrough of
that whole loop, with this song as the worked example, is
[`docs/tour.md`](../../docs/tour.md).

## Provenance

Authored end-to-end in one Claude Code session (2026-08-11) from the sparse
prompt quoted in `annotations/01-the-brief.md`, through `/song-brief`
elicitation, composition, push, render, and one measured mix correction —
the session the tour documents. The dialed mix is baked into
`captured_session.json`, so it survives `build.py --reset`.

A second session the same day re-cut it for **feel and dirt**, because the
first pass read as Beethoven-played-correctly rather than as punk:

- Per-part feel became four `Player` objects — the constant push/pull of
  `decisions/04` kept, with 1/f-correlated timing and velocity *breathing*
  realized on top by `performance.apply_profile`, per player. Not a random
  per-note nudge: memoryless noise is what the performance lens grades
  *sloppy*, and correlation is what it grades *human*
  (`decisions/08-sloppy-but-enthusiastic.md`).
- The drums gained a garage vocabulary: ghost snares, hats that open where a
  hand would lean on them, ~6% of hats dropped outright, and the coda running
  at `heat=1.5` while the final bar locks back to 1.0.
- Two gain stages were added — Pedal *Guitar Dirt* on the guitar, Saturator
  *Rough Tone* on the voice, drum Saturator drive 6.9 → 11 dB
  (`decisions/09-the-dirt.md`). Still 14/14 stock Live devices.

Measured full-song after: delivered true peak **−2.1 to −2.6 dBTP**, 2–4
pre-fader bus overshoots across three realtime captures, 8/8 sections analyzed. All four parts read `human` on the
performance lens (`measurements/`).

A third session re-cut it again — this time for **tone**, because the
performance read as punk but the *sound* didn't: the guitar came back as "an
electronic trumpet". Nothing was broken; every chain had been chosen by preset
**name** and never verified by **parameter**
(`decisions/10-it-has-to-sound-punk.md`):

- *Guitar-Dual Amped **Crunch*** had both nested amps on `Amp Type: Blues`, and
  Pedal *Guitar **Dirt*** had **1.6 % drive** with the mids scooped — so almost
  no distortion, and therefore none of the intermodulation that fuses a power
  chord into a guitar instead of three oscillators. Now `Rock` amps at 8.8/9.0
  input gain, 42 % pedal drive, mid-forward.
- A **24 %-wet Reverb was hiding inside the guitar rack** (declared nowhere),
  on top of the reverb send. Its "Room" macro went 30 → 6.
- Drums came **up 11 dB** (fader −13.9 → −5.5), because the master finally got a
  **Glue Compressor → Limiter** — the previous passes bought headroom by pulling
  faders down, which is what made the record polite.

Measured full-song after: **−0.34 dBTP delivered, 0 overshoots, 0 findings**,
8/8 sections, with guitar spectral flatness 0.117 → **0.156** and master
0.158 → **0.192** — noisier *and* louder, which is the trade every earlier pass
had gotten backwards.

Then the last synthetic thing in the band went: the Operator square lead that had
been standing in for the vocal read as *"main street electrical parade — beep
beep beep bloop"*. **Track 4 is a second guitar now**
(`decisions/11-the-vocal-line-is-a-lead-guitar.md`) — `Guitar-Dual Amped Heavy`
retuned to `Lead` amps at 9.29 gain, dry (Room 25 → 9), with the vocal-style
slapback sends cut roughly in half. The formant argument that picked a square
wave in the first place was right about frequency range and wrong about genre.
Voice-stem spectral flatness **0.110 → 0.147**, master **0.192 → 0.247** — the
biggest single jump in noisiness of any pass on this song, at
**−0.40 dBTP, 0 overshoots, 0 findings**, with the other three stems unchanged to
three decimals.

The concept line above still says "a staccato mono-synth singing the vocal line."
That was true of the song for two days and is kept here as history; the band is
now drums, bass, rhythm guitar and lead guitar.
