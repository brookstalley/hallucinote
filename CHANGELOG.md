# Changelog

All notable changes to Hallucinote are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
- **`docs/new-song-checklist.md`** — authoritative 14-item must / should
  / emergent pre-composition checklist. The agent infers aggressively,
  states inferences explicitly, asks for must-haves it can't infer.
  Decisions persist as markdown under `songs/<slug>/decisions/` so the
  song's intent survives `/clear` and future-session re-opens via
  `/song-context`.

### Changed

- **`/new-song` SKILL** — restructured around two explicit phases
  (pre-composition elicitation, then scaffold + decisions + pick
  instruments). The final report now points at next-steps
  (pick instruments → push → recapture → compose) instead of just
  naming the scaffolded directory.
- **`start_new_song` MCP prompt** — mirrors the new-song checklist.
  Adds an explicit elicitation step (Step 0) and decisions-persistence
  step (1a). Step 2b (`pick_instruments_for_song`) cross-references
  `preset_query` as the portable selector for built-in content.
- **Scaffold template** (`tools/templates/song/captured_session.json.tmpl`)
  — return names use the stripped form (`Reverb`, `Delay`) instead of
  Live's auto-slot-prefixed form (`A-Reverb`, `B-Delay`). Closes the
  noise on every fresh-scaffold build where `replay_capture` emitted
  a (correct but distracting) strip warning.

### Schema migration

- **`devices.preset_query TEXT`** — JSON-serialized compose-time
  portable preset selector. Added to existing v0.9.0 DBs via the
  `_ADDED_COLUMNS` migration in `db/connection.py`; existing devices
  get NULL.

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
