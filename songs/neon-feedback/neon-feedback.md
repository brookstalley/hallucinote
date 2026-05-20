# Neon Feedback

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

Disco + prog-metal fusion. Subdivision-halving intro simulates 'too fast to hear' settling to verse tempo. Jazzy disco voicings (Am9, D9, Gmaj7, Cmaj7) in verses, Phrygian power chords (F5, G5, Am) in pre-chorus, modal interchange (Am to A to F#m to D) in the bridge, with a 5/8 bridge-twist section testing section-boundary meter changes. Danceable rhythm with chromatic walk fills, polymetric hat layer in bridge, double-time hat in chorus-2 tag. Designed to exercise chord voicing ergonomics, per-note micro-timing offsets, and refusal paths (tempo automation, meter ratchet).

## Core specs

- **Slug:** `neon-feedback`
- **Title:** Neon Feedback
- **Key:** Am
- **Tempo:** 120.0 BPM
- **Time signature:** 4/4

## Structure

| Section | Bars | Feel |
|---------|------|------|
| `intro` | 1–8 | _TODO: fill in_ |
| `verse-1` | 9–16 | _TODO: fill in_ |
| `pre-chorus-1` | 17–24 | _TODO: fill in_ |
| `chorus-1` | 25–32 | _TODO: fill in_ |
| `verse-2` | 33–40 | _TODO: fill in_ |
| `pre-chorus-2` | 41–48 | _TODO: fill in_ |
| `bridge` | 49–56 | _TODO: fill in_ |
| `bridge-twist` | 57–64 | _TODO: fill in_ |
| `bridge-return` | 65–72 | _TODO: fill in_ |
| `chorus-2` | 73–80 | _TODO: fill in_ |
| `outro` | 81–88 | _TODO: fill in_ |

---

## Build

```bash
python songs/neon-feedback/build.py            # state-converger — re-run is no-op if nothing changed
python songs/neon-feedback/build.py --reset    # drop + rebuild from scratch
pytest songs/neon-feedback/tests/ -v           # shape tests
```

## Next steps

1. **Stage Live**: open Ableton, recreate the track shape that `captured_session.json` describes (or capture from a real Live session to overwrite the synthetic snapshot).
2. **Author clips**: open `build.py` and replace the `=== Compose-half ===` placeholder with library generators + hand-authored notes per section.
3. **Push to Live**: `/ableton-push neon-feedback --new-session` for the first push (W9-B `--auto-session` bootstraps the binding row + prints its id; reuse the id for subsequent pushes).
