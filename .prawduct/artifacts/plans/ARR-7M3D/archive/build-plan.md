---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-7M3D — Build Plan: energy-realization lens

See `design.md` for the both-sides shape, decision records (DR-1..DR-5), the
ruler-not-stamp boundary, and the proposed canonical deltas. This plan does not
restate them (LINK-DON'T-SUMMARIZE).

## Requirements Confidence: Medium

The problem, both-sides shape, intensity proxy, and rank-correlation methodology
are each statable in one sentence (`research.md` closed the two open design
questions; `design.md` resolved the source-of-truth question DR-1). Two assumptions
keep it from High, both closed cheaply inside the early chunks:

1. **DR-1 schema migration must match the project's actual idempotent pattern.**
   RAISED to near-certain by reading `db/connection.py` `_ADDED_COLUMNS` /
   `_ensure_added_columns` / `_check_schema_canary` — the `sends.intended_rt60_s`
   reverb-intent column add (connection.py:115) is a near-exact precedent
   ARR-7M3D mirrors. Chunk 1 follows it (dual declaration: `schema.sql` CREATE +
   `_ADDED_COLUMNS` row, or the canary raises).
2. **Onset-density detector may read sun-zone's real sections poorly** (the C7
   slow-attack / double-onset risk). Chunk 2 CALIBRATES against real section audio
   before locking assertions and degrades to loudness-only ρ if density proves
   untrustworthy — so it cannot silently ship a wrong number.

The one PENDING by-ear call (DR-5, the "notable inversion" surfacing threshold) is
deferred-not-guessed and does not lower confidence — Spearman ρ reports without a
threshold; only the per-pair surfacing gate is by-ear.

---

## Verification strategy

- **Unit (every chunk):** `pytest` against the three test trees
  (`tests/unit/...`, `hallucinote_mcp/tests/...`). Tests come first/alongside.
- **Fixture-driven join (chunk 3):** the realization lens is fully unit-testable
  NOW against a synthetic `MixReport` — a declared curve `[A:0.3, B:0.6, C:0.9]`
  plus a hand-built `SectionMetrics` set with a DELIBERATE inversion (C renders
  quieter than B), asserting ρ < 1, the correct `EnergyInversion`, and (the
  ruler-not-stamp lock) that the lens emits NO re-authored curve and NO verdict.
