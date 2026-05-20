# Changelog

All notable changes to Hallucinote are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased work — v1.0 is the active development line._

## [1.0.0] — 2026-05-21

**Beta-readiness release.** The v1.0 gate: a beta tester can prompt
"make me song X", get a finished-sounding result, share it with another
tester, and not bounce on common papercuts. v1.0 closes the device-load
forgiveness, cross-machine portability, drum-kit portability, push-state
coherence, and provenance gaps that v0.9 left exposed. The skills the
agent reaches for daily (`/song-new`, `/song-pick-instruments`,
`/ableton-push`) now operate against a hardened surface; the composer
workflow described in `CLAUDE.md` "Hallucinote Behavioral Norms" is
codified in product code, not in per-user agent memory.

### Added

#### Composer-experience overhaul (Wave 17)

- **`CLAUDE.md` Hallucinote Behavioral Norms appendix** — four
  product-level rules promoted from per-user agent memory: "Stop only
  on high-stakes decisions or must-answer questions," "Creative product
  prompts vs planning prompts," "Sound design IS composition," and
  "Microtiming feel is authorship, not post-hoc humanize." These shape
  how every agent collaborates on a song.
- **`docs/song-authoring-conventions.md`** — new "Sound design is
  authorship" + "Per-part feel (microtiming is authorship)" sections
  with verse-vs-chorus examples.
- **Per-part `feel` parameter** — 11 generator helpers (drums × 8 +
  bass × 3 + harmony tresillo_pluck) gain `feel: Mapping[float, float]
  | None`; the LLM resolves verbal genre intent ("lazy back-half",
  "push hard") into structured offset dicts at compose time. `apply_feel`
  helper lives in `primitives.py`. Per-part-per-call granularity — verse
  drums and chorus drums can have different feels; punk drums + lazy
  bluegrass guitar in the same section is a valid intent.
- **`/song-pick-instruments`** rewrite — picks instrument CHAINS
  (instrument + post-FX + initial sends) rather than bare instruments.
  Default chain shapes per role (drums / bass / lead / pads / vocals);
  rationale persisted as `songs/<slug>/decisions/NN-signal-chains.md`
  after user confirmation.
- **`docs/snapshot-schema.md`** — new "Multi-device chains (sound is
  composition)" subsection + canonical "stage chain → push →
  recapture" workflow section.

#### Push reliability (Wave 18)

- **Push coherence layer** — `push.check_coherence` + `push_cli
  check-coherence` + `push_cli execute --snapshot` opt-in. Pure
  validation that refuses on session / link / snapshot mismatch before
  any push phase fires.
- **Probe-driven `/ableton-push`** — skill rewrite makes the
  orchestrator own the snapshot probe + session mint + link
  reconciliation in that order, every push. New `--probe` flag on
  `probe-and-link` / `execute` / `check-coherence` runs an in-process
  MCP TCP probe (no tmp snapshot file). `M.unlink_db_from_ableton`
  mutator + strict reconciliation in `push.probe_and_link` deletes
  links whose `ableton_index` is gone from the fresh probe.
- **Soft reset** — `M.reset_song_content` narrows `build.py --reset`
  scope to song-content tables; preserves `ableton_sessions` and the
  `ableton_links` projection rows (including `db_kind='device'` links).
  Closes the punk-fate state-drift bug where `--reset` wiped Ableton
  bindings mid-iteration.
- **First-push clean-default-scaffold** — `default_scaffold_unmatched_
  tracks` field on `ProbeAndLinkResult` (fires when auto-session was
  created AND every unmatched Live track is in the canonical default
  `{1-MIDI, 2-MIDI, 3-Audio, 4-Audio}`). Skill Step 2a documents the
  push-then-delete-defaults flow with descending track-index delete
  order + post-delete reconciliation.
- **Last-track / last-scene refuse-and-teach** — `ableton_track(action=
  'delete')` and `ableton_scene(action='delete')` raise a teaching
  precondition error before Live's bare RuntimeError fires.

#### Capture polish (Wave 19)

- **`tools/capture.py` → `tools/capture_cli.py`** rename — closes the
  capture/load name collision; 8 reference updates across skills, docs,
  MCP guide, and tests.
