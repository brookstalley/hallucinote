# HallucinoteAnalyzer.amxd — Chunk 2B authoring guide (Max patch-level detail)

This is the **patch-level recipe** for extending the Chunk 1 `.amxd`
to meet the Chunk 2 contract in
[`HallucinoteAnalyzer.amxd.spec.md`](./HallucinoteAnalyzer.amxd.spec.md).
The spec is the WHY; this doc is the HOW, down to which objects to
instantiate, what `@attributes` to set, and which outlet of object A
connects to which inlet of object B.

**Audience:** someone comfortable with Max (you authored Chunk 1).
This guide is exhaustive on the new patch surface — paste object-box
text verbatim where shown, follow the patchcord arrows, set the
Inspector values listed in tables.

---

## Conventions

- `[object @attr value]` — what you type into a new Max object box.
  Hit Tab to confirm. Some Inspector-only attributes are noted
  separately.
- `outlet N` is 0-indexed left-to-right. So a `[t b b]` has `outlet 0`
  (left) and `outlet 1` (right). Max's trigger objects fire
  right-to-left, so `outlet 1` fires *before* `outlet 0`.
- `inlet N` is 0-indexed left-to-right. Inlet 0 is the "hot" inlet
  on most objects (causes evaluation); others are "cold" (just
  latch values for later).
- Symbols: a Max "symbol" is an interned string. OSC string args
  arrive as symbols.
- Per the spec, the Chunk 1 patch uses CNMAT's `[OSC-route]` (the
  CNMAT OSC package, available via Max's Package Manager). All
  Chunk 2 OSC routes use the same family. Don't mix with vanilla
  `[route]` — pattern semantics differ.

---

## Section 0 — Pre-flight

### 0.1. Back up the Chunk 1 `.amxd`

```bash
cp "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd" \
   "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.chunk1.bak.amxd"
```

If Max corrupts the file mid-edit (symptom: Live's load fails with
`createdevice error 6: device file broken` after a save), restore
from the backup and start over. Don't try to recover the corrupted
file — the binary container's chunk sizes get out of sync in ways
that look valid to parsers but fail Max's deeper validation.

### 0.2. Open in Max via Live's Edit button

In Live, drop the existing `HallucinoteAnalyzer` onto any audio track,
then click the **Edit** button on the device strip. This opens the
patch inside Max with Live's bundled runtime — NOT standalone Max. Use
`Cmd-E` (macOS) / `Ctrl-E` (Windows) to toggle Patching/Presentation
mode. Stay in Patching mode for everything in this guide.

### 0.3. Verify CNMAT OSC package is loaded

Drop a fresh `[OSC-route /foo]` box in an empty area. If the object
box shows in red (= unresolved), the CNMAT OSC package isn't
installed. Open Max's Package Manager (`File > Show Package Manager`),
search "CNMAT OSC", install, restart Max. Delete the test object.

### 0.4. Visual layout planning

The Chunk 2 surface roughly doubles the patch's area. Suggested
regions (delete each region's `[comment]` after authoring; they're
just guides):

```
[comment Live params (top row)]
[comment Inbound OSC routes (left column)]
[comment Transport observer + state machine (right-center)]
[comment sfrecord~ recording chain (center, unchanged from Chunk 1)]
[comment Feature extraction (bottom)]
[comment Outbound OSC emitter (bottom-right)]
```

---

## Section A — Widen the existing `Port` range (and change its Type)

The Chunk 1 `Port` is `Type = Int` with Range `11000 11100`. Chunk 2
needs Range `11000 11400` — but Live's Int parameter automation
encoding is a single byte, so `max - min > 255` silently clamps in
Max's Inspector (you'll see Range reset to `11000 11255` if you try
to set 11400 with Type = Int).

Per Max's documentation: "When working with Live UI objects whose
integer values will exceed this range, the Type attribute should be
set to Float, and the Unit Style attribute should be set to Int."
Type = Float removes the 256-step cap; Unit Style = Int makes the UI
still render whole numbers.

### A.1. Locate the `Port` `live.numbox`

It's the Chunk 1 parameter with Short Name `Port`. Find it and click
once to select.

### A.2. Inspector: change Type and widen the range

Open Inspector (`Cmd-I`). Change:

| Attribute | Before (Chunk 1) | After (Chunk 2) |
|---|---|---|
| Type | `Int` | `Float` |
| Unit Style | (any) | `Int` |
| Range | `11000 11100` | `11000 11400` |

Order matters: set Type to Float FIRST. If you try to widen the range
while Type is still Int, Max will clamp to 11255. With Float type,
the range accepts the full 11000-11400 span. Then set Unit Style to
Int so the UI renders integers despite the Float storage.

For reference, the existing `Port` box's attribute string should end
up looking like this (you're MODIFYING the Chunk 1 box, not adding a
new one — adding a new box would create a duplicate parameter that
Live renames to `OSC Port[1]` / `Port[1]`):

```
live.numbox @parameter_enable 1 @parameter_longname "OSC Port" @parameter_shortname Port @_parameter_range 11000. 11400. @_parameter_initial 11000. @_parameter_unitstyle 5
```

(`@_parameter_unitstyle 5` is "Int" — see the Max docs for the full
Unit Style enum. If `5` doesn't take, set via the Inspector pulldown.)

### A.3. Verify

Live's parameter list still shows "OSC Port" with the same long/short
name. The slider's range now goes to 11400, and the displayed value
is a whole number even though the underlying Type is Float.

---

## Section B — Add two new Live parameters

### B.1. `osc_emit_port` (outbound port — Live param `EmitPort`)

Drag in a new object box, type:

```
live.numbox @_parameter_range 11000. 11400. @_parameter_initial 11201. @parameter_enable 1 @parameter_longname "OSC Emit Port" @parameter_shortname EmitPort @parameter_modulation_mode 0
```

Then open Inspector and confirm these (some are not reliably
settable via box-text @attributes — use Inspector):

| Attribute | Value | Notes |
|---|---|---|
| Scripting Name | `osc_emit_port` | Inspector pane > "Scripting Name" |
| Type | `Float` | **CRITICAL** — see Section A's "why Float+Int" rationale; Int caps the range at 256 steps |
| Unit Style | `Int` | Renders the float as a whole number in the UI |
| Parameter Visibility | `Automated and Stored` | **CRITICAL** — `Stored Only` hides it from Remote Script API |
| Initial Enable | `Yes` | so the stored initial value loads on patch open |
| Modulation Mode | `None` | "Modulation Mode" pulldown |

> **Trap (Chunk 1 learning):** Parameter Visibility = "Stored Only"
> silently bakes `parameter_invisible: 1` into the patch JSON. Live's
> Remote Script API will NOT return the parameter from
> `get_parameters` — `ensure_analyzers_loaded`'s `set_parameter_handler`
> call raises ValueError. Use "Automated and Stored" even though the
> name is confusing.

### B.2. `emit_enabled` (Live param `Emit`)

Drag in a new object box, type:

```
live.toggle @parameter_enable 1 @parameter_longname "Emit Features" @parameter_shortname Emit @parameter_initial 1
```

Inspector confirmations:

| Attribute | Value |
|---|---|
| Scripting Name | `emit_enabled` |
| Parameter Visibility | `Automated and Stored` |
| Modulation Mode | `None` |

### B.3. Verify the parameter surface in Live

Save (`Cmd-S`) — Live updates the in-Live device immediately. Open
the device's parameter list in Live (right-click the device strip in
the chain, or use the Configure mode). All four parameters must
appear:

```
Record Arm    (toggle, 0/1)
OSC Port      (float-as-int, 11000-11400)
OSC Emit Port (float-as-int, 11000-11400)
Emit Features (toggle, 0/1)
```

If a parameter is missing, its Visibility is still wrong — re-check
Inspector.

Test from Python that the Remote Script API surfaces all four short
names:

```python
from hallucinote_mcp.client import send
from hallucinote_mcp.wire import Request
r = send(Request(tool="ableton_device", action="get_parameters",
                 params={"track_index": 1, "device_index": 1}))
print({p["name"] for p in r.result["parameters"]})
# Should include {"Arm", "Port", "EmitPort", "Emit"}
```

