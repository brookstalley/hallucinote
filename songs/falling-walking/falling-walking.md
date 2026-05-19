# falling-walking

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.
>
> This file is the **canonical overview** other songs should copy when starting. Keep it short: concept, structural reference, build orientation. Detail belongs in `decisions/` and `annotations/`.

---

## Concept

Verse seeks; chorus finds. Verse feels like inevitable falling. Chorus feels circular — Escher's stairs, climbing forever without arriving. Bridge is a sneaky sideways step into a brighter room.

Per-section feel: `annotations/verse-feel.md`, `annotations/chorus-feel.md`, `annotations/bridge-feel.md`, `annotations/intro-outro-feel.md`.

## Core specs

- **Key:** D minor (verse + chorus), B♭ major (bridge)
- **Tempo:** 132 BPM
- **Time signature:** 4/4
- **Aesthetic:** Unabashedly electronic, powerful

---

## Harmony

### Verse — "falling, seeking" (15 bars)

| Bars | Chord | Function |
|------|-------|----------|
| 1–8  | Dm    | i        |
| 9–12 | Gm    | iv       |
| 13–14| B♭    | VI       |
| 15   | A     | V        |

Why these chord choices feel like falling/seeking: `annotations/verse-feel.md`.

### Chorus — "circular, finding" (8 bars, 2 each)

| Bars | Chord | Function              |
|------|-------|-----------------------|
| 1–2  | Dm    | i                     |
| 3–4  | F     | III                   |
| 5–6  | C     | VII                   |
| 7–8  | G     | IV (Dorian, borrowed) |

Why ascending fifths + the Dorian IV: `annotations/chorus-feel.md`.

### Bridge — "sideways step" (B♭ major, 8 bars)

| Bars | Chord    | Function |
|------|----------|----------|
| 1–2  | B♭maj7   | I        |
| 3–4  | Gm7      | vi       |
| 5–6  | Cm7      | ii       |
| 7–8  | F7       | V        |

Why B♭ works as the pivot key + how F7 leads back: `annotations/bridge-feel.md`.

### Why the three pair

- Verse bass falls overall (D–G–B♭–A); chorus bass climbs in fifths (D–F–C–G); bridge sits on a brighter parallel plane.
- Verse harmonic rhythm decelerates toward resolution; chorus is metronomic; bridge is even, smooth.
- All three share B♭ and F as common chords — same harmonic neighborhood, three different psychologies.

### C3' twist (the climax)

C3' (bars 40-48) substitutes B♭maj7 for the chorus's final G. This is the central deliberate harmonic move — see `decisions/2026-05-01-c3-prime-twist.md`.

| Bars | C3 (with 7ths) | C3' (with twist)  |
|------|----------------|-------------------|
| 1–2  | Dm7            | Dm7               |
| 3–4  | Fmaj7          | Fmaj7             |
| 5–6  | Cmaj7          | Cmaj7             |
| 7–8  | G              | **B♭maj7**        |

---

## Form

| Section  | Bars | Notes                                     |
|----------|------|-------------------------------------------|
| Intro    | 16   | Chiptune lead establishes vocal hook      |
| V1       | 15   | 8/4/2/1 accelerating descent              |
| C1       | 8    | Half-time, calypso, Dm-F-C-G              |
| V2       | 15   |                                           |
| C2       | 8    |                                           |
| Tag      | 4    | Instrumental breath before modulation     |
| Bridge   | 8    | B♭ major bossa, B♭maj7-Gm7-Cm7-F7         |
| C3       | 8    | Standard chorus, with 7ths                |
| C3'      | 8    | Twist: last 2 bars sub G → **B♭maj7**     |
| Outro    | 8    | Stripped trip-hop pulse, chiptune fade    |
| **Total**| **98** | **~2:58 at 132 BPM**                    |

Groove patterns per section: `annotations/groove-conventions.md`.

---

## Live session — what was built

### Tracks (added at indices 5-12; user's existing 1-4 left untouched)

