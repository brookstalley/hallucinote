# Snapshot schema — `captured_session.json`

The snapshot is a JSON document describing the mix layout of an Ableton Live set. `hallucinote.capture.replay_capture` reads it and creates DB rows for tracks, returns, sends, master, devices, dialed parameters, and nested rack chains to any depth (DEEP-RACK-ADDR).

**Two roles for snapshots:**
1. **Captured** — `python -m hallucinote.tools.capture_cli` walks a running Live set via MCP and writes the result. Use this once you've staged the target Live shape.
2. **Synthetic** — `/hallucinote:song-new` generates a minimal snapshot (4 MIDI + 2 returns + master) so the build runs immediately on a brand-new song. Replace by capturing once Live is staged.

`replay_capture` is **idempotent**: re-replaying the same snapshot updates rows whose state changed and is a no-op for unchanged rows. The "song already exists" guard was removed; underlying mutators converge.

---

## Top-level shape

```json
{
  "_note":           "(optional) free-form author note",
  "_capture_status": "(optional) free-form provenance tag",
  "song":    { ... },
  "returns": [ ... ],
  "tracks":  [ ... ]
}
```

`_note` and `_capture_status` keys (and any other `_`-prefixed keys) are informational; `replay_capture` ignores them.

---

## `song`

```json
{
  "song": {
    "name":      "(optional, defaults to caller-supplied)",
    "key":       "(optional)",
    "tempo":     132.0,
    "signature": "4/4",
    "master":    {"volume": 0.85, "panning": 0.0,
                  "devices": [ ... ]}
  }
}
```

- `tempo` and `signature` are **informational** — the score-half `tempo_map` / `time_signature_map` tables are the source of truth. `build.py` writes those via `M.add_tempo_point` / `M.add_time_signature_point`.
- `master` becomes a `tracks` row with `kind='master'` and `track_index=0` (sentinel). Volume and panning use Live's normalized 0.0–1.0 / -1.0–1.0 ranges.
- `master.devices` (optional, **SNP-4K7M**) — a device chain on the master, same shape as a track's `devices[]` (see "Device chain shape" below). A master Limiter / EQ declared here round-trips: `replay_capture` materializes it on the master chain, the push side loads it (DEV-6M2K), and `/song-snapshot` captures a hand-placed master device back. The `HallucinoteAnalyzer` is filtered out at capture/migration exactly as on tracks and returns. Master **automation envelopes** are a separate, still-open surface (MAW-4K7P).

---

## `returns`

```json
"returns": [
  {
    "index": 1,
    "name": "A-Reverb",
    "volume": 0.85,
    "panning": 0.0,
    "color": null,
    "devices": [
      {"index": 1, "name": "Reverb", "class": "Reverb"}
    ]
  }
]
```

- `index` is 1-based, matching Live's slot ordering.
- **Name handling — return names: stored stripped.** Live unconditionally prefixes return names with `<slot-letter>-` (A-, B-, ...). `replay_capture` strips this on the way in — the DB stores `Reverb`, not `A-Reverb`. Push re-emits the suffix and Live re-adds its slot prefix. **Author trap**: hand-authored snapshots that write `"name": "A-Reverb"` get the prefix stripped silently; downstream `Q.get_return_by_name(..., "A-Reverb")` will fail to find the row because it's stored as `"Reverb"`. `replay_capture` emits a `UserWarning` summarizing strips so this isn't completely silent. Write the stripped form in hand-authored snapshots, and pass the stripped form to lookups. The regex strips any single uppercase-letter prefix (`[A-Z]-`), so names like `"Ghost-Reverb"` or `"Bus-A"` pass through unchanged.
- `volume` / `panning` optional; default is whatever Live applies to a freshly-created return.
- `devices` (optional) — see "Device chain shape" below.

---

## `tracks`

