# Bug report — MixReport masking schema gaps (2026-06-11)

Context: first `mix-review` pass on `swell` in hallucinote-songs. Engine +
plugin 0.9.0, hallucinote-mcp `0.1.0+a5479db86125`, Live 12.4.1 Suite.
Report: `songs/swell/analysis/20260611T202022Z.json`.

---

## 1. Masking entries expose raw track IDs, not resolved names

**What happened.** The `per_section[n].masking` and `per_section[n].bed_masking`
arrays surface `masker_track_id` / `maskee_track_id` (raw IDs like `"track:4"`)
with no companion display-name fields. Reading code that expects `masker` /
`maskee` (as the skill documentation implies with examples like *"Drums masks
Bass 0.61 in lows"*) gets `None` back and the whole masking read fails silently.

**Exact raw shape** (from the report above):
```json
{
  "masker_track_id": "track:4",
  "maskee_track_id": "track:9",
  "masked_fraction": 0.893,
  "dominant_band": "mud (250-500)",
  "dominant_region_hz": [200.0, 300.0]
}
```

**What the skill doc implies:**
> `masking` — ranked ordered pairs `masker → maskee`, `masked_fraction` (0–1),
> `dominant_band`. "Drums masks Bass 0.61 in lows."

The narrative form only works if the reading agent has `surface_name` strings
directly in the masking entry. Without them, every consumer has to manually join
against the top-level `stems` list, and any code that reads `m["masker"]` gets
`None` without raising.

**Same issue in `bed_masking`**: only `maskee_track_id` is present, no name.

**Suggested fix.** Add `masker_surface_name` / `maskee_surface_name` (or just
`masker` / `maskee`) string fields to each masking and bed_masking entry at
analysis write time. The analyzer already has the surface-name map when building
the report. The raw `_track_id` fields can stay for programmatic use.

---

## 2. `per_section[n].section_id` is always `null`

**What happened.** Every `per_section` entry has `"section_id": null`. The
`section_name` string is correctly populated (`"breathe1"`, `"summit"`, etc.)
and `start_beat` / `end_beat` are correct, so the name-based path works. But
`section_id` is never set.

**Exact shape:**
```json
{
  "section_name": "breathe1",
  "section_id": null,
  "start_beat": 32.0,
  "end_beat": 165.0,
  ...
}
```

**Impact.** Any downstream code that tries to correlate a MixReport finding back
to a DB `sections` row (e.g. "write an annotation for the section whose finding
fired") can't do it via `section_id` and has to fall back to a name or beat
match. Low urgency since `section_name` is usable, but the null field is
confusing and contradicts the intent of having the field at all.

**Suggested fix.** Populate `section_id` from the DB `sections` record at
analysis write time, or remove the field if it isn't used.

---

## Repro

```bash
# In hallucinote-songs on the compose/missing branch:
python3 -c "
import json
with open('songs/swell/analysis/20260611T202022Z.json') as f:
    r = json.load(f)
s = r['per_section'][1]  # breathe1
print('section_id:', s['section_id'])          # None
print('masking[0] keys:', list(s['masking'][0].keys()))  # no 'masker' key
print('masking[0]:', s['masking'][0])
"
```
