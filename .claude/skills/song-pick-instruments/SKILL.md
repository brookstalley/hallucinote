---
name: song-pick-instruments
description: Pick instrument **chains** per track (instrument + post-instrument FX + initial send levels) via Ableton's browser, respecting a portability mode (strict / relaxed / unrestricted). Filters `ableton://browser/instruments`, `ableton://browser/effects`, and `ableton://plugins/installed`, proposes a chain per track with rationale (why this combination, not just this instrument), confirms with the user, then loads every device in chain order via `ableton_device(action='load')` and writes initial sends. Use after scaffolding a song or when changing the instrumentation palette. The chain is authorship, not a mix-time todo — see `docs/song-authoring-conventions.md` "Sound design is authorship".
argument-hint: <tracks-csv> [portability=strict|relaxed|unrestricted] [style-hint]
user-invocable: true
disable-model-invocation: false
---

# /song-pick-instruments

You translate a track list (names alone — `Drums,Bass,Lead,Pads` — or name + role — `Drums (kit), Bass (sub), Lead (mono saw), Pads (warm)`) into concrete instrument **chains** — instrument + post-instrument processing + appropriate sends — then load them onto the song's tracks. Portability mode controls the catalogue you draw from.

$ARGUMENTS

## Chains, not bare instruments (W17-C)

A finished song has the *sound* it's supposed to have — punk drums saturate; lead vocals sit in their own room; sub-bass is clean and present; pads breathe with chorus. That sound is authorship, not a mix-time todo list (see `docs/song-authoring-conventions.md` "Sound design is authorship"). So you pick a **chain** per track, not just an instrument:

- **The instrument** — the device that makes the sound (Operator, Drum Rack, plugin).
- **Post-instrument processing** — saturation, EQ, compression, bus glue that's intrinsic to the part's character at the *track* level (not the song-wide bus level — that lives on returns / a master chain).
- **Sends** — initial send levels into shared returns (Reverb, Delay) that put the part in the right space.

The chain is one unit per track. The user picks tracks; you propose chains; you confirm; you load every device in the chain in order. The chain lands in `captured_session.json` as the track's `devices[]` array (top-to-bottom matches signal flow).

Default chain shapes (heuristic, not registry — adjust per song role):

