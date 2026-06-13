# Improvement requests — device param `value_display` addressability + a doc fix (2026-06-13)

Context: mix pass on `swell` (hallucinote-songs), heavy use of
`ableton_device(action='set_parameter')` and `set_sidechain`. Three friction
points, all minor individually but each cost extra round-trips.

## 1. `value_display` refuses non-monotonic params, leaving only raw-curve guesswork

Setting a compressor Release or a sidechain `S/C EQ Freq` by display value fails:

```
set_parameter(... parameter_name='Release', value_display='120 ms')
-> DisplayValueError: parameter 'Release' display isn't monotonic across its range
   ('1.00 ms'..'3.00 s') — its leading number reverses (ms->s) ... use the normalized `value`
```

The refusal is *correct* (the leading digit isn't monotonic across the unit
change), but it dumps the caller onto the raw normalized `[0,1]` curve with **no
way to address the param in real units** — so I had to reverse-engineer the
frequency curve from two probed data points
(`(0.158→80 Hz),(0.305→200 Hz)` ⇒ `norm = (log10 f − log10 30)/(log10 15000 −
log10 30)`) to set 150 Hz as `0.259`. Every agent hits this for EQ freqs,
comp release/attack, LFO rates, etc.

**Suggested fix:** accept an explicit-unit display string and parse the unit
rather than the leading-digit heuristic — `value_display='120 ms'` and
`'2.5 s'` are each unambiguous; `'150 Hz'` and `'2 kHz'` likewise. The
monotonicity guard only needs to fall back to "raw required" when the *parsed,
unit-normalized* target is still ambiguous (rare). Alternatively expose a
`value_hz` / `value_ms` / `value_db` typed setter, or return the param's
(raw→display) sample points in the `get_parameters` payload so the caller can
invert locally without probing.

## 2. Display rounding (0.01 Hz) is too coarse for phase-critical params

The Phaser-Flanger `Mod Freq` displays in 0.01 Hz steps. To align the phaser to
a 136-beat span (10 cycles ⇒ 0.1544 Hz) I needed ~3% precision, but:
- `value_display='0.1544 Hz'` inverted to a raw that read back as **"0.16 Hz"**
  (ambiguous overshoot), and
- the readback display can't distinguish 0.150 from 0.1544 at all (both round to
  "0.15").

So neither setting nor *verifying* a phase-critical rate is possible through the
display surface; I set the raw value (0.32762) from a 2-point linear fit and
accepted I can't confirm it from the readback.

**Suggested fix:** in the `set_parameter` response, echo the achieved **raw**
value (already present) *and* a higher-precision computed real-unit value (not
just the device's rounded display string), so the caller can confirm sub-display
precision. Bonus: a `get_parameters` option to return the param's display at full
float precision.

## 3. Doc: `set_sidechain` / `set_input_routing` example shows `1-Drums`, real value is the bare track name

The help example is `source_display_name='1-Drums'` /
`type_display_name='1-Drums'` (an index-prefixed form). In Live 12.x the actual
accepted values are the **bare track names** — `set_sidechain(...,
source_display_name='2-02 Kit Punk')` failed with:

```
ValueError: input routing type '2-02 Kit Punk' not in available
['01 Glitch', '02 Kit Punk', ... 'PRE-MAIN', 'A-Hall', ..., 'Main', 'No Input']
```

`'02 Kit Punk'` worked. The `<index>-<name>` example sends agents down a wrong
first attempt every time. Suggest updating the examples/param docs to the bare
track/return name form (and note returns appear as `A-Hall` etc., master as
`Main`, plus `No Input`/`No Output`), or have the resolver accept the
index-prefixed form too.
