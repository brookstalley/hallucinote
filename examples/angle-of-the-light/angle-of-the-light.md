# The Angle of the Light

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

Doubt, transfigured, and then revealed as doubt again. The intro layers to D-F-Ab-C-Eb (half-diminished with a b9). The chorus re-roots those same five pitches on Ab -- Ab6/9#11, Lydian, radiant. Nothing changes but the bass, which moves by tritone. At the crescendo the bass slides back to D and the triumph is not destroyed but revealed: it was the doubt chord all along. We never escape doubt because we were never outside it.

## Core specs

- **Slug:** `angle-of-the-light`
- **Title:** The Angle of the Light
- **Key:** Dm
- **Tempo:** 144.0 BPM
- **Time signature:** 1/4

## Structure

| Section | Bars | Feel |
|---------|------|------|
| `intro` | 1–4 | _TODO: fill in_ |
| `verse` | 5–8 | _TODO: fill in_ |
| `riser` | 9–12 | _TODO: fill in_ |
| `bridge` | 13–16 | _TODO: fill in_ |
| `chorus` | 17–20 | _TODO: fill in_ |
| `chorus-reprise` | 21–24 | _TODO: fill in_ |
| `outro` | 25–28 | _TODO: fill in_ |

---

## Build

```bash
python songs/angle-of-the-light/build.py            # state-converger — re-run is no-op if nothing changed
python songs/angle-of-the-light/build.py --reset    # drop + rebuild from scratch
pytest songs/angle-of-the-light/tests/ -v           # shape tests
```

## Next steps

1. **Stage Live**: open Ableton, recreate the track shape that `captured_session.json` describes (or capture from a real Live session to overwrite the synthetic snapshot).
2. **Author clips**: open `build.py` and replace the `=== Compose-half ===` placeholder with library generators + hand-authored notes per section.
3. **Push to Live**: `/ableton-push angle-of-the-light --new-session` for the first push (W9-B `--auto-session` bootstraps the binding row + prints its id; reuse the id for subsequent pushes).
