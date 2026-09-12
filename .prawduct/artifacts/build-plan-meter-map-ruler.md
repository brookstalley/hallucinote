---
artifact: build-plan
version: 2
scope: meter-map-ruler
branch: feat/566-meter-map
depends_on:
  - artifact: arrangement-model
  - artifact: data-model
governed_by:
  - artifact: arrangement-model
    dispositions:
      - "meter-feel(ii) literal meter stays a CANDIDATE until a second odd-meter song forces it → amendment proposed: `alien` is that song; this plan promotes it to a built structure intent (Chunk 05 writes the amendment)"
      - "a dimension is a ruler + (ideally) a read-side lens (BOTH SIDES) → conforms: Chunks 02-03 are the ruler, Chunk 04 the reads"
  - artifact: data-model
    dispositions:
      - "the SQLite DB is materialized state, never the source of truth → conforms: the song's meter is declared in build.py on the Arrangement and materialized into time_signature_map, not edited in the DB"
      - "all writes go through mutators; no write SQL in callers → conforms: materialize authors meter via M.add_time_signature_point, and the retiming check reads through conn.execute SELECTs only"
      - "every mutator emits exactly one event, in the same transaction as its state change → conforms: no mutator is added or changed; add_time_signature_point's existing emit is untouched"
      - "identity is a Python-generated UUID from the mutators, never a database rowid → inapplicable because this plan adds no table, no row identity and no id-bearing column"
      - "Live's own identifiers are never used as identity → inapplicable because nothing here reads or stores a Live id"
      - "an existing song DB is opened through init_db, never a bare connect → conforms: no new open path; schema.sql's change is comment-only, so no _ADDED_COLUMNS migration is owed"
partition: serial — 02 needs 01's value type, 03 needs 02's plan output, 04 needs 03's PlacedSection fields
last_validated: 2026-09-12
---

## Requirements Confidence

**Level:** High

