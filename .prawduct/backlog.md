# Backlog — Hallucinote

<!--
Last scrubbed: 2026-05-23 (hygiene wave fix/hygiene-wave-p0-p1-p3 close-out)
Last scrubbed by: Claude (hygiene wave: P0 + P1 + P3 sweep)

2026-05-23 pass removed: P0 W12-A `delete_notes` clip_id fix (shipped — one
NOTES_DELETED event per affected clip with clip_id set); P0 W8-B agent-side
M.request wraps (verified ALREADY shipped by W23-C — `push_execute.py:410`
opens kind='push', `pull_cli.py:161+277` open kind='pull', MCP dispatcher's
`auto_request` opens kind='mutate'; `/song-snapshot` doesn't mutate DB);
P0 `tools/migrate_arrangement_clip.py` tests (shipped — 7 cases including
JSON1 payload rewrite + both-tables-present refusal + rollback);
P1 JSONSchema enum/min/max/description enrichment (shipped via
`Annotated[Optional[T], Field(...)]` in `_register_tool`); P3
`_FINGERPRINT_PATHS` binary-safety guard (shipped — NUL-byte sniff skips
CRLF→LF normalization).

2026-05-22 pass removed: Arc 3 live verification (shipped post-2026-05-21),
clean-default-scaffold ≥1-track (auto-session `cleanup-default-scaffold`
ships), compose-time `preset_query` (push.py resolves it), W13-A v1.0
fallback (shipped v1.3.1), Drum Rack `loaded_class_name` (Arc 7/P5),
`tools/capture.py` collision (file no longer exists), W4-E mixer-column
docs nit (rolled into push skill), legacy-tool prose in falling-walking.md
(shipped), `docs/mcp-requirements.md` gap #4 prose (shipped), and the two
`sync/push.py` raw SELECTs (only one remains at line 1452, a JOIN of a
different shape — see polish entries).

Discipline (load-bearing — drift here ruined the d159e4c scrub):

1. **Close-in-the-same-PR.** When a PR ships work that resolves a backlog entry,
   *delete the entry in that PR*. Do not annotate "RESOLVED" inline — the git log
   is the audit trail. Critic and PR reviewer should flag any PR that ships work
   matching an open backlog item without deleting it.

2. **Verifiable signal required.** Every new entry must name a probe a future
   scrub can run to confirm it's still pending: a file path + line, a function
   name to grep for, a CLI invocation to run, or a behavior to reproduce.
   Without this, the entry is unscrubable — a future agent can't tell shipped
   from pending without re-reading the whole codebase.

3. **No inline RESOLVED scar tissue.** If a sub-bullet inside a multi-part
   entry shipped, edit the entry to remove the resolved sub-bullet (or delete
   the whole entry if the remainder is small). Don't leave "RESOLVED (Arc N)"
   annotations — they accumulate noise and the next scrub trusts them too much.

4. **Trust-but-verify on scrub.** A periodic scrub MUST re-read code against
   every entry it considers, not just trust the entry's text. Entries dated
   > 60 days are especially suspect. Run `python3 tools/product-hook backlog-stale-check`
   to surface candidates (when that tooling lands — see P1).

5. **Source marker required.** Each entry ends with `(builder)`, `(critic)`,
   `(reflection)`, `(migrated)`, or a chunk/session tag like `(Arc 3 / C2 follow-up)`.
   The marker is the scope hint — what surfaced this and where to look for
   shipped follow-up work.

Format: organized by **priority band** (P0 highest leverage → P6 future). Within
each band, bullets are most-recent-first. Use `**bold lead**` for the headline.
Priority = benefit / effort. Re-rank during each scrub — items move between
bands as the codebase + product shape evolves.
-->

## P0 — Highest leverage (small effort, real benefit, ready to ship)

_(no items)_

## P1 — Strong benefit, moderate effort

- **Per-section contribution attribution + masking.** Section-windowed *loudness* shipped (`MixReport.per_section`, keyed to `sections`-table names; master-overshoot findings tagged with their section). The remaining per-section dimensions are heavier: (a) re-run `master_bus_attribution` per section window so "kick + bass dominate the chorus low end" is answerable per-section, not just at the song's overshoot windows; (b) section-scoped masking analyzer (custom DSP — the spike's differentiator-vs-iZotope piece, §9 "Section-scoped masking analyzer ~1-2 weeks"). **Verifiable signal:** `SectionMetrics` carries an `overshoots`/`attribution` field populated per window. **Also:** variable-tempo-accurate beat→sample windowing — section windowing (and overshoot rebeat-ing) currently shares the constant-tempo linear map in `analyze._rebeat_overshoot`; songs with a multi-entry `tempo_map` get approximate sample boundaries. (section-windowed loudness shipped 2026-05-28; attribution/masking carried forward from spike §9)