```json
"tracks": [
  {
    "index": 5,
    "name": "01 Drums",
    "type": "midi",
    "volume": 0.6249,
    "panning": 0.0,
    "mute": false,
    "solo": false,
    "arm": false,
    "color": null,
    "instrument_uri": "query:Drums#FileId_5418",
    "sends": {"A-Reverb": 0.0, "B-Delay": 0.0},
    "devices": [ ... ]
  }
]
```

- `index` is 1-based, matching Live's track slot ordering.
- `type` ∈ `{"midi", "audio", "group"}`. The legacy `"return"` value was dropped V1 close-out — real returns live in the `returns` array (different shape: no slots, no instrument).
- `volume` (0.0–1.0), `panning` (-1.0–1.0): nullable; `null` means "user never set" — push skips emission until set.
- `mute` / `solo` / `arm`: nullable booleans.
- `instrument_uri` (optional) — Live's `preset_uri` for the track's primary instrument (often present after a real capture; usually `null` for synthetic snapshots).
- `sends`: dict from return name (stripped: `A-Reverb` → `Reverb`) to send level (0.0–1.0). Entries map to `sends` rows via `M.set_send_level`.
- `devices` (optional) — see below.

---

## Device chain shape

```json
"devices": [
  {
    "index": 1,
    "name": "Late Nite Kit",
    "class": "Drum Rack",
    "class_name": "DrumGroupDevice",
    "kind": "instrument",
    "guess_uri": "query:Drums#FileId_5418",
    "params_dialed": {
      "Filter": {"value": "1", "normalized": 0.01},
      "Low Freq": {"value": "2.51 dB", "normalized": 0.71}
    },
    "params_total": 17,
    "chains": [
      {"chain_index": 1, "name": "Kick", "devices": [ ... ]}
    ]
  }
]
```

