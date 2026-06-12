# RTE-1K9T — Track Routing (input/output + parallel busses) — Design & Requirements

**Status:** READY TO BUILD (discovery complete, live-probed). **Date:** 2026-06-12.
**Branch context:** authored on `develop`; build on a feature branch `feature/rte-1k9t-track-routing`.
**Scope decision (user, 2026-06-12):** RTE-1K9T keystone; **TRK-2H6K (group tracks) DEFERRED** — see Decision D2.

---

## Motivation — the WHY

User goal (verbatim intent, 2026-06-12): *"I REALLY want to avoid dealing with .als files, and I
really want automation on some master-like bus."*

Discovery this session (live probes, Live 12.4.2) established the route:

- The **master / return / group are clip-less summing points** → no lossless LOM automation
  envelope (only lossy `perform_batch` gesture recording, or `.als` cold-write). Confirmed:
  `master_track.arrangement_clips` raises; `write_envelope` on a clip-less track refuses both
  session (`slot empty`) and arrangement (`create_automation_envelope rejects mixer/pan/send/
  device_parameter unless the clip is a session clip; track-level arrangement creation isn't
  exposed`). See `.prawduct/artifacts/research-spike-automation-ingest.md` and the MAW-4K7P
  backlog entry for the full automation-fidelity map.
- A **plain audio track is fully LOM-creatable** (`Song.create_audio_track`) **and routable**
  (`output_routing_type`) and inherits all normal track automation paths. So the **"master-like
  bus" = a plain audio "PRE-MAIN" track that everything routes through** → master. No `.als`,
  no group, no special-casing.
- The one missing primitive is **first-class track routing** — today reachable only via raw
  `ableton_probe` (object-valued `output_routing_type` set), not via any clean MCP action.

**Therefore RTE-1K9T (track routing) is the keystone that delivers the master-like-bus goal.**
It also independently unlocks parallel busses (parallel compression, sub-mixes, reverb pre-busses)
and explicit output/input routing config — long-standing gaps.

---

## Discovery findings — live-probed, Live 12.4.2

| Finding | Evidence |
|---|---|
| **Output routing surface** | `track.output_routing_type` (a `RoutingType`) + `track.available_output_routing_types` (`RoutingTypeVector`); `output_routing_channel` + `available_output_routing_channels` (Pre FX / Post FX / Post Mixer / Track In). |
| **Set works end-to-end** | Routed audio track 3 → "PRE-MAIN": enumerate `available_output_routing_types`, resolve by `display_name`, `set output_routing_type = <type>`, read back `display_name == "PRE-MAIN"`. ✓ Reverted cleanly. |
| **Input routing surface (symmetric)** | `input_routing_type` / `available_input_routing_types` (+ channel). For a summing bus to PASS routed audio it also needs **monitor state** = `current_monitoring_state` (`In`/`Auto`/`Off`); a bus wants `In`. |
| **Targets are SOURCE-dependent** | bare MIDI track (no instrument) → 2 output types (`Main`, `Sends Only`); audio track → 5 (`Ext. Out`, `Main`, `<other audio track>`, `PRE-MAIN`, `Sends Only`). ⇒ resolve by `display_name` against the *source track's own* list; teaching error must list the actual options. |
| **No group-track creation** | `Song` exposes `create_audio_track`, `create_midi_track`, `create_return_track`, `create_scene` — **no `create_group_track`**. Groups are UI-only (Cmd+G); LOM can READ membership (`track.group_track`, `is_grouped`) but not create. ⇒ TRK-2H6K create-group is not LOM-authorable. |
| **Same-callback readback is unreliable** | Reading `output_routing_type.display_name` back in the *same* MCP callback that set it can return the prior value (the live probe in row 2 used *separate* MCP calls = separate callbacks, so it read the new value). Same constraint the session-view handlers already encode (`handlers/session.py:167-171`). ⇒ the set handlers ECHO the requested name as the success signal (the side effect is authoritative); to confirm the new value, issue a *subsequent* `get_output_routing`. |

---

## Requirements

- **R1** — Track **output routing** authorable via a clean `ableton_track` action (by `display_name`,
  capability-probed, teaching errors that list available targets).
- **R2** — Track **input routing + monitor state** authorable (the summing-bus pass-through depends
  on `current_monitoring_state = In`).
- **R3** — Routing **modeled in the DB through mutators (+ events)** and pushed + pulled like mixer
  state (mutator discipline — `feedback_mutator_discipline`).
