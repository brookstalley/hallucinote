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

## Reconciliation at merge — 2026-09-10

This plan was written 2026-09-09 and then sat unmerged while 252 commits of release
work landed on `develop`. It is merged reconciled, not as written.

**What was re-checked, and what was not.** Every item number below was re-read against
the tracker; the Phase 0 registry state and #487's blast radius were re-measured against
the tree. **The path-ownership table was NOT re-verified.** Its disjointness was verified
against the 2026-09-09 tree, and 252 commits have landed since — so that verification is
the one claim in this plan that is stale by construction. Re-run it before dispatching
anyone; it is the assumption the whole parallel shape rests on.

**Nine items shipped elsewhere in the interim**, two chunks entirely: C1 (#325, #481) and
C12 (#496, #237-A) are done, C4 lost #310, C8 lost #503, and #501, #222 and #498 closed
on their own branches. The rows below say so.

**What did not change**: the argument. Phase 0 still buys the parallelism, #486 still runs
last and solo, and `cli.py` is still coordinator-owned. No chunk has been dispatched.

---

## Why this shape

Delegates run in separate worktrees because this repo's primary checkout is what
`--plugin-dir` serves to a live Ableton session — uncommitted WIP there destabilises
concurrent sessions. Worktrees are created by the coordinator with `git worktree add`,
never by the harness's own isolation, so every tree has a name the coordinator can
address before the agent is inside it.

---

## The integrator's job (the coordinator — one session, never a delegate)

**Everything in this section is mine. No delegate does any of it.**

1. **Phase 0, before dispatching anyone** — land the two mechanical changes that would
   otherwise conflict with every open branch. Delegates then branch from a base that already
   contains them, and those conflicts never exist.
2. **Create every worktree** — `git worktree add -b <branch> ../hallucinote-<slug>
   integration/backlog-wave-1`, and write the brief into it at `.prawduct/.delegate-brief.md`
   so an abandoned worktree is visible at a later session start. Never the harness's own
   isolation, which hands back a tree you cannot name until the agent is already inside it.
3. **Merge each delegate branch** with `git merge --no-ff`. Never squash.
4. **Apply every registration request** — the delegate reports the line; I write it.
5. **Run the full no-path suite** after each merge (or each pair, when two land close
   together), and tick the chunk's Status box only once that run is green.
6. **All governance**: Critic, `project-state.yaml`, the change-log, backlog `status=shipped`
   with `closed-by`, the PR.
7. **Remove worktrees** after merge.

## The integration contract

**Delegates never govern.** No Critic, no Status boxes, no `project-state.yaml`, no
change-log entry, no PR, no merge, no backlog write. A delegate returns a branch and a report.

**Delegates never run heavy tests.** The bar is *the narrowest run that covers its own diff* —
normally the one or two test files it touched, plus a targeted grep or one real CLI
invocation for anything prose- or contract-shaped. **Explicitly forbidden**: a bare
`python -m pytest`, `pytest tests/`, anything marked `audio` or `ableton`, and any render,
capture or analysis run. This is a cost bound *and* a correctness one: several whole-suite
runs contending on one machine each report a different total, none complete, and all exit 0 —
a green nobody can attribute to a known set of tests is not evidence. The full run is mine,
at integration.

**Delegates report, in this order**: what changed; the exact command run and its result;
assumptions made; any wording decided rather than taken from the issue, marked `proposed`;
and any registration request.

---

## How the parallelism is bought

Three things serialize work here. Two dissolve if the integrator spends ten minutes up front,
which is what Phase 0 is for.

**1. Tree-wide mechanical churn.** #487 (ruff `I001` + `UP`) touches most of the tree, so it
conflicts with every open branch if it lands late, and with **nothing** if it lands first,
because every delegate then branches from already-formatted code. So it moves from "last,
solo" to **first, solo**. It flips the MCP fingerprint, but that only bites when Live next
loads the code, so it costs nothing now and is absorbed by the operator sitting.

Measure the blast radius when you run it — `ruff check --select I001,UP --statistics .` —
and do not carry a number here. This plan filed 250/216 on 2026-09-09; the same command read
290/245 on 2026-09-10, and finding 13 of the sweep records it drifting once before that. The
recommendation survives every re-measurement; the counts have never survived one.

**2. Shared schema and event registries.** `db/schema.sql` + `_ADDED_COLUMNS` and
`db/events.py` are what force #243, #496 and #237-A to serialize. But **an unused column and
an unused event constant break nothing** — so the integrator pre-lands all of them in one
commit, and those chunks then run in parallel, each touching only its own mutators and
planners. This is the single largest wall-clock win in the plan.

**3. `src/hallucinote/cli.py`.** Cannot be pre-landed: a subcommand whose module does not
exist yet breaks the CLI at import. So it stays **coordinator-owned**. A delegate needing a
subcommand writes its module and tests, exercises it by calling the entry point directly, and
reports the exact registration line. Four chunks need one line each — four one-line edits by
one writer, not a four-way conflict.

Genuinely un-parallelizable: **#486** (17 raw-SQL read sites spread across the tree) runs
**last, solo**, after every feature branch has merged. Early it conflicts with most chunks;
last it conflicts with none.

### Phase 0 — integrator, solo, before any dispatch

- [ ] **#487** — one mechanical, behaviour-free commit from `ruff check --fix` at a pinned
  version. The 3 non-autofixable sites get reasoned `noqa`, never an ignore widening. Keep it
  clear of every behaviour change.
- [x] **`bar_ruler` and #237-A's column — already landed.** #496 and #237 shipped on their own
  branches, and they brought their registry entries with them: `bar_ruler` is on
  `arrangement_clips` / `cue_points` / `sections` in `db/schema.sql` with `_ADDED_COLUMNS`
  entries beside it in `db/connection.py`. Nothing to pre-land for C12, which is itself done.
- [ ] **Registry pre-land**, one commit, for what is left: the
  `BREAKPOINTS_REPLACED_IN_SPAN` event constant (#243), which is still absent from the tree;
  and the version bump shared by #253 and #261. Columns land nullable and unused — no reader,
  no writer, no behaviour change.

  **Resolve the version reference before writing that commit.** This plan says
  "the SCHEMA_VERSION bump", and there is no bare `SCHEMA_VERSION` in the DB layer to bump.
  The two candidates are `SNAPSHOT_SCHEMA_VERSION` (`capture.py`) and `inventory.SCHEMA_VERSION`
  — different surfaces with different readers. Decide which #253 and #261 actually share.

---

## Phase 1 — twelve chunks, all parallel

Merged ahead of the phase: **#498** capture-arm-order fix, so
`hallucinote_mcp/.../handlers/render.py` is out of every delegate's diff.

Ownership is **disjoint by construction** — every path appears in exactly one row, verified
against the tree rather than assumed. A delegate that finds it needs a file owned by another
row stops and reports instead of editing it.

| Chunk | State | Items | Owns (exclusive) |
|---|---|---|---|
| C1 | **shipped elsewhere** | ~~#325 #481~~ | — closed on their own branches before this plan merged |
| C2 | open | #220 | new `src/hallucinote/tools/prose_drift.py` + test + committed fixture |
| C3 | open | #258 | new `src/hallucinote/kit_library.py`; `src/hallucinote/kits.py`; the `drum_pads` write site in `src/hallucinote/capture.py` |
| C4 | **narrowed** | #311 #312 (~~#310~~ shipped) | install CLI + preflight; the install skill; `docs/known-issues.md`; new `switch-status` |
| C5 | open | #250 #259 | `src/hallucinote/sync/pull/mix.py`; `ApplyResult.notes`; the scenes-phase planner |
| C6 | open | #455 | `src/hallucinote/takes.py` + test |
| C7 | open | #499 | `src/hallucinote/melody/lens.py`; `src/hallucinote/melody/profile.py` + tests |
| C8 | **narrowed** | #502 (~~#503~~ shipped) | `src/hallucinote/audio/bark.py`; band labels in `src/hallucinote/audio/levels.py`; `src/hallucinote/markdown_refs.py` |
| C9 | open | #292 A | the imaging control pair — Chunk A only; Chunk B stays frozen |
| C10 | open | #239 | new `src/hallucinote/constraint/` package |
| C11 | open | #243 | the envelope mutator under `src/hallucinote/db/mutations/`; the `BuildSession` collision guard |
| C12 | **shipped elsewhere** | ~~#496 #237A~~ | — closed on their own branches before this plan merged |

**C4 and C8 lost an item each, not a chunk.** #310 shipped in RELBLK-V19 and #503 on its own
branch; the paths those rows own are still owned by them for the items that remain.

**C11 and C12 were parallel only because Phase 0 pre-landed their registry entries.** C12 has
since shipped, taking `schema.sql`'s side of that collision with it, so C11 now needs only the
`events.py` constant — which is why the surviving Phase 0 bullet is smaller than the original.

**Dispatch #479 first, ahead of all twelve.** It is a live silent-wrong-output bug:
`_write_breakpoints_as_steps` collapses a two-point linear ramp into one flat step, and when
that value matches the parameter's static value Live discards the envelope while the push
still reports `ok` — on the very route we are about to start preferring. Owns new
`src/hallucinote/sync/envelope_curve.py` plus the push emitter and the pull comparator;
disjoint from all twelve rows.

**Sequenced on a predecessor, not on a wave:** #478 after #479 (which shrinks the perform
population and so changes #478's cost case) · #261 after #502 (same Bark grid; different
ceilings silently compare different spans) · #283 R5–R6 and #308 after Phase 1 settles.
(~~#501 after #222~~ — both shipped; that ordering is spent.)

Suggested concurrency: **six delegates at once**, refilling as each merges. The binding
constraint is disk and integrator attention, not correctness.

### Status

Nothing here was ticked by this plan. The two ticked boxes record work that shipped on
other branches while the plan sat unmerged — they are closed, not delivered from here.

- [ ] Phase 0 — #487 · registry pre-land (`bar_ruler` half already landed)
- [ ] #479 (dispatch first)
- [x] C1 — shipped elsewhere · [ ] C2 · [ ] C3 · [ ] C4 (#311 #312) · [ ] C5 · [ ] C6
- [ ] C7 · [ ] C8 (#502) · [ ] C9 · [ ] C10 · [ ] C11 · [x] C12 — shipped elsewhere
- [ ] #478 (after #479) · [ ] #261 (after #502)
- [ ] Phase 2 — #486, solo, last

---

## Rulings taken 2026-09-09 — nothing is owner-blocked any more

Every item that was waiting on a decision has one. The ruling is recorded as a comment on
each issue; the one-line versions:

| Item | Ruling |
|---|---|
| #239 | **Amend the hold and promote.** The relational register is a SIBLING type, so promotion freezes only the proven section-scoped corner. Weighed against the shim drifting on unmerged `compose/missing`. |
| #292 | **The analyzer freeze binds Chunk B only.** Chunk A emits no grade, so the 2026-08-10 ruling's own test puts it outside. |
| #308 | **Build the helper.** No `tempo_map` migration, no VISION amendment — VISION already states grid encoding as the mechanism. |
| #306 | **Adopt the release gate.** 10 days, per-release non-carrying waivers. Threshold is unmeasured; revisit after the queue drains once. |
| #281 | **Accept F3, skip the Max sitting.** Recorded as a determination with its falsifier. |
| #283 | **Record now, coverage tool later.** R1–R4 ship; R5–R6 sequenced after wave 1. |
| #489 | **Send R5, comment R7 on `prawduct#724`.** See the egress note below — this one is approved but NOT executed. |
| #227 | **Run the calibration.** Everything but the renders builds now. |
| #500 → #255 | **Decline the vendored shared package.** The lock-tests are the mechanism. Both closed — executed; both read CLOSED on 2026-09-10. |
| #253 | **Split.** (c) → #502, (d) → #503; #253 keeps (a)+(b). Executed; #503 has since shipped. |
| #251 | **Re-scoped to one CLAUDE.md line** pointing at `/song-context`; the rest was dead, not blocked. |
| #488 | **Leave `docs/release-process.md` where it is.** A good published doc beats template conformance. |
| #460 | **Intro and Lite formally unsupported.** Don't buy licences to test them. |

### One thing approved but deliberately not done

**#489's upstream send.** The disposition is approved; the bytes are not. `file-upstream`
refuses without `--approve sha256:<digest>` matching a preview, and a blanket approval is
not approval of a payload nobody has read. The recomposed payload sits in #489's body. Run
the preview, read the outbound bytes, then approve that digest.

---

## Design notes for four of the table's rows

These carried a second, older chunk roster that contradicted the table above — it numbered
#501 as "C11" where the table numbers #243 C11, and #501 has since shipped. The roster is
gone; what it knew that the table does not is kept here, against the table's numbering.

- **C7 — melody phrase-altitude grading (#499).** Grades `contour_intent`/`apex_position`
  against `phrase_contours` on a strict majority, falling back to section altitude when the
  tuple is empty. **Delete** `melody/profile.py`'s `DOC-7K3M` caveat rather than amending it
  — it prescribes leaving the contested contour field `None`, which becomes wrong the moment
  a per-phrase contour read exists, and this chunk is that read.
- **C8 — masking ceiling (#502).** **#502 `blocks` #261** — the reference curves ride the same
  Bark grid, so ship the ceiling first or the two silently compare different spans.
- **C9 — stereo image control, Chunk A only (#292).** Generalize the shipped
  `DeclaredWidthControl`/`WidthRealization` into an axis-carrying pair; emit **no** verdict.
- **C10 — promote the constraint substrate (#239).** A mechanical lift of the proven
  song-local shim with the DB adapter replaced by an in-memory arrangement adapter. **Lift it
  off `compose/missing` (`672ee01`) before that branch rots** — finding 9 of the sweep is the
  orphaning risk. That commit is on the **songs** repo, not this one; confirm it is still
  reachable there before scoping the lift, because nothing in this repo can tell you.

---

## The operator queue — batched, not scheduled

The owner is away from the machine. These are ordered so that **one re-vendored Live session
discharges four of them**; do not schedule them as four separate interruptions.

### Sitting 1 — one re-vendor, four verifications

A re-vendor plus a Live quit/reopen is the expensive part; everything below rides the same
one. **If #487 (the ruff sweep) has landed by then, do it immediately before this sitting** —
it flips the fingerprint and forces a re-vendor anyway, so the two costs collapse into one.

1. **#498 — the capture fix.** Shipped since, and its verification box now lives in
   `.prawduct/operator-verification.md` under **RELBLK-V19**, which is the canonical operator
   surface — batch this sitting with that one rather than running two. The box is still
   unticked: park Live's start position at a distant bar (the locate must actually MOVE the
   playhead — the only condition under which the old order bit), render, check
   first-sound-per-stem. Do it first.
2. **#240 — the pre-flight probe.** One render with the disarm loop's
   `_INTER_MUTATION_YIELD_S` set to 0. Spread unchanged → the dispatch-ramp cause is
   confirmed and the Max patch edit is justified. Spread collapses → the original
   "sequential disarm" attribution was right and #240 shrinks to a small Python change.
   **Minutes, and it decides whether an L is real.**
3. **#265 — device smoke.** ~20–30 minutes, mostly building the fixture set (Drum Rack,
   Instrument Rack with ≥2 chains, Compressor, Operator); the driver runs in under a minute.
   Build the driver before the sitting so the time is fixtures, not authoring.
4. **#298 — the curved-envelope round-trip.** Write a linear envelope, save, quit and reopen
   Live, read back. The quit/reopen is already happening for the re-vendor.

### Sitting 2 — calibration renders (#227)

Five identical re-renders on each of two songs with different instrumentation, nothing
touched between takes. Largely unattended once started. Land the CLI, the admission gate and
the floors formula **first**, so the sitting produces numbers rather than design.

### Later, and dependent

- **#234** — needs your ears, and needs the audition mechanism built first.
- **#306(a)** — the attended burn-down, starting with ARR-PROJ Chunk 2 E2E. Several sessions.
  Run the cheap quirk-replay at the top of each so a stale vendor is caught before an hour is
  spent on it.
- **#460** — ruled unsupported; no sitting to schedule. Listed so nobody re-opens it.