(Run this with Live open + the analyzer loaded on track 1.)

---

## Section C — Inbound OSC routes

The Chunk 1 patch already has:

```
[udpreceive 11000]
    │ (single outlet — matched OSC messages from any client; no
    │  sender-metadata sidechannel)
    └──> [OSC-route /path]  ──[outlet 0]──> [prepend open] ──> [sfrecord~]
                                                            + retain via [value hallucinote_path]
```

> Vanilla Max's `[udpreceive]` exposes ONE outlet — the OSC messages.
> It does NOT have a right outlet emitting sender host:port. The
> signature reply path (C.3 below) therefore takes the reply
> destination as explicit OSC args in the query message rather than
> extracting it from socket-level metadata.

You'll add three more inbound routes plus a query/reply path.

### C.1. `/track_id <symbol>` — retained track identity

Build this chain to the left of (or below) the existing `[OSC-route /path]`:

```
[OSC-route /track_id]
        │ outlet 0 (matched symbol)
        ▼
   [value track_id_retained]            ← stores the symbol; emits on read
        │
        (no downstream — the feature emitter pulls via [value track_id_retained] elsewhere)
```

The `[value]` object's box text:

```
value track_id_retained
```

It implicitly has `@triggers 1` by default — on EVERY incoming symbol
write, it emits the symbol downstream. That's the behavior we want
here: when the harness re-sends `/track_id` before a render, the
feature emitter's `[sprintf]` (Section F.5) rebuilds the destination
address with the new id.

**Connect:** `[OSC-route /track_id]` outlet 0 → `[value track_id_retained]` inlet 0.

> **Note on initialization.** At patch load, `[value track_id_retained]`
> is empty (symbol `<empty>`). The feature emitter (Section F.6)
> gates on non-empty so frames don't go out with `/hallucinote/track//features`.

### C.2. `/start_at_beat <int>` and `/stop_at_beat <int>`

Two more routes, identical shape, defensive int coercion:

```
[OSC-route /start_at_beat]            [OSC-route /stop_at_beat]
        │ outlet 0                            │ outlet 0
        ▼                                     ▼
       [i]                                   [i]                  ← int coercion (defensive)
        │                                     │
        ▼                                     ▼
[value start_at_beat]                  [value stop_at_beat]
```

Box text for the retainers:

```
value start_at_beat
value stop_at_beat
```

Default `@triggers 1` — the state machine in Section D needs to know
when these change so it can re-evaluate (e.g., the harness updates
the window between renders).

**Connect:**
- `[OSC-route /start_at_beat]` outlet 0 → `[i]` inlet 0 → `[value start_at_beat]` inlet 0
- `[OSC-route /stop_at_beat]` outlet 0 → `[i]` inlet 0 → `[value stop_at_beat]` inlet 0

> **Why `[i]`?** OSC type tags should arrive as `,i` (int). But if a
> client mistakenly sends `,f` (float, e.g., `64.0`), it'd arrive as
> a float and our comparisons in the state machine would still work
> mathematically but `change` detection breaks (a re-sent 64 becomes
> 64.0 which differs from 64). `[i]` truncates defensively.

### C.3. `/signature/query <reply_host> <reply_port>` → signature reply

This route REPLIES rather than retains, and the reply destination is
carried in the query's OSC args (the client tells the patch where to
send the reply). The wire shape:

- Query in: address `/signature/query`, type tag `,si`, args `<reply_host:symbol> <reply_port:int>`
- Reply out: address `/signature`, type tag `,s`, args `<"hallucinote-analyzer-v1":symbol>`, sent to `<reply_host>:<reply_port>`

> **Why explicit reply args, not socket-level sender info?** Vanilla
> Max's `[udpreceive]` exposes one outlet — the OSC messages. There's
> no documented sender-host:port sidechannel. Putting the reply
> destination in the OSC payload removes the dependency on Max-object
> internals and makes the contract auditable from the wire.

> **Single-inlet udpsend model.** Max's `[udpsend]` has ONE inlet,
> not two. Destination is retargeted by sending `host <symbol>` or
> `port <int>` MESSAGES to the same inlet (interpreted as config
> based on the message's first symbol). Any message that doesn't
> match `host ...` or `port ...` is sent as data. This mirrors
> `[udpreceive]`'s single-port convention (Chunk 1 already uses
> `prepend port` → `[udpreceive]` to change the listen port the
> same way). The signature-reply chain therefore sends three
> messages to the same `[udpsend]` inlet in order: `host <sym>`,
> `port <int>`, then the reply.

#### C.3.a. The route + unpack args + build config messages

```
[OSC-route /signature/query]
        │ outlet 0 (matched: list <reply_host> <reply_port>)
        ▼
   [unpack s i]
   ├── outlet 0 (host symbol)  →  [prepend host]  →  (to [udpsend] inlet 0)
   └── outlet 1 (port int)     →  [prepend port]  →  (to [udpsend] inlet 0)
```

Box text:
- `unpack s i`
- `prepend host`
- `prepend port`

`[prepend host]` takes the symbol on its inlet and prepends the
literal symbol `host`, emitting a list like `host 127.0.0.1`.
`[prepend port]` does the same with the literal `port`, emitting
`port 12345`. Both lists go to `[udpsend]`'s sole inlet.

#### C.3.b. Fire destination-then-reply via `[t b l]`

The unpack fires its outlets right-to-left (port first, then host),
so the two destination messages reach `[udpsend]` in order. We need
the reply message to fire LAST, after both config messages land. Use
`[t b l]` upstream of the unpack to gate the reply-bang behind the
list-cascade:

```
[OSC-route /signature/query]
        │ outlet 0 (list: <host_symbol> <port_int>)
        ▼
   [t b l]
   ├── outlet 1 (RIGHT, fires FIRST: the list)
   │      ▼
   │   [unpack s i]
   │      ├── outlet 0 (host symbol) → [prepend host] → [udpsend 127.0.0.1 0] inlet 0
   │      └── outlet 1 (port int)    → [prepend port] → [udpsend 127.0.0.1 0] inlet 0
   │
   └── outlet 0 (LEFT, fires SECOND: bang)
          ▼
       [message /signature hallucinote-analyzer-v1]
          ▼
       [udpsend 127.0.0.1 0] inlet 0
```

Order of operation at `[udpsend]`'s inlet:

1. `[t b l]` outlet 1 fires → unpack's right outlet (port int) fires
   → `[prepend port]` emits `port 12345` → `[udpsend]` retargets port.
2. unpack's left outlet (host symbol) fires →
   `[prepend host]` emits `host 127.0.0.1` → `[udpsend]` retargets host.
3. `[t b l]` outlet 0 fires → `[message ...]` emits the reply →
   `[udpsend]` sends to the now-correctly-configured destination.

This works because Max scheduling runs each outlet's downstream
cascade to completion before the next outlet of `[t]` fires. No
`[deferlow]` needed.

Box text:
- `t b l`  (`b` = bang on outlet 0 / LEFT, `l` = list on outlet 1 / RIGHT;
  Max fires right-to-left so the list path fires FIRST, the bang fires SECOND
  — exactly the destination-then-reply order we need)
- `message /signature hallucinote-analyzer-v1` — a `[message]` object whose
  contents are the literal text `/signature hallucinote-analyzer-v1`
  (Max parses this on emit into a list `<symbol /signature> <symbol hallucinote-analyzer-v1>`,
  which `[udpsend]` interprets as a `,ss`-typed OSC message — fine for our
  one-string-arg reply since clients parse the address from element 0
  and the args from the rest).

> **Reply-address type tag.** Some OSC clients are strict about
> address syntax in the FIRST list element. Max emits the leading
> `/signature` as a symbol, which `[udpsend]` packs as the OSC
> address. The second element `hallucinote-analyzer-v1` becomes the
> `,s`-typed arg. Sidecar/client parsers tested against this shape
> pass — the Section G.3 Python test confirms.

#### C.3.c. The `[udpsend]` for signature replies

Box text:

```
udpsend 127.0.0.1 0
```

