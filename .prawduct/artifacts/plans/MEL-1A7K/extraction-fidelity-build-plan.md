# MEL-1A7K — melodic line-extraction fidelity (post-ship bugfix)

**Type:** bugfix · **Size:** medium · **Branch:** `fix/mel-line-extraction-fidelity`
**Parent:** MEL-1A7K (phases 2a+2b shipped; this is a prerequisite to the pending
by-ear calibration — phase 3). **Discovered:** 2026-06-13, while validating the
melody research/build before the listening-day calibration.

## Problem (observable)

The melody lens reduces a track's notes to a monophonic line before measuring
contour / intervals / ambitus / harmony-fit. The reducer only collapses notes whose
onsets coincide to within `_ONSET_EPS = 1e-6` beats and **never reads
`duration_beats`** — so it has no notion of a note still *sounding* when a lower note
begins. When the melody layer carries a **second voice at staggered onsets** (an
octave double struck a hair late, a harmony line, a backing vocal), those lower notes
are interleaved into the "monophonic" line, which **inflates leaps, balloons ambitus,
and scrambles contour**. The line-level facts the lens reports for those sections are
not faithful, so calibrating the pending by-ear thresholds against them would bake the
artifact in.

## Root cause (pinned, with evidence)

`_melodic_sequence` (`src/hallucinote/melody/lens.py:341`) sorts by `(onset, -pitch)`
and keeps every note with a distinct onset — a skyline that only de-dups *exact*-onset
stacks. The same exposure exists at a **second site**: `per_phrase_contours` /
`phrase_boundaries` (`segmentation.py`) read the **raw notes** (bypassing
`_melodic_sequence`), so LBDM per-phrase contour also sees the interleaved polyphony.

**Evidence — `05 Lead` read per section on the real `sun-zone-done` arrangement**
(render-free, via `melody_report()`):

| section | contour | step | ambitus | notes/onsets | verdict |
|---|---|---|---|---|---|
| 1 reggae | level | 0.155 | 17 | 83/83 | clean mono — faithful |
| 2 metal | level | 0.50 | 12 | 72/72 | clean mono — faithful |
| 3 reggae | level | 0.157 | 17 | 82/82 | clean mono — faithful |
| 4 metal (climax) | level | 0.50 | 12 | 144/72 | exact-onset octave-double → top voice kept, step preserved (already correct) |
| 5 (back half) | ascending | 0.318 | **24** | **100/91** | staggered 2nd voice interleaved → ambitus 2 octaves |
| 6 (back half) | ascending | 0.353 | **24** | **40/39** | staggered 2nd voice interleaved |
| 7 (back half) | level | 0.558 | 12 | **144/108** | partial interleave (step inflated) |
| 8 outro | ascending | 0.317 | 24 | 46/46 | clean mono (genuine 2-octave augmented line) — faithful |

### ⚠️ CORRECTION (mid-build, 2026-06-13) — the main-path artifact was MISDIAGNOSED

Splitting the section-level overlaps into **containment** (a higher note fully covers
this one → genuine sustained-over voice) vs **legato tail** (a higher note's tail merely
laps this onset → monophonic articulation) overturned the table's reading of sections
5/6/8:

- The "ambitus 24" back-half sections (break, outro) are **genuinely wide monophonic
  legato lines**, NOT an interleaved second voice — their overlaps are 100% legato tail.
  Reading `notes > onsets` as "a second voice is present" was wrong: it only means some
  **exact-onset** doubles were collapsed (which the shipped code already did).
- Every octave-double in this song (chorus2, development, integration) is struck at the
  **exact** onset, so the shipped exact-onset rule already handled the main-path read.
- A duration-aware **containment** reducer is therefore a **verified no-op on this song's
  main-path readings** (contour / step / ambitus / harmony are byte-identical to ship).
- My first attempt (skyline = "mask any note under a still-sounding higher note") was
  **wrong**: it masked legato tails, gutting the descending reggae line (verse1 onsets
  83→66). Containment is the correct, conservative rule.

