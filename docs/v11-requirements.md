# v1.1 Requirements — Hallucinote

**Status.** Planning document — not a build plan. Groups the medium-to-high-priority backlog items into bodies of work, names dependencies, and sketches sequencing. Build plans get generated arc-by-arc against this document.

**Source.** `.prawduct/backlog.md` (79 items as of 2026-05-21). PR #68 (R-1 + R-2) merged to develop, then shipped to main as v1.0.1 (PR #69) on 2026-05-21; back-merged to develop as PR #70. This document picks up everything *after* v1.0.1.

**Scope audit (2026-05-21).** Initial draft of this document overstated Arc 1's remaining work by ~70%. Code-level audit against current `src/hallucinote/sync/push.py` + `push_cli.py` confirms that A1 (coherence layer), A2 (W20-A device idempotency), A4 (`create_song` by-name reuse), A6 (W18-E last-element refuse-and-teach), and A7 (cleanup-default-scaffold push-first ordering) already shipped during v1.0.0. The audit-corrected Arc 1 is below; nothing else in this document changed.

**Release posture.** Same as v1.0 — quality is the gate, not a calendar. v1.1 ships when the recurring state-coherence failures stop biting, drum-based songs sound right on a fresh push, and the composer-intent layer (annotations + provenance) is wired through enough surfaces that future sessions arrive with context instead of cold.

**Naming caveat.** Per project memory `feedback_no_premature_version_bump`, this document stays labeled v1.1 *only as a planning bucket*. No `v1.1.0` tag, changelog entry, or README claim until v1.1 actually ships and the scope below is real.

---

## Architectural framing

Two decisions shape the arcs below; surface them up front so the rationale is visible from every arc.

### Push is probe-driven, not state-driven

v1 shipped three pieces of per-machine state (`/tmp/ableton-push-snapshot.json`, `ableton_sessions`, `ableton_links`) with independent invalidation rules and no shared coherence check. Three drift bugs in two days (sun-zone-done + punk-fate) are the same architectural smell expressed three ways, not three independent fixes. v1.1's Arc 1 introduces a coherence layer (cheap defense) and points at a one-canonical-entrypoint model (long-term shape).

### Composer intent is product data, not session memory

`requests` + `events` already audit *what* changed. The user-named gap is *why* — and the gap is wide enough that every new session starts cold against structural DB state, even though the structural data is rich. v1.1's Arc 2 extends `requests` for provenance (prompts, cycles, rationale) and adds an `annotations` table for the curated subset worth keeping forever. Both ship with retrieval surfaces (`/decisions`, session-briefing wiring) so the next session arrives with the song's working memory loaded.

---

## Resolved on the feat/r1-r2-push-cue-and-compat branch

PR #68 (not yet merged at planning time) closes:

- Cue phase idempotency (`if_exists={refuse,skip}` on `cue_create` / `cue_create_batch`)
- Default-scaffold cleanup CLI (`push_cli cleanup-default-scaffold`)
- First-push default-scaffold offer (subsumed by the CLI)
- Compat compose-time `preset_query` validation (`preset_query_invalid` / `kind_unresolvable` / `kind_ambiguous` / `preset_query_unverified` statuses)
- `docs/snapshot-schema.md` consolidated edit: `root` enum inline, `path_prefix` list-only, default-vs-preset section, class/display-name dual-accept, `kind` field documented as informational

Follow-ons live in Arc 3 (CLI orchestration of `browser_dry_runs`) and Arc 1 (`cleanup-default-scaffold` mid-loop failure recovery).

---

## Arc 1 — Drum mapping + push-loop residuals

**Originally framed as.** Push reliability + state coherence + drum mapping (seven chunks A1-A7).

**Audit revision (2026-05-21).** Five of the seven chunks are already in code from v1.0.0. The substantive remaining work is **A3 (drum pad mapping)** — the Hot Rod Kit cowbell-on-metal failure is still open. The other three residuals (A1-resid CLI hardening, A2-resid error message, A5 docs) are leaf-sized and bundle naturally with A3's PR.

### Already shipped (audit findings)

