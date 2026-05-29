---
name: song-pick-instruments
description: Pick instrument **chains** per track (instrument + post-instrument FX + initial send levels) via Ableton's browser, respecting a portability mode (strict / relaxed / unrestricted). Filters `ableton://browser/instruments`, `ableton://browser/effects`, and `ableton://plugins/installed`, proposes a chain per track with rationale (why this combination, not just this instrument), confirms with the user, then loads every device in chain order via `ableton_device(action='load')` and writes initial sends. Use after scaffolding a song or when changing the instrumentation palette. The chain is authorship, not a mix-time todo — see `docs/song-authoring-conventions.md` "Sound design is authorship".
argument-hint: <tracks-csv> [portability=strict|relaxed|unrestricted] [style-hint]
user-invocable: true
disable-model-invocation: false
---

# /song-pick-instruments

You translate a track list (names alone — `Drums,Bass,Lead,Pads` — or name + role — `Drums (kit), Bass (sub), Lead (mono saw), Pads (warm)`) into concrete instrument **chains** — instrument + post-instrument processing + appropriate sends — then load them onto the song's tracks. Portability mode controls the catalogue.

$ARGUMENTS

## Rule: chains, not bare instruments

A finished song has the sound it's supposed to have. Pick a **chain** per track: instrument + post-instrument processing (saturation, EQ, compression, bus glue) + sends (initial levels into shared returns). The chain is one unit per track. Default chain shapes per role (drums, bass, lead, pads, vocals) live in `docs/song-authoring-conventions.md` "Default chain shapes" — read that for the per-role starting points and adjust per song style.

## Portability modes

- **strict** (default) — stock Live devices only. Read `ableton://browser/instruments` and `ableton://browser/effects`; do NOT read `ableton://plugins/installed`. Guarantees the song opens on any Live install of the same edition. Suite-only instruments: Operator, Analog, Electric, Tension, Collision, Drift, Meld. Standard ships: Wavetable, Simpler, Sampler, Drum Rack, Impulse.
- **relaxed** — stock + common third-party. Read both browser catalogues AND `ableton://plugins/installed`. Prefer well-known names (Serum, Massive X, Diva, Spire, Omnisphere, Kontakt). `compat check` flags missing ones on consumer machines.
- **unrestricted** — anything installed. Pick the best musical fit; tell the user explicitly this song is not strict-portable.

Reject unknown modes with a teaching error listing the valid choices.

## Steps

1. **Read the catalogue.** First decide live vs offline (see "Live vs offline" below).
   - **Live connected** — open the resources for the chosen mode. Each node has `{name, uri, is_loadable, is_folder?, children?}` — `name` is Live's browser display name (`Operator`, `Drum Rack`, `Meld`, `EQ Eight`); `uri` is the `query:...` or `plugins:...` string for `ableton_device(action='load', preset_uri=...)`. Filter to `is_loadable=true`. Read `ableton://browser/effects` too — that's where post-instrument processing comes from. Do NOT read a `class_name` field; it doesn't exist on browser nodes. **Then warm the offline cache** (see below) so future offline picks work.
   - **Offline** — read the machine inventory cache instead and author `preset_query` selectors. See "Live vs offline".

2. **Propose a chain per track.** Build ONE chain per track with rationale:
   - **`track`** — track name.
   - **`devices`** — ordered list `[{name, preset_uri, role}]` from instrument first to final-FX last. `role` is a short tag (`instrument`, `saturation`, `eq`, `compression`, `bus-glue`, `chorus`, `delay`, `reverb`).
   - **`sends`** — initial send levels `{return_name: level_0_to_1}` (skip 0.0-level sends).
   - **`rationale`** — one sentence per chain explaining sonic intent (why this combination).

   Drum tracks anchor on Drum Rack or Impulse — single-pitch synths don't make sense for a kit. Use the style hint and the song's `decisions/` files (especially `02-tempo.md`, `07-energy-aesthetic.md`) to steer character.

3. **Confirm.** Present chains as a compact table — track / chain (instrument → FX1 → FX2) / sends / rationale. Wait for OK or substitutions. The user may steer individual picks ("use Wavetable instead of Analog") or the whole chain shape ("don't compress the bass"). Honour and re-confirm.

