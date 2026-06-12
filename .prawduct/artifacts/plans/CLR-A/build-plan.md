# CLR-A — Build Plan (compose-loop reliability, wave A: swell friction fixes)

The 2026-06-10 swell first-compose friction log (`incoming-bugs/2026-06-10-swell-first-compose-friction.md`),
triaged 2026-06-11 into backlog items SYN-9F2L, SYN-6B4Q, INV-3K8W, SYN-5C3J,
MCP-4T6Y, DEV-5R8Q, INS-2Q7F, SKL-8N3V. One branch
(`feature/clr-a-swell-friction`), one chunk per item-cluster, one PR into
`develop` (gitflow — pass the develop base to `/prawduct:critic` and the PR
reviewer, per `feedback_pr_gate_base_is_develop`).

## Requirements Confidence: **Medium**

- **Problem (one sentence):** The swell compose session surfaced one silent
  correctness bug (snapshot-authored device params never land) and seven
  reliability/teaching holes that tax every song's bootstrap-and-compose loop.
- **Success (one sentence):** A fresh-song bootstrap (scaffold → picks →
  skeleton push → compose → re-push) completes with zero silent drops, zero
  false PARTIALs, and errors that teach the actual fix.
- **Out of scope (one sentence):** The master-analyzer template (TPL-2D8K,
  human-authored `.als`), Live-side Remote Script changes requiring a Live
  restart cycle to verify, and Wave B (CLR-B: RND-7K3M, SYN-2M9P, ENV-5R2J).

**Why Medium, not High:** the params_dialed root cause is hypothesized from
code reading (same-pass link race + idempotency skip), not yet reproduced in a
test; the cues fix has two viable homes (planner pre-check vs apply-layer
result handling) decided in-chunk.

**Open assumptions / unknowns:**

- `[ASSUMPTION: SYN-9F2L root cause — plan_push_devices plans set_parameter
  calls only for ALREADY-LINKED devices (sync/push/devices.py "not linked yet"
  early return); a device loaded in the same execute pass gets its link at
  apply-time, AFTER parameter planning, and the next push's phase fingerprint
  skips devices entirely — so params_dialed never lands and nothing warns.
  Confirmed by failing test before fixing | HIGH impact | user can veto fix
  direction]`
- `[ASSUMPTION: the params_dialed fix prefers the display `value` string
  (handler-side display-curve inversion, like set_parameter value_display)
  over `normalized` when both present, because normalized is ambiguous for
  center-zero params | MED impact | user can override]`
- `[ASSUMPTION: MCP-4T6Y minimal fix = extend the server's read_timeout
  selection (hallucinote_mcp/server.py, currently `None` only for
  ableton_render(render)) to known-long actions (ensure_loaded) with a
  generous bounded timeout, NOT an async/progress protocol — the protocol
  redesign stays a design note on the backlog item | MED impact | user can
  override]`
- `[ASSUMPTION: SYN-5C3J ships as recovery teaching (the version-mismatch
  refusal prints the exact worktree+PYTHONPATH pin recipe + error-recovery
  guide section), not a process-re-exec --pin flag — a flag that mutates
  sys.path after import is a lie, and a launcher wrapper is out of
  proportion | MED impact | user can override]`
- `[ASSUMPTION: DEV-5R8Q decision register — document the
  delete-descending/reload-in-order pattern in the conventions guide now;
  a `rebuild_chain` planner convenience only if it falls out as a pure-planner
  emission (no new wire actions); otherwise record the deferral on the item
  | LOW impact | defer]`

**What would raise confidence:** the chunk-01 failing test reproducing the
params_dialed drop (cheapest concrete probe; written before the fix).

## Status

- [x] Chunk 01: SYN-9F2L — params_dialed lands or warns (root cause + fix + regression)
- [x] Chunk 02: SYN-6B4Q — skeleton-push cues skip-with-warning past arrangement extent
- [x] Chunk 03: INV-3K8W — preset_query teaching errors point at the actual fix
- [x] Chunk 04: SYN-5C3J + MCP-4T6Y — version-pin recovery teaching + long-action read window
- [x] Chunk 05: DEV-5R8Q + INS-2Q7F + SKL-8N3V — chain-rebuild decision + doc fixes (cumulative-final)
Context (chunk 05): DEV-5R8Q — documented the delete-descending/reload-in-order
chain-rebuild pattern in `conventions.md` ("Reordering / inserting mid-chain")
and DECIDED against a `rebuild_chain` convenience: it is NOT a pure-planner
emission (the planner binds devices idempotently by class+position with no
"reorder existing chain" diff; a convenience needs new Remote-Script-side
orchestration to sequence delete+reload and manage the transient-empty-chain
window) → deferred with rationale recorded in the guide note + backlog.
SKL-8N3V — `/song-new` postlude now says call `ensure_loaded` with NO params
(verified against the action: no ParamSpec; `song_slug` errors unknown-param).
INS-2Q7F — OBSOLETE ON ARRIVAL: the install-hardening refactor already replaced
the hand-authored rsync with `install_ops.py`'s `shutil.copytree` + Python
`fnmatch` exclude predicate (no shell glob boundary → the zsh `--exclude=*.pyc`
abort is structurally impossible; the module docstring names that exact
friction). No change needed; recorded with evidence rather than inventing one.
Conventions section content-pinned in test_resources; skill docs have no test
harness (expected). All chunks [x]. Suite 3338 passed / 2 skipped.

