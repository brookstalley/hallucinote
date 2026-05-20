# Snapshot schema — `captured_session.json`

The snapshot is a JSON document describing the mix layout of an Ableton Live set. `hallucinote.capture.replay_capture` reads it and creates DB rows for tracks, returns, sends, master, devices, dialed parameters, and one level of nested rack chains.

**Two roles for snapshots:**
1. **Captured** — `tools/capture.py` walks a running Live set via MCP and writes the result. Use this once you've staged the target Live shape.
2. **Synthetic** — `/song-new` generates a minimal snapshot (4 MIDI + 2 returns + master) so the build runs immediately on a brand-new song. Replace by capturing once Live is staged.

W12-A guarantees `replay_capture` is **idempotent**: re-replaying the same snapshot updates rows whose state changed and is a no-op for unchanged rows. The "song already exists" guard was removed; underlying mutators converge.

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
    "master":    {"volume": 0.85, "panning": 0.0}
  }
}
```

- `tempo` and `signature` are **informational** — the score-half `tempo_map` / `time_signature_map` tables are the source of truth. `build.py` writes those via `M.add_tempo_point` / `M.add_time_signature_point`.
- `master` becomes a `tracks` row with `kind='master'` and `track_index=0` (sentinel). Volume and panning use Live's normalized 0.0–1.0 / -1.0–1.0 ranges.

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
    "class": "DrumGroupDevice",
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
- `class` is Live's device class name (`Compressor2`, `Eq8`, `DrumGroupDevice`, `InstrumentGroupDevice`, `AudioEffectGroupDevice`, ...). Source of truth for "what kind of device is this." Note: Wave 0 surfaced that `class` doesn't always map 1:1 to the loader's accepted `kind` value (`AnalogDevice` rejection — backlog item filed).
- `name` is the user-set display name (often equal to class; preset names like "Late Nite Kit" persist).
- `guess_uri` (optional) — Live's `preset_uri` for browser-reload. Most devices loaded via `ableton_browser` carry a URI; default empty devices may not. **Per-machine** (FileIds differ across machines for the same preset). Captured automatically by `tools/capture.py`; **hand-authoring URIs is unreliable** — prefer `preset_query` (below) for portable compose-time selection, OR probe via `ableton_browser` first.
- `preset_query` (optional, mutually exclusive with `guess_uri`) — **Sweep B: cross-machine portable preset selector.** A JSON object `{root, pattern, mode?, path_prefix?, case_sensitive?}` resolved at push time on the consumer's machine via `ableton_browser(action='search')`. Example: `"preset_query": {"root": "drums", "pattern": "Late Nite Kit"}`. The push planner threads this into `ableton_device(action='load', preset_query=...)`, which refuses the load if 0 or 2+ matches (strict — no fuzzy match). Use this for built-in Live content that has a stable name across machines (drum kits, instrument presets) so the snapshot doesn't bake in this machine's FileId.
- `params_dialed` (optional) — only **dialed** params (defaults are implied by absence). Discrete-enum params (Filter Type = "Lowpass") have `"normalized": null` because there's no continuous form.
- `params_total` (optional) — informational; count of all params on the device.
- `chains` (optional) — nested chains for rack devices (`DrumGroupDevice`, `InstrumentGroupDevice`, `AudioEffectGroupDevice`). One level only — nested-nested racks raise on encounter (filed in backlog).

### Multi-device chains (sound is composition)

Per "sound is composition" (see `docs/song-authoring-conventions.md` and `/song-pick-instruments`), a track's `devices[]` typically holds a *chain* — instrument + post-instrument processing — not a single device. The chain is part of authorship and ships in the snapshot, not as a "mix-time follow-up":

```json
"devices": [
  {
    "index": 1,
    "name": "Hot Rod Kit",
    "class": "DrumGroupDevice",
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
    "class": "Glue",
    "kind": "audio_effect",
    "params_dialed": {"Ratio": {"value": "4", "normalized": 0.50}, "Threshold": {"value": "-8.0 dB", "normalized": 0.60}}
  }
]
```

Top-to-bottom matches signal flow. `replay_capture` loads them in `index` order, so the chain ends up on the track in the same shape on the consumer's machine. The push planner (W12-A + Sweep B) drives `ableton_device(action='load')` once per device; `params_dialed` is applied after load.

---

## Canonical workflow: stage chain → push → recapture

For songs that need verified-against-Live chain state (most "make-me-X" prompts), use this loop instead of pure hand-authoring:

1. **Pick chains via `/song-pick-instruments`.** It proposes per-track chains, confirms with the user, and writes the picks into `captured_session.json` (composer-time, before Live touches anything).
2. **Push the song with `/ableton-push`.** The push planner loads each chain device-by-device in order, applies `params_dialed`, and initializes send levels.
3. **Stage in Live** (only if the picker couldn't fully specify). Dial in params that need ear-driven tuning (Saturator Drive, Glue threshold). Most picks shouldn't need this — `/song-pick-instruments` aims to ship sound-correct defaults.
4. **Recapture via `/song-snapshot` (or `tools/capture.py`).** Writes a `captured_session.refresh.json` side-by-side; diff against the existing snapshot; confirm; overwrite. Now `captured_session.json` reflects the actual chain state — the next push from a fresh DB will reproduce it exactly.

The recapture step is what makes step 3 ("staging in Live") part of authorship and not a sidecar. The on-disk snapshot is the source of truth for sound design once you've recaptured. See `/song-snapshot` for the diff-and-confirm flow.

---

## What `replay_capture` doesn't ingest

- **Clips** and **notes**. The snapshot can carry `"clips": [...]` on tracks but `replay_capture` ignores them. Clips are authored by `build.py` (the compose-half).
- **Score-half**: tempo map, time signature map, sections, cue points. All authored by `build.py`.
- **Automation envelopes**. The capture pipeline doesn't ingest envelopes (MCP envelope-read landed W6; capture-side reading is still backlog).

---

## Picking built-in content presets (drum kits, instrument presets)

For built-in Live content (Operator presets, Impulse drum kits, Drum Rack content) you have three options, in order of portability:

1. **`preset_query`** (most portable, recommended for hand-authored snapshots). Express the kit by name + scope: `{"root": "drums", "pattern": "Late Nite Kit"}`. The push planner resolves it on the consumer's machine via `ableton_browser(action='search')`. Strict — refuses if 0 or 2+ matches. No FileId baked in; transfers cross-machine cleanly. Best for built-ins whose names are stable across Live installations.
2. **Capture-then-recapture loop.** Stand up the device by hand in Live (or via `ableton_device(action='load')` directly), then run `python tools/capture.py` against the running set. The capture pipeline records `guess_uri` for you — accurate, but per-machine.
3. **Hand-authored `guess_uri`** — discouraged. Hand-written URIs are unreliable per Wave 0 (spa-7c). If you do this, verify the URI exists via `ableton_browser(action='at_path', ...)` first.

---

## Hand-authoring tips

- **Start from the `/song-new` scaffold's synthetic snapshot** — it's the minimal shape that satisfies `replay_capture`. Edit from there.
- **Names must match across `sends` keys and `returns[].name`** (after slot-prefix stripping). A `sends` entry to `"Reverb"` resolves to the return named `"Reverb"` (or originally `"A-Reverb"`).
- **The `"index"` keys are 1-based across the board** (Live convention; also enforced by schema CHECKs on the DB side).
- **Synthetic snapshots are fine as a starting point**, but their `volume`/`panning` defaults won't match the eventual Live state. Recapture (via `tools/capture.py`) once you've staged Live.

---

## Reference

- Implementation: `src/hallucinote/capture.py` (`replay_capture` is the entry point).
- Example: `songs/falling-walking/captured_session.json` (real capture from a populated session).
- Scaffold template: `tools/templates/song/captured_session.json.tmpl`.
