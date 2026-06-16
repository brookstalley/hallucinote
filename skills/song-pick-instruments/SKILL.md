---
name: song-pick-instruments
description: Pick instrument **chains** per track (instrument + post-instrument FX + initial send levels) via Ableton's browser, respecting a portability mode (strict / relaxed / unrestricted). Filters `ableton://browser/instruments`, `ableton://browser/effects`, and `ableton://plugins/installed`, proposes a chain per track with rationale (why this combination, not just this instrument), confirms with the user, then loads every device in chain order via `ableton_device(action='load')` and writes initial sends. Use after scaffolding a song or when changing the instrumentation palette. The chain is authorship, not a mix-time todo — see `docs/song-authoring-conventions.md` "Sound design is authorship".
argument-hint: <tracks-csv> [portability=strict|relaxed|unrestricted] [style-hint]
user-invocable: true
disable-model-invocation: false
---

# /song-pick-instruments

> **Running engine commands.** The engine ships in the plugin's uv env. Resolve `$PY` once from `ableton://server/info`'s `python`; run `hallucinote inventory …` — and the inline `compile_snapshot` Python in the capture step — through it: `"$PY" -m hallucinote.cli …`, and run the inline `compile_snapshot` Python with the same interpreter (`"$PY" - <<'EOF' … EOF`). See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

You translate a track list (names alone — `Drums,Bass,Lead,Pads` — or name + role — `Drums (kit), Bass (sub), Lead (mono saw), Pads (warm)`) into concrete instrument **chains** — instrument + post-instrument processing + appropriate sends — then load them onto the song's tracks. Portability mode controls the catalogue.

$ARGUMENTS

## Rule: chains, not bare instruments

A finished song has the sound it's supposed to have. Pick a **chain** per track: instrument + post-instrument processing (saturation, EQ, compression, bus glue) + sends (initial levels into shared returns). The chain is one unit per track. Default chain shapes per role (drums, bass, lead, pads, vocals) live in `docs/song-authoring-conventions.md` "Default chain shapes" — read that for the per-role starting points and adjust per song style.

## Portability modes

- **strict** (default) — built-in Live devices only: read `ableton://browser/instruments` and `ableton://browser/effects`, not `ableton://plugins/installed`. Pick from whatever the user's Live actually exposes — their edition and installed Packs included. **The browser is the source of truth; never assume an edition or hardcode which devices "ship" with which edition** (it varies by version and Packs — probe, don't whitelist). This keeps the song free of third-party plugins, the big cross-machine portability risk. Portability is verified where it counts: at push the consumer's own browser resolves each `preset_query` and refuses loudly on a miss, and `compat check` surfaces gaps ahead of time.
- **relaxed** — stock + common third-party. Read both browser catalogues AND `ableton://plugins/installed`. Prefer well-known names (Serum, Massive X, Diva, Spire, Omnisphere, Kontakt). `compat check` flags missing ones on consumer machines.
- **unrestricted** — anything installed. Pick the best musical fit; tell the user explicitly this song is not strict-portable.

Reject unknown modes with a teaching error listing the valid choices.

## Steps

1. **Read the catalogue.** First decide live vs offline (see "Live vs offline" below).
   - **Live connected** — open the resources for the chosen mode. Each node has `{name, uri, is_loadable, is_folder?, children?}` — `name` is Live's browser display name (`Operator`, `Drum Rack`, `Meld`, `EQ Eight`); `uri` is the `query:...` or `plugins:...` string for `ableton_device(action='load', preset_uri=...)`. Filter to `is_loadable=true`. Read `ableton://browser/effects` too — that's where post-instrument processing comes from. Do NOT read a `class_name` field; it doesn't exist on browser nodes. **Then warm the offline cache** (see below) so future offline picks work.
   - **Offline** — read the machine inventory cache instead and author `preset_query` selectors. See "Live vs offline".

