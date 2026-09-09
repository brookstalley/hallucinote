---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build plan — ARR-ORPHAN: `replace_notes` true total-replace

**Backlog:** ARR-ORPHAN (`.prawduct/backlog.md`). Branch: `fix/arr-orphan` (worktree off develop).
**Refs:** `backlog ARR-ORPHAN`,
`backlog ARR-FROMBUILD/ARR-VERIFY`.

## Confidence check

1. **Problem:** `ableton_clip(action='replace_notes')` on an *arrangement* clip is non-atomic —
   `clip.set_notes()` (Live) does NOT reliably clear pre-existing notes, so older-generation
   notes survive a write (alien `Drums chorus2`: wrote 243, clip held 248 — 5 stale orphans).
   The call reports `ok` / `notes_written: 243` with no warning: it lies.
2. **Success:** after a `replace_notes` call the clip holds exactly the written set (orphans
   gone); the result reports the actual resulting count so a caller can detect a leak;
   live operator-verify on an arrangement clip with known orphans comes back clean.
3. **Out of scope:** the session-view path already total-replaces correctly (defensive clear is
   harmless there); the broader build↔Live drift detector (`verify-arrangement`) already shipped
   in PR #201 — see Chunk 2 note.

## Root cause (bugfix discipline)

The report's hypothesis (a scoped `remove_notes_extended` derived from incoming notes) is **wrong**
— `replace_notes_handler` already calls `clip.set_notes(coerced)` directly (`handlers/clip.py:874`),
no scoped clear. The empirical fact: Live's `set_notes` on an arrangement clip left 5 notes (older
`note_id`s, distinct `(pitch,start)`, inside the clip extent) untouched. The precise Live-internal
reason can only be pinned in Live; the fix is **defensive and self-verifying** regardless: a full-
extent clear before the write + a post-write read-back guarantees + detects total-replace.

## Chunk 1 — prevention: clear-before-write + read-back count  [status: in progress]

- `replace_notes_handler` (`hallucinote_mcp/.../handlers/clip.py`): before `set_notes`, call
  `clip.remove_notes_extended(0, 128, 0.0, float(clip.length))` (full-extent clear). After the
  write, read back `len(clip.get_notes_extended(0, 128, 0.0, float(clip.length)))` (MIDI-guarded,
  mirrors the list-handler idiom at `clip.py:104`) and return it as `notes_present`.
- **Collapse-aware warning, no cry-wolf:** Live collapses same-`(pitch,start)`, so a faithful
  write can hold *fewer* than `len(coerced)` (e.g. `add_wildness` stacks). Collapse only ever
  *reduces*; therefore `notes_present > notes_written` is impossible after a true clear and is the
  only unambiguous leak signal → warn then (preserve the existing inline-notes soft-cap warning;
  join if both fire). `notes_present < notes_written` is legitimate collapse → silent.
- Tests (`hallucinote_mcp/tests/unit/test_actions_clip.py`): extend `FakeClip` with a faithful
  windowed `remove_notes_extended`; add (a) orphan-prone arrangement clip (additive `set_notes`,
  working clear) → after handler, clip == written, `notes_present == notes_written`, no orphan
  warning; (b) clear-failure clip (no-op `remove`, additive `set_notes`) → `notes_present >
  notes_written` and a surfaced warning. Existing `test_replace_notes_*` stay green.
- **Contract surface:** Live-side handler change → flips the MCP fingerprint → re-vendor +
  operator-verify required (operator-verification.md entry).

**Done when:** MCP suite green incl. new regression tests; operator-verification entry queued;
Critic (chunk) clean.

### Boundary investigation (Live Clip contract surface)

Adding `remove_notes_extended` + the `get_notes_extended`/`is_midi_clip` read-back made the
handler depend on more of the **Live Clip object contract**. Production Live clips expose all
three (the bug report's own workaround called `remove_notes_extended`), but test fakes that stand
in for a Clip had to grow them. Two consumers found + fixed:
- `hallucinote_mcp/tests/.../test_actions_clip.py::FakeClip` — added `remove_notes_extended`;
  added bug-faithful `OrphanProneArrangementClip` / `StubbornOrphanArrangementClip`.
- `tests/unit/sync/test_push_mix_unified_shape.py::_Clip` — added the three methods.

**Incidental finding (fixed, in scope per no-pre-existing-exception):** 8 `test_push_cli.py`
execute tests were **non-hermetic** — they skip coherence (`--no-coherence-check`) and so fall
through to the real `_probe_live_via_mcp`, which connects to the running dev MCP server. They
passed only because that server's fingerprint matched; this change flips the fingerprint, so the
probe raised a version-mismatch `SystemExit`. Fixed by adding the file's own established
`_probe_live_via_mcp` stub (used by ~15 sibling tests) so they no longer depend on a running
server. **Pre-existing latent gap noted, NOT fixed here (out of scope):** an invalid `--only`
phase is only rejected *inside* `execute_push` (after the live probe), so `push_cli execute --only
bogus` touches Live before failing — a "validate phase targets before probing" robustness item
worth a backlog entry.

### Verify (Chunk 1)

- `hallucinote_mcp` suite: 1422 passed.
- engine suite: 4390→ (re-run after the fake/hermeticity fixes); the 9 transient failures my
  fingerprint flip surfaced (1 fake-contract gap + 8 non-hermetic probe tests) all green.
- **Operator-verify required** (fingerprint flip + Live-only orphan reproduction) — queued in
  `.prawduct/operator-verification.md`.

## Chunk 2 — detection: `verify-arrangement --from-build`  [status: DEFERRED to backlog ARR-FROMBUILD (user decision 2026-06-22)]

`hallucinote verify-arrangement` + the collapse-tolerant comparator + push-time assert already
SHIPPED (PR #201, ARR-PROJ Chunk 3). The only un-built delta from the capability report is
"fresh build → canonical set" as one command — today it's "rebuild the DB by hand, then verify".
Implementing it needs a new DB-path **env-override** on `resolve_db_path` (a persisted-path
resolver — lock-in-ish contract) and is **not testable in this repo** (no `songs/` here; needs the
songs repo + Live). Recommendation: **defer to backlog** with the env-override design noted; ship
Chunk 1 alone. Pending user decision.
