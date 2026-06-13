# Bug report — snapshot capture (`/song-snapshot`) records the HallucinoteAnalyzer devices into `captured_session.json` (2026-06-13)

Context: mix pass on `swell`. After `ableton_render(render)` (which
"auto-loads HallucinoteAnalyzer on every audio track + return AND the master,
idempotent"), I went to bake the mix changes back with `/song-snapshot` and
stopped when I realized the analyzer devices would be captured.

## TL;DR

`ableton_render` leaves a `HallucinoteAnalyzer` device **permanently in every
track/return/master chain** (it loads them idempotently and does not remove them
after the capture pass). `ableton_device(action='list')` — the probe
`/song-snapshot` and `hallucinote.tools.capture_cli plan` iterate — returns them
as ordinary chain devices:

```
track 2 (Kit Punk) chain:
  1 Garage Kit  2 EQ Eight  3 Drum Buss  4 Compressor
  5 HallucinoteAnalyzer   class_name=MxDeviceAudioEffect  display="Max Audio Effect"

return 1 (Hall) chain:
  1 Hybrid Reverb
  2 HallucinoteAnalyzer   <-- INTERLEAVED, between the reverb and...
  3 Compressor            <-- ...a device loaded after it
```

There is no analyzer filter in `compile_snapshot` / the pull-mix capture path
(grep of `src/hallucinote/sync/pull/` and `capture.py` for `analyzer` is empty).
So a `/song-snapshot` refresh writes `HallucinoteAnalyzer` entries into
`captured_session.json`.

## Why it's harmful

1. `replay_capture` / push `devices` phase would try to **recreate** a device
   named `HallucinoteAnalyzer` / display "Max Audio Effect" via the browser —
   not a loadable browser node, so the rebuild breaks or silently drifts.
2. The analyzer is **interleaved** in the chain (e.g. Hall return: reverb,
   analyzer, compressor). Capturing it shifts every downstream device's index,
   so even if recreation were skipped, the chain order/positions recorded are
   wrong relative to a clean (analyzer-free) authored chain.
3. It defeats `/song-snapshot` as the bake path after a render — which is the
   exact moment you want to bake (you just rendered to verify, now persist the
   tweaks). Today the safe move is to hand-strip analyzer devices from the
   `.refresh.json` before merge, which is error-prone.

## Related (same root, distinct failure): `load` appends AFTER the analyzer — the analyzer should stay LAST

`ableton_device(action='load')` appends to the END of the chain (Live 12.4 has
no reorder API). Because the analyzer already sits last, **every device loaded
after a render lands *after* the analyzer**, so the analyzer is no longer the
final node. Observed this session — loading compressors / a saturator landed
them past the analyzer:

```
return 1 (Hall):  Hybrid Reverb | HallucinoteAnalyzer(2) | Compressor(3)   <- comp AFTER analyzer
track 4 (Gtr):    rack | EQ8 | Saturator | HallucinoteAnalyzer(4) | Compressor(5)
track 6 (Cb):     rack | EQ8 | Compressor | HallucinoteAnalyzer(4) | Saturator(5)
track 8 (Celli):  rack | EQ8 | HallucinoteAnalyzer(3) | Compressor(4)
```

The analyzer is a **measurement tap that must capture the chain's final
output.** With devices after it, the per-track/return stem WAV captures the
signal *before* those devices — so the stem analysis (masking/loudness)
**silently under-measures** any post-analyzer device. In this session the
timpani→Celli duck, the kick→Gtr pump, the ducked Hall, and the Contrabass
sub-saturator were all post-analyzer, so the per-stem MixReport didn't reflect
them (the master capture still does, since it's post-everything at the master).
That's a correctness trap: the numbers look like "the change did nothing" when
the change simply wasn't in the captured stem.

**Suggested fix:** the analyzer must always be the last device. Either (a) on
`ableton_device(action='load')`, if a trailing `HallucinoteAnalyzer` is present,
insert the new device *before* it (and/or move the analyzer back to last after
the load), or (b) have the render's idempotent analyzer-load *reposition* the
analyzer to the end of each chain (delete + re-add last) rather than only
ensuring presence. (b) also self-heals chains where devices were added between
renders. Until then, the only manual fix is delete the analyzers and re-render
(they reload last) — there is no reorder API.

## Suggested fix

Filter the analyzer out of capture at the source, by the stable identity
`name == "HallucinoteAnalyzer"` (and/or the M4L class + the known device):

- In the device-chain capture (`compile_snapshot` / the per-device probe loop /
  `capture_cli`), skip any device whose name is `HallucinoteAnalyzer`, so it
  never enters `captured_session.json`. Symmetric with how `render` treats it as
  infrastructure, not authored content.
- Bonus robustness: have the push `devices` phase ignore/skip a
  `HallucinoteAnalyzer` entry if one ever does appear in the DB, so a
  pre-existing polluted snapshot can't break a rebuild.
- Optional: `ableton_device(action='list')` could carry an `is_infrastructure`
  flag on the analyzer so callers can filter generically.

## Repro

1. `ableton_render(render, ...)` any song (loads analyzers).
2. `ableton_device(action='list', track_index=N)` → `HallucinoteAnalyzer`
   appears as the last chain device (and interleaved on returns where devices
   were added post-render).
3. Walk `/song-snapshot` → the compiled `captured_session.refresh.json` contains
   `HallucinoteAnalyzer` device entries.
