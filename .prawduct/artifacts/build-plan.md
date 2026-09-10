---
artifact: build-plan
version: 1
scope: OPENBUGS-0910
branch: fix/lens-partials-and-capture-playhead
depends_on:
  - artifact: api-contract
  - artifact: boundary-patterns
governed_by:
  - artifact: api-contract
    dispositions:
      - "Refuse-and-teach over silent wrong behavior, at every boundary → conforms (02 replaces a silent wrong-baseline capture with a verified park-at-0, and refuses outright while the transport rolls; 01 replaces a silently inflated economy with one that counts only what it can call a recall)"
      - "Errors teach — structured recovery information, never a bare string → conforms (02's playing-transport refusal names the transport state and the fix; 01's exit-3 hint stops pointing at a song that does not define the function and describes both authoring shapes instead)"
      - "The MCP surface is versioned by content fingerprint, never a hand-maintained number → inapplicable because neither chunk changes a fingerprinted path (02 CALLS two existing MCP actions from the CLI side; it adds none)"
      - "No compatibility shims for consumers that cannot exist; one-major-version aliases → conforms (both chunks add fields/params with defaults that reproduce today's behavior for every existing caller — no shim, no alias)"
      - "Mutator signatures are keyword-only after conn, and every mutator accepts actor/reason → inapplicable because neither chunk touches a mutator"
      - "Timing transforms stay in the engine and off the MCP surface → inapplicable because neither chunk touches timing"
      - "The MCP tool surface stays inside the band where tool-selection accuracy holds → conforms (no tool and no action is added)"
      - "These interfaces stay internally scoped → conforms (nothing changes about what is published)"
partition: >
  serial — two chunks, disjoint files, but small enough that delegation costs
  more than it saves (each is one source module plus its tests, and the
  coordinator would still own the combined suite, the Critic and every state
  update). Chunk 01 owns `recurrence/{lens,economy}.py` +
  `tools/recurrence_lens.py` + their tests; chunk 02 owns
  `tools/capture_cli.py` + `skills/song-snapshot/SKILL.md` + its tests. No file
  is named by both.
last_validated: 2026-09-10
---

## Requirements Confidence

**Level:** High for chunk 01, Medium for chunk 02.

**Why:** Both defects come from operator reports written against `songs/alien` on
2026-09-10 (`incoming-bugs/2026-09-10-recurrence-lens-partials-and-wiring-pointer.md`,
`incoming-bugs/2026-09-10-capture-execute-bakes-automated-values-as-baselines.md`), and
both were re-verified in the tree at `446f732` before this plan was written rather than
taken from the report text — the verification note appended to each report names the
lines that still carry the defect.

Chunk 01 is High: the whole mechanism is pure, in-process and covered by unit tests that
run without Live. Chunk 02 is Medium for one reason named in its assumptions — the fix
depends on how Live re-applies automated parameter values on a locate, which cannot be
exercised from this session.

**What each defect actually costs, since that shapes the fix:**

- **01.** The report describes partials burying recalls in the CLI render and inflating
  `compression_ratio`. Reading the code found a third consequence the report did not
  name, and it is the worst of the three: `economy._recurring_motifs` counts a motif as
  recurring on *any* non-home recall, so 50 %-coverage derived partials on every layer in
  every section make `recall_coverage` read 100 % and empty `never_recalled` — which
  silences the one coaching question the economy path is allowed to emit
  (`registered-never-recalled`). The noise does not merely bury the signal; it deletes a
  finding.
- **02.** `replay_capture` re-asserts a captured baseline on every rebuild, so a value
  captured at the end of the arrangement permanently redefines the value every envelope
  rides from. The report observed five such corruptions in one session, each silent, each
  indistinguishable in the diff from a deliberate by-ear tweak.

**Open assumptions / unknowns:**

- [ASSUMPTION: seeking to beat 0 makes Live re-apply every automated parameter to its
  beat-0 value before the capture probes read it | HIGH impact | owner can override]
  This is the report's own recommendation and it matches what the report measured (the
  same parameters read different values at beat 0 than at the end), but the settle
  behaviour when the transport is *stopped* is not provable from this session. The
  mitigation is in the design rather than in hope: the seek goes through
  `ableton_session(action='seek')`, whose handler already settle-verifies and returns
  `settled_beats`, and chunk 02 refuses to capture unless that read-back confirms 0. If
  Live turns out to need a further yield before parameter values follow the playhead, the
  symptom is a snapshot that still shows end-of-song values with the playhead reading 0 —
  named in the operator-verification entry as the thing to look for.
- [ASSUMPTION: 0.75 is the right default recall-coverage floor | MED impact | owner can
  override] Whole-motif ops score 1.0 and the observed noise floor is derived partials at
  exactly 0.50, so any threshold in (0.5, 1.0] separates them; 0.75 is the filter the
  report's author wrote by hand and reported as "a reading I could act on". The threshold
  is a parameter with a default, not a constant, so overriding it is a call-site change.
- Live cannot be driven from this session — the standing limit in `learnings.md`. Chunk 02
  lands with unit coverage against a fake probe plus an `operator-verification.md` entry;
  the fake cannot prove the Live-side behaviour and this plan does not claim it does.

