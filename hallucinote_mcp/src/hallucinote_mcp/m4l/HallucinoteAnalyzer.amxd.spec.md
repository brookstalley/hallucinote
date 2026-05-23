# HallucinoteAnalyzer.amxd — build spec

This file is the **authoring contract** for `HallucinoteAnalyzer.amxd`. The
`.amxd` is a binary Max for Live patch; it has to be built inside Max's
visual environment by a human (or an external Max-aware tool). This spec
exists so the patch can be authored against a written contract rather than
"whatever felt right."

Once the `.amxd` exists, drop it next to this spec in
`hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd` and
commit. Binary file — no text diffs; the spec is the auditable surface.

---

## Scope: Chunk 1 only

Chunk 1's `.amxd` is the **minimum viable proof of life**:

- One `sfrecord~` per instance, writing the inserting track's audio to disk.
- Two exposed parameters (`record_arm`, `output_path`).
- Nothing else. No OSC emitter, no signature parameter, no `track_id`.

Chunk 2 extends this same patch with OSC + `track_id` + a Hallucinote
signature parameter — all listed under "Reserved for Chunk 2" below so the
build doesn't paint into a corner.

---

## Patch type

**Audio Effect** (`amxd~ audioeffect`). One audio inlet (stereo), one audio
outlet (stereo) that passes-through unmodified — the device must be sonically
transparent so analysis never alters the mix.

Sample rate and channel count follow Live's session SR; do not hardcode.
Output WAVs are **32-bit float stereo at Live's session SR**. `sfrecord~` is
the canonical write path — it handles SR + format negotiation inside the
audio thread, which is what we want for sample-accurate alignment.

## Inlets / outlets

```
audio inlet  L  ──┐
audio inlet  R  ──┼──> [sfrecord~ 2 @numchans 2]   (writes to disk)
                  │
                  └──> outlet L / outlet R         (sonic pass-through)
```

The dry path must reach the outlets with **no extra sample delay** beyond
what `sfrecord~` introduces in the parallel branch (which is zero — it's a
tap, not an insert). PDC alignment depends on this.

## Exposed Live parameters

Both parameters must be **automatable + scripted-name'd** so Hallucinote's
Remote Script can write them via the existing `ableton_device.set_parameter`
path.

