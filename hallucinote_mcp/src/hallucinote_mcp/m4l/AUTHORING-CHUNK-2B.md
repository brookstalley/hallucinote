# HallucinoteAnalyzer.amxd — Chunk 2B authoring guide (Max GUI)

This is the **step-by-step procedure** for extending the Chunk 1 `.amxd`
in Max for Live's GUI to meet the Chunk 2 contract in
`HallucinoteAnalyzer.amxd.spec.md`. The spec is the WHY; this doc is
the HOW.

Read the spec first (or have it open in a second window). It defines
the parameters, OSC routes, behavior contract, and the GO/NO-GO
criteria you're authoring toward.

**Audience:** someone comfortable with Max (you authored Chunk 1).
This guide tells you what to instantiate, what to wire, and which
inspector values to set — not how Max patching works in general.

---

## Pre-flight

### 0.1. Back up the Chunk 1 `.amxd`

```bash
cp ~/Music/Ableton/User\ Library/Presets/Audio\ Effects/Max\ Audio\ Effect/HallucinoteAnalyzer.amxd \
   ~/Music/Ableton/User\ Library/Presets/Audio\ Effects/Max\ Audio\ Effect/HallucinoteAnalyzer.chunk1.bak.amxd
```

The Chunk 1 `.amxd` shipped clean — keep it as a recovery point. If
Max corrupts the file mid-edit (you'll know — Live's load fails with
`createdevice error 6: device file broken`), restore from the backup
and start over.

### 0.2. Open the device in Max

In Live, drop the Chunk 1 `HallucinoteAnalyzer` onto any audio track,
then click the **Edit** button on the device. This opens it in Max
with Live's bundled runtime (NOT standalone Max). Patching view
(`Cmd-E` to toggle) is where you'll work.

### 0.3. Layout planning (eyeball it before you start)

The Chunk 2 additions roughly double the patch's surface area. Before
clicking anything, decide where each region lives. Suggested layout:

```
┌─────────────────────────────────────────────────────────────┐
│ Top:   Live parameters row (Arm, Port, EmitPort, Emit)     │
├─────────────────────────────────────────────────────────────┤
│ Left:  Inbound OSC chain (existing /path + new routes)     │
│ Right: Transport observer + recording trigger              │
├─────────────────────────────────────────────────────────────┤
│ Center: sfrecord~ (unchanged from Chunk 1)                 │
├─────────────────────────────────────────────────────────────┤
│ Bottom: Feature-extraction branch + outbound OSC           │
└─────────────────────────────────────────────────────────────┘
```

Don't fight the layout later — it's easier to grow into empty real
estate than to rearrange working signal flow.

---

## Section A — Widen the existing `Port` range

The Chunk 1 spec said `Port` accepted 11000-11100. Chunk 2's port
allocation policy (see spec §"Port allocation policy") uses up to
11400. Existing `Port` numbox needs widening so `ensure_analyzers_loaded`
can assign return-track ports (11100+) and master (11200) without
clamping.

**Steps:**

