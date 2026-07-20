# BAK-7D2V — Pull durability: close the general pull→replay silent-revert hole

`stage: design` · 2026-07-04 · successor to the BAK-3M9T umbrella (its "Option 1 —
one durable bake" decision STANDS and this design operates inside it; see
[`../BAK-3M9T/requirements.md`](../BAK-3M9T/requirements.md))

## The hole (verified in code)

"The DB and Ableton agree, always" is false in one specific, work-destroying way:

1. `pull_cli apply` / `execute` writes live edits into the DB
   (`src/hallucinote/sync/pull_cli.py` — `M.create_request(kind="pull",
   actor="sync")` → `pull.apply_pull_results(actor="sync")`, inside
   `transaction`).
2. Nothing in `sync/` ever writes those edits back to `captured_session.json`.
3. The next `build.py` run calls `replay_capture(captured_session.json)`
   (`src/hallucinote/tools/templates/song/build.py.tmpl`), whose mutators are
   upsert-shaped — they **re-assert the stale snapshot's values over the pulled
   rows**, silently.
4. Both pull and replay write as `actor='sync'` (the template hardcodes
   `actor="sync"`; pull_cli hardcodes `actor="sync"`), so the actor-precedence
   machinery (`db/mutations/build.py` — `_latest_actor_for` /
   `_LATEST_ACTOR_EVENTS`) **cannot see the conflict**: to it, sync overwrote
   sync. The claim in
   [`authorship-model.md`](../../authorship-model.md) §"One source of truth"
   that "code vs snapshot is not a new conflict — it's the existing actor
   precedence" misses exactly this failure mode (that artifact now carries a
   correction pointing here).