**Why:** The requirement is written out as R1-R6 with acceptance criteria in
[#566](https://github.com/brookstalley/hallucinote/issues/566); the issue is the spec and
this plan does not re-derive it. The two open design forks were put to the owner
2026-09-12 and answered: the authoring surface is **map points plus per-section
sugar**, and the read side ships **with** the authoring fix (#247's BOTH-SIDES rule).
#567 rides along because R2 is what makes its advice wrong.

**Open assumptions / unknowns:**

- [ASSUMPTION: Live anchors arrangement content in BEATS, so adding a meter change by
  hand relabels the ruler without moving what is already placed | HIGH impact on R1's
  claim, ZERO impact on this plan's code | resolved only at a Live console]
  This is #566's "design note — the assumption to confirm first". It is **not** a
  blocker for the build: every position this plan authors resolves to absolute beats
  through the map whether or not Live's ruler agrees, which is precisely what R1 asks
  for. What the assumption gates is the *claim we make to the operator* in Chunk 05's
  rewritten alert — that the hand-add is safe and optional. Enqueued in
  `operator-verification.md`; Chunk 05 may not claim "safe" until it clears.

- [ASSUMPTION: no existing song authors a `time_signature_map` that its `Arrangement`
  does not also declare | LOW impact | checked 2026-09-12 across all 12 songs in
  `hallucinote-songs`: only `sun-zone-done` constructs `Arrangement(beats_per_bar=…)`,
  and every song's map is bar-1 only, so Chunk 03's equality assert has nothing to
  trip on today]

**What would raise confidence:** the Live probe above.

## Status

- [x] Chunk 01: `hallucinote.meter` — one bar ruler, as a value type
- [x] Chunk 02: `Arrangement` declares meter; `plan()` walks the map (R2, R6)
- [x] Chunk 03: `materialize()` authors the map, stamps `map`, refuses divergence (R3, R4)
- [x] Chunk 04: the read side reads the map (R5)
- [ ] Chunk 05: the push alert tells the operator the truth (#567) + artifact amendment

Context: All five chunks are built on `feat/566-meter-map`, and the `cumulative`
Critic review (`rev-20260912T143558Z-dfbc97bb`) has run — 5 blocking, 13 warning,
7 note — with every finding dispositioned in one pass and the fixes folded into a
single commit. What that review moved, beyond paperwork:

- **The author-facing docs were the real gap** (R-10, blocking). The bundle moved the
  ruler in `src/` and amended the `.prawduct/` artifacts, and left every document that
  *instructs the composing agent* still describing the two-ruler world — including the
  file seven skills cite. Chunk 05's Deliverables now name that sweep, because it was
  a deliverable all along and the plan had not said so.
- **The R4 guard was point-in-time** (R-5 / R-19). `materialize()` checks map agreement
  when it runs, so meter written AFTER positions exist was unguarded — and worse than
  before, because those rows now carry `map` and the push detector drops `map` rows by
  design. Closed where the map changes rather than where positions are written:
  `add_time_signature_point` warns when the write actually moves an existing position's
  resolved beat. It asks whether beats MOVE, not whether the map was touched, so the
  ordinary order (meter first, then materialize, then a state-converger re-run) is
  silent — the first cut of it fired on four existing tests, which is what a warning
  every build prints looks like before you catch it.
- **The alert was hedged** (R-7 / R-20). It told the operator the hand-add "changes
  nothing" while METER-0912 — this branch's own probe of exactly that — is PENDING, and
  this plan's own Requirements Confidence forbids claiming safe until it clears.
- **A grading surface shifted silently** (R-9). `BarGrid` clamped at its last bar where
  `start % beats_per_bar` extrapolated forever, so a note overhanging a section's
  declared length re-graded. It extrapolates now, continuing the last bar's own meter.

Chunk 05's box stays unticked until `verify-resolutions` clears — ticking the last box
is what disarms the Stop gates.

**Two deviations from this plan as written, both deliberate:**

- **Chunks 02-04 share one commit.** They are `arrangement.py`'s `plan()`,
  `materialize()` and its four lens bridges, plus the two melody modules the fourth
  reaches into. Splitting them would mean staging hunks of one file into three
  commits, none of which is independently green — 04 is largely the *consequence* of
  02 carrying beats on `PlacedSection`, not separable work.
- **Reviews roll up rather than running per chunk.** Per this repo's own learning
  (`feedback_critic_cadence_for_small_chunks`) and the Session Scope rule — the honest
  unit is a risk surface, and all five chunks are one: the bar ruler. One `cumulative`
  covers the whole diff.

**Deliberately NOT in this plan:** re-authoring `alien` on the meter map. It is #566's
last acceptance criterion and it stays unticked when this plan closes — the owner
declined it for this branch (2026-09-12), and it lives in the separate
`hallucinote-songs` repo against a song carrying live by-ear edits.

**What re-authoring `alien` takes, so the next session need not re-derive it.** In
`songs/alien/build.py`: declare `meter_change(at_bar=86, "7/4")` and
`meter_change(at_bar=87, "4/4")`, then delete the `HANG_BARS = HANG_BEATS / 4.0`
block (= 0.75) and the `bar N + HANG_BARS` anchoring of every section from THE HANG
on. chorus3 returns to bar 89 and the outro to bar 113 — both INTEGER, both at the
same absolute beats they already sit on (355 and 451, which
`tests/unit/test_meter.py::test_alien_s_hang_puts_the_landing_where_the_fraction_did`
asserts from both directions). Two stale claims in that file's header die with it:
that `add_time_signature_point` "refuses any start_bar > 1.0" (#221 made that false
months ago) and that `overview-drift` must report chorus3 and outro as MOVED by 0.75
forever. The by-ear edits are all in absolute beats and none of them move.

## Verification Strategy

Each chunk's tests are the contract. Beyond them, two whole-tree checks that only mean
something once the parts are together:

1. **The two rulers agree, by construction.** A test song with a mid-song meter change
   is planned through `Arrangement.plan()` and, independently, resolved through
   `sync.geometry._position_bar_to_beats` against the materialized DB map. Every
   section boundary must land on the same absolute beat. This is #566's first
   acceptance criterion and it is the test that would have caught the `alien`
   misplacement.
2. **The uniform ruler is unreachable.** A test greps `src/` for a writer that stamps
   `bar_ruler="uniform"` and asserts there is none (R3). The string survives in the
   schema, the migration and the legacy *detector*; it may not survive in a *writer*.

## Project Structure

```
src/hallucinote/
├── meter.py                  # NEW — the one bar ruler (leaf; imports nothing from hallucinote)
├── arrangement.py            # declares meter, plans against it, materializes it
├── melody/
│   ├── lens.py               # SectionMelody carries a bar grid, not a scalar
│   └── harmony_fit.py        # the strong-beat read becomes per-bar
└── sync/
    ├── geometry.py           # rebuilt on hallucinote.meter; public behavior unchanged
    └── push/tempo.py         # the reach-limit alert (#567)
```

### Module Boundaries

`hallucinote.meter` is a **leaf**: no imports from anywhere else in `hallucinote`, so
both the authoring side (`arrangement`) and the sync side (`geometry`) can depend on it
without either depending on the other. `arrangement` must never import `sync` — that
inversion is how the two rulers would grow back.

`MeterMap` is a pure value type. DB rows enter it through one adapter
(`MeterMap.from_rows`); nothing else in the tree walks `time_signature_map` by hand
after this plan.

## Build Chunks

### Chunk 01: `hallucinote.meter` — one bar ruler, as a value type

- **Description:** Extract the meter walk that `sync/geometry.py` already implements
  correctly into a neutral, DB-free value type, so the authoring side can use the
  *same* ruler push uses instead of a second one. Nothing about push's behavior
  changes; this is the move that makes Chunk 02 possible without an import inversion.
- **Depends on:** none
- **Artifacts consumed:** `data-model.md` (`time_signature_map`), `db/schema.sql:181-190`
  (the two-ruler comment — the canonical statement of the problem)
- **Deliverables:** new `src/hallucinote/meter.py` carrying:
  - `MeterPoint(start_bar: float, numerator: int, denominator: int)` — frozen
  - `MeterMap` — an ordered, validated set of points with a bar-1 point always present;
    `beats_at(bar) -> float`, `meter_at(bar) -> tuple[int, int]`,
    `beats_per_bar_at(bar) -> float`, `split_bar(bar) -> (int, float)`,
    `join_bar_beat(bar, beat) -> float`, `bar_at_beats(beats) -> float`
  - `MeterMap.from_rows(rows)` — the one adapter from `time_signature_map` rows
  - `MeterMap.uniform(beats_per_bar)` — the 4/4-ish default, and the bridge from the
    `beats_per_bar` scalar Chunk 02 retires
  - `parse_meter("7/4") -> (7, 4)` — the authoring spelling
  - `src/hallucinote/sync/geometry.py` reimplemented on it: `_meter_at_bar`,
    `_split_bar`, `_position_bar_to_beats`, `_join_bar_beat`, `_beats_to_position_bar`
    and `uniform_bar_math_divergences` keep their signatures and behavior and delegate
    the arithmetic.
- **Tests:** unit — `tests/unit/test_meter.py`: the walk across a mid-song change in
  both directions (`beats_at` / `bar_at_beats` round-trip), a denominator that is not 4
  (6/8 → 3 beats, 7/8 → 3.5), bars before the first point, an empty map, a fractional
  bar inside a changed region, and a single borrowed bar (4/4 → 3/4 at bar 9 → 4/4 at
  bar 10) shortening the song by one beat. `geometry`'s existing tests are the
  behavior-preservation contract and **do not change**.
- **Acceptance criteria:** the full suite passes unchanged; `import hallucinote.meter`
  pulls in nothing else from the package.
- **Type:** refactor
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 02: `Arrangement` declares meter; `plan()` walks the map (R2, R6)

- **Description:** The heart of the item. `Arrangement` stops accumulating
  `bar += s.bars` against one `beats_per_bar` and places every section by walking its
  declared `MeterMap`. The arrangement becomes the authoring surface for meter — the
  one place a composer says what the song's meter is.
- **Depends on:** Chunk 01
- **Artifacts consumed:** #566 R2 and R6; `arrangement-model.md` §1 (meter-feel(ii))
- **Deliverables:**
  - `Arrangement(meter="4/4")` — the bar-1 default in num/den form. `beats_per_bar=`
    is kept as the scalar spelling of the same bar-1 default (`beats_per_bar=3.0` →
    3/4) because a song already passes it; the two are **mutually exclusive** and
    passing both raises. R6 is satisfied by there being one *declaration* (the map),
    not by deleting a keyword.
  - `Arrangement.meter_change(at_bar: float, meter: str)` — an explicit map point.
  - `Arrangement.section(..., meter: str | None = None)` — the per-section sugar the
    owner chose. **It is sugar for exactly one thing: a map point at that section's
    start bar.** The meter then persists until the next point, because that is what
    the map means; a section does not "own" a meter and does not restore the previous
    one at its end. A borrowed bar therefore reads
    `meter_change(at_bar=86, "7/4"); meter_change(at_bar=87, "4/4")`, and the docstring
    says so with that example. Two declarations landing on the same bar with different
    meters raise at author time.
  - `Arrangement.meter_map` — the resolved `MeterMap` property, so a composer can print
    what they actually declared. Sugar that is not inspectable is how a second ruler
    hides.
  - `PlacedSection` gains `start_beat: float` and `length_beats: float`, both
    map-resolved. These are what make the four lens bridges in Chunk 04 stop doing bar
    arithmetic of their own.
  - `plan()` resolves `offset_beats` / `section_len_beats` from the map (the harmony
    slice already consumes them, so `progression="inherit"` becomes meter-correct for
    free).
- **Tests:** unit — a 4/4 song turning 7/4 at bar 9 puts section boundaries where
  `geometry._position_bar_to_beats` puts them (the exact case
  `arrangement.py`'s docstring predicted and could not fix: bar 13 at beat 60, not 48);
  a borrowed 3/4 bar shortens the arrangement's total beats by one; `progression=
  "inherit"` slices at map-resolved offsets across a change; `beats_per_bar=` and
  `meter=` together raise; conflicting declarations at one bar raise; an
  all-4/4 arrangement plans byte-identically to today (the regression floor).
- **Acceptance criteria:** #566 acceptance 1 — a mid-song meter change places every
  section at the same absolute beat via `plan()` as via a direct map-resolved call.
- **Exposed API:** `hallucinote.arrangement` — consumed by every song's `build.py` in
  the separate `hallucinote-songs` repo. Additive only: no existing call signature
  changes meaning, and an arrangement that declares no meter behaves exactly as before.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 03: `materialize()` authors the map, stamps `map`, refuses divergence (R3, R4)

- **Description:** Close the loop between the two stores of the same fact. The
  arrangement writes its declared meter into `time_signature_map`, stamps every row it
  writes `map` instead of `uniform`, and refuses to materialize when the DB's map and
  its own disagree — which is #566 R4's "a divergence is a defect and should fail
  where it is introduced".
- **Depends on:** Chunk 02
- **Artifacts consumed:** #566 R3 and R4; `db/mutations/score.py:359`
  (`add_time_signature_point`), `db/schema.sql:181-190` (the `bar_ruler` column)
- **Deliverables:**
  - `materialize()` authors each declared `MeterPoint` through
    `M.add_time_signature_point` before it writes any positioned row. The mutator is
    already idempotent on an identical point, so a `build.py` that also authors its own
    bar-1 row (all 12 songs do) is unaffected.
  - Every `create_section` / `add_cue_point` / `add_arrangement_clip` call in
    `materialize()` drops `bar_ruler="uniform"` and takes the mutator's `map` default
    (R3). The long docstring paragraph explaining why this class stamps `uniform`
    is deleted, not amended — it documents a ruler that no longer exists.
  - A read-back check: after authoring, `Q.get_time_signature_map` must equal the
    arrangement's own map. A mismatch raises with both maps named and the first
    diverging bar identified. This is the author-time error R4 asks for, and it is the
    thing that makes "two places to declare it" impossible rather than merely
    discouraged.
  - `Arrangement`'s class docstring loses its "**Single meter only**" paragraph and the
    `ARR-4M3T` pointer; it gains the worked borrowed-bar example.
- **Tests:** unit — materializing an arrangement with a declared change writes the map
  points and stamps every row `map`; a DB whose map already holds a *different* meter
  at some bar raises, naming the bar; a DB holding the *same* map does not raise;
  no row written by `materialize` carries `uniform`. Tree-wide — the grep test from
  Verification Strategy §2.
- **Acceptance criteria:** #566 acceptance 2 and 3 — the two-ruler divergence is
  unreachable from `hallucinote.arrangement`, and a diverging map fails at author time.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 04: the read side reads the map (R5)

- **Description:** #247's BOTH-SIDES rule: the authoring surface and the reads land
  together. The measured cost is far below #566's 138-call-site estimate, and the
  reason is worth recording — **most `beats_per_bar` call sites are not the song's
  ruler.** The 74 sites in `generators/` (drums 41, bass 17, harmony 16) are a
  *pattern's* bar length, a legitimate per-call parameter that a 7/4 bar should be able
  to set freely; touching them would be scope creep, not correctness. The sites that
  genuinely mis-grade an odd bar are the four arrangement bridges and one strong-beat
  predicate.
- **Depends on:** Chunk 03
- **Artifacts consumed:** #566 R5; `arrangement.py:319,336,366,394` (the four bridges)
- **Deliverables:**
  - `section_lints`, `section_perf_inputs`, `section_melody_inputs` and
    `section_recurrence_inputs` take their `length_beats` / `start_beat` from
    `PlacedSection` (Chunk 02) instead of multiplying by `self.beats_per_bar`. Three of
    the four need nothing else — their meter-awareness is a consequence of Chunk 02,
    not new code.
  - `melody/lens.SectionMelody.beats_per_bar` (a scalar) becomes a **bar grid**: the
    section-relative beat offsets of its bar lines plus each bar's length, produced by
    `MeterMap.grid_for(start_bar, end_bar)`. `MeterMap.uniform(4.0).grid_for(...)`
    reproduces today's behavior exactly, so a single-meter song's melody report does
    not move.
  - `melody/harmony_fit._is_strong_beat(start_beats, beats_per_bar)` becomes
    `_is_strong_beat(start_beats, grid)`: find the bar the beat falls in, then test its
    downbeat and its own midpoint. A 13/16 bar's strong beats are 13/16's, not the
    song's.
- **Tests:** unit — a section spanning a meter change reports the right `length_beats`
  through all four bridges; a note on beat 0 of a 7/4 bar reads strong and a note on
  beat 2 of it does not (where the old scalar read said it did); `MeterMap.uniform`
  grids reproduce the pre-change melody report on an existing single-meter fixture
  (the regression floor — this is a grading surface and a silent shift in it is worse
  than a loud break).
- **Acceptance criteria:** #566 acceptance 4 — a lens reading strong beats across a
  13/16 bar in a 3/4 song reads that bar's meter, not the song's.
- **Exposed API:** `hallucinote.melody` — and unlike Chunk 02's, this one is
  **breaking, not additive**. `SectionMelody.beats_per_bar` (a float) becomes
  `bars` (a `BarGrid`), and `analyze_harmony_fit(..., beats_per_bar=)` becomes
  `bars=`. Four songs in the separate `hallucinote-songs` repo construct
  `SectionMelody(...)` directly (punk-fate, swell, the-argument, audio-hearing).
  **Versioning call: break it, with no shim.** The check was run across all 12
  songs and none passes either keyword — every one relies on the 4/4 default,
  which `bars=None` reproduces exactly — so a compatibility shim would carry a
  scalar nobody passes and re-admit the ambiguity (3 beats is 3/4 or 6/8) the
  grid exists to remove. The change-log carries the migration line for a song
  that does pass it later: `beats_per_bar=n` → `bars=MeterMap.uniform(n).grid_for(start_bar, end_bar)`.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 05: the push alert tells the operator the truth (#567) + artifact amendment

- **Description:** Land [#567](https://github.com/brookstalley/hallucinote/issues/567)
  on the surface this plan just made honest, and record the decision in the artifact
  that governs it. The alert's current advice — "the felt meter has to live in note
  placement and accent" — predates #221 and is *actively wrong* after Chunk 02: the
  song's literal meter now lives in the map and every position resolves through it.
- **Depends on:** Chunk 04
- **Artifacts consumed:** #567; `src/hallucinote/sync/push/tempo.py`;
  `.prawduct/artifacts/arrangement-model.md` §1
- **Deliverables:**
  - `src/hallucinote/sync/push/tempo.py` — `plan_push_time_signature_map`'s alert names each non-bar-1 point as
    `bar N -> num/den`, in bar order, as an **optional** hand-add for Live's ruler, and
    drops the accent advice. The reach limit itself stays stated on the same channel —
    it is still true and this is still its one home.
  - `.prawduct/artifacts/arrangement-model.md` §1: meter-feel(ii) is promoted from
    **candidate** to a built structure intent, with the rationale (`alien` is the
    second odd-meter song the entry named as the trigger) and what it cost. The
    candidate-vs-built sentence is amended, not appended to.
  - **Every author-facing description of the retired ruler**, which is where the
    composing agent actually reads: `docs/song-authoring-conventions.md` (the Meter
    section — cited by seven skills), `docs/known-issues.md`, `docs/song-workflow.md`,
    `docs/song-new-checklist.md`, `skills/song-new/SKILL.md`,
    `skills/song-brief/SKILL.md` and
    `.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`. Moving the ruler in
    `src/` and amending only the `.prawduct/` artifacts leaves the instructions that
    produce next session's song saying the opposite of the code.
  - The three DB carriers that still assert the retired rule in the present tense:
    `src/hallucinote/db/mutations/arrangement.py`, `src/hallucinote/db/mutations/score.py`
    and `src/hallucinote/db/connection.py`.
  - `src/hallucinote/arrangement.py` module docstring, `.prawduct/artifacts/data-model.md` and `src/hallucinote/db/schema.sql`:
    `uniform` is described as provenance on historical rows, not as a live ruler.
  - `.prawduct/operator-verification.md`: the Live-anchors-in-beats probe, written as
    the two-minute check it is — open `alien`'s set, note a downstream clip's
    `position_beats`, add the 7/4 at bar 86 by hand, read it back.
  - A note, in this plan's Status block, of what re-authoring `alien` on the map would
    take — the `HANG_BARS = 0.75` block, the sections anchored at `bar N + HANG_BARS`,
    and the stale comment claiming `add_time_signature_point` "refuses any start_bar >
    1.0" (#221 made that false).
- **Tests:** unit — the alert names every non-bar-1 point in bar order; the alert does
  not contain the accent advice; the reach limit is still stated. Doc parity — whatever
  `test_song_lifecycle_doc_parity` / `test_overview_drift` style checks cover the
  amended artifacts.
- **Acceptance criteria:** #567's Expected, verbatim; `arrangement-model.md` no longer
  calls literal meter a candidate.
- **Type:** cumulative-final
- **Visual change:** no
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed, then `/prawduct:critic cumulative` run and blocking findings resolved
  3. Chunk marked `[x]` in Status

## Early Feedback Milestone

**Milestone chunk:** 02
**What the user can do:** declare `meter_change(at_bar=86, "7/4")` on an `Arrangement`
and see `plan()` put every downstream section on an integer bar at the absolute beat
push would compute for it — the thing `alien` currently spells `bar N + 0.75`.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic review passes. Chunk 05's
`cumulative` review makes the branch PR-ready; `/prawduct:pr create` runs when the user
asks.

- After Chunk 01: confirm `hallucinote.meter` is genuinely a leaf before anything
  depends on it — a cycle here is the import inversion that regrows the second ruler.
- After Chunk 03: the two whole-tree checks in Verification Strategy both run. If
  either is red, stop: the plan's premise has failed, not one chunk.
- Before merge: the operator-verification entry is enqueued, not cleared. It does not
  block this branch (see Requirements Confidence) but it must not be lost.
