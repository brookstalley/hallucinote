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

## Scope: Chunk 1 (shipped) + Chunk 2 (this round)

**Chunk 1** (closed 2026-05-26) shipped the minimum viable proof of life:

- One `sfrecord~` per instance, writing the inserting track's audio to disk.
- Inbound OSC receiver for path delivery. (Live parameters are float / int /
  enum only — there is no string parameter type, so `output_path` cannot be
  a Live parameter. The path is delivered out-of-band via OSC. See
  [Path delivery](#path-delivery-out-of-band-via-osc) below.)
- Two exposed Live parameters (`record_arm`, `osc_port`).
- No OSC *emitter*, no signature parameter, no `track_id`.

**Chunk 2** extends this same patch with:

- **Outbound OSC feature emitter** — LUFS-M, true peak (sample-peak proxy),
  low-mid (200–500 Hz) band power per instance at ~30 Hz. UDP target
  `127.0.0.1:<osc_emit_port>` (a new Live parameter; see below). Frame
  shape: `/hallucinote/track/<track_id>/features [lufs_m, peak_dbfs, low_mid_power]`.
- **`track_id` surface** — string-valued, delivered out-of-band via OSC
  (same rationale as `/path`: Live params are float / int / enum only).
  Inbound address `/track_id <symbol>`. Retained inside the patch so the
  outbound feature frame can name itself.
- **Hallucinote signature** — a fixed string `"hallucinote-analyzer-v1"`
  used by `ensure_analyzers_loaded` to distinguish HallucinoteAnalyzer
  instances from other Max devices that happen to share a name. Surfaced
  via OSC query `/signature/query` → reply `/signature hallucinote-analyzer-v1`
  on the inbound port. (See [Signature surface](#signature-surface) below
  for why OSC-query won over the enum-parameter and filename-inference
  alternatives. The hierarchical query path avoids the `?` OSC wildcard
  character that would otherwise make `/signature?` ambiguous in clients
  that do pattern-matched address dispatch.)
- **Transport-position-driven recording boundaries** — the Python harness
  no longer defines the recording window via MCP-latency-bounded
  `Arm` toggles. Instead, the patch reads Live's transport position at
  signal rate and starts/stops `sfrecord~` when transport crosses
  requested beats. `/start_at_beat <N>` and `/stop_at_beat <M>` arrive
  via OSC. `Arm` just gates whether the patch ACTS on those events.
  Buys sample-accurate boundaries, tempo-change immunity, and multi-
  analyzer alignment for free (every analyzer observes the same Live
  transport). See [Transport-position-driven timing](#transport-position-driven-timing-chunk-2).

The Chunk 2 additions live alongside the Chunk 1 surface — they don't
replace it. The Chunk 1 `Arm`/`Port`/`/path` interfaces are unchanged.

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
                  ├──> [sfrecord~ 2 @nchans 2]     (writes to disk)
                  │           ↑
                  │           │ messages: samptype float32 (at loadbang),
                  │           │           open <path>,
                  │           │           1 (start), 0 (stop+finalize)
                  │           │
                  │  [udpreceive <osc_port>]                       Chunk 1 + Chunk 2 inbound
                  │       ├──> [OSC-route /path] → [prepend open]
                  │       ├──> [OSC-route /track_id] → [value $track_id]      (Chunk 2)
                  │       ├──> [OSC-route /start_at_beat] → [int] → start-beat   (Chunk 2)
                  │       ├──> [OSC-route /stop_at_beat] → [int] → stop-beat     (Chunk 2)
                  │       └──> [OSC-route /signature/query] → unpack reply host+port → reply via [udpsend]  (Chunk 2)
                  │
                  └──> Feature-extraction branch (Chunk 2)
                            │
                            ├──> LUFS-M (K-weighted, 400 ms momentary integration)
                            ├──> peak (sample-peak proxy via [peakamp~] @ ~30 Hz)
                            ├──> low-mid power (200–500 Hz bandpass → [average~] → dB)
                            │
                            └──> [pak f f f] @ 30 Hz → [prepend /hallucinote/track/<track_id>/features]
                                                    → [udpsend 127.0.0.1 <osc_emit_port>]
```

The dry path must reach the outlets with **no extra sample delay** beyond
what `sfrecord~` introduces in the parallel branch (which is zero — it's a
tap, not an insert). PDC alignment depends on this. The feature-extraction
branch is also a tap, not an insert — same zero-delay requirement.

The transport-position observer (Chunk 2; see [Transport-position-driven
timing](#transport-position-driven-timing-chunk-2)) lives in a
control-rate region; it doesn't touch the audio path.

## Exposed Live parameters

All parameters must be **automatable + scripted-name'd** so Hallucinote's
Remote Script can write them via the existing `ableton_device.set_parameter`
path.

| Scripting name    | Long name        | Short name (what `set_parameter` uses) | Type | Range / values | Default |
|---|---|---|---|---|---|
| `record_arm`      | `Record Arm`     | `Arm`        | bool toggle (`live.toggle` w/ `@parameter_visible 1 @parameter_modulation_mode 0`) | 0 / 1         | 0     |
| `osc_port`        | `OSC Port`       | `Port`       | int-displayed float (`live.numbox` w/ `Type = Float`, `Unit Style = Int`, `@parameter_visible 1`) | 11000 – 11400 | 11020 |
| `osc_emit_port`   | `OSC Emit Port`  | `EmitPort`   | int-displayed float (`live.numbox` w/ `Type = Float`, `Unit Style = Int`, `@parameter_visible 1`) | 11000 – 11400 | 11221 |
| `emit_enabled`    | `Emit Features`  | `Emit`       | bool toggle (`live.toggle`)                                                        | 0 / 1         | 1     |

**Why Type=Float with Unit Style=Int for the port parameters?** Live
encodes Int-typed parameter automation as a single byte (0-255), so
Int-typed `live.numbox` parameters have `max - min ≤ 255` silently
clamped in Max's Inspector. Per Max's documentation: "When working
with Live UI objects whose integer values will exceed this range,
the Type attribute should be set to Float, and the Unit Style
attribute should be set to Int." This renders whole-number values
in the UI while removing the 256-step cap. The Remote Script's
`set_parameter(value_type='continuous', value='11042.0')` writes
through normally — the patch reads `[live.numbox]`'s outlet as a
float and coerces with `[i]` where an int is needed.

**Port allocation policy** (Chunk 2): `ensure_analyzers_loaded` assigns
per-instance `Port` deterministically by surface address, so the next
sweep recovers the same layout without inspecting prior state.

- Tracks: `11020 + (track_index - 1)` (stride 1). Supports 100 audio tracks.
- Returns: `11120 + (return_index - 1)`. Supports 100 returns.
- Master: `11220`.
- Emit port (shared sidecar): `11221` (default; overridable per-run).

Total span 11020-11221 = 202 ports. Range 11000-11400 (the .amxd's
declared `Port` range) leaves headroom for future expansion above AND
below the active range. Accidental port collisions surface as
`[udpreceive]` bind failures at patch load — the patch can't silently
double-bind.

**Why base 11020, not 11000?** AbletonOSC — the most common community
Remote Script for Live — binds ports 11000 + 11001 by convention. A
Hallucinote installation alongside AbletonOSC would have track 1 + 2
analyzers fail to bind their assigned ports. Shifting the base up 20
ports clears the collision and leaves room (11002-11019) for other
community Remote Scripts following similar low-port conventions. The
default `Port` value baked into the .amxd is therefore `11020`, not
`11000` — every freshly-loaded analyzer (before the sweep configures
it) targets a port that doesn't collide with AbletonOSC.

**Note:** Live's Remote Script API surfaces parameters by their **short name**
— `ableton_device(action='get_parameters', ...)` returns `{name: "Arm", ...}`
not `{name: "Record Arm", ...}`. Harnesses and Chunk 2's
`ensure_analyzers_loaded` must address the parameters by their short names
(`Arm`, `Port`, `EmitPort`, `Emit`). Setting `parameter_longname` is still
useful for the Live UI parameter list that humans browse.

Implementation hints (informative, not contractual):

- Use `live.toggle` for `record_arm` and `emit_enabled` so the Remote Script's
  `set_parameter(value_type='continuous', value=1)` resolves to "on" cleanly.
- `osc_port` drives the *inbound* `udpreceive`'s listen port. `osc_emit_port`
  drives the *outbound* `udpsend` destination port. They are deliberately
  separate Live parameters so every analyzer can emit features to one
  shared sidecar port (11221) while listening on per-instance inbound
  ports (11020, 11021, 11022 …). On `osc_port` change, send
  `[prepend port]` → `[udpreceive]` so the bind updates without a patch
  reload. On `osc_emit_port` change, send `[prepend port]` →
  `[udpsend]`'s single inlet (symmetric to udpreceive's
  config-by-message convention).
- On `[loadbang]`, push each `live.numbox`'s current value into its
  destination so the initial port matches the stored value, not just the
  Max object's constructor argument.
- `emit_enabled` gates the OSC emitter only. It does NOT gate
  `sfrecord~` — recording is governed by `Arm` + the transport-position
  observer.
- All controls need `Parameter Visibility = Automated and Stored` (NOT
  `Stored Only` — that still bakes `parameter_invisible: 1` into the
  patch JSON and hides the param from Live's Remote Script API, despite
  the inspector label suggesting otherwise). This is the value that
  surfaces the param to Live AND survives Live file save/load. (`record_arm`
  going to **0** at save time is fine — arming is per-render, not authored
  state — but the parameter itself must exist on patch load. `osc_port`,
  `osc_emit_port`, and `emit_enabled` persist their per-instance values
  so `ensure_analyzers_loaded` doesn't have to re-assign on every Live
  session open.)

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
- For Chunk 1's single-instance test, default `osc_port=11020` is fine.
  Chunk 2's `ensure_analyzers_loaded` assigns per-instance ports so
  multiple analyzers on different tracks don't collide.

## Track-id delivery (Chunk 2; out-of-band, via OSC)

The outbound feature frame needs an identity prefix
(`/hallucinote/track/<track_id>/features ...`) so the sidecar can route
frames to the right ring buffer. Like `/path`, the value is a string and
can't be a Live parameter.

- Inbound OSC address: `/track_id <symbol>` on `osc_port`.
- Filtered by `[OSC-route /track_id]` and retained in the patch via
  `[value track_id_retained]` (read-by-bang storage — `[value]`
  doesn't emit on cold-inlet write per learnings "M4L `[value]`
  doesn't emit on write", so the feature emitter explicitly bangs
  the `[value]` once per metro tick to fetch the current symbol).
- A separate `has_track_id` int flag (plumbed via `[send]`/`[receive]`,
  NOT `[value]` — see the "Gating" section below for the contract)
  controls whether the emitter actually fires. If no track_id has
  been received since patch load, the emitter holds frames (does
  NOT emit a placeholder address — empty / "unknown" identities would
  poison the sidecar's ring buffer).
- `track_id` strings are opaque to the patch. The Python side chooses
  the shape (UUIDs in MVP, with the option to switch to `<song-slug>:<track-name>`
  later for human-readability) — the patch just round-trips whatever
  symbol it receives.
- `ensure_analyzers_loaded` sends `/track_id` once per analyzer at
  load time. The patch retains the value across Live session saves so
  per-render re-assignment isn't required.

## Signature surface (Chunk 2; via OSC query)

`ensure_analyzers_loaded` needs to tell a HallucinoteAnalyzer instance
apart from any other Max Audio Effect that happens to have the same
device name. (Different M4L patches can be saved with the same display
name; relying on device name alone is fragile.) Three options
considered; the OSC-query path wins:

- ❌ **Enum Live parameter** with one fixed slot (`signature = "hallucinote-analyzer-v1"`).
  Hides identity behind another `get_parameters` call; pollutes the
  device's parameter surface with a not-really-a-parameter; consumes one
  of Live's limited Live-API parameter slots; offers no advantage over
  OSC.
- ❌ **Filename inference** via Live's `device.class_name` /
  `device.class_display_name`. Today `class_display_name` equals the
  `.amxd` filename for M4L devices — but that's an empirical behavior,
  not a contract, and any user-renamed device file would break the
  check. Couples identity to the install path, which is the surface
  the install skill is *about* to start auto-managing.
- ✅ **OSC query/response with explicit reply destination**. Inbound
  `/signature/query <reply_host> <reply_port>` on `osc_port`; the
  patch replies via `[udpsend]` to the explicit `reply_host:reply_port`
  carried in the query's OSC args with `/signature
  hallucinote-analyzer-v1`. Identity lives inside the patch as a
  hardcoded constant; doesn't pollute the parameter surface; works
  the same whether the device file was renamed or not; reuses the
  OSC channel already in place from Chunk 1. The hierarchical query
  path (`/signature/query`) avoids the `?` OSC pattern-match wildcard
  that would make `/signature?` ambiguous in OSC clients that
  dispatch by pattern. The explicit reply-destination args (vs. trying
  to extract sender host:port from `[udpreceive]`'s status outlet)
  removes the dependency on Max-object internals — vanilla
  `[udpreceive]` exposes one outlet (the OSC messages), not a sender-
  metadata sidechannel.

The signature value is a **versioned string** so future incompatible
patch revisions can identify themselves (`hallucinote-analyzer-v2`,
etc.) and `ensure_analyzers_loaded` can refuse to drive an
incompatible analyzer. For Chunk 2's MVP, all analyzers emit
`hallucinote-analyzer-v1`.

The signature response carries no `track_id` — the caller correlates
by the source UDP port it sent the query from (one query per analyzer
instance, since each analyzer listens on its own `osc_port`).

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

### Transport-position-driven timing (Chunk 2)

Chunk 1 defined the recording window via MCP-latency-bounded `Arm`
toggles: arm via MCP (~700 ms), play, sleep, stop, disarm via MCP (~700
ms). Result: ~2 s of silence padding around the actual audio content,
and worse, *non-deterministic* alignment between multiple analyzers in
the same render — each one's arm-high window is bounded by an
independent MCP round-trip. PDC math at the master-vs-track level
breaks under that timing model.

Chunk 2 moves the boundary decision *into* the patch. The harness writes
two integer-valued OSC messages before starting transport, and the
patch handles the rest.

**Inbound OSC (Chunk 2):**

- `/start_at_beat <int>` — the absolute song beat at which `sfrecord~`
  should start writing. Integer beats only for MVP (matches Live's
  beat count convention; sub-beat alignment is a post-MVP refinement).
- `/stop_at_beat <int>` — the absolute song beat at which `sfrecord~`
  should stop AND finalize. Must be > `start_at_beat`. The patch
  refuses to arm if the inequality doesn't hold.

Both are retained inside the patch (`[value]`-style) and persist until
overwritten or until the patch is reloaded. The harness owns "send
fresh `/start_at_beat` + `/stop_at_beat` per render" — the patch does
NOT clear them after firing.

**Transport observer:**

The patch subscribes to Live's transport-beat counter (via the
`[live.observer]` external pointed at `live_set song_time`, OR the
`live.thisdevice`-rooted equivalent that exposes the current song beat
position). It runs at control rate — the granularity is one Max
scheduler tick, which is fine for beat-accurate boundaries at all
reasonable tempos. Sample-accurate (sub-tick) boundaries are
deliberately out of scope for the MVP; if PDC math ever demands them,
the upgrade path is `[plugsync~]` + signal-rate comparison, but
empirical multi-analyzer alignment at tick rate looks adequate.

**Behavior contract:**

- `Arm=0`: patch ignores all transport events. `sfrecord~` is closed.
- `Arm=1` + transport stopped: patch holds. `sfrecord~` is NOT open
  yet. The retained `/path` is read but not acted on.
- `Arm=1` + transport playing + current_beat < `start_at_beat`:
  patch holds. `sfrecord~` is NOT open yet.
- `Arm=1` + transport-position observer fires "current_beat crossed
  `start_at_beat`": patch sends `open <path>` then `1` (integer) to
  `sfrecord~` in the documented order (`[t b b]` right-then-left).
  Recording is now active.
- `Arm=1` + recording active + observer fires "current_beat crossed
  `stop_at_beat`": patch sends `0` to `sfrecord~`. Recording is
  finalized.
- After the stop-beat crossing, the patch returns to the
  "Arm=1 + holding" state. A subsequent `/start_at_beat` +
  `/stop_at_beat` pair (with the harness having also sent a fresh
  `/path`) re-arms for the next render WITHOUT requiring the harness
  to toggle `Arm`. This is the multi-section render path: one Arm
  cycle covers an arbitrary number of beat-windowed captures, each
  written to its own path.
- `Arm` falling edge (1 → 0) DURING active recording: patch sends `0`
  to `sfrecord~` immediately (the "user pulled the cord" path). Same
  rising-edge no-path / no-parent-dir guards apply.

**Why beat-based, not sample-based, for the wire:**

- Tempo automation between bars just works (the beat observer crosses
  the boundary at the actual wall-clock moment dictated by the active
  tempo, not by a sample count the harness pre-computed at one tempo).
- Multi-analyzer alignment is structural — every analyzer observes the
  same Live transport, so they all see `current_beat = start_at_beat`
  at the same audio buffer.
- The harness can express "record the entire arrangement" as
  `(0, arrangement_length_in_beats)` regardless of tempo automation.

**Why arm-as-gate (not arm-as-boundary):**

`Arm` is a Live parameter; writes go through Remote Script with its
~700 ms latency. Defining a sample-accurate boundary on top of that is
hopeless. By making `Arm` the gate ("do you care about transport
events?") and the beat observer the boundary ("which transport
events?"), MCP latency becomes irrelevant to the recording window.

**Unset `start_at_beat` / `stop_at_beat` is an error.** The driver
(`ableton_render`) MUST send both before raising `Arm`; the patch
refuses to begin recording without them.

## OSC feature emitter (Chunk 2)

Each analyzer emits a periodic feature frame to a Python sidecar. The
sidecar maintains a per-`track_id` ring buffer and exposes the buffer
to the rest of the MCP server as an internal API. Frames are emitted
whenever Live's audio thread is running — independent of `Arm` /
`sfrecord~` / transport state — so a future "always-on realtime
mix-coaching" surface (post-MVP) sees data even when nothing is being
recorded. `emit_enabled` (Live parameter) is the kill switch.

**Sample-rate dependency (MVP constraint).** The K-weighting biquad
coefficients (LUFS-M pre-filter) and the 200–500 Hz bandpass biquad
coefficients are hardcoded for **48 kHz session sample rate** — the
ITU-R BS.1770-4 reference rate. Running the patch at a different SR
shifts the filter cutoffs by `(48000 / actual_Fs)`. The MVP-tolerance
envelope:

- **48 kHz session:** 0.0 LU drift, low-mid band delivered as 200–500 Hz
  (spec design). GO.
- **44.1 kHz session:** ~0.1–0.3 LU drift (content-dependent), low-mid
  band ~218–544 Hz. At the edge of the spec's ±0.2 LU tolerance — GO
  for MVP, but expect occasional out-of-tolerance readings on bass-heavy
  content.
- **88.2 kHz / 96 kHz session:** ~0.2–0.5+ LU drift, low-mid band shifted
  to ~100–250 Hz (wrong band). NO-GO for the MVP — file an MCP-side
  pre-flight check that refuses `ableton_render` when session SR > 48 kHz
  until SR-adaptive coefficients land (post-MVP backlog).

Sample-window sizes for `[average~]` (LUFS-M 400 ms, low-mid 100 ms) ARE
SR-adaptive — computed at patch load from `[adstatus sr]`. So those
remain correct at any SR. Only the filter coefficients are SR-pinned.

**SR-mismatch contract (load-time warning).** The patch prints a
Max-console warning at load (and on driver SR change) if the session SR
isn't 48 kHz. Format:

```
HallucinoteAnalyzer: WARNING — LUFS coefficients tuned for 48 kHz; session SR differs ...
```

The MCP-side `ableton_render` action SHOULD probe Live's session SR
before triggering a render and surface a warning in the manifest's
`status` field (`'ok' | 'incomplete' | 'sr_mismatch'`) so the analysis
pipeline (Chunk 3) can apply an SR-correction calibration if available
or refuse to produce a `MixReport` if not. (Chunk-3 scope; not Chunk 2.)

**Frame shape:**

- OSC address: `/hallucinote/track/<track_id>/features`
- Type tag: `,ffff` (four 32-bit floats; grows to `,fffff` etc.
  as features are added — see "Growth convention" below)
- Payload, in this fixed positional order:
  0. `beat_position` — Live transport position in beats at the
     moment the frame was sampled. Source: `[live.observer]` on
     `current_song_time` (the same observer Section D's
     transport-crossing logic uses; the feature emitter forks the
     outlet via `[t f f]` and latches via `[f beat_pos_latched]`).
     Units: beats (float). During transport stop, holds the
     last-played position. **Always payload[0], always present, even
     as additional features are added** — this is the wire-protocol
     anchor for cross-analyzer reconciliation.
  1. `lufs_m` — momentary loudness per ITU-R BS.1770-4, K-weighted,
     400 ms integration window. Units: LUFS (LU above silence).
     Patch implementation: K-weighting filter (high-shelf at 1.5 kHz
     +4 dB → high-pass at 38 Hz) → squared → mean over 400 ms →
     `10 * log10()` → minus 0.691 (the BS.1770 constant). Use
     Max's `[poly~]` or a flat-patch implementation of the
     pre-filter cascade; do NOT use a Max external whose
     coefficients aren't documented.
  2. `peak_dbfs` — sample-peak (NOT true-peak; true-peak requires
     4× oversampling, deferred to Chunk 3's offline analysis). Read
     via `[peakamp~ 33]` self-clocked at 33 ms (~30 Hz). Units: dBFS.
  3. `low_mid_power` — RMS power in the 200–500 Hz band. Patch
     implementation: 200 Hz high-pass → 500 Hz low-pass (both 4th-
     order Linkwitz-Riley or equivalent, ~24 dB/oct so the band is
     well-defined) → `[average~]` over 100 ms → `10 * log10()`.
     Units: dB relative to full scale. Chunk 3's master-bus
     contribution attribution wants this band specifically because
     it's where kick + bass interact (the "is the mix muddy" /
     "what's clipping the master" diagnostic).

**Growth convention (load-bearing for sidecar parser stability).**
When new feature measurements are added in future analyzer
versions, they **append** to the end of the payload — they never
displace `beat_position` (which stays at payload[0]) or the
existing feature ordering. Sidecars parse positionally:
`payload[0]` is always the sample timestamp; `payload[1:]` is the
feature vector. An older sidecar parsing a newer frame reads the
known floats and ignores trailing extras (no error). A newer
sidecar reading an older frame sees a shorter `payload[1:]` and
treats the missing features as unavailable. The analyzer's
`/signature` reply (`hallucinote-analyzer-v1` → `v2` →...) lets
sidecars discover feature-vector length when strict
shape-checking is needed.

**Why `beat_position` first, not in the OSC address?** OSC
addresses are symbol routes (topic dispatch); putting a float in
the address (`/hallucinote/track/<id>/at/<beat>`) breaks address
pattern-matching for clients that dispatch by symbol, inflates
the per-frame byte count (longer symbol vs a 4-byte float arg),
and balloons as more metadata accrues. The "address as topic,
payload as measurements" idiom matches AbletonOSC + TouchOSC. By
fixing `beat_position` at `payload[0]` rather than threading it
through the address, the wire format stays growable without
re-versioning the route.

**Emit rate:** ~30 Hz (every 33 ms). Driven by a `[metro 33]` →
`[snapshot~]`-on-each-extractor chain. Rate is intentionally not
exposed as a Live parameter; if it ever needs to be tuned, Chunk 3
will surface the trade-off.

**Destination:** `127.0.0.1:<osc_emit_port>` via `[udpsend]`. The
emit port is per-instance (Live parameter), but `ensure_analyzers_loaded`
configures every analyzer to emit to the same port (default 11221,
sitting just past the master analyzer's inbound port at 11220) so
the sidecar opens one socket. Multiple analyzers writing to one UDP
socket is fine — UDP delivery is best-effort and the sidecar's ring
buffers are keyed by `track_id` (extracted from the address), so
interleaving is the expected shape.

**Gating:**

- `emit_enabled=0`: no frames. The extractors keep running (no audio-
  thread cost difference) but the `[udpsend]` is gated by a `[gate]`
  whose control inlet is wired directly to the `Emit` `[live.toggle]`'s
  outlet (which emits int 0/1 directly — no symbol-to-int shim — see
  learnings "M4L `[live.toggle]` outlet emits int (0/1) directly").
- `track_id` unset (no `/track_id <symbol>` received since patch
  load): no frames. A second `[gate]` in series consumes a
  `has_track_id` int flag. The flag is set to 0 by `[loadbang]` and
  to 1 by the `/track_id` OSC route, broadcast via `[send has_track_id]`
  / `[receive has_track_id]`. **The flag MUST be plumbed via
  `[send]`/`[receive]`, not `[value]`** — `[value]` doesn't emit on
  cold-inlet write (learnings "M4L `[value]` doesn't emit on write"),
  so a `[value has_track_id]` would leave the gate stuck at its
  loadbang value forever. The patcher contract:
  - `/track_id` OSC route → `[t b]` → `[1]` → `[send has_track_id]`
  - `[loadbang]` → `[0]` → `[send has_track_id]`
  - `[receive has_track_id]` → second `[gate]`'s control inlet 0
- Audio thread idle (Live's audio engine off): no frames as a
  side effect — `[metro]` runs but the extractors return -inf / 0
  and the patch emits the literal zeros. Sidecar consumers must
  tolerate this; the ring buffer treats -120 LUFS as "silent",
  not as "broken". The sidecar's `-inf`/`-120 LUFS` distinction is
  semantic, not numeric — `-120` is the patch's canonical "log of
  silence" sentinel.

**What the patch does NOT compute (deferred to offline analysis):**

- LUFS-integrated (LUFS-I) — the full song integration. Requires the
  full WAV; computed by `pyloudnorm` in Chunk 3.
- LUFS-short-term (LUFS-S) — 3 s sliding window. Computable inside
  the patch but not needed for the MVP's realtime surface; offline
  analysis derives it from the WAV.
- True peak (oversampled) — 4× resample then max-abs. Computed in
  Chunk 3 offline from the WAV; sample-peak is the realtime proxy.
- PSR / dynamic range — derived offline.
- Spectral centroid, 1/3-octave bands beyond low-mid, masking
  ratios, intersample peaks — all deferred to offline analysis.

The split is deliberate: the patch carries the minimum that
realtime mix-coaching needs (deferred to post-MVP), the offline
pipeline carries everything that benefits from looking at the
whole stem.

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

**Step-by-step authoring guide:** see
[`AUTHORING-CHUNK-2B.md`](./AUTHORING-CHUNK-2B.md) — procedural recipe
for the Chunk 2 GUI work (which objects to drag in, inspector values,
wiring order, sanity checks). The spec (this file) is the contract;
the authoring guide is the recipe.


---

## Verifying the build (Chunk 2 GO/NO-GO)

Chunk 2 verifies the multi-analyzer capture path end-to-end:
`ableton_render` on a real song — every audio track + every return +
master picks up an analyzer; one playback pass produces N+R+1 WAVs +
a manifest.

Once the Chunk 2 `.amxd` is built and copied into the User Library
(via `/ableton-mcp-install`):

1. Open a Hallucinote song with multiple tracks and at least one
   return. `falling-walking` is the obvious choice — it has the
   typical 4 tracks + 2 returns shape.
2. Invoke `ableton_render` via the MCP. The action's silent
   ensure-analyzers sweep places HallucinoteAnalyzer on every
   track + return + master if not already present, configures
   ports + track_ids via OSC, then drives the render.
3. Confirm `songs/falling-walking/captures/<timestamp>/` exists
   with N+R+1 WAVs (one per analyzer) + `manifest.json`.
4. Each WAV is FLOAT / stereo / Live's SR. Duration should match
   the arrangement length within one buffer (no leading/trailing
   silence padding — that's the transport-position-sync win).
5. Cross-correlate any track WAV vs the master WAV; the lag should
   be within ± 64 samples of zero (PDC alignment).
6. While the render runs, confirm the OSC sidecar received feature
   frames at ~30 Hz per analyzer (smoke test; the
   `ableton_render` return value should report frame counts).

### GO criteria (Chunk 2 scope)

- `ableton_render` produces one WAV per analyzer + a manifest.
- Every WAV is FLOAT / stereo / Live's SR with frames > 0 and audio
  content above -60 dBFS (modulo intentionally-muted tracks).
- WAV duration matches arrangement length within one audio buffer
  (no MCP-latency silence padding around the content).
- Any track WAV cross-correlated against the master WAV produces a
  lag within ± 64 samples of zero (PDC alignment is structural —
  every analyzer observes the same Live transport).
- OSC sidecar receives ≥ one frame per analyzer per render. Full
  ~30 Hz rate validation is post-MVP (the sidecar surface for
  realtime mix-coaching ships after Chunk 4).
- Running `ableton_render` twice produces two independent captures
  directories — the silent ensure-analyzers sweep is idempotent.

### NO-GO criteria (Chunk 2)

- Recording boundaries are still MCP-latency-bounded (~2 s padding
  around content). Likely cause: the transport-position observer
  isn't actually observing, or the patch is still treating `Arm` as
  the boundary.
- PDC alignment is off by > 64 samples between analyzers in the
  same render. Likely cause: the beat observer in different
  analyzer instances is firing on different audio buffers (out-of-
  sync due to a per-instance computation; should be reading Live's
  shared transport).
- OSC sidecar receives no frames during a render. Likely cause:
  `emit_enabled` defaulted to 0, or `track_id` wasn't set, or the
  emit port doesn't match the sidecar's listen port, or the K-
  weighting / band-power extractors are stuck.
- `ensure_analyzers_loaded` isn't idempotent — a second run
  duplicates analyzers on tracks. Likely cause: signature check
  failing (OSC query has no reply, or reply on a different port,
  or `track_id` is being used as identity instead of signature).

NO-GO at the Chunk 2 level falls back to a track-only render (skip
master + skip returns) so Chunk 3 has at least per-track WAVs to
work with while the alignment / sidecar / master-strip surface
gets debugged in a follow-up.