**What would raise confidence:** running chunk 02's operator-verification entry against a
set with automation on a return (the `alien` A-Reverb decay is the sharpest witness: 6.87 s
at the end vs 2.50 s at beat 0).

## Status

- [x] Chunk 01: a sub-threshold partial is still reported, but stops counting as a recall
- [x] Chunk 02: `capture execute` parks the playhead at 0, or refuses to capture

Context: cut from `origin/develop` @ `446f732`. Both defects are the two reports left
open by the 2026-09-10 incoming-bugs triage; the other two reports from that triage were
verified already-fixed and archived in the same pass. Built serially in one session;
suite green at every chunk close — the evidence store carries the per-tree result, so
no total is copied here to drift — and each new test was mutation-checked by reverting
the mechanism it names.

No backlog items were filed. Both defects arrived through `incoming-bugs/` rather than
the backlog and were fixed in the same pass, so an item would have been opened and
shipped in one motion; the record lives in the change-log entry and in the two archived
reports. Chunk 02's Live-side assumption is queued in `operator-verification.md`.

**What the build found that the plan did not.** A coverage-only floor — the obvious
reading of the report's own fix — would have demoted `fragment[a,b)`, the matcher's
structured claim that a layer quotes a named sub-window of the motif, to the same status
as the tier-4 derived reading it falls back to when nothing clean matches. The report's
author had already resolved this by hand (their filter kept every non-derived variation
at any coverage) and the plan missed it. Caught by reading the matcher rather than the
label; recorded as a decision below, and the plan was amended before the code was.

## Chunk 01 — a sub-threshold partial is still reported, but stops counting as a recall

**Delivers.** A `min_coverage` floor (default 0.75) that separates a *recall* from an
honest *partial*, applied so that the partial is never dropped — REC-4Z8Q wants partials
reported — but stops being counted as a recall by the economy summary and stops
outnumbering the recalls in the render.

**Design.** The threshold marks, it does not filter:

1. `lens.MotifRecall` gains `partial: bool = False`. `analyze_recurrence` gains
   `min_coverage: float = DEFAULT_MIN_RECALL_COVERAGE` and sets `partial=True` on a
   recall that is BOTH below that floor AND from the matcher's derived tier (see the
   decision "A partial is a weak *reading*, not merely a low number"). Every
   occurrence still reaches the report and `to_dict()`, so `--json` consumers keep
   seeing everything.
   `match.MatchResult` gains `derived: bool = False`, set at the one site that builds
   a `derived (<op>, <coverage>)` label, so the tier is read from the match rather
   than prefix-matched out of a human-facing string.
2. `RecurrenceReport` carries `min_coverage` so the render can name the threshold it
   applied rather than hardcoding a number next to one that could change.
3. `economy.summarize_economy` and `economy.economy_finding` ignore `partial=True`
   recalls for the cell-set, `recall_coverage`, `never_recalled`, `recalled_note_mass`
   and `occurrence_records`. The default `partial=False` means every existing caller and
   test keeps its current behavior.
4. `tools/recurrence_lens.py` lists whole recalls per section and folds the partials into
   one line per section (`+ N partial(s) below 75% coverage — --all to list`); `--all`
   expands them inline. The header counts recalls and partials separately.
5. The wiring hint stops naming `songs/sun-zone-done/build.py`, which defines no
   `recurrence_report()`, and stops implying `analyze_arrangement` is the only shape — a
   song whose notes never pass through an `Arrangement` cannot use it. Both the module
   docstring and the exit-3 message describe the two shapes inline instead of pointing at
   a file this repo does not even carry.

**Acceptance criteria.**

- A 0.50-coverage derived partial is present in `report.recalls` and in `to_dict()`, with
  `partial: true`.
- That same partial does not make its motif count as recurring: a motif whose only
  non-home recalls are partials appears in `never_recalled` and raises the
  `registered-never-recalled` finding.
- `recalled_note_mass` and `occurrence_records` exclude partials.
- The render prints partials as a per-section count line, and `--all` expands them.
- The exit-3 hint names neither `sun-zone-done` nor `analyze_arrangement` as the only path.
- Every existing recurrence test passes unchanged.

**Done when:** the above hold, `tests/unit/recurrence/` + `tests/unit/tools/test_recurrence_lens_cli.py` are green, and the full suite is green.

## Chunk 02 — `capture execute` parks the playhead at 0, or refuses to capture

**Delivers.** A capture whose baselines are deterministic instead of playhead-dependent.

**Design.** Before `assemble_snapshot_via_probes` walks anything, `_cmd_execute` reads
`ableton_session(action='info')` and then:

- **transport rolling** (`is_playing` true) → refuse (exit 2) with a teaching error. A
  capture taken while the transport moves reads each parameter at whatever beat the probe
  happened to land on, so no seek can make it deterministic.
- **playhead not at 0** → `ableton_session(action='seek', bar=1, beat=0)`, then confirm
  the returned `settled_beats` is 0 (within a beat epsilon). Refuse if it is not — a seek
  that did not take is exactly the silent case this chunk exists to end. Say on stderr
  that the playhead was moved and from where, because it is the user's transport.
