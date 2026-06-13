# Push `routing` phase runs before `devices` → audio-bus routing fails on a fresh push

**Severity:** M — blocks first-push (`--auto-session`) of any song using the
PRE-MAIN submaster pattern (RTE-1K9T) into a fresh Live set. Reproduced twice on
swell (2026-06-13); halts at `routing`, never reaching `devices` /
`device_sidechain` / `performed_automation`.

**ROOT CAUSE (confirmed empirically, not hypothesised).** The push phase order is
`… → mix → routing → devices → device_sidechain → …`. A MIDI track with **no
instrument loaded** exposes only **MIDI** output routing (targets = other MIDI
tracks); its **audio** output routing — the only thing that can target an audio
bus like PRE-MAIN — doesn't exist until an instrument is on the track. Because
`routing` runs **before** `devices`, every source track is still instrument-less,
so `set_output_routing(track, 'PRE-MAIN')` fails with PRE-MAIN absent from the
available types.

**Decisive test.**
- Fresh set, `devices` phase not yet run → `ableton_device(list, track=6)` = `[]`
  (empty), and `set_output_routing(track=6, 'PRE-MAIN')` → **fails**, available
  list = MIDI tracks + `No Output` only (no audio tracks).
- Load the instrument (`ableton_device(load, track=6, Garage Kit)`) → retry the
  **same** `set_output_routing(track=6, 'PRE-MAIN')` → **succeeds**.

That single before/after flips the result with nothing else changed — it's the
instrument (hence phase order), not Monitor state, not the default scaffold.

```
output routing type (track 5) 'PRE-MAIN' not in available
['1-MIDI','2-MIDI','02 Kit Punk', … '22 Meter Hat','No Output']   # all MIDI, no audio tracks
```

**Why it didn't surface earlier.** Prior swell pushes were onto a set whose tracks
already had instruments (re-push / pre-existing), so audio output routing already
existed. This is specifically a **first-push / fresh-set** bug.

**Fix.** Reorder the push phases so **`devices` precedes `routing`** (load
instruments before resolving track output routing). Natural order:
`tracks → returns → scenes → clips → devices → mix → routing → device_sidechain → …`
— instruments first, then mixer/routing on top. No phase appears to need routing
*before* devices; `device_sidechain` must stay after `devices` (already does) and
is unaffected by where track `routing` lands. Add a fresh-set first-push
regression test for the PRE-MAIN pattern (the existing coverage clearly ran on
already-instrumented tracks).

**Note (superseded hypothesis).** An earlier draft of this report guessed the
cause was PRE-MAIN needing `Monitor=In` first; that is wrong — the before/after
instrument test above disproves it. Monitor=In never even got set, because the
phase halts before configuring the bus, but that's a symptom, not the cause.

**Workaround to unblock a push now.** Run the `devices` phase before `routing`
(e.g. load instruments on the MIDI tracks, then re-run `execute` — idempotent;
routing then resolves), or fix the phase order and re-run.

**Related:** RTE-1K9T (track routing + PRE-MAIN bus). Distinct from the push
mid-run observability gap (no progress until exit) filed same day.
