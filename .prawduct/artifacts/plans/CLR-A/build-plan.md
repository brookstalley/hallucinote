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

- [ ] Chunk 01: SYN-9F2L — params_dialed lands or warns (root cause + fix + regression)
- [ ] Chunk 02: SYN-6B4Q — skeleton-push cues skip-with-warning past arrangement extent
- [ ] Chunk 03: INV-3K8W — preset_query teaching errors point at the actual fix
- [ ] Chunk 04: SYN-5C3J + MCP-4T6Y — version-pin recovery teaching + long-action read window
- [ ] Chunk 05: DEV-5R8Q + INS-2Q7F + SKL-8N3V — chain-rebuild decision + doc fixes (cumulative-final)
Context: plan authored 2026-06-11; nothing built yet.

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
idempotently picked up by the next push once clips exist. Fix home decided
in-chunk: either the apply layer downgrades per-cue `past last_event_time`
failures to skip-with-warning (exit 0, listed as deferred), or the planner
pre-partitions against the extent it can compute; the hard error is reserved
for cue positions beyond the *composed* song length. Engine-side only
(`src/hallucinote/sync/push/arrangement.py` + apply/result handling) — no
Remote Script change.

- **Done when:**
  1. A skeleton-push simulation (no arrangement content) plans/applies cues
     as skip-with-warning, not PARTIAL; composed-length overrun still hard-fails;
     both test-pinned.
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
