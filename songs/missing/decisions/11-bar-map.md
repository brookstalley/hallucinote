# 11 — Arrangement bar-map

**Date:** 2026-06-01
**Decided by:** user ("this is perfect")
**Status:** locked (encoded in `build.py` constants; contracted by the shape test)

## Decision

128 bars, ~4:48 at 100 BPM, 4/4. Most sections 16 bars; two deliberate exceptions.

| # | Section | Bars | Range | ~Time | Arc beat |
|---|---|---|---|---|---|
| 1 | intro | 8 | 1–8 | 0:19 | Lost — pad only, notch wide, phantom root tail (`decisions/12`) |
| 2 | verse1 | 16 | 9–24 | 0:38 | Lost |
| 3 | chorus1 | 16 | 25–40 | 0:38 | Lost at the doorstep — full energy, no resolution |
| 4 | verse2 | 16 | 41–56 | 0:38 | Still lost |
| 5 | chorus2 | 16 | 57–72 | 0:38 | Notch Q narrows a hair |
| 6 | break | 16 | 73–88 | 0:38 | **False summit** — G-major illusion → B7 pivot |
| 7 | verse3 | **8** | 89–96 | 0:19 | **Disabused** — half-length gut-punch |
| 8 | finalchorus | 16 | 97–112 | 0:38 | Approach — D# pulls hardest |
| 9 | coda | 16 | 113–128 | 0:38 | **Found** — ~4-bar sub-osc swell + settle |

## Rationale for the two non-16 choices

- **Verse 3 = 8 bars (half-length).** The disabuse should land *fast and cold* — the
  narrator is dropped, not eased down. A full 16 would let it dwell and soften the
  cruelty of "the summit was a lie." Half-length makes it a gut-punch.
- **Break = 16 bars (not stretched to 24).** Considered 24 to let the false summit
  feel more euphoric/earned before it's snatched away. Chose 16 for punchier pacing;
  the "win" is briefer but the song stays tight at ~4:48. Revisit by ear — if the
  false summit doesn't feel *earned* in the mix, stretch the break to 24 (→ ~5:07).

## Notes

- Encoded as the `*_BAR` constants in `build.py`; sections + cue points derive from
  them. `tests/test_missing_build.py` asserts the exact (name, start, end) map, so the
  structure can't drift silently.
- The coda's last ~4 bars are reserved for the sub-osc swell (`decisions/03`).