| # | Name | Device | Role |
|---|------|--------|------|
| 5 | 01 Drums | Drum Rack — Subtle Electronics Kit | Trip-hop / half-time / bossa drums |
| 6 | 02 Sub Bass | Operator (default) | Sine-ish sub layer |
| 7 | 03 Synth Bass | Wavetable (default) | Mid-bass with bite |
| 8 | 04 Verse Pad | Wavetable (default) | All chord pad work + intro/outro swell |
| 9 | 05 Chorus Pluck | Operator (default) | Calypso tresillo cell |
| 10 | 06 Bell | Operator (default) | High counter-melody accents |
| 11 | 07 Bridge EP | Electric (Rhodes-style) | Bossa chord voicings |
| 12 | 08 Chiptune Lead | Operator (default) | Vocal-hook placeholder, intro/outro |

### Session clip slots

`build.py` uses the same slot number for the same section across every track that participates, so the Session view shows aligned columns per section.

| Slot | Section |
|------|---------|
| 1 | Intro |
| 2 | Verse |
| 3 | Chorus (with 7ths) |
| 4 | Chorus C3' twist (B♭maj7 swap) |
| 5 | Bridge |
| 6 | Tag |
| 7 | Outro |
| 8 | C3' Drums variant (added v2) |

### Arrangement (98 bars, ≈2:58 at 132 BPM)

| Bar | Section | Length |
|-----|---------|--------|
| 1   | Intro          | 16 |
| 17  | Verse          | 15 |
| 32  | Chorus         | 8  |
| 40  | Chorus C3'     | 8  |
| 48  | Bridge         | 8  |
| 56  | Tag            | 4  |
| 60  | Outro          | 8  |
| 68  | (end)          | —  |

Cue points at every section. Form built from session clips via `duplicate_clip_to_arrangement`.

### Mix baseline

- Drums 0.78, Synth Bass 0.72, Chorus Pluck 0.72, Bridge EP 0.74, Chiptune Lead 0.72
- Sub Bass 0.62, Verse Pad 0.66, Bell 0.60 (foundation/atmospheric layers tucked back)
- Stereo: Chorus Pluck +0.25 R, Bell -0.30 L (chorus stereo width)
- All other tracks centered

Mix v1 device chains + intended settings: `decisions/2026-05-01-mix-v1-eq-first.md`.

---

## For future agents working on this song

### Where things live

- **Composer intent + dated decisions**: `decisions/` and `annotations/` in this folder (query via `/song-context`).
- **Curated overview**: this file. Keep it short — detail belongs in the split files.
- **Build script**: `build.py` — the source of truth for every clip, arrangement entry, and envelope. Run `python build.py --reset` to drop and rebuild the SQLite DB; push to Ableton via the hallucinote sync layer.
- **Repo location**: `~/source/hallucinote/songs/falling-walking/`. The MCP server is the in-repo `hallucinote_mcp/` package; `.mcp.json` invokes the `hallucinote-mcp` console script.
- **Iteration workflow**: edit `build.py` → `python songs/falling-walking/build.py --reset` → push to Ableton via the sync layer. Arrangement entries live in the DB; push regenerates Live's arrangement from those entries.

### MIDI pitch reference (key D minor, B♭ major bridge)

- Sub-bass register: D1=26, G1=31, B♭1=34, A1=33, C2=36, F2=41
- Bass register: D2=38, G2=43, B♭2=46, A2=45
- Pad register: F3=53, G3=55, A3=57, B♭3=58, B3=59, C4=60, C#4=61, D4=62, E♭4=63, E4=64, F4=65, G4=67, A4=69, B♭4=70, B4=71, C5=72, D5=74
- Lead register (chiptune): mostly D4-A4 range
- Drum kit (GM-style): kick=36, side-stick=37, snare=38, closed hat=42, open hat=46, ride bell=53, splash=55, crash1=49, crash2=57, china=52, hi-tom=50, mid-tom=47

### Voice leading conventions

See `annotations/voice-leading.md`.

### Groove conventions

See `annotations/groove-conventions.md`.

---

## Open

- [ ] Vocal melody / topline (see `annotations/vocals-intent.md`)
- [ ] Lyrical concept and content
- [ ] Sound design pass on each synth patch (see `annotations/production-tricks.md` + `annotations/known-limitations-v1.md`)
- [ ] Tag transition into bridge (currently chorus-style first 2 + bossa-foreshadow last 2; no riser/sweep)
- [ ] Send + sidechain routing per `decisions/2026-05-01-mix-v1-eq-first.md` deferred list