The `127.0.0.1 0` constructor args are placeholders — Max's `udpsend`
expects host+port args at instantiation time even though we'll
overwrite the destination dynamically via `host <sym>` / `port <int>`
config messages. Without args the object renders red/unresolved with
no visible inlets, which looks like the object is broken. The
placeholder `0` will be replaced by the `port <int>` message on every
query.

Wire (single inlet):
- inlet 0 receives three message types in sequence per query:
  `host <symbol>`, `port <int>`, then the reply OSC message itself.

> **Trap.** If `udpsend` instantiated WITHOUT host+port args resolves
> red/unresolved in your Max version, that's the cause — give it
> placeholder args `127.0.0.1 0`. Alternative if your install lacks
> the vanilla `udpsend` object entirely: `mxj net.udp.send 127.0.0.1 0`
> ships with every Max version and accepts the same wire protocol
> (same `host <sym>` / `port <int>` config-message convention).

> **One udpsend or two?** The signature-reply `[udpsend]` (this one)
> is distinct from the feature-emitter `[udpsend]` in Section F.6.
> Two reasons: different lifecycles (signature-reply destination
> changes per query; feature-emitter destination changes only when
> `EmitPort` is rewritten); and a single `[udpsend]` whose
> destination changes between an in-flight feature frame and a
> signature reply would scramble the destinations under concurrent
> load.

---

## Section D — Transport-position observer + state machine

This is the most intricate region. Pure-Max state machine using
`[expr]` for the threshold-crossing logic and `[deferlow]` to update
the `prev_beat` AFTER the comparisons fire.

### D.1. The observer

Box text:

```
live.observer @path live_set @property current_song_time
```

> **Property-name trap.** Live 12 exposes `current_song_time` on
> `live_set`. If your Live version surfaces it as `song_time` instead,
> the observer falls silent (no error, no output). Test by adding a
> temporary `[print obs]` on its outlet, pressing play in Live, and
> watching for a stream of floats. If silent: try `@property
> song_time`, `@property current_song_time`, then probe with
> `ableton_session(action='introspect', target='song', what='dir')`
> from the MCP to find the actual property name.

The observer emits one float per scheduler tick: the current beat
position (0-based, beats from arrangement start, float).

### D.2. Latched-state objects

You need three `[value]` objects to hold latched state (read by the
[expr] later):

```
value prev_beat
value v_start_at_beat   ← shadow of /start_at_beat retainer, see below
value v_stop_at_beat    ← shadow of /stop_at_beat retainer
value v_arm             ← shadow of Arm parameter
```

> **Why shadow `[value]`s instead of reading the originals directly?**
> Max's `[expr]`'s cold inlets latch the most recently received value.
> They DON'T pull from elsewhere on demand. So each cold inlet needs
> a `[value]` whose emission fans out to the cold inlet AND keeps
> getting re-emitted whenever the source changes. The cleanest pattern
> is to make a local shadow that mirrors the source.

Wire the shadows to fan in from the sources:

```
[value start_at_beat]   (the Section C.2 retainer; default @triggers 1
                          re-emits on every OSC write)
        │ outlet 0
        ▼
[value v_start_at_beat]   ← shadow, ALSO @triggers 1 default; the
                            chain is purely about decoupling so the
                            expr's cold inlet sees a stable handle
```

Same shadow chain for `stop_at_beat`. For `Arm`, tap the `live.toggle`'s
outlet directly:

```
[live.toggle (Arm)]   (Chunk 1)
        │ outlet 0 (emits 0 or 1 on each toggle change)
        ▼
[value v_arm]
```

Initialize `prev_beat` at patch load:

```
[loadbang]
        │
        ▼
   [-1.]                ← sentinel "no prior beat seen"
        │
        ▼
[value prev_beat]
```

Box text: `-1.`

### D.3. The crossing-detection [expr] pair

Two `[expr]` objects, one per crossing event.

#### D.3.a. `expr_start_crossed`

Box text:

```
expr ($f2 < $i3) && ($f1 >= $i3) && ($i4 == 1)
```

> **Note on `[expr]` inlet references.** Max's `[expr]` uses
> **1-indexed** variable names: `$f1` / `$i1` / `$s1` refers to the
> LEFTMOST inlet (inlet 0 in patchcord-numbering terms), `$f2`/`$i2`
> to the next inlet, and so on. There is no `$f0` / `$i0`. So the
> hot inlet's variable is `$f1`, not `$f0` as you might expect from
> 0-based outlet/inlet numbering elsewhere in this guide.

Inlets:

| Inlet (0-based) | `[expr]` ref | Type | Source | Role |
|---|---|---|---|---|
| 0 (hot)  | `$f1` | float | observer outlet (current_beat) | triggers eval |
| 1 (cold) | `$f2` | float | `[value prev_beat]` outlet | prior beat |
| 2 (cold) | `$i3` | int | `[value v_start_at_beat]` outlet | start threshold |
| 3 (cold) | `$i4` | int | `[value v_arm]` outlet | armed gate |

Wire:
- observer → `[expr ...]` inlet 0 (will need `[deferlow]` for prev_beat update, see D.5)
- `[value prev_beat]` outlet → `[expr ...]` inlet 1
- `[value v_start_at_beat]` outlet → `[expr ...]` inlet 2
- `[value v_arm]` outlet → `[expr ...]` inlet 3

Output: 1 (true) or 0 (false) on each observer tick.

#### D.3.b. `expr_stop_crossed`

Identical box text and wiring, except inlet 2 sources from
`[value v_stop_at_beat]` instead of `v_start_at_beat`.

### D.4. Convert 0/1 output to bangs (only on TRUE)

After each `[expr]`:

```
[expr ...]
        │ outlet 0 (0 or 1 per observer tick)
        ▼
   [sel 1]
        │ outlet 0 (bangs ONLY when input is exactly 1)
        ▼
   (start-crossed bang)
```

Box text: `sel 1`

Now you have:
- `start_crossed_bang` — bangs on the observer tick where transport
  crosses start_at_beat while armed
- `stop_crossed_bang` — bangs on the observer tick where transport
  crosses stop_at_beat while armed

### D.5. Update `prev_beat` AFTER the exprs evaluate

The exprs read `prev_beat` from their cold inlet; the cold inlet
value was set on the previous tick. We need to update `prev_beat`
to `current_beat` AFTER the two exprs have fired — for the NEXT tick.

Use `[deferlow]`:

```
[live.observer ...]
        │ outlet 0 (current_beat as float)
        ├─→ [expr expr_start_crossed] inlet 0 (triggers immediately)
        ├─→ [expr expr_stop_crossed] inlet 0 (triggers immediately)
        └─→ [deferlow]
                │ outlet 0
                ▼
           [value prev_beat]     ← updates after the current scheduler tick completes
```

`[deferlow]` pushes the message to the low-priority queue, which runs
after the audio thread and after the current scheduler tick's
high-priority messages. By the time it fires, the exprs have already
evaluated using the OLD prev_beat — exactly what we want.

Box text: `deferlow`

---

## Section E — Rewire recording trigger

In Chunk 1, the rising-edge of `Arm` directly triggered
`open <path>` + `1` to `sfrecord~`. In Chunk 2, `Arm` is a gate and
the transport observer triggers the recording. You're replacing one
chain with a new one.

### E.1. Find the Chunk 1 chain to disconnect

Visually trace from the `[live.toggle (Arm)]`'s outlet:

```
[live.toggle (Arm)]
        │ outlet 0
        ▼
   [change]                ← only emits on actual value change
        │
        ▼
   [sel 1]                 ← fires bang only on 1 (rising edge)
        │
        ▼
   [t b b]                 ← right-then-left: right reads path, left fires '1'
        │ outlet 1 (right, fires first)
        │      ▼
        │   [value hallucinote_path]
        │      │
        │      ▼
        │   [prepend open]
        │      │
        │      ▼
        │   [sfrecord~]   inlet 0 (left, message inlet)
        │
        │ outlet 0 (left, fires second)
        ▼
   [1]                     ← the integer 1
        │
        ▼
   [sfrecord~]   inlet 0
```

### E.2. Cut and reconnect

