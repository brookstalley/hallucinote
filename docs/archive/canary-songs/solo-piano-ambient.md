# Canary: `solo-piano-ambient`

## Shape

A 4-minute solo-piano ambient piece in C Lydian. **One MIDI track** (piano), **two return tracks** (reverb send, delay send), **master**. **60 BPM**, **4/4**. No drums, no bass, no vocals. Long sustained chords (whole-notes and dotted-half across bars), sparse melodic gestures (single-note motifs separated by 2-4 bars of silence), pedal-down throughout.

Section shape (intentionally minimal):

| Section | Bars | Feel |
|---------|------|------|
| `prelude` | 1–8   | Solitary single notes, MM=60, *pp*. |
| `bloom`   | 9–32  | Stacked chord pads (whole-notes), MM=60, *p → mp* via slow envelope crescendo. |
| `recede`  | 33–48 | Sparse motifs return over fading pad, MM=60, *mp → pp* via slow decrescendo. |
| `silence` | 49–56 | Empty bars (8 bars of intentional rest) — tests the empty-arrangement case. |

Mixing intent:

- Piano track sends ~40% to **Send A (Reverb)** and ~20% to **Send B (Delay)** throughout.
- Envelope on Send A automates the reverb send up to ~60% across `bloom` (long ramp), back down across `recede`.
- Master ceiling at -6 dBFS via a Utility on master (gain only).

## What this canary exercises

**Long-envelope authoring (the main target).** Falling-walking's envelopes are short and sectional. This canary writes envelopes whose breakpoint lists span entire sections (~96+ bars of beats), exercising the W6 envelope write path and Wave 7's round-trip robustness without trip-hop's groove crutch hiding sloppy spacing.

**Empty-arrangement sections.** The `silence` section has no clips on any track. Tests whether the arrangement planner handles holes correctly (a section with zero `arrangement_clips` rows).

**Single-track sparsity.** Most of falling-walking's tests assume 8+ authoring tracks. One-track shape stresses any place a planner has hardcoded "multi-track" assumptions (per-domain reports, push-progress lines, etc.).

**Slow tempo (60 BPM).** Falling-walking is 132 BPM; pieces below ~80 BPM exercise any beat-math that quietly assumes higher density.

**Sustained chords as whole-notes-with-overlap.** Some chords intentionally tie across bar boundaries via overlapping start/end beats — tests the note ingestion + push path for legato/overlapping voicings (vs. falling-walking's overwhelmingly mono-rhythmic patterns).

**Send-bus envelope.** Send-level automation on a return-track receive is a path that doesn't run in falling-walking's mix tests at this depth.

## Out of scope for the canary

- No third-party instruments; the piano is **Live's stock "Grand Piano" Instrument Rack** (no Pack required beyond Core Library, which ships with Live).
- No vocals.
- No tempo or signature changes.
- No nested racks.

## Success criteria for the agent

The agent attempts, in order:

1. Scaffold `songs/solo-piano-ambient/` (no `/new-song` skill exists yet — surface that as friction).
2. Author a `build.py` that produces the structure above against the `hallucinote` library + generators.
3. Author a `captured_session.json` representing the piano + 2 returns + master shape (since they cannot capture from a real Live without manual setup — surface the chicken-and-egg).
4. Write `tests/test_<slug>_build.py` (per-song convention so files stay unique under `pytest -n auto`) mirroring falling-walking's shape assertions.
5. Run the build + tests; record what passed and what failed.
6. **Do NOT** attempt to push to Live (no Live session is available in this harness; the push-side smoke is W0-B's manual follow-up, not the agent's job).

The agent surfaces every friction encountered in steps 1-5 to `solo-piano-ambient-runbook.md`.