Cumulative Critic (base develop, `3b5a82d...9d50cd9`): 1 BLOCKING + 3 WARNING +
6 NOTE. BLOCKER (all three tracks independently found it): SYN-9F2L's own
silent-drop survived on the execute path — the devices planner warned a
no-writable-form params_dialed write into `plan.notes`, but `push_execute` never
drained `plan.notes`, so the warning was discarded on the PRIMARY push path.
Resolved (commit 24d7774) with a severity-scoped fix: `PushPlan.alert()` channel
(operator-actionable, drained into the benign `warnings` channel) distinct from
`notes` (diagnostic noise) and `errors` (halt); regression-tested end-to-end for
already-linked + same-pass-load (convergence) cases. WARNINGS resolved: stale
artifacts refreshed (devices docstring + push-execute-design #3/#7 +
boundary-patterns 4-channel), triplicated halt bookkeeping collapsed into
`_halt()` (+ redundant `error_phase` deleted), backlog recordings landed
(DEV-5R8Q deferral, INS-2Q7F archived obsolete). NOTES: fallback/pad-probe
broad-excepts now log; conventions wording tightened. `verify-resolutions`
(24d7774 vs 9d50cd9): all findings resolved, 0 blocking/0 warning, chain record
extends the cumulative → satisfies the PR gate (CRT-4J8W). Suite 3340 passed /
2 skipped. NEXT: branch ready for `/prawduct:pr` when the user asks.
Context (chunk 04): SYN-5C3J — push_cli now detects a version-handshake refusal
in `ExecuteResult.top_error_patterns` and prints the pin recovery (worktree +
PYTHONPATH + preflight verify) instead of the misleading generic "fix build.py
and re-run" footer (`_version_mismatch_recovery`); the error-recovery guide
gained an "Engine version drift during a live compose session" subsection
(cross-referenced by the CLI footer). The teaching lives CLI-side, not in
`wire.py`, because the refusal is generated by the (possibly old) Remote Script
and its hint can't change in a running session. No Remote-Script change, no
`--pin` flag (sys.path mutation post-import is a lie). MCP-4T6Y — server
read-timeout selection refactored into a `(tool, action)`-keyed policy
(`_read_timeout_for`): render unbounded (None), `ensure_loaded` a generous
bounded 180s (was the 15s default → two timeouts mid-load on a 25-surface set),
everything else the 15s default; async/progress protocol stays a design note.
Per-chunk Critic deferred to cumulative. Suite 3337 passed / 2 skipped.
Context: chunks 01 + 02 + 03 BUILT + committed. Chunk 01 (5384f98) + chunk 03
per-chunk Critic deferred to cumulative (small/single-file). Chunk 03 (INV-3K8W)
— both authoring foot-guns in `resolve_query` now teach the actual fix: a
pattern containing `/` (matches a leaf NAME only) gets the move-to-path_prefix
teaching + concrete decomposition + path-shape sugar suggestion; a `path_prefix`
whose first segment repeats `root` (case/space-insensitive) gets the drop-the-
leading-segment teaching (or "omit path_prefix entirely" when it's the only
segment). Both fixes are in the 0-match / not-found-under-root branches only —
zero behavioral change for valid queries; the `"no loadable matches"` phrase is
preserved so `inventory.find`'s partial-root augmentation still keys off it.
`inventory.find` inherits both teachings (it delegates to `resolve_query`). The
MCP push-time resolver (`device.py:_resolve_preset_query`) is a SEPARATE
Remote-Script-side mirror with its own parallel error text — left unchanged:
out of scope per the plan (Remote-Script changes needing a Live restart to
verify) and the friction was hit on the offline authoring path. Suite 3325
passed / 2 skipped. NEXT: chunk 04 (SYN-5C3J version-pin recovery teaching +
MCP-4T6Y long-action read window).
Chunk 02 (SYN-6B4Q) — the original "no Remote Script
change" constraint was LIFTED by the user mid-build ("fix this right"); the
fix now spans the handler + engine. Shipped: (a) handler `cue_create_batch`
`on_out_of_range='refuse'|'skip'` — skip creates in-extent cues, defers the
rest into `skipped_out_of_range`+`last_event_time`; refuse preserves W5-C
atomic. (b) new `PushPlan.errors` channel — planner hard-error → executor
halts the phase without dispatching. (c) planner partitions cues against the
COMPOSED song length: past-composed → `plan.error`; skeleton (no arrangement)
→ defer+warn; else emit with skip-mode. (d) executor `ExecuteResult.warnings`
+ state-file `warnings[]` + "Warnings" summary section; deferred cues are
benign (exit 0), not PARTIAL. Chunk-mode Critic CLEAN (0/0/0). Suite 3320
passed / 2 skipped. Operator-verification: skip-mode wire round-trip in Live
needs a Live restart to verify (unit-covered via FakeSong). NEXT: chunk 03
(INV-3K8W preset_query teaching errors, `src/hallucinote/preset_query.py`).