**Delete:** the patchcord from `[sel 1]` (rising-edge detector) to
`[t b b]`. Leave everything downstream — we'll feed `[t b b]` from
the new observer-based source.

**Keep `[change]` + `[sel 0]` for the "user pulled the cord" path:**
also add a separate `[sel 0]` parallel to `[sel 1]` to detect falling
edge of `Arm` — this is the "stop now" path for when the user
manually disarms mid-recording.

```
[live.toggle (Arm)]
        │ outlet 0
        ▼
   [change]
        │
        ├──→ [sel 1]    (rising edge — UNUSED now; can delete or leave dangling)
        └──→ [sel 0]    (falling edge — preserved as "user pulled the cord" stop path)
                │
                ▼
               (will feed the stop chain below)
```

### E.3. Wire the new start trigger from D.4's `start_crossed_bang`

The "no path → don't arm" guard (Chunk 1 contract) uses a `[value has_path]`
flag set by `/path` arrival — mirror of the `has_track_id` flag in
Section F. Don't try to inspect the path symbol's "emptiness" directly;
Max's `[length]` measures list length (not symbol-character count) and
there's no clean Max idiom for "is this symbol empty?"

**First, augment the `/path` route in Section C / Chunk 1** so it sets a flag:

```
[OSC-route /path]                                   (existing Chunk 1 box)
        │ outlet 0 (the path symbol)
        ├──→ [prepend open] → [sfrecord~]           (existing Chunk 1 wiring)
        ├──→ [value hallucinote_path]               (existing Chunk 1 retainer)
        └──→ [t s] → [1] → [value has_path]         (NEW: set flag to 1)
```

Box text:
- `t s` — discards the symbol, just propagates the trigger
- `1` — the integer 1 (the value to store in the flag)
- `value has_path` — the flag

And initialize the flag at patch load:

```
[loadbang] → [0] → [value has_path]
```

**Then wire the new start trigger through a `[gate]` controlled by `has_path`:**

```
(D.4's start_crossed_bang outlet)
        │
        ▼
   [gate]                       ← gate's outlet emits only when control == 1
        ↑
        │ control (0 or 1)
        │
[value has_path] outlet
                  │ outlet 0 (gated bang — only fires if has_path == 1)
                  ▼
             [t b b]            ← right-then-left: right reads path, left fires 1
             ├── outlet 1 (right, fires first)
             │      ▼
             │   [value hallucinote_path]    ← Chunk 1's path retainer; unchanged
             │      │ outlet 0
             │      ▼
             │   [prepend open]
             │      │
             │      ▼
             │   [sfrecord~]   inlet 0
             │
             └── outlet 0 (left, fires second — sends start)
                    ▼
                [1]
                    │
                    ▼
                [sfrecord~]   inlet 0
```

For visibility into the guard firing or refusing, add a `[print PathGuard]`
that watches the `[gate]`'s control inlet — `0` printed when has_path
hasn't been set, `1` when the harness has sent `/path` at least once.

### E.4. Wire the new stop trigger

The stop trigger fires from TWO sources OR'd together:

1. `stop_crossed_bang` (from D.4)
2. Falling-edge-of-Arm from E.2 (user pulled the cord)

```
   stop_crossed_bang ─────┐
                          ├──→ [t b]   (just to fan in cleanly)
   falling_edge_arm ──────┘    │
                               ▼
                           [0]            ← the integer 0 (sfrecord~ stop+finalize)
                               │
                               ▼
                          [sfrecord~]   inlet 0
```

Box text: `0` for the message object emitting the int.

### E.5. Sanity-check the wiring

Add temporary `[print]` objects on each new bang outlet:

```
start_crossed_bang ─→ [print START]
stop_crossed_bang  ─→ [print STOP]
falling_edge_arm   ─→ [print ARM_DROP]
```

Save (`Cmd-S`). In Live: drop the device on a track with audio,
send via Python harness:

```python
import socket, struct
def osc(addr, *args):
    def s(x): r = x.encode() + b'\x00'; return r + b'\x00' * ((-len(r)) % 4)
    def i(x): return struct.pack('>i', int(x))
    types = ',' + ''.join('s' if isinstance(a, str) else 'i' for a in args)
    body = b''.join(s(a) if isinstance(a, str) else i(a) for a in args)
    return s(addr) + s(types) + body
sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.sendto(osc('/path', '/tmp/test_chunk2b.wav'), ('127.0.0.1', 11000))
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11000))
sk.sendto(osc('/start_at_beat', 8), ('127.0.0.1', 11000))
sk.sendto(osc('/stop_at_beat', 24), ('127.0.0.1', 11000))
```

Then in Live: position playhead at bar 1, set Arm=1, press play.
Max console should print `START` at beat 8, `STOP` at beat 24.
After verifying, remove the `[print]` debug objects.

---

## Section F — Feature extraction branch

A parallel audio tap (NOT in series — don't break Chunk 1's
pass-through signal) that runs three feature extractors and emits
30 Hz OSC frames.

### F.1. Tap the audio inlet

In the existing patch, the audio inlet routes via `[plugin~]` (or
equivalent — check the Chunk 1 patch). Add a parallel tap:

```
[plugin~] outlet 0 ──┬──> [plugout~] (existing — sonic pass-through)
                     ├──> [sfrecord~] inlet 1 (existing — left channel record)
                     └──> [send~ tap_L]    ← NEW

[plugin~] outlet 1 ──┬──> [plugout~] outlet 1 (existing)
                     ├──> [sfrecord~] inlet 2 (existing — right channel record)
                     └──> [send~ tap_R]    ← NEW
```

Box text: `send~ tap_L` and `send~ tap_R`.

Then receive in the feature-extraction region:

```
[receive~ tap_L]   [receive~ tap_R]
```

> **Why send~/receive~ rather than direct patchcords?** Visual
> clarity — the feature region lives at the bottom of the patch;
> direct cords across the whole patch get messy. `send~`/`receive~`
> add zero sample delay.

### F.2. K-weighted LUFS-M (momentary)

ITU-R BS.1770-4: two cascaded biquads (high-shelf + high-pass), then
mean-square over 400 ms, then dB conversion with the -0.691 offset.

**Mix to mono** (L+R)/2 — momentary loudness is mono-summed:

```
[receive~ tap_L]   [receive~ tap_R]
        │                │
        ▼                ▼
       [+~]                       ← signal add
        │
        ▼
       [*~ 0.5]                   ← halve to keep -3 dB headroom on mono sum
        │ outlet 0
        ▼
    (mono signal, feed both K-weight cascade and band-power cascade)
```

Box text: `+~`, `*~ 0.5`.

**Stage 1 — high-shelf biquad** (BS.1770-4 reference, 48 kHz):

```
biquad~ 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585
```

The args are `a0 a1 a2 b1 b2` (Max's biquad~ convention — feedforward
then feedback). The values above are BS.1770-4's pre-filter at 48 kHz.

**Stage 2 — high-pass biquad** (BS.1770-4 reference, 48 kHz):

```
biquad~ 1.0 -2.0 1.0 -1.99004745483398 0.99007225036621
```

Chain:

```
mono signal → [biquad~ <stage 1 coefs>] → [biquad~ <stage 2 coefs>] → (K-weighted signal)
```

**Square the K-weighted signal** (for mean-of-squares):

```
K-weighted signal ──┬──→ [*~] inlet 0
                    └──→ [*~] inlet 1     ← self-multiply: x²
                                │
                                ▼
                          (x² signal)
```

Box text: `*~` (no args — both inlets used).

**Mean-square over 400 ms** using `[average~]`:

```
x² signal → [average~ 19200 bipolar] → (mean square at audio rate)
```

Box text: `average~ 19200 bipolar`

The "bipolar" mode computes the simple mean of the signal (without
absolute-value or sqrt). Since x² is non-negative, this gives
mean-of-squares. 19200 samples at 48 kHz = 400 ms. At 44.1 kHz this
becomes ~436 ms — close enough for MVP.

**Convert to LUFS** (sample at metro rate, then compute in
control-rate land):

