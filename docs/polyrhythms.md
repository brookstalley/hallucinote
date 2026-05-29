# Polyrhythm & cross-rhythm detection — design

Status: **C8a (single-part cross-rhythm) + C8b (two-part phasing) SHIPPED**
(`audio/cross_rhythm.py`, `audio/onsets.py`, `PartCrossRhythm`/`Phasing` on
`SectionMetrics`, `/mix-review` consumer). C8c (polymeter cycle-length +
additive grouping) is **deferred** — a probe showed it needs an accent /
onset-strength feature the current front-end doesn't carry; the design fork is
recorded in `.prawduct/backlog.md`. Masking chunk **C8**, the read-side sibling
of the timing analyzer (`audio/timing.py`, C7).

This document records what we built to validate the design (a throwaway harness
over a synthetic genre corpus), the approach that won and why, what it's great
at, where it breaks, and how it slots into Hallucinote. The numbers quoted below
are from that prototype run — they're reproducible, not aspirational.

---

## 1. The problem C7 left open

The timing analyzer (`PartTiming`) measures a part's onset deviation **from a
single straight grid** (16th subdivisions of the known beat): push/drag (signed
drift), tightness (drift stdev), and swing (median off-beat-8th phase). When a
part plays *against* the grid — a 3-over-2 hemiola, a 4-against-3, a quintuplet
run — C7 honestly reports **low confidence / high stdev** ("this isn't on the
straight grid") but cannot say *what it is on*. C8 closes that: it names the
relationship.

Four distinct phenomena hide under "polyrhythm," and conflating them is the main
way naive designs fail. We keep them separate:

| phenomenon | what it is | who owns it |
|---|---|---|
| **Cross-rhythm / tuplet** | one part subdivides the beat against the meter (3:2, 4:3, 5:4, quintuplets) | **C8** (this doc) |
| **Phasing** | two identical parts at fractionally different tempi, drifting (Reich) | **C8** two-part pass |
| **Polymeter** | parts loop different cycle lengths (4 vs 3 bars) and realign periodically | **C8** (partial — see limits) |
| **Displacement** | a straight pattern shifted off the beat by a constant offset | **C7** (it's a drift, period unchanged) |
| **Swing** | triplet-feel long-short 8ths | **C7** (`swing_ratio`) |
| **Rubato / accel** | the *tempo itself* moves | neither — **detected and excluded** as a confound |

The discipline that makes this tractable: **Hallucinote already knows the grid**
(tempo, meter, section spans, from the DB). General music-information-retrieval
polyrhythm work is hard because it must *induce* the beat blind. We don't. The
question collapses from "find the pulse" to the narrow "given the known beat,
how does this part subdivide it?" — which is why a light, interpretable method
beats a heavyweight one here.

---

## 2. Approaches evaluated

We prototyped three families against ~20 ground-truth fixtures (§6).

### A — anchored grid-sweep
For each candidate subdivision *S* ∈ {1..8} per beat, snap onsets to that grid
and score the fit; pick the coarsest grid that fits. **Verdict: partial.** It
correctly separates the *family* (binary vs ternary vs 5/7-tuple) and gives
alignment to the song grid (phase) — but it is **blind to ratios whose onsets
land on the binary grid**: a 4:3 (onsets every 0.75 beat = every third 16th)
reads as plain "16ths." Useful as a cross-check and for phase, not as the namer.

### B — dominant-IOI ratio
Take the part's inter-onset intervals, find the base pulse period *P* (beats),
and express it as a rational *M/N* (continued fraction, denominator ≤ 8). An IOI
of *M/N* beats means *N* onsets span *M* beats → an **N-against-M** cross-rhythm;
*M=1* is a plain *N*-per-beat subdivision. **Verdict: winner.** It names the
ratio directly and exactly. 0.667→2/3→**3:2**, 0.75→3/4→**4:3**, 0.8→4/5→**5:4**,
0.571→4/7→**7:4**, 0.2→1/5→**quintuplet**. The only question was how to estimate
*P* robustly.

### Period estimator — the one real fork
- **Median IOI** — perfect for steady patterns, but fooled by **rests/skips**
  (a 3:2 that rests once a cycle has some IOIs at 2×*P*, dragging the median).
- **Onset-train autocorrelation** — *rejected.* At any practical sample
  resolution it (a) misaligns for periods that aren't grid-multiples (triplets
  came out as 0.665 ≈ 2×0.333, a **harmonic**, not 0.333) and (b) needs harmonic
  suppression. Over-engineering that introduced bugs the simpler method doesn't.
- **Mode of IOIs** — *chosen.* The modal adjacent interval tracks the true pulse;
  rests are minority large outliers and don't move the mode. Resolution-free
  (uses exact onset times). This fixed the skip case (3:2-with-rests → **3:2**,
  occupancy 0.82) **without** breaking any steady case.

---

## 3. Recommended approach (the validated algorithm)

Per part, per section — pure DSP, DB-agnostic, neutral measurement (exactly like
`masking.py` / `timing.py`; the interpreter grades it, not the DSP):

1. **Detect onsets** — librosa onset-strength + backtrack + near-coincident
   dedup. *Reuses C7's front-end verbatim.*
2. **Base period P** = **mode of inter-onset intervals** (beats), refined by
   averaging IOIs within one bin of the modal bin. Skip/rest-robust.
3. **Density floor** — if *P* < 1/8 beat (> 8 hits/beat), classify as
   **roll/tremolo, low-confidence**; do not name a ratio. (Buzz rolls → here.)
4. **Rational approximation** — *P ≈ M/N*, denominator ≤ 8 → candidate label
   `N:M` (or `N/beat` when *M*=1).
5. **Grid-fit on P** — phase-fold onsets onto the *P*-grid; compute drift
   **stdev** (tightness) and **occupancy** (fraction of expected pulse slots
   filled). These drive confidence, not a raw-IOI variance (which rests break).
6. **Rubato gate** — if the IOIs show a strong monotonic trend (|corr| > 0.6)
   *and* the constant-period fit is poor, label **RUBATO/accel** — the tempo is
   moving; this is not a polyrhythm.
7. **Swing deference** — if the best fit is a triplet (3/beat) at partial
   occupancy *and* C7's `swing_ratio` is in the swing band (≈1.3–2.3), report
   **SWING (see timing)** rather than a triplet cross-rhythm. C8 composes with
   C7 instead of double-reporting the same feel.
8. **Verdict + confidence** — `confidence = f(fit tightness, occupancy, onset
   count)`. A clean ratio with *M*>1 or a non-binary *N* ∈ {3,5,6,7} and good fit
   → **named cross-rhythm**; *N* ∈ {1,2,4,8}, *M*=1 → plain subdivision; else
   **low-confidence**.

### Two-part pass (relationships)
- **Phasing** (validated): slide a window over two parts; track the mean
  nearest-onset offset of B relative to A across segments. A **monotonic drift**
  in that offset = phasing. In the prototype, Reich-style "B 3% faster" produced
  a clean march (−0.02 → −0.06 → … → −0.21 beat) while each part stayed
  individually steady (cv ≈ 0.003).
- **Polymeter** (partial): each part's **repeat-cycle length** (long-lag
  self-similarity) — a 4-beat cell against a 3-beat cell realigns every 12 beats.
  The concept validated directionally but cycle-length detection needs more work
  than sub-beat period detection; shipping it is a v2 of C8 (see limits).

