---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# BAK-3M9T Chunk 01 — verify-api findings (Done-when #0)

Read the existing sidechain surfaces before writing the snapshot half.

## Reference form (Assumption 1 — CONFIRMED: store by surface name)

- `ableton_device(action='get_input_routing')` → `get_input_routing_handler`
  (`hallucinote_mcp/.../handlers/device.py:1730`) returns, via
  `routing_surface_fields` (`handlers/_routing.py:99`):
  - `has_input_routing: bool` — True only for devices exposing
    `available_input_routing_types` (Compressor / Gate / sidechain-capable
    plugins). False (cheap no-op) otherwise — probing every device is safe.
  - `current_type: str | None` — `input_routing_type.display_name`, i.e. the
    **source track's display name** (a string). This is exactly the surface name
    to store in the snapshot.
  - `current_channel: str | None` — `input_routing_channel.display_name`
    ("Pre FX" / "Post FX" / "Post Mixer"), or None for the device default.
- Push half: `set_device_sidechain(device_id, source_track_id: UUID, channel:
  display_name)` (`db/mutations/devices.py:492`) — semantic FK + channel string,
  idempotent, `source_track_id=None` clears (and forces channel NULL).
- Pull half: `_apply_device_sidechain_source` (`sync/pull/devices.py:458`)
  resolves `current_type` → exactly one song **track** by name. Source is ALWAYS
  a track (its policy comment). No-ops on: own host track (default input),
  no-track-match (non-track input / "No Input" / external), name collision (warn).
  ⇒ Snapshot stores the source by track surface name; replay resolves name → id.

## Tombstone protection (Assumption 2 — CONFIRMED: already registered)

`_LATEST_ACTOR_EVENTS["device"]` (`db/mutations/build.py:104-111`) ALREADY lists
`("device_sidechain_set", "device_id")`. No production change needed — a pulled/
captured sidechain set as actor='sync' survives the next build sweep. Chunk 01
adds a **regression test** guarding this (learning #25).

## Upsert behaviour (drives clear-on-absence)

`create_device` (`db/mutations/devices.py:326`) upserts on `(chain_id, position)`
and does NOT touch the sidechain columns on update — so a re-replay that DROPPED
a sidechain needs an EXPLICIT `set_device_sidechain(None)` to clear it. This is
the same idiom `set_chain_properties` uses (`capture.py:489-491`: "passed
explicitly (None when omitted) so a re-replay of a snapshot that DROPPED a prop
clears the stale DB value — the snapshot is the source of truth"). Replay applies
the snapshot's sidechain truth for **every** device (present → set, absent →
clear), idempotently.

## Design decisions (Chunk 01 scope)

- **Capture** (`_capture_devices_for_parent`): probe `get_input_routing` per
  top-level device; store raw `sidechain_source` (+ `sidechain_source_channel`)
  when `has_input_routing and current_type`. A post-pass
  (`_resolve_captured_sidechain_sources`) over the assembled snapshot — where all
  track names are known — drops the own-track default and any source that doesn't
  resolve to a track in `snapshot['tracks']`. (Chunk 02 upgrades that drop to a
  warn + re-apply list; the non-track-input / collision cases are its job.)
  Top-level only, matching the pull's `_iter_linked_top_level_devices` scope.
- **Replay** (`_replay_devices` → `replay_capture` post-pass): collect every
  replayed device into a pending list; after all tracks exist, resolve each
  `sidechain_source` name → song track id via `track_ids_by_name` and call
  `set_device_sidechain` (None → clear). Deferred because a source may be a track
  created later in the loop. An unresolvable source name on a hand-authored
  snapshot raises ValueError — same hard contract as a send to a missing return
  (`capture.py:753`).
- **Surface-id-not-UUID** (learning #22): the snapshot never stores a track UUID;
  resolution keys on the surface name. Tested with UUIDs ≠ name/index.