- `index` is 1-based, position in the chain.
- `class` is the **browser display name** for the device — what shows up in Live's browser tree and what the loader's kind-as-given walk matches against. Examples: `"Compressor"`, `"EQ Eight"`, `"Phaser-Flanger"`, `"Drum Rack"`, `"Operator"`. The pull-side capture writes Live's `device.class_display_name` here. Hand-authored snapshots MUST use the browser display name — internal class names like `"Compressor2"` or `"DrumGroupDevice"` no longer resolve (the translation table is gone; the loader uses what Live's own API reports). When in doubt, probe via `ableton_browser(action='tree', root='audio_effects', depth=2)` and copy the node's `name`.
- `class_name` (optional for Live built-ins; **REQUIRED for third-party plugins**) is Live's **internal class identifier** — `"Compressor2"`, `"PhaserNew"`, `"DrumGroupDevice"`, `"PluginDevice"`, etc. Informational for built-ins; load-bearing for plugin discrimination. compat-check classifies a device as third-party iff `class_name` is in `{PluginDevice, AuPluginDevice, Vst3PluginDevice}`. **For third-party plugins (Serum, Diva, Spitfire LABS, anything VST/AU), you MUST set `class_name` to the wrapper class** — otherwise compat falls back to `kind` (the plugin's display name like `"Serum"`), which isn't in the plugin family, and the plugin gets silently classified as a Live built-in. Capture-from-Live populates it correctly; hand-authored snapshots have to be explicit.
- `name` is the user-set display name on the device instance (often equal to `class` for default loads; preset names like "Late Nite Kit" persist; user renames also land here).
- `kind` (optional, **informational only**) — a free-form classification hint (`"instrument"` / `"audio_effect"` / `"midi_effect"`). The push loader does NOT read this field; it routes by `class` and `preset_query.root` only. Safe to omit; if included, treat it as author commentary, not a routing signal.
- `guess_uri` (optional) — Live's `preset_uri` for browser-reload. Most devices loaded via `ableton_browser` carry a URI; default empty devices may not. **Per-machine** (FileIds differ across machines for the same preset). Captured automatically by `python -m hallucinote.tools.capture_cli`; **hand-authoring URIs is unreliable** — prefer `preset_query` (below) for portable compose-time selection, OR probe via `ableton_browser` first.
- `preset_query` (optional, mutually exclusive with `guess_uri`) — **cross-machine portable preset selector.** A JSON object `{root, pattern, mode?, path_prefix?, case_sensitive?}` resolved at push time on the consumer's machine via `ableton_browser(action='search')`. The push planner threads this into `ableton_device(action='load', preset_query=...)`, which refuses the load if 0 or 2+ matches (strict — no fuzzy match).
  - **`root` must be one of** (loader-accepted enum, NOT the resource-URI form): `instruments`, `audio_effects`, `midi_effects`, `drums`, `plugins`, `samples`, `user_library`, `packs`. Common typo: writing `effects` (the resource-URI form) instead of `audio_effects` — the loader refuses. Compat-check (`python -m hallucinote.sync.compat check <slug>`) catches this at compose time.
  - **`path_prefix` MUST be a JSON list** of name segments, NOT a string. Wrong: `"path_prefix": "Tension"`. Right: `"path_prefix": ["Tension"]`. The loader raises `preset_query.path_prefix must be a list` on the string form.
  - **`pattern` is a substring match by default** (or a glob / regex via `mode`). Use a more-specific pattern, an explicit `.adv` suffix, or a tighter `path_prefix` when a broad pattern matches multiple presets — the strict loader refuses on 2+ matches.
  - Example: `"preset_query": {"root": "drums", "pattern": "Late Nite Kit"}`.
  - **Path-shape sugar.** `M.create_device(preset_query=...)` also accepts a path string like `"Drums/Kit-Core 909"` or `"Instruments/Operator/Bass/Pluck-Sub"` — first segment is the root (case-insensitive, `" "` ≡ `"_"`, so `"Audio Effects/Hall"` ≡ `"audio_effects/Hall"`), last segment is the pattern, anything in between is `path_prefix`. The mutator normalizes to the canonical dict before persisting (the DB always stores the structured form so downstream consumers see one shape). `mode` / `case_sensitive` aren't surfacable through the path-shape — authors who need those pass a dict. Snapshot JSON only carries the dict form (path-shape is a Python-API ergonomic).