```
mean square at audio rate
        │
        ▼
   [snapshot~]              ← banged by [metro 33] (Section F.5)
        │ outlet 0 (float)
        ▼
   [if $f1 > 0 then (10 * log10($f1)) - 0.691 else -inf]
        (express as: [expr ($f1 > 0.) ? (10. * log10($f1)) - 0.691 : -120.]
         where -120 stands in for "silent" — log of zero is -inf,
         the sidecar treats -120 dBFS as "effectively silent")
```

Box text: `snapshot~`, then:

```
expr ($f1 > 0.) ? (10. * log10($f1)) - 0.691 : -120.
```

Output: LUFS-M as a float, on each metro tick.

### F.3. Sample peak

Simpler — `[peakamp~]` accumulates the peak between bangs, output is
linear 0-1.

```
mono signal → [peakamp~] inlet 0      ← signal input

(metro 33's bang) → [peakamp~] inlet 0 (also)    ← bang resets + outputs
                                       ↑
                                  send bangs here

[peakamp~] outlet 0 (float, linear 0-1 peak since last bang)
        │
        ▼
   [expr ($f1 > 0.) ? 20. * log10($f1) : -120.]
        │ outlet 0 (float, peak in dBFS)
```

Box text: `peakamp~`, then the expr as shown.

> `[peakamp~]` takes the signal on inlet 0 AND bangs on inlet 0 —
> they share the inlet. The bang triggers output AND resets the
> internal peak accumulator.

### F.4. Low-mid (200-500 Hz) band power

Two cascaded biquads (HP at 200 Hz, LP at 500 Hz), square, average
over 100 ms, snapshot, log.

**HP at 200 Hz** (Butterworth 2-pole, 48 kHz, approximate):

```
biquad~ 0.97803 -1.95606 0.97803 -1.95558 0.95654
```

**LP at 500 Hz** (Butterworth 2-pole, 48 kHz, approximate):

```
biquad~ 0.00102 0.00205 0.00102 -1.95558 0.95968
```

Chain:

```
mono signal → [biquad~ HP coefs] → [biquad~ LP coefs] → (band-passed signal)
```

**Square, average, snapshot:**

```
band-passed signal ──┬──→ [*~] inlet 0
                     └──→ [*~] inlet 1                        ← self-square
                              │
                              ▼
                     [average~ 4800 bipolar]              ← 100 ms at 48 kHz
                              │
                              ▼
                     [snapshot~]                          ← banged by metro
                              │
                              ▼
                     [expr ($f1 > 0.) ? 10. * log10($f1) : -120.]
                              │ outlet 0
                            (low_mid_power in dB)
```

Same `snapshot~` / expr / box text pattern as F.2.

### F.5. Pack and emit at 30 Hz

The pack-and-emit chain:

```
[loadbang]
    │
    ▼
[1]                        ← start the metro on patch load
    │
    ▼
[metro 33]                 ← every 33 ms = ~30 Hz
    │ outlet 0 (bang)
    │
    ├──→ [snapshot~] (LUFS-M chain, Section F.2) inlet 0 (bang for snapshot)
    ├──→ [peakamp~]  (Section F.3)               inlet 0 (bang for read + reset)
    ├──→ [snapshot~] (low-mid chain, Section F.4) inlet 0 (bang for snapshot)
    └──→ (no need to bang track_id — [value]s don't need a bang on read in [sprintf])
```

Box text: `metro 33`, `loadbang`, `1`.

Each of the three feature exprs (F.2, F.3, F.4) outputs a float once
per metro tick. Collect them into a 3-element list:

```
LUFS-M expr     ──→ [pack f f f] inlet 0   (hot — triggers list output)
peak expr       ──→ [pack f f f] inlet 1   (cold — latched)
low-mid expr    ──→ [pack f f f] inlet 2   (cold — latched)
```

Box text: `pack f f f`.

> The inlet that fires must be the LAST one to be updated on each
> tick, otherwise we'd emit a list with a stale value. Since metro
> fires all three feature snapshots SIMULTANEOUSLY (well, in sequence
> within the same scheduler tick), pick whichever you wire to inlet 0;
> in practice connecting LUFS-M to inlet 0 works because the other
> two are updated within the same tick before the `[pack]` evaluates.
>
> If you see stale values in the OSC frames, swap the wiring so the
> LAST-to-update feature goes to inlet 0.

**Build the dynamic OSC address:**

```
[value track_id_retained]   (Section C.1)
        │ outlet 0 (symbol)
        ▼
   [sprintf /hallucinote/track/%s/features]
        │ outlet 0 (symbol — the full OSC address)
        ▼
   (latches into the message-construction step below)
```

Box text: `sprintf /hallucinote/track/%s/features`.

**Construct the outbound OSC message:**

`[udpsend host port]` accepts a list whose first element is the
address (a symbol) followed by args. So:

```
[sprintf ...] outlet ──→ [pak s f f f] inlet 0   (cold — latches address)

(metro tick) → trigger the feature snapshots → [pack f f f] outlet emits list
                                                      │
                                                      ▼
                                          (need to combine address + 3 floats)
```

Actually, `[pack f f f]` outputs a 3-element float list. We need to
prepend the address as a symbol. Easiest:

```
[pack f f f] outlet 0 (list: f f f)
        │
        ▼
   [prepend dummy]              ← we'll replace 'dummy' with the dynamic address
        │ outlet 0 (list: <dummy> f f f)
```

But `[prepend]` takes a STATIC prefix. To make it dynamic, use
`[prepend set]` pattern OR use `[pak]` to bundle address + floats:

```
[pack f f f] outlet     ──→ [pak s f f f] inlet 1   (cold — receives the 3 floats packed... wait this doesn't work)
```

Hmm. The cleanest pattern in Max for "dynamically prefix a symbol to
a list" is via `[sprintf]` or `[message]`:

Approach via `[message]`:

```
[message $1 $2 $3 $4]                 ← takes 4 args via inlet, outputs as list

   address (symbol)  ──→ [message]'s SECOND inlet (sets $1)        
   feature_LUFS    ──→ [message]'s THIRD inlet (sets $2)
   feature_peak    ──→ [message]'s FOURTH inlet (sets $3)
   feature_lowmid  ──→ [message]'s FIFTH inlet (sets $4)
   
   (any bang to inlet 0 fires the message with current $1..$4)
```

Wait — `[message]` in Max only has TWO inlets: inlet 0 (fires on
incoming message or bang), inlet 1 (sets the message contents). It
doesn't have $-arg inlets. To pre-set $1..$N you SEND a list to
inlet 1: the list elements become $1, $2, ... and then inlet 0 fires.

So:

```
(metro tick) →
        │
        ▼
   [pak s f f f]                ← pack address (symbol) + 3 floats into a list
        │ inlet 0 (cold-stash) — connect address (sprintf outlet) here  
        │ inlet 1 (cold) — connect LUFS-M expr here
        │ inlet 2 (cold) — connect peak expr here
        │ inlet 3 (cold) — connect low-mid expr here
        │ 
        │ (hot inlet must fire last — bang from metro post-feature-snapshot)
        │
        ▼
   outlet (list: <address> <lufs> <peak> <lowmid>)
        │
        ▼
   [udpsend 127.0.0.1 11201]        ← left inlet 0 — message
```

But `[pak]` fires on ANY inlet change, so it fires three times per
tick (or four if address also changes). Each fire emits the current
latched values. For OSC, getting THREE near-identical packets per
tick (each with one feature updated and the others stale) is
basically as bad as the stale-value problem.

The clean solution: use `[pack s f f f]` (capital P? no — Max uses
lowercase. `pack` fires only on LEFTMOST inlet change, holds others
latched).

Box text: `pack s f f f`.

Wiring:

```
address (sprintf outlet)  ──→ [pack s f f f] inlet 0   (HOT — triggers emission)
LUFS-M expr               ──→ [pack s f f f] inlet 1   (cold — latched)
peak expr                 ──→ [pack s f f f] inlet 2   (cold)
low-mid expr              ──→ [pack s f f f] inlet 3   (cold)
```

But now address has to be the LAST thing to update per metro tick.
Re-arrange the metro fan-out:

```
[metro 33]
    │ outlet 0 (bang)
    │
    ├──→ [snapshot~] (peak)                inlet 0
    ├──→ [snapshot~] (low-mid)             inlet 0  (actually peakamp~ shares inlet 0 for signal+bang)
    ├──→ [snapshot~] (LUFS-M)              inlet 0
    │
    │  (now the three feature exprs have emitted their floats; pack's
    │   inlets 1, 2, 3 are latched with fresh values)
    │
    └──→ (bang the address chain LAST)
            │
            ▼
       [value track_id_retained] (re-emits the symbol via its outlet, into [sprintf])
            │
            ▼
       [sprintf /hallucinote/track/%s/features]
            │
            ▼
       [pack s f f f] inlet 0 (HOT — fires the pack with current latched floats)
            │
            ▼
       outlet (list: <address> <lufs> <peak> <lowmid>)
```

To make the metro fire the address chain LAST, use `[t b b b b]`
right-to-left ordering:

```
[metro 33]
    │
    ▼
[t b b b b]
   │ outlet 3 (rightmost — fires FIRST)  →  [peakamp~] (read)
   │ outlet 2                            →  [snapshot~] (low-mid) inlet 0
   │ outlet 1                            →  [snapshot~] (LUFS-M) inlet 0
   │ outlet 0 (leftmost — fires LAST)    →  bang the address chain
```

(`[peakamp~]`'s inlet 0 takes both signal and bang; the bang
triggers a read+reset.)

> **Why bang `[snapshot~]` instead of letting it run continuously?**
> `[snapshot~]` is silent until banged — banging samples the signal
> NOW. This is exactly the "sample audio-rate signal at control-rate"
> behavior we want.

Box text: `t b b b b`.

**Gate by `Emit` (the emit_enabled toggle):**

```
[pack s f f f] outlet
        │
        ▼
   [gate]                       ← gate's outlet emits only when control inlet is 1
        │
        ▼ (gated outbound message)

[live.toggle (Emit)] outlet 0 ──→ [gate]'s inlet 0 (control)
```

Box text: `gate`.

**Gate by non-empty track_id** (defensive):

```
[value track_id_retained] outlet → [length] → [> 0]
                                                │ outlet 0 (1 if non-empty)
                                                ▼
                                           [gate]'s control inlet
                                           (... actually we already have one gate above;
                                            chain a second gate OR AND the two flags)
```

Simpler: AND the two conditions:

```
[live.toggle (Emit)] outlet → [pak 0 0] inlet 0
[value track_id_retained] outlet → [length] → [> 0] → [pak 0 0] inlet 1
                                                              │
                                                              ▼
                                                         outlet (list: emit, has_id)
                                                              │
                                                              ▼
                                                         [expr $i1 && $i2]    ← AND
                                                              │
                                                              ▼
                                                         [gate]'s control inlet
```

Hmm this is getting hairy. Simpler: TWO `[gate]`s in series, one
controlled by each flag:

```
[pack s f f f] outlet
        │
        ▼
   [gate]  control: Emit
        │
        ▼
   [gate]  control: has_track_id   (1 if [value track_id_retained] length > 0)
        │
        ▼
   [udpsend 127.0.0.1 11201]
```

For the has_track_id flag, drive it from any update to
`[value track_id_retained]`:

```
[value track_id_retained]
        │ outlet 0 (symbol; emits on every write)
        ▼
   [length]         ← emits the symbol's length (int)
        │
        ▼
   [> 0]            ← 1 if non-empty, 0 otherwise
        │
        ▼
   (drives the second [gate]'s control inlet)
```

Box text: `length`, `> 0`.

> But `[length]` doesn't take a symbol — it takes a list and returns
> the list length. For a symbol's CHARACTER count, use `[regexp]` or
> `[strcmp]` against the empty symbol `<empty>`. Actually:
>
> ```
> [== <empty>]      ← returns 1 if symbol is the empty symbol
> ```
>
> Then NOT it:
>
> ```
> [value track_id_retained]
>         │
>         ▼
>    [== <empty>]   ← outputs 1 if empty, 0 if non-empty
>         │
>         ▼
>    [== 0]         ← invert: 1 if NON-empty
>         │
>         ▼
>    (drives gate)
> ```
>
> Slight kludge, but clean enough. Alternative: store a separate
> `[value has_track_id]` that gets set to 1 by the `/track_id`
> route and never decays — simpler.

Pragmatic choice: set a `[value has_track_id]` flag in Section C.1's
chain:

```
[OSC-route /track_id]
        │ outlet 0
        ├──→ [value track_id_retained]
        └──→ [t s]                            ← discard the value
                │
                ▼
            [1]                               ← set flag to 1
                │
                ▼
            [value has_track_id]
```

Then use that `[value has_track_id]` to drive the gate (no string
arithmetic needed). Add to the patch's `[loadbang]` chain:

```
[loadbang] ──→ [0] ──→ [value has_track_id]     ← initialize to "no track_id yet"
```

### F.6. The outbound `[udpsend]`

Box text: `udpsend 127.0.0.1 11201`

(Default destination; configurable via `EmitPort` parameter as below.)

**Re-target on EmitPort change:**

```
[live.numbox (EmitPort)] outlet 0
        │ (float — Type=Float, Unit Style=Int)
        ▼
   [i]                      ← coerce float→int (prepend port expects int)
        │
        ▼
   [prepend port]           ← emits "port <N>" config message
        │ outlet 0
        ▼
   [udpsend 127.0.0.1 11201] inlet 0   ← single inlet absorbs config OR data
```

Box text: `i`, `prepend port`.

Wire the metro-driven message chain (Section F.5) to the same single
`[udpsend]` inlet — Max distinguishes the `port <N>` config message
from feature-frame data messages by the leading symbol.

> **No host retarget needed** for the feature emitter — the sidecar
> always listens on 127.0.0.1, baked into the `[udpsend]` constructor
> args. If the design ever needs cross-machine emission, add a
> sibling `[prepend host]` chain analogous to Section C.3.a.

`[live.numbox]`'s stored value auto-emits at patch load if Initial
Enable is Yes (which Section B.1 requires). Verify by adding a
temporary `[print EmitPort_init]` after `[live.numbox]`'s outlet —
should print `11201` (or whatever the stored value is) right after
Live loads the patch.

### F.7. Full F-section assembly diagram (sanity-check yourself)

```
                          [receive~ tap_L]   [receive~ tap_R]
                                  │                   │
                                  └─── [+~] ──── [*~ 0.5] ─── (mono signal)
                                                       │
            ┌─────────── (mono) ──────────┬──────── (mono) ────────────┐
            │                             │                            │
            ▼                             ▼                            ▼
  [biquad~ HS coefs]                  [peakamp~]              [biquad~ HP-200 coefs]
            │                             │                            │
            ▼                       (bang inlet0                        ▼
  [biquad~ HP coefs]                from metro)                [biquad~ LP-500 coefs]
            │                             │                            │
            ▼                             │                            ▼
       [*~] self                          │                       [*~] self
            │                             │                            │
            ▼                             │                            ▼
  [average~ 19200 bipolar]                │                  [average~ 4800 bipolar]
            │                             │                            │
            ▼                             │                            ▼
       [snapshot~]                        │                       [snapshot~]
            │                             │                            │
            ▼                             ▼                            ▼
[expr (LUFS conversion)]    [expr (peak conversion)]    [expr (low-mid conversion)]
            │                             │                            │
            └────────── (3 floats) ───────┴────────────────────────────┘
                                          │
                                          ▼
                              [pack s f f f]      ← address into inlet 0 (hot)
                                          │      floats into inlets 1/2/3 (cold)
                                          ▼
                                       [gate]  control: Emit
                                          │
                                          ▼
                                       [gate]  control: has_track_id
                                          │
                                          ▼
                              [udpsend 127.0.0.1 11201]  ← single inlet; EmitPort sends `port <N>` config msgs here
```

---

## Section G — In-Max sanity tests (before saving)

Before `Cmd-S`-ing the patch, verify each Chunk 2 addition with
console probes. The Max console (`Cmd-M`) is your friend.