- **Backlog accuracy structural enforcement — `product-hook backlog-stale-check` subcommand + Critic goal "closed-but-not-removed".** Both target files (`tools/product-hook`, `.prawduct/critic-review.md`) carry uncommitted v1.5 framework WIP introducing `/critic verify-resolutions` mode — landing this as a sibling would PR the framework work per memory `project_prawduct_framework_authorship`. **Two parts:** (a) `product-hook backlog-stale-check` subcommand — parses backlog entries, surfaces > 60-day candidates + diff-grep against recent PRs flags shipped-but-not-removed candidates; output rides the session briefing; (b) Critic / PR-reviewer goal extension — for cumulative reviews, grep diff for keywords matching open backlog headlines + named files/functions; flag PRs that ship work matching an entry without deleting it in the same diff. **Verifiable signal:** `python3 tools/product-hook backlog-stale-check` exists and exits 0; `.claude/skills/critic/SKILL.md` (or `.prawduct/critic-review.md`) contains a goal block naming "backlog closed-but-not-removed". **Sized:** small once unblocked. **Land after** v1.5 framework sync (verify-resolutions) ships, or coordinate with the user to bundle into that sync. (Arc 5 P0 deferral 2026-05-21)

- **Derived-views drift: `regen-views` no longer errors but still emits nothing.** Refreshed 2026-05-22: `python3 tools/product-hook regen-views` now exits 0 (no `ModuleNotFoundError`), and `tools/lib/` exists. The source-of-truth side is healthy — tagged change-log entries (`chunks=...|status=...|release=...|scope=...`) land in `.prawduct/change-log.md` for every entry since 2026-05-20. The view-derivation side is still inert: `scope_rollups: {}` in `.prawduct/project-state.yaml` stays empty, and `.prawduct/release-notes.md` is never created. Likely a tag-parsing or write-side bug in the regen logic. Two paths: (a) fix the regen path (likely in the framework-WIP `tools/product-hook` — coordinate with the upstream sync); (b) flip `views_enabled: false` in `project-state.yaml` until the fix lands. **Verifiable signal:** `scope_rollups` block in `project-state.yaml` is non-empty AND `.prawduct/release-notes.md` exists after a `regen-views` run. (W10-B/C/D + W12-C/W15-D + W15-B Critic notes, 2026-05-19/20; refreshed 2026-05-22)

