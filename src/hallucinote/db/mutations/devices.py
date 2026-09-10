"""Mix: device chains, devices, parameters, drum-pad mappings, and
automation envelopes + breakpoints.

Envelopes live here (rather than a separate module) because the envelope
mutators resolve song provenance through the device/chain helpers
(`_resolve_device_song`, `_resolve_chain_song`) defined for devices.
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Sequence

from hallucinote.db import queries as Q
from hallucinote.preset_query import normalize as _normalize_preset_query

from .tracks import TRACK_KINDS

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _touches,
    _uuid,
    json,
    transaction,
)


# ---------------------------------------------------------------------------
# Mix: device chains, devices, parameters
# ---------------------------------------------------------------------------
# Parent enforcement: `create_device_chain` accepts exactly one of three
# parent kwargs. The schema CHECK also enforces this, but raising in Python
# yields a clean error before the DB does. Top-level chains (track / return)
# use position=0 by convention; rack chains use their position within the
# parent rack device.


@_atomic
def create_device_chain(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None = None,
    parent_return_id: str | None = None,
    parent_rack_device_id: str | None = None,
    position: int = 0,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    parents = [
        ("parent_track_id", parent_track_id),
        ("parent_return_id", parent_return_id),
        ("parent_rack_device_id", parent_rack_device_id),
    ]
    set_parents = [(k, v) for k, v in parents if v is not None]
    if len(set_parents) != 1:
        raise ValueError(
            f"create_device_chain: exactly one parent kwarg required, "
            f"got {[k for k, _ in set_parents]}"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Identity by (parent_*_id, position). Each parent column is mutually
    # exclusive by schema CHECK, so the SELECT below matches on the one set.
    existing = conn.execute(
        """SELECT id FROM device_chains
           WHERE parent_track_id IS ? AND parent_return_id IS ?
             AND parent_rack_device_id IS ? AND position = ?""",
        (parent_track_id, parent_return_id, parent_rack_device_id, position),
    ).fetchone()
    if existing is not None:
        # Identity is (parent, position) — an existing match is the same chain.
        # Its per-drum properties (choke_group / out_note) are NOT touched here;
        # they ride `set_chain_properties` (NODE-ADDR Chunk C), symmetric with
        # how a track's routing rides set_track_routing, not create_track.
        chain_id = existing["id"]
        _record_touch_if_session("device_chain", chain_id)
        return MutatorResult(chain_id, "unchanged")
    chain_id = _uuid()
    conn.execute(
        """INSERT INTO device_chains
               (id, parent_track_id, parent_return_id, parent_rack_device_id, position)
           VALUES (?, ?, ?, ?, ?)""",
        (chain_id, parent_track_id, parent_return_id, parent_rack_device_id, position),
    )
    # Resolve song_id for the event so audit queries find it via song.
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=parent_track_id,
        parent_return_id=parent_return_id,
        parent_rack_device_id=parent_rack_device_id,
    )
    _emit(
        conn,
        E.DEVICE_CHAIN_CREATED,
        {
            "chain_id": chain_id,
            "parent_track_id": parent_track_id,
            "parent_return_id": parent_return_id,
            "parent_rack_device_id": parent_rack_device_id,
            "position": position,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device_chain", chain_id)
    return MutatorResult(chain_id, "created")


def _resolve_chain_song(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None,
    parent_return_id: str | None,
    parent_rack_device_id: str | None,
) -> str | None:
    """Walk a chain's parent up to its song_id. Nested rack chains recurse
    through their parent device's chain until reaching a track or return."""
    if parent_track_id is not None:
        row = conn.execute(
            "SELECT song_id FROM tracks WHERE id = ?", (parent_track_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_return_id is not None:
        row = conn.execute(
            "SELECT song_id FROM returns WHERE id = ?", (parent_return_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_rack_device_id is not None:
        # Device -> its chain -> recurse on that chain's parent.
        row = conn.execute(
            """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (parent_rack_device_id,),
        ).fetchone()
        if row is None:
            return None
        return _resolve_chain_song(
            conn,
            parent_track_id=row["parent_track_id"],
            parent_return_id=row["parent_return_id"],
            parent_rack_device_id=row["parent_rack_device_id"],
        )
    return None


# NODE-ADDR Chunk C/F: per-chain authored properties. Sentinel distinguishes
# "field not passed" from "field passed as None" (None = clear to the Live
# default — a meaningful value, exactly like set_track_routing's clear-a-route).
# Chunk C: choke_group / out_note (DrumChain only). Chunk F: mute / solo /
# volume / pan (every chain — the per-chain mixer state).
_UNSET: Any = object()
_CHAIN_PROP_FIELDS: tuple[str, ...] = (
    "choke_group", "out_note", "mute", "solo", "volume", "pan",
)


@_touches("device_chain", "chain_id")
@_atomic
def set_chain_properties(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    choke_group: Any = _UNSET,
    out_note: Any = _UNSET,
    mute: Any = _UNSET,
    solo: Any = _UNSET,
    volume: Any = _UNSET,
    pan: Any = _UNSET,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> MutatorResult:
    """Partial update of a chain's authored properties (NODE-ADDR Chunk C/F).
    Only fields actually passed are touched; pass a field as ``None`` to clear
    it to the Live default — symmetric with ``set_track_routing``'s
    clear-a-route. Idempotent: per-field diff against the current row, emits
    ``DEVICE_CHAIN_PROPS_SET`` only when something changes.

    ``choke_group`` / ``out_note`` (Chunk C) exist on a ``DrumChain`` only;
    ``mute`` / ``solo`` / ``volume`` / ``pan`` (Chunk F — the per-chain mixer
    state) exist on every chain. The capture / pull paths store them
    non-default-filtered (choke != 0, out_note != in_note, mute/solo only when
    set, volume/pan only off their preset default). The mutator itself is
    storage-only — it does not re-probe Live; the handler / capability matrix
    own the per-property "does this chain have it?" decision.
    """
    changes: dict[str, Any] = {}
    if choke_group is not _UNSET:
        changes["choke_group"] = choke_group
    if out_note is not _UNSET:
        changes["out_note"] = out_note
    if mute is not _UNSET:
        changes["mute"] = mute
    if solo is not _UNSET:
        changes["solo"] = solo
    if volume is not _UNSET:
        changes["volume"] = volume
    if pan is not _UNSET:
        changes["pan"] = pan
    if not changes:
        return MutatorResult(chain_id, "unchanged")
    if changes.get("choke_group") is not None:
        cg = changes["choke_group"]
        if not isinstance(cg, int) or isinstance(cg, bool) or cg < 0:
            raise ValueError(
                f"choke_group must be a non-negative int or None, got {cg!r}"
            )
    if changes.get("out_note") is not None:
        on = changes["out_note"]
        if not isinstance(on, int) or isinstance(on, bool) or not (0 <= on <= 127):
            raise ValueError(
                f"out_note must be a MIDI note 0..127 or None, got {on!r}"
            )
    for flag in ("mute", "solo"):
        if changes.get(flag) is not None:
            fv = changes[flag]
            # bools are accepted and coerced to 0/1 (the wire passes bool, the DB
            # stores int) — but reject other types and out-of-range ints.
            if isinstance(fv, bool):
                changes[flag] = int(fv)
            elif isinstance(fv, int) and fv in (0, 1):
                pass
            else:
                raise ValueError(
                    f"{flag} must be 0/1 (or bool) or None, got {fv!r}"
                )
    if changes.get("volume") is not None:
        vol = changes["volume"]
        if not isinstance(vol, (int, float)) or isinstance(vol, bool) \
                or not (0.0 <= float(vol) <= 1.0):
            raise ValueError(
                f"volume must be a float 0.0..1.0 or None, got {vol!r}"
            )
        changes["volume"] = float(vol)
    if changes.get("pan") is not None:
        pn = changes["pan"]
        if not isinstance(pn, (int, float)) or isinstance(pn, bool) \
                or not (-1.0 <= float(pn) <= 1.0):
            raise ValueError(
                f"pan must be a float -1.0..1.0 or None, got {pn!r}"
            )
        changes["pan"] = float(pn)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    row = conn.execute(
        """SELECT parent_track_id, parent_return_id, parent_rack_device_id,
                  choke_group, out_note, mute, solo, volume, pan
           FROM device_chains WHERE id = ?""",
        (chain_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"set_chain_properties: no device_chains row {chain_id!r}"
        )
    actual = {k: v for k, v in changes.items() if row[k] != v}
    if not actual:
        return MutatorResult(chain_id, "unchanged")
    sets = ", ".join(f"{k} = ?" for k in actual)
    conn.execute(
        f"UPDATE device_chains SET {sets} WHERE id = ?",
        [*actual.values(), chain_id],
    )
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )
    _emit(
        conn,
        E.DEVICE_CHAIN_PROPS_SET,
        {"chain_id": chain_id, "changes": actual},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return MutatorResult(chain_id, "updated")


@_atomic
def delete_device_chain(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        """SELECT parent_track_id, parent_return_id, parent_rack_device_id
           FROM device_chains WHERE id = ?""",
        (chain_id,),
    ).fetchone()
    if row is None:
        return
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )
    conn.execute("DELETE FROM device_chains WHERE id = ?", (chain_id,))
    _emit(
        conn,
        E.DEVICE_CHAIN_DELETED,
        {"chain_id": chain_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


@_atomic
def create_device(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    position: int,
    kind: str,
    display_name: str,
    class_name: str | None = None,
    preset_uri: str | None = None,
    preset_query: dict[str, Any] | str | None = None,
    browser_path: list[str] | None = None,
    audio_file: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a device in `chain_id` at 1-based `position`.

    Arc 4 / D4 convention:
    - ``kind`` is the BROWSER DISPLAY NAME (= Live's
      ``device.class_display_name``): ``"Compressor"`` / ``"Phaser-Flanger"``
      / ``"EQ Eight"`` / ``"Operator"``. The loader's kind-as-given walk
      matches against this directly in Live's browser tree.
    - ``class_name`` (optional) is Live's INTERNAL class identifier:
      ``"Compressor2"`` / ``"PhaserNew"`` / ``"PluginDevice"``.
      Informational + drives plugin classification (compat-check reads
      this to detect third-party plugins). Captured-from-Live writes
      populate it; hand-authored snapshots may omit it.
    - ``display_name`` is the user-visible instance label. Often equals
      ``kind`` for default loads; diverges on preset loads (``"Hall"``
      on a Hybrid Reverb) and user renames (``"Bass Squish"`` on a
      Compressor).

    ``preset_uri`` and ``preset_query`` are mutually exclusive selectors —
    pass one or the other (or neither, for kind-only loading).
    ``preset_query`` is the compose-time portable form (Sweep B): a dict
    ``{root, pattern, mode?, path_prefix?, case_sensitive?}`` stored as
    JSON; the push planner threads it through to
    ``ableton_device(action='load', preset_query=...)`` which resolves on the
    consumer's machine. ``preset_uri`` is the per-machine canonical URI.

    Arc 3 / C2: ``preset_query`` also accepts a path-shape string like
    ``"Drums/Kit-Core 909"`` — normalized to the canonical dict via
    :func:`hallucinote.preset_query.parse_path_shape` before persistence.

    SMP-7K2D: ``audio_file`` assigns a sample to a sampler instrument
    (Simpler/Sampler) — a song-relative POSIX path (canonically under
    ``assets/``) or absolute, stored exactly as authored and resolved at push
    via :func:`hallucinote.paths.resolve_audio_path` (the same resolver
    ``clips.audio_file`` uses). NULL for non-sampler devices. No device-kind
    guard here on purpose — capability is probed/adapted at push, not whitelisted
    (third-party samplers must work too). Window / reverse / pitch / gain are
    NOT carried here; they are ``device_parameters`` (static) or
    ``device_parameter`` envelopes (automated).
    """
    if position < 1:
        raise ValueError(f"device position {position} must be >= 1")
    if preset_uri is not None and preset_query is not None:
        raise ValueError(
            "preset_uri and preset_query are mutually exclusive — pass one "
            "(preset_query for cross-machine portability, preset_uri for "
            "an unambiguous per-machine URI)"
        )
    if browser_path is not None:
        if (
            not isinstance(browser_path, list)
            or len(browser_path) < 1
            or not all(isinstance(s, str) and s for s in browser_path)
        ):
            raise ValueError(
                "browser_path must be a non-empty list of non-empty strings "
                "from the browser root to the loaded item — got "
                f"{browser_path!r}"
            )
    preset_query = _normalize_preset_query(preset_query)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    preset_query_json = (
        json.dumps(preset_query, sort_keys=True) if preset_query is not None
        else None
    )
    browser_path_json = (
        json.dumps(browser_path) if browser_path is not None else None
    )
    existing = conn.execute(
        """SELECT id, kind, display_name, class_name, preset_uri, preset_query,
                  browser_path_json, audio_file
           FROM devices WHERE chain_id = ? AND position = ?""",
        (chain_id, position),
    ).fetchone()
    if existing is not None:
        device_id = existing["id"]
        existing_browser_path_json = (
            existing["browser_path_json"]
            if "browser_path_json" in existing.keys() else None
        )
        if (
            existing["kind"], existing["display_name"], existing["class_name"],
            existing["preset_uri"], existing["preset_query"],
            existing_browser_path_json, existing["audio_file"],
        ) == (
            kind, display_name, class_name, preset_uri, preset_query_json,
            browser_path_json, audio_file,
        ):
            _record_touch_if_session("device", device_id)
            return MutatorResult(device_id, "unchanged")
        conn.execute(
            """UPDATE devices SET kind = ?, display_name = ?, class_name = ?,
                                  preset_uri = ?, preset_query = ?,
                                  browser_path_json = ?, audio_file = ?
               WHERE id = ?""",
            (kind, display_name, class_name, preset_uri, preset_query_json,
             browser_path_json, audio_file, device_id),
        )
        song_id = _resolve_device_song(conn, device_id=device_id)
        _emit(
            conn, E.DEVICE_CREATED,
            {"device_id": device_id, "chain_id": chain_id, "position": position,
             "kind": kind, "display_name": display_name,
             "class_name": class_name,
             "preset_uri": preset_uri, "preset_query": preset_query,
             "browser_path": browser_path,
             "audio_file": audio_file,
             "result_kind": "updated"},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
        _record_touch_if_session("device", device_id)
        return MutatorResult(device_id, "updated")
    device_id = _uuid()
    conn.execute(
        """INSERT INTO devices (id, chain_id, position, kind, display_name,
                                class_name, preset_uri, preset_query,
                                browser_path_json, audio_file)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (device_id, chain_id, position, kind, display_name,
         class_name, preset_uri, preset_query_json, browser_path_json,
         audio_file),
    )
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_CREATED,
        {
            "device_id": device_id,
            "chain_id": chain_id,
            "position": position,
            "kind": kind,
            "display_name": display_name,
            "class_name": class_name,
            "preset_uri": preset_uri,
            "preset_query": preset_query,
            "browser_path": browser_path,
            "audio_file": audio_file,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device", device_id)
    return MutatorResult(device_id, "created")


@_touches("device", "device_id")
@_atomic
def set_device_sidechain(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    source_track_id: str | None,
    channel: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Set (or clear) a device's sidechain SOURCE — SDC-7K3M.

    The source is a SEMANTIC reference (FK to the source track), symmetric with
    ``set_track_routing``'s track-FK input routing: it survives renames + the
    rebuild→push loop. Push resolves it to Live's display_name via the device's
    ``set_input_routing``; pull captures it via ``get_input_routing``. The
    ``S/C On`` / ``S/C Gain`` / ``S/C Mix`` params are ordinary
    ``device_parameters`` and round-trip separately — the SOURCE is the one piece
    they can't carry.

    ``source_track_id=None`` clears the sidechain source (and forces ``channel``
    NULL — a channel with no source is meaningless). ``channel`` is Live's input
    channel display_name (Pre FX / Post FX / Post Mixer); NULL = device default.

    No device-kind guard: sidechain capability is probed at push (Live exposes
    input routing on Compressor / Gate / plugins carrying an ``S/C`` param),
    never whitelisted.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    row = conn.execute(
        """SELECT sidechain_source_track_id, sidechain_source_channel
           FROM devices WHERE id = ?""",
        (device_id,),
    ).fetchone()
    if row is None:
        return
    song_id = _resolve_device_song(conn, device_id=device_id)
    if source_track_id is None:
        channel = None  # no source ⇒ no channel
    else:
        trow = conn.execute(
            "SELECT song_id FROM tracks WHERE id = ?", (source_track_id,)
        ).fetchone()
        if trow is None:
            raise ValueError(
                f"sidechain source_track_id {source_track_id!r} does not "
                "reference an existing track"
            )
        if song_id is not None and trow["song_id"] != song_id:
            raise ValueError(
                f"sidechain source_track_id {source_track_id!r} belongs to a "
                "different song than the device"
            )
    # Idempotent — skip the event when nothing changes.
    if (row["sidechain_source_track_id"], row["sidechain_source_channel"]) == (
        source_track_id, channel,
    ):
        return
    conn.execute(
        """UPDATE devices SET sidechain_source_track_id = ?,
                              sidechain_source_channel = ?
           WHERE id = ?""",
        (source_track_id, channel, device_id),
    )
    _emit(
        conn,
        E.DEVICE_SIDECHAIN_SET,
        {"device_id": device_id, "source_track_id": source_track_id,
         "channel": channel},
        song_id=song_id, actor=actor, request_id=request_id, reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def _resolve_device_song(
    conn: sqlite3.Connection,
    *,
    device_id: str,
) -> str | None:
    row = conn.execute(
        """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE d.id = ?""",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )


@_atomic
def delete_device(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    song_id = _resolve_device_song(conn, device_id=device_id)
    cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    if cur.rowcount == 0:
        return
    _emit(
        conn,
        E.DEVICE_DELETED,
        {"device_id": device_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


@_atomic
def set_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    value_display: str,
    value_normalized: float | None = None,
    value_items: Sequence[str] | None = None,
    value_raw: float | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Upsert a device parameter by (device_id, name). Returns parameter id.

    `value_display` is always set (the human-readable form). `value_normalized`
    is optional — discrete-enum parameters (e.g., Filter Type = "Lowpass")
    have no continuous form.

    `value_items` is the enum cardinality — Live's `value_items` tuple for
    discrete-enum params, in order (index in the tuple = numeric value
    Live stores). Persisted as JSON; NULL for continuous params. Captured
    at pull time when present; the enum-aware envelope helper reads it
    back to resolve enum-name breakpoints at compose time.

    `value_raw` (DEV-4P7R) is the UNCLAMPED raw continuous channel — Live's own
    `param.value`, pushed via set_parameter's raw `value`. It is the only
    authorable form for a quantized continuous param whose raw range != [0,1]
    and whose display is non-monotonic (Wavetable LFO S. Rate). Mutually
    exclusive with `value_normalized` (the other numeric continuous channel) and
    with `value_items` (enum). `value_display` may still carry a readable hint.
    """
    if value_normalized is not None and not (0.0 <= value_normalized <= 1.0):
        raise ValueError(
            f"value_normalized {value_normalized} out of range [0.0, 1.0]"
        )
    if value_raw is not None:
        if not isinstance(value_raw, (int, float)) or isinstance(value_raw, bool):
            raise ValueError(
                f"value_raw must be a number, got {value_raw!r}"
            )
        if value_normalized is not None:
            raise ValueError(
                f"param {name!r}: value_raw and value_normalized are mutually "
                "exclusive continuous channels — pass exactly one"
            )
        if value_items is not None:
            raise ValueError(
                f"param {name!r}: value_raw is for continuous params; an enum "
                "uses value_items, not value_raw"
            )
        value_raw = float(value_raw)
    value_items_json: str | None = None
    if value_items is not None:
        items_list = [str(item) for item in value_items]
        # Reject empty value_items=[] symmetrically with M.create_enum_envelope's
        # kwarg path. An empty list is ambiguous — pass None for continuous
        # params, or a non-empty list for enum params. Pre-fix this branch
        # silently coerced [] to NULL, asymmetric with the envelope path
        # which raised. (E1 Critic paper-cut 2026-05-22.)
        if not items_list:
            raise ValueError(
                "value_items=[] is ambiguous — pass None for continuous "
                "params or a non-empty list of enum strings (Live's "
                "value_items tuple in order)"
            )
        value_items_json = json.dumps(items_list)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, value_display, value_normalized, value_items_json, value_raw
             FROM device_parameters
           WHERE device_id = ? AND name = ?""",
        (device_id, name),
    ).fetchone()
    if existing is not None:
        param_id = existing["id"]
        if (
            existing["value_display"],
            existing["value_normalized"],
            existing["value_items_json"],
            existing["value_raw"],
        ) == (value_display, value_normalized, value_items_json, value_raw):
            _record_touch_if_session("device_parameter", param_id)
            return MutatorResult(param_id, "unchanged")
        conn.execute(
            """UPDATE device_parameters
                  SET value_display = ?,
                      value_normalized = ?,
                      value_items_json = ?,
                      value_raw = ?
                WHERE id = ?""",
            (value_display, value_normalized, value_items_json, value_raw,
             param_id),
        )
        result_kind = "updated"
    else:
        param_id = _uuid()
        conn.execute(
            """INSERT INTO device_parameters
                   (id, device_id, name, value_display,
                    value_normalized, value_items_json, value_raw)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (param_id, device_id, name, value_display,
             value_normalized, value_items_json, value_raw),
        )
        result_kind = "created"
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_SET,
        {
            "parameter_id": param_id,
            "device_id": device_id,
            "name": name,
            "value_display": value_display,
            "value_normalized": value_normalized,
            "value_items_json": value_items_json,
            "value_raw": value_raw,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device_parameter", param_id)
    return MutatorResult(param_id, result_kind)


@_atomic
def remove_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    cur = conn.execute(
        "DELETE FROM device_parameters WHERE device_id = ? AND name = ?",
        (device_id, name),
    )
    if cur.rowcount == 0:
        return
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_REMOVED,
        {"device_id": device_id, "name": name},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


# ---------------------------------------------------------------------------
# Mix: Drum Rack pad mappings (M1-C)
# ---------------------------------------------------------------------------
# Each row binds one MIDI note on a Drum Rack to the verbatim Live chain
# name at that pad. Canonicalization (chain_name → "kick" / "snare" /
# "hat_closed") happens at READ time in `hallucinote.generators.kit.Kit`,
# not on the way in — preserves Live's name so canonicalization rules can
# evolve without DB rewrites.
#
# Replace-style mutator (mirrors `replace_breakpoints`). A capture probe
# emits a full pad list per Drum Rack device; the mutator atomically
# deletes the old set and inserts the new one in a single transaction
# with a single event.


@_touches("device", "device_id")
@_atomic
def replace_drum_pad_mappings(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    mappings: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every drum_pad_mappings row for ``device_id``, insert
    the new set. Returns the new mapping ids in insertion order. One event.

    Each mapping dict: ``{chain_name: str, midi_note: int}``. The mutator
    rejects mappings with midi_note outside [0, 127] (the schema CHECK
    enforces too, but surfacing it here gives a better error).

    W12-A: idempotent — when the existing rows already match the incoming
    set (by content), the function is a no-op and emits no event. The parent
    DEVICE is marked touched on every path (``@_touches``): pad mappings are
    CASCADE children with no row-kind of their own in the build sweep, so
    protecting the device is what keeps them alive.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    incoming_sig: list[tuple[str, int]] = []
    for m in mappings:
        chain_name = str(m.get("chain_name", ""))
        midi_note = int(m["midi_note"])
        if midi_note < 0 or midi_note > 127:
            raise ValueError(
                f"replace_drum_pad_mappings: midi_note {midi_note} out of "
                "MIDI range [0, 127]"
            )
        if not chain_name:
            raise ValueError(
                "replace_drum_pad_mappings: chain_name must be non-empty "
                f"(got {m!r})"
            )
        incoming_sig.append((chain_name, midi_note))
    existing_rows = conn.execute(
        """SELECT id, chain_name, midi_note FROM drum_pad_mappings
           WHERE device_id = ? ORDER BY midi_note""",
        (device_id,),
    ).fetchall()
    existing_sig = [(r["chain_name"], r["midi_note"]) for r in existing_rows]
    if sorted(existing_sig) == sorted(incoming_sig):
        return [r["id"] for r in existing_rows]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute(
            "DELETE FROM drum_pad_mappings WHERE device_id = ?",
            (device_id,),
        )
        new_ids: list[str] = []
        for chain_name, midi_note in incoming_sig:
            mid = _uuid()
            conn.execute(
                """INSERT INTO drum_pad_mappings
                       (id, device_id, chain_name, midi_note)
                   VALUES (?, ?, ?, ?)""",
                (mid, device_id, chain_name, midi_note),
            )
            new_ids.append(mid)
        song_id = _resolve_device_song(conn, device_id=device_id)
        _emit(
            conn,
            E.DRUM_PAD_MAPPINGS_REPLACED,
            {
                "device_id": device_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "mapping_ids": new_ids,
            },
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


# ---------------------------------------------------------------------------
# SNP-2H9F: nested-param overrides on a preset_query device
# ---------------------------------------------------------------------------
# A preset device has only its top-level row in the DB (the preset instantiates
# the nested tree at push time), so a by-ear tweak on a descendant can't ride
# set_device_parameter — there's no nested device row to key on. These overrides
# live in their own table, keyed by (device_id, descent path, name), and push
# re-asserts each via a node-addressed set_parameter after the preset loads.
# Replace-style (atomic full-set replace + one event), mirroring drum_pad_mappings.


def _canonical_override_path(path: Any) -> list[dict[str, int]]:
    """Validate + canonicalize a param override's descent path to a list of
    ``{chain_index, device_position}`` int steps (1-based, DEEP-RACK-ADDR).

    An override addresses a DESCENDANT of the preset device, so the path must be
    NON-EMPTY (a top-level param is an ordinary ``params_dialed`` entry, not an
    override). Extra keys on a step are dropped — the canonical form is exactly
    the two index keys so ``path_json`` is stable for the UNIQUE constraint and
    content-equality idempotency.
    """
    if not isinstance(path, (list, tuple)) or not path:
        raise ValueError(
            "param override path must be a non-empty list of "
            f"{{chain_index, device_position}} steps, got {path!r}"
        )
    out: list[dict[str, int]] = []
    for step in path:
        if not isinstance(step, dict) or "chain_index" not in step \
                or "device_position" not in step:
            raise ValueError(
                "param override path step must carry chain_index + "
                f"device_position, got {step!r}"
            )
        ci = step["chain_index"]
        dp = step["device_position"]
        if not isinstance(ci, int) or isinstance(ci, bool) or ci < 1:
            raise ValueError(
                f"param override chain_index must be an int >= 1, got {ci!r}"
            )
        if not isinstance(dp, int) or isinstance(dp, bool) or dp < 1:
            raise ValueError(
                f"param override device_position must be an int >= 1, got {dp!r}"
            )
        out.append({"chain_index": ci, "device_position": dp})
    return out


@_touches("device", "device_id")
@_atomic
def replace_device_param_overrides(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    overrides: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every ``device_param_overrides`` row for ``device_id``,
    insert the new set. Returns the new override ids in insertion order. One
    ``DEVICE_PARAM_OVERRIDES_REPLACED`` event. Idempotent — a no-op (no event)
    when the existing rows already match the incoming set by content (SNP-2H9F).

    Each override dict: ``{path, name, value_display[, value_normalized]
    [, value_items][, value_raw]}`` where ``path`` is the non-empty NodeAddr
    descent (``[{chain_index, device_position}, ...]``) to a device nested inside
    the preset. The value columns mirror ``set_device_parameter`` (value_display
    always set; value_normalized for continuous params; value_items for enums;
    value_raw — DEV-4P7R — the UNCLAMPED raw channel, mutually exclusive with
    value_normalized + value_items).
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # (path_json, name, value_display, value_normalized, value_items_json, value_raw)
    incoming: list[
        tuple[str, str, str, float | None, str | None, float | None]
    ] = []
    seen: set[tuple[str, str]] = set()
    for o in overrides:
        path = _canonical_override_path(o.get("path"))
        path_json = json.dumps(path)
        name = o.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"param override name must be a non-empty str, got {name!r}"
            )
        value_display = o.get("value_display")
        if not isinstance(value_display, str):
            raise ValueError(
                f"param override {name!r}: value_display must be a str, "
                f"got {value_display!r}"
            )
        value_normalized = o.get("value_normalized")
        if value_normalized is not None:
            if not isinstance(value_normalized, (int, float)) \
                    or isinstance(value_normalized, bool) \
                    or not (0.0 <= float(value_normalized) <= 1.0):
                raise ValueError(
                    f"param override {name!r}: value_normalized "
                    f"{value_normalized!r} out of range [0.0, 1.0]"
                )
            value_normalized = float(value_normalized)
        value_items = o.get("value_items")
        value_items_json: str | None = None
        if value_items is not None:
            items_list = [str(item) for item in value_items]
            if not items_list:
                raise ValueError(
                    f"param override {name!r}: value_items=[] is ambiguous — "
                    "pass None for continuous params or a non-empty list of "
                    "enum strings"
                )
            value_items_json = json.dumps(items_list)
        value_raw = o.get("value_raw")
        if value_raw is not None:
            if not isinstance(value_raw, (int, float)) \
                    or isinstance(value_raw, bool):
                raise ValueError(
                    f"param override {name!r}: value_raw must be a number, "
                    f"got {value_raw!r}"
                )
            if value_normalized is not None:
                raise ValueError(
                    f"param override {name!r}: value_raw and value_normalized "
                    "are mutually exclusive continuous channels — pass one"
                )
            if value_items_json is not None:
                raise ValueError(
                    f"param override {name!r}: value_raw is for continuous "
                    "params; an enum uses value_items, not value_raw"
                )
            value_raw = float(value_raw)
        key = (path_json, name)
        if key in seen:
            raise ValueError(
                f"param override duplicate (path, name): "
                f"path={path_json} name={name!r}"
            )
        seen.add(key)
        incoming.append(
            (path_json, name, value_display, value_normalized, value_items_json,
             value_raw)
        )
    existing_rows = conn.execute(
        """SELECT id, path_json, name, value_display, value_normalized,
                  value_items_json, value_raw
             FROM device_param_overrides
            WHERE device_id = ?""",
        (device_id,),
    ).fetchall()
    existing_sig = {
        (r["path_json"], r["name"], r["value_display"],
         r["value_normalized"], r["value_items_json"], r["value_raw"])
        for r in existing_rows
    }
    # Set equality (tuples carry None for normalized/items, so set membership —
    # not sorted-list comparison — sidesteps None-vs-value ordering).
    # The touch is recorded against the parent DEVICE by `@_touches` (not an
    # override row-kind, which the build session doesn't track): touching the
    # device is what protects it — and its CASCADE-child overrides — from the
    # build sweep, the same reason DEVICE_PARAM_OVERRIDES_REPLACED registers
    # under "device".
    if existing_sig == set(incoming):
        return [r["id"] for r in existing_rows]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute(
            "DELETE FROM device_param_overrides WHERE device_id = ?",
            (device_id,),
        )
        new_ids: list[str] = []
        for path_json, name, vd, vn, vi_json, vr in incoming:
            oid = _uuid()
            conn.execute(
                """INSERT INTO device_param_overrides
                       (id, device_id, path_json, name, value_display,
                        value_normalized, value_items_json, value_raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (oid, device_id, path_json, name, vd, vn, vi_json, vr),
            )
            new_ids.append(oid)
        song_id = _resolve_device_song(conn, device_id=device_id)
        _emit(
            conn,
            E.DEVICE_PARAM_OVERRIDES_REPLACED,
            {
                "device_id": device_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "override_ids": new_ids,
            },
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


# ---------------------------------------------------------------------------
# Mix: automation envelopes + breakpoints
# ---------------------------------------------------------------------------
# Unified shape per target_kind. The mutator validates that the right target
# kwarg is set for the given kind, that parameter_path is present where it's
# required, and resolves song_id from the target (so the event carries song
# provenance even when target_song_id isn't passed explicitly).
#
# Cascade: every target FK has ON DELETE CASCADE, so deleting a clip/note/
# device/track/return collapses any envelopes that pointed at it. No mutator
# discipline needed for cascade — schema handles it.


ENVELOPE_TARGET_KINDS = frozenset({
    "clip_cc",
    "clip_pitch_bend",
    "note_expression",
    "device_parameter",
    "mixer_volume",
    "mixer_pan",
    "send_level",
    "return_mixer_volume",
    "return_mixer_pan",
})

# parameter_path is required for these kinds (CC number / MPE axis / param name)
# and optional/forbidden for the rest.
_PARAMETER_PATH_REQUIRED = frozenset({
    "clip_cc", "note_expression", "device_parameter",
})

# `note_expression` is retained in the vocabulary above (a DB predating its
# retirement may hold rows) and refused here, so a build.py cannot author a new
# one. Live's Python API exposes no per-note expression surface under any name
# — not a method waiting on the right spelling, and not a gap a Live update is
# expected to close — so accepting the row only defers the refusal to push
# time, after the author has written a part around it.
_NOTE_EXPRESSION_UNAUTHORABLE = (
    "target_kind='note_expression' cannot be authored: Live's Python API has "
    "no per-note expression surface under any name, so a polyphonic per-note "
    "bend cannot be pushed by any route. Author a monophonic glide as a "
    "`device_parameter` envelope on the instrument's pitch parameter instead."
)

# Track-hosted target_kinds whose push route depends on the host track's
# kind (ENV-7G4K eligibility, superseding the W10-F blanket refusal;
# ENV-9P4T extends it to audio + the per-clip/continuous infer-from-span):
#   kind='midi'   -> session-clip route when a covering session clip exists
#                    (Clip.create_automation_envelope — Live 12.4 only
#                    accepts these targets on session clips), else perform
#   'master'/'group' -> perform route (gesture-recorded arrangement
#                    automation at push time; probe-verified, see
#                    docs/research/audio-first-class/lom-probe-results.md)
#   'audio'       -> the same partition as midi: session-clip route when a
#                    covering audio session clip exists, else perform for a
#                    clip-independent continuous ride
# The fine per-clip-vs-continuous decision needs the song's clips, so it is
# made by the planner (classify_envelope_route), not this create-time gate.
_HOST_KIND_ROUTED_KINDS = frozenset({
    "mixer_volume", "mixer_pan", "send_level", "device_parameter",
})

BREAKPOINT_CURVE_KINDS = frozenset({"linear", "hold", "fast", "slow"})


def _track_kind(
    conn: sqlite3.Connection, track_id: str,
) -> str | None:
    # Arc 7 / P7: route through Q.get_track instead of an inline SELECT
    # so this and `sync.push._track_kind_for_envelope` share the same
    # single-row lookup (one query name to maintain when the tracks
    # schema evolves).
    row = Q.get_track(conn, track_id)
    return None if row is None else row["kind"]


def _resolve_envelope_host_track(
    conn: sqlite3.Connection,
    *,
    target_kind: str,
    target_track_id: str | None,
    target_device_id: str | None,
) -> str | None:
    """Return the track_id that hosts a session-clip-routed envelope, or None
    if it can't be resolved yet (e.g. return-side device, which the planner
    handles separately).

    - mixer_volume / mixer_pan / send_level -> target_track_id directly.
    - device_parameter -> the parent_track_id of the device's chain. Returns
      None if the device lives on a return or doesn't exist (the planner
      already warns on those paths).
    """
    if target_kind in ("mixer_volume", "mixer_pan", "send_level"):
        return target_track_id
    if target_kind == "device_parameter":
        if target_device_id is None:
            return None
        row = conn.execute(
            """SELECT dc.parent_track_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (target_device_id,),
        ).fetchone()
        return None if row is None else row["parent_track_id"]
    return None


def _envelope_track_kind_refusal(target_kind: str, host_kind: str) -> str:
    """Teaching message for a host kind with no push route at all.

    After ENV-9P4T every TRACK_KINDS value is authorable: midi/audio hosts
    route per-clip (a covering session clip) OR continuous (perform), and
    master/group hosts are performed into arrangement automation at push
    time. So this is purely defensive against a future track kind that
    lands without a route chosen — the schema CHECK already constrains kind
    to {midi,audio,master,group}, so it is unreachable today.
    """
    return (
        f"target_kind={target_kind!r} on track kind={host_kind!r} has no "
        "push route: midi/audio host envelopes route per-clip (session "
        "clip) or continuous (perform); master/group are performed. A new "
        "track kind must explicitly choose a route."
    )


@_atomic
def create_envelope(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    target_kind: str,
    target_clip_id: str | None = None,
    target_note_id: str | None = None,
    target_device_id: str | None = None,
    target_track_id: str | None = None,
    target_send_return_id: str | None = None,
    parameter_path: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create an envelope row. Returns the envelope id.

    Caller passes exactly the target kwarg(s) the kind requires:
      clip_cc / clip_pitch_bend  -> target_clip_id
      note_expression            -> target_note_id (parameter_path = MPE axis)
      device_parameter           -> target_device_id (parameter_path = name)
      mixer_volume / mixer_pan   -> target_track_id
      send_level                 -> target_track_id + target_send_return_id
      return_mixer_volume / return_mixer_pan -> target_send_return_id
                                    (a return track's own mixer; ENV-7G4K)

    The schema CHECK is the last-line defense; this mutator raises early with
    a clearer message and validates parameter_path semantics (required for
    clip_cc / note_expression / device_parameter; MPE axis allowlist).
    """
    if target_kind not in ENVELOPE_TARGET_KINDS:
        raise ValueError(
            f"invalid target_kind {target_kind!r}; "
            f"expected one of {sorted(ENVELOPE_TARGET_KINDS)}"
        )

    expected_targets: dict[str, tuple[str, ...]] = {
        "clip_cc":          ("target_clip_id",),
        "clip_pitch_bend":  ("target_clip_id",),
        "note_expression":  ("target_note_id",),
        "device_parameter": ("target_device_id",),
        "mixer_volume":     ("target_track_id",),
        "mixer_pan":        ("target_track_id",),
        "send_level":       ("target_track_id", "target_send_return_id"),
        "return_mixer_volume": ("target_send_return_id",),
        "return_mixer_pan":    ("target_send_return_id",),
    }
    all_targets = {
        "target_clip_id": target_clip_id,
        "target_note_id": target_note_id,
        "target_device_id": target_device_id,
        "target_track_id": target_track_id,
        "target_send_return_id": target_send_return_id,
    }
    required = expected_targets[target_kind]
    for k in required:
        if all_targets[k] is None:
            raise ValueError(
                f"target_kind={target_kind!r} requires kwarg {k}"
            )
    for k, v in all_targets.items():
        if k not in required and v is not None:
            raise ValueError(
                f"target_kind={target_kind!r} forbids kwarg {k} (got {v!r})"
            )

    if target_kind in _PARAMETER_PATH_REQUIRED:
        if not parameter_path:
            raise ValueError(
                f"target_kind={target_kind!r} requires parameter_path "
                "(CC number / MPE axis / parameter name)"
            )
    else:
        if parameter_path is not None:
            raise ValueError(
                f"target_kind={target_kind!r} does not use parameter_path "
                f"(got {parameter_path!r})"
            )

    if target_kind == "note_expression":
        raise ValueError(_NOTE_EXPRESSION_UNAUTHORABLE)

    if target_kind == "clip_cc":
        try:
            # A None parameter_path deliberately lands in the except arm
            # (TypeError) and raises the teaching error below.
            cc_number = int(parameter_path)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"clip_cc parameter_path must be an integer CC number "
                f"(got {parameter_path!r})"
            ) from exc
        if not 0 <= cc_number <= 127:
            raise ValueError(
                f"clip_cc CC number {cc_number} out of MIDI range [0, 127]"
            )

    # ENV-7G4K eligibility (supersedes the W10-F blanket refusal), extended
    # by ENV-9P4T: midi hosts route through session clips (per-clip) OR
    # perform (clip-independent ride); master/group hosts are performed at
    # push time; audio hosts are authorable too and route exactly like midi —
    # a covering audio session clip takes the per-clip route, an uncovered
    # ride performs. The planner
    # partitions the same way (sync/push/envelopes.py
    # `classify_envelope_route` infer-from-span). This create-time gate is
    # only the coarse authorability check; the per-clip-vs-continuous routing
    # decision needs the song's clips and so lives in the planner.
    if target_kind in _HOST_KIND_ROUTED_KINDS:
        host_track_id = _resolve_envelope_host_track(
            conn,
            target_kind=target_kind,
            target_track_id=target_track_id,
            target_device_id=target_device_id,
        )
        if host_track_id is not None:
            host_kind = _track_kind(conn, host_track_id)
            if host_kind is not None and host_kind not in TRACK_KINDS:
                raise ValueError(
                    _envelope_track_kind_refusal(target_kind, host_kind)
                )
            # Live's master track has no sends — a send_level envelope
            # addressed to it is unauthorable on any route (the perform
            # handler refuses the same shape wire-side).
            if host_kind == "master" and target_kind == "send_level":
                raise ValueError(
                    "target_kind='send_level' on the master track is "
                    "invalid: Live's master has no sends. Author the send "
                    "ride on the source track or group instead."
                )

    # Provenance: a clip envelope carries its own target_clip_id. The one kind
    # that resolved a clip through its note — `note_expression` — is refused
    # above, so nothing reaches here needing that hop.
    event_clip_id = target_clip_id

    actor, request_id = _resolve_actor_and_request(actor, request_id)

    # Identity by (song_id, target_kind, all target FKs, parameter_path).
    # Use IS for nullable FK comparisons (SQL equality is NULL-vs-NULL = false).
    existing = conn.execute(
        """SELECT id FROM envelopes
           WHERE song_id = ? AND target_kind = ?
             AND target_clip_id IS ? AND target_note_id IS ?
             AND target_device_id IS ? AND target_track_id IS ?
             AND target_send_return_id IS ?
             AND parameter_path IS ?""",
        (song_id, target_kind, target_clip_id, target_note_id,
         target_device_id, target_track_id, target_send_return_id,
         parameter_path),
    ).fetchone()
    if existing is not None:
        # Envelope rows have no non-identity content — breakpoints are
        # separate. Identity match means unchanged by definition.
        env_id = existing["id"]
        _record_touch_if_session("envelope", env_id)
        return MutatorResult(env_id, "unchanged")

    env_id = _uuid()
    conn.execute(
        """INSERT INTO envelopes
               (id, song_id, target_kind,
                target_clip_id, target_note_id, target_device_id,
                target_track_id, target_send_return_id, parameter_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            env_id, song_id, target_kind,
            target_clip_id, target_note_id, target_device_id,
            target_track_id, target_send_return_id, parameter_path,
        ),
    )
    _emit(
        conn,
        E.ENVELOPE_CREATED,
        {
            "envelope_id": env_id,
            "target_kind": target_kind,
            "target_clip_id": target_clip_id,
            "target_note_id": target_note_id,
            "target_device_id": target_device_id,
            "target_track_id": target_track_id,
            "target_send_return_id": target_send_return_id,
            "parameter_path": parameter_path,
        },
        song_id=song_id,
        clip_id=event_clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("envelope", env_id)
    return MutatorResult(env_id, "created")


@_atomic
def delete_envelope(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM envelopes WHERE id = ?", (envelope_id,))
    _emit(
        conn,
        E.ENVELOPE_DELETED,
        {"envelope_id": envelope_id},
        song_id=row["song_id"],
        clip_id=row["target_clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def _resolve_envelope_song(
    conn: sqlite3.Connection, envelope_id: str,
) -> tuple[str | None, str | None]:
    """Return (song_id, target_clip_id) for an envelope, for event provenance."""
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["song_id"], row["target_clip_id"]


@_touches("envelope", "envelope_id")
@_atomic
def add_breakpoint(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    time_beats: float,
    value: float,
    curve_kind: str = "linear",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Append a single breakpoint to an envelope. Returns the breakpoint id."""
    if curve_kind not in BREAKPOINT_CURVE_KINDS:
        raise ValueError(
            f"invalid curve_kind {curve_kind!r}; "
            f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
        )
    bp_id = _uuid()
    conn.execute(
        """INSERT INTO automation_breakpoints
               (id, envelope_id, time_beats, value, curve_kind)
           VALUES (?, ?, ?, ?, ?)""",
        (bp_id, envelope_id, time_beats, value, curve_kind),
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_ADDED,
        {
            "breakpoint_id": bp_id,
            "envelope_id": envelope_id,
            "time_beats": time_beats,
            "value": value,
            "curve_kind": curve_kind,
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return bp_id


@_atomic
def remove_breakpoint(
    conn: sqlite3.Connection,
    *,
    breakpoint_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT envelope_id FROM automation_breakpoints WHERE id = ?",
        (breakpoint_id,),
    ).fetchone()
    if row is None:
        return
    envelope_id = row["envelope_id"]
    conn.execute(
        "DELETE FROM automation_breakpoints WHERE id = ?", (breakpoint_id,)
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_REMOVED,
        {"breakpoint_id": breakpoint_id, "envelope_id": envelope_id},
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    # Removing a breakpoint leaves the ENVELOPE standing — mark it touched so
    # the build sweep doesn't delete the arc we just edited. (Keyed by
    # breakpoint_id, so `@_touches` can't express this; the envelope is
    # resolved from the row above.)
    _record_touch_if_session("envelope", envelope_id)


@_touches("envelope", "envelope_id")
@_atomic
def replace_breakpoints(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    breakpoints: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every breakpoint for `envelope_id`, insert the new set.
    Returns the new breakpoint ids in insertion order. Single event emitted.

    Each breakpoint dict: {time_beats: float, value: float,
    curve_kind: 'linear'|'hold'|'fast'|'slow' (default 'linear')}.

    W12-A: idempotent — when the existing breakpoints already match the
    incoming set (by content, ignoring ids), the function is a no-op and
    emits no event. Returns the existing breakpoint ids in that case.

    The parent envelope is marked TOUCHED on every path (``@_touches``) —
    the no-op one included. Breakpoints have no row-kind of their own in
    the build sweep; they survive because their envelope does, so the
    "nothing changed" return must still mark it or the next build deletes
    the arc it was converging.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Idempotency check: compare incoming vs existing.
    incoming_sig = [
        (float(bp["time_beats"]), float(bp["value"]),
         bp.get("curve_kind", "linear"))
        for bp in breakpoints
    ]
    existing_rows = conn.execute(
        """SELECT id, time_beats, value, curve_kind
           FROM automation_breakpoints WHERE envelope_id = ?
           ORDER BY time_beats""",
        (envelope_id,),
    ).fetchall()
    existing_sig = [
        (r["time_beats"], r["value"], r["curve_kind"]) for r in existing_rows
    ]
    if sorted(existing_sig) == sorted(incoming_sig):
        return [r["id"] for r in existing_rows]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute(
            "DELETE FROM automation_breakpoints WHERE envelope_id = ?",
            (envelope_id,),
        )
        new_ids: list[str] = []
        for bp in breakpoints:
            curve = bp.get("curve_kind", "linear")
            if curve not in BREAKPOINT_CURVE_KINDS:
                raise ValueError(
                    f"invalid curve_kind {curve!r}; "
                    f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
                )
            bp_id = _uuid()
            conn.execute(
                """INSERT INTO automation_breakpoints
                       (id, envelope_id, time_beats, value, curve_kind)
                   VALUES (?, ?, ?, ?, ?)""",
                (bp_id, envelope_id, float(bp["time_beats"]),
                 float(bp["value"]), curve),
            )
            new_ids.append(bp_id)
        song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
        _emit(
            conn,
            E.BREAKPOINTS_REPLACED,
            {
                "envelope_id": envelope_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "breakpoint_ids": new_ids,
            },
            song_id=song_id,
            clip_id=clip_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


def performed_automation_fingerprint(
    *,
    target_kind: str,
    target_track_id: str | None,
    target_device_id: str | None,
    target_send_return_id: str | None,
    parameter_path: str | None,
    breakpoints: Sequence[Any],
) -> str:
    """Content fingerprint of a perform-routed arc (ENV-7G4K).

    Covers the target addressing, parameter_path, and the ordered
    (time_beats, value, curve_kind) list — any change to any of them
    yields a new digest, and breakpoint *input order* never does (the
    list is canonically sorted, matching how the arc is performed).
    Push compares this against `performed_automation.fingerprint` to
    decide re-perform vs skip; the surface is write-only, so this digest
    is the only honesty mechanism there is.

    Accepts breakpoint dicts or sqlite3.Rows (anything `bp["key"]`-able;
    curve_kind defaults to 'linear' for dicts that omit it, mirroring
    `replace_breakpoints`).
    """
    def _curve(bp: Any) -> str:
        try:
            return bp["curve_kind"]
        except (KeyError, IndexError):
            return "linear"

    canonical = sorted(
        (float(bp["time_beats"]), float(bp["value"]), _curve(bp))
        for bp in breakpoints
    )
    payload = json.dumps(
        {
            "target_kind": target_kind,
            "target_track_id": target_track_id,
            "target_device_id": target_device_id,
            "target_send_return_id": target_send_return_id,
            "parameter_path": parameter_path,
            "breakpoints": canonical,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@_atomic
def record_performed_automation(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    session_id: str,
    fingerprint: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> MutatorResult:
    """Upsert the performed-state row for one (envelope, session) after a
    successful perform call (ENV-7G4K). Sync-state, like
    `link_db_to_ableton`: emits an event for the audit trail but does not
    touch the song's authored-content timestamp. Session-keyed — each
    bound Live set carries its own fingerprint, so a fresh set performs
    every arc instead of false-skipping on another set's record.

    Returns MutatorResult states: 'created' (first perform in this
    session), 'updated' (re-performed with a new fingerprint),
    'unchanged' (same fingerprint — callers normally skip the perform
    entirely, so this is the idempotent-replay guard, not the common
    path).
    """
    env_row = conn.execute(
        "SELECT song_id FROM envelopes WHERE id = ?", (envelope_id,),
    ).fetchone()
    if env_row is None:
        raise ValueError(
            f"record_performed_automation: envelope {envelope_id!r} not found"
        )
    session_row = conn.execute(
        "SELECT id FROM ableton_sessions WHERE id = ?", (session_id,),
    ).fetchone()
    if session_row is None:
        raise ValueError(
            f"record_performed_automation: session {session_id!r} not found"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, fingerprint FROM performed_automation
           WHERE envelope_id = ? AND session_id = ?""",
        (envelope_id, session_id),
    ).fetchone()
    if existing is not None and existing["fingerprint"] == fingerprint:
        return MutatorResult(existing["id"], "unchanged")
    if existing is not None:
        row_id = existing["id"]
        state = "updated"
        conn.execute(
            """UPDATE performed_automation
               SET fingerprint = ?,
                   performed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (fingerprint, row_id),
        )
    else:
        row_id = _uuid()
        state = "created"
        conn.execute(
            """INSERT INTO performed_automation
                   (id, envelope_id, session_id, fingerprint)
               VALUES (?, ?, ?, ?)""",
            (row_id, envelope_id, session_id, fingerprint),
        )
    _emit(
        conn,
        E.AUTOMATION_PERFORMED,
        {
            "performed_automation_id": row_id,
            "envelope_id": envelope_id,
            "session_id": session_id,
            "fingerprint": fingerprint,
            "state": state,
        },
        song_id=env_row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return MutatorResult(row_id, state)


@_atomic
def create_enum_envelope(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    parameter_name: str,
    breakpoints: Sequence[dict[str, Any]],
    value_items: Sequence[str] | None = None,
    curve_default: str = "hold",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Author a device_parameter envelope from enum-name breakpoint values.

    The DB layer stays meter-agnostic and value-numeric — this is a
    compose-time sugar that resolves enum names to the numeric indices
    Live actually stores. Mirrors the MCP handler's ``value_type='enum'``
    surface so build.py authors don't have to look up ``value_items``
    indices by hand to write "Amp Type: Clean→Heavy" automation.

    Resolution order for the enum cardinality:
      1. ``value_items`` kwarg (escape hatch — wins when supplied)
      2. ``device_parameters.value_items_json`` for (device_id, parameter_name)
         — captured at pull time via detail='full'.
      3. Otherwise raises ValueError with a teaching message pointing at
         re-pull (snapshot was captured pre-E1) or value_type='continuous'
         (param isn't enum-shaped).

    Stores numeric breakpoints by calling ``create_envelope`` +
    ``replace_breakpoints`` — no envelope-side schema change. Each
    breakpoint's ``curve`` (or ``curve_kind``) is preserved; ``curve_default``
    fills in when absent (defaults to 'hold' since enum envelopes are
    step-shaped — see Live 12.4's ``Envelope.insert_step`` semantics).

    Returns the envelope id.
    """
    if curve_default not in BREAKPOINT_CURVE_KINDS:
        raise ValueError(
            f"invalid curve_default {curve_default!r}; "
            f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
        )
    if not breakpoints:
        raise ValueError(
            "breakpoints must be a non-empty sequence of "
            "{time_beats, value, curve?} dicts"
        )

    resolved_items = _resolve_enum_value_items(
        conn,
        device_id=device_id,
        parameter_name=parameter_name,
        value_items=value_items,
    )

    numeric_breakpoints: list[dict[str, Any]] = []
    for i, bp in enumerate(breakpoints):
        if not isinstance(bp, dict):
            raise ValueError(
                f"breakpoint {i}: expected dict, got {type(bp).__name__}"
            )
        if "time_beats" not in bp:
            raise ValueError(
                f"breakpoint {i} missing 'time_beats': {bp!r}"
            )
        if "value" not in bp:
            raise ValueError(
                f"breakpoint {i} missing 'value': {bp!r}"
            )
        raw = bp["value"]
        if not isinstance(raw, str):
            raise ValueError(
                f"breakpoint {i}: create_enum_envelope expects string "
                f"values (enum names), got {type(raw).__name__} "
                f"({raw!r}) — use create_envelope + replace_breakpoints "
                f"for numeric authoring"
            )
        if raw not in resolved_items:
            raise ValueError(
                f"breakpoint {i}: enum value {raw!r} not in value_items "
                f"for parameter {parameter_name!r}: {resolved_items}"
            )
        curve_kind = bp.get("curve") or bp.get("curve_kind") or curve_default
        if curve_kind not in BREAKPOINT_CURVE_KINDS:
            raise ValueError(
                f"breakpoint {i}: invalid curve {curve_kind!r}; "
                f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
            )
        numeric_breakpoints.append({
            "time_beats": float(bp["time_beats"]),
            "value": float(resolved_items.index(raw)),
            "curve_kind": curve_kind,
        })

    song_id = _resolve_device_song(conn, device_id=device_id)
    if song_id is None:
        raise ValueError(
            f"device {device_id} not found or has no resolvable song; "
            f"verify the device row exists before authoring envelopes"
        )

    envelope_id = create_envelope(
        conn,
        song_id=song_id,
        target_kind="device_parameter",
        target_device_id=device_id,
        parameter_path=parameter_name,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    replace_breakpoints(
        conn,
        envelope_id=envelope_id,
        breakpoints=numeric_breakpoints,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return envelope_id


def _resolve_enum_value_items(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    parameter_name: str,
    value_items: Sequence[str] | None,
) -> list[str]:
    """Resolve the enum cardinality for (device_id, parameter_name).

    Distinguishes the three "no enum items" states (per the
    `Detection that replaces a user question` learning):
      - no param row for (device, name) → ValueError "not captured"
      - row exists but value_items_json is NULL → ValueError "not enum
        OR pre-E1 capture"
      - row exists with malformed JSON → ValueError "malformed"

    Each surfaces a teaching error pointing at the right remedy.
    """
    if value_items is not None:
        items_list = [str(v) for v in value_items]
        if not items_list:
            raise ValueError(
                "value_items kwarg must be a non-empty sequence"
            )
        return items_list
    param_row = conn.execute(
        """SELECT value_items_json FROM device_parameters
           WHERE device_id = ? AND name = ?""",
        (device_id, parameter_name),
    ).fetchone()
    if param_row is None:
        raise ValueError(
            f"parameter {parameter_name!r} not captured on device "
            f"{device_id} — pull device parameters first (detail='full') "
            f"so value_items is available, or pass value_items=[...] "
            f"explicitly"
        )
    items_json = param_row["value_items_json"]
    if items_json is None:
        raise ValueError(
            f"parameter {parameter_name!r} on device {device_id} has no "
            f"value_items captured — either the param isn't enum-shaped "
            f"(use create_envelope + replace_breakpoints with numeric "
            f"values), or it was captured before value_items_json was "
            f"added (re-pull the song's device parameters). Escape "
            f"hatch: pass value_items=[...] explicitly."
        )
    try:
        loaded = json.loads(items_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"value_items_json on device {device_id} parameter "
            f"{parameter_name!r} is malformed: {items_json!r}"
        ) from exc
    if not isinstance(loaded, list) or not loaded:
        raise ValueError(
            f"value_items_json on device {device_id} parameter "
            f"{parameter_name!r} must decode to a non-empty list, "
            f"got {loaded!r}"
        )
    return [str(v) for v in loaded]


__all__ = [
    "BREAKPOINT_CURVE_KINDS",
    "ENVELOPE_TARGET_KINDS",
    "add_breakpoint",
    "create_device",
    "create_device_chain",
    "create_enum_envelope",
    "create_envelope",
    "delete_device",
    "delete_device_chain",
    "delete_envelope",
    "remove_breakpoint",
    "remove_device_parameter",
    "replace_breakpoints",
    "replace_drum_pad_mappings",
    "set_device_parameter",
]
