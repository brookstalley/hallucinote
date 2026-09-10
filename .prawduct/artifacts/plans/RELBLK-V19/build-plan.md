---
artifact: build-plan
version: 1
scope: RELBLK-V19
branch: fix/release-blockers-v19
last_validated: 2026-09-09
---

# Build plan — RELBLK-V19: the release blockers

**Scope tag:** `RELBLK-V19` · **Branch:** `fix/release-blockers-v19` (off `develop`)
**Size:** large (six subsystems, new API surface on two) · **Type:** bugfix + one feature
**Critic mode:** `cumulative-final` — per-chunk `chunk` reviews, one `cumulative` at the last chunk.
**partition:** delegated, one isolated worktree per chunk. File ownership is disjoint by
construction and stated per chunk below; no two chunks name the same path. Chunks 01–06 are
mutually independent. Chunk 07 is operator-gated and runs serial with the owner.

## Context

The owner asked which backlog items gate a release, ratified the Tier-1 list, and approved
filing the one bug that had no issue. `check-releasability` reports `no-release-plan` across 13
pending scopes and 209 unreleased commits since `v1.8.6`; the bulk is the sampling wave, so the
release introduces a new user-facing surface and these are the items that make that surface
honest. The release-plan artifact and the four planless scopes are a separate, later step — this
plan is only the code.

## Confidence check

1. **Problem:** six shipped defects and one wrong recovery recipe would ship with the next cut —
   two of them (the vendored-content blind spot, the pin recipe) are defects *in the release
   mechanism itself*.
2. **Success:** every Tier-1 item's own "verifiable signal" flips, with a regression test that
   fails before the fix.
3. **Out of scope:** everything in Tier 2 and Tier 3 from the triage; #222 (see the assumption
   below); the release cut itself.

## Requirements confidence

- **High** — 01, 02, 05, 06. Each issue carries acceptance criteria or a full design.
- **Medium** — 03, 04. Root cause is identified and cited to line numbers, but neither can be
  *product*-verified without Live; both ship with unit-level regression tests and an operator
  verification entry.
- **Low** — 07. It is a design question whose answer is a Live probe nobody has run.

### `[ASSUMPTION: #501 is built standalone, ahead of #222]`
#501's body says "sequence this after #222", which is `OPEN` and effort **L**. The dependency is
a *vocabulary* one — #501 wants to mirror the enumerated `DeviceStatus` shape #222 establishes —
not a code one; #501's own scope-out ("existence and readability only") is self-contained.
Pulling an L-effort item into a release-blocker cluster costs more than it buys, so chunk 06
defines the enumerated status vocabulary for samples and #222 adopts it later rather than the
reverse. **Vetoable** — say so and chunk 06 drops to Tier 2 instead.

### `[DECISION: #514 excludes name + untouched, not name alone]`
The issue named this as the one thing to settle before writing the filter. Settled by the
issue's own Expected clause: "A **claimed** scaffold track — canonical name, but carrying devices
or clips — survives capture." Push can afford a name-only predicate because it only ever sees
unmatched tracks; capture cannot. So the capture-side predicate is canonical-name **and** no
devices **and** no clips.

## Chunks

### Chunk 01: #310 — the vendored-content advisory fingerprint
The install vendors eleven entries that `_FINGERPRINT_PATHS` does not cover, so Live runs stale
non-wire code on a green handshake. Release step 5 derives the consumer-facing `Re-vendor:`
verdict from those same paths, which is why this one is a release blocker and not just a bug.
The issue carries a complete design; follow it, including its rejected alternatives.
**Owns:** `hallucinote_mcp/src/hallucinote_mcp/{__init__,install_paths,install_ops}.py`,
`cli/preflight.py`, `skills/ableton-mcp-install/SKILL.md`, `docs/release-process.md`,
`hallucinote_mcp/tests/unit/test_{install_paths,install_ops,cli_preflight}.py`
**Done when:** editing `analyzer/setup.py` flips the advisory to false while
`compute_version_for` is unchanged, and `differing_paths` names exactly that file.

