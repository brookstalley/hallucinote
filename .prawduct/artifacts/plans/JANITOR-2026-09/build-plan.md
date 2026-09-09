---
artifact: build-plan
version: 1
scope: JANITOR-2026-09
branch: chore/janitor-2026-09
depends_on:
  - artifact: project-preferences
  - artifact: data-model
  - artifact: architecture
  - artifact: api-contract
governed_by:
  - artifact: project-preferences
    dispositions:
      - "norms bind, descriptions track → this plan AMENDS four norm statements under owner ruling; it never doc-drifts code to match a norm or a norm to match code without a recorded ruling"
      - "audit home = janitor → this plan is that sweep's first execution, and stamps the baseline the next one reads"
partition: serial — Chunk 05 records the outcome of 01-04 and must run last; 01-04 touch disjoint surfaces and could interleave
last_validated: 2026-09-08
rulings: R1-R7 + 9-item bulk (2026-09-08); R2 mechanism (2026-09-08)
---

# Build plan — JANITOR-2026-09: first Norm Health sweep + accumulated maintenance

**Why this plan lives here and not at `.prawduct/artifacts/build-plan.md`:** that path
holds the perform-start-position plan, which the owner ruled stays live because its work
is merged but unreleased (gitflow). This repo's established convention for a concurrent
plan is `plans/<ID>/build-plan.md` — 51 such directories precede this one.

## Requirements Confidence

**Level:** High

**Why:** Every item below is a measurement taken against the tree during the survey, and
every judgment call was ruled by the owner before this plan was written (R1-R7 plus a
9-item bulk confirmation). Nothing here is inferred intent.

**Open assumptions / unknowns:**

- [ASSUMPTION: the 8 no-checklist plan dirs classify as completed on reading | LOW impact
  | resolved in-chunk] Their per-chunk `[status: done]` headings and, for MICROTUNE, an
  explicit `Status: CLOSED`, say so. Chunk 01 reads each before archiving and reclassifies
  any that disagree rather than assuming.
- [ASSUMPTION: `ruff` isort with `required-imports` fixes exactly the 5 missing sites and
  reorders imports elsewhere | MED impact | verified in-chunk] The reorder blast radius is
  measured with `--diff` before anything is written; if it exceeds a reviewable size the
  chunk lands `required-imports` alone and defers general isort to its own item.

## Scope boundary — what this plan does NOT do

- **R7 (narrow `verify-resolutions`) is not built here.** It is entirely plugin-owned
  (`prawduct-hook`, `methodology/building.md`, `methodology/planning.md`,
  `agents/critic-reviewer.md`); this repo has no configuration surface for it. The owner's
  ruling is carried upstream as a prawduct report in Chunk 04, not implemented locally.
- **`capture.py` (2,740 lines) is not split.** Already scoped as #304; renovation, not
  cleaning.
- **No release.** `develop` is 101 ahead of `main`; the owner deferred that separately.
- **The two cold branches are not revived or deleted** — only recorded (R6).

## Status

- [x] Chunk 01: version-control and plan-directory hygiene
- [ ] Chunk 02: norm statements reconciled to the owner's R1/R3/R4/R5 rulings
- [ ] Chunk 03: `Kit` dependency inversion (loader module + alias) and the ruff `required-imports` gate
- [ ] Chunk 04: findings that leave this repo — backlog items and the upstream report
- [ ] Chunk 05: sweep baseline, change-log, learnings

---

### Chunk 01: version-control and plan-directory hygiene

**Spec.** Delete the 6 merged local branches (`docs/tour-walkthrough`,
`docs/release-process-v180-corrections`, `docs/release-readiness`, `feat/tour-evidence`,
`chore/archive-effort-s-plan`, `chore/governance-file-sizes`) and the merged remote
`origin/claude/github-issues-access-h7r909`. Each verified 0-ahead of `origin/develop`
during the survey; **re-verify at delete time**, since the survey and the execution sit on
different `develop` tips. Leave `design/collaboration-turn-model` (live worktree) and the
two cold branches (R6) alone.