- **Drums (kit / drum rack)** — kit + Saturator (drive) + Glue Compressor (bus glue). Sends: ~0.0 reverb, ~0.4 drum bus if a drum bus return exists.
- **Bass (sub / synth)** — instrument + EQ (high-pass anything below the fundamental's safe zone) + Saturator (presence) OR Compressor (control). Sends: 0.0 reverb (mud killer), tiny delay only if the part calls for it.
- **Lead (mono / pad)** — instrument + Compressor (presence) + (optional) Chorus / Phaser for movement. Sends: ~0.2-0.5 reverb, ~0.1-0.3 delay.
- **Pads / textures** — instrument + Chorus + EQ (carve mids for the lead). Sends: high reverb (0.4-0.8), moderate delay.
- **Vocals (if present)** — instrument or audio + EQ + Compressor (smoothing) + (optional) De-Esser. Sends: 0.2-0.4 reverb, taste-driven delay.

These are *starting points* you adjust per song. Punk needs more saturation than ambient; bossa wants less compression than EDM. Use the style hint + the song's `decisions/` files (especially `02-tempo.md`, `07-energy-aesthetic.md`) to steer the chain character.

## Portability modes

- **strict** (default) — stock Live devices only. Read `ableton://browser/instruments`; do NOT pull from `ableton://plugins/installed`. Strict guarantees the resulting song opens on any Live install of the same edition with no missing-device errors. Edition tier matters: Operator / Analog / Electric / Tension / Collision / Drift / Meld are Suite-only; Wavetable / Simpler / Sampler / Drum Rack / Impulse ship with Standard.
- **relaxed** — stock + common third-party. Read both `ableton://browser/instruments` AND `ableton://plugins/installed`. When picking third-party, prefer well-known names a collaborator plausibly already owns (Serum, Massive X, Diva, Spire, Omnisphere, Kontakt). Avoid niche / boutique plugins in this mode. Consumers may need to install one or two; W13-B's `compat check` flags them.
- **unrestricted** — anything installed. Pick the best musical fit without portability concern. Assume the consumer side will resolve missing plugins via `python -m hallucinote.sync.compat check <slug>` and the emitted `songs/<slug>/REQUIREMENTS.md`. Tell the user explicitly that this song is not strict-portable.

Reject unknown modes with a teaching error listing the valid choices.

## Steps

1. **Read the catalogue.** Open the resources for the chosen mode. Each node has fields `{name, uri, is_loadable, is_folder?, children?}` — `name` is Live's browser display name (`Operator`, `Drum Rack`, `Meld`, `EQ Eight`), `uri` is the `query:...` or `plugins:...` string passable to `ableton_device(action='load', preset_uri=...)`. Filter to `is_loadable=true` so only pickable nodes remain. Read `ableton://browser/effects` too — that's where you draw post-instrument processing (Saturator, EQ Eight, Compressor, Glue Compressor, Chorus, Phaser, etc.). Do NOT read a `class_name` field off a node — that field does not exist on browser nodes.

2. **Propose a chain per track.** For each track, build ONE chain (instrument + post-FX + send levels) with rationale. Record:
   - **`track`** — the track name.
   - **`devices`** — ordered list `[{name, preset_uri, role}]` from instrument first to final-FX last. `role` is a short tag (`instrument`, `saturation`, `eq`, `compression`, `bus-glue`, `chorus`, `delay`, `reverb`).
   - **`sends`** — initial send levels `{return_name: level_0_to_1}` for sends-on-returns this track needs (skip 0.0-level sends).
   - **`rationale`** — one sentence per chain explaining the sonic intent (why this combination, not just why this instrument).

   Drum tracks anchor on Drum Rack (kind `Drum Rack`) or Impulse (kind `Impulse`) — single-pitch synths don't make sense for a kit. See "Default chain shapes" above for the per-role starting points. Adjust depth and character per song style.

3. **Confirm with the user.** Present chains as a compact-but-readable table — track / chain (instrument → FX1 → FX2) / sends / rationale. Wait for OK or substitutions before loading. The user may steer individual picks ("use Wavetable instead of Analog for Lead") OR the whole chain shape ("don't compress the bass, I want it loose"); honour the steer and re-confirm.

4. **Load the chain.** For each track's confirmed chain, load every device in order:
   - **First device** — use `/track-new-with-instrument` (creates the track + loads the first device, typically the instrument), OR if the track exists, call `ableton_device(action='load', track_index=<i>, kind=<name>, preset_uri=<uri>)` directly.
   - **Subsequent devices in the chain** — call `ableton_device(action='load', track_index=<i>, kind=<name>, preset_uri=<uri>)` once per device, in order. Each lands at the end of the track's device chain, after the instrument.
   - **`kind` is REQUIRED**. Pass the browser node's `name` directly — that's the BROWSER DISPLAY NAME the loader matches against. Examples that work: `Drum Rack`, `EQ Eight`, `Wavetable`, `Compressor`, `Phaser-Flanger`. Arc 4 / D4: Live's internal class names (`DrumGroupDevice`, `Eq8`, `InstrumentVector`, etc.) no longer resolve — there's no translation table anymore, the loader uses what Live's `device.class_display_name` reports natively. Third-party plugins use the same string in both spaces.
   - **Capture `resolved_path` after each load (E3, W13-A v1.0 snapshot-write side).** Every `ableton_device(action='load')` response carries `resolved_path` — the browser-path segments from the root key to the loaded item's name (e.g. `["instruments", "Operator"]` or `["plugins", "Native Instruments", "Massive X", "FatBass"]`). Keep a running list of load records as you go through the chain:
     ```python
     loads = []  # accumulate across all tracks
     # after each ableton_device(action='load') call:
     loads.append({
         "track_index": <i>,
         "device_index": <response.device_index>,
         "browser_path": <response.resolved_path>,
     })
     ```
     The list gets handed to `compile_snapshot(..., browser_paths=loads)` in step 6 so the snapshot carries the cross-machine fallback identity. Skipping this step doesn't break the load itself — push falls back to `preset_uri` alone — but it means a teammate on a different Live install won't be able to auto-resolve the part if their per-machine FileId differs.
   - **Sends** — set initial send levels with `ableton_track(action='set_send', track_index=<i>, return_index=<j>, value=<0..1>)`. Skip 0.0-level sends.

5. **Write a signal-chain decision (W17-G).** After the user confirms the chains, write `songs/<slug>/decisions/NN-signal-chains.md` (next free `NN`, typically right after `08-instrument-picks.md` or replacing it for fresh songs). Shape:

   ```markdown
   ---
   date: <YYYY-MM-DD>
   kind: decision
   scope: song
   decided_by: agreed-after-confirm
   tags: [signal-chains, portability-<mode>]
   ---

   # Signal chains per track

   ## Question
   What's the full chain (instrument + post-FX + sends) per track that gives this song its sound?

   ## Chains

   | Track | Chain (top → bottom) | Sends | Rationale |
   |-------|----------------------|-------|-----------|
   | Drums | Drum Rack (Hot Rod Kit) → Saturator (Drive 5) → Glue Compressor | Reverb 0.0, Drum Bus 0.5 | Punk drums need saturation + bus glue baked in; no clean kit, no mix-time todo. |
   | Bass  | ...                  | ...   | ... |

   ## Rationale
   <One paragraph per chain explaining why this combination, not just this instrument. Reference the song's energy/aesthetic decision (07-*.md) and the genre.>
   ```

   This decision file IS the sound design. Treat post-instrument processing as authorship, not as a "mix-time follow-up." Older songs that have an `08-instrument-picks.md` with a "mix-time follow-ups" section: leave it as historical (don't backport), and write the new chains decision alongside.

6. **Capture for the DB.** After loading, run the capture probes yourself (the same sequence `tools/capture_cli.py plan` documents — global session info, returns, per-track info + sends + device parameters + nested rack chains) and assemble the result via `compile_snapshot`, passing your accumulated `loads` list:

   ```python
   from hallucinote.capture import compile_snapshot
   import json, pathlib

   snapshot = compile_snapshot(
       session_info=<dict from ableton_session(action='info')>,
       returns=<probed returns>,
       tracks=<probed tracks>,
       browser_paths=loads,  # the list you accumulated in step 4
   )
   pathlib.Path("songs/<slug>/captured_session.json").write_text(
       json.dumps(snapshot, indent=2)
   )
   ```

   Do NOT delegate this step to `/song-snapshot` — that skill's job is *refreshing* an existing snapshot from probes (it can't see `resolved_path` because Live doesn't track each device's browser origin after load). Only the just-loaded flow has the `resolved_path` values in hand, so the just-loaded flow is what writes them to the snapshot. The captured `devices[]` array preserves chain order; each device's `(class, display_name, browser_path, manufacturer, pack_name, params_dialed)` is what W13-A's fallback-identity path uses to re-find equivalents on another machine.

7. **For unrestricted mode only:** tell the user explicitly that the song is not strict-portable; collaborators will need to install whatever `compat check` flags before their push.

## Style hint

If the user supplied a style hint, let it steer tonal choice — `warm vintage analog` → Operator FM bells, Analog subtractive; `aggressive modern EDM` → Wavetable saws, Serum-style sounds in relaxed/unrestricted.

## Snapshot integration

Picks can also land in `captured_session.json` via composer-time `preset_query` selectors (`{root, pattern}`) without Live running — see `docs/snapshot-schema.md`. For built-in Live content, `preset_query` is portable across machines; for third-party plugins, `preset_uri` is per-machine and must be re-resolved on the consumer side.
