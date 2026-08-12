# Changelog

This is the public release record: what changed in each version, written for
people using Hallucinote. It is distilled at release time from the internal
engineering change-log (`.prawduct/change-log.md`), which carries the full
per-fix narratives if you want the deep story behind any entry.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.8.6] — 2026-08-12

The demo release. The README now opens with a two-minute video of a prompt
becoming a finished arrangement playing in Live, so you can hear what this does
before installing anything.

**Upgrade note:** none. **Re-vendor: not required** — no handshake-fingerprint
paths changed, so the Remote Script in your Live User Library keeps working as
is. Documentation only; no behavior changes.

### Added

- **A demo video in the README**, playing inline. Previously the only demo was
  an audio link you had to download to hear.
- **A GitHub Release for each version.** The project had been tagging releases
  without publishing them, so there was nothing to land on; v1.8.5 was published
  retroactively and every release from here carries notes and assets.

### Changed

- **The README says what the tool is, in the user's own terms.** The opening,
  the worked-example intro and the bridge example were rewritten by the project
  owner; the round-trip through Ableton is now stated up front, including that
  audio does not come back yet.
- **The docs stopped defining things by what they are not.** Roughly forty-five
  constructions across the README, VISION, FAQ, tour, CONTRIBUTING and SECURITY
  now state the capability, the mechanism or the fact outright. The honest
  limits are unchanged and still stated plainly — `docs/known-issues.md`,
  VISION's non-goals and SECURITY's scope list all read as before.

### Fixed

- **A stale claim in the demo-video design** that listed work as outstanding
  when it had already shipped.
- **A contributor-facing inaccuracy**: the CI section described its own coverage
  gaps under a heading that undersold what CI does check.

## [1.8.5] — 2026-08-11

A documentation release, from a critical read of everything a new user sees.
The docs now answer what the tool costs to run, what it does with your melody,
and whether you end up with an Ableton set you can finish and release — and
several claims that disagreed with each other now agree. No behavior changes.

**Upgrade note:** none. **Re-vendor: not required** — no handshake-fingerprint
file changed, so the plugin auto-updates and Ableton Live needs nothing:
no `/hallucinote:ableton-mcp-install`, no Live restart.

### Added

- **What it costs to run** — README Status and a new FAQ entry name all three
  costs: the Ableton licence (plus Max for Live for the measured mix review),
  the Claude usage behind a long agentic session, and disk for renders. No
  token figure is published yet because none has been measured; that's tracked.
- **"Who it's for"** in the README — what the tool gives you if you're learning
  the craft, if you're playing already and reaching for an arrangement you'd
  otherwise spend a week programming, or if you want leverage and a measured
  second opinion.
- **New FAQ answers** — what happens with the melody, whether you end up with a
  normal Live set you can finish and release (yes), whether two builds of the
  same song match (yes, humanization is seeded), and who owns the music (you).
- **A guard on the tool count in the plugin marketplace description** — the
  number shown in the `/plugin install` dialog was the one such count no test
  pinned.

### Changed

- **The README speaks to the musician, not about the agent.** You make the
  calls; the tool builds what you decided, measures it, and reports back.
- **"Any Live 12 edition" is now "Standard and Suite"** — the editions this is
  actually exercised on. Intro and Lite are untested; `docs/known-issues.md`
  names the two limits likely to bite (the track ceiling, the thinner device
  palette). This corrected five surfaces, including the capability table the
  agent answers "what can you do?" from.
- **`CONTRIBUTING.md` matches the toolchain that ships** — uv against the
  locked environment, the current waiver pragma, the real `testpaths`, and a
  new section stating plainly what CI covers (no Ableton, no macOS or Windows
  leg, one interpreter).

### Fixed

- **The plugin marketplace description no longer claims you need a separate
  engine install.** It was stale from before the plugin absorbed the engine —
  and it was the first sentence anyone read, in the install dialog.
- **`docs/VISION.md` no longer claims recorded audio round-trips into the
  database.** It doesn't yet; `docs/known-issues.md` always said so. The
  symbolic round-trip that does work is described as what it is.
- **The FAQ's disk-usage note matches what a real workspace does** — a
  workspace created by Hallucinote gitignores both `captures/` and `analysis/`.
- **Documented Windows support says what's actually behind it** — implemented
  and unit-tested, with fewer real sessions than macOS.

## [1.8.4] — 2026-08-11

A documentation release: the README is a quarter shorter, the docs got read
against the writing guide, and the template that generates every new song's
overview was fixed at the source. No behavior changes.

### Changed

- **The README says more with less** — 1334 → 1008 words, cut by merging two
  sections that were describing the same three capabilities rather than by
  squeezing sentences. The install steps, troubleshooting causes and example
  prompts are untouched.
- **The lifecycle diagram names what the agent measures** — the analysis step's
  caption now reads "composition, mix, and audio measurements".
- **`docs/quickstart.md` and the demo song's overview lead with the point** —
  both used to open on housekeeping (a cross-reference, a note about where
  intent files live) before saying what you actually get. That content moved
  below the thing it was burying.

### Fixed

- **New songs no longer scaffold with a broken pointer or an unresolvable
  command.** The song-overview template sent authors to
  `.prawduct/artifacts/song-conventions.md` — a file that exists only in this
  repo, never in a user's workspace — and told them to run a bare
  `/song-context`, which doesn't resolve when Hallucinote is installed as a
  plugin. Those are now `docs/song-authoring-conventions.md` and
  `/hallucinote:song-context`, and the overview leads with the concept instead
  of the housekeeping. Every song scaffolded from now on gets the corrected
  template; existing songs are unaffected.
- Screen-reader users get the current description of the lifecycle diagram — the
  SVG's `<desc>` still carried wording that had been retired from the visible
  caption, so the stale framing was reaching exactly the readers who couldn't
  see the correction.

### Upgrade note

Nothing to do. This release does not change the Remote Script handshake
fingerprint, so your vendored copy in Live still matches the server — no
`/ableton-mcp-install`, no Live restart.

## [1.8.3] — 2026-08-11

The worked-example release: a real song ships in the repo, and a two-chapter
walkthrough of how it actually got made. No behavior changes.

### Added

- **A demo song you can rebuild** — [`examples/punk-fate/`](examples/punk-fate/)
  is Beethoven's Fifth crammed into 115 seconds of basement punk, composed by
  Claude end-to-end from a one-sentence prompt in a live session.
  `python examples/punk-fate/build.py` rebuilds its database from a clean
  checkout with no Ableton Live installed, and CI runs exactly that — so the
  example can't quietly rot.