Archive 47 plan directories with `prawduct-hook archive-plan <path> --state <state>`:
30 completed (all boxes ticked), 9 superseded (partial — each `--superseded-by` naming
what absorbed it, e.g. SYN-8Q3F Chunk 05 → #304, WS-BOOTSTRAP → its successor), and 8
carrying no `## Status` checklist, which are **read individually first** and archived under
whichever state the reading supports. `build-plan.md` at the artifacts root is NOT
archived — add a line to it recording why (merged-but-unreleased, gitflow).

De-duplicate `.gitignore`: `.prawduct/.handoff-notes.md` appears twice; consolidate the 5
repeated `# Prawduct session files` headers into one block, preserving every entry.

**Done when.** `git branch --merged origin/develop` lists only branches with a live
worktree; `plans/` holds only directories with genuinely open work; `.gitignore` has no
duplicate entry and one session-files block; full suite green.

**Risk.** Deleting a branch someone else needs. Mitigated by the re-verify and by leaving
every unmerged branch untouched.

### Chunk 02: norm statements reconciled to the owner's rulings

**Spec.** Four amendments, each recording that the owner ruled it and when.

- **R1** — `data-model.md` § Direction: narrow "no raw SQL in callers, **ever**" to cover
  **writes**, matching the why that justifies it (a caller reaching around the mutators
  makes the event log a lie — a read cannot). Record the `markdown_refs` projection
  rebuild as a **bounded exception** with its why, so a second bypass has something to be
  measured against. Update the mirroring preferences row (127).
- **R3a** — preferences rows 126 and 131: row 126's mechanism becomes Linter (the
  `required-imports` rule Chunk 03 adds). Row 131 keeps `UP` and full `E` as an explicit
  open item rather than standing language nobody is acting on.
- **R4** — `architecture.md` § Direction, push-projection norm: strike the
  "AGENT-PROPOSED, PENDING OWNER VETO" block; record owner affirmation 2026-09-08. The
  statement text does not change — only its standing.
- **R5** — `architecture.md`: state that this artifact models runtimes, boundaries and
  data flow, **not** module inventory, and that the source tree is the module index.
  Then dismiss the `stale-architecture` advisory with that reason.
- **Row 130** (bulk item 7) — narrow "`sync.*` produces plans, never invokes MCP tools
  directly" to "sync **planners** produce plans; only the executor layer sends," matching
  `sync-boundary-contract.md` §Executor, which already models that layer.

**Done when.** Every amended norm carries its ruling and date; no norm statement is
contradicted by code that this plan leaves in place; `grep` confirms the advisory is
dismissed with a reason.

**Risk.** Amending a norm to match code is the tell for the exact failure the norm
lifecycle guards against. Mitigated structurally: every amendment here is an *owner
ruling* recorded as such, and R1's narrowing follows the norm's own stated why rather than
the code's convenience.

### Chunk 03: `Kit` dependency inversion and the ruff import gate

**Spec.** Remove `from hallucinote.db import queries as Q` from
`src/hallucinote/generators/kit.py`. Add `Kit.from_rows(rows, *, name, device_id)` — pure,
caller-supplied rows — restoring the purity norm's actual guarantee: `Kit` constructible
and testable with no DB. Add a test that builds a `Kit` from rows with no `sqlite3`
connection in scope.