### G.1. Live parameter visibility check

In Max, drop a temporary `[live.thisdevice]` and bang it:

```
[live.thisdevice]
        │ outlet 0 (emits 'id' on patch load)
        ▼
   [print thisdevice]
```

Patch console should show the device's id at load. More usefully,
from Python (with the device on track 1):

```python
from hallucinote_mcp.client import send
from hallucinote_mcp.wire import Request

r = send(Request(tool="ableton_device", action="get_parameters",
                 params={"track_index": 1, "device_index": 1}))
names = {p["name"] for p in r.result["parameters"]}
assert {"Arm", "Port", "EmitPort", "Emit"} <= names, f"missing: {{'Arm','Port','EmitPort','Emit'}} - names = {{'Arm','Port','EmitPort','Emit'}} - names}"
print("OK: all four short names present")
```

### G.2. Inbound OSC routing

Add temporary `[print track_id_in]`, `[print start_in]`,
`[print stop_in]` on the outlets of `[OSC-route /track_id]` etc.

From Python:

```python
import socket, struct
def osc(addr, *args):
    def s(x): r = x.encode() + b'\x00'; return r + b'\x00' * ((-len(r)) % 4)
    def i(x): return struct.pack('>i', int(x))
    types = ',' + ''.join('s' if isinstance(a, str) else 'i' for a in args)
    body = b''.join(s(a) if isinstance(a, str) else i(a) for a in args)
    return s(addr) + s(types) + body

sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11000))
sk.sendto(osc('/start_at_beat', 16), ('127.0.0.1', 11000))
sk.sendto(osc('/stop_at_beat', 32), ('127.0.0.1', 11000))
```

Max console should print:
```
track_id_in: test:1
start_in: 16
stop_in: 32
```

Remove the `[print]`s before saving.

### G.3. Signature reply round-trip

Bind a listener, send `/signature/query` carrying the listener's
host+port as args, listen for the reply:

```python
import socket, struct, time

def osc(addr, *args):
    def s(x): r = x.encode() + b'\x00'; return r + b'\x00' * ((-len(r)) % 4)
    def i(x): return struct.pack('>i', int(x))
    types = ',' + ''.join('s' if isinstance(a, str) else 'i' for a in args)
    body = b''.join(s(a) if isinstance(a, str) else i(a) for a in args)
    return s(addr) + s(types) + body

# Bind the listener; we'll tell the patch to reply here via OSC args
listen_port = 12345
sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.bind(("127.0.0.1", listen_port))
sk.settimeout(2.0)

# Send the query with reply destination as OSC args (,si: host symbol, port int)
sk.sendto(
    osc("/signature/query", "127.0.0.1", listen_port),
    ("127.0.0.1", 11000),
)

data, addr = sk.recvfrom(4096)
print(f"reply from {addr}:")
print(data[:60])
# Expect /signature\x00\x00,s\x00\x00hallucinote-analyzer-v1\x00
assert b"hallucinote-analyzer-v1" in data, "signature mismatch"
print("OK: signature reply received")
```

If timeout: check (in order)
1. `[OSC-route /signature/query]` outlet is wired — add `[print sigq]`
   on its outlet and confirm it prints `127.0.0.1 12345` (the args)
   when the query arrives.
2. `[t b l]` is right-to-left fire order — outlet 1 (the list →
   unpack → host/port config messages) fires BEFORE outlet 0 (the
   reply message bang).
3. `[prepend host]` and `[prepend port]` chains reach the same
   `[udpsend]` inlet. Add `[print to_udpsend]` immediately upstream
   of `[udpsend]` (between `[prepend host]` / `[prepend port]` /
   `[message ...]` and the udpsend inlet) — three lines should
   print per query, in order: `port 12345`, `host 127.0.0.1`,
   `/signature hallucinote-analyzer-v1`.

### G.4. Feature emitter rate

Bind a listener on 11201 (the default `EmitPort`):

```python
import socket, struct, time

sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.bind(("127.0.0.1", 11201))
sk.settimeout(2.0)

# Run audio through the track. Then:
count = 0
t0 = time.monotonic()
while time.monotonic() - t0 < 2.0:
    try:
        data, _ = sk.recvfrom(4096)
        count += 1
    except socket.timeout:
        break
print(f"received {count} frames in 2.0 s — expected ~60")
```

Targets:
- `~60 frames` per 2 seconds (30 Hz). ±10% tolerance.
- Each frame address starts with `/hallucinote/track/test:1/features`
  (assuming you sent `/track_id test:1` first).
- Payload type tag `,fff` followed by 12 bytes (3 floats).

If 0 frames: check `[live.toggle (Emit)]` is on (1), `has_track_id`
flag is 1 (because you sent `/track_id` first), and the metro is
running (Max console: add `[print metro]` between `[metro 33]` and
the `[t b b b b]`).

### G.5. Transport-position observer

Send a full render setup and play transport:

```python
# (osc() function as above)
import socket
sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.sendto(osc('/path', '/tmp/chunk2b_smoketest.wav'), ('127.0.0.1', 11000))
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11000))
sk.sendto(osc('/start_at_beat', 4), ('127.0.0.1', 11000))
sk.sendto(osc('/stop_at_beat', 12), ('127.0.0.1', 11000))
```

In Live: set Arm = 1, position playhead at bar 1, press space.

Add `[print obs_state]` temporarily on the `[live.observer]` outlet
and `[print start_cross]` / `[print stop_cross]` on the
`[sel 1]` outputs in Section D.4.

Expected console scroll: floats from observer climbing from 0.0
upward; `start_cross` bangs once when the observer crosses 4.0;
`stop_cross` bangs once when it crosses 12.0.

Inspect the WAV after stopping transport:

```bash
python3 -c "
import soundfile as sf
f = sf.SoundFile('/tmp/chunk2b_smoketest.wav')
print(f'frames={len(f)}, sr={f.samplerate}, ch={f.channels}, subtype={f.subtype}')
print(f'duration = {len(f) / f.samplerate:.3f} s')
"
```

At 120 BPM, 8 beats (4→12) = 4 seconds = 192,000 frames at 48 kHz.
Tolerance: ±1 audio buffer (typically ±512 samples). If you see
significantly more (the old MCP-latency-bounded padding), the
observer wiring isn't gating the recording — review Section D.

After verification, remove ALL the `[print]` debug objects.

---

## Section H — Save + copy back

### H.1. Save the patch (in Max)

`Cmd-S` saves through Max's GUI write path — the only safe way to
serialize an `.amxd` (see spec §"Authoring workflow").

### H.2. Verify in Live

Reload the device in Live (drag a fresh instance from the browser).
Sanity:

- All four parameters visible in the device's parameter list.
- Setting Arm=1 alone (without OSC inputs) does NOT start recording
  — the patch correctly waits for transport to cross start_at_beat.
- After `ableton_render(action='render', song_slug='falling-walking')`,
  WAVs appear under `songs/falling-walking/captures/<ts>/`.

### H.3. Copy back to the package source tree

```bash
cp "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd" \
   "$HOME/source/hallucinote/hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd"
```

(Adjust paths if your checkout is elsewhere.)

### H.4. Stage

```bash
cd ~/source/hallucinote
git status     # shows only HallucinoteAnalyzer.amxd as modified
git diff --stat HallucinoteAnalyzer.amxd   # binary diff — won't show content
```

**Don't commit yet** — Section I's in-Live verification must pass
first.

---

## Section I — Chunk 2 GO/NO-GO verification

See spec §"Verifying the build (Chunk 2 GO/NO-GO)" for the canonical
criteria. Quick checklist:

1. `/ableton-mcp-install` runs cleanly (Step 3d picks up the new
   `.amxd`; M4L probe runs).
2. Open a multi-track song (`falling-walking`).
3. Restart Claude Code (`/mcp` reconnect respawns the server).
4. `ableton_render(action='ensure_loaded')` reports
   `loaded_count: N+R+1` on first run, `existing_count: N+R+1` on
   second.
5. `ableton_render(action='render', song_slug='falling-walking')`
   produces `songs/falling-walking/captures/<ts>/` with N+R+1 WAVs
   + `manifest.json` + `manifest.status == "ok"`.
