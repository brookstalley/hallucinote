# Capability: interactive device-chain reorder / insert-at-position (state-preserving)

**Type:** capability request (ergonomics; works around a Live LOM gap).
**Severity:** M. Not blocking — there's a manual workaround — but it's footgun-prone
(loses device param state if you're not careful) and comes up on every interactive
re-voice of an existing track.

**Engine / server:** `0.1.0+4372b6734f8d`. Surfaced re-voicing `alien`'s Alien Voice
track (swap the position-1 instrument Analog→Operator while keeping EQ Eight + Erosion
downstream).

## The gap

`ableton_device(action='load')` appends to the END of the chain, and its docstring
already notes *"Live 12.4 has no public reorder API."* Live's LOM exposes only
append-at-end (browser load) + `delete_device(index)`; there is no `move_device` /
insert-at-index, and drag-to-reorder is GUI-only. So to change the instrument at
position 1 of a populated chain `[Analog, EQ Eight, Erosion]`, the only path is:

1. delete all three (the EQ/Erosion can't stay — they'd end up BEFORE the newly-loaded
   instrument, which appends last → broken signal flow), then
2. reload `Operator → EQ Eight → Erosion` in order, then
3. **manually re-apply every EQ/Erosion parameter** that wasn't default.

Step 3 is the footgun: a re-voice silently reverts downstream-effect tuning unless the
operator remembers to capture and restore it. On `alien` the EQ was transparent and
Erosion only lightly dialed (Amount 20 % / 500 Hz), so the loss was small — but on a
heavily-tuned chain this quietly destroys mix work.

## What would help (any one)

- **`set_chain_order(track, [desired device order])`** — captures each device's full
  param state (+ sidechain/routing), deletes, reloads in the requested order, restores
  state. Atomic, lossless. The composer says "put Operator first, keep EQ+Erosion after
  it" and the helper does the dance.
- **`insert_device_at(position=...)`** (or a `position` arg on `load`) — same mechanism,
  scoped to one insertion.
- At minimum, a **documented recipe + a `capture_device_state` / `restore_device_state`
  pair** so the delete→reload→restore dance is safe-by-construction instead of
  hand-rolled per re-voice.

## Notes / scope

- This is purely the **interactive** path. The push/build materialization ALREADY orders
  chains correctly (it loads in chain order onto a fresh, empty track) — so the durable
  source-of-truth path is fine. The gap is editing a populated live chain in place.
- Adjacent design question it raises: what's the blessed way to *durably* re-voice a
  track? Today it's "edit the live chain → `/song-snapshot` to bake into
  captured_session.json." A `set_chain_order` helper makes the "edit the live chain"
  half safe; the snapshot half already exists. (An alternative — edit
  captured_session.json directly and re-push devices onto a fresh set — avoids the live
  surgery but needs a fresh set and a non-duplicating device push.)
- True in-place reorder is impossible via the current LOM; this is explicitly a
  convenience wrapper over capture-delete-reload-restore, not a new Live capability.
