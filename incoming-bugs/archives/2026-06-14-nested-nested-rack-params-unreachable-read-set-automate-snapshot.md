# Nested-nested rack device params are unreachable (read / set / automate / snapshot) — blocks deep-rack sound design

> **RESOLVED — framing corrected (NODE-ADDR / DEV-9K7N, 2026-06-15).** This
> report frames the gap as "(1) Depth-N device *addressing*" + "(2) snapshot
> capture". That framing was imprecise: depth-N *addressing* (`device_path` /
> `NodeAddr.path`) for read/set/automate SHIPPED via DEEP-RACK-ADDR (2026-06-14)
> + NODE-ADDR Chunk A (2026-06-15) — items (1) and (3) are done. The real
> residual was the **read-side ACQUISITION**: there was no in-code Live→snapshot
> capture, so a probe-set deep value couldn't be persisted (item 2's "killer").
> NODE-ADDR Chunk B closes it with `capture execute` (in-code capture that probes
> `get_parameters` at every depth) + depth-N pull. Item (4) Voices is a separate
> probe-gated follow-up (DEEP-RACK-ADDR Chunk 4).

**Severity:** H (capability gap) — a parameter that lives **two or more rack
levels deep** (rack → chain → rack → chain → device) cannot be **read**, **set**,
**automated**, *or* **captured into the snapshot** through the device API. The
last one is the killer: even using the raw-LOM escape hatch to set such a param
by hand, **nothing persists it to source**, so any fix is silently reverted by
the next `build.py` rebuild + push. This blocks a real song task (swell's
`04 Gtr Power` reads mono on chords) and, more broadly, any sound design on the
factory **instrument racks** (Guitar/Bass/Orchestral packs), which are routinely
rack-in-a-rack.

## Concrete case (swell `04 Gtr Power`)

The patch the song relies on for distorted power chords is nested two levels:

```
track 4 "04 Gtr Power"
└─ device 1  "Guitar-Dual Amped Heavy"   (Instrument Rack)
   └─ chain 1 "Guitar"
      ├─ device 1  "Guitar"              (Instrument Rack)   ← nested rack
      │  └─ chain 1
      │     ├─ device 1  "Pitch"         (MidiPitcher)
      │     └─ device 2  "Guitar Dead Notes" (sampler/articulation) ← the tone generator
      ├─ device 2  Audio Effect Rack
      ├─ device 3  Chorus (off)
      ├─ device 4  Reverb
      ├─ device 5  Utility
      └─ device 6  Limiter               ← chord-collapse suspect
```

To diagnose/fix "sounds mono on chords" I need to reach two params that both sit
below the addressable depth:
- the sampler's **voice/polyphony** count (`devices[0].chains[0].devices[0].chains[0].devices[1]`), and
- the end-of-chain **Limiter** (`devices[0].chains[0].devices[5]`) — heavy amp
  distortion into a limiter is a strong "chord → one fat mono tone" suspect.

## Second concrete case (swell Voice Lead LFO tempo-sync, 2026-06-15)

Same depth, a DIFFERENT song surface — confirms this recurs, not a one-off. The
Voice Lead's vibrato is the **Wavetable's `LFO 1 Sync`** param, two rack levels
deep:

```
track 21 "21 Voice Lead"
└─ device 1 "Synth Vox Ai"   (Instrument Rack)
   └─ chain 1
      └─ device 1 …          (nested rack)
         └─ chain 1
            └─ Wavetable      ← LFO 1 Sync (Free→Tempo) + synced rate (1/2 note)
```
(probe path `[{1,1},{1,1}]` from the top-level device.)