- **Calibration-first (chunk 2):** before locking density assertions, run real
  section audio through the onset front-end and print per-section densities
  (the learning's required step; the C7 precedent).
- **End-to-end objective render (chunk 5, Live UP + UNATTENDED):** render
  sun-zone-done (declared 0.25→1.0 across 9 sections), `analyze_mix`, read
  `energy_realization` — assert the realized arc's ρ and surface the measured
  inversions + magnitudes. This is FULLY OBJECTIVE (rank correlation, no ear) and
  is the primary integration proof. NOTE: sun-zone-done lives in the *songs* repo
  (`hallucinote-songs`), built against the installed engine — chunk 5 builds it
  there after `pip install -e .` of this branch.
- **Migration verification (chunk 1):** open a *pre-existing* DB (one built before
  the column) through `init_db` and confirm the ALTER lands once + is a no-op on
  re-open; confirm the schema canary passes (it enforces the dual declaration).

## Governance checkpoints

- After **chunk 1** (the thin slice — schema + persistence + read-through end to
  end): architecture validation. The source-of-truth path is the riskiest part.
- After **chunk 3** (the lens lands): the keystone — every later chunk surfaces it.
- Before completion: **chunk 6** cumulative.

---

## Chunks (dependency-ordered; chunk 1 is the thin vertical slice)

### Chunk 1 — Thin slice: persist declared energy + read it back end-to-end

The thinnest path proving the architecture: declared energy reaches a durable home
and the analysis handler can read it. NO lens math yet — just prove the value flows
from `Arrangement` → DB → `SectionWindow`-adjacent read, end to end.

- **Type:** code
- **Foreign API:** none
- **Done when:**
  1. `sections.energy REAL` column added in BOTH `schema.sql`'s CREATE TABLE block
     AND `db/connection.py` `_ADDED_COLUMNS` (mirroring the `sends.intended_rt60_s`
     precedent at connection.py:115). `_check_schema_canary` passes (it raises if
     the dual declaration drifts).
  2. `M.create_section(..., energy: float | None = None)` threads energy into the
     INSERT and the `SECTION_CREATED`/`SECTION_UPDATED` event payloads + the
     update-detection tuple (so re-materialize with a changed energy is an
     `updated`, not a stale `unchanged`). Mutator discipline: every write through
     the mutator, emits the event (memory: mutator discipline).
  2a. **Second mutator path — `update_section` (W1, do NOT silently drop):**
     `update_section` (score.py:100) gates `changes` against an allowlist
     `_SECTION_FIELDS` (score.py:97) that does NOT include `energy`, so a partial
     section update can never change energy and `energy=` would raise
     `unsupported fields`. Add `energy` to `_SECTION_FIELDS` so the partial-update
     path supports it symmetrically with `create_section` (energy is a first-class
     authored section attribute — `arrangement-model.md:254` — so the update path
     owning it is correct, not gold-plating). Test: `update_section(section_id,
     energy=...)` persists and emits `SECTION_UPDATED` with the energy change; a
     `update_section(..., energy=...)` on a section that previously had NULL energy
     sets it. (If a future reason emerges to deliberately exclude energy from the
     partial-update path, that omission must be written here with rationale — never
     left silent. The decision for this build: include it.)
  3. `Arrangement.materialize` passes `energy=sec.energy` to `create_section`
     (arrangement.py:372). The PlacedSection already carries `energy`
     (arrangement.py:222).
  4. `_collect_sections` (handlers/analysis.py) reads the energy column and exposes
     a declared-energy list (a parallel `[(name, energy|None)]` the lens will
     consume) — the SectionWindow stays unchanged (name/start/end); declared energy
     rides alongside, not inside the window (it's intent, not geometry).
  5. Boundary investigation recorded: grep consumers of `sections` rows
     (`get_sections_for_song`, `_collect_sections`, `_extract_song_structure`, any
     `dict(row)` reader) — confirm a new nullable column doesn't break them
     (`SELECT *` + `dict(row)` tolerate it; `_extract_song_structure` gains the
     field for free, which is correct — the eval judge should see authored energy).
  6. Tests: mutator round-trips energy (incl. NULL default, and the changed-energy
     → `updated` path with a raw-bypass backstop for the no-energy legacy row);
     migration test opens a pre-column DB and asserts the ALTER lands once + no-op
     on re-open; `_collect_sections` surfaces energy incl. the NULL case.
  7. Acceptance criteria met and tests pass.
  8. `/critic` run and blocking findings resolved.
  9. Committed and chunk marked `[x]` in Status.
- **Critic mode:** `final` (override forward — DR-1 is the architectural keystone:
  schema + mutator + contract-surface change whose coherence every later chunk
  builds on; Goals 4–7 pay off before widening).

### Chunk 2 — Onset-density-per-section primitive (calibrate before asserting)

The one new measured signal beyond in-hand loudness. Reuses the calibrated
`onsets.detect_onset_samples` front-end over the windowed stems `_measure_sections`
already slices — no new detector.

- **Type:** code
- **Foreign API:** none (librosa is wrapped by the existing `onsets` front-end,
  already verified upstream; this chunk consumes our own `onsets.py`, not librosa
  directly)
- **Done when:**
  1. A pure function (in `audio/` — sibling to `onsets.py`/`section.py`) computing
     per-section onset density = (onsets summed across sliced stems, deduped via the
     shared `dedup_onsets`) / window-beats. Level-blind (onsets don't move with
     gain — no `stem_gains` reconstruction, matching `_all_window_timing`).
  2. **CALIBRATION FIRST (hard, from learnings):** a tiny calibration script runs
     representative real section audio (sun-zone sections, or a sharp-attack
     `click`-style synthetic if a render isn't yet available) through the function
     and PRINTS per-section densities; eyeball them vs what the sections *are*
     before locking any assertion. Record the calibration read in the chunk's
     reflection. If densities read implausibly (the C7 slow-attack/double-onset
     failure), document the caveat and gate density behind a confidence/plausibility
     note rather than shipping a wrong number.
  3. Density is wired so `_measure_sections` can surface a per-section density
     value (the lens reads it in chunk 3). It's a *relative* read across sections
     (only the ranking feeds Spearman), robust to a constant per-detector offset.
  4. Tests: density on a synthetic window with a known onset count returns the
     expected onsets/beat; an empty/too-short window returns 0 (or a sentinel the
     lens excludes), never raises (mirror the `_measure_sections` skip discipline).
  5. Acceptance criteria met and tests pass.
  6. `/critic` run and blocking findings resolved.
  7. Committed and chunk marked `[x]` in Status.
- **Critic mode:** inferred (`chunk`).

### Chunk 3 — The energy-realization lens (the keystone RULER)

The join + Spearman ρ + inversion detection. Fully unit-testable against a fixture
`MixReport` — Live render only *validates* it end-to-end (chunk 5).

- **Type:** code
- **Foreign API:** none (`scipy.stats.spearmanr` — scipy is already a dep,
  pyproject.toml:19; verified importable this session)
- **Done when:**
  1. `EnergyInversion` + `EnergyRealization` + `SectionEnergy` dataclasses added to
     `report.py` (DR-2 shape — each section identified by `start_beat`, not name),
     `MixReport.energy_realization: EnergyRealization | None = None` field, and
     `_energy_realization_to_dict` in `to_json_dict` (explicit boundary, matching
     every sibling dataclass — NOT `dataclasses.asdict`). The serializer emits `None`
     (→ JSON `null`) for an undefined correlate ρ — never `nan`. **JSON-write
     hardening (B1):** the report's `json.dumps` at analysis.py:457 is changed to
     pass `allow_nan=False` so any future stray `nan` fails loud instead of writing
     invalid JSON. A test asserts that serializing an `EnergyRealization` whose
     `correlate_rho` contains a `None` round-trips through `json.dumps(...,
     allow_nan=False)` cleanly (and that a hypothetical `nan` would raise — proving
     the backstop is wired).
  2. A pure lens function: given declared `[SectionEnergy]` (start_beat, name,
     energy; NULL-energy already excluded) + the per-section measured correlates
     (LUFS-S median already in `SectionMetrics`; onset density from chunk 2),
     **joined by `start_beat` (the song-unique key — NOT name; B2)**, computes
     per-correlate Spearman ρ over the energy-declared sections and the inversion
     list. **Undefined-ρ contract (B1):** when `spearmanr` returns `nan` (constant /
     fully-tied measured correlate — `math.isnan` on the statistic), record that
     correlate's ρ as `None` and add a `skipped` entry naming why; never put `nan`
     in `correlate_rho`. **Measured-nan symmetry (W2):** a section whose *measured*
     correlate is missing or `nan` (out-of-capture / too-quiet / degenerate window —
     `lufs_s_median` can be `nan`) is EXCLUDED from that correlate's ρ input and
     named in `skipped`, exactly as a NULL-*declared* section is. Returns `None`
     when <2 energy-declared sections remain after exclusions (recorded as a
     `skipped_analyses` entry, not a fabricated ρ). NULL-energy sections are
     EXCLUDED and named in `EnergyRealization.skipped`.
  3. **Ruler-not-stamp test (the boundary lock):** assert the lens output contains
     ONLY measurements (ρ, inversions, ranked declared curve) and NO re-authored
     energy / no target LUFS / no pass-fail grade. A test that would FAIL if a
     future edit made the lens emit a "corrected" curve.
  4. Fixture tests covering the full ρ/inversion contract:
     - **Deliberate inversion:** declared `[A:0.3, B:0.6, C:0.9]`, measured LUFS
       where C < B → assert ρ < 1, exactly one loudness `EnergyInversion` (B,C)
       carrying both sections' `start_beat` + correct deltas.
     - **Perfect monotonic:** measured rank == declared rank → ρ == 1.0, zero
       inversions.
     - **Ordinal-not-linear:** a monotonic-but-curvilinear measured set still
       yields ρ == 1.0 (Spearman sees rank, not slope — `research.md` §3, why
       Pearson was rejected).
     - **Tied/constant correlate (B1 — the degenerate case the first draft
       omitted):** declared `[A:0.3, B:0.6, C:0.9]` with measured loudness ALL EQUAL
       → `correlate_rho["loudness"] is None` (NOT `nan`), with a `skipped` entry
       naming the tie; the report serializes through `json.dumps(...,
       allow_nan=False)` without raising.
     - **Same-named sections lock (B2 — FAILS under a name-keyed join):** two
       sections both named `"Chorus"` at DIFFERENT `start_beat` and DIFFERENT
       declared energy (e.g. `start_beat=0.0, energy=0.9` and `start_beat=64.0,
       energy=0.4` — the Nobile energy-drop final chorus) with different measured
       loudness → assert each is paired with ITS OWN measured value (not collapsed,
       not cross-paired), and any resulting inversion names them by `start_beat`.
       This test is the join-key lock: it passes under `start_beat` keying and fails
       under name keying.
     - **Measured-nan exclusion (W2):** one section with `lufs_s_median = nan` is
       excluded from the loudness ρ (named in `skipped`), and ρ is computed over the
       remaining finite sections (or `None` if <2 remain).
  5. `analyze_mix` accepts the declared-energy list (`Sequence[SectionEnergy]`, a
     new keyword arg defaulting `()` so synthetic-fixture callers are unaffected — no
     back-compat shim needed, memory) and populates `MixReport.energy_realization`.
     Stays DB-agnostic (the handler does the DB→`SectionEnergy` lift, chunk 4).
  6. Acceptance criteria met and tests pass.
  7. `/critic` run and blocking findings resolved.
  8. Committed and chunk marked `[x]` in Status.
- **Critic mode:** `final` (override forward — the keystone the wiring + verify
  chunks build on; coherence of the report shape + the ruler boundary matters here).

### Chunk 4 — Wire declared energy through the analysis handler

Connect the chunk-1 persisted column → chunk-3 lens via the MCP analysis handler
(the only DB-aware layer).

- **Type:** code
- **Foreign API:** none
- **Done when:**
  1. `handlers/analysis.py::_collect_sections` (or a sibling collector) lifts the
     declared energy into a `list[SectionEnergy]` `analyze_mix` consumes, **carrying
     each section's `start_beat`** (the same `_position_bar_to_beats(row["start_bar"],
     ts_points)` conversion `_collect_sections` already does for `SectionWindow`) so
     it shares the join key the lens uses (`start_beat`, NOT name — B2). NULL energy
     → excluded from the lift (not coerced to a fabricated value); the lens never
     sees a NULL-energy declared section.
  1a. Test (B2 at the handler layer): a song with two same-named sections at
     different `start_bar`/energy lifts to two distinct `SectionEnergy` rows with
     distinct `start_beat` — proving the handler doesn't collapse repeated names.
  2. `analyze_handler` passes the declared-energy list to `analyze_mix`. Summary +
     `_analysis_code_status` unaffected.
  3. Tests: `test_handlers_analysis` covers a song whose sections declare energy →
     `energy_realization` populated; a song with no energy declared → `None` +
     a `skipped_analyses` entry (never a fabricated ρ).
  4. Acceptance criteria met and tests pass.
  5. `/critic` run and blocking findings resolved.
  6. Committed and chunk marked `[x]` in Status.
- **Critic mode:** inferred (`chunk`).

### Chunk 5 — End-to-end objective render + the by-ear threshold (PENDING calibration)

Validate the whole path against a real render, and calibrate the one by-ear gate.

- **Type:** code
- **Foreign API:** ableton-render / ableton-analysis (MCP) — exercised, not wrapped
- **Done when:**
  0. verify-api — confirm the render→analyze MCP path produces a report with the new
     `energy_realization` key (read the handler response + the JSON on disk;
     respawn `/mcp` if stale per the reconnect-workflow memory).
  1. Build sun-zone-done in the `hallucinote-songs` repo against this branch
     (`pip install -e .` of `hallucinote` first), render it (Live UP, UNATTENDED),
     run `ableton_analysis`, read `energy_realization`.
  2. Assert OBJECTIVELY (no ear): ρ(declared 0.25→1.0, measured LUFS-S) is computed
     (or recorded as `None`-with-reason if the render happens to tie a correlate —
     B1; not `nan`) and the measured inversions + their magnitudes are surfaced.
     Per-pair inversion magnitudes are well-defined even if the aggregate ρ is
     `None`, so the e2e read does NOT go dark on a tied-ρ render (N1). Record the
     measured ρ (or its `None`-reason) + inversion magnitudes in the chunk
     reflection. Confirm the on-disk report JSON parses (it will, since ρ is
     `None`-or-finite by construction + `allow_nan=False` backstop).
  3. **PENDING BY-EAR (DR-5):** set the "notable inversion" surfacing threshold as a
     NAMED module constant in `analyze.py` (sibling to `_MASKING_REPORTING_FLOOR` /
     `_TIMING_MIN_CONFIDENCE`), CALIBRATED against the measured inversion
     distribution from step 2 — NOT guessed. Document the calibration basis in a
     comment (the existing floors' convention). If the real distribution is
     ambiguous about the gate's exact value, leave the constant at a conservative
     surface-everything default and flag in `operator-verification.md` that the
     final tune awaits a human-ear pass (Live is unattended this run).
  4. If the density correlate's calibration (chunk 2) flagged it untrustworthy on
     real audio, the e2e read documents that and the report ships loudness-ρ as the
     primary signal with density caveated — never a confidently-wrong density ρ.
  5. Acceptance criteria met and tests pass.
  6. `/critic` run and blocking findings resolved.
  7. Committed and chunk marked `[x]` in Status.
- **Critic mode:** inferred (`chunk`).
- **PENDING by-ear:** the surfacing threshold (DR-5) — render+measure objectively,
  set the gate as a calibrated constant; final fine-tune flagged for a human-ear
  pass since Live is unattended.

### Chunk 6 — Wire into /mix-review + canonical deltas (the VERIFIABLE SIGNAL surface)

The doc/skill edits that make the lens the wired read-side surface the item requires.

- **Type:** cumulative-final (W3 — declared explicitly: this is the last chunk and the
  bundle ships as one PR, so the `Type` triggers the `/critic cumulative` pass that
  gates `/pr create`, rather than leaving it to inference. The chunk's own work is
  prose/doc + a backlog state edit — no executable code — so the `final` review's
  test-evidence checks are correctly skipped; the cumulative pass reviews the full
  `merge-base...HEAD` bundle including the code chunks. The backlog edit in criterion 5
  is prose/state, explicitly in-scope for the doc side of this chunk — it is not
  executable code.)
- **Foreign API:** none
- **Done when:**
  1. `skills/mix-review/SKILL.md` MEASURE (§2) gains the `energy_realization` feed
     bullet; INTERPRET (§3) gains the intent-gating clause (DR-4 / design §5).
     **MIX-3S7P collision (design §6):** re-read the skill before editing; the edit
     is an additive bullet in a distinct section, so it's textually independent of
     any MIX-3S7P space/atmosphere note — confirm no overlap at edit time.
  2. `arrangement-model.md` derivative-lens bullet gains the audio-realization
     sentence (design §5) — LINK to the lens, don't restate the method. Spectral
     deferral noted (DR-3, flagged-not-dropped).
  3. Tree-wide grep (the "pattern sweeps are tree-wide" learning): confirm no other
     agent-facing surface (`.claude/`, `docs/`, MCP resources) describes the energy
     read as symbolic-only now that the audio lens exists — update or backlog any
     stale reference.
  4. `/compose-review` SKILL: confirm its symbolic energy-arc read (it owns the
     compose axis) still correctly says "symbolic, render-free" and points at the
     new audio lens as the render-time complement (one sentence, not a duplication).
  5. Backlog: mark ARR-7M3D's verifiable signal met; record the spectral correlate
     (DR-3) as a flagged follow-on item.
  6. `/critic` final + cumulative run and blocking findings resolved (the cumulative
     pass is required by `Type: cumulative-final` and gates `/pr create`).
  7. Committed and chunk marked `[x]` in Status.

---

## Status

- [x] Chunk 1 — persist declared energy + read-back (thin slice)
- [x] Chunk 2 — onset-density-per-section primitive (calibrate first)
- [x] Chunk 3 — energy-realization lens (Spearman ρ + inversions, the RULER)
- [x] Chunk 4 — wire declared energy through the analysis handler
- [x] Chunk 5 — e2e objective render + by-ear threshold calibration (DEFERRED-RENDER)
- [x] Chunk 6 — wire into /mix-review + canonical deltas

**Context:** Chunks 1–4 + 6 built FULLY; chunk 5 built in DEFERRED-RENDER form
(Live unattended this run — no live render attempted; verify-api proven via the
handler/report unit path, DR-5 floor set to the conservative surface-everything
default `_ENERGY_INVERSION_SURFACING_FLOOR=0.0`, and the e2e ρ read + by-ear
DR-5 tune + density plausibility flagged in `.prawduct/operator-verification.md`).
Source-of-truth fix landed: `sections.energy` persists the curve that previously
never reached the DB. Full suite green (2846 passed, 2 skipped; develop baseline
was 2804 + 42 new tests). Per-chunk commits clean. PENDING: `/critic` (cumulative
+ final), PR, and the attended-run operator verification — all governed by the
main agent, not run here.

## Files the plan will touch (production)

- `src/hallucinote/db/schema.sql` (chunk 1 — `sections.energy` CREATE)
- `src/hallucinote/db/connection.py` (chunk 1 — `_ADDED_COLUMNS` row)
- `src/hallucinote/db/mutations/score.py` (chunk 1 — `create_section` energy param
  + `_SECTION_FIELDS`/`update_section` energy support, W1)
- `src/hallucinote/arrangement.py` (chunk 1 — `materialize` passes energy)
- `src/hallucinote/audio/onsets.py` or a new `audio/` density module (chunk 2)
- `src/hallucinote/audio/analyze.py` (chunks 2,3,5 — density wiring, lens call,
  the by-ear threshold constant)
- `src/hallucinote/audio/report.py` (chunk 3 — `EnergyRealization` dataclasses +
  serializer)
- `hallucinote_mcp/src/hallucinote_mcp/handlers/analysis.py` (chunks 1,4 —
  `_collect_sections` energy lift, `analyze_handler` wiring; chunk 3 —
  `json.dumps(..., allow_nan=False)` at analysis.py:457, B1 backstop)
- `skills/mix-review/SKILL.md` (chunk 6 — MEASURE feed + INTERPRET gate) ⚠️ MIX-3S7P
- `skills/compose-review/SKILL.md` (chunk 6 — point at the audio complement)
- `.prawduct/artifacts/arrangement-model.md` (chunk 6 — derivative-lens delta)

---

## Review resolution (revise → resolved)

Independent reviewer verdict was **REVISE** (`review.md`): 2 blocking, 3 warnings.
All resolved in the design + plan before building (each fix verified against the
real code this run, not the review's summary). Nothing dropped.

- **B1 — Spearman ρ can be `nan` (tied/constant correlate), forbidden by the shape +
  invalid JSON.** Confirmed: `scipy.stats.spearmanr([1,2,3],[5,5,5])` → `statistic=nan`
  (`ConstantInputWarning`), and `to_json_dict` → `json.dumps` at analysis.py:457 has
  no `allow_nan=False`. Resolved: DR-2 `correlate_rho` is now `dict[str, float | None]`
  with an explicit undefined-ρ contract (detect `nan` → record `None` + a `skipped`
  reason, never serialize `nan`); chunk 3 adds the tied/constant test (was omitted)
  and hardens the write path with `allow_nan=False` as a structural backstop. The
  false "ρ always lands" claim in design §2/§4/DR-5 is corrected throughout.

- **B2 — name-keyed section join mis-pairs repeated section names.** Confirmed: no
  UNIQUE on `sections.name` (schema.sql:131); `vary()`/recapitulation repeats names;
  the Nobile energy-drop two-"Chorus" case is the design's own ruler-not-stamp
  example. Resolved: the join key is now `start_beat` (carried on `SectionMetrics`
  report.py:401 and added to `EnergyInversion`/new `SectionEnergy` in DR-2), in the
  lens (chunk 3 crit 2) and the handler lift (chunk 4 crit 1). Added the chunk-3
  same-named-sections lock test (FAILS under name keying) and a chunk-4 handler test.
  Also caught a deeper point: a plain ordered-index join ALSO breaks because
  `_measure_sections` (analyze.py:454) skips out-of-capture sections —
  `per_section` is not positionally aligned — so `start_beat` is the correct key,
  not the index.

- **W1 — `update_section` drops energy.** Confirmed: `_SECTION_FIELDS` (score.py:97)
  omits `energy` and `update_section` raises on unknown fields. Resolved: chunk 1
  criterion 2a adds `energy` to `_SECTION_FIELDS` + `update_section` support with a
  test — the decision is stated explicitly (include it, since energy is a first-class
  section attribute), never silently dropped.

- **W2 — measured-side `nan` not handled.** Resolved: DR-2 + chunk 3 crit 2 now
  exclude any section whose *measured* correlate is missing/`nan` from that
  correlate's ρ (named in `skipped`), symmetric with the NULL-declared exclusion, and
  tied to the same B1 nan discipline. Chunk 3 crit 4 adds the measured-nan exclusion
  test.

- **W3 — chunk 6 Type/marker ambiguity.** Resolved: chunk 6 now declares
  `Type: cumulative-final` explicitly (was `doc-only` with a conditional note), so the
  `/pr create` cumulative gate is triggered by the Type rather than left to inference;
  the backlog state edit is confirmed in-scope for the doc side.

No residual blocking items — all fixes are spec-level and resolvable in the design
phase (the only by-ear item, DR-5's surfacing threshold, was already flagged PENDING
and is unaffected by the revisions). MIX-3S7P collision flag carried (design §6,
chunk 6 crit 1).
