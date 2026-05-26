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
- Inbound OSC receiver for path delivery. (Live parameters are float / int /
  enum only — there is no string parameter type, so `output_path` cannot be
  a Live parameter. The path is delivered out-of-band via OSC. See
  [Path delivery](#path-delivery-out-of-band-via-osc) below.)
- Two exposed Live parameters (`record_arm`, `osc_port`).
- Nothing else. No OSC *emitter*, no signature parameter, no `track_id`.

Chunk 2 extends this same patch with the outbound OSC feature emitter +
`track_id` + a Hallucinote signature surface — all listed under
"Reserved for Chunk 2" below so the build doesn't paint into a corner.

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
audio inlet  L  ──┬──> [plugout~]                  (sonic pass-through to next device)
audio inlet  R  ──┤
                  │
                  └──> [sfrecord~ 2 @nchans 2]     (writes to disk)
                              ↑
                              │ messages: samptype float32 (at loadbang),
                              │           open <path>,
                              │           1 (start), 0 (stop+finalize)
                              │
                       [udpreceive <osc_port>] → [OSC-route /path] → [prepend open]
```

The dry path must reach the outlets with **no extra sample delay** beyond
what `sfrecord~` introduces in the parallel branch (which is zero — it's a
tap, not an insert). PDC alignment depends on this.

## Exposed Live parameters

Both parameters must be **automatable + scripted-name'd** so Hallucinote's
Remote Script can write them via the existing `ableton_device.set_parameter`
path.

| Scripting name | Long name | Short name (what `set_parameter` uses) | Type | Range / values | Default |
|---|---|---|---|---|---|
| `record_arm`  | `Record Arm`  | `Arm`  | bool toggle (`live.toggle` w/ `@parameter_visible 1 @parameter_modulation_mode 0`) | 0 / 1 | 0 |
| `osc_port`    | `OSC Port`    | `Port` | int (`live.numbox` w/ `Type = Int`, `@parameter_visible 1`)                       | 11000 – 11100 | 11000 |

**Note:** Live's Remote Script API surfaces parameters by their **short name**
— `ableton_device(action='get_parameters', ...)` returns `{name: "Arm", ...}`
not `{name: "Record Arm", ...}`. Harnesses and Chunk 2's
`ensure_analyzers_loaded` must address the parameters as `Arm` and `Port`.
Setting `parameter_longname` is still useful for the Live UI parameter list
that humans browse.

Implementation hints (informative, not contractual):

- Use `live.toggle` for `record_arm` so the Remote Script's
  `set_parameter(value_type='continuous', value=1)` resolves to "on" cleanly.
- `osc_port` drives `udpreceive`'s listen port. On parameter change, send
  `[prepend port]` → `[udpreceive]` so the bind updates without a patch
  reload. On `[loadbang]`, push the current `live.numbox` value into the
  same chain so the initial port matches the stored value, not just
  `udpreceive`'s constructor argument.
- Both controls need `Parameter Visibility = Automated and Stored` (NOT
  `Stored Only` — that still bakes `parameter_invisible: 1` into the
  patch JSON and hides the param from Live's Remote Script API, despite
  the inspector label suggesting otherwise). This is the value that
  surfaces the param to Live AND survives Live file save/load. (`record_arm` going to **0** at save time is fine —
  arming is per-render, not authored state — but the parameter itself must
  exist on patch load. `osc_port` should persist its per-instance value so
  Chunk 2's `ensure_analyzers_loaded` doesn't have to re-assign on every
  Live session open.)

## Path delivery (out-of-band, via OSC)

Live parameters cannot carry strings, so the destination path is delivered
via OSC instead of via a parameter write.

- The patch instantiates `[udpreceive <osc_port>]` and re-binds when
  `osc_port` changes.
- Inbound OSC address: `/path <symbol>` — `<symbol>` is the absolute
  filesystem path the next render should write to.
- Filtered by `[OSC-route /path]` (CNMAT OSC package — standard Max
  install via Package Manager) and routed into `[prepend open]` →
  `[sfrecord~]`. The path is also retained inside the patch (`[value]` or
  equivalent) so an arm cycle without a preceding `/path` can detect the
  "no path set" error condition.
- The Python harness MUST send `/path` **before** writing `record_arm=1`.
  See the rising-edge contract for the race-window guard.
- For Chunk 1's single-instance test, default `osc_port=11000` is fine.
  Chunk 2's `ensure_analyzers_loaded` assigns per-instance ports so
  multiple analyzers on different tracks don't collide.

## Behavior contract

### sfrecord~ control API (documented)

The patch drives `sfrecord~` via the **bare-integer left-inlet API**, NOT
via `record <N>` messages:

- **`1` (integer to left inlet)** → starts recording (indefinite, until stopped)
- **`0` (integer to left inlet)** → stops recording AND finalizes the WAV
  header in one operation

There is **no** `close` message, **no** `stop` message, and **no** `record 0`
stop variant. The `record <N>` message is a *separate* API for
fixed-duration recording (`record 100` records for 100 ms then auto-stops);
do NOT use it for indefinite recording.

After a `0` is sent, the file is finalized and closed. To record again,
send a fresh `open <path>` BEFORE the next `1`. See the
[Max sfrecord~ reference](https://docs.cycling74.com/max8/refpages/sfrecord~)
for the canonical documentation.

### On rising edge of `record_arm` (0 → 1)

1. Read the most recently received `/path` (retained from the OSC inbound
   chain). If no path has been received since patch load, **do not arm**;
   emit a `[print HallucinoteAnalyzer]` error so the harness sees it and
   abort.
2. If the path's parent directory doesn't exist, **do not arm**; same error
   path. (The Python harness pre-creates the directory in Chunk 1 — this
   guard catches the "config drift" failure mode.)
3. If a file already exists at that path, overwrite it. The Python side
   owns naming (timestamped directories); no append semantics.
4. Send `open <path>` then `1` (integer) to `sfrecord~`. Ordering matters
   — the `open` MUST arrive before the `1`, or sfrecord~ logs
   `"start requested without preceding 'open'"` and ignores the start.
   Use `[t b b]` with the right-outlet bang firing `open`'s chain and the
   left-outlet bang firing `1` (right-outlet fires first in Max).
5. The recording is **32-bit float stereo at Live's session sample rate**.
   `sfrecord~` is instantiated with `2 @nchans 2`, and a `samptype float32`
   message is sent at `[loadbang]` so every subsequent `open` writes
   float32. Sample rate is inherited from Live's audio engine — do not
   set it explicitly; `sfrecord~` will not sample-rate-convert.

   Attribute-name note: `sfrecord~` in current Max uses `@nchans` (not
   `@numchans`), and sample format is **set via message, not attribute**
   (`@samptype` / `@bitdepth` are unreliable across versions; the
   `samptype <type>` message is the documented control path).

### On falling edge of `record_arm` (1 → 0)

1. Send `0` (integer) to `sfrecord~`. This stops recording AND finalizes
   the WAV header in one operation — no separate close needed.
2. The retained `/path` value is left as-is until the next `/path` message
   overwrites it. The harness owns "send a fresh `/path` per render" — the
   patch does not auto-clear it. Note that after `0`, sfrecord~ requires
   a fresh `open <path>` before the next `1` — see the Max docs.

### Steady state

- `record_arm` held at 1 across multiple transport stops/starts: keep
  writing. Live's transport state is independent of `sfrecord~`'s write
  state by design — the Chunk 1 harness drives both, and we want them
  decoupled so a future "render only one section" use case still works.
- `record_arm` held at 0: emit nothing. `sfrecord~` should not be open.

### Transport-relative timing (Chunk 1 vs Chunk 2)

**Chunk 1 (current):** The harness sets `Arm=1` via MCP, then plays
transport, then sleeps, then stops transport, then sets `Arm=0`. Each
MCP round-trip is ~700 ms in practice, so the actual arm-high window
inside the patch is ~2 s wider than the transport play window. The
recorded WAV therefore has ~1.5–2 s of leading silence (before transport
plays) and ~0.5–1 s of trailing silence (after transport stops). This is
acceptable for Chunk 1's track-only proof-of-life — the audio content is
still identifiable via the harness's `audio_start_s`/`audio_end_s`
bracket analysis.

**Chunk 2 (planned):** Recording boundaries become **transport-position-
driven** inside the patch — the patch reads Live's transport via
`live.transport` (or equivalent) and starts/stops sfrecord~ at requested
beat positions. This makes the recording sample-accurate, tempo-change-
immune (beats are the unit), and gives multi-analyzer alignment for free
(all analyzers observe the same Live transport, so they start at the
same sample). The Python side passes `/start_at_beat <N>` and
`/stop_at_beat <M>` via OSC; the patch handles the rest. MCP latency
becomes irrelevant to the recording boundary because arming just gates
whether the patch ACTS on transport events; it doesn't define them.

## Install path (manual, Chunk 1)

Copy the built `.amxd` to:

```
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd
```

Chunk 2 automates this copy inside the `ableton-mcp-install` skill.

## Authoring workflow (route through Max GUI, not direct file edits)

`.amxd` is a binary container — `ampf` magic + `ptch` chunk + embedded JSON
patcher + embedded ZIP (CNMAT OSC-route external bundle) + Mach-O fat binary
+ trailing chunks (`e64`/`sz32`/`of32`/`vers`/`flag`/`mdat`). Hand-editing
the JSON inside the file can produce a structurally-valid file (chunk sizes
update with file size) that nonetheless fails Max-for-Live's deeper loader
validation with `createdevice error 6: device file broken`. The trailing
chunks observed in working vs hand-edited files were byte-identical, so
the discrimination isn't at the chunk layer — Max is checking something
internal we don't have docs for.

**Authoring rule:** All `.amxd` edits go through Max's GUI save path. Open
the device by clicking the **Edit** button on a loaded instance in Live
(opens it in Max with Live's bundled runtime), make changes in Max's
patching view, save (`Cmd-S`). Then copy the saved file from the User
Library back to `hallucinote_mcp/src/hallucinote_mcp/m4l/` and commit.

Do **not** write a script that splices patchlines into the JSON portion
of the `.amxd` binary. It looks like it works (the file parses, the
header sizes update), and Live rejects it on load.

## Verifying the build (Chunk 1 GO/NO-GO)

Chunk 1 is a **track-only proof-of-life**. It verifies that `sfrecord~`
works under Remote Script control. It does NOT verify multi-analyzer
alignment (track + master) or strict timing precision — both deferred
to Chunk 2 (master-strip MCP support + transport-position-sync, see
build-plan.md).

Once the patch loads in Live and the Remote Script is running:

1. Drop the device on one audio track carrying audible audio (a MIDI track
   with an instrument + arrangement-playing clip is fine).
2. Run `hallucinote_mcp/tools/test_capture.py` against that track.
3. The harness writes a WAV to `/tmp/hallucinote-chunk1-<timestamp>/`.
4. The harness's `_inspect_wav` reports the verification automatically:
   - **status: clean** — non-silent audio, no clipping
   - **subtype: FLOAT**, **channels: 2**, **sample_rate: Live's SR**
   - **frames > 0** — WAV header was properly finalized
   - **audio_start_s / audio_end_s** — bracket the actual audio content
     (will be padded with MCP-latency silence at head/tail; this is
     expected and structural)
5. Record any `sfrecord~` quirks in the chunk handoff for the Chunk 2 author.

## GO criteria (Chunk 1 scope)

- WAV exists at expected path with expected dtype/channels/SR.
- WAV header is finalized (soundfile reports frames > 0).
- Audio content is non-silent (peak above -60 dBFS, no clipping).
- Param writes from the harness reliably trigger record start/stop via
  the patch's rising/falling-edge handlers.

## NO-GO criteria

- WAV missing, empty (0 frames), or unreadable.
- Audio is silent (peak ≤ -60 dBFS) — signal isn't reaching `sfrecord~`.
- `Arm` parameter writes don't reliably trigger record start (race
  condition between Remote Script parameter-write and `sfrecord~` open).

**Not in Chunk 1's GO scope (deferred to Chunk 2):**

- **Strict duration match** (recording window precisely equals transport
  play window). The current MCP-latency-bounded recording is structurally
  ~2 s longer than the transport window. Chunk 2 fixes this with
  transport-position-driven recording boundaries inside the patch.
- **PDC alignment** (track vs master cross-correlation). Requires
  simultaneous master analyzer capture, which requires master-strip MCP
  support — Chunk 2 work.

NO-GO at the Chunk 1 level falls back to the spike's Resampling-tracks
alternative (§1) — re-plan before continuing to Chunk 2.

---

## Reserved for Chunk 2 (do NOT add in Chunk 1)

Chunk 2 will extend this patch with the following. Listed here so the Chunk 1
build leaves space for them without painting into a corner:

- **`signature` surface** — value `"hallucinote-analyzer-v1"`. Used by
  `ensure_analyzers_loaded` to detect existing analyzer instances vs other
  Max devices that happen to share the name. Strings cannot be Live
  parameters; Chunk 2 will decide between (a) an enum Live parameter with
  a single fixed-value slot, (b) inferring identity from the device's
  `.amxd` filename via the Live API, or (c) an OSC query/response on the
  same `osc_port`.
- **`track_id` surface** — same string constraint as `signature`. Chunk 2
  will likely deliver it via OSC (e.g., `/track_id <symbol>`) using the
  already-built inbound channel, mirroring how `/path` works in Chunk 1.
- **OSC emitter** — `udpsend` to `127.0.0.1:<emit_port>` (separate from
  the inbound port), frame format
  `/hallucinote/track/<track_id>/features [lufs_m, peak_dbfs, low_mid_power]`
  at ~30 Hz. Feature extraction from the audio inlet runs in parallel with
  `sfrecord~`. May reuse `osc_port` for outbound or introduce
  `osc_emit_port` — Chunk 2 decides.

Leave room in the patch for those additions. The Chunk 1 patch should
already have visual real estate (e.g., a clearly-named region) for them so
the Chunk 2 author isn't fighting layout. (`osc_port` and `[udpreceive]`
are already in place from Chunk 1; Chunk 2 just adds the outbound side
and the identity surface.)
