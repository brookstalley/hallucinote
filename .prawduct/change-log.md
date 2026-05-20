# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously. -->

## 2026-05-20 — v0.9.0 milestone: cross-machine portability + first tagged release

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

<!-- chunks=W13-B|W13-C|hygiene status=shipped release=v0.9.0 scope=cross-machine-portability+v0.9.0-cut -->

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
