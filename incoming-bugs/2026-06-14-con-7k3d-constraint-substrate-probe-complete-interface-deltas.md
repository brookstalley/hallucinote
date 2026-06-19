# CON-7K3D constraint substrate — probe complete: interface deltas from `missing`'s first build, the relational gate still unmet, and a rev-coupling alert

**Type:** design input (not a bug) — closes the "learn from the first build" loop
the design doc explicitly asks for (`declared-constraint-substrate.md:238-240`).
**Severity:** M (act before the framework rev freezes the arrangement/query model —
the promotion adapter is coupled to it; see §3).
**Refs:** `.prawduct/artifacts/declared-constraint-substrate.md` (CON-7K3D, "Status:
designed 2026-06-03 — not yet built"); songs repo `songs/missing/_constraint.py`
(the substrate shim), `songs/missing/constraints.py` (the song-owned predicates),
`songs/missing/tests/test_missing_constraints.py` (the gate).

## TL;DR

The interface probe the design doc planned (build the first song's predicates against
a song-local shim "in the substrate's eventual shape," §"When to build it" (1)) is
**done**. `missing`'s three withheld-foundation predicates authored cleanly. The shape
holds. But the design doc still says "not yet built" and carries the *first-draft*
`ConstraintCtx`/`Severity` — the probe diverged from that draft in several deliberate,
recorded ways. **Fold these deltas into the spec before any promotion to `src/`**, so
the lift stays the mechanical byte-for-byte move the design intends rather than a
re-litigation. And **the promotion gate is still unmet**: it waits for a *relational*
second song, and swell — the natural candidate — shipped non-constraint.

## 1. Interface deltas the build forced (spec draft → shipped shim)

Each is a deliberate, in-code-recorded deviation, not drift:

1. **Frozen dataclasses, not namedtuples.** The doc's sequencing note (§"When to build
   it" (1)) sketched the shim as namedtuples; the doc's *code block* uses
   `@dataclass(frozen=True)`. The shim used frozen dataclasses so the lift to `src/` is
   byte-for-byte identical shape (`_constraint.py:17-19`). Recommend the spec drop the
   "namedtuple shim" phrasing — the eventual and the shim are the same dataclasses.

2. **`Severity` is `Literal["info","warning"]` — `"blocking"` removed from the *type*.**
   The doc declares `Severity = Literal["info","warning","blocking"]` (`:89`) but its own
   guarantee #2 (`:199-202`) says a constraint finding is *never* blocking. The shim
   resolved that contradiction by making it unrepresentable (`_constraint.py:33`):
   `"blocking"` stays reserved for the LNT-1V9K technical-error class and is not a value
   a `ConstraintFinding` can hold. Recommend tightening the spec's type the same way.

3. **`ConstraintCtx` lost `progression`, gained bar-local beat helpers.** The draft ctx
   carried `progression: Progression | None` and only `bar_of()`. All three of
   `missing`'s predicates are vertical+temporal and **never touched `progression`**, so
   the shim dropped it (recorded as a PROBE NOTE, `_constraint.py:57-62`). Authoring
   *did* force two helpers the draft lacked — `beat_in_bar()` and `is_strong_beat()`
   (`_constraint.py:76-84`): the kick-on-3 and root-landing rules need bar-local beat,
   not just which bar. Net ctx surface that the vertical+temporal corner actually
   requires: `section, start_bar, end_bar, beats_per_bar, key_pc, mode` +
   `bar_of/beat_in_bar/is_strong_beat`. `progression` and any cross-section view remain
   **undesigned** — correctly, per the doc's own open question (`:284-290`).

4. **The combined section surface must tag each note with its `track`.** The doc's
   `section_constraint_inputs` returns `SectionConstraint`s but the signature says
   nothing about per-note track identity. The probe found it *load-bearing*: the root
   rule scopes to the Lead only (the tonic E is a legit inner voice / weightless bass
   5th of the rootless `iv`), and the register rule must exclude the drum rack (GM
   percussion numbers are timbre indices, not pitch register) — see `constraints.py:24-34`.
   Both are impossible without a `track` tag on each note. Recommend the spec mandate
   that the combined surface tags every note with its track (`_constraint.py:163-176`).
   This empirically answers the doc's "vertical vs horizontal / predicate picks its
   slice" open question (`:291-295`): slicing works, but only given the tag.

5. **Constraints are applied at analyze time, not bundled into the inputs.** The draft
   threads `constraints=` through `section_constraint_inputs(...)`; the shim keeps inputs
   as pure data and passes constraints to `analyze_constraints(inputs, constraints)`
   (`_constraint.py:125-138`). Cleaner separation — inputs are reusable across constraint
   sets. Minor, but recommend the spec adopt it.

6. **`ConstraintReport.violations` defined = warnings only.** The doc references
   `assert report.violations == ()` (`:208`) without defining `violations`. The shim
   defines it as the `warning`-severity findings; `info` findings are coaching and do
   **not** count as violations (`_constraint.py:117-122`). `missing`'s gate asserts
   `report.violations == ()` (`test_missing_constraints.py`). Recommend codifying this.

## 2. The promotion gate is still unmet (swell went non-constraint)

The doc is explicit (§"When to build it" (2), and open-question `:284-290`): promote to
`src/` only after a **deliberately relational / cross-section** second song has been
felt against `ctx` — not after a second *withholding* song that re-confirms the
vertical+temporal corner. As of this rev there is still exactly **one** constraint song
(`missing`), and all three of its predicates are that same corner.

swell — the other song now in the workspace — was the natural second candidate, but it
shipped **without** the constraint substrate (its "constraint" mentions are prose in
decision docs, not predicates). So the relational corner remains unexercised, and
`ConstraintCtx` should **not** be frozen yet. If the rev wants to unblock promotion, the
cheapest path is to commission one relational predicate on an existing song (e.g. a
"no parallel fifths between bass and lead" or "this chorus's pitch-set must differ from
the last" rule) specifically to pressure-test a `progression` / whole-arrangement ctx
variant.

## 3. Rev-coupling alert — the promotion adapter binds to the arrangement/query model

This is the rev-timed part. The shim's `section_constraint_inputs()` (the DB adapter
that the eventual `Arrangement.section_constraint_inputs()` replaces) depends on a
specific surface (`_constraint.py:141-187`). **If this rev restructures any of it, both
the shim and the eventual framework adapter spec must move with it:**

- `hallucinote.db.queries`: `get_tracks_for_song`, `get_sections_for_song`,
  `get_clips_for_track`, `get_notes_for_clip` (names + signatures).
- `clip["section_role"]` as the section↔clip matching key.
- Schema field names read by hand: `track["id"]`/`["name"]`, `clip["id"]`,
  `section["name"]`/`["start_bar"]`/`["end_bar"]`, note `pitch`/`start_beats`/
  `duration_beats`/`velocity`.
- **The section-relative-beat invariant** — every clip in a section starts at the
  section's first bar, so clip-local beats pass straight to `bar_of/beat_in_bar`
  unchanged. The whole ctx beat math assumes this; if the rev changes how clip times
  relate to section origin, the predicates silently misfire.

## Suggested next action

1. Fold §1's six deltas into `declared-constraint-substrate.md` and flip its status to
   "probed (2026-06-14) — promotion pending a relational second song."
2. Note the §3 bindings wherever the rev tracks arrangement/query-model changes, so the
   constraint adapter doesn't get orphaned by the refactor.
3. Keep the substrate **out of `src/`** this rev unless a relational song is commissioned
   to exercise the `progression`/cross-section ctx first.