---

## 4. What it's great at

Empirically, on the corpus (§6), the recommended core gets **every clean case
right** and **degrades honestly** on the hard ones:

- **Exact cross-rhythm naming**: 3:2, 4:3, 5:4, 7:4, 5:3 — all named correctly,
  confidence ≥ 0.97.
- **Tuplet subdivisions**: triplets (3/beat), quintuplets (5/beat), septuplets
  (7/beat) — correct, conf ≈ 0.97.
- **Rests/skips**: a 3:2 with a rest each cycle → still **3:2** (occupancy 0.82
  flags the holes without losing the ratio).
- **Phasing**: cleanly detected as a drifting inter-part offset.
- **Confound rejection** (the part most naive designs get wrong):
  - **Displacement** (16ths shifted +0.1 beat) → stays "on-grid 16ths"; the
    offset is C7's drift, not a cross-rhythm. ✓
  - **Swing** → deferred to C7's `swing_ratio`, not mislabeled as 3/beat. ✓
  - **Rubato/accel** → flagged via the IOI trend (corr −1.00), not read as a
    bizarre ratio. ✓
  - **Buzz rolls / tremolo** → density floor → "roll, low-confidence," not a
    degenerate ratio. ✓
  - **Additive grouping** (3+3+2; Stravinsky 2+2+3 = 7/8) → **low-confidence**,
    honestly (it has no single clean pulse). ✓

It **names** the relationship in musician's terms ("4-against-3"), which is what
makes `/mix-review` able to ask the right question.

---

## 5. Limitations (honest, like masking's F-notes)

1. **Additive / grouping meters are not decoded.** 3+3+2, Stravinsky's shifting
   cells, Balkan aksak — these have no single repeating IOI, so C8 reports
   *low-confidence* rather than "2+2+3." Decoding them needs **accent/meter
   analysis** (onset *strength* patterns, bar-level structure), a separate effort.
