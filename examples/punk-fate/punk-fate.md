# Punk Fate

## Concept

Beethoven's Fifth Symphony crammed into two minutes of basement punk. The whole four-movement harmonic arc — C minor fate riff, the E-flat relative-major lift, the A-flat andante as a half-time breakdown, the C minor scherzo, the great dominant-pedal transition, and the C MAJOR finale with its hammering coda — played by a four-piece: drums, bass, rhythm guitar, and a lead guitar carrying what started life as the vocal line. Raw and blown-out: darkness to triumph in 115 seconds.

> **Where this song's intent lives.** `decisions/` holds deliberate choices with
> their rationale (ADR-shaped, dated); `annotations/` holds timeless scoped intent
> (section feel, instrumentation, conventions). Query both with
> `/hallucinote:song-context [topic]`. How to write one:
> [`docs/song-authoring-conventions.md`](../../docs/song-authoring-conventions.md).

## Core specs

- **Slug:** `punk-fate`
- **Title:** Punk Fate
- **Key:** Cm → Cmaj
- **Tempo:** 200.0 BPM
- **Time signature:** 4/4

## Structure

96 bars of 4/4 at 200 BPM — one bar = 1.20 s, so 1:55 of music; the rendered
audio runs 1:58 with the coda's decay. The bar budget and why each section got
its share: `decisions/02-tempo-and-the-section-budget.md`.

| Section | Bars | Feel |
|---------|------|------|
| `intro-fate` | 1–8 | The fate cell twice, each answered by a full-band hole (the fermata as one bar of silence), then the band arrives |
| `verse-cm` | 9–24 | i–♭VI–♭III–V churn; guitar plays quarters through the first half so the bass carries the engine |
| `chorus-eb` | 25–36 | The relative-major lift — the motif re-harmonized as the hook, vocal doubled at the octave |
| `break-ab` | 37–48 | Half-time A-flat andante; the one section the lead line *sings* rather than chants — with Beethoven's own 2-bar C-major blaze inside it |
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

Authored end-to-end by Claude Code on 2026-08-11 from the sparse prompt quoted
in `annotations/01-the-brief.md`, then re-cut three times the same day. Each
pass's reasoning is a decision record; the beat-by-beat walkthrough, with the
transcript and the screenshots, is [`docs/tour.md`](../../docs/tour.md).

| Pass | What it changed | Why |
|---|---|---|
| **Compose** (`decisions/01`–`07`) | Brief → parts → push → render → one measured mix rebalance | The bass measured as the masked instrument in all eight sections, contradicting the arrangement's own stated intent |
| **Feel & dirt** (`08`, `09`) | Four `Player` profiles breathing in 1/f; a garage drum vocabulary; two gain stages added | The first pass read as Beethoven-played-correctly, and its per-part feel measured *mechanical* — every bass note the identical distance off the grid |
| **Tone** (`10`) | `Rock` amps at 42 % pedal drive, a hidden 24 %-wet reverb dialed out, drums up 11 dB behind a new Glue Compressor → Limiter | The guitar came back as "an electronic trumpet": every chain had been chosen by preset **name** and never verified by **parameter** |
| **Lead guitar** (`11`) | Track 4's Operator square became a second guitar | The last synthetic thing in the band — *"beep beep beep bloop"* |

Where that left it, measured full-song: **−0.40 dBTP delivered, 0 overshoots, 0
findings** across 8/8 sections, master spectral flatness **0.247**, and all four
parts reading `human` on the performance lens. The figures each pass cited ship
in `measurements/`, next to the decision that acted on them. Every device is
stock Live — no third-party plugins (`REQUIREMENTS.md`).

The dialed mix is baked into `captured_session.json`, so it survives
`build.py --reset`.

**Not done, on purpose:** both guitar racks' `Articulate` macro sits at 0 — the
rhythm guitar never switches between palm-mute and ring, the lead never engages
its glide. `decisions/10` names that UNDECIDED, owner: the next compose pass.
