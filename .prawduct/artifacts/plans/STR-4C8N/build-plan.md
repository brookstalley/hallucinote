---
artifact: build-plan
version: 1
scope: str-4c8n
depends_on:
  - artifact: masking-analyzer-goals
  - artifact: intent-architecture
  - artifact: api-contract
governed_by:
  - artifact: masking-analyzer-goals
    dispositions:
      - "measurement is neutral; the report never grades → conforms (this plan adds metrics + a declared-vs-measured join to the report, and puts ALL grading in the /mix-review skill)"
      - "a measurement must never become a verdict → conforms, and MORE strictly than first written: this lens emits no findings at all. The original wording claimed findings at severity `info`; it ships none, so the skill is the only place any judgement happens."
  - artifact: intent-architecture
    dispositions:
      - "declared intent enters analysis through the MCP handler, not by analyze.py reaching into the DB → conforms (A3 mirrors `declared_reverb_sends`)"
  - artifact: project-preferences
    dispositions:
      - "every new preference gets an enforcement mechanism → n/a (this plan adds no preference)"
      - "numbers that drift are not restated in prose → conforms"
Critic mode: cumulative-final
last_validated: 2026-08-10
---

## Requirements Confidence

**Level:** High

**Why:** The motivating defect is measured, reproduced, and fixed by hand already
(`songs/the-argument/decisions/07-flanger-stereo-mod-phase.md`), so the metric's
value is demonstrated rather than assumed. The two failure modes each have a
worked example with numbers from a real render. The insertion points are read,
not guessed: `audio/automation.py` `_verify_timbre` is the false-positive site,
`audio/analyze.py` builds the report, and `analyze.py`'s DB-agnostic contract
(its own module docstring) dictates how declared intent arrives.

**Open assumptions / unknowns:**

- [ASSUMPTION: a Pearson L/R correlation + mono-sum loss pair is sufficient
  evidence for both failure modes | MED impact | falsifiable at A1] Broadband
  correlation is blunt: a part wide in the highs and mono in the lows averages to
  something unremarkable. Per-band correlation is the obvious extension and is
  deliberately NOT in this plan — if A1's numbers on `the-argument` fail to
  separate the known no-op (Drone) from the known over-width (Brass), that
  assumption is falsified and per-band moves in scope.
- [ASSUMPTION: accepting EITHER a timbre shift or an image shift is the right fix
  for the false positives, rather than selecting a probe by device class | LOW
  impact | decided, with reasoning] Device class is not available at this layer
  and threading it would cross the DB-agnostic boundary for no gain. "The declared
  change produced a measurable effect in some probed dimension" is the honest
  claim and is strictly more correct than today's timbre-only test.
- [ASSUMPTION: `mono_sum_loss_db` thresholds stay OUT of the report | LOW impact]
  The report carries numbers; the skill decides what is worth surfacing. This is
  the masking precedent (no severity number in the report) and is load-bearing for
  "never a verdict."

**What would raise confidence:** A1's measurements on the three known cases
(Drone no-op, Brass over-width, guitars fixed) reproducing the hand-computed
numbers. That is A1's acceptance criterion, so nothing needs deciding first.

## Status

- [x] Chunk A1: Per-stem stereo metrics in the MixReport
- [x] Chunk A2: Dual-probe device-parameter verification (timbre OR image)
- [x] Chunk A3: Declared-vs-measured width join + `/mix-review` reading guidance

Context: Plan authored 2026-08-10 on `feat/str-4c8n-stereo-lens` off `develop`.
Backlog item **STR-4C8N**; the sibling altitude question against **STR-9P4M**
(aesthetic stereo grading) is recorded in both items and is NOT settled by this
plan — this one catches deliverability and no-op failures, not taste.

Driven by a real incident on `songs/the-argument`, which is also the acceptance
fixture: a chorus flanger declared to give a mono guitar chain stereo, whose
`Dry/Wet` automation was verified recorded AND playing, while the stem measured
`L−R = −180 dB` (bit-exact mono). Cause was `Mod Phase 0.0°`. Every symbolic and
API-level check passed; only rendered-audio measurement caught it.

### Disposition: the QLT-3D8R analyzer-freeze — RECORDED, NOT RESOLVED

**QLT-3D8R** carries a dated, user-owned hold from the 2026-07-02 audit: *hold
the listening day before shipping another analyzer*, target on/before
2026-08-01, and "until held, the standing guidance is analyzer-freeze: no new
analysis lenses." The listening day has not been held, the date has passed, and
this plan ships a new analysis lens plus two uncalibrated thresholds. Nothing
asked the owner. That is the gap being recorded here; recording it is not the
same as clearing it.

