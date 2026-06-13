# Improvement request — make the live→source "bake" turnkey (the whole round-trip is expert-only) (2026-06-13)

Context: mix pass on `swell`. After dialing the mix in Live, baking it back into
`captured_session.json` (so a rebuild reproduces it) turned out to be an
expert-level, multi-trap operation. The user's words: "we really want this to be
easy to use." Today I had to bypass `/song-snapshot` entirely and hand-author the
snapshot JSON in Python, learning several sharp edges by hitting them.

This is a roll-up of what makes the round-trip hard; the individual fixes are in
the sibling files, but the *goal* is one reliable command:

> change the mix in Live → run one thing → `captured_session.json` updates →
> `python build.py` + push reproduces it. No hand-editing, no format lore.

## The traps I hit (each one silently breaks the bake)

1. **Analyzer pollution** — `/song-snapshot` captures the `HallucinoteAnalyzer`
   devices (render leaves them in every chain, sometimes interleaved). Filed:
   `2026-06-13-snapshot-capture-includes-hallucinote-analyzer-devices.md`.
2. **Device ordering** — devices loaded after a render land *after* the analyzer,
   so the analyzer is no longer last and per-stem captures under-measure them.
   Same file.
3. **`params_dialed` value vs normalized** — `set_device_parameter` requires
   `value_normalized ∈ [0,1]`, but param "values" reported by probes are in the
   param's OWN range (Threshold −10 dB, Gain +6 dB, Notches 4, Transients 0.30 in
   −1..1). Passing those as `normalized` raises `out of range`, OR (worse, for a
   −1..1 param whose value happens to land in [0,1]) is silently accepted and
   dials the WRONG value. There's no probe field that hands back the true 0–1
   normalized, so the author has to know which params are 0–1 vs not.
4. **Display vs normalized at push** — push prefers `value_display`, which the
   handler can't invert for non-monotonic params (Hz↔kHz, ms↔s). So freq/rate
   params must be baked normalized-*only* (`value=""`), while non-0–1 monotonic
   params (dB thresholds/gains) must be baked as a display string. Opposite
   rules, no guardrail. Related: `2026-06-13-device-param-value-display-precision-and-docs.md`.
5. **Enum params** — must carry `value_items`; unclear they round-trip through
   push without it.
6. **Return naming / send keys** — returns are stored slot-stripped ('Motion',
   not Live's 'E-Motion') and sends must key to the stripped name. Easy to get
   wrong by copying Live's displayed name.
7. **Sidechain sources don't model at all** — so even a perfect bake silently
   drops them. Filed: `2026-06-13-device-sidechain-source-not-in-snapshot-model.md`.

## What "easy" looks like

- `/song-snapshot` (or a `bake` action) that **just works** post-render: filters
  analyzer devices, captures each dialed param in a form that round-trips
  **losslessly** (store BOTH the true 0–1 normalized AND the display string; push
  picks the safe one per param — normalized for non-monotonic, display
  otherwise), handles enums + return-name stripping, and warns (doesn't silently
  drop) anything unmodelable (sidechain sources → "N sidechains not captured;
  here's the re-apply list").
- A probe that returns the **true 0–1 normalized** alongside value/display, so
  authoring tools never have to guess a param's range.
- A `diff` that's safe to trust for confirm/overwrite (it already exists; it just
  needs the capture side to stop polluting it).

Net: the agent should never have to know `params_dialed` internals or
monotonicity rules to persist a mix. Today it does.