1. Click the existing `live.numbox` for `Port` (currently displayed
   in Live's parameter list as "OSC Port").
2. Open Inspector (`Cmd-I`).
3. Change `Range/Enum` from `11000 11100` to `11000 11400`.
4. Leave `Initial Value`, `Type`, `Parameter Visibility`, scripting
   name, long name, short name untouched. Those are correct.

**Verify:** the inspector's "Range" field reads `11000 11400`. Click
elsewhere to commit. Don't save yet — we'll save once at the end
after every section's changes are in.

---

## Section B — Add two new Live parameters

### B.1. `osc_emit_port` (outbound port)

Drag in a new `live.numbox`. Inspector:

| Inspector field | Value |
|---|---|
| Scripting Name | `osc_emit_port` |
| Long Name | `OSC Emit Port` |
| Short Name | `EmitPort` |
| Type | `Int` |
| Range/Enum | `11000 11400` |
| Initial Value | `11001` |
| Initial Enable | `Yes` |
| Parameter Visibility | `Automated and Stored` |
| Parameter Modulation Mode | `None` |

> **Trap (from Chunk 1, see learnings.md):** "Parameter Visibility =
> Stored Only" silently bakes `parameter_invisible: 1` into the patch
> and hides the param from Live's Remote Script API. Use
> **Automated and Stored** even though the inspector label is
> confusing. The Remote Script's `get_parameters` returning an empty
> list (or this parameter missing) is the visible symptom.

### B.2. `emit_enabled` (feature emitter on/off)

Drag in a new `live.toggle`. Inspector:

| Inspector field | Value |
|---|---|
| Scripting Name | `emit_enabled` |
| Long Name | `Emit Features` |
| Short Name | `Emit` |
| Initial Value | `1` |
| Initial Enable | `Yes` |
| Parameter Visibility | `Automated and Stored` |
| Parameter Modulation Mode | `None` |

> **Trap (Chunk 1):** the Remote Script API uses the **Short Name**
> (`Emit`, not `Emit Features`). Make sure the short name is exactly
> `Emit` — `ensure_analyzers_loaded` addresses it that way.

### B.3. Verify the parameter list in Live

Save the patch (`Cmd-S` — in Live's Edit context this updates the
in-Live instance immediately) and check that the Live device view
shows all four parameters: `Record Arm`, `OSC Port`, `OSC Emit Port`,
`Emit Features`. If any are missing, the visibility setting didn't
take — re-check Section B.1 / B.2 step 6.

---

## Section C — Add four new inbound OSC routes

The Chunk 1 `[udpreceive]` already handles `/path`. Chunk 2 adds:

- `/track_id <symbol>` → retained value, used by feature emitter
- `/start_at_beat <int>` → retained value, transport observer reads it
- `/stop_at_beat <int>` → retained value, transport observer reads it
- `/signature?` → reply with `/signature hallucinote-analyzer-v1`

### C.1. Add `/track_id` route

Next to the existing `[OSC-route /path]`, add `[OSC-route /track_id]`.

- Its left outlet (matched messages) → `[t l]` (trigger anything) →
  `[value @triggers 0]` (stores the symbol; `@triggers 0` makes it
  store without firing downstream — feature emitter will pull on demand).
- Give the `[value]` object the name `track_id_retained` via the
  `@varname track_id_retained` attribute. This makes it referenceable
  by other parts of the patch with `[value track_id_retained]`.

> The `[value]` object's *triggers* attribute matters: with `@triggers 1`
> (the default), every received symbol re-fires the outlet, spamming
> downstream listeners every time the Python side re-sends `/track_id`
> at render setup. `@triggers 0` (set-on-write, read-on-bang) is what
> we want — track_id should only fan out when the emitter pulls it.

### C.2. Add `/start_at_beat` and `/stop_at_beat` routes

Two more `[OSC-route]` objects, identical shape to C.1 but:

| Route | varname for the `[value]` retainer |
|---|---|
| `/start_at_beat` | `start_at_beat` |
| `/stop_at_beat` | `stop_at_beat` |

Both retainers also use `@triggers 0` — the transport-position
observer will read them, it shouldn't fire when they change.

Type coercion: OSC ints arrive as `int` in Max, but if the harness ever
sends them as floats (off-by-one of the OSC type tag), the comparison
in the observer breaks. Put `[i]` (the int truncator) between the
route's outlet and the `[value]` to coerce defensively.

### C.3. Add `/signature?` query/reply

This is the only Chunk 2 OSC route that REPLIES rather than retains.

- Add `[OSC-route /signature]` (note the trailing `?` is part of the
  match — use `[OSC-route /signature?]`).
- Its outlet → `[t b]` (trigger bang on any incoming message) →
  `[prepend /signature]` → `[append hallucinote-analyzer-v1]` (or use
  a single `[message /signature hallucinote-analyzer-v1]` triggered by
  the bang).
- The reply goes to `[udpsend]` — but to WHICH host:port? The sender's.
  `[udpreceive]`'s **right outlet** emits the source `host port` of
  the most recent incoming packet. Wire that right outlet into
  `[unpack s i]` → `[pak host port]` → `[udpsend]`'s right inlet
  (the `host port` configuration inlet), then send the
  `/signature hallucinote-analyzer-v1` message into `[udpsend]`'s
  left inlet.

> **Order of operations matters.** The reply destination
> (`host port`) MUST be configured on `[udpsend]` BEFORE the message
> arrives at its left inlet, or it sends to the previous (or empty)
> destination. Use `[t l b]` (trigger list-then-bang) so the host/port
> packing fires before the reply message.

> **Why an OSC query and not a Live parameter?** See spec §"Signature
> surface" — short answer: strings can't be Live parameters, the
> filename-inference approach is brittle, and an enum parameter
> pollutes the device's surface.

---

## Section D — Transport-position observer

The patch needs to read Live's current song-time at the audio
scheduler's rate so it can fire `sfrecord~` start/stop when transport
crosses requested beats.

### D.1. Instantiate the observer

Drag in `[live.observer]`. Inspector / object box:

- `@property` → `song_time` (some Live versions call this attribute
  differently; if `song_time` doesn't observe, try `current_song_time`)
- `@path` → `live_set` (the song-level path)

### D.2. Convert song_time to beats

`song_time` is in beats already in Live 12. Wire its outlet to
`[unpack 0.]` to strip the `time` symbol prefix if your version of
Max emits it as a list, otherwise direct.

### D.3. Cross-detection logic

The observer fires on EVERY change (audio scheduler rate). Build a
small change-detection state machine:

```
[live.observer @property song_time]
        │
        ▼
   [unpack 0.]                    (current_beat, as float)
        │
        ├──> [pak current 0. start 0. stop 0.]
        │                ▲                ▲
        │                │                │
        │       [value start_at_beat]  [value stop_at_beat]
        │             (bang every observer tick to read latest)
        │
        ▼
   [route current start stop]
   (route by the symbol prefix you packed)
```

Honestly, the simplest shape is a JavaScript object (`[js]`) that
holds the prior beat as state and emits messages on threshold
crossings — Max's pure-message scheduling makes the state machine
verbose otherwise. If you prefer to stay pure-Max:

```
prior_beat = [value prior_beat @triggers 0]
              (initialize to -1 at [loadbang])

on every observer tick:
  if Arm == 1
     and prior_beat < start_at_beat
     and current_beat >= start_at_beat:
        → fire start-recording chain
  if Arm == 1
     and prior_beat < stop_at_beat
     and current_beat >= stop_at_beat:
        → fire stop-recording chain
  prior_beat := current_beat
```

Express the inequality checks with `[<]` and `[>=]` Max objects + an
`[&&]` (logical and). Each comparison's result feeds a `[sel 1]` or
`[gate]` to fire its respective trigger only on the true→true edge.

### D.4. Connect to the existing Arm gate

The `[live.toggle]` for `Arm` already exists. Tap its parameter value
(via `[live.observer @property value @path Arm]` OR by routing the
toggle's output through a `[live.thisdevice]`-rooted path). Use it to
GATE the start/stop fire chains:

```
start-crossing-detected ──> [gate]
                              ↑
                          Arm value (0 or 1)
                              │
                              ▼
                       open <path> + 1 → sfrecord~
```

When `Arm == 0`, the gate blocks; transport crossings have no effect.
This is the "Arm-as-gate, observer-as-boundary" model from the spec.

---

## Section E — Rewire the recording trigger

Chunk 1's patch fired `open <path>` + `1` on the **rising edge of
the Arm parameter**. Chunk 2 fires it on the **transport-position
crossing while armed**. This means: disconnect the existing Arm rising-
edge handler from the open+start chain, and connect the observer's
start-crossing-detected output instead.

### E.1. Find and disconnect the old Arm rising-edge chain

In Chunk 1, the chain was approximately:

```
Arm (live.toggle) → [sel 1] (true on rising edge)
                  → [t b b] (right-then-left)
                  → right: [value path_retained] → [prepend open] → sfrecord~
                  → left:  [1( → sfrecord~
```

Delete the cable from `[sel 1]` to `[t b b]`. Leave the rest of the
chain in place — we'll feed `[t b b]` from the new source.

### E.2. Connect the observer's start-crossing to `[t b b]`

The "start-crossing-detected" bang you built in Section D.3, gated by
Arm in Section D.4 — wire it into the `[t b b]` that was the rising-
edge handler's downstream. The open + 1 sequence now fires at the
transport-position boundary.

### E.3. Stop-crossing → `[0]` → sfrecord~

Similarly, Chunk 1's falling-edge handler sent `0` to `sfrecord~`.
Wire BOTH:
- Falling edge of Arm (the "user pulled the cord" path)
- AND the stop-crossing-detected output from Section D.3

…into a `[trigger 0]` (or `[message 0]`) → `sfrecord~` left inlet.
Either source stops the recording.

### E.4. Verify pre-arm guard still works

The Chunk 1 rising-edge handler had a guard: if no `/path` had been
received since patch load, refuse to arm and `[print]` the error.
Make sure the start-crossing handler in E.2 has the SAME guard —
check `[value path_retained]` is non-empty before firing `open`.
Without this, the patch silently records to whatever stale path it
last had.

---

## Section F — Feature-extraction branch

This is the heaviest section. The audio inlet is tapped (not
intercepted) and feeds three parallel extractors. Their outputs are
packed into a 3-float OSC frame and sent at ~30 Hz to the sidecar.

### F.1. Tap the audio inlet

Use `[receive~ inlet_audio]` if the audio inlet is exposed by name,
or a `[send~ tap_audio]` upstream + `[receive~ tap_audio]` here.
**The tap must NOT add latency** (PDC alignment with the master
analyzer depends on this — see spec §"Inlets / outlets").

### F.2. LUFS-M (K-weighted, 400 ms momentary)

K-weighting is ITU-R BS.1770-4: a high-shelf (+4 dB above ~1500 Hz)
followed by a high-pass (~38 Hz, -3 dB).

**Stage 1 — High-shelf biquad** (at 48 kHz; see SR note below):
```
[biquad~ 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585]
```

**Stage 2 — High-pass biquad** (at 48 kHz):
```
[biquad~ 1.0 -2.0 1.0 -1.99004745483398 0.99007225036621]
```

Chain Stage 1 → Stage 2 (signal flow), then:

**Mean square over 400 ms** (the "momentary" integration window):
```
filtered → [*~] (square: connect to its own second inlet for x²)
         → [avg~ @sr-relative 1] over 400 ms window
```

If `[avg~]` isn't available in your Max version, build the window
from `[delay~ 19200]` (400 ms at 48 kHz) + a running sum. Easier: use
`[poly~]` with a small avg patcher.

**Convert to LUFS:**
```
mean_square → [log10~] → [*~ 10.] → [+~ -0.691]
```

The `-0.691` is the BS.1770 absolute scale offset (so a -23 LUFS
pink-noise reference reads exactly -23.0 after K-weighting and
integration).

**Snapshot at emit rate:** `[snapshot~]` driven by the `[metro]`
in F.5 will sample this at 30 Hz. Don't snapshot in the audio thread.

> **SR note (deferred to post-MVP).** The biquad coefficients above
> are computed for 48 kHz. At 44.1 kHz the K-weighting filter
> characteristic shifts slightly (the +4 dB shelf turnover lands ~7%
> higher, the -3 dB HP corner lands ~7% higher). LUFS-M reads ~0.2-0.4
> LU low at 44.1 kHz vs. Live's meter. For MVP this is acceptable
> noise — Hallucinote's MixReport doesn't gate on sub-LU precision.
> A future enhancement runs the coefficient math at `[loadbang]`
> from `[samplerate~]`. **Document the assumption in your patch with
> a `[comment]` block** so the next Chunk-3 author knows the
> precondition.

### F.3. Sample peak

```
tap_audio → [peakamp~] → [snapshot~] (at the metro rate)
         → [log10~] → [*~ 20.]
```

The `[peakamp~]` object holds the peak between snapshots and resets
on read — exactly the "peak between emit frames" semantics we want.
Output is dBFS (negative for non-clipping signal).

### F.4. Low-mid (200-500 Hz) band power

Cascade two `[biquad~]` (2-pole HP at 200 Hz, 2-pole LP at 500 Hz).
At 12 dB/oct each you get a comfortable band-pass with -6 dB at the
edges; the MVP doesn't need sharp skirts.

Coefficients (48 kHz, Butterworth):
```
HP 200 Hz:  [biquad~ 0.97803 -1.95606 0.97803 -1.95558 0.95654]
LP 500 Hz:  [biquad~ 0.00102 0.00205 0.00102 -1.95558 0.95968]
```

(These are approximations — fine-tune with `[filtergraph~]` if you
care. The MVP only uses this band-power value in Chunk 3's master-bus
contribution attribution; relative comparisons across stems matter
more than absolute calibration.)

Then:
```
bandpassed → [*~] (self-multiply: x²)
           → [avg~ over 100 ms]
           → [snapshot~] (at metro rate)
           → [log10~] → [*~ 10.]
```

Output is dB relative to full scale.

### F.5. Pack + emit at 30 Hz

```
[metro 33]                              ← every 33 ms = ~30 Hz
   │
   ├──> bang [snapshot~] for LUFS-M     ─┐
   ├──> bang [snapshot~] for peak       ─┤
   ├──> bang [snapshot~] for low-mid    ─┤
   └──> bang [value track_id_retained]  ─┤
                                         │
                  ┌──────────────────────┘
                  ▼
        [pak f f f]   (LUFS-M, peak, low-mid)
                  │
                  ▼
        [prepend address]
                  ▲
                  │   address built dynamically:
                  │   track_id → [sprintf /hallucinote/track/%s/features] → set $1
                  │
                  ▼
        [gate] ────── gated by `Emit` Live parameter (0 = mute)
        and also by track_id non-empty check
                  │
                  ▼
        [udpsend 127.0.0.1 <osc_emit_port>]
                  ▲
                  │
        EmitPort change → [pak host port] → right inlet (re-bind destination)
```

The `[metro]` should be turned ON at `[loadbang]` so feature emission
starts as soon as Live's audio engine runs. The `Emit` gate lets users
disable the emitter without affecting recording.

### F.6. Gate frames when track_id isn't set

If `track_id_retained` is empty (string `""`) the address would be
`/hallucinote/track//features` — malformed. The sidecar's parser
rejects empty track_ids, so frames would silently drop, but it's
cleaner to gate on the patch side.

```
[value track_id_retained] → [length] → [> 0] → [gate]'s control inlet
```

(Or use a `[route]` that drops the empty case.)

---

## Section G — Sanity test inside Max (before saving)

You can verify a lot from the Max console before involving Live's
Remote Script or the MCP server.

### G.1. Open the Max console

`View > Open Max Console` (`Cmd-M`).

### G.2. Probe the parameter list

Drag in `[live.thisdevice]`. Click its outlet to bang. The console
prints the device's parameter list — confirm all four short names
appear: `Arm`, `Port`, `EmitPort`, `Emit`.

### G.3. Test inbound OSC

Open Terminal:
```bash
echo "Try sending OSC manually if you want — easiest is via Python:"
python3 -c "
import socket, struct
def osc(addr, *args):
    def s(x): r = x.encode() + b'\x00'; return r + b'\x00' * ((-len(r)) % 4)
    def i(x): return struct.pack('>i', x)
    types = ',' + ''.join('s' if isinstance(a,str) else 'i' for a in args)
    body = b''.join(s(a) if isinstance(a,str) else i(a) for a in args)
    return s(addr) + s(types) + body
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11000))
sock.sendto(osc('/start_at_beat', 0), ('127.0.0.1', 11000))
sock.sendto(osc('/stop_at_beat', 16), ('127.0.0.1', 11000))
"
```

Add `[print track_id_in]` / `[print start_beat_in]` / `[print stop_beat_in]`
hanging off each route's outlet temporarily. The Max console should
show each value as it arrives. Remove the `[print]` objects before
saving.

### G.4. Test the signature reply

After sending `/signature?`, the patch should reply on the source
port. Run a UDP receiver on whatever port you sent FROM (the OS picks
a random source port unless you bind one) — easier to bind a known
port:

```python
import socket
listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
listen.bind(('127.0.0.1', 12345))
listen.settimeout(2.0)
send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Send /signature? from port 12345 (use the listen socket to send so
# the source port matches what we're listening on)
listen.sendto(<osc bytes for /signature?>, ('127.0.0.1', 11000))
print(listen.recvfrom(4096))  # should print /signature hallucinote-analyzer-v1
```

### G.5. Test the feature emitter

Run the sidecar's listen port (default 11001):
```python
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('127.0.0.1', 11001))
s.settimeout(2.0)
for _ in range(5):
    print(s.recvfrom(4096))
```

Play audio through the track Live's running the analyzer on. You
should see five OSC frames printed, each starting with
`/hallucinote/track/test:1/features` followed by three floats.

If you see no frames: check `Emit` is set to 1, `track_id` was sent
(test G.3), and the `[metro 33]` is running (`[loadbang]` should
have started it).

### G.6. Test the transport-position observer (the trickiest one)

This requires running Live's transport, since `[live.observer]`
won't fire without the song clock advancing.

1. Set Arm = 0 in Live's device view.
2. Send `/path /tmp/test_chunk2b.wav`, `/track_id test:1`,
   `/start_at_beat 8`, `/stop_at_beat 24` via OSC.
3. Set Arm = 1.
4. In Live, position playhead at bar 1 (beat 0) and press space.
5. The patch should NOT start writing until transport reaches beat 8
   (bar 3 in 4/4). Add `[print obs_state]` on the observer's outlet
   temporarily to watch its ticks scroll past.
6. At beat 8: `sfrecord~` should open `/tmp/test_chunk2b.wav` and
   start writing.
7. At beat 24: `sfrecord~` should stop (send 0). Console should
   show no further activity.
8. Set Arm = 0.

Inspect the WAV:
```bash
python3 -c "
import soundfile as sf
f = sf.SoundFile('/tmp/test_chunk2b.wav')
print(f'frames={len(f)}, sr={f.samplerate}, ch={f.channels}, subtype={f.subtype}')
"
```

At 120 BPM, 16 beats = 8 seconds = 384,000 frames at 48 kHz. Tolerance:
±1 audio buffer (typically 512 samples).

---

## Section H — Save + copy back to source tree

### H.1. Save the patch

`Cmd-S` in Max. Live receives the updated patch immediately.

### H.2. Verify in Live

Reload the device in Live (drag it off, drop a fresh one on, or
restart Live). All four parameters visible? Set Arm = 1 with a
preceding `/path` + `/track_id` + start/stop beats sent via OSC —
does recording happen at the expected beats? If yes → continue.

### H.3. Copy the `.amxd` back into the package source tree

The User Library is the authoritative location for Max; the package
source needs an identical copy for `pip install` to ship it via
`pyproject.toml`'s `package-data`.

```bash
cp ~/Music/Ableton/User\ Library/Presets/Audio\ Effects/Max\ Audio\ Effect/HallucinoteAnalyzer.amxd \
   ~/source/hallucinote/hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd
```

(Adjust paths if your checkout is elsewhere.)

### H.4. Stage + commit

```bash
cd ~/source/hallucinote
git add hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd
git status  # should show only the .amxd as modified
```

Don't commit yet — wait for the full Section I verification to pass.

---

## Section I — In-Live end-to-end verification (Chunk 2 GO/NO-GO)

The spec's GO/NO-GO criteria are at the bottom of
`HallucinoteAnalyzer.amxd.spec.md`. Quick checklist:

1. **Install with the updated MCP:** run `/ableton-mcp-install`. Step
   3d should detect the new `.amxd` and copy it. (If Live's running,
   the skill will refuse — quit Live first.)
2. **Open a multi-track Hallucinote song** with at least one return
   (e.g., `falling-walking`).
3. **Restart Claude Code** (`/mcp` reconnect respawns the server with
   the new `ableton_render` action registered).
4. **Run `ableton_render(action='ensure_loaded')`** — should report
   `loaded_count: N+R+1, existing_count: 0` on first call,
   `loaded_count: 0, existing_count: N+R+1` on second call.
5. **Run `ableton_render(action='render', song_slug='<slug>')`** —
   should produce `songs/<slug>/captures/<ts>/` with one WAV per
   surface + `manifest.json`.
6. **Verify GO criteria** (spec §"GO criteria (Chunk 2 scope)"):
   - Every WAV is FLOAT/stereo/Live's SR with audio content above -60 dBFS
   - WAV duration matches arrangement length ± one audio buffer (no
     MCP-latency padding around the content — the transport-position-sync win)
   - Cross-correlate any track WAV vs master WAV; lag ≤ 64 samples
     (PDC alignment)
   - Sidecar received ≥ 1 frame per analyzer (visible in
     `manifest.json`'s `frames_received` field)
   - Two consecutive renders produce two independent captures dirs

If any of these fail, the patch needs adjustment — restart from the
relevant section above. The spec's NO-GO criteria list common causes
for each failure mode.

---

## Section J — Close-out

After the in-Live verification passes:

1. Commit the `.amxd`:
   ```
   git commit -m "chunk 2 of 2 (audio-analysis MVP, Chunk 2): in-Live close-out + .amxd"
   ```
2. Update `.prawduct/.test-evidence.json` with the in-Live results
   (frame counts, render duration, alignment lag).
3. Append a reflection to `.prawduct/.session-reflected` — same
   pattern as Chunk 1's close-out, document any traps that surfaced.
4. Update `.prawduct/artifacts/build-plan.md`'s Status section — mark
   Chunk 2 `[x]`.
5. Add a `chunks=2 | status=shipped | release=unreleased | scope=audio-analysis-mvp`
   change-log entry.
6. Run `/critic chunk` for the cumulative Chunk 2 review.
7. The branch is now ready for `/pr` if/when you want to merge.

---

## Common traps (from Chunk 1's experience)

If something doesn't work in Max, check these first — Chunk 1 hit
each of them, and they're now durable rules in `learnings.md`:

| Symptom | Likely cause | Fix |
|---|---|---|
| Remote Script API can't see a parameter | `Parameter Visibility = Stored Only` (silently sets `parameter_invisible:1`) | Set to `Automated and Stored` |
| `set_parameter(name='Record Arm')` says unknown parameter | API uses short name | Use `Arm` |
| `set_parameter(name='OSC Emit Port')` says unknown | API uses short name | Use `EmitPort` |
| WAV has 44 frames (~1 ms) | Used `record 1` instead of `1` | Use bare integer `1` to start, `0` to stop |
| `sfrecord~` ignores `close` / `stop` messages | They aren't part of the documented API | Use `0` to stop AND finalize |
| `sfrecord~` says "start requested without preceding 'open'" | `1` arrived before `open <path>` | Use `[t b b]` right-then-left so `open`'s chain fires first |
| Live rejects the device with `createdevice error 6` | You hand-edited the JSON inside the `.amxd` binary | Restore the backup; only ever save via Max GUI |
| OSC sender receives no reply for `/signature?` | `[udpsend]` destination wasn't configured before the message | `[t l b]` to set host:port FIRST, then fire reply |
| Feature emitter sends frames with empty track_id | No `/track_id` received yet | Gate emission on `[value track_id_retained]` length > 0 |
| Recording window starts/stops at wrong beats | `[live.observer]` observed wrong property | Try `current_song_time` if `song_time` doesn't fire |

If you hit a NEW trap that isn't in this list, capture it in
`.prawduct/learnings.md` during close-out — future M4L authoring
work will benefit.
