# Device-parameter automation can drive a part into silence with no warning — caught only by ear after a full real-time perform push

**Severity:** M (authoring safety) — a `device_parameter` envelope can put a
macro into an inaudible range (here, a lowpass cutoff closed onto the
fundamental) and nothing in the build → push → perform chain flags it. The
regression survived build (clean), tests (pass), a full 14-phase push (exit 0),
and a ~6-minute real-time perform pass before the composer heard the part was
silent. Source-side authoring against a parameter has no notion of "this value
is audible."

## What happened (swell, Voice Lead "Synth Vox Ai")

We rewrote the voice's Filter Cutoff into a per-note envelope that "follows the
chords." The macro (Macro 0, 0–127) maps the rack's `Filter_Frequency` across
**50 Hz … 18 kHz** (~exponential), preset default **114.5 (~8–10 kHz)**. The new
`cutoff_for` mapped pitch D3–D5 to macro **58→122 floored at 40**, with negative
section bias — so the voice's normal register landed at macro ~54–86 and the
entry (bias −4) bottomed near **macro 40 ≈ 320 Hz**. Result: fader up, the
Filter Cutoff lane visibly *moving*, output **meter dead**, lead silent from its
first entry through the whole song. Perceptually "the filter is automating" — but
the band it moved through was entirely below audibility.

Everything downstream said OK:
- `build.py` built clean; the symbolic shape was "correct" (171 breakpoints).
- tests passed (none asserted audibility).
- push `execute` returned exit 0; the perform warning correctly listed the arc
  (`21 Voice Lead Filter Cutoff [171.98–903]`) but said nothing about its values.

## Why it's framework-shaped, not just a song bug

- **No ground-truth scale at authoring time.** The snapshot stores the rack as a
  `preset_query` (`Synth Vox Ai.adg`) with **no macro ranges/curve**. To author a
  safe cutoff we had to `gunzip` the factory `.adg` out of the Live app bundle
  and read `Filter_Frequency` min/max + the macro default by hand. Authors have
  no in-toolkit way to ask "what does macro 0 map to, and what's audible?"
- **Perform records blindly.** The perform pass sets the param to the DB value
  and records it; a value that yields zero output records just as happily as a
  good one. The MixReport/analysis lens runs on captured audio, but here the
  perform pass *is* the expensive step — by the time you could analyze, you've
  paid the full real-time pass.

## Suggested directions

1. **Capture macro ranges + mapping into the snapshot** (or expose a resource):
   for each rack macro, its min/max and the target param(s) it maps to, so
   authors can convert Hz↔macro without spelunking `.adg` files.
2. **Optional per-parameter "audible floor/ceiling" assertion helper** the build
   can opt into (`assert_param_audible(env, floor=...)`), so silencing envelopes
   fail the build instead of a push.
3. **Silence/near-silence detection in the perform/render path** — flag any part
   whose output stays below a noise floor for the bulk of its active span
   ("21 Voice Lead: meter < −60 dB for 92% of [44–227] — automation may have
   closed it"), the cheap structural cousin of the masking report.

## Workaround in the song (no Live needed)

Anchored `cutoff_for` to the preset's real curve, mapped pitch to an
always-audible band, hard-floored at macro 86 (~2.7 kHz), and added a build-time
`AssertionError` + a pytest regression (`test_voice_filter_cutoff_never_closes`)
so the build refuses to ship an inaudible lead. (songs/swell/build.py,
tests/test_swell_build.py)

## Triage (2026-06-14) — routed to [DEV-3W9R], two directions descoped

This is a real bug, but a **witness** of a known gap, not a new one. Both
claims above verified TRUE against the code (snapshot stores the rack as an
opaque `preset_query` with no macro metadata — `docs/snapshot-schema.md:105-147`,
`capture.py:136-304`; no toolkit surface exposes a macro's mapping or its
target's physical range — `handlers/device.py:290-348`, `:1912-1958`).

**Root cause = [DEV-3W9R]** "Rack macros are unmodeled." Filed this report as
its real-world witness and **bumped its impact M→H** — it escalates the gap from
"can't author a basic macro idiom" to "silently ships an inaudible part." The
fix to author against is exactly DEV-3W9R: capture macro ranges + the macro→param
mapping into the snapshot so authors convert Hz↔macro without gunzipping `.adg`.
DEV-3W9R stays `stage: requirements`, gated on a LOM macro-mapping capability
probe (needs a real Live session).

**Descoped** the two lighter suggested directions:
- **§2 `assert_param_audible` build helper** — the song already has the right
  thing at the right altitude (a per-song build-time assertion + regression).
  Generalizing it is redundant *and* meaningless without DEV-3W9R's macro→Hz
  curve (an "audible floor" without the curve is just a magic macro number).
- **§3 perform/render silence detection as a gate** — rejected on ruler-vs-stamp
  grounds (`feedback_great_art_not_software`): a near-silent part is valid art
  (ambient beds, breakdowns, fade-outs, sidechain ducking), so a gate that
  fails/flags it makes the musical decision. Defensible only as a *non-verdict*
  mix-review surface, and even there redundant with the MixReport's existing
  per-part loudness read — and it only fires after the expensive perform pass.

Nothing on fire: the song fix + regression test hold. This report stays active
(not archived) until DEV-3W9R ships.
