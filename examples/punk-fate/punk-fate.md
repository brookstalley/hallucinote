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
