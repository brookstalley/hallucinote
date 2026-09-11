---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# BAK-3M9T — Turnkey live→source bake: requirements & shipped-state audit

`stage: requirements` · audit date 2026-06-17 · umbrella item, children shipped piecemeal underneath it

This is the retrospective requirements pass the umbrella's `stage: requirements`
gate asked for. Because nearly every child fix shipped *before* this pass, the
job is **reconciliation**: audit the shipped composite against the original
intent, name the residual gaps, and write acceptance criteria that close the
umbrella.

## Feature-discovery (the three questions)

1. **Problem.** Baking a Live mix back into source must be ONE reliable command —
   *change the mix in Live → run one thing → source updates → `build.py` + push
   reproduces it* — with no hand-editing and no format lore. As filed (swell
   dogfood, 2026-06-13), it was an expert-only, multi-trap operation.
2. **Success (verifiable signal).** One command, run post-render, refreshes the
   on-disk source such that `build.py` + push reproduces the dialed mix —
   analyzer-free, params lossless, enums + return-naming handled — and **every
   unmodelable element surfaces as a warning with a re-apply list, never a silent
   drop**.
3. **Out of scope.** Clips/notes (own path: `/ableton-pull` clip-notes),
   automation envelopes (MAW-4K7P / ENV-* own the fidelity surface), arrangement
   + cue points (owned by `build.py`). Nested-param *durability* depth work
   (DEV-9K7N / NODE-ADDR) is independent — the bake already reaches params at
   every depth via the shipped NodeAddr path.

## Trap-by-trap audit (the 7 traps from the source bug)

