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
**Worktree:** `~/source/hallucinote-wt-integrity`. The primary checkout `~/source/hallucinote` serves `--plugin-dir` to a live songs session and is deliberately untouched.
**Origin:** owner ask (2026-09-08), after the sharpness/transient lenses merged. The question "are there other lenses we should add" was steered to a class the report has none of: *is the audio itself damaged* — clipping, clicks and pops, dropouts, phase and soundstage problems.

## Confidence Check

- **Problem:** every lens in the MixReport measures *musical realization against intent*. Nothing measures whether the captured audio is **defective**. Across all 23 modules in `audio/` there is no clipping detection, no DC offset, no discontinuity/click detection, no dropout detection, no polarity check and no stem-vs-master reconciliation; the only clip-adjacent number in the whole report is the master's delivered true peak. The string `click` appears only as a *musical* term (the kick beater's 2–6 kHz band in `transients.py`) and as a test fixture.
- **Success:** a render whose stems clip, carry a DC offset, contain a buffer dropout, start on a non-zero-crossing, are polarity-flipped, sit at a non-zero time offset, are panned lopsided, or fail to sum to the captured master — says so in the report, per surface and per pair, with the location in beats. A clean render says so too, distinguishably from "could not check".
- **Out of scope:** repairing anything (every lens is measurement; `/mix-review` interprets); Live-side capture changes; source separation; a verdict on how much of any defect is acceptable — thresholds that encode taste stay out (see Design decision 2).

## Requirements Confidence

**Level:** High (unusually, for this repo)

**Why:** unlike the musical lenses, every quantity here has physical ground truth. A sample discontinuity, a zero-run, a polarity inversion and a cross-correlation lag are facts, not readings against a declared intent. There is no calibration campaign hiding behind these numbers.

