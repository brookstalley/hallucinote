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
live.numbox @parameter_enable 1 @parameter_longname "OSC Port" @parameter_shortname Port @_parameter_range 11000. 11400. @_parameter_initial 11020. @_parameter_unitstyle 5
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
live.numbox @_parameter_range 11000. 11400. @_parameter_initial 11221. @parameter_enable 1 @parameter_longname "OSC Emit Port" @parameter_shortname EmitPort @parameter_modulation_mode 0
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
[udpreceive 11020]
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

### C.1. `/track_id <symbol>` — retained identity + has_track_id flag

Build this chain to the left of (or below) the existing `[OSC-route /path]`.
Two parallel responsibilities: (a) store the symbol for read-by-bang in
Section F.8, and (b) set the `has_track_id` gate-control flag that
Section F.9 consumes.

```
[OSC-route /track_id]
        │ outlet 0 (matched symbol)
        ├──→ [value track_id_retained]                  ← (a) symbol storage; read-by-bang from F.8
        │
        └──→ [t b] → [1] → [send has_track_id]          ← (b) flag set; broadcast to F.9
```

Initialize the flag at patch load (anywhere in the patch — convention is to
group all loadbang init chains together):

```
[loadbang] → [0] → [send has_track_id]                  ← flag init: gate closed at load
```