| # | Trap | Child | Verdict | Evidence |
|---|------|-------|---------|----------|
| 1 | Analyzer pollution | SNP-8R4K | ✅ closed | `capture.py` filters `is_analyzer_device` in both `assemble_snapshot_via_probes` and replay (`survivors = [...]`, lines 308, 934) |
| 2 | Device ordering post-render | SNP-8R4K | ✅ closed | survivors densely renumbered to 1-based rank, not raw Live index (capture.py:305, 924) |
| 3 | `params_dialed` value-vs-normalized silent-wrong-dial | SYN-9F2L + DEV-4P7R | ✅ closed | tri-channel `{value, normalized, value_raw, value_items}` captured; `value_raw` (DEV-4P7R, PR #177) carries non-[0,1] raw params |
| 4 | display-vs-normalized monotonicity at push | DPP-7H2K + DEV-4P7R | ✅ closed | push precedence **enum → value_raw → value_display → value_normalized** picks the safe channel per param (`push/devices.py:330-342`) |
| 5 | Enum params (`value_items`) | (folded into SYN/DEV work) | ✅ closed | `value_items_json` captured + `value_type='enum'` at push (`push/devices.py:330`) |
| 6 | Return naming / send keys | (folded in) | ✅ closed | `strip_return_slot_prefix` at capture **+ a replay-time `UserWarning`** naming the stripped pairs (capture.py:697) |
| 7 | **Sidechain sources** | SDC-7K3M | ⚠️ **RESIDUAL** | SDC-7K3M shipped sidechain round-trip via the **`/ableton-pull` → DB** path (`device_sidechain_source` handler). The **snapshot** (`captured_session.json`) does **not** model sidechain, and `/song-snapshot` does **not warn** it is blind to it → a dialed sidechain run through `/song-snapshot` is **silently dropped** — the exact failure mode trap #7 named. |

**Result: 6 of 7 traps fully closed in the snapshot path; trap #7 closed as a
capability but on a *different* command, with a silent-drop seam at
`/song-snapshot`.**

## The core residual is NOT just UX — it's a durability mismatch between TWO persistence targets

There are three bake skills, but the root cause is that they write to **two
targets with different durability**, and only one of those targets is the bake's
durable home:

| Target | Durable? | Written by |
|--------|----------|-----------|
| `captured_session.json` (+ `build.py`) | ✅ git-tracked authorship; `python build.py` reproduces from it | `/song-snapshot` |
| The song `.db` | ❌ **regenerable build artifact** (`*.db` is git-ignored) | `/ableton-pull`, `/snapshot-bake-recent-changes` |

**The smoking gun:** every `build.py` run calls `replay_capture(captured_session.json)`
(template `build.py.tmpl:54-61`), and `replay_capture` is upsert-shaped — it
**re-asserts the snapshot's values onto the DB** ("updates rows whose state changed
(snapshot edits)", `capture.py:550-557`). So for anything the snapshot models
(params, sends, mixer, returns, chains), a DB-only pull is **overwritten on the very
next `build.py`** — not even a `--reset`, the normal authoring loop reverts it. For
things the snapshot does *not* model (sidechain source), a DB pull survives a no-reset
rebuild but is lost on a clean DB delete and is invisible to the diff.

This is why the three surfaces are dangerous, not just confusing:

| Surface | Persists to | Bake durability |
|---------|-------------|-----------------|
| `/song-snapshot` | `captured_session.json` (durable) | ✅ correct — reproduces across rebuilds |
| `/snapshot-bake-recent-changes` | DB only | ⚠️ "survives the next *push*" but **reverts on the next `build.py`** — its own docs say *push*, not *build*; the footgun is known but unaddressed |
| `/ableton-pull` (mix domains) | DB only | ⚠️ same revert; durable only for build.py-owned domains the human then folds into build.py (clip-notes) |

`/snapshot-bake-recent-changes` is, by its own description (`SKILL.md:108`), "a
UX-tuned wrapper around the `device-parameters` slice of `/ableton-pull`" — a
**redundant alias** whose durability promise is a trap.

## DECISION (user, 2026-06-17): **Option 1 — one durable bake**

Make `/song-snapshot` the single mix bake, model sidechain in the snapshot so it
round-trips durably, **delete `/snapshot-bake-recent-changes`**, and reframe
`/ableton-pull` as the build.py-staging primitive (not a parallel mix bake). The
options considered are below; Option 1 is chosen.

### Resulting build shape (design → chunked build → Critic per chunk)

1. **Chunk A — model sidechain in the snapshot (thin vertical slice).** Add
   `sidechain_source` to the snapshot schema + capture (`assemble_snapshot_via_probes`)
   + `replay_capture` so a dialed sidechain round-trips through `captured_session.json`
   durably (rebuild-safe). This is the one genuine *capability* gap; everything else is
   consolidation. Verifiable: a sidechain survives capture → `build.py` → push.
2. **Chunk B — audit the snapshot for any OTHER unmodeled mix state** (the "warns,
   never silently drops" catch-all): on capture, warn + list anything live in the set
   that the snapshot can't carry, rather than dropping it silently.
3. **Chunk C — delete `/snapshot-bake-recent-changes`**; redirect its callers/docs to
   `/song-snapshot`. (Per `feedback_no_backcompat_to_throwaway` — delete, don't shim.)
4. **Chunk D — reframe `/ableton-pull`** docs/skill as the build.py-staging primitive
   for build.py-owned domains (clip-notes, automation), explicitly NOT a mix bake;
   document the one-bake model in the snapshot-schema doc + `/song-workflow`.
5. **Operator verification (Live-gated)** — acceptance criterion 5.

Note: this is a **framework** change touching the MCP-served `--plugin-dir` tree, so
build it on a feature branch / worktree (`feedback_worktree_for_wip`,
`feedback_worktree_governance_gates_blind`) and review via independent Agents + `gh`.

## The decision (high-stakes — touches the skill surface + snapshot schema)

The umbrella wanted ONE turnkey bake. The honest path to that is to make the
**durable target** (`captured_session.json`) the single mix-bake home and retire the
DB-pull surfaces *as a mix bake*:

- **Recommended — Option 1: one durable bake; delete the redundant alias; model the gap.**
  - `/song-snapshot` becomes THE mix bake (optionally renamed `/bake`).
  - Extend the snapshot schema to model **sidechain source** (audit for any other
    unmodeled mix state) so trap #7 round-trips through the durable target — closes
    the silent-drop *and* makes it rebuild-safe.
  - **Delete `/snapshot-bake-recent-changes`** (redundant + durability footgun).
  - Reframe `/ableton-pull` as the lower-level primitive for genuinely build.py-owned
    domains (clip-notes, automation staging) — explicitly **not** a parallel mix bake.
  - Effort: **M**. Truly closes BAK-3M9T and removes the durability trap.
- **Option 2: a `/bake` orchestrator over the existing primitives.** One command that
  dispatches. Hides the routing but **leaves the durability mismatch** (DB pulls still
  revert on rebuild). Lower value; the user's "under control" is partly a correctness
  ask. Effort: S–M.
- **Option 3: lighter touch — collapse 3→2 + cross-warnings.** Delete the redundant
  alias, add a sidechain warn+redirect to `/song-snapshot`, document the durable-vs-DB
  boundary. Effort: **S**. Closes the silent drop but keeps two surfaces.

The two-target split itself (durable authorship vs regenerable DB) is the
intended architecture (`architecture_db.md`: state-store now, event-store eventual);
fully dissolving it is the future event-store flip, out of scope here.

## Acceptance criteria (for closing BAK-3M9T)

1. Every one of the 7 traps has a verified disposition (this audit: 1–6 ✅; 7
   pending the chosen option).
2. There is **one** command a user runs after dialing a mix; any element it cannot
   carry surfaces as a **warning + re-apply list**, never a silent drop (the
   umbrella's core guarantee). Sidechain specifically must round-trip durably (Option
   1) or warn+redirect (Option 3).
3. No bake surface writes ONLY the regenerable DB and calls it "baked" — the
   durability footgun is removed (Option 1: deleted; Option 3: documented + redirected).
4. The bake-surface model is documented in one place (snapshot-schema doc and/or
   `/song-workflow`).
5. **End-to-end operator verification (Live-gated):** in one session, dial a mix
   exercising all 7 trap categories in a single set (non-[0,1] continuous param, enum,
   renamed return, sidechain) → run the bake → rebuild + push → confirm reproduction,
   analyzer-free, sidechain durable. Folds in SDC-7K3M's pending operator check.

## Net effort

Was labeled **L**; the trap-fixes are done. Remaining depends on the option:
Option 1 **M** (snapshot sidechain modeling + skill consolidation + delete the alias
+ operator verify), Option 3 **S** (warn/redirect + delete the alias + doc). The
build of the 6 closed traps is NOT re-done either way.
