# HallucinoteAnalyzer.amxd — build spec

Authoring contract for `HallucinoteAnalyzer.amxd`. The `.amxd` is a binary Max
for Live container; this spec is the auditable text surface and the contract
the patch must honor.

To modify the patch, see
[`PATCH-MODIFICATION-GUIDE.md`](./PATCH-MODIFICATION-GUIDE.md).

---

## Patch type

**Audio Effect** (`amxd~ audioeffect`). Stereo in, stereo pass-through out.
Sample rate and channel count follow Live's session SR. The dry signal must
reach the outlets with **no extra sample delay** — the device must be
sonically transparent so analysis never alters the mix. Recording and feature
extraction are parallel taps, not inserts.

Output WAVs: **32-bit float stereo at Live's session SR**. `sfrecord~` is the
write path.

## Inlets / outlets

```
audio inlet  L  ──┬──> [plugout~]                          (sonic pass-through)
audio inlet  R  ──┤
                  │
                  ├──> [sfrecord~ 2 @nchans 2]              (records to disk)
                  │           ↑
                  │           │ messages: samptype float32 (at loadbang),
                  │           │           open <path>,
                  │           │           1 (start), 0 (stop+finalize)
                  │           │
                  │  [udpreceive <osc_port>]                inbound OSC
                  │       ├──> [OSC-route /path]          → [prepend open] → [sfrecord~] inlet 0
                  │       ├──> [OSC-route /track_id]      → [prepend set] → [message] (per-instance storage; banged by metro)
                  │       ├──> [OSC-route /start_at_beat] → [int] → start-beat storage ([i])
                  │       ├──> [OSC-route /stop_at_beat]  → [int] → stop-beat storage ([i])
                  │       └──> [OSC-route /signature/query] → unpack reply host+port → reply via [udpsend]
                  │
                  └──> Feature-extraction branch
                            │
                            ├──> LUFS-M (K-weighted, 400 ms mean-square integration)
                            ├──> sample-peak (via [peakamp~ 33])
                            ├──> low-mid power (200–500 Hz band → 100 ms mean-square)
                            │
                            └──> [pack s f f f f] @ ~30 Hz
                                  → [prepend /hallucinote/track/<track_id>/features]
                                  → [udpsend 127.0.0.1 <osc_emit_port>]
```

The transport-position observer (control-rate) drives recording boundaries;
it doesn't touch the audio path.

## Exposed Live parameters

All parameters must be **automatable + scripted-name'd** with
`Parameter Visibility = Automated and Stored` so Hallucinote's Remote Script
can write them via `ableton_device.set_parameter`. Live surfaces parameters
by their **short name**; harnesses must use the short names below.

| Scripting name    | Long name        | Short name | Type                                | Range / values | Default |
|---|---|---|---|---|---|
| `record_arm`      | `Record Arm`     | `Arm`      | `live.toggle`                       | 0 / 1          | 0      |
| `osc_port`        | `OSC Port`       | `Port`     | `live.numbox`, Type=Float, Unit Style=Int | 11000 – 11400 | 11020 |
| `osc_emit_port`   | `OSC Emit Port`  | `EmitPort` | `live.numbox`, Type=Float, Unit Style=Int | 11000 – 11400 | 11221 |
| `emit_enabled`    | `Emit Features`  | `Emit`     | `live.toggle`                       | 0 / 1          | 1      |

