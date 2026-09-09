---
artifact: build-plan
version: 2
scope: aud-lenses
branch: feature/aud-sharpness-transient-lenses
---

# Build Plan — AUD: sharpness (shrillness) + drum-hit transient lenses

**Branch:** `feature/aud-sharpness-transient-lenses` (off `develop`)
**Type:** Feature (two read-side analysis lenses) · **Size:** Medium
**Critic mode:** cumulative (run via an independent Agent from the songs workspace session — the framework checkout is not this session's primary repo, so the Stop-hook gate is blind to it; same posture as `build-plan-aud-8t3k-timbre.md`)
**Origin:** dogfooding `alien` (hallucinote-songs, 2026-09-08). Two by-ear complaints — "the higher-pitched elements come across as a bit shrill" and "the kick is a thud, muffled, muddy with other instruments" — had no number in the MixReport to reason over, so both were measured with throw-away scripts against the captured stems. Those scripts are the spec.

## Why this plan is still live

Its chunks are complete and the work merged (#470), but on gitflow a
merged-but-unreleased plan stays in the live directory until its release ships,
and `develop` is ahead of `main` with no release cut. Archive it when that
release lands.

Reviewed and left live during the JANITOR-2026-09 sweep (2026-09-08), which
archived the six flat plans whose releases had already shipped.

## Confidence Check

- **Problem:** the MixReport's timbre lens (centroid / flatness / rolloff) cannot say whether a surface is *shrill* — a bright-but-pleasant pad and a piercing lead can share a centroid — and nothing in the report describes the *shape of a drum hit* (how fast it rises, how long it rings, whether its attack is sub weight, low-mid thud, or click). A "make it less shrill" or "make the kick punchier" edit could only be judged by ear.
- **Success:** (1) every surface's `timbre` object carries `sharpness_acum` — a psychoacoustic sharpness (von Bismarck / Zwicker weighting over Bark specific loudness) that goes UP for piercing content and is unmoved by level; `compare_to` diffs it. (2) each section carries `transients[]`: per part that has ≥ N low-band (kick-class) hits, the median rise time, 20 dB decay time, and the attack-window band balance (sub / low / low-mid / click), plus the click-vs-sub and low-vs-sub differences. A "sharpen the kick" edit moves `rise_ms` down and `click_minus_sub_db` up; a "de-shrill" edit moves `sharpness_acum` down. Both A/B-able across renders.
- **Out of scope:** grading (both lenses are neutral measurement, read against intent by `/mix-review`); per-pad separation of a kit stem via the DB's note times (a follow-up — the low-band onset picker isolates the kick class well enough for the question asked); calibrating sharpness to the DIN 45692 1-acum reference (provisional, like every timbre threshold).

## Requirements Confidence

**Level:** Medium

**Why:** the problem and the success criteria are concrete (two by-ear complaints turned into numbers on a real render, and the throw-away scripts that did it are the spec), but the numbers that make the lenses *decisive* are inferred, not calibrated.

**Open assumptions / unknowns:**
- [ASSUMPTION: the acum scale is relative — ordering and A/B deltas are the contract; the 0.10 acum significance floor is a first guess from one song | MED impact | resolved by a re-capture-jitter set, the AUD-TIMBRE-CALIB follow-up]
- [ASSUMPTION: `min_hits=4`, `peak_rel=0.25`, `min_sep_s=0.09` pick kick-class hits on a typical kit stem | MED impact | the reasoning is recorded beside each constant in `transients.py`; resolved by running the lens over a second song's kit and reading `transient_skips`]
- [ASSUMPTION: the transient significance floors (3 ms / 25 ms / 1.5 dB) separate a chain change from re-render jitter | LOW impact | one dogfood A/B, no jitter set; every row carries `provisional: true`]

**What would raise confidence:** a jitter calibration set (two renders of one unchanged song) for both families; a second song's kit through the transient lens.

## Design decisions

1. **Sharpness rides `measure_timbre`, not a new lens.** It is computed from the same silence-gated Bark band powers flatness already uses (one STFT, one band aggregation), and it is a timbre descriptor. `TimbreMetrics` gains a fourth field with a NaN default so hand-built fixtures and pre-sharpness baselines stay valid (AUD-2N6K optional-field pattern); the serializer emits it through `_finite_or_none`; `compare.py` adds a provisional 0.10 acum floor.
2. **Specific loudness by Stevens' law, not the full Zwicker loudness model.** N'(z) = P(z)^0.23 over the 24 Bark band powers. The full model (excitation spreading, thresholds in quiet) is not needed for a *relative* descriptor whose contract is ordering (piercing > bright > dark) and scale-invariance; the `0.11 · Σ N'·g(z)·z / Σ N'` form with the von Bismarck / Zwicker g(z) weighting is the standard sharpness estimator on top of any specific-loudness pattern. Absolute acum calibration is explicitly provisional.
3. **The transient lens keys on LOW-BAND onsets (40–150 Hz), not the spectral-flux front-end.** The question it answers is about kick-class hits, and a kit stem's hats/snares would swamp a broadband picker. Envelope = |Hilbert| of the band-passed slice, 5 ms smoothed; peaks ≥ 25 % of the window max (`_DEFAULT_PEAK_REL`), ≥ 90 ms apart (`_DEFAULT_MIN_SEP_S`, so 16ths up to 160 BPM count separately) and rising ≥ 50 % of the window max above their surrounding valley (`_DEFAULT_PROMINENCE_REL` — load-bearing, and paired with the separation: 90 ms alone admits tail lobes and snare leakage). Rise = 10→90 % of the low envelope on the hit's final approach to the peak (both thresholds scanned BACK from the peak — see Chunk 03); T20 = time for the low envelope to fall 20 dB; the attack window = 30 ms from the 10 % point, extended when needed to reach 15 ms past the peak. Medians across hits. *(Constants corrected here after Critic round 4 found this paragraph describing an earlier draft: it had said "≥ 200 ms apart", named no prominence floor, and omitted the peak-coverage extension.)*
4. **Wired per section behind `analyze_transients`,** gated (like timing) on declared sections by the server handler; it shares the window slices and needs no `stem_gains` (band *differences* and times are level-blind; the absolute dBFS levels are reported as-is, pre-fader, and named so).

## Chunks

### Chunk 01: sharpness on the timbre lens
- `audio/timbre.py`: `_band_sharpness(band_power) -> [n_frames]`; `measure_timbre` returns the median; `_SILENT` gains the fourth NaN.
- `audio/report.py`: `TimbreMetrics.sharpness_acum: float = nan`; `_stem_to_dict` emits it.
- `audio/compare.py`: `SIGNIFICANCE_TIMBRE["sharpness_acum"] = 0.10` (provisional).
- Tests: 5 kHz tone > 1 kHz > 200 Hz; white noise > 1 kHz tone; scale-invariant; NaN on silence; report round-trip; compare count 18 → 20.
- **Done when:** timbre / report / compare / analyze suites green.

### Chunk 02: transient lens
- `audio/transients.py` (new): `analyze_transients_window(stem_segments, sample_rate, *, min_hits, ...) -> TransientWindowResult`.
- `audio/report.py`: `PartTransient` dataclass, `SectionMetrics.transients`, `_part_transient_to_dict`, section dict key `transients`.
- `audio/analyze.py`: `analyze_transients` flag → `_measure_sections` → per window.
- `hallucinote_mcp/.../server_side/analysis.py`: `analyze_transients=bool(sections)`.
- `skills/mix-review/SKILL.md`: document `sharpness_acum` and `transients`.
- Tests: a synthetic "punchy" kick (fast attack + click) vs a "thuddy" one (slow attack, no click) → rise ordering, click-vs-sub ordering, T20 ordering; a part with too few low hits is omitted; end-to-end `analyze_mix(analyze_transients=True)` populates + serializes.
- **Done when:** suites green; cumulative Critic via independent Agent.

## Status
- [x] Chunk 01 — sharpness
- [x] Chunk 02 — transients
- [x] Critic round 1 (rev-20260908T132456Z-cec6448a): 3 blocking + 12 warnings addressed in one commit — a failure channel (`transient_skips`), censored estimators counted and excluded, per-section `section_deltas` in `compare_to` (so the skill's A/B claim is true), band names carrying their edges, constants justified, the two known-issues mechanisms corrected, plan frontmatter + this confidence block, test evidence recorded from this worktree.

**Context:** both chunks built; `tests/unit/audio` 344 passed against the
worktree source (PYTHONPATH-shadowed — the main checkout stays on the branch
the Remote Script was vendored from, see the songs workspace memory
`framework-checkout-fingerprint-trap`). Full suite run recorded in the commit.
`SCHEMA_VERSION` stays "1": both fields are additive (a pre-sharpness baseline
diffs to a null sharpness delta; `transients` is an empty list when disabled).
Critic rounds: rev-20260908T132456Z-cec6448a (3 blocking / 12 warning / 12 note) → fixes in 53b0d05 → rev-20260908T141447Z-4f0c1b2a (all resolved, 1 new blocking) → c785301 → rev-20260908T143223Z-ffb4b53e (clean). Six demoted observations accepted as-is: the `### Chunk N —` heading shape in nine older plans is other work's record; `section_deltas` covers timbre + transients only (timing / cross-rhythm / phasing / polymeter stay per-section-undiffed — a follow-up if a by-ear A/B ever needs them); no reachable off-switch for the lens (it mirrors the other three per-section lenses); `all_hits_censored` is near-unreachable and kept as the honest terminal branch; "both lists empty = lens off" is also true over zero stems; the pre-ship field rename crosses no schema bump. Remaining: merge PR #470 to `develop`.

### Chunk 03: the rise estimator's bimodality (dogfood finding, post-#470-open)

Found by using the lens on alien: `rise_ms` read **42 ms in verse 1 and ~16 ms in
eight other sections** off the same kick sample, and the tenth (outro) read 43.6.
Not a slower kick — the estimator.

- **Mechanism.** This kick's 40–150 Hz envelope has two comparable lobes 31.8 ms
  apart (invariant across the song; the beater click leads the second lobe by
  ~50 ms, so the hit band never sees the real onset). `_part_transient` found the
  90 % point with `np.argmax(win >= 0.90 * pv)` — the FIRST crossing scanning
  forward from the search window's edge. First lobe ≥ 0.90 × peak → `i90` lands
  on lobe 1 → ~16 ms; first lobe < 0.90 × peak → `i90` skips to lobe 2 → ~44 ms.
  A 1 % change in one lobe's height moves the reported number by ~28 ms.
- **What tripped it.** A mix edit (−2 dB at 100–250 Hz on the kick's EQ, the drum
  bus Glue attack 1 → 10 ms) lowered every section's lobe-1/peak ratio by the
  same ~0.04. Verse 1 landed at 0.889 and the outro at 0.878 — the only two under
  0.90 — so exactly those two flipped. Verse 1's hits split 30 fast / 32 slow:
  the median was a coin toss.
- **Fix.** Measure the rise on the hit's FINAL approach to the peak: scan
  BACKWARD from the peak for the last sample under 90 %, then backward from there
  for the last under 10 %. An earlier lobe can no longer capture the crossing.
  Rise censoring is strictly more correct: it subsumes the old
  `win[0] >= 0.10 * pv` edge test. *(This bullet originally said the censoring
  semantics were "unchanged in kind (… `i10 = w0` for the attack window)" —
  round 4 found that `i10 = w0` fallback to be a second defect and removed it;
  see the round-4 block below. Corrected here rather than left to contradict
  it 20 lines apart.)*
- **Also documented, because the number invited an absolute reading.** `rise_ms`
  is a LOW-BAND, band-edge-dependent, relative number: the same alien hits read
  44 ms at 40–150 Hz, 49 ms at 30–200 Hz, 41 ms at 40–120 Hz and 15 ms at
  50–150 Hz. `/mix-review`'s field list now says compare it across renders and
  sections of the same kit, never across kits or against an absolute "punchy"
  threshold; the old gloss ("a punchy kick is a few ms, a soft thud tens") is
  gone, since it is what made 42 ms read as "the kick got worse".
- **Test.** `test_a_two_lobe_hit_does_not_read_bimodally_across_the_90_percent_line`
  sweeps a synthetic two-lobe kick's first lobe across the 0.90 line. Verified to
  FAIL on the old estimator with the flip in the assertion message
  (`[45.4, 45.6, 45.9, 15.7, 15.3, 14.8]`) and pass on the new one.
- **Done when:** suites green; Critic round 4 dispositioned.

**Critic round 4 (`rev-20260908T153427Z-da1764a1`, cumulative, 3 reviewers): 0 blocking, 8 warning, 7 note.** The estimator change itself was verified sound by the correctness reviewer (`i10_rel <= i90_rel` always, a negative rise unreachable, the empty-`below90` branch deterministically censoring, and the new censoring a strict subset of the old — so the commit's "subsumes the old edge test" claim holds). Fixed in one commit:

1. **`PartTransient`'s docstring still carried the absolute `rise_ms` gloss** the previous commit deleted from `/mix-review` — filed independently by all three reviewers, and the third carrier of a rule the learnings already warn drifts. The field definition is the home; it now carries the relative-reading rule and the band-edge dependence, and the skill points at the same rule.
2. **A censored rise silently redefined the attack window** (correctness W1, design W3): `i10 = w0` on the censored branch made that hit's attack window `[peak-60 ms, peak+15 ms]` — 75 ms, not the documented 30 — and its four band RMS values still entered the medians, pooling two window lengths 2.5× apart in a mix that varied with how many hits censored. Same defect class as the bimodal rise: a number produced by window geometry, not by the sound. A rise-censored hit is now attack-censored, so no band level is read over a window that could not be placed. This makes `all_hits_censored` reachable on real material (the plan had called it near-unreachable) — a part whose hits all ride the previous hit's tail is now a skip instead of four contaminated bands, which is what two existing fixtures turned out to be doing.
3. **The regression test's load-bearing property was implicit** (sustainability): the six `first_rel` values only straddle `0.90 × peak` because of the fixture's decay, lobe spacing, band and smoothing, none of which it pinned — move any and all six land on one side, passing green over a forward-scanning regression. It now asserts the straddle directly.
4. **`_section_deltas` iterated stems only** (correctness W2), so the per-section MASTER — the whole-mix number a "de-shrill chorus 3" edit is actually judged on, and the one the alien turn reported — and the returns had no A/B row at all. Now every surface the window measured, with tests for both and for a section carrying neither key.
5. **`significant_delta_count` did not see `section_deltas`** (correctness W3). Added as a SEPARATE `significant_section_delta_count` rather than folded in, so a many-sectioned song's routine churn cannot swamp the surface-level headline; zero there while the surface count is nonzero means the change did not land where it was made.
6. Skip-kind enumerations completed in both carriers (3 of 5 and 4 of 5 → the complete set), the `all_hits_censored` reason string corrected to name both causes, and the `ableton_analysis` cost model's per-section pass list updated now that transients is a fourth.
7. The reusable class recorded in `.prawduct/learnings.md` + `learnings-detail.md` (an estimator reporting the FIRST threshold crossing is bimodal on multi-lobe material), which is what round 4 asked for beyond the one-off patch.

**Accepted, not fixed:** the two `suite-total-claim` record-lint hits (the correctness reviewer explicitly wanted no edit); and the backlog reconciliation the sustainability reviewer could not run — `prawduct-hook backlog cache-query` exits 6 on a schema v7/v8 mismatch, which is a tooling gap outside this branch, and its silence is recorded here as a gap rather than a clean bill.

**Evidence (real material, shipped code, alien drum stem per section, ms):**

| render | intro | verse1 | pre1 | ch1 | verse2 | pre2 | ch2 | bridge | ch3 | outro |
|---|---|---|---|---|---|---|---|---|---|---|
| pre-fix, old estimator | 15.8 | **15.3** | 16.0 | 15.7 | 15.8 | 15.9 | 16.1 | 15.9 | 15.9 | 14.6 |
| final, old estimator | 15.7 | **41.8** | 15.8 | 16.3 | 16.7 | 15.8 | 16.9 | 15.9 | 16.8 | **43.6** |
| pre-fix, new estimator | 45.1 | 45.4 | 45.2 | 45.3 | 45.2 | 45.2 | 45.6 | 45.1 | 45.0 | 14.6 |
| final, new estimator | 43.8 | 43.7 | 44.2 | 43.8 | 44.0 | 44.2 | 44.6 | 44.1 | 44.4 | 43.6 |

The mix edit now reads as the uniform −1.3 ms it was, instead of two sections
teleporting. (The outro's pre-fix 14.6 is a REAL shape change between the two
renders — its lobe-1/peak went 0.231 → 0.878 while every other section moved
~0.04 — not an artifact, and out of scope here.)

Full suite after the fix: **5097 passed, 2 skipped**.
