---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-7M3D — Design: energy-realization lens (declared energy vs rendered intensity)

**Item:** ARR-7M3D — measurement-coverage gap. ENERGY is a first-class authored
dimension (`Arrangement.section(..., energy=)` → `Arrangement.energy_curve`); the
read side is symbolic-only. No tool joins the declared per-section energy curve to
the *rendered* per-section intensity. Effort M, impact L. Area: energy.

**Stage:** DESIGN + BUILD-PLAN. No production code written here. Canonical-doc
edits recorded as PROPOSED deltas (§5), not applied — Critic governs those.

**Grounding:** research already done (`research.md`) confirmed both design choices
the LIGHT directive asked about — the loudness+density+spectral proxy triple and
Spearman/flag-inversions over Pearson. This design does NOT re-litigate those; it
turns them into a buildable both-sides shape and resolves the source-of-truth
problem the code reads surfaced (§1, which `research.md` did not).

---

## 0. The thing research did not catch — declared energy is NOT in the DB

This is the load-bearing discovery from the code reads, and it reshapes the whole
build order. `research.md` §1 says "the authoring surface exists" — true at the
`Arrangement` object level, but **the declared energy curve never reaches a place
the analyzer can read.**

- `Arrangement.energy_curve` (`arrangement.py:268`) is a property of the in-memory
  `Arrangement` object, live only during a `build.py` run.
- `Arrangement.materialize` (`arrangement.py:344`) persists sections to the DB via
  `M.create_section(conn, song_id, name, start_bar, end_bar, ...)` — **energy is
  not passed.** (`arrangement.py:372`.)
- The `sections` table (`schema.sql:128`) has columns
  `id, song_id, name, start_bar, end_bar, color, notes_md` — **no energy column.**
- The analysis handler (`handlers/analysis.py::_collect_sections`) reads sections
  from the DB and builds `SectionWindow(name, start_beat, end_beat)` — there is no
  channel through which declared energy could reach `analyze_mix` today.

So the backlog line "no reference to the authored `energy_curve` anywhere in
`src/hallucinote/audio/`" is true at a deeper level than stated: the curve is not
merely un-consumed by audio — **it is not persisted at all.** Any realization lens
must first give declared energy a durable home the read side can reach. This is the
ONE-SOURCE-OF-TRUTH decision (DR-1), and it is the thin slice's first job.

---

## 1. Both-sides shape

ENERGY's AUTHOR side already exists (`Arrangement.section(energy=)`). What's
half-built is (a) **persistence** of that authored value and (b) the **MEASURE
lens**. This item ships both halves of what's missing.

### AUTHOR half (the gap is persistence, not authoring)

The composer already authors energy. The missing piece is that `materialize` drops
it on the floor. **DR-1 (below) persists the authored energy to the `sections`
table** so it survives to analysis time. No new authoring verb — the existing
`section(energy=)` is the surface; we stop discarding its value.

### MEASURE half — the realization lens (the new RULER)

A read-side check that takes the declared per-section energy curve + a `MixReport`
and reports, per intensity correlate, how well rendered intensity *ranks* against
declared intent:

- **Input:** declared `[(section_name, energy)]` (from the persisted column) +
  `MixReport.per_section` (already carries per-section LUFS; onset density is
  computed in this item — see §3).
- **Output (a new `MixReport.energy_realization` field, DR-2):** per correlate, a
  **Spearman ρ** of (declared energy rank, measured intensity rank) across sections
  — the "whether intensity tracked intent overall" scalar **when it is defined**
  (see the undefined-ρ contract in DR-2: ties / a constant correlate yield `None`,
  not `nan`) — PLUS a list of **inversion findings** — ordered section pairs where
  the higher-declared-energy section measures *lower* intensity (the "where it
  didn't" locals). The inversion list is per-pair magnitude and remains well-defined
  even when the aggregate ρ is undefined, so a flat-loudness render does not go dark.
- **Surfaced via `/mix-review`** (DR-4 wiring) as intent-gated producer questions:
  "you authored the chorus hotter than verse 2, but it renders 2 LU quieter —
  intended, or did the arrangement not land?" Never a verdict.

This is the same both-sides shape harmony got (`theory.lint` conformance) and
performance got (the perf lens) — the two siblings ARR-8P5K's taxonomy names. It
closes energy's MEASURE half (`arrangement-model.md` taxonomy line 53; ARR-8P5K
design line 48 lists "energy realization MEASURE → ARR-7M3D (this batch)").