- **[The tour](docs/tour.md)** — that song documented beat by beat, with the real
  session transcript, screenshots taken while it ran, and the mix numbers the
  agent measured. **Chapter 1** is the composing session: one prompt to a mixed
  four-track song in about forty minutes. **Chapter 2** is what happened when
  somebody listened and said it didn't sound punk — three measured re-cuts
  covering performance feel, garage-drum vocabulary, gain staging, and finally
  swapping the synth "vocal" for a second guitar. It ends on something
  deliberately *not* finished.
- Every figure the tour quotes is recomputed from committed evidence by tests, so
  a number that drifts fails the build instead of going quietly stale.

### Changed

- The demo song's overview and `REQUIREMENTS.md` describe the band that's
  actually playing, and the docs index no longer counts the tour's parts.
- `docs/song-authoring-conventions.md` now documents the `analysis/` vs
  `measurements/` split — the log of every mix run versus the specific runs a
  decision cites.
- Building the demo song no longer prints a spurious warning about return-track
  names.

### Fixed

- A test-harness bug where tests that launch a subprocess could exercise a
  different checkout of Hallucinote than the one under test. It showed up as
  confusing failures in the `capture` CLI tests when working from a git worktree,
  and it meant a plain `pytest` couldn't be trusted there.

No re-vendor required — no bridge code changed; the Remote Script handshake is
unaffected.

## [1.8.2] — 2026-08-11

The documentation release: the repo gets the public face the code already
earned. No behavior changes.

### Changed

- **README rebuilt for reading** — what it is, what you can do, how to use it,
  where to learn more — with a real captured hero image: the README's own
  example prompt (punk-fate) composed from scratch in a live session, beside
  the finished arrangement it built.
- **This changelog is maintained again**, with entries back-filled through
  1.8.1, and the release process now owns keeping it current at every cut.
- **Docs got an audience index** (`docs/README.md`), enforced by tests; known
  issues split to their own page with workarounds; quickstart and FAQ now teach
  the pull → bake → build loop; every command the docs tell you to run has been
  verified runnable from a fresh marketplace install.
- Governance: the project's norm registry was ratified (27 norms) — internal,
  but it rides this tag.

No re-vendor required — no bridge code changed.

## [1.8.1] — 2026-08-10

Internal housekeeping; no behavior changes.

