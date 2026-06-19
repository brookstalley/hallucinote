# Modifying HallucinoteAnalyzer.amxd

Procedural guide for patch edits. The contract lives in
[`HallucinoteAnalyzer.amxd.spec.md`](./HallucinoteAnalyzer.amxd.spec.md).
**Read `learnings.md` (M4L section) before any patch edit.**

## Editing rule

- Edit only through Max's GUI. The `.amxd` is a binary container; hand-edited
  JSON looks valid but fails Live's loader (`createdevice error 6`).
- After edits: `Cmd-S` in Max, then `Cmd-W` to close the patcher window.
  Live and Max fight over `[udpreceive]` when both have the patch open.
  (See `learnings.md` "M4L patcher editor and Live runtime fight over
  udpreceive".)
- Copy the saved `.amxd` from
  `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd`
  back to `hallucinote_mcp/src/hallucinote_mcp/m4l/`.
- After the source `.amxd` is updated, run `/ableton-mcp-install` and then
  **fully quit and reopen Live**. Live caches device patches at instance
  load — partial reload hangs Live.

## Patch regions (where things live on the canvas)

| Region | Typical canvas location | What's there |
|---|---|---|
| Inbound OSC | top-left | `[udpreceive]` → `[OSC-route /path]`, `/track_id`, `/start_at_beat`, `/stop_at_beat`, `/signature/query`. Storage cells (`[value track_id_retained]`, `[i]` for beats). `has_track_id` send chain. |
| Transport observer + state machine | top-right / center-right | `[live.thisdevice]` → `[live.path live_set]` → `[live.observer]`; `[t f f]` fork to crossing-detection expr + beat-position latch; `prev_beat` `[f]`; `[sel 0 1]` outlet 1 → `[-1.]` reset chain off `Arm`. |
| Audio + feature extraction | center / center-left | `[plugin~]` → `[send~ tap_L / tap_R]`. Mono-sum → three parallel chains: K-weighting biquads → LUFS-M; `[peakamp~ 33]` → peak; 200–500 Hz biquads → low-mid. Each terminates in `[send <feature>_value]`. |
| OSC emit | bottom-right | `[metro 33]` → `[t b b b b]` → bang sequence (track_id `[value]`, beat-latch, snapshots). `[pack s f f f f]` → two `[gate]`s → `[udpsend]`. `EmitPort` `[live.numbox]` → `[i]` → `[prepend port]` → `[udpsend]` config inlet. |
| sfrecord~ | bottom-left | `[sfrecord~ 2 @nchans 2]` with `samptype float32` loadbang message; left inlet receives `prepend open` chain from `/path` route AND `1` / `0` integers from the state machine. |
| Live params | floating | `[live.toggle (Arm)]`, `[live.numbox (Port)]`, `[live.numbox (EmitPort)]`, `[live.toggle (Emit)]`. Long-range wires to the regions they drive. |

## Adding a new feature emitter

1. **Tap the mono signal.** `[receive~ mono]` (already broadcast by the
   audio region). If your feature is stereo-aware, tap `tap_L` / `tap_R`
   separately.
2. **Filter / process at signal rate.** Add `[biquad~]` boxes if you need
   filtering (see spec's "Filter coefficients" for the 48 kHz pinning
   convention — match it for any new filter).
3. **Square if you want power.** `[*~]` with the signal connected to both
   inlets.
4. **Integrate / accumulate.** `[average~ <window_samples> bipolar]` over
   the desired window. SR-adapt the window via
   `[adstatus sr] → [expr $f1 * <seconds>] → [i] → average~`'s **left
   inlet** (same inlet as the audio signal — `[average~]` has only one;
   see `learnings.md` "M4L `[average~]` has one inlet").
5. **Snapshot to control rate.** `[snapshot~]` banged by the existing
   `[metro 33]` chain — add a new outlet to the `[t b b b b]` (becomes
   `[t b b b b b]`) at the appropriate position (snapshots fire BEFORE
   the address bang, which fires last as the hot inlet).
6. **Clip + log.** `[clip 1e-12 1e10]` (for power) or `[clip 1e-6 1.0]`
   (for amplitude), then `[expr 10. * log10($f1)]` (power) or
   `[expr 20. * log10($f1)]` (amplitude). M4L's `[expr]` has no `max` /
   conditionals — clip upstream. (See `learnings.md` "M4L `[expr]`
   function vocabulary is narrow".)
7. **Broadcast.** `[send <new_feature>_value]`.
8. **Wire into the frame.** Add `[receive <new_feature>_value]` and
   append a new cold inlet to `[pack s f f f f]` (widen to
   `[pack s f f f f f]`). Bump the OSC type tag conceptually
   (`,fffff`) — Max's `[pack]` derives the type tag from the typespec
   so widening the pack is sufficient.
9. **Document.** Add the new payload index to the spec's "Wire format"
   section and bump the signature string if older sidecars must reject
   the new shape (otherwise the growth convention keeps older parsers
   compatible).

## Adding a new inbound OSC route

1. **Add an `[OSC-route /foo]` branch** off the existing `[udpreceive]`
   fan-out.
2. **Coerce if needed.** For int args, `[i]` after the route. For
   floats, `[f]`. For symbols, no coercion needed.
3. **Store.** Use `[i]` (int) or `[f]` (float) for cold-inlet storage —
   both emit on every write. **NEVER use `[value <name>]`** for
   per-instance state — it is GLOBAL across all device instances in
   the same Live set and will clobber across the analyzer chain.
   (See `learnings.md` "M4L `[value <name>]` is GLOBAL-by-name across
   all device instances" and "M4L `[value]` doesn't emit on write".)
4. **Update the spec's inbound-OSC routes table** in the inlets/outlets
   diagram.

## Modifying state-machine timing

The transport-cross detector lives off `[live.observer]` →
`[t f f]` outlet 1 → `[expr ($f2 < $i3) && ($f1 >= $i3) && ($i4 == 1)]`
where `$f1` = current_beat, `$f2` = prev_beat, `$i3` = target-beat,
`$i4` = `Arm`.

- Changing the comparison shape (`<` / `>=` vs `<=` / `>`) affects edge
  detection at boundaries. Don't make this swap without understanding
  the `[deferlow]` prev_beat update timing — the expr fires, then
  deferlow runs, then the next observer tick reads the new prev_beat.
- `prev_beat` is reset to `-1` on **both** loadbang AND `Arm` rising
  edge: `[sel 0 1]` outlet 1 → `[-1.]` → prev_beat `[f]`. The
  Arm-rising reset is essential for the `start_at_beat=0` case under
  repeated renders.

## Testing changes

1. **Unit tests (no Live needed):**
   ```
   pytest hallucinote_mcp/tests/unit/test_actions_render.py \
          hallucinote_mcp/tests/unit/test_analyzer_setup.py
   ```
2. **Deploy to User Library:** `/ableton-mcp-install`.
3. **Full Live restart.** Quit Live completely (Cmd-Q), reopen. Partial
   reload hangs.
4. **Drive a render:**
   ```
   ableton_render(action='start', song_slug='reggae-metal',
                  start_at_beat=8, stop_at_beat=24)
   # then poll: ableton_render(action='status', job_id=…) until state=done
   ```
5. **Inspect the captures dir.** Each WAV is FLOAT/stereo/Live's SR;
   duration matches the beat window within one buffer.
6. **Cross-correlate** any track WAV vs master via the Python recipe
   in `.test-evidence.json` notes. Lag should be ± 64 samples of zero.

## Known traps

Every M4L trap learned during MVP authoring lives in `learnings.md`.
**Do not re-derive.** Key entries to read before patch edits:

- "M4L `[value <name>]` is GLOBAL-by-name across all device instances"
- "M4L `[value]` doesn't emit on write — use `[i]` / `[f]` for
  cold-inlet storage"
- "sfrecord~ control API: bare integers (1 / 0), not `record N`"
- "M4L Int parameter range capped at 256 — use Float + Unit Style Int"
- "M4L `live.observer` needs runtime `property <name>` message;
  outputs bare value"
- "M4L `live.toggle` outlet emits int (0/1) directly"
- "M4L patcher editor and Live runtime fight over udpreceive — close
  the editor before testing"
- "M4L `[peakamp~]` is self-clocked via a reporting-interval arg, not
  banged"
- "M4L `[average~]` has one inlet, not two — window-size message
  shares the signal inlet"
- "M4L `[expr]` function vocabulary is narrow — no conditionals, no
  min/max; use `[clip <floor> <ceiling>]` upstream"
- "M4L device source belongs in `Presets/Audio Effects/Max Audio
  Effect/`, not Remote Scripts"
- "M4L device identity is in `device.name`, not
  `device.class_display_name`"
- "M4L devices installed under User Library require `preset_query`,
  not `kind=`, in `ableton_device(action='load')`"
