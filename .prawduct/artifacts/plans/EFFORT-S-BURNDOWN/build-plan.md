# EFFORT-S-BURNDOWN — Build Plan

**Goal:** in one `fix/` branch, burn down every `effort:S` item open on
`brookstalley/hallucinote` (30 at branch time, 2026-08-11).

**Branch:** `fix/effort-s-burndown`

## Requirements Confidence: **High** (for the buildable set) / **N/A** (for the deferred set)

Each item carries its own problem statement, fix sketch and verifiable signal in
its GitHub issue — this plan does not restate them. What this plan adds is the
**triage**: which of the 30 an agent can actually close on this branch, and an
explicit disposition for every one it cannot. Nothing is silently dropped.

Two items (#318, #225) ship with a decision the issue leaves open at implement
time; both branches are fully specified in the issue and the choice is recorded
in the chunk's Done-when. One item (#274) offers "code OR a decision-record" —
the choice is recorded the same way.

## Triage — all 30 items

**Buildable on this branch (18, incl. #256 re-triaged in):** 447, 445, 327, 326,
320, 318, 317, 316, 315, 314, 303, 264, 263, 274, 223, 225, 236, 256

**Buildable but needs in-branch scoping first (2):** 233, 248

**Re-triaged mid-branch (1):** **#252** moved to non-buildable. The scenario
harness needs two INDEPENDENT subagents (a persona kept blind to the rubric,
and a judge); this session may not spawn them, and the only alternative —
playing all three roles itself — destroys the independence the harness exists
for. A canonical result recorded that way would be worse than a stale one
because it would look fresh. Disposition comment posted.

**Blocked on upstream work that has not shipped (2, was 3 — #256 left this
bucket)** — each verified
against the CODE, not the issue text, after #256 proved that distinction matters;
each gets a disposition comment naming its blocker:
- **#268** envelope: mixer envelopes on audio *session* clips — gated on
  **CLP-AUD2**. Verified: `sync/push/clips.py:51` refuses `kind='audio'` clips
  outright, so an audio session clip cannot reach Live at all; deleting the
  `refused_audio` route would emit a wire call targeting a clip that does not
  exist.
- **#256** — **RE-TRIAGED AND BUILT (2026-08-11).** Originally filed here as
  gated, and that was my error: I re-confirmed the gate from the issue's own
  text instead of checking the tree. `_extract_song_structure` reads **DB
  queries**, not Live probes, and `device_chains` has been a recursive tree
  since DEEP-RACK-ADDR. The gate had lifted; the extract now flattens nested
  racks to arbitrary depth. **Lesson worth keeping: a "blocked" label ages, and
  re-confirming it from the item's own body reproduces the original assumption
  rather than testing it.**
- **#255** device: extract the shared plugin-discriminator — gated on a
  **vendored-package capability that does not exist yet** (an id, `W11-A`, was
  cited here and resolves to nothing a future session can look up, so the
  blocker is stated in its own words instead — Critic R-23).
  Verified, and the reason is sharper than "the package hasn't landed": the
  duplication is **cross-process**. `handlers/device.py` runs inside Live's
  Remote Script, whose vendored env has no `hallucinote` at all, so it cannot
  import a shared module from `src/` under any arrangement — not even a
  stdlib-only leaf. Sharing needs a package vendored beside the Remote Script
  and imported by it — that mechanism is what has to be built first. The
  lock-test pins the copies in sync meanwhile, so there is
  duplication but no drift risk.

**Needs the user's ears, a second human, or a live Ableton probe (6)** — not
agent-buildable by construction; each gets a disposition comment:
- **#279** listening day (owner's ears — the item says so in its own body)
- **#242** melody by-ear calibration locks (same listening day)
- **#227** timbre/stereo threshold calibration (needs a render-jitter study in Live)
- **#305** forkability experiment (needs a second human on a second machine)
- **#311** relax quit-before-vendor (needs a macOS file-lock probe with Live running)
- **#281** probe Live 12.5+ pitch-bend/CC envelope support (needs Live 12.5+)

**Owner product decision (1):**
- **#308** polytempo in the schema vs. amending VISION.md — the item states
  outright that this is "a creative lock-in only the user can make — the agent
  flags it, never decides it." Left for the owner; the flag is re-raised.

## Work classification

Debt paydown, wide but shallow. Chunked by **blast radius**, not by issue
number, so each Critic pass sees one coherent surface. Docs/artifact chunks and
code chunks are kept apart so a doc-only chunk stays cheap.

---

## Chunk 1 — the PR #213 deferred-warning cluster (docs, skill, docstring)

Closes **#318, #315, #314, #316, #317**. These five were all deferred out of the
same PR #213 Critic review and touch the same story (the BAK-7D2V snapshot
durability contract). #318 decides `restamp`'s fate and #315 documents whatever
#318 leaves standing, so they must land together.

- **Type:** docs + one CLI surface decision
- **Critic mode:** chunk
- **Done when:**
  1. **#318 decided and executed.** Either `restamp` is deleted (subcommand +
     `capture.restamp_captured_at` + its tests) or it is kept and listed in
     `docs/snapshot-schema.md`'s `StaleSnapshotError` exits with its safety
     fence. The third state (present, unreferenced, undocumented) is gone.
  2. **#315** `capture_cli`'s module docstring enumerates every subcommand the
     parser registers, and a unit test asserts that set equality so it cannot
     drift again.
  3. **#314** in `skills/song-snapshot/SKILL.md`, the empty-diff `capture merge`
     fence sits *below* its trigger condition and yes/no consent prompt;
     `tests/unit/test_song_snapshot_empty_diff_bake.py` still passes.
  4. **#316** `boundary-patterns.md`'s Pull Planner section documents the
     two-channel contract (stdout JSON / stderr contract text the consumer MUST
     relay), stated as a consumer requirement and carried into the section's
     "When changing this surface" bullets.
  5. **#317** the BAK-7D2V closure note describes the shipped empty-diff **bake**
     (not the superseded re-stamp) and its check range matches the numbered
     checks in `.prawduct/operator-verification.md` — corrected on **closed
     issue #337**, NOT in `.prawduct/backlog.md`.
     **Resolved tension:** the issue (filed 2026-07-20) names the backlog file,
     but the 2026-08-10 cutover froze that file as the migration's source corpus
     under an explicit "preserve it verbatim" — it is what `verify-migration`
     and rollback read. The note migrated verbatim into #337, so #337 is the
     record a future scrub trusts and the frozen copy stays wrong as history.
     A grep of `.prawduct/backlog.md` will therefore still match the old text;
     that is the intended end state, not an undelivered item.

