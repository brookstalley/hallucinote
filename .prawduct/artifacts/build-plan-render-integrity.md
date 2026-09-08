---
artifact: build-plan
version: 1
scope: render-integrity
branch: feat/render-integrity
---

# Build Plan — Render integrity: defect, phase, imaging and reconciliation lenses

**Branch:** `feat/render-integrity` (off `develop`)
**Type:** Feature (four read-side analysis lenses + integration) · **Size:** Large
**Critic mode:** cumulative (run via an independent Agent — worktree work is blind to the primary session's Stop-hook gate; same posture as `build-plan-aud-sharpness-transients.md`)
**Worktree:** `/Users/brookstalley/source/hallucinote-wt-integrity`. The primary checkout `/Users/brookstalley/source/hallucinote` serves `--plugin-dir` to a live songs session and is deliberately untouched.
**Origin:** owner ask (2026-09-08), after the sharpness/transient lenses merged. The question "are there other lenses we should add" was steered to a class the report has none of: *is the audio itself damaged* — clipping, clicks and pops, dropouts, phase and soundstage problems.

## Confidence Check

- **Problem:** every lens in the MixReport measures *musical realization against intent*. Nothing measures whether the captured audio is **defective**. Across all 23 modules in `audio/` there is no clipping detection, no DC offset, no discontinuity/click detection, no dropout detection, no polarity check and no stem-vs-master reconciliation; the only clip-adjacent number in the whole report is the master's delivered true peak. The string `click` appears only as a *musical* term (the kick beater's 2–6 kHz band in `transients.py`) and as a test fixture.
- **Success:** a render whose stems clip, carry a DC offset, contain a buffer dropout, start on a non-zero-crossing, are polarity-flipped, sit at a non-zero time offset, are panned lopsided, or fail to sum to the captured master — says so in the report, per surface and per pair, with the location in beats. A clean render says so too, distinguishably from "could not check".
- **Out of scope:** repairing anything (every lens is measurement; `/mix-review` interprets); Live-side capture changes; source separation; a verdict on how much of any defect is acceptable — thresholds that encode taste stay out (see Design decision 2).

## Requirements Confidence

**Level:** High (unusually, for this repo)

**Why:** unlike the musical lenses, every quantity here has physical ground truth. A sample discontinuity, a zero-run, a polarity inversion and a cross-correlation lag are facts, not readings against a declared intent. There is no calibration campaign hiding behind these numbers.