- The development backlog moved from an in-repo markdown file to
  [GitHub Issues](https://github.com/brookstalley/hallucinote/issues), so open
  work is publicly visible and linkable.
- The release process document was corrected where the v1.8.0 cut proved it
  wrong.

No re-vendor required — no bridge code changed; the Remote Script handshake is
unaffected.

## [1.8.0] — 2026-08-10

### Added

- **The mix report can see stereo.** Per-stem and per-section stereo metrics —
  L/R correlation and mono-sum loss — plus declared-vs-measured width: a width
  or spread control a song declares is paired with what the rendered audio
  actually did, on tracks *and* return busses. This catches the two silent
  failure modes that motivated it: a "stereo" effect rendering bit-exact mono
  (a flanger with its L/R phase offset at 0°), and an aggressive width setting
  doing nothing because it multiplied a side signal that wasn't there.
  `/mix-review` reads both. A/B comparison (`compare_to`) gained a matching
  stereo family, so a mono-loss improvement shows as a delta instead of nothing.
- **`/song-brief`, a new stage 0 in front of `/song-new`** — the elicitation
  pass that resolves what a prompt left open (key, tempo, section budget, what
  a named gesture means musically) in one consolidated turn of proposals, and
  writes the song's brief. With it, every authoring stage got an explicit
  definition of done: a stage may no longer hand an unresolved question
  downstream dressed as a decision.

### Fixed

- **Seven push/sync correctness fixes — six of which previously reported
  success while doing the wrong thing.** The most visible: a full push could
  duplicate every FX chain in the set (and still say OK); a first push into an
  empty set could silently skip the arrangement phase; a browser load aimed at
  the master could also append devices to an unrelated track; a song slug could
  resolve into the wrong workspace, sending renders and analysis to a phantom
  directory; and a render could start playback from the wrong position when a
  locate hadn't settled. Pushes now reconcile device links before planning,
  report blocked phases as failures instead of "skipped", bracket browser loads
  with a device census, resolve slugs to the workspace that actually holds the
  song, and settle locates before rolling.
- **Rebuild reliability:** captured preset names now match exactly (no more
  refusing to load `Kit-BritishVintage` because an `MPE Kit-BritishVintage`
  also exists), stale device links are detected when you swap Live sets, and a
  build that *changed* an automation arc no longer loops create/delete/create
  without converging.
- **MixReports no longer embed your home directory.** Capture and baseline
  paths in tracked analysis files are song-relative now; existing absolute
  reports still load and still work as comparison baselines.

### Changed

- The in-repo demo song was retired; the walkthrough it anchored is being
  re-authored from a sparse prompt through the new `/song-brief` flow. Its
  scouting value — six framework defects found by rebuilding it from scratch —
  shipped as the fixes above.

### Upgrade note

After updating, rerun `/hallucinote:ableton-mcp-install` and fully quit and
reopen Live — this release changes bridge handler code, so the version
handshake requires a re-vendored Remote Script.

## [1.7.2] — 2026-08-06

Preparation for the repo going public. No behavior changes.

- Internal bug-report archives left the tree; provenance now cites backlog ids.
- Hardcoded local paths and a private sibling project's details were scrubbed
  from docs and history-facing files.
- `SECURITY.md` now states the trust model explicitly — including the sharpest
  edge: a song's `build.py` is executable Python by design, so review a song
  you cloned before building it.
- `architecture.md` and `api-contract.md` were written (the four-runtime
  topology, the fingerprint-not-semver versioning decision, the errors-teach
  model).

**Upgrade note:** although behavior is unchanged, one repointed docstring sits
in a fingerprinted bridge path, so the handshake flips — rerun
`/hallucinote:ableton-mcp-install` and fully quit and reopen Live after
updating.

## [1.7.1] — 2026-08-03

### Added

- **Render captures get a rolling retention window.** Every render writes
  ~23 MB per surface-minute of per-stem WAVs, and nothing ever deleted them —
  real songs had reached ~4 GB per take. A song now settles at 3 takes on disk
  after each render; pin a reference take with `captures pin` to exempt it.
  MixReports are never swept — analysis is self-contained JSON, so deleting an
  old take costs only the ability to re-analyze that specific audio.
  `HALLUCINOTE_CAPTURE_KEEP` / `HALLUCINOTE_CAPTURE_SWEEP=0` tune or disable
  the sweep.

### Fixed

- Provenance tests no longer assert ambient git state (first red CI run on a
  PR branch).

## [1.7.0] — 2026-07-04

### Added

- **CI off-laptop:** lint, types, tests, and lock-consistency run as four
  gates in GitHub Actions; ruff and mypy debt taken to zero.
- **Pull-durability guard:** a mix edit you pull from Live but don't bake with
  `/song-snapshot` is no longer silently reverted by the next build — the
  build refuses to run (`StaleSnapshotError`) until you bake or explicitly
  `--force-replay`. The loop is pull → bake → build.
- **Event-log hardening:** atomic write+emit, stable event IDs, and a replay
  smoke test — groundwork for the future event-store migration.
- Sync-boundary contract and phase-ordering DAG, with a controlled halt on
  unknown link kinds instead of undefined behavior.

## [1.6.1] — 2026-06-24

### Added

- Standing timbre metrics — brightness and noisiness — in the mix report.

## [1.6.0] — 2026-06-23

The entries below were drafted here as "Unreleased" and shipped in v1.6.0's
catch-up window; v1.6.0 contained substantially more (see release notes).

### Fixed — swell rebuild-reliability cluster (dogfood)

- **Full push no longer halts on a `value_raw` device-param override.**
  `apply_push_results` had no case for the `device_param_override` result kind the
  devices phase emits for a nested preset override (DEV-4P7R), so a from-scratch
  push of any song carrying one died mid-`devices` (no routing / envelopes /
  automation / arrangement / cues followed). It is now ack-only, like
  `device_parameter` — the value originates in the snapshot/DB, with no Live-side
  index to record back.
  (`backlog PSH-8K3D`)
- **Converger idempotency restored for any song with sidechains.**
  `replay_capture` enqueued every device's `sidechain_source` and cleared it when
  the snapshot was silent, clobbering a `build.py`-authored source on every build
  (real → null → real = 2 spurious events per sidechain, forever). Replay now
  treats snapshot *silence* as "no opinion" and acts only when the snapshot
  declares the key; an explicit null still clears.
  (`backlog SYN-7N4K`)
- **`reindex_markdown` no longer dies on a frontmatter-less decision.** A decision
  authored as a bare `# Title` body is now indexed (kind inferred from the corpus
  dir, full text searchable) instead of aborting the corpus; a genuinely
  unparseable file is skipped with a warning so one bad doc can't blind
  `/song-context` search to all the good ones.
  (`backlog IDX-5W2P`)

### Changed

- Snapshot semantics for device **sidechain sources**: a snapshot is authoritative
  for what it *declares*, never for what it *omits* (was "absent → clear"). This is
  what lets a `build.py`-authored sidechain survive a rebuild; see *Known
  limitations* for the accepted cost.

## [1.5.0] — 2026-06-17

**Version-track unification + the develop→main catch-up release.** The product
version is normalized to a single source of truth at **1.5.0** across
`pyproject.toml`, `.claude-plugin/plugin.json`, and `hallucinote.__version__`,
ending a silent drift where those three read 0.9.0 / 0.9.8 / 0.1.0 independently.
(History: an early 1.x git-tag/CHANGELOG track — last at 1.3.2 — was abandoned for
a 0.9.x reset that the package files never consistently followed; 1.5.0 steps
forward of the old `v1.4.0` high-water mark and re-unifies every track.) A new
`tests/unit/test_version_parity.py` locks the three product-version literals to
`pyproject` so they can't diverge again; the MCP server's
`hallucinote_mcp.BASE_VERSION` stays a deliberately separate wire-protocol axis
(bumping it per release would force every Live install to re-vendor the Remote
Script). This entry consolidates the work landed since 1.3.2 — the CHANGELOG was
not stamped through the 0.9.x line.

### Added — uniform node addressing (NODE-ADDR / DEV-9K7N)

- One `NodeAddr` object replaces flat device addressing on the MCP wire; read-side
  acquisition reaches device parameters at **every nesting depth** (`capture
  execute` + depth-N pull + a `default_value` capture filter).
- Per-DrumChain authorship (`choke_group` / `out_note`) and per-chain mixer state
  (mute / solo / volume / pan) via the `chain` terminal; rack macro authorship
  with an honest capability matrix (zones surfaced as `UNSUPPORTED_IN_LIVE`).
- Chain-terminal device load uses the real Live API (`Chain.insert_device`).

### Added — self-contained plugin + onboarding

- The engine runs in the plugin's own uv env — unified CLI + server-python +
  Python hooks, no separate install. Skills invoke the engine via that env.
- `hallucinote init-workspace` bootstraps a songs workspace; `/getting-started`
  and `ableton_render` teach when the Max-for-Live analyzer isn't installed
  (ONBOARD-M4L).

### Added — durable authoring round-trips

- **Sidechain sources** round-trip through the durable snapshot, and the mix bake
  is consolidated to one command (`/song-snapshot`): the redundant DB-only
  `/snapshot-bake-recent-changes` alias is removed and `/ableton-pull` is reframed
  as the build.py-staging primitive (BAK-3M9T).
- **Nested-param overrides** on a `preset_query` device persist durably without
  dropping the preset's timbre (SNP-2H9F); a **`value_raw`** channel carries
  quantized non-`[0,1]` device params that neither the display string nor the
  normalized channel could express (DEV-4P7R).
- Note edits propagate to arrangement clips (PSH-6W2J).

### Added — track routing + the PRE-MAIN submaster bus (RTE-1K9T)

- First-class track signal routing end-to-end (MCP → DB → push → pull) and the
  PRE-MAIN audio-bus convention it unlocks — a no-`.als` automatable master /
  sub-mix path. The routing target is a **semantic FK reference** that survives
  renames and re-pushes; the push gains a `routing` phase. Documented in
  `docs/song-authoring-conventions.md` and the MCP conventions guide.

### Added — per-song attempt ledger (ATL-7K3M)

- `kind: attempt` entries + `/song-attempts` record what was tried on a part and
  how it turned out (including reverted dead ends), so each iteration starts
  smarter instead of re-running a move that already failed.

### Fixed

- Analyzer-infra robustness (MCP-7F2K): master device-link reconcile is
  analyzer-aware (stops re-pushing params at the analyzer), and analysis picks the
  latest captures dir by manifest `captured_at`, not directory name.

### Verified

- Full suite green (4071 passing / 2 skipped), including the new version-parity
  guard. Each feature landed on develop via its own PR with independent Critic
  review; this release is the develop→main promotion.

## [1.3.2] — 2026-05-23

**Hygiene wave — five backlog items closed in one bundle (PR #94).** Two P0 bugfixes, one P0 test coverage gap, one P1 schema enrichment, one P3 defensive guard. No new product surfaces; the value is correctness + future-defensiveness on existing ones.

### Fixed — `delete_notes` tags `events.clip_id` per affected clip

- **`db/mutations.delete_notes`** now emits one `NOTES_DELETED` event per affected clip with `events.clip_id` populated, symmetric with `NOTE_UPDATED` + `insert_notes`. Previously emitted a single event with `clip_id=None`, so `_latest_actor_for(row_kind='clip')` — which scans `events.clip_id` directly — missed the LLM touch and a build-owned clip whose only LLM edit was `delete_notes` became falsely tombstone-eligible on the next build.
- Single-clip path (the only shape today's `sync/pull.py:2971` exercises) unchanged externally — still one event, just with the column populated. Multi-clip path yields per-clip events instead of one spanning many, also restoring per-clip granularity on the events table.

### Fixed — `_hash_file` NUL-byte sniff for binary safety

- **`hallucinote_mcp/__init__._hash_file`** now skips CRLF→LF normalization when the file contains a NUL byte (binary heuristic). Forward-defensive against a future contributor adding a non-Python entry to `_FINGERPRINT_PATHS` (JSON manifest with embedded CRLF, static `.als` skeleton, `.so` binary) — without the sniff, `b"\r\n"` substrings would be silently rewritten and the fingerprint would drift for non-drift. Python source has no NUL bytes, so the existing cross-platform stability path is unchanged.

### Added — JSONSchema enum/min/max/description enrichment

- **MCP server `_register_tool`** propagates `ParamSpec.enum` / `minimum` / `maximum` / `description` into FastMCP's pydantic-derived wire schema via `Annotated[Optional[T], Field(...)]`. Agents that consult the schema can now prune impossible calls earlier (e.g. `cc_number` 0–127, `bpm` 20–999, the seven `target_kind` enums) rather than waiting for the dispatcher's teaching error. Dispatch-time validation is unchanged.

### Added — `tools/migrate_arrangement_clip.py` synthetic-fixture test coverage

- **7-case test file** covering the one-shot `arrangement` → `arrangement_clips` migration: table+index renames, event-kind rename, JSON1 payload-key rewrite (with a sentinel kind proving unrelated rows stay untouched), `ableton_links.db_kind` rename, second-run no-op idempotency, both-tables-present refusal, and full rollback on mid-transaction failure. Round-trip was previously verified manually on falling-walking's real DB; this locks the contract.

### Verified — W8-B agent-side `M.request` wrap already shipped

- Verified the backlog item ("Agent-side push/pull/capture skill wraps in `M.request(...)`") is structurally satisfied by W23-C: `push_execute.py:410` opens `kind='push'`, `pull_cli.py:161+277` open `kind='pull'`, the MCP dispatcher's `auto_request` opens `kind='mutate'`, and `/song-snapshot` doesn't mutate the DB (the snapshot file IS the deliverable). Entry deleted from backlog as stale.

### Verified

- **Suite: 2027 / 2027 passing** (+11 new tests this wave: 1 schema enrichment + 1 fingerprint NUL-sniff + 2 `delete_notes` + 7 migrate).
- Cumulative `/critic` + independent `/pr` reviewer both clean (0 blocking, 0 warnings, notes addressed inline).

### Notes

- Banner refreshed from Prawduct v1.4.0 to v1.5.0 (post-sync state).
- Backlog scrub deletes the five closed entries inline per discipline rules #1 + #3 ("close-in-the-same-PR", "no inline RESOLVED scar tissue"). `docs/v11-requirements.md` F2 strike-through marks `delete_notes events.clip_id` as shipped.

## [1.3.1] — 2026-05-22

**Compose-time audit-log retrieval + W13-A v1.0 round-trip closeout + W6-K real-Live finding.** Three small focused landings (PRs #89 + #90 + #91) bundled — each closes a gap in v1.3.0's structural surfaces.

### Added — `/decisions` skill + audit-log query (PR #89, Group 2)

- **`Q.find_related_decisions(conn, song_id, *, keywords, scope=None, limit=20)`** — single `UNION ALL` across `requests.prompt_text + requests.metadata_json` and `annotations.body`, song-scoped, AND-of-keywords, most-recent-first across both sources. Each row carries a synthetic `source` column (`'request'` or `'annotation'`) so the formatter can route per-source rendering.
- **`/decisions` skill + `tools/decisions_cli.py`** — markdown-output CLI mirroring `/song-context`'s shape, `context: fork`, `user-invocable: true`. Surfaces the audit-log layer (compose-time prompts + decision rationale) that `/song-context`'s markdown ADR search couldn't reach. The two skills are complementary by design — both query `annotations.body`, but `/decisions` reads `requests` directly while `/song-context` queries the markdown ADR layer via FTS5.
- **Load-bearing convention documented**: at compose time, the LLM writes its reasoning into `requests.metadata_json.decision_rationale` (consumer surface motivates the convention).

### Added — Snapshot drift completeness (PRs #90 + #91, W13-A v1.0 round-trip closeout)

- **DB schema dual-declaration canary** — `init_db` reads `_ADDED_COLUMNS` and runs `PRAGMA table_info` per column; raises if any additive column is declared in `_ADDED_COLUMNS` but missing from `schema.sql` (or vice versa). Caught 7 real drifts immediately on rollout. Closes the structural enforcement gap surfaced repeatedly across E1 / Sweep B / Arc 4 column lifts.
- **Drift comparator fix** — post-push `probe-and-link` re-probe stopped spamming false "device drift" notes (~17 per push). Comparator was reading `class_name` (internal Live identifier) instead of `class_display_name` (the post-D4 convention the DB stores).
- **`load_in_rack_handler` symmetric post-condition** — mirrors `load_handler`'s three-shape post-condition (append / replace-in-place / no-change-error). No empirical driver in current songs; closes the structural asymmetry that would have surfaced identically if Live exhibited replace-in-place inside a rack chain.
- **`set_device_parameter` empty-list rejection** — refuses `value_items=[]` for parity with `M.create_enum_envelope`'s kwarg path (the asymmetric paper-cut from E1's Critic review).
- **`merge_snapshots` stickiness floor (G1-C)** — Python helper + CLI subcommand + `/song-snapshot` integration. Capture probes can't expose `browser_path` (Live doesn't track per-device browser origin), so refreshing via probes would silently drop the W13-A v1.0 fallback identity for every device. `merge_snapshots` carries forward sticky fields where identity matches.
- **Snapshot-write side of `resolved_path → browser_path` (E3 follow-up, PR #91).** Closes the W13-A v1.0 autonomous round-trip: `/song-pick-instruments` now captures `resolved_path` per `ableton_device(action='load')` and threads the records to `compile_snapshot(browser_paths=...)`. New `hallucinote.capture.inject_browser_paths(snapshot, loads)` writes `browser_path` into top-level device entries. `hallucinote.capture.preserve_browser_paths(old, new)` is the refresh path's preservation primitive — identity-keyed `(parent_kind, parent_index, position, class)` so swapped/moved devices drop their stale paths silently. Validated end-to-end in real Live 12: positive fallback (stale `preset_uri` + valid `browser_path` → loads) and negative fallback (bogus path → refuses with teaching error naming the missing segment).
- **Push planner: malformed-`preset_query` fallback threads `browser_path`.** Symmetry fix in `sync/push.py:_emit_device_calls` so the malformed-JSON branch (corner-of-corner, but real) doesn't silently drop the fallback identity.

### Fixed — W6-K real-Live `set_sidechain` normalized-S/C-Gain refusal (PR #91)

- **`set_sidechain(gain_db=N)` now refuses on Compressor and devices like it.** Empirical Live 12 finding (real-Live smoke 2026-05-22): Compressor's `S/C Gain` has internal range 0.0..1.0 (normalized) but displays in dB — writing `gain_db` straight to `parameter.value` trips Live's range check. Live exposes no public dB→normalized conversion (`str_for_value` exists but `value_for_str` does not). Handler pre-validates `gain_db` before any mutation; if `gain_param.min==0.0 && gain_param.max==1.0`, raises a teaching error pointing at `set_parameter` with the empirical Compressor curve (`0.0 → -inf dB`, `0.4 → 0 dB`, `1.0 → +24 dB`) for calibration. dB-native plugins (range outside 0..1) keep the existing convenience path.
- **Test fixture corrected** — `_compressor_with_routing()`'s `S/C Gain` was `min=-24/max=24` (an *assumed* dB-native shape); now `min=0/max=1` to mirror real Live. Hits the project's existing "fakes that mirror an *assumed* Live API give false confidence" learning.

### Tests

Suite: 2016 / 2016 passing (+66 from the v1.3.0 baseline at 1950). +23 from `/decisions`, +15 from G1 sweep, +25 from E3 snapshot-write, +3 from S/C Gain refusal.

### After upgrade

Re-run `/ableton-mcp-install` to refresh Live's vendored Remote Script (the S/C Gain fix lands in `set_sidechain_handler` which executes inside Live). `/mcp` reconnect alone won't pick it up — Live caches Control Surface modules at startup.

## [1.3.0] — 2026-05-22

**Arcs 5 + 6 + 7 + 7-tail: iteration-loop polish, song-author hygiene, production polish, and per-section enum-parameter envelope authoring.** Five feature PRs bundled (Arcs 5/6/7/7-tail + sun-zone-done v2 rebuild + reference-song hygiene). v1.1 requirements plan (Arcs 5-7) closed.

### Added — Arc 7-tail (E1+E2+E3, PR #85 + #86)

- **Per-section enum-parameter envelope authoring (E1).** Schema lift `device_parameters.value_items_json` carries enum cardinality at pull `detail='full'`; new mutator `M.create_enum_envelope` resolves enum-name breakpoints (`["Clean", "Heavy", ...]`) to numeric indices via DB snapshot or `value_items` kwarg escape-hatch; MCP `write_envelope` accepts `value_type='enum' | 'continuous'` mirroring `set_parameter`'s dual path. The sun-zone-done song uses this for its Amp Type Clean↔Heavy genre flips.
- **Device-load post-condition hardening (E2).** `load_handler` post-condition now accepts three success shapes: append (chain grew), replace-in-place (chain length unchanged but class at one position changed), and silent-no-op (still an error, but distinguished from real loads). Multi-position-change and chain-shrink raise distinct `RuntimeError`s. `_canonical_class_name(device)` factored so pre-load snapshot and `loaded_class_name` response use the same `class_display_name || class_name || ""` rule. `_raise_silent_noop` typed `NoReturn` so refactors can't silently fall through.
- **W13-A v1.0 instrument fallback identity (E3).** Cross-machine plugin-load portability via captured browser path. Single new column `devices.browser_path_json` carries JSON-encoded path segments — design shift from the original two-column (manufacturer + pack_name) plan since vendor/pack live at different depths across Live's browser tree. MCP `load_handler` accepts `browser_path` alongside `preset_uri`, falls back via synthesized `preset_query` on URI-walk failure, reuses the existing strict-resolution path. Load response surfaces `resolved_path` so capture flows can record automatically. Push planner emits `browser_path` alongside `preset_uri`.
- **`load_in_rack_handler` regression fix.** Empirical-Live verification surfaced that E3's refactor of `_find_browser_item` (returning `tuple[item, path]`) had updated the standalone `load_handler` callsite but missed `load_in_rack_handler` at `handlers/device.py:1695`. The `_FakeBrowser` unit-test fake was type-permissive — silently shipping the regression. Fixed the callsite AND tightened the fake with `isinstance(item, _FakeItem)` that would have caught the original. Hits the "Unit fakes that mirror an *assumed* Live API give false confidence" learning.

### Added — Arc 7 production polish (P1, P4, P5, P7) + Arc 2 / B5 (PR #84)

- **Envelope WRITE polish (P1).** `write_envelope_handler` threads `note_duration` so the note_expression branch extends its last step to note end (W7-0 clip-scoped fix in note-LOCAL coords). `sidechain_trigger` gains `envelope_start_beats` to floor the first attack window at a section boundary. Three `_emit_*_envelope` emitters (mixer / send / device_parameter) consolidate into thin shells around `_resolve_and_translate_to_session_clip` + `_emit_session_clip_envelope_post_warnings` helpers.
- **Nested-rack tombstone CTE (P4).** `_tombstone_untouched`'s device_chain / device / device_parameter SELECTs now go through a `WITH RECURSIVE` CTE so chains parented by `parent_rack_device_id` are enumerated alongside top-level chains. Recursion terminates naturally.
- **`loaded_class_name` in load response (P5).** `ableton_device(action='load')` response includes the loaded device's `class_display_name` (with `class_name` fallback) so callers can detect kind / preset_uri mismatches without a follow-up `device.list` probe.
- **W4-C strip enforced at mutator boundary (P7).** `M.create_return` / `M.update_return` strip Live's `<letter>-` slot prefix; shared helper extracted to `hallucinote/return_naming.py` so `capture.py` and `mutations.py` import from one place.
- **MCP auto-mutate (Arc 2 / B5).** MCP dispatcher auto-opens a `M.request(kind='mutate')` around `ableton_annotation` writes via `provenance.auto_request` so handlers get `_request_id` threaded automatically and emitted events carry full provenance.

### Added — Arc 6 song-author hygiene (H1-H5, PR #82)

- H1: `full-band-rock/build.py` + `solo-piano-ambient/build.py` switched to `resolve_db_path()` so per-branch DBs pick up D4's display-name ALTER.
- H2: `songs/falling-walking/tests/test_build.py` renamed to `tests/test_falling_walking_build.py` per the per-song unique-test-name convention.
- H3-H5: kit-strict guards (`assert_has(strict=True)`); negative-beats refusal at the DB mutator; minor planner doc polish.

### Added — Arc 5 iteration-loop polish (P1-P6, PR #81)

- Compose-time iteration UX polish: clip-humanize velocity-jitter via DB-as-source-of-truth (W23-B); push-cli `cleanup-default-scaffold` subcommand (W18-D) bundles the post-execute default-track cleanup; `Q.get_latest_request_for_song` + `Q.get_events_for_request` (W23-C) close the provenance reachability loop; ApplyResult.details for transparent diff after pull/push.

### Changed — sun-zone-done v2 rebuild (PR #86)

- Full rebuild from `decisions/01-intent-and-theme.md` (the user's brief). New decisions docs 02-06; new build.py with monolithic 256-beat Rhythm Gtr clip hosting the Amp Type envelope (the structural fix for Live 12.4 LOM's clip-coverage requirement on `device_parameter` envelopes — one envelope per `(device, parameter)`, must be hosted by a clip covering the envelope's full beat range; ONE long clip is the structural answer). Other tracks (drums / bass / organ / lead) use per-section clips for compose-time convenience. Empirical-Live verified: all 10 push phases ok including `envelopes 1/1`; envelope round-trip from Live matches authored breakpoints exactly.

### Changed — reference-song hygiene sweep (PR #86)

- W4-C convention sweep: snapshots in falling-walking / full-band-rock / solo-piano-ambient updated to use stripped return names (`"Reverb"` not `"A-Reverb"`, etc.) in both `returns[].name` and every track's `sends` map keys. Module-level `pytest.mark.filterwarnings` on `tests/unit/capture/test_capture.py` for fixtures that legitimately use prefixed names (the dedicated warn test uses `pytest.warns()` which overrides the filter).

### Fixed

- Mutator boundary now strips W4-C return-name prefix (P7); previously only the capture layer stripped, leaving a hand-authoring trap if `M.create_return` was called directly.
- `load_in_rack_handler` tuple-unpack regression (above).
- `pre-v1-walkthrough.md`-style canary friction-log comments removed from the three reference songs' build.py / tests.

### Tests

Suite: 1950 / 1950 passing (+46 from the v1.2.0 baseline at 1904). Per-song tests: falling-walking (5), full-band-rock (3), solo-piano-ambient (3), sun-zone-done (4 incl. the restored idempotency regression test). Empirical-Live round-trip verifications closed for both E1 (sun-zone-done Amp Type envelope) and E2 (load post-condition across 27/27 device loads).

### After upgrade

Re-run `/ableton-mcp-install` to refresh Live's vendored Remote Script (Arc 7-tail E1/E2/E3 ship new MCP wire shapes — `value_type='enum'`, `browser_path`, `loaded_class_name` — that need both halves of the bridge in sync).

## [1.2.0] — 2026-05-22

**Arcs 2 + 3 + Arc 4 / D4: composer-intent layer, compose-time validation R-2 follow-ons, and the structural display-name shift.** Four landings bundled (Arc 2 + Arc 3 + sqlite hotfix + Arc 4 / D4) because each ships a small focused piece and the project has no consumers yet — releasing one minor-bump cuts the cadence overhead.

### Added — Arc 2 (composer intent)

- **`ableton_annotation` MCP tool** (add / list / get_at_bar / update / delete) wrapping the W8-C annotations table + mutators. Closes the storage-without-affordance gap from W8-C — compose-time agents can read AND write annotations during a session instead of shelling out to a 3-line Python invocation. Per-song DB resolution via `resolve_db_path`; teaching errors on unknown slug / track / annotation_id.
- **Provenance rationale columns on `requests`** — `prompt_text` (verbatim seed prompt), `parent_id` (self-FK so child cycles chain to enclosing parents), `metadata_json` (`{model, git_sha, branch, hostname, ...}`). Idempotent column migration via the existing `_ensure_added_columns` pattern.
- **`M.provenance_metadata()` helper** — best-effort git/socket probes with `subprocess.check_output` 2-second timeout caps. Failed probes drop the key rather than raising.
- **`build_session` auto-captures provenance** + accepts `prompt_text` / `parent_id` / `metadata` kwargs that thread to `create_request`. Caller-provided metadata overrides auto-captured.
- **`push_execute.py` and `pull_cli.py` thread `metadata=provenance_metadata(...)`** on their `create_request` calls — every push/pull cycle has full attribution for free.
- **`/song-context` defensive + generative modes** — `--defensive` flags rows with negation/constraint language; `--generative` surfaces tag-related rows under a "Related context" header. Single SQL `LIKE` pass for v1.2; semantic search is v1.3+.
- **`allow_version_mismatch` envelope param** on the MCP wire — per-call bypass for dev-loop introspection when server/Remote-Script version drift exists. Strict-by-default; bypass attaches a warnings advisory naming the data-corruption risk.

### Added — Arc 3 (compose-time validation R-2 follow-ons)

- **`compat check --probe`** — orchestrates `ableton_browser(action='search')` in-process via the MCP TCP client for every unique structurally-valid `preset_query`, populates `browser_dry_runs`, feeds it to `check_song`. Closes the R-2 follow-on that left the CLI orchestration on the backlog. Failed searches raise loud (a partial map = false-clean report).
- **`preset_query` path-shape syntactic sugar** — `M.create_device(preset_query=...)` accepts either the canonical dict OR a path string like `"Drums/Kit-Core 909"` (case-insensitive root, `" "` ≡ `"_"`, last segment is pattern). New top-level `src/hallucinote/preset_query.py` with `BROWSER_ROOTS` constant + `parse_path_shape` + `normalize`. DB always stores canonical dict so downstream consumers see one shape.
- **`pull_cli execute <domain> <session_id>`** — collapses the historical plan → file → probe → file → apply dance into one in-process pass. Generic across all 10 `_DOMAINS`; the "clear diff" comes free via `ApplyResult.details`. Same `kind='pull'` request provenance envelope as `_cmd_apply`.

### Changed — Arc 4 / D4 (structural display-name shift)

- **`devices.kind` semantics flip from internal class name to browser display name.** Pull writes Live's `device.class_display_name` here (e.g. `"Compressor"` / `"Drum Rack"` / `"Phaser-Flanger"`). The loader matches `kind` directly against Live's browser tree — kind-as-given walk, no translation. Live's internal class names (`Compressor2`, `DrumGroupDevice`, `PhaserNew`, etc.) no longer resolve.
- **New `devices.class_name` column** (nullable; informational) carries Live's internal class identifier. Drives plugin discrimination (compat-check tests this for the third-party wrapper family `{PluginDevice, AuPluginDevice, Vst3PluginDevice}`). REQUIRED on hand-authored snapshots for third-party plugins — silent mis-classification risk if omitted.
- **MCP capture probes** (`device.list` / `info` / `get_device_chains`) return `class_display_name` alongside `class_name`.
- **Snapshot schema convention shift**: `class` field is now the browser display name; new optional `class_name` field carries the internal class. Five `captured_session.json` files migrated; `docs/snapshot-schema.md` + `docs/song-authoring-conventions.md` rewritten with the post-D4 examples.

### Deleted — Arc 4 / D4

- **`_CLASS_TO_DISPLAY` translation table** (and `class_name_to_display` + `strip_device_suffix`) — Live exposes the right value natively via `device.class_display_name`. The static table was reinventing a Live API attribute and required maintenance per built-in rename in every new Live version. `browser_root_for_rack_kind` survives (W7-0 cross-category protection is independent).

### Fixed

- **`ableton_annotation` handler crashed Live's Remote Script load** — the handler imported `sqlite3` at module top, but Live 12.x's embedded Python ships without the `_sqlite3` C extension. Cascade aborted the entire Hallucinote Control Surface load (Live shows the surface in the dropdown but the MCP bridge on `127.0.0.1:9878` never starts). The `sqlite3` reference was dead code under `from __future__ import annotations` (lazy type-string annotations); removed. New AST-based regression test in `hallucinote_mcp/tests/unit/test_remote_script_import_safety.py` walks the Remote Script load chain and refuses top-level imports of stdlib modules known absent from Live's embedded Python.

### After upgrade

Re-run `/ableton-mcp-install` to refresh Live's vendored Remote Script (the new `class_display_name` probe field and the sqlite hotfix both ship there).

### Tests

Main + MCP suite 1848 passing (was 1788 at v1.1.0).

## [1.1.0] — 2026-05-21

**Arc 1: Drum Rack pad-mapping discovery + push-loop residuals.** Closes the **Hot Rod Kit cautionary tale** structurally — sun-zone-done's metal sections clanged on cowbell because GM-default ride at note 51 lands on Hot Rod's "Cowbell Fenk Chick" pad. Composition now fails loudly at compose time when a kit can't deliver a canonical pad, instead of silently playing the wrong sound.

Initial Arc 1 plan covered seven chunks (A1-A7); code audit on 2026-05-21 identified five chunks as already shipped in v1.0 (A1 via W18-A/B, A2 via W20-A, A4 in `create_song`'s by-name lookup, A6 via W18-E, A7 in `ableton-push/SKILL.md`). The four remaining chunks ship here: A3 (the substantive one) + A1-resid + A2-resid + A5.

### Added

- **`Kit.try_pitch_of(canonical_name) -> int | None`** — optional drum-pad resolver. Returns `None` when the kit has captured chains but no chain matches the canonical name. Use when composition can react to pad absence (e.g., "drop the ride pattern if this kit has no ride").
- **`Kit.assert_has(*canonical_names)`** — bulk fail-fast validator. Refuses at composition start when the kit can't deliver every required pad.
- **Auto-population of `drum_pad_mappings`** — `push_cli execute` walks every linked Drum Rack after the devices phase and dispatches `pad_info` to capture the kit's actual chain layout. Runs on both phase-OK and phase-SKIPPED (so re-pushes with W20-A device idempotency still trigger pad capture). Best-effort: per-Drum-Rack failures count via new `PhaseOutcome.pad_probes_ok` / `pad_probes_failed` fields but don't halt the phase.
- **`push_cli execute --no-coherence-check`** — visible opt-out flag for the coherence check (previously the silent default when neither `--probe` nor `--snapshot` was passed). The argparse mutex group is now required so the safety net can't be skipped by accident.
- **`Q.get_linked_drum_racks_for_session`** — direct DB-layer query returning every Drum Rack with its MCP-addressing for the post-phase walker.

### Changed

- **`Kit.pitch_of` now raises** on the **wrong-sound case** — kit has captured mappings but no canonical-name match, AND the GM-default note is taken by a differently-named chain. The exception message names the colliding chain and points at `try_pitch_of` as the safe alternative. The empty-pad-slot fall-through case (GM-default points at a Live empty pad on this kit, playing silence) stays warn-and-fall-through. This is a behavior change — songs that previously got a wrong-sound substitution with only a warning will now refuse to build. Update those `build.py` files to use `try_pitch_of` or pick a different kit.
- **`browser.load_item` no-append error** — `ableton_device(action='load')` failure due to a silent no-op now enumerates the parent's existing chain (`[index:class_name, ...]`) so diagnose-and-fix doesn't need a separate `ableton_device(list)` probe. The misleading "instrument on a return" hint is preserved only for return-parent calls (where it's actually structural).
- **`push_cli execute` FAIL summary** — appends the verbatim recovery command on partial / connection_lost exit, so the agent doesn't have to reassemble flags from the help text.

### Fixed

- **Hot Rod Kit cowbell-on-metal failure** — closed structurally per the Changed section above. The Kit class's three resolution paths (`pitch_of` raises / `try_pitch_of` returns None / `assert_has` bulk validates) let composers express the right intent for each part.

### Documentation

- **`.claude/skills/ableton-push/SKILL.md`** — new "Recovering from partial push" subsection naming the structural diagnose → fix → rebuild → re-run loop. No `--resume` flag — W20-A's device-binding idempotency makes re-run the right structural recovery.
- **`docs/song-authoring-conventions.md`** — new "Drum kits: probe, don't assume" subsection documenting the three resolution paths and the cowbell-on-metal cautionary tale.
- **`docs/v11-requirements.md`** — v1.1 planning document with audit-corrected Arc 1 scope (Already shipped table + remaining residuals).

### Backlog items closed

Hot Rod Kit cautionary tale · Drum Rack pad-mapping discovery · Push planner duplicates devices on re-push (retroactively reconciled — W20-A confirmed) · `browser.load_item` misleading "instrument on a return" hint · Partial push has no documented resume path.

### Tests

Main suite 1788 (+30 from v1.0.1) + MCP suite 664 (+3 from v1.0.1) = 2452 passing, 0 failed.

## [1.0.1] — 2026-05-21

**Push reliability polish.** Closes eight backlog items surfaced during
the sun-zone-done iteration session — all small, additive, and
backwards-compatible. The compose → push loop no longer halts on cues
the second time around, and two compose-time author traps that cost
11 of 13 push failures in sun-zone-done now classify cleanly in the
compat report.

### Added

- **`ableton_arrangement(cue_create | cue_create_batch)`** —
  `if_exists` parameter (`"refuse"` for single calls, `"skip"` for the
  batch default). `plan_push_cue_points` emits `if_exists="skip"` so
  re-pushing the same DB no-ops the cues phase instead of failing
  on every cue with "a cue already exists at position_beats=0.0".
- **`push_cli cleanup-default-scaffold <session_id>`** — single-command
  cleanup of Live's brand-new-set defaults (`1-MIDI` / `2-MIDI` /
  `3-Audio` / `4-Audio`, `A-Reverb` / `B-Delay`) after a first push.
  Pure planner `push.plan_cleanup_default_scaffold` refuses on
  non-canonical unmatched parents (user hand-resolves) and on "would
  empty Live tracks" (Live's ≥1-track constraint). CLI dispatches in
  descending index order, then re-runs `probe_and_link` to reconcile
  shifted indexes. Replaces the prior 6+ hand-issued MCP-call workflow.
- **`compat.classify_preset_query()`** — structural validation for
  `preset_query.root` (must be in the loader-accepted enum) and
  `path_prefix` (must be a list). `check_song` accepts an optional
  `browser_dry_runs` map; structurally-valid queries classify as
  `kind_unresolvable` (0 browser matches), `kind_ambiguous` (2+
  matches), `preset_query_unverified` (no dry-runs provided), or
  fall through on 1 match. Four new `DeviceStatus` values, all flagged
  by `has_issues`. Lock-test against `hallucinote_mcp.actions.browser._ROOTS`
  prevents enum drift between the two sides.

### Changed

- **`docs/snapshot-schema.md`** — consolidated authoring-trap pass:
  documents loader's class-or-display-name dual accept (with the
  `Glue` / `Glue Compressor` failing case named); `kind` field as
  informational only (the loader ignores it); `preset_query.root`
  enum enumerated inline with the `effects` vs `audio_effects` typo
  callout; `path_prefix` must-be-list rule with wrong/right examples;
  "default device vs named preset" subsection with worked examples
  of each shape.
- **`format_requirements_md`** surfaces preset_query authoring issues
  in a dedicated section so authors see them alongside missing-plugin
  classifications.

### Fixed

- **Re-push idempotency on the cues phase** — same-name same-position
  cues now no-op with `skipped=true`; name mismatch still refuses so
  rename intent goes through `cue_rename` explicitly.
- **`test_apply_device_parameters_property_round_trip`** —
  `@settings(deadline=None)` to suppress a pre-existing hypothesis
  `FlakyFailure` surfaced under parallel xdist contention. The test
  checks correctness, not timing.

### Backlog items closed

Cue idempotency · default-scaffold cleanup · default-scaffold first-push
offer · snapshot-schema preset_query gaps · `kind` field documented ·
default-vs-named preset doc · class-vs-display-name doc · compat
preset_query validation.

### Tests

Main suite 1758 (+31 from v1.0) + MCP suite 661 (+8 from v1.0) =
2419 passing, 0 failed.

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
- Removing a device **sidechain source in Live** needs a full (fresh-DB)
  rebuild, not an incremental one: replay treats a snapshot that omits a
  device's sidechain source as "no opinion" (so a `build.py`-authored
  source survives), so it will not clear a source you deleted in Live.
  Clear it via a fresh-DB rebuild, `set_device_sidechain(None)` in
  `build.py`, or an explicit null source in the snapshot.
- Linux is documented as unsupported for v0.9 (Live itself doesn't
  ship a Linux build). Wine/CrossOver paths get a best-effort install
  candidate with warn-and-confirm.

---

_Historical context._ v0.9.0 is the first formally tagged release. Pre-
tag work shipped through Waves 0–15 across `main` / `develop` between
project inception and the V1 cumulative merge (commit `f4b6d58`,
2026-05-20). Detailed wave-by-wave history lives in the git log
(the original `docs/v1-build-plan.md` was removed after the V1 merge,
per the post-merge build-plan cleanup). The v1.0 CHANGELOG entry absorbed
v0.9's content + the v1.0 additions (W11, W13-A, W16-A, release-prep R-1
exhaustive Critic sweep).
