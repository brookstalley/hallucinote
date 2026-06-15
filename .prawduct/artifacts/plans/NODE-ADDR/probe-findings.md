# NODE-ADDR — Chunk-A Predecessor LOM Probes (findings)

**Date:** 2026-06-15. **Set:** swell (open working set — 23 tracks, 5 returns, master). **Live:** 12.x.
**Tool:** `ableton_probe` (read-only — `describe`/`get` only; no mutation of swell).
**Gates:** Chunk-A wire freeze (`design.md` §1/§2/§3; `build-plan.md` Chunk A predecessor probes).

> **Settability note.** `ableton_probe(describe)` does not emit a per-property "settable" flag. Settability is
> inferred from LOM convention: a value-bearing primitive (`int`/`bool`/`str`/`float`) that carries an
> `add_<name>_listener` method is a read/write property; `available_*` vectors, `canonical_parent`, and
> `_live_ptr` are read-only structure. Where a write would be the only way to confirm, it is flagged
> "settability inferred (no scratch-set run — swell is read-only)."

---

## PROBE 1 — drum_pad vs DrumChain (THE pivotal wire-freeze question)

### Evidence (verbatim)

**`DrumPad` at `song.tracks[1].devices[0].drum_pads[36]`** (`name`="Kick TL", `note`=36) — class `DrumPad`. **Complete property list:**
`_live_ptr`, `canonical_parent`(RackDevice), `chains`(Vector→1 DrumChain), `mute`(bool=false), `name`(str="Kick TL"), `note`(int=36), `solo`(bool=false).
Methods: `delete_all_chains`, and listeners for `chains`/`mute`/`name`/`solo` only.