- **Cue auto-disambiguation** — push planner appends `-N` suffix when
  multiple cues share a name (`chorus-1` / `chorus-2` / `chorus-3`)
  so Live's locator strip stays readable. Singletons unsuffixed;
  nameless cues left empty.
- **Nested-rack capture** — `_replay_rack_chains` walks one level +
  populates `device_chains` with `parent_rack_device_id`; rejects
  two-level nesting with a teaching error.

#### Push planner hygiene (Wave 20)

- **Device probe-and-link by `(class_name, chain_position)`** —
  `probe_and_link` accepts `live_devices_by_parent`, walks each matched
  track/return's chain in parallel with DB devices, writes
  `db_kind='device'` links on (position, class_name) match. Closes the
  device-duplication path on re-push when Live has pre-existing
  matching devices. `push_cli --probe` auto-populates via a new
  `_probe_live_devices_via_mcp` helper.
- **Query consolidation** — `sync/push.py` raw `SELECT`s factored into
  `queries.py` (`Q.get_clips_for_song`, `Q.get_device_parent_chain`,
  `Q.get_note`). `_track_kind_for_envelope` uses `Q.get_track`. Dropped
  dead `pan` alias from capture's mixer/return field lists (all real
  snapshots use `panning`).

#### Provenance + annotations (Wave 23)

- **Provenance read surface** — `Q.list_requests_for_song(song_id,
  kind=...)`, `Q.get_latest_request_for_song`,
  `Q.get_events_for_request`, `Q.get_request_event_summary`. Stable
  ordering via `ts DESC, rowid DESC` tiebreaker. Sessions can now
  query "what did I do last time on this song" without re-deriving from
  scattered files.
- **Structured song annotations** — new `annotations` table (song /
  time / track scopes via column nullability), 3 mutators
  (add/update/delete) + 3 events, 3 queries
  (`get_annotations_for_song`, `get_annotations_for_track`,
  `get_annotations_at_bar` with half-open `[start, end)` intervals +
  open-ended forward). Coexists with markdown-file annotations: the
  table is for live composing notes; markdown is for ADR-shaped
  decisions.
- **Push/pull request lifecycle** — `push_execute.execute_push` opens
  `kind='push'` request, threads `request_id` through
  `apply_push_results`, closes with outcome mapped from push's
  tri-state (ok / partial / failed). `pull_cli._cmd_apply` mirror with
  `kind='pull'`.

#### Device-load forgiveness (M1-A)

- **`device_names.strip_device_suffix`** — algorithmic fallback for
  Live's `*Device` class-name pattern (`AnalogDevice → Analog`,
  `OperatorDevice → Operator`, etc.). Runs after the explicit
  `_CLASS_TO_DISPLAY` translation table so bespoke renames like
  `AnalogSimplerDevice → Simpler` still win.
- **`device_names.browser_root_for_rack_kind`** — restricts the
  display-name walk for all four rack kinds (Drum / Instrument / Audio
  Effect / MIDI Effect) to their canonical browser root. Fixes the
  W7-0 finding where `kind='Drum Rack'` matched a user-saved
  Instrument Rack preset named "Drum Rack" in the instruments root
  before the canonical empty Drum Rack node. Restriction applies to
  translated candidates too, so `kind='DrumGroupDevice'` (translates
  to "Drum Rack") gets the same cross-category protection.
- **Bare `kind='Instrument Rack'`** — finds the canonical empty rack
  when exposed under the instruments root, or surfaces a teaching
  error pointing at Cmd+G grouping / `preset_uri` workaround when
  absent. Replaces the prior bare "did not append" runtime error.

#### Cross-machine instrument fallback (M1-B)

- **`push_execute._attempt_load_fallback`** — when an
  `ableton_device(action='load')` call carrying a `preset_uri`
  captured on the author's machine fails because the URI is
  unresolvable on the consumer's machine (Live FileIds differ across
  installs), the executor composes an `ableton_browser(action=
  'search', pattern=display_name, root=<kind-routed>)` call and
  retries the load with the first match's URI. Root selection: Plugin
  classes → `plugins`; DrumGroupDevice → `drums`; others →
  `instruments`. The subsequent parameter-write phase fires unchanged
  against the fallback device, so dialed parameter state still lands.
  The DB's `preset_uri` stays untouched (song stays portable); the
  fallback URI surfaces in the state file via `fallback_preset_uri`.

#### Drum-kit portability (M1-C)

