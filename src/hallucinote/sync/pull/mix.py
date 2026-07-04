"""Mix-state pull: track / return / master mixer fields, sends, and the
global score fields (tempo + signature) that ride the session_info probe.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.return_naming import normalize_live_return_name

from hallucinote.db import mutations as M, queries as Q

from ..routing_names import (
    OUTPUT_DISPLAY_NAME_KIND,
    INPUT_DISPLAY_NAME_KIND,
    OUTPUT_DEFAULT_KIND,
    MONITOR_DEFAULT,
)

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
    ``ableton_return(action='list')`` globally, plus — per linked track — one
    ``ableton_track(action='info')``, one ``ableton_track(action='get_sends')``,
    and (RTE-1K9T chunk 05) three routing reads:
    ``get_output_routing`` / ``get_input_routing`` / ``get_monitoring_state``.
    All domain probes use the unified surface as of Wave M-2.
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
                "push it via the tracks phase (plan_push_song_tracks) first, "
                "then re-run pull"
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
        # RTE-1K9T chunk 05: per-track routing — three independent LOM reads
        # (one MCP call each), mirroring the three push routing keys. Probed
        # for EVERY linked track (not gated on DB routing state) so a manual
        # reroute in Live is discovered even when the DB carries no routing yet.
        plan.add(PullCall(
            tool="ableton_track",
            args={"action": "get_output_routing", "track_index": track_at},
            key=f"track_output_routing:{t['id']}",
            purpose=f"pull output routing for {t['name']}",
        ))
        plan.add(PullCall(
            tool="ableton_track",
            args={"action": "get_input_routing", "track_index": track_at},
            key=f"track_input_routing:{t['id']}",
            purpose=f"pull input routing for {t['name']}",
        ))
        plan.add(PullCall(
            tool="ableton_track",
            args={"action": "get_monitoring_state", "track_index": track_at},
            key=f"track_monitor:{t['id']}",
            purpose=f"pull monitor state for {t['name']}",
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
        # before diffing so the no-op case actually no-ops. SYN-RENDER-RELINK:
        # also strip a render-appended ` | HallucinoteAnalyzer` suffix — otherwise
        # pulling a post-render set writes the dirty name straight into the DB.
        stripped = normalize_live_return_name(result["name"])
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
        # SYN-RENDER-RELINK: also strip a render-appended analyzer suffix so the
        # send doesn't silently drop when get_return_by_name misses.
        return_name = normalize_live_return_name(raw_name)
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


# ---------------------------------------------------------------------------
# RTE-1K9T chunk 05 — routing pull (inverse of sync/push/routing.py)
# ---------------------------------------------------------------------------
#
# Push resolves a DB routing reference → a Live display_name; pull does the
# inverse — maps the probed display_name back to a DB reference and writes it
# through ``set_track_routing``. Two churn-avoidance rules govern the apply (D8):
#
#   1. DB-NULL ≡ Live-default. A track with no authored routing has NULL routing
#      columns; Live still reports a concrete default ("Main" / "No Input" /
#      "Auto"). Treating NULL as the default means a first pull of an unrouted
#      track is a no-op instead of churning every NULL into an explicit default.
#   2. Faithful, Ableton-authoritative writes. Only a NON-default Live route (or
#      a user reverting a previously-authored route back to default) mutates the
#      DB; the value written is exactly what Live reports.
#
# V1 input scope (D6/D8): pull persists ONLY a track→track input (input routed
# from a sibling track's output). Fixed input kinds (Ext. In / No Input /
# Resampling) and arbitrary hardware inputs are NOT persisted — Live's non-track
# input default is open, hardware-bound, and NOT live-probed, so a NULL≡default
# rule on them would risk churning every track's default on the first pull. They
# are deferred until a live-probe pins Live's input defaults (enqueued in
# operator-verification.md). Output + monitor — the PRE-MAIN bus's actual
# mechanism — pull fully; input routing the bus pattern does not use.


def _resolve_routing_reference(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    direction: str,            # 'output' | 'input'
    display_name: str,
    source_track_id: str,
) -> tuple[str, str | None] | str | None:
    """Map a Live routing ``display_name`` → a DB reference ``(kind, target_id)``.

    Returns:
      * ``(kind, None)``      — a fixed-vocabulary target (master / sends_only /
                                ext_out / ext_in / no_input / resampling);
      * ``("track", tid)``    — the name matched exactly one sibling track;
      * ``"ambiguous"``       — the name matched 2+ sibling tracks (no reliable
                                reference can be formed);
      * ``None``              — unmappable (not a fixed name, not a known track).

    Fixed names win over track-name resolution: "Main" always means the master
    output even if some track happens to be named "Main". The source track and
    the master row are excluded from track-target matching (a track never routes
    to itself, and the master is reached via the fixed "Main" name, never as a
    track-target).
    """
    inverse = (
        OUTPUT_DISPLAY_NAME_KIND if direction == "output"
        else INPUT_DISPLAY_NAME_KIND
    )
    fixed_kind = inverse.get(display_name)
    if fixed_kind is not None:
        return (fixed_kind, None)

    matches = [
        t for t in Q.get_tracks_for_song(conn, song_id)
        if t["name"] == display_name
        and t["id"] != source_track_id
        and t["kind"] != "master"
    ]
    if len(matches) == 1:
        return ("track", matches[0]["id"])
    if len(matches) >= 2:
        return "ambiguous"
    return None


def _apply_track_routing(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    track_id: str,
    direction: str,            # 'output' | 'input'
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest one direction (output | input) of one track's routing from a
    ``get_{output,input}_routing`` probe (shape: ``{has_*_routing, current_type,
    current_channel, available_*}``).

    Defense in depth: re-verifies the track link before mutating (the planner
    already enforces it, but a hand-rolled results.json could route around it).
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_{direction}_routing:{track_id} — track not linked in this "
            "session; the planner would not have emitted this. Skipping."
        )
        return
    row = Q.get_track(conn, track_id)
    if row is None:
        out.warnings.append(
            f"track_{direction}_routing:{track_id} — DB row missing; skipping"
        )
        return

    # No routing surface (a clip-less family) or no current target reported —
    # nothing to ingest.
    if result.get(f"has_{direction}_routing") is False:
        out.no_ops += 1
        return
    current_type = result.get("current_type")
    if current_type is None:
        out.no_ops += 1
        return
    live_channel = result.get("current_channel")

    ref = _resolve_routing_reference(
        conn, song_id=row["song_id"], direction=direction,
        display_name=current_type, source_track_id=track_id,
    )
    if ref == "ambiguous":
        out.warnings.append(
            f"track {row['name']!r} {direction} routing -> {current_type!r}: "
            "matches multiple tracks by name; cannot form an unambiguous "
            "reference — skipping (rename one of the colliding tracks)"
        )
        return
    if ref is None:
        if direction == "output":
            out.warnings.append(
                f"track {row['name']!r} output routing -> {current_type!r}: "
                "not a known routing target or track in this song — skipping"
            )
            return
        # INPUT, unmappable (an arbitrary MIDI / interface input, e.g. "All Ins").
        # Falls through to the non-track-input path below (clears a stale
        # authored route; otherwise a quiet no-op).
        live_kind, live_target = None, None
    else:
        live_kind, live_target = ref

    if direction == "input" and live_kind != "track":
        # V1 pulls ONLY a track→track input — fixed input kinds (ext_in /
        # no_input / resampling) and arbitrary hardware inputs sit on Live's
        # open/hardware-bound, unprobed default, so persisting them risks
        # churning every track (D6/D8). BUT if the DB holds an AUTHORED input
        # route and Live now shows a non-track input, the user changed it in
        # Live: clear the stale route (Ableton-authoritative) so the next push
        # doesn't SILENTLY re-assert it over the manual edit. A track that never
        # had an authored input route is a quiet no-op (the common default case).
        if row["input_routing_kind"] is None:
            out.no_ops += 1
            return
        try:
            M.set_track_routing(
                conn,
                track_id=track_id,
                input_routing_kind=None,
                input_routing_target_id=None,
                input_routing_channel=None,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        except ValueError as e:
            out.warnings.append(
                f"track {row['name']!r} input routing -> {current_type!r}: "
                f"clearing the stale authored route was rejected ({e}); DB unchanged"
            )
            return
        out.mutations += 1
        out.details.append(
            f"track {row['name']!r} input routing: cleared the authored "
            f"{row['input_routing_kind']!r} route — Live now shows non-track "
            f"{current_type!r}, which V1 doesn't persist (so it won't re-assert "
            "the old route on the next push)"
        )
        return

    db_kind = row[f"{direction}_routing_kind"]
    db_target = row[f"{direction}_routing_target_id"]
    db_channel = row[f"{direction}_routing_channel"]

    # A track-target (input or output) is never Live's default, so it always
    # takes the persist path; only OUTPUT has a fixed-name default to collapse.
    is_default_route = (
        direction == "output"
        and live_kind == OUTPUT_DEFAULT_KIND
        and live_target is None
    )
    if is_default_route:
        # Live shows the DEFAULT "Main" output. NULL ≡ default, so an unrouted
        # DB track (or one explicitly at 'master') is a no-op — no churn (D8).
        if db_kind is None or db_kind == OUTPUT_DEFAULT_KIND:
            out.no_ops += 1
            return
        # A previously-authored non-default route was reverted to default in
        # Live — Ableton-authoritative, so reset the DB to the default route.
        changes: dict[str, Any] = {
            f"{direction}_routing_kind": OUTPUT_DEFAULT_KIND,
            f"{direction}_routing_target_id": None,
            f"{direction}_routing_channel": None,
        }
    else:
        # Non-default route — persist faithfully (kind + target + channel).
        if (
            live_kind == db_kind
            and live_target == db_target
            and live_channel == db_channel
        ):
            out.no_ops += 1
            return
        changes = {
            f"{direction}_routing_kind": live_kind,
            f"{direction}_routing_target_id": live_target,
            f"{direction}_routing_channel": live_channel,
        }

    try:
        M.set_track_routing(
            conn,
            track_id=track_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
            **changes,
        )
    except ValueError as e:
        # Validation rejects BEFORE any write, so the transaction stays clean;
        # surface and continue rather than abort the whole pull batch (mirrors
        # _apply_track_sends' per-send ValueError guard).
        out.warnings.append(
            f"track {row['name']!r} {direction} routing -> {current_type!r}: "
            f"rejected ({e}); DB unchanged"
        )
        return
    out.mutations += 1
    out.details.append(
        f"track {row['name']!r} {direction} routing: "
        f"{db_kind!r} -> {current_type!r}"
        + (f" (channel {live_channel!r})" if live_channel is not None else "")
    )


def _apply_track_monitor(
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
    """Ingest a track's monitor state from a ``get_monitoring_state`` probe
    (shape: ``{has_monitoring_state, monitoring_state}``). Same NULL ≡ default
    rule as ``_apply_track_routing`` — Live's default 'Auto' is a no-op against a
    NULL (or explicitly-'Auto') DB column (D8)."""
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_monitor:{track_id} — track not linked in this session; "
            "the planner would not have emitted this. Skipping."
        )
        return
    row = Q.get_track(conn, track_id)
    if row is None:
        out.warnings.append(f"track_monitor:{track_id} — DB row missing; skipping")
        return

    if result.get("has_monitoring_state") is False:
        out.no_ops += 1
        return
    live_ms = result.get("monitoring_state")
    if live_ms is None:
        # Don't persist a value the mutator would reject. The getter names an
        # out-of-vocabulary Live enum int as monitoring_state=None + a
        # monitoring_state_raw diagnostic (the future-Live-enum-shift signal it
        # was built to surface) — propagate it so the one-constant fix is
        # diagnosable rather than silently swallowed; a plain absent field is a
        # benign no-op.
        raw = result.get("monitoring_state_raw")
        if raw is not None:
            out.warnings.append(
                f"track {row['name']!r} monitor: Live reported an "
                f"out-of-vocabulary monitoring_state int ({raw!r}); not "
                "persisted (update _MONITORING_STATE_NAMES in the MCP handler)"
            )
        out.no_ops += 1
        return
    db_ms = row["monitoring_state"]

    if live_ms == MONITOR_DEFAULT:
        if db_ms is None or db_ms == MONITOR_DEFAULT:
            out.no_ops += 1
            return
        new_ms = MONITOR_DEFAULT
    else:
        if live_ms == db_ms:
            out.no_ops += 1
            return
        new_ms = live_ms

    try:
        M.set_track_routing(
            conn,
            track_id=track_id,
            monitoring_state=new_ms,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
    except ValueError as e:
        out.warnings.append(
            f"track {row['name']!r} monitor -> {live_ms!r}: "
            f"rejected ({e}); DB unchanged"
        )
        return
    out.mutations += 1
    out.details.append(
        f"track {row['name']!r} monitor: {db_ms!r} -> {new_ms!r}"
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
    "_apply_track_routing",
    "_apply_track_monitor",
]
