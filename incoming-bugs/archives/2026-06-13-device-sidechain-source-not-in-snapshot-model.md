# Bug report — device sidechain *source* routing is not captured by the snapshot/pull model nor materialized by push (2026-06-13)

Context: mix pass on `swell` (hallucinote-songs). Added five sidechains in Live
via `ableton_device(action='set_sidechain', source_display_name=...)` — a machine
kick-pump (kick → Bass Punk, kick → Gtr Power), a timpani-audibility duck
(Timpani → Contrabass, Timpani → Celli), and a ducked reverb (PRE-MAIN → Hall
return). All work in the live set. Then went to bake them so they survive
rebuild/re-push.

## TL;DR

The DB persists:
- **track-level** input/output routing (`tracks.input_routing_kind /
  input_routing_target_id / input_routing_channel`, schema.sql:79–81), and
- **device parameter values** (`device_parameters`, schema.sql:390) — so
  `S/C On`, `S/C Gain`, `S/C Mix`, `S/C EQ *` round-trip as ordinary params.

But there is **no field for a device's sidechain SOURCE** — the
`input_routing_type` set by `set_input_routing` / the `source_display_name` arg
of `set_sidechain`. The `devices` table (schema.sql:336) has no routing columns;
`device_parameters` only holds the canonical param family. So after
`song-snapshot` (or `pull`) + rebuild + push, every sidechained compressor comes
back with `S/C On = 1` but **no source assigned** — the sidechain is silently
broken (it either does nothing or ducks off the wrong/last input).

## Why it matters

Sidechaining is a first-class mix technique (pumps, ducks, ducked reverb), and
the tool *offers* `set_sidechain` as a supported action — but the result isn't
durable through the song's own source-of-truth round-trip. The mix only survives
in the saved `.als`, which defeats the "build.py + snapshot are the source of
truth, the .als is regenerable" model. A `--reset` or any device-chain rebuild
drops every sidechain source.

## Mitigation in use

- Bake the *params* (they persist), set sidechain *sources* in Live, and **save
  the .als**; avoid full device rebuilds / `--reset`.
- Rely on push being a state-converger that doesn't touch device sidechain
  routing (it neither sets nor clears it), so pre-existing Live sidechains
  survive a no-op device phase — fragile (depends on devices not being
  recreated), not a real fix.

## Suggested fix

Add device-level input/sidechain routing to the model, symmetric with
track-level routing:

- `devices.sidechain_source_track_id` (nullable FK → tracks, semantic reference
  so it survives renames, like the PRE-MAIN bus FK) + optional
  `sidechain_source_channel` ('Pre FX' / 'Post FX' / 'Post Mixer').
- Capture it in `pull/mix.py` via `get_input_routing` per device that exposes
  the API (the probe already exists — `ableton_device(action='get_input_routing')`).
- Materialize it in a push phase (after `devices`, since the device must exist):
  `set_input_routing` by resolved source name.
- A mutator (`set_device_sidechain(device_id, source_track_id, channel)`) so
  build.py can author it directly too, not only capture it.

This makes the five sidechains above (and any future ones) survive
bake → rebuild → push instead of living only in the .als.
