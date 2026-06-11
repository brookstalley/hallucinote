# AUD-3F8M — Build Plan (master-bus windowing for post-fader automation)

Item: `mixer_volume` / `mixer_pan` envelope verification via master-bus windowing
(audio-analysis, M/S, `stage: ready`; ranked next after the friction basket by the
2026-06-09 repo-wide review — post-fader verification is the hole exactly where mix
authorship lives under "sound design is composition"). One branch
(`feature/aud-3f8m-master-bus-automation`), one PR into `develop`.

## Requirements Confidence: **Medium**

- **Problem (one sentence):** Declared `mixer_volume`/`mixer_pan` envelopes are
  post-fader, invisible to the pre-fader stem tap, so
  `verify_envelope_realization` reports them `measurable=False` instead of verifying
  the swell/pan move actually happened.
- **Success (one sentence):** A declared `mixer_volume` swell (and `mixer_pan` move) on
  a real capture reports `measurable=True` + a `realized` verdict derived from
  windowing the master (post-fader sum) around the breakpoint, with an honest
  inconclusive path when other sources confound the master window.
- **Out of scope (one sentence):** A Live-side post-fader tap (capture pipeline change),
  per-stem post-fader *rendering*, and any change to how envelopes are authored or
  pushed — this is read-side analysis only.

**Why Medium, not High:** the measurement basis (master window, mirroring the shipped
`send_level` RMS pattern) is solid, but the confound guard (when is the target stem's
contribution big enough for the master to speak?) and the pan metric are design choices
to be validated against real captures, not settled requirements.

**Open assumptions / unknowns:**

- `[ASSUMPTION: master-window RMS delta is attributable to the target stem only when the
  stem's predicted post-fader contribution (pre-fader stem RMS × live_fader_gain from
  audio/levels.py) is a sufficient share of master-window energy; below the threshold we
  report measurable=True + an inconclusive/not-realized-with-note verdict rather than a
  false verdict — threshold to be picked empirically in Chunk 01 against the
  sun-zone-done capture set | HIGH impact | user can veto the inconclusive semantics]`
- `[ASSUMPTION: mixer_pan metric = L−R balance shift (per-channel RMS dB difference) in
  the master window, direction-checked against the declared pan move, contribution-gated
  the same way | MED impact | user can override]`
- `[ASSUMPTION: the existing EnvelopeVerification record shape can carry the verdict
  (realized + note) without new fields; if a confidence/share field proves necessary it
  is additive, not a reshape | LOW impact | defer]`

**What would raise confidence:** the Chunk 01 spike step — measure contribution shares
on an existing sun-zone-done capture before freezing the threshold (~30 min, planned in).

## Status

- [x] Chunk 01: mixer_volume end-to-end via master windowing
- [x] Chunk 02: mixer_pan + report surfacing
Context: Chunk 01 done 2026-06-10. **Spike evidence (Done-when 1):** on the
sun-zone-done `v4-full-aligned` capture, pre-fader stem/master power ratios
span 0.0–3.3 across stems and 6 windows — a fixed share threshold is
meaningless, so the design predicts the expected master dB step per
breakpoint from the declared fader values (`levels.live_fader_gain`) + the
measured pre-fader stem power (uncorrelated power model), gates
measurability at 0.75 dB predicted, and requires direction + ≥0.3× predicted
magnitude (lenient for the house master limiter). **Real-capture run:** the
song's one declared mixer_volume envelope (Rhythm Gtr amp-coupled trim,
0.70→0.64 ≈ −1.1 dB stem-side) predicts only ±0.06–0.39 dB on the master —
all 12 change-points honestly gated as too-diluted, no false verdicts; the
detection path (real swells, e.g. 0.5→0.85) is pinned by synthetic tests.
**Explicit divergence from plan assumption 1 (governance checkpoint):** the
below-threshold gate reports `measurable=False` (the existing honest-skip
channel report consumers already understand), NOT the assumed
`measurable=True + inconclusive` — sub-threshold means the master genuinely
cannot speak, which IS unmeasurability; Honest Confidence favors the
existing channel over a new tri-state. Critic chunk findings resolved:
model-breakdown guard (negative predicted power → honest unmeasurable, not
a false NOT-realized), analyze-level mixer_volume end-to-end test, dead
`_POST_FADER_KINDS` removed. **Chunk 02 done 2026-06-10:** `_verify_mixer_pan`
(constant-power pan gains × static `stem_gain` from the snapshot mixer state,
threaded from `analyze_mix`'s existing `stem_gains`), `master_balance_db`
metric, same floor/breakdown/0.3× semantics. **Real-capture run:** the
sun-zone-done break pan sweep (±0.95) reports 4/4 measurable change-points
REALIZED on the master; the two static pan envelopes correctly carry 0
change-points. Critic final's blocking finding (contract-drift sweep: tool
description, collector docstring, mix-review skill, module comments) fixed
tree-wide; pan guard tests (quiet master, model breakdown) added;
`_VOLUME_REALIZED_FRACTION` renamed `_MIXER_REALIZED_FRACTION`. Remaining:
cumulative Critic vs develop + PR; backlog flips post-merge (AUD-3F8M shipped,
AUD-8H2M archived-note, MIX-3S7P stale "can't verify time-varying" line).
Pan-floor question flagged for QLT-3D8R listening day.