- **`drum_pad_mappings` table** — per-Drum-Rack pad layout captured
  via `ableton_device(action='pad_info')` and persisted as `(device_id,
  chain_name, midi_note)` rows. Chain names stored verbatim from
  Live; canonicalization happens at READ time.
- **`Kit` class** (`src/hallucinote/generators/kit.py`) — typed read
  surface. Three constructors: `Kit.from_device(conn, device_id)`
  loads from the DB; `Kit.from_dict({canonical: note})` is
  test-friendly; `Kit.gm_default()` returns a standard
  General-MIDI layout. `pitch_of()` does fuzzy chain-name matching —
  "Kick Drum" / "BD Big" / "Bass Drum" all resolve to canonical
  "kick"; "Closed Hat" / "Hi-Hat Closed" / "CHH" all resolve to
  "hat_closed". Missing pads warn-and-fall-through to GM defaults so
  composition flow stays unblocked.
- **`capture_plan` adds `ableton_device(action='pad_info')`** for
  every `DrumGroupDevice`. Replay reads `device['drum_pads']` and
  calls `M.replace_drum_pad_mappings`.

#### MCP surface

- **`ableton_browser(action='search')`** — pattern-match nodes under a
  browser root. Lets agents find instruments / presets / plugins without
  knowing exact names. Default mode is case-insensitive substring; glob
  and regex modes available as opt-ins. Bounded by depth (default 8,
  max 12) and match limit (default 20, max 200); `path_prefix` narrows
  the walk to a sub-tree. Returns matches with name + uri + full path +
  is_loadable so the agent can disambiguate among same-name results.
- **`ableton_device(action='load', preset_query={...})`** — compose-time
  portable preset selector. Snapshot stores `preset_query` (e.g.
  `{root: "drums", pattern: "Late Nite Kit"}`) instead of (or alongside)
  per-machine `preset_uri`. The MCP handler resolves on the consumer's
  machine via the search primitive. Strict-mode — refuses if 0 or 2+
  matches (no fuzzy match shipping by accident). The cross-machine
  portability path for built-in Live content (drum kits, instrument
  presets) so snapshots transfer cleanly across installations.

#### Onboarding

- **`docs/song-new-checklist.md`** — authoritative 14-item must / should
  / emergent pre-composition checklist. The agent infers aggressively,
  states inferences explicitly, asks for must-haves it can't infer.
  Decisions persist as markdown under `songs/<slug>/decisions/` so the
  song's intent survives `/clear` and future-session re-opens via
  `/song-context`.
- **`push_cli execute`** — agent-bypassing dispatcher (W10-E2). The
  ten-phase push planner emits plans the agent has historically
  dispatched itself via MCP tool calls; for large songs that's a
  context ceiling. `execute` dispatches directly against Live's Remote
  Script via `hallucinote_mcp.client.send` so bytes never enter the
  agent's context.

### Changed

- **Workflow skills replace MCP prompts.** The 7 MCP prompts shipped in
  v0.9.0 (`create_midi_track_with_instrument`,
  `setup_sidechain_compression`, `build_return_bus`,
  `humanize_clip_velocity`, `compose_section_pattern`, `start_new_song`,
  `pick_instruments_for_song`) are deleted — MCP prompts surface only as
  user-facing slash commands in Claude Code; the agent could never reach
  them autonomously. The recipes moved into assistant-callable Claude Code
  skills under `.claude/skills/`:
  - `start_new_song` content folded into `/song-new` (the scaffold skill).
  - `pick_instruments_for_song` → `/song-pick-instruments`.
  - `create_midi_track_with_instrument` → `/track-new-with-instrument`.
  - `build_return_bus` → `/return-new`.
  - `setup_sidechain_compression` → `/mix-sidechain`.
  - `humanize_clip_velocity` → `/clip-humanize`.
  - `compose_section_pattern` → `/pattern-compose`.
- **Skill namespace standardized to `<scope>-<action>`** for Hallucinote-
  specific skills. Renames: `/new-song` → `/song-new` (matches existing
  `/song-snapshot`, `/song-context`); `/ableton-install-mcp` →
  `/ableton-mcp-install`; `/ableton-uninstall-mcp` →
  `/ableton-mcp-uninstall`. Framework-shaped skills (`/critic`, `/pr`,
  `/janitor`, `/learnings`, `/prawduct-doctor`) keep their scope-less
  names. `docs/new-song-checklist.md` renamed to
  `docs/song-new-checklist.md` for namespace consistency.
