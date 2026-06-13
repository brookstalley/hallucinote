"""Live-Ableton snapshot format and replay.

The snapshot is a JSON document describing the mix layout of an Ableton set —
tracks (with kind + mixer state), returns, sends, the master strip, and (post
chunk 4a) device chains with dialed parameters. It is the seed mechanism for
`build.py`: capture once (live Ableton -> snapshot.json), then replay into the
DB through mutators.

Scope (chunks 3 + 4a + W7-B): tracks + returns + sends + master + mixer state +
top-level device chains + dialed device parameters + one level of nested rack
chains. Each rack-kind device (Arc 4 / D4 display names: ``Drum Rack``,
``Instrument Rack``, ``Audio Effect Rack``; pre-D4 these were the internal
class names ``DrumGroupDevice``/``InstrumentGroupDevice``/``AudioEffectGroupDevice``)
may optionally carry a ``chains: [{chain_index, name, devices: [...]}]``
array; replay walks one level. Recursively nested racks
(rack-inside-a-rack) are deferred (raises on encounter) — tracked in backlog
under "nested-nested rack support". Automation envelopes (chunk 4b) are
schema-modeled and push-plannable but the capture/replay path doesn't ingest
them yet — MCP exposes no read surface for the seven envelope target families
(see `ableton://guides/gaps`).

Snapshot shape (extends the existing `captured_session.json` prototype):

    {
      "song": {
        "name":      "..." (optional; defaults to caller-supplied),
        "key":       "..." (optional),
        "tempo":     132.0,         # informational; score-chunk tempo_map owns this
        "signature": "4/4",         # informational; score-chunk time_signature_map owns this
        "master":    {"volume": 0.85, "panning": 0.0}
      },
      "returns": [
        {"index": 1, "name": "A-Reverb", "volume": 0.85, "panning": 0.0, "color": null}
      ],
      "tracks": [
        {
          "index": 5, "name": "01 Drums", "type": "midi",
          "volume": 0.6249, "panning": 0.0,
          "mute": false, "solo": false, "arm": false,
          "color": null,
          "instrument_uri": "query:Drums#FileId_5418",   # optional
          "sends": {"A-Reverb": 0.0, "B-Delay": 0.0}
        }
      ]
    }

Replay creates: returns (1 row per `returns[]`), tracks (1 row per `tracks[]`,
plus a `kind='master'` row for `song.master`), sends (1 row per non-null entry
in each track's `sends` map, keyed by return name), top-level device chains
(1 per track/return that has a `devices: [...]` array — chunk 4a), devices
(1 row per array entry), device parameters (1 row per entry in each device's
`params_dialed: {...}` map). `clips: [...]` on tracks is still ignored —
populated by build.py hand-authored sections.

Live capture (Ableton -> snapshot.json) is agent-orchestrated: the agent runs
MCP probes against the v1 unified-action-dispatch surface
(`ableton_session(action='info')`, `ableton_return(action='list')`,
`ableton_track(action='info'|'get_sends')`,
`ableton_device(action='get_parameters'|'get_device_chains')`) and assembles
the dict via `compile_snapshot`. See `tools/capture_cli.py` for the probe sequence.
"""
from __future__ import annotations

import sqlite3
import warnings
from typing import Any

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.db import mutations as M, queries as Q
from hallucinote.return_naming import strip_return_slot_prefix

# SNP-8R4K chunk 2 — snapshot schema version stamped on every compiled snapshot
# (`compile_snapshot`) and asserted by the at-rest cleanup (`migrate_snapshot`).
# Bumped deliberately when the snapshot schema changes in a way the migrator
# must act on. v1 = "analyzer-free, dense authored device positions" (the
# SNP-8R4K release). An unstamped snapshot (missing key) or one stamped < this
# version is pre-SNP-8R4K and triggers the one-time cleanup
# (`snapshot_needs_migration`). This is an INTENTIONAL schema version — bumped
# by hand as part of a migration — not a freshness/staleness label, so the
# "derive from content, never hand-bump" learning does not apply.
SNAPSHOT_SCHEMA_VERSION = 1

# Track types accepted in snapshot["tracks"][n]["type"]; mapped 1:1 to
# `tracks.kind` in the DB. Unknown values raise; the snapshot is authoritative.
_VALID_TRACK_TYPES = frozenset({"midi", "audio", "group"})


# Live device classes that own nested chains. Mirrors `_resolve_rack_chains`
# in hallucinote_mcp.handlers.device — kept here so the snapshot replay path
# can validate "this device carries `chains`, but its class isn't a rack"
# at the boundary. W6-I/J shipped the MCP-side walk; W7-B threads it through
# capture + pull.
# Arc 4 / D4: rack identity is checked against browser display names
# (the post-D4 ``devices.kind`` convention) — ``"Drum Rack"`` /
# ``"Instrument Rack"`` / ``"Audio Effect Rack"``. The pre-D4 set
# used internal Live class names (``DrumGroupDevice`` etc.) to match
# the old ``snapshot.class`` semantics; with the convention shift
# they're the same identity expressed in the loader-facing namespace.
RACK_CLASS_NAMES = frozenset({
    "Drum Rack",
    "Instrument Rack",
    "Audio Effect Rack",
})


def _norm_pan(value: Any) -> float | None:
    """Snapshot uses `panning`; DB column is `pan`. Pass-through with type check."""
    if value is None:
        return None
    f = float(value)
    if not -1.0 <= f <= 1.0:
        raise ValueError(f"pan {f} out of range [-1.0, 1.0]")
    return f


def _norm_vol(value: Any) -> float | None:
    if value is None:
        return None
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"volume {f} out of range [0.0, 1.0]")
    return f