- `browser_path` (optional) — fallback identity. JSON list of strings from the browser root key to the loaded item's name, e.g. `["plug-ins", "Native Instruments", "Massive X", "FatBass"]` or `["instruments", "Operator", "Bass", "Sub Bass"]`. Captured at original-load time by the MCP load handler (returned as `resolved_path` in the load response). Stored in `devices.browser_path_json`. Pairs with `guess_uri`, not `preset_query`: the planner emits `preset_uri` (fast path, per-machine FileId) AND `browser_path` (fallback identity, path-scoped search) together. On a target machine where the captured FileId doesn't resolve (same plugin under a different catalog id, or moved between Live versions), the MCP load handler falls back to a path-scoped browser search using `browser_path[0]` as the root, `browser_path[1:-1]` as the `path_prefix`, and `browser_path[-1]` as an exact-match pattern. Refuses on 0-match (plugin not installed at the captured path) and on multi-match (ambiguous within the captured scope) — both surface a teaching error so the agent can decide whether to surface the gap to the user. Older snapshots that omit this key keep the column NULL and the load uses preset_uri only (no fallback).
- `params_dialed` (optional) — **the home for static device-parameter authoring** ("sound design is authorship": EQ curves, comp thresholds, drum-bus settings, reverb Dry/Wet). **Sparse** — only NON-default params appear (a default is implied by absence), so a device with nothing dialed has no `params_dialed` key at all. Each entry is keyed by the param's display name with shape `{"value": <display-string-or-normalized-float>, "normalized"?: float, "value_items"?: [...], "value_raw"?: float}`. Flow: `replay_capture` reads each entry into a `device_parameters` row (`value` → `value_display`, `normalized` → `value_normalized`, `value_raw` → `value_raw`); the push planner emits it via `ableton_device(action='set_parameter')` after the device loads.
  - **Continuous params (frequency, gain, threshold, ratio) — author a DISPLAY STRING.** Write `{"value": "180 Hz"}`, `{"value": "-10 dB"}`, `{"value": "3:1"}`. The push emits `value_display` and the **live setter inverts the curve at push time** (DPP-7H2K — it bisects the device's own `str_for_value`, so a logarithmic EQ frequency knob is inverted for you). You do **not** hand-invert a log curve. A captured snapshot carries BOTH `value` and `normalized`; when both are present the display string wins at push.
  - **Quantized non-`[0,1]` params with a non-monotonic display — author `value_raw` (DEV-4P7R).** A param whose RAW range is not `[0,1]` and whose display is a non-monotonic step list (the witness: Wavetable `LFO 1 S. Rate`, raw `8.0` → "1/2", range `[0,21]`, displays `8,6,4,…,1/64`) cannot use either other channel: the display is **refused** at push (`DisplayValueError`, not monotonic) and `normalized` is pushed **as raw** (there is no `value_normalized` handler kwarg) so it mis-dials unless the raw range happens to be `[0,1]`. Author the literal raw value: `{"name": "LFO 1 S. Rate", "value_raw": 8.0}` (a readable `"value"` hint may ride alongside: `{"value": "1/2", "value_raw": 8.0}`). Push sends it as the continuous raw `value`, range-checked in Live against the param's true `[min,max]`. `value_raw` is mutually exclusive with `normalized` + `value_items`; it takes precedence over the display string. `/song-snapshot` + `/ableton-pull` emit `value_raw` automatically for any non-enum param whose raw range ≠ `[0,1]`.
  - **Trap — a bare numeric `value` with no `normalized`.** `{"value": 0.71}` (a JSON number) is stored as the display string `"0.71"` and pushed via the display path, mis-dialing a continuous param. To author a true 0..1 NORMALIZED value, set `normalized` explicitly: `{"value": "", "normalized": 0.71}`; for a quantized non-`[0,1]` param use `value_raw` (above). `replay_capture` warns when it sees a bare numeric value with no `normalized` / `value_raw`.
  - **Enum params (Filter Type = "Lowpass")** carry the display label as `value`, `"normalized": null` (no continuous form), and `"value_items": [...]` (Live's `value_items` order — the list index IS the numeric value Live stores), captured at pull time via `detail='full'` so `M.create_enum_envelope` can resolve enum-name breakpoints at compose time without build.py authors hand-listing cardinality.
- `params_total` (optional) — informational; count of all params on the device.
- `chains` (optional) — nested chains for rack devices (`Drum Rack`, `Instrument Rack`, `Audio Effect Rack` — browser display names). Recurses to ANY depth (DEEP-RACK-ADDR): a nested device may itself be a rack carrying its own `chains`. Replay walks the whole tree; push materializes nested dialed params via the canonical `device_path`. Each `chains[]` entry carries `chain_index` (1-based), `name`, an optional nested `devices[]`, and the optional **per-chain authored properties** below.
- **Per-chain authored properties** (optional, on a `chains[]` entry) — a chain's own authorable state, distinct from its `devices`. **Sparse / non-default-filtered** like `params_dialed` (absent = the Live/preset default). `replay_capture` reads them via the `set_chain_properties` mutator; push re-asserts them on the reloaded rack via the `node` `chain` terminal, so a by-ear chain tweak survives a `build.py --reset` rebuild **without saving the `.als`**. Which apply where: `ableton://reference/node-feature-matrix`; the authorship rationale (materialized-state leg): [`.prawduct/artifacts/authorship-model.md`](../.prawduct/artifacts/authorship-model.md).
  - `choke_group` (int, **DrumChain only**) — pads sharing a group cut each other off (the open/closed hi-hat). `0` / absent = no choke.
  - `out_note` (MIDI note 0–127, **DrumChain only**) — the pad's output transposed to this note; absent = the pad's `in_note` (no transpose).
  - `mute` / `solo` (bool; captured as `1`) — per-chain mute / solo *inside* the rack (**any chain**).
  - `volume` (0.0–1.0) / `pan` (−1.0..1.0) — the chain's mixer level / pan (**any chain**); absent = the chain's preset default.
  - `choke_group` / `out_note` on a plain (non-drum) chain are refused with a teaching error; the mixer four apply to every chain.
- `param_overrides` (optional, on a device entry — SNP-2H9F) — **the durable home for a by-ear tweak on a param NESTED inside a `preset_query` instrument.** A preset device loads its whole internal tree from the portable preset, so its descendants have NO snapshot `devices`/`chains` rows (the preset owns the structure). Dumping the full `chains` instead would drop the preset seed AND the preset's un-parameterizable timbre (a Wavetable waveform is not a `DeviceParameter`) and bloat the file. Instead, list each nested override here and **keep `preset_query`**:
  - Shape: a flat list of `{"path": [{"chain_index", "device_position"}, …], "name": <param>, "value": <display-string-or-normalized>, "normalized"?: float, "value_items"?: [...], "value_raw"?: float}`. `path` is the **NodeAddr descent** (1-based, DEEP-RACK-ADDR) from the preset device to the nested device the param lives on; the value fields are exactly `params_dialed`'s (same display-string / `normalized` / enum / **`value_raw`** rules + the bare-numeric trap). The `value_raw` channel (DEV-4P7R) bites hardest here — a preset instrument's nested params are the whole point, and the witness (Wavetable `LFO 1 S. Rate` two levels deep in swell's `Synth Vox Ai`) is exactly the quantized non-`[0,1]` non-monotonic class that needs it.
  - Flow: `replay_capture` lands them in `device_param_overrides` (keyed `device_id` + `path` + `name`); push re-asserts each via `ableton_device(action='set_parameter')` at `(device_index, path)` **after** the preset loads — **no chain creation**, so the preset's waveform/samples survive and nothing duplicates. A deep by-ear value survives a `build.py --reset` rebuild **without saving the `.als`**.
  - **Mutually exclusive with `chains` on the same device** (`replay_capture` raises): `chains` authors/dumps the nested tree; `param_overrides` overrides params on the preset-instantiated tree in place. Author one. `/song-snapshot` emits `param_overrides` (not a `chains` dump) for a device the prior snapshot loaded via `preset_query`; a preset DRUM rack with authored per-chain props keeps its `chains` dump instead (those props can't ride `param_overrides` — a documented fast-follow).
- `sidechain_source` (optional, on a device entry — BAK-3M9T) — **the durable home for a device's sidechain SOURCE** (a sidechained Compressor / Gate's "Audio From" track — the one mix element the `S/C On` / `S/C Gain` / `S/C Mix` params can't carry; those ride `params_dialed`). **Stored by the source track's surface NAME** (`"Kick"`), never a per-build UUID — exactly like a send keys its return by name. `replay_capture` resolves the name → the song's track id and applies it via `set_device_sidechain` AFTER every track exists (so a source may name a track created later in the snapshot). A name that matches no track in `tracks[]` raises (same hard contract as a send to a missing return) — only reachable via a hand-authored snapshot, since capture pre-filters unresolvable sources (below).
  - `sidechain_source_channel` (optional, alongside `sidechain_source`) — Live's input-channel display name (`"Pre FX"` / `"Post FX"` / `"Post Mixer"`); absent = the device default.
  - **The source is always a track** — the DB column `devices.sidechain_source_track_id` references `tracks(id)` (SDC-7K3M). A sidechain off a *return* / master / external input isn't representable; capture does NOT drop it silently — it emits a `UserWarning` listing each dropped source so you can RE-APPLY it manually in Live (the umbrella's no-silent-drop guarantee). **Top-level devices only**, matching the pull's scope — a nested sidechained compressor is uncommon and not auto-captured (a hand-authored `sidechain_source` on a nested entry still replays).
  - **Snapshot is authoritative** — capture omits the field *quietly* for the own-track default input (Live reports a device's own host track as its default "Audio From" — that is not a sidechain). A device with no `sidechain_source` **clears** any prior source on rebuild (idempotent), the same drop-clears-stale rule as the per-chain properties above. This is what makes `/song-snapshot` the single durable mix bake for sidechain (BAK-3M9T): a dialed sidechain round-trips through `captured_session.json` and survives a `build.py` rebuild.

### Multi-device chains (sound is composition)

Per "sound is composition" (see `docs/song-authoring-conventions.md` and `/hallucinote:song-pick-instruments`), a track's `devices[]` typically holds a *chain* — instrument + post-instrument processing — not a single device. The chain is part of authorship and ships in the snapshot, not as a "mix-time follow-up":

```json
"devices": [
  {
    "index": 1,
    "name": "Hot Rod Kit",
    "class": "Drum Rack",
    "class_name": "DrumGroupDevice",
    "kind": "instrument",
    "preset_query": {"root": "drums", "pattern": "Hot Rod Kit"}
  },
  {
    "index": 2,
    "name": "Saturator",
    "class": "Saturator",
    "kind": "audio_effect",
    "params_dialed": {"Drive": {"value": "5.0 dB", "normalized": 0.55}}
  },
  {
    "index": 3,
    "name": "Glue Compressor",
    "class": "Glue Compressor",
    "kind": "audio_effect",
    "params_dialed": {"Ratio": {"value": "4", "normalized": 0.50}, "Threshold": {"value": "-8.0 dB", "normalized": 0.60}}
  }
]
```

(Note `"class": "Glue Compressor"` — the browser display name. The loader matches `kind` against display names ONLY; the internal Live class name `GlueCompressor` no longer resolves. The optional `class_name` field is where you record the internal class for informational use — pull populates it from Live's `device.class_name`.)

Top-to-bottom matches signal flow. `replay_capture` loads them in `index` order, so the chain ends up on the track in the same shape on the consumer's machine. The push planner drives `ableton_device(action='load')` once per device; `params_dialed` is applied after load.

---

## Canonical workflow: stage chain → push → recapture

For songs that need verified-against-Live chain state (most creative product prompts — a finished song to press play on), use this loop instead of pure hand-authoring:

1. **Pick chains via `/hallucinote:song-pick-instruments`.** It proposes per-track chains, confirms with the user, and writes the picks into `captured_session.json` (composer-time, before Live touches anything).
2. **Push the song with `/hallucinote:ableton-push`.** The push planner loads each chain device-by-device in order, applies `params_dialed`, and initializes send levels.
3. **Stage in Live** (only if the picker couldn't fully specify). Dial in params that need ear-driven tuning (Saturator Drive, Glue threshold). Most picks shouldn't need this — `/hallucinote:song-pick-instruments` aims to ship sound-correct defaults.
4. **Recapture via `/hallucinote:song-snapshot` (or `python -m hallucinote.tools.capture_cli`).** Writes a `captured_session.refresh.json` side-by-side; diff against the existing snapshot; confirm; overwrite. Now `captured_session.json` reflects the actual chain state — the next push from a fresh DB will reproduce it exactly.

The recapture step is what makes step 3 ("staging in Live") part of authorship and not a sidecar. The on-disk snapshot is the source of truth for sound design once you've recaptured. See `/hallucinote:song-snapshot` for the diff-and-confirm flow.

---

## What `replay_capture` doesn't ingest

- **Clips** and **notes**. The snapshot can carry `"clips": [...]` on tracks but `replay_capture` ignores them. Clips are authored by `build.py` (the compose-half).
- **Score-half**: tempo map, time signature map, sections, cue points. All authored by `build.py`.
- **Automation envelopes**. The capture pipeline doesn't ingest envelopes (MCP envelope-read exists; capture-side reading is still backlog).

---

## Picking built-in content presets (drum kits, instrument presets)

For built-in Live content (Operator presets, Impulse drum kits, Drum Rack content) you have three options, in order of portability:

1. **`preset_query`** (most portable, recommended for hand-authored snapshots). Express the kit by name + scope: `{"root": "drums", "pattern": "Late Nite Kit"}`. The push planner resolves it on the consumer's machine via `ableton_browser(action='search')`. Strict — refuses if 0 or 2+ matches. No FileId baked in; transfers cross-machine cleanly. Best for built-ins whose names are stable across Live installations.
2. **Capture-then-recapture loop.** Stand up the device by hand in Live (or via `ableton_device(action='load')` directly), then run `python -m hallucinote.tools.capture_cli` against the running set. The capture pipeline records `guess_uri` for you — accurate, but per-machine.
3. **Hand-authored `guess_uri`** — discouraged. Hand-written URIs are unreliable. If you do this, verify the URI exists via `ableton_browser(action='at_path', ...)` first.

### Default-device vs named-preset

Live's browser tree exposes some devices BOTH as loadable nodes (load the device with default settings) AND as folders containing preset leaves. `Hybrid Reverb` is both: a Hybrid Reverb node (loads the device with default settings) and a `Hybrid Reverb/Hall/...` folder of presets.

For "load the device with default settings" use **NO `preset_query`** and rely on `class`:

```json
{"index": 1, "name": "Hybrid Reverb", "class": "Hybrid Reverb", "class_name": "HybridReverb"}
```

For "load a named preset" use **`preset_query` pointing at a leaf** (typically a `.adv` file). The path_prefix narrows to the preset folder; the pattern is the leaf name:

```json
{
  "index": 1,
  "name": "Cathedral Bloom",
  "class": "Hybrid Reverb",
  "class_name": "HybridReverb",
  "preset_query": {
    "root": "audio_effects",
    "pattern": "Cathedral Bloom",
    "path_prefix": ["Hybrid Reverb", "Hall"]
  }
}
```

Do **not** target a folder name in `pattern` (e.g. `pattern: "Vintage Delay"` when "Vintage Delay" is a folder, not a leaf). The strict loader will report 0 matches (no leaf at that path) or N matches (several siblings inside the folder), and refuse either way. When in doubt, run `ableton_browser(action='search', root=..., pattern=...)` once and confirm the result is exactly one leaf.

---

## Hand-authoring tips

- **Start from the `/hallucinote:song-new` scaffold's synthetic snapshot** — it's the minimal shape that satisfies `replay_capture`. Edit from there.
- **Names must match across `sends` keys and `returns[].name`** (after slot-prefix stripping). A `sends` entry to `"Reverb"` resolves to the return named `"Reverb"` (or originally `"A-Reverb"`).
- **The `"index"` keys are 1-based across the board** (Live convention; also enforced by schema CHECKs on the DB side).
- **Synthetic snapshots are fine as a starting point**, but their `volume`/`panning` defaults won't match the eventual Live state. Recapture (via `python -m hallucinote.tools.capture_cli`) once you've staged Live.

---

## Reference

- Implementation: `src/hallucinote/capture.py` (`replay_capture` is the entry point).
- Example: a song's `captured_session.json` in the separate **hallucinote-songs** repo (e.g. `songs/<slug>/captured_session.json` — a real capture from a populated session). Songs no longer live in this framework repo (see `project-root-contract`).
- Scaffold template: `src/hallucinote/tools/templates/song/captured_session.json.tmpl`.
