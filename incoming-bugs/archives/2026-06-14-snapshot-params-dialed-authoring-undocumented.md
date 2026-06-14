# Static device-param authoring lives in snapshot `params_dialed` — undocumented, and frequency must be a normalized float (no display-value path)

**Severity:** M (docs) + S (ergonomics) — authoring static device parameters in
source (EQ curves, comp thresholds, drum-bus settings) is a core composing task
("sound design is authorship"), but the source-of-truth format is undiscoverable
without reverse-engineering. Cost ~20 min of detective work on the 2026-06-14
swell clarity pass before a single EQ move could be written.

**What's confusing (the mental-model gap).** A reasonable composer looks for
static device params in the obvious places and finds nothing:
- `build.py` authoring helpers cover sidechain *sources*, routing, envelopes,
  master-swell — but **no static device params**. `grep set_device_parameter`
  in the song returns only the voice-expression *envelope*.
- The per-song DB *has* a `device_parameters` table (60 rows for swell), so the
  params clearly exist — but nothing in the song's Python writes them.
- `captured_session.json` device entries show only `{index, name, class}`, so
  they look param-free.

The actual home is a **`params_dialed`** key that appears on a device entry
**only when it holds non-default params** (sparse capture). Decision-19's whole
mix pass (timpani knock, choir −3 dB @ 350, glue −10 dB, drum-bus boom, reverb
Dry/Wet 100%) lives there. `replay_capture` reads `params_dialed` →
`device_parameters` rows → push materializes them. This is the documented-nowhere
seam that the entire "bake mix into source" story depends on.

**Format (also undocumented), reconstructed from the swell snapshot:**
```jsonc
"params_dialed": {
  "1 Filter Type A": {"value": "High Pass 12dB", "value_items": [...]}, // enum: display label
  "1 Frequency A":   {"value": "", "normalized": 0.195},               // continuous: NORMALIZED 0..1
  "5 Gain A":        {"value": "6 dB"}                                  // continuous: display string OK here
}
```

**The ergonomic defect — frequency has no display-value path.** Enum params take
a label and gain takes a display string (`"6 dB"`), but **frequency only round-
trips as a normalized 0..1 float**. EQ Eight's frequency knob is logarithmic, so
to author "HPF at 180 Hz" in source you must invert the log curve yourself. I had
to solve `normalized = a·log10(f) + b` from three captured data points
(45 Hz→0.195, 350→0.462, 3500→0.761 ⟹ a≈0.2997, b≈−0.3004) to author the pass.
Meanwhile the **live** `ableton_device(set_parameter)` happily accepts
`value_display="180 Hz"` and inverts the curve internally — so the capability
exists; it's just not available in the snapshot authoring format. `params_dialed`
should accept `{"value": "180 Hz"}` for continuous params and invert at
replay/push time (same inversion the live setter already does).

**Asks:**
1. **Document `params_dialed`** in the snapshot schema doc: that it's the home for
   static device params, that it's sparse (non-default only), the per-entry shape,
   and how it flows snapshot → `device_parameters` → push.
2. **Accept display values for continuous params** in `params_dialed` (`"180 Hz"`,
   `"-10 dB"`, `"3:1"`), inverting via the same display curve the live setter uses,
   so authors never hand-invert a log knob.

**Verifiable signal.** A composer can author "EQ Eight: HPF 180 Hz, +3 dB high
shelf @ 8 kHz" in source by typing display units, find it documented, and have it
materialize on push. Surfaced 2026-06-14 dogfooding the swell mix pass.
