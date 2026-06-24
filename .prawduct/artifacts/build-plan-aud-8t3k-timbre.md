# Build Plan — AUD-8T3K: Standing per-stem/per-section timbre metrics

**Branch:** `feature/aud-8t3k-timbre` (worktree off `develop`)
**Type:** Feature (read-side analysis lens) · **Size:** Medium
**Critic mode:** cumulative (run via independent Agent — worktree is invisible to the primary-session gate, per `feedback_worktree_governance_gates_blind`)

## Confidence Check

- **Problem:** The mix report carries loudness only per stem/section — no timbre
  descriptor — so "make X noisier / brighter / grittier" can only be judged by ear,
  never verified against a number, even though the engine renders the audio and owns
  the DSP.
- **Success:** `analyze_mix` emits a standing `timbre` object (centroid, flatness,
  rolloff) per surface in the report JSON and per section; `compare_to` surfaces
  before/after timbre deltas; the section centroid registers as energy.py's DR-3
  spectral-intensity correlate. A "make it brighter" edit moves a number.
- **Out of scope:** grading/re-authoring (read-side lens only, per `energy.py`'s
  never-grades stance); realtime OSC spectral STREAM (AUD-7W1N, different surface);
  empirical calibration of timbre significance thresholds (deferred — see Chunk 2).

## Design decisions (rationale that has no home in code)

1. **Flatness over Bark band powers, NOT raw FFT bins** (spec-mandated). Raw bins
   crush to ~0 for any pitched material (near-zero bins between harmonics drag the
   geometric mean to 0 → flatness ≈ 0 for everything, useless). Aggregating to the
   24 Zwicker Bark bands `masking.py` already uses gives a meaningful tonal↔noise
   axis. → reuse the Bark machinery (extracted to `audio/bark.py`).

2. **Median over silence-gated frames for the whole-stem stat (NOT p90).** The spec
   flags the concern that a plain median understates transient broadband content
   (drums). Resolution: the **silence gate is what makes the median fair** — frames
   below the energy floor (inter-onset quiet) are dropped before aggregating, so the
   median reflects timbre *during sound*, not *including silence*. For sparse
   percussive material only the hit frames survive, so their median is the brightness
   *during hits* — exactly what we want. This avoids p90's single-bright-frame noise
   sensitivity while still capturing transient character. Median is the conventional,
   stable, interpretable central tendency for a standing descriptor.

3. **Section centroid fills the DR-3 slot; coordinate with ARR-2S9D (unbuilt).**
   `energy.py:38` documents an open-by-design correlate registry (DR-3). Registering
   the per-section **master** centroid as a `spectral_centroid` correlate is additive
   — it ranks section brightness vs declared energy (neutral ρ, never grades).
   ARR-2S9D (per-section energy correlate, same slot, `stage: requirements`, unbuilt)
   adds further keys the same way when built — no conflict.

4. **Section timbre rides the per-section `StemMetrics`, not a new `SectionMetrics`
   field.** The spec named both `StemMetrics` and `SectionMetrics` as homes, but
   `SectionMetrics` already holds `master` / `stems` / `returns` as `StemMetrics`,
   each serialized through `_stem_to_dict` — so adding `timbre` to `StemMetrics`
   delivers per-section timbre for free (identical to how per-section *loudness* is
   homed). No separate `SectionMetrics.timbre` field is needed; the observable
   requirement (timbre per section in the JSON) is met and tested.

5. **Timbre significance thresholds are PROVISIONAL (uncalibrated).** Unlike loudness
   (calibrated against the sun-zone-done re-capture jitter set), there is no
   render-jitter baseline for centroid/flatness/rolloff yet. `compare.py` surfaces
   timbre deltas with provisional thresholds explicitly marked uncalibrated; a
   re-capture-jitter calibration is filed as a follow-up backlog item. Honest
   Confidence over a fabricated noise/signal verdict.

## Chunks