Box text:
- `value track_id_retained` — the symbol storage (read by F.8's bang)
- `t b` — converts the incoming symbol to a bang on its outlet. **Don't use
  `[t s]`** here: that would forward the path symbol to `[1]`, which can't
  coerce → "doesn't understand <symbol>" in the Max console. See learnings
  "has_path / has_track_id flag chains need `[t b]`, not `[t s]`".
- `1` — the integer 1 (the flag's "set" value)
- `send has_track_id` — broadcast to every `[receive has_track_id]` in the
  patch (Section F.9's gate is the only consumer in MVP)

**Connect:**
- `[OSC-route /track_id]` outlet 0 → `[value track_id_retained]` inlet 0
- `[OSC-route /track_id]` outlet 0 → `[t b]` → `[1]` → `[send has_track_id]`
- `[loadbang]` → `[0]` → `[send has_track_id]`

> **Why `[value]` for the symbol, but `[send]`/`[receive]` for the flag?**
> `[value]` only emits when banged, not on cold-inlet write (learnings.md
> "M4L `[value]` doesn't emit on write"). For the symbol, that's what we
> want — Section F.8 explicitly bangs it once per metro tick to fetch the
> current stored symbol. For the flag, the gate consumer in F.9 needs to
> see the value change AT THE MOMENT `/track_id` arrives, not wait for an
> explicit bang. `[send]` / `[receive]` always emits on broadcast — the
> gate updates immediately.
>
> A `[value has_track_id]` connected to a gate's control inlet would stay
> stuck at its `[loadbang]` value forever, blocking all frames even after
> `/track_id` arrived. Section F.A.3 documents this rejected alternative.

> **Note on initialization.** At patch load, `[value track_id_retained]`
> is empty (symbol `<empty>`) and `has_track_id == 0`. Section F.9's gate
> #2 is therefore closed at load — frames are NOT emitted until
> `/track_id` arrives. This prevents `/hallucinote/track//features` (with
> empty `%s`) from poisoning the sidecar's ring buffer.

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

> **`[value]` is read-by-bang, not push.** `[value]` only emits when banged,
> not on cold-inlet write (learnings.md "M4L `[value]` doesn't emit on
> write"). Section D's state machine reads these by explicitly banging
> the `[value]` boxes from its observer chain — not by relying on a
> downstream-side-effect of the cold-inlet write here.
>
> If you find yourself wanting a downstream chain to react the moment
> `/start_at_beat` or `/stop_at_beat` arrives (rather than on the next
> observer tick), use `[f]` (float) or `[i]` (int) storage instead — both
> emit on every cold-inlet write. Section D doesn't need that for the MVP.

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
> is distinct from the feature-emitter `[udpsend]` in Section F.9.
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

### D.1. The observer (canonical pattern)

The naive form — `live.observer @path live_set @property current_song_time`
as a single box with all attributes — silently fails to fire in Max
for Live (audio-analysis MVP Chunk 2 sub-chunk 2B in-Live verification,
2026-05-26). The `@property` attribute isn't honored at load and the
device's loadbang chain can be poisoned by the failed observer.

**Use the multi-box canonical pattern** instead:

```
[live.thisdevice]              ← emits bang when device fully embedded in Live
        │ outlet 0
        ▼
[live.path live_set]           ← resolves the path; emits "id <N>"
        │ outlet 0
        ▼
[live.observer]                ← receives "id <N>" → starts observing the object
```

`[live.observer]` ALSO needs to know WHICH property to observe on that
object. The `@property` attribute approach doesn't work — **send a
`property <name>` message at load** instead. Split the live.thisdevice
bang via `[t b b]`:

```
[live.thisdevice]
        │
        ▼
   [t b b]
   ├── outlet 1 (right, fires FIRST)
   │      ▼
   │   [live.path live_set] → [live.observer] inlet 0   (sets object via "id <N>")
   │
   └── outlet 0 (left, fires SECOND)
          ▼
      [message property current_song_time]
          │
          ▼
      [live.observer] inlet 0                            (sets property to observe)
```

Box text:
- `live.thisdevice` (no args)
- `live.path live_set` (path string as constructor arg)
- `live.observer` (NO @property attribute — set via message)
- `t b b` (split the device-ready bang)
- `message property current_song_time` (a MESSAGE box containing the literal `property current_song_time`)

**`live.observer` outputs only the VALUE** (a bare float), not
`<property_name> <value>` as some Max documentation suggests. Wire
its outlet directly to the downstream consumers — DO NOT insert
`[route current_song_time]` (it filters everything out because there's
no property-name prefix to match).

> **Property-name probe.** If observer doesn't fire when transport
> plays (no floats scrolling from a temp `[print obs]` on its outlet),
> the property name may be wrong for your Live version. Probe via
> `ableton_session(action='introspect', target='song', what='dir')`
> from the MCP — look for `<name>` whose paired `add_<name>_listener`
> method exists. In Live 12, `current_song_time` works.

> **Trap: keep the patcher editor closed during testing.** Max's
> patcher editor (the window you open via Live's "Edit" button) and
> Live's runtime device fight over the udpreceive socket — and
> `live.observer` may not fire when the editor is open. Save with
> Cmd-S, close the patcher window (Cmd-W on the patcher), then test.
> Re-open only to make further edits.

### D.2. Latched-state storage objects

Each `[expr]` cold inlet latches the most recently received value.
Each needs a storage box whose outlet feeds the cold inlet. **Use
`[i]` (int) and `[f]` (float)** — NOT `[value]`. Max's `[value]`
silently stores writes without emitting them downstream in current
Max for Live versions, so cold inlets fed from `[value]` outlets
never get updated (audio-analysis MVP Chunk 2 sub-chunk 2B
in-Live verification).

| Source | Storage box | Type | Feeds expr inlet |
|---|---|---|---|
| `[value start_at_beat]` (Section C.2 retainer) | `[i]` | int | inlet 2 of expr_start |
| `[value stop_at_beat]` (Section C.2 retainer) | `[i]` | int | inlet 2 of expr_stop |
| `[live.toggle (Arm)]` outlet | `[i]` | int | inlet 3 of BOTH exprs |
| `[live.observer]` outlet (deferred via `[deferlow]`) | `[f]` | float | inlet 1 of BOTH exprs |

> **Skip the `[value]` shadows entirely** — the Section C.2 retainers
> can pass their value directly through an `[i]` chain to the expr.
> So the wiring is:
>
> ```
> [OSC-route /start_at_beat] → [i] → [i] → [expr_start] inlet 2
> ```
>
> One `[i]` after the OSC route for defensive int coercion, one `[i]`
> right before the expr to provide the cold-inlet handle. NO `[value]`
> in between.

> **No `[== on]` symbol-to-int converter needed.** In current Max
> versions, `[live.toggle]` outputs **int 0 or 1** directly (not the
> symbol "off"/"on" as some older Max docs suggest). Wire
> `[live.toggle (Arm)]` outlet directly to the `[i]` for v_arm. If you
> add a `[== on]` shim, it INVERTS the value because `[== on]` coerces
> the symbol arg `on` to int 0, so it returns `1` when input is 0 and
> `0` when input is 1. Trap; just don't.

Initialize `prev_beat` at patch load. Use `[f]` (NOT `[value]`):

```
[loadbang]
        │
        ▼
   [-1.]                ← sentinel "no prior beat seen"
        │
        ▼
[f]                    ← prev_beat storage; default 0 but loadbang overrides to -1
```

Box text: `-1.` (message box containing `-1.`)

The prev_beat `[f]` ALSO has a SECOND input: a reset on Arm-rising-edge.
See Section E.4.

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
| 0 (hot)  | `$f1` | float | `[live.observer]` outlet (current_beat) | triggers eval |
| 1 (cold) | `$f2` | float | `[f]` (prev_beat storage) outlet | prior beat |
| 2 (cold) | `$i3` | int | `[i]` (start_at_beat shadow) outlet | start threshold |
| 3 (cold) | `$i4` | int | `[i]` (v_arm — direct from live.toggle) outlet | armed gate |

Wire:
- `[live.observer]` outlet → `[expr ...]` inlet 0 (will need `[deferlow]` for prev_beat update, see D.5)
- `[f]` (prev_beat) outlet → `[expr ...]` inlet 1
- `[i]` (start_at_beat shadow) outlet → `[expr ...]` inlet 2
- `[i]` (v_arm — direct from live.toggle) outlet → `[expr ...]` inlet 3

Output: 1 (true) or 0 (false) on each observer tick.

#### D.3.b. `expr_stop_crossed`

Identical box text and wiring, except inlet 2 sources from the
`[i]` shadowing `stop_at_beat` instead of `start_at_beat`.

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
[live.observer]
        │ outlet 0 (current_beat as float)
        ├─→ [expr expr_start_crossed] inlet 0 (triggers immediately)
        ├─→ [expr expr_stop_crossed] inlet 0 (triggers immediately)
        └─→ [deferlow]
                │ outlet 0
                ▼
           [f] (prev_beat)     ← updates after the current scheduler tick completes
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

**Keep `[change]` + `[sel 0 1]` for the "user pulled the cord" path AND for prev_beat reset:**
`[sel 0 1]` has two outputs — outlet 0 (matched 0, falling edge) and
outlet 1 (matched 1, rising edge). Outlet 0 drives the stop chain
("user pulled the cord"). Outlet 1 drives the prev_beat reset (see
Section E.4 below) — without it, the crossing detection fires once
at load and never again, because prev_beat gets stuck past the
start threshold.

```
[live.toggle (Arm)]
        │ outlet 0 (emits int 0 or 1 — NO [== on] needed in current Max versions)
        ▼
   [change]
        │
        ▼
   [sel 0 1]
   ├── outlet 0 (matched 0 — falling edge) → "user pulled the cord" stop path
   └── outlet 1 (matched 1 — rising edge)  → prev_beat reset (Section E.4)
```

> **No `[== on]` symbol-to-int shim needed.** In current Max versions,
> `[live.toggle]` outputs int 0/1 directly. Adding `[== on]` between
> live.toggle and downstream INVERTS the value (because `[== on]`
> coerces the symbol `on` to int 0, so `0==0→1` and `1==0→0`). Trap
> we hit during Chunk 2B verification; don't add the shim.

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
        └──→ [t b] → [1] → [value has_path]         (NEW: set flag to 1)
```

Box text:
- `t b` — converts ANY incoming message into a bang on its outlet, so
  the downstream `[1]` int box receives a bang (not the path symbol).
  Using `[t s]` here is wrong: it would forward the path symbol, which
  the int box can't coerce → "doesn't understand <path>" in the
  Max console.
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

### E.4. Reset `prev_beat` on Arm rising edge

**Load-bearing for repeatable arming.** At loadbang, prev_beat starts
at -1. The first observer tick after the patch loads might detect a
"crossing" simply because prev_beat (-1) < start_at_beat. After
`[deferlow]` updates prev_beat to the current beat, that crossing
condition is no longer satisfied — and won't be again unless prev_beat
resets.

Without a reset, you can arm + play + nothing fires (because the
crossing was already "spent" at load time, before /start_at_beat /
/path / Arm were properly set up).

**Fix:** every time Arm transitions 0→1 (a rising edge), reset
prev_beat to -1. Then the next observer tick will see prev=-1, current
slightly past 0, → can detect the upcoming crossing of start_at_beat.

Wire `[sel 0 1]` outlet 1 (matched 1 — rising edge of Arm) to the
SAME `[-1.]` message that loadbang feeds. The `[-1.]` then drives
the prev_beat `[f]`:

```
[loadbang] ──────────────┐
                         │
[sel 0 1] outlet 1 ──────┤
                         │
                         ▼
                      [-1.]              ← shared "reset to -1" message
                         │
                         ▼
                       [f] (prev_beat)
```

Two sources fire the same message. The `[f]` for prev_beat resets to
-1 on (a) device load AND (b) every arm transition.

### E.5. Wire the new stop trigger

The stop trigger fires from TWO sources OR'd together:

1. `stop_crossed_bang` (from D.4)
2. `[sel 0 1]` outlet 0 (matched 0 — falling-edge-of-Arm — "user pulled the cord")

```
   stop_crossed_bang ─────┐
                          ├──→ [t b]   (just to fan in cleanly)
   sel_0_1 outlet 0 ──────┘    │
                               ▼
                           [0]            ← the integer 0 (sfrecord~ stop+finalize)
                               │
                               ▼
                          [sfrecord~]   inlet 0
```

Box text: `0` for the message object emitting the int.

### E.6. Sanity-check the wiring

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
sk.sendto(osc('/path', '/tmp/test_chunk2b.wav'), ('127.0.0.1', 11020))
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11020))
sk.sendto(osc('/start_at_beat', 8), ('127.0.0.1', 11020))
sk.sendto(osc('/stop_at_beat', 24), ('127.0.0.1', 11020))
```

Then in Live: position playhead at bar 1, set Arm=1, press play.
Max console should print `START` at beat 8, `STOP` at beat 24.
After verifying, remove the `[print]` debug objects.

---

## Section F — Feature extraction branch

The feature extractor adds three parallel audio analyzers (LUFS-M,
sample peak, low-mid band power), packs their outputs into one OSC
frame per metro tick, and emits to the sidecar via `[udpsend]`. The
branch is a **tap** — it does not modify the audio path.

This section is dense because three trap classes converge here:

1. **Biquad coefficients are sample-rate-dependent.** A 48 kHz
   filter computed once and run at 44.1 kHz is the wrong filter. The
   MVP ships 48 kHz coefficients (the BS.1770-4 reference rate) and
   a runtime SR-mismatch warning probe (F.11). Backlog: SR-adaptive
   coefficient computation post-MVP.
2. **`[value]` doesn't emit on cold-inlet write** (see learnings
   "M4L `[value]` doesn't emit on write"). A `has_track_id` gate
   driven by `[value]` would stay stuck at its `[loadbang]` value.
   We use `[send]` / `[receive]` for the flag and reserve `[value]`
   for read-by-bang storage of the symbol itself.
3. **`[pack]` cold-inlet latch ordering.** `[pack]` fires only on
   hot inlet (inlet 0); cold inlets latch values for later. The
   three feature snapshots MUST hit the cold inlets BEFORE the
   address hits the hot inlet, or the emitted frame contains stale
   features. The metro's `[t b b b]` enforces this with
   right-to-left fire order.

Read F.0 in full before touching the patch. The traps documented
here cost hours in Chunk 2B verification; the goal of this rewrite
is to bake them into the build path.

---

### F.0. Sample-rate assumption + design assumptions

**The patch is tuned for 48 kHz session SR.** The K-weighting
biquad coefficients (F.3) and the low-mid bandpass coefficients
(F.5) are the canonical BS.1770-4 / Butterworth values pre-warped
for `Fs = 48000`. Running the patch at a different SR shifts the
filter cutoffs by `(48000 / actual_Fs)`, so:

| Session SR | LUFS-M drift | Low-mid band actually delivered |
|---|---|---|
| 48 kHz | 0.0 LU (reference) | 200–500 Hz (design) |
| 44.1 kHz | ~0.1–0.3 LU (content-dependent) | ~218–544 Hz |
| 96 kHz | ~0.2–0.5 LU | ~100–250 Hz (wrong band) |

The 44.1 kHz drift is at the edge of the MVP tolerance (spec
§"Verifying the build" → ±0.2 LU vs Live's meters). 96 kHz is out
of spec and will return wrong-band power. F.11 adds a console
warning at load time if the session SR isn't 48 kHz so the failure
mode is visible.

**SR-dependent values that ARE made adaptive at runtime** (because
sample-window sizes are cheap to compute from SR; F.3 and F.5 use
`[adstatus sr]` + `[expr $f1 * 0.4]` / `[expr $f1 * 0.1]` to set
window-in-samples):

- LUFS-M integration window: 400 ms → 19200 samples at 48 kHz,
  17640 at 44.1 kHz
- Low-mid power smoothing window: 100 ms → 4800 samples at 48 kHz,
  4410 at 44.1 kHz

Filter coefficients themselves remain hardcoded for 48 kHz — see
F.11 for the mismatch warning.

> **Backlog (post-MVP):** make biquad coefficients SR-adaptive at
> load time. Options: (a) precomputed coefficient tables for
> 44.1k / 48k / 88.2k / 96k with a `[sel]` switch on `[adstatus sr]`,
> or (b) bilinear-transform formula in `[js]` driven by `[adstatus sr]`.
> Either lifts the 48-kHz-only constraint. Out of scope for Chunk 2.

---

### F.1. Tap the audio inlet

The feature branch is a parallel TAP off the same signal Chunk 1's
`sfrecord~` records — NOT in series with the pass-through. Adding
to the existing wiring (`[plugin~]` outlet → `[plugout~]` +
`[sfrecord~]`):

```
[plugin~] outlet 0 ──┬──> [plugout~]                    (existing — pass-through)
                     ├──> [sfrecord~] inlet 1           (existing — left record)
                     └──> [send~ tap_L]                 ← NEW

[plugin~] outlet 1 ──┬──> [plugout~] outlet 1           (existing)
                     ├──> [sfrecord~] inlet 2           (existing — right record)
                     └──> [send~ tap_R]                 ← NEW
```

Box text: `send~ tap_L`, `send~ tap_R`.

Receive in the feature-extraction region (visually at the bottom of
the patch):

```
[receive~ tap_L]   [receive~ tap_R]
```

> **Why `[send~]`/`[receive~]`?** Visual clarity — direct patchcords
> across the whole patch get messy. `send~`/`receive~` add zero
> sample delay.

---

### F.2. Mono signal builder (shared by LUFS-M and low-mid)

Both LUFS-M and the low-mid extractor consume a mono signal (the
true peak extractor uses the mono sum as well, since BS.1770-4
inter-channel sum is appropriate for our peak proxy). Build it once:

```
[receive~ tap_L]   [receive~ tap_R]
        │                  │
        └──── [+~] ───┐
                       │
                       ▼
                   [*~ 0.5]                  ← halve to avoid +6 dB on sum
                       │
                       ▼
                   [send~ mono]              ← broadcast to extractors
```

Box text: `+~`, `*~ 0.5`, `send~ mono`.

> **Why halve?** Summing L+R doubles correlated content; halving
> normalizes the energy back. BS.1770-4 actually channel-sums
> *squared* values weighted by channel — for mono content, that
> reduces to summing-then-halving the squared sum, which is what
> our downstream `[*~]` self-square + `[average~]` chain produces.

Receivers in F.3, F.4, F.5: `[receive~ mono]`.

---

### F.3. K-weighted LUFS-M extractor

BS.1770-4 K-weighting: two cascaded biquads (high-shelf pre-filter
+ high-pass RLB), then mean-square over 400 ms, then `10·log10()`
with the -0.691 offset.

**Filter coefficients (48 kHz — see F.0 for SR caveat):**

```
biquad~ 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585
```

```
biquad~ 1.0 -2.0 1.0 -1.99004745483398 0.99007225036621
```

Args are `a0 a1 a2 b1 b2` (Max's `biquad~` convention: feedforward
then feedback). Source: ITU-R BS.1770-4 §2.1.2.1, pre-warped at
48 kHz. Verifiable against `pyloudnorm.Meter`'s internal
`_filter_stages` for `rate=48000`.

**The chain:**

```
[receive~ mono]
        │
        ▼
[biquad~ <stage 1 coefs above>]                ← high shelf, +4 dB at ~1.5 kHz
        │
        ▼
[biquad~ <stage 2 coefs above>]                ← high pass at ~38 Hz
        │
        ▼   (K-weighted signal)
        │
        ├──→ [*~] inlet 0
        └──→ [*~] inlet 1                      ← self-multiply: x²
                 │
                 ▼
            [average~ 19200 bipolar]           ← 400 ms at 48 kHz — REPLACED at load (see SR adapter below)
                 │
                 ▼
            [snapshot~]                        ← banged by metro (F.7)
                 │
                 ▼
            [clip 1e-12 1e10]                  ← clamp floor: log10(1e-12)·10 = -120 LU
                 │                               (ceiling 1e10 is a safety net — real audio
                 ▼                                mean-square stays well below)
            [expr 10. * log10($f1) - 0.691]
                 │
                 ▼
            [send lufs_m_value]                ← float, LUFS units (LU above silence)
```

Box text in order: `biquad~ <stage 1 coefs>`, `biquad~ <stage 2 coefs>`,
`*~` (no args; both inlets used for self-square), `average~ 19200 bipolar`,
`snapshot~`, `clip 1e-12 1e10`, `expr 10. * log10($f1) - 0.691`,
`send lufs_m_value`.

> **Why `[clip <floor> <ceiling>]` upstream, not a conditional / function inside `[expr]`?**
> M4L's bundled `[expr]` has neither `if(cond, then, else)` (returns
> "function if not found") nor `max(a, b)` (also "function max not
> found") nor reliable ternary `? :` parsing. The function vocabulary
> is limited to `abs / ceil / floor / int / float / exp / log / log10 /
> fact / ln / pow / sqrt / rand / random` plus the trig family — no
> conditionals or min/max. (Some Max docs list `max()` but it's
> empirically absent in M4L's runtime — confirmed during Chunk 2B
> verification.)
>
> `[clip <floor> <ceiling>]` is a standard Max control-rate object —
> space-separated args (no comma escape headaches), single inlet/outlet,
> clamps each incoming number to `[<floor>, <ceiling>]`. Floor selection
> below picks the value so silence maps to the sidecar's -120 dB
> sentinel; the ceiling is a far-from-real-audio safety net that
> exists just to satisfy `[clip]`'s two-arg signature.
>
> | Extractor | Input domain | `[clip <floor> <ceil>]` | Output at floor |
> |---|---|---|---|
> | LUFS-M (mean-square) | non-negative power | `clip 1e-12 1e10` | `10·log10(1e-12) - 0.691 = -120.69` |
> | Peak (linear amplitude 0-1) | non-negative amplitude | `clip 1e-6 1.0` | `20·log10(1e-6) = -120.0` |
> | Low-mid (mean-square) | non-negative power | `clip 1e-12 1e10` | `10·log10(1e-12) = -120.0` |
>
> Same `[clip]` pattern in F.4 (peak) and F.5 (low-mid). `[clip]` also
> kills any rare-but-possible negative outputs from `[average~]` due
> to floating-point error near zero (which would make `log10` return
> NaN). The expr stays simple — just the actual log10 math.
>
> **Why not `[expr~]` (signal-rate)?** `[snapshot~]` (and `[peakamp~]`)
> intentionally convert from signal-rate to control-rate. Going back
> to signal-rate for the log10 would require an extra `[snapshot~]`
> on the way back to feed `[pack]`. The "int16 limit" hinted at in
> some Max docs doesn't apply to `[expr]`'s float math — `$f<N>`
> variables operate in 32-bit float, and our values (mean-square
> ~1e-12 to ~1e0, log results -120 to 0) are well within range.

> **Why `bipolar` on `[average~]`?** It computes the simple mean of
> the signal (no abs, no sqrt). Since x² is non-negative, the result
> is mean-of-squares — exactly what BS.1770 §2.1.3 requires.
>
> **The -0.691 offset** is the BS.1770 calibration constant for
> single-channel loudness — see the standard for derivation.
>
> **`-120.` as the silence floor** stands in for log(0) = -∞. The
> sidecar's ring buffer treats -120 dBFS / LUFS as "effectively
> silent." Don't lower this — `-120.` is a sentinel value the
> sidecar can distinguish from real-but-quiet content.

**SR-adaptive window size** (sets `[average~]` window correctly even
when session SR isn't 48 kHz):

```
[loadbang]
        │
        ▼
[adstatus sr]
        │ outlet 0 (current SR, float)
        ▼
[expr $f1 * 0.4]                                ← 400 ms expressed in samples = SR * 0.4
        │
        ▼
[i]                                             ← coerce to int (samples must be int)
        │
        ▼
(connect to [average~ ... bipolar] LEFT INLET — same inlet as the audio signal)
```

Box text: `adstatus sr`, `expr $f1 * 0.4`, `i`.

> **`[average~]` has only one inlet.** It shares that inlet between
> the audio signal (left audio connection via `~`) and control
> messages (a number message sets the window size in samples).
> Same single-inlet multiplexing pattern as `[peakamp~]` (which
> takes the signal on its left inlet and accepts a runtime int
> message on the same inlet to change its reporting interval).
> Max disambiguates by message type — the `~` connection carries
> signal; the non-`~` connection from `[i]` carries the int window
> message. They don't collide.
>
> The constructor arg (`19200`) is the default until a runtime
> message updates it. Loadbang-then-`[adstatus sr]` recomputes and
> updates the window before the first metro tick.

---

### F.4. Sample-peak extractor

`[peakamp~]` is **self-clocked** via its constructor arg (reporting
interval in ms). It accumulates the peak over each interval and
auto-emits + resets at the boundary. No bang from the metro fan-out
is needed — `[peakamp~]` runs on its own ~30 Hz clock and feeds
`[pack]`'s cold inlet whenever it has a fresh value.

```
[receive~ mono]
        │
        ▼
   [peakamp~ 33]                                 ← auto-emit every 33 ms (~30 Hz, matches metro rate)
        │ outlet 0 (linear peak since last emission)
        ▼
   [clip 1e-6 1.0]                               ← clamp: silence → -120 dBFS
        │
        ▼
   [expr 20. * log10($f1)]
        │ outlet 0 (peak in dBFS)
        ▼
   [send peak_dbfs_value]
```

Box text: `peakamp~ 33`, `clip 1e-6 1.0`, `expr 20. * log10($f1)`,
`send peak_dbfs_value`.

> **Why `[peakamp~ 33]` self-clocked instead of metro-banged?** In
> M4L's bundled Max, `[peakamp~]` with no argument doesn't reliably
> emit on bang to the left inlet — the canonical control surface is
> the integer-interval constructor arg (or right-inlet int message).
> Configured with `33`, it auto-emits every 33 ms, which matches
> the metro's ~30 Hz cadence well enough that `[pack]`'s cold inlet
> 2 always holds a peak value at most ~33 ms old when the metro
> fires.
>
> **Why `20·log10`** (not `10·log10`)? Sample peak is an amplitude,
> not a power. dBFS for amplitude is `20·log10`.
>
> **Phase note.** `[peakamp~ 33]` and `[metro 33]` run on independent
> clocks — they're not phase-aligned. The peak value latched in
> `[pack]`'s cold inlet 2 at metro tick time is between 0 and 33 ms
> old. For MVP-grade peak reporting at 30 Hz this is fine; the peak
> still captures any transients in the most recent ~33 ms window.
> If precise phase alignment is ever needed (Chunk 3 offline analysis
> doesn't care — it reads peaks from the WAV directly), use a
> shorter `[peakamp~]` interval like `10`, accepting more frequent
> stale-window-bounded reporting.

---

### F.5. Low-mid (200–500 Hz) band-power extractor

Two cascaded biquads (HP at 200 Hz, LP at 500 Hz), square, average
over 100 ms, snapshot, log.

**Filter coefficients (48 kHz — see F.0 for SR caveat):**

HP at 200 Hz (Butterworth 2-pole):
```
biquad~ 0.97803 -1.95606 0.97803 -1.95558 0.95654
```

LP at 500 Hz (Butterworth 2-pole):
```
biquad~ 0.00102 0.00205 0.00102 -1.95558 0.95968
```

Source: scipy `signal.butter(2, [200, 500], btype='bandpass', fs=48000)`,
factored into separate HP + LP biquads for clarity (cascade-equivalent
to a single 2nd-order bandpass).

**The chain:**

```
[receive~ mono]
        │
        ▼
[biquad~ <HP coefs above>]
        │
        ▼
[biquad~ <LP coefs above>]                      ← band-passed signal
        │
        ├──→ [*~] inlet 0
        └──→ [*~] inlet 1                       ← self-square
                 │
                 ▼
            [average~ 4800 bipolar]             ← 100 ms at 48 kHz — REPLACED at load
                 │
                 ▼
            [snapshot~]                         ← banged by metro
                 │
                 ▼
            [clip 1e-12 1e10]                   ← clamp: silence → -120 dB
                 │
                 ▼
            [expr 10. * log10($f1)]
                 │
                 ▼
            [send low_mid_power_value]          ← float, dB relative to full scale
```

Box text: same pattern as F.3; biquads with the LP/HP coefs above;
`average~ 4800 bipolar`; `snapshot~`; the expr; `send low_mid_power_value`.

**SR-adaptive window** (parallels F.3's adapter — same single-inlet
multiplexing of signal + window-size message):

```
[loadbang] → [adstatus sr] → [expr $f1 * 0.1] → [i]
                                                  │
                                                  ▼
                              (connect to [average~ ... bipolar] LEFT INLET — same inlet as the audio signal)
```

> **Why `10·log10`** (not `20·log10`)? Power, not amplitude. dB for
> power is `10·log10`.

> **Same `[adstatus sr]` object as F.3?** No — drop a SECOND
> `[adstatus sr]` for the low-mid window. (Or share one and fan its
> outlet to both `[expr]` adapters; either works. Two boxes is
> simpler to wire.)

---

### F.6. `has_track_id` gate control — driven by `[send]` / `[receive]`

The feature emitter must NOT emit frames with an empty `<track_id>`
in the address (sidecar's ring buffers are keyed by track_id; an
empty key would poison every subsequent lookup). A `[gate]` in F.9
controlled by `has_track_id` is the kill switch.

The flag is set by Section C.1's `/track_id` route (which see — C.1
needs the amendment shown below) and read by F.9's gate.

**Section C.1 amendment** — wire alongside the existing
`[value track_id_retained]` storage:

```
[OSC-route /track_id]
        │ outlet 0 (the symbol)
        ├──→ [value track_id_retained]              (existing — symbol storage, read by F.8)
        └──→ [t b] → [1] → [send has_track_id]      ← NEW
```

Box text on the new chain:
- `t b` — converts the incoming symbol into a bang on its outlet, so
  the downstream `[1]` int box receives a bang (not the symbol).
  Using `[t s]` would forward the symbol; `[1]` would then refuse with
  `"doesn't understand <symbol>"` in the Max console.
- `1` — the integer 1 (the flag's "set" value)
- `send has_track_id` — broadcasts to every `[receive has_track_id]`
  in the patch

**Initialize the flag at patch load** (also in Section C.1):

```
[loadbang] → [0] → [send has_track_id]
```

**Read in F.9** (the gate consumer):

```
[receive has_track_id]                  ← emits 0 at load, 1 once /track_id received
        │ outlet 0 (int)
        ▼
   (drives the second [gate]'s control inlet 0 — F.9)
```

> **Why `[send]` / `[receive]`, not `[value has_track_id]`?**
> `[value]` only emits when banged, not on cold-inlet write
> (learnings.md "M4L `[value]` doesn't emit on write"). A
> `[value has_track_id]` connected to a gate's control inlet would
> never update the gate — the gate would stay at whatever value
> reached it during init, blocking all frames forever even after
> `/track_id` arrived. `[send]` / `[receive]` always emit on
> broadcast, so the gate's control updates on the rising edge of
> `/track_id`.

> **Why not `[i has_track_id]`?** Max's `[i]` (alias for `[int]`)
> can't be named the way `[value]` can — there's no shared-state
> binding by name across patcher regions. `[send]` / `[receive]`
> is the canonical named-broadcast in Max.

---

### F.7. Beat-position latch + metro fan-out

#### F.7.1. Beat-position latch (consumed by `[pack]` cold inlet 1)

Each OSC frame carries the transport beat position at which it
was sampled (see Spec "OSC feature emitter → Frame shape" — `beat_position`
is payload[0], the convention being "first float is always the
sample timestamp; remaining floats are features in documented
order"). This lets the sidecar reconcile frames across analyzers
that aren't phase-aligned and across UDP delivery skew.

Reuse Section D's existing `[live.observer current_song_time]`
without re-instantiating an observer. Fork the observer's outlet
via `[t f f]` so:
- One branch continues into Section D's existing transport-crossing
  logic (unchanged).
- The new branch updates `[f beat_pos_latched]` — a control-rate
  float storage that holds the most recent beat position.

```
(Section D's [live.observer] outlet — current_song_time, bare float)
        │
        ▼
   [t f f]                          ← fork: forward float to two destinations
   ├── outlet 1 (right, fires FIRST) → (existing Section D chain — change/deferlow/expr crossing)
   └── outlet 0 (left, fires SECOND) → [f beat_pos_latched] (right inlet — cold-stores the float)
```

Box text: `t f f`, `f beat_pos_latched`.

The metro tick (F.7.2 below) bangs `[f beat_pos_latched]` from its
new outlet 1, causing the stored float to emit into `[pack]`'s
cold inlet 1.

> **Why `[f]` and not `[value]`?** Per the M4L `[value]`-doesn't-emit
> learning, `[value beat_pos_latched]` would silently fail to emit
> when the metro bangs it. `[f]` (float) emits on every bang AND on
> every cold-inlet write. Same fix shape as has_path and
> prev_beat from earlier sections.
>
> **Why `[t f f]` not direct multi-cord?** Two fans on the
> observer's outlet would still work (Max allows multiple cords
> from one outlet), but `[t f f]` makes the ordering explicit:
> outlet 1 (right, fires first) into the existing D-section state
> machine, outlet 0 (left, fires second) into the new latch. That
> matters if you ever add downstream logic that depends on
> "Section D evaluated this beat first, then F latched it."
>
> **Semantics during transport stop.** `[live.observer]` holds its
> last value when transport stops, so frames during silence carry
> the last play-position. Sidecar contract: "beat_position is
> song-time-in-beats at the moment of emission; identical values
> across frames indicate transport stopped between them; differing
> values across tracks at 'the same' wall-clock moment quantify
> inter-analyzer skew."

#### F.7.2. Metro and ordered fan-out

The metro fires at ~30 Hz. Each tick must:

1. Bang the two `[snapshot~]` extractors (LUFS-M, low-mid) so their
   `[expr]` outputs latch cold inlets 2 and 4 of
   `[pack s f f f f]` (F.8). `[peakamp~ 33]` is self-clocked (F.4)
   and emits into cold inlet 3 on its own schedule — no metro bang.
2. Bang `[f beat_pos_latched]` (F.7.1) so it emits the stored beat
   into `[pack]`'s cold inlet 1.
3. THEN bang `[value track_id_retained]` so it emits the symbol
   into `[sprintf]` (F.8), which then hits `[pack s f f f f]`'s
   hot inlet 0 — firing the pack with all five values latched.

**Ordering matters.** `[pack]` fires only when its HOT (leftmost,
inlet 0) inlet receives a value. Cold inlets latch silently. If
the address hits inlet 0 BEFORE the snapshots / beat-latch have
updated their cold inlets, the emitted list contains stale values
from the previous tick. (Peak's cold inlet 3 is always
"current within ~33 ms" since `[peakamp~]` runs continuously —
no ordering concern there.)

`[t b b b b]` fires its outlets **right-to-left**. So outlet 3
(rightmost) fires FIRST, outlet 0 (leftmost) fires LAST. Wire the
address chain to outlet 0 so it fires after all three cold-inlet
sources have updated.

```
[loadbang]
    │
    ▼
[1]                                     ← turn the metro on at load
    │
    ▼
[metro 33]                              ← 33 ms ≈ 30.3 Hz
    │ outlet 0 (bang)
    ▼
[t b b b b]
    ├── outlet 3 (rightmost — fires FIRST)
    │      ▼
    │   bang [snapshot~] inlet 0 (low-mid, F.5)  → updates pack cold inlet 4
    │
    ├── outlet 2
    │      ▼
    │   bang [snapshot~] inlet 0 (LUFS-M, F.3)   → updates pack cold inlet 2
    │
    ├── outlet 1
    │      ▼
    │   bang [f beat_pos_latched] (F.7.1)        → updates pack cold inlet 1
    │
    └── outlet 0 (leftmost — fires LAST)
           ▼
       (to F.8's address chain — see next section)
```

Box text: `1`, `metro 33`, `t b b b b`.

> **Why depth-first ordering matters here.** Max scheduling runs
> each `[t]` outlet's downstream cascade to completion before the
> next outlet of `[t]` fires. So outlet 3's bang propagates through
> `[snapshot~]` (low-mid) → `[expr]` → `[send low_mid_power_value]`
> → `[receive low_mid_power_value]` → `[pack]` inlet 4 (cold latch)
> completely BEFORE outlet 2 fires. Same for the LUFS-M chain on
> outlet 2 and the beat-latch on outlet 1. When outlet 0 finally
> fires, all three cold-inlet destinations from the metro tick
> hold fresh values from THIS tick.
>
> If any extractor included a `[deferlow]` or async element, this
> guarantee would break. The two snapshot extractors and the
> beat-latch are all synchronous — no deferral.
>
> `[peakamp~ 33]` (F.4) is asynchronous to this chain — it pushes
> into `[pack]` cold inlet 3 on its own ~30 Hz clock, independent
> of the metro. That's fine because cold-inlet writes always
> succeed (they just latch), and the pack only fires when the
> HOT inlet hits — which happens here, after the three
> synchronous-to-metro inlets have propagated.

> **Why `[1]` from loadbang to `[metro 33]`?** Metro's left inlet
> takes 0/1 to stop/start. We want it always-on from patch load.
> An alternative is `[metro 33 @active 1]` (loadbang start built
> in), but the explicit `[1] → [metro]` pattern is more visible to
> a future patcher reader.

---

### F.8. Address builder and `[pack]`

The metro's outlet 0 (F.7.2) bangs the address chain:

```
(metro's [t b b b b] outlet 0)
        │
        ▼
   [value track_id_retained]            ← banged → emits the stored symbol
        │ outlet 0 (symbol)
        ▼
   [sprintf /hallucinote/track/%s/features]
        │ outlet 0 (symbol — the full OSC address)
        ▼
   (to [pack s f f f f] inlet 0 — hot, fires the pack)
```

Box text: `sprintf /hallucinote/track/%s/features`.

Pack cold-inlet layout (5 inlets total: 1 hot symbol + 4 cold floats):

| Inlet | Type | Source | Latched by |
|---|---|---|---|
| 0 (HOT) | symbol | `[sprintf]` outlet | metro outlet 0 — fires the pack |
| 1 (cold) | float | `[f beat_pos_latched]` outlet (F.7.1) | metro outlet 1 bangs the [f] |
| 2 (cold) | float | `[receive lufs_m_value]` outlet | metro outlet 2 bangs LUFS-M's [snapshot~] |
| 3 (cold) | float | `[receive peak_dbfs_value]` outlet | `[peakamp~ 33]` self-clocked emission (F.4) |
| 4 (cold) | float | `[receive low_mid_power_value]` outlet | metro outlet 3 bangs low-mid's [snapshot~] |

Box text: `pack s f f f f`.

> **Why `[pack]` not `[pak]`?** `[pack]`'s hot inlet is leftmost,
> cold inlets are right. `[pak]` fires on ANY inlet change (hot
> on every inlet) — each fire emits with whatever is currently
> latched, producing N near-identical packets per tick with
> partial updates. `[pack]` is the right primitive for
> "fire-once-per-tick with all-fresh cold-latched values."
>
> **Why `s f f f f` (5 inlets) — not separate prepend / pak?**
> `[pack s f f f f]` declares the type signature: a symbol followed
> by four floats. The outlet emits a flat list
> `<symbol> <f> <f> <f> <f>` which `[udpsend]` packs as an OSC
> message with address (the symbol) and `,ffff` type-tagged
> payload. To add more features later, widen the pack to
> `s f f f f f` and append the new `[receive]` to the new cold
> inlet — `beat_position` stays pinned at index [0] of the float
> args.

`[pack s f f f f]` outlet emits the complete frame:
`<address> <beat_pos> <lufs> <peak> <low_mid>`.

---

### F.9. Output gates and `[udpsend]`

Two `[gate]`s in series — kill switches that block the frame if
either condition isn't met:

```
[pack s f f f] outlet
        │
        ▼
   [gate]                                   ← gate #1: controlled by Emit param
        │ control inlet 0 (left): driven by [live.toggle (Emit)] outlet
        │ message inlet 1 (right): the frame list
        ▼
   [gate]                                   ← gate #2: controlled by has_track_id flag
        │ control inlet 0: driven by [receive has_track_id] (F.6)
        │ message inlet 1: the frame list
        ▼
   [udpsend 127.0.0.1 11221]                ← single inlet — frame data, also config msgs (F.10)
```

Box text: `gate`, `gate`, `udpsend 127.0.0.1 11221`.

> **Max `[gate]` semantics.** A `[gate]` (or `[gate 1 0]` —
> 1 outlet, initially closed) has TWO inlets:
> - **Left inlet (inlet 0): control.** Receives 0 (close) or 1
>   (open). Stored internally.
> - **Right inlet (inlet 1): message.** Receives the data flow.
>   Forwarded to the outlet ONLY when control == 1.
>
> Wire the data IN on the RIGHT inlet, the control on the LEFT.
> Reversing them is a silent failure mode.

> **`[live.toggle]` outlet emits int 0/1 directly** (learnings.md
> "M4L `[live.toggle]` outlet emits int (0/1) directly"). Wire it
> DIRECTLY to gate #1's control inlet — no `[== on]` or `[sel on]`
> shim. The shim inverts the value because Max coerces the symbol
> arg `on` to int 0.

---

### F.10. `EmitPort` retarget chain

`[live.numbox (EmitPort)]` writes propagate to the `[udpsend]` so a
runtime port change re-targets the destination. The pattern
mirrors Section C.3's signature-reply `[udpsend]` retarget:

```
[live.numbox (EmitPort)] outlet 0
        │ (float — Type=Float, Unit Style=Int per Section B.1)
        ▼
   [i]                                     ← coerce float→int
        │
        ▼
   [prepend port]                          ← emits list: "port <N>"
        │
        ▼
   (to [udpsend 127.0.0.1 11221] inlet 0 — same single inlet as the frame data)
```

Box text: `i`, `prepend port`.

> **`[udpsend]` has ONE inlet.** Frame data AND config messages
> (`host <sym>`, `port <int>`) all enter through inlet 0.
> `[udpsend]` disambiguates internally by the leading symbol —
> `port` and `host` are config; anything else is data forwarded to
> the network. See learnings "udpsend has one inlet, retarget via
> host/port messages".
>
> **Constructor args 127.0.0.1 11221 are placeholders** — they get
> overwritten by the `port <N>` message at first
> `[live.numbox (EmitPort)]` emission (which fires at loadbang via
> Inspector's "Initial Enable: Yes" — see Section B.1). The
> placeholder values prevent the object from rendering
> red/unresolved in Max. See learnings "udpsend needs host+port
> constructor args even when overridden dynamically".

**No host retarget needed** — the sidecar is always on 127.0.0.1
for the MVP. If the design ever needs cross-machine emission, add
a sibling `[prepend host]` chain analogous to C.3.a.

---

### F.11. SR-mismatch warning probe

Print a Max-console warning at patch load (and on driver SR change)
if the session SR isn't 48 kHz:

```
[loadbang]
    │
    ▼
[adstatus sr]                                       ← also re-emits on driver SR change
    │ outlet 0 (current SR, float)
    ▼
[== 48000.]
    │ outlet 0 (1 if 48k, 0 if not)
    ▼
[sel 0]                                             ← match: SR != 48k
    │ outlet 0 (bang on mismatch)
    ▼
[message HallucinoteAnalyzer: WARNING — LUFS coefficients tuned for 48 kHz; session SR differs (see F.0 in AUTHORING-CHUNK-2B.md). LUFS readings will drift ~0.1-0.3 LU at 44.1 kHz.]
    │
    ▼
[print HallucinoteAnalyzer]
```

Box text:
- `adstatus sr`
- `== 48000.`
- `sel 0`
- `message ...` (a message box containing the warning text shown above)
- `print HallucinoteAnalyzer`

> **Why `48000.` (float)?** `[adstatus sr]` emits a float. `[== 48000]`
> with an int arg compares int-to-float, which works in Max but is
> less robust than float-to-float. The `.` is cheap insurance.

> **Re-emit on SR change.** `[adstatus sr]` re-emits whenever Live's
> audio driver SR changes (the user toggles Live's Audio preferences
> mid-session, say). The mismatch warning will re-print, which is
> the desired behavior.

---

### F.12. Full assembly diagram (sanity check)

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
       │                          (self-clocked,                     │
       ▼                           auto-emits ~30 Hz)                ▼
[biquad~ HP RLB]                       │                       [biquad~ LP 500]
       │                               │                             │
       ▼                               ▼                             ▼
[*~ self-square]               [clip 1e-6 1.0]                 [*~ self-square]
       │                               │                             │
       ▼                               ▼                             ▼
[average~ <19200> bipolar]    [expr 20·log10($f1)]            [average~ <4800> bipolar]
   (window set by [adstatus sr]        │                          (window set by [adstatus sr]
    × 0.4 at load — same                ▼                           × 0.1 at load — same
    inlet as the signal)         [send peak_dbfs_value]             inlet as the signal)
       │                                                             │
       ▼                                                             ▼
[snapshot~]                                                    [snapshot~]
       │                                                             │
       ▼                                                             ▼
[clip 1e-12 1e10]                                              [clip 1e-12 1e10]
       │                                                             │
       ▼                                                             ▼
[expr 10·log10($f1) - 0.691]                                  [expr 10·log10($f1)]
       │                                                             │
       ▼                                                             ▼
[send lufs_m_value]                                           [send low_mid_power_value]


(Section D's [live.observer] outlet — current_song_time)
                  │
                  ▼
              [t f f]
              ├── outlet 1 (FIRST) → existing Section D crossing-detection chain
              └── outlet 0 (SECOND) → [f beat_pos_latched] (cold-stores the float)
                                              │
                                              │ (banged by metro outlet 1)
                                              ▼

[metro 33] → [t b b b b]
                  │
                  ├── outlet 3 (FIRST)  → bang [snapshot~ low-mid]
                  ├── outlet 2          → bang [snapshot~ LUFS-M]
                  ├── outlet 1          → bang [f beat_pos_latched]
                  └── outlet 0 (LAST)   → bang [value track_id_retained]
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
                                       │            beat into in1 (cold)
                                                    lufs into in2 (cold)
                                                    peak into in3 (cold)
                                                    low_mid into in4 (cold)
                                       │
                                       ▼  (right inlet — message)
                                  [gate]  ← control inlet 0 (left): [live.toggle Emit]
                                       │
                                       ▼  (right inlet — message)
                                  [gate]  ← control inlet 0 (left): [receive has_track_id]
                                       │
                                       ▼
                          [udpsend 127.0.0.1 11221]
                                       ▲
                                       │ (config msg path)
                          [prepend port]
                                       ▲
                          [i]
                                       ▲
                          [live.numbox (EmitPort)] outlet
```

Section C.1 amendment (separately):
```
[OSC-route /track_id]
       ├──→ [value track_id_retained]                  (existing)
       └──→ [t b] → [1] → [send has_track_id]          (NEW — F.6 consumer)
[loadbang] → [0] → [send has_track_id]                 (NEW — init flag closed)
```

SR-mismatch warning probe (separately):
```
[loadbang] → [adstatus sr] → [== 48000.] → [sel 0] → [message WARNING ...] → [print HallucinoteAnalyzer]
```

---

### F.13. Pre-save probe checklist

Add these temporary `[print]` boxes BEFORE saving. Verify each
prints what's expected, then DELETE the prints before `Cmd-S`.

| What to probe | Where to add `[print]` | Expected on transport play with audio |
|---|---|---|
| Tap signal alive | between `[+~]` and `[*~ 0.5]` — add `[snapshot~] → [print TAP_SUM]` banged by a temp `[metro 100]` | non-zero floats when audio is playing |
| K-weighted signal | after second `biquad~` (HP RLB) — add `[snapshot~] → [print K_OUT]` banged by same temp metro | floats; values smaller in magnitude than TAP_SUM for low-freq-heavy content |
| LUFS-M raw mean-square | between `[average~]` and `[snapshot~]` — temp `[snapshot~ T] → [print LUFS_RAW]` | small positive floats (e.g., 1e-3 to 1e-1 for typical music). Silence: tiny values approaching 0 — the `max($f1, 1e-12)` inside the expr clamps these so log10 never sees zero |
| LUFS-M output | on outlet of LUFS expr — `[print LUFS_M]` | typical music: -28 to -10 LUFS. Silence: -120. |
| Peak output | on outlet of peak expr — `[print PEAK]` | typical music: -20 to -1 dBFS. Silence: -120. |
| Low-mid output | on outlet of low-mid expr — `[print LOWMID]` | typical music: -40 to -10 dB. Silence: -120. |
| Metro firing | between `[metro 33]` and `[t b b b]` — `[print METRO]` | `METRO: bang` printing ~30×/sec |
| Peakamp self-clocking | between `[peakamp~ 33]` outlet and `[max 1e-6]` — `[print PEAK_RAW]` | `PEAK_RAW: <linear-amplitude-float>` printing ~30×/sec even without metro running (peakamp~ has its own clock) |
| Beat-position latch | on outlet of `[f beat_pos_latched]` — `[print BEAT]` | float that increases during transport play, holds steady during stop. Same value Section D's expr boxes see |
| Pack output | between `[pack s f f f f]` outlet and gate #1 — `[print FRAME]` | one list per metro tick: `FRAME: /hallucinote/track/<id>/features 18.250 -23.4 -8.1 -32.7` — note 4 floats now (beat first) |
| Gate #1 control (Emit) | on `[live.toggle (Emit)]` outlet — `[print EMIT_TOGGLE]` | `EMIT_TOGGLE: 1` when Live UI shows Emit on |
| Gate #2 control (has_track_id) | on `[receive has_track_id]` outlet — `[print HAS_TID]` | `HAS_TID: 0` at load; `HAS_TID: 1` after `/track_id` arrives |
| EmitPort value path | between `[i]` and `[prepend port]` — `[print EMITPORT_INT]` | initial value once at load, then on every Live UI change |
| SR mismatch | the F.11 warning's `[print HallucinoteAnalyzer]` | nothing if session is 48 kHz; warning line if not |

**Workflow per probe:** add the probe, `Cmd-S`, **`Cmd-W` to close
the patcher window** (Max editor and Live runtime fight over
udpreceive — see Section G.0 / learnings "M4L patcher editor and
Live runtime fight over udpreceive"), test, re-open patcher to
delete probe and add next one. Re-opening Max console (separate
window: `Window → Max Console`) is fine — that's the print sink,
not the patcher.

End-state: NO `[print]` objects in the patch. Section G's broader
tests then run against the clean patch.

---

### F.A. Appendix — Rejected designs

Documented so future readers don't re-derive these from scratch.

**A.1. `[pak s f f f]` instead of `[pack s f f f]`** — rejected
because `[pak]` fires on ANY inlet change, emitting multiple
near-identical packets per metro tick (one per snapshot update,
each with the other features stale from the previous tick).
`[pack]` fires only on hot-inlet (leftmost), making the address
chain the explicit "tick boundary."

**A.2. `[message $1 $2 $3 $4]` for address-plus-floats list
construction** — rejected because Max's `[message]` only has TWO
inlets (inlet 0 fires the message, inlet 1 sets the message
contents via a list). It does NOT have per-`$N` inlets.
`[pack s f f f]` is the canonical primitive for typed list
construction.

**A.3. `[value has_track_id]`** (instead of `[send]` / `[receive]`)
— rejected per learnings.md "M4L `[value]` doesn't emit on write":
the gate's control inlet would never update from a cold-inlet
write to `[value]`. `[send]` / `[receive]` always emits on
broadcast. (Section C.1 still uses `[value track_id_retained]` for
the SYMBOL storage because F.8 explicitly bangs it via the
`[t b b b b]` leftmost outlet — read-by-bang is `[value]`'s
documented use case.)

**A.4. `[length] → [> 0]` to test "is `[value track_id_retained]`
empty?"** — rejected because Max's `[length]` measures *list*
length, not *symbol* character count. A symbol arriving at
`[length]`'s inlet returns 1 (a single-element list of one
symbol), which makes `[> 0]` always true — defeating the gate.
The `[send has_track_id]` flag avoids string introspection
entirely.

**A.5. SR-adaptive biquad coefficients via `[js]` or
`[filtergraph~]`** — rejected for MVP because (a) `[js]`
introduces a runtime JavaScript dependency that's brittle across
Max versions, (b) `[filtergraph~]`'s coefficient outputs are
intended for `[cascade~]` / `[biquad~]` runtime configuration but
add visual-editor complexity. The 48 kHz coefs + F.11 mismatch
warning is the MVP-grade trade-off; backlog will replace with
runtime-SR-adaptive coefficients (likely via precomputed tables
per SR with `[sel 44100 48000 88200 96000]` switching).

**A.6. Per-channel BS.1770 weighted sum (channel weights 1.0 + 1.0
for stereo)** — rejected as overkill for MVP. The mono-sum
approximation (F.2) is within the spec's ±0.2 LU tolerance for
typical stereo content. Full per-channel BS.1770 (squared-energies
summed with channel weights, then K-weight applied per channel)
becomes warranted if PSR or multichannel content (5.1, immersive)
is ever in scope — out of scope here.

---


## Section G — In-Max sanity tests (before saving)

Before `Cmd-S`-ing the patch, verify each Chunk 2 addition with
console probes. The Max console (`Cmd-M`) is your friend.

> **CRITICAL workflow rule — close the patcher editor between tests.**
> Max's patcher editor (the window opened via Live's "Edit" button)
> and Live's runtime device fight over the `udpreceive` socket. With
> the patcher editor open, the runtime device's udpreceive may fail
> to bind, AND `live.observer` may silently not fire. Symptom: OSC
> messages reach SOMETHING but the wrong instance; recording never
> starts. Workflow: open the patcher to make changes, `Cmd-S` to save,
> **`Cmd-W` to close the patcher window** (NOT Cmd-Q on Max — just
> close the patcher; keep `Window → Max Console` open to watch prints).
> Re-open the patcher only when you need to edit further.
> See learnings.md "M4L editor vs Live runtime UDP conflict".

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
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11020))
sk.sendto(osc('/start_at_beat', 16), ('127.0.0.1', 11020))
sk.sendto(osc('/stop_at_beat', 32), ('127.0.0.1', 11020))
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
    ("127.0.0.1", 11020),
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

Bind a listener on 11221 (the default `EmitPort`):

```python
import socket, struct, time

sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sk.bind(("127.0.0.1", 11221))
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
- Payload type tag `,ffff` followed by 16 bytes (4 floats):
  `[beat_position, lufs_m, peak_dbfs, low_mid_power]`. With
  transport playing, `beat_position` advances frame-over-frame.
  With transport stopped, it holds the last play-position
  unchanged.

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
sk.sendto(osc('/path', '/tmp/chunk2b_smoketest.wav'), ('127.0.0.1', 11020))
sk.sendto(osc('/track_id', 'test:1'), ('127.0.0.1', 11020))
sk.sendto(osc('/start_at_beat', 4), ('127.0.0.1', 11020))
sk.sendto(osc('/stop_at_beat', 12), ('127.0.0.1', 11020))
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
| `adstatus sr` | current session sample rate (re-emits on driver change) | F.3, F.5, F.11 |
| `average~ <samples> bipolar` | sliding mean of signal | F.3, F.5 |
| `biquad~ a0 a1 a2 b1 b2` | 2-pole filter section | F.3 (K-weighting), F.5 (band-pass) |
| `change` | emit only on value change | E.2 |
| `clip <floor> <ceiling>` | clamp control-rate value to range; single inlet/outlet, space-separated args | F.3 (`1e-12 1e10`), F.4 (`1e-6 1.0`), F.5 (`1e-12 1e10`) |
| `deferlow` | push to low-priority queue | D.5 |
| `expr <expression>` | evaluate arithmetic; function vocabulary in M4L: `abs / ceil / floor / int / float / exp / log / log10 / fact / ln / pow / sqrt / rand / random` + trig. **No conditionals, no `max` / `min`** — use upstream `[clip]` / `[gate]` instead | D.3, F.3, F.4, F.5 |
| `gate` | gate a signal/message by control | E.3, F.9 |
| `i` | int truncator / storage with emit-on-write | C.2, F.3, F.5, F.10 |
| `live.numbox` | Live parameter (numeric) | A, B.1, F.10 |
| `live.observer` | Live LOM property observer | D.1 |
| `live.thisdevice` | self-reference (id, sample rate, etc.) | G.1 |
| `live.toggle` | Live parameter (boolean) | B.2, F.9 |
| `loadbang` | bang on patch load | C.1, F.3, F.5, F.7, F.11 |
| `message <text>` | static or dynamic message | C.3, F.11 |
| `metro 33` | bang every 33 ms | F.7 |
| `OSC-route /path/literal` | route OSC by address | C |
| `pack <typespec>` | pack into list (fires on left/hot inlet only) | F.8 |
| `peakamp~ <interval_ms>` | sample-peak accumulator, **self-clocked** — auto-emits + resets every `<interval_ms>` ms (no bang needed) | F.4 (`33`) |
| `plugin~` / `plugout~` | M4L audio in/out | F.1 |
| `prepend <prefix>` | prepend static prefix to list | C.3, F.10 |
| `print <label>` | log to Max console | F.11, F.13, sanity tests throughout |
| `receive <name>` | named message receiver | F.6 (`has_track_id`), F.8 (feature values) |
| `receive~ <name>` | named audio receiver | F.1, F.2 |
| `sel <value>` | bang when input matches | D.4, E.2, F.11 |
| `send <name>` | named message broadcaster | C.1 (`has_track_id`), F.3/F.4/F.5 (feature values) |
| `send~ <name>` | named audio sender | F.1, F.2 |
| `sfrecord~` | audio file writer | E.3, E.4 (unchanged from Chunk 1) |
| `snapshot~` | sample audio signal at control rate | F.3, F.5 |
| `sprintf <format>` | format string with %s/%d | F.8 |
| `t <typespec>` | trigger (right-to-left fire order) | C.1, C.3, D, E.3, F.7 |
| `udpreceive <port>` | UDP message receiver | C (unchanged base from Chunk 1) |
| `udpsend <host> <port>` | UDP message sender (single inlet; constructor args required) | C.3 (reply), F.9 (emitter) |
| `value <varname>` | named state cell — read-by-bang only (does NOT emit on write) | C (path, track_id, beats), D (state machine) |

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
| Trying to check "is this symbol empty?" with `[if ... <empty>]` or `[length]` | `<empty>` isn't a Max literal in `[if]`; `[length]` measures LIST length, not symbol-character count — always returns 1 for a single symbol | Use a separate `has_X` int flag plumbed via `[send]` / `[receive]` (NOT `[value]` — see the next row): set the flag to 1 from the OSC route that populates the symbol; gate downstream actions with `[gate]` controlled by `[receive has_X]` (Sections C.1, F.6, F.9) |
| `[value]` stores writes but downstream never sees them — connected `[print]` silent, exprs see stale values | Max for Live's `[value]` in current versions doesn't emit on write — only on bang. Cold inlets fed via `[value]` outlets stay at their default | Use `[i]` (int) or `[f]` (float) instead of `[value]` for storage. Both emit on every write. Trade-off: lose named-shared-variable semantics, but for local-only use that doesn't matter |
| `live.toggle` outlet appears to be inverted — Arm=1 in Live makes downstream see 0 | A `[== on]` symbol-to-int shim was added between live.toggle and downstream. In current Max versions, live.toggle outputs **int 0/1 directly**. `[== on]` then compares int input to the symbol arg `on`, which Max coerces to int 0 — so `0==0→1` and `1==0→0`, inverting the value | Remove `[== on]`. Wire `[live.toggle]` outlet directly to downstream `[i]` storage |
| `live.observer @path live_set @property current_song_time` never fires — observer outlet silent during transport play | The `@property` attribute on `[live.observer]` isn't honored at load in current Max versions. AND a misconfigured live.observer can silently poison the patcher's loadbang sequence, breaking other init prints | Use the canonical chain: `[live.thisdevice]` → `[live.path live_set]` → `[live.observer]` (no @property arg). At loadbang, ALSO send a `property current_song_time` message to `[live.observer]`'s inlet 0 (via a separate `[message]` box driven off live.thisdevice through a `[t b b]`). Section D.1 walks through this |
| `[route current_song_time]` after live.observer drops everything | live.observer outputs just the bare value (a float), NOT `<property_name> <value>`. `[route <symbol>]` filters by leading symbol and finds no match | Delete `[route current_song_time]` entirely. Wire live.observer outlet directly to expr / deferlow / etc |
| Crossing-detection expr fires once at load then never again, even with transport playing | `prev_beat` starts at -1 at loadbang. The first observer tick after device load satisfies (prev=-1 < start) && (current=anywhere >= start), so the expr returns true ONCE. Then `[deferlow]` updates prev_beat to current_beat, and subsequent ticks can't detect a new crossing. By the time the user arms + plays from beat 0, prev_beat is already past start_at_beat | Reset prev_beat to -1 on Arm rising edge. Wire `[sel 0 1]` outlet 1 (matched 1 — rising edge of Arm after `[change]`) to the same `[-1.]` message that loadbang drives. Section E.4 |
| Max patcher editor open + Live runtime instance simultaneously — OSC routes silently wrong | Both Max-editor and Live-runtime have their own instance of the patcher. They fight over the udpreceive socket; one binds, the other can't, and `live.observer` may not fire in either or both. Symptom: signature reply works erratically; transport observer silent | Always Cmd-S to save, then Cmd-W to close the patcher editor window before runtime testing. Keep `Window → Max Console` open separately (it persists after the patcher closes) |
| `[udpsend]` shows red / no visible inlet | Instantiated without host+port constructor args | Re-create as `udpsend 127.0.0.1 0`. Fallback if the object's missing entirely: `mxj net.udp.send 127.0.0.1 0` |
| Feature frames arrive with one stale float | `[pack]` fires on wrong inlet first | Re-wire so address (inlet 0) fires LAST |
| Feature frames have empty track_id in address | `[value track_id_retained]` not set | Section F.9 `has_track_id` gate (driven by `[receive has_track_id]`, sourced from C.1) — verify by adding `[print HAS_TID]` per F.13 |
| LUFS readings drift ~0.3 LU from `pyloudnorm` reference at the same SR | Session SR isn't 48 kHz; K-weighting biquad coefs are SR-pinned for MVP | F.11 warning probe prints to Max console at load when SR mismatches. Resolve by switching Live's session to 48 kHz, or wait for post-MVP SR-adaptive coefs (backlog) |
| Feature frame `[pack]` doesn't fire at all on metro tick | Address chain (hot inlet 0) not reaching `[pack]` — e.g., `[t b b b b]` outlet 0 not wired to `[value track_id_retained]`, or sprintf outlet not wired to pack inlet 0 | Trace per F.13's probe ladder: METRO → LUFS_M/PEAK/LOWMID → FRAME |
| Tried to wire SR-adapter (`[i]` outlet) to `[average~]`'s right inlet — "average~ only has a left input" | `[average~]` has ONLY one inlet, shared between the audio signal (left audio connection) and the window-size int message (control-rate connection). Same single-inlet multiplexing as `[peakamp~]` | Wire `[i]`'s outlet to `[average~]`'s LEFT inlet (the same one the signal enters from). Max disambiguates by message type — `~` carries signal, non-`~` carries the int |
| `[expr]` rejects ternary `? :` or returns "function if not found" / "function max not found" for `if(...)` / `max(...)` | M4L's bundled `[expr]` function vocabulary is limited to `abs / ceil / floor / int / float / exp / log / log10 / fact / ln / pow / sqrt / rand / random` + the trig family — no conditionals, no `max` / `min`. Some Max docs list `max(a, b)` but it's absent in M4L's runtime | For "log of X with silence sentinel" conversions, do the floor clamp UPSTREAM with `[clip <floor> <ceiling>]` (a Max control-rate object, space-separated args). Then the expr is plain math: `expr 10. * log10($f1) - 0.691`. See F.3 floor/ceiling table |
| Box `max 1e-12` resolves red / not found — Max's object lookup only shows `[maximum]` (list-max) and `[maximum~]` (signal-rate) | The plain `[max]` scalar object exists in Max but auto-complete or quick-lookup may not surface it in some Max versions | Use `[clip <floor> <ceiling>]` instead — same semantics for our floor-clamp need (single inlet, clamps to range), and the two-arg form is space-separated so there's no comma-escape ambiguity. `[clip]` is unambiguous in Max's object lookup |
| Live rejects device with `createdevice error 6` | Patch saved via non-GUI path or hand-edited binary | Restore from `.chunk1.bak.amxd`; only ever save via Max GUI |
| Live's main thread freezes during render | `[average~]` window size or `[metro]` running on audio thread | Verify `[average~]` is at control rate, not signal |
| LUFS-M values off by ~0.3 LU vs Live's meters | 48 kHz biquad coefficients running at 44.1 kHz | Document; SR-adaptive coefficient math is post-MVP |