- **Arrangement-VIEW state pull (loop region, follow mode, view zoom).** Distinct from arrangement-clip-placement pull (which M+1-3b shipped). `ableton_arrangement(action='info')` exposes the view state but there is no DB home for loop region or view zoom today; tempo/signature are better diffed against `tempo_map`/`time_signature_map` via dedicated probes. Needs an explicit decision: add DB columns for view state (probably on `ableton_sessions` — it's session-bound view state, not authored song data) or leave view state non-round-tripped per "DB is the score, not the rehearsal-room state." Filed for explicit decision, not silent drop. **Verifiable signal:** a `ableton_sessions` column for loop region exists OR a decision-record in `decisions/` says "view state intentionally not round-tripped." (reflection, M+1-3 re-plan 2026-05-17)

- **W8-C framework-coupled wiring — session briefing + CLAUDE.md addendum for song context.** The Wave 8 plan named two targets: (a) extend `tools/product-hook` so the session briefing surfaces in-scope song decisions + annotations; (b) add a CLAUDE.md addendum mirroring the existing `/learnings [topic]` guidance for song context. Both files are in the parked-upstream-framework set per memory `project_prawduct_framework_authorship` — adding hallucinote-specific behavior conflicts with the in-flight upstream sync. W8-C shipped only the SKILL.md guidance enhancement; the framework-coupled pieces are deferred. Then: (1) `product-hook` should detect "song in-scope" (any file touched in `songs/<slug>/`) and inject a `Song context:` block with the song's 5 most-recent markdown decisions + structural-fact annotations + `Q.get_annotations_for_song(..., kind='intent'|'structure')` from the W23-B annotations table; (2) CLAUDE.md should add a line: "Before non-trivial composition, run `/song-context [topic]` and read DB annotations via `ableton_annotation(action='list')`." **Verifiable signal:** session in a `songs/<slug>/` touch injects a `Song context:` block; CLAUDE.md mentions `ableton_annotation(action='list')`. (W8-C descope 2026-05-19; expanded for W23-B 2026-05-22)

## P2 — Useful, larger investments

- **Section-scoped masking analyzer (custom DSP).** No mature Python library implements iZotope-style inter-track masking. Build from primitives: STFT-align stems, Bark-band power, Schroeder spreading function, per-tile masking threshold, count masked-tile ratio per stem-pair. Section-scoped using DB clip schedule. ~1-2 weeks + synthetic test corpus. Differentiator vs. commercial maskers — no other tool can scope masking to "during the chorus only." **Verifiable signal:** `src/hallucinote/audio/masking.py` exists with `analyze_masking(stems, section_window, db) -> MaskingReport`. (spike §9 defer 2026-05-23)

- **`compare_to` baseline diffs for MixReports.** Skeleton field reserved in audio-analysis MVP schema; implementation deferred. Diff two MixReports keyed to DB audit-log seq numbers, surface metric deltas with significance flags ("low-mid ratio went from 0.31 → 0.24, ∆ -0.07 — meaningful improvement"). Enables A/B verification workflow described in audio-analysis spike §2 (`.prawduct/artifacts/research-spike-audio-analysis.md`). **Verifiable signal:** `analyze_mix(..., compare_to=<seq>)` populates `MixReport.deltas` with per-metric ∆ values + significance flags. (spike §9 defer 2026-05-23)

- **Candidate mutation proposals — the "fix" side of master-bus diagnosis.** Audio-analysis MVP diagnoses; this proposes ranked mutations with predicted metric deltas ("Lower rhythm guitar 1.5 dB in chorus — predicted master peak drops ~0.6 dB"). Requires a mutation-template library (sidechain insert, EQ carve, mixer-level adjust, limiter ceiling) + a predictor estimating post-mutation metric. Each proposal must cite which DB intent it's verifying or improving. **Verifiable signal:** `MixReport.proposals: list[Proposal]` populated with named mutations + predicted deltas + DB-intent citations. (spike §9 defer 2026-05-23)

- **W13-B follow-up: extract shared plugin-discriminator into a single module.** Both `src/hallucinote/sync/compat.py:_PLUGIN_CLASSES` + `_is_plugin_class()` and `hallucinote_mcp/.../handlers/device.py:1236-1241` (`is_third_party_plugin`) implement the same logic (explicit set + `"Plugin" in class_name` substring). Lock-tests keep them consistent (`test_plugin_classes_lock_matches_mcp_side` + `test_classify_device_substring_branch_routes_to_third_party`) — sufficient short-term, but drift-prone long-term. Natural home: W11-A's `hallucinote-core` shared package. **Verifiable signal:** a `hallucinote-core` package exists; both compat.py and device.py import the discriminator from it. **Defer until** W11-A's extraction lands so the move happens once rather than twice. (v0.9.0 cumulative Critic note + PR reviewer note 3, 2026-05-20)

- **Future sibling skill: `/song-import` — ingest an existing Ableton Live set into a new Hallucinote song dir.** Sibling to `/song-new`. `/song-new` scaffolds from templates (no Live required); `/song-import` would capture an open Live set + pull notes / arrangement / envelopes into a fresh DB + generate a build.py thin wrapper. Today the agent can do this manually by chaining `tools.scaffold_song` + `tools/capture.py` + `/ableton-pull`, but `/ableton-pull` is built for state diffs on an existing DB, not first-ingest of clips/notes/arrangement. Needs a "pull first-time everything" path (gated on pull-side scope items below). Naming chosen to match the `<scope>-<action>` convention. **Verifiable signal:** `.claude/skills/song-import/` exists. (skills-replace-prompts refactor, 2026-05-20)

- **Cross-song shared drum-kit mappings (post-M1-C).** M1-C ships `drum_pad_mappings` scoped per-song (rows reference `devices.id`, which is per-song). The same Drum Rack `.adg` loaded on machine A and machine B has the same pad layout (chain names + MIDI notes are kit-intrinsic). Hoisting mappings into a shared layer keyed on `(preset_uri OR preset_query OR plugin_identity)` would let one capture run benefit every song using that kit. Aligns with memory `project_cross_song_reuse` (shared kits/grooves/templates). Non-trivial schema + ownership design (who owns the mapping when two captures disagree). **Verifiable signal:** `drum_pad_mappings` table has a shared/hoisted layer keyed on preset identity, not per-song device_id. **Sized:** medium. (M1-C scoping 2026-05-20)

- **Per-scene tempo/signature as the supported workaround for the multi-bar tempo gap.** Hallucinote DB stores `tempo_map` and `time_signature_map` keyed by `start_bar`. Live exposes per-scene tempo/sig (each session-view scene can override the global values when launched). A sync-side change could map "bar X starts a new section" → "create a scene with tempo Y at that bar boundary," giving users multi-bar tempo/sig in the supported architecture without the missing LOM envelope API. Scope: schema-level decision on scene-bar binding, planner emit logic in `plan_push_tempo_map` (use scene path when non-bar-1 rows are present + scenes are part of the song's structure), test coverage. **Verifiable signal:** `plan_push_tempo_map` emits scene-create calls for non-bar-1 rows. **Defer until** a song actually needs multi-bar tempo (falling-walking doesn't). (W6-F 2026-05-19)

- **Clean-default-scaffold: option (a) "rename last instead of delete last" path.** Today's `cleanup-default-scaffold` ships option (b): push the song first (which creates the song's tracks), then delete the four defaults. Option (a) — delete N-1 defaults, rename the last to absorb one of the song's DB tracks — is cheaper at the LOM level (avoids creating then deleting tracks) but requires probe-and-link rerun to pick up the renamed track. Worth adopting if the cleanup latency becomes user-visible. **Verifiable signal:** `cleanup-default-scaffold` documents both modes and lets the caller choose. **Sized:** medium. (neon-feedback test session 2026-05-20)