## Chunk 2 — stale citations + waiver hygiene

Closes **#445, #447, #320**. All three are "the tree says something that is no
longer true", spread across source comments, pragmas and a governing artifact.

- **Type:** chore
- **Critic mode:** chunk
- **Done when:**
  1. **#445** `git grep -n "backlog\.md" -- "*.py"` returns nothing outside
     `.prawduct/`; the user-facing MCP error string at `clip.py:358` no longer
     names any tracker; the quantize/groove comment no longer cites dropped
     GEN-2T8M.
  2. **#447** `git grep -n 'ok-broad-except' -- '*.py'` returns 0, and no
     place that INSTRUCTS the spelling still teaches it (`CONTRIBUTING.md`,
     `project-state.yaml`, `project-preferences.md`). Stated relationally
     rather than as a tree-wide grep: `.prawduct/` records legitimately carry
     the retired form as append-only history, so a literal tree-wide grep can
     never return 0 and an agent chasing it would edit the change-log. A
     sweep that stops at one file extension leaves the retired form being taught
     to the next contributor. Each of the 21 rewritten code sites carries a
     reason **specific to that catch**. A blanket reason string is a failure of
     this item, not a completion of it — any catch whose reason cannot be written
     honestly gets narrowed instead.
  3. **#320** every `songs/` path in `project-preferences.md` describes a
     workspace-relative location or is explicitly scoped to the `examples/`
     bounded exception (`examples/hallucinote.toml` has landed); no example
     command references a song absent from this repo.

## Chunk 3 — path resolution + compat-gate correctness

Closes **#327, #326**. Two real bugs where a check disagrees with the thing it
checks. They live in `src/hallucinote/sync/compat.py` and
`src/hallucinote/db/connection.py`, and both need regression tests.