- **R4** — The **"PRE-MAIN submaster" pattern** documented + exercised on the new primitives
  (create audio bus → route instrument tracks' output to it → route bus → master → bus Monitor=In).
- **R5** — **No `.als`. No group creation. No new automation surface** (the bus rides via the existing
  `perform_batch` path; lossless bus automation is out of scope — see Caveat).

---

## Decisions

- **D1** — The master-like bus is a **plain audio track + routing**, not a group track.
- **D2** — **Defer TRK-2H6K** (group-track support). Its core — *create* a group — is LOM-blocked, and
  a group offers no automation advantage (clip-less, same wall as master). The routing layer is the
  deliverable; group membership *read/model* can be revisited later behind a real need + a non-LOM
  create path. (User-ratified scope, 2026-06-12.)
- **D3** — **Capability-probe + by-`display_name`** resolution, mirroring `device.py`'s
  `set_input_routing_handler`. Never a hardcoded target list (the available set is source-dependent).
- **D4** — **DB model:** routing is single-valued per track (1:1), so model output routing + input
  routing + monitor as **columns on `tracks`** (matching mixer-state-as-columns), not a side table.
  *Confirm in chunk 03 against the schema's existing shape.* Target is a reference:
  `{kind: master|track|sends_only|ext_out, target_track_id?}` + channel.
- **D5** — **Push phase order:** insert a `routing` phase **after `mix` (7), before `devices` (8)** —
  routing needs track links to exist (created in `tracks`, phase 3) and is logically a mixer concern.
- **D6** (chunk 03, persisted-shape lock-in) — **Routing-reference columns + the CHECK asymmetry.**
  D4 enumerated only the *output* kind vocabulary; chunk 03 must also persist *input* routing and
  monitor. Decided shape — seven nullable columns on `tracks` (matching mixer-state-as-columns):
  `output_routing_kind` / `output_routing_target_id` (FK→`tracks.id`, `ON DELETE SET NULL`) /
  `output_routing_channel`; the `input_*` triple; and `monitoring_state`. The target is **always a
  semantic reference, never Live's `display_name`** — `kind='track'` ⇒ `target_id` FKs the
  destination track (the submaster bus), so the reference survives renames + re-pushes; push
  resolves the FK→display_name, pull maps display_name→reference.
  **CHECK asymmetry (deliberate):** `output_routing_kind` (`master|track|sends_only|ext_out`) and
  `monitoring_state` (`In|Auto|Off`) get schema-level CHECKs — both domains are *closed and
  live-probed certain*. `input_routing_kind` (`ext_in|resampling|no_input|track`) gets **no schema
  CHECK** — input's domain is *open and hardware-bound* (specific MIDI ports / interface channels
  vary per machine), and a wrong CHECK is a destructive SQLite migration (no `ALTER … CHECK`). The
  mutator validates the input vocabulary in Python (extensible without a migration). Cross-field
  invariant (`target_id` present ⟺ `kind='track'`) lives in the mutator both directions (ALTER
  can't add a table-level CHECK — the clips audio-invariant precedent). **V1 input scope:** input
  types outside the four-value set (arbitrary MIDI ports / interface inputs) are not persisted —
  chunk-05 pull leaves input routing NULL for them; input exists so a bus's Monitor=In round-trips,
  and a bus needs no specific input source. The dangling state (`kind='track'`, `target_id=NULL`)
  the FK cascade produces when a target is deleted is *legal* and detectable — push (chunk 04)
  treats it as "target gone" and alerts; the mutator re-validates a direction only when that
  direction's kind/target is touched, so an unrelated update on a dangling track is not blocked.

---

- **D7** (chunk 04, spec correction) — **Routing push is NOT fingerprint-gated; it
  re-emits idempotent sets, mirroring `mix`/`devices`.** The build plan's chunk-04 line
  "fingerprint-gate so unchanged routing never re-emits (match the existing mix/send gating)"
  rests on a **false premise**: neither `plan_push_mix` nor `plan_push_devices` fingerprint-gates
  — both re-emit every `set_property` / `set_parameter` call on every push and rely on Live's
  idempotent set semantics. The *only* fingerprint-gated phase is `performed_automation`, which
  gates because each changed arc costs **real wall-clock transport time** (the playhead plays the
  span). A routing set has no such cost — it's a cheap, idempotent LOM write. Moreover a
  pure-data planner **cannot** read Live's current routing to gate against it (planners read the
  DB only; the agent executes MCP calls), and no per-track "last-pushed routing" fingerprint is
  stored — adding one would be unjustified complexity no sibling planner carries. **Decision:**
  `plan_push_routing` emits routing calls unconditionally for every linked track that carries
  routing columns; "re-push is a no-op" (the chunk-04 acceptance criterion) holds at the **effect
  level** (re-setting the same route changes nothing in Live), exactly as `mix` re-pushing volume
  is. Keys are ack-only (`track_output_routing` / `track_input_routing` / `track_monitor`) — the
  routing state already lives in the DB, so there's no Live-side index to bind back.