## Scaffolding

Existing project — no scaffold work. Tests in `tests/unit/audio/` (pytest, `audio`
marker for DSP-heavy tests, opt-out via HALLUCINOTE_SKIP_AUDIO=1). Verification beyond
tests: run `analyze_mix` against an on-disk sun-zone-done capture set (no Live needed —
pure read-side numpy); if no capture with a declared mixer swell exists on disk, the
real-capture signal is verified on the next render and flagged in the PR as pending.

---

## Chunk 01 — mixer_volume end-to-end (thin slice)

Route `_POST_FADER_KINDS` volume envelopes in
`src/hallucinote/audio/automation.py::verify_envelope_realization` to a new
master-windowed measurement instead of the `measurable=False` early-return: window the
master before/after the breakpoint (mirror the shipped `send_level` RMS-dB pattern and
its `_WINDOW_BEATS`/`_mono_window` helpers), direction-check against the declared
swell, and gate on the target stem's predicted post-fader contribution share (per plan
assumption 1 — spike against a real capture before freezing the threshold). Plumb the
master surface through: `_run_automation_verifications`
(`src/hallucinote/audio/analyze.py`) passes `capture.master`
(`src/hallucinote/audio/io.py::CaptureSet`) into the verifier.

The existing tests pinning `mixer_volume → measurable=False` encode the *old
limitation*, which this item explicitly supersedes — updating them to the new contract
is a requirement change being implemented, not a weakened test; say so in the commit.

- **Type:** code
- **Deliverables:** `src/hallucinote/audio/automation.py`,
  `src/hallucinote/audio/analyze.py` (master plumb-through); updated + new tests in
  `tests/unit/audio/test_automation.py` and `tests/unit/audio/test_analyze.py`.
- **Tests:** synthetic-capture units — a stem with a declared fader swell whose master
  sum shows the level step → `measurable=True, realized=True`; declared swell absent
  from master → `realized=False`; target stem far below contribution threshold →
  inconclusive verdict + note (never a false `realized`); existing timbre/send
  verifications unchanged.
- **Acceptance criteria:** the backlog item's verifiable signal for volume — a declared
  `mixer_volume` swell on a capture reports `measurable=True` + `realized` from
  master-bus windowing, not the post-fader skip; the old teaching note is gone.
- **Done when:**
  1. Contribution-share spike on an on-disk capture recorded in the chunk notes
     (threshold choice + evidence)
  2. Acceptance criteria met and tests pass
  3. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  4. Committed and chunk marked `[x]` in Status

## Chunk 02 — mixer_pan + report surfacing

Add the pan path (L−R balance shift per plan assumption 2, same windowing + gating),
and surface the new verdicts wherever automation verifications render
(`src/hallucinote/audio/report.py` — `EnvelopeVerification` notes/docs, and the
`automation_not_realized` finding path now reachable for mixer kinds). Update
`audio/levels.py` module docs if the pre-fader framing sentence now overstates the
limitation.

- **Type:** cumulative-final
- **Deliverables:** `src/hallucinote/audio/automation.py`,
  `src/hallucinote/audio/report.py`; tests in `tests/unit/audio/`.
- **Tests:** pan-move synthetic units (realized / not realized / inconclusive);
  a MixReport-level test that a non-realized mixer envelope produces the
  `automation_not_realized` finding.
- **Acceptance criteria:** the full verifiable signal — both mixer kinds report
  `measurable=True` with windowed verdicts; report findings fire for mixer kinds.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: final) and blocking findings resolved
  3. `/prawduct:critic cumulative` against `develop...HEAD` clean — the `/prawduct:pr
     create` gate (base: develop)
  4. Committed, chunk marked `[x]` in Status; backlog pass via `/prawduct:backlog`:
     AUD-3F8M → shipped on merge; drop a note on AUD-8H2M (archived parent) if its text
     references the post-fader gap as open

## Early Feedback Milestone

**Milestone chunk:** 01 — re-running `analyze_mix` on an existing capture shows mixer
swells verified (or honestly inconclusive) instead of skipped.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic passes; one PR into `develop`
after Chunk 02's final + cumulative reviews pass (`/prawduct:pr`, base develop).

- After Chunk 01: review the inconclusive-verdict semantics against "Honest Confidence"
  before pan builds on the same gate.