Ports use Float type with Unit Style=Int because Live's Int-typed automation
is single-byte (0-255). (See `learnings.md` "M4L Int parameter range capped
at 256 — use Float + Unit Style Int".)

### Port allocation policy

`ensure_analyzers_loaded` assigns per-instance `Port` deterministically by
surface address:

- Tracks: `11020 + (track_index - 1)`. Supports 100 audio tracks.
- Returns: `11120 + (return_index - 1)`. Supports 100 returns.
- Master: `11220`.
- Feature emit port (shared sidecar): `11221` (default; overridable per-run).

Total active span 11020-11221 fits inside the 11000-11400 range with
headroom both directions. Base 11020 (not 11000) avoids collision with
AbletonOSC, which binds 11000-11001.

On `osc_port` change, the patch sends `[prepend port]` → `[udpreceive]` so
the bind updates without a patch reload. Symmetrically for `osc_emit_port`
→ `[udpsend]`. At `[loadbang]`, each `live.numbox`'s current value is
pushed into its destination so initial port matches the stored value.

`emit_enabled` gates the OSC emitter only; it does NOT gate `sfrecord~`.

## Path delivery (out-of-band, via OSC)

Live parameters cannot carry strings. Path is delivered via OSC:

- Inbound OSC address: `/path <symbol>` — absolute filesystem path.
- Routing: `[OSC-route /path]` outlet 0 → `[prepend open]` → `[sfrecord~]`
  inlet 0 **directly**. No retainer. `sfrecord~` holds the open file
  internally; the next `1` integer starts recording into it.
- The harness MUST send `/path` before raising `Arm` for a render. With no
  preceding `/path`, `sfrecord~` has no file open and silently records
  nothing (implicit guard — no separate `has_path` flag).

## Track-id delivery (out-of-band, via OSC)

The outbound feature frame needs an identity prefix
(`/hallucinote/track/<track_id>/features`) so the sidecar can route frames
to the right ring buffer. Track-id is a string and can't be a Live parameter.

- Inbound OSC address: `/track_id <symbol>` on `osc_port`.
- Stored in a `[message]` box fed by `[prepend set]` (right inlet stores
  without emitting); the metro chain bangs the message's left inlet once
  per tick to emit the current track_id into the address sprintf. The
  message box is per-patcher (no global namespace), so each analyzer
  instance has its own storage — see `learnings.md` "M4L `[value <name>]`
  is GLOBAL-by-name across all device instances" for the trap this
  pattern avoids.
- A separate `has_track_id` int flag (plumbed via `[send]` / `[receive]`,
  NOT `[value]`) gates the emitter. If no track_id has been received since
  patch load, frames are held (no placeholder address — empty identities
  would poison the sidecar's ring buffer).
- `track_id` strings are opaque to the patch. `ensure_analyzers_loaded`
  assigns one per analyzer at load time.

## Signature query (via OSC)

`ensure_analyzers_loaded` distinguishes HallucinoteAnalyzer instances from
other Max devices that happen to share a display name.

- Inbound OSC address: `/signature/query <reply_host> <reply_port>` on
  `osc_port`.
- The patch replies via a transient `[udpsend]` (re-configured per-query
  with `host` / `port` messages) to `reply_host:reply_port` with
  `/signature hallucinote-analyzer-v1`.
- The hierarchical query path avoids the OSC `?` pattern-match wildcard
  that would make `/signature?` ambiguous.
- The signature value is a versioned string; future incompatible patch
  revisions surface as `hallucinote-analyzer-v2` etc.

The reply carries no `track_id`; the caller correlates by which inbound
port it queried (one analyzer per port).

## Recording boundaries: transport-position-driven

Recording is bracketed by Live's transport position, not by MCP-latency-
bounded `Arm` toggles. The harness writes `/start_at_beat <int>` and
`/stop_at_beat <int>` before raising `Arm`; the patch handles the rest.
This buys sample-accurate boundaries, tempo-automation immunity, and
structural multi-analyzer alignment (every analyzer observes the same
Live transport).

`Arm` is the gate ("act on transport events"); the beat observer is the
boundary ("which events").

### State machine

- `Arm=0`: ignore all transport events. `sfrecord~` not recording.
- `Arm=1` + transport stopped or before `start_at_beat`: hold.
- `Arm=1` + observer fires "current_beat crossed `start_at_beat`":
  send `1` to `sfrecord~`. Recording active.
- `Arm=1` + recording + observer fires "current_beat crossed
  `stop_at_beat`": send `0` to `sfrecord~`. Recording finalized.
- After stop-beat crossing, the patch returns to `Arm=1 + holding`.
  A subsequent `/path` + `/start_at_beat` + `/stop_at_beat` triple
  re-arms for the next render WITHOUT toggling `Arm`. One Arm cycle
  covers an arbitrary number of beat-windowed captures.
- `Arm` falling edge during active recording: send `0` immediately.

### Crossing detection

The transport-cross detector is wired off `[live.observer]` →
`[t f f]` outlet 1 → `[expr ($f2 < $i3) && ($f1 >= $i3) && ($i4 == 1)]`
where `$f1` is current_beat, `$f2` is prev_beat, `$i3` is target-beat,
`$i4` is `Arm`. `prev_beat` is updated via `[deferlow]` after the expr
evaluates.

`prev_beat` is reset to `-1` on **both** loadbang AND `Arm` rising edge
(`[sel 0 1]` outlet 1 → `[-1.]` → prev_beat `[f]`). The Arm-rising
reset handles the `start_at_beat=0` case under repeated renders — without
it, `prev_beat` stays past 0 from the previous render and the crossing
expr never fires.

### sfrecord~ control

Bare integers to `sfrecord~`'s left inlet: `1` starts, `0` stops AND
finalizes the WAV header. No `close`, no `stop`, no `record N`. (See
`learnings.md` "sfrecord~ control API: bare integers (1 / 0), not
`record N`".)

After `0`, a fresh `open <path>` is required before the next `1`. The
direct `/path` → `prepend open` wiring makes this automatic: the harness
sends `/path` per render, and `sfrecord~` is open the moment the
start-crossing fires.

`sfrecord~` is instantiated `2 @nchans 2`; `samptype float32` is sent at
`[loadbang]` so every subsequent `open` writes float32.

## OSC feature emitter

Each analyzer emits a periodic feature frame to a Python sidecar over UDP.
Frames are emitted whenever Live's audio thread is running — independent
of `Arm` / `sfrecord~` / transport state — so a future always-on
realtime mix-coaching surface sees data even when nothing is being
recorded. `emit_enabled` is the kill switch.

### Wire format

- OSC address: `/hallucinote/track/<track_id>/features`
- Type tag: `,ffff`
- Payload (fixed positional order):
  0. `beat_position` — Live transport beat at the sample moment.
     Float. Source: `[live.observer]` outlet → `[t f f]` outlet 0 →
     `[f beat_pos_latched]`. **Always payload[0], even as features
     are added.**
  1. `lufs_m` — momentary loudness per ITU-R BS.1770-4, K-weighted,
     400 ms integration. LUFS. Silence floor: -120.
  2. `peak_dbfs` — sample-peak (NOT true-peak — true-peak is
     offline-only). dBFS. Silence floor: -120.
  3. `low_mid_power` — RMS power in 200–500 Hz band. dB relative to
     full scale. Silence floor: -120.

**Growth convention:** new features append to the end of the payload.
`beat_position` stays at payload[0]; existing feature ordering is
preserved. Sidecars parse positionally; an older sidecar reading a
newer frame ignores trailing extras. Sidecars discover feature-vector
length via `/signature` reply.

### Emit rate

~30 Hz, driven by `[metro 33]` → `[t b b b b]` (right-to-left fire
order: bang track_id `[value]`, latch beat_position, snapshot LUFS-M,
snapshot low-mid).

### Destination

`127.0.0.1:<osc_emit_port>` via `[udpsend]`. Per-instance Live
parameter, but `ensure_analyzers_loaded` configures every analyzer to
emit to the same port (default 11221), so the sidecar opens one
socket. UDP interleaving is the expected shape; sidecar ring buffers
are keyed by `track_id` from the address.

### Gating

- `emit_enabled=0`: no frames. `[gate]` between `[pack]` and
  `[udpsend]`, controlled by `[live.toggle (Emit)]` outlet directly.
- `track_id` unset: no frames. Second `[gate]` in series, controlled
  by `[receive has_track_id]`. The flag is `0` at loadbang, `1` after
  any `/track_id` arrives. Plumbed via `[send]` / `[receive]` (not
  `[value]`).

### Filter coefficients (48 kHz)

K-weighting (cascaded biquads, BS.1770-4 §2.1.2.1):

```
biquad~ 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585
biquad~ 1.0 -2.0 1.0 -1.99004745483398 0.99007225036621
```

Low-mid bandpass (200 Hz HP + 500 Hz LP, scipy
`signal.butter(2, [200, 500], btype='bandpass', fs=48000)` factored
into separate biquads):

```
biquad~ 0.97803 -1.95606 0.97803 -1.95558 0.95654
biquad~ 0.00102 0.00205 0.00102 -1.95558 0.95968
```

Max `biquad~` arg order: `a0 a1 a2 b1 b2` (feedforward then feedback).

Coefficients are pinned to 48 kHz. `[average~]` window sizes (LUFS-M
19200 samples = 400 ms; low-mid 4800 samples = 100 ms) are SR-adapted
at load via `[adstatus sr]` × 0.4 / × 0.1. Filter coefficient
SR-adaptation is post-MVP backlog.

### Full assembly diagram

```
[receive~ tap_L]   [receive~ tap_R]
       │                  │
       └─── [+~] ── [*~ 0.5] ── [send~ mono]
                                       │
       ┌───────────────────────────────┼─────────────────────────────┐
       │                               │                             │
       ▼                               ▼                             ▼
[receive~ mono]                 [receive~ mono]               [receive~ mono]
       │                               │                             │
       ▼                               ▼                             ▼
[biquad~ HS K-weight]           [peakamp~ 33]                 [biquad~ HP 200]
       │                          (self-clocked)                     │
       ▼                                │                            ▼
[biquad~ HP RLB]                        │                       [biquad~ LP 500]
       │                                │                            │
       ▼                                ▼                            ▼
[*~ self-square]               [clip 1e-6 1.0]                 [*~ self-square]
       │                                │                            │
       ▼                                ▼                            ▼
[average~ <19200> bipolar]    [expr 20·log10($f1)]            [average~ <4800> bipolar]
       │                                │                            │
       ▼                                ▼                            ▼
[snapshot~]                   [send peak_dbfs_value]          [snapshot~]
       │                                                             │
       ▼                                                             ▼
[clip 1e-12 1e10]                                             [clip 1e-12 1e10]
       │                                                             │
       ▼                                                             ▼
[expr 10·log10($f1) - 0.691]                                  [expr 10·log10($f1)]
       │                                                             │
       ▼                                                             ▼
[send lufs_m_value]                                           [send low_mid_power_value]


(live.observer outlet — current_song_time)
                  │
                  ▼
              [t f f]
              ├── outlet 1 (FIRST) → crossing-detection expr chain
              └── outlet 0 (SECOND) → [f beat_pos_latched]
                                              │
                                              │ (banged by metro outlet 1)
                                              ▼

[metro 33] → [t b b b b]
                  │
                  ├── outlet 3 (FIRST)  → bang [snapshot~ low-mid]
                  ├── outlet 2          → bang [snapshot~ LUFS-M]
                  ├── outlet 1          → bang [f beat_pos_latched]
                  └── outlet 0 (LAST)   → bang [message] (track_id storage; per-patcher)
                                              │
                                              ▼
                                        [sprintf /hallucinote/track/%s/features]
                                              │
                                              ▼ (hot — inlet 0)

[f beat_pos_latched] outlet      ────────────────┐
[receive lufs_m_value]           ────────────────┤
[receive peak_dbfs_value]        ────────────────┤
[receive low_mid_power_value]    ────────────────┤
                                                 ▼
                                [pack s f f f f]    ← address into in0 (hot)
                                       │
                                       ▼
                                  [gate]  ← control: [live.toggle Emit]
                                       │
                                       ▼
                                  [gate]  ← control: [receive has_track_id]
                                       │
                                       ▼
                          [udpsend 127.0.0.1 11221]
                                       ▲
                          [prepend port] ← [i] ← [live.numbox (EmitPort)]
```

## Authoring workflow

`.amxd` is a binary container. Hand-editing the JSON portion can produce a
structurally-valid file that nonetheless fails Live's deeper loader
validation (`createdevice error 6`). **All edits go through Max's GUI.**

1. Open the device by clicking **Edit** on a loaded instance in Live.
2. Make changes in Max's patcher view.
3. `Cmd-S` to save. `Cmd-W` to close the patcher window (Live and Max
   fight over `[udpreceive]` when both have the patch open — see
   `learnings.md` "M4L patcher editor and Live runtime fight over
   udpreceive").
4. Copy the saved file from
   `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd`
   back to `hallucinote_mcp/src/hallucinote_mcp/m4l/` and commit.

For step-by-step modification recipes, see
[`PATCH-MODIFICATION-GUIDE.md`](./PATCH-MODIFICATION-GUIDE.md).

For deployment after a source-file update, see the `ableton-mcp-install`
skill.

## Object inventory

Max objects used in the patch:

| Object | Purpose |
|---|---|
| `adstatus sr` | current session sample rate (re-emits on driver change) |
| `average~ <samples> bipolar` | sliding mean of signal |
| `biquad~ a0 a1 a2 b1 b2` | 2-pole filter section |
| `change` | emit only on value change |
| `clip <floor> <ceiling>` | clamp control-rate value to range; space-separated args |
| `deferlow` | push to low-priority queue |
| `expr <expression>` | evaluate arithmetic; narrow function vocabulary (no conditionals, no min/max) |
| `f` | float storage with emit-on-write |
| `gate` | gate a signal/message by control |
| `i` | int truncator / storage with emit-on-write |
| `live.numbox` | Live parameter (numeric) |
| `live.observer` | Live LOM property observer |
| `live.thisdevice` | self-reference (id, sample rate, etc.) |
| `live.toggle` | Live parameter (boolean) |
| `loadbang` | bang on patch load |
| `message <text>` | static or dynamic message |
| `metro 33` | bang every 33 ms |
| `OSC-route /path/literal` | route OSC by address (CNMAT) |
| `pack <typespec>` | pack into list; fires on left/hot inlet only |
| `peakamp~ <interval_ms>` | sample-peak accumulator, self-clocked |
| `plugin~` / `plugout~` | M4L audio in/out |
| `prepend <prefix>` | prepend static prefix to list |
| `print <label>` | log to Max console |
| `receive <name>` | named message receiver |
| `receive~ <name>` | named audio receiver |
| `sel <value>` | bang when input matches |
| `send <name>` | named message broadcaster |
| `send~ <name>` | named audio sender |
| `sfrecord~` | audio file writer |
| `snapshot~` | sample audio signal at control rate |
| `sprintf <format>` | format string with %s/%d |
| `t <typespec>` | trigger (right-to-left fire order) |
| `udpreceive <port>` | UDP message receiver |
| `udpsend <host> <port>` | UDP message sender (single inlet; constructor args required) |
| `value <varname>` | named state cell — read-by-bang only; GLOBAL by name across instances |