### Chunk 02: #518 — the pin-recovery recipe names a commit that does not exist
`_version_mismatch_recovery` (`src/hallucinote/sync/push_cli.py:663`) tells the user the `+<sha>`
suffix "is the commit it was vendored from" and hands them `git worktree add /tmp/hallucinote-pin
<sha>`. It is `_compute_content_fingerprint` output — `git cat-file -t` rejects it and the recipe
cannot work. `resources/guides/error-recovery.md:72-77` carries the same false recipe.
The worktree recipe was #388's *own shipped resolution*, so #518 is a regression against #388's
acceptance rather than a gap. Replace
both with the overlay-from-the-vendored-copy pin that was actually verified to work, and fix the
test that currently asserts the wrong recipe (it is a test encoding a defect, so correcting it is
not weakening it — say so in the change-log).
**Owns:** `src/hallucinote/sync/push_cli.py`, `tests/unit/sync/test_push_cli.py`,
`hallucinote_mcp/src/hallucinote_mcp/resources/guides/error-recovery.md`,
`hallucinote_mcp/tests/unit/test_resources.py`
**Done when:** neither site claims the suffix is a commit, and the printed recipe is one a reader
can paste.

### Chunk 03: #505 — a failed replace must not destroy the clip first
`create_handler(replace=True)` calls `slot.delete_clip()` (`handlers/clip.py:560`) before a create
Live may refuse, leaving the slot empty and the previous clip unrecoverable. Pre-check track kind
via `has_midi_input`/`has_audio_input` before deleting. Wave 1 deferred this because the fake LOM
does not model track kind — modelling it is part of this chunk.
**Owns:** `hallucinote_mcp/src/hallucinote_mcp/handlers/clip.py` and the fake-LOM track-kind
model plus its clip tests.
**Done when:** a replace of an audio path onto a MIDI track refuses with the existing clip intact.

### Chunk 04: #498 — the capture starts a beat early
Root cause is identified and is an ordering bug, not a Max bug: `render.py:554` arms every
analyzer, then `:591` locates, and the patch's detector — whose prev-beat is reset to `-1` on the
arm rising edge — fires on the first `current_song_time` change while armed, which is the locate,
not the transport crossing. Reorder so the arm follows the locate, and handle the
`start_at_beat = 0` case where the pre-roll clamps away. This file is fingerprint-bearing: the
fix forces a re-vendor, which must be recorded for release step 5.
**Owns:** `hallucinote_mcp/src/hallucinote_mcp/handlers/render.py`, `handlers/_transport.py`,
their tests.
**Done when:** a simulated transport reproduces the +1.1-beat offset before the change and not
after. **Operator verification required** — the real signal is a Live render, so enqueue it.

**ALREADY BUILT — not dispatched.** `fix/rnd-capture-arm-order` (`8b54a53`, authored by the owner
2026-09-09) carries exactly this fix: the arm moves below the locate, `_set_arm_on_all`'s
docstring is corrected where it claimed arm timing was irrelevant to the recording boundary, and
72 lines of tests assert the ORDER rather than mere occurrence. The reorder also subsumes the
issue's second half — with the arm after the locate, the `start_at_beat = 0` pre-roll clamp is no
longer harmful, because the first post-arm movement is the transport itself.

**Folded in by the owner 2026-09-09**, at the release-landing turn rather than during the build —
absorbing another session's in-flight branch was never the coordinator's call to take. The merge
was clean and the fix's 72 lines of order-asserting tests now run in this suite. It leaves the
wider integration backlog (roughly 25 local branches) untouched; that is a release problem in its
own right, separate from this plan.

### Chunk 05: #514 — capture must exclude an untouched default scaffold
Capture ingests Live's brand-new-set scaffold as song content, `probe-and-link` then matches it,
the W18-D classifier goes silent, and the link state never converges. Apply the predicate decided
above, following the SNP-8R4K analyzer-filter precedent already in `capture.py`. The issue's
evidence is read off the code and not yet reduced to a repro — **confirm it before building.**
**Owns:** `src/hallucinote/capture.py`, `src/hallucinote/sync/push/probe.py`, their tests.
**Done when:** a second capture→replay→push round emits zero net link changes while
`default_scaffold_unmatched_tracks` still populates, and a scaffold-named track carrying a device
survives.

