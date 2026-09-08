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
3. **The transient lens keys on LOW-BAND onsets (40–150 Hz), not the spectral-flux front-end.** The question it answers is about kick-class hits, and a kit stem's hats/snares would swamp a broadband picker. Envelope = |Hilbert| of the band-passed slice, 5 ms smoothed; peaks ≥ 25 % of the window max, ≥ 200 ms apart. Rise = 10→90 % of the low envelope; T20 = time for the low envelope to fall 20 dB; the attack window = first 30 ms after the 10 % point, over which four band RMS levels are read. Medians across hits.
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
Critic rounds: rev-20260908T132456Z-cec6448a (3 blocking / 12 warning / 12 note) → fixes in 53b0d05 → rev-20260908T141447Z-4f0c1b2a (all resolved, 1 new blocking) → c785301 → rev-20260908T143223Z-ffb4b53e (clean). Six demoted observations accepted as-is: the `### Chunk N —` heading shape in nine older plans is other work's record; `section_deltas` covers timbre + transients only (timing / cross-rhythm / phasing / polymeter stay per-section-undiffed — a follow-up if a by-ear A/B ever needs them); no reachable off-switch for the lens (it mirrors the other three per-section lenses); `all_hits_censored` is near-unreachable and kept as the honest terminal branch; "both lists empty = lens off" is also true over zero stems; the pre-ship field rename crosses no schema bump. Remaining: PR to `develop`.