- **Type:** bugfix
- **Critic mode:** chunk
- **Done when:**
  1. **#327** with a song dir in repo A on branch `main` and the process cwd in
     repo B on branch `feat/x`, `resolve_db_path(slug, root=<songs-root>)`
     returns `<song_dir>/<slug>-main.db`; `resolve_db_path(slug)` and
     `resolve_db_path(slug, root=...)` agree on the filename for the same song;
     a test pins the two-repo case. The DB-filename remap is called out in the
     change-log as a resolution-semantics change, not a pure bugfix.
  2. **#326** `_dry_run_key` includes `mode` and `case_sensitive`, and
     `_probe_browser_dry_runs` passes both into the browser search params, so the
     probe uses the matcher the loader will. A genuinely ambiguous substring
     query still reports `kind_ambiguous` — the fix must not become a rubber
     stamp. Tests pin both directions.

## Chunk 4 — push/capture robustness

Closes **#225, #264**. Both are push-path defects found in dogfood.

- **Type:** bugfix
- **Critic mode:** chunk
- **Done when:**
  1. **#225** a `set_chain_property` write against a disabled/locked chain-mixer
     parameter no longer manufactures a permanent phase halt. The fix option is
     chosen and recorded in the chunk close (capture-side `is_enabled`,
     planner-side pre-probe, or executor-side warning); a regression test pins
     the round-trip (capture → replay → push of an unchanged set is a clean
     no-op run).
     **Amended mid-branch (Critic R-19):** the option shipped is the
     **capture-side** one, pinned by `tests/unit/capture/test_chunk_c_chains.py
     ::test_disabled_chain_property_is_tolerated`. Recorded here because this
     is where "close the 20 issues at merge" sends a reader.
  2. **#264** spurious-clip detection no longer relies on start-time alone, so a
     pre-existing clip sitting at exactly `dest_beats + source.length` cannot
     mask a new spurious clip. A test seeds that collision.
     **Extended mid-branch (Critic R-2):** counting surplus at a start was only
     half of it — WHICH of the tied clips is surplus was still decided by Live's
     enumeration order, so the reverse ordering DELETED the operator's authored
     clip and kept the artifact, reported as a successful cleanup. Contested
     starts are now resolved by clip identity (start, length, name) and a start
     that will not resolve deletes nothing and reports through
     `spurious_clips_remaining`. A second test seeds the reversed ordering
     (verified red against the old walk).

## Chunk 5 — self-ignoring artifacts + capture audit event

Closes **#303, #263**. Both are additive writes on the tool-output path.

- **Type:** feature
- **Critic mode:** chunk
- **Done when:**
  1. **#303** the tool-output path self-ignores its own regenerable output — a
     pre-bootstrap workspace stops surfacing it as committable with no manual
     root-`.gitignore` edit.
     **Amended mid-branch (Critic R-7/R-19), on the same terms as #263 and
     #256 below.** As first written this read "the render/analyze path writes
     `analysis/.gitignore` (`*`) when it creates `analysis/`, and the
     notes-push + snapshot paths self-ignore their state/backup files".
     Neither half survived, and both reversals are deliberate:
     - **`analysis/` is NOT self-ignored.** Two records say analysis output is
       checked in, so a blanket `*` there would have hidden tracked work. The
       self-ignore went to `captures/` instead, scoped to the song's own root
       (see the owner-decision section below, and `server_side/analysis.py`'s
       comment).
     - **No snapshot path calls `self_ignore_files`.** `captured_session.json.bak`
       is covered incidentally, when a push happens to have run first
       (`paths.py`: "whichever runs first covers the rest").
     Amended here rather than left to the tick, because the plan sends a
     merge-time reader to this line to grade #303.
  2. **#263** `events.AUDIO_CAPTURED` exists and is emitted by the capture-success
     path with a `{captures_dir, manifest_seq, track_count}` payload, readable
     through the existing generic `queries.get_events_for_song`.
     **Scope note (Critic R-20):** the WRITE half is this item. No surface yet
     ASKS "when was this take captured" — `get_events_for_song` is the generic
     query the item named, not a dedicated reader. A consumer is follow-on work;
     recording it here so the Done-when is not read as claiming one exists.

## Chunk 6 — screen-recording grant + envelope confirmation lock

Closes **#223, #236**.