---

## 2. The RULER-NOT-STAMP boundary (made explicit)

The lens is a **ruler**: it *measures* whether declared intensity ranking was
realized and *names* where it inverted. It is forbidden from making the musical
decision. Concretely:

- **It never re-authors the energy curve.** It does not write a "corrected" energy,
  does not propose a target LUFS per section, does not smooth the curve. (`research.md`
  §2: summing the correlates into one weighted intensity number would be a STAMP —
  the helper inventing the musical decision via arbitrary weights. We rank each
  correlate independently and never combine them into a verdict.)
- **It reports rank association, not a pass/fail grade.** A negative ρ is "the arc
  inverted vs intent" — *evidence*, surfaced as a question. A deliberately quiet
  "peak" (a stripped final chorus; the Nobile energy-drop-into-chorus at
  `arrangement-model.md:238`) is **authorship, not a defect** — the inversion is
  surfaced for the producer to confirm or correct, never auto-flagged as wrong.
- **Intent gates surfacing, not measurement.** Exactly like masking/timing: the DSP
  (ρ + inversions) always runs and lands in the report neutrally; `/mix-review`
  decides whether an inversion *becomes a surfaced question* by grading it against
  recalled markdown intent (a `density`/wash section, a declared energy-drop).
- **The lens is ordinal, matching the authored intent.** `energy=0.9` means "more
  intense than 0.6," not "−9 LUFS." Spearman assesses the *monotonic* (rank)
  relationship the composer actually authored; a Pearson/linear fit would impose a
  calibrated scale they never declared — itself a STAMP (`research.md` §3).
- **ρ is defined-or-`None`, never `nan` — and the inversion list does not depend on
  it.** Spearman ρ does NOT "always land": a constant/tied measured correlate (a
  flat-loudness render, or every section identical) makes `scipy.stats.spearmanr`
  return `nan` (verified — `ConstantInputWarning`, `statistic=nan`). The lens never
  emits or serializes `nan`; it records the correlate's ρ as `None` and names the
  reason in `skipped`. This is why the per-pair inversion list (magnitudes, not a
  correlation) is the surfacing-relevant signal at the DR-5 by-ear gate — it is
  well-defined even when the aggregate ρ is undefined. The earlier framing "ρ needs
  no threshold to report" is true only of the *threshold* (ρ has no surfacing gate);
  it does NOT mean ρ is always a finite number.

---

## 3. The intensity proxy — what ships in the thin slice, what's deferred

`research.md` §2/§4 confirmed the triple (loudness dominant; spectral and onset
density as robust secondary correlates) and the DISCOVERED-FROM-FRICTION ordering.
This design commits to:

| Correlate | Source | Status |
|---|---|---|
| **Loudness** (LUFS-S median per section) | `SectionMetrics.master.loudness.lufs_s_median` — **already computed**, zero new DSP | **SHIP (thin slice).** The dominant perceptual correlate (`research.md` §2/§4 [1][3]); a loudness-only MVP is honest, not a corner-cut. |
| **Onset/event density** (onsets-per-beat per section) | reuse the calibrated `onsets.detect_onset_samples` front-end over the windowed stems `_measure_sections` already slices | **SHIP (chunk 2).** Cheap; strong second signal; no new detector. |
| **Spectral density/flux/centroid** | the one NEW DSP primitive (librosa spectral features over the windowed master) | **DEFER — flagged, not dropped** (DR-3). Add when loudness+density prove insufficient (a chorus that opens the spectrum at matched loudness). |

**Why loudness uses LUFS-S median, not LUFS-I:** LUFS-S median is the per-section
short-term loudness already in `SectionMetrics` and is robust to the gating
edge-effects LUFS-I has on short windows. It is the level correlate the lens reads.

