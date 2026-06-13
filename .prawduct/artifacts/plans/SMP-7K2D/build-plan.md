# SMP-7K2D — Build Plan (sample-instrument + playback-parameter model)

Design: `.prawduct/artifacts/plans/SMP-7K2D/design.md`. Cluster keystone for the
swell buried-"we" centerpiece (siblings ENV-4S2K, AUD-7R3M, AST-6D3K — re-triaged
into this plan; see design §"Per-item disposition").

**Critic mode:** cumulative at PR (per the small-chunk cadence preference); chunk
Critic optional per chunk if a chunk lands a schema surface.

**Context (cross-session handoff):** Direction approved by the user 2026-06-13
("do this right, no intermediate state; reverse is a playback param"). Live was
occupied by another agent, so the probe (chunk 0) is pending and the probe-gated
push chunks (3, 4) are blocked. Reverse is delivered as a playback parameter, not
a derived asset (AST-6D3K demoted to a possible hidden push fallback only).
**Done 2026-06-13 (no-Live):** chunks 1 + 2 — the playback-parameter DB model
(`devices.audio_file` + `clips.reverse`) with additive migrations, mutator
support, snapshot replay encoding, and regression tests. Full suite green (3499).
NOT yet committed/Critic'd (working tree also carries AUD-2N6K + the incoming-bugs
re-triage from earlier this session). **Next no-Live:** chunk 5 (ENV-4S2K lock).
**Blocked on Live/probe:** chunks 0, 3, 4.

## Status

- [ ] **0 — Capability probe** (Live; gates 3, 4) — sample-assignment mechanism + window/reverse co-expressibility
- [x] **1 — `devices.audio_file` DB model** (no-Live; keystone foundation) — schema + `_ADDED_COLUMNS` migration + canary + `create_device(audio_file=)` + event + `_replay_devices` encoding + 6 tests
- [x] **2 — `clips.reverse` DB model** (no-Live; AUD-7R3M audio-clip path) — schema + migration + `create_audio_clip(reverse=)` + `_validate_audio_fields` + `_AUDIO_CLIP_UPDATE_FIELDS` + 3 tests
- [ ] **3 — Sample-instrument push** (Live; gated on 0)
- [ ] **4 — Reverse push** (Live; gated on 0)
- [ ] **5 — ENV-4S2K lock** (no-Live; confirmation test + ordering doc)

## Chunk 0 — Capability probe (Live; gates 3, 4)

**Deliverable:** a probe-results note (append to `docs/research/audio-first-class/lom-probe-results.md`
or a sibling) recording, with live evidence:
- How a sample assigns to Simpler/Sampler via LOM (`browser.load_item` on an
  audio BrowserItem vs a device-then-set-sample path), and whether an arbitrary
  `assets/` file is reachable (BrowserItem addressability — CLP-AUD2 caveat).
- Full Simpler AND Sampler playback surface: presence + automatability of
  `Reverse`; coexistence with automatable `S Start`/`S Length`; and whether
  Live's audio-clip reverse is LOM-settable.

**Acceptance:** the two open questions in design §"Open questions" answered with
probe evidence; push mechanism for chunks 3/4 selected and recorded.

**Done when:** results recorded; design §"Push design" branch chosen.

## Chunk 1 — `devices.audio_file` DB model (no-Live; keystone foundation)

**Deliverable:**
- `devices.audio_file TEXT` (nullable) in `schema.sql` + an additive migration in
  `init_db` (ALTER TABLE … ADD COLUMN if absent — `feedback_open_song_db_via_init_db`).
- `create_device(..., audio_file: str | None = None)` persists it + emits the
  paired event (mutator discipline). Stored exactly as authored (no resolution at
  write — resolution is a push-time concern, like `clips.audio_file`).
- `capture._replay_devices` reads an optional `audio_file` key from the device
  dict and threads it to `create_device`; `capture_plan`'s device probe emits it
  (the probe READ value is Live-side, but the encoding/replay path is no-Live and
  testable with synthetic dicts).
