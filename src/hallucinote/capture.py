"""Live-Ableton snapshot format and replay.

The snapshot is a JSON document describing the mix layout of an Ableton set —
tracks (with kind + mixer state), returns, sends, the master strip, and (post
chunk 4a) device chains with dialed parameters. It is the seed mechanism for
`build.py`: capture once (live Ableton -> snapshot.json), then replay into the
DB through mutators.

Scope (chunks 3 + 4a): tracks + returns + sends + master + mixer state +
top-level device chains + dialed device parameters. Nested rack chains
(`DrumGroupDevice` pads, `InstrumentGroupDevice` chains) are schema-supported
but NOT yet populated by replay — the snapshot's `_note` flags them as
"internal chain instruments not captured" and MCP gap #17b currently blocks
deep probe. Automation envelopes (chunk 4b) are schema-modeled and push-
plannable but the capture/replay path doesn't ingest them yet — MCP exposes
no read surface for the seven envelope target families (see
docs/mcp-requirements.md, chunk-4b section).

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
MCP probes (`ableton_session(action='info')`, `get_track_info`,
`list_return_tracks`, `get_track_sends`, `get_track_volume`) and assembles
the dict via `compile_snapshot`. The non-session-domain probes retarget to
the unified surface in Wave M-2 onward. See `tools/capture.py` for the probe
sequence.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

SNAPSHOT_FORMAT_VERSION = 1

# Track types accepted in snapshot["tracks"][n]["type"]; mapped 1:1 to
# `tracks.kind` in the DB. Unknown values raise; the snapshot is authoritative.
_VALID_TRACK_TYPES = frozenset({"midi", "audio", "group"})


# Live 12.4 unconditionally prefixes every `ReturnTrack.name` with a
# `<slot-letter>-` segment (A-, B-, ..., Z-). Storing the prefixed form in
# the DB causes double-prefixing on push (DB "A-Reverb" → Live "A-A-Reverb").
# W3-H real-Live finding (2026-05-18); W4-C cross-layer fix.
_RETURN_SLOT_PREFIX = re.compile(r"^[A-Z]-")


def strip_return_slot_prefix(name: str | None) -> str | None:
    """Strip Live's `<slot-letter>-` prefix from a return-track name.

    Idempotent: names without the prefix (already-stripped, or never had it)
    pass through unchanged. The DB stores SUFFIX-only return names; push
    re-emits the suffix and Live re-adds its slot prefix.
    """
    if name is None:
        return None
    return _RETURN_SLOT_PREFIX.sub("", name, count=1)


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
) -> None:
    """Insert each entry of `devices_array` into the given chain, plus any
    dialed parameters. Nested rack chains are not recursed — see module
    docstring on the capture/MCP gap.
    """
    for d in devices_array:
        if "index" not in d or "class" not in d:
            raise ValueError(
                f"snapshot device missing required keys (index, class): {d!r}"
            )
        device_id = M.create_device(
            conn,
            chain_id=chain_id,
            position=int(d["index"]),
            kind=d["class"],
            display_name=d.get("name", d["class"]),
            preset_uri=d.get("guess_uri"),
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
            M.set_device_parameter(
                conn,
                device_id=device_id,
                name=name,
                value_display=str(p["value"]),
                value_normalized=(
                    float(normalized) if normalized is not None else None
                ),
                actor=actor,
                request_id=request_id,
                reason=reason,
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
    """Replay a snapshot into a fresh song in the DB. Returns the new song_id.

    Idempotency / overwrite: callers are expected to operate on a fresh DB (or
    a song that doesn't yet exist). Replay does not delete prior state; if the
    song already exists, it raises so a stale partial replay can't shadow real
    data.

    Notes/clips/devices in the snapshot are ignored — chunk 3 covers only the
    mix layout. Score-half (tempo/time-signature/sections/cue points) is also
    not populated by replay; build.py is expected to author those alongside
    the captured mix.
    """
    if Q.get_song_by_name(conn, song_name) is not None:
        raise ValueError(
            f"song {song_name!r} already exists; replay expects a clean slate"
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
    for r in snapshot.get("returns") or []:
        # W4-C: strip Live's `<letter>-` slot prefix on the way into the DB.
        # The snapshot's `t["sends"]` is keyed by the SAME prefixed names
        # Live reports, so we strip on the lookup side too (below).
        stripped_name = strip_return_slot_prefix(r["name"])
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

    Chunk 3 baseline: tempo/master/returns/tracks/sends. Chunk 4a adds device
    probes — `get_track_info` already returns top-level device lists, but the
    per-device parameter probe (`get_device_parameters`) is MCP gap #17b
    (raises `No module named 'MCP_Server'`). Until that's patched, the agent
    captures device chain identity (kind + display_name + position) but not
    dialed parameters. Nested rack chains remain a separate MCP gap (see
    docs/mcp-requirements.md, chunk-4 P2 section).
    """
    return [
        {"tool": "ableton_session(action='info')",
         "purpose": "global state: tempo, signature, master volume/pan, track counts"},
        {"tool": "list_return_tracks",
         "purpose": "return tracks: name + volume + pan per return; "
                    "chunk 4a: include each return's top-level device chain"},
        {"tool": "get_track_info",
         "purpose": "per-track: name, type, volume, pan, mute/solo/arm, "
                    "top-level device chain (kind + display_name + position) "
                    "— loop over tracks"},
        {"tool": "get_track_sends",
         "purpose": "per-track: sends map keyed by return name (loop over tracks)"},
        {"tool": "get_device_parameters",
         "purpose": "per-device: dialed parameter map "
                    "(name -> {value, normalized}) — loop over each device. "
                    "MCP gap #17b: currently raises, captures parameters "
                    "only when patched"},
    ]


def compile_snapshot(
    *,
    session_info: dict[str, Any],
    returns: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a snapshot dict from raw MCP probe outputs.

    Inputs are already-shaped dicts:
      session_info = {tempo, signature, master: {volume, panning}, ...}
      returns      = [{index, name, volume, panning, ...}, ...]
      tracks       = [{index, name, type, volume, panning, mute, solo, arm,
                        sends: {return_name: level, ...}, ...}, ...]

    Output is normalized to the snapshot schema documented in this module.
    Devices/clips on inputs are preserved verbatim; replay ignores them.
    """
    return {
        "song": {
            "tempo": session_info.get("tempo"),
            "signature": session_info.get("signature"),
            "master": session_info.get("master"),
        },
        "returns": returns,
        "tracks": tracks,
    }