| Chunk | Status | Evidence |
|---|---|---|
| **A1** — coherence layer | Shipped (W18-A + W18-B) | `push.check_coherence` at `push.py:2757`; `_cmd_execute` invokes it under `--probe` / `--snapshot`; `probe_and_link` deletes stale links at `push.py:2542-2578`. |
| **A2** — devices-phase idempotency | Shipped (W20-A) | `_match_devices_for_linked_parents` at `push.py:2614` binds by `(parent_kind, parent_index, position, class_name)`. `_probe_live_devices_via_mcp` wired into `_cmd_probe_and_link --probe` at `push_cli.py:120`. |
| **A4** — stable `song_id` across `build.py` re-runs | Correct as written | `create_song` at `mutations.py:575-617` looks up by `name`, reuses the row, returns `MutatorResult(sid, 'unchanged')`. The original bug report wasn't reproducible from a code read; no canary required unless a real repro surfaces. |
| **A6** — last-element refuse-and-teach | Shipped (W18-E) | Both `track.py:187` (`len(song.tracks) <= 1`) and `scene.py:124` (`len(song.scenes) <= 1`) refuse with teaching errors pointing at the Live constraint. |
| **A7** — cleanup-default-scaffold ordering | Already named | `.claude/skills/ableton-push/SKILL.md:159` explains push-first-then-cleanup explicitly, citing the ≥1-track constraint as the rationale. R-1.2's CLI also refuses "would empty Live tracks" structurally. |

### Remaining Arc 1 work

- **A3 — Drum Rack pad-mapping discovery.** M1-C shipped the `pad_info` MCP action + `drum_pad_mappings` schema + `replace_drum_pad_mappings` mutator + `get_drum_pad_mappings` query. What's **missing**: the auto-population path (devices phase probes `pad_info` after a Drum Rack load and persists the result) and the `hallucinote.drums.resolve_pad(conn, device_id, canonical_name)` helper that lets `build.py` reference `KICK` / `SNARE` / `RIDE` / `CRASH` and resolves to whatever MIDI note the loaded kit actually maps. Closes the Hot Rod Kit cautionary tale (cowbell-on-metal). This is the substantive chunk.
- **A1-resid — `_cmd_execute` default-skip hardening.** Currently `push_cli execute` runs without `--probe` / `--snapshot` and skips the coherence check, with a docstring noting "legacy behavior; not recommended." Tighten the default: require `--probe` unless the caller explicitly opts into legacy behavior via `--no-coherence-check` (visible name; refuse-by-omission). Closes the architectural gap where the safety net is opt-in instead of opt-out.
- **A2-resid — `browser.load_item` no-append error.** `device.py:572-575` raises with the hint "the item may not be loadable on this parent (e.g. instrument on a return)" but the punk-fate `--reset`-then-repush repro hit this when the real cause was "device with matching class already present at this position." Surface what's already on the parent (list `class_name`s at the parent's positions) so diagnose-and-fix doesn't need a separate `ableton_device(action='list')` probe.
- **A5 — Partial-push recovery docs.** `.claude/skills/ableton-push/SKILL.md` gets a "Recovering from partial push" section naming the re-run-converges behavior (A2 idempotency is what makes this clean — already in place). `push_cli execute` FAIL summary prints the next command verbatim. No `--resume` flag — A2's idempotency makes re-run the right path.

**Sequencing within Arc 1.** A3 is the substantive chunk; do it first (tests + production code). A1-resid / A2-resid / A5 bundle as a small janitorial follow-up commit. Single cumulative Critic + PR at the end.

---

## Arc 2 — Provenance + annotations (user-flagged HIGH PRIORITY)

**Why parallel with Arc 1.** Independent code surface — DB schema + mutators + MCP, not push planner. Two senior backlog entries (annotations + provenance log) explicitly user-tagged HIGH PRIORITY.

**Note on Wave 8 (v1).** v1's Wave 8 shipped a markdown-corpus + FTS5 + events-backed annotation/decision layer (`feat/wave-8-song-metadata`, closed 2026-05-19). Arc 2 *extends* that surface, it does not duplicate it — the Provenance items below tighten the `requests` table's rationale-capture, and the Annotations items here add structured-in-DB annotations alongside the existing markdown-ref shape. Before chunking, read W8-A/B/C's shipped artifacts and decide for each item: "extend existing W8 surface" vs "add adjacent column/table." The split below is a starting frame, not a load-bearing commitment.

**Items:**