- **Type:** bugfix + test lock
- **Critic mode:** chunk
- **Done when:**
  1. **#223** `assert_capture_permission()` calls `CGRequestScreenCaptureAccess`
     on a denied preflight, so the OS prompt is actually raised. The existing
     actionable error path **survives**: on still-denied *or* newly-granted, the
     raised message still names the host app and states the relaunch
     requirement — the permission is read at process launch, so granting does not
     retroactively enable a running process. The fake CoreGraphics in
     `tests/unit/tools/test_capture_live_shot.py` covers denied→request→
     still-denied.
  2. **#236** a confirmation test pins that a `device_parameter` envelope on a
     sample-instrument MIDI track covered by its session clip routes to the
     sample-accurate `session_clip` path (it would fail if it regressed to the
     lossy perform path), plus the note-on ordering note (the breakpoint must sit
     at/just-before the trigger note-on so a phrase plays with its own window).
     The semantic-addressing half stays deferred on rule-of-three — that is the
     issue's own narrowing, restated here so it is not read as a silent drop.

## Chunk 7 — energy spectral correlate

Closes **#274**.

- **Type:** feature
- **Critic mode:** chunk
- **Done when:** either `MixReport.energy_realization.correlate_rho` carries a
  spectral correlate key computed over the windowed master and ranked by the same
  `realize_energy` Spearman path, **or** a decision record states loudness+density
  suffice with rationale. Whichever is chosen is recorded at chunk close.

## Chunk 8 — scoped-then-built: coherence guard, eval refresh, overview derivation

Closes **#248, #252, #233** — each needs a scoping call this chunk makes before
building. Any that the scoping shows is not S-sized on inspection gets re-sized
on the issue rather than half-built.

- **Type:** mixed
- **Critic mode:** chunk
- **Done when:**
  1. **#248** the taxonomy coherence pass is re-run against the siblings that
     have landed since 2026-06-03, and either records "no incoherence found" in
     `arrangement-model.md` or fixes what it finds.
  2. **#252** `canonical-priya.json` / `canonical-elena.json` are re-graded
     against the current two-sided melody rubric and canonicalized via
     `write_result(canonical=True)` with their transcripts — or, if the harness
     cannot be driven here, the blocker is recorded on the issue.
  3. **#233** the generate-vs-warn question is decided (**warn**, rationale in
     `overview_drift.py`'s module docstring) and built: a build-time staleness
     warning fires over BOTH derived surfaces — `<slug>.md`'s Structure table
     and `build.py`'s docstring section layout — when either diverges from the
     DB's sections.
     **Explicitly narrowed:** the warning is wired into the scaffold's
     `build.py` close, so it fires on every build of a song scaffolded from
     2026-08-11 onward. **Songs scaffolded BEFORE that do not get it
     automatically** — their `build.py` has no call — and there is no
     retrofit: rewriting an existing `build.py` is exactly the clobbering this
     item decided against. Those songs use `hallucinote overview-drift <slug>`,
     which checks the same two surfaces on demand. What would close the gap: a
     hook that fires for every song regardless of when it was scaffolded (the
     natural home is `/compose-review`, the reader-facing surface where a stale
     map actually costs something).

## Chunk 9 — dispositions for the 10 non-buildable items

No code. Every item in the blocked / needs-user / owner-decision buckets gets a
comment on its issue naming **why** it is not closed on this branch and **what
would unblock it**, so the burndown leaves no silent residue.

- **Type:** chore
- **Critic mode:** chunk
- **Done when:** each of #268, #255, #279, #242, #227, #305, #311, #281, #308
  carries a dated disposition comment — plus **#252**, re-triaged into this
  bucket mid-branch — and this plan's triage section matches what the comments
  say. **#256 left this roster** — re-examination showed it was
  buildable, so it got a "built" comment rather than a "not closed here" one.

---

## Status