## Scaffolding

Existing project — no scaffold work. Tests via `pytest`; homes:
`tests/unit/sync/` (chunks 01, 02), `tests/unit/test_preset_query.py`
(chunk 03), `tests/unit/sync/test_push_cli.py` +
`hallucinote_mcp/tests/unit/test_server.py` (chunk 04). Verification beyond
tests: drive `push_cli` against a scratch song DB where wire-free; wire
verification against the open Live set only where it requires no
Remote-Script reload.

---

## Chunk 01 — SYN-9F2L: params_dialed lands or warns

**Type:** code

The bug: a snapshot-authored device (`params_dialed: {"Drive": {"value":
"14 dB", "normalized": 0.389}}`) loads at push but its dial never lands, no
error surfaced, and the next push fingerprint-skips the devices phase — the
drop is permanent and silent. Two sub-issues from the friction log: (a) the
same-pass ordering drop (assumed root cause above — confirm with a failing
test FIRST); (b) `normalized` is ambiguous for center-zero params (Saturator
Drive raw 0.5→0 dB; naive fraction-of-max dials negative) — the wire write
should prefer the display `value` string (the handler's display-curve
inversion is exact), keeping `value_normalized` as fallback when no display
value exists, and `plan_push_devices` must emit a visible warn whenever a
params_dialed write is skipped for any reason.

- **Done when:**
  1. A regression test reproduces the silent drop (fails on current code),
     then passes with the fix; the warn path is test-pinned.
  2. Full suite green; `/prawduct:critic` per cadence (chunk mode).
  3. Committed; chunk marked [x] in Status.

## Chunk 02 — SYN-6B4Q: cues skip-with-warning past arrangement extent

**Type:** code

First push of a freshly-scaffolded song halts PARTIAL at `cues`
(`cue_create_batch: N cue(s) past last_event_time=24.0`) — Live's locator
setter clamps to the arrangement extent and the arrangement is empty. The
operator sees a false failure for "cues wait for content"; the cues are
idempotently picked up by the next push once clips exist.

**Requirement change (2026-06-11, user):** the original spec said "Engine-side
only — no Remote Script change." The user explicitly lifted that constraint
("we can DEFINITELY change the remote script ... let's fix this right"). The
chosen design now spans the Remote Script handler AND the engine, because the
two distinct questions live in two places:

- *"Is this cue placeable RIGHT NOW in Live?"* — a runtime question only Live's
  `last_event_time` answers → owned by the **handler**.
- *"Will this cue EVER be placeable?"* — a DB question only the composed
  arrangement extent answers → owned by the **planner**.

Design (all four cases — A skeleton / B overrun / C healthy full push / D
arrangement-not-built-at-runtime):

1. **Handler** `cue_create_batch` gains `on_out_of_range: "refuse" | "skip"`
   (`hallucinote_mcp/.../handlers/arrangement.py` + the action ParamSpec).
   `"refuse"` (default) preserves the W5-C atomic raise-write-nothing contract
   for direct/strict callers (existing tests stay green). `"skip"` creates the
   in-`last_event_time` cues and returns the rest in `skipped_out_of_range`
   (+ `last_event_time`) instead of failing — deferred, idempotently retried
   next push.