def _norm_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _replay_devices(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    devices_array: list[dict[str, Any]],
    actor: str,
    request_id: str | None,
    reason: str | None,
    _depth: int = 0,
) -> None:
    """Insert each entry of `devices_array` into the given chain, plus any
    dialed parameters and (at depth 0) one level of nested rack chains.

    `_depth` is private — used to enforce the "one level of recursion only"
    invariant. A rack device inside a rack chain (nested-nested) raises on
    encounter; recursive support is deferred (tracked in backlog).

    SNP-8R4K — defensive analyzer exclusion: capture filters the analyzer at
    `compile_snapshot`, but a legacy-polluted snapshot on disk may still carry
    an analyzer entry. We skip `is_analyzer_device` entries here so replay
    never writes an analyzer device row, and assign each survivor's `position`
    its 1-based rank among survivors (not the entry's raw `index`) so a dropped
    analyzer can't leave a hole or shift authored positions.
    """
    survivors = [d for d in devices_array if not is_analyzer_device(d)]
    for survivor_rank, d in enumerate(survivors, start=1):
        if "index" not in d or "class" not in d:
            raise ValueError(
                f"snapshot device missing required keys (index, class): {d!r}"
            )
        # Sweep B: snapshot device entries may carry preset_query as the
        # compose-time portable alternative to per-machine preset_uri.
        # The two are mutually exclusive — create_device refuses both at once.
        # Hand-authored snapshots use this to express "load a 909 kit"
        # without baking in this machine's FileId.
        preset_query = d.get("preset_query")
        preset_uri = d.get("guess_uri") if preset_query is None else None
        # Arc 7-tail / E3 (W13-A v1.0): snapshots may carry the browser
        # path the device was originally loaded from (captured by the
        # MCP load handler's `resolved_path` response field). The push
        # planner threads this through to the load handler as a
        # fallback identity when the per-machine preset_uri doesn't
        # resolve. Pre-E3 snapshots omit it — devices stay loadable
        # via preset_uri / kind-only, just without cross-machine
        # FileId fallback.
        browser_path_raw = d.get("browser_path")
        browser_path: list[str] | None
        if isinstance(browser_path_raw, list) and browser_path_raw:
            browser_path = [str(s) for s in browser_path_raw]
        else:
            browser_path = None
        # Arc 4 / D4: snapshots may carry `class_name` (Live's internal
        # class identifier) alongside `class` (the browser display name
        # the loader matches). Capture-from-Live populates both; hand-
        # authored snapshots may omit `class_name`. The mutator accepts
        # None for that field — informational column, drives plugin
        # classification when present.
        # SMP-7K2D: a sample-instrument device entry carries `audio_file`
        # (song-relative under assets/, or absolute) — the sampler's assigned
        # sample. Non-sampler devices omit it. Push resolves it via
        # paths.resolve_audio_path, the same resolver clips use.
        device_id = M.create_device(
            conn,
            chain_id=chain_id,
            position=survivor_rank,
            kind=d["class"],
            display_name=d.get("name", d["class"]),
            class_name=d.get("class_name"),
            preset_uri=preset_uri,
            preset_query=preset_query,
            browser_path=browser_path,
            audio_file=d.get("audio_file"),
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        for name, p in (d.get("params_dialed") or {}).items():
            if not isinstance(p, dict) or "value" not in p:
                raise ValueError(
                    f"snapshot param {name!r} on device {d.get('name')!r}: "
                    f"expected dict with 'value' key, got {p!r}"
                )
            normalized = p.get("normalized")
            raw_items = p.get("value_items")
            value_items = (
                [str(item) for item in raw_items]
                if isinstance(raw_items, (list, tuple))
                else None
            )
            M.set_device_parameter(
                conn,
                device_id=device_id,
                name=name,
                value_display=str(p["value"]),
                value_normalized=(
                    float(normalized) if normalized is not None else None
                ),
                value_items=value_items,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        nested = d.get("chains")
        if nested:
            if _depth > 0:
                raise ValueError(
                    f"snapshot device {d.get('name')!r} (class {d['class']!r}): "
                    "nested-nested rack chains are not supported — replay "
                    "walks one level only"
                )
            if d["class"] not in RACK_CLASS_NAMES:
                raise ValueError(
                    f"snapshot device {d.get('name')!r} carries `chains` but "
                    f"class {d['class']!r} is not a rack "
                    f"({sorted(RACK_CLASS_NAMES)})"
                )
            _replay_rack_chains(
                conn,
                rack_device_id=device_id,
                chains_array=nested,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        # M1-C: Drum Rack pad mapping. Each Drum Rack may carry a
        # `drum_pads` array captured via `ableton_device(action='pad_info')`:
        # ``[{chain_name: str, midi_note: int}, ...]``. Replay persists into
        # `drum_pad_mappings` so the song's generators can resolve
        # ``Kit.from_device(...).kick`` to the kit's actual MIDI note.
        # Arc 4 / D4: identity check uses the browser display name
        # ``"Drum Rack"`` (post-D4 ``snapshot.class`` semantics).
        pads = d.get("drum_pads")
        if pads:
            if d["class"] != "Drum Rack":
                raise ValueError(
                    f"snapshot device {d.get('name')!r} carries `drum_pads` "
                    f"but class {d['class']!r} is not 'Drum Rack' — "
                    "pad_info only applies to Drum Racks"
                )
            M.replace_drum_pad_mappings(
                conn,
                device_id=device_id,
                mappings=[
                    {
                        "chain_name": str(p.get("chain_name", p.get("name", ""))),
                        "midi_note": int(p["midi_note"] if "midi_note" in p else p["note"]),
                    }
                    for p in pads
                ],
                actor=actor,
                request_id=request_id,
                reason=reason,
            )


def _replay_rack_chains(
    conn: sqlite3.Connection,
    *,
    rack_device_id: str,
    chains_array: list[dict[str, Any]],
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Insert each nested chain under `rack_device_id` and recurse one level
    into the chain's devices.

    Each entry: ``{chain_index: int>=1, name: str (optional), devices: [...]}``.
    The chain row's `position` matches W6-I/J's 1-based `chain_index` on the
    wire; top-level chains use `position=0` so the two address spaces don't
    collide.
    """
    for chain in chains_array:
        if "chain_index" not in chain:
            raise ValueError(
                f"snapshot nested chain missing 'chain_index': {chain!r}"
            )
        ci = int(chain["chain_index"])
        if ci < 1:
            raise ValueError(
                f"snapshot nested chain chain_index must be >= 1, got {ci}"
            )
        nested_chain_id = M.create_device_chain(
            conn,
            parent_rack_device_id=rack_device_id,
            position=ci,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _replay_devices(
            conn,
            chain_id=nested_chain_id,
            devices_array=chain.get("devices") or [],
            actor=actor,
            request_id=request_id,
            reason=reason,
            _depth=1,
        )


def _mixer_from_snapshot(t: dict[str, Any]) -> dict[str, Any]:
    """Pick the mixer fields out of a snapshot track dict, normalizing key names
    (`panning` -> `pan`) and skipping fields the snapshot didn't set."""
    out: dict[str, Any] = {}
    if "volume" in t:
        out["volume"] = _norm_vol(t["volume"])
    if "panning" in t:
        out["pan"] = _norm_pan(t["panning"])
    elif "pan" in t:
        out["pan"] = _norm_pan(t["pan"])
    if "mute" in t:
        out["mute"] = _norm_bool(t["mute"])
    if "solo" in t:
        out["solo"] = _norm_bool(t["solo"])
    if "arm" in t:
        out["arm"] = _norm_bool(t["arm"])
    if "color" in t and t["color"] is not None:
        out["color"] = int(t["color"])
    return out


def replay_capture(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    song_name: str,
    song_title: str | None = None,
    song_key: str | None = None,
    timing_mode: str = "native",
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Replay a snapshot into a song in the DB. Returns the song_id.

    W12-A: replay is idempotent — every underlying mutator (create_song,
    create_track, create_return, create_device_chain, create_device,
    set_device_parameter) is upsert-shaped. Re-replay onto an existing
    song updates rows whose state changed (snapshot edits) and is a no-op
    for unchanged rows. The prior "song already exists, raise" guard
    pre-dated mutator idempotency and is no longer needed; the actor='sync'
    threading still distinguishes pulled state from build-owned state for
    tombstone-time semantics.

    Notes/clips/devices in the snapshot are NOT replayed via this function
    — chunk 3 covers only the mix layout. Score-half (tempo/time-signature/
    sections/cue points) is also not populated by replay; build.py authors
    those alongside the captured mix.

    SNP-8R4K chunk 2 — build-time migration trigger: if the snapshot predates
    the clean-at-rest contract (unstamped/old version, or still carrying
    analyzer device entries), emit a warning pointing at the migrate command.
    Replay/build is READ-ONLY on source files — chunk 1's `_replay_devices`
    already strips analyzer rows so the DB is correct either way; this is the
    one-line nudge to clean the committed FILE, not an auto-rewrite.
    """

    if snapshot_needs_migration(snapshot):
        analyzer_count = sum(
            _parent_analyzer_count(p)
            for p in (snapshot.get("tracks") or []) + (snapshot.get("returns") or [])
        )
        if analyzer_count:
            detail = f"{analyzer_count} analyzer device entr" + (
                "y" if analyzer_count == 1 else "ies"
            )
        else:
            detail = "unstamped/pre-SNP-8R4K"
        warnings.warn(
            f"replay_capture: snapshot predates SNP-8R4K ({detail}) — analyzer "
            "rows are ignored on build (the DB is clean either way), but the "
            "committed snapshot file is still dirty at rest. Run "
            "`python -m hallucinote.tools.capture_cli migrate <captured_session.json>` "
            "to clean + version-stamp the committed file.",
            UserWarning,
            stacklevel=2,
        )

    song_id = M.create_song(
        conn,
        name=song_name,
        title=song_title,
        key=song_key,
        timing_mode=timing_mode,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )

    song_block = snapshot.get("song") or {}
    master = song_block.get("master")
    if master:
        # Master is stored as a track row with the sentinel `track_index=0`.
        # Live's master strip has no real index, but the schema requires one.
        # Replay enforces `track_index >= 1` for non-master tracks below so the
        # 0 sentinel is unique within a song.
        master_id = M.create_track(
            conn,
            song_id=song_id,
            track_index=0,
            name="Master",
            instrument_uri=None,
            kind="master",
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        master_mixer = _mixer_from_snapshot(master)
        if master_mixer:
            M.set_track_mixer(
                conn,
                track_id=master_id,
                actor=actor,
                request_id=request_id,
                reason=reason,
                **master_mixer,
            )

    return_ids_by_name: dict[str, str] = {}
    stripped_pairs: list[tuple[str, str]] = []
    for r in snapshot.get("returns") or []:
        # W4-C: strip Live's `<letter>-` slot prefix on the way into the DB.
        # The snapshot's `t["sends"]` is keyed by the SAME prefixed names
        # Live reports, so we strip on the lookup side too (below).
        stripped_name = strip_return_slot_prefix(r["name"])
        if stripped_name != r["name"]:
            stripped_pairs.append((r["name"], stripped_name))
        rid = M.create_return(
            conn,
            song_id=song_id,
            name=stripped_name,
            position=int(r["index"]),
            volume=_norm_vol(r.get("volume")),
            pan=_norm_pan(r.get("panning", r.get("pan"))),
            color=int(r["color"]) if r.get("color") is not None else None,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        return_ids_by_name[stripped_name] = rid
        if r.get("devices"):
            return_chain_id = M.create_device_chain(
                conn,
                parent_return_id=rid,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
            _replay_devices(
                conn,
                chain_id=return_chain_id,
                devices_array=r["devices"],
                actor=actor,
                request_id=request_id,
                reason=reason,
            )

    if stripped_pairs:
        pretty = ", ".join(f"{orig!r} -> {stripped!r}" for orig, stripped in stripped_pairs)
        warnings.warn(
            "replay_capture: stripped Live's <letter>- slot prefix from "
            f"{len(stripped_pairs)} return name(s): {pretty}. The DB stores "
            "SUFFIX-only return names (W4-C convention) — hand-authored "
            "snapshots should use the stripped form, and build.py lookups "
            "(Q.get_return_by_name) should pass the stripped form too. See "
            "docs/snapshot-schema.md ('Return names: stored stripped').",
            UserWarning,
            stacklevel=2,
        )

    track_ids_by_name: dict[str, str] = {}
    for t in snapshot.get("tracks") or []:
        track_type = t.get("type", "midi")
        if track_type not in _VALID_TRACK_TYPES:
            raise ValueError(
                f"track {t.get('name')!r}: type {track_type!r} not in "
                f"{sorted(_VALID_TRACK_TYPES)}"
            )
        idx = int(t["index"])
        if idx < 1:
            # 0 is reserved for the master sentinel; Live's tracks are 1-based.
            raise ValueError(
                f"track {t.get('name')!r}: index {idx} must be >= 1 "
                "(0 is reserved for the master sentinel)"
            )
        tid = M.create_track(
            conn,
            song_id=song_id,
            track_index=idx,
            name=t["name"],
            instrument_uri=t.get("instrument_uri"),
            kind=track_type,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        track_ids_by_name[t["name"]] = tid
        mixer = _mixer_from_snapshot(t)
        if mixer:
            M.set_track_mixer(
                conn,
                track_id=tid,
                actor=actor,
                request_id=request_id,
                reason=reason,
                **mixer,
            )
        for return_name, level in (t.get("sends") or {}).items():
            if level is None:
                continue
            # W4-C: the snapshot's send map is keyed by Live's prefixed names;
            # the return_ids_by_name dict is keyed by stripped names, so we
            # strip here too for consistent lookup.
            target = return_ids_by_name.get(strip_return_slot_prefix(return_name))
            if target is None:
                raise ValueError(
                    f"track {t['name']!r} sends to return {return_name!r} "
                    "which is not defined in snapshot['returns']"
                )
            M.set_send_level(
                conn,
                from_track_id=tid,
                to_return_id=target,
                level=float(level),
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        if t.get("devices"):
            track_chain_id = M.create_device_chain(
                conn,
                parent_track_id=tid,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
            _replay_devices(
                conn,
                chain_id=track_chain_id,
                devices_array=t["devices"],
                actor=actor,
                request_id=request_id,
                reason=reason,
            )

    return song_id


# ---------------------------------------------------------------------------
# Capture-plan (Ableton -> snapshot dict)
# ---------------------------------------------------------------------------
# The actual live capture is agent-orchestrated — Python can't call MCP tools
# directly. `compile_snapshot` assembles the JSON dict from MCP probe results
# the agent has gathered; `capture_plan` documents the probe sequence.


def capture_plan() -> list[dict[str, str]]:
    """List the MCP probe calls the agent should run to populate a snapshot.

    Returns a sequence of `{tool, purpose}` records. The agent executes each,
    accumulates the results, and hands them to `compile_snapshot`.

    Chunk 3 baseline: tempo/master/returns/tracks/sends. Chunk 4a adds top-
    level device chain + per-device dialed parameter probes. W7-B adds the
    nested-rack chain walk: for every rack device returned in a track's or
    return's top-level chain, probe `get_device_chains` to capture one level
    of nested chains and their devices.
    """
    return [
        {"tool": "ableton_session(action='info')",
         "purpose": "global state: tempo, signature, master volume/pan, track counts"},
        {"tool": "ableton_return(action='list')",
         "purpose": "return tracks: name + volume + pan per return; "
                    "chunk 4a: include each return's top-level device chain"},
        {"tool": "ableton_track(action='info')",
         "purpose": "per-track: name, type, volume, pan, mute/solo/arm, "
                    "top-level device chain (kind + display_name + position) "
                    "— loop over tracks"},
        {"tool": "ableton_track(action='get_sends')",
         "purpose": "per-track: sends map keyed by return name (loop over tracks)"},
        {"tool": "ableton_device(action='get_parameters')",
         "purpose": "per-device: dialed parameter map "
                    "(name -> {value, normalized}) — loop over each device"},
        {"tool": "ableton_device(action='get_device_chains')",
         "purpose": "per-rack-device: one level of nested chains + their "
                    "devices (W7-B). Emit for every device whose probed "
                    f"`class_display_name` is in {sorted(RACK_CLASS_NAMES)} "
                    "(Arc 4 / D4 — was `class_name` in {DrumGroupDevice, "
                    "InstrumentGroupDevice, AudioEffectGroupDevice} pre-D4; "
                    "now keyed off Live's class_display_name to match the "
                    "post-D4 snapshot.class convention). The agent attaches "
                    "the result as the device's `chains` field on the "
                    "snapshot. DO NOT emit a `_note` placeholder ('Rack — "
                    "internal chain instruments not captured', etc.) on "
                    "rack devices any more — the capture path now walks "
                    "one level. Recursively nested racks (rack-in-rack) "
                    "remain out of scope; replay raises on encounter."},
        {"tool": "ableton_device(action='pad_info')",
         "purpose": "per-Drum-Rack: pad layout (midi_note + chain_name per "
                    "non-empty pad). M1-C. Emit ONLY for devices whose "
                    "probed `class_display_name` is 'Drum Rack' (Arc 4 / "
                    "D4 — was class_name 'DrumGroupDevice' pre-D4). The "
                    "agent attaches the result as the device's `drum_pads` "
                    "field on the snapshot: ``[{midi_note: int, chain_name: "
                    "str}, ...]``. Replay persists into `drum_pad_mappings` "
                    "so songs can "
                    "use `Kit.from_device(conn, device_id)` to author kit-"
                    "portable drum patterns instead of GM-assumed MIDI notes."},
    ]


def compile_snapshot(
    *,
    session_info: dict[str, Any],
    returns: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    browser_paths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a snapshot dict from raw MCP probe outputs.

    Inputs are already-shaped dicts:
      session_info = {tempo, signature, master: {volume, panning}, ...}
      returns      = [{index, name, volume, panning, ...}, ...]
      tracks       = [{index, name, type, volume, panning, mute, solo, arm,
                        sends: {return_name: level, ...}, ...}, ...]

    Output is normalized to the snapshot schema documented in this module.
    Devices/clips on inputs are preserved verbatim; replay ignores them.

    `browser_paths` (Arc 7-tail / E3, snapshot-write side of W13-A v1.0):
    optional list of load records the caller accumulated by reading each
    `ableton_device(action='load')` response's `resolved_path`. Each record
    is `{track_index|return_index: int, device_index: int, browser_path:
    [str, ...]}`. When supplied, the function injects `browser_path` into
    the matching top-level device entry on the assembled snapshot so the
    cross-machine fallback identity round-trips through capture.

    SNP-8R4K — analyzer exclusion (THE off-by-one fix): the
    HallucinoteAnalyzer is measurement infrastructure, not authored content.
    Every parent's `devices` array is filtered to drop `is_analyzer_device`
    entries before assembly, and each survivor's `index` is re-assigned its
    1-based rank among survivors — NEVER the raw Live chain index. So an
    interleaved analyzer can never shift an authored device's position, and
    the analyzer (and its M4L params) never enters the snapshot. Browser-path
    injection runs AFTER the densify so its `device_index` records address the
    renumbered positions.
    """
    returns = [_exclude_analyzer_from_parent(r) for r in returns]
    tracks = [_exclude_analyzer_from_parent(t) for t in tracks]
    snapshot = {
        # SNP-8R4K chunk 2 — every compiled snapshot carries the schema version
        # so a consumer (and the at-rest cleanup) can tell a fresh capture from
        # a pre-SNP-8R4K one without inspecting device arrays.
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        "song": {
            "tempo": session_info.get("tempo"),
            "signature": session_info.get("signature"),
            "master": session_info.get("master"),
        },
        "returns": returns,
        "tracks": tracks,
    }
    if browser_paths:
        inject_browser_paths(snapshot, browser_paths)
    return snapshot


def _exclude_analyzer_from_parent(parent: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a snapshot parent (track / return) whose top-level
    `devices` array has the HallucinoteAnalyzer dropped and surviving devices
    densely renumbered (`index` = 1-based rank among survivors). SNP-8R4K R3/R5.

    Position-independent by construction: correct whether the analyzer is last
    or interleaved. Parents without a `devices` array pass through unchanged.
    Each surviving device entry is shallow-copied before its `index` is
    rewritten so the caller's input dicts aren't mutated.
    """
    devices = parent.get("devices")
    if not devices:
        return parent
    survivors = [d for d in devices if not is_analyzer_device(d)]
    renumbered = [
        {**d, "index": rank}
        for rank, d in enumerate(survivors, start=1)
    ]
    return {**parent, "devices": renumbered}


# ---------------------------------------------------------------------------
# At-rest snapshot migration (SNP-8R4K chunk 2 — State-1 clean-at-rest)
# ---------------------------------------------------------------------------
# Chunk 1 already makes a polluted snapshot *functionally* clean on the next
# build (`compile_snapshot` + `_replay_devices` both strip the analyzer and
# densify). This chunk cleans the committed `captured_session.json` FILE so the
# artifact itself stops carrying analyzer rows — strip + densify + stamp a
# version so the rewrite runs exactly once, and announce per parent what was
# stripped (never a silent rewrite). The migrate command (capture_cli) is the
# action; `replay_capture` emits the warning that points users at it.


def _parent_analyzer_count(parent: dict[str, Any]) -> int:
    """Number of `is_analyzer_device` entries in a parent's top-level `devices`
    array (0 if it has none / no array)."""
    return sum(1 for d in (parent.get("devices") or []) if is_analyzer_device(d))


def snapshot_needs_migration(snapshot: dict[str, Any]) -> bool:
    """True if `snapshot` predates SNP-8R4K's clean-at-rest contract and the
    one-time cleanup should run.

    Two independent triggers (either fires):
      * version: `snapshot_version` is missing or < SNAPSHOT_SCHEMA_VERSION
        (an unstamped or older snapshot).
      * pollution: any track or return `devices` array still carries an
        `is_analyzer_device` entry (a polluted snapshot — even one that has
        somehow been version-stamped — must still be cleaned).
    """
    version = snapshot.get("snapshot_version")
    if version is None or version < SNAPSHOT_SCHEMA_VERSION:
        return True
    parents = (snapshot.get("tracks") or []) + (snapshot.get("returns") or [])
    return any(_parent_analyzer_count(p) > 0 for p in parents)


def migrate_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Clean a committed snapshot at rest: drop `is_analyzer_device` entries +
    densely renumber survivors on every track and return, and stamp the schema
    version. Pure function — the input dict is never mutated.

    Returns ``(cleaned_snapshot, report)``. The report announces what was
    stripped so the rewrite is never silent::

        {
          "stripped": [{"parent": <name>, "kind": "track"|"return",
                        "removed": <count>}, ...],   # only parents with removals
          "total_removed": <int>,
          "version_before": <old version int or None>,
          "version_after": SNAPSHOT_SCHEMA_VERSION,
        }

    Reuses `_exclude_analyzer_from_parent` (the chunk-1 strip+densify helper) so
    the cleanup is identical to capture/replay — single source of truth, no
    reimplementation. The master path is intentionally untouched: the master
    has no device array in the snapshot today (SNP-4K7M); the analyzer filter
    joins the master path when SNP-4K7M lands master-device capture.
    """
    stripped: list[dict[str, Any]] = []

    def _clean(parents: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for parent in parents:
            removed = _parent_analyzer_count(parent)
            if removed:
                stripped.append({
                    "parent": parent.get("name"),
                    "kind": kind,
                    "removed": removed,
                })
            cleaned.append(_exclude_analyzer_from_parent(parent))
        return cleaned

    cleaned_tracks = _clean(snapshot.get("tracks") or [], "track")
    cleaned_returns = _clean(snapshot.get("returns") or [], "return")

    # Shallow-copy the top level; `_exclude_analyzer_from_parent` already returns
    # fresh parent/device dicts for the device arrays we rewrite, and untouched
    # sub-trees (song/master) are carried by reference unchanged. The input dict
    # is never mutated.
    cleaned = dict(snapshot)
    cleaned["tracks"] = cleaned_tracks
    cleaned["returns"] = cleaned_returns
    version_before = snapshot.get("snapshot_version")
    cleaned["snapshot_version"] = SNAPSHOT_SCHEMA_VERSION

    report = {
        "stripped": stripped,
        "total_removed": sum(s["removed"] for s in stripped),
        "version_before": version_before,
        "version_after": SNAPSHOT_SCHEMA_VERSION,
    }
    return cleaned, report


# ---------------------------------------------------------------------------
# Browser-path injection / preservation (Arc 7-tail / E3, snapshot-write side)
# ---------------------------------------------------------------------------
# E3 (Arc 7-tail, 2026-05-22) shipped the READ side of W13-A v1.0:
# `ableton_device(action='load')` returns `resolved_path`, replay_capture
# consumes snapshot `browser_path` into `devices.browser_path_json`, push
# threads it back to the load handler as a fallback identity. The producer
# side — where the agent captures `resolved_path` from a fresh load and
# attaches it to the snapshot's device entry — lives here.
#
# Two surfaces:
#
# - `inject_browser_paths(snapshot, loads)` — used by `/song-pick-instruments`
#   (and any other load-driven flow) after `ableton_device(action='load')`.
#   The agent records each load's `resolved_path` into a list of records;
#   this helper writes them into the right device entries on the assembled
#   snapshot. Top-level devices only (track + return chains); nested rack
#   chain devices loaded via `load_in_rack` are out of scope for v1 since
#   no current skill drives that path.
#
# - `preserve_browser_paths(old, new)` — used by `/song-snapshot` (the
#   refresh flow). Capture probes don't expose `browser_path` (Live doesn't
#   track each loaded device's browser origin), so without preservation
#   every refresh would silently drop the fallback identity for every
#   device. The helper copies `browser_path` from `old` to `new` for
#   devices whose identity matches (same parent index + position + class).
#   `browser_path` already present in `new` (e.g. just-loaded via
#   `inject_browser_paths`) wins over the old value.


def _attach_browser_path_to_device(
    parent: dict[str, Any],
    *,
    device_index: int,
    browser_path: list[str],
    parent_kind: str,
    parent_index: int,
) -> None:
    """Write `browser_path` onto the device at position `device_index` (1-based)
    in `parent["devices"]`. Raises if no such device exists — the caller
    passed a stale record."""
    devices = parent.get("devices") or []
    for d in devices:
        if int(d.get("index", -1)) == device_index:
            d["browser_path"] = list(browser_path)
            return
    raise ValueError(
        f"inject_browser_paths: no device at index={device_index} on "
        f"{parent_kind} {parent_index} (parent has "
        f"{len(devices)} device(s))"
    )


def inject_browser_paths(
    snapshot: dict[str, Any],
    loads: list[dict[str, Any]],
) -> None:
    """Attach `browser_path` to snapshot device entries the agent just loaded.

    Each load record (one per `ableton_device(action='load')` call the
    agent ran while assembling the snapshot):

      {"track_index":  int (>=1), "device_index": int (>=1),
       "browser_path": [str, ...]}
      OR
      {"return_index": int (>=1), "device_index": int (>=1),
       "browser_path": [str, ...]}

    `browser_path` is the value the MCP load handler returned as
    `resolved_path` — segments from the browser root key to the loaded
    item's leaf name. The push planner threads this onto subsequent loads
    as a fallback identity when the per-machine preset_uri stops resolving
    (different Live install, plugin moved between catalog versions).

    Mutates `snapshot` in place. Raises on malformed records or on records
    that don't match any device in the snapshot.
    """
    for record in loads:
        bp = record.get("browser_path")
        if not isinstance(bp, list) or not bp or not all(
            isinstance(s, str) and s for s in bp
        ):
            raise ValueError(
                "inject_browser_paths: each record must carry a non-empty "
                "browser_path list of non-empty strings; got "
                f"{bp!r} on record {record!r}"
            )
        if "device_index" not in record:
            raise ValueError(
                f"inject_browser_paths: record missing device_index: {record!r}"
            )
        device_index = int(record["device_index"])
        if device_index < 1:
            raise ValueError(
                f"inject_browser_paths: device_index must be >= 1, got "
                f"{device_index} on record {record!r}"
            )
        has_track = "track_index" in record
        has_return = "return_index" in record
        if has_track == has_return:
            raise ValueError(
                "inject_browser_paths: each record must carry exactly one of "
                f"track_index or return_index; got {record!r}"
            )
        if has_track:
            ti = int(record["track_index"])
            for t in snapshot.get("tracks") or []:
                if int(t.get("index", -1)) == ti:
                    _attach_browser_path_to_device(
                        t,
                        device_index=device_index,
                        browser_path=bp,
                        parent_kind="track",
                        parent_index=ti,
                    )
                    break
            else:
                raise ValueError(
                    f"inject_browser_paths: no track with index={ti} in "
                    "snapshot"
                )
        else:
            ri = int(record["return_index"])
            for r in snapshot.get("returns") or []:
                if int(r.get("index", -1)) == ri:
                    _attach_browser_path_to_device(
                        r,
                        device_index=device_index,
                        browser_path=bp,
                        parent_kind="return",
                        parent_index=ri,
                    )
                    break
            else:
                raise ValueError(
                    f"inject_browser_paths: no return with index={ri} in "
                    "snapshot"
                )


def _collect_browser_paths(
    snapshot: dict[str, Any],
) -> dict[tuple[str, int, int, Any], list[str]]:
    """Build an identity-keyed lookup of every top-level device that carries
    a `browser_path`. Key: (parent_kind, parent_index, device_index, class).
    The class is included so re-using an index slot with a different device
    (e.g. swap Operator for Wavetable at position 1) doesn't carry forward
    a stale path that no longer matches identity."""
    out: dict[tuple[str, int, int, Any], list[str]] = {}
    for t in snapshot.get("tracks") or []:
        if "index" not in t:
            continue
        ti = int(t["index"])
        for d in t.get("devices") or []:
            bp = d.get("browser_path")
            if not bp or "index" not in d:
                continue
            out[("track", ti, int(d["index"]), d.get("class"))] = list(bp)
    for r in snapshot.get("returns") or []:
        if "index" not in r:
            continue
        ri = int(r["index"])
        for d in r.get("devices") or []:
            bp = d.get("browser_path")
            if not bp or "index" not in d:
                continue
            out[("return", ri, int(d["index"]), d.get("class"))] = list(bp)
    return out


def preserve_browser_paths(
    old: dict[str, Any],
    new: dict[str, Any],
) -> None:
    """Copy `browser_path` from `old` snapshot to `new` for devices whose
    identity matches (same parent index + position + class).

    Used by `/song-snapshot` during refresh: capture probes don't expose
    `browser_path` (Live doesn't track each loaded device's browser
    origin), so without this preservation every refresh would silently
    drop the cross-machine fallback identity for every device.

    A `browser_path` already present on a `new` device wins (e.g. the
    flow just loaded a fresh device and `inject_browser_paths` attached
    its `resolved_path`). Position-or-class identity mismatch drops the
    old path silently — the device at that slot is a different one now.

    Mutates `new` in place.
    """
    old_paths = _collect_browser_paths(old)
    if not old_paths:
        return
    for t in new.get("tracks") or []:
        if "index" not in t:
            continue
        ti = int(t["index"])
        for d in t.get("devices") or []:
            if d.get("browser_path") or "index" not in d:
                continue
            key = ("track", ti, int(d["index"]), d.get("class"))
            if key in old_paths:
                d["browser_path"] = list(old_paths[key])
    for r in new.get("returns") or []:
        if "index" not in r:
            continue
        ri = int(r["index"])
        for d in r.get("devices") or []:
            if d.get("browser_path") or "index" not in d:
                continue
            key = ("return", ri, int(d["index"]), d.get("class"))
            if key in old_paths:
                d["browser_path"] = list(old_paths[key])


# ---------------------------------------------------------------------------
# Snapshot diff (W12-B)
# ---------------------------------------------------------------------------
# W12-B's `/song-snapshot` skill drives a fresh capture, then diffs the result
# against the on-disk `captured_session.json` so the user can see what changed
# before overwriting. The diff lives here (not in the skill body) so the
# matching logic is testable and the LLM doesn't have to re-derive it from a
# 50KB JSON every refresh.
#
# Identity rules:
#   - Returns matched by `index` (Live's 1-based return slot)
#   - Tracks matched by `index` (Live's 1-based track slot)
#   - Devices inside a chain matched by `index` within that chain
# Name drift is reported as a field_change, not as add/remove. Reordering
# Live's tracks moves the indices; we report that as removed-from-old-index
# + added-at-new-index rather than trying to track-by-name (Live allows
# duplicate track names, so name is not a reliable identity).
#
# Per-device dialed-param drift is diffed in full; nested rack chains are
# walked one level (matching `_replay_devices`). Recursively nested racks
# are reported as a single "subtree_changed" flag — keeping the depth bounded
# matches what replay supports anyway.


_MIXER_FIELDS = ("volume", "panning", "mute", "solo", "arm", "color")
_RETURN_FIELDS = ("name", "volume", "panning", "color")
_TRACK_IDENTITY_FIELDS = ("name", "type")
_DEVICE_IDENTITY_FIELDS = ("name", "class", "kind", "guess_uri")


def _field_diff(old: dict[str, Any], new: dict[str, Any], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Compare each named field in two dicts; return {field: {old, new}} entries
    where the value differs. Fields absent from one side are reported only when
    the other side has a non-None value (avoids spurious None-vs-missing churn)."""
    out: dict[str, dict[str, Any]] = {}
    for f in fields:
        o = old.get(f)
        n = new.get(f)
        if o == n:
            continue
        if o is None and n is None:
            continue
        out[f] = {"old": o, "new": n}
    return out


def _sends_diff(
    old_sends: dict[str, Any] | None,
    new_sends: dict[str, Any] | None,
) -> dict[str, Any]:
    """Diff two sends maps (return_name -> level). Returns
    {added: {name: level}, removed: {name: level}, changed: {name: {old, new}}}.
    Empty fields are omitted from the result."""
    old = old_sends or {}
    new = new_sends or {}
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, dict[str, Any]] = {}
    for k in old.keys() & new.keys():
        if old[k] != new[k]:
            changed[k] = {"old": old[k], "new": new[k]}
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _params_diff(
    old_params: dict[str, Any] | None,
    new_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Diff two `params_dialed` maps. Each entry is `{value, normalized}`; an
    entry differs if either subfield differs."""
    old = old_params or {}
    new = new_params or {}
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, dict[str, Any]] = {}
    for k in old.keys() & new.keys():
        if old[k] != new[k]:
            changed[k] = {"old": old[k], "new": new[k]}
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _devices_diff(
    old_devices: list[dict[str, Any]] | None,
    new_devices: list[dict[str, Any]] | None,
    _depth: int = 0,
) -> dict[str, Any]:
    """Diff two device arrays (top-level or nested-chain). Matches by `index`."""
    old = old_devices or []
    new = new_devices or []
    old_by_idx = {int(d["index"]): d for d in old if "index" in d}
    new_by_idx = {int(d["index"]): d for d in new if "index" in d}
    added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
    removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
    changed: list[dict[str, Any]] = []
    for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
        od = old_by_idx[i]
        nd = new_by_idx[i]
        entry: dict[str, Any] = {"index": i}
        fc = _field_diff(od, nd, _DEVICE_IDENTITY_FIELDS)
        if fc:
            entry["field_changes"] = fc
        pd = _params_diff(od.get("params_dialed"), nd.get("params_dialed"))
        if pd:
            entry["params"] = pd
        # Nested rack chains: walk one level, matching capture/replay depth.
        old_chains = od.get("chains")
        new_chains = nd.get("chains")
        if old_chains or new_chains:
            if _depth > 0:
                # Deeper-than-one-level nested chains: flag as opaque change.
                if old_chains != new_chains:
                    entry["nested_chains_subtree_changed"] = True
            else:
                cd = _chains_diff(old_chains, new_chains)
                if cd:
                    entry["chains"] = cd
        if len(entry) > 1:
            entry["name"] = nd.get("name", od.get("name"))
            changed.append(entry)
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _chains_diff(
    old_chains: list[dict[str, Any]] | None,
    new_chains: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Diff two `chains` arrays (rack-device nested chains). Matches by
    `chain_index`. Each chain's devices are diffed at `_depth=1` so the
    'one level only' invariant from replay holds."""
    old = old_chains or []
    new = new_chains or []
    old_by_idx = {int(c["chain_index"]): c for c in old if "chain_index" in c}
    new_by_idx = {int(c["chain_index"]): c for c in new if "chain_index" in c}
    added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
    removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
    changed: list[dict[str, Any]] = []
    for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
        oc = old_by_idx[i]
        nc = new_by_idx[i]
        entry: dict[str, Any] = {"chain_index": i}
        if oc.get("name") != nc.get("name"):
            entry["name_change"] = {"old": oc.get("name"), "new": nc.get("name")}
        dd = _devices_diff(oc.get("devices"), nc.get("devices"), _depth=1)
        if dd:
            entry["devices"] = dd
        if len(entry) > 1:
            changed.append(entry)
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _entity_diff(old: dict[str, Any], new: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Diff a track or return: mixer/identity fields + sends + devices.
    `fields` selects the named-field set (different for track vs return)."""
    entry: dict[str, Any] = {"index": int(new.get("index", old.get("index")))}
    fc = _field_diff(old, new, fields)
    if fc:
        entry["field_changes"] = fc
    sd = _sends_diff(old.get("sends"), new.get("sends"))
    if sd:
        entry["sends"] = sd
    dd = _devices_diff(old.get("devices"), new.get("devices"))
    if dd:
        entry["devices"] = dd
    return entry


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compute a structured diff between two captured-session snapshots.

    Identity: tracks/returns matched by `index`; devices within a chain matched
    by `index` within that chain. Name drift is a field-change, not an
    add/remove (Live track names aren't unique enough to use as identity).

    Returns a dict with keys (only those with non-empty content):

      ``song``    : ``{field: {old, new}}`` for tempo / signature changes
      ``master``  : ``{field: {old, new}}`` for master volume/pan changes
      ``returns`` : ``{added: [...], removed: [...], changed: [entity_diff]}``
      ``tracks``  : same shape as ``returns``

    An ``entity_diff`` is:

      ``{index, field_changes, sends, devices}`` — any field is omitted if the
      sub-diff is empty.

    The whole result is empty (`{}`) when snapshots are identical at this
    schema's resolution. Caller checks ``not result`` to know "no changes."
    """
    out: dict[str, Any] = {}

    old_song = old.get("song") or {}
    new_song = new.get("song") or {}
    song_fc = _field_diff(old_song, new_song, ("tempo", "signature"))
    if song_fc:
        out["song"] = song_fc
    master_fc = _field_diff(
        old_song.get("master") or {},
        new_song.get("master") or {},
        ("volume", "panning"),
    )
    if master_fc:
        out["master"] = master_fc

    for kind, fields in (("returns", _RETURN_FIELDS), ("tracks", _MIXER_FIELDS + _TRACK_IDENTITY_FIELDS)):
        old_items = old.get(kind) or []
        new_items = new.get(kind) or []
        old_by_idx = {int(it["index"]): it for it in old_items if "index" in it}
        new_by_idx = {int(it["index"]): it for it in new_items if "index" in it}
        added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
        removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
        changed: list[dict[str, Any]] = []
        for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
            entry = _entity_diff(old_by_idx[i], new_by_idx[i], fields)
            if len(entry) > 1:
                changed.append(entry)
        sub: dict[str, Any] = {}
        if added:
            sub["added"] = added
        if removed:
            sub["removed"] = removed
        if changed:
            sub["changed"] = changed
        if sub:
            out[kind] = sub

    return out


# ---------------------------------------------------------------------------
# Snapshot merge (Group 1 / G1-C — browser_path stickiness floor)
# ---------------------------------------------------------------------------
# `browser_path` (Arc 7-tail / E3, W13-A v1.0) is captured at LOAD time by
# the MCP load handler's `resolved_path` response field. The list-time
# probes that drive `/song-snapshot` (`ableton_track(action='info')`,
# `ableton_device(action='get_parameters')`) don't surface it — Live's API
# exposes the path only via the browser walk performed at load.
#
# Without stickiness, refreshing a snapshot would wipe every device's
# `browser_path`, breaking the W13-A v1.0 cross-machine fallback identity
# whenever someone re-snapshots a song. Autonomous re-capture (load-time
# snapshot write) is the longer-term fix and is tracked separately; this
# merge helper is the floor that keeps existing values from getting lost.
#
# Sticky fields (preserved when `new` omits them):
#   - device-level `browser_path`
# Other fields use `new`'s value verbatim (intentional drift: a knob move
# captured in the fresh probe must overwrite the on-disk value).

_DEVICE_STICKY_FIELDS: tuple[str, ...] = ("browser_path",)


def _merge_devices(
    old_devices: list[dict[str, Any]] | None,
    new_devices: list[dict[str, Any]] | None,
    _depth: int = 0,
) -> list[dict[str, Any]]:
    """Walk two device arrays (matched by `index`), returning `new` with
    sticky fields copied from the matching `old` entry when `new` doesn't
    carry them. Recurses one level into nested rack `chains` to match the
    capture / replay / diff depth invariant.
    """
    new = new_devices or []
    old_by_idx = {
        int(d["index"]): d for d in (old_devices or []) if "index" in d
    }
    merged: list[dict[str, Any]] = []
    for nd in new:
        if "index" not in nd:
            merged.append(nd)
            continue
        od = old_by_idx.get(int(nd["index"]))
        if od is None:
            merged.append(nd)
            continue
        entry = dict(nd)
        for field in _DEVICE_STICKY_FIELDS:
            if entry.get(field) in (None, [], {}) and od.get(field) not in (
                None, [], {},
            ):
                entry[field] = od[field]
        if _depth == 0 and (entry.get("chains") or od.get("chains")):
            entry["chains"] = _merge_chains(
                od.get("chains"), entry.get("chains"),
            )
        merged.append(entry)
    return merged


def _merge_chains(
    old_chains: list[dict[str, Any]] | None,
    new_chains: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Walk two nested-chain arrays (matched by `chain_index`), merging
    each chain's devices at `_depth=1`. Returns the new chains with
    stickiness applied; an old-only chain isn't preserved (chain
    structure tracks Live, not the snapshot's history)."""
    new = new_chains or []
    old_by_idx = {
        int(c["chain_index"]): c for c in (old_chains or [])
        if "chain_index" in c
    }
    merged: list[dict[str, Any]] = []
    for nc in new:
        if "chain_index" not in nc:
            merged.append(nc)
            continue
        oc = old_by_idx.get(int(nc["chain_index"]))
        if oc is None:
            merged.append(nc)
            continue
        entry = dict(nc)
        entry["devices"] = _merge_devices(
            oc.get("devices"), nc.get("devices"), _depth=1,
        )
        merged.append(entry)
    return merged


def merge_snapshots(
    old: dict[str, Any], new: dict[str, Any],
) -> dict[str, Any]:
    """Return a snapshot dict that takes `new` as base but preserves
    sticky device fields (`browser_path`) from `old` where `new` omits
    them. Other fields use `new`'s value verbatim — a snapshot refresh
    must reflect the user's actual changes (knob moves, send tweaks,
    track renames) without false drift.

    The merge is structural — track / return / device identity is
    `index`; nested-rack chains match by `chain_index`. Recurses one
    level into rack chains to match capture/replay/diff depth.
    """
    out = dict(new)
    old_tracks = old.get("tracks") or []
    new_tracks = new.get("tracks") or []
    old_tracks_by_idx = {
        int(t["index"]): t for t in old_tracks if "index" in t
    }
    merged_tracks: list[dict[str, Any]] = []
    for nt in new_tracks:
        if "index" not in nt:
            merged_tracks.append(nt)
            continue
        ot = old_tracks_by_idx.get(int(nt["index"]))
        if ot is None:
            merged_tracks.append(nt)
            continue
        entry = dict(nt)
        if ot.get("devices") or nt.get("devices"):
            entry["devices"] = _merge_devices(
                ot.get("devices"), nt.get("devices"),
            )
        merged_tracks.append(entry)
    out["tracks"] = merged_tracks

    old_returns = old.get("returns") or []
    new_returns = new.get("returns") or []
    old_returns_by_idx = {
        int(r["index"]): r for r in old_returns if "index" in r
    }
    merged_returns: list[dict[str, Any]] = []
    for nr in new_returns:
        if "index" not in nr:
            merged_returns.append(nr)
            continue
        or_ = old_returns_by_idx.get(int(nr["index"]))
        if or_ is None:
            merged_returns.append(nr)
            continue
        entry = dict(nr)
        if or_.get("devices") or nr.get("devices"):
            entry["devices"] = _merge_devices(
                or_.get("devices"), nr.get("devices"),
            )
        merged_returns.append(entry)
    out["returns"] = merged_returns
    return out


def format_diff_summary(diff: dict[str, Any]) -> str:
    """One-screen human-readable summary of a diff dict. The skill prints this
    for the user, then asks to confirm overwrite. Detailed per-param drift is
    summarized as counts; users who want the full per-field detail read the
    JSON itself."""
    if not diff:
        return "No changes — snapshot is up to date."
    lines: list[str] = []
    if "song" in diff:
        for f, ch in diff["song"].items():
            lines.append(f"  song.{f}: {ch['old']!r} -> {ch['new']!r}")
    if "master" in diff:
        for f, ch in diff["master"].items():
            lines.append(f"  master.{f}: {ch['old']!r} -> {ch['new']!r}")
    for kind in ("returns", "tracks"):
        sub = diff.get(kind)
        if not sub:
            continue
        for item in sub.get("added") or []:
            lines.append(f"  +{kind[:-1]} {item.get('index')} {item.get('name')!r}")
        for item in sub.get("removed") or []:
            lines.append(f"  -{kind[:-1]} {item.get('index')} {item.get('name')!r}")
        for item in sub.get("changed") or []:
            idx = item["index"]
            bits: list[str] = []
            if "field_changes" in item:
                bits.append(f"{len(item['field_changes'])} field(s)")
            if "sends" in item:
                s = item["sends"]
                send_bits = []
                if s.get("added"):
                    send_bits.append(f"+{len(s['added'])}")
                if s.get("removed"):
                    send_bits.append(f"-{len(s['removed'])}")
                if s.get("changed"):
                    send_bits.append(f"~{len(s['changed'])}")
                bits.append(f"sends {' '.join(send_bits)}")
            if "devices" in item:
                d = item["devices"]
                dev_bits = []
                if d.get("added"):
                    dev_bits.append(f"+{len(d['added'])}")
                if d.get("removed"):
                    dev_bits.append(f"-{len(d['removed'])}")
                if d.get("changed"):
                    dev_bits.append(f"~{len(d['changed'])}")
                bits.append(f"devices {' '.join(dev_bits)}")
            lines.append(f"  ~{kind[:-1]} {idx}: {', '.join(bits)}")
    return "\n".join(lines) if lines else "No changes — snapshot is up to date."