## P3 — Polish, defensive, observability


- **Tonal balance reference curves + small internal genre corpus.** Compute long-window average spectra for a handful of professionally-mixed reference tracks per genre tag; surface as comparison targets in MixReports. Stem-level LUFS targets within a mix are *not* standardized in literature — building this internally is the honest path per audio-analysis spike §5. **Verifiable signal:** `tests/fixtures/audio/references/<genre>/*.wav` exists + `MixReport.reference_curve_delta` populated when song carries a genre tag. (spike §9 defer 2026-05-23)

- **Full realtime audio-feature set + streaming dashboard.** Audio-analysis MVP emits 3 OSC features (LUFS-M, sample peak, low-mid band power). Post-MVP: add LUFS-S, all six bands, spectral centroid, spectral flatness; expose the OSC sidecar's ring buffer via an MCP resource (e.g. `ableton://audio/features/stream`) for live mix coaching during playback. Currently the sidecar collects but doesn't expose externally. **Verifiable signal:** MCP resource yielding per-track frames at ≥20 Hz exists; MVP's 3-feature emit replaced or extended with the fuller set. (spike §9 defer 2026-05-23)

- **Audio-capture take retention: rolling window + pinned takes.** Captures are heavy (~165 MB per song per take); audio-analysis MVP keeps everything indefinitely. Add a rolling-window cleanup (keep last N captures per song) with explicit "pin this take" marker for important reference points. Analysis JSONs always retained (cheap). **Verifiable signal:** a `tools/audio-prune` (or similar) exists with `--keep N` + pinned captures have a `.pinned` marker file. (spike §9 defer 2026-05-23)

- **`AUDIO_CAPTURED` event kind for capture audit trail.** Audio-analysis MVP records DB seq number in the capture manifest but emits no event. Adding an event kind would put capture timestamps into the audit log, supporting "when was this take captured" queries via the existing `queries.get_events_for_song`. Additive (event-kinds are append-only per boundary-patterns). **Verifiable signal:** `events.AUDIO_CAPTURED` constant exists; emitted by `ableton_render` on capture-success with `{captures_dir, manifest_seq, track_count}` payload. (spike §9 defer 2026-05-23)

