# Build plan — backlog wave 1 (parallel worktree delegates)

**Scope**: the first executable wave drawn from the 54 backlog items advanced to
`stage: ready` in the 2026-09-09 requirements+design sweep. Every chunk below has its
requirement and design written in its GitHub issue body — **the issue is the spec; this
plan is only the partition, the sequencing and the integration contract.** Do not
re-derive a design here that the issue already carries.

**Integration branch**: `integration/backlog-wave-1` (off `develop`).
**Coordinator**: the session that owns this file. **Delegates**: one per chunk, each in
its own `git worktree`.

---

## Why this shape

Delegates run in separate worktrees because this repo's primary checkout is what
`--plugin-dir` serves to a live Ableton session — uncommitted WIP there destabilises
concurrent sessions. Worktrees are created by the coordinator with `git worktree add`,
never by the harness's own isolation, so every tree has a name the coordinator can
address before the agent is inside it.

---

## The integration contract

**Delegates never govern.** No Critic, no Status boxes, no `project-state.yaml`, no
change-log entry, no PR, no merge. A delegate returns a branch and a report. Everything
in this paragraph is the coordinator's.

**Delegates never run the full suite.** The verification bar for a delegate is *the
narrowest run that covers its own diff* — normally the one or two test files it touched,
plus a targeted grep or a real CLI invocation for anything prose- or contract-shaped.
This is a cost bound, not a rigor discount, and what it prevents fails **silently**:
several whole-suite runs contending on one machine each report a different total, none
complete, and all exit 0. A green you cannot attribute to a known set of tests is not
evidence. The full no-path `python -m pytest` run is the **coordinator's**, once, at
integration.

**Delegates report, in this order**: what they changed, the exact command they ran and
its result, what they assumed, any wording they decided rather than took from the issue
(marked `proposed`), and any **registration request** (below).

**The coordinator** merges each delegate branch into `integration/backlog-wave-1` with
`git merge --no-ff`, resolves registry conflicts, runs the full suite after each merge
(or after each pair, if merges land close together), and only then ticks the chunk's
Status box.

---

## File ownership

Ownership is disjoint by construction except for four **shared registries**, which are
append-only and are called out here rather than pretended away.

**Coordinator-owned — no delegate commits to these:**

- `.prawduct/**` — all governance, this plan included
- `pyproject.toml`
- `docs/capability-truth.md` — one shared table, one writer

**Shared registries — a delegate MAY append, under one convention:** add a single
contiguous block at the position the file's existing ordering implies, never reformat or
re-sort a neighbour, and name the addition in your report as a *registration request* so
the coordinator can expect the conflict.

- `src/hallucinote/cli.py` — subcommand registry
- `src/hallucinote/db/events.py` — event-name constants
- `src/hallucinote/db/schema.sql` and its `_ADDED_COLUMNS` migration list

Everything else is owned by exactly one chunk per wave, listed below.

---

## Wave 1 — six chunks, fully parallel

Already merged ahead of the wave: **#498** capture-arm-order fix
(`fix/rnd-capture-arm-order`). It is the only wave-1 change to
`hallucinote_mcp/.../handlers/render.py`, so that file is out of every delegate's diff.

### Status

