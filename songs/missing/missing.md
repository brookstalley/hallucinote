# missing

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

'missing' renders loss of purpose as a harmonic constraint: every chord is voiced without its root, so the tonal foundation is literally absent. In E harmonic minor (i-V-iv = Em-B7-Am, voiced rootless), the raised-7th leading tone D# pulls the ear toward an E that never arrives. The narrator is lost, searching for a ground that isn't there; the choruses, where pop form promises arrival, deny it twice. The break is a FALSE SUMMIT: the song slips into its own bright G-major illusion and the narrator believes they have found their purpose, until the pivot chord B7 reintroduces D#, collapses the illusion, and the last verse disabuses them. Only at the very end does the root return: a sub-oscillator E swells up from the empty bottom octave as the melody lands on E for the first time. Found, finally, meaning located rather than happy. Energetic (100 bpm, pulsing arp) with one structural wound. Theme is LOSS OF PURPOSE, not loss of a person.

## Core specs

- **Slug:** `missing`
- **Title:** missing
- **Key:** Em
- **Tempo:** 100.0 BPM
- **Time signature:** 4/4

## Dramatic arc — lost → false summit → disabused → found

The whole song is one withheld resolution. See `annotations/00-theme.md` (the spine)
and the dated `decisions/`. Theme is **loss of purpose, not loss of a person**;
"found" means *located*, not happy.

The **idiom shifts by section** (`decisions/13`): **cinematic** verses/intro/coda (the
real lost-and-found) vs. **synthpop** choruses + break peak (the bright, false hope) —
the song's most euphoric sound sits on its least honest moments.

## Structure

> Locked bar map (`decisions/11-bar-map.md`), encoded in `build.py` and contracted by
> the shape test. 128 bars, ~4:48 at 100 BPM. The DB is the source of truth.

| Section | Bars | Arc beat | Feel |
|---------|------|----------|------|
| `intro` | 1–8 | Lost | Pad only, notch wide open (max root absence). Opens on the **phantom root tail** — an E power chord struck two beats before the song, heard only as a dying reverb hint: *the root you just missed* (`decisions/12`). |
| `verse1` | 9–24 | Lost | Bass (5ths, hi-passed), pulsing arp, melody enters reaching for a ground that isn't there. |
| `chorus1` | 25–40 | Lost at home's doorstep | Full arrangement energy, **zero harmonic resolution** — the cruelest denial. |
| `verse2` | 41–56 | Still lost | As V1; texture a touch fuller. |
| `chorus2` | 57–72 | Coalescing | Notch Q narrows a hair — root overtones bleed through subliminally. Still no floor. |
| `break` | 73–88 | **False summit** | Modulates into the bright **G-major illusion** (still rootless) — euphoric, the narrator believes they've found their purpose. Pivot **B7** reintroduces D#, collapses it, lands on **V of E**. |
| `verse3` | 89–96 | Disabused | Half-length gut-punch — the last verse takes the purpose back. The summit was a lie. |
| `finalchorus` | 97–112 | Approach | Tension at maximum; the D# leading tone pulls hardest toward an E about to arrive. |
| `coda` | 113–128 | **Found** | **The reveal:** sub-osc **E** swells up over ~4 bars (first energy in the bottom octave all song) — the same root whose tail died in the intro; melody lands on E for the first time. Voice and floor arrive together. Located, not happy. |

---

## Build

```bash
python songs/missing/build.py            # state-converger — re-run is no-op if nothing changed
python songs/missing/build.py --reset    # drop + rebuild from scratch
pytest songs/missing/tests/ -v           # shape tests
```

## Next steps

1. **Stage Live**: open Ableton, recreate the track shape that `captured_session.json` describes (or capture from a real Live session to overwrite the synthetic snapshot).
2. **Author clips**: open `build.py` and replace the `=== Compose-half ===` placeholder with library generators + hand-authored notes per section.
3. **Push to Live**: `/ableton-push missing --new-session` for the first push (W9-B `--auto-session` bootstraps the binding row + prints its id; reuse the id for subsequent pushes).
