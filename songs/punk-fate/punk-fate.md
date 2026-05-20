# Punk Fate

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

Condense the chord progressions of Beethoven's 5th into a 2-minute punk-rock arc. Verses pull from Mvt. I's i-iv-V and III-VI-iio6-V in C minor (the fate motif); choruses lift to C major mirroring Mvt. IV's triumph; bridge nods to the Eb-major second theme. Four parts: drums, bass, lead guitar, and a staccato synth carrying the vocal line. Real punk energy — fast, raw, driving, no precious moments.

## Core specs

- **Slug:** `punk-fate`
- **Title:** Punk Fate
- **Key:** Cm
- **Tempo:** 180.0 BPM
- **Time signature:** 4/4

## Structure

| Section | Bars | Feel |
|---------|------|------|
| `intro` | 1–8 | _TODO: fill in_ |
| `verse` | 9–16 | _TODO: fill in_ |
| `chorus` | 17–24 | _TODO: fill in_ |
| `verse2` | 25–32 | _TODO: fill in_ |
| `chorus2` | 33–40 | _TODO: fill in_ |
| `bridge` | 41–48 | _TODO: fill in_ |
| `outro` | 49–56 | _TODO: fill in_ |

---

## Build

```bash
python songs/punk-fate/build.py            # state-converger — re-run is no-op if nothing changed
python songs/punk-fate/build.py --reset    # drop + rebuild from scratch
pytest songs/punk-fate/tests/ -v           # shape tests
```

## Next steps

1. **Stage Live**: open Ableton, recreate the track shape that `captured_session.json` describes (or capture from a real Live session to overwrite the synthetic snapshot).
2. **Author clips**: open `build.py` and replace the `=== Compose-half ===` placeholder with library generators + hand-authored notes per section.
3. **Push to Live**: `/ableton-push punk-fate --new-session` for the first push (W9-B `--auto-session` bootstraps the binding row + prints its id; reuse the id for subsequent pushes).