| Scripting name | Long name (Live's parameter list) | Type | Range / values | Default |
|---|---|---|---|---|
| `record_arm`   | `Record Arm`   | bool toggle (`live.toggle` w/ `@parameter_visible 1 @parameter_modulation_mode 0`) | 0 / 1 | 0 |
| `output_path`  | `Output Path`  | string (Max symbol via `live.text` w/ `@parameter_visible 1`) | absolute filesystem path | empty string |

Implementation hints (informative, not contractual):

- Use `live.toggle` for `record_arm` so the Remote Script's
  `set_parameter(value_type='continuous', value=1)` resolves to "on" cleanly.
- `live.text` exposes a string parameter; route its output to a
  `[prepend open]` → `[sfrecord~]` chain to set the destination filename
  before each record.
- Both controls need `Parameter Visibility = Stored` so the value survives
  Live file save/load. (`record_arm` going to **0** at save time is fine —
  arming is per-render, not authored state — but the parameter itself must
  exist on patch load.)

## Behavior contract

### On rising edge of `record_arm` (0 → 1)

1. Read the current `output_path` string. If empty, **do not arm**; emit a
   `[print HallucinoteAnalyzer]` error so the harness sees it and abort.
2. If the path's parent directory doesn't exist, **do not arm**; same error
   path. (The Python harness pre-creates the directory in Chunk 1 — this
   guard catches the "config drift" failure mode.)
3. If a file already exists at that path, overwrite it. The Python side
   owns naming (timestamped directories); no append semantics.
4. Send `open <path>` then `record 1` to `sfrecord~`.
5. The recording is **32-bit float stereo at Live's session sample rate**.
   Set `sfrecord~` with `@samptype float32 @numchans 2`. Format must not be
   sample-rate-converted.

### On falling edge of `record_arm` (1 → 0)

1. Send `record 0` to `sfrecord~`.
2. Send `close` to flush and finalize the WAV header.
3. Do not retain the path; the next render gets a fresh `output_path`.

### Steady state

- `record_arm` held at 1 across multiple transport stops/starts: keep
  writing. Live's transport state is independent of `sfrecord~`'s write
  state by design — the Chunk 1 harness drives both, and we want them
  decoupled so a future "render only one section" use case still works.
- `record_arm` held at 0: emit nothing. `sfrecord~` should not be open.

### Transport-relative timing

The harness sets `record_arm=true` **before** starting the transport, so
the first sample of the recorded file is t=0 of arrangement playback. Any
device-side pre-roll or pre-buffering would offset the dry+wet alignment
that Chunk 3's deconvolution depends on. **The patch must not pre-buffer.**

Document in the chunk handoff: measure start-of-file silence (in samples)
on the first capture and report. The Chunk 1 PDC test
(`tests/unit/audio/test_pdc_alignment.py`) tolerates ± 64 samples of
residual; this is the budget that absorbs any unavoidable pre-buffer.

## Install path (manual, Chunk 1)

Copy the built `.amxd` to:

```
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd
```

Chunk 2 automates this copy inside the `ableton-mcp-install` skill.

## Verifying the build (Chunk 1 GO/NO-GO)

Once the patch loads in Live and the Remote Script is running:

1. Drop the device on one audio track and one instance on master.
2. Run `hallucinote_mcp/tools/test_capture.py` (the throwaway harness — see
   that file's docstring for invocation).
3. The harness writes WAVs to `/tmp/hallucinote-chunk1-<timestamp>/` —
   one for the test track, one for master.
4. Open both WAVs in a sample editor (or `soundfile.read` in a Python
   REPL) and verify:
   - Both are 32-bit float, 2 channels, Live's session SR.
   - Duration matches the harness's stop window within ± one buffer.
   - Track WAV cross-correlates with master WAV at zero lag ± 64 samples
     at 48 kHz. Reuse `tests/unit/audio/test_pdc_alignment.py`'s
     `cross_correlation_peak_lag` on the loaded buffers.

5. Record any `sfrecord~` quirks in the chunk handoff:
   - Start-of-file silence (samples until first non-zero).
   - End-of-file truncation (does `record 0` lose the last buffer?).
   - Sample-rate mismatch handling (if the project SR doesn't match the
     device's view of it).

## GO criteria

- WAVs exist at expected paths, with expected dtype/channel/SR.
- PDC alignment within tolerance.
- Param writes from the harness reliably trigger record start/stop.

## NO-GO criteria

- Alignment unstable across runs.
- Files truncate or contain unexpected silence the PDC tolerance can't
  absorb.
- `record_arm` parameter writes don't reliably trigger record start (race
  condition between Remote Script parameter-write and `sfrecord~` open).

NO-GO falls back to the spike's Resampling-tracks alternative (§1) — re-plan
before continuing to Chunk 2.

---

## Reserved for Chunk 2 (do NOT add in Chunk 1)

Chunk 2 will extend this patch with the following. Listed here so the Chunk 1
build leaves space for them without painting into a corner:

- **`signature` parameter** — read-only string, value `"hallucinote-analyzer-v1"`.
  Used by `ensure_analyzers_loaded` to detect existing analyzer instances
  vs other Max devices that happen to share the name.
- **`track_id` parameter** — string set by Python at load time so each
  instance knows its own identity for OSC frame addressing.
- **`osc_port` parameter** — integer, default 11001. Allows future
  per-instance OSC port assignment if needed.
- **OSC emitter** — `udpsend` to `127.0.0.1:<osc_port>`, frame format
  `/hallucinote/track/<track_id>/features [lufs_m, peak_dbfs, low_mid_power]`
  at ~30 Hz. Feature extraction from the audio inlet runs in parallel with
  `sfrecord~`.

Leave room in the patch for those four additions. The Chunk 1 patch should
already have visual real estate (e.g., a clearly-named region) for them so
the Chunk 2 author isn't fighting layout.