- **`/song-new` SKILL restructured** — two explicit phases
  (pre-composition elicitation, then scaffold + decisions + pick
  instruments). Mode detection (`make-me-X` vs `scaffold-only`)
  determines the final-report shape. The orchestration content that
  v0.9 shipped as the `start_new_song` MCP prompt now lives in this
  skill body.
- **Drum helper API: `kit: Kit` is required (M1-C breaking change).**
  All 9 `drums.X` helpers (`kick_stumble`, `lazy_snare`, `trip_hop_hats`,
  `tresillo_hats`, `bossa_shaker`, `ghost_kicks`, `ghost_snares`,
  `open_hat_lifts`, `trip_hop_drum_pattern`) now require a `kit: Kit`
  keyword-only argument; the `pitch: int = KICK / SNARE / HAT_CLOSED`
  defaults are gone. Composers express intent ("a kick pattern") and the
  loaded kit decides which MIDI note that means. `bossa_shaker` now uses
  `kit.pitch_of("shaker")` (canonically right — GM note 70) instead of
  `HAT_CLOSED` (the original "best fit" hack — GM note 42); songs that
  authored shaker-on-hat patterns need to construct an explicit
  `Kit.from_dict({"shaker": HAT_CLOSED, ...})` to preserve the old
  behavior. Pure inline-`_note(KICK, ...)` authoring (`neon-feedback`-
  style) is unaffected — the GM constants in `primitives.py` remain
  available for direct use.
- **Scaffold template** (`tools/templates/song/captured_session.json.tmpl`)
  — return names use the stripped form (`Reverb`, `Delay`) instead of
  Live's auto-slot-prefixed form (`A-Reverb`, `B-Delay`). Closes the
  noise on every fresh-scaffold build where `replay_capture` emitted
  a (correct but distracting) strip warning.

### Fixed

- **Stale MCP action names in skill descriptions / docstrings.**
  `/song-snapshot` skill description referenced `list_return_tracks` /
  `get_track_info` (the actual actions are `ableton_return(action='list')`
  / `ableton_track(action='info')`). `src/hallucinote/capture.py`
  docstring + `capture_plan()` runtime emit referenced
  `ableton_track(action='get_info')` (actual: `'info'`).

### Schema migration

- **`devices.preset_query TEXT`** — JSON-serialized compose-time
  portable preset selector (Sweep B). Added to existing v0.9.0 DBs via
  the `_ADDED_COLUMNS` migration in `db/connection.py`; existing devices
  get NULL.
- **`annotations` table** (W23-B) — structured song annotations with
  song / time / track scopes via column nullability. New install
  creates the table; existing DBs add it on first connection via
  `init_db`.
- **`drum_pad_mappings` table** (M1-C) — per-Drum-Rack pad layout
  (`device_id, chain_name, midi_note`). Populated by capture replay;
  empty until a song's snapshot has been refreshed via
  `tools/capture_cli.py`.

### Test counts

Main suite: **1725 passing** (up from 1452 at v0.9.0; net +273 across
W17 → M1-C). MCP suite: **653 passing** (up from 581 at v0.9.0; net
+72 across the M1-A device-load forgiveness work).

## [0.9.0] — 2026-05-20

**First user-facing release.** Composes a song end-to-end against
Ableton Live: scaffold from a prompt, build via Python, push the result
into Live, iterate by pulling Live's edits back into the song's DB. The
v0.9 milestone is "moderately sophisticated Claude Code + Ableton user
can sit down and be productive reliably" — the inline-iteration read
surface (`hallucinote://`, W11) is held for v1.0 so its API design can
be informed by real user friction.

### Added

#### Song authoring + onboarding

- **`/new-song <slug>` skill** — scaffolds a new song from templates
  (`tools/scaffold_song.py` + `tools/templates/song/*.tmpl`). Prompts for
  slug / title / tempo / signature / sections. Refuses on bad slug or
  existing path. Replaces the "copy from falling-walking" pattern as the
  onboarding entry point.
- **`start_new_song` MCP prompt** — workflow prompt the agent can run
  to bootstrap a new song from a natural-language description.