### Chunk 1 — DSP core: `bark.py` extraction + `timbre.py` + centroid dedup
- **`audio/bark.py`** (new): extract `BARK_EDGES_HZ`, `BarkMap`, `bark_band_map`,
  `aggregate_to_bands` from `masking.py` (behavior-preserving move). `masking.py`
  imports them; its `_band_power` becomes `stft → aggregate_to_bands`. Masking tests
  are the safety net.
- **`audio/timbre.py`** (new): `measure_timbre(audio, sr) -> TimbreMetrics` — one
  STFT (n_fft=2048/hop=512, matching masking), silence-gate frames, per-frame
  centroid (rfftfreq-weighted) + rolloff (0.85 cumulative) + flatness (geo/arith mean
  over Bark bands), median over surviving frames; NaN-triple when no measurable frame.
  Plus `spectral_centroid_hz(mono, sr) -> float` (whole-window, lifted from
  `automation._spectral_centroid_hz`). Reuse `onsets.to_mono`.
- **`audio/report.py`**: add `@dataclass(frozen=True) TimbreMetrics` beside
  `LoudnessMetrics`.
- **`audio/automation.py`**: delete its private `_spectral_centroid_hz`, import the
  lifted one (dedup). No external callers — clean.
- **Tests:** pure-DSP unit tests for `measure_timbre` (pitched tone → low flatness;
  white noise → high flatness ≈ 1; bright vs dark sweep → centroid ordering; rolloff
  monotonic with brightness; silence → NaN triple); `bark.py` extraction parity;
  masking suite still green.
- **Done when:** new + masking tests green.

### Chunk 2 — wire onto the report + compare
- **`report.py`**: `StemMetrics.timbre: TimbreMetrics | None = None` (additive,
  AUD-2N6K optional-field pattern); `_stem_to_dict` emits `"timbre"` (None → null,
  else 3 fields via `_finite_or_none`).
- **`analyze.py`**: `_measure_surface` (342) + `_measure_window` (853) populate
  `timbre=measure_timbre(...)`.
- **`compare.py`**: `_surface_deltas` adds timbre rows using a provisional
  `SIGNIFICANCE_TIMBRE` map (documented uncalibrated); null on either side → delta
  null / significant false (mirrors loudness).
- **Tests:** report serialization includes timbre; analyze end-to-end populates it;
  compare surfaces timbre deltas (incl. provisional-threshold + null-side cases).
  Update report/analyze/compare snapshot tests for the additive key.
- **Done when:** tests green; backlog item filed for threshold calibration.

### Chunk 3 — DR-3 energy correlate
- **`energy.py`**: add `SPECTRAL_CENTROID = "spectral_centroid"` constant.
- **`analyze.py` `_realize_energy`**: build `centroid_by_beat` from each section's
  `master.timbre.spectral_centroid_hz` (None-safe), add `SPECTRAL_CENTROID` to the
  `measured` dict.
- **Tests:** energy realization ranks the new correlate; update test_energy /
  test_analyze for the additive `correlate_rho` key. Section with no measurable
  centroid → excluded + named (existing W2 path).
- **Done when:** tests green; cumulative Critic via independent Agent passes.

## Status
- [x] Chunk 1 — DSP core (`bark.py` extraction + `timbre.py` + centroid dedup)
- [x] Chunk 2 — report + compare wiring (provisional timbre deltas)
- [x] Chunk 3 — DR-3 energy correlate (`spectral_centroid`)

**Context:** All three chunks built + green. Full configured suite (engine +
`hallucinote_mcp/tests`) **4435 passed / 2 skipped, exit 0** (baseline was 4419;
+16 new tests). `SCHEMA_VERSION` kept at "1" — the timbre field + the new
`spectral_centroid` correlate are purely additive (the differ degrades gracefully
against a pre-timbre baseline), matching the established no-bump-on-additive
convention. Calibration follow-up filed as **AUD-TIMBRE-CALIB**. Remaining:
cumulative Critic (independent Agent — worktree is gate-blind from the primary
session), then commit. No Live dependency; no operator-verification entry needed.
Worktree at `/Users/brookstalley/source/hallucinote-aud8t3k`.