**Open assumptions / unknowns:**
- ~~[ASSUMPTION: detection floors that separate a real defect from ordinary program material can be set from first principles plus synthetic fixtures]~~ **FALSIFIED and corrected 2026-09-08.** Run over two real `alien` captures, the floors held for dropouts, DC and truncation and FAILED for clipping and lag — both in the false-positive direction, and neither detectable synthetically because the synthetic corpus contained no pre-fader stem above full scale and no genuinely unrelated pair. Both fixed with regression tests; the general lesson is that a detector's *negative* control has to be real program material, not clean fixtures.
- [ASSUMPTION: stems summed at their fader gains reconstruct the captured master closely enough that a residual is diagnostic | HIGH impact for Chunk 04 only | `masking.py`'s level reconstruction has known limits (backlog #253); Chunk 04 reports the residual and its band distribution rather than asserting a pass/fail]

## Design decisions

1. **This class is upstream of every other lens, so it is reported at the top level, per surface, not per section.** A click reads as an onset to `onsets.py` and corrupts the timing and cross-rhythm lenses; a dropout reads as a dynamics move; an uncompensated plugin latency reads as *feel* — the timing lens will faithfully report a part as laid-back when it is actually a PDC bug. Integrity is a precondition for believing the rest of the report, so it is measured over the whole capture and surfaced beside `alignment`, not inside `per_section`.
2. **This class is exempt from the analyzer freeze, and may emit `blocking` findings.** `arrangement-model.md`'s 2026-08-10 owner ruling gates lenses whose thresholds *encode taste*. A sample discontinuity has physical ground truth, so no listening day is required — and unlike every musical lens, which may only inform, a defect lens may legitimately block. The line is drawn per lens in its module docstring: *what is a defect* is in scope, *how much of it is acceptable musically* is not.
3. **Four independent DSP modules; the coordinator owns the wire.** Each chunk delivers one self-contained module in `src/hallucinote/audio/` with pure functions over `np.ndarray` plus module-local frozen result dataclasses — the precedent is `transients.TransientWindowResult`, which `report.py` names as living in its own module. `report.py`, `analyze.py`, `compare.py` and the skill docs are the coordinator's alone. **This is what makes the four chunks parallel-safe: file ownership is disjoint by construction, so there is no merge conflict to resolve.**
4. **`cross_correlation_peak_lag` is promoted out of the test file, not reimplemented.** It has lived in `tests/unit/audio/test_pdc_alignment.py:48` since the MVP, with a docstring promising promotion to `alignment.py` "in Chunk 3" — a chunk that shipped without it, leaving `alignment.py:39` pointing at a function in the test tree. Chunk 02 promotes it and drops the stale plan reference (no "pre-existing" exception).

5. **Imaging rides `StemMetrics`; the other three sit at the top level.** Design decision 1 placed all four at the top level, and that was right for the three *defect* lenses — integrity, phase and reconciliation answer "is this capture damaged", which is a property of the render, not of a section. Imaging is not a defect lens: it is a standing per-surface descriptor exactly like `timbre` and `stereo`, and putting it on `StemMetrics` beside them gives the per-section reading for free instead of duplicating the field. Amended after the delegates landed, when the shape was concrete rather than predicted.
6. **`report.py` imports the lens result types under `TYPE_CHECKING` only.** `phase.py` and `imaging.py` import `stereo.py`, which imports `report.py` — a runtime import in `report.py` would close that cycle. The module already carries `from __future__ import annotations`, so the annotations stay strings and the serializers read attributes rather than types.

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
- [x] Chunk 01 — render integrity
- [x] Chunk 02 — phase and alignment
- [x] Chunk 03 — soundstage imaging
- [x] Chunk 04 — reconciliation
- [x] Chunk 05 — integration

## Context

All four delegates landed and merged into `feat/render-integrity` without a conflict — the disjoint-module partition held exactly as designed. Their worktrees (`hallucinote-wt-ri-{integrity,phase,imaging,reconcile}`) and `chunk/ri-*` branches are merged and ready to remove.

**What the real-capture pass found, which synthetic fixtures could not.** Two lenses shipped a false positive that only real program material exposes, and both are fixed:

- *Clipping keyed on amplitude.* Captured stems are pre-fader float32, so a healthy part peaking at +6.30 dBFS spends most of every cycle above full scale without ever going flat — 7970 phantom clip runs on undamaged audio, and it accused the loudest healthy stem in the song. Clipping is now a flat top (samples pinned to one value near the surface's own ceiling), which reads zero there and still catches genuine flat-topping at any level.
- *Every lag was reported as if believable.* A cross-correlation always peaks somewhere, so all eight uncorrelated stem pairs reported offsets of tens of milliseconds at r ~ 0 — two parts sharing a downbeat, which `/mix-review` would have read as device latency. `lag_correlation` now carries how much of the reading to trust (0.001-0.043 on those pairs; >0.9 for a genuine delay).

**Two delegates independently reached for the same private helpers** (`attribution._single_band_energy`, `stereo._correlation`) rather than duplicate a definition. That convergence is why both are now public as `band_energy` / `channel_correlation`.

**Independent review round (2026-09-08).** Four blocking findings, all fixed, plus five notes accepted and filed as #482. The blocking ones were: `stem_gains` converted through Live's fader curve twice (the handler already returns linear gains) so every reconciliation number was wrong on a real render; a single global sigma in the discontinuity detector, which reports tens of thousands of clicks on any percussive part because music is non-stationary; the new flat-top clipping rule carrying an absolute flatness tolerance, which is a false positive at the *quiet* end exactly as the amplitude rule was at the loud end; and a zero-run accepted on *either* abrupt edge, which makes every musical rest a dropout. Findings emission — a named Chunk 05 deliverable — was genuinely missing and is now built at `warning` severity.

**Two rulings on the reviewer's pushback, both of which I accept.**

- *Design decision 2 proved less than it claimed.* "A sample discontinuity has physical ground truth, so no listening day is required" is true of the **quantity** and false of the **threshold placed on it**. Three of the four blocking findings were exactly that: a physically-grounded quantity given a bound no synthetic corpus could falsify. Exempt from the freeze is not exempt from calibration, and this family needs a real-render negative control — a drum stem, a sub, a quiet pad — as badly as a taste lens needs a listening day.
- *Design decision 3's partition guaranteed no merge conflict and guaranteed nobody owned the interface.* Both defects that mattered most (the gain-unit mismatch, and a skip token unreachable from the real caller) were **seam** defects between a delegate's module convention and the coordinator's call site — invisible to each side's own tests, because each was self-consistent. The cheap mitigation, now written into the pattern: for each delegate module, one integration test at the `analyze_mix` level exercising the **production** argument shapes rather than the module's own convention. `test_analyze_mix_passes_stem_gains_as_linear_gains` is that test, and it was mutation-checked against the reintroduced bug.

**Deferred, with reasons:** the staircase-ramp gesture request from the songs session (a finer-authored ramp currently produces MORE not-realized findings than a coarse one, inverting the signal) is a real defect in the *automation verifier*, not in any lens here — filed, not built, because a peer session cannot widen this plan's scope. `compare.py` significance floors for the new A/B-able quantities are also unbuilt: every threshold here would encode taste, which is the one thing this family is exempt from *because* it avoids.