- **B1 — Annotations table.** Schema + mutators + queries + events. Polymorphic shape (`song_id` + nullable `track_id` + nullable `start_bar`/`end_bar` + `kind` enum {intent, stylistic, structure, reference, todo} + `body`). Three scoping levels (song / time / track) fall out of column nullability. Events: `ANNOTATION_ADDED` / `ANNOTATION_UPDATED` / `ANNOTATION_REMOVED`.
- **B2 — Annotations MCP surface + session-briefing wiring.** `ableton_annotation` tool (or action on `ableton_session`): `list`, `add`, `update`, `delete`, `get_at_bar`. Resource `hallucinote://annotations/<song_id>` for cheap full-song reads. Session-briefing hook surfaces "song annotations exist; read them before composing" when a file in `songs/<name>/` is touched.
- **B3 — Provenance extension on `requests`.** Add columns: `kind` (`compose` | `push` | `pull` | `capture` | `analyze` | `mutate`), `prompt_text`, `duration_ms`, `outcome` (`ok` | `partial` | `failed`), `parent_id` (self-FK), `metadata_json` (`{model, git_sha, branch, session_id, hostname}`). `M.open_request` / `M.close_request` / `M.request(...)` context-manager helper.
- **B4 — Wire provenance into push/pull/capture/compose drivers.** Push/pull skills open `kind='push'`/`kind='pull'` request before fan-out, close after `apply_*_results`. Capture opens `kind='capture'` with Live-set path + timestamp. Compose sessions open `kind='compose'` at session start with the user's initial prompt as `prompt_text`. MCP per-tool dispatcher auto-opens `kind='mutate'` if no parent exists (degraded but always-present provenance).
- **B5 — `/decisions [topic]` skill + `find_related_decisions` retrieval.** Analogous to `/learnings`. Surfaces decisions about the same element (defensive — challenge contradictions) AND related concepts (generative — propose connections the user hasn't drawn yet). Single SQL `LIKE` pass for v1.1; semantic search is a v1.2+ follow-on.

**Sequencing within Arc 2.** B1 + B3 in parallel (schema chunks, independent). B2 + B4 next (wiring; each depends on its own schema). B5 last (skill atop both).

**Out of Arc 2.** Transcript persistence (just the seed prompt — full conversation transcripts live in Claude Code's storage). Multi-user attribution. Cross-DB request merge. `M.promote_decision_to_annotation` (deferred — natural after both layers settle).

---

## Arc 3 — Compose-time validation, round 2 (R-2 follow-ons)

**Why.** R-2 landed the pure module (`compat.classify_preset_query`, `browser_dry_runs` map plumbing) but left the CLI orchestration on the backlog. Closes the loop the R-2 PR opens.

**Items:**

- **C1 — CLI orchestration of `browser_dry_runs`.** `push_cli check --probe` (or a `--with-browser-dry-runs` flag) invokes `ableton_browser(action='search')` for every device's `preset_query`, populates the dry-runs map, feeds it to `compat.check_song`. Closes the R-2 follow-on flagged in the partial-resolved backlog entries.
- **C2 — Compose-time built-in content selection by name.** Snapshot-author writes `preset_query: "Drums/Kit-Core 909"` (path-shaped); push planner resolves at push time via `ableton_browser(action='search')`. Strict-mode-only (loader refuses on unresolvable). Closes the FileId-portability gap for Live built-ins (Case A from W13-A's framing).
- **C3 — Manual MCP tweaks → `snapshot-bake-recent-changes`.** Lighter than `/song-snapshot` — capture *just* the parameters changed since last push, with a clear diff, into the snapshot. Closes the round-trip gap where mix-time `set_parameter` calls are lost on next full re-push.

**Sequencing.** C1 first (it's the smallest and closes the R-2 follow-on cleanly). C2 + C3 in parallel afterwards.

**Dependencies.** C2 depends on `ableton_browser(action='search')` (already shipped on develop).

---

## Arc 4 — Loader robustness (leaf MCP fixes)

**Why bundled.** Each is a small leaf fix; cumulative Critic at the arc boundary is cheaper than per-chunk.

**Items:**

- **D1 — Device kind canonical mapping + loader auto-fallback.** `ableton_device(action='load', kind='AnalogDevice')` is currently rejected even though `AnalogDevice` IS Live's internal `class_name`. Add a mapping table OR loader auto-fallback that retries with `name=class_name.removesuffix("Device")` if the `kind`-named browser node fails. Likely fits as a W13-A sub-task.
- **D2 — `Instrument Rack` bare-name load fix.** Empty Instrument Rack node isn't directly loadable by display name from the instrument root. Either special-case in the handler with the correct browser node lookup, or surface a teaching error pointing at the workaround (Cmd+G in Live's UI then probe via MCP).
- **D3 — Browser name-match wrong-class fix.** Loading `kind='Drum Rack'` empirically loaded an `InstrumentGroupDevice` because Live's browser had a saved Instrument Rack preset named "Drum Rack" that matched before the canonical empty Drum Rack node. Restrict the handler's display-name walk to nodes under the *canonical* category root.
- **D4 — Phaser/Flanger + Eq3/FilterEQ3 round-trip class_name preservation.** Live 12.x merged these into one browser node; load works for either source class, but re-capture may report the merged form rather than the original, breaking deterministic re-push. During real-Live validation: load via `kind='Flanger'`, re-capture, verify `class_name`. If not preserved, emit `preset_uri` for merged-display devices instead of relying on class-name resolution.
- **D5 — Cue-point auto-disambiguation for repeated section names.** When a song has cue-name duplicates (3 cues named `chorus`), emit `chorus 1` / `chorus 2` / `chorus 3` in the planner. Or document the convention so authors handle it on the build.py side.

---

## Arc 5 — Authoring API extensions

**Why.** Recurring authoring patterns that today require workarounds. Each is "documented recipe + small helper API."

**Items:**

- **E1 — Per-section parameter automation (esp. enum params like Amp.Type).** Channel-switched guitar amp design (Clean for reggae, Heavy for metal) needs Amp.Type automation per clip / per section. Two viable shapes to evaluate: (a) clip-level enum-param envelopes with discrete breakpoints, (b) two Amp devices in the chain + per-device on/off automation per section. Investigate, document the recipe, possibly add helper API. Recurring pattern (any genre-mashup song, verse/chorus tone differences).
- **E2 — `docs/song-authoring-conventions.md`: repeated-section pattern.** Schema permits both "one clip, N arrangement placements" and "N clips, N placements" for a section that repeats. Document the convention; mutation semantics of the former are undefined today.
- **E3 — `docs/snapshot-schema.md`: post-push + recapture canonical workflow.** Current text says what NOT to do (no hand-authoring URIs) but doesn't name the right workflow for "I want this specific drum kit." Add the canonical recipe.
- **E4 — `docs/song-authoring-conventions.md`: per-part-feel doc fix.** Rule 2 says `feel` accepts string OR dict; the generator API is dict-only. Clarify the string form is LLM-side intent; the value reaching the generator is always a dict.

---

## Arc 6 — Schema/mutator defensive fixes (cumulative janitorial chunk)

- **F1 — W4-C suffix-only invariant: structural enforcement.** Push the return-name slot-prefix strip into `M.create_return` / `M.update_return` so all callers benefit. Add schema-level `CHECK (name NOT GLOB '[A-Z]-*')`.
- **F2 — W12-A delete_notes events.clip_id edge case.** Emit one `NOTES_DELETED` event per affected clip with `clip_id` set (or extend the tombstone-actor lookup to scan `affected_clips`).
- **F3 — W7-A `_TRANSACTION_DEPTH` thread-safety.** Defensive `WeakKeyDictionary` or `threading.local` (not exercised today; defensive for future async/thread adoption).
- **F4 — `_serialize_markdown` list-item quoting defensive.** Quote (or reject) list items containing `,` / `[` / `]`.
- **F5 — `sidechain_trigger` principled section-clamp.** Add `envelope_start_beats` parameter (or floor `attack_start` to a configurable section start) so the generator clips the pre-attack window without shifting the hits themselves.
- **F6 — W4-B rule-of-three refactor.** Consolidate `_emit_mixer_envelope` / `_emit_send_envelope` / `_emit_device_parameter_envelope` into a single `_resolve_and_translate_to_session_clip` helper.

---

## Arc 7 — Tooling / hygiene (opportunistic; bundle when convenient)

- **G1 — `tests/test_build.py` → `tests/test_falling_walking_build.py`.** Filename collision risk under `pytest -n auto --dist loadgroup`.
- **G2 — Derived-views drift.** `views_enabled: true` but no tagged change-log entries and `tools/product-hook regen-views` errors on missing `lib/`. Likely belongs in upstream `prawduct` framework sync the user is authoring — coordinate before fixing locally.
- **G3 — Post-commit hook to bump `.prawduct/.test-evidence.json` `git_sha`.** Flagged by PR reviewer 6+ times. ~10 LoC in `tools/product-hook`.

---

## Dependencies & critical sequencing

```
Arc 1 (push coherence) ─┬─ A1 ──┬── A2 ─── A3 ─── A4..A7
                        │       (parallelizable after A1)
                        │
Arc 2 (provenance)    ──┤       (parallel with Arc 1 — different code surface)
                        │
Arc 3 (compose validation r2) ── needs R-2 merged (PR #68) ── C1 ── C2 ── C3
                        │
Arc 4 (loader robustness) ────── independent leaves; opportunistic ── runs throughout
Arc 5 (authoring API) ────────── depends on Arc 1 A3 for E1 drum-mapping recipe
Arc 6 (defensive) ────────────── opportunistic janitorial; cumulative
Arc 7 (tooling) ─────────────── opportunistic
```

**Suggested first three sessions after PR #68 merges:**

1. **Arc 1 head** — A1 (coherence layer) + A2 (devices idempotency). Closes the recurring state-drift bugs.
2. **Arc 2 head** — B1 + B3 (annotations + provenance schemas). User-flagged HIGH; independent of Arc 1.
3. **Arc 1 tail + Arc 3 head** — A3 (drum mapping) + C1 (browser_dry_runs CLI). Fixes drum songs + closes R-2 follow-on.

The remaining arcs are mostly mop-up that can interleave with creative work as that work surfaces specific pain.

---

## Out of v1.1 scope (named for clarity)

- `/song-import` skill (depends on first-time pull mode; future sibling to `/song-new`).
- Native Linux support (gated on Ableton shipping a Linux build).
- W13-B shared plugin-discriminator extraction (gated on W11-A `hallucinote-core` shared package).
- W13-A v1.0 instrument fallback identity Case A (v1.0 scope, not v1.1 — already deferred).
- Per-scene tempo/sig workaround for multi-bar gap (deferred until a song actually needs multi-bar tempo).
- Cross-song shared drum-kit mappings (post-M1-C v1.1; depends on Arc 1 A3 first).
- Recursive nested-nested rack chains.
- Master-strip device chains.
- Track routing (sidechain at the routing layer, parallel busses, input/output config).
- Group tracks.
- Audio clips: clip kind discriminator, file references, warp metadata.
- Session-view audio clip placement via browser-load workaround.
- Event replay function (`replay(events) → state`) and merge tooling — required for cross-DB merges; only useful after the event-store flip.
- Real-time concurrent editing / cloud DB migration.
- Audio render + analysis (`ableton_render` + `ableton_analysis`) — user-flagged "sooner than later, but not yet."
- Module-size watch (`mutations.py` 2117 LOC, `push.py` 1333 LOC, `pull.py` 1089 LOC) — revisit when suite exceeds ~30s or new contributor onboards.
- Envelope discovery on pull (envelopes authored only in Live; explodes the read surface).
- Wave 0 D1 v1.1: planner auto-partition envelopes across per-section session clips.
- Wave 0 D3 v1.1: mixer envelopes on audio tracks (gated on audio-clip DB model).

---

## Open questions for the user (not blocking; raise when starting each arc)

1. **Arc 1 A1 — coherence layer surface.** Per-symptom validators (refuse with teaching error) vs unified "refresh and reconcile" entrypoint that papers over staleness silently? Backlog recommends refuse-and-teach for v1.1; revisit at chunk time.
2. **Arc 2 — extend Wave 8 vs add adjacent shape.** Wave 8's markdown-corpus + FTS5 annotations layer is the existing shape. Decide per-chunk: extend that surface, or add a structured-in-DB annotations table alongside it.
3. **Arc 3 C2 — `preset_query` path-shape syntax.** `"Drums/Kit-Core 909"` vs `{root: "drums", pattern: "Kit-Core 909"}` vs both. Compat in R-2.1 already validates the structured form; C2 may want the path-shaped form as syntactic sugar.
4. **Arc 5 E1 — enum-param automation.** Two viable shapes; pick before designing the helper API.
