"""Mix-state pull: track / return / master mixer fields, sends, and the
global score fields (tempo + signature) that ride the session_info probe.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.return_naming import strip_return_slot_prefix

from hallucinote.db import mutations as M, queries as Q

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _floats_differ,
    _bool_db,
    _ints_differ,
    _parse_signature,
)


def plan_pull_mix(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull mix state (track + return + master + sends).

    The plan probes only rows that are *linked* in this session. Tracks or
    returns created in Ableton outside of the session are not auto-discovered
    in V1 (the agent could create-then-link them in a follow-up, but the
    Ableton side has no DB-discovery mechanism we can rely on yet).

    Emits one ``ableton_session(action='info')`` + one
    ``ableton_return(action='list')`` globally, plus one
    ``ableton_track(action='info')`` and one ``ableton_track(action='get_sends')``
    per linked track. All five domain probes use the unified surface as of
    Wave M-2.
    """
    plan = PullPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)

    plan.add(PullCall(
        tool="ableton_session",
        args={"action": "info"},
        key="session_info",
        purpose="pull tempo / signature / master volume+pan",
    ))
    plan.add(PullCall(
        tool="ableton_return",
        args={"action": "list"},
        key="returns_list",
        purpose="pull return-track index (name + index per return)",
    ))

    # The returns_list probe under the unified surface returns only
    # {return_index, name, color} per return — no mixer state. To populate
    # the apply layer's full per-return contract (name + volume + panning),
    # we follow the list with one ableton_return(action='info') per linked
    # return. The apply layer reads these by the `return_info:<id>` key.
    for r in Q.get_returns_for_song(conn, song_id):
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            continue
        plan.add(PullCall(
            tool="ableton_return",
            args={"action": "info", "return_index": return_at},
            key=f"return_info:{r['id']}",
            purpose=f"pull mixer state for return '{r['name']}'",
        ))

    any_linked_track = False
    for t in tracks:
        if t["kind"] == "master":
            # master is reached via session_info, not the per-track probe.
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "push it via plan_push_clip first, then re-run pull"
            )
            continue
        any_linked_track = True
        plan.add(PullCall(
            tool="ableton_track",
            args={"action": "info", "track_index": track_at},
            key=f"track_info:{t['id']}",
            purpose=f"pull mixer state for {t['name']}",
        ))
        plan.add(PullCall(
            tool="ableton_track",
            args={"action": "get_sends", "track_index": track_at},
            key=f"track_sends:{t['id']}",
            purpose=f"pull sends for {t['name']}",
        ))

    if not any_linked_track:
        plan.warn(
            "no linked tracks for this session — pull will only ingest "
            "master + returns; per-track mixer state needs a push first"
        )

    return plan