- [x] Chunk 1 — PR #213 deferred-warning cluster (#318, #315, #314, #316, #317)
- [x] Chunk 2 — stale citations + waiver hygiene (#445, #447, #320)
- [x] Chunk 3 — path resolution + compat gate (#327, #326)
- [x] Chunk 4 — push/capture robustness (#225, #264)
- [x] Chunk 5 — self-ignoring artifacts + capture event (#303, #263)
- [x] Chunk 6 — screen-recording grant + envelope lock (#223, #236)
- [x] Chunk 7 — energy spectral correlate (#274)
- [x] Chunk 8 — coherence guard, eval refresh, overview derivation (#248, #252, #233)
- [x] Chunk 9 — dispositions for the 10 non-buildable items

**Context:** branch created from `develop` at `aa682e1`. Baseline 4986 passed /
2 skipped; final 5052 passed / 2 skipped. **All nine chunks shipped.**

Review history: a cumulative after chunks 1-3 (0 blocking), a cumulative after
chunks 4-9 (2 blocking, 9 warning, 16 note), then four `verify-resolutions`
rounds, the last two returning zero findings. Every blocking finding was fixed
and every warning/note dispositioned. Three of the fixes were themselves wrong
and were reverted on review evidence — the orphaned-sibling-DB warning (it
misfired on a routine `git switch -c`, and sat in a resolver called per MCP tool
call) and the `case_sensitive: null` tightening (it made the gate stricter than
the loader, reintroducing a variant of the bug #326 fixed). Both reverts are
better outcomes than the original fixes.

**Item-level outcome: 20 closed, 10 not closable here.** (#256 was re-triaged
into the built set mid-branch — see the triage section.) The 10 each carry a
dated disposition comment naming the blocker and what would unblock it.
**#281's disposition improved mid-branch**: its blocker was recorded as "needs
Live 12.5+", and checking rather than assuming showed **there is no Live 12.5** —
the newest release is 12.4 (2026-05-05). The version half of that item is now
answered and dated in `.prawduct/artifacts/research-envelope-lom-gaps.md`; only
the M4L-bridge probe remains.

**At merge:** close the 20 issues then, not before — they carry "closed by"
comments but closing them on an unmerged branch would misreport shipped state.

---

## Follow-on work, deliberately not absorbed on this branch

Recorded HERE rather than only in `.prawduct/.handoff-notes.md`, which is
gitignored and regenerated at `/clear` — a deferral that does not survive the
merge is a drop. Each was named by a Critic review on this branch and judged the
wrong thing to take at round 9+.

1. **`/song-snapshot` hard-codes `songs/<slug>/…` in ~16 places, and it is a real
   seam, not just prose.** Step 1 (`capture execute --song <slug>`) writes to
   `resolve_song_dir(slug)/captured_session.refresh.json`, while Step 2 diffs
   `songs/<slug>/captured_session.refresh.json`. Under the shipped `examples/`
   workspace (`layout="monorepo"`, `songs_root="."`) the diff reads a path the
   capture never wrote. Step 1 already prints the real path to stdout —
   consuming it closes this.
2. ~~**#225 is ticked with no in-plan amendment.**~~ **Discharged** at the
   develop-merge review round: Chunk 4's Done-when 1 now records the shipped
   capture-side option and its test, as #263 and #256 already did.
3. **#454 is NOT addressed here, despite sitting in a file this branch
   reworked.** Chunk 3 rewrote `compat.py`'s preset matcher for #326; #454 is a
   separate defect in `format_requirements_md`, which renders eight of the nine
   `DeviceStatus` buckets and omits `preset_query_unverified` entirely — so on
   the sole write path every structurally-valid `preset_query` device is named
   nowhere, under a heading asserting the song needs no installs. Re-verified
   at the develop-merge round (Critic R-24): still live, still unrelated to
   #326. Recorded so work shipping beside it does not read as having fixed it.
4. **The four swallow-with-log diagnostics are unasserted** —
   `overview_drift.warn_on_form_drift`, both `paths.self_ignore_*`, and
   `server._record_audio_capture_event`'s inner `except`. They were the entire
   deliverable of the "never swallow silently" norm fix, and
   `paths.self_ignore_files`' OSError branch has no test at all. The repo
   already has the idiom (`caplog.at_level` + substring) in
   `hallucinote_mcp/tests/unit/test_server.py`.

## An owner decision this branch surfaced but did not make

**Is `songs/<slug>/analysis/` checked in, or ignored?** The root `.gitignore`
("the small MixReport JSONs in analysis/ ARE checked in") and
`hallucinote.paths` (whose `portable_path` exists *because* they land in git)
say committed. `init_workspace.GITIGNORE_BLOCK`'s `**/analysis/` says otherwise,
and #303 called them noise. This branch briefly resolved it by writing a blanket
`*` there; that was reverted and the conflict is named in the code instead.
`captures/` keeps its self-ignore — nothing claims those are tracked.