- **`_TRANSACTION_DEPTH` module-level state may leak under thread/async patterns.** W7-A's SAVEPOINT-based reentrant `transaction()` keeps depth in a module-level `dict[int, int]` keyed by `id(conn)`. Single-threaded today (per project preferences "Sync throughout. SQLite WAL + timeout=10.0. No async planned"), but multi-threaded use would interleave the counter. Defensive options: (a) `WeakKeyDictionary` keyed by the connection object; (b) attach the counter to the connection via a wrapper; (c) `threading.local`. **Sized:** ~5 LoC + 1 thread-safety test. (W7 cumulative-Critic note 3, 2026-05-19)

- **`_serialize_markdown` defensive: list items may contain `,` / `[` / `]`.** W8-B's `write_markdown_ref` calls `_serialize_markdown` to round-trip frontmatter through the YAML-subset parser. List items (`tags`, `related`, `bars`) get serialized as `[a, b, c]` without quoting. If a future tag or `related` path contains `,` or `[` / `]`, the parser silently splits or fails. Today's tags are slug-shaped so this isn't exercised, but the wrap is the LLM-facing surface. Defensive fix: (a) quote list items containing those chars, (b) reject at serialization with a teaching error, or (c) switch to multi-line list format. **Sized:** ~10 LoC + 2 tests. (W8-B Critic cumulative note 3, 2026-05-19)

- **`_apply_session_clips_for_track` cascades `delete_clip` → `arrangement_clips` silently.** Design-consistent with the project's cascade discipline, but the cross-domain side effect is invisible in `out.details` (no per-row events for the cascaded placements). Worth counting + logging cascaded arrangement-clip placements when a session-clip delete fires during pull. (PR review #22, 2026-05-17)