- **`pick_instruments_for_song` MCP prompt** — browser-driven instrument
  picker with three portability modes (`strict` / `relaxed` /
  `unrestricted`). Strict mode reads only Live built-ins for guaranteed
  round-trip; relaxed adds well-known third-party plugins; unrestricted
  defers consumer-side concerns to W13-B's compat check.

#### Push reliability

- **Push idempotency** — re-running `/ableton-push` against a Live set
  with partially-applied state is now safe. The arrangement phase reads
  `ableton_links` for `arrangement_clip` rows and skips already-linked
  placements with a tracking warn ("N placements already linked — already
  in the arrangement, idempotent re-push"). Returns + clips + cues
  + tempo / signature inherit the same idempotent semantics from the
  Wave 12-A mutator refactor.
- **Envelope-reach refusals (D1 / D2 / D3)** — `create_envelope` refuses
  with teaching errors when the target violates Live's mixer-envelope
  reach (master strip, audio-track post-arrangement, group track).
  Planner-side safety-nets catch legacy DB rows.
- **Meter-ratchet refusal (H1)** — `add_time_signature_point` and
  `update_time_signature_point` refuse post-bar-1 changes with a
  teaching error pointing at the v1.1 backlog item. v1.0 makes the
  limitation explicit rather than silently failing at push time.
- **Partial-state normalization** — `plan_push_arrangement` no longer
  raises on unlinked dependencies. It skips with a note so the agent
  can continue or abort.
- **Confirm gate on unmatched Live state** — push refuses-and-confirms
  when probe-and-link finds tracks or returns in Live that aren't in
  the song's DB (the can't-distinguish "default scaffolding vs another
  song" risk).

#### Cross-machine portability (W13-B + W13-C)

- **`python -m hallucinote.sync.compat check <slug>`** — walks the
  song's DB (including nested rack chains), classifies every device
  into five tagged statuses (`native` / `placeholder` /
  `third_party_ok` / `third_party_missing` / `third_party_unverified`),
  emits a JSON report, exits 1 if user attention is needed.
- **`compat write-requirements <slug>`** — (re)generates
  `songs/<slug>/REQUIREMENTS.md` so the consumer-facing shopping list
  travels with the song.
- **Compat preflight in `/ableton-push`** — Step 0a probes Live for the
  installed-plugin list; Step 0b runs `compat check` and refuses-and-
  confirms before any push phase fires. Express non-goal: never
  substitute, never bundle.
- **Placeholder device kind** — `kind='placeholder'` device rows skip
  cleanly in the push planner with a warn. Lets authors mark
  intentional empty slots for the consumer to fill.
- **`docs/collaboration.md`** — end-to-end walkthrough naming the three
  portability cases (A solved-in-v1.0, B detect-and-shop, C
  explicit-non-goal).

#### State hygiene

- **Idempotent mutators + `BuildSession`** — 13 UPSERT mutators + 5
  update-shape no-op-when-matching, threading actor + request via a
  `ContextVar`-based session context. The DB is now a materialized view
  of the event log: state-store now, event-store eventually. Identical
  rebuilds emit zero events.
- **Per-branch DB filename** — `songs/<slug>/<slug>-<branch>.db` inside
  a git repo (`songs/<slug>/<slug>.db` outside or on detached HEAD).
  Branch switches no longer leave the agent looking at a stale DB.
- **`/song-snapshot <slug>` skill** — re-runs capture probes, diffs vs
  the existing `captured_session.json`, asks the user to confirm before
  overwriting. Identity-aware diff matches tracks by index, devices by
  chain position, one level of nested rack chains.
- **MCP/Remote-Script drift visibility** — `hallucinote_mcp.cli
  preflight` reports per-candidate
  `{installed, version, matches_mcp_server}`. Wire-version-handshake
  errors point at the diagnostic command.

#### Pull + push UX

- **UUID-rotation warning on pull** — `_apply_notes_for_clip` pairs DB-
  only deletes with Ableton-only inserts on (pitch, velocity, mute) and
  emits an informational warning when matches exist. Surfaces the
  "Live rotated note ids" failure mode without false-positiving on
  legitimate deletes.
- **Per-domain pull progress** — agent emits `pulling domain N/M:
  <name>` for multi-domain runs.
- **Post-push Live 12.4 UX heads-up** — conditionally surfaces the two
  Live UI quirks the user is likely to hit (mixer column hides on
  empty-chain tracks; clip envelope dropdown hides mixer envelopes by
  default). Skip if neither applies.
- **Cue-zoom hint** — one-line locator-strip + zoom-out hint when the
  `cues` phase wrote at least one cue point.
- **Minimal push-results format + `--plan` flag** — ~50% reduction in
  per-call JSON; legacy format still accepted.

#### Compose flow

- **Generator meter parametrization** — 11 generators (drums × 8 +
  bass × 2 + harmony × 1) gain `beats_per_bar: float = 4.0` kwarg; bar
  iteration scales correctly through non-4/4 sections. Within-bar
  shapes remain 4/4-flavored; authors are pointed at hand-authoring
  for non-4/4 work where the within-bar pattern matters.
- **`hallucinote.tempo.to_live_bpm(pulse_bpm, pulse_kind,
  time_signature=None)`** — 12 pulse kinds. Closes the odd-meter-
  experimental canary's odd-meter tempo arithmetic.

#### MCP surface (stable)

- 10 unified Ableton tools
  (`ableton_{session,track,return,clip,note,device,automation,arrangement,scene,browser}`).
- 11 resources for low-context-cost reads (`ableton://session/snapshot`,
  `ableton://browser/*`, `ableton://plugins/installed`,
  `ableton://reference/*`, `ableton://guides/*`).
- 7 workflow prompts (`create_midi_track_with_instrument`,
  `setup_sidechain_compression`, `build_return_bus`,
  `humanize_clip_velocity`, `compose_section_pattern`,
  `start_new_song`, `pick_instruments_for_song`).

#### Install + docs

- **README** — parallel macOS / Windows install blocks, troubleshooting
  section covering the top 5 install/runtime failure modes, Linux
  documented as unsupported for v1 (Wine/CrossOver users see a warn-and-
  confirm in the install skill).
- **`/ableton-install-mcp` skill** — Python 3.10+ refuse-with-fix
  guidance, cwd-project-marker warn-and-confirm, post-install hand-off
  in user-facing voice (not MCP developer syntax).
- **Reliability harness (Wave 0)** — three canary songs built end-to-end
  by fresh-context agents to surface paper cuts. 12 net findings drove
  Waves 9 / 10 / 12 / 14 / 15 scope.

### Deferred to v1.0

- **W11** — inline DB read surface via `hallucinote://` resources.
  Held so the API design can be shaped by real inline-iteration friction
  rather than guesses.
- **W13-A** — instrument fallback identity (same plugin, different
  catalog id). Depends on an MCP-side `ableton_browser(action='search')`
  action not yet available.
- **W16-A** — assertions module + dogfood. Held for v1.0 so it can lean
  on cross-song data that v0.9 user feedback will surface.

### Explicit non-goals

- **Plugin substitution.** A missing third-party plugin is never
  swapped for a similar-sounding native device. The compat check
  preflight refuses; the consumer installs from the vendor.
- **Asset distribution.** Hallucinote does not ship instruments,
  presets, or sample packs. Case C (sample-pack dependencies) is not
  detected programmatically.
- **Distributed-collaboration concurrency.** v0.9 assumes one author
  per branch per DB. Multi-user concurrency belongs at the DB / app
  layer, not in the MCP wire shape.

### Known limitations

- Pre-bar-1 tempo / signature changes round-trip; mid-song changes
  surface as a refuse-and-teach (the MCP gap is real). Workaround
  guidance documented per refusal site.
- Some Live device-parameter enums have no normalized form on the MCP
  wire and are skipped with a warn. Continuous params round-trip
  cleanly.
- Linux is documented as unsupported for v0.9 (Live itself doesn't
  ship a Linux build). Wine/CrossOver paths get a best-effort install
  candidate with warn-and-confirm.

---

_Historical context._ v0.9.0 is the first formally tagged release. Pre-
tag work shipped through Waves 0–15 across `main` / `develop` between
project inception and the V1 cumulative merge (commit `f4b6d58`,
2026-05-20). Detailed wave-by-wave history lives in
`docs/v1-build-plan.md`. The v1.0 CHANGELOG entry will absorb v0.9's
content + the v1.0 additions (W11, W13-A, W16-A, release-prep R-1
exhaustive Critic sweep).
