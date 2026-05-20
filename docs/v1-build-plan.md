# V1 Build Plan — Pre-Release Closeout

**Source.** Findings in `docs/pre-v1-walkthrough.md` (30 items, severity-ranked) + design discussion 2026-05-19.

**Release posture.** **Quality is the gate; there is no calendar.** v1 ships when a moderately sophisticated Claude Code + Ableton user can sit down and be productive *reliably*. Edge cases matter. The "ship if time" bucket is much smaller than typical because the bar is reliability, not feature count.

**Status of Wave 8 (in flight on `feat/wave-8-song-metadata`, separate branch).** Wave 8 (Song Metadata Layer — annotations + provenance via markdown corpus + FTS5 + events) closes walkthrough findings **#5** and **#6**. W8-A, W8-B, and W8-C shipped 2026-05-19 on `feat/wave-8-song-metadata` (commits c9fe09d / 3d5279d / 9dfc291 / 2a37560). W8-C's framework-coupled wiring (briefing surface + CLAUDE.md addendum) is descoped to backlog pending upstream sync. **No further W8 work in this plan.** Song-aware context in CLAUDE.md is folded into Wave 9's documentation.

**Branching.** Each wave gets its own feature branch off `develop`. Per project preferences gitflow + `PR creation: wait_for_user`.

---

## Architectural framing

Two decisions shape the whole plan; surface them up front so the rationale is visible from every wave.

### The DB is a materialized view of the event log