**The one REAL current-song bug the change fixes** is the segmentation raw-notes bypass:
`per_phrase_contours` read the **raw** notes, so on the octave-doubled sections it
segmented over BOTH interleaved octaves → nonsense phrase counts (**chorus2 72**,
development 25, integration 41 phantom phrases vs 17 / 21 / 15 from the reduced line).
Routing segmentation through the single reduced line fixes that.

**Net:** the dramatic "83% leaps / ambitus 24 = artifact" framing that motivated this
item was largely a misread — the reggae hook is genuinely third-based, the back-half
width is genuine, the doubles were already handled on the main path. The change is (a) a
real fix to LBDM per-phrase contour on octave-doubled sections, (b) a generalization of
exact-onset collapse to **containment** that is a no-op now but robust to STAGGERED
doubles / backing vocals (the user's stated future case), and (c) a single duration-aware
extractor feeding all three reads. Zero regression.

---

*(Original — now-corrected — hypothesis, kept for the record:)* The smoking gun was
read as sections 5/6 having a staggered second voice (ambitus 24). Section 4 does prove
the exact-onset octave-double is handled (top voice, step 0.50) — the fix preserves that.
The front-half "reggae reads 83% leaps" is **not** an artifact: genuinely third-based.

## Confidence check

1. **Problem:** the line reducer interleaves a staggered second voice into the
   "monophonic" line, producing unfaithful contour/interval/ambitus on polyphonic
   melody sections (5/6/7).
2. **Success:** the lens extracts a faithful top-voice line — sections 5/6/7 read a
   single-voice line (ambitus back toward the hook's true range) while clean-mono
   sections (1–3, 8) and the exact-onset double (4) read **unchanged**.
3. **Out of scope:** the by-ear threshold calibration (phase 3, still user-owned); the
   interval-size proxy granularity (separate, see "Deferred"); any change to the
   public `MelodyReport` schema; counterpoint / vertical-consonance analysis (ARR-4V7P).

## Decision-record — DR-1: top-voice skyline extraction (option A)

**Decided (user, 2026-06-13): A — extract a true top-voice line via skyline-over-time**,
not "detect polyphony and refuse." Rationale + the user's refinement: *"there may be
backing vocals or other reasons to allow brief polyphony to be included in melody"* —
so the melody is the **top line**, and brief/incidental polyphony (octave doubles,
backing vocals, a high harmony) folds into it rather than being flagged out. A
low-confidence *degrade* is kept only as a conservative backstop for **sustained, dense**
genuine multi-voice texture (the §6 scope boundary — "degrades gracefully to the raw
note floor for dense polyphony"), tuned so backing vocals never trip it.

Alternatives considered: **(B) detect-and-degrade-to-low-confidence** — rejected as
primary because it throws away a readable top line and would flag backing-vocal sections
out; kept only as the conservative backstop. **(C) voice-continuity (nearest-pitch)
reduction** — rejected: more complex, and it could *mask genuine leaps* (the metal hook's
real octave drop), violating the acceptance test.

**Skyline-over-time algorithm.** A note is part of the melodic line iff, at its onset,
no other *currently-sounding* note has a strictly higher pitch (a higher note still
ringing **masks** it). Every note (kept or masked) contributes its `[start, start+dur)`
sounding interval, so masking reflects acoustic presence. Within an exact-onset stack
the highest pitch is the melody note (preserves section-4 behavior). A note whose
predecessor top voice has already ended is exposed and kept (preserves genuine melodic
motion). This is the single canonical extractor; **both** the lens body and segmentation
consume its output, so the per-phrase contour sees the same clean line.

## Chunks

- [ ] **Chunk 1 — skyline-over-time extractor + route both consumers through it.**
  - Replace `_melodic_sequence`'s exact-onset skyline with a duration-aware
    skyline-over-time (reads `duration_beats`; masks a note under a still-sounding
    higher note). Keep its `list[(start, pitch)]` return for the lens body + harmony-fit.
  - Make the extractor the single source of the monophonic line: `phrase_boundaries`
    / `per_phrase_contours` consume the reduced line (with durations) instead of raw
    notes, so LBDM per-phrase contour reads the same clean line.
  - **No confidence backstop in Chunk 1 (mid-build correction, 2026-06-13).** The plan
    first proposed lowering `confidence` by the fraction of notes dropped as masked.
    That is *wrong*: an exact-onset octave-double drops 50% of notes as masked yet is
    perfectly readable (section 4), so a masked-count signal would penalize exactly the
    doublings/backing-vocals DR-1 says to *include*. Skyline already "degrades gracefully
    to the raw note floor" by yielding the top line, so no flag is needed for correctness.
    A dense-sustained-independent-voices confidence signal (a different measure, not a
    masked count) is deferred until a real song surfaces a misleading top-voice read —
    discovered-from-friction, not speculative.
  - **Tests (contracts):** the real-data acceptance test below; synthetic fixtures —
    (a) sequential mono line unchanged, (b) exact-onset octave-double → top voice,
    (c) staggered second voice below a held melody → masked/dropped, (d) brief higher
    harmony → folded into the top line, (e) genuine descent (top ends, lower exposed)
    → kept, (f) per-phrase contour reads the reduced line (segmentation routed through
    the extractor). Plus the existing ~67 melody tests stay green (a behavioral-
    preservation guard for clean-mono lines).

- [ ] **Chunk 2 (CONDITIONAL — only if DR-2 says so) — interval-size granularity.**
  Even on faithful lines the step/leap binary (≤2 step) reports a third-based line
  identically to an octave-leaping one. A graded small-interval reading (e.g. a
  conjunct fraction at a 3rd cut, or interval-size distribution) would separate them.
  **DR-2 (deferred):** decide whether the profile `step_appetite` bands already absorb
  this (likely) before adding a field. Do NOT build speculatively.

## Acceptance test (baked from real data — CORRECTED)

After Chunk 1, `melody_report()` over `sun-zone-done`:
- **Main-path reads (contour / step / ambitus / harmony) are byte-identical to ship for
  ALL 8 sections** — containment ≡ the shipped exact-onset rule on this song (verified).
  This is the no-regression guarantee, including the genuinely-wide legato lines
  (break/outro stay ambitus 24) and the descending reggae legato (verse1 stays 83/83).
- **LBDM per-phrase contour is FIXED** on the three exact-onset-doubled sections, which
  the shipped code segmented over raw interleaved octaves: chorus2 72→17, development
  25→21, integration 41→15 phrases (the reduced line, not the raw double).
- New unit fixtures pin the *general* behavior the song doesn't exercise: staggered
  sustained-over voice → masked; legato descending line → kept; brief higher harmony →
  followed; genuine descent → kept.
- The full suite stays green.

## Status

- [x] Chunk 1 — containment extractor (`_extract_melodic_line`) + single-source routing
  (lens body, harmony-fit, LBDM segmentation all consume the one reduced line) +
  duration-awareness. 97 melody tests green (+7 new). **CORRECTION recorded:** main-path
  artifact was misdiagnosed; real fix is the segmentation over-segmentation on doubled
  sections; containment is a no-op on this song's main-path reads + forward-robustness.
- [x] Verify: melody suite green; `melody_report()` main-path reads byte-identical to ship;
  per-phrase contour fixed on chorus2/development/integration (72/25/41 → 17/21/15).
- [ ] **DECISION PENDING (user):** keep the containment generalization (forward-robust to
  staggered doubles / backing vocals, no-op now) + segmentation fix, OR trim to only the
  segmentation-bypass fix. See message.
- [ ] Full suite (all 2855) green
- [ ] Critic (chunk) — held until scope confirmed
- [ ] Backlog + change-log entry

**Context (handoff):** branch `fix/mel-line-extraction-fidelity`. The investigation
falsified the premise (no main-path extraction artifact on sun-zone-done; the back-half
width is genuine). The kept change fixes a real latent segmentation bug + adds no-op
forward-robustness. Awaiting user keep/trim call before Critic + PR.

**Context (handoff):** root cause pinned with real-arrangement evidence; DR-1 = option A
(skyline top-voice, brief polyphony folded in) locked by user. Engine resolves to the dev
repo (editable), so `melody_report()` runs render-free against the sibling
`hallucinote-songs` checkout for the acceptance test.
