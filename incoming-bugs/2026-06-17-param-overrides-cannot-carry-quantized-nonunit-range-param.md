# `param_overrides` (SNP-2H9F) can't carry a quantized continuous param whose raw range ≠ [0,1] and whose display is non-monotonic (e.g. Wavetable `LFO * S. Rate`)

**Date:** 2026-06-17
**Severity:** medium — partial durability loss on the very case SNP-2H9F was built
for. The new `param_overrides` channel durably carries an **enum** nested override
(verified), but **silently cannot express** a sibling quantized param on the same
device. Half the by-ear fix survives a from-scratch rebuild; the other half reverts
with no durable home. The original SNP-2H9F report's own proposed-fix EXAMPLE is
wrong for this param class (see below).

**Relationship to SNP-2H9F (PR #176, commit 2feb163):** that fix shipped and is
correct for what it covers. This is a residual facet discovered while *applying*
it to the swell case it was written for. Not a regression — a gap the design didn't
reach.

## Repro (swell, real — the same `21 Voice Lead` case as SNP-2H9F)

The by-ear voice vibrato fix is TWO nested-Wavetable params at path `[{1,1},{1,1}]`
inside the `preset_query` "Synth Vox Ai" rack (track 21):

| param | kind | working value | channel result |
|---|---|---|---|
| `LFO 1 Sync` | enum `["Free","Tempo"]` | `Tempo` | ✅ baked durably via `param_overrides` (verified: materializes + re-asserts) |
| `LFO 1 S. Rate` | quantized continuous, `min 0 / max 21`, raw **8.0** → displays **"1/2"** (default 15.0 → "1/8") | raw `8.0` | ❌ **no channel can carry it** |

Authoring `{"name":"LFO 1 S. Rate","value":"1/2"}` and/or `"normalized":0.38095238`
(exactly the original report's proposed example, lines ~96–98) does NOT round-trip.

## Root cause — a three-way bind

For a continuous param the override has two wire channels (`_param_value_kv`,
`sync/push/devices.py:309`). Both fail for `LFO 1 S. Rate`:

1. **`value_display` ("1/2") → REFUSED at push.** `ableton_device(set_parameter,
   value_display="1/2")` returns:
   > `DisplayValueError: parameter 'LFO 1 S. Rate' display isn't monotonic across
   > its range ('8'..'1/64') even after unit normalisation, so value_display can't
   > address it; use the normalized value`

   The fraction displays (`8, 6, 4, 3, 2, 1, 1/2, 1/4 … 1/64`) aren't numerically
   parseable/monotonic to the curve inverter. So the display channel is out.

2. **`value_normalized` → clamped to [0,1] AND structurally unreachable.**
   - `replace_device_param_overrides` (`db/mutations/devices.py:927-936`) raises
     `value_normalized {v} out of range [0.0, 1.0]` — so the working **raw 8.0**
     cannot be stored at all.
   - Even if it could: push's normalized branch emits the stored number as the
     **raw** `set_parameter` value (`devices.py:331-333`:
     `{"value": str(p["value_normalized"]), "value_type":"continuous"}`). The
     handler range-checks raw against the param's TRUE `[min,max]` (here `[0,21]`),
     **not** [0,1]. So the channel only round-trips when the param's raw range IS
     [0,1] (raw == normalized). For `[0,21]`, a stored normalized `0.381` dials raw
     `0.381` → displays **"8"** (coarsest), not "1/2". The "normalized" column is
     used as a raw value; the name lies.
   - And it's never even reached: replay `_param_value_fields` (`capture.py:212`)
     ALWAYS sets `value_display = str(value)`, and push checks `value_display`
     BEFORE `value_normalized` (`devices.py:328`). So a hand-authored override with
     any `value` falls into branch (1) and gets refused; the normalized branch is
     dead code for the replay→push path.

**Net:** there is no authorable form for a quantized continuous param whose raw
range ≠ [0,1] and whose display is non-monotonic. (`params_dialed` on a top-level
device has the same two channels, so the same class of param is unauthorable there
too — but it bites hardest in `param_overrides`, where a preset device's nested
params are the whole point.)

## Proven at the wire (this session)

- `set_parameter(value=4.0, value_type='continuous')` on `LFO 1 S. Rate` → lands
  `value_display="2"`. `value=8.0` → `"1/2"`. **The RAW `value` channel works** and
  range-checks against the param's real `[0,21]`.
- `set_parameter(value_display="1/4", ...)` → `DisplayValueError` (above).
- Enum override end-to-end: snapshot `param_overrides` → from-scratch `build.py`
  rebuild → `device_param_overrides` row (`value_display="Tempo"`,
  `value_items_json=["Free","Tempo"]`) → push helpers emit
  `set_parameter(node=…path [{1,1},{1,1}], value="Tempo", value_type="enum")` →
  flipped live Sync→Free, applied that exact call → re-asserts **Tempo**. ✅

## Proposed fix — a raw passthrough channel

Add an explicit **`value_raw`** author key (the literal `DeviceParameter.value`),
stored UNCLAMPED in its own column, emitted by push as
`{"value": str(value_raw), "value_type":"continuous"}` — bypassing the display
inverter entirely. This mirrors `set_parameter`'s own raw `value` semantics, and
the handler already range-checks it against the live param's true `[min,max]`, so
push needs no knowledge of the range (it can't convert normalized→raw at plan time
anyway — the range lives in Live, not the DB; that's WHY today's normalized branch
passes the value straight through).

- Author: `{"path":[…], "name":"LFO 1 S. Rate", "value_raw": 8.0}`.
- Replay (`_param_value_fields` / `_override_entry_for_replay`): when `value_raw`
  present, store `value_raw`, leave `value_display` empty (so push reaches the new
  branch — must NOT also populate `value_display`, or branch ordering refuses it).
- Push (`_param_value_kv`): a `value_raw`-present branch → raw `value`,
  `'continuous'`. Order it so an explicit raw beats the display branch.
- Capture (`capture execute` / nested probe): emit `value_raw` for quantized
  params whose `max != 1` (or whose display is non-monotonic) instead of the
  normalized form they currently can't represent. (The probe's own error already
  steers the author here: "use the normalized value.")

The probe even surfaces the exact monotonicity test (`DisplayValueError`) — capture
could read `is_quantized` / param range to decide `value_raw` vs `value_display`
automatically.

## Workaround in use (swell, 2026-06-17)

`LFO 1 Sync` is now baked durably (`param_overrides` enum entry in
`captured_session.json`; verified across a from-scratch rebuild). `LFO 1 S. Rate`
stays on the manual MCP runbook (`set_parameter value=8.0`) until `value_raw`
ships — see swell's `voice-lfo-sync-rebuild-fragility` annotation. So a from-scratch
rebuild now restores in-time sync (Sync=Tempo) automatically; only the **division**
(1/2 vs the preset's 1/8) still needs the one-line re-apply.