**Density correlate, calibration-first (a HARD discipline from learnings).** Onset
density reuses a *detection* front-end, so per the learning "DSP with a detection
front-end: calibrate against real cases, don't assert from intuition" — the build
plan REQUIRES running real section audio through the onset front-end and reading
the per-section densities BEFORE locking any test assertion. The C7 story (a
slow-attack fixture read wildly off; spurious double-onsets) is the precedent. The
density is per-section onsets-summed-across-stems / window-beats (already deduped
by the shared `dedup_onsets`); it is a *relative* read across sections (only the
ranking matters for Spearman), which is robust to a constant per-detector offset.

---

## 4. Decision records

### DR-1 — Persist declared energy to the `sections` table (the source-of-truth fix)

**Decision:** add an `energy REAL` column to the `sections` table (nullable,
default NULL), thread it through `M.create_section(..., energy=None)` and
`Arrangement.materialize` (pass `sec.energy`), and surface it in
`get_sections_for_song` (already `SELECT *`). The analysis handler's
`_collect_sections` then reads it into a declared-energy list the realization lens
consumes.

**Alternatives considered:**

- **(A) Read energy from `build.py` at analysis time** (re-import the song's
  Arrangement). REJECTED — violates ONE-SOURCE-OF-TRUTH and the architecture: the
  DB is the materialized state, the analyzer is DB-agnostic by design
  (`analyze.py` docstring; the handler is the only DB-aware layer), and songs now
  live in a *separate repo* (memory: framework⇄songs split) so the engine can't
  assume `build.py` is reachable. Re-running build at analyze time is the
  data-loss-trap the project already rejected for intent (memory:
  `project_intent_home_rationalization`).
- **(B) Store energy in `sections.notes_md`** (the existing free-text column).
  REJECTED — `notes_md` is prose/markdown intent (the WHY); energy is a structured
  scalar (the WHAT). Overloading prose with a parsed number re-creates the
  "disposable annotation" smell and couldn't be queried cleanly. The project
  already drew the WHAT/WHY line (memory: split build.py WHAT from markdown WHY).
- **(C) A separate `section_energy` annotation/markdown ref.** REJECTED for the
  thin slice — energy is a *structural* per-section scalar authored on the section
  itself (`arrangement-model.md:254` lists energy as a Section property), so its
  home is the section row, parallel to `start_bar`/`end_bar`. A markdown ref is for
  relational/learned intent (the mix-intent tags), not a section's own authored
  attribute.

