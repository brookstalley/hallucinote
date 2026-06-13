# Bug report — master-track devices have no authorship / round-trip path (snapshot + capture), only push + raw mutators (2026-06-12)

Context: adopting the 0.9.5 PRE-MAIN submaster bus + a master "swell" in `swell`
(hallucinote-songs). Engine checkout `develop @ 0dc395c` (post-`v0.9.5`); plugin
0.9.5; hallucinote-mcp `0.1.0+486e7e2653ec`; Live 12.x Suite.

## TL;DR

The PRE-MAIN bus convention makes a **master ceiling limiter** a real need: the
master "swell" rides the bus's *post-chain* volume fader, so the only place a
limiter can catch the ride is **on the master** (a limiter in the bus device
chain is pre-fader and never sees the swell — verified). But a master-track
device **can't be authored as part of the song's source of truth**:

- The snapshot models the master as `song.master = {volume, panning}` — **no
  `devices` array**. `replay_capture` therefore creates no master devices.
- `capture.py` doesn't probe master devices either, so `/song-snapshot` can't
  capture a hand-placed master device — **no round-trip**: a Limiter loaded in
  Live is invisible to the snapshot and lost on the next from-scratch build.

So the only way to get a master ceiling today is to `ableton_device(action='load',
master=true, ...)` by hand in Live — exactly the "mix-time todo" the
sound-design-is-authorship convention says chains should NOT be. It persists in
the open set and survives re-pushes (the push doesn't delete unmanaged master
devices), but a fresh-machine rebuild from `build.py` won't recreate it.

## The asymmetry (why this is a gap, not a missing feature)

The two ends already exist; only the **authorship middle** is missing:

- **Push side: present.** DEV-6M2K ("master device load", shipped in v0.9.5)
  materializes master-chain devices — the render's HallucinoteAnalyzer auto-loads
  onto the master, and `ableton_device(master=true)` loads a Limiter fine.
- **Mutator primitive: present-ish.** `create_device_chain(parent_track_id=…)`
  takes a track id, and `create_device(chain_id=…)` exists — so in principle a
  `build.py` could author a master chain + device via raw mutators (UNVERIFIED:
  haven't confirmed `create_device_chain` accepts a `kind='master'` track, and
  the master track currently has **zero** `device_chains` rows).
- **Snapshot + capture model: ABSENT.** The established authorship surface —
  "chains ship in the snapshot, and `/song-snapshot` round-trips them" — has a
  hole exactly at the master. `song.master` carries no devices; capture doesn't
  probe them.

Net: the push can build a master device, but nothing the *song author* writes
(snapshot entries, `/song-pick-instruments`, `/song-snapshot`) can declare or
preserve one.

## Concrete driver

`swell` now routes everything through a PRE-MAIN bus and rides a whole-mix
"swell" on the bus fader (decisions/16). That ride can push the sparse summit
crest above unity; a static master Limiter (ceiling −0.3 dB) is the safety net.
It had to be hand-loaded via MCP and is flagged in
`songs/swell/decisions/16-meter-hat-and-master-swell.md` as "loaded in Live but
not yet in build.py's source-of-truth — the snapshot model doesn't carry master
devices." This is the first song to hit it, driven directly by the new bus
convention — the bus makes master-bus processing a normal thing to want.

## Suggested fixes

1. **Model master devices in the snapshot.** Add a `song.master.devices` array
   mirroring the per-track / per-return device encoding (`{index, name, class,
   class_name?, preset_query?}`), and have `replay_capture` create the master's
   device chain + devices from it. This is the smallest change that restores the
   "chains are authorship in the snapshot" invariant at the master.
2. **Capture the master chain.** Extend `capture.py` / `/song-snapshot` to probe
   the master's device chain so a hand-placed master Limiter round-trips into the
   snapshot (closes the loop with #1).
3. **Document the build.py mutator path** (if `create_device_chain(parent_track_id=
   master_id)` already works for a `kind='master'` track): a worked snippet for
   authoring a master ceiling, so songs that need it before #1/#2 land have a
   sanctioned path instead of a hand-load.

## Adjacent note

Because a bus-chain limiter is pre-fader, the PRE-MAIN convention's
automation-fidelity story implicitly assumes a *master* ceiling for any ride that
approaches 0 dBFS. Worth a one-line pointer in
`docs/song-authoring-conventions.md` "The PRE-MAIN submaster bus": "ride the bus,
but put the safety ceiling on the master (post-fader) — and note master devices
aren't yet snapshot-authorable (this bug)."
