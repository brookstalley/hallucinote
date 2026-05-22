# Sun Zone / Stuff Done

> **Composer intent + dated decisions** for this song live alongside this overview:
> - `decisions/` — deliberate choices with rationale (ADR-shaped, dated)
> - `annotations/` — timeless scoped intent (section feel, instrumentation, conventions)
>
> Query both via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md` for the convention.

---

## Concept

Reggae / speed-metal mashup. Alternating (not overlapping) sections express the tension between wanting to relax and having too much to do. Reggae sections in E Dorian carry the chill 'sun zone' half, felt half-time at 90 BPM; metal sections in E Phrygian carry the 'NO TIME FOR THAT' urgency at 180. Tempo constant, subdivision changes — the genre flip is articulation, not a tempo cut. Genre pivots harmonically on F-sharp -> F-natural and C-sharp -> C-natural, same E tonic, modes flip. Fun but not novelty: the harmony does the joke. Vocal-shaped hole pre-carved via placeholder lead in E3-E4 register; vocals to be performed later.

## Core specs

- **Slug:** `sun-zone-done`
- **Title:** Sun Zone / Stuff Done
- **Key:** Em
- **Tempo:** 180.0 BPM
- **Time signature:** 4/4

## Structure

| Section | Bars | Feel |
|---------|------|------|
| `intro` | 1–8 | _TODO: fill in_ |
| `verse1` | 9–16 | _TODO: fill in_ |
| `chorus1` | 17–24 | _TODO: fill in_ |
| `verse2` | 25–32 | _TODO: fill in_ |
| `chorus2` | 33–40 | _TODO: fill in_ |
| `bridge` | 41–48 | _TODO: fill in_ |
| `chorus3` | 49–56 | _TODO: fill in_ |
| `outro` | 57–64 | _TODO: fill in_ |

---

## Build

```bash
python songs/sun-zone-done/build.py            # state-converger — re-run is no-op if nothing changed
python songs/sun-zone-done/build.py --reset    # drop + rebuild from scratch
pytest songs/sun-zone-done/tests/ -v           # shape tests
```

## Next steps

1. **Stage Live**: open Ableton, recreate the track shape that `captured_session.json` describes (or capture from a real Live session to overwrite the synthetic snapshot).
2. **Author clips**: open `build.py` and replace the `=== Compose-half ===` placeholder with library generators + hand-authored notes per section.
3. **Push to Live**: `/ableton-push sun-zone-done --new-session` for the first push (W9-B `--auto-session` bootstraps the binding row + prints its id; reuse the id for subsequent pushes).