- Snapshot device-dict shape documented (the `audio_file` key) alongside the
  existing `{index, class, name, class_name?, preset_query?, params_dialed?, …}`.

**Acceptance:** a synthetic snapshot device dict with `audio_file` replays into a
`devices` row carrying it; a hand-authored `create_device(audio_file=…)` persists
+ emits an event; legacy DBs (no column) upgrade via `init_db`; full suite green;
a song rebuilds with `--reset`.

**Done when:** tests cover create+event, replay encoding, and the migration;
`grep` shows `audio_file` resolution reuses `paths.resolve_audio_path` at the
push seam (not duplicated). Boundary surface (schema) updated per
`boundary-patterns.md`.

## Chunk 2 — `clips.reverse` DB model (no-Live; AUD-7R3M audio-clip path)

**Deliverable:**
- `clips.reverse INTEGER` (nullable; 0/forward default) in `schema.sql` + the
  init_db additive migration.
- `mutations.clips` audio-field support: accept/validate `reverse` (sibling to
  `warping`; only valid on `kind='audio'`, NULL on MIDI — the existing
  `_validate_audio_fields` dual-layer guard).
- `create_audio_clip` (CLP-AUD1) accepts `reverse`.

**Acceptance:** an audio clip authored with `reverse=1` persists + round-trips;
a MIDI clip rejects/ignores `reverse` per the kind-guard; migration upgrades
legacy DBs; full suite green.

**Done when:** mutator tests cover the kind-guard + event; schema surface updated.

## Chunk 3 — Sample-instrument push (Live; gated on chunk 0)

**Deliverable:** the device-load push phase (`sync/push/devices.py`) materializes
a sample-bearing device — resolve `audio_file` via `paths.resolve_audio_path`,
then the probe-selected mechanism (browser-load the audio item, or load-device +
assign-sample). Capture round-trips a hand-placed sample-instrument back into the
snapshot.

**Acceptance:** a `build.py` authoring a Simpler-with-assigned-sample part pushes
to Live and the instrument plays the sample; re-push is idempotent; `/song-snapshot`
round-trips it. (Operator-verified — enqueue in `operator-verification.md`.)

**Done when:** live-verified; idempotent re-push confirmed.

## Chunk 4 — Reverse push (Live; gated on chunk 0)

**Deliverable:** reverse honoured at push — `clips.reverse` → Live clip reverse
(if LOM-settable), and/or the sample-instrument `Reverse` device-param path. The
hidden deterministic materialization fallback (design §"Push design") **only if**
chunk 0 proves window+reverse aren't co-expressible.

**Acceptance:** a declared reverse plays reversed in Live; if the fallback is
needed, it's deterministic + content-addressed + uncommitted + invisible to the
author. swell can author the forward→centre→reverse fold and flip its direction
with no hand-managed audio files. (Operator-verified.)

**Done when:** live-verified; no committed derived binary in the repo.

## Chunk 5 — ENV-4S2K lock (no-Live; confirmation + doc)

**Deliverable:**
- A unit test against the pure planner (`classify_envelope_route` /
  `_route_for_host_kind`) confirming a `device_parameter` envelope on a MIDI
  track covered by its session clip routes to `session_clip` (sample-accurate),
  NOT `perform` — pinning the property ENV-4S2K depends on.
- A one-line authoring-discipline note (conventions guide): a one-shot device
  param (window/reverse) must carry a breakpoint at/just-before the trigger
  note-on so the phrase plays with its own settings, not the previous phrase's.

**Acceptance:** the route test is green and would fail if the device-param clip
route regressed to perform; the doc note exists.

**Done when:** test green; conventions guide updated; ENV-4S2K narrowed in the
backlog to "semantic-addressing sugar, rule-of-three" with this lock recorded.