The only defense before this item was an unenforced manual ritual ("remember to
re-capture before you build").

## Direction constraint (inherited, not re-litigated)

BAK-3M9T's user decision: **one durable bake** — `captured_session.json` is the
single durable home of the mix layer; `/song-snapshot` (capture) is THE mix
bake; `/ableton-pull` is a build.py-staging / drift-detection primitive, *not*
a parallel mix bake. This design must make pulled live edits durable **within**
that shape.

## Alternatives considered

### A — pull-apply writes through to `captured_session.json` (REJECTED)

After applying probe results to the DB, project the same mutations into the
snapshot file. Rejected because:

- It requires a **second serializer** (DB-diff → snapshot JSON) that must
  mirror `compile_snapshot` / `assemble_snapshot_via_probes` field-for-field
  forever — a standing drift hazard (the snapshot carries probe-only facts
  like `browser_path`, `value_items`, preset `param_overrides` that a DB diff
  can't regenerate; a partial rewrite risks corrupting exactly the fields the
  stickiness machinery in `merge_snapshots` exists to protect).
- Pull spans domains the snapshot intentionally does NOT model (clip-notes,
  envelopes, arrangement, cue points) — write-through would be partial, giving
  a *mixed* durability story that is worse to reason about than a crisp one.
- It quietly re-crowns `/ableton-pull` as a mix bake, reversing BAK-3M9T's
  decision that capture is the one durable bake.

### B — actor separation: `actor='pull'` vs `actor='sync'` (REJECTED as the fix; the provenance idea survives in cheaper form)

Add `'pull'` to `ACTORS`, have pull write `actor='pull'`, and teach
`replay_capture` per-row arbitration: skip re-asserting a row whose latest
event is a pull newer than the snapshot. Rejected because:

- It makes the revert *not happen* but leaves the pulled state living **only in
  the regenerable, git-ignored DB** — lost on a clean rebuild / DB delete, and
  permanently divergent from the committed snapshot. That is precisely the
  state BAK-3M9T acceptance criterion 3 forbids ("no bake surface writes ONLY
  the regenerable DB and calls it baked"). Silent per-row skips also hide the
  divergence instead of surfacing it.
- It touches the actor model everywhere (`ACTORS`, tombstone-eligibility in
  `_delete_build_owned`, every `_LATEST_ACTOR_EVENTS` consumer) for a fix whose
  end state is still wrong.
- The *detection* half of this idea is real, but we get it **without touching
  the actor model**: pull writes are already perfectly attributable via
  `requests.kind='pull'` (`pull_cli` opens a request per apply and threads
  `request_id` into every emitted event). The events⋈requests join is the
  actor separation, for free.

### C — enforced staging + one durable bake (CHOSEN)

Keep the architecture BAK-3M9T chose and make the ritual **structural**:

- **Pulled DB state is staging, by definition.** Its durable home is either
  `build.py` (for build-owned domains the human folds in — clip-notes,
  arrangement) or a fresh capture of `captured_session.json` (for mix
  domains). This is already the documented model (`/song-snapshot` SKILL.md,
  BAK-3M9T Chunk D); what's missing is enforcement.
- **`replay_capture` refuses to run over newer pulled state** (the guard —
  shipped in this item's Chunk 1, below). The refusal names the at-risk rows,
  the durable fix (re-capture), and the conscious-revert override. The guard is
  not a temporary shim: in the end state it *is* the replay-side contract that
  makes "DB and snapshot agree" checkable instead of aspirational.
- **The snapshot carries `captured_at`** (stamped by `compile_snapshot`, i.e.
  both the agent-orchestrated `/song-snapshot` path and `capture_cli execute`),
  which is the guard's comparison anchor and the thing a fresh capture updates —
  so *the bake itself disarms the guard*, closing the loop with zero extra user
  steps beyond the workflow that was always the right one.
- **Pull-side UX names the contract** (Chunk 2): after a mix-domain apply,
  pull_cli prints the durability notice ("this landed in the regenerable DB;
  bake with /song-snapshot or it blocks/reverts on the next build"), and the
  `/ableton-pull` skill text is finished per BAK-3M9T Chunk D.

Why C wins: it is the only option where the durable artifact, the DB, and the
enforcement all point at the same single serializer (capture) — no second
write path, no divergent-but-alive DB state, and the failure mode converts
from *silent data loss* to *loud, actionable refusal*.

## The guard (Chunk 1 — shipped with this design)

### Signal: "sync-actor rows newer than the snapshot"

Cheapest reliable discriminator, verified against the schema:

- Every pull apply runs under a request row with `kind='pull'`
  (`pull_cli.py`), and every mutator it calls `_emit`s an event carrying that
  `request_id`, the `song_id`, and a `ts` defaulting to
  `strftime('%Y-%m-%dT%H:%M:%fZ','now')` (`db/schema.sql` events table).
- So: `events e JOIN requests r ON r.id = e.request_id WHERE r.kind='pull' AND
  e.song_id = :song AND e.kind IN (replay-asserted kinds) AND e.ts > :captured_at`.
- **Kind filter** (`_REPLAY_ASSERTED_EVENT_KINDS` in `capture.py`): only event
  kinds for state `replay_capture` actually re-asserts (track/return identity +
  mixer, sends, device chains/devices/params/param-overrides/sidechain, chain
  props, **including `device_chain_deleted`** — see the audit below). Pulled
  state replay *cannot* revert — clip-notes, envelopes, tempo map, cue points,
  arrangement, track routing, tuning (`tuning/pull_cli.py` also opens
  `kind='pull'` requests) — never trips the guard. This is what keeps ordinary
  build.py-staging pulls (the sanctioned use of `/ableton-pull`) unbricked.
- Dry-run pulls roll back their request + events (`_DryRunRollback`), so they
  leave no signal — correct.

### Kind-set audit (Critic-driven re-audit, 2026-07-04)

The Critic found the original tuple missed **pulled nested-rack-chain
deletions**: removing a chain inside a Rack in Live and pulling `devices` /
`nested-rack-chains` calls `M.delete_device_chain`
(`sync/pull/devices.py:1019`), which emits ONLY `device_chain_deleted` — the
cascade removes the chain's nested devices with **no per-device events** — and
`_replay_rack_chains` unconditionally recreates every snapshot-declared chain.
Guard didn't fire; deletion silently reverted. Fixed by adding
`device_chain_deleted`, then re-auditing the whole tuple.

**Method:** enumerate every mutator any pull apply handler can call
(`grep -o 'M\.[a-z_]*(' src/hallucinote/sync/pull/*.py`, all domains +
`tuning/pull_cli.py`), map each to the event kind(s) it emits, and mark
whether `replay_capture` re-asserts that state — if yes, the kind MUST be in
the tuple. Cascade-deleting mutators were checked specifically for whether the
parent event is the only signal. Re-run this audit whenever a pull apply
handler is added or replay's write surface grows.

| Pull-called mutator (sync/pull/) | Event kind(s) | Replay re-asserts? | In tuple |
|---|---|---|---|
| `set_track_mixer` (mix.py) | `track_mixer_set` | yes (mixer) | ✅ |
| `update_return` (mix.py) | `return_updated` | yes (returns) | ✅ |
| `set_send_level` / `remove_send` (mix.py) | `send_set` / `send_removed` | yes (sends) | ✅ |
| `create_device_chain` (devices.py) | `device_chain_created` | yes (chains) | ✅ |
| **`delete_device_chain` (devices.py:1019)** | **`device_chain_deleted`** (cascade: nested devices die event-less — sole signal) | **yes** — `_replay_rack_chains` recreates every snapshot chain | ✅ **added by this audit (the BLOCKING gap)** |
| `create_device` / `delete_device` (devices.py) | `device_created` / `device_deleted` | yes (devices) | ✅ |
| `set_device_parameter` / `remove_device_parameter` (devices.py) | `device_parameter_set` / `device_parameter_removed` | yes (params) | ✅ |
| `set_device_sidechain` (devices.py) | `device_sidechain_set` | yes | ✅ |
| `set_chain_properties` (devices.py) | `device_chain_props_set` | yes (choke/out_note/chain mixer) | ✅ |
| `set_track_routing` (mix.py) | `track_routing_set` | **no** — replay does not ingest track routing (capture reads device *input* routing only, which lands as `device_sidechain_set`) | correctly excluded |
| `add/update_tempo_point`, `add/update_time_signature_point` (mix.py) | `tempo_point_*` / `time_signature_point_*` | no — score-half is build.py-owned; replay never writes it | correctly excluded |
| `add_cue_point` / `remove_cue_point` (score.py) | `cue_point_added/removed` | no | correctly excluded |
| `update_clip` / `delete_clip` / `remove_arrangement_clip` (clips.py) | `clip_updated/deleted` / `arrangement_clip_removed` | no — replay ignores clips/arrangement | correctly excluded |
| `update_note` / `insert_notes` / `delete_notes` (notes.py) | `note_updated` / `notes_inserted` / `notes_deleted` | no | correctly excluded |
| `delete_envelope` / `replace_breakpoints` (envelopes.py) | `envelope_deleted` / `breakpoints_replaced` | no — replay does not ingest envelopes | correctly excluded |
| tuning pull (`tuning/pull_cli.py`) | `song_tuning_set` | no — replay does not touch tuning | correctly excluded |

Kinds in the tuple that pull currently never emits (`song_created/updated`,
`track_created/updated`, `return_created`, `device_param_overrides_replaced`,
`drum_pad_mappings_replaced`) are harmless over-coverage: the request-kind
join gates first, so they can never trip a non-pull cycle, and they
future-proof against pull growing those writes. Pull deletes no tracks or
returns today, so `track_deleted` / `return_deleted` have no pull emitter; if
pull ever gains those deletes, this audit's method flags the addition.

### Timestamp: `captured_at` on the snapshot

- The snapshot did **not** carry a capture timestamp (`compile_snapshot`
  emitted only `snapshot_version` + content). Added: `captured_at`, UTC ISO in
  the exact `events.ts` format (`YYYY-MM-DDTHH:MM:SS.mmmZ`) so a lexicographic
  string comparison is a correct chronological comparison against event rows.
  The shape check is a **fullmatch** on exactly that format: a
  timezone-*offset* stamp (`...T14:34:56+02:00`) can compare up to +14h ahead
  of the equivalent UTC instant and would silently defeat the guard, so any
  non-exact form (offset, missing millis, garbage) takes the conservative
  legacy/warn path instead of being compared.
- Stamped in `compile_snapshot` — the single assembly point used by both
  `assemble_snapshot_via_probes` (capture_cli execute / `/song-snapshot`) and
  any hand-orchestrated `capture_plan` assembly. `merge_snapshots` takes `new`
  as base, so the fresh stamp survives the `/song-snapshot` merge step.
  `diff_snapshots` diffs named fields only, so the stamp adds no diff noise.
- `migrate_snapshot` deliberately does **NOT** back-stamp `captured_at` on a
  legacy file: stamping "now" onto content captured at an unknown earlier time
  would assert the snapshot is newer than pulls it doesn't contain — silently
  defeating the guard. Only a real capture may stamp.
- Hand-authored snapshots (`/song-pick-instruments` composer-time authoring)
  may set `captured_at` to authoring time; absent, they get legacy handling.

### Refuse / warn matrix (as shipped)

| Snapshot | Newer pull-attributed replay-asserted events? | Behavior |
|---|---|---|
| any | none | proceed silently (no pull ever happened, or all pulls predate the capture / were re-baked) |
| stamped `captured_at` | yes | **raise `StaleSnapshotError`** before any mutation — names the newest offending events, the durable fix (re-capture via `/song-snapshot` or `capture_cli execute`), and the override |
| stamped, override given | yes | proceed with a `UserWarning` naming how many pulled changes are being reverted |
| legacy (no / unparseable `captured_at`) | yes (any pull-attributed replay-asserted events at all — no ordering possible) | **`UserWarning`, proceed** — points at re-capture to stamp |

- **Override:** `replay_capture(..., allow_stale_snapshot=True)`; the scaffolded
  `build.py` template exposes it as `--force-replay`. Existing songs' build.py
  predate the flag — the refusal message therefore names the *parameter* first
  and the flag as the scaffolded spelling.
- **Legacy warns instead of refusing — rationale:** a legacy snapshot carries
  zero ordering evidence, so refusal would fire on *every* previously-pulled
  song forever regardless of actual risk (most dogfood songs have old pull
  requests that long predate their current snapshot). A permanent false alarm
  teaches users to reach for `--force-replay` habitually, which destroys the
  guard's value for the real case. The loud warning migrates the fleet: the
  next real capture stamps the file and the hard refusal takes over.
- **A forced replay does not disarm the guard** (the pull events remain newer
  than the still-stale snapshot), so it fires on every subsequent build until a
  re-capture. Intentional for an interim guard: the durable fix is the bake;
  forcing is per-run consent. The message says so explicitly. (The full fix's
  Chunk 2/3 may add a "replay-superseded" disarm if the nag proves costly; see
  Open refinements.)

### Known imprecisions (accepted for the interim guard, documented)

- *Pull → hand-revert in Live → capture shows no diff*: guard stays armed even
  though replay would now be value-identical. Rare.

  **RESOLVED — and the resolution reversed this section's original proposal.**
  As designed, this corner's exit was `--force-replay`, with a *re-stamp on an
  empty diff* ("no content changes; refresh `captured_at` anyway?") planned as
  Chunk 3 work. That was built and then rejected in review: re-stamping asserts
  the snapshot matches Live using an empty diff as the evidence, but an empty
  diff does not prove the on-disk file is current — it only proves the freshly
  captured state matches what the differ compared. Moving the timestamp without
  writing the bytes therefore disarms the guard on an unproven file, which is
  the exact failure the guard exists to prevent.

  **What shipped instead:** `/song-snapshot`'s empty-diff path *bakes* the
  refresh — it writes the freshly captured content over the canonical file via
  `capture merge`, so the stamp is backed by bytes that were actually captured.
  `capture restamp` survives only as a deliberate override and REFUSES an
  unstamped file rather than back-stamping one. `--force-replay` remains the
  discard-the-pulled-edits path, not the re-stamp path.

  This artifact outlives the build plan (the plan is scope-named and deleted at
  the develop→main release), so the reversal is recorded here rather than only
  in the plan's Status block.
- Event-vs-file clock: `captured_at` uses Python's UTC clock, `events.ts`
  SQLite's — same machine in this single-user tool; sub-second skew only
  matters in the seconds right around a capture, where either outcome is safe.
- Scoping is per-`song_id` (DBs are per-song by construction); a mix-layer
  event hypothetically emitted without `song_id` would be missed — all current
  mix mutators thread `song_id` (verified: tracks/returns/devices/sends).

## Chunked build plan (full fix)

1. **Chunk 1 — snapshot `captured_at` + the replay guard + template `--force-replay`**
   (THIS session; tests prove: audit scenario refuses with no revert; override
   reverts with warning; no-pull and fresh-capture paths don't trip; legacy
   warns; non-replay-asserted pull domains don't trip; converger idempotency
   family stays green).
2. **Chunk 2 — pull-side contract UX**: `pull_cli apply|execute` prints a
   durability notice after a mix-domain apply with mutations > 0 ("staged in
   the DB only — bake with `/song-snapshot` before the next build, which will
   otherwise refuse"); finish `/ableton-pull` skill reframe (BAK-3M9T Chunk D)
   so the skill itself tells the user the bake is the closing move.
3. **Chunk 3 — `/song-snapshot` closes the loop**: after a confirmed overwrite,
   the skill states the guard is disarmed ("snapshot now newer than all pulled
   state"); on an empty diff the skill **bakes the refresh** — writing the
   freshly captured content over the canonical file via `capture merge`, so the
   stamp is backed by captured bytes (this superseded the originally-designed
   "re-stamp on an empty diff"; see *Known imprecisions* above for why a
   timestamp-only refresh was rejected); `/song-pick-instruments` stamps `captured_at` on
   hand-authored snapshots; docs (`snapshot-schema.md`, `/song-workflow`) name
   the pull→bake→build contract in one place (done for snapshot-schema in
   Chunk 1).
4. **Operator verification (Live-gated)**: real Live session — dial a knob,
   `/ableton-pull` device-parameters, run `build.py` → observe refusal; run
   `/song-snapshot` → build passes and the knob survives; `--force-replay` →
   knob reverts. Queue in operator-verification.md.

### Open refinements (explicitly deferred, not silently dropped)

- **Disarm-after-forced-replay** (row-granular "was this pulled row since
  re-asserted by a newer non-pull write?"): needs per-row event attribution à
  la `_latest_actor_for`; only worth it if the repeat-nag is reported as real
  friction.
- **Guard for build.py-owned pulled domains** (pulled tempo/clip-notes vs the
  build.py code that re-authors them as `actor='build'`): a *different* revert
  channel (the user's own code, not replay), owned by the staging workflow
  ("fold into build.py"), out of BAK-7D2V's scope.
- The event-store flip eventually dissolves the two-target split entirely
  (`architecture_db.md`); this guard is the state-store-era containment.
