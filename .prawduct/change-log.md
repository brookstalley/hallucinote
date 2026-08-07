# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously.

     TAG-LINE FORM (canonical — the lifecycle tooling only reads this shape).
     One HTML comment at the HEAD of the entry body (before any prose), wrapping
     exactly this payload (NOTE: delimiters written as words, because a literal
     closing delimiter here would end THIS comment early — HTML comments do not
     nest, and that bug hid the paragraph below as visible body text):
         open-comment prawduct: type=<t> | chunks=<a,b,c> | scope=<tag> | status=<s> | release=<r> close-comment
     Pipe ` | ` separates keys; `chunks` is a COMMA list (never pipe — pipe is the
     key delimiter); keys are freeform (unknown keys are preserved). A tag line
     placed after prose is treated as body text, not metadata.

     RELEASE VOCAB for in-flight work (VEW-9QH4): tag `release=unreleased` while the
     work sits on develop with no release cut. At release cut, flip it to the real
     `release=vX.Y.Z` (mirrors how v1.4.0/v1.5.0 tags were flipped). This avoids
     pre-bumping a version (against `feedback_no_premature_version_bump`) or
     mislabeling in-flight work as an already-shipped version. -->

## 2026-08-07 — Six defects the demo song found by actually being rebuilt

<!-- prawduct: type=bugfix | chunks=B1 | scope=tour+push+workspace+db-converger | release=unreleased -->

Building `examples/angle-of-the-light` end to end surfaced six framework defects.
Every one was found by *reproducing from scratch* — pushing into an empty Live set,
rendering, rebuilding — and not one by reading code. That is the finding worth
keeping: a push into a set that already matches reports OK and proves nothing,
which is exactly the claim the tour makes to its readers.

**Preset names matched as substrings.** A captured `browser_path` leaf was resolved
with `mode="substring"` although the leaf IS the browser item's own display name.
`Kit-BritishVintage.adg` therefore also matched `MPE Kit-BritishVintage.adg`, and the
strict loader refused the ambiguous pair. `exact` existed for precisely this shape and
the sibling test already described the contract in prose; the code was contradicting
its own documentation.

**A stale device link survived a Live set swap.** Reconciliation asked only whether the
link's PARENT still existed, never whether the device's own index did. Live's factory
`B-Delay` makes this routine: an authored device loads at index 2 behind the stock one,
and a fresh set puts index 2 out of range while the parent still matches by name. The
planner then read the link as present, skipped the load, and every parameter write
addressed an index nothing would ever create — a permanent halt, not a race.

**`testpaths` excluded `examples/`.** The demo song's own tests never ran in CI, so its
"builds headless with no Live" claim was asserted rather than checked.

**The workspace marker was unreachable below the session root.** `find_workspace()`
walked upward only, so `resolve_song_dir` fell through to a *silently successful*
relative `songs/<slug>`. Renders wrote ~290 MB into a phantom directory and analysis
then reported "the song isn't built" and advised a rebuild — for a song that was built,
elsewhere. Fixed with bounded downward discovery that declines on ambiguity, plus error
text that distinguishes the three failures. Deliberately NOT fixed by adding a root
marker: that fixes one repo rather than the class, and converts "the framework repo
contains a bounded workspace" into "the framework repo IS a workspace".

**Mark-and-sweep deleted rows the build had just converged.** `build_session` tombstones
any build-owned row the build did not touch, and sixteen mutators returned without
registering their touch. `replace_breakpoints` registered none on ANY path, so a build
that CHANGED an arc lost it too — producing an infinite create/delete/create loop that
never converges. Fixed structurally with a `_touches` decorator applied outside
`_atomic`, because the trap is a property of the return path and patching today's
returns leaves the next one to re-open it.

**Live's "do not retry" guidance was unreachable.** Every `read_timeout` equalled its
`main_thread_timeout`, while `run_on_main` spends up to 2.0 s on admission before its
bout timer starts — so the client always gave up first and the agent got a bare socket
timeout instead of the one instruction that stops it queueing more work behind
uncancellable Live operations. The implicit 15/15 default was never checked at all,
because the test only iterated the explicit entries. Caller ceilings widened; the
invariant is now asserted strictly.

`examples/angle-of-the-light` was RETIRED from the tree in the same batch. It was
a scouting run: its real output was the six defects above, found by rebuilding it
from scratch, not its audio. It is archived outside the repo with both masters and
its decision records, and its ADRs remain in this branch's history. The next take
is re-authored from a sparse prompt through discovery and elicitation, so it will
be a different song by design — see `tour-walkthrough-design.md`, *A walkthrough,
not a recipe*.

Two more were pinned rather than fixed and are filed: push appends behind a matched
parent's foreign devices while promising to load over them (no reorder API in Live 12.4,
so the honest fix is a chain-tail rebuild), and `run_on_main` releases the bout lock on
the timeout path, so admission stops refusing while Live is still committed.

Suite 4830 -> 4865 passing across the batch; ruff and mypy clean.

## 2026-08-06 — The tour's capture tooling, built against probes that kept saying no

<!-- prawduct: type=feature | chunks=A2,A3,A4 | scope=tour | status=shipped | release=unreleased -->

Three chunks of Phase A tooling, and all three had the mechanism their plan specified
falsified by the verify-api probe that plan required first. That is the whole story of
this batch, and the reason the step is not ceremony.

**A3 asked GitHub whether it renders an inline `<video>` from a repo path.** It does
not, and the reason is stronger than "the relative src won't resolve": the sanitizer
removes the **element**, absolute `raw.githubusercontent` src included, and
`![clip](x.mp4)` degrades to a broken `<img>`. Only a poster still linking to the mp4
survives. So the hero is a poster — which is what C1 now knows to capture, before
spending the shoot rather than after.

That verdict then propagated backwards into A3's own other deliverable. The `showwaves`
video existed to make audio "skimmable inline rather than a download link"; once nothing
renders inline, a waveform video is a megabytes-large download link showing a moving
line. An 8 KB `showwavespic` still renders inline and shows the whole arrangement's
dynamics, so it replaced the video. Killing a specified deliverable was only visible by
re-reading *why* it was specified.

**A2's mechanism did not exist at all.** Ableton Live publishes zero accessibility
windows — `count of windows` is 0, `AXWindows` empty — and its own AppleScript
dictionary blocks 120 seconds before failing with -1712. No AppleScript path yields a
window id. `CGWindowListCopyWindowInfo` through `ctypes`, serialised via
`CFPropertyListCreateData` for `plistlib`, does, and adds no dependency. A2's capture
remains blocked on Screen Recording permission, which only the operator can grant; the
tool now preflights it and names the host app, because the native failure reads as a bad
window id.

**A4** is theme-*proof* rather than theme-lucky: `prefers-color-scheme` follows the OS
while GitHub's toggle is its own, so every label sits on an opaque card and a
disagreement changes only the gaps. Verified by rendering all four combinations.

The cumulative Critic returned 0 blocking, 9 warning, 9 note; fifteen were fixed in one
commit. The most valuable found a failure no other guard could see: the capture
manifest's `status`/`analyzer_not_terminal`/`terminal` flags were ignored, and an
incomplete render yields a *short but valid* master, so bounds, duration and size checks
all agree with each other and are wrong together. It also found the publication gate had
no credential rule, and that A2/A3 left stale output in place on failure — the exact
trap A1 closes.

One mistake is worth recording because it generalises. A comment here claimed an
out-of-range ffmpeg seek writes a zero-length file, and a guard was built on it. ffmpeg
exits 0, with empty stderr, writing 428 bytes of valid mp3 header — sailing through that
exact check. When a guard's premise is a claim about a tool's behaviour, the claim is a
test, not a comment.

## 2026-08-06 — Session transcripts become publishable, behind a gate that fails closed

<!-- prawduct: type=feature | chunks=A1 | scope=tour | status=shipped | release=unreleased -->

`tools/tour_transcript.py` renders a real Claude Code session JSONL into a markdown
excerpt fit to publish, so the tour quotes genuine agent output instead of a hand-written
reconstruction — which is the first thing a skeptical reader catches — and can be
regenerated after a behaviour change instead of rotting.

The renderer is mostly a disclosure gate. A transcript carries absolute `/Users/<name>/…`
paths in three encodings, hook output, and whole memory files injected as
`<system-reminder>` blocks. So record types are an allowlist where an unknown type
*raises* rather than being skipped, only `text` blocks survive, tool calls render as
one-liners rather than full inputs, and the finished document is re-scanned for every
forbidden pattern before a byte is written.

Reality validated the fail-closed stance three separate times, each on a real session and
none on the fixture: an unseen `queue-operation` record type, and two gates keyed on the
*marker* rather than on the thing that leaks. Re-keying them onto the account segment
closed a real hole in the other direction — `/Users/alice` with no trailing slash had
been escaping redaction entirely.

Three independent Critic rounds then found three leak paths in a module whose entire
purpose is not leaking, including dash-encoded home paths, which the chunk's own
`grep -c '/Users/'` acceptance check had certified clean. The generalisable rule, now a
comment in the code because it outlives this work: **a gate that shares its patterns with
the mechanism it guards cannot catch that mechanism's blind spot.** The fix was not a
better pattern but a rule keyed on the redactor's *output shape*.

## 2026-08-06 — Internal bug reports leave the public record; the backlog id becomes their provenance

<!-- prawduct: type=chore | chunks=C3 | scope=pub-ready | status=shipped | release=v1.7.2 -->

The first pass at "get the internal bug inbox out of the public repo" ignored the raw
drop-zone and kept `incoming-bugs/archives/` tracked, because ~130 references from
shipped source comments, tests and plans cited those files as provenance. The Critic
measured the result and found it untracked **zero** files — and that the three freshly
triaged reports had gone from local-only to public. It also drew the right line: whether
64 internal reports get published is the owner's decision, not a chunk's.

The owner chose to untrack them, which meant paying the repointing cost. 108 references
across 24 files now carry a non-file provenance form: the **backlog id** where one
exists (50 of the 64 reports map to one), and the report's own title restated inline for
the other 14. A restatement beats a link nobody can follow.

That inverts this repo's usual link-don't-summarize rule for exactly one class of file,
so `project-preferences.md`'s triage norm was rewritten rather than left to contradict
the tree — the backlog item is now the citable evidence, and nothing tracked may cite a
path into the dropbox.

Four references used an elided (`…`) path form invisible to a whole-name match, and one
in shipped source wraps its filename across two lines — the reason an earlier sweep
reported itself complete while leaving dangling pointers behind. Sweeps here match on
the prefix, not the full path.

## 2026-08-06 — The repo gets ready to be public

<!-- prawduct: type=chore | chunks=C1,C2,C3,C4,C5,C6 | scope=pub-ready | status=shipped | release=v1.7.2 -->

An audit ahead of making the repo public found the engineering substrate sound — 4614
tests green, ruff/mypy/uv-lock clean, CI real and gating four things, no secrets, MIT
LICENSE and CONTRIBUTING present, every README link resolving, develop and main in sync
at v1.7.1. What it also found was six classes of exposure that only matter once
strangers can read the tree.

The sharpest was a reference disclosing a *private* sibling project's local filesystem
path and file inventory, inside an archived design doc that cites that project ~20 times
as the precedent for the 13-tool surface. Deleting the discussion would have gutted the
doc; the project's repo URL had already been deliberately redacted, so the name was
anonymized and only the pointer removed. Fifteen hardcoded `/Users/<name>/...` paths
across six files went the same way.

`SECURITY.md` states the trust model rather than implying one, and its central claim is
uncomfortable on purpose: a song's `build.py` is executable Python, so building someone
else's song runs their code with your privileges. That is the feature — it is what makes
a song forkable and reproducible — so reports of the form "build.py runs arbitrary code"
are working-as-designed. The line that *is* defended: song **data** must never reach
execution without someone running `build.py`.