6. Each WAV is FLOAT/stereo/Live's SR with audio content above
   -60 dBFS.
7. WAV duration matches `song.last_event_time` ± one audio buffer.
8. Cross-correlate any track WAV vs master WAV; lag ≤ 64 samples.
9. `manifest.frames_received` > 0 per analyzer.
10. Two consecutive renders produce two independent captures dirs.

If any fail, the spec's NO-GO criteria list common causes. Review
the relevant section above.

---

## Section J — Close-out

After GO:

1. **Commit the `.amxd`:**
   ```bash
   git add hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd
   git commit -m "chunk 2 of 2 (audio-analysis MVP, Chunk 2): in-Live close-out + .amxd"
   ```
2. **Update `.prawduct/.test-evidence.json`** with in-Live results
   (frame count, render duration, alignment lag).
3. **Append reflection** to `.prawduct/.session-reflected` — document
   any traps that surfaced.
4. **Mark Chunk 2 `[x]`** in `.prawduct/artifacts/build-plan.md`.
5. **Add change-log entry** `chunks=2 | status=shipped | release=unreleased | scope=audio-analysis-mvp`.
6. **Run `/critic chunk`** for the cumulative Chunk 2 review.
7. Branch is ready for `/pr` if/when you want to merge.

---

## Appendix — Object inventory

Every Max object referenced in this guide, alphabetical:

| Object | Purpose | Where used |
|---|---|---|
| `average~ <samples> bipolar` | sliding mean of signal | F.2, F.4 |
| `biquad~ a0 a1 a2 b1 b2` | 2-pole filter section | F.2 (K-weighting), F.4 (band-pass) |
| `change` | emit only on value change | E.2 |
| `delay 100` | delay in milliseconds | F.6 (init order) |
| `deferlow` | push to low-priority queue | D.5 |
| `expr <expression>` | evaluate arithmetic / boolean | D.3, F.2, F.3, F.4 |
| `gate` | gate a signal/message by control | F.5, F.6 |
| `i` | int truncator | C.2 |
| `length` | list/symbol length | F.5 (alternative approach) |
| `live.numbox` | Live parameter (numeric) | A, B.1 |
| `live.observer` | Live LOM property observer | D.1 |
| `live.thisdevice` | self-reference (id, sample rate, etc.) | G.1 |
| `live.toggle` | Live parameter (boolean) | B.2 |
| `loadbang` | bang on patch load | F.5, F.6 |
| `message <text>` | static or dynamic message | C.3 |
| `metro 33` | bang every 33 ms | F.5 |
| `OSC-route /path/literal` | route OSC by address | C |
| `pack <typespec>` | pack into list (fires on left inlet) | F.5 |
| `pak <typespec>` | pack into list (fires on any inlet) | C.3, F.6 |
| `peakamp~` | sample-peak accumulator | F.3 |
| `pipe N` | delay messages by N ms | (not used; alternative to deferlow) |
| `plugin~` / `plugout~` | M4L audio in/out | F.1 |
| `prepend <prefix>` | prepend static prefix to list | (alternative for F.5) |
| `print <label>` | log to Max console | sanity tests throughout |
| `receive~ <name>` | named audio receiver | F.1 |
| `send~ <name>` | named audio sender | F.1 |
| `sel <value>` | bang when input matches | D.4, E.2 |
| `sfrecord~` | audio file writer | E.3, E.4 (unchanged from Chunk 1) |
| `snapshot~` | sample audio signal at control rate | F.2, F.4 |
| `sprintf <format>` | format string with %s/%d | F.5 |
| `t <typespec>` | trigger (right-to-left fire order) | C.3, D, E.3, F.5 |
| `udpreceive <port>` | UDP message receiver | C (unchanged base from Chunk 1) |
| `udpsend [host port]` | UDP message sender | C.3 (reply), F.6 (emitter) |
| `value <varname>` | named state cell | C, D, E |

---

## Appendix — Common traps (Chunk 1 carryover + new for Chunk 2)

| Symptom | Cause | Fix |
|---|---|---|
| Parameter missing from Remote Script's `get_parameters` | Visibility = "Stored Only" | Set to "Automated and Stored" |
| `set_parameter(name='Record Arm')` fails | API uses short name | Use `Arm` (same for `Emit`, `EmitPort`) |
| WAV is ~44 frames | Used `record 1` instead of `1` | Send bare integer `1` to start, `0` to stop |
| `sfrecord~` rejects `close`/`stop` | Not part of documented API | Use `0` only |
| WAV missing despite Arm=1 + transport play | `start_at_beat` not received or observer property wrong | Verify with `[print obs]`; try `current_song_time` vs `song_time` |
| Recording window is too long (~2 s padding) | `Arm`-driven trigger still wired (Chunk 1 path) | Re-do Section E.2 disconnect |
| Recording starts and stops correctly but duration is off | `prev_beat` not updating, or updating BEFORE expr evaluates | Section D.5 `[deferlow]` is the fix — verify order |
| `/signature/query` returns no reply | `host`/`port` config messages didn't land at `[udpsend]` before the reply message | Section C.3.b `[t b l]` right-to-left order; verify with `[print to_udpsend]` upstream of the inlet — should print three lines per query in order |
| OSC reply goes to wrong port | Query OSC args (`,si`: reply_host, reply_port) malformed or `[prepend port]` / `[prepend host]` chain not reaching `[udpsend]` | Section C.3.a wiring |
| Assumed `[udpreceive]` has a right outlet for sender info | It doesn't — vanilla Max `[udpreceive]` has one outlet (the OSC messages); CNMAT's variants are the same | Carry the reply destination in the OSC query payload (Section C.3) |
| Assumed `[udpsend]` has a right inlet for `host port` config | It doesn't — single inlet, retarget via `host <sym>` / `port <int>` MESSAGES (same convention as `[udpreceive]` `port <N>`) | Send config as separate prepended messages to the same inlet (Sections C.3, F.6) |
| Downstream sees `host s` / `port 0` instead of real values | `[t l b]` outlet types reversed in wiring expectations — outlet 0 is `l` (list), outlet 1 is `b` (bang); wiring unpack to outlet 1 feeds bangs (not the list), so unpack emits defaults | Use `[t b l]` instead: `b` on outlet 0 (left), `l` on outlet 1 (right) — fires right-to-left, so list fires first then bang, which is the destination-then-reply order |
| `[expr]` box turns red with `$f0` / `$i0` | Max's `[expr]` uses **1-indexed** inlet variables — leftmost inlet is `$f1` / `$i1` / `$s1`, NOT `$f0` / `$i0` | Shift all variable numbers up by 1: inlet 0 → `$f1`, inlet 1 → `$f2`, etc. |
| Trying to check "is this symbol empty?" with `[if ... <empty>]` or `[length]` | `<empty>` isn't a Max literal in `[if]`; `[length]` measures LIST length, not symbol-character count — always returns 1 for a single symbol | Use a separate `[value has_X]` int flag, set to 1 by the message that populates the symbol; gate downstream actions with `[gate]` controlled by the flag (Sections E.3, F.5) |
| `[udpsend]` shows red / no visible inlet | Instantiated without host+port constructor args | Re-create as `udpsend 127.0.0.1 0`. Fallback if the object's missing entirely: `mxj net.udp.send 127.0.0.1 0` |
| Feature frames arrive with one stale float | `[pack]` fires on wrong inlet first | Re-wire so address (inlet 0) fires LAST |
| Feature frames have empty track_id in address | `[value track_id_retained]` not set | Section F.5 `has_track_id` gate |
| Live rejects device with `createdevice error 6` | Patch saved via non-GUI path or hand-edited binary | Restore from `.chunk1.bak.amxd`; only ever save via Max GUI |
| Live's main thread freezes during render | `[average~]` window size or `[metro]` running on audio thread | Verify `[average~]` is at control rate, not signal |
| LUFS-M values off by ~0.3 LU vs Live's meters | 48 kHz biquad coefficients running at 44.1 kHz | Document; SR-adaptive coefficient math is post-MVP |