def plan_pull_score_globals(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan a single `ableton_session(action='info')` probe to pull the
    *global* score parameters: tempo (bar 1) and time signature (bar 1) —
    plus master volume/pan as a free side-effect (they share the same probe).

    Multi-point tempo maps and per-arrangement signature changes are an MCP
    read gap; this pulls only the global values.
    """
    plan = PullPlan()
    plan.add(PullCall(
        tool="ableton_session",
        args={"action": "info"},
        key="session_info",
        purpose="pull global tempo + signature (+ master mixer state)",
    ))
    return plan


def _apply_session_info(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest fields from `ableton_session(action='info')`: master volume /
    pan, plus the *global* tempo + time signature (the bar-1 row in each map).
    Multi-point tempo / signature maps are an MCP read gap — pull leaves any
    non-bar-1 rows untouched until per-point reads land."""
    _apply_session_master(
        conn, song_id=song_id, result=result, out=out,
        actor=actor, request_id=request_id, reason=reason,
    )
    _apply_session_tempo(
        conn, song_id=song_id, result=result, out=out,
        actor=actor, request_id=request_id, reason=reason,
    )
    _apply_session_signature(
        conn, song_id=song_id, result=result, out=out,
        actor=actor, request_id=request_id, reason=reason,
    )


def _apply_session_master(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest master volume/pan from `session_info.master`.

    Contract: if the probe payload omits `master` entirely, this is a no-op —
    no probe data is not a divergence. Counts/warnings reflect only the
    fields the probe actually reported.
    """
    master_in = result.get("master")
    if not master_in:
        return
    master_row = next(
        (
            r for r in Q.get_tracks_for_song(conn, song_id)
            if r["kind"] == "master"
        ),
        None,
    )
    if master_row is None:
        out.warnings.append(
            "session_info: no master row in DB for this song — "
            "snapshot replay typically creates one; skipping master ingest"
        )
        return

    changes: dict[str, Any] = {}
    if "volume" in master_in and _floats_differ(
        master_in["volume"], master_row["volume"]
    ):
        changes["volume"] = float(master_in["volume"])
    # MCP shape uses 'panning'; DB uses 'pan'.
    pan_in = master_in.get("panning", master_in.get("pan"))
    if pan_in is not None and _floats_differ(pan_in, master_row["pan"]):
        changes["pan"] = float(pan_in)

    if not changes:
        out.no_ops += 1
        return

    M.set_track_mixer(
        conn,
        track_id=master_row["id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
        **changes,
    )
    out.mutations += 1
    for k, v in changes.items():
        out.details.append(f"master {k}: {master_row[k]!r} -> {v!r}")


def _apply_session_tempo(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Upsert the bar-1 tempo_map row from `session_info.tempo`. Per-arrangement
    tempo points are an MCP read gap — multi-point maps stay untouched."""
    tempo_in = result.get("tempo")
    if tempo_in is None:
        return
    try:
        bpm = float(tempo_in)
    except (TypeError, ValueError):
        out.warnings.append(f"session_info.tempo {tempo_in!r}: not a number; skipping")
        return
    if bpm <= 0:
        out.warnings.append(f"session_info.tempo {bpm}: non-positive; skipping")
        return
    existing = next(
        (r for r in Q.get_tempo_map(conn, song_id) if r["start_bar"] == 1.0),
        None,
    )
    if existing is None:
        M.add_tempo_point(
            conn, song_id=song_id, start_bar=1.0, tempo_bpm=bpm, ramp="hold",
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(f"tempo: added bar-1 row at {bpm:g} bpm")
        return
    if not _floats_differ(bpm, existing["tempo_bpm"]):
        out.no_ops += 1
        return
    M.update_tempo_point(
        conn, point_id=existing["id"], tempo_bpm=bpm,
        actor=actor, request_id=request_id, reason=reason,
    )
    out.mutations += 1
    out.details.append(
        f"tempo: {existing['tempo_bpm']:g} -> {bpm:g} bpm (bar 1)"
    )


def _apply_session_signature(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Upsert the bar-1 time_signature_map row from `session_info.signature`
    (string `"N/D"`). Per-arrangement signature changes are an MCP read gap."""
    sig_in = result.get("signature")
    if sig_in is None:
        return
    try:
        num, den = _parse_signature(sig_in)
    except ValueError as e:
        out.warnings.append(
            f"session_info.signature {sig_in!r}: parse error ({e}); skipping"
        )
        return
    existing = next(
        (r for r in Q.get_time_signature_map(conn, song_id)
         if r["start_bar"] == 1.0),
        None,
    )
    if existing is None:
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=num, denominator=den,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(f"signature: added bar-1 row at {num}/{den}")
        return
    if num == existing["numerator"] and den == existing["denominator"]:
        out.no_ops += 1
        return
    M.update_time_signature_point(
        conn, point_id=existing["id"], numerator=num, denominator=den,
        actor=actor, request_id=request_id, reason=reason,
    )
    out.mutations += 1
    out.details.append(
        f"signature: {existing['numerator']}/{existing['denominator']} "
        f"-> {num}/{den} (bar 1)"
    )


def _apply_returns_list(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    result: list[dict[str, Any]],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest per-return mixer state from a returns-list result.

    Under Wave M-2, the canonical shape is the new unified
    ``ableton_return(action='list')`` payload — wrapped as
    ``{"returns": [...]}`` — which only carries identity (``return_index``,
    ``name``, ``color``). Mixer state arrives separately via per-return
    ``return_info`` probes. For backward compat the handler also accepts
    the legacy flat-list / ``index``-keyed shape (with optional
    ``volume`` / ``panning`` fields) so the skill's normalization path
    can be retired incrementally.
    """
    # Accept either the new wrapped shape or the legacy bare list.
    entries = result.get("returns") if isinstance(result, dict) else result
    if entries is None:
        out.warnings.append("returns_list result missing 'returns' field")
        return
    for entry in entries:
        idx = entry.get("return_index", entry.get("index"))
        if idx is None:
            out.warnings.append(
                f"returns_list entry missing 'return_index'/'index': {entry!r}"
            )
            continue
        ret_id = Q.get_db_id_by_ableton_index(
            conn, session_id=session_id, db_kind="return", ableton_index=int(idx)
        )
        if ret_id is None:
            out.skipped_unlinked += 1
            out.warnings.append(
                f"return at Ableton index {idx} (name={entry.get('name')!r}) "
                "not linked in session — skipping"
            )
            continue
        ret_row = Q.get_return(conn, ret_id)
        if ret_row is None:
            out.warnings.append(
                f"link points at missing return row {ret_id!r}; skipping"
            )
            continue

        changes: dict[str, Any] = {}
        if "volume" in entry and _floats_differ(entry["volume"], ret_row["volume"]):
            changes["volume"] = float(entry["volume"])
        pan_in = entry.get("panning", entry.get("pan"))
        if pan_in is not None and _floats_differ(pan_in, ret_row["pan"]):
            changes["pan"] = float(pan_in)

        if not changes:
            out.no_ops += 1
            continue

        M.update_return(
            conn,
            return_id=ret_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
            **changes,
        )
        out.mutations += 1
        for k, v in changes.items():
            out.details.append(
                f"return {ret_row['name']!r} {k}: {ret_row[k]!r} -> {v!r}"
            )


def _apply_return_info(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    return_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Wave M-2: ingest per-return mixer state from
    ``ableton_return(action='info', return_index=N)``.

    Probe shape: ``{return_index, name, color, volume, panning, mute, solo}``.

    All six fields are ingested as of M+1-4 (when ``returns`` gained
    nullable ``mute`` / ``solo`` columns); ``mute``/``solo`` follow the
    same nullable-bool pattern as ``tracks.mute``/``solo``/``arm``
    (None on DB means "user never set it" -> a real value from Ableton
    counts as a change).

    Link verification is defense-in-depth: even though the planner only emits
    ``return_info`` for linked returns, a hand-rolled results.json could route
    around that guard. We re-check the link the same way ``_apply_track_info``
    does.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="return", db_id=return_id
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"return_info for return_id={return_id!r}: not linked in session; skipping"
        )
        return

    ret_row = Q.get_return(conn, return_id)
    if ret_row is None:
        out.warnings.append(
            f"link points at missing return row {return_id!r}; skipping"
        )
        return

    # Accept `panning` (the new shape) OR `pan` (legacy) for symmetry with
    # `_apply_session_master` and `_apply_track_info`.
    pan_in = result.get("panning", result.get("pan"))

    changes: dict[str, Any] = {}
    if "name" in result:
        # W4-C: Live unconditionally prefixes return names with `<slot-letter>-`
        # (W3-H 2026-05-18). The DB stores SUFFIX-only; strip the prefix
        # before diffing so the no-op case actually no-ops.
        stripped = strip_return_slot_prefix(result["name"])
        if stripped != ret_row["name"]:
            changes["name"] = stripped
    if "volume" in result and _floats_differ(result["volume"], ret_row["volume"]):
        changes["volume"] = float(result["volume"])
    if pan_in is not None and _floats_differ(pan_in, ret_row["pan"]):
        changes["pan"] = float(pan_in)
    for bool_field in ("mute", "solo"):
        if bool_field in result:
            new = _bool_db(result[bool_field])
            if new is not None and new != ret_row[bool_field]:
                changes[bool_field] = new
    if "color" in result and result["color"] is not None and (
        ret_row["color"] is None or int(result["color"]) != int(ret_row["color"])
    ):
        changes["color"] = int(result["color"])

    if not changes:
        out.no_ops += 1
        return

    M.update_return(
        conn,
        return_id=return_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
        **changes,
    )
    out.mutations += 1
    for k, v in changes.items():
        out.details.append(
            f"return {ret_row['name']!r} {k}: {ret_row[k]!r} -> {v!r}"
        )


def _apply_track_info(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    track_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest one track's mixer state. Handles volume / pan (float diff),
    mute / solo / arm (bool -> 0/1 int diff), color (int diff).

    Defense in depth: verifies the track is linked in this session before
    mutating. The planner already enforces linkage, but a hand-rolled or
    stale results.json could route around that guard."""
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_info:{track_id} — track not linked in this session; "
            "the planner would not have emitted this. Skipping."
        )
        return
    row = Q.get_track(conn, track_id)
    if row is None:
        out.warnings.append(f"track_info:{track_id} — DB row missing; skipping")
        return

    changes: dict[str, Any] = {}
    if "volume" in result and _floats_differ(result["volume"], row["volume"]):
        changes["volume"] = float(result["volume"])
    pan_in = result.get("panning", result.get("pan"))
    if pan_in is not None and _floats_differ(pan_in, row["pan"]):
        changes["pan"] = float(pan_in)
    for bool_field in ("mute", "solo", "arm"):
        if bool_field in result:
            new = _bool_db(result[bool_field])
            if new is not None and new != row[bool_field]:
                changes[bool_field] = new
    if "color" in result and result["color"] is not None and _ints_differ(
        result["color"], row["color"]
    ):
        changes["color"] = int(result["color"])

    if not changes:
        out.no_ops += 1
        return

    M.set_track_mixer(
        conn,
        track_id=track_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
        **changes,
    )
    out.mutations += 1
    for k, v in changes.items():
        out.details.append(
            f"track {row['name']!r} {k}: {row[k]!r} -> {v!r}"
        )


def _apply_track_sends(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    track_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest one track's sends map. The MCP shape is keyed by return *name*;
    we resolve names to DB return ids. Three diff classes:
      - level changed: set_send_level
      - send present in Ableton but not DB: set_send_level (creates row)
      - send present in DB but not Ableton: remove_send

    Defense in depth: verifies the track link before mutating; catches
    `ValueError` per-send so one out-of-range level (e.g. an MCP shape drift)
    doesn't abort the whole pull batch.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_sends:{track_id} — track not linked in this session; "
            "the planner would not have emitted this. Skipping."
        )
        return
    track_row = Q.get_track(conn, track_id)
    if track_row is None:
        out.warnings.append(f"track_sends:{track_id} — DB row missing; skipping")
        return

    db_sends = Q.get_sends_for_track(conn, track_id)
    # Map by return_name for quick diff.
    db_by_return_name: dict[str, sqlite3.Row] = {
        s["return_name"]: s for s in db_sends
    }
    seen_names: set[str] = set()

    for raw_name, level in result.items():
        if level is None:
            continue
        # W4-C: Live's send map is keyed by prefixed return names
        # (`A-Reverb`); the DB stores suffix-only, so strip on lookup.
        return_name = strip_return_slot_prefix(raw_name)
        seen_names.add(return_name)
        ret_row = Q.get_return_by_name(conn, song_id=song_id, name=return_name)
        if ret_row is None:
            # Arc 7 / P7: identify the return by its DB form (`return_name`),
            # not Live's `<letter>-` prefixed UI form (`raw_name`). The user
            # reasons in DB-shaped terms — `Q.get_return_by_name` expects the
            # stripped name — so the message matches the lookup that just
            # failed. Live's prefixed form only appears in the UI; the
            # snapshot author writes the stripped name too (W4-C).
            out.warnings.append(
                f"track {track_row['name']!r} send -> {return_name!r}: "
                "no matching return in DB; skipping (V1 does not auto-create)"
            )
            continue

        existing = db_by_return_name.get(return_name)
        if existing is not None and not _floats_differ(level, existing["level"]):
            out.no_ops += 1
            continue
        try:
            M.set_send_level(
                conn,
                from_track_id=track_id,
                to_return_id=ret_row["id"],
                level=float(level),
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        except ValueError as e:
            # Out-of-range / cross-song / bad-endpoint. Surface and continue —
            # one malformed send must not abort the rest of the batch.
            out.warnings.append(
                f"send {track_row['name']!r} -> {return_name!r} "
                f"(level={level!r}): rejected ({e}); DB unchanged"
            )
            continue
        out.mutations += 1
        if existing is None:
            out.details.append(
                f"send {track_row['name']!r} -> {return_name!r}: "
                f"added (level {level!r})"
            )
        else:
            out.details.append(
                f"send {track_row['name']!r} -> {return_name!r}: "
                f"{existing['level']!r} -> {level!r}"
            )

    # Removals: DB has a send Ableton doesn't.
    for return_name, send in db_by_return_name.items():
        if return_name in seen_names:
            continue
        M.remove_send(
            conn,
            from_track_id=track_id,
            to_return_id=send["to_return_id"],
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"send {track_row['name']!r} -> {return_name!r}: removed"
        )


__all__ = [
    "plan_pull_mix",
    "plan_pull_score_globals",
    "_apply_session_info",
    "_apply_session_master",
    "_apply_session_tempo",
    "_apply_session_signature",
    "_apply_returns_list",
    "_apply_return_info",
    "_apply_track_info",
    "_apply_track_sends",
]