`architecture.md` and `api-contract.md` were both *required* by recorded structural
characteristics and both absent. They now name the four-runtime topology, why the
process boundary into Live is forced rather than chosen, and the three tracked API
decisions — fingerprint-not-semver versioning, the errors-teach model (the consumer is
an LLM, so an error is the next turn's input), and a deprecation policy that refuses to
build compatibility shims for consumers that do not exist.

The `incoming-bugs/` decision inverted under investigation. Untracking it wholesale
would have dangled ~130 references from shipped source comments, tests and plans that
cite `archives/` as provenance — so only the raw drop-zone is ignored. That dig also
turned up 11 refs in shipped source and tests still naming pre-archive paths, silently
stale since those files were archived. *(Superseded the same day — the owner chose to
untrack the whole tree and pay the repointing cost; see the entry above.)*

Deliberately not done: the hero image is still a placeholder, deferred to a dedicated
pass with a new demo song showing the full create → push → arrange flow. And the
`project-state.yaml` / `learnings.md` size-compaction advisories were declined with
reasoning rather than half-executed — `learnings.md` is already 70 rules averaging 695
bytes, and compacting further means deleting rules.

**Re-vendor: required.** This release changes no behavior at all — the only edits under
`src/` and `tests/` repoint doc comments from `incoming-bugs/` paths to backlog ids. But
one of those repointed comments is a docstring in
`hallucinote_mcp/.../handlers/_arrangement_latch.py`, and the handshake fingerprint
hashes file *content* under `handlers/`, so it flipped anyway: `53201e72fa4d` →
`aeb1af696f59`. Marketplace consumers must re-run `/ableton-mcp-install` and fully quit
+ reopen Live, or every bridge call fails the version handshake. A zero-behavior release
forcing a re-vendor is the fingerprint design working as specified, not a defect — the
cost is real, and worth knowing before editing prose inside a fingerprint path.

## 2026-08-03 — Capture takes get a rolling window (renders no longer grow without bound)

<!-- prawduct: type=feature | chunks=1,2,3,4 | scope=aud-2d6t | status=shipped | release=v1.7.1 -->

Nothing in the tree ever deleted a capture. Every `ableton_render` wrote a take to
`songs/<slug>/captures/<ts>/` — a 48 kHz stereo 32-bit-float WAV per track, return and
master, ~23 MB per surface-minute — and every take was kept forever. A reported
real-world song had takes reaching ~4 GB each.

The audio format is not the lever and was left alone: float32 is what lets the master
overshoot analysis measure above 0 dBFS at all (`audio/attribution.py`). Retention is
the lever, and it is safe because captures are **write-once, read-once**: the render
writes them, `ableton_analysis` reads them once and emits a self-contained MixReport to
`songs/<slug>/analysis/<ts>.json`, and baseline comparison resolves against those JSONs
(`audio.compare.resolve_baseline` keys on `db_seq`) — never re-opening a WAV. The
MixReport trail is the audit log of mix evolution and is never swept; what a sweep costs
is re-analyzing one specific take with different parameters.

New `hallucinote.takes` owns the window, split plan-then-execute the way the sync layer
splits `PushPlan` from execution: `plan_sweep` classifies every take while writing
nothing, `execute_sweep` removes what the plan named and collects per-take failures
rather than letting one locked directory strand the rest. Two guards never sweep — a
`.pinned` take (which also does not consume a keep slot, so pinning a reference can't
silently evict a working take) and a take whose `status.json` still reads
`state="running"`. It lives at the package top level, not under `hallucinote.audio`,
because that package eagerly imports the numpy/librosa stack and the MCP server is
stdlib-only at startup — the same constraint that placed `paths.py`.

The sweep runs automatically in `server.py` before an `ableton_render(start)` is
forwarded, keeping the newest 2 takes. Render start is the one moment no take is in
flight (one render at a time), so it cannot race a capture. Scope is always the song's
own captures root, never the parent of a caller-supplied `output_dir`, and the incoming
dir is protected explicitly; the whole thing is best-effort, so disk hygiene can never
cost a capture. `HALLUCINOTE_CAPTURE_KEEP` sets the window, `HALLUCINOTE_CAPTURE_SWEEP=0`
turns it off.

`hallucinote captures list | prune | pin | unpin` is the operator surface. `prune`
requires an explicit `--song` or `--all` — reading is safe and defaults to everything,
but deleting gigabytes is not what a forgotten argument should do — and `--dry-run`
previews. `recency_key` was hoisted out of the analysis handler's `_capture_recency_key`
into `takes` so the sweep's ordering and the analysis selector's "newest take" are one
definition; had they drifted, a sweep could have deleted the take the next analysis
would have chosen.

`/render-analyze` also carries a **when-to-pin policy**, recorded here because it is
shipped agent behavior a maintainer would otherwise find only in a commit body: pin on
expressed intent to keep a take (not on a nickname or a compliment), and say so when you
do. A pin is permanent *and* free of a keep slot — `plan_sweep` appends pinned takes to
`kept` before the budget decrement — so pinning on weak signals would re-create the
unbounded growth this window exists to bound.

Departs from backlog AUD-2D6T's proposed shape (a manual `tools/audio-prune`): a manual
tool relies on the operator remembering, which is the regime that produced the 4 GB
takes. The CLI is kept, but the sweep is automatic. Retention policy (auto-sweep, keep
2) chosen by the user 2026-08-03. Server-side only — `server.py` and
`server_side/analysis.py` are outside `_FINGERPRINT_PATHS`, so no Live re-vendor.

**Verified against real data**, not only fixtures: on this repo's own
`songs/missing/captures/` (one 406.3 MB take), `captures list` reported it,
`prune --keep 0 --dry-run` named it and removed nothing, `pin` followed by a real
`prune --keep 0` left it untouched ("nothing to prune (1 take(s) kept)"), and
`unpin` restored it — so the pin guard was exercised against a take that would
otherwise have been deleted. The AUTOMATIC render-path sweep is unit-tested
against a faked `client.send` but needs a live render to confirm end-to-end; it
is queued in `.prawduct/operator-verification.md`.

## 2026-07-20 — Provenance tests no longer assert ambient git state (first red PR-CI run)

<!-- prawduct: type=bugfix | scope=highroi-sweep | status=shipped | release=v1.7.1 -->

`test_provenance_metadata_captures_standard_signals` asserted `"branch" in meta`
against whatever checkout the suite happened to run from. `actions/checkout` checks a
`pull_request` out at the **detached merge commit**, so `git symbolic-ref --short HEAD`
exits non-zero and `provenance_metadata()` correctly drops `branch` — the helper is
documented best-effort. The test, not the code, held the false premise that a git
checkout is always on a branch. It went unseen from 2026-05-21 (PR #74) because CI's
`push:` runs on develop check out a real branch ref; PR #213 was the first
`pull_request:` run to exercise it.

All four provenance tests now build a throwaway one-commit repo and `chdir` into it, so
the branch name is a *known* value rather than an ambient one — which makes them
stronger, not weaker: `test_build_session_auto_captures_metadata` previously settled for
`"git_sha" in meta or "branch" in meta` and now pins auto-capture to the real probe by
asserting the controlled branch name. Added the missing halves of the documented
contract as regression tests: detached HEAD drops `branch` while keeping `git_sha`, and
a non-git cwd drops both while keeping `hostname`. Reproduced against a real detached
worktree (old test fails, new passes) rather than trusting the local attached checkout.
Suite 4523 → 4526.

## 2026-07-20 — Repo hygiene sweep: gitignore contract, stale branches, untracked reports

<!-- prawduct: type=process | scope=highroi-sweep | status=shipped | release=v1.7.1 -->

Local and remote git hygiene. `.gitignore` reconciled with the prawduct session-file
contract via `prawduct-hook update-gitignore`: adds `.critic-active`,
`.critic-partials/`, and `.session-base-tree` (session state that was landing as
untracked noise), and un-ignores `.prawduct/artifacts/build-plan.md`, which is
tracked-by-contract. Four backlog items written during the 2026-07-07 re-vendor/restart
analysis (MCP-6D3V, INS-8F2R, INS-5J9C, INS-7Q4Y) and three 2026-07-11 incoming-bug
reports were sitting uncommitted on disk — both now landed, the reports pending triage
per the usual triage→archive loop. On the remote: `fix/syn-9f4k-empty-rack-fail-loud`
deleted (merged via PR #200) and the stale tracking ref for
`fix/quickwin-cluster-mcp1v8k-pshphaseorder` pruned (squash-merged as PR #205), leaving
origin at `main` + `develop` + the active branch. Dropped a stash from the deleted
`fix/snp-8r4k-live-chunks` branch, verified subsumed (the `mix → devices → routing`
phase reorder it held is present in HEAD).

## 2026-07-04 — Pull-durability loop-close: contract UX + /song-snapshot empty-diff bake (BAK-7D2V Chunks 2–3)

<!-- prawduct: type=feature | chunks=B,C | scope=highroi-sweep | status=shipped | release=v1.7.1 -->

Closes the pull-durability item (Chunk 1's replay guard shipped in v1.7.0 / PR #210).
**Chunk 2 — pull-side contract UX:** `pull_cli apply/execute` now print a durability
notice on stderr after a mix-layer pull ("N change(s) staged in the regenerable DB
only; on a stamped snapshot the next `build.py` will REFUSE rather than revert — bake
with `/song-snapshot`"). The notice, the `/ableton-pull` skill, and `docs/song-workflow.md`
all state the refusal as conditional on a `captured_at` stamp: a legacy unstamped
snapshot gives replay no ordering evidence, so it warns and still reverts.
It fires on the same EVENT KINDS the guard arms on, by reusing the guard's own
`_REPLAY_ASSERTED_EVENT_KINDS` via new `capture.count_request_replay_asserted_events`
(scoped to the just-applied pull's `request_id`) — no parallel domain whitelist to
drift. (Kind parity, not outcome parity: what the guard then DOES with those events
depends on the snapshot's stamp — refuse when stamped, warn-and-revert when not.) Quiet on zero-change applies, build.py-owned domains, and dry-runs. The
`/ableton-pull` skill is reframed (BAK-3M9T Chunk D): names the bake as the closing
move and the refuse-not-revert behavior. **Chunk 3 — loop-close:** `/song-snapshot`
closes the pull-then-hand-revert corner, where the guard is armed by pull EVENTS but a
fresh capture shows no content diff. On an empty diff it now BAKES the refresh it just
captured (`capture merge` over `captured_session.json`), which disarms the guard and
carries a fresh `captured_at`. It deliberately does NOT merely re-stamp: an empty
`capture diff` does not prove the snapshot is current, because the diff never compares
device sidechain sources, drum-pad mappings, or per-chain authored props — all of which
replay re-asserts. A pull touching only those fields diffs clean, so a re-stamp would
disarm the guard over stale values and let the next build silently revert the pulled
work (found by Critic review before merge). `capture_cli restamp` (+
`capture.restamp_captured_at`) survives as an explicit operator override on an
ALREADY-stamped snapshot, warning that it asserts freshness it cannot verify. It now
REFUSES (exit 2) a snapshot with no usable `captured_at`: replay reads an unusable
stamp as "no ordering evidence" and warns before reverting, so back-stamping one
would trade that last signal for a silent pass. `--force-replay` remains the
conscious-discard path, and re-warns every build rather than disarming permanently.
`/song-pick-instruments` snapshots already carry `captured_at` (via `compile_snapshot`);
`docs/song-workflow.md` names the enforced pull→bake→build contract. **Live operator-
verification** (dial → pull → build refuses → snapshot → survives → force-replay reverts,
plus a pull the diff is blind to) is queued, not gated. Tests: notice fire/silence +
helper discrimination + restamp disarm/idempotence + the diff's replay-asserted blind
spot and merge's coverage of it + a doc-drift lock on the skill's empty-diff commands.

## 2026-07-04 — Change-log tag canonicalization + unreleased vocab (VEW-7T2C, VEW-9QH4)

<!-- prawduct: type=process | chunks=A | scope=highroi-sweep | status=shipped | release=v1.7.1 -->

The lifecycle tooling (`TAG_LINE_RE` / stamp-merged / regen-views in the plugin's
`lib/views.py`) now sees the whole log. Swept 34 historical tag lines from the
pre-canonical space-delimited form (`chunks=… status=…`) to the canonical
pipe-delimited `prawduct:` form: added the `prawduct:` prefix,
converted key separators to ` | `, and fixed `chunks=A|B|C` values (pipe collides
with the key delimiter → truncated chunk lists) to comma form. Relocated 3
foot-positioned tag lines (v0.9.0–v1.1.0 entries) to the entry head so the parser
reads them as metadata. Resolved 10 `release=unreleased status=shipped` entries to
the release that FIRST contained each commit — 7 to `release=v0.9.5`, 3 to
`release=v0.9.2`. **Corrected during PR review:** the first pass resolved all 10 to
`v1.5.0` on the rule "ancestor of v1.5.0 but not of v1.4.0", which is not the same
question as *which release shipped it*. This repo ran two concurrent version tracks
— the v0.9.x series is chronologically LATER than v1.2.0–v1.4.0 (v0.9.5 is
2026-06-12; v1.4.0 is 2026-05-28) and the two only converged at v1.5.0, whose tag
subject is "version-track unification". So a commit can sit outside v1.4.0 while
already having shipped in v0.9.2/v0.9.5. Use `git tag --contains <sha> | sort -V |
head -1`, never an ancestor test against one later tag. Re-verified per scope
(friction-basket/AUD-4W7K/AUD-3F8M → v0.9.5; install-hardening/tools-don't-narrow/
audio-verification → v0.9.2); this also keeps these entries consistent with
un-flipped siblings from the same window (e.g. INS-7V2D → v0.9.3) instead of
splitting one release window across two `release-notes.md` sections.
Documented the `release=unreleased`→flip-at-release vocab in the change-log
header (VEW-9QH4). Result: **every entry but 2** parses as tagged (75 of 77 at this
branch's tip; the count moves as entries land); the 2 remaining are
genuinely tag-less pre-v1.4.0 entries (never carried a tag — left untouched rather
than fabricate chunk IDs). Verified against the live parser for both visibility and
per-entry chunk-id integrity. **Framework-coupled deferral:** the parser itself lives
in the plugin (not this repo) — no tooling change here. No post-v1.7.0 unreleased
commits exist (develop == main at v1.7.0), so the "missing entries" audit is
trivially satisfied.

## 2026-07-04 — CI: the four gates run off-laptop; lint/type debt to zero (INF-2C4X)

<!-- prawduct: type=infrastructure | chunks=INF-2C4X | scope=ci,lint,types,tests | status=shipped | release=v1.7.0 -->

Closes audit rec #4 — "green" no longer means "someone remembered to run it locally."
`.github/workflows/ci.yml` (push/PR to develop+main, ubuntu-latest, setup-uv pinned 0.11.8):
`uv lock --check` → `uv sync --all-packages --all-extras --locked` → `ruff check .` → `mypy` →
full **no-path** `python -m pytest` (the path-scoped form silently skips `hallucinote_mcp/tests`
— the standing learning, now encoded in CI). ruff (`E4,E7,E9,F,W,PLE`, no formatter): 170
findings → 0, re-export surfaces preserved via explicit aliases + commented per-file-ignores.
mypy (both packages, 201 files, default strictness): 92 → 0 — ~40 genuine fixes, narrow
commented override clusters for the Optional-narrowing debt (enumerated in pyproject as
tightening targets), per-module `ignore_missing_imports` only for genuinely stub-less packages.
The uv.lock re-lock + release-process lock-check/back-merge steps landed earlier on develop
(6f2b0ba). Shipped via PR #212. Known-accepted: single 3.12 runner (3.10 floor covered
statically by mypy); first linux run of the audio half is unverified until the first push
(`HALLUCINOTE_SKIP_AUDIO=1` documented in the workflow header).

**Re-vendor: required** — six `_FINGERPRINT_PATHS` files carry behavior-neutral lint/type edits
(imports/comments/annotations; no wire-shape change) — the fingerprint flips at the next release.

## 2026-07-04 — sync-boundary contract + ordering DAG + controlled unknown-kind halt (SYN-8Q3F, partial)

<!-- prawduct: type=refactor | chunks=SYN-8Q3F | scope=sync,artifacts,tests | status=shipped | release=v1.7.0 -->

Audit rec #8 — the push boundary gets an explicit contract and a complexity budget instead of
prose and point patches. Shipped via PR #211: **(a)** `sync-boundary-contract.md` — all **14**
push phases (code-derived; the prose said "thirteen") with ASSUME / RE-PROBE / failure-policy +
file:line refs, enforced by a coverage test; contract violations recorded honestly (V2, V3, V6,
V8 open — backlog-triage candidates in build-plan Chunk 06), not normalized. **(b)** phase
ordering: `_PHASE_DEPS` + `validate_phase_order` at plan time (unknown dep / dep-after-dependent
/ cycles raise before any request row); the tuple stays the single execution-order source, order
pinned byte-identical against a literal historical tuple. **(c)** the unknown-result-kind halt
class closed structurally: apply-layer contract-drift ValueErrors become a controlled phase halt
(atomic errors file with teaching hint, terminal state file, request closed `partial` in a
`finally`, EXIT_PARTIAL) — the class that was point-patched twice can't be a raw traceback
again. **(e)** the two diff engines' float semantics DECIDED as intentionally asymmetric (push
1e-6: false-EQUAL = wrong mix; pull 1e-3: false-DIFFER = DB churn) and pinned by cross-engine
tests calling both real comparison functions, known channel boundaries documented. Deferred:
**(d)** the `capture.py` split (Chunk 05 — was blocked on BAK-7D2V's parallel capture.py work,
now unblocked) + Chunk 06 violation triage. Two independent Critic reviews (0 blocking).

**Re-vendor: not required** — engine-side only; no `_FINGERPRINT_PATHS` file changed.

## 2026-07-04 — event-seed hardening: atomic write+emit, stable-ID event log, replay smoke test (EVT-6H9R)

<!-- prawduct: type=feature | chunks=EVT-6H9R | scope=db,tests | status=shipped | release=v1.7.0 -->

Audit rec #9 — "harden the seed while it's cheap." Shipped via PR #208, three legs:
**(1) atomic write+emit** — `@_atomic` on all 59 state-writing mutators wraps state-write +
`_emit()` in the existing re-entrant `transaction()` (nested mutators join via SAVEPOINT; only
the outermost commits); `transaction()` now opens `BEGIN IMMEDIATE` at depth 0 (closes a
Critic-reproduced WAL stale-snapshot-upgrade fail-fast under the MCP-server+build.py two-writer
topology) and unwinds its depth counter in a `finally` (a failed COMMIT can no longer strand the
connection in savepoint limbo). Crash-injection tests prove no state-row-without-event.
**(2) stable-ID event log** — `events.song_id/clip_id/request_id` FKs (ON DELETE SET NULL)
dropped via a guarded, idempotent, transactional table-recreate migration in `init_db`; the
audit log no longer loses lineage to a cascade. The PSH-3K9D dangling-clip guard (which existed
only to dodge the FK) is gone; `delete_clip` now stamps `clip_id` on CLIP_DELETED.
**(3) replay smoke test** — a representative mutator-built song's event log folds into a fresh
DB and must converge with materialized state (12 tables); FOLDED ∪ NOT_YET_FOLDED must cover
every event-kind constant, every FOLDED kind must be exercised, and `_emit` now validates `kind`
against the constants-derived frozenset (inline-string kinds can't ship). The notes-payload gaps
blocking full replay are pinned as a test + documented per-kind — the real EVT-4K8H blockers.
Independent Critic: PASS; both WARNINGs + both NOTEs landed.

**Re-vendor: not required** — engine-side only (`db/`); no `_FINGERPRINT_PATHS` file changed.

## 2026-07-04 — ceremony sweep: 4-obligation close-out, compacted governance mass, 30-day scrub (PRC-5W2N)

<!-- prawduct: type=process | chunks=PRC-5W2N | scope=process,docs,skills | status=shipped | release=v1.7.0 -->

Audit rec #10 — the bookkeeping tax, cut. Shipped via PR #209 (sub-items b/d landed earlier on
develop: one changelog surface at 6f2b0ba, main→develop back-merge at 50a66ae + now a mandatory
release step): **(a)** `reflections.md` 724KB → 143KB, 112 pre-June entries archived byte-exact
to the (gitignored, per-machine) `reflections-archive-2026H1.md`, 3 new distilled rules into
`learnings.md`; **(c)** ship stamping batched — backlog-close + change-log + state-record = ONE
commit (backlog header rule 1); **(e)** compose-pass bookkeeping: ~12 obligations across four
stores → **4 obligations, one close-out protocol** in `docs/song-authoring-conventions.md`;
`/compose-part`, `/compose-review`, `/mix-review` link to it instead of restating; all CLAUDE.md
norms preserved (Critic caught + fixed the one drop: kept moves still file `resolution: kept`
attempt entries so `related:` correction chains close); **(f)** `project-state.yaml` 50.2KB →
40.0KB, dead-plan narrative relocated, EMPTY-not-null footnote intact; **(g)** backlog staleness
suspicion threshold 60d → **30d** (velocity + the BLG-7K2Q 4/8-already-shipped precedent).

**Re-vendor: not required** — no engine/MCP code changed.

## 2026-07-04 — pull-durability guard: replay refuses to silently revert pulled live edits (BAK-7D2V)

<!-- prawduct: type=feature | chunks=BAK-7D2V | scope=capture,sync,docs,tests | status=shipped | release=v1.7.0 -->

Closes the audit's #1 finding: `/ableton-pull` bakes live edits into the regenerable DB only,
and the next `build.py`'s `replay_capture(captured_session.json)` silently re-asserted the
stale snapshot over them — both writers are `actor='sync'`, so actor precedence never saw the
conflict. The only defense was an unenforced "remember to re-capture" ritual; it is now
structural.

- **Snapshots carry `captured_at`** — stamped by `compile_snapshot` (both `/song-snapshot` and
  `capture_cli execute`) in the events-table timestamp shape; the song scaffold stamps its
  synthetic snapshot too. `capture_cli migrate` deliberately never back-stamps a legacy file
  (that would defeat the guard).
- **`replay_capture` refuses** (`StaleSnapshotError`, before any mutation) when the DB holds
  events from a `requests.kind='pull'` request, of a kind replay re-asserts (mix layer only —
  staged clip-notes/tempo/tuning pulls never trip it), NEWER than `captured_at`. The message
  names the offending rows, the durable fix (re-capture), and the override.
- **Override:** `replay_capture(..., allow_stale_snapshot=True)`; scaffolded `build.py` exposes
  it as `--force-replay`. Forcing is per-run consent — the guard re-arms until a re-capture.
- **Legacy (unstamped) snapshots warn instead of refusing** — no ordering evidence exists, and a
  permanent false alarm would teach users to force habitually; the warning funnels to a
  stamping re-capture.
- Full-fix design (enforced staging + one durable bake; write-through and actor-separation
  alternatives rejected) at `.prawduct/artifacts/plans/BAK-7D2V/design.md`; corrects
  `authorship-model.md`'s "code vs snapshot is not a new conflict" claim.
- **Critic fixes:** pulled **nested-rack-chain deletions** now arm the guard
  (`device_chain_deleted` added — the cascade kills nested devices event-less, so the chain
  event is the sole signal; full pull-mutator→event-kind audit table in the design);
  `captured_at` shape check is a **fullmatch** so a timezone-offset stamp (up to +14h ahead
  lexicographically) takes the legacy/warn path instead of silently defeating the comparison;
  refusal/warn messages spell the complete re-capture recipe (`capture_cli execute` writes
  `captured_session.refresh.json`, NOT the canonical file); Live operator verification queued
  in `.prawduct/operator-verification.md`.

**Re-vendor: not required** — engine-side (`capture.py`, scaffold, docs); no
`_FINGERPRINT_PATHS` file changed.

## 2026-06-24 — v1.6.1: standing timbre metrics (brightness · noisiness) in the mix report (AUD-8T3K)

<!-- prawduct: type=feature | chunks=AUD-8T3K | scope=analysis,docs,tests | status=shipped | release=v1.6.1 -->

Standing **timbre** per surface and per section in the mix report, so a directive like "make X
brighter / noisier / grittier" is now verifiable against a number, not only by ear.

- **AUD-8T3K** — new `audio/timbre.py` `measure_timbre()` → spectral **centroid · flatness ·
  rolloff**, taken as the median over silence-gated frames (the gate makes the median fair for
  sparse / percussive material, so a noisy single frame can't dominate). Flatness is computed
  over **Bark bands** — raw FFT bins crush to ~0 for pitched material — and the Bark grid was
  extracted to a behavior-preserving `audio/bark.py`; the centroid helper was lifted out of
  `automation.py` and de-duplicated. `TimbreMetrics` rides per-stem **and** per-section
  `StemMetrics` (NaN→null), surfaced through `compare.py` with thresholds flagged
  `provisional: true`; section centroid is registered as the DR-3 `spectral_centroid` energy
  correlate, so brightness ranks against declared energy. `SCHEMA_VERSION` stays `"1"`
  (additive fields; the differ degrades gracefully against a pre-timbre baseline). Follow-up
  **AUD-TIMBRE-CALIB** filed for the re-capture-jitter study that will drop the `provisional`
  flag.
- **Docs** — corrected the post-1.5.0 version-lockstep narrative in `docs/release-process.md`.

**Re-vendor: not required** — no `_FINGERPRINT_PATHS` file changed since v1.6.0 (engine-side
analysis + docs only). The auto-updated server and the existing vendored Remote Script still
compute the same fingerprint; marketplace consumers need take no action.

## 2026-06-23 — v1.6.0 catch-up: clusters shipped to develop since v1.5.0 without an individual change-log entry

<!-- prawduct: type=feature | chunks=MICROTUNE,MCP-9R3T,MCP-5N8K,MCP-7F2K,MCP-7P3R,MCP-2K9F,MCP-8H4N,PSH-3K9D,PSH-8K3D,SYN-7N4K,IDX-5W2P,SYN-4R7P,SYN-9F4K,SYN-RENDER-RELINK,SYN-SCAFFOLD-MISLINK,SYN-RACK-PRESET-RELINK,ARR-ORPHAN,REC-4Z8Q,DOC-7K3M,DEC-CAP,master-true-peak,FK-clip-guard | scope=tuning,mcp-bridge,mcp-render,sync-push,sync-pull,db,analysis,methodology,docs,tests | status=shipped | release=v1.6.0 -->

A consolidated entry for work that merged to `develop` between v1.5.0 (2026-06-17) and this
release but never got its own change-log entry — reconstructed from commit history at release
time so the v1.6.0 notes don't silently omit it. The six clusters that *do* have full detail
(ARR-PROJ, ARR-CMPHALT, SYN-2D9K, RND-2R9K, PSH-3H8M, MCP-1V8K/PSH-PHASEORDER) keep their own
entries below. One line per otherwise-unentered cluster:

**MCP bridge — async + reliability**
- **MCP-9R3T / MCP-5N8K** — `render` and `analyze` became async `start`/`status` actions; the synchronous `render` was retired; `/render-analyze` runs render+analyze out of the agent's context; start+poll is taught (PRs #182, #183, #185, #186).
- **MCP-7F2K / MCP-7P3R** — handshake-fingerprint relocation, an arrangement-recovery path, and a transport-teaching correction (PR #183).
- **MCP-2K9F / MCP-8H4N** — reliability papercuts: probe-set no-op exposure + version-mismatch self-diagnosis (PR #181).
- arrangement clip `list` now carries `note_count` + `muted`, with a read signpost from `ableton_arrangement`.

**Tuning — a new feature**
- **MICROTUNE (TUN-4Q7W)** — alternate tunings as an isolated bolt-on: an integer-MIDI degree mapper into unchanged generators, a worked 19-EDO example, a gated lens caveat + drift-warn + push re-load instruction, the verify-api close, and the `/tuning-pull` command (Chunks 1–4).

**Sync round-trip reliability**
- **PSH-8K3D / SYN-7N4K / IDX-5W2P** — swell rebuild-reliability cluster (PR #180).
- **PSH-3K9D** — push devices phase diff-reconciles (skips already-current params) + a mid-phase progress heartbeat.
- **SYN-4R7P** — probe-and-link reconciles stale `arrangement_clip` links by position (PR #191).
- **SYN-9F4K** — push devices phase fails loud on an empty rack (preset-didn't-load) instead of writing into nothing (PR #200).
- **SYN-RENDER-RELINK** — probe-and-link / pull / capture all normalize the analyzer's render-rename suffix so a render no longer breaks relink.
- **SYN-SCAFFOLD-MISLINK** — drop set-swap-mislinked track links onto a fresh default scaffold.
- **SYN-RACK-PRESET-RELINK** — honor `.adg`/`.adv` as a standalone preset load source + a normalized-value pan retry; `device_chain_props` registered ack-only in `apply_push_results`.
- **ARR-ORPHAN** — `replace_notes` is a true total-replace on arrangement clips (full-extent clear before set) (PR #202).
- **FK-clip-guard** — `unlink_db_from_ableton` guarded against a dangling `events.clip_id` foreign key.

**Analysis / lenses**
- **master-true-peak** — delivered (post-fader) master true-peak in `MixReport` (PR #195).
- **REC-4Z8Q** — recurrence matcher now matches zero-interval (repeated-pitch) motifs; **DOC-7K3M** closed in-code read-side doc gaps.

**Methodology / framework**
- **DEC-CAP** — decision capture wired into the iterate loop (`/compose-part` close + `/compose-review` / `/mix-review` backstops).
- repo hygiene — untracked an accidental worktree gitlink + gitignored `.claude/worktrees/`.

**Re-vendor: required** — 14 files under `_FINGERPRINT_PATHS` changed since v1.5.0 (`actions/`, `handlers/`, `schema.py`, `wire.py`). Marketplace consumers must re-run `/ableton-mcp-install` and fully quit + reopen Ableton Live.

## 2026-06-23 — Device loads survive Arranger focus; push rejects bad phase names before any Live probe (MCP-1V8K, PSH-PHASEORDER)

<!-- prawduct: type=fix | chunks=MCP-1V8K,PSH-PHASEORDER | scope=mcp-device,sync-push,tests | status=shipped | release=v1.6.0 -->

Two quick-win bugfixes triaged from the incoming-bug batch. (The other two fresh "ready"
items — BLD-RESET, RND-3W7P — were verified already-fixed in code and closed, not rebuilt.)

- **MCP-1V8K** — `ableton_device(load)` silently no-opped when Live's focused view was
  Arranger (the state every render leaves behind), bricking the push device phase,
  `/song-pick-instruments`, and any interactive re-voice with a misleading "did not append"
  error. `load_handler` now focuses Session before `browser.load_item` (the single affected
  callsite — the nested-rack `Chain.insert_device` path is unaffected), and the silent-noop
  teaching error now names the Arranger-view cause. Live-gated: `device.py` is in
  `_FINGERPRINT_PATHS`, so it needs a re-vendor + handshake — operator-verification queued.
- **PSH-PHASEORDER** — a typo'd `--only`/`--start-at`/`--stop-after` paid the full coherence
  + arrangement Live probe (and could be masked by a stale-link coherence refusal) before
  being rejected. Extracted a pure `validate_phase_targets()` from `_filter_phases`; the push
  CLI runs it before any Live round-trip, so a bad phase name fails fast (exit 2) with the
  valid-phase list and zero Live contact. `_filter_phases` delegates to the same function —
  one rule. 4419 tests green.

## 2026-06-23 — Device-phase no longer halts on orphaned device_parameters (SYN-2D9K)

<!-- prawduct: type=fix | chunks=SYN-2D9K | scope=sync-push,capture,tests | status=shipped | release=v1.6.0 -->

**Orphaned `device_parameters` from a device-class swap no longer HALT the push.**
Swapping a track's instrument to a different device *class* between captures (e.g.
`alien`'s Operator→Analog) left the prior class's params orphaned in the DB; `create_device`
reuses the `device_id` (no CASCADE), replay's upsert never prunes, and a soft `--reset`
preserves the device tables — so 92 orphans survived every rebuild and HALTed the devices
phase with a misleading value-range hint.

- **Ch1** — per-device param-SET reconcile in `_replay_devices`, mirroring the existing
  pull-path reconcile: drop DB params absent from the snapshot's `params_dialed` via
  `remove_device_parameter` (no new mutator, no schema change). Tri-state mirrors the
  sidechain idiom: absent key = preserve; present (even empty) = authoritative/clear.
- **Ch2** (defense-in-depth) — the device-phase orphan error is now taught engine-side at
  the `push_execute` failure-record site (pure `_orphan_param_hint`, no MCP fingerprint flip).
- **Safety** — verified no framework `build.py` path calls `set_device_parameter` (only
  capture/pull do), so `params_dialed` is authoritative and the reconcile is data-loss-safe;
  the cumulative Critic independently re-confirmed this. PR #204. 2991 engine tests green.

## 2026-06-23 — Arrangement-integrity comparator stops false-halting a faithful push (ARR-CMPHALT)

<!-- prawduct: type=fix | chunks=ARR-CMPHALT | scope=arrangement-verify,tests | status=shipped | release=v1.6.0 -->

**The ARR-PROJ integrity assert no longer HARD-HALTs `execute --only arrangement` on a
faithful materialization.** Two pure-module defects in `arrangement_compare.py`:

- **Ch1** — same-pitch overlap-trim was unmodeled. Live's `set_notes` truncates an earlier
  note when a same-pitch note starts before it ends; the comparator compared the DB's
  untrimmed durations against Live's trimmed read-back. `_clamp_same_pitch_overlaps`
  normalizes both note sets before grouping — only *shortens* durations, so a real
  drop/orphan is still caught.
- **Ch2** — `_bucket`'s `round()` was unstable at half-eps boundaries, splitting one onset
  across `missing` + `extra`. Replaced exact-bucket-key set ops with key pairing + boundary
  reconcile (composes with the wildness-stack collapse; a drifted twin reads as one
  mismatch, not missing+extra).
- **Safety** — the cumulative Critic adversarially proved the loosened detector still
  catches real bulk-drop / orphan / dur-vel-drift (the cardinal risk of loosening a
  detector). PR #203. 2985 engine tests green.

## 2026-06-22 — Arrangement materialization is now a projection of the DB (ARR-PROJ)

<!-- prawduct: type=feat | chunks=ARR-PROJ | scope=sync-push,arrangement-verify,cli,skills,docs,tests | status=shipped | release=v1.6.0 -->

**Two foundational bugs retired by construction, not patched.** Thirteen months of
arrangement whack-a-mole (stacking on re-materialize — ARR-9X4T; a silently-dropped
track's notes — ARR-7H2N; the SYN-4R7P delete-by-hand recovery dance) traced to two
design choices, not N bugs: `duplicate_to_arrangement`'s B-24 overlap-split, and a
persistent *positional* `ableton_link` that Live renumbers out from under us. The fix
reframes the arrangement as a **projection of the DB** — clear, then recreate — so both
failure modes become impossible by construction rather than guarded against.

- **Projection rebuild planner** (`sync/push/arrangement.py`): per track, clear its
  arrangement clips (descending per-clip `delete`) then create+fill each placement from
  the DB on a FRESH clip (`create_midi_clip` + `set_notes`), all-or-nothing per track
  (probe-failure skips rather than stacks). `duplicate_to_arrangement` is retained ONLY
  for envelope-bearing placements (the one Live constraint that needs it); audio uses the
  existing path. Re-materialize onto an occupied timeline clears-then-rebuilds — the
  ARR-9X4T stacking witness can no longer be produced.
- **Integrity comparator** (`sync/arrangement_compare.py` + `arrangement_verify.py`): one
  canonical DB-collapsed-set vs Live-arrangement-set comparator with three normalizations
  (distinct-(pitch, ε-bucketed start) collapse — Live collapses same-(pitch,start) while
  build.py legitimately stacks; float tolerance; note-content compare via the note API in
  a fresh callback, never inline). Two consumers: a **push-time assert** wired after the
  arrangement phase that HALTs (PARTIAL) on genuine corruption instead of reporting OK,
  and a **`hallucinote verify-arrangement --song <slug>`** audit CLI (non-zero exit on any
  divergence). Surfaces a `probe_failed` count as a benign warning so an all-probe-failed
  verify is no longer indistinguishable from a clean pass.
- **Reconcile subsystem removed** (`sync/push/probe.py`, net −392 lines): with rebuild as
  the sole path, the SYN-4R7P positional-link reconcile (drop/keep/rebind-by-position) had
  nothing left to protect — it only ever guarded the old `replace_notes`-refresh branch
  that Chunk 2 replaced. Deleted outright; the `arrangement_clip` link is still written
  fresh each push for the scoped PSH-6W2J refresh.
- **Docs/skill** (`skills/ableton-push/SKILL.md`): the delete-then-re-duplicate recovery
  dance is retired in favor of the idempotent clear+rebuild path; `verify-arrangement`
  surfaced; the two 2026-06-21 incoming-bug reports archived RESOLVED.

Five chunks (Chunk 6 bulk-clear-wire DROPPED — planner-deletes suffice, zero MCP
fingerprint change). Live spike (Chunk 1) confirmed the model end-to-end on a real set
(faithful, idempotent, drop-free). 4396 passed, 0 failed. Cumulative Critic clean (0
blocking; two integrity-layer correctness warnings — silent-pass-on-probe-failure and a
coincident-start false-halt — fixed at root). The full-path live e2e
(`push execute --only arrangement --probe --song alien` + `verify-arrangement` + render)
is queued in operator-verification.md (deferred, user-directed). Closes ARR-9X4T,
ARR-7H2N, SYN-4R7P.

## 2026-06-21 — perform_batch transport-stall watchdog + loop/punch reset (PSH-3H8M)

<!-- prawduct: type=fix | chunks=PSH-3H8M | scope=mcp-perform,tests | status=shipped | release=v1.6.0 -->

**Hang on a frozen transport, mitigated.** `perform_batch` could hang when the
transport won't advance (manual stop, a loop region trapping the playhead, residual
state from an interrupted prior perform). The span-proportional wall-clock ceiling
(already live) means it no longer hangs *forever*, but for a long (8–11 min) perform
that ceiling is ~16–33 min away — so a stalled transport still read as a black-box
hang whose only exit was `kill -9`. This closes the residual:

- **Fast non-advancement watchdog** (`_PERFORM_STALL_TIMEOUT_S = 15s`): the record
  loop polls `current_song_time`; if it doesn't advance for 15 s it aborts with a
  structured error naming the stuck beat, instead of waiting out the ceiling. Seeded
  at `-inf` so the spin-up tick can't false-trip, and any real advance resets the
  clock — a slow-but-advancing high-`slowdown_factor` pass never aborts.
- **Pre-perform loop/punch reset**: `_arm_and_seek` saves then clears
  `loop`/`punch_in`/`punch_out` (only flags actually set → no churn) and the `finally`
  restores them, so a residual loop region can't trap the playhead and the user's set
  isn't mutated.

5 new unit tests (fast abort + named beat, no-false-positive while advancing,
loop/punch clear-then-restore + ordering, clean-set no-churn, restore-on-abort). Live
stall repro + loop-trap queued in operator-verification.md. **Still-open residual:**
a `run_on_main`-blocked 0%-CPU sub-case needs a timeout on `run_on_main` itself (the
watchdog runs between callbacks, so it can't fire while blocked inside one) — high
blast radius, Live-only tunable; tracked on PSH-3H8M.

## 2026-06-21 — Render no longer leaves RETURN-track names dirty (RND-2R9K)

<!-- prawduct: type=fix | chunks=RND-2R9K | scope=mcp-render,tests | status=shipped | release=v1.6.0 -->

**Residual name hygiene, fixed.** `ableton_render`'s analyzer auto-load made Live
natively append ` | HallucinoteAnalyzer` to every RETURN track's name (a
`browser.load_item` side effect Live applies to returns but not tracks/master), so
a render left the user's set dirty. The functional half — the suffix defeating
probe-and-link's return matcher — was already fixed defensively by SYN-RENDER-RELINK
(`normalize_live_return_name` strips it at the read boundaries); this closes the
residual so a render leaves the set byte-for-byte. The analyzer sweep
(`hallucinote_mcp/analyzer/setup.py`) now restores each return's pre-load bare name
after the load — `_return_name_restoration` strips Live's slot prefix + the analyzer
suffix (the value a fresh push would set, per the W3-H/W4-C contract), runs read-only
when the name is clean (no churn; self-heals a pre-fix-dirtied set), and is scoped to
returns. The strip logic is a forced twin of `hallucinote.return_naming` (this package
is engine-independent / runs Live-side, so it can't import the engine — a parity
test locks the twin against drift). 8 new unit tests; full suite 4349 passed. Live
round-trip (real rename; single- vs double-prefix on restore) queued in
operator-verification.md.

## 2026-06-17 — Durable nested-param overrides on a preset_query device (SNP-2H9F)

<!-- prawduct: type=feat | chunks=SNP-2H9F | scope=capture,db-schema,db-mutations,db-queries,sync-push,docs,tests | status=shipped | release=v1.5.0 -->

**Silent durability loss, fixed.** A by-ear param tweak NESTED inside a rack loaded
via `preset_query` reverted on every from-scratch rebuild: a preset device has only
its top-level row in the DB (the preset instantiates the nested tree at push time),
so the nested delta had no durable home, and capture's full `chains` dump dropped
`preset_query` + the preset's un-parameterizable timbre (a Wavetable waveform is not
a `DeviceParameter`) and bloated the snapshot. There was no clean snapshot shape for
"load X from its portable preset, then override nested param P".

New `param_overrides` representation on a device entry, end-to-end (NODE-ADDR Chunk B
follow-on; folds into the same uniform-addressing release):

- **Schema** — `device_param_overrides` table keyed `(device_id, path_json, name)`,
  auto-migrating onto existing song DBs via `init_db`'s `CREATE TABLE IF NOT EXISTS`
  (mirrors `drum_pad_mappings`); `DEVICE_PARAM_OVERRIDES_REPLACED` event registered
  under the `device` row-kind so a pulled override protects the preset device from
  the build sweep.
- **Mutator + query** — `replace_device_param_overrides` (atomic, idempotent,
  validating) + `get_device_param_overrides`.
- **Replay** — `_replay_devices` lands overrides keeping `preset_query`; `chains` +
  `param_overrides` on one device is a `ValueError` (contradictory representations).
- **Push** — `_emit_param_override_writes` re-asserts each override via a
  node-addressed `set_parameter` at its NodeAddr path after the preset loads — no
  `create_device_chain`, so the preset's waveform/samples survive and nothing
  duplicates. Shared `_param_value_kv`/`_param_value_fields` helpers so an override
  dials identically to a top-level `params_dialed`.
- **Capture** — `preserve_preset_overrides` carries `preset_query` forward and
  rewrites the fresh `chains` dump into a flat `param_overrides` list; a
  drum-rack-via-preset with authored per-chain props keeps its `chains` dump + warns
  (a documented fast-follow).

Verifiable signal met: a preset device's depth-2 override round-trips
capture→replay→DB→push (fake-probe). 34 new tests; full suite 4037 passed.
Docs: `docs/snapshot-schema.md`. Plan: `NODE-ADDR/snp-2h9f-slice.md`.
**Deferred fast-follows** (tracked on SNP-2H9F): pull-symmetry (confirmed
non-corrupting), drum-rack-chain-props, bounded preset-cache if over-capture bloats.

## 2026-06-17 — Note edits now propagate to arrangement clips (PSH-6W2J)

<!-- prawduct: type=fix | chunks=PSH-6W2J | scope=sync-push,queries,tests | status=shipped | release=v1.5.0 -->

**Silent correctness bug.** An arrangement clip is a distinct Live copy of a
session clip, made once by `duplicate_to_arrangement`. A later note edit pushed to
the session clip never reached the copy — yet push reported success, the DB and
session clip were correct, and `/mix-review` ran clean against the *stale*
arrangement audio. The only way to notice was probing arrangement-clip note counts
directly. Root cause: `plan_push_arrangement` was idempotent on the **existence** of
the `arrangement_clip` link (skip-if-linked), never on note **content** — and
`push_notes` only ever touched the session clip.

Fix (report direction 1 — propagate, don't re-duplicate): an already-linked
placement now emits a `replace_notes(location='arrangement')` refresh instead of
being skipped. The MCP handler already accepted `location='arrangement'` with
`clip_index = arrangement_clip_index`, so the copy's notes are rewritten in place —
idempotent on the *placement* (no doubled clips), but notes stay in sync. Both push
paths are covered:

- **Full `execute`** — `sync/push/arrangement.py::plan_push_arrangement`: the
  already-linked branch emits a refresh; new-duplicate vs refresh are tracked
  separately so the "agent must clear existing arrangement clips" warn fires only
  for genuine new placements. A re-push of a built song refreshes every
  arrangement-copy's notes unconditionally — the **heal path** for any
  already-stale arrangement.
- **Scoped `push-notes`** — `sync/push_notes.py`: after the session clip push,
  appends `plan_push_arrangement_clip_notes(clip_id)` refresh calls for the clip's
  linked placements; rides the existing `changed_only` fingerprint (unchanged
  session clip ⇒ unchanged copy ⇒ no refresh).

New: `queries.get_arrangement_for_clip`; `push.plan_push_arrangement_clip_notes`;
ack-only key kind `arrangement_clip_notes` in `apply_push_results`. Unlinked
placements (not yet materialized) and audio sources (no notes; CLP-AUD2) are skipped;
when a linked placement can't be refreshed (unresolved track link / audio), the
idempotency note names the gap rather than claiming a clean refresh.

**Contract correction (tests-are-contracts note):** the prior
`test_plan_push_arrangement_skips_already_linked_placements` asserted
`plan.calls == []` for a re-push — that *encoded* the bug (W10-A's idempotent-skip
was too aggressive, suppressing propagation). Rewritten to assert exactly one
arrangement refresh (no `duplicate_to_arrangement`). Not a weakened test: a contract
found to be wrong, corrected to match the fixed behavior.

Resolves the report archived under
`backlog PSH-6W2J`.

## 2026-06-17 — Songs-workspace bootstrap (`hallucinote init-workspace`) + two doc-only decisions

<!-- prawduct: type=feat | chunks=WS-BOOTSTRAP | scope=cli,tools,skills,docs,backlog,artifacts,tests | status=shipped | release=v1.5.0 -->

Delivers the **author side** of the project-root contract. The reader
(`hallucinote.workspace`) already discovered a `hallucinote.toml` marker, but
nothing *wrote* one — so a song scaffolded outside a workspace silently scattered
into `./songs/<slug>` (a documented prerequisite with zero authoring tooling and a
silent-degrade failure mode).

- **`hallucinote init-workspace`** (`src/hallucinote/tools/init_workspace.py` +
  `cli.py` subcommand) writes the `hallucinote.toml` marker atomically
  (`os.replace`), seeds an **idempotent** `.gitignore` managed block (BEGIN/END
  sentinels — re-runs are no-ops), and `git init`s. Refuses to clobber an existing
  workspace without `--force`; `--check` reports detection without writing;
  `--no-gitignore` opts out of the managed block. `git init` failure degrades
  gracefully — the marker is the essential artifact. The written marker keys
  (`layout`/`songs_root`/`slug`) round-trip cleanly through the existing reader's
  `_workspace_from_marker`.
- **`/getting-started` + `/song-new`** now `--check` for a workspace and offer to
  create one instead of silently scattering a song into `./songs/<slug>`.
- Closes the **fresh-workspace half** of the filed gitignore bug
  (`backlog WS-BOOTSTRAP/WSP-3R7K`)
  at the natural moment (workspace creation): the managed block covers the
  regenerable-artifact set.

Two doc-only decisions ride along (no code):

- **MCP-7F2K** fingerprint over-trigger — approach decided (c→a) in
  `.prawduct/artifacts/mcp-fingerprint-design.md`; backlog moved research→ready.
  Root cause: server-side-only handlers (`handlers/analysis.py`,
  `runs_server_side=True`, never executes in Live) are hashed into the version
  fingerprint, prompting needless re-vendor.
- **AUD-8K2N** — split `docs/capability-truth.md` Mix into *authoring* (any edition)
  vs *measured review* (Max-for-Live only); the anti-hallucination spine had listed
  the M4L-gated review as "✓ full" for Standard users. Build declined by design.

24 unit tests for init-workspace (`tests/unit/tools/test_init_workspace.py`),
including CLI-level `--no-gitignore` coverage. Full suite green this session.

## 2026-06-16 — Analyzer-infra robustness: master device-param re-push + captures-dir recency (sun-zone-done mix pass)

<!-- prawduct: type=fix | chunks=master-device-analyzer-aware,captures-dir-recency | scope=mcp-handlers,sync-push,analysis,tests | status=shipped | release=v1.5.0 -->

**Re-vendor REQUIRED by the current fingerprint** — `handlers/analysis.py` is in
`_FINGERPRINT_PATHS`, so the version handshake flags drift and prompts
`/ableton-mcp-install`. But the analysis change is SERVER-INTERNAL (captures-dir
selection; the wire contract is unchanged), so this re-vendor is an over-trigger —
exactly the case MCP-7F2K now tracks. To pick up the fix in a running dev server:
relaunch dev-mode / `/mcp`, then re-vendor to clear the handshake. The master-side
fix lives in the engine (`src/hallucinote/`), outside the fingerprint.

Two framework bugs surfaced dogfooding the sun-zone-done mix pass:

- **Master device-param re-push wasn't analyzer-aware** (`sync/push`). Re-pushing a
  master device parameter (e.g. the master Limiter's Ceiling) targeted the
  auto-loaded HallucinoteAnalyzer and hard-halted the devices phase. The push probe
  re-binds track/return device links every push (filtering the analyzer before
  position-matching, BUG1A), but the master was excluded entirely and never even
  probed into `live_devices_by_parent` — so a master device link froze at first-load
  and mis-targeted once a render's analyzer load/reposition shifted the chain.
  DEV-6M2K newly made master device chains pushable; the probe's master-exclusion
  was a pre-DEV-6M2K assumption that was never updated. Fix:
  `_probe_live_devices_via_mcp` now probes the master chain (`master=True`, keyed
  `("master", 0)`) and `_match_devices_for_linked_parents` reconciles the master with
  the same analyzer-filtered position match — the link self-heals against analyzer
  drift. Side-benefit: the push-preflight stale-set detector now covers the master
  surface too (closes the "still-open piece" in `analyzer_staleness.py`).
- **Captures-dir picked by dir NAME, not capture time** (`handlers/analysis`).
  `_latest_captures_dir` used `max()` over dir names assuming ISO-8601 naming, so a
  hand-named focused-capture dir (`v4-…`, lexically above `2026…`) shadowed the
  newest render → analysis read the wrong (tiny, single-section) audio. Now keys on
  the manifest's recorded `captured_at`.

Full suite 3971 passed / 2 skipped @ HEAD. Cumulative Critic 0 blocking (base
develop); 1 warning (master stale-set label `master #0` → `master:`) resolved via
verify-resolutions chain. Resolved bug report archived under
bug report "Master device-parameter re-push isn't analyzer-aware — the stale master
device link targets the HallucinoteAnalyzer and hard-halts the push" (resolved
2026-06-16 on branch `fix/analyzer-infra-robustness-sunzone`).
Filed MCP-7F2K (fingerprint over-triggers re-vendor for server-internal changes).

## 2026-06-16 — Uniform node addressing (NODE-ADDR / DEV-9K7N) + release-prep: self-contained plugin, onboarding, M4L handling

<!-- prawduct: type=feat | chunks=NODE-ADDR-B,NODE-ADDR-C,NODE-ADDR-D,NODE-ADDR-E,NODE-ADDR-F,PLUGIN-SELF-CONTAINED,ONBOARD-M4L | scope=node-features,mcp-handlers,capture,sync-pull,db-mutations,skills,docs,readme,pyproject,cli,hooks,project-state | status=shipped | release=v1.5.0 -->

**Re-vendor REQUIRED** — the wire shape changed (`_FINGERPRINT_PATHS` touched): uniform
`node` addressing, the new `chain` terminal, and `set_chain_property`. Operator-verified
live on 2026-06-15 (user re-vendored; no-clone install path verified end to end).

Three threads land together as the pre-1.0 release-prep bundle:

- **NODE-ADDR (DEV-9K7N) — uniform node addressing.** One `NodeAddr` (terminals
  track|return|master|device|chain) reaches every node; operations stay honest via the
  tri-state node-feature matrix (`SUPPORTED` / `NOT_IMPLEMENTED` / `UNSUPPORTED_IN_LIVE`,
  published as `ableton://reference/node-feature-matrix`). Chunk B: read-side acquisition
  (capture execute + depth-N pull + `default_value` capture filter). Chunk C: per-DrumChain
  authorship (`choke_group` / `out_note` via the `chain` terminal). Chunk D: macro authorship
  honesty (value-via-params; macro-names/variations re-scoped). Chunk E: zones →
  `UNSUPPORTED_IN_LIVE`. Chunk F: per-chain mixer state (mute/solo/volume/pan).
- **PLUGIN-SELF-CONTAINED.** The engine ships INSIDE the plugin's uv env (uv workspace +
  `uv sync --all-packages`); no PyPI, no separate clone. New unified `hallucinote` console-CLI
  (`src/hallucinote/cli.py`) so skills sequence one command; skills run it via the server's
  own interpreter (`"$PY" -m hallucinote.cli`, $PY = `ableton://server/info`'s `python`) — the
  same env the bridge runs in, on a read-only plugin root. Bash hooks ported to Python
  (`uv run --no-project python`) for Windows. Decision recorded in project-state
  (supersedes INS-7V2D's PyPI-out assumption).
- **ONBOARD-M4L.** `/getting-started` orientation skill; render teaches when the Max-for-Live
  analyzer is absent (`AnalyzerNotInstalledError`); compose/push/pull/compose-review qualified
  as edition-agnostic vs. the Suite-only audio-analysis path; install ASKS the edition (D1 —
  edition isn't reliably detectable).

Plus a README rewrite (no-clone install, breadth examples), the three-leg authorship model
(`.prawduct/artifacts/authorship-model.md`), and doc coherence cleanup.

Full suite 3965 passed / 2 skipped @ HEAD. Cumulative Critic 0 blocking (base develop); 2
warnings + 2 notes resolved in HEAD + a real py3.10/3.11 f-string defect the green-on-3.12
suite had masked. Plans: `.prawduct/artifacts/plans/{NODE-ADDR,PLUGIN-SELF-CONTAINED,ONBOARD-M4L}/`.
**Follow-ups before develop→main/marketplace:** install-skill `python -m hallucinote_mcp.cli`
→ server-python migration; Windows-hook + read-only-root operator-verify; deferred
`[live]`/PyPI extra scrub.

## 2026-06-14 — Per-song attempt ledger (ATL-7K3M): `kind: attempt` + `/song-attempts`

<!-- prawduct: type=feat | chunks=ATL-7K3M-ch1,ATL-7K3M-ch2 | scope=db-schema,markdown-refs,song-context,skills,docs,claude-md | status=shipped | release=v1.5.0 -->

**No re-vendor** — no `_FINGERPRINT_PATHS` touched (no MCP handler reads `markdown_refs`).
A per-song ledger of *what was tried and how it turned out*, incl. reverted dead ends —
augments `decisions/` (kept rationale) + `annotations/` (intent) with the experiment trail
so a later pass doesn't re-try a known dead end. Pull-only, musical-craft only.

- **ch1 (code):** new `kind: attempt` on the `markdown_refs` corpus with `outcome`
  (worked|partial|failed) + `resolution` (kept|reverted|superseded); the
  try→outcome→correction chain rides the existing `related` links. `markdown_refs` joins the
  disposable-projection rebuild (the new kind CHECK is a domain change ALTER can't express;
  reindex rebuilds rows from disk → no authored data lost; schema canary stays green).
  `find_markdown_refs` gains an `outcome` filter; `song_context` gains `--kind attempt` +
  `--outcome`; `song-new` scaffolds `attempts/`. 16 new tests.
- **ch2 (doc):** new `/song-attempts` pull skill; a LOG-ATTEMPTS capture step in
  `/compose-review` + `/mix-review` (distinct from the intent learn-back); discoverability
  spine (`/song-workflow` + `docs/song-workflow.md`, `song-conventions.md` schema + worked
  example, `docs/song-authoring-conventions.md`, CLAUDE.md norm).

Full suite 3752 passed / 2 skipped. Cumulative Critic 0 blocking / 0 warning (5 notes, 2
acted on); verify-resolutions chain clean. Requirements:
`.prawduct/artifacts/song-attempt-ledger.md`; plan: `.prawduct/artifacts/plans/ATL-7K3M/build-plan.md`.

## 2026-06-14 — Song-workflow discoverability: `/song-workflow` spine + review-checkpoint wiring

<!-- prawduct: type=docs | chunks=song-workflow-spine,discoverability-wiring | scope=skills,docs,mcp-primer,claude-md | status=shipped | release=v0.9.8 -->

**No re-vendor** — the MCP `server.py` PRIMER string is outside `_FINGERPRINT_PATHS`
(effective on the next `/mcp` respawn). Fixes the problem that agents don't discover
`/compose-review` and `/mix-review` exist.

- **New `/song-workflow` skill** — a thin, always-in-context lifecycle map; its
  description names both review checkpoints so they surface even in a flat skill list.
  Plus `docs/song-workflow.md`, the depth doc: the full lifecycle, the five expertise
  layers, and links into the research corpus (link, never summarize).
- **Layer 0 wiring (always loaded):** the MCP PRIMER's flat 7-skill list — which
  omitted both review skills *and* `/ableton-push` — is now the lifecycle arc + a
  pointer to `/song-workflow`; CLAUDE.md's skill-chain names the full arc incl. both
  checkpoints.
- **Layer 2 wiring (in-flow handoffs):** `/compose-part` → `/compose-review` (the
  critical broken link — compose-part tells agents not to stop), `/song-pick-instruments`
  → compose, `/ableton-push` → `/mix-review`. Index back-references added in
  `docs/skills.md` (a "Start here" row) and the README "Learn more" table.

## 2026-06-14 — Critic-debt refactor batch: SYN-6T2W + ENV-5R2J (DEV-1F9X deferred)

<!-- prawduct: type=refactor | chunks=SYN-6T2W,ENV-5R2J | scope=sync-pull,db-mutations,sync-push,tests | status=shipped | release=v0.9.8 -->

**Re-vendor: not required** — engine-only (no `actions/`/`handlers/` touched). Behavior-preserving
dedup of two Critic-flagged duplications; full suite green (3736 passed, +1 drift-guard).

- **SYN-6T2W — shared linked-parent/device iterators for the `plan_pull_*` family.** The four
  `plan_pull_*` planners each re-walked linked tracks (master-skipped) + returns → top-level chain
  → devices. Extracted `_iter_linked_parents` and the layered `_iter_linked_top_level_devices`;
  per-planner warning text, rack filtering, and `any_emitted`/`any_top_level_device` bookkeeping
  stay in the callers via an `unlinked_warn` callback. Behavior preserved (225 pull tests unchanged).
- **ENV-5R2J — single host-kind vocabulary + planner drift-guard.** The host track-kind set
  `{midi,audio,master,group}` was hardcoded as a literal in `create_envelope`'s eligibility gate
  while the canonical `TRACK_KINDS` already existed; point the gate at `TRACK_KINDS` (same set) and
  add a completeness test pinning the planner's `_route_for_host_kind` to it — a new track kind with
  no route now fails the test, not silently routes to `unroutable` at push. Eligibility and routing
  stay separate policies; only the vocabulary is shared (no layering inversion — `sync→db` is the
  existing direction).
- **DEV-1F9X DEFERRED (not built).** The plugin-discriminator duplication is CROSS-PACKAGE
  (`hallucinote` ↔ `hallucinote_mcp`); a shared module would either pull the heavy engine into the
  MCP's stdlib-only-at-startup hot path or needs the W11-A `hallucinote-core` package that doesn't
  exist yet. A lock-test already pins the two copies, so there's no live drift. Kept on the backlog,
  gated on W11-A.

## 2026-06-14 — DEEP-RACK-ADDR (depth-N device addressing) + PULL-DRIFT-DETECT (usable drift detection)

<!-- prawduct: type=feature | chunks=DEEP-RACK-ADDR-1,DEEP-RACK-ADDR-2,DEEP-RACK-ADDR-3,DEEP-RACK-ADDR-4,PULL-DRIFT-DETECT | scope=mcp-actions,mcp-handlers,capture,sync-push,sync-pull,db-queries,skills,docs | status=shipped | release=v0.9.8 -->

**Re-vendor: REQUIRED** (DEEP-RACK-ADDR chunks 1 & 3 touch `actions/`+`handlers/`, flipping the
MCP fingerprint — re-run `/ableton-mcp-install` + restart Live). PULL-DRIFT-DETECT and the
capture/push/queries halves are engine-only (no flip, effective immediately). Live-side checks
(read/set/automate at depth, durability round-trip, the "Voices" parameter-vs-property probe) are
queued in `.prawduct/operator-verification.md` (DEEP-RACK-ADDR block).

- **DEEP-RACK-ADDR — rack devices nested 2+ levels deep are now fully addressable** (resolves the
  Severity-H bug: deep params were unreadable, unsettable, un-automatable, and — the killer —
  NON-DURABLE, since capture stored them and push silently dropped them, so a `build.py` rebuild
  reverted any deep fix). One canonical `device_path` (`[{chain_index, device_position}…]`, 1-based,
  any depth) replaces six reinvented depth ceilings.
  - **Chunk 1 (wire):** `_resolve_device_path` — the single positional descent every device surface
    speaks; `set_parameter`/`get_parameters`/`load` (with `chain_index`) gained optional
    `device_path`; `get_device_chains` recurses the whole tree reporting `is_rack` + `device_path`
    per device. `set_parameter_in_rack`/`load_in_rack` RETIRED (zero production callers; folded in).
  - **Chunk 2 (durability — the unblocker):** capture replay recurses to arbitrary depth (the
    `_depth>0` raise deleted); `Q.get_device_nesting_path` (pure-DB positional path); push emits
    `set_parameter` + `device_path` for nested dialed params (NOT loaded — they arrive with the rack
    preset). Pinned by a capture→DB→push depth-2 round-trip (the swell guitar case).
  - **Chunk 3 (automation):** nested `device_parameter` envelopes route to PERFORM (the gesture
    surface rides nested params via `device_path`; the session-clip route can't — Live 12.4
    `Clip.create_automation_envelope` is top-level only, an honest teaching skip).
  - **Chunk 4 (Voices, ask #4):** the "Voices IS a DeviceParameter" branch is covered by Chunks 1-2;
    the "is a LOM property" branch is probe-gated (operator-verification), not built speculatively.
- **PULL-DRIFT-DETECT — `pull device-parameters` is a usable drift detector again** (resolved the
  Severity-M bug: on an in-sync song the dry-run reported ~2530 false "mutations" — and a real apply
  WROTE 2452 preset defaults into the DB — while a version-skewed probe silently reported 0).
  - **Scope to the tracked set:** the apply diffs only DB-tracked (dialed) params; Live-only params
    are preset defaults the pull can't distinguish from dials, so they're SKIPPED, not added
    (capturing new dialed params is `/song-snapshot`'s full-recapture job).
  - **Round-trip-aware comparison:** compare by the param's authoritative form (normalized within
    `_FLOAT_EPS` for continuous, display string for display-only) — kills the false "updated" on
    unchanged values.
  - **Fail loud on unreadable probes:** `ApplyResult.unreadable` counts failed/empty probes;
    `pull_cli execute`/`apply` exit non-zero when >0; `/snapshot-bake-recent-changes` +
    `/ableton-pull` check it first so "couldn't read" never reads as "in sync".

## 2026-06-14 — swell-dogfood incoming-bug cluster (params authoring, analyzer-aware push, render/analyze poll)

<!-- prawduct: type=feature | chunks=BUG4-params-dialed,BUG1A-analyzer-match,BUG3-timeout-doc,BUG1B-strip,BUG3-status-json | scope=capture,sync-push,snapshot,render,analysis,skills | status=shipped | release=v0.9.8 -->

**Re-vendor: REQUIRED** (the `strip` action + status.json heartbeat touch `handlers/`/`actions/`,
flipping the MCP fingerprint — re-run `/ableton-mcp-install` + restart Live). Bugs 4/1A/3-doc are
no-flip and effective immediately. Four bugs from the 2026-06-14 swell mix dogfood; Bug 2
(install `--plugins-dir`) was already fixed by INS-3W8P (v0.9.7) → no code.

- **BUG4 — static device-param authoring (`params_dialed`).** Documented `params_dialed` as the
  home for static device params in `docs/snapshot-schema.md` — sparse, the per-entry shape, and the
  display-value workflow: a continuous param authored as a display string (`{"value":"180 Hz"}`)
  already flows through to the live setter's curve inversion (DPP-7H2K), so authors never hand-invert
  a log knob. `replay_capture` now warns on the bare-numeric-no-`normalized` trap.
- **BUG1A — analyzer-aware push device-matching.** `probe_and_link` excludes the trailing
  HallucinoteAnalyzer before position-matching, so a newly authored device at the analyzer's slot no
  longer false-drifts + skips its link (which forced manual analyzer deletion before a re-push). Engine-only.
- **BUG1B — bulk `ableton_render(action='strip')`.** The inverse of `ensure_loaded`: removes the
  analyzer from every track/return/master in one call (idempotent), for a clean deterministic push /
  save instead of ~29 hand-deletes.
- **BUG3 — render/analyze 60 s false-failure.** `render` + `analyze` handlers write a `status.json`
  heartbeat (`{state: running|done|error}`) so a poller sees a robust completion signal; mix-review
  documents the expected 60 s wrapper timeout + the poll. Interim toward MCP-4T6Y (full async render),
  which stays open.

## 2026-06-14 — master device snapshot authorship + relative reverb verdict band

<!-- prawduct: type=feature | chunks=SNP-4K7M,AUD-3T6L | scope=sync,snapshot,audio | status=shipped | release=v0.9.8 -->

- **SNP-4K7M — master-track device snapshot authorship.** The push side shipped
  (DEV-6M2K loads master devices) but the capture/replay middle was missing, so a
  song author couldn't declare or round-trip a master Limiter — "sound design is
  authorship" was violated at the master. `replay_capture` now materializes a master
  device chain (`create_device_chain(parent_track_id=master_id)` — the mutator is
  kind-agnostic), and `compile_snapshot` / `migrate_snapshot` /
  `snapshot_needs_migration` / `capture_plan` all join the master to the SNP-8R4K
  analyzer strip (the code TODO that read "joins when SNP-4K7M lands"). `song.master`
  carries an optional `devices` array; documented in `docs/snapshot-schema.md`. Master
  AUTOMATION envelopes remain a separate open surface (MAW-4K7P).
- **AUD-3T6L — relative reverb RT60 verdict band.** Live's Reverb RT60 is a nonlinear
  function of Decay Time + Room Size + diffusion, so the realized RT60 legitimately
  diverges from the nominal knob by an amount that scales with magnitude. The fixed
  ±0.15 s absolute band false-positived on clean long-decay captures (sun-zone A-Plate
  3.37 vs 3.0). New `reverb_tolerance_s(declared) = max(floor 0.15 s, 0.20 × declared)`;
  `REVERB_TOLERANCE_S` → `REVERB_TOLERANCE_FLOOR_S` (still the measurement-accuracy
  bound). mix-review frames an out-of-band reverb as a producer's note (% longer/shorter
  than intent), not a pass/fail verdict.

## 2026-06-13 — device sidechain SOURCE pull-capture (round-trip completion) + extract coverage

<!-- prawduct: type=feature | chunks=SDC-7K3M-pull,DEV-4X2N | scope=sync-pull,analysis | status=shipped | release=v0.9.7 -->

Completes the device-sidechain round-trip whose PUSH half shipped in v0.9.6: a
sidechain SOURCE is now captured FROM a live set back into the DB, so a manual
re-route in Ableton survives the next push instead of being silently dropped.

- **SDC-7K3M pull-capture (author).** New `device-sidechain` pull domain
  (`plan_pull_device_sidechain`) + `_apply_device_sidechain_source`, resolving
  Live `get_input_routing` `current_type` → a song-track FK by name match →
  `set_device_sidechain`. Conservative V1 policy: distinct-track captured;
  self / none / ambiguous / non-track-input no-op; idempotent; link-gated. The
  no-auto-clear limitation is documented (a removed sidechain isn't pulled). 13
  dedicated tests. Engine-only — the MCP getter already existed, so no wire-shape
  fingerprint flip / re-vendor. Live round-trip verification is operator-gated.
- **DEV-4X2N coverage.** Regression test pinning the extract's documented
  top-level-only chain exclusion (seeds a nested rack, asserts the inner device
  is excluded) — bidirectional with the push-side guarantee.

## 2026-06-13 — song round-trip reliability (push ordering, clip-link cascade, unit-aware params)

<!-- prawduct: type=bugfix | chunks=RTE-2P9X,SYN-3C8K,DPP-7H2K,SKL-8N3V | scope=sync-push,db,mcp-bridge,skills | status=shipped | release=v0.9.7 -->

Round-trip reliability fixes traced to swell-dogfood findings.

- **RTE-2P9X.** Push `routing` phase now runs AFTER `devices`, so an
  instrument-bearing track's bus routing resolves on a fresh (from-empty) push
  instead of targeting a track Live hasn't built yet.
- **SYN-3C8K.** Cascade stale clip-link drops + classify scaffold on reuse, so a
  set-swap re-push no longer carries dead clip links into the rebuilt set.
- **DPP-7H2K.** Unit-aware `value_display` + `value_real` echo + bare-name
  parameter routing docs; calibrated live against real EQ Eight + Compressor
  curves (the value-display inversion validated against actual Live formatting).
- **SKL-8N3V.** `/song-new` postlude pins `ensure_loaded` with no params (locks
  the documented call shape).

## 2026-06-12 — PSH-2R7K / PSH-5T9D: push `execute` phase-targeting + mid-run progress

<!-- prawduct: type=feature | chunks=PSH-2R7K,PSH-5T9D | scope=sync-push,cli | status=shipped | release=v0.9.7 -->

Two swell-dogfood findings, engine-only (no MCP fingerprint change).

- **PSH-2R7K — `execute` is no longer all-or-nothing.** New `--only` / `--start-at`
  (`--from`) / `--stop-after` / `--resume` slice the phase sequence, so recovering from
  a halt is one command instead of a full replay (including the ~8–11 min realtime
  perform). Filtering is by phase NAME (order-agnostic, composes with a future phase
  reorder) and validated against the canonical list before the audit row is created (a
  typo teaches the valid phases, no dangling row). `--resume` reads
  `.last-push-state.json`'s `phase_halted`; a `scope` field marks scoped runs so they're
  never mistaken for a full push.
- **PSH-5T9D — mid-run progress.** `.last-push-state.json` is flushed after every phase
  (pollable mid-run, adds `current_phase`), and per-phase start/finish lines stream to
  stderr (stdout stays the final summary), with a heads-up for the multi-minute perform
  phase so it isn't mistaken for a hang.

## 2026-06-13 — INS-3W8P: install/preflight resolve the running server, not the invoking interpreter

<!-- prawduct: type=bugfix | chunks=INS-3W8P | scope=plugin-distribution,mcp-bridge | status=shipped | release=v0.9.7 -->

The install resolved `hallucinote_mcp` via the invoking interpreter (`package_root` from
`__file__`), so in a coexistence setup (installed plugin + editable clone, incl. the
README's `pip install -e`) it vendored the WRONG source and preflight computed
`matches_mcp_server` against the wrong copy — reporting a match while the real server
refused (cost multiple Live-restart cycles 2026-06-13).

- New `ableton://server/info` resource (static, Live-independent) →
  `{version, base_version, fingerprint, package_root}`. `resources/` is outside
  `_FINGERPRINT_PATHS`, so the handshake fingerprint is unchanged.
- `preflight --server-version` relabels `package` as the invoking interpreter and adds a
  `server` block + `coexistence_divergence`; the install skill reads `server/info` and
  `install-remote-script --from-package-root --require-server-version` vendors the
  SERVER's copy (or refuses a wrong source). A transitional run against an old
  (pre-`server/info`) server falls back correctly.

## 2026-06-13 — SNP-8R4K: the analyzer is measurement infrastructure, excluded at every model boundary

<!-- prawduct: type=feature | chunks=SNP-8R4K-01,SNP-8R4K-02,SNP-8R4K-03,SNP-8R4K-04 | scope=capture,sync-push,sync-pull,render | status=shipped | release=v0.9.7 -->

Ends the capture-pollution → push-as-own-device → duplicate-accumulation cycle and the
off-by-one authored-position drift the HallucinoteAnalyzer caused when treated as
authored content.

- **Chunk 1 — exclude by identity.** `analyzer_identity.py` (`ANALYZER_DEVICE_NAME` +
  `is_analyzer_device`, drift-guarded against the MCP constant) consumed at every
  Live↔model boundary: capture drops the analyzer + dense-renumbers survivors; pull's
  chain-diff and push's device-emit filter it too. Auto-migrates the model.
- **Chunk 2 — clean-at-rest.** `SNAPSHOT_SCHEMA_VERSION` + a pure `migrate_snapshot` + a
  `capture_cli migrate` subcommand clean the committed `captured_session.json` file
  (strip + densify + stamp); replay warns (read-only) when a snapshot needs it.
- **Chunk 3 — render re-asserts the terminal tap.** The analyzer is repositioned
  strictly-last at render start (delete + re-add only when not already last — no needless
  M4L reload), with per-surface `terminal` status + an `analyzer_not_terminal` roll-up in
  the render manifest so a reading agent never trusts an under-tapped stem.
- **Chunk 4 — push-preflight stale-set detection.** A pure detector flags a saved set
  whose authored devices were loaded after the analyzer (non-terminal tap), with
  non-fatal rebuild guidance.

Live firing of chunks 3–4 is deferred to operator-verification.

## 2026-06-13 — v0.9.6: device sidechain round-trip + playback-param model + perform hardening

<!-- prawduct: type=feature | chunks=SDC-7K3M,SMP-7K2D-01,SMP-7K2D-02,AUD-2N6K,ENV-8K2R,ENV-2T9K,MEL-1A7K-line | scope=db,sync-push,audio-analysis,mcp-bridge | status=shipped | release=v0.9.6 -->

A consolidation release. The headline is **device sidechain SOURCE now survives the
DB round-trip** — previously sidechains only lived in the saved `.als` and were
silently dropped on any device-chain rebuild.

- **SDC-7K3M — device sidechain source round-trip (author + push).**
  `devices.sidechain_source_track_id` (semantic FK, survives renames) +
  `sidechain_source_channel`; `set_device_sidechain()` mutator; a new push phase
  `device_sidechain` (after `devices`) that resolves the source FK to the Live
  display_name and emits `ableton_device(set_input_routing)`. Symmetric with
  RTE-1K9T track routing; registered as a non-build actor touch so a captured
  source isn't tombstoned on rebuild. Pull-capture half + Live round-trip
  verification are the open remainder (tracked on SDC-7K3M).
- **SMP-7K2D chunks 1-2 — sample-instrument + reverse playback-param model.**
  `devices.audio_file` (a sampler's assigned sample as DB source-of-truth) +
  `clips.reverse` (the missing CLP-AUD1 playback-param sibling), on the principle
  that reverse/window/gain/pitch are declared playback parameters on one immutable
  asset, never an author-declared derived file. Push materialization (chunks 3-4)
  is Live-gated and pending.
- **AUD-2N6K — MixReport schema gaps closed.** Masking / bed_masking entries carry
  resolved `masker_surface_name` / `maskee_surface_name` beside the raw ids;
  `per_section` carries the DB `section_id`. Additive — no `schema_version` bump.
- **ENV-8K2R + ENV-2T9K — perform-handler hardening + tempo-reduction fidelity.**
  Settle-verified async disarms, gesture-endpoint pinning, planner/apply/client
  robustness, and perform fidelity via tempo-reduction-during-record.
- **MEL-1A7K — faithful top-voice line extraction + single-source reduction.**

The push pipeline grows from thirteen to **fourteen phases** (adds
`device_sidechain` after `devices`).

## 2026-06-12 — RTE-1K9T: track routing + the PRE-MAIN submaster bus

<!-- prawduct: type=feature | chunks=RTE-1K9T-01,RTE-1K9T-02,RTE-1K9T-03,RTE-1K9T-04,RTE-1K9T-05,RTE-1K9T-06 | scope=mcp-bridge,db,sync-push,sync-pull,docs | status=shipped | release=v0.9.5 -->

First-class track signal routing end-to-end (MCP → DB → push → pull) and the
convention it unlocks: a plain audio **PRE-MAIN** bus you route everything
through for master-like automation and sub-mixing — the no-`.als` path to an
automatable "master" that Live's clip-less master/group/return strips can't
provide. The push pipeline grows from twelve to thirteen phases.

- **MCP** (chunks 01–02): `ableton_track` gains `set/get_output_routing`,
  `set/get_input_routing`, `set/get_monitoring_state` on a shared
  capability-probing helper (`handlers/_routing.py`) — by-`display_name`,
  source-dependent, teaching errors that list the real targets, set handlers
  echo the requested name (same-callback readback is unreliable).
- **DB** (chunk 03): routing on `tracks` as seven nullable columns written
  through `set_track_routing` (one `TRACK_ROUTING_SET` event). The target is a
  **semantic reference** (`kind` + FK to `tracks.id`), never Live's display_name,
  so a submaster link survives renames + re-pushes. CHECK asymmetry (D6): output
  + monitor schema-constrained; the open input domain is mutator-validated.
- **Push** (chunk 04): a `routing` phase after `mix`, before `devices`; dangling
  targets alert + skip, never silently drop. No fingerprint gating (D7).
- **Pull** (chunk 05): a manual reroute ingests back through the mutator;
  `DB-NULL ≡ Live-default` avoids churning every default into explicit state (D8).
- **Convention + docs** (chunk 06): the PRE-MAIN bus documented for song authors
  (`song-authoring-conventions.md`) and for agents driving Live
  (`ableton://guides/conventions`); a doc-drift-locked worked example.

Per-chunk Critic across the build, a whole-plan `final` review (2 real
silent-drop bugs caught + fixed — tombstone-protection registration for the new
event kind, master-subject routing reject), and a cumulative + verify-resolutions
chain (3 warnings resolved: a pull silent-override of a manual input revert, a
self/master target validation gap, a stale plan comment). Group-track support
(TRK-2H6K) stays deferred — group *creation* is LOM-blocked. One operator
Live-smoke is enqueued (`operator-verification.md`): push materialization +
manual-reroute round-trip in a real set, plus a probe of Live's non-track input
default (V1 pull persists only track→track input until that's pinned).

## 2026-06-12 — DEV-6M2K: re-enable master device load across the stack

<!-- prawduct: type=bugfix | chunks=DEV-6M2K | scope=mcp-bridge,sync-push | status=shipped | release=v0.9.5 -->

Un-gates master-strip device loading. DEV-2M9K shipped the verdict "Live 12.4
has no LOM path to load a device onto the master" (`song.view.selected_track =
master` silently no-ops) and gated three surfaces; that premise is **refuted on
Live 12.4.2** — the master selection *sticks*, so `select master →
browser.load_item → delete_device` works end-to-end (live-proven; research spike
in `.prawduct/artifacts/research-spike-automation-ingest.md`).

The fix is pure subtraction — master now flows through the same generic path as
track/return:
- `handlers/device.py`: drop `load_handler`'s master refusal (the existing
  silent-noop post-condition catches a hypothetical mis-load).
- `analyzer/setup.py`: drop the master detect-only `RuntimeError` — the master
  analyzer auto-loads like any surface.
- `sync/push/devices.py`: drop the SYN-2M9P configure-only skip — an unlinked
  master device emits `device.load(master=True)`, links via the `device:<id>`
  key, and the SYN-9F2L convergence re-plan writes its params. No more
  PARTIAL-by-master halt.
- `server.py`: the `ableton_render` tool description no longer says master is
  place-by-hand.

Tests are corrected, not weakened — the test *double* (`FakeSongView`) encoded
the refuted premise and now models Live 12.4.2; the `test_syn_2m9p_master_load.py`
→ `test_dev_6m2k_master_load.py` rewrite adds multi-hop execute-path coverage.
Live corroboration of the integrated paths (native non-M4L device, full
master-chain push, fresh-set render auto-load) is enqueued in
`.prawduct/operator-verification.md`; DEV-6M2K stays open until that lands, and
the DEV-2M9K / SYN-2M9P / TPL-2D8K re-triage finalizes then.

## 2026-06-12 — ENV-9P4T: performed automation at mix scale

<!-- prawduct: type=feature | chunks=ENV-9P4T-01,ENV-9P4T-02 | scope=mcp-bridge,sync-push,db | status=shipped | release=v0.9.5 -->

Extends ENV-7G4K's performed automation toward real mixes: write automation at
greater **performance** (one transport pass for all arcs) and broader **reach**
(any track, not just master/group/return). Harvesting hand-edited arrangement
automation is explicitly deferred. **Chunk 01 — single-pass batched recording:**
the single-arc `perform` action becomes `perform_batch` (no back-compat) — all
changed perform-routed arcs record in ONE transport pass over the union span with
**per-parameter gesture windowing** (`_PreparedArc` pending→open→closed; each
arc's `begin_gesture`/`end_gesture` opens at its span entry and closes at its
exit, so a short arc never stamps a flat value across the song). The planner emits
one batched call (union-span cost estimate + an operator `alert()` enumerating
every overwritten span + a duplicate-target preflight); `apply_push_results` gates
each arc independently on its own `automation_state`; the wire read-timeout is
unbounded for `perform_batch` at the shared `client.send` chokepoint (the single
source both recv routes use). **Chunk 02 — plain/audio-track perform targets:**
`classify_envelope_route` gains infer-from-span — a track-hosted mixer/device
envelope COVERED by a single session clip routes per-clip (session_clip for midi,
refused/CLP-AUD2 for audio), UNCOVERED (incl. the song-spanning send across tacet
gaps) routes perform; the `create_envelope` mutator admits audio hosts; perform
addressing was already kind-agnostic (no change). The superseded v1.1
"partition-by-hand" teaching is removed (this is that capability). **Chunk 03 —
fidelity: conscious descope.** The verify-api probe proved the framed adaptive-
tick-density approach unrealizable: the realtime loop is scheduling-bound at
~2.5 Hz (not sleep-bound — adaptive ticking can't help), a 0.5-beat dip authored
to 0.1 records to 0.589, and the perform target's `DeviceParameter` exposes only
`begin/end_gesture` (no direct-write surface — live-confirmed). The achievable
lever (tempo-reduction-during-record) is spun out as **ENV-2T9K**; perform-handler
hardening carryovers as **ENV-8K2R**. **Live-verified this session** (no `.als`
needed — seek-and-read suffices): chunk 01 windowing (return reads manual 0.85
before its span, live ramp 0.499 at mid-span; `updates_written` bounds the
gesture); chunk 02 plain-MIDI vol+pan + audio-track vol all `automation_state==1`
in one pass with faithful mid-span reads. Cumulative Critic (develop base) caught
three stale audio-refusal authoring docs (BLOCKING — fixed to the shipped
behavior) and a chunk-02 verify-api gap (probe then run + recorded); a
`verify-resolutions` chain record extends the cumulative to HEAD (CRT-4J8W).
Suite 3061 passed / 311 skipped. (Change-log entry added directly to develop
post-merge — the feature-branch commit carrying it was not pushed before the
squash; REL-6C3W-class gap, repaired here.)

## 2026-06-11 — CLR-A: compose-loop reliability (swell friction wave A)

<!-- prawduct: type=bugfix | chunks=CLR-A-01,CLR-A-02,CLR-A-03,CLR-A-04,CLR-A-05 | scope=compose-loop-reliability | status=shipped | release=v0.9.5 -->

Triaged from the 2026-06-10 swell first-compose friction log: one silent
correctness bug plus reliability/teaching holes that tax every song's
bootstrap-and-compose loop. **SYN-9F2L (01):** a snapshot-authored device
parameter (`params_dialed`) loaded at push but its dial never landed and the
next push fingerprint-skipped the devices phase — a permanent silent drop. Root
cause: `set_parameter` calls were planned only for already-linked devices, so a
device loaded in the same execute pass got its link after parameter planning and
was never dialed. Fixed via the same-pass devices convergence re-plan (the
parameter writes now emit for newly-loaded devices too); the wire write prefers
the display `value` string over the center-zero-ambiguous `normalized`; and a
no-writable-form params_dialed write now surfaces on a new severity-scoped
`PushPlan.alert()` channel (operator-actionable, drained into the benign
`warnings` channel) instead of `plan.notes`, which `push_execute` never drained.
**SYN-6B4Q (02):** first push of a freshly-scaffolded song no longer halts
false-PARTIAL at `cues` past the (empty) arrangement extent — handler
`cue_create_batch` gains `on_out_of_range='refuse'|'skip'`, the planner
partitions cues against the composed extent (past-composed-with-arrangement →
hard `PushPlan.errors` channel halting the phase; skeleton → defer+warn), and
deferred cues surface via the benign `ExecuteResult.warnings` channel (exit 0).
**INV-3K8W (03):** `preset_query` strict-mode errors now teach the actual fix —
a `/`-containing pattern points at `path_prefix`; a `path_prefix` repeating
`root` says to drop the leading segment (0-match / not-found branches only, zero
behavioral change for valid queries; `inventory.find` inherits both). **SYN-5C3J
+ MCP-4T6Y (04):** an engine↔Remote-Script version-mismatch refusal now prints
the exact worktree+PYTHONPATH pin recovery (+ error-recovery guide section)
instead of the misleading generic "fix build.py" footer; the MCP server's
read-timeout becomes a `(tool,action)`-keyed policy — `ensure_loaded` gets a
bounded 180s (was timing out at the 15s default on a 25-surface set), render
stays unbounded, everything else the 15s default. **DEV-5R8Q + INS-2Q7F +
SKL-8N3V (05):** documented the delete-descending/reload-in-order chain-rebuild
pattern in `conventions.md` and DECIDED against a `rebuild_chain` convenience (it
is not a pure-planner emission — it needs Remote-Script orchestration to sequence
delete+reload); `/song-new` postlude now calls `ensure_loaded` with no params;
INS-2Q7F recorded obsolete-on-arrival (the install-hardening refactor already
replaced the hand-authored rsync with a Python `copytree`+`fnmatch` exclude).
Cumulative Critic (develop base) caught SYN-9F2L's warning still discarded on the
execute path — resolved by the `alert()` channel above and verified end-to-end;
a `verify-resolutions` chain record extends the cumulative to HEAD (CRT-4J8W).
Suite 3340 passed / 2 skipped.

## 2026-06-11 — ENV-7G4K: performed automation (master/group/return)

<!-- prawduct: type=feature | chunks=ENV-7G4K-01,ENV-7G4K-02,ENV-7G4K-03,ENV-7G4K-04 | scope=mcp-bridge,db,sync-push | status=shipped | release=v0.9.5 -->

AUD-1M4V stage 0b: the automation surface session clips can't reach —
master/group mixer (volume, pan), group sends, return mixer, master- and
return-chain device parameters — becomes authorable via gesture-recorded
**performed automation**. **Bridge:** `ableton_automation(action='perform')`
plays the transport through the arc's span in record while stepping the
parameter (runs_on_worker, `live_state_lock`, settle-poll on `record_mode`,
per-step `finally` restore incl. `re_enable_automation`, beat-space interp
with linear/hold/fast/slow). Probe-verified end-to-end first (probes 4/4b/
10/12/13: group-host recording + same-span re-record overwrite both
CONFIRMED). **Engine:** `return_mixer_volume`/`return_mixer_pan` kinds +
`performed_automation` state table; W10-F's dual-layer master/group refusal
replaced by routing eligibility — `classify_envelope_route` is the single
partition source (clip_scoped / session_clip / perform / refused_audio /
unroutable); audio hosts keep their ENV-8H1T refusal; the false "route to a
sub-bus" master teaching deleted. **Push:** twelfth phase
`performed_automation` (after envelopes) — fingerprint-gated (unchanged arcs
skip + are listed), per-arc tempo-map-aware wall-clock estimates in the plan
(Visible Costs), apply records state + `AUTOMATION_PERFORMED` event gated on
`automation_state == 1` (unverified writes retry next push). **Evidence:**
S-7 wire smoke PASS on real Live 12.4.1 — 5 arc families, skip-all re-push,
targeted re-perform; `.als` dump verdict: all 5 arcs faithful (~3 Hz step
rate). Docs/gaps guide updated from "can't" to "performed via push". Scope
notes: return→return sends not in wave-1 vocab; nested-rack device params
unreachable on either route; pull/read of arrangement automation has no LOM
surface.

## 2026-06-10 — CLP-AUD1: audio-clip DB model (wave 1)

<!-- prawduct: type=feature | chunks=CLP-AUD1-01,CLP-AUD1-02 | scope=clip-audio | status=shipped | release=v0.9.5 -->

AUD-1M4V stage 0a: clips gain a `kind` discriminator (`'midi'` default |
`'audio'`) plus the user-locked wave-1 audio field set — `audio_file`
(song-relative POSIX or absolute, stored as-given), `audio_gain` (0–1 linear),
`pitch_coarse`/`pitch_fine`, `warping`, `warp_mode` (Live enum ints, named via
`WARP_MODES`), `start_marker`/`end_marker` (beats when warped, seconds when
not) — via canonical `schema.sql` definitions + `_ADDED_COLUMNS` migration.
New event-emitting `create_audio_clip` mutator (audio-host-track guard,
audio_file required, idempotent rebuild). **Kind-guards at every
MIDI-assuming surface:** `kind` immutable everywhere (MIDI<->audio is
delete+create — `create_clip`/`create_audio_clip` both refuse a foreign-kind
slot; `update_clip` refuses `kind`); `update_clip` whitelist gains the audio
fields, refused on MIDI rows (and `audio_file` can't be cleared);
`insert_notes`/`replace_clip_notes` refuse audio targets (notes live on MIDI
clips); push planner refuses `kind='audio'` loudly — warn naming CLP-AUD2, no
MIDI create emitted — with a matching kind-aware warn in the arrangement
planner; pull exempts audio-clip rows (session-slot diff, arrangement-
placement removal, note probes) so authored-but-unsynced state can't be
clobbered. New pure `hallucinote.paths.resolve_audio_path(song_dir, ref)`
(top-level home keeps it importable without the numpy-bound
`hallucinote.audio` package). Docs: `docs/terminology.md` clips section gains
the kind/audio-field semantics. Push/pull of audio clips is CLP-AUD2; envelope
hosting ENV-8H1T; take lanes AUD-9R3V; warp markers deferred (lock 3).

## 2026-06-10 — AUD-1M4V discovery: `ableton_probe` tool + audio-as-first-class requirements

<!-- prawduct: type=feature | chunks=AUD-1M4V-discovery | scope=mcp-bridge,discovery | status=shipped | release=v0.9.4 -->

The AUD-1M4V umbrella's discovery cycle. **Code:** a permanent 13th bridge tool,
`ableton_probe` — constrained LOM introspection (`describe`/`get`/`set`/`call` with
`then` chaining and `{"$path": …}` LOM-object args) over a regex path grammar (no
eval); makes capability probing a wire call instead of throwaway Remote Script code
plus a Live restart per iteration. Adds the `any` ParamType for polymorphic params.
55 new unit tests incl. wire-path regression coverage. **Evidence:** the full LOM
probe suite executed against real Live 12.4.1 (`docs/research/audio-first-class/
lom-probe-results.md` + raw JSONL): audio clip creation native since 12.2 (browser
workaround obsolete), mixer envelopes on audio session clips confirmed end-to-end,
scripted master/return automation via `record_mode` + `begin/end_gesture` ramps
playback-verified, recording via `fire(record_length)` confirmed incl. take lanes +
comping substitute. **Research corpus:** adversarially verified producer practice,
primary-source mastering norms, two LOM research passes (same dir). **Artifact:**
`.prawduct/artifacts/plans/AUD-1M4V/discovery.md` — producer-led requirements
(R1–R5) traced to mechanisms + staged plan. **Backlog:** AUD-1M4V → design;
CLP-AUD2 redefined; ENV-8H1T reduced; ENV-4M2T partially superseded; new ENV-7G4K
(performed automation, stage 0b parallel) + AUD-9R3V (recording workflow).

## 2026-06-10 — DOC-5W8B: REQUIREMENTS.md auto-regen after device-changing push

<!-- prawduct: chunks=FRICTION-03 | status=shipped | release=v0.9.5 | scope=friction-basket -->

`push_cli execute --song <slug>` now regenerates `songs/<slug>/REQUIREMENTS.md`
whenever the devices phase applied at least one call — including pushes that
halted at a later phase (the doc tracks current set state, not push success).
`compat.regen_requirements(song_slug)` is the extracted callable seam; the
`write-requirements` CLI command is a thin wrapper. `--db`-only pushes print a
stale-notice with the manual command instead of guessing the song dir; regen
failures degrade to a stderr notice (waivered broad catch) so the push's exit
code is never masked. `docs/collaboration.md` handoff checklist updated.

## 2026-06-10 — WFL-7Q2N: session-ID auto-discovery in push/pull CLIs

<!-- prawduct: chunks=FRICTION-02 | status=shipped | release=v0.9.5 | scope=friction-basket -->

`session_id` may now be omitted on every session-taking `push_cli` /
`pull_cli` subcommand. `sync/session_resolve.resolve_session_id` resolves
it from the DB the command already opened: explicit id wins; one session →
used; several → most recent, echoed on stderr with alternatives; apply
commands treat a plan file's embedded `session_id` as authoritative (and
refuse a conflicting explicit id); multi-song DBs refuse to guess; zero
sessions → bootstrap guidance. New `db.queries.list_ableton_sessions`
(newest-first). Render takes no session id — out of scope by inspection.
Also: fixed a latent Hypothesis flake (per-example 200ms deadline under
xdist load) by setting `deadline=None` in both profiles.

## 2026-06-10 — PSH-4E2W: push failure prints halt cause + next step

<!-- prawduct: chunks=FRICTION-01 | status=shipped | release=v0.9.5 | scope=friction-basket -->

`push_cli execute` failures previously printed only the errors-file path plus
bare "top error patterns", forcing a read of `.last-push-errors.json` on every
halt. `_group_errors` now carries a representative `tool`/`action` and the
first non-null responder `hint` per pattern, and `format_summary` renders a
"Halt cause" block: `tool.action: error (N calls)` + a `next:` line
(responder hint first; hint-less `device.load` failures point at
REQUIREMENTS.md; connection-class halts at the Live-running checklist;
otherwise the generic fix→rebuild→re-execute loop). Summary redaction is now
test-pinned (large payloads can never leak past the 60-char grouping prefix).
`skills/ableton-push/SKILL.md` + `push-execute-design.md` updated to match.

## 2026-06-10 — AUD-4W7K chunk 2: db_seq provenance + seq resolver + surfacing sweep

<!-- prawduct: chunks=AUD-4W7K-02 | status=shipped | release=v0.9.5 | scope=aud-4w7k -->

The seq keying layer: the MCP server reads the song's latest audit-log seq
at render-forward time (`server._attach_render_db_seq` — the render handler
runs in Live's hallucinote-less env, so the read lives server-side, a
deviation from the plan's handler-side wording) and the handler writes it
as `manifest.db_seq`; `CaptureSet` and `MixReport` carry it (old manifests
load as None). `compare.resolve_baseline(analysis_dir, seq)` finds the
matching report (latest tie-break, teaching error otherwise);
`analyze_mix(compare_to=<seq>, analysis_dir=...)` and
`ableton_analysis(analyze, compare_to=<seq>)` complete the loop, with the
baseline validated before the DSP passes. Surfacing sweep: render-handler
"deferred" paragraph, analyze action description/tips, `/mix-review` A/B
recipe, spike decision-record updates. AUD-4W7K complete pending merge.

## 2026-06-10 — AUD-4W7K chunk 1: compare_to baseline diffs via explicit path

<!-- prawduct: chunks=AUD-4W7K-01 | status=shipped | release=v0.9.5 | scope=aud-4w7k -->

`MixReport.compare_to` is no longer a reserved skeleton: `audio/compare.py`
diffs two serialized reports — per-surface loudness deltas keyed by
track_id (added/removed surfaces explicit), overshoot count, significance
floors calibrated on the six real sun-zone-done analysis JSONs (0.5 dB
default; 1.0 dB for the timing-sensitive lufs_s_median). Deltas are neutral
evidence — no finding kinds derive from them. `analyze_mix(compare_to=<path>)`
loads the baseline fail-fast and populates the field. The v3→v4 real-pair
diff tells the known story exactly (true peak 1.52→−0.96 dBTP, 8
overshoots→0). Seq keying lands next chunk.

## 2026-06-10 — AUD-3F8M chunk 2: mixer_pan verified via master L−R balance

<!-- prawduct: chunks=AUD-3F8M-02 | status=shipped | release=v0.9.5 | scope=aud-3f8m -->

`mixer_pan` joins `mixer_volume` on the master-bus verification path:
constant-power pan gains × the stem's static fader gain (threaded from
`analyze_mix`'s existing `stem_gains`) predict the expected L−R balance
shift (`master_balance_db`); same detectability floor / model-breakdown /
direction+0.3× semantics as volume. Real-capture evidence: sun-zone-done's
break pan sweep (±0.95) verifies 4/4 measurable change-points REALIZED.
Contract text updated everywhere the old "mixer kinds are unverifiable"
claim lived (tool description, envelope collector, `/mix-review` skill,
module docs). AUD-3F8M complete pending merge.

## 2026-06-10 — AUD-3F8M chunk 1: mixer_volume verified via master-bus windowing

<!-- prawduct: chunks=AUD-3F8M-01 | status=shipped | release=v0.9.5 | scope=aud-3f8m -->

`mixer_volume` envelopes are no longer skipped as post-fader-invisible:
`audio/automation.py` windows the MASTER (post-fader sum) around each
breakpoint and checks the level step against a prediction built from the
declared fader values (`levels.live_fader_gain` calibration) + the measured
pre-fader stem power (uncorrelated power model). Predicted step < 0.75 dB →
honest `measurable=False` (stem too diluted/silent); model breakdown
(stem-at-gain exceeding limited master power) is also an honest skip, never
a false verdict; realized = declared direction + ≥0.3× predicted (lenient
for the house master limiter). `master_audio` is a required kwarg through
`analyze_mix`. Spike + real-capture evidence in the AUD-3F8M plan Status
(sun-zone-done's one mixer_volume envelope is a subtle trim — honestly
gated at all 12 change points). `mixer_pan` lands next chunk.

## 2026-06-04 — INS-7V2D follow-up: MCP cold-start startup timeout fix (`MCP_TIMEOUT`)

<!-- prawduct: type=bugfix | chunks=INS-7V2D-cold-start-timeout | scope=plugin-distribution | status=shipped | release=v0.9.4 -->

The plugin-bundled `hallucinote-mcp` server timed out on a genuinely-cold first start: the spawn
runs a full `uv` build (numpy/scipy/librosa/llvmlite, ~70 MiB) and the connection timed out at
**30000ms** despite `plugin.json` declaring `"timeout": 60000`. **Root cause:** the per-server
`plugin.json` `timeout` governs *tool execution*, not the *startup* handshake — startup is
governed by the `MCP_TIMEOUT` env var (default 30000ms), which the v0.9.3 design never raised, so
the intended 60s safety net never existed for startup. (This supersedes the v0.9.3 entry's
"cold-cache-within-60s" residual framing.) **Fix:** a tested, atomic, idempotent config op raises
`env.MCP_TIMEOUT` in `settings.json` to a **180000ms (3 min) floor** (`STARTUP_TIMEOUT_FLOOR_MS`),
never downgrading a higher existing value; `/ableton-mcp-install` writes it into
`~/.claude/settings.json` for end users, and this dev repo carries it via committed
`.claude/settings.json`. The SessionStart pre-warm hook also emits a clean `additionalContext`
heads-up so Claude can guide a `/mcp` reconnect when a cold build loses the spawn race; every
non-success hook branch now routes to **stderr** so warm sessions inject nothing into Claude's
context. **Live-verified (this session):** the operator ran `uv cache clean` (genuinely cold uv
cache) and restarted (`--plugin-dir .`); the cold build completed and the `hallucinote-mcp` tools
connected **on first launch — no `/mcp` reconnect needed**, confirming the 30 000 ms
startup-timeout failure does not recur under the 3-min floor (operator-verification check #1; the
race→reconnect fallback, statusMessage display, and uninstall reversal remain unverified). 22 new
unit tests pin the config-op and hook semantics.

## 2026-06-04 — INS-7V2D: plugin-bundled MCP server via uv (version-locked)

<!-- prawduct: chunks=INS-7V2D | status=shipped | release=v0.9.3 | scope=plugin-distribution -->

The Claude Code plugin now **bundles the `hallucinote-mcp` server** and launches it via
`uv run --frozen --all-packages --project ${CLAUDE_PLUGIN_ROOT}` from a committed `uv.lock`
into `${CLAUDE_PLUGIN_DATA}/venv` — version-coupling the running bridge to the plugin *by
source* (editable workspace members in the lock), so the bridge can never drift from the
engine it shipped with. A SessionStart pre-warm hook (`hooks/prewarm-mcp-env.sh`) rebuilds
the DATA venv only on lock change and never fails the session; **verified firing live** in a
clean-room `--plugin-dir .` restart (sentinel `uv.lock` byte-matches the repo, `MCP env
ready.` at startup). The old install-skill PATH-override config-writing path (`configure-mcp`
/ `plan_mcp_config` / `merge_server_entry`) is retired — the plugin provides the server
PATH-independently; install now adds a `uv`-presence preflight and only confirms `/mcp`.
Docs (README/quickstart/collaboration), an engine-pin record (`docs/engine-pin.md`), and
operator-verification updated. 8 commits, full suite 3043 passed / 2 skipped; cumulative
Critic clean; independent PR review 0 blocking. (PR #150 → develop; promoted to main here.)
Residual live checks honestly enqueued in `operator-verification.md`: cold-cache-within-60s
on a clean machine + the plugin-update rebuild cycle.

## 2026-06-04 — Backlog low-cost sweep: ~13 items fixed in parallel (file-disjoint clusters)

<!-- prawduct: chunks=backlog-low-cost-sweep | status=shipped | release=v0.9.2 | scope=backlog-low-cost-sweep -->

A parallel sweep of the low-cost / no-Live tier of the backlog, executed as seven
file-disjoint clusters (verify-against-current-code, then surgical fix + narrow
tests) since the backlog's file references had drifted (`sync/push.py` was split
into `sync/push/` + `sync/pull/`). 9 commits, +~1840/-92, full suite 3033 passed
across 3 consecutive `-n auto --dist loadgroup` runs.

- **SYN-2M9P** — `plan_push_devices` no longer emits an impossible
  `device.load(master=True)` for an unlinked master device (Live 12.4 has no LOM
  master-load path). It skips the load with a place-by-hand note; `set_parameter`
  still fires on a hand-placed+linked master device. Removes the reliably-PARTIAL
  push (devices-phase halt stranding envelopes/arrangement/cues) for any song
  authoring a master-strip chain. Mirrors DEV-2M9K's "configure-only" contract.
- **SYN-8H2W** — markdown frontmatter inline-list items containing `,` / `[` / `]`
  now survive the serialize→parse round-trip (quote-aware split + conditional item
  quoting; loud raise on the unrepresentable both-quote-chars case).
- **SYN-1T4K** — `_TRANSACTION_DEPTH` moved to a `threading.local`-backed map; the
  single-thread nesting contract is byte-identical.
- **SYN-3D7M / SYN-9K5T** — session-clip `delete_clip → arrangement_clips` cascade
  is now counted + reported in `out.details`; a populated entry missing BOTH name
  and length now warns (parity with the arrangement path) instead of silent no-op.
- **SYN-2K8T** — the one raw `arrangement_clips JOIN clips` read factored into
  `Q.get_arrangement_placements_with_clip_length` (read-helper discipline).
- **DEV-6T2W** — the `inventory_handler` device-walk is now bounded by a node-visit
  budget (`max_nodes`, default 200000) vs the 15s main-thread ceiling; returns
  `truncated=True` (never-silently-truncate) and the misleading "raise read_timeout"
  tip was corrected to "subdivide via `path_prefix`".
- **GEN-5K2D** — new exact-rational `generators.primitives.polyrhythm()` via
  `fractions.Fraction` (composed ratios land exact; float→edge at the mutator only).
- **INS-4H8M** — analyzer `HallucinoteAnalyzer.amxd` raw-byte sha256 fingerprint +
  a preflight `analyzer` drift block; `/ableton-mcp-install` Step 3d branches on
  `matches` to skip the redundant overwrite prompt (parity with the Remote Script
  verify). Verified on the real machine.
- **TST-7H2M** — `@settings(deadline=None)` on the two compute-bound `@given`
  correlation/DFA tests (the parallel-xdist flake class; assertions unchanged).
- **TST-4M9D** — FastMCP single-tool lookup centralized in a `get_registered_tool`
  helper that prefers the public `get_tool()` accessor (was reaching into `_tools`).
- **DOC-3P7K / AUD-9D3P / MET-9D4H** — deep reference docs reprefixed to
  `/hallucinote:*` + songs-repo paths (post-split); the audio dep-adoption recorded
  in `project-state.yaml` (the stack uses numpy/scipy/librosa as CORE deps — the
  "stdlib-only" decision was superseded, not reversed); Requirements-Confidence
  header convention documented.
- **TST-7K3H** — verified already-fixed-and-tested (the W6-A note-expression
  validate-before-gap precedence + its three tests predate the stale item).

Deferred with rationale (NOT silently dropped): **DEV-1F9X** (plugin-discriminator
dedup) stays open — correctly gated on the unshipped W11-A `hallucinote-core`
extraction so the move happens once, not twice. Also filed **TPL-2D8K** (a project
`.als` template with the master-bus chain pre-placed — the user-requested workaround
for "LOM can't add master devices"). Cumulative Critic: 0 blocking, 2 warnings
(stale evidence + this change-log entry — both resolved here), 2 notes (markdown
write-boundary hardened; backlog reconciled).

## 2026-06-04 — Install hardening: every install mutation in tested, atomic Python

<!-- prawduct: chunks=install-hardening | status=shipped | release=v0.9.2 | scope=install-hardening -->

Moved every `/ableton-mcp-install` + `/ableton-mcp-uninstall` filesystem and
MCP-config mutation out of hand-authored skill shell into tested, atomic,
cross-platform Python in the stdlib-only `hallucinote_mcp` package, exposed via CLI
subcommands. Triggered by a zsh-glob abort (`--exclude=*.pyc`) that left a
half-installed Control Surface (the `rm` ran, the copy didn't).

- **`install_ops.py`** — `vendor_remote_script` (stage → verify → swap with rollback;
  the half-install is now structurally impossible), `verify_remote_script`
  (source-derived completeness + held excludes, drift-proof — no hardcoded file
  list), `install_analyzer` (atomic file swap + overwrite-guard),
  `remove_remote_script`/`remove_analyzer`. The rsync anchoring (package-root
  `server.py` out, `remote_script/server.py` kept) is reproduced as a pure-Python
  `copytree` ignore predicate — no shell, no glob expansion.
- **`mcp_config.py`** — `plan_mcp_config` (pure 5-row truth table keyed on `on_path`
  + `already_registered`, NOT plugin-detection — closes the venv-not-on-PATH gap with
  a user-scope absolute-path override that dominates a plugin entry by precedence),
  `merge_server_entry` (preserves siblings), `write_config_atomic`, `delete_entry`.
- **CLI** — `install-remote-script`, `install-analyzer`, `uninstall-remote-script`,
  `uninstall-analyzer`, `configure-mcp`, `remove-mcp-config`.
- **Skills** — `/ableton-mcp-install` + `/ableton-mcp-uninstall` rewritten to
  orchestration-only (preflight → confirm → CLI → hand-off); zero hand-authored
  mutation shell. The consistency test's exclude-STRING drift checks consolidated
  into behavioral tests in `test_install_ops.py` + a "skills invoke the CLI, no
  mutation shell in command blocks" contract (contract moved, not weakened).
- **Bug fix** — `existing_mcp_config_files`/`malformed_mcp_config_files` coerce a str
  `cwd` to `Path` (the CLI passes `--cwd` as a str; was an `AttributeError`),
  surfaced by the round-trip integration test.

+42 tests (excludes, atomicity incl. rollback + backup-preservation, the config
truth table, hermetic install→uninstall round-trip). Full `hallucinote_mcp` suite
938 passed. Cumulative Critic: 0 blocking. INS-4H8M (analyzer fingerprinting) is
adjacent but unresolved — left open.

## 2026-06-03 — Tools-don't-narrow-the-art (gate verdicts / generator altitude / review workflow) + helpers DRY

<!-- prawduct: chunks=LNT-1V9K,GEN-1S4K,REV-2W8K,helpers,chunk0 | status=shipped | release=v0.9.2 | scope=tools-dont-narrow-the-art+helpers-dry -->

One thesis across four pieces: a build-time lens/helper is a **ruler, not a stamp** —
it measures and asks; it never vetoes a deliberate choice or makes the musical decision.

- **A1 (LNT-1V9K) gate verdicts.** `theory/lint.py`'s `harmonic-stasis` — the only
  `severity="blocking"` verdict in the codebase — split into `harmonic-stasis` WARNING
  (still named in `stasis_sections`) + a new `harmonic-absence` INFO (the case that
  false-blocked a bass-less section). Removed the build raise in `sun-zone-done/build.py`;
  the realization regression moved to the song's own test. New `gate-verdict-policy.md`
  enumerates BLOCKING = technical/structural errors only.
- **A2 (GEN-1S4K) generator altitude.** `generator-altitude-policy.md` — no
  section/genre-archetype builders in the package (song-local only); package idioms are
  single-part conveniences over exposed primitives; the interplay vocabulary is a
  friction-driven primitive layer (ARR-3R8F), not a fusion-section builder.
- **A3 (REV-2W8K) structured review.** `review-workflow-model.md` (one axis per turn, 5
  archetypes) + a per-song `review_workflow` annotation (sun-zone-done = C Subtractive) +
  `/compose-review` and `/mix-review` wired to read the archetype and edit one axis per turn.
- **Helpers DRY.** Hoisted duplicated song-build bookkeeping into the library —
  `Q.tracks_by_name`/`returns_by_name` (queries) and `arrange_section`/`run_build`
  (new `hallucinote/authoring.py`). All four songs migrated to the helper functions;
  the `/song-new` scaffold uses `run_build`. Existing composed songs' build() lifecycle
  migration deferred (SNG-4H2D).
- **Chunk 0.** sun-zone-done back-half Pass-A close-out (prior stale-doc Critic warning
  resolved) + backlog true-up (6 merged items archived, scene-provision dedup).

Full suite 2881 passed. Cumulative Critic + independent PR review both clean (0 blocking).

## 2026-06-02 — Audio verification correctness: reverb RT60 + automation realization

<!-- prawduct: chunks=AUD-6R2M,AUD-4S8T,AUD-8H2M | status=shipped | release=v0.9.2 | scope=audio-verification -->

Branch `fix/reverb-rt60-decay-tail` (off `develop`). Made the audio analyzer's
verification surfaces trustworthy on real multi-track songs. (Shipped in v0.9.2;
tagged `release=unreleased` at author time pending a release cut, flipped to the
real version by VEW-9QH4 — first resolved to v1.5.0, corrected to v0.9.2 in PR
review once the two concurrent version tracks were untangled. Live re-render
validation of the real reverb tail + the Amp-flip is deferred to the user.)

- **Reverb RT60 — per-return decay-tail (AUD-6R2M).** Replaced the multi-source
  single-dry deconvolution (which returned 252–370 s on real 5–6-send returns)
  with a dry-source-free measurement: RT60 once **per return** from the return's
  own captured ring-out via Schroeder backward integration. `ReverbVerification`
  reshaped per-return with honesty fields; refuses to fabricate a number
  (`sufficient_tail=False`/NaN) when no ring-out exists. On the real sun-zone
  capture: 11 garbage per-send values → 2 honest per-return skips.
- **Source-side ring-out capture (AUD-4S8T).** A measure-first check showed the
  real capture has no ring-out (master plays to within 35 ms of the file end).
  `render.py` now records `ring_out_beats` (default 8) past the arrangement end
  so the reverb decays into a captured tail — Python-only, **no `.amxd` change**
  (the device records to whatever stop-beat it's handed). Loop forced off +
  restored; manifest records the actual rounded ring-out.
- **Automation realization verification (AUD-8H2M).** New `audio/automation.py`
  windows each declared envelope breakpoint and reports realized-vs-declared: a
  device-parameter timbre flip (Amp Type) as a directional spectral-centroid
  shift, a dynamic send as a level step. `mixer_volume`/`pan` are reported
  unverifiable (post-fader, invisible to the pre-fader stem) — master-bus
  windowing is a follow-up.

Two cumulative `/critic` passes (0 BLOCKING each); all warnings/notes resolved.
Full suite 2840 passed / 0 failed (18 `songs/missing` corpus-parse failures are a
pre-existing, user-acknowledged-out-of-scope gap in a different song, deselected).

## 2026-05-30 — Arrangement model + sun-zone-done flagship (Chunks 1–5)

<!-- prawduct: chunks=arrangement-1-5 | status=shipped | release=v1.4.0 | scope=arrangement-model -->

The `feature/sun-zone-done-flagship` branch. A new song-structure subsystem
(`hallucinote.arrangement`) plus its first full demonstration: sun-zone-done
rebuilt from a 7-section/64-bar skeleton into a **9-section / 80-bar narrative
arc** authored entirely on the model. (Release tag matches the current
in-progress release; confirm/regroup at merge into `develop`. Live verification
of the song is deferred — see `songs/sun-zone-done/sun-zone-done.md`.)

- **The module (Chunk 1, prior commit `2f971bf`):** `arrangement.py`
  (`Motif` / `Arrangement` with `section`/`plan`/`materialize`/`energy_curve`,
  `PlacedSection`, `vary()` delta ruler) + the six canonical motivic variation
  ops + `shift` in `generators/variations.py`. All **rulers** — they carry
  identity / presence / references / arithmetic and emit the same DB rows through
  the mutators; the composer makes every musical decision. Design foundation in
  `.prawduct/artifacts/arrangement-model.md`.
- **Section map + energy curve (Chunk 2):** the full arc with genre-flip energy
  **discontinuities** (never smoothed) and recurrence as one-identity-plus-a-delta
  via `vary()` (verse2 organ +12; chorus2 lead −12 power-octave). Rhythm gtr stays
  a monolithic 320-beat clip + Amp envelope, driven by the same `plan()`.
- **Polyrhythm intro (Chunk 3):** a hand-authored 3:4:5:7 Em7 cross-rhythm
  shimmer that builds to unbearable then drops — registered as the
  `polyrhythm-cloud` motif.
- **Metal energy + steel pans (Chunk 4):** a crash per 4-bar phrase + rising
  snare fills so long metal stretches breathe; a new `06 Steel` Island-Pans track
  entering in the later reggae sections (verse2 as a `vary()` add-delta + outro).
- **Convention-break + integration + outro (Chunk 5):** the Amp **timbre**
  decoupled from groove **time-feel** and inverted in the break; the integration
  **quotes** the polyrhythm motif on the organ (recapitulation — the two worlds
  fused); the outro fragment+diminishes the `no-time-stab` motif into double-time
  Phrygian bursts → DubDelay.
- **Framework robustness:** `reggae_one_drop` / `metal_gallop` now degrade
  gracefully on kits missing the optional open-hat / crash pads
  (`kit.try_pitch_of`) — Ableton's Hot Rod Kit ships closed hats only, which was
  crashing the real build.

Cumulative `/critic`: 3 warnings + 1 note, no BLOCKING — all resolved. Full suite
**2515 passing** (+18 song shape/intent tests, +2 generator degradation tests).

## 2026-05-29 — Bulk note-authoring: scoped push + /compose-part + inline guardrail (B1–B4)

<!-- prawduct: chunks=bulk-notes-B1-B4 | status=shipped | release=v1.4.0 | scope=bulk-note-authoring -->

The `feature/bulk-note-authoring` branch. **Notes are authored as code, never as
data-in-context**: the LLM writes the smallest correct generator expression, a
build expands it through mutators (events fall out), and a scoped push
materializes only what changed to Live — bytes never enter the agent's context.
External validation: Anthropic's Nov-2025 "code execution with MCP" is exactly
this pattern; the hard mechanism (`push_cli execute`) already existed, so the
real work was retiring the inline paths and wrapping the loop in a usable skill.

- **B1 — scoped push** (`sync/push_notes.py` + `push-notes` CLI subcommand):
  materialize only targeted (`--clip`) or **content-changed** (`--changed`)
  clips' notes, in-process, with a counts-only summary (notes never tokenized;
  mirrors `_summarize_args`/`_LARGE_LIST_KEYS`). Change detection is
  **content-fingerprint** based, not event-watermark — a whole-DB rebuild that
  didn't alter a clip won't re-push it. Modify/delete/total-replace ride this for
  free (the unit of change is the clip's full note array). 15 tests.
- **B1b — opt-in clip-prune** (`push.plan_clip_prune` + `prune` CLI): structural
  deletion of Live session slots with no matching DB clip, dry-run by default,
  deletes only on `--apply`. Core safety: a DB-backed slot is NEVER pruned;
  whole-track-orphan refused per-track. Pure planner kept offline-testable. 7 tests.
- **B2 — `/compose-part` skill**: the interactive author→build→scoped-push loop
  driven to a FINISHED audible part (creative-deliverable DoD) — read intent →
  author notes as code in `build.py` (`hallucinote.generators`, feel baked in,
  probe kits) → `python build.py` → `push-notes --changed`. Adds a discoverable
  **Authoring API** index to `docs/song-authoring-conventions.md` (progressive
  disclosure), guarded by a bidirectional drift test.
- **B3 — `/pattern-compose` retired (supersede)**: deleted, not migrated — its
  inline-`ableton_clip(notes=)` + direct-to-Live DB-bypass were exactly the
  anti-patterns this work removes, and its named patterns already exist as
  `generators` helpers. Live refs repointed to `/compose-part`.
- **B4 — inline-notes guardrail** (`handlers/clip.py`): soft cap (32) on
  `create` + `replace_notes`; above it, a non-blocking teaching `warning` points
  at the author-as-code loop. Parity-locked across both actions; agent-facing
  mirror in `ableton://guides/conventions`. Non-blocking — trivial edits stay
  frictionless.

Suite: 2319 passing (from 2289 at branch start). Per-chunk Critic review across
B1/B1b (1 cumulative), B2/B3, and B4 — all clean at completion.

## 2026-05-29 — Masking analyzer + intent architecture + timing feel (C1–C7)

<!-- prawduct: chunks=masking-C1-C7 | status=shipped | release=v1.4.0 | scope=masking-analyzer -->

The `feature/masking-analyzer` branch: the section-scoped, intent-aware audio
analyses no commercial meter can produce — measurement DSP that stays neutral,
with intent-grading pushed entirely to one holistic interpreter (`/mix-review`).

- **C1 — inter-stem masking DSP** (`audio/masking.py`): STFT → Bark critical
  bands → Schroeder spreading → per-tile masked-fraction. Pairwise
  (`MaskingPair`) + cumulative-bed (`BedMasking`, catches distributed low-mid
  buildup pairwise misses). Pure, DB-agnostic, scale-invariant, energy-gated.
  No severity — neutral evidence.
- **C3 — mix-level reconstruction** (`audio/levels.py`): captured stems are
  pre-fader (M4L parallel tap), so masking (a relative-level measure) needs the
  static fader gain reapplied. Fader curve **calibrated against real Live 12**
  (swept volume, read display_value): [0.40,1.00] is exactly 40·(v−0.85),
  sub-0.40 a measured table.
- **C4 — mix-intent + feel/groove tag vocabulary**: controlled tags
  (`focal`/`blend-group`/`submerged`/`density`; `feel`/`groove`/`push`/`drag`/
  `swing`) on markdown frontmatter — no schema change.
- **C5 — `markdown_refs` recall-on-read reindex**: `/song-context` was silently
  empty because the corpus was only reindexed by a manual CLI; now reindexed on
  read (single-song-scoped).
- **C6 — `/mix-review` holistic interpreter** (the moat): recall intent →
  read the whole `MixReport` → interpret across metrics vs declared intent →
  two-register response (execute if directed, ask one question if volunteered)
  → learn revealed intent back as a markdown annotation. The single read-side
  surface over all analyses.
- **C2 — retire the dead DB `annotations` table + `ableton_annotation` MCP
  surface**: 0 rows across 14 DBs; the disposable DB made it a data-loss trap.
  Intent's single authored home is the git-tracked markdown corpus. 13→12 MCP
  tools, 12→11 resources; `/decisions` repointed to requests-only.
- **C7 — per-part timing-deviation analyzer** (`audio/timing.py`): the read-side
  counterpart to the `feel` generator. Recovers push/drag (signed drift),
  tightness (drift stdev), and swing (median off-beat-8th phase) from captured
  audio onsets per part, per section. Neutral measurement, tightness-based
  confidence so transient-poor / cross-rhythm parts self-flag as low-trust.

Architecture decision (see `intent-architecture.md`): every DSP module stays a
pure measurement producer feeding `MixReport`; intent lives in markdown (WHAT =
`build.py`, WHY = markdown, WHY-CHANGED = decisions); the disposable DB is never
the authored home. Validated end-to-end on real Live audio (sun-zone-done).
Full suite 2248 → 2251.

## 2026-05-28 — Section-windowed audio analysis: `MixReport.per_section`

<!-- prawduct: chunks=section-windowing | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

First post-MVP item off the audio-analysis roadmap (spike §9 deferred
#1). The same loudness metrics, scoped to each named section instead of
only the full-song aggregate — answers "is the chorus actually louder
than the verse?" and "did the bass-cut help in the section it was
supposed to?"

**Windowing source: the `sections` table, not `cue_points`.** The
backlog said "cue_points," but the named sectional structure with
half-open `[start_bar, end_bar)` spans lives in the `sections` table
(populated via `M.create_section`); `cue_points` are point markers with
no spans and can't scope a window. Decision recorded here.

- New module `src/hallucinote/audio/section.py`: `SectionWindow`
  (name + half-open beat window) and pure geometry —
  `intersect_window` maps a beat window onto clamped sample bounds via
  the capture's constant-tempo linear beat→sample map; `slice_audio`
  returns the overlapping slice. No-overlap / degenerate-span /
  empty-audio all yield `covered=False` (no divide-by-zero).
- `analyze_mix(..., sections=...)` runs a fourth pass producing
  `MixReport.per_section: list[SectionMetrics]` — per-surface loudness
  (master + stems + returns) scoped to each window, mirroring the
  top-level report shape. A section entirely outside the captured
  transport window — or overlapping it by less than the 400 ms BS.1770
  block minimum — is recorded in `skipped_analyses` (kind
  `section_windowed`) rather than crashing `measure_loudness` or emitting
  empty metrics; no sections declared → one teaching skip naming
  `create_section`.
- `master_overshoot` findings now tag their `db_reference` with the
  section the overshoot lands in (`"section:chorus1 (beat:...)"`) — the
  read-side tie between headline attribution and sectional structure.
  (Also fixed the long-standing `bar:` mislabel — the value was always
  in beats.)
- Handler `_collect_sections` reads the `sections` table + the
  `time_signature_map` and converts each bar bound to song-absolute
  beats via the canonical `push._position_bar_to_beats` (walks the meter
  map exactly — the only constant-tempo assumption is the downstream
  beat→sample step). `analyze_mix` stays DB-agnostic, same pattern as
  `declared_reverb_sends`. Summary gains `section_count`.
- Stale `ableton_analysis` action tips fixed: the "MVP DB has no schema
  for declared RT60 sends yet" line was stale since PR #99.

Tests +18 (2168 → 2186): `test_section.py` (windowing geometry + edge
clamping), `test_analyze.py` (per-section populated, loud>quiet, skip
for out-of-capture section, skip for sub-400 ms overlap, overshoot
section-tagging), `test_report.py` (SectionMetrics serialization),
handler tests (DB sections → per_section, no-sections skip).

Backlog: section-windowed *loudness* shipped; per-section contribution
attribution, section-scoped masking (the iZotope differentiator), and
variable-tempo-accurate windowing carried forward as a P1 follow-on.

## 2026-05-28 — Audio Analysis MVP follow-on: `sends.intended_rt60_s` schema + loudness helper unification

<!-- prawduct: chunks=3-followup | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Two small bundled chunks against `develop` after the Chunk 3 squash-merge
(d4d2387 on develop).

**A. DB schema for declared reverb-send intent (P2 backlog → closed).**
Closes the teaching-error gap shipped in Chunk 3: real-song `analyze_mix`
invocations no longer fall through to the no-intent skip record when the
composer has declared RT60s on reverb sends.

- `sends.intended_rt60_s REAL` column (CHECK > 0 or NULL) — schema.sql
  + `_ADDED_COLUMNS` migration entry. Existing songs pick it up on next
  `init_db` open.
- New mutator `M.set_send_intended_rt60(from_track_id, to_return_id,
  intended_rt60_s)` — requires existing send row, accepts None to clear,
  emits `SEND_INTENT_SET` event, idempotent on no-change.
- New query `Q.get_reverb_send_intents_for_song(song_id)` — returns sends
  with non-NULL intent. `get_sends_for_song` also gains the column in
  its projection.
- `analyze_handler` walks the DB intents and lifts each row into a
  `DeclaredReverbSend` before calling `analyze_mix`. `analyze_mix` stays
  DB-agnostic — the lift happens in the MCP layer, not in
  `src/hallucinote/audio/`. The empty-intent skip record now names the
  mutator (`set_send_intended_rt60(...)`) rather than the old
  "wait for the DB schema" placeholder.
- P2 backlog entry deleted (close-in-the-same-PR discipline).

**C. Loudness helper unification (Critic note #3).** `_short_term` and
`_short_term_from_momentary` collapsed into one `_short_term_median`
backed by a shared `_blockwise_loudness(audio, sr, block_size)` helper.
`_ShortTermResult` dataclass removed — the function returns a float
directly. Behavior unchanged; net -25 LoC. New regression test pins the
sub-3s fallback path with calibrated pink noise (was untested).

**Tests:** 2159 → 2168 (+9). Full suite passes in ~41s parallel.
- +6 in `tests/unit/sync/test_mix.py` — intent mutator (lifecycle,
  validation, idempotence, event emission), query filtering NULLs,
  schema CHECK at the raw-SQL boundary.
- +1 in `tests/unit/audio/test_loudness.py` — short-clip fallback path
  produces a finite LUFS-S via momentary blocks.
- +2 in `hallucinote_mcp/tests/unit/test_handlers_analysis.py` —
  handler picks up DB intent and produces `reverb_verifications`
  populated; absent intent re-asserts the teaching-message contents.

**Cross-boundary check.** Boundary crossed: DB schema → handler DB read.
`set_send_level` callers unchanged (the new column is additive + NULL-
default). `get_sends_for_song` callers see the new column appended; sync
push/pull don't touch it (intent is composer authorship, not Live state).

## 2026-05-28 — Audio Analysis MVP, Chunk 3 (3-A + 3-B + 3-C) — analysis pipeline + `ableton_analysis` MCP tool

<!-- prawduct: chunks=3 | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Chunk 3 sub-chunks 3-A, 3-B, and 3-C closed. The analysis half of the
audio-analysis MVP is now built: captures dirs produced by
`ableton_render` are now consumable through a new MCP tool that
produces a `MixReport` JSON keyed to the song's DB-recorded intent.

3-D (Critic + final commit/PR) is the last remaining step — the
pipeline is feature-complete and real-data verified, but the formal
Critic pass + change-log polish is the in-flight close work.

**Worktree:** branch `feature/audio-analysis-chunk3` off
`origin/develop@f0d0a46`. Local `develop` was 1 ahead / 1 behind origin
at the start of this session; the user is doing framework-sync work
separately so a worktree was the lowest-disruption path to ship Chunk 3
without entangling with the framework drift on `develop`.

**What landed (3-A — foundation + loudness):**

1. `src/hallucinote/audio/` is a new sibling of `db/`, `generators/`,
   `sync/` per the project's "layer folders inside src/hallucinote"
   convention. Pure-Python computation against WAVs + DB; never imports
   MCP.
2. `report.py` — `MixReport` dataclass + sub-dataclasses
   (`StemMetrics`, `LoudnessMetrics`, `MasterOvershoot`,
   `ReverbVerification`, `Finding`). Schema version pinned at `"1"` in
   the report itself (matches the capture-manifest pattern).
   `compare_to` field reserved as a skeleton for the P2 baseline-diff
   backlog. `skipped_analyses` field is the structural "Never silently
   drop a requirement" surface.
3. `io.py` — `load_capture(manifest_path) -> CaptureSet`. Reads
   `manifest.json` + per-surface WAVs via `soundfile`; refuses
   non-float32 / non-stereo / sample-rate-mismatch with teaching
   errors (analysis math depends on the exact format `sfrecord~` writes
   per the analyzer spec).
4. `loudness.py` — BS.1770-4 LUFS-I / LUFS-S median / LUFS-M peak via
   `pyloudnorm.Meter`, plus 4×-oversampled true peak in dBTP via
   `scipy.signal.resample_poly` (the 15-LoC spike §3 sketch). Short-clip
   guard raises rather than silently returning NaN.

**What landed (3-B — attribution + reverb):**

5. `attribution.py` — `find_master_overshoots` (4×-oversampled detection
   with gap-merge + min-window thresholds) + `master_bus_attribution`
   (per-overshoot dominant-band detection via per-band RMS, then
   per-stem RMS contribution ranking in that band). Six named bands per
   spike §3 (sub_20_60 through air_6k_plus); names are stable wire
   format. Beat conversion happens at the `analyze_mix` boundary, not
   in this module — keeps attribution tempo-agnostic.
6. `reverb.py` — `deconvolve_ir` (Wiener-regularized spectral
   deconvolution with ε floor for stability) + `verify_reverb_send`
   (deconvolves IR, trims to onset, runs
   `pyroomacoustics.experimental.rt60.measure_rt60`, compares to
   declared). Stable on noisy dry signals (regularization works) but
   only accurate on clean dry — the spike §7 "honest gap" is pinned in
   a stability-only regression test, not a fake accuracy claim.

**What landed (3-C — `ableton_analysis` MCP tool):**

7. `analyze.py` — `analyze_mix(captures_dir, song_db_conn=None,
   declared_reverb_sends=())` orchestrator. Reads the capture set,
   measures per-surface loudness, finds + attributes master
   overshoots, runs reverb verification for any declared sends,
   derives structured `Finding`s, returns a populated `MixReport`.
   DB conn parameter is plumbed for future intent extraction (MVP DB
   has no `reverb_send_intent` schema yet — when declared sends are
   empty, `skipped_analyses` carries a teaching explanation).
8. `hallucinote_mcp.schema.TOOLS` extended with `"ableton_analysis"`
   (12 → 13 unified tools). `hallucinote_mcp.actions.analysis` exposes
   three actions: `help`, `analyze(song_slug, captures_dir?)`,
   `get_latest_report(song_slug)`. Both real actions are
   `runs_server_side=True` — mirrors `ableton_annotation`'s pattern.
9. `hallucinote_mcp.handlers.analysis` — `analyze_handler` opens song
   DB to validate slug, defaults `captures_dir` to the latest
   ISO-8601-named dir under `songs/<slug>/captures/`, calls
   `analyze_mix`, writes the report to
   `songs/<slug>/analysis/<iso-ts>.json`, returns
   `{report_path, schema_version, finding_count, summary}`.
   `get_latest_report_handler` returns the most recent MixReport JSON
   contents + path.
10. Tree-wide doc sweep for the tool-count drift: server.py PRIMER,
    server.py module docstring, `create_server()` docstring (12 → 13),
    `hallucinote_mcp/README.md` headline + tool table (added two new
    rows for render + analysis — the table had been one behind through
    Chunk 2), root `README.md` project-layout block.

**Dependencies added** (`pyproject.toml`):
`pyloudnorm>=0.2`, `librosa>=0.10`, `pyroomacoustics>=0.7`. All
MIT/BSD/ISC. Comment in pyproject explaining what each does and why
they belong as main deps (per Chunk 1's precedent: audio foundation
belongs alongside the rest of the platform, not behind extras).

**Tests:** +46 (2113 → 2159). Distribution:
- `tests/unit/audio/`: 6 report, 7 loudness, 7 io, 5 attribution,
  4 reverb, 4 analyze-orchestrator = 33
- `hallucinote_mcp/tests/unit/`: 6 actions_analysis, 7 handlers_analysis
  = 13
Full suite: 2159 passed in 16.6 s parallel (`-n auto --dist loadgroup`).

**Three measurable success criteria pass on synthetic fixtures:**
- #3 — per-stem LUFS-I within ±0.2 LU on calibrated -23 LUFS pink noise
- #4 — top-2 stems >60% attribution in the 60-200 Hz band on a
  deliberately-overdriven kick+bass+rhythm fixture
- #5 — measured RT60 within ±0.15 s of declared 1.2 s on a synthetic
  dry impulse + known-IR convolution

**Real-data sanity check** (informational; not gated on user verification):
`analyze_mix('songs/reggae-metal/captures/20260527T200614Z')`
produced a structurally-correct report: master at -16.48 LUFS-I,
-2.03 dBTP (no overshoots — render not hot enough to overshoot);
5 stems all in plausible mix-bus territory (-16 to -22 LUFS-I, drums
peaking at -0.63 dBTP); A-Plate return shows real reverb tail
(-57 LUFS-I) while B-Room + C-DubDelay are silent (no sends were active
during that render — informational, not a bug). Reverb verification
section correctly skipped with the structured teaching reason (no
declared RT60 schema in DB yet).

**Out of scope for Chunk 3, deferred to backlog:**
- Section-windowed analysis (P1 — chorus / verse / bridge scoping)
- `compare_to` baseline diffs (P2 — field reserved in schema)
- Masking analyzer (P2 — custom DSP)
- Candidate mutation proposals (P2 — the "fix" side of §6)
- Reference corpus + full realtime feature set + take retention +
  `AUDIO_CAPTURED` event (P3 cluster)
- Source-separation fallback (P4)
- DB schema for `reverb_send_intent` (the missing piece that unblocks
  populated reverb_verifications on real songs without caller-supplied
  sends — natural Chunk-3 follow-up)

**Bundled M4L bugfix (commit `c46288a`):** the P0 backlog entry "`.amxd`
`[value track_id_retained]` is GLOBAL-by-name; multi-analyzer
/signature reply routing is unsafe" closed in this branch. The Max
patch was rewired to use a per-patcher `[message]` box for track_id
storage instead of `[value <name>]` — same shape as the
`[value hallucinote_path]` fix that closed Chunk 2 sub-chunk 2B,
applied to the OSC-feature-emit side. `.amxd` re-exported from Max
(487308 → 487801 bytes; verified byte-identical against the User
Library install); spec.md updated to reflect the new wiring and remove
the "Known multi-instance caveat" section that documented the bug;
P0 backlog entry deleted (Verifiable signal "no `[value <name>]` boxes
remain in the .amxd JSON" is satisfied). Not strictly required for
the Chunk 3 analysis pipeline (the analyzer's `/signature` reply
routing isn't on the analyze hot path), but bundling it here closes
the only known structural M4L bug ahead of the next sidecar work that
would have triggered it.

## 2026-05-27 — Audio Analysis MVP, Chunk 2 close-out — multi-analyzer simultaneous capture verified

<!-- prawduct: chunks=2 | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Chunk 2 — Capture pipeline — closed. Multi-analyzer simultaneous capture
verified end-to-end on reggae-metal song in Live 12.4 at 180 BPM:
`ableton_render(action='render', song_slug='reggae-metal',
start_at_beat=8, stop_at_beat=24)` produced 9 WAVs (5 tracks + 3 returns
+ master, each ~1.9 MB FLOAT/stereo/44.1k matching the 16-beat window at
180 BPM) + `manifest.json` in `songs/reggae-metal/captures/<utc-ts>/`.
Cross-correlation of track-01 Drums vs master.wav: peak lag = 0 samples
(sample-accurate). The transport-position-driven recording design
(Chunk 2 architecture decision) is structurally PDC-correct.

**Five fix sets landed in this close-out session:**

1. **Four integration-layer fixes from the prior session's afternoon
   triage backlog** (each with dedicated regression tests pinning the
   structural property that prevents recurrence):
   - (a) `ensure_analyzers_loaded` marshals each Live touch through
     `context.run_on_main` with a 50ms inter-surface yield. Was packing
     9-surfaces × 3-ops into one Remote-Script request-thread call, which
     deadlocked Live's main thread on the M4L runtime.
   - (b) `render_handler` splits seek/play and stop/disarm into separate
     `context.run_on_main` bouts with a worker-thread yield between.
     Fixes Live's "Changes cannot be triggered by notifications" error
     when one bout writes a state-change that triggers a listener
     cascade then synchronously enters another mutation.
   - (c) `server.handle_tool_call` absolutizes `ableton_render(render)`'s
     `output_dir` against the MCP server's cwd before forwarding to the
     Remote Script. Live's process cwd is `/` on macOS (read-only); the
     handler's pre-existing relative default raised `OSError [Errno 30]`.
   - (d) Port range shifted 11000 → 11020 (track base), 11100 → 11120
     (return base), 11200 → 11220 (master), 11201 → 11221 (sidecar
     emit). Clears AbletonOSC, the most common community Remote Script,
     which binds 11000 + 11001.

2. **Pre-roll seek fix** in render_handler: seeks to
   `max(0, start_at_beat - pre_roll_beats)` instead of directly to
   `start_at_beat`. Without the pre-roll, the patch's transport-cross
   detector (`$f2 < $i3 && $f1 >= $i3`) lands its first observer fire
   AT the threshold and misses the edge. Default `pre_roll_beats=4`
   (one bar at 4/4), symmetric to `post_roll_beats`.

3. **Wire/client `read_timeout` split**: `client.send`'s single 15s
   `timeout` split into `connect_timeout` (default 15s, bounds socket-
   accept) and `read_timeout` (default 15s, may be `None` for indefinite-
   block). `server.handle_tool_call` passes `read_timeout=None` for
   `ableton_render(render)` since the handler plays the full arrangement
   (minutes for long songs). `wire.recv_message(timeout=None)` now
   explicitly clears any inherited socket timeout.

4. **MAJOR ROOT-CAUSE PATCH FIX**: in-Live verification revealed that
   the `.amxd`'s `[value hallucinote_path]` storage was a GLOBAL shared
   variable across all M4L instances (M4L's `[value <name>]` is global-
   by-name). When N analyzers received `/path` in sequence, only the
   LAST path survived globally; all N `sfrecord~` instances raced to
   open the SAME file at cross-detect time, only one wins. Deterministic
   and order-dependent: OSC to track 1 then track 2 → only track 2
   records; reverse order → only track 1 records. Patch rewired so
   `OSC-route /path → prepend open → sfrecord~` directly (per-instance
   file handle on `/path` arrival), removing the value-storage
   indirection. Plus a `[sel 0 1]` outlet 1 → `[-1.]` wire for arm-
   rising-edge prev-pos reset (handles `start_at_beat=0` case under
   repeated renders). New learning landed: "M4L `[value <name>]` is
   GLOBAL-by-name across all device instances — never use for per-
   instance state."

5. **Critic-round-2 cleanups** (from `/critic chunk` second pass):
   deleted duplicate `_default_captures_dir` helper from handlers/
   render.py (server.py's `_absolutize_render_output_dir` is the single
   source of truth for default-resolution + absolutization); handler
   now refuses missing `output_dir` to make the contract explicit.
   Removed obsolete `_PER_INSTANCE_OSC_YIELD_S` constant + the
   `time.sleep` call — the patch fix makes per-instance OSC arrival
   truly independent (each udpreceive owns its own bound port), so the
   prior 50ms defensive yield is no longer load-bearing. Fixed
   `shared_sidecar` test to monkey-patch the default port (was failing
   when MCP server's sidecar was already running on 11221).

**Tests:** 2114/2114 pass (+10 since chunk start, all regression-pinning
the structural fixes above). Critic `chunk` mode after the Critic-round-2
cleanups: 0 blocking, 0 warnings, 0 notes.

**Cumulative session learnings (4 new entries to `.prawduct/learnings.md`
during this close-out):** the global-by-name `[value]` rule; the
`[sel 0 1]` outlet-2-vs-outlet-1 disambiguation around `[-1.]`. Plus
struck-through deprecation marker on the pre-existing "`[value]`
doesn't emit on cold write — bang to emit" rule (subsumed by the new
"always GLOBAL" warning).

**Out of scope for Chunk 2, deferred to Chunk 3 or later:** the
`[value track_id_retained]` global-by-name bug (used in /signature
query reply target routing) — same shape as the hallucinote_path bug
but lower-priority since /signature isn't called in the multi-analyzer
render path. Backlog candidate when /signature becomes load-bearing
for sidecar version-discovery.

## 2026-05-26 — Audio Analysis MVP, Chunk 2 sub-chunk 2B partial — in-Live recording-path verification

<!-- prawduct: chunks=2b-partial | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Sub-chunk 2B's recording-path half shipped. The HallucinoteAnalyzer
`.amxd` was extended in Max's GUI to the Chunk 2 contract, and the
transport-position-sync render was verified end-to-end against Live's
transport on a Hallucinote song.

**GO criterion met:** render window [4, 12] beats at 180 BPM produced
`/tmp/chunk2_dtest.wav` as FLOAT/stereo/44.1 kHz with duration
2.6703s vs expected 2.6667s — **+3.6ms / +0.31 audio buffer drift**,
far inside the spec's ±4 buffer tolerance. Peak -8.19 dBFS, clean
audio content from the source track's instrument. Transport-position-
sync delivered the architectural win pinned at Chunk 1 close: no more
MCP-latency padding around the recording window.

**M4L surface authored:** widened `Port` Live param to 11000-11400
(via Float + Unit Style = Int — Live's Int parameter cap is 256),
added `EmitPort` + `Emit` Live params, added four new OSC routes
(`/track_id` symbol retainer, `/start_at_beat` int, `/stop_at_beat`
int, `/signature/query` with explicit reply-args), built the
canonical `live.thisdevice → live.path live_set → live.observer`
transport observer with `property current_song_time` sent as
runtime message, replaced all `[value]` cold-inlet storage with
`[i]`/`[f]` (the `[value]` non-emit issue), wired `[t b b]` →
open + 1 → sfrecord cascade, gated via `has_path` flag, added
prev_beat reset on Arm rising edge.

**Five durable M4L learnings landed in learnings.md** — each was a
multi-hour in-Live discovery, codified so the next M4L author starts
from a better baseline:

- `[value]` doesn't emit on write — use `[i]` / `[f]` for cold-inlet
  storage. The `[value]` object stores writes silently; only banged
  reads emit. Trade-off: lose named-shared semantics for emit-on-write
  reliability.
- `live.toggle` emits int 0/1 directly — no `[== on]` shim needed
  (and adding it INVERTS the value because `==` coerces the symbol
  arg `on` to int 0).
- `live.observer` needs runtime `property <name>` message; the
  `@property` constructor attribute silently fails AND can poison
  the patcher's loadbang sequence. Outputs bare value (no
  `<prop> <val>` prefix), so `[route <prop>]` filters out everything
  if added downstream.
- M4L patcher editor and Live runtime conflict over `udpreceive` —
  close the patcher window (Cmd-W, not Cmd-Q) before runtime
  testing. Keep `Window → Max Console` open separately.

Plus the install bug fix at e388242 (which prevented this whole
debugging session from being even longer): the install skill was
copying the `m4l/` subdir into Remote Scripts in addition to the
proper Presets/Audio Effects/Max Audio Effect/ location, so Live's
browser indexed the analyzer twice and the user kept dragging the
stale Chunk 1 copy onto tracks while editing the Chunk 2 copy. Fix
landed in `install_paths.py` (added `m4l` to `REMOTE_SCRIPT_EXCLUDE_DIRS_ANY`)
+ install skill body update.

The authoring guide `AUTHORING-CHUNK-2B.md` was rewritten through
Section D (observer chain), Section E.2 (live.toggle directly; no
`[== on]`), new Section E.4 (prev_beat reset on Arm rising edge),
Section G preamble (close-the-editor workflow rule), and the
appendix traps table (six new rows for each discovered gotcha).

Python-side: 2103/2103 tests still passing, no regressions.

**Remaining for full Chunk 2 close:** Section F feature emitter
(audio tap → K-weighted LUFS + sample peak + low-mid band → 30 Hz
OSC frames to sidecar), in-Live master-strip analyzer load
(`master=True` path; Python side ready), multi-analyzer simultaneous
capture verification, PDC cross-correlation between track and master
WAVs, `/critic chunk`. The recording-path verification alone is the
hardest architectural piece — the rest is incremental in-Live
authoring + verification work.

## 2026-05-26 — Audio Analysis MVP, Chunk 2 sub-chunk 2A — Python deliverables for the capture pipeline

<!-- prawduct: chunks=2a | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Sub-chunk 2A of Chunk 2 closed with the full Python-side surface for
the audio-capture pipeline. M4L authoring + in-Live verification (sub-
chunk 2B) is the next deliverable; the split mirrors Chunk 1's per the
"Human-authoring boundaries split the chunk" learning.

What landed:

- **Master-strip device push** — `plan_push_devices`
  (`src/hallucinote/sync/push.py`) now walks `kind='master'` tracks and
  emits load + set-parameter ToolCalls addressed via `master=True`
  instead of `track_index`. The `ableton_device` action schema +
  `_resolve_parent` accept the new addressing uniformly across every
  device action. **Closes the P0 backlog entry "Master-strip device
  chains"** (open since 2026-05-17).
- **`hallucinote_mcp.analyzer` package** — `setup.ensure_analyzers_loaded`
  (idempotent silent sweep over audio tracks + returns + master,
  deterministic per-instance OSC port assignment, writes Port + EmitPort
  Live params on load), `osc.AnalyzerOSC` (OSC 1.0 string/int packer
  for `/path`, `/track_id`, `/start_at_beat`, `/stop_at_beat`),
  `sidecar.OSCSidecar` (lazy-spawned UDP receiver with per-`track_id`
  ring buffers, lenient frame parsing — malformed frames drop without
  killing the receiver).
- **`ableton_render` MCP tool** with two actions:
  `ensure_loaded` (silent sweep, returns layout) and `render`
  (orchestrates ensure-load → OSC delivery → batch arm → seek + play →
  poll transport → batch disarm → manifest write). Render handler is
  fully unit-tested via injected seams; status='ok' on clean exit,
  'incomplete' on transport timeout.
- **Install skill extension** — copies
  `HallucinoteAnalyzer.amxd` from the package into Live's
  `Presets/Audio Effects/Max Audio Effect/` during install, probes
  M4L runtime (returns `None` for MVP — Live edition isn't reliably
  detectable; skill asks the user).
- **Auto-load postlude** wired into `/song-new`,
  `/track-new-with-instrument`, and `/return-new` skill bodies so
  structural mutations keep analyzer placement in sync.
- **Spec extension** in `m4l/HallucinoteAnalyzer.amxd.spec.md`: full
  Chunk 2 surface documented (OSC feature emitter shape, transport-
  position observer behavior contract, signature OSC query rationale,
  widened `Port` range to 11000-11400 for the deterministic per-
  surface port allocation).
- **`.gitignore`** updates for `songs/*/captures/`, `.hallucinote/stems/`,
  `*.amxd~`.

Test impact: +66 unit tests across `analyzer/*`, `actions_render`,
`actions_device` (master-strip), `push_devices` (master-strip planner),
`install_paths` (analyzer copy + M4L probe), `install_skill_consistency`
(structural-skill postlude wiring). 2033 → 2099 passing.

## 2026-05-26 — Audio Analysis MVP, Chunk 1 — Plumbing proof-of-life shipped

<!-- prawduct: chunks=1 | status=shipped | release=v1.4.0 | scope=audio-analysis-mvp -->

Chunk 1 of the audio-analysis MVP closed with track-only proof-of-life
verified in Live: `HallucinoteAnalyzer.amxd` (Max for Live audio effect)
records a clean WAV under Remote Script control. The full Chunk 1 arc
landed in two passes: the Python-side deliverables (numpy/scipy/soundfile
deps, synthetic-stem fixtures, PDC alignment unit test, spec, throwaway
harness) landed 2026-05-23, and the binary `.amxd` authoring + in-Live
verification + close-out landed 2026-05-26.

In-Live verification surfaced three M4L-authoring traps now codified in
spec + learnings.md as durable rules:

1. **Live parameters are float/int/enum only** — strings need an
   out-of-band OSC channel. `output_path` cannot be a Live parameter;
   delivered via `/path` to `[udpreceive]`.
2. **Remote Script API uses short names** — `Parameter.name` returns the
   `parameter_shortname`, not the long name. Harness addresses `Arm` /
   `Port`, not `Record Arm` / `OSC Port`.
3. **`sfrecord~` uses bare integers** — `1` (start) / `0` (stop AND
   finalize). NOT `record 1` (= "record 1 ms" — produced 44-frame
   captures), NOT `stop` / `close` (rejected with "doesn't understand").

The MCP-latency-bounded recording window observed in Chunk 1 (~2 s wider
than transport play window due to ~700 ms per `set_parameter` round-trip)
pinned the **transport-position-driven, beat-based** recording boundary
design for Chunk 2. The patch will read Live's transport at signal rate
and start/stop `sfrecord~` at requested beat positions; arm parameter
becomes a gate, not a boundary definer. Sample-accurate, tempo-change-
immune, multi-analyzer-aligned for free.

Chunk 1 GO criteria explicitly tightened to track-only proof-of-life
scope (clean WAV, header finalized, format correct, signal reaches
`sfrecord~`). Strict-duration and track-vs-master PDC alignment deferred
to Chunk 2 (both require master-strip MCP support, a known Chunk 2
deliverable). Full test suite green: 2033 passed in 18.42 s.

## 2026-05-23 — Hygiene wave: P0 delete_notes + migrate tests + P1 JSONSchema enrichment + P3 fingerprint NUL-sniff

<!-- prawduct: chunks=hygiene | status=shipped | release=v1.4.0 | scope=mutator-event-shape+test-coverage+wire-schema-enrichment+fingerprint-binary-safety -->

Five backlog items closed in one feature branch (fix/hygiene-wave-p0-p1-p3),
each with tightly-scoped regression tests, accurate root-cause commit
messages, and same-PR backlog deletions per discipline rules #1 + #3.

**P0 `delete_notes` clip_id fix** (`b123e93`): `delete_notes` previously
emitted a single NOTES_DELETED event with `clip_id=None`, so
`_latest_actor_for(row_kind='clip')` — which scans `events.clip_id`
directly — missed the touch. A build-owned clip whose only LLM-touch
was delete_notes became falsely tombstone-eligible. Fix emits one event
per affected clip with `clip_id` set, symmetric with NOTE_UPDATED +
insert_notes so events.clip_id carries consistent semantics for every
clip-touching event. Single-clip path (the only shape today's
`sync/pull.py:2971` exercises) still emits one event; multi-clip path
yields per-clip events instead of one spanning many, also restoring
per-clip granularity on the events.clip_id column.

**P0 W8-B verification** (no code): verified the agent-side push/pull/
capture wrap-in-M.request item is already structurally satisfied by
W23-C — `push_execute.py:410` opens kind='push', `pull_cli.py:161+277`
open kind='pull', MCP dispatcher's `auto_request` opens kind='mutate',
and `/song-snapshot` doesn't mutate the DB (the snapshot file IS the
deliverable). Entry deleted from backlog as stale.

**P0 `tools/migrate_arrangement_clip.py` test coverage** (`6369c21`):
401-line synthetic-fixture test file with 7 cases covering the one-shot
`arrangement` → `arrangement_clips` migration: table+index renames,
event-kind rename, JSON1 payload-key rewrite (with a sentinel kind
proving unrelated rows stay untouched and that no legacy
`arrangement_id` key survives anywhere), `ableton_links.db_kind` rename,
second-run no-op idempotency, both-tables-present refusal, and full
rollback on mid-transaction failure. Loader pattern mirrors
`test_migrate_returns_strip_prefix.py` (importlib.util + raw-SQL seeding
via the inverse rename).

**P1 JSONSchema enum/min/max/description enrichment** (`44955e1`):
ParamSpec already carries `enum` / `minimum` / `maximum` / `description`
(used by the dispatcher's teaching errors and `action='help'`), but
only the Python type flowed into FastMCP's pydantic-derived JSONSchema.
Agents saw `Optional[int]` for `cc_number` (no 0–127 bound),
`Optional[str]` for `target_kind` (no seven-value enum), and no
descriptions — pruning impossible calls happened only after the
dispatcher's error. New helper `_annotated_param_type` wraps each
param's Python type in `Annotated[Optional[T], Field(...)]` inside
`_register_tool`: `ge` / `le` for ranges, `description` passes through,
and `json_schema_extra={"enum": [...]}` for runtime-data enums.
Dispatch-time validation is unchanged; this widens the discovery surface
only. Test pins three representatives (bpm 20–999+description,
target_kind enum, cc_number 0–127 integer range).

**P3 `_FINGERPRINT_PATHS` binary-safety guard** (`49e546d`):
`_hash_file`'s CRLF→LF normalization is correct for the current
`_FINGERPRINT_PATHS` membership (every entry resolves to Python source),
but the invariant lived only in the docstring. A future contributor
adding a non-Python entry (JSON manifest with embedded CRLF, static
`.als` skeleton, `.so`) would have `b"\r\n"` substrings silently
corrupted by the replace. Fix sniffs the read bytes for a NUL byte: if
present (binary heuristic), skip the replace and hash byte-for-byte.
Python source has no NUL bytes, so the existing CRLF/LF cross-platform
stability path is unchanged for them. Test pins the new invariant —
two binary blobs differing only in a CRLF↔LF substitution must hash
differently.

Backlog scrub closes the five entries inline. `docs/v11-requirements.md`
F2 strike-through marks delete_notes events.clip_id as shipped (Critic
note from the bundle review). Settings.json banner refreshed from v1.4.0
to v1.5.0 alongside the post-sync state.

Test count: **2027 passing** (11 new tests this wave: 1 schema
enrichment, 1 fingerprint NUL-sniff, 2 delete_notes, 7 migrate). Both
cumulative-Critic and PR-review gates clean.

## 2026-05-22 — Arc 7-tail: enum envelopes + device-load hardening + W13-A fallback identity (E1+E2+E3)

<!-- prawduct: chunks=E1,E2,E3 | status=shipped | release=v1.4.0 | scope=enum-envelope-authoring+device-load-post-condition+w13a-fallback-identity -->

Three chunks bundled per the user's "one PR for the bundle" direction,
all empirically scoped from the 2026-05-22 Live-side probing session.
Empirical-Live round-trip verification for E1 and E3 is explicitly
deferred behind the MCP version-mismatch gate
(`project_mcp_reconnect_workflow`); each chunk's "Done when" leaves the
deferred verification line as `[ ]` rather than collapsing scope.

E1 closes the per-section enum-parameter envelope authoring gap. Schema
lift `device_parameters.value_items_json` carries enum cardinality at
`detail='full'`; pull captures it on the same path that already captured
numeric value; new mutator `M.create_enum_envelope` resolves enum-name
breakpoints via DB snapshot (primary) or `value_items` kwarg
escape-hatch; MCP `write_envelope` accepts `value_type='enum' |
'continuous'` (default continuous for back-compat) and mirrors
`set_parameter`'s enum-resolution path. `songs/sun-zone-done/` ships as
the empirical driver — Amp.Type Clean↔Heavy authored via the helper at
section boundaries (28 breakpoints across 8 sections, escape-hatch
`value_items` until a Live round-trip populates the snapshot).
Tree-wide doc sweep updated `song-authoring-conventions.md`,
`snapshot-schema.md`, `mcp-tool-design.md`, and the ableton-pull skill.

E2 closes the device-load post-condition false-positive surfaced in the
2026-05-22 probing pass: `ableton_device(action='load', kind='Drum
Rack')` onto a track ending with an Instrument Rack succeeded
semantically (chain ended `[1:DrumGroupDevice]`) but the handler raised
because the post-condition only checked chain-length growth. Fix lifts
the post-condition to three success shapes — chain grew (append, the
common case), chain length unchanged but class at exactly one position
changed (replace-in-place), or zero changes (still the silent-no-op
error) — and raises distinct `RuntimeError`s for multi-position-change
and chain-shrink. `_canonical_class_name(device)` factored so the
pre-load snapshot and the response's `loaded_class_name` use the same
`class_display_name || class_name || ""` rule. `_raise_silent_noop`
typed `NoReturn` so future refactors can't silently fall through.
Backlog refresh: Instrument Rack bare-name entry struck
(fixed-by-drift on Live 12.4); Drum Rack name-collision entry reframed
as per-machine library hazard.

E3 closes the W13-A v1.0 instrument fallback identity gap (cross-machine
plugin-load portability). Single new column `devices.browser_path_json`
carries the JSON-encoded browser path from root to loaded item — design
shift from the original two-column (manufacturer + pack_name) plan
since vendor/pack live at different depths across Live's browser tree
(third-party plugins 1-deep under `plug-ins`; Live packs 1-deep under
`packs`; Suite instruments 1-deep under `instruments`). `M.create_device`
accepts `browser_path: list[str] | None`, validates shape, JSON-encodes,
participates in idempotency tuple + DEVICE_CREATED event payload.
`replay_capture` reads the snapshot's `browser_path` key (pre-E3
snapshots land NULL — graceful degradation). MCP `load_handler`
accepts `browser_path` alongside `preset_uri`, tries URI first, on
URI-walk failure synthesizes a `preset_query` from
`path[0]`/`path[1:-1]`/`path[-1]` and reuses `_resolve_preset_query`
with its 0/multi-match teaching errors. Load response surfaces
`resolved_path` so capture flows can record the path automatically.
Push planner emits `browser_path` alongside `preset_uri` (not alongside
`preset_query`, which is itself the path-scoped selector — redundant
layering avoided).

Tests: +43 across the bundle (E1: +21, E2: +4, E3: +18). Suite:
1949 / 1949 passing in 14.82s (+45 from the 1904 baseline at the prior
Arc 7 polish PR). Three files intentionally left unstaged on the
branch (parked v1.5 framework WIP per
`project_prawduct_framework_authorship`): `.claude/settings.json`,
`.prawduct/critic-review.md`, `tools/product-hook`.

## 2026-05-22 — Arc 7: production polish (P1, P4, P5, P7) + Arc 2 / B5 (MCP auto-mutate)

<!-- prawduct: chunks=P1,P4,P5,P7,B5,backlog-scrub | status=shipped | release=v1.4.0 | scope=envelope-polish+nested-rack-tombstone+device-load-class+mutator-prefix-strip+mcp-auto-mutate -->

Arc 7 production-polish chunks bundled per the user's "one PR for
several fixes" direction; P2 / P3 / P6 collapsed to documentation-only
(P3 + P6 turned out to be already shipped; P2 deferred — needs Live
access for the enum-param investigation).

P1 closes the envelope WRITE polish backlog tail: `write_envelope_handler`
threads `note_duration` so the note_expression branch extends its last
step to note end (mirrors the W7-0 clip-scoped fix in note-LOCAL
coords); `sidechain_trigger` gains `envelope_start_beats` to floor the
first attack window at a section boundary (drops the redundant rest
anchor when clamping collapses onto the hit); falling-walking drops
its per-chorus `+ attack_beats` workaround; three `_emit_*_envelope`
emitters (mixer / send / device_parameter) consolidate into thin shells
around `_resolve_and_translate_to_session_clip` +
`_emit_session_clip_envelope_post_warnings` helpers.

P4 closes the last residual nested-rack gap: `_tombstone_untouched`'s
device_chain / device / device_parameter SELECTs now go through a
`WITH RECURSIVE` CTE (`_NESTED_RACK_CHAINS_CTE`) so chains parented by
`parent_rack_device_id` are enumerated alongside top-level chains.
Recursion terminates naturally; correct at any depth even though
capture/push still target one level.

P5 adds `loaded_class_name` to the `ableton_device(action='load')`
response (reads `class_display_name` with `class_name` fallback) so
callers can detect kind / preset_uri mismatches without a follow-up
device.list probe. The other P5 items (canonical-root walk,
Instrument Rack teaching error) were already shipped; master-strip
device push deferred to the existing backlog entry.

P7 enforces the W4-C `<letter>-` slot-prefix strip at the mutator
boundary (`M.create_return` / `M.update_return`); shared helper moved
to `hallucinote/return_naming.py` so capture.py and mutations.py both
import from there (no circular dep). Send warnings consolidated on the
`return_name` (DB-form) identity convention; `_track_kind` routed
through `Q.get_track` so the two single-row lookups share one query.

Arc 2 / B5 (committed earlier in the branch): MCP dispatcher
auto-opens a `M.request(kind='mutate')` around `ableton_annotation`
writes via `provenance.auto_request` so the handlers get `_request_id`
threaded automatically and emitted events carry full provenance.

Backlog scrub closed 7 entries shipped this PR per frontmatter rule 1
(W7-0 cumulative-Critic warning 4, W4-B W1, W4-B N3, W4-C N1, W4-C N2,
W10-F note 1, W12-A nested-rack tombstone, plus the stale W12-B pan
alias entry).

Suite: 1904/1904 passing (+31 from the 1873 baseline at Arc 6 tail).

## 2026-05-22 — Arc 6: song-author hygiene tail (H1–H5)

<!-- prawduct: chunks=H1,H2,H3,H4,H5,backlog-scrub | status=shipped | release=v1.4.0 | scope=song-author-hygiene+kit-strict+negative-beats-refusal -->

Five small chunks closing song-author-side polish items the cumulative
PR reviewer surfaced.

H1 switched `full-band-rock/build.py` and `solo-piano-ambient/build.py`
to `resolve_db_path()` — both had been pinned to bare
`Path(__file__).parent / "<slug>.db"`, so their DBs never picked up
D4's ALTER-add of `devices.class_name` and their regen'd
`REQUIREMENTS.md` kept emitting `DrumGroupDevice` / `Compressor2`
instead of post-D4 display names. With the change, per-branch DBs now
carry "Drum Rack" / "Glue Compressor" / "Instrument Rack" in
`devices.kind` and `REQUIREMENTS.md` regenerates cleanly.

H2 renamed `songs/falling-walking/tests/test_build.py` →
`tests/test_falling_walking_build.py` per the project's per-song
convention (every song's bootstrap test file must be unique under
`pytest -n auto --dist loadgroup`).

H3 added `Kit.assert_has(*, strict=True)` — refuses pre-capture state
explicitly so an empty-mappings kit doesn't silently pass via GM
fall-through and then surface the wrong-sound case on a later session
once `drum_pad_mappings` populates.

H4 added a `start_beats < 0` refusal to `_normalize_note` — the
chokepoint every note-write passes through. `apply_feel`'s math
stays correct (within-bar positions can shift below zero); the wire
layer rejects with a teaching error naming the most common cause (a
feel shift on bar-1's downbeat) and the two valid fixes.

H5 reworked `docs/song-authoring-conventions.md` "Per-part feel" rule
2 to make explicit that the generator API is dict-only (strings live
in the LLM prompt, resolve to dicts at compose time). `apply_feel`
now also raises `TypeError` for non-Mapping non-None inputs so the
documented contract is enforced at the boundary.

Backlog scrub closed 5 entries shipped this PR per frontmatter rule 1.

Suite: 1873/1873 passing (+3 from Arc 5 baseline, after Critic-driven fix-up tests).

## 2026-05-22 — Arc 5: iteration-loop polish (P1–P6)

<!-- prawduct: chunks=P1,P2,P3,P4,P5,P6 | status=shipped | release=v1.4.0 | scope=iteration-loop-polish+backlog-discipline -->

Six small chunks of polish closing iteration-loop pain points after
Arcs 2–4 shipped, plus structural backlog-accuracy discipline added
to the frontmatter of `backlog.md`.

P1 added `pull_cli execute --dry-run` (SAVEPOINT-wrapped preview;
applied diff surfaces without DB mutation). P2 wrote the
`/snapshot-bake-recent-changes` skill wrapping that engine. P3 shipped
the first `hallucinote://` templated resource —
`hallucinote://song/{slug}/annotations` — with parallel
`RESOURCE_TEMPLATE_URIS` + `registered_resource_template_uris`
plumbing. P4 added a Stop-hook-driven
`tools/stamp_evidence_sha.py` that auto-refreshes
`.test-evidence.json`'s `git_sha` so the recurring PR-review staleness
friction stops. P5 guarded `parse_path_shape` against empty interior
segments. P6 regenerated four songs' `REQUIREMENTS.md` post-D4 and
added a `_post_d4_note` to `device-params.json`.

P0 (backlog accuracy tooling) deferred to coordinate with in-flight
v1.5 framework WIP. P6c (Arc 3 e2e against real Live) deferred — needs
a known-good Live session.

In-session backlog scrub: frontmatter discipline rules added; three
verified-shipped entries removed (build.py song_id reuse, ableton_track
delete refuse, push-state coherence three-bug entry); seven entries
closed by the PR itself.

Both cumulative `/critic` and the independent `/pr` reviewer were
unable to run during the session due to Anthropic API 529s; merged
under explicit `.gates-waived` rationale with the commitment to
re-run when API recovers.

Suite: 1870/1870 passing.

## 2026-05-22 — Arc 4 / D4: structural display-name shift (delete _CLASS_TO_DISPLAY)

<!-- prawduct: chunks=D4-1,D4-2,D4-3,D4-4,D4-5,D4-6,D4-7 | status=shipped | release=v1.4.0 | scope=loader-display-name-convention -->

D4 verification surfaced a deeper problem than the spec called for.
Live merged Phaser+Flanger in 12.x and minted a new internal class
`PhaserNew` — the existing translation table (`_CLASS_TO_DISPLAY`)
had no entry, so the captured class name didn't round-trip. Empirical
investigation showed Live ALREADY exposes the right value natively
via `device.class_display_name` (already read by the `capabilities`
MCP action); the translation table has been reinventing a Live API
attribute the whole time.

Per user direction (no back-compat — no snapshots in the wild yet),
the table is eliminated entirely rather than patched with a
`PhaserNew` entry. Convention shift:

- **`devices.kind`** semantics flip from "Live's internal class
  name" to **"browser display name"** (= `device.class_display_name`).
  This is what the loader's kind-as-given walk matches against.
- New nullable **`devices.class_name`** column carries Live's
  internal class identifier (`Compressor2`, `PhaserNew`,
  `PluginDevice`, etc.). Informational + drives plugin
  classification (compat's third-party-plugin discriminator now
  reads class_name).
- MCP capture probes (`ableton_device(action='list')` / `info` /
  `get_device_chains`) gain a `class_display_name` field. Pull
  writes `class_display_name → kind`, `class_name → class_name`.
- Loader simplified to single kind-as-given match. `_kind_candidates`
  removed. `_CLASS_TO_DISPLAY`, `class_name_to_display`, and
  `strip_device_suffix` deleted from `device_names.py`. The W7-0
  cross-category rack-root protection (`browser_root_for_rack_kind`)
  stays — that's a separate concern, still load-bearing.

**Maintenance footprint dropped dramatically.** Pre-D4 the table
required an entry per Live built-in whose internal class differed
from its display name (~30 entries today; growing with each Live
release). Post-D4 there's nothing to maintain — Live's own API
provides the data.

Test fixtures + 5 captured_session.json files migrated to the new
convention. Action descriptions + agent-facing skill markdown updated
(loader contract docs that drive every `ableton_device(action='load')`
call were the cumulative Critic's BLOCKING finding — the test
explicitly pins kind='Compressor2' as a FAILURE post-D4, but the
description was still recommending that exact value to agents).
`docs/snapshot-schema.md` updated: `class` field convention shifted
to browser display name + `class_name` field added.

After merge: re-run `/ableton-mcp-install` to refresh the vendored
Remote Script (the `class_display_name` probe field needs to be in
Live's Python before pull benefits from it). The MCP server side
ships in the next pip release.

Suite: 1847 passing (was 1880 — 33 tests removed via deletion, no
behavior regressions; the functions they covered no longer exist).

## 2026-05-21 — Fix: annotation handler crashed Live's Remote Script load

<!-- prawduct: chunks=hotfix | status=shipped | release=v1.4.0 | scope=arc-2-live-verification-fallout -->

Arc 2's `ableton_annotation` handler imported `sqlite3` at module
load. Live 12.x's embedded Python ships without the `_sqlite3` C
extension, so the import raised `ModuleNotFoundError` and cascaded
up through `actions/__init__.py` to abort the entire Hallucinote
Control Surface load. Symptom: Live shows "Hallucinote" in the
Control Surface dropdown but the MCP bridge on `127.0.0.1:9878`
never starts and `ableton_session(action='info')` returns
"Connection refused." Diagnose via Live's `Log.txt` — the
`RemoteScriptError` traceback names the chain.

This is exactly the gap the Arc 2 cumulative-Critic backlog item
"`ableton_annotation` live verification end-to-end" predicted: unit
tests pass against the host Python (which has `sqlite3`), but the
embedded Python is the runtime that matters. The `sqlite3.Connection`
/ `sqlite3.Row` references in the handler were function-signature
annotations only, lazy strings under `from __future__ import
annotations` — so the import was dead at runtime and could be
removed without touching any logic. A load-bearing NB comment now
names the trap.

**Regression test (AST-based, host-Python-independent).** New
`hallucinote_mcp/tests/unit/test_remote_script_import_safety.py`
walks every action/handler/transitive top-level module in the
Remote Script load chain, collects module-load-time imports, and
refuses any in `_FORBIDDEN_TOP_LEVEL_STDLIB` (`sqlite3`, `_sqlite3`
today). Imports nested in function bodies / try/except guards /
conditionals don't count — those are deferred to invocation time,
which is the safe pattern. AST inspection rather than runtime import
because several Remote Script modules depend on `_Framework`
(Live-only) and would fail with the wrong error if imported
directly.

Suite: main 1878 passing (+2 for the new tests), MCP 697 passing.

After merge users must: quit Live (caches Control Surface modules
at startup), `/ableton-mcp-install` to refresh the vendored copy,
reopen Live, then `/mcp` to respawn the MCP subprocess.

## 2026-05-21 — Arc 3: Compose-time validation, round 2 (R-2 follow-ons)

<!-- prawduct: chunks=C1,C2,C3 | status=shipped | release=v1.4.0 | scope=compose-validation-r2-followons -->

R-2 (v1.0.1) shipped the pure module `compat.classify_preset_query`
and the `browser_dry_runs` map plumbing through `check_song`, but left
the CLI orchestration on the backlog. Arc 3 closes the loop the R-2
PR opened: in-process browser-search probing for compat check,
ergonomic path-shape sugar at the authoring boundary, and a one-shot
`pull_cli execute` that bakes mix-time tweaks back into the DB.

**C1 — `compat check --probe`.** New flag on the existing CLI. When
set, walks the song's DB for unique structurally-valid `preset_query`
specs, dedupes by `(root, pattern, path_prefix)`, issues
`ableton_browser(action='search', limit=2)` per unique key
in-process via the MCP TCP client, populates `browser_dry_runs` and
feeds it to `check_song`. Orthogonal to `--installed-plugins <path>` —
the two flags can be combined or used independently. Without
`--probe`, existing behavior preserved (preset_query devices land in
`preset_query_unverified`). `limit=2` because the report only buckets
0 / 1 / 2+ matches — walking past 2 is wasted work. Failed searches
raise `SystemExit` (a partial map would silently surface as a
false-clean report). The stale `--browser-dry-runs <file>` reference
in the `preset_query_unverified` detail message replaced with the
now-real `--probe` flag. 8 new tests.

**C2 — `preset_query` path-shape sugar.** New top-level module
`src/hallucinote/preset_query.py` ships `BROWSER_ROOTS` (single source
of truth replacing the duplicate constant in `compat.py`) +
`parse_path_shape("Drums/Kit-Core 909") → {root, pattern}` +
`normalize(dict | str | None)`. `M.create_device(preset_query=...)`
accepts either form; the DB always stores the canonical dict so
downstream consumers (push planner, compat.check_song, MCP loader)
see a single shape. Root segments are case-insensitive with
``" "`` ≡ ``"_"`` (`"Audio Effects/Hall"` ≡ `"audio_effects/Hall"`).
≥2 segments required; empty/whitespace pattern rejected; unknown root
rejected naming the valid set. ``mode``/``case_sensitive`` not
surfacable through path-shape — authors who need those keep using
the dict form. 20 new tests (parser + integration through
`create_device` for persistence/idempotency/error propagation).
Closes the v11 Arc 3 C2 open question on syntax — resolved in favor
of sugar-at-the-authoring-boundary with DB stored only as canonical
dict.

**C3 — `pull_cli execute` (in-process probe + apply).** The spec
framed this as "snapshot-bake-recent-changes" but the real round-trip
durability lives in the DB, not in `captured_session.json` —
`captured_session.json` only feeds `replay_capture(snap)` in
`build.py`, while push reads directly from the DB. So writing to the
DB is the right target. New `pull_cli execute <domain> <session_id>
--song <slug>` subcommand collapses the historical `plan → file →
execute probes → file → apply` dance into one in-process pass.
Generic across all 10 existing `_DOMAINS` (device-parameters is the
motivating use case; the surface is domain-agnostic). The "clear
diff" comes free via `ApplyResult.details`. Provenance envelope
identical to `_cmd_apply` — every `execute` opens a `kind='pull'`
request closed on success. 6 new tests.

Deferred for v1: dedicated `--dry-run` (a proper rollback wrapper
or in-memory DB clone is bigger than C3's spec calls for; backlog if
the workflow shows it's needed). Live verification deferred for both
`--probe` (C1) and `execute` (C3) — Live's Control Surface slot wasn't
enabled in this session; unit tests cover wire shapes against the
production schema. Skill markdown
(`/snapshot-bake-recent-changes`) deliberately not in this arc.

Suite: 1876/1876 passing (was 1842 — 34 net new tests).

## 2026-05-21 — Arc 2: Provenance + annotations MCP + dev-loop dispatcher bypass

<!-- prawduct: chunks=Q1,B3-resid,B2,B4,B5 | status=shipped | release=v1.4.0 | scope=provenance+annotations-mcp+dev-ergonomics -->

After a Wave 8 audit found that B1 had already shipped wholesale and
B3/B5 were partial, Arc 2 reduced to: Q1 (dev-loop dispatcher param)
+ B3-residual (three missing `requests` columns) + B2 (the agent-facing
annotations MCP surface W8-C didn't ship) + B4 (provenance wiring into
drivers) + B5 (defensive/generative `/song-context` modes).

**Q1 — `allow_version_mismatch` MCP envelope bypass.** The strict
server/Remote-Script version handshake is correct for production but
poisonous for the dev loop where every Python edit invalidates the
source fingerprint. New envelope-level `allow_version_mismatch: bool`
on `wire.Request` (default `False`) lets a caller opt into dispatching
across drift. On bypass+drift, the response carries a `warnings: [...]`
advisory naming the data-corruption risk and "development only" intent;
on bypass+no-drift it's a no-op. The existing version-mismatch error's
`hint` now mentions the escape hatch so agents discover it through the
error path itself (no docs lookup). Wired through `wire.Request`,
`wire.Response.warnings`, new `check_version_compat_with_override`
helper, FastMCP `_register_tool` synthetic-param injection, and
Remote Script `_handle_client`. Covered by unit + 3 end-to-end TCP
integration tests.

**B3 residual — provenance rationale columns on `requests`.** Adds
`prompt_text` (verbatim seed prompt), `parent_id` (self-FK so child
cycles chain to enclosing parents), and `metadata_json` (`{model,
git_sha, branch, hostname, ...}`) via the same idempotent
`_ensure_added_columns` path W8-B used. Existing rows get NULL on all
three; `create_request` + `M.request(...)` context manager accept the
new fields. Invalid `parent_id` raises (vs silent dangling FK).

**B2 — `ableton_annotation` MCP tool.** W8-C shipped the annotations
table + mutators + queries but no agent-facing surface — storage
without affordance. New unified tool wraps `M.add_annotation` /
`update_annotation` / `delete_annotation` / `Q.get_annotations_for_song`
/ `get_annotations_at_bar` via `add` / `list` / `get_at_bar` / `update`
/ `delete` actions. Handler resolves `song_slug` → per-song DB →
song row + 1-based `track_index` → `track_id`. Teaching errors on
unknown slug / unknown track / unknown annotation_id. Three-line
Python-via-Bash workaround replaced with a single MCP call so the
"annotate as you compose" habit becomes cheap. Resource
`hallucinote://annotations/<song_slug>` deferred (templated-resource
test plumbing; the `list` action covers the read use case).
Session-briefing wiring dropped per user direction (prawduct-framework
upstream territory).

**B4 — provenance wiring into drivers.** New `M.provenance_metadata()`
helper (best-effort git_sha/branch/hostname + caller extras).
`build_session` auto-captures via this helper AND accepts explicit
`prompt_text`/`parent_id`/`metadata` kwargs (caller-provided keys
override auto-captured). `push_execute` and `pull_cli` pass
`metadata={"driver": ..., "session_id": ..., +/- "domain": ...}` on
their `M.create_request` calls. Every compose / push / pull cycle
now carries platform context for free. Dispatcher-level auto-`mutate`
parent descoped — the MCP dispatcher has no DB awareness today and
threading one in is its own chunk.

**B5 — `/song-context --defensive` + `--generative`.** Adds two
retrieval orientations to the existing read-only markdown_refs surface.
`--defensive` reframes results as "items below MAY CONTRADICT your
plan" and flags rows whose snippet carries negation/constraint
language. `--generative` runs a second `Q.find_markdown_refs(tags=...)`
pass surfacing related-by-tag rows under a "Related context" heading.
Single additional SQL pass; semantic search is v1.2+. Skill name kept
as `/song-context` rather than renamed to `/decisions` — the corpus
spans decisions + annotations + structural-facts; "context" is broader
and matches object-action naming.

**Tests:** suite 1788 → 1841 (+53 new). Coverage spans wire shape +
4-state handshake bypass, FastMCP wrapper propagation, integration
TCP loop, request column round-trips + parent FK enforcement + ALTER
idempotency, annotation handlers (15 tests, end-to-end DB ops),
provenance metadata + build_session auto-capture, and defensive +
generative mode rendering + related-by-tags exclusion of seeds.

**Out of scope (carried to backlog):** dispatcher-level auto-`mutate`
parent (architectural), `hallucinote://annotations/<song_slug>`
templated resource (test plumbing), live verification of
`ableton_annotation` end-to-end against a real Live session (requires
`/ableton-mcp-install` + Live restart to materialize the new tool;
will fire on first compose-time use).


## 2026-05-21 — Arc 1: Drum Rack pad-mapping discovery + push-loop residuals

<!-- prawduct: chunks=A3,A1-resid,A2-resid,A5 | status=shipped | release=v1.1.0 | scope=push-reliability+drum-mapping -->

**A3 (substantive) — Drum Rack pad-mapping discovery.** Closes the
sun-zone-done Hot Rod Kit cautionary tale (metal sections clanging on
cowbell because GM-default ride at note 51 lands on Hot Rod's "Cowbell
Fenk Chick" pad) structurally:

- `Kit.pitch_of(canonical)` now **raises** with a teaching message
  when the kit has captured mappings, no canonical-name chain matches,
  AND the GM-default note is taken by a differently-named chain (the
  wrong-sound case). The empty-pad-slot fall-through stays warn+GM
  (harmless silence — GM-default points at a Live empty pad on this
  kit; nothing plays).
- `Kit.try_pitch_of(canonical) -> int | None` — additive safe
  resolver for callers that want to react to absence.
- `Kit.assert_has(*canonicals)` — bulk fail-fast at composition start.
- `push_cli execute` auto-populates `drum_pad_mappings` via a new
  `Q.get_linked_drum_racks_for_session` walker invoked after the
  devices-phase position (runs on both phase-OK and phase-SKIPPED so
  W20-A's idempotent re-pushes still trigger pad capture).
- `PhaseOutcome.pad_probes_ok` / `pad_probes_failed` surface in the
  state file only when probes actually fire (zero-ceremony for songs
  without Drum Racks).

**A1-resid — `_cmd_execute` coherence-check default hardening.** The
argparse mutex group is now `required` and includes a visible
`--no-coherence-check` opt-out. Pre-hardening the default behavior was
"silently skip the check when neither --probe nor --snapshot is set"
(the punk-fate state-drift safety net was opt-in by accident). Now the
default is "refuse with the three flag options enumerated."

**A2-resid — `browser.load_item` no-append error.** The handler's
`device.py::load_handler` no-append path now enumerates the parent's
existing chain (`[index:class_name, ...]`) so diagnose-and-fix doesn't
need a separate `ableton_device(list)` probe. The misleading
"instrument on a return" hint is preserved only for return-parent
calls (where it's actually structural).

**A5 — Partial-push recovery docs.** `push_cli execute` FAIL summary
now appends the verbatim recovery command (idempotent re-run after
fix). `.claude/skills/ableton-push/SKILL.md` gains a "Recovering from
partial push" subsection naming the structural pattern. No `--resume`
flag — W20-A's device-binding idempotency makes re-run the right
recovery path.

**Scope audit.** Initial Arc 1 plan covered seven chunks (A1-A7).
Code-level audit on 2026-05-21 confirmed five chunks already shipped
during v1.0.0: A1 via W18-A/B, A2 via W20-A, A4 in `create_song`'s
existing by-name lookup, A6 via W18-E, A7 in `ableton-push/SKILL.md:159`.
`docs/v11-requirements.md` Arc 1 + the build-plan carry the
audit-corrected scope; the backlog reconciliation marks Hot Rod Kit +
Drum Rack pad-mapping discovery + Push planner duplicates devices +
browser.load_item misleading hint (i) as RESOLVED with cross-references.

**Documentation.** `docs/song-authoring-conventions.md` gains a "Drum
kits: probe, don't assume" subsection. `docs/v11-requirements.md` Arc 1
section rewritten with audit-accurate scope.

Suite: main 1788 (+30) + MCP 664 (+3) = 2452 passing, 0 failed.


## 2026-05-20 — R-1 + R-2: cue idempotency, scaffold cleanup CLI, compat preset_query validation

<!-- prawduct: chunks=R-1,R-2 | status=shipped | release=v1.0.1 | scope=push-reliability+compose-time-validation -->

**R-1.1 — Cue push idempotency.** `ableton_arrangement(cue_create /
cue_create_batch)` gains `if_exists={"refuse", "skip"}`. Single-cue
default `"refuse"` preserves one-shot caller semantics; batch default
`"skip"` makes the planner's re-push idempotent (same-name same-position
no-ops with `skipped=true`; name mismatch refuses so rename intent goes
through `cue_rename` explicitly). `plan_push_cue_points` emits
`if_exists="skip"` so re-pushing the same DB into a Live set that
already has the cues no-ops the second time, instead of the prior
"halt with `a cue already exists at position_beats=0.0` on every cue."

**R-1.2 — Default-scaffold cleanup CLI.** `push_cli
cleanup-default-scaffold <session_id>` replaces the 6+ hand-issued
`ableton_track/return(action='delete')` calls W18-D's detect-only path
required. Pure planner `push.plan_cleanup_default_scaffold` refuses on
non-canonical unmatched parents (user must hand-resolve "another song's
tracks") and on "would empty Live tracks" (Live's ≥1-track constraint).
CLI dispatches deletes in descending index order in-process, then
re-runs `probe_and_link` to reconcile shifted indexes.
`.claude/skills/ableton-push/SKILL.md` Step 2a now points at the
subcommand.

**R-2.1 — Compose-time preset_query validation.**
`compat.classify_preset_query()` catches the two structural traps that
hit sun-zone-done at push time: `root` not in the loader-accepted enum
(typo `'effects'` vs `'audio_effects'` — 8 push failures) and non-list
`path_prefix` (3 failures). `check_song` accepts an optional
`browser_dry_runs` map; structurally-valid preset_queries classify as
`kind_unresolvable` (0 matches), `kind_ambiguous` (2+ matches),
`preset_query_unverified` (no dry-runs provided), or fall through to
the existing classifier on 1 match. `has_issues` flips True for every
new failure mode. Lock-test against `hallucinote_mcp.actions.browser._ROOTS`
prevents enum drift between the two sides. `format_requirements_md`
surfaces preset_query authoring issues in a dedicated section.

**R-2.2 — `docs/snapshot-schema.md` consolidated edit.** Documents:
loader's class-or-display-name dual accept (with the `Glue`/`Glue
Compressor` failing case named explicitly); `kind` field is
informational only (the loader ignores it); `preset_query.root` enum
enumerated inline with the `effects` vs `audio_effects` typo callout;
`path_prefix` must-be-list rule with wrong/right examples; "default
device vs named preset" subsection with both worked examples.

**Housekeeping.** `tests/unit/sync/test_pull.py::test_apply_device_parameters_property_round_trip`
gained `@settings(deadline=None)` — pre-existing hypothesis
`FlakyFailure` surfaced under parallel xdist contention; the test
checks correctness, not timing. Eight backlog items closed (cue
idempotency, default-scaffold cleanup, snapshot-schema gaps, `kind`
field documentation, default-vs-named preset doc, class-vs-display-name
doc, compat preset_query validation, first-push scaffold cleanup
offer) — `.prawduct/backlog.md` marked with RESOLVED / PARTIALLY
RESOLVED tags pointing at the chunk that closed them.

Suite: main 1758 (+31) + MCP 661 (+8) = 2419 passing, 0 failed.


## 2026-05-20 — v0.9.0 milestone: cross-machine portability + first tagged release

<!-- prawduct: chunks=W13-B,W13-C,hygiene | status=shipped | release=v0.9.0 | scope=cross-machine-portability+v0.9.0-cut -->

First user-facing tagged release. Bundles W13-B (missing-plugin detection
+ REQUIREMENTS.md + push preflight refuse-and-confirm), W13-C
(`docs/collaboration.md` walkthrough naming three portability cases), the
v0.9.0 CHANGELOG, and a hygiene sweep deleting four stale `.prawduct/`
investigation/triage artifacts (`bug-triage.md`, `bug-triage-wave2.md`,
`build-plan-wave-SD-paused.md`, `w12-a-investigation.md` — all covered
shipped work; git history preserves them).

New module `hallucinote.sync.compat` with five tagged status values
(`native`, `placeholder`, `third_party_ok`, `third_party_missing`,
`third_party_unverified`), nested-rack-recursive song walk, and a
`check | write-requirements` CLI surface. Push planner gains a clean
skip-with-warn for `kind='placeholder'` devices. The `/ableton-push`
skill adds Steps 0a (probe Live for installed plugins) and 0b (run
compat check, refuse-and-confirm on exit 1) before any push phase
fires. Express non-goal pinned in CHANGELOG: Hallucinote will never
substitute plugins or bundle audio.

W11 (inline `hallucinote://` DB read surface), W13-A (instrument
fallback identity — blocked on missing MCP `browser(search)` action),
and W16-A (assertions module) explicitly deferred to v1.0.

Suite 1510 → 1549 (+39 tests, ~11.8s). All four canary songs
(`falling-walking`, `full-band-rock`, `solo-piano-ambient`,
`odd-meter-experimental`) have REQUIREMENTS.md generated — all-native,
no install needed.

## 2026-05-17 — `arrangement` → `arrangement_clip` rename

DB table `arrangement` becomes `arrangement_clips`; indexes follow.
Mutators `add_arrangement` / `remove_arrangement` become
`add_arrangement_clip` / `remove_arrangement_clip` (kwarg
`arrangement_id` → `arrangement_clip_id`; payload key same). Event kinds
`ARRANGEMENT_ADDED` / `ARRANGEMENT_REMOVED` become
`ARRANGEMENT_CLIP_ADDED` / `ARRANGEMENT_CLIP_REMOVED` (constant + value
both move). Sync-layer link kind `"arrangement"` becomes
`"arrangement_clip"` in both `push._LINK_KINDS` and
`mutations.ABLETON_LINK_KINDS`; the planner key prefix on the
`batch_arrangement_layout` inner ops moves with it.

MCP-side `location='arrangement'` enum is **deliberately unchanged** —
it names Live's Arrangement *View*, per `docs/terminology.md`.

Latent footgun closed: `handlers/clip.py` `create_handler` for
`location='arrangement'` was returning `result["clip_index"] = i`, but
`_LINK_KINDS["arrangement_clip"]` expects `arrangement_clip_index`. The
mismatch silently dropped the `ableton_links` row the moment any
planner emitted `ableton_clip(create, location='arrangement', key='arrangement_clip:...')`.
No live consumer today (`batch_arrangement_layout`'s
`duplicate_to_arrangement_handler` already returned the right field) —
fix is forward-defensive.

Migration: `python tools/migrate_arrangement_clip.py <song.db>` —
single-transaction, idempotent. Renames table + 3 indexes, rewrites
`events.kind` (both kinds) + `events.payload_json.arrangement_id` →
`.arrangement_clip_id`, rewrites `ableton_links.db_kind`. Verified
round-trip against falling-walking's DB (32 placements + 32 events +
3 indexes rewritten; re-run is a clean no-op). The real
`songs/falling-walking/falling-walking.db` was migrated in place;
`build.py --reset` from the new schema is the alternative path.

Suite: 804/804 passing (no count change — pure refactor).

## 2026-05-17 — Install / uninstall skill cross-platform hardening

`hallucinote_mcp/src/hallucinote_mcp/install_paths.py` grew detection
helpers for User Library candidates (Windows OneDrive Documents
redirection, USERPROFILE divergence), installed Live versions, Live
process probing, `hallucinote-mcp` command resolution (PATH +
venv-bin/Scripts fallback, returning `(path, on_path)`), and MCP config
scanning across three scopes (project-local `.mcp.json`, global
top-level `~/.claude.json`, and the `projects.<cwd>.mcpServers` scope
that `claude mcp add` writes by default).

`python -m hallucinote_mcp.cli preflight` is a new CLI subcommand that
emits a JSON report consumed by both SKILL.md bodies — single source of
truth for install/uninstall detection. Both SKILL.md files rewritten to
drive off preflight: Claude Code now auto-detects Live state, User
Library location, installed Live versions, MCP config scope, and
malformed JSON instead of asking the user. Drift between SKILL.md copy
commands (rsync / robocopy / Copy-Item fallback) and `REMOTE_SCRIPT_EXCLUDE`
is now structurally enforced by `test_install_skill_consistency.py`.
