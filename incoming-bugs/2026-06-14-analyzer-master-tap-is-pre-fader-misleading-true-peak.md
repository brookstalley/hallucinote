# MixReport master true-peak/overshoots are measured PRE master-fader → not the delivered peak, and undocumented

**Severity:** M (clarity/correctness) — the `master` loudness block in the
MixReport reads the master tap **before** the master volume fader, so its
`true_peak_dbtp` / overshoot counts describe the **mix bus**, not the **delivered
(post-fader) output**. Nothing in the report says which, and the natural reading
("master true peak = the file's true peak") is wrong. Cost a wasted render on the
2026-06-14 swell pass: lowering the master fader 0.85→0.82 to "recover headroom"
moved neither `lufs_i` (−16.7→−16.9, ≈ noise) nor `true_peak_dbtp` (+0.08→+0.14),
because the analyzer can't see the fader.

**Why it happens.** `ableton_render` loads the HallucinoteAnalyzer into the master
*track's device chain*, which Live processes **before** the master mixer
volume/pan. So every master metric (loudness, true-peak, overshoots, attribution)
is a pre-fader mix-bus measurement. The master fader (and master pan) are
invisible to it.

**Why it bites.**
- "Is my master clipping at delivery?" can't be answered from the report — a bus
  reading +0.14 dBTP with the fader at −1.5 dB delivers ≈ −1.4 dBTP (clean), but
  the report shows +0.14 and the agent over-corrects.
- Conversely a hot master fader (> unity) could push the *delivered* output over 0
  while the report still reads the bus as clean — a false all-clear.
- decisions/19's "clipping eliminated, −2.17 dBTP" and this pass's "+0.14 dBTP"
  are both **bus** numbers; whether they reflect the deliverable depends on the
  (unreported) master fader.

**Asks (any of):**
1. **Document it** — label the master block "mix bus, pre-fader" in the schema/doc
   and in `/mix-review`'s vocabulary, so true-peak is never misread as delivery.
2. **Also report delivered true-peak** — apply the master volume (and any master
   limiter) and emit a separate `delivered_true_peak_dbtp`, OR capture the master
   post-fader. This is the number a mastering check actually needs.
3. At minimum, surface the **master fader value** alongside the master block so the
   delivered peak can be inferred (bus_tp + 20·log10(master_volume)).

**Verifiable signal.** The MixReport distinguishes mix-bus true-peak from delivered
true-peak (or documents that `master` = pre-fader bus), so an agent never trims the
master fader expecting the report's TP to move. Surfaced 2026-06-14 on the swell
clarity pass.