4. **Load.** For each confirmed chain, load every device in order:
   - **First device** — use `/track-new-with-instrument` (creates track + loads instrument), OR if track exists: `ableton_device(action='load', track_index=<i>, kind=<name>, preset_uri=<uri>)`.
   - **Subsequent devices** — `ableton_device(action='load', track_index=<i>, kind=<name>, preset_uri=<uri>)` once per device, in order. Each lands at the end of the chain.
   - **`kind` is REQUIRED** — pass the browser node's `name` directly (browser display name; see `ableton://guides/conventions`).
   - **Capture `resolved_path` after each load.** Every load response carries `resolved_path` (browser-path segments). Keep a running list:
     ```python
     loads = []  # accumulated across all tracks
     # after each ableton_device(action='load') call:
     loads.append({
         "track_index": <i>,
         "device_index": <response.device_index>,
         "browser_path": <response.resolved_path>,
     })
     ```
     This goes to `compile_snapshot(..., browser_paths=loads)` in Step 6 for cross-machine fallback identity. Skipping doesn't break the load itself but loses portability for teammates on different Live installs.
   - **Sends** — `ableton_track(action='set_send', track_index=<i>, return_index=<j>, value=<0..1>)`. Skip 0.0-level sends.

5. **Write a signal-chain decision.** Write `songs/<slug>/decisions/NN-signal-chains.md` (next free `NN`). See `docs/song-authoring-conventions.md` for the decision-file template (or copy an existing `NN-signal-chains.md` from another song as a model). The decision IS the sound design — treat post-instrument processing as authorship, not a mix-time follow-up.

6. **Capture for the DB.** Run the capture probes yourself (the sequence `tools/capture_cli.py plan` documents — session info, returns, per-track info + sends + device parameters + nested rack chains) and assemble via `compile_snapshot`, passing your accumulated `loads`:

   ```python
   from hallucinote.capture import compile_snapshot
   import json, pathlib

   snapshot = compile_snapshot(
       session_info=<dict from ableton_session(action='info')>,
       returns=<probed returns>,
       tracks=<probed tracks>,
       browser_paths=loads,
   )
   pathlib.Path("songs/<slug>/captured_session.json").write_text(
       json.dumps(snapshot, indent=2)
   )
   ```

   Do NOT delegate to `/song-snapshot` — that skill refreshes existing snapshots from probes and can't see `resolved_path` (Live doesn't track per-device browser origin after load). Only the just-loaded flow has these values in hand.

7. **For unrestricted mode:** tell the user explicitly the song is not strict-portable.

## Live vs offline

This skill works whether or not Ableton Live is running. Picking by name without
Live is what kills the old push-then-recapture loop. There are exactly four
states — handle each, never silently guess:

1. **Live connected.** Use the live browser resources (Step 1). After loading,
   **warm the cache** so the offline path stays usable:
   ```bash
   python -m hallucinote.inventory refresh
   ```
   Run this whenever you have Live up — it's cheap insurance for the next
   offline session. (It walks the installed library one root at a time;
   `samples` is excluded by default.)

2. **Live not running, cache fresh.** Read the cache and pick by name:
   ```python
   from hallucinote import inventory
   cache = inventory.read_cache()              # None if it has never been built
   age = inventory.cache_age_days(cache)       # advisory only
   entry = inventory.find(cache, "Drums/Kit-Core 909")  # or a {root, pattern, ...} dict
   ```
   `find()` resolves with the SAME strict single-match semantics as push, so a
   pick that resolves here resolves identically when you push with Live open.
   Author the chain with **`preset_query` only** (root + pattern) — never a
   per-machine `uri`/FileId. This is inherently portability-**strict**;
   third-party plugins (relaxed/unrestricted) are per-machine and can't be
   picked offline — tell the user and defer those picks to a live session.

3. **Live not running, cache stale.** Same as (2), but tell the user the cache
   is N days old and offer to refresh it next time Live is up. Staleness is
   **advisory, never blocking** — proceed with the pick. If a chosen preset was
   uninstalled since the last refresh, the `preset_query` fails *loudly at push*
   (in Live, where it can be confirmed), never as a silent wrong load.

4. **Live not running, no cache** (`read_cache()` returns `None`). You cannot
   pick built-in content by name offline yet. Tell the user to open Live once
   and run `python -m hallucinote.inventory refresh`, or proceed live now. Do
   not invent `preset_query` patterns blind — an unverified guess becomes a
   push-time failure.

When a query targets a root the cache marks `roots_partial` or `roots_excluded`
(e.g. `samples`), `find()` says so explicitly — that's a coverage gap, not
"not installed"; resolve those live at push.

## Style hint

If the user supplied a style hint, let it steer tonal choice — `warm vintage analog` → Operator FM bells, Analog subtractive; `aggressive modern EDM` → Wavetable saws, Serum-style sounds in relaxed/unrestricted.

## Snapshot integration

Picks can also land in `captured_session.json` via composer-time `preset_query` selectors (`{root, pattern}`) without Live running — see `docs/snapshot-schema.md`. Built-in Live content is portable across machines via `preset_query`; third-party plugins are per-machine and must be re-resolved consumer-side.
