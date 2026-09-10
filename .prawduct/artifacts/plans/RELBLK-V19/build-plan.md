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

### `[ ]` 01 — #310: the vendored-content advisory fingerprint
The install vendors eleven entries that `_FINGERPRINT_PATHS` does not cover, so Live runs stale
non-wire code on a green handshake. Release step 5 derives the consumer-facing `Re-vendor:`
verdict from those same paths, which is why this one is a release blocker and not just a bug.
The issue carries a complete design; follow it, including its rejected alternatives.
**Owns:** `hallucinote_mcp/src/hallucinote_mcp/{__init__,install_paths,install_ops}.py`,
`cli/preflight.py`, `skills/ableton-mcp-install/SKILL.md`, `docs/release-process.md`,
`hallucinote_mcp/tests/unit/test_{install_paths,install_ops,cli_preflight}.py`
**Done when:** editing `analyzer/setup.py` flips the advisory to false while
`compute_version_for` is unchanged, and `differing_paths` names exactly that file.

### `[ ]` 02 — #518: the pin-recovery recipe names a commit that does not exist
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

### `[ ]` 03 — #505: a failed replace must not destroy the clip first
`create_handler(replace=True)` calls `slot.delete_clip()` (`handlers/clip.py:560`) before a create
Live may refuse, leaving the slot empty and the previous clip unrecoverable. Pre-check track kind
via `has_midi_input`/`has_audio_input` before deleting. Wave 1 deferred this because the fake LOM
does not model track kind — modelling it is part of this chunk.
**Owns:** `hallucinote_mcp/src/hallucinote_mcp/handlers/clip.py` and the fake-LOM track-kind
model plus its clip tests.
**Done when:** a replace of an audio path onto a MIDI track refuses with the existing clip intact.

### `[ ]` 04 — #498: the capture starts a beat early
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

The branch is unpushed and unintegrated, and its worktree still exists, so it may belong to a
live session. **Left for its owner rather than absorbed** — folding another session's in-flight
branch into this one is the owner's call, not the coordinator's. It is one of roughly 25 local
branches awaiting integration; that backlog is a release problem in its own right, separate from
this plan.

### `[ ]` 05 — #514: capture must exclude an untouched default scaffold
Capture ingests Live's brand-new-set scaffold as song content, `probe-and-link` then matches it,
the W18-D classifier goes silent, and the link state never converges. Apply the predicate decided
above, following the SNP-8R4K analyzer-filter precedent already in `capture.py`. The issue's
evidence is read off the code and not yet reduced to a repro — **confirm it before building.**
**Owns:** `src/hallucinote/capture.py`, `src/hallucinote/sync/push/probe.py`, their tests.
**Done when:** a second capture→replay→push round emits zero net link changes while
`default_scaffold_unmatched_tracks` still populates, and a scaffold-named track carrying a device
survives.

### `[ ]` 06 — #501: the compat check must verify `clips.audio_file` exists
A song whose audio clip points at a moved sample passes compat clean and fails in Live. Add a
second entry family with its own rendering path — never a synthesized `DeviceEntry` — with an
enumerated status distinguishing missing from unreadable. Existence and readability only.
**Owns:** `src/hallucinote/sync/compat.py`, the REQUIREMENTS rendering path, their tests.
**Done when:** a dangling `clips.audio_file` fails compat with the path named, and the device
path is untouched.

### `[ ]` 07 — #509: an audio placement's extent never reaches the arrangement
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

**Owns:** `src/hallucinote/sync/push/arrangement.py` and its tests.
**Done when:** an audio placement's copy plays the authored region; the operator text no longer
claims an unreachable trim nor promises a reachable one it does not perform; and the permanent
LOM limit (the block extent) is stated once, as a limit, not as a gap awaiting a fix.
**Bookkeeping owed at close:** #509's body is stale against its own probe — update it to the
re-scope rather than leaving the answered design questions standing.

## Status

- `[ ]` 01 · `[ ]` 02 · `[ ]` 03 · `[ ]` 04 · `[ ]` 05 · `[ ]` 06 · `[ ]` 07

## Integration debt raised by delegates

Coordinator-owned follow-ups, reported by a delegate against a file outside its ownership. Each
is discharged at integration, not by the delegate that found it.

- **Chunk 03 → the `replace` wire-schema text.** `hallucinote_mcp/src/hallucinote_mcp/actions/clip.py:130,218`
  describes `replace` as "delete the existing slot's clip". Not made false by the pre-check — it
  still describes the succeeding case — but it no longer describes the whole contract, since a
  definite kind mismatch now refuses before deleting. One line, owned by nobody in this plan.
- **Chunk 03 → `src/hallucinote/sync/push/clips.py` calls `replace=True` at :494, :563, :734.**
  No consumer change needed: none reads the error string and none can depend on the destruction,
  so the push now receives a refusal instead of a destroyed clip plus an error. Recorded so the
  integration run is not surprised by a behaviour change in files no chunk owns.

## Corrected tests, recorded here because delegates cannot write `.prawduct/`

Each of these encoded the defect its chunk fixes. Correcting them is legitimate under Tests Are
Contracts; weakening them would not be. Carry these into the change-log entry at the cut.

- **Chunk 03** — `test_replace_that_fails_to_recreate_says_the_slot_is_now_empty` asserted the
  clip was destroyed on a wrong-kind replace. Retargeted to a bad audio path on an audio track —
  a failure the pre-check genuinely cannot foresee — so the post-delete disclosure contract stays
  pinned exactly as before.