- [ ] C1 — automation verification: window span + staircase gestures (#325, #481)
- [ ] C2 — `build.py` prose-drift checker (#220)
- [ ] C3 — cross-song drum-kit seeding (#258)
- [ ] C4 — install boundary trio (#310, #311, #312)
- [ ] C5 — pull-side small wins (#250, #259)
- [ ] C6 — evidence-tree retention lifecycle (#455)

### C1 — automation verification (#325 + #481)

**Why one chunk**: both rewrite the same window logic. #325 replaces the fixed
2-beats-back window with one bounded by the transition interval; #481 groups
consecutive same-direction changes into one gesture. Shipped separately, the second
rewrites the first.
**Owns**: the automation-verification module and its test file; the `curve_kind`
threading through `server_side/analysis.py` into `DeclaredEnvelope`.
**Verify**: that module's test file only.

### C2 — prose-drift checker (#220)

**Owns**: new `src/hallucinote/tools/prose_drift.py`, its new test file, and a committed
fixture. **Registration request expected**: one `cli.py` subcommand line.
**Note the corrected acceptance**: `97816e1` is the commit that *fixed* the phantom
Shifter; the phantom state is its parent `02be0ec`, and `examples/angle-of-the-light` no
longer exists in the tree — so the acceptance case ships as a committed fixture, not a
working-tree path. Model the module on the existing `overview_drift.py` (detect fn +
non-raising build-close hook + 0/1/2 CLI).
**Verify**: its own test file, plus one real CLI invocation against the fixture.

### C3 — cross-song drum-kit seeding (#258)

**Owns**: new `src/hallucinote/kit_library.py`, `src/hallucinote/kits.py`, the
`drum_pads` write site in `src/hallucinote/capture.py`, new tests.
**Registration request expected**: one `cli.py` subcommand line.
**Hard constraint**: `drum_pad_mappings` keeps its per-song `device_id` FK. The cache
SEEDS through the existing `replace_drum_pad_mappings` mutator — mutator + event, never
raw SQL — and never overwrites a mapping a song already carries.
**Verify**: its own two or three test files.

### C4 — install boundary trio (#310, #311, #312)

**Why one chunk**: all three touch preflight and the install skill; splitting them
guarantees an intra-wave conflict.
**Owns**: the install CLI and preflight surface, the install skill, `docs/known-issues.md`,
the new `switch-status` subcommand and its skill.
**Carries a measurement already taken** (#311): with Live 12.4.5 running and the control
surface serving, `lsof` showed zero open descriptors under the User Library, and the
Live-side tree is imported eagerly at instantiation — so the macOS refusal becomes
warn-and-proceed. **Keep the refusal on Windows**; nobody has measured it there.
**#310 is wider than its title**: eleven entries sit outside `_FINGERPRINT_PATHS`, not
just `analyzer/`, and `server_side/` is excluded deliberately — hence a uniform ADVISORY
content fingerprint, never "add analyzer/ to the tuple".
**Verify**: the install/preflight test files only.

### C5 — pull-side small wins (#250, #259)

**Why one chunk**: both touch the pull/apply result surface.
**Owns**: `src/hallucinote/sync/pull/mix.py`, the `ApplyResult.notes` channel, and the
scenes-phase planner.
**Hard constraint** (#259): do **not** retire the capture-span guard. Scene tempo applies
only on scene launch in session view; render drives the arrangement transport. The guard
is about what the render played, so it survives — `audio/alignment.py`'s docstring should
drop the `#259` reference and keep `#321`.
**Verify**: the pull and planner test files only.

### C6 — evidence-tree retention (#455)

**Owns**: `src/hallucinote/takes.py`, a new `hallucinote evidence` subcommand, new tests.
**Registration request expected**: one `cli.py` subcommand line.
**Hard constraint**: a superseded run is promoted to `measurements/`, never deleted; only
*working* evidence is swept.
**Verify**: its own test file, plus one real CLI invocation.

---

## Wave 2 — serialized after wave 1 merges

These conflict with wave 1 or with each other and must not run beside it.

- **#479** session_clip ramp (new `sync/envelope_curve.py` + push emitter + pull
  comparator). Conflicts with C5's pull work. **This is a live silent-wrong-output bug**:
  `_write_breakpoints_as_steps` collapses a 2-point linear ramp into one flat step, and
  if that value matches the parameter's static value Live discards the envelope while the
  push reports `ok`. Sequence **#479 before #478**.
- **#243** span-scoped envelope writes (new `replace_breakpoints_in_span` mutator + event
  + `BuildSession` collision guard). Touches the events registry.
- **#496** `bar_ruler` provenance (additive schema column + `_ADDED_COLUMNS` + planners).
  Touches the schema registry; serialize with #243 rather than beside it.
- **#237 chunk A** — correct the false `clips.reverse` contract at `db/schema.sql:137-142`
  (the LOM research confirms Live exposes no `reversed` property) and refuse `reverse=1`
  loudly. Schema registry again; land it with #496.

## Wave 3 — solo, whole-tree, one at a time

- **#487** ruff `I001` + `UP` in one mechanical, behaviour-free commit. Re-measured
  2026-09-09 at ruff 0.15.20: I001 250, UP 216, 284 files. **33 of those files sit under
  `_FINGERPRINT_PATHS`, so this commit flips the MCP fingerprint and forces a Remote
  Script re-vendor** — schedule it where a re-vendor is already happening.
- **#486** consolidate the 17 raw-SQL read sites into `db/queries`. Run last: it touches
  call sites all over the tree. One of the 17 is a latent correctness difference, not
  style — `tools/song_context.py:197` omits the `song_id` scope that `Q.tracks_by_name`
  carries.

---

## Blocked on an owner ruling — not in any wave

Each has requirements and design written; what is missing is a decision only the owner
can give. Do not start these.

| Item | The ruling needed |
|---|---|
| #239 | Promoting the constraint substrate crosses the recorded "wait for a relational song" hold. Time-sensitive: the shim exists only on unmerged `compose/missing` (`672ee01`). |
| #292 | Narrowing the analyzer-freeze gate to Chunk B only. |
| #308 | Whether polytempo is a priority now. VISION already describes grid encoding, so no amendment is needed unless the build is declined. |
| #306(b) | Ratifying the >10-day release gate. |
| #462 | Flipping a ratified norm row from `Critic` to `Test + Critic`. |
| #281 | Accepting the M4L determination without a Max sitting. |
| #283, #307 | Product priority. |
| #261, #460, #489 | Public-surface wording and outbound sends. |

## Needs the owner's hands, not a ruling

#498's live verify (re-vendor, then one render with Live's start position parked at a
distant bar) · #240's cheap pre-flight probe (one render with `_INTER_MUTATION_YIELD_S`
set to 0) · #227's calibration renders · #265's 20–30 attended minutes · #298's curved
round-trip · #234's ears.