2. **Polymeter is only partially handled.** Sub-beat cross-rhythm is solid;
   bar-level cycle mismatch (Tool/Meshuggah "different parts, different bar
   lengths") needs robust cycle-length detection (long-lag self-similarity),
   which is a v2.
3. **Rubato within a section degrades the constant-period assumption.** We
   *detect and flag* accel/rit (so it's never silently mislabeled), but C8 does
   not track a moving tempo within a window. Chopin-style rubato → "rubato,
   low-confidence," not a decoded ratio. (Same family as C7's
   constant-tempo-within-window caveat.)
4. **One rhythmic line per stem.** If a single stem carries two simultaneous
   cross-rhythms (a pianist's 3-in-the-right-hand, 2-in-the-left on one mic), the
   onsets interleave and C8 sees one confused stream. Clean per-part captures
   (Hallucinote's norm) sidestep this; mixed stems need source separation (out of
   scope).
5. **Sparse parts can't be judged.** A one-drop kick (2 onsets/bar) has too few
   intervals to assert a pulse → low-confidence. Correct, but it means C8 says
   nothing about the groove of very sparse parts.
6. **Onset-detection limits are inherited from C7.** Slow-attack sources (subby
   kicks, pads) detect late/poorly; dense material floods. C8 carries the same
   transient-richness dependency — surfaced as low confidence, not corrected.
7. **The swing/triplet boundary is a judgment call.** Swing *is* triplet-based;
   we resolve the overlap by deferring to C7's `swing_ratio`, but a part that is
   genuinely playing straight triplets vs swinging hard sits near that boundary.
   The `swing_ratio` + occupancy split is a heuristic, not a proof.
8. **Ratios are capped at denominator 8.** 9:8, nested 3:2-inside-4:3, and other
   exotica round to the nearest representable ratio. Raising the cap trades
   naming reach for false-precision risk; 8 covered every musical case we tried.

None of these are silent failures — every one resolves to an explicit
*low-confidence* or *rubato/roll* verdict the interpreter can read.

---

## 6. The stress-test corpus (what we ran it against)

Each fixture is synthetic with a *known* ground truth (onsets placed at exact
beat positions, rendered as sharp clicks so onset detection is accurate — per
C7's "calibrate against detection accuracy" learning). Result summary:

| fixture | ground truth | C8 verdict | ✓ |
|---|---|---|---|
| straight 8ths / 16ths | binary subdivision | on-grid 2/beat, 4/beat | ✓ |
| triplets | ternary | cross-rhythm 3/beat | ✓ |
| hemiola | 3:2 | cross-rhythm 3:2 | ✓ |
| 4-against-3 | 4:3 | cross-rhythm 4:3 | ✓ |
| 5-against-4 | 5:4 | cross-rhythm 5:4 | ✓ |
| 7-against-4 | 7:4 | cross-rhythm 7:4 | ✓ |
| 5-against-3 | 5:3 | cross-rhythm 5:3 | ✓ |
| quintuplet / septuplet | 5/beat, 7/beat | cross-rhythm 5/beat, 7/beat | ✓ |
| 3:2 with rests | 3:2 (sparse) | cross-rhythm 3:2 (occ 0.82) | ✓ |
| swing 8ths | feel, not poly | deferred to C7 `swing_ratio` | ✓ |
| displaced 16ths (+0.1) | C7 drift | on-grid 16ths | ✓ |
| rubato (accel) | tempo moving | rubato flagged (trend −1.0) | ✓ |
| buzz roll | density | roll, low-confidence | ✓ |
| additive 3+3+2 / 2+2+3 (7/8) | grouping | low-confidence | ✓ (honest) |
| straight 8ths in 7/8 | odd meter, binary | on-grid 2/beat | ✓ |
| Reich phasing (B 3% faster) | phasing | drifting offset detected | ✓ |

### Genre map — what each style exercises
- **Classical cross-rhythm** (Brahms/Chopin 3-against-4, Fantaisie-Impromptu) →
  core cross-rhythm naming. ✓
- **Classical rubato** (Chopin tempo rubato) → rubato gate. Flagged, not decoded.
- **Romantic tuplets** (quintuplet/septuplet runs) → tuplet subdivision. ✓
- **Minimalism — Reich** ("Piano Phase", "Clapping Music") → phasing (two-part
  drift, ✓) and displacement ("Clapping Music" is a *displaced* pattern → reads
  as drift, correct). **Glass additive** → low-confidence (grouping, limit #1).
- **Prog rock** (Rush 7/8, Tool 5/4) → odd-meter binary subdivision works; *Tool
  polymeter* (alternating cells) → limit #2.
- **Math rock** (Don Caballero, Battles — mixed groupings) → mostly limit #1
  (additive), with embedded clean tuplets detected where present.
- **Primus** (Claypool syncopation, Alexander's polyrhythms) → syncopation reads
  as low-confidence (no single pulse); displaced figures → C7 drift; genuine
  3-over-4 drum/bass cross-rhythms → named.
- **Stomp** (interlocking body percussion) → per-part cross-rhythms named where
  each performer holds a steady ratio; the *interlock* across performers is the
  two-part/polymeter relationship (phasing ✓, polymeter partial).
- **Expert snare** (rudiments) → paradiddles read as the underlying 16ths (onset
  level); **flams/drags** are merged by the dedup window (we lose the ornament —
  a known trade-off; ornament detection is a separate fine-timing feature);
  **buzz rolls** → density floor.
- **Stravinsky / neoclassical** (additive, shifting meter) → limit #1.
- **Afro-Cuban / West African** (clave, bell patterns, 12/8-vs-4/4) → the 12/8
  vs 4/4 relationship is exactly a 3:2 family cross-rhythm and is named; the
  *clave pattern itself* (a specific syncopated cell) is grouping, limit #1.

---

## 7. How it slots into Hallucinote

Mirrors the masking/timing precedent exactly — pure measurement producer →
`MixReport` → graded by `/mix-review`.

**New module:** `src/hallucinote/audio/cross_rhythm.py`
- `analyze_cross_rhythm_window(stem_segments, sample_rate, *, window_start_beat,
  bpm, swing_ratios=None) -> CrossRhythmResult`
- Reuses C7's onset front-end (factor the shared `_detect_onset_samples` /
  `_dedup_onsets` out of `timing.py` into a small `onsets.py` both import).
- Optionally consumes the section's C7 `swing_ratio` per part for the swing
  deference (step 7) — the one cross-module input.

**New neutral dataclass** (in `report.py`, alongside `PartTiming`):
```
@dataclass(frozen=True)
class PartCrossRhythm:
    track_id: str
    pulse_ratio: str | None      # "3:2", "4:3", "5/beat", or None
    against_meter: bool          # True when the pulse fights the song grid
    base_period_beats: float
    occupancy: float             # 0..1 — how completely the pulse is filled
    confidence: float            # 0..1
    verdict: str                 # "cross-rhythm" | "subdivision" | "rubato"
                                 # | "roll" | "swing(see-timing)" | "low-confidence"
```
Plus a two-part `Phasing(track_a, track_b, drift_beats_per_cycle, confidence)`
on `SectionMetrics` (or a sibling list).

**Wiring** (one new field + one gate, identical shape to C7):
- `SectionMetrics.cross_rhythm: list[PartCrossRhythm]` + serialization in
  `_section_to_dict`.
- `analyze_mix(..., analyze_cross_rhythm=False)`; `_measure_window_cross_rhythm`
  in `analyze.py` (level-blind, like timing — gain doesn't move onsets).
- Handler gate `analyze_cross_rhythm=bool(sections)`.
- `/mix-review`: read `cross_rhythm` per section; surface as a producer question
  ("the guitar's in 3-over-2 against the straight-8th drums — intended hemiola,
  or do you want them locked?"). Gate on `confidence`.

**Test corpus:** promote the prototype fixtures (`onsets_at_beats` already
exists; add the cross-rhythm/phasing builders) into
`tests/unit/audio/test_cross_rhythm.py` — the corpus *is* the spec, same as
masking/timing.

### Suggested chunking (proportional)
- **C8a** — single-part cross-rhythm core (mode-IOI → ratio → grid-fit + guards)
  + corpus. The bulk of the value; fully validated here.
- **C8b** — two-part phasing pass + corpus.
- **C8c** *(optional, later)* — polymeter cycle-length detection (limit #2) and
  accent-based additive/grouping decoding (limit #1), if the songs need it.

---

## 8. Why this is the right call

- **Fits the architecture** — neutral DSP, per-part, fed to one interpreter;
  reuses C7's onset front-end; same dataclass/wiring/corpus pattern as masking.
- **Leverages the unfair advantage** — the score is known, so a light
  subdivide-the-known-beat method beats blind beat-induction MIR.
- **Names the relationship** in musician's terms, which is what makes the
  interpreter useful rather than just "low confidence here."
- **Fails honestly** — every hard case resolves to an explicit
  low-confidence/rubato/roll verdict, never a confident wrong answer.
- **Validated before building** — the recommendation isn't a guess; it survived
  a deliberately adversarial genre corpus, and we recorded exactly where it
  bends (additive, polymeter, rubato-within-window).