- **Chunk 02** — `test_version_mismatch_recovery_teaches_pin_recipe`,
  `test_cli_execute_version_mismatch_prints_pin_recovery_not_generic` and
  `test_error_recovery_guide_documents_version_pin_recovery` all asserted
  `"git worktree add" in text`, pinning a recipe that cannot work. Replaced with assertions that
  the suffix is never called a commit and that the printed recipe, executed, actually pins.

## Finding: `incoming-bugs/` is gitignored, and an issue's `refs:` can point into it

`.gitignore:113` ignores `incoming-bugs/` wholesale. The chunk 02 delegate could not read the
report its own issue references, because the directory exists only in the primary checkout and is
in no branch's history. Two consequences worth deciding on separately from this plan:

- **#518's `refs:` names evidence nobody else can open** — not the delegate, not a reviewer, not
  a future reader of the issue. The verified recipe survived only because the issue body repeated
  it in a `<details>` block.
- The reports are **unbacked**. A lost checkout loses every bug report not yet promoted to an
  issue.

Not fixed here — it is a repo-convention decision, not a release blocker. Flagged to the owner.

## Release facts owed to the change-log and to the cut

- **Chunk 01 is itself `Re-vendor: recommended`.** Its diff touches `install_paths.py`,
  `install_ops.py` and `__init__.py` — vendored but NOT in `_FINGERPRINT_PATHS` — so by the very
  rule it adds to `docs/release-process.md` step 5, it is a recommended re-vendor, not a required
  one. The release commit body must carry that verdict.
- **Chunk 01 corrected the release-blocking sentence.** `docs/release-process.md`'s consumer-facing
  section claimed that a release which did not flip the fingerprint meant "nothing to do". That
  sentence is why #310 was a release blocker and not merely a bug; step 5 now carries a third
  verdict, `Re-vendor: recommended`.
- **Chunk 01 pinned the handshake fingerprint with a golden value.** Now that the hash helper is
  shared between the hard and advisory fingerprints, a well-meaning change from the advisory side
  would silently invalidate every install in the field. `test_handshake_fingerprint_value_is_
  unchanged_by_the_shared_hash_helper` pins it to the pre-change value.

## Files touched outside a delegate's stated ownership (disclosed, no collision)

- **Chunk 01 → `hallucinote_mcp/tests/unit/test_version_fingerprint.py`.** The `_hash_file` →
  `hash_path_into` rename the design mandates has three call sites there; the alternative was an
  alias nobody needs. Mechanical rename plus one added test. No other chunk owns the file. The
  partition held — the delegate reported it rather than letting integration find it.

## Backlog candidate raised by chunk 01 (file at close, not now)

Under `coexistence_divergence: true` the advisory compares the vendored tree against the
**invoking interpreter's** package, but the handshake's real reference is the *running server's*
copy, which the preflight process cannot read — `preflight` has `--server-version` but no
server-root override. Out of scope for #310 and correctly left alone; it is a real gap in the
advisory's honesty under a divergent-coexistence install.

## Chunk 05: what it closed, and the residue it did not

**Closed.** The defect was reduced to a runnable repro before any code changed, per the brief:
pre-fix, all four scaffold tracks are captured, `probe_and_link` matches them all by name,
`unmatched_live_tracks` empties and the W18-D classifier is permanently silent. Post-fix the same
script captures one real track and reports all four in `default_scaffold_unmatched_tracks`.

A second fix rode along and matters independently of #514: survivors are now numbered by **dense
rank** rather than the raw Live index. `create_track` upserts on `(song_id, track_index)`, so a
snapshot numbered *around* the scaffold would replay the same song track into a second row once
the scaffold was deleted.

**`[RESIDUE: the scaffold RETURNS are still captured as song content]`** — not a silent gap, and
not a defect in this chunk. Live's default `A-Reverb` / `B-Delay` ship WITH devices, so the
settled untouched predicate (name AND no devices AND no clips) can never fire on them; applying
it to returns would be dead code, and a name-only return exclusion would drop a claimed return's
captured mix and break replay, since a surviving track's `sends` map would name a return the
snapshot no longer defines. Track-only satisfies the issue's Expected clause and all three
Done-when items. But the consequence stands: on a pre-cleanup capture the scaffold returns still
become permanent song content, and push-side return cleanup can never fire on them either.
**Follow-up item owed at close** — this is part of #514's problem statement that #514's settled
predicate cannot reach.

**Two deliberate non-changes, both reasoned rather than skipped.** `compile_snapshot` does not
filter, because deciding "untouched" needs a clip inventory it never sees, and a name-only drop
there would silently discard a `3-Audio` track carrying a user's audio clip and no device — a
real shape on the `/song-pick-instruments` hand-assembly path. The reason is written into the
docstring, not just the report.

## Integration debt (coordinator)

- **`docs/snapshot-schema.md` documents the analyzer capture exclusion but not this one.** Genuine
  artifact drift, outside every delegate's ownership. One paragraph, owed at integration.
- **Layering nit for the Critic's judgment:** chunk 05 adds a `capture.py` → `sync.push.probe`
  import to keep one source of truth for the canonical scaffold names. That edge is slightly
  backwards. The SNP-8R4K precedent solved the same shape by extracting `analyzer_identity.py` to
  the top level; the parallel move is a `hallucinote/default_scaffold.py`. Creating a new module
  was outside the owned set, so it was flagged rather than taken.