- **D8** (chunk 05, pull normalization) — **Pull is faithful + Ableton-authoritative
  and uses `DB-NULL ≡ Live-default` to avoid default-churn.** The inverse of D6/D7's
  push: a `get_{output,input}_routing` / `get_monitoring_state` probe per linked track
  (three keys — `track_output_routing` / `track_input_routing` / `track_monitor` —
  mirroring push; one MCP read each, since the three getters are separate LOM
  surfaces), mapped from Live's `display_name` back to a DB reference and written via
  `set_track_routing`. The display_name↔kind map is **shared** (`sync/routing_names.py`),
  so push (kind→name) and pull (name→kind) can never drift. **Default-churn rule:** a
  track with no authored routing has NULL routing columns, but Live always reports a
  concrete default (`Main` / `No Input` / `Auto`). Pull treats NULL as EQUIVALENT to
  the default, so a first pull of an unrouted track is a no-op — only a NON-default
  Live route (or a user reverting an authored route back to default) mutates the DB,
  and the value written is exactly what Live reports (Ableton-authoritative). **Track
  targets** resolve by name against the song's tracks (fixed names like `Main` win over
  track-name matching; the source track + master are excluded; a 2+-way name collision
  is unmappable → warn+skip, never a wrong reference). **V1 input scope (Critic W1 →
  narrowed):** pull persists ONLY a track→track input — the one input case that is
  default-independent. Fixed input kinds (`ext_in` / `no_input` / `resampling`) and
  arbitrary MIDI/interface inputs are deferred: Live's non-track input default is open,
  hardware-bound, and **not live-probed** (a MIDI track likely defaults to "All Ins"),
  so a `NULL ≡ default` rule on them would rest on an unverified premise and could churn
  every track on the first pull. There is consequently **no `INPUT_DEFAULT_KIND`
  constant** (`routing_names.py` carries only the live-probed-certain OUTPUT + MONITOR
  defaults). Non-track input is a quiet no-op (not a per-track warning — the deferral is
  by-design, and Live's default input would otherwise spam). The fixed-input-kind pull
  is unblocked once a live-probe pins Live's input defaults — **enqueued in
  `operator-verification.md`**. The output direction is unaffected (output's "Main"
  default is closed + live-probed). **Channel** rides along faithfully with a non-default
  route (it never enters the default-route no-op path, so it can't churn). A mutator
  `ValueError` is caught per-track (validation rejects before any write → transaction
  stays clean), surfaced as a warning, and the batch continues — mirroring
  `_apply_track_sends`.

## Out of scope (explicit — never silently drop)

- **Group-track creation** (TRK-2H6K) — LOM-blocked (no `create_group_track`).
- **Lossless bus automation** — gated on the audio-clip gap (**CLP-AUD2** session audio-clip
  placement / **ENV-8H1T** mixer envelopes on audio tracks). The bus rides via `perform_batch` today.
- **`.als` write** (MAW-4K7P) — explicitly avoided per user intent.
- **Sidechain SOURCE routing** — already shipped at the *device* layer (`device.set_input_routing`);
  this plan adds the *track* layer, it does not redo the device layer.

## Automation-fidelity caveat (read before claiming "master automation solved")

The PRE-MAIN bus delivers **perform-fidelity** rides today — lossy ~2.5 Hz gesture recording, which
is **adequate for slow master moves** (volume rides, filter sweeps over many bars) and the common
case. **True-lossless** bus automation needs a hosting session clip the audio bus cannot carry until
**CLP-AUD2** lands. **This plan delivers ROUTING, not new automation fidelity** — but it removes the
master special-casing and makes the bus a first-class, normally-automatable track, which is the
no-`.als` path the user wants.

---

## Integration map (file:line — from code exploration, 2026-06-12)

- **DB schema:** `src/hallucinote/db/schema.sql` — `tracks` (L36–58; `kind` already allows `'group'`;
  **no** routing cols, **no** `parent_track_id`), `sends` (L246–254), `returns` (L213–231),
  device chains carry `parent_track_id` FK (L278).
- **Mutators:** `src/hallucinote/db/mutations/tracks.py` — `create_track` (L21–95),
  `set_track_mixer` (L101–145), `_delete_track` (L147–174). `returns.py` — `set_send_level`
  (L168–226). Pattern: `_emit(conn, E.<KIND>, payload, song_id, actor, request_id, reason)`.
- **Push phases:** `src/hallucinote/sync/push/plan.py` `_PHASE_NAMES` (L53–66): tempo_map,
  time_signature_map, tracks, returns, scenes, clips, mix, devices, envelopes,
  performed_automation, arrangement, cues. Track create: `sync/push/tracks.py`
  `plan_push_song_tracks`. Sends: `sync/push/mix.py` `plan_push_mix` (L150–174).
- **Pull:** `src/hallucinote/sync/pull/mix.py` `plan_pull_mix` (L24–110), `_apply_track_info`
  (L488–551), `_apply_track_sends` (L554+).
- **Capability-probe template (mirror this):** `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py`
  — `_find_routing_by_display_name` (L1155–1169), `_enumerate_available` (L1172–1181),
  `set_input_routing_handler` (L1184–1267), `get_input_routing_handler` (L1269+).
- **MCP track actions:** `hallucinote_mcp/src/hallucinote_mcp/actions/track.py` — `create` (L99–149;
  "Group-track creation is not supported yet" at L113–114), `set_property`, `set_send`/`get_sends`.
  Register new routing actions here; registration side-effect via `actions/__init__.py`.
- **Test homes:** DB → `tests/unit/db/test_mutations.py`; push → `tests/unit/sync/test_push_mix.py`
  (or new `test_push_routing.py`); pull → `tests/unit/sync/test_pull.py`; MCP →
  `hallucinote_mcp/tests/unit/test_actions_track.py`. Mirror the input-routing suite at
  `hallucinote_mcp/tests/unit/test_actions_device.py` (L2003–2151).