- `mute` — PRESENT, settable (has `add_mute_listener`).
- `solo` — PRESENT, settable (has `add_solo_listener`).
- `name` — PRESENT, settable (has `add_name_listener`).
- `note` — PRESENT, **NO listener → fixed/positional** (the pad's trigger note = its index; not a writable transpose).
- `chains` — PRESENT (read-only vector; the way down to the DrumChain).
- `choke_group` — **ABSENT on DrumPad.**
- `out_note` / transpose — **ABSENT on DrumPad.**
- output routing — **ABSENT on DrumPad.**

**`DrumChain` at `song.tracks[1].devices[0].drum_pads[36].chains[0]`** — class `DrumChain`. Relevant properties:
`choke_group`(int=0), `in_note`(int=36), `out_note`(int=60), `mute`(bool), `solo`(bool), `muted_via_solo`(bool),
`name`(str), `color`/`color_index`, `mixer_device`(ChainMixerDevice), `has_audio_output`(true), `devices`(Vector).
Each of `choke_group`/`in_note`/`out_note`/`mute`/`solo` carries an `add_<name>_listener` → all settable.

- `choke_group` — **PRESENT on DrumChain, settable** (`add_choke_group_listener`).
- `out_note` (transpose) — **PRESENT on DrumChain, settable** (`add_out_note_listener`; =60 here, a real remap vs `in_note`=36).
- `mute` / `solo` — PRESENT on DrumChain, settable (plus read-only `muted_via_solo`).
- `name` — PRESENT, settable.
- `mixer_device` — PRESENT → `ChainMixerDevice`.

**Per-chain OUTPUT (audio) routing — does NOT exist:**
`get song.tracks[1].devices[0].drum_pads[36].chains[0].available_output_routing_types` →
`AttributeError: ... (DrumChain) has no attribute 'available_output_routing_types'`.
There is **no** `output_routing_type` / `current_output_routing` / `output_routing_channel` on a DrumChain either.

**`ChainMixerDevice` at `…chains[0].mixer_device`** — properties: `volume`(DeviceParameter), `panning`(DeviceParameter),
`sends`(Vector of DeviceParameter), `chain_activator`(DeviceParameter). All are `DeviceParameter`s (set via the existing
`set_parameter`-style value write). No mute/solo here (those are on the DrumChain itself).

### Verdict — where each feature lives

| feature | object | settable | note |
|---|---|---|---|
| choke group | **DrumChain** (`choke_group`) | yes | NOT on DrumPad |
| per-drum transpose (out_note) | **DrumChain** (`out_note`) | yes | NOT on DrumPad; pad `note` is fixed index |
| per-drum/chain **audio output routing** + channel | **neither** | n/a | `available_output_routing_types` raises AttributeError on DrumChain; no output-routing surface on DrumPad |
| pad/chain mute | **both** (`DrumPad.mute` AND `DrumChain.mute`) | yes | redundant — DrumChain covers it |
| pad/chain solo | **both** (`DrumPad.solo` AND `DrumChain.solo`) | yes | redundant — DrumChain covers it |
| chain mixer vol/pan/sends | **DrumChain.mixer_device** (`ChainMixerDevice`) | yes (DeviceParameters) | DrumPad has no mixer |
| name | both | yes | — |

### Wire/schema implication

**A distinct `drum_pad` terminal is NOT needed.** Every per-drum feature the design attributed to `DrumPad`
(`choke group`, `transpose`/`out_note`, mute, solo) **lives on the `DrumChain`** — reachable today via a `chain`
terminal. The only properties unique to `DrumPad` are `mute`/`solo`/`name`/`note`, and `mute`/`solo`/`name` are
**duplicated on the DrumChain**; `note` is a fixed positional index, not authorable. The design's premise
("choke/pad-mute/transpose live on `DrumPad`, distinct from its `Chain`") is **falsified** — they live on the
DrumChain. Drop `drum_pad` from the frozen terminal enum; the `chain` terminal covers per-drum authorship.
(The chain is reachable two equivalent ways — `drum_pads[note].chains[0]` or `devices[0].chains[K]` — so the
`chain` terminal's `chain_index` step suffices; no pad-index step needed.)

**Corollary correction to the design's feature matrix:** the "per-pad-out on drum chains" / "per-drum routing"
cell (§1, §2 table, Chunk C "per-drum routing + choke") is partly **`UNSUPPORTED_IN_LIVE`**: there is no
per-chain *audio output* routing on a DrumChain. "Per-drum routing" in Live's LOM is `out_note` (MIDI note remap)
+ chain sends, not a separate audio output. Chunk C should be re-scoped to **choke group + out_note + chain
mixer (vol/pan/sends) + mute/solo**, all on the `chain` terminal; the separate-output ambition is a hard wall.

---

## PROBE 2 — addresses-as-value (macro mappings + sidechain source)

### 2a. Macro mappings — evidence (verbatim)

**`RackDevice` at `song.tracks[20].devices[0]`** (`name`="Synth Vox Ai", `class_name`="InstrumentGroupDevice"). Macro-related surface:
- `has_macro_mappings`(bool=**true**) — "are ANY macros mapped at all," a single boolean. **Not a target.**
- `macros_mapped`(tuple=`[true,true,true,true,true,true,true,true,false,…]`) — per-slot "is THIS macro mapped" boolean ×16. **Not a target.**
- `visible_macro_count`(int=8); `parameters`(18 DeviceParameters — the macro knobs are the first ones).
- `variation_count`(int=0), `selected_variation_index`(int=-1); methods `store_variation`/`recall_selected_variation`/`add_macro`/`randomize_macros`.

**Macro knob `parameters[1]`** (a `DeviceParameter`): `name`="Filter Cutoff", `original_name`="Macro 1",
`value`=114.49, `default_value`=114.49, `min`/`max`=0/127. So macro **values + custom names + original names are fully readable.**

**The mapping TARGET is absent.** Nowhere on the `RackDevice` is there a property or method exposing *which
parameter on which nested device* a macro maps to — no `macro_mappings`, no `get_mapping`, no target reference.
The macro knob's own `DeviceParameter` likewise carries no back-reference to its mapped destination(s). The richest
signal is `has_macro_mappings`(bool) + `macros_mapped`(bool×16) — presence only, never the destination address.

**Conclusion (macros):** Live's LOM exposes macro **values + names** and macro **variations**
(`variation_count`/`store_variation`/`selected_variation_index`), but **does NOT expose the macro→parameter
mapping target.** Confirmed firsthand — the known Live limitation holds.

### 2b. Sidechain source — evidence (verbatim)

**`Compressor2` at `song.tracks[2].devices[2]`** (on "03 Bass Punk"; `class_display_name`="Compressor"). It exposes the
**Track routing object model**: `input_routing_type`(RoutingType), `input_routing_channel`(RoutingChannel),
`available_input_routing_types`(RoutingTypeVector, 30 entries), `available_input_routing_channels`(RoutingChannelVector).
- `input_routing_type.display_name` = **"02 Kit Punk"** (the current sidechain source — a *track name*).
- `available_input_routing_types[1].display_name` = "02 Kit Punk"; `[2]` = "03 Bass Punk" — i.e. the source list is the set of track names (plus internal types).

So the sidechain source is a `RoutingType` keyed by `display_name` = a **track name**, structurally identical to a
track's own input routing. The existing MCP `set_sidechain(source_display_name=…)` writes exactly this. A source maps
**cleanly to/from a track NodeAddr**: render the source-track NodeAddr → its display_name → match against
`available_input_routing_types`; read back the source by reverse-matching `input_routing_type.display_name` to a track.

### Verdict — does "NodeAddr-as-value" belong in the frozen wire?

- **Sidechain source: YES, but it is a *track* NodeAddr rendered to a display_name string, not an arbitrary node/param
  address.** It is genuinely backed by the LOM (RoutingType.display_name = track name). The value space is "a track,"
  so the as-value need is satisfied by a **track-terminal NodeAddr** (no device/param depth required for this feature).
- **Macro mappings: NOT backed by the LOM for the *target*.** Since Live does not expose which param a macro maps to,
  a macro→param `NodeAddr`-as-value **cannot be read or round-tripped** through capture/push. The "macro target is an
  address" justification for as-value is **UNSUPPORTED_IN_LIVE for the read/acquisition side.** Macro values/names/
  variations are authorable; the *mapping* is not.

**Implication:** Keep "NodeAddr-as-value" in the frozen wire, but **scope it to the track-terminal case (sidechain
source)** — that is the only feature genuinely backed by the LOM. The value grammar does NOT need to carry full
device/param-depth addresses-as-value for macro mappings, because macro mappings can't be acquired at all.
**Chunk D (macro mappings) is partly `UNSUPPORTED_IN_LIVE`:** macro *values/names* and *variations* =
`NOT_IMPLEMENTED` (buildable); macro→param *mapping targets* = `UNSUPPORTED_IN_LIVE` (Live exposes no target).
The §2b honesty-caveat list should add macro-mapping-targets alongside send pre/post.

---

## PROBE 3 — send pre/post-fader toggle

### Evidence (verbatim)

- **`MixerDevice` (return) at `song.return_tracks[0].mixer_device`** — full property set:
  `crossfade_assign`, `crossfader`(err: main only), `cue_volume`(err: main only), `left_split_stereo`,
  `panning`, `panning_mode`, `right_split_stereo`, `sends`(Vector of DeviceParameter), `song_tempo`(err: main only),
  `track_activator`, `volume`. **No `pre`, `post`, or any pre/post-fader send-mode property.**
- **A send itself** `song.return_tracks[0].mixer_device.sends[0]` is a bare `DeviceParameter`:
  `value`/`display_value`/`min`/`max`/`name`("A-Hall")/`original_name`/`state`/`automation_state`/`default_value`.
  **No pre/post property on the send.** Same shape on `song.tracks[1].mixer_device.sends[0]`.

### Verdict

**`UNSUPPORTED_IN_LIVE`.** Live's LOM exposes **no** per-send (or per-return) pre/post-fader toggle anywhere on
`MixerDevice` or on the send `DeviceParameter`. The design's flagged suspicion is confirmed: classify send pre/post
mode as **`UNSUPPORTED_IN_LIVE`, not `NOT_IMPLEMENTED`** (a hard wall; the agent routes around it, never waits).

### Wire/schema implication

Send pre/post ships as a documented **`UNSUPPORTED_IN_LIVE`** static cell in the single-source capability table
(`build-plan.md` "Documented stubs" list) — *not* a `NOT_IMPLEMENTED` stub. Its row's Live-support-evidence field
should cite "no pre/post property on MixerDevice or send DeviceParameter (probed 2026-06-15, Live 12.x)."

---

## PROBE 4 — return/master input-routing capability (contents, not presence)

### Evidence (verbatim) — the design's "empty / No-Input ⇒ UNSUPPORTED" assumption is REFUTED for input routing

**Return `song.return_tracks[0]`:**
- `available_input_routing_types` — **30 entries, NON-trivial.** `[0].display_name`="Resampling", `[1].display_name`="01 Glitch" (track names follow).
- `input_routing_type` — resolves to a real `RoutingType` object (present, not null).
- `available_output_routing_types` — 4 entries: `[0]`="Ext. Out", `[1]`="Main".

**Master `song.master_track`:**
- `available_input_routing_types` — **30 entries, NON-trivial.** `[0].display_name`="Resampling".
- `input_routing_type` — resolves to a real `RoutingType` object.
- `available_output_routing_types` — 4 entries: `[0]`="Ext. Out", `[1]`="Main".

**Monitor state — genuinely unavailable on both:**
`get song.return_tracks[0].current_monitoring_state` → `RuntimeError: Main and Return Tracks have no monitoring state!`
(same error on master).

### Verdict

| node | input routing | output routing | monitor state |
|---|---|---|---|
| **return** | **AVAILABLE** (`available_input_routing_types` = ["Resampling","01 Glitch",…], 30 entries; `input_routing_type` resolves) | **AVAILABLE** (["Ext. Out","Main",…]) | **`UNSUPPORTED_IN_LIVE`** ("no monitoring state") |
| **master** | **AVAILABLE** (`available_input_routing_types` = ["Resampling",…], 30 entries; `input_routing_type` resolves) | **AVAILABLE** (["Ext. Out","Main",…]) | **`UNSUPPORTED_IN_LIVE`** ("no monitoring state") |

This **contradicts design OQ4**, which pre-classified return/master input routing as `UNSUPPORTED_IN_LIVE`
("no audio input"). The LOM contents prove otherwise: returns and master **DO** expose input routing (Resampling +
per-track sources) in Live 12.x — exactly the routing object model already on tracks and on the sidechain Compressor.

### Wire/schema implication

- **Output routing on return + master: AVAILABLE** — build it in the routing chunk (matches design OQ4's intent).
- **Input routing on return + master: AVAILABLE, NOT `UNSUPPORTED_IN_LIVE`** — correct the design. It's the same
  `input_routing_type` / `available_input_routing_types` surface as a track, so it costs nothing extra to support;
  classify as **`NOT_IMPLEMENTED` → buildable**, not a structural wall. (Whether to *build* it is a scope call, but
  the tri-state cell must say `NOT_IMPLEMENTED`, not `UNSUPPORTED_IN_LIVE`, or the published matrix lies.)
- **Monitor state on return + master: `UNSUPPORTED_IN_LIVE`** — confirmed (static cell; "Main and Return Tracks have
  no monitoring state"). This one matches the design's expectation.

---

## Wire-freeze decisions (summary)

1. **`drum_pad` terminal — DROP it.** choke_group, out_note (transpose), mute, solo, and the chain mixer all live on
   the **`DrumChain`**, reachable via the `chain` terminal. `DrumPad` adds only redundant `mute`/`solo`/`name` + a
   fixed `note` index. The frozen terminal enum is **`track | return | master | device | chain`** — no `drum_pad`.
   *Bonus:* per-chain **audio output routing does not exist** (`available_output_routing_types` raises on DrumChain)
   → re-scope Chunk C to choke/out_note/chain-mixer/mute-solo; the separate-output ambition is `UNSUPPORTED_IN_LIVE`.

2. **NodeAddr-as-value — KEEP, but scope to the track-terminal sidechain case only.** Sidechain source is a
   `RoutingType.display_name` = a track name → round-trips cleanly to/from a **track NodeAddr** (LOM-backed). Macro
   mapping *targets* are **not** exposed by the LOM (`has_macro_mappings`/`macros_mapped` are presence-only), so the
   macro→param address-as-value is **`UNSUPPORTED_IN_LIVE` on acquisition** and must NOT be the justification for a
   device/param-depth value grammar. The wire's as-value slot only needs to carry a **track NodeAddr**.

3. **Send pre/post-fader — `UNSUPPORTED_IN_LIVE`** (not `NOT_IMPLEMENTED`). No pre/post property on `MixerDevice` or
   on the send `DeviceParameter`. Static documented stub.

4. **Return/master routing:**
   - **output routing — AVAILABLE** on both (build per OQ4: "Ext. Out"/"Main").
   - **input routing — AVAILABLE** on both (Resampling + per-track sources, 30 entries) → **correct the design's
     `UNSUPPORTED_IN_LIVE` pre-classification to `NOT_IMPLEMENTED`/buildable.**
   - **monitor state — `UNSUPPORTED_IN_LIVE`** on both (confirmed: "no monitoring state").

5. **Two design corrections flagged for Chunk A's capability table** (so the published matrix can't lie):
   (a) macro-mapping-target = `UNSUPPORTED_IN_LIVE` (add to the §2b honesty-caveat list with send pre/post);
   (b) return/master **input** routing = `NOT_IMPLEMENTED`, not `UNSUPPORTED_IN_LIVE` (OQ4 was wrong on input).