**The agent's read, offered for the owner to accept or overrule.** The freeze's
stated rationale is *unvalidated measurement compounding* — coaching that is
confidently miscalibrated because nobody checked it by ear. This lens is a poor
fit for that rationale in one specific way: it emits **no findings and no
grades**, and its two primary numbers (`correlation`, `mono_sum_loss_db`) are
determinate physics with no threshold in them at all — a bit-exact-mono stem
reads `+1.0 / 0.00 dB` on any ear. The freeze bites hardest on *aesthetic*
lenses whose thresholds encode taste, which is precisely the sibling work this
plan pushes to **STR-9P4M**.

**Where the freeze does bite, and is not waived.** Two thresholds here ARE
uncalibrated first guesses: `CORRELATION_ABS_THRESHOLD` (the image probe's
realized/not floor) and `SIGNIFICANCE_STEREO` (the A/B floors, which ship
`provisional: true` for exactly this reason). Both are ear-calibration
questions and belong on the listening day's list.

**Owner action, if the read is wrong:** the honest remedies are to revert the
lens, or to hold the day before the release cut. The agent has not assumed
either. Reconcile QLT-3D8R's freeze wording after ruling, so its scope reads
true afterwards.

## Chunk A1: Per-stem stereo metrics in the MixReport

**Delivers:** a `stereo` block per stem (and per section, matching `masking`'s
shape) carrying `correlation` (Pearson L/R over the window) and
`mono_sum_loss_db` (RMS of the mono sum minus RMS of the stereo signal, in dB).
Mono-native surfaces report `correlation: 1.0`, `mono_sum_loss_db: 0.0` rather
than null — bit-exact mono is a measurement, not a gap.

**Where:** a new `src/hallucinote/audio/stereo.py` (mirrors `timbre.py` /
`density.py` — one metric family per module), consumed by `audio/analyze.py`
alongside `measure_timbre`. Report schema in `audio/report.py`. Also
`audio/compare.py`: a third `_surface_deltas` family (`SIGNIFICANCE_STEREO`)
beside loudness and timbre, because an A/B that enumerates families by name is
otherwise blind to the exact change this lens exists to expose — reducing Brass
from −3.84 dB to −2.86 dB of mono loss showed as no delta at all.

Those A/B floors ship `provisional: true`, and the debt is **the same one
AUD-TIMBRE-CALIB already tracks** for the timbre floors it mirrors: no
render-jitter calibration set exists for either family. Clearing `provisional`
for stereo means adding correlation and `mono_sum_loss_db` to that item's
re-capture-jitter sweep — recorded there rather than as a second item, since one
sweep answers both. `CORRELATION_ABS_THRESHOLD` (the image probe's floor, which
`compare.py` imports rather than restates) is the third number on that list.

**Acceptance criteria:**
- `the-argument`'s render reproduces the hand-computed values within rounding:
  Rhythm Gtr ≈ +0.985 / −0.03 dB, Drone ≈ +0.898 / −0.23 dB, Bass exactly
  +1.0 / 0.00 dB. Brass ≈ −0.174 / −3.84 dB **on the capture taken before its
  width was reduced 155 % → 125 %** — measure that one against
  `captures/20260810T153308Z`, not the newest capture, or the criterion reads as
  a failure when it is actually the mix decision that followed it.
  *(All five verified 2026-08-10; Brass on the current capture reads
  +0.035 / −2.86 dB, which is the reduction working.)*
- A synthetic bit-exact-mono stem reports `+1.0` / `0.00 dB` and does not divide
  by zero; a synthetic anti-phase stem reports ≈ `−1.0` and a large loss.
- Whole-stem and per-section values are both present; a section too short to
  measure is a `skipped_analyses` entry, never a silent absence.
- The report still validates against its schema version and old reports still
  load (additive field only).

**Done when:** the above pass, `audio/report.py`'s field documentation describes
both metrics in the same voice as the existing blocks, and the suite is green.

## Chunk A2: Dual-probe device-parameter verification

**Delivers:** `_verify_timbre` in `audio/automation.py` becomes a two-probe test.
A `device_parameter` change is `realized` when the centroid moved past its
existing relative threshold **OR** the stereo correlation moved by more than its
own threshold across the same before/after windows. The note names which probe
fired, so a reader can tell a timbre move from an image move.

**Why (do not lose this):** a flanger is a comb filter and notches roughly
symmetrically, so it barely moves the spectral centroid however wet it gets.
Today that yields `no audible timbre shift (2244→2219 Hz, 1% < 12%)` and a
`warning` on automation that provably DID land — three such false warnings on
`the-argument` alone. Centroid is the wrong probe for an image effect.