2. **Propose a chain per track — grounded in the song's intent.** First recall everything the song has declared: run `/song-context <slug>` (the brief, `decisions/`, annotations) and read `song.md`; if any parts are already composed, read each part's role / register / density from `build.py` + the arrangement. The palette serves *this* song's intent — its era, energy arc, and the job each part does — not a generic genre default. Then build ONE chain per track with rationale:
   - **`track`** — track name.
   - **`devices`** — ordered list `[{name, preset_uri, role}]` from instrument first to final-FX last. `role` is a short tag (`instrument`, `saturation`, `eq`, `compression`, `bus-glue`, `chorus`, `delay`, `reverb`).
   - **`sends`** — initial send levels `{return_name: level_0_to_1}` (skip 0.0-level sends).
   - **`rationale`** — one sentence per chain explaining sonic intent (why this combination).

   Drum tracks anchor on Drum Rack or Impulse — single-pitch synths don't make sense for a kit. Every pick traces to something the song declared — the energy arc, the era/character, the part's role — matched against what the browser actually offers (and the style hint, if one was given).

3. **Decide it together (propose-and-react).** Present the chains as a compact table — track / chain (instrument → FX1 → FX2) / sends / rationale — then surface the genuine choices for the user to own. Where two instruments both fit the intent but pull the character differently — a warm analog lead vs a bright digital one, an acoustic kit vs an 808 — name the fork and ask which way they hear it, rather than silently picking. The user may steer individual picks ("use Wavetable instead of Analog") or the whole chain shape ("don't compress the bass"). Honour and re-confirm. The instrument palette is a creative lock-in — collaborate on it, don't rubber-stamp a list.

4. **Load.** For each confirmed chain, load every device in order:
   - **First device** — use `/track-new-with-instrument` (creates track + loads instrument), OR if track exists: `ableton_device(action='load', node={'parent': {'kind': 'track', 'index': <i>}, 'terminal': 'track'}, kind=<name>, preset_uri=<uri>)`.
   - **Subsequent devices** — `ableton_device(action='load', node={'parent': {'kind': 'track', 'index': <i>}, 'terminal': 'track'}, kind=<name>, preset_uri=<uri>)` once per device, in order. A `track` terminal appends to the track's main chain; each lands at the end.
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

6. **Capture for the DB.** Run the capture probes yourself (the sequence `hallucinote.tools.capture_cli plan` documents — session info, returns, per-track info + sends + device parameters + nested rack chains) and assemble via `compile_snapshot`, passing your accumulated `loads`:

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
   "$PY" -m hallucinote.cli inventory refresh
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
   and run `"$PY" -m hallucinote.cli inventory refresh`, or proceed live now. Do
   not invent `preset_query` patterns blind — an unverified guess becomes a
   push-time failure.

When a query targets a root the cache marks `roots_partial` or `roots_excluded`
(e.g. `samples`), `find()` says so explicitly — that's a coverage gap, not
"not installed"; resolve those live at push.

## Style hint

If the user supplied a style hint, let it steer tonal choice — `warm vintage analog` → Operator FM bells, Analog subtractive; `aggressive modern EDM` → Wavetable saws, Serum-style sounds in relaxed/unrestricted.

## Audition by ear (the right direction; not here yet)

Today you pick by name + rationale, not by sound — the skill can't yet play a candidate so the user can hear it before committing. That's a real limit: the strongest instrument choice is often made by ear. Auditioning — load a candidate, play a short phrase, listen, keep or swap — is where this is headed (tracked in the backlog). Until it lands, lean on the rationale and the user's ear; when a pick is genuinely uncertain, invite them to audition it in Live and react.

## Snapshot integration

Picks can also land in `captured_session.json` via composer-time `preset_query` selectors (`{root, pattern}`) without Live running — see `docs/snapshot-schema.md`. Built-in Live content is portable across machines via `preset_query`; third-party plugins are per-machine and must be re-resolved consumer-side.

## Next: compose

With chains picked, compose the parts with **`/compose-part`** (author-as-code in
`build.py`), then read the result with **`/compose-review`** before pushing. The
full lifecycle is `/song-workflow`.