2. **Planner** `plan_push_cue_points` partitions authored cues against the DB's
   composed extent (`max(arrangement_clips.end_bar)`): a cue past the composed
   song length **when an arrangement is authored** is a hard authoring error
   (it references content that can't exist) → `plan.error(...)`, emit no calls.
   With NO arrangement authored yet (skeleton) all cues simply defer. Otherwise
   it emits the batch with `on_out_of_range="skip"` so cues ahead of Live's
   current runtime extent (skeleton, or arrangement-not-built) defer.
3. **New `PushPlan.errors` channel** (`_core.py`) gives a planner a first-class
   way to signal a hard authoring error distinct from a warn; the executor
   halts the phase (PARTIAL) on it without dispatching, with the clear
   composed-length message — *not* the opaque runtime `past last_event_time`.
4. **Executor** (`push_execute.py`): a `skipped_out_of_range` cue result is
   surfaced via a new benign `ExecuteResult.warnings` channel (state-file
   `warnings[]` + a "Warnings:" summary section), outcome stays `ok` (exit 0);
   a phase whose plan carries `errors` halts → PARTIAL.

Verification: unit-tested against the fake-Live `FakeSong`/`FakeCtx` harness
(handler) and fake `send_fn` (executor) + planner DB tests. The real wire path
(skip-mode round-trip in Live) needs a Live restart to verify — enqueue for
operator verification (F10), don't block the chunk on it.

- **Done when:**
  1. A skeleton-push simulation (no arrangement content) plans/applies cues
     as skip-with-warning, not PARTIAL; composed-length overrun still hard-fails;
     both test-pinned. Handler skip-mode + default-refuse-atomic both pinned.
  2. Full suite green; `/prawduct:critic` per cadence.
  3. Committed; chunk marked [x] in Status.

## Chunk 03 — INV-3K8W: preset_query teaching errors

**Type:** code

Two strict-mode errors point away from the fix (`src/hallucinote/preset_query.py`):
(a) a pattern containing `/` matches entry NAMES only — the 0-match error
should teach "patterns match entry names; use path_prefix for path scoping";
(b) `path_prefix` whose first segment equals `root` errors "not found under
root" — detect `path_prefix[0] == root` and say to drop it.

- **Done when:**
  1. Both teaching branches test-pinned (error text contains the actual fix).
  2. Full suite green; `/prawduct:critic` per cadence.
  3. Committed; chunk marked [x] in Status.

## Chunk 04 — SYN-5C3J + MCP-4T6Y: version-pin recovery + long-action read window

**Type:** code

(a) SYN-5C3J: when push_cli refuses on an engine↔Remote-Script version
mismatch, the refusal teaches the exact recovery that worked (git worktree at
the matching commit + PYTHONPATH pin, verified via preflight); the
error-recovery guide (`hallucinote_mcp/src/hallucinote_mcp/resources/guides/`)
gains the editable-install + parallel-engine-dev section. (b) MCP-4T6Y: the
MCP server's read-timeout selection (`hallucinote_mcp/src/hallucinote_mcp/server.py`,
currently `None` only for `ableton_render(render)`) extends to known-long
actions — `ensure_loaded` on a 25-surface set outruns the 15 s window while
the work continues server-side; give it a generous bounded timeout. The
async/progress protocol stays a design note on MCP-4T6Y (do not build here).

- **Done when:**
  1. Refusal text + guide section test-pinned where testable; the timeout
     selection test-pinned (ensure_loaded ≠ 15 s default).
  2. Full suite green; `/prawduct:critic` per cadence.
  3. Committed; chunk marked [x] in Status.

## Chunk 05 — DEV-5R8Q + INS-2Q7F + SKL-8N3V: chain-rebuild decision + doc fixes

**Type:** cumulative-final

(a) DEV-5R8Q (stage: requirements — this chunk makes the decision): document
the delete-descending/reload-in-order device-chain-rebuild pattern in the
conventions guide (`hallucinote_mcp/src/hallucinote_mcp/resources/guides/conventions.md`
or the docs home found in-chunk); build a `rebuild_chain` convenience ONLY if
it falls out as a pure-planner emission; otherwise record the deferral +
rationale on the backlog item. (b) INS-2Q7F: quote `--exclude='*.pyc'` in the
install skill's rsync example (zsh glob abort). (c) SKL-8N3V: song-new
postlude says call `ensure_loaded` with no params.

- **Done when:**
  1. Pattern documented; decision recorded; both skill-doc fixes landed.
  2. Full suite green; commit the chunk, then `/prawduct:critic cumulative`
     (develop base) — the PR-gate review; resolve blockers.
  3. Committed; chunk marked [x] in Status.
