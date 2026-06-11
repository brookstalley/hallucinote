# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously. -->

## 2026-06-11 — CLR-A: compose-loop reliability (swell friction wave A)

<!-- prawduct: type=bugfix | chunks=CLR-A-01,CLR-A-02,CLR-A-03,CLR-A-04,CLR-A-05 | scope=compose-loop-reliability | status=merged -->

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

<!-- prawduct: type=feature | chunks=ENV-7G4K-01,ENV-7G4K-02,ENV-7G4K-03,ENV-7G4K-04 | scope=mcp-bridge,db,sync-push | status=merged -->

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

<!-- prawduct: type=feature | chunks=CLP-AUD1-01,CLP-AUD1-02 | scope=clip-audio | status=merged -->

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

<!-- chunks=FRICTION-03 status=shipped release=unreleased scope=friction-basket -->

`push_cli execute --song <slug>` now regenerates `songs/<slug>/REQUIREMENTS.md`
whenever the devices phase applied at least one call — including pushes that
halted at a later phase (the doc tracks current set state, not push success).
`compat.regen_requirements(song_slug)` is the extracted callable seam; the
`write-requirements` CLI command is a thin wrapper. `--db`-only pushes print a
stale-notice with the manual command instead of guessing the song dir; regen
failures degrade to a stderr notice (waivered broad catch) so the push's exit
code is never masked. `docs/collaboration.md` handoff checklist updated.

## 2026-06-10 — WFL-7Q2N: session-ID auto-discovery in push/pull CLIs

<!-- chunks=FRICTION-02 status=shipped release=unreleased scope=friction-basket -->

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

<!-- chunks=FRICTION-01 status=shipped release=unreleased scope=friction-basket -->

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

<!-- chunks=AUD-4W7K-02 status=shipped release=unreleased scope=aud-4w7k -->

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

<!-- chunks=AUD-4W7K-01 status=shipped release=unreleased scope=aud-4w7k -->

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

<!-- chunks=AUD-3F8M-02 status=shipped release=unreleased scope=aud-3f8m -->

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

<!-- chunks=AUD-3F8M-01 status=shipped release=unreleased scope=aud-3f8m -->

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

<!-- chunks=INS-7V2D status=shipped release=v0.9.3 scope=plugin-distribution -->

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

<!-- chunks=backlog-low-cost-sweep status=shipped release=v0.9.2 scope=backlog-low-cost-sweep -->

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

<!-- chunks=install-hardening status=shipped release=unreleased scope=install-hardening -->

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

<!-- chunks=LNT-1V9K,GEN-1S4K,REV-2W8K,helpers,chunk0 status=shipped release=unreleased scope=tools-dont-narrow-the-art+helpers-dry -->

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

<!-- chunks=AUD-6R2M,AUD-4S8T,AUD-8H2M status=shipped release=unreleased scope=audio-verification -->

Branch `fix/reverb-rt60-decay-tail` (off `develop`). Made the audio analyzer's
verification surfaces trustworthy on real multi-track songs. (`release=unreleased`:
post-v1.4.0 work, no release cut yet — see backlog VEW-9QH4. Live re-render
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

<!-- chunks=arrangement-1-5 status=shipped release=v1.4.0 scope=arrangement-model -->

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

<!-- chunks=bulk-notes-B1-B4 status=shipped release=v1.4.0 scope=bulk-note-authoring -->

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

<!-- chunks=masking-C1-C7 status=shipped release=v1.4.0 scope=masking-analyzer -->

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

<!-- chunks=section-windowing status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=3-followup status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=3 status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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
`analyze_mix('/Users/brookstalley/source/hallucinote/songs/reggae-metal/captures/20260527T200614Z')`
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

<!-- chunks=2 status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=2b-partial status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=2a status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=1 status=shipped release=v1.4.0 scope=audio-analysis-mvp -->

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

<!-- chunks=hygiene status=shipped release=v1.4.0 scope=mutator-event-shape+test-coverage+wire-schema-enrichment+fingerprint-binary-safety -->

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

<!-- chunks=E1|E2|E3 status=shipped release=v1.4.0 scope=enum-envelope-authoring+device-load-post-condition+w13a-fallback-identity -->

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

<!-- chunks=P1|P4|P5|P7|B5|backlog-scrub status=shipped release=v1.4.0 scope=envelope-polish+nested-rack-tombstone+device-load-class+mutator-prefix-strip+mcp-auto-mutate -->

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

<!-- chunks=H1|H2|H3|H4|H5|backlog-scrub status=shipped release=v1.4.0 scope=song-author-hygiene+kit-strict+negative-beats-refusal -->

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

<!-- chunks=P1|P2|P3|P4|P5|P6 status=shipped release=v1.4.0 scope=iteration-loop-polish+backlog-discipline -->

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

<!-- chunks=D4-1|D4-2|D4-3|D4-4|D4-5|D4-6|D4-7 status=shipped release=v1.4.0 scope=loader-display-name-convention -->

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

<!-- chunks=hotfix status=shipped release=v1.4.0 scope=arc-2-live-verification-fallout -->

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

<!-- chunks=C1|C2|C3 status=shipped release=v1.4.0 scope=compose-validation-r2-followons -->

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

<!-- chunks=Q1|B3-resid|B2|B4|B5 status=shipped release=v1.4.0 scope=provenance+annotations-mcp+dev-ergonomics -->

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
