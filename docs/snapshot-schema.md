# Snapshot schema — `captured_session.json`

The snapshot is a JSON document describing the mix layout of an Ableton Live set. `hallucinote.capture.replay_capture` reads it and creates DB rows for tracks, returns, sends, master, devices, dialed parameters, and one level of nested rack chains.

**Two roles for snapshots:**
1. **Captured** — `tools/capture.py` walks a running Live set via MCP and writes the result. Use this once you've staged the target Live shape.
2. **Synthetic** — `/new-song` generates a minimal snapshot (4 MIDI + 2 returns + master) so the build runs immediately on a brand-new song. Replace by capturing once Live is staged.

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
- **Name handling**: Live unconditionally prefixes return names with `<slot-letter>-` (A-, B-, ...). `replay_capture` strips this on the way in — the DB stores `Reverb`, not `A-Reverb`. Push re-emits the suffix and Live re-adds its slot prefix.
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
- `guess_uri` (optional) — Live's `preset_uri` for browser-reload. Most devices loaded via `ableton_browser` carry a URI; default empty devices may not. **Hand-authoring URIs is unreliable** (Wave 0 spa-7c). Prefer probing via `ableton_browser` first.
- `params_dialed` (optional) — only **dialed** params (defaults are implied by absence). Discrete-enum params (Filter Type = "Lowpass") have `"normalized": null` because there's no continuous form.
- `params_total` (optional) — informational; count of all params on the device.
- `chains` (optional) — nested chains for rack devices (`DrumGroupDevice`, `InstrumentGroupDevice`, `AudioEffectGroupDevice`). One level only — nested-nested racks raise on encounter (filed in backlog).

---

## What `replay_capture` doesn't ingest

- **Clips** and **notes**. The snapshot can carry `"clips": [...]` on tracks but `replay_capture` ignores them. Clips are authored by `build.py` (the compose-half).
- **Score-half**: tempo map, time signature map, sections, cue points. All authored by `build.py`.
- **Automation envelopes**. The capture pipeline doesn't ingest envelopes (MCP envelope-read landed W6; capture-side reading is still backlog).

---

## Hand-authoring tips

- **Start from the `/new-song` scaffold's synthetic snapshot** — it's the minimal shape that satisfies `replay_capture`. Edit from there.
- **Names must match across `sends` keys and `returns[].name`** (after slot-prefix stripping). A `sends` entry to `"Reverb"` resolves to the return named `"Reverb"` (or originally `"A-Reverb"`).
- **The `"index"` keys are 1-based across the board** (Live convention; also enforced by schema CHECKs on the DB side).
- **Synthetic snapshots are fine as a starting point**, but their `volume`/`panning` defaults won't match the eventual Live state. Recapture (via `tools/capture.py`) once you've staged Live.

---

## Reference

- Implementation: `src/hallucinote/capture.py` (`replay_capture` is the entry point).
- Example: `songs/falling-walking/captured_session.json` (real capture from a populated session).
- Scaffold template: `tools/templates/song/captured_session.json.tmpl`.