- **`_apply_session_clips_for_track` silently tolerates missing `length` / `name` on populated entries** (via `_floats_differ(None, X) → False`), unlike `_apply_arrangement_clips_for_track` which warns explicitly on missing fields. Asymmetry, not a correctness bug. Tighten for parity. (PR review #22, 2026-05-17)

- **`duplicate_to_arrangement` spurious-clip detection is start-time-only.** Chunk W2-H detects the B-24 side effect by comparing arrangement_clips' start_times before vs after the call. If a pre-existing clip already sits at exactly `dest_beats + source.length`, its start_time is already in the before-set and the new spurious clip slips past detection. Object-identity diff (`id(c)`) would be more robust — though Live's wrapper recreation (B-1) makes that fragile too. Unlikely in real songs. (critic W2 N2, Chunk W2-H 2026-05-18)

- **Confirm Phaser/Flanger and Eq3/FilterEQ3 round-trip class_name preservation in real Live.** Chunk W2-B's `device_names` mapping merged `Phaser`/`Flanger` to display `Phaser-Flanger` (similarly `Eq3`/`FilterEQ3` → `EQ Three`, `AutoPan` → `Auto Pan-Tremolo`) because Live 12.x merged these device families under one browser node. Load works for either source class_name; but when the device is captured (`device.list`), the reported `class_name` may be the merged form, breaking deterministic re-push. Post-D4 (commit `305742c`, "structural display-name shift — delete `_CLASS_TO_DISPLAY`"), the mapping was restructured to `device_names.py` with rack-root lookup only — the round-trip may be structurally solved. Real-Live verify path: load via `kind='Flanger'`, re-capture, confirm class_name preserved. If not, planner needs `preset_uri` for merged-display devices. **Verifiable signal:** real-Live smoke confirms class_name preservation; or a unit test pins the post-D4 invariant. (critic W2 N1, Chunk W2-B 2026-05-18; D4 context added 2026-05-22)

- **FastMCP private-API access in `test_server.py`.** Three tests reach into `mcp._tool_manager._tools[name]` directly to fetch a `Tool` for `.run()`. The existing `registered_tool_names` helper tries multiple attribute names for FastMCP version-drift resilience; a symmetric `get_registered_tool(mcp, name)` would centralize the version-coupling. **Verifiable signal:** `get_registered_tool` helper exists in tests. (critic W2 N1, Chunk W2-1 2026-05-18)

- **Clear + note_expression: omit-required-args path untested.** `ableton_automation(action='clear', target_kind='note_expression')` raises the gap-citing `NotImplementedError` regardless of whether note_pitch / note_start_beats / axis were supplied (gap check fires before parameter validation). Asymmetric with `write_envelope` which validates first. Either add a docstring note or a one-line test pinning the precedence. (critic, Chunk D 2026-05-18)

- **W6-K real-Live smoke — remaining surfaces.** Wave 6 shipped a substantial MCP-side surface validated against fakes. Sidechain smoke landed with `c80d4a6` (2026-05-22 — S/C Gain refusal fix). Still wants real-Live empirical confirmation: (a) `read_envelope` round-trips on a mixer_volume / device_parameter envelope; (b) `get_device_chains` structure on a real Drum Rack; (c) `load_in_rack` + `set_parameter_in_rack` on an InstrumentGroupDevice; (d) `set_input_routing` finds the right RoutingType by display_name; (e) W5-F deferred — round-trip parity on parameter-dialed native instruments via the W5-D pull path. (W6 close-out 2026-05-19; sidechain shipped 2026-05-22)

- **One raw `conn.execute("SELECT ...")` JOIN read in `sync/push.py:1452`.** The original two-SELECT concern (PR #24) is down to one — the remaining read is a join between `arrangement_clips` and `clips` to resolve envelope addressing; harder to factor into a `queries.py` helper because of the JOIN. Worth doing for consistency, but lower-leverage than when there were two. (PR review #24, 2026-05-17; refreshed 2026-05-22)

- **Wave plan headers missing top-level `Requirements Confidence` field.** Each M+1 chunk has an inline Confidence check, but the wave-level header in `build-plan.md` lacks a `Requirements Confidence: High|Medium|Low` declaration. Methodology cleanup — apply to the next wave header rather than retrofitting. (critic, M+1 final 2026-05-17)

- **Module-size watch (refreshed 2026-05-22): the trigger has likely fired.** `src/hallucinote/db/mutations.py` is now 4232 lines (was 2117 at first watch), `sync/push.py` 3062 (was 1333), `sync/pull.py` 3401 (was 1089) — roughly 2× growth since the 2026-05-17 watchpoint. Per-domain splits (e.g. `mutations/clips.py`, `mutations/devices.py`, `mutations/automation.py`) are now attractive enough to schedule. Not blocking, but a deliberate split-wave would land cleanly before the next big domain (audio clips) doubles them again. **Verifiable signal:** line counts re-measured at next scrub; if still ≥4kLOC for any of the three, schedule. (janitor, J-3; refreshed 2026-05-22)

## P4 — Future / v1.1+ enhancements

- **Source separation fallback for stemless audio inputs (lazy-import demucs).** When users want to analyze an imported reference track (not authored in Hallucinote — no stems available), use HT-Demucs v4 to derive vocals/drums/bass/other pseudo-stems. PyTorch dep + ~9.2 dB SDR; lazy-import only when invoked so the dep stays optional. Audio-analysis MVP's normal mode is "we have the stems via `sfrecord~`" — separation is the fallback for analyzing reference tracks, not the primary path. **Verifiable signal:** `src/hallucinote/audio/separation.py` exists with `separate_stems(mixed_audio) -> dict[str, ndarray]` gated behind a `[audio-separation]` extras group. (spike §9 defer 2026-05-23)

- **Wave 0 / D1 v1.1: planner auto-partition envelopes across per-section session clips.** v1 ships refuse-with-teaching (W10-F) for long envelopes whose range exceeds any single session clip. v1.1: planner detects the multi-clip case, splits the DB's logical envelope at session-clip boundaries, emits one sub-envelope per covering session clip; pull stitches adjacent identical envelopes back. Natural Hallucinote shape. Requires push-side split + pull-side stitch + round-trip test coverage. (Wave 0 triage Group D 2026-05-19)

- **Wave 0 / D3 v1.1: mixer envelopes on audio tracks via audio-clip DB model.** Gated on `scope.later` "audio clips: clip kind discriminator, file references, warp metadata." Once audio session clips are addressable, the envelope-emitter family can host mixer/send envelopes on audio session clips the same way it does for MIDI session clips. v1 ships refuse-with-teaching (W10-F). (Wave 0 triage Group D 2026-05-19)

- **Wave 0 paper-cut: polyrhythm helper using `fractions.Fraction`.** `(7.0 / 5) * 3 / 2.0` yields `2.0999999999999996` (IEEE 754 sub-LSB drift). The SQLite REAL column round-trips it faithfully, but authoring introduces it without warning. A future `hallucinote.polyrhythm(n, against=k)` helper should compute via `fractions.Fraction(against, n)` and float-convert only at the mutator boundary. (Wave 0 canary `odd-meter-experimental` runbook step 8, 2026-05-19)

- **Envelope discovery on pull — envelopes authored only in Live.** W7-A (2026-05-19) ships `plan_pull_envelopes` in DB-mirrored mode. It does NOT discover envelopes the user authored *only* in Live — that would explode the read surface (~10s-100s of probes per pull). A future "envelope discovery" pass could batch-probe likely surfaces (clips/devices/tracks mutated recently per `events` log). Not blocking V1. (W7-A 2026-05-19)

- **Recursive nested-nested rack chain support.** W6-I/J ship one-level-deep nested-rack support. Live allows racks-inside-racks-inside-racks; addressing beyond one level requires a path-style API (e.g., `chain_path=[2, 1, 3]`). Not exercised by today's songs. (W6-I/J 2026-05-19)

- **Return-side device_parameter envelopes need a return-track session-clip model.** W4-B routes track-side mixer/pan/send/device_parameter envelopes through session clips on the parent track. Return tracks have arrangement-side mixer state but the DB has no session-clip model for returns (`clips.track_id` references `tracks(id)` only). Live 12.4 only accepts device_parameter envelopes on session clips, so return-side envelopes get warn+skip today. Non-trivial: schema branch + mutators + push/pull routing. (W4-B 2026-05-18)

- **Live API residual on gap #4: true surgical Ableton-side note writes.** V1 close-out shipped READ-with-stable-IDs + WRITE-whole-clip (sufficient for compose/produce). Residual: per-note Ableton writes that preserve playback continuity (Live retriggers a clip on `set_notes` during playback) — would land via `apply_note_modifications` / `add_new_notes` / `remove_notes_by_id`. Out of V1 scope per `scope.never` (no live-performance use case). Re-open if performance use cases enter scope. (V1 close-out 2026-05-17)

- **Hallucinote-side quantize / swing / groove module — REVISIT WHETHER NEEDED.** Original M-3 scoping reaffirmed the DB-as-source-of-truth principle for note timing. But memory `feedback_prefer_llm_over_deterministic_module` says: before proposing a transform module (quantize/groove/timing math), ask whether the LLM can do it directly. The microtiming-as-authorship note (`feedback_microtiming_is_authorship`) reinforces this — feel is baked at pattern-helper generation time, not via a post-hoc transform. **Decision needed:** does this module still earn its keep, or should it be removed from backlog entirely in favor of LLM-direct timing offset authorship + the per-helper `feel` parameter? Defer until a real song needs structured grooves; downgrade-or-remove on the next scrub. (reflection, Wave M-3 user pivot 2026-05-17; flagged for re-decision 2026-05-22)

- **Native Linux support — gated on Ableton shipping a Linux build.** Today: README + install skill warn-and-confirm; `_live_preferences_root()` returns `None` on Linux (existing Wine/CrossOver branch in `install_paths.candidate_user_libraries()` is best-guess). If Ableton ships native Linux: real preferences root, `live_is_running()` Linux branch (`pgrep -i -f 'Ableton Live'`), `live_log_path()` mapping, decision on Wine fallback. (W15-C 2026-05-19)

## P5 — Investigations closed (reference, do not re-open without new evidence)

- **Multi-bar tempo / time-signature automation — NO MCP-SIDE FIX POSSIBLE.** Bar-1 case solved (W5-A 2026-05-18). Multi-bar cannot be closed via MCP: the underlying Live LOM does not expose `create_automation_envelope` from any song-level path. `song.master_track.mixer_device.song_tempo` IS a `DeviceParameter` but has no envelope-creation path. `signature_numerator/denominator` are plain int properties; per Ableton's forum (t=144193) time-signature automation is unsupported in the API. Sources: Cycling74 LOM, gluon/AbletonLive12 `_MxDCore/LomTypes.py`, Live 12 release notes. **Workarounds**: per-scene tempo/sig (see P2); real-time step-write (degraded, lost on reload). The planner's "warn and skip non-bar-1 rows" is the right shape until Ableton extends the API. (corrected W4-E entry; investigation closed W6-F 2026-05-19)

- **Live 12.4 envelopes are step-only — plan-time warn shipped.** `plan_push_envelopes` emits a per-envelope `plan.warn` when any breakpoint has `curve_kind in {'linear', 'fast', 'slow'}`, surfacing round-trip lossiness at plan time. Only `'hold'` curves round-trip losslessly. No segment-curve API exists in Live 10–12. `Live.Clip.AutomationEnvelope` exposes exactly two public methods (`insert_step`, `value_at_time`). Ableton's own Push remote script calls only `insert_step`. Sources: Structure-Void's LOM XML (Live 10.1.19), gluon Live 12, Live 12 release notes. **Workaround if curve fidelity is required:** emit a dense sequence of stepped points approximating the desired curve (XML bloat + post-load editability cost). The structural close is on Ableton's roadmap. (real-Live smoke, W4-E 2026-05-18; warn shipped W5-E; investigation closed W6-C 2026-05-19)

- **Live 12.4 hides the mixer column on tracks with empty device chains.** MIDI tracks created via `ableton_track(action='create')` with no devices loaded show NO volume/pan/sends/master faders. Loading any device into the chain makes the mixer column appear. Mixer state IS settable via MCP regardless — Live just hides the UI surfaces. Not a Hallucinote bug; documented in the push skill prose. (real-Live smoke, W4-E 2026-05-18)

- **Drum Rack browser name-collision is a per-machine library hazard.** Empirical (W7-0 2026-05-19): `kind='Drum Rack'` actually loaded an `InstrumentGroupDevice` because that machine had a saved Instrument Rack preset named "Drum Rack" higher in the browser walk. Per-machine library state, not a code bug. **Mitigations shipped:** Arc 7 / P5 surfaces `loaded_class_name` in the load response so callers can detect mismatches; Arc 7-tail E2 confirmed the symmetric replace-in-place case. **Workaround today:** use `preset_uri` for unambiguous loads; verify the returned `loaded_class_name` matches the snapshot's expected class. **Remaining fix candidates if it resurfaces:** restrict display-name walks to canonical category roots, or prefer the empty-rack canonical URI when the name matches a built-in rack class. (W7-0 session 2026-05-19; refreshed 2026-05-22)

## P6 — Truly future / event-store era / pre-V1 migrated

- Audio clips: clip kind discriminator, file references, warp metadata, warp markers. (migrated)

- **Session-view audio clip placement via browser-load workaround.** Live 10–12 has no `ClipSlot.create_audio_clip`. The only path is async browser-load: set `song.view.highlighted_clip_slot = target_slot`, then `application.browser.load_item(audio_browser_item)`. Caveats: async (no completion callback), audio must be addressable as a BrowserItem (Library/User/Places — not arbitrary filesystem path), browser-indexing dependent. Could expose as `ableton_clip(action='load_audio_to_session', track_index, clip_index, browser_uri)`. (W6-D investigation 2026-05-19)

- Track routing: sidechain, parallel busses, input/output routing config. Schema + sync work. (migrated)

- Group tracks (`tracks.parent_track_id` + Live group semantics). (migrated)

- Pull-side sync follow-on (status W5-D 2026-05-19): **Shipped:** mix-state, cue points + score globals, device chain structure, arrangement-clip placements, session-view clip slots, note pull via stable-ID read + whole-clip write, device-parameter values. **Deferred (above):** envelope pull (gated on `hallucinote-mcp` envelope read surface), nested rack chain pull (gated on `hallucinote-mcp` `get_device_chains`). (migrated; rewritten 2026-05-17; W5-D update 2026-05-19)

- Event replay function (`replay(events) → state`) and merge tooling. Required for cross-DB event-stream merges; only useful after the event-store flip. (migrated)

- Post-hoc event annotation (`event_annotations` table) for narrative on-the-fly addition to history. (migrated)

- Real-time concurrent editing / cloud DB migration. Out of foreseeable scope; mutator-discipline + storage abstraction keep the door open. (migrated)

- Song tests (on-demand layer): DB consistency + mix hygiene + audio/spectral. Land per-chunk as appetite allows; not gating any chunk's completion. (migrated)