- **playhead already at 0** → proceed, no Live write at all.
- `--no-seek` is the escape hatch for capturing deliberately at a non-zero playhead. It
  skips the whole preflight and prints a warning naming the risk. Off by default.

`skills/song-snapshot/SKILL.md` records the guarantee, so the skill stops being the place
where a user has to know this.

**Explicitly descoped:** the report's alternative — detect whether each captured parameter
is under an automation envelope at the current position and name the ones that differ.
Parking at 0 makes the baseline correct rather than merely *reported*, and the envelope
walk is a much larger surface (it needs every envelope for every device parameter) for a
strictly weaker outcome. Recorded here rather than dropped silently.

**Acceptance criteria.**

- With the fake probe reporting `is_playing: true`, `_cmd_execute` returns 2, writes no
  file, and its stderr names the transport as the reason.
- With `current_song_time: 512.0`, `_cmd_execute` issues the seek before the first capture
  probe, and the snapshot is still written.
- With a seek that settles somewhere other than 0, `_cmd_execute` refuses rather than
  capturing.
- With `current_song_time: 0.0`, no seek is sent.
- `--no-seek` sends neither `info` nor `seek` and warns.
- The ordering assertion is real: the test records the probe call sequence and asserts the
  seek precedes every capture probe.

**Done when:** the above hold, `tests/unit/tools/test_capture_cli.py` is green, the full
suite is green, and an `operator-verification.md` entry is queued naming the A-Reverb
decay witness.

## Decisions taken

### The coverage floor marks recalls rather than dropping them

The report offered two fixes: (a) fold partials in the CLI render, (b) a `min_coverage`
that gates both the section lists and the economy's note-mass. Taking (b) alone would drop
partials from the data, and REC-4Z8Q's whole point was that the matcher reports partials
rather than hiding them. Taking (a) alone would leave `compression_ratio` inflated and
`never_recalled` empty — the render would read well and the numbers under it would still
be wrong.

Marking rather than filtering gets both: the occurrence stays in the report and in
`--json`, and every *count* that claims to describe recall stops including it. The cost is
one more field on a serialized structure, which is additive for consumers.

### A partial is a weak *reading*, not merely a low number

Surfaced mid-build, against the plan as first written. A coverage-only floor was the
obvious reading of the report's fix (b), and it is wrong: it demotes
`fragment[0,1.5)` at 0.50 — the matcher's *structured* claim that the layer contains a
contiguous sub-window of the motif, carrying the fragment tier's own evidence floor —
to the same status as `derived (invert ∘ diminish ×2, 0.50)`, which is what the matcher
reports when no clean op was recoverable at all. The lens's own comments treat a bare
`fragment` as a real musical recall (the reggae-cell answer, the integration-trade
signal, "neither silently dropped").

The report's author had already resolved this by hand and the plan missed it: their
filter was `coverage >= 0.75 OR not variation.startswith("derived")` — a fragment
survives at any coverage. So the rule is the conjunction: an occurrence is a partial
only when it is both sub-threshold AND derived-tier.

Reading the tier off the label prefix would work and would be brittle — the label is
human-facing prose composed for a reader. `MatchResult.derived` is set where the tier
is actually chosen, one site, and the lens reads that.

### Chunk 02 refuses on a rolling transport rather than stopping it

Stopping the transport is a bigger liberty than moving the playhead: the user may be
listening. Refusing costs them one command and keeps the destructive option in their
hands, and per the api-contract's refuse-and-teach norm the refusal names what to do.

### Both chunks default to today's behavior for existing callers

`partial` defaults False and `min_coverage` has a default, so no existing test changes
meaning; the capture preflight is additive. This is what keeps "tests never weaken" true
by construction rather than by inspection — the only test edits in this work are the two
`argparse.Namespace(...)` constructions that must learn the new flag.

### The guard belongs to the capture contract, not to `capture execute` — scope EXTENDED

Chunk 02 as written scoped the playhead guard to `capture execute`. The cumulative
Critic (`rev-20260910T215848Z-0aed784e`, R-8) found the other half: `capture_plan()`
emits the by-hand probe recipe that `skills/song-snapshot` and
`skills/song-pick-instruments` step 6 both drive, and it carried no transport read and
no seek — so a hand capture taken after a render bakes end-of-song envelope values in
as dialed baselines with none of the refusal, which is the defect chunk 02 exists to
end, reachable by the route the same skill offers one line after promising the playhead
is parked.

**This is an explicit scope extension, not a silent one.** The requirement chunk 02
should have carried is *the capture contract refuses to read parameters at an unknown
playhead*, not *`capture execute` parks the playhead* — an entry-point-shaped
requirement where the defect is boundary-shaped. The transport read + park are now the
first two records `capture_plan()` emits, so both paths are generated from one
description of the same precondition, and a test pins that they come first (a seek
listed after the parameter walk documents nothing).

The hand path can only be *told*, not made to comply — it is a recipe an agent
executes. That asymmetry stands and is why the record says "prefer `capture execute`",
which walks it in code.
