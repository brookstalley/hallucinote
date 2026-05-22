# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously. -->

## 2026-05-22 — Arc 6: song-author hygiene tail (H1–H5)

<!-- chunks=H1|H2|H3|H4|H5|backlog-scrub status=shipped release=unreleased scope=song-author-hygiene+kit-strict+negative-beats-refusal -->

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

<!-- chunks=P1|P2|P3|P4|P5|P6 status=shipped release=unreleased scope=iteration-loop-polish+backlog-discipline -->

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

<!-- chunks=D4-1|D4-2|D4-3|D4-4|D4-5|D4-6|D4-7 status=shipped release=unreleased scope=loader-display-name-convention -->

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

<!-- chunks=hotfix status=shipped release=unreleased scope=arc-2-live-verification-fallout -->

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

<!-- chunks=C1|C2|C3 status=shipped release=unreleased scope=compose-validation-r2-followons -->

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

<!-- chunks=Q1|B3-resid|B2|B4|B5 status=shipped release=unreleased scope=provenance+annotations-mcp+dev-ergonomics -->

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

<!-- chunks=A3|A1-resid|A2-resid|A5 status=shipped release=v1.1.0 scope=push-reliability+drum-mapping -->


## 2026-05-20 — R-1 + R-2: cue idempotency, scaffold cleanup CLI, compat preset_query validation

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

<!-- chunks=R-1|R-2 status=shipped release=v1.0.1 scope=push-reliability+compose-time-validation -->


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