**Trade-offs accepted:** a schema column add. The schema uses `CREATE TABLE IF NOT
EXISTS` + idempotent `init_db` migration; **the column add must be an idempotent
ALTER guarded against re-runs** (the project's migration pattern — see how `init_db`
handles schema). Nullable/default NULL means pre-existing songs (and the DB-only
authoring path that never declared energy) degrade gracefully: a NULL-energy section
is simply *excluded* from the realization correlation (you can't rank intent you
don't have), recorded as a `skipped_analyses` entry naming why — never a fabricated
0.5. **No back-compat shims** beyond the nullable column (memory: no back-compat to
throwaway code) — there is no deployed multi-user DB to migrate; the column is
additive.

**Boundary crossing (investigate per building.md):** this touches a contract
surface — the `sections` table schema, consumed by `get_sections_for_song`,
`_collect_sections`, `_extract_song_structure`, and any reader that does `dict(row)`.
The build plan's chunk 1 includes a consumer grep + the migration-idempotency check.

### DR-2 — `MixReport.energy_realization` shape (top-level, not per-section)

**Decision:** a new top-level `MixReport.energy_realization` field (the realization
read is inherently *cross-section* — it correlates a curve, so it cannot live on a
single `SectionMetrics`). Shape:

```python
@dataclass(frozen=True)
class EnergyInversion:
    """One ordered section pair where rendered intensity inverts declared intent.

    Sections are identified by ``start_beat`` (the robust, song-unique key — see
    the join-key note below), NOT by name: ``vary()``/recapitulation produces
    repeated section names (two "Chorus" rows), so name alone mis-pairs.
    """
    higher_energy_start_beat: float  # start_beat of the section authored MORE intense
    higher_energy_section: str       # its name (display only; not the join key)
    lower_energy_start_beat: float   # start_beat of the section authored LESS intense
    lower_energy_section: str        # its name (display only; not the join key)
    declared_energy_delta: float     # higher.energy - lower.energy  (> 0 by construction)
    correlate: str                   # "loudness" | "onset_density"
    measured_higher: float           # the measured value of the higher-energy section
    measured_lower: float            # the measured value of the lower-energy section
    measured_delta: float            # measured_higher - measured_lower (< 0 = inverted)

@dataclass(frozen=True)
class EnergyRealization:
    """Declared-energy-curve vs rendered-intensity read (ARR-7M3D). RULER, not
    stamp: reports ranked intensity vs intent + names inversions; never re-authors
    the curve. Neutral evidence — /mix-review grades it against intent."""
    # Per correlate, Spearman ρ — or None when ρ is undefined (a constant/tied
    # measured correlate makes scipy return nan; we record None, never serialize
    # nan). The reason for each None is in ``skipped``.
    correlate_rho: dict[str, float | None]    # {"loudness": ρ|None, "onset_density": ρ|None}
    inversions: list[EnergyInversion]         # notable inversions across correlates
    # Declared curve over the energy-declared sections, each carrying its start_beat
    # so the surfaced report keeps repeated-name sections distinct.
    sections_ranked: list[SectionEnergy]      # declared (start_beat, name, energy), excl. NULL
    skipped: list[str]                        # human-readable exclusion reasons (NULL
                                              # declared energy, missing/nan measured
                                              # correlate, undefined ρ) — each names why

@dataclass(frozen=True)
class SectionEnergy:
    """A declared section in the ranked curve, keyed by its song-unique start_beat."""
    start_beat: float
    name: str
    energy: float
```

**Undefined-ρ contract (resolves B1).** `scipy.stats.spearmanr` returns
`statistic = nan` (with `ConstantInputWarning`) whenever a measured correlate is
constant or fully tied across the ranked sections — verified directly, this run.
The lens MUST detect this (`math.isnan` on the returned statistic) and record that
correlate's ρ as `None` plus a `skipped` entry naming the reason
(`"loudness ρ undefined: measured values tied/constant across sections"`). It NEVER
puts `nan` in `correlate_rho`. Because `to_json_dict` → `json.dumps` is called
WITHOUT `allow_nan=False` today (analysis.py:457), a stray `nan` would serialize as
a bare `NaN` token — invalid JSON that strict consumers (`JSON.parse`, the eval
judge, any non-Python reader) reject. So the lens guarantees `correlate_rho` values
are `None`-or-finite **by construction**, AND chunk 3 hardens the write path by
passing `allow_nan=False` to the report's `json.dumps` so any future regression
fails loud rather than writing invalid JSON. (Both belt and suspenders: the
by-construction guarantee is the contract; `allow_nan=False` is the structural
backstop.)

**Measured-side nan symmetry (resolves W2).** `lufs_s_median` (and a degenerate
onset-density window) can themselves be `nan`/missing for an out-of-capture or
too-quiet section — and `spearmanr` propagates that to a `nan` ρ. The lens excludes,
**symmetrically on both sides of the join**, any section whose *measured* correlate
is missing or `nan` from that correlate's ρ input, naming it in `skipped` — exactly
as a NULL *declared* energy section is excluded. NULL-declared and nan-measured are
the two exclusion reasons; both feed the same `skipped` discipline.

**Join key is `start_beat`, never name (resolves B2).** The `sections` table has NO
UNIQUE constraint on `name` (schema.sql:131 is bare `TEXT NOT NULL`; only sibling
tables carry UNIQUE), and repeated names are normal/intended — `vary()` /
recapitulation produces multiple "Chorus" sections, and two "Chorus" sections at
*different* energy is the exact Nobile energy-drop-into-final-chorus case the design
holds up as the ruler-not-stamp authorship example (§2, `arrangement-model.md:238`).
A name-keyed join collapses or mis-pairs those rows — wrong on the central case.
The robust key is `start_beat`: it is carried on `SectionMetrics` (report.py:401),
derived from the section row's `start_bar`, and is song-unique in practice
(non-overlapping `[start_bar, end_bar)` spans; `get_sections_for_song` orders by
`start_bar`). The lens joins declared `SectionEnergy.start_beat` to
`SectionMetrics.start_beat`. **A plain ordered-index join would ALSO break** because
`_measure_sections` (analyze.py:454) *skips* out-of-capture sections — so
`per_section` is not positionally aligned with the declared list when any section is
skipped. `start_beat` is robust to that; the index is not.

`MixReport.energy_realization` is `None` when fewer than 2 energy-declared sections
exist (Spearman needs ≥2 ranks) — recorded with a `skipped_analyses` entry, not a
fabricated ρ. Serialized via an explicit `to_json_dict` boundary entry (mirroring
every other report dataclass — `report.py` does NOT use `dataclasses.asdict`); the
serializer emits `None` (→ JSON `null`) for an undefined correlate, never `nan`.

**Alternative (per-section field) rejected:** a realization read is a property of
the *sequence*, not any one section; forcing it per-section would duplicate the
whole-curve ρ onto every row.

### DR-3 — Spectral correlate deferred (flagged, not dropped)

Per DISCOVERED-FROM-FRICTION and `research.md` §4: ship loudness + onset-density;
defer the spectral-flux/centroid correlate until friction shows loudness+density
miss a real case. The `correlate_rho` dict is open-keyed precisely so a third
correlate adds a key without a schema change. **This is a flagged deferral, not a
silent drop** (CLAUDE.md "never silently drop a requirement") — it is recorded in
the build plan and in the proposed `arrangement-model.md` delta.

### DR-4 — Surface via `/mix-review` MEASURE+INTERPRET (the wired surface)

The VERIFIABLE SIGNAL requires the check be "wired into `/mix-review`." DR-4 adds an
`energy_realization` feed bullet to MEASURE (§2) and an intent-gating clause to
INTERPRET (§3): an inversion is a producer *question*, gated on intent (a declared
energy-drop / `density` wash is authorship — stay quiet), never a verdict. This is a
doc/skill edit (no code) and is where the **MIX-3S7P collision** lives (§6).

### DR-5 (PENDING by-ear) — the "notable inversion" surfacing threshold

How big a measured inversion (how many LU "wrong-direction", or how large a declared
energy gap inverting) before the report lists it as *notable* (vs DSP noise) is a
perceptual judgment. Per the run constraint (Live unattended, no human ear) this is
**NOT guessed.** It is calibrated exactly like the existing `_MASKING_REPORTING_FLOOR`
/ `_TIMING_MIN_CONFIDENCE` floors in `analyze.py`: render sun-zone-done objectively,
compute the measured inversions and their magnitudes, surface them, and leave the
gate as a named module constant tuned against the real measured distribution.
Spearman ρ itself needs no *surfacing threshold* — when ρ is defined it is reported
verbatim, and when it is undefined (constant/tied correlate) it is reported as `None`
with a reason (DR-2's undefined-ρ contract), never gated and never `nan`. Only the
per-pair "is this inversion worth surfacing" gate is by-ear, and it operates on
per-pair *magnitude*, which is well-defined even when the aggregate ρ is `None` — so
the inversion surfacing does not go dark on a tied-ρ render. Flagged as the one
PENDING by-ear call.

---

## 5. PROPOSED canonical deltas (recorded — NOT applied; Critic governs edits)

### `.prawduct/artifacts/arrangement-model.md`

Under "The derivative question … as a ruler and a lens" (the read-side lens bullet,
~line 303–308), add a sentence (LINK-DON'T-SUMMARIZE — point at the lens, don't
restate the method):

> The energy curve now has an **audio-realization lens** (ARR-7M3D):
> `MixReport.energy_realization` reports per-correlate Spearman ρ of declared
> `energy_curve` rank vs measured per-section intensity (LUFS-S + onset density),
> and names rank inversions — parallel to the harmonic-conformance lint and the
> performance lens, closing energy's BOTH-SIDES MEASURE half. The spectral-intensity
> correlate is a flagged deferral (loudness+density first). The lens is a ruler:
> it reports ranked intensity vs intent and never re-authors the curve.

(Also: the taxonomy line ~53 and the ARR-8P5K cross-ref already predict this as
energy's MEASURE half — no edit needed there, it's already written.)

### `skills/mix-review/SKILL.md`

- **MEASURE (§2)** — add a feed bullet alongside `loudness`/`timing`/`performance`:
  > - `energy_realization` — declared-energy-curve vs rendered-intensity (ARR-7M3D).
  >   `correlate_rho` (Spearman ρ per correlate — `loudness`, `onset_density` —
  >   near +1 = the arc tracked intent; ~0 = no relationship; negative = the arc
  >   *inverted* vs intent; a correlate's ρ is `null` when it's undefined — a
  >   constant/tied render, with the reason in `skipped`) and `inversions` (ordered
  >   section pairs, each identified by `start_beat`, where the higher-declared-energy
  >   section renders *lower* intensity — well-defined even when ρ is `null`). Neutral
  >   evidence — a deliberate energy-drop chorus is authorship. The whole
  >   `energy_realization` is `null` when <2 sections declare energy.
- **INTERPRET (§3)** — add the intent gate: an inversion **matches intent** (a
  declared energy-drop / `density` wash) → stay quiet; **contradicts a clear intent**
  (a `focal`/lift section that renders quieter than the section it should top) →
  surface as a producer question with the cheapest musical fix; **intent unknown** →
  ask one good question, then learn it back. Frame as the song's lift question:
  "the chorus reads 2 LU under verse 2 though you authored it hotter — landing, or
  does the arrangement need to open up?"

### `src/hallucinote/audio/report.py`

Add the `EnergyInversion` + `EnergyRealization` + `SectionEnergy` dataclasses (DR-2,
each carrying `start_beat` as the section identity) and the
`MixReport.energy_realization: EnergyRealization | None = None` field with its
`_energy_realization_to_dict` serializer in `to_json_dict`. The serializer emits
`None` (→ JSON `null`) for an undefined correlate ρ — never `nan` — mirroring the
explicit-boundary pattern (`_section_to_dict` et al.); it does NOT use
`dataclasses.asdict`. (This is code, edited under the build plan, not a
canonical-doc delta — listed here for completeness of the touch-set.)

---

## 6. Collision with MIX-3S7P (flagged per directive)

Both ARR-7M3D and MIX-3S7P were flagged as potentially touching `skills/mix-review`.
Investigated:

- **MIX-3S7P** (`research.md`) is substantially already-implemented song-side
  (atmosphere pan/send envelopes in the *songs* repo) + an engine-side LOM/sync
  question. Its plan dir holds only `research.md` (no build-plan yet), and its
  research references **no edit to `skills/mix-review/SKILL.md`** — its surface is
  the sync planner + song authoring, not the review skill.
- **ARR-7M3D** edits `skills/mix-review/SKILL.md` in two bounded spots (MEASURE feed
  bullet + INTERPRET gate clause, DR-4).

**Assessment:** low collision risk *today* (MIX-3S7P has no mix-review edit in
flight). The mitigation if MIX-3S7P later edits the same skill: both edits are
*additive bullets in distinct sections* (a feed bullet vs an atmosphere/space note),
so a textual merge is mechanical. The build plan notes this so whichever lands second
re-reads the skill before editing (the "pattern sweeps are tree-wide" + "re-read,
don't trust prior summary" learnings). Flagged in StructuredOutput.

---

## 7. Requirements confidence (carried into the build plan)

**Medium.** The problem, the both-sides shape, the proxy, and the methodology are
each statable in one sentence (research closed the two open design questions). The
assumptions that keep it from High, all closed cheaply in-plan:
(1) DR-1's schema-migration idempotency must match the project's actual `init_db`
migration pattern — confirmed by reading that pattern in chunk 1 (cheap; the thin
slice does it); (2) the onset-density calibration could reveal the detector reads
sun-zone's real sections poorly (the C7 risk) — chunk 2 calibrates before asserting
and degrades to loudness-only-ρ if density proves untrustworthy, so it can't silently
ship a wrong number; (3) **[was implicit, surfaced by review B1]** the first draft
assumed "Spearman ρ always lands as a finite number" — false: a constant/tied
measured correlate returns `nan`. Resolved in DR-2's undefined-ρ contract (record
`None` + reason, `allow_nan=False` backstop) with a chunk-3 tied/constant test;
(4) **[was implicit, surfaced by review B2]** the first draft assumed section `name`
is a unique join key — false: no UNIQUE constraint, and `vary()`/recapitulation
intentionally repeats names. Resolved by joining on `start_beat` (DR-2) with a
chunk-3 lock test (two same-named sections at different energy). The by-ear threshold
(DR-5) is explicitly deferred-not-guessed, so it doesn't lower confidence.