**Acceptance criteria:**

> **Criterion corrected mid-build, 2026-08-10.** It originally read "the three
> `Dry/Wet` findings stop being reported as not-realized." That was written from
> the finding COUNT and assumed all of them were false. They are not: each arc has
> three change points (beats 265, 288, 290), and the beat-288 move is
> `0.38 → 0.42` — a 4 % Dry/Wet change that is genuinely inaudible, so
> "not realized" there is the lens being RIGHT. A criterion that demanded those
> flip would have been satisfied only by making the probe lie.

- Findings on `the-argument`'s current render drop from 9 to 5, and per-breakpoint
  **6 of the 9 `Dry/Wet` verifications realize** (verified 2026-08-10: track:6 all
  three; track:4 at 265 via image +0.09 and at 290 via timbre +22 %; track:3 at 290
  via image +0.07).
- Every realization note names the probe that carried it, so a reader can tell an
  image move from a timbre move.
- The beat-288 verifications (`0.38 → 0.42`) correctly stay not-realized — an
  inaudible declared move must keep reporting as inaudible.
- A genuinely unrealized device-parameter change (synthetic: identical before and
  after windows) is STILL reported as not realized — the fix must not become a
  rubber stamp. This is the regression test that matters most.
- A pre-fix-style capture (wet flanger, `Mod Phase 0°`, no image change AND no
  centroid change) still reports not-realized, which is the true positive the old
  code got right for the wrong reason.
- `measurable=false` paths (quiet windows) are untouched.

**Done when:** the above pass, and the false-positive count on `the-argument`
drops from 9 findings to the ones that survive on their merits.

**Residual, discovered at A2 and deliberately NOT fixed here:** `track:3` at beat
265 still reads not-realized, and that one IS an artifact. The arc ramps 0 → 0.38
across beats 261–265, but the before-window is clamped to
`max(prev_breakpoint, beat − _WINDOW_BEATS)` = 263 — already halfway up the ramp —
so both windows contain a partly-wet flanger and the delta collapses. This is
**window placement on a smooth ramp**, a different defect from probe choice, and
it affects every target kind rather than just device parameters. Fixing it means
changing window semantics for all of them (sample where the OLD value is actually
in effect, i.e. around the previous breakpoint, rather than a fixed span back from
this one). That is a bigger, riskier change than A2's scope and belongs in its own
item — filed rather than smuggled in here.

## Chunk A3: Declared-vs-measured width join + `/mix-review` guidance

**Delivers:** two things, split by layer.

*Report side:* the MCP handler
(`hallucinote_mcp/src/hallucinote_mcp/server_side/analysis.py`) reads
declared width-type device params from the song DB and passes them into
`analyze_mix` as `declared_width_controls`, mirroring `declared_reverb_sends`
exactly — `analyze.py` stays DB-agnostic. The report gains a neutral
`width_realizations` list: declared control, its declared value, the measured
`mono_sum_loss_db` on that surface, and nothing else. No severity, no verdict.

*Skill side:* `/mix-review`'s MEASURE section gains a `stereo` /
`width_realization` entry in the same voice as the others, and INTERPRET gains
the gating rule: surface ONLY on contradiction with declared intent, in dB not
correlation, element-aware. The canonical example is the motivating incident.

**Acceptance criteria:**
- A declared width control above unity with a measured loss near zero is
  represented in the report as evidence a reader can act on (the Drone case:
  165 % declared, −0.23 dB measured).
- A declared width control with a large measured loss is likewise represented
  (the Brass case as it was: 155 % declared, −3.84 dB measured).
- `analyze_mix` gains no DB import; the join happens in the handler.
- When nothing declares a width control, a `width_realization`-kind
  `skipped_analyses` entry is recorded, not silently absent — and it says
  "none RECOGNISED", never "none authored", because recognition is a closed
  name set over top-level devices only.
- `/mix-review`'s SKILL.md states the dB-not-correlation rule and the
  only-on-contradiction gate, and carries the caveat that broadband correlation
  is blunt for a part that is wide in one band and mono in another.

**Done when:** the above pass; the skill text is consistent with what the report
actually emits (no described-but-unbuilt field); suite green.

## Out of scope (deliberate)

- **Aesthetic stereo grading** — whether the image is *good*. That is STR-9P4M,
  a different judgment class, and the altitude question between the two items is
  recorded in both and left open.
- **Per-band correlation.** See A1's first assumption — it enters scope only if
  broadband fails to separate the three known cases.
- **Auto-applying any fix.** The mix skills already refuse this; nothing here
  changes it.
- **Panning / imaging analysis** beyond correlation + mono-sum loss.