decisions/22 #8 switched `LFO 1 Sync` Free→Tempo to stop the vibrato drifting
against 126 BPM. It works — but set via raw `ableton_probe`, and **the snapshot
doesn't carry it**, so it's live-only: a rebuild + push reloads the rack from its
preset default and the wobble goes back out of time. Every session since has had
to remember "SAVE the .als or lose the LFO sync." Exactly the `params_dialed`
top-level-only gap in (5) below, now in a SECOND surface — a stock vocal-synth
rack, not just the guitar pack. (Added from swell's 2026-06-15 timpani/voice pass.)

## What's blocked, by surface

1. **`ableton_device(action='get_device_chains')`** — its own help: *"does NOT
   recurse into nested-nested racks (filed as backlog)."* So the sampler's params
   aren't even enumerable through the device API.
2. **`ableton_device(action='set_parameter_in_rack')`** — addresses exactly **one**
   nesting level: `(device_index, chain_index, nested_device_position)`. There is
   no way to express rack → chain → **rack → chain** → device, so depth-2 params
   are unwritable.
3. **`ableton_device(action='get_parameters')`** — top-level chain only; same
   depth ceiling.
4. **Automation** — `sync/push/envelopes.py::classify_envelope_route` returns
   `'unroutable'` for any `device_parameter` envelope whose device has a
   `parent_rack_device_id` (lines ~303–307: *"Nested-rack devices have no
   addressable parameter surface on either route"*). So even a nested **top-level**
   rack device can't be automated, let alone a depth-2 one.
5. **Snapshot capture / push (`params_dialed`)** — the bake only records params
   for **top-level** devices on a track/return chain. Audited swell's
   `captured_session.json`: every `params_dialed` entry is a top-level device
   (Compressors, EQ Eights, Drum Buss, the phaser…); **no** nested-rack device
   carries params. So a value set inside a nested rack is **never captured**, and
   a rebuild reloads the rack from its `preset_query` default — reverting the fix.

## Current escape hatch (and why it's not enough)

`ableton_probe` **can** reach arbitrary depth — I read
`song.tracks[3].devices[0].chains[0].devices[0].chains[0].devices[1].name →
"Guitar Dead Notes"` with it, and `action='set'` can write a settable
property/param there. But:
- it's **index-fragile** raw LOM (no name resolution, no capability probing), and
- it is **not part of the snapshot capture path**, so a probe-set value is
  **not durable** — exactly the failure mode above.

So today the only durable "fix" is to **flatten the patch** (rebuild the guitar
as a non-nested chain we can address), which throws away the factory rack.

## What we need (MCP improvements)

1. **Depth-N device addressing** for `get_parameters` / `set_parameter` /
   `get_device_chains`: a device *path* like
   `[(chain_index, device_position), (chain_index, device_position), …]` to any
   depth, replacing the single-level `set_parameter_in_rack` triple. (The
   `get_device_chains` recursion is already backlogged — make it the read half of
   this.)
2. **Snapshot capture + push of nested params** — `params_dialed` (or an
   equivalent) for deeply-nested devices, keyed by the same device path, so deep
   sound-design is **durable** across `build.py` rebuilds. This is the one that
   actually unblocks the work; (1) without it still reverts on rebuild.
3. **(Lower priority) nested-rack `device_parameter` automation** — give
   `classify_envelope_route` an addressable surface for nested-rack devices
   (today they're `'unroutable'`).
4. **(Nice) a polyphony/voices accessor** — if a sampler's voice count is exposed
   as a LOM *property* rather than a `DeviceParameter`, the device API should
   surface it (read + set) so "make this patch polyphonic" doesn't require raw
   probe paths. Needs a quick check of whether Voices is a parameter or property
   on the pack samplers.

## Repro

1. Open swell's set; `ableton_device(action='get_device_chains', track_index=4,
   device_index=1, detail='full')` → see chain "Guitar" with a nested `Guitar`
   rack at position 1, no way to descend further via the device API.
2. Try to set the nested sampler's voices or the chain Limiter via
   `set_parameter_in_rack` → no addressing for depth 2.
3. Set it via `ableton_probe(action='set', …)` → works in-memory, but
   `pull_cli execute device-parameters --dry-run` won't capture it and a rebuild
   reverts it.

## Workaround until fixed

Diagnose with `ableton_probe` (is it Voices=1, or the Limiter squashing the
chord?). For a one-off render, set via probe and **don't rebuild**. For a durable
fix, flatten `Guitar-Dual Amped Heavy` into an addressable top-level chain, or
re-pick a non-nested distorted-guitar instrument in
`/song-pick-instruments`. Both are worse than fixing the capability.

Filed from the swell production pass, 2026-06-14.