Per project memory `architecture_db`: state-store now, event-store eventually. The DB is the *cache* of replayed mutator events, not the source of truth. The event log is. The DB exists so reads are fast. When DB schema changes or corruption strikes, the canonical recovery is *replay from events*, not migration. This framing is what makes per-branch DB files cheap (they're just caches) and what makes the eventual event-store flip a small step rather than a rewrite.

### Option E — idempotent mutators — is the down-payment on the event-store flip

The single biggest decision in this plan: every mutator becomes idempotent ("create-or-update by entity identity"), enabling `build.py` to act as a state-converger rather than a state-creator. This buys two things simultaneously: (a) branch-switch staleness is structurally impossible (re-running build.py converges to current state, pulled edits in DB-only fields survive), and (b) the mutator surface starts to look like event-application — which is exactly what the event-store flip needs. **Wave 12-A is the load-bearing chunk.** If it slips, the cheap fallback is per-branch DB filenames alone (Option F) — solves branch-switch silently-stale but loses pulled edits on rebuild.

---

## Critic cadence rules

Per project memory `feedback_critic_cadence_for_small_chunks` and the locked-in policy "minimize Critic except at major milestones": **one Critic per wave, at PR time, covering everything in the wave as a unit.**

The only exception in v1: **W12-A** (idempotent mutators) gets its own mid-wave Critic because it's foundational enough to deserve independent eyes before the polish chunks land on top of it. Every other wave gets exactly one wave-end Critic.

Expected Critic invocations across v1: ~10 total (one per wave + one extra for W12-A). Compare to a per-chunk model which would have been ~20+.

Individual chunks below don't carry Critic marks; assume wave-end unless otherwise noted.

---

## Wave 0 — Reliability harness

**Wave goal.** Prove the v1 quality bar empirically, not just by checking feature boxes. Build 2-3 representative songs end-to-end through fresh-context agent sessions, log every paper cut, fix or file. This is the falling-walking-as-canary pattern, extended adversarially.

**Wave branch.** `feat/wave-0-reliability-harness`.

**Why first.** Wave 0 surfaces the actual gaps. Some Wave 1+ chunks will need adjustment based on what hurts in practice. Better to run the harness now than after building speculative fixes.

### W0-A — Pick + spec the canary songs

**Goal.** Choose 2-3 song shapes that stress different parts of the system, write a one-paragraph brief for each (genre / instrumentation / structure / specifically what it exercises).

**Investigate first.** What corners of the system are least-exercised by falling-walking? Candidate angles:
- **Solo piano ambient** — minimal tracks, long arrangement clips, slow envelope work, no drums. Exercises envelope authoring without trip-hop's groove crutch.
- **Full-band rock with vocals** — many tracks, audio + MIDI mix, third-party plugins (the case-B-missing path). Exercises Wave 13 directly.
- **Polyrhythmic / odd-meter experimental** — 5/4 or 7/8 sections, multiple simultaneous tempos via 1/64 grid encoding. Exercises VISION's "reach music Ableton wasn't built for" claim.

**Scope.** A brief per song in `docs/canary-songs/<slug>.md`. No code.

**Done when.** Briefs exist; user signs off on the 2-3 shapes.

### W0-B — Build each canary as a fresh-context agent run

**Goal.** Each canary song gets built by a fresh agent session (no carry-over context), following the README + skills as a moderately-sophisticated user would. Every friction, error, dead-end, and recovery is logged.

**Scope.** Per canary:
- A `Task` agent (fresh context) given only "build this song from the brief; surface every problem you hit" instruction.
- A running log written to `docs/canary-songs/<slug>-runbook.md`.
- The agent doesn't fix problems — it surfaces them and continues. Fixes happen in subsequent waves.

**Done when.** All canaries attempted. Runbooks complete (success OR documented dead-end with diagnosis).

### W0-C — Triage the findings

**Goal.** Each runbook entry classified: blocker (must fix before v1) / important (should fix) / paper cut (file in backlog).

**Scope.** A consolidated triage doc `docs/canary-songs/triage.md` that maps every finding to a wave / chunk in this plan, OR a new backlog entry. Reshape the rest of the plan based on what came out.

**Done when.** Every runbook finding has a destination. The build plan is updated to reflect surprises.

**PR:** one PR for all of W0 (briefs + runs + triage).

---

## Wave 9 — Song-new onboarding

**Wave goal.** Make "compose a new song from a prompt" work end-to-end. Closes findings **#0** (misleading exemplar), **#1** (no `/song-new`), **#2** (snapshot chicken-and-egg), **#10** (session_id bootstrap), **#15** (no compose MCP prompt). Subject to revision based on Wave 0 findings.

**Wave branch.** `feat/wave-9-new-song-onboarding`.

### W9-A — `/song-new <slug>` skill

**Goal.** Scaffolding skill that creates `songs/<slug>/` with build.py template, captured_session.json template, tests/ skeleton, W8-convention directories.

**Scope.**
- `.claude/skills/song-new/SKILL.md` — prompts for slug, title, tempo, signature, sections. Refuses on bad slug or existing path.
- `tools/scaffold_song.py` — parameterized filesystem work, unit-tested.
- Templates under `tools/templates/song/`: minimal `build.py.tmpl` (section markers, no inlined song-specific notes), generic `captured_session.json.tmpl` (4 MIDI tracks + 2 returns + master), `tests/test_build.py.tmpl` (shape-only assertions), `decisions/.gitkeep`, `annotations/.gitkeep`.
- One-line addendum at top of `songs/falling-walking/falling-walking.md` noting it's historical and not a template.
- CLAUDE.md addendum (was Wave 17): "If a song slug is mentioned, read `songs/<slug>/decisions/` and `songs/<slug>/annotations/` first."

**Done when.** Skill scaffolds a new song; `python3 songs/<slug>/build.py --reset` succeeds; test_build.py passes.

### W9-B — Auto-bootstrap `session_id` in `/ableton-push`

**Goal.** First-time push works without prior knowledge of `ableton_sessions`.

**Scope.**
- `--auto-session` flag on `push_cli probe-and-link`: if no session exists, create one named `<slug>-<timestamp>` or `--session-name`, print id, proceed.
- `/ableton-push` skill calls with `--auto-session` after user confirmation ("No session bound to this Live set yet — create one now? [Y/n]").
- Tests: idempotency on re-run, name-conflict handling.

**Done when.** First-time push works.

### W9-C — Orchestration content in `/song-new` *(was: `start_new_song` MCP prompt)*

**Goal.** Canonical scaffold → musical specification → first push orchestration.

**Scope.**
- Originally specced as a `start_new_song` MCP prompt. **Migrated to skill in v0.9** because MCP prompts are not assistant-callable in Claude Code (they surface only as user-facing slash commands). The orchestration content folded into `.claude/skills/song-new/SKILL.md` — same workflow steps, but reachable by the agent without user mediation.

**Done when.** `/song-new` orchestrates the full flow; sibling workflow skills (`/song-pick-instruments`, etc.) handle the post-scaffold steps.

**PR:** W9-A solo; W9-B + W9-C bundled.

---

## Wave 10 — Push/pull robustness + UX

**Wave goal.** Close findings **#13** (push idempotency), **#14** (pull progress), **#16** (UUID-rotation warning), **#21** (Live UI quirks). All in v1 given the reliability gate.

**Wave branch.** `feat/wave-10-sync-ux`.

### W10-A — Push idempotency: arrangement phase

**Goal.** Verify whether re-push duplicates arrangement clips. Fix if so. Walkthrough flagged this **uncertain** — investigation first.

**Investigate first.**
- Read `src/hallucinote/sync/push.py` arrangement-phase emitter + apply layer's `arrangement_clip:<id>` handling.
- Determine current behavior empirically (unit test against pre-populated `ableton_links`).

**Scope.**
- Unit test: `plan_push_arrangement` emits zero calls for already-linked rows.
- Real-Live smoke test at `tests/integration/test_live_smoke.md` slot S-2.
- Fix planner if needed.

**Done when.** Test exists + passes + matches Live behavior.

### W10-B — Post-push UX message (Live UI quirks)

**Goal.** Proactively flag the two Live 12.4 quirks (mixer-column-hidden, envelope-dropdown-hidden) post-push.

**Scope.** Move the existing skill-body verbiage into the user-facing final report.

**Done when.** Skill emits the notice.

### W10-C — Pull: UUID-rotation warning

**Goal.** When `clip-notes` pull detects pitch/duration-matched delete+insert pairs (likely moved notes), warn with count + one-line explanation.

**Scope.** New warning in pull `details`; synthetic-pull test.

**Done when.** Warning surfaces; test asserts it.

### W10-D — Pull progress indicators

**Goal.** Per-domain progress lines during `everything` pull ("domain 3/9: devices").

**Scope.** `/ableton-pull` skill output only.

**Done when.** Progress visible on a real-Live pull.

**PR:** W10-A solo; W10-B + W10-C + W10-D bundled as "sync UX polish."

---

## Wave 11 — Inline iteration: DB read surface

**Wave goal.** Close finding **#12**. Reading the DB conversationally shouldn't require `python3 -c "..."` improvisation.

**Wave branch.** `feat/wave-11-db-read-surface`.

### W11-A — `hallucinote://` resources

**Investigate first.**
- Resources (URIs read implicitly, no turn cost) vs. a `hallucinote_query` MCP tool — which fits where?
- Where does this live? `hallucinote_mcp` does not currently import `hallucinote.db`. Adding it might cross a boundary the project preferences enforce — confirm with `boundary-patterns.md`.

**Scope (post-investigation).**
- Resources: `hallucinote://song/<slug>/tracks`, `.../sections`, `.../clip/<id>/notes`, `.../envelopes`.
- Possibly one query tool for parameterized retrieval.
- DB-path resolution via `songs/<slug>/<slug>.db` convention (today's path; post-Wave-12-A becomes per-branch).

**Done when.** A conversation can read note arrays from the DB without shelling out.

**PR:** W11-A solo.

---

## Wave 12 — State hygiene (Option E)

**Wave goal.** Make branch switches structurally safe. Close findings **#7** (silent staleness), **#17** (two-branch Frankenstein), **#18** (snapshot refresh), **#22** (MCP/Live drift). **The load-bearing chunk of v1.**

**Wave branch.** `feat/wave-12-state-hygiene`.

### W12-A — Idempotent mutators + per-branch DB filename (Option E)

**Goal.** Every mutator becomes idempotent. `build.py` becomes a state-converger. Branch-switch staleness becomes structurally impossible. **Down-payment on the event-store flip.**

**Investigate first.**
- Enumerate every mutator in `src/hallucinote/db/mutations.py`. For each: what's the entity identity? (E.g., `create_track(song_id, track_index)` — identity is `(song_id, track_index)`; the mutator becomes "upsert by identity, emit `TRACK_CREATED` only if new, `TRACK_UPDATED` if changed, no-op if identical.")
- Decide tombstone semantics: build.py removes a track from its output — does that delete the existing row, or does build.py only converge what it knows about? Lean: build.py emits a `BUILD_BEGIN` event + a manifest of entity identities it owns; at `BUILD_END`, any owned entity not seen is deleted. Pulled entities (different `actor`) are untouched.
- Decide event semantics: when a mutator is a no-op (state matches), does it emit nothing or a `NO_CHANGE` event? Lean: nothing (don't pollute the audit log with no-ops; mutator return signals to caller).
- Per-branch filename: `<slug>-<branch>.db` derived from `git branch --show-current`. Fallback to `<slug>.db` outside a git repo. Test the detached-HEAD case.

**Scope.**
- Mutator-by-mutator refactor: every `M.create_*` becomes `M.upsert_*` semantically, returning `(id, kind)` where `kind ∈ {created, updated, unchanged}`. Internal name can stay `create_*` for clarity; the *behavior* is what changes.
- New `M.begin_build(conn, song_id, manifest_owner) -> request_id` + `M.end_build(conn, request_id)` pair; entities created/updated/seen within the build are tagged with the request_id; entities owned by this owner and not touched are deleted.
- `init_db` reads current branch + opens `<slug>-<branch>.db`. Stale DBs from old branches sit gitignored, easy to `rm`.
- `build.py` template updated (W9-A coordination): wraps the build in `with M.build_session(conn, owner='build.py')`.
- Comprehensive tests: every mutator's idempotency property; build.py reruns converge; pulled edits in DB-only fields survive; branch switch picks up the right DB.

**Done when.** Re-running build.py against an existing DB produces zero net events for unchanged state. Branch switch works without `--reset` ceremony. Full test suite passes. **Critic: per-chunk** (heavy, foundational, deserves independent eyes).

### W12-B — Snapshot refresh workflow

**Goal.** `/song-snapshot <slug>` skill re-runs capture probes against current Live state, diffs vs. existing `captured_session.json`, shows the diff before writing.

**Scope.** Skill + tests against fixture snapshots.

**Done when.** Skill round-trips a Live drift back into the captured snapshot.

### W12-C — Push: warn on non-empty Live set

**Goal.** Promote `unmatched_live_tracks` / `unmatched_live_returns` from informational to YES/NO confirmation when non-empty.

**Scope.** Push skill orchestration change only.

**Done when.** Behaves on a real Live set with extra tracks.

### W12-D — MCP/Live drift visibility

**Goal.** Improve the version-handshake error message; add a one-line "MCP version: X | Remote Script version: Y | match: yes/no" to `hallucinote_mcp.cli preflight`.

**Scope.** Polish.

**Done when.** Drift surfaces clearly.

**PR:** W12-A solo (it's the big one); W12-B + W12-C + W12-D bundled as "state hygiene polish."

---

## Wave 13 — Cross-machine portability

**Wave goal.** Close findings **#9** (instrument identity), **#19** (cross-machine session_id), **#30** (collab story). **Express non-goal: distributing instruments or effects.** Missing-plugin path = tell Devon what to install. Period.

**Wave branch.** `feat/wave-13-portability`.

### W13-A — Instrument fallback identity (case A: same plugin, different catalog id)

**Goal.** Close finding **#9**. Same plugin on Devon's machine resolves to a different FileId; fall back to (class, display_name, manufacturer).

**Scope.**
- Capture extension: snapshot records `(class, display_name, manufacturer, pack_name, params_dialed)` for every browser-loaded device.
- Push: `ableton_device(action='load')` emitter tries FileId; on failure, falls back via `ableton_browser(action='search', name=display_name, class=...)`.
- Params re-applied after load via `set_parameter`.

**Done when.** A song with native Live instruments round-trips between two Live libraries with different scan orders.

### W13-B — Missing-plugin detection + REQUIREMENTS report (case B: plugin not installed)

**Goal.** Detect ahead of push when the consumer's Live install is missing required plugins/Packs/samples. Emit a clear shopping list. Refuse to push by default. **Do not substitute. Do not bundle.**

**Scope.**
- New CLI: `python -m hallucinote.sync.compat check <song-slug>` — probes Live's browser via MCP, walks the DB device-chain specs, classifies each as `ok` / `missing` / `unknown`. Outputs JSON + a Markdown summary.
- `/ableton-push` skill calls this as preflight between probe-and-link and phase 1. On missing items: prints the report; refuses to push unless `--allow-missing` or user confirms.
- On confirmed push with missing items: those tracks get device chains with `kind='placeholder'` rows carrying the original spec; Live-side those chains stay empty. Devon reads the placeholder spec from the DB, installs the missing plugins, re-pushes.
- Writes `songs/<slug>/REQUIREMENTS.md` listing what the consumer needs to install.

**Done when.** Pushing falling-walking against a Live install missing one of its instruments emits a clean report + REQUIREMENTS.md + refuses by default.

### W13-C — Collaboration walkthrough (doc)

**Goal.** Close findings **#19**, **#30**. Document the cross-machine flow honestly.

**Scope.**
- New doc `docs/collaboration.md`. Cover: cloning a song, session_id rebind, the three portability cases (A solved, B detect-and-shop, C explicit-non-goal), build.py + captured_session.json as the mergeable artifacts, the .db as per-branch cache.

**Done when.** Doc lands.

**PR:** W13-A + W13-B + W13-C bundled.

---

## Wave 14 — Compose flow polish

**Wave goal.** Close findings **#3** (generator audit, contingent) and **#4** (instrument picking).

**Wave branch.** `feat/wave-14-compose-flow`.

### W14-A — Browser-driven instrument picker

**Goal.** Close finding **#4**. After scaffolding, before first push, propose instrument choices per track via `ableton_browser`.

**Scope.**
- Originally specced as a `pick_instruments_for_song` MCP prompt. **Migrated to skill in v0.9** (`.claude/skills/song-pick-instruments/`) because MCP prompts are not assistant-callable in Claude Code.
- The skill takes `<tracks-csv>`, optional `<portability>` (`strict` / `relaxed` / `unrestricted`), and optional `<style-hint>`. It reads `ableton://browser/instruments` (and `ableton://plugins/installed` in non-strict modes), proposes per-track matches with rationale, confirms with the user, then loads via `ableton_device(action='load')`.
- `portability=strict` = native Live only (guarantees round-trip). `relaxed` = native + common third-party. `unrestricted` = anything, with W13-B's REQUIREMENTS handling the consumer side.
- Composes with `/song-new`'s scaffold flow as the post-scaffold instrument-picking step.

**Done when.** Skill scaffolded; one smoke conversation works.

### W14-B — Generator library audit (CONTINGENT on Wave 0)

**Goal.** **Defer until Wave 0 surfaces a real gap.** Direction: generators are music-theory primitives, not genre kits; the LLM hand-rolling raw notes is 100% OK. If Wave 0's canary builds reveal *the same primitive being hand-rolled five times across five songs*, audit and add. Otherwise do nothing.

**Scope (only if triggered by Wave 0).**
- Audit existing generators for hidden falling-walking-overfit. If `tresillo_bass` or `chord_pad` bake assumptions that aren't pure music theory, refactor.
- Add the specific missing primitives Wave 0 surfaced. Each one named for its theory shape (voice leading, contrary motion, arpeggio pattern, scale-degree-aware melodic helper, etc.), not for any genre.

**Done when.** Wave 0 findings addressed OR explicitly punted to v1.1 with rationale.

**PR:** W14-A solo; W14-B (if it happens) solo.

---

## Wave 15 — Install + docs polish

**Wave goal.** Close findings **#11**, **#23-#29**. Reduce "install failed at step 2" exits.

**Wave branch.** `feat/wave-15-install-polish`.

### W15-A — README rewrite

**Goal.** Close findings **#11** (no troubleshooting), **#23** (`[dev]` jargon), **#25** (no Windows quick-start), **#27** (final message in MCP syntax).

**Scope.**
- Parallel macOS / Windows / Linux quick-start blocks.
- Reword `[dev]` extras justification in user terms.
- Annotated text (or screenshot) of the Ableton Preferences click.
- New "Troubleshooting" section: top 5 install/runtime failures + recovery.
- Install skill final message in English, not MCP syntax.

**Done when.** A clean-machine teammate completes setup using only the README.

### W15-B — Install skill polish

**Goal.** Close findings **#24** (Python version preflight), **#28** (post-install hand-off), plus cwd check.

**Scope.**
- Preflight: error clearly on Python < 3.10.
- Preflight: refuse if cwd isn't the cloned repo.
- Post-install message: "Try: 'load falling-walking into Live' or 'start a new song'."

**Done when.** Preflight catches both failure modes; final message is friendlier.

### W15-C — Linux User Library decision

**Goal.** Close finding **#26**. Either implement Linux candidates or document "Linux unsupported for v1."

**Investigate first.** Confirm whether anyone is actually trying to run Ableton on Linux (wine-based?). My lean: document as unsupported; file in backlog.

**Done when.** Decision made + documented.

### W15-D — Cue zoom hint

**Goal.** Close finding **#29**. One-line addition to push skill output: "Section cue points are at the top of arrangement view — zoom out to see them."

**Done when.** Line lands.

**PR:** W15-A solo (README rewrite is a big artifact); W15-B + W15-C + W15-D bundled.

---

## Wave 16 — Testability

**Wave goal.** Honor VISION's "songs are testable" promise. Close finding **#20**.

**Wave branch.** `feat/wave-16-assertions`.

### W16-A — `hallucinote.assertions` module

**Investigate first.** Audit falling-walking's existing tests + Wave 0's canary tests. Distill 5-7 reusable structural-assertion helpers — alignment, presence, range, voice-leading legality, harmonic conformance — that aren't genre-specific.

**Scope.**
- `src/hallucinote/assertions.py` with the distilled helpers.
- Refactor falling-walking's tests + canary tests to use them (dogfood).
- Document in README's testing section.

**Done when.** Falling-walking tests use the helpers; module has its own tests.

**PR:** W16-A solo.

---

## v1 release gate

**Everything below ships in v1** (no honest "ship if time" tier given the reliability gate):

- Wave 0 (all)
- Wave 9 (all)
- Wave 10 (all)
- Wave 11 (all)
- Wave 12 (all — W12-A is the biggest chunk)
- Wave 13 (A + B + C; no asset bundling)
- Wave 14-A (instrument picker)
- Wave 15 (all)
- Wave 16 (all)
- CLAUDE.md addendum for song context (folded into W9-A)

**Honest v1.1 (announce as "next"):**

- W14-B (generator expansion) — only if Wave 0 didn't trigger it
- Full Linux support
- Plugin version-mismatch handling (case C — Serum v1 vs v2 param map drift)
- The event-store flip itself (W12-A is the down-payment; the flip swaps the read-side primary)
- Time-travel debugging UI / queries against the event log
- Per-clip / per-track time-indexed projections for diff and review

---

## Sequencing

1. **Wave 0** first. The canaries probably reshape parts of the plan; better to find out now.
2. **Wave 12-A** second. It's the largest single chunk, foundational, and every later wave benefits from idempotent mutators (build.py templates in W9, push idempotency in W10, DB read surface in W11 all simplify). Doing it early avoids retrofit.
3. **Wave 9** (song-new onboarding) after W12-A — the build.py template can be written against the new idempotent semantics.
4. **Waves 10, 11, 12-B/C/D in parallel** — focused, independent, can run on independent branches.
5. **Wave 13** after Waves 9 + 10 — depends on the snapshot extensions from W12-B.
6. **Wave 14-A** after Wave 9 — natural extension of the compose flow.
7. **Wave 15** can land any time — pure docs/polish, parallelizable with everything.
8. **Wave 16** late — best done after Wave 0's canaries give it real assertions to consolidate.

Estimated chunks: ~22 (more if W14-B triggers, fewer if Wave 0 triages aggressively). Cadence: 1-3 substantive chunks per session; polish chunks bundle freely. No timeline target; we move at quality-permitting pace.

---

## Next action

When you sign off on this plan, I'll create `.prawduct/artifacts/build-plan.md` with the **Wave 0** scope expanded to the full chunk-spec shape (Investigate first / Scope / Done when / etc.), following the format of the shipped Wave 8 plan. Subsequent waves get their own `build-plan.md` per branch as we cut them.