### Chunk 06: #501 — the compat check must verify clips.audio_file exists
A song whose audio clip points at a moved sample passes compat clean and fails in Live. Add a
second entry family with its own rendering path — never a synthesized `DeviceEntry` — with an
enumerated status distinguishing missing from unreadable. Existence and readability only.
**Owns:** `src/hallucinote/sync/compat.py`, the REQUIREMENTS rendering path, their tests.
**Done when:** a dangling `clips.audio_file` fails compat with the path named, and the device
path is untouched.

### Chunk 07: #509 — an audio placement's extent never reaches the arrangement
**Re-scoped 2026-09-09 — the probe this chunk was going to write had already been run.**
Chunk 17 of SMP-6V2K-W2 answered #509 against Live 12.4.5 and recorded it as row 27 of
`docs/research/audio-first-class/lom-probe-results.md`: `end_marker` and `loop_end` are writable
on **both** placement routes (`arrangement_clips[N].end_marker` 8.0 → 4.0 succeeded on the
duplicate route and on the direct create), but `end_time` has **no setter** and did not follow
either write — the block a clip occupies in the arrangement is fixed at placement time and no LOM
write moves it.

So the item's assumed build — trim the arrangement copy to `end_bar` — is **unreachable through
the LOM**, and #509's body still asks for a probe that has already returned. What IS reachable is
setting the clip's **playable region** so the copy plays the authored region. Two consequences:

- The operator text is currently **false in the direction that matters**. It says the extent
  cannot travel and tells the user to "Trim in Live", when the playable region is in fact
  settable. Correcting that text is the release-facing half.
- The second pass #509 hypothesised is buildable: `apply_push_results` already records the
  binding from `arrangement_clip_index` (`sync/push/arrangement.py:321`), so the copy can be
  addressed by its recorded link without the positional guess ARR-PROJ diagnosed.

**Owns (AMENDED at integration — the original line was wrong).** The playable-region write is
not reachable from `arrangement.py` alone: a `ToolCall`'s args are frozen at plan time and the
link is recorded only at phase apply, so the pass needs a post-apply hook. The delegate reported
the overrun rather than trimming the deliverable to fit a boundary that could not hold it, which
is the right call. Actual set: `src/hallucinote/sync/push/arrangement.py`, `push_execute.py`,
`push/plan.py` (declare `arrangement_clip_region` ack-only, or `apply_push_results` raises),
`push/__init__.py` (export, required by the coverage canary), and tests in `tests/unit/sync/`
including `test_planner_mcp_coverage.py`, whose own stated contract is "when a new planner ships,
register it". No other chunk names any of these paths, so the partition held.
**Done when:** an audio placement's copy plays the authored region; the operator text no longer
claims an unreachable trim nor promises a reachable one it does not perform; and the permanent
LOM limit (the block extent) is stated once, as a limit, not as a gap awaiting a fix.
**Bookkeeping owed at close:** #509's body is stale against its own probe — update it to the
re-scope rather than leaving the answered design questions standing.

## Status

- [x] Chunk 01: #310 — the vendored-content advisory fingerprint
- [x] Chunk 02: #518 — the pin-recovery recipe names a commit that does not exist
- [x] Chunk 03: #505 — a failed replace must not destroy the clip first
- [x] Chunk 04: #498 — the capture starts a beat early
- [x] Chunk 05: #514 — capture must exclude an untouched default scaffold
- [x] Chunk 06: #501 — the compat check must verify clips.audio_file exists
- [x] Chunk 07: #509 — an audio placement's extent never reaches the arrangement

Chunk 04 was built on its own branch (`fix/rnd-capture-arm-order`) and stayed UNTICKED while that
was true — ticking it would have told `lib/buildplan_refs.py`, which reads these boxes to answer
"are all chunks done", that a branch carrying the fix was ready when it did not carry it. The
owner folded that branch in on 2026-09-09, so the box is now honest in the other direction: the
fix is in this history, its order-asserting test runs in this suite, and its live check joins the
RELBLK-V19 queue in `.prawduct/operator-verification.md`.

The earlier compact form of this roster (`- \`[x]\` 01 · …`) was never machine-read at all:
`_iter_status_section_items` matches `- [ ]` / `- [x]` at line start, so backtick-wrapped boxes
parse as nothing in either direction, and `[~]` is not a value it knows.