**Norm collision, ruled by the owner 2026-09-08.** `Kit.from_device(conn, device_id)` is
not internal — it is the documented song-authoring API, named in `capture.py`'s guidance
strings, `drums.py`'s module docs and `push_execute.py`, with `hallucinote-songs` as a
live consumer. So the purity norm (`architecture`-adjacent, homed in preferences row 129)
and the authoring-API alias norm (`api-contract.md` § Direction: *"renaming or removing an
authoring function earns an alias for one major version"*) point opposite ways on the same
function. **Ruling: loader module, keep the alias.** DB loading moves to a new
`src/hallucinote/kits.py`, outside `generators/`; `Kit.from_device` survives as a
one-major deprecated alias that lazily delegates to it, so `import
hallucinote.generators.kit` pulls in no DB code and no `build.py` breaks. Announce the
deprecation in `CHANGELOG.md`, as that norm requires.

Add to `[tool.ruff.lint]`: `"I"` selected, with
`[tool.ruff.lint.isort] required-imports = ["from __future__ import annotations"]`. Measure
the reorder diff with `ruff check --select I --diff .` **before** applying; if it is not
reviewable, land `required-imports` alone and file general isort separately. Either way the
5 `__init__.py` files gain the import.

**Done when.** No import of `hallucinote.db` under `generators/`; `ruff check .` clean and
gating the future-annotations norm mechanically; full suite green; `mypy` clean.

**Risk.** Retired by the ruling above — the alias means no `build.py` breaks. Residual
risk is the alias itself decaying into a trap (the api-contract norm's own warning about
code with no caller), so it carries a deprecation date in `CHANGELOG.md` rather than
standing indefinitely.

### Chunk 04: findings that leave this repo

**Spec.** File via `/prawduct:backlog`:
- `fix/tmp-7b3x-meter-source-of-truth` — 4 commits, 28 files, +781/-211, cold since
  2026-08-07. Question: revive or retire.
- `feat/elicitation-conversational` — 4 commits, 16 files, +1163/-222, rewrites
  `skills/song-brief/SKILL.md`. Question: did COLLAB-TURN (2026-09-01) supersede it?
- R1 residual: whether the 17 raw-SQL **read** sites should consolidate into `db/queries`
  on their own merits.
- R3b: enable `UP` and full `E` (formatting-churn decision).
- Template currency: `test-specifications.md` (property-based and state-transition
  sections earn their place — `hypothesis` is already a dev dep and the sync executor is
  the state-machine shape) and a release `runbook.md`. `product-brief.md` and
  `dependency-manifest.yaml` assessed **not applicable** and recorded as such.

Each item names a verifiable signal, per the preferences row requiring it.

File upstream via `/prawduct:report-bug`: R7, carrying the `review-stats` evidence —
`verify-resolutions` at 84 reviews / 6.1h / 30% actionable / 0.81 findings per review,
against `cumulative` at 81% and 12.15.

**Done when.** Every deferred finding has an id; nothing from the survey exists only in
conversation.

### Chunk 05: sweep baseline, change-log, learnings

**Spec.** Write to `project-state.yaml`: `norm_health_last_run: 2026-09-08` (top-level
scalar) and the first `norm_health:` entry — a list, appended never overwritten, with a
`measurements:` map of norm handle to one-line distance. This run's measurements:

    - date: 2026-09-08
      measurements:
        "raw-sql-outside-db": "5 write sites (all markdown_refs, now a recorded bounded exception), 17 read sites — norm narrowed to writes by owner ruling R1"
        "generators-pure": "1 violation site (kit.py), inverted in this sweep — 0 remaining"
        "sync-plans-not-calls": "7 modules call client.send; norm restated to planners-vs-executor per sync-boundary-contract §Executor"
        "future-annotations": "5 missing sites (all __init__.py), now mechanized via ruff required-imports"
        "mcp-handlers-async": "0 violations — enforced at one anyio.to_thread wrapper plus test_threading_invariants.py"
        "broad-except-waived": "38 catches / 45 waiver pragmas — over-covered"
        "deps-locked": "0 violations — uv lock --check gates CI"
        "no-telemetry": "0 outbound calls in tree"
        "engine-api-support-window": "event-bound revisit has NOT fired — no external song repo, no break report"

Update `.prawduct/change-log.md` with what this sweep changed. Capture in
`.prawduct/learnings.md` the pattern worth keeping (see Reflection below).

**Done when.** The next sweep can read a baseline instead of measuring from zero.

## Verification Strategy

Chunks 01, 02, 04 and 05 touch no source, so the suite is a regression guard, not
evidence. Chunk 03 is the only behavioral change and carries its own test (a `Kit` built
with no DB connection in scope) plus the mechanical gates (`ruff`, `mypy`).

Full suite runs with **no path argument** before Chunk 01 and after every chunk — the
nonfunctional-requirements norm, because `testpaths` spans three trees and a path-scoped
run reports green over untested code.

## Reflection — what this sweep says about the process

The survey found a codebase in good order and bookkeeping that had fallen behind it: 47
finished plans still reading as active, 6 merged branches undeleted, and four norms whose
*statements* had drifted wider than the code while the code itself stayed disciplined. That
is the signature the Norm Health sweep exists to catch and no diff review can: each
individual gap was defensible in the moment, and the sum was a set of norms that overstate
what the project actually holds. It had never run, so there was no baseline — which is why
Chunk 05 exists.