**Open assumptions / unknowns:**
- [ASSUMPTION: detection floors that separate a real defect from ordinary program material (a click's derivative threshold, a dropout's minimum run length) can be set from first principles plus synthetic fixtures, without a jitter calibration set | MED impact | resolved by running the pass over a real Live capture — requested from the songs session]
- [ASSUMPTION: stems summed at their fader gains reconstruct the captured master closely enough that a residual is diagnostic | HIGH impact for Chunk 04 only | `masking.py`'s level reconstruction has known limits (backlog #253); Chunk 04 reports the residual and its band distribution rather than asserting a pass/fail]

## Design decisions

1. **This class is upstream of every other lens, so it is reported at the top level, per surface, not per section.** A click reads as an onset to `onsets.py` and corrupts the timing and cross-rhythm lenses; a dropout reads as a dynamics move; an uncompensated plugin latency reads as *feel* — the timing lens will faithfully report a part as laid-back when it is actually a PDC bug. Integrity is a precondition for believing the rest of the report, so it is measured over the whole capture and surfaced beside `alignment`, not inside `per_section`.
2. **This class is exempt from the analyzer freeze, and may emit `blocking` findings.** `arrangement-model.md`'s 2026-08-10 owner ruling gates lenses whose thresholds *encode taste*. A sample discontinuity has physical ground truth, so no listening day is required — and unlike every musical lens, which may only inform, a defect lens may legitimately block. The line is drawn per lens in its module docstring: *what is a defect* is in scope, *how much of it is acceptable musically* is not.
3. **Four independent DSP modules; the coordinator owns the wire.** Each chunk delivers one self-contained module in `src/hallucinote/audio/` with pure functions over `np.ndarray` plus module-local frozen result dataclasses — the precedent is `transients.TransientWindowResult`, which `report.py` names as living in its own module. `report.py`, `analyze.py`, `compare.py` and the skill docs are the coordinator's alone. **This is what makes the four chunks parallel-safe: file ownership is disjoint by construction, so there is no merge conflict to resolve.**
4. **`cross_correlation_peak_lag` is promoted out of the test file, not reimplemented.** It has lived in `tests/unit/audio/test_pdc_alignment.py:48` since the MVP, with a docstring promising promotion to `alignment.py` "in Chunk 3" — a chunk that shipped without it, leaving `alignment.py:39` pointing at a function in the test tree. Chunk 02 promotes it and drops the stale plan reference (no "pre-existing" exception).

**partition:** parallel, four delegates. The chunks are independent by construction (decision 3): disjoint modules, disjoint test files, no shared edits, and none consumes another's output. Integration and all governance stay with the coordinator.

## Chunks

### Chunk 01: render integrity — clipping, DC, dropouts, clicks, truncation
- `audio/integrity.py` (new): `measure_integrity(audio, *, sample_rate, ...) -> SurfaceIntegrity`.
- Detects: consecutive-sample clipping runs (count, worst run, fraction, first location); per-channel DC offset; zero-run dropouts and abrupt RMS collapses; sample-derivative discontinuities not explained by a detected onset; non-zero signal at the final sample (truncated decay); an all-silent surface.
- Tests: `tests/unit/audio/test_integrity.py`.
- **Done when:** `test_integrity.py` green; every detector fires on a synthetic positive and stays silent on a clean fixture.

### Chunk 02: phase and alignment integrity
- `audio/phase.py` (new): pairwise polarity inversion, time offset, and per-band cancellation between surfaces.
- `audio/alignment.py`: promote `cross_correlation_peak_lag` from the test tree; correct the stale reference at line 39.
- Tests: `tests/unit/audio/test_phase.py`; `test_pdc_alignment.py` imports the promoted function instead of defining it.
- **Done when:** both test files green; a polarity flip, an injected lag, and a comb-filtered pair are each recovered.

### Chunk 03: soundstage imaging
- `audio/imaging.py` (new): per-surface L/R energy balance in dB, per-Bark-band L/R correlation, and mid/side ratio with a derived image position and width.
- Tests: `tests/unit/audio/test_imaging.py`.
- **Done when:** `test_imaging.py` green; a hard-panned, a centred, a wide and a mono-low/wide-top fixture each read as expected.

### Chunk 04: stem-sum vs master reconciliation
- `audio/reconcile.py` (new): sum stems at their fader gains, compare to the captured master, report broadband and per-band residual.
- Tests: `tests/unit/audio/test_reconcile.py`.
- **Done when:** `test_reconcile.py` green; a faithful sum reads ~0 dB residual, a missing stem and a master-chain gain change are each distinguishable.

### Chunk 05: integration (coordinator)
- `audio/report.py`: the four result types on `MixReport`; serialization through the existing `_finite_or_none` optional-field pattern so pre-integrity baselines stay valid.
- `audio/analyze.py`: flags and wiring; findings emission.
- `audio/compare.py`: significance floors for the A/B-able quantities.
- `skills/mix-review/SKILL.md`, `docs/` and change-log.
- **Done when:** full suite green (`python -m pytest`, no path arg); cumulative Critic via an independent Agent; artifacts current.

## Status
- [ ] Chunk 01 — render integrity
- [ ] Chunk 02 — phase and alignment
- [ ] Chunk 03 — soundstage imaging
- [ ] Chunk 04 — reconciliation
- [ ] Chunk 05 — integration

## Context

Delegates dispatched 2026-09-08 into sibling worktrees (`hallucinote-wt-ri-{integrity,phase,imaging,reconcile}`), each branching `chunk/ri-*` off `feat/render-integrity`. Each carries its brief at `.prawduct/.delegate-brief.md`. The coordinator merges them into `feat/render-integrity` as they land and does Chunk 05 on top.
