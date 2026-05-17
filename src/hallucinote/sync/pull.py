"""Ableton -> DB planner. Mirror of `push.py` for the inbound direction.

Produces a list of `PullCall` objects describing MCP *read* probes the agent
should run. After the agent executes the plan, it calls `apply_pull_results`
to diff each probe response against the DB and write mutations through the
standard mutator path — so events fall out naturally.

Why a plan rather than direct calls: same reason as push. MCP tools run in
the agent, not in Python. Returning a plan keeps this layer pure, testable,
and lets the skill orchestrate without inlining MCP shape knowledge.

Conflict policy (V1): **Ableton-authoritative on pull**. If the DB and Ableton
disagree on a field, the Ableton value wins and a mutation is emitted with
`actor='sync'` (matching push). Pull-vs-push provenance lives in the event's
`reason` field — callers should pass `reason="pull from <session>"` or similar.
Three-way merge with a last-pushed snapshot is the right long-term answer for
multi-collaborator workflows but is over-scope for a single-user authoring
tool right now (see docs/VISION.md "What this costs").

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Reverse lookups (Ableton index -> DB id) go through `ableton_links` via
`queries.get_db_id_by_ableton_index`. Unlinked Ableton rows are reported but
not ingested — V1 does not auto-create DB rows for tracks/returns the user
made in Ableton outside of a session.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

from hallucinote.db import mutations as M, queries as Q
from hallucinote.db.connection import transaction

# Float tolerance for diff detection. 1e-3 means anything within ~0.1% of full
# scale is a no-op — covers Live's display-rounding (e.g. 0.6249 vs 0.6250)
# without papering over real moves.
_FLOAT_EPS = 1e-3


@dataclass
class PullCall:
    """One MCP *read* probe. `key` identifies what it pulls back; the apply
    layer dispatches on the `<kind>` prefix of `key`.

    Names are *canonical* (post-Wave-1 MCP). Agent uses `mcp_names.resolve` to
    map onto today's surface if needed.

    Expected `result` shape per key kind:
      - `session_info`           -> {master: {volume, panning}, tempo, signature, ...}
      - `returns_list`           -> [{index, name, volume, panning, ...}, ...]
      - `track_info:<track_id>`  -> {name, type, volume, panning, mute?, solo?,
                                     arm?, color?, ...}  (mixer fields)
      - `track_sends:<track_id>` -> {<return_name>: level, ...}
    """
    tool: str
    args: dict[str, Any]
    key: str
    purpose: str = ""


@dataclass
class PullPlan:
    calls: list[PullCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, call: PullCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


@dataclass
class ApplyResult:
    """Summary of an `apply_pull_results` run.

    `details` carries one human-readable line per applied diff so the skill
    can show the user exactly what changed. `warnings` carries non-fatal
    things the user should know (unlinked Ableton rows, missing results, etc.).
    """
    mutations: int = 0
    no_ops: int = 0
    skipped_unlinked: int = 0
    warnings: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Planners
# ---------------------------------------------------------------------------


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
        if t["kind"] in ("master", "return"):
            # master is reached via session_info; return rows are reserved.
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


def plan_pull_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan a single `get_cue_points` probe.

    Cue identity is `(position_bar)` with float-tolerance — matching by
    position is the only stable handle today. Names are NOT pulled into the
    DB: MCP gap #13 (`get_cue_points` returns numeric IDs, not names),
    so any name returned would clobber real names. Apply diffs names as
    *warnings* only.
    """
    plan = PullPlan()
    plan.add(PullCall(
        tool="get_cue_points",
        args={},
        key="cue_points_list",
        purpose="pull arrangement cue points (positions only; names gap-flagged)",
    ))
    return plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _floats_differ(new: Any, existing: Any) -> bool:
    """Tolerant float compare.

    If `new` is None, the probe didn't report a value — no diff (caller should
    skip rather than write null). If `existing` is None and `new` is a value,
    that IS a real change (DB had no setting; Ableton has one). Otherwise
    diff iff the magnitude exceeds `_FLOAT_EPS`.
    """
    if new is None:
        return False
    if existing is None:
        return True
    return abs(float(new) - float(existing)) > _FLOAT_EPS


def _bool_db(v: Any) -> int | None:
    """Normalize an MCP boolean into the DB's 0/1 int convention."""
    if v is None:
        return None
    return 1 if v else 0


def _ints_differ(new: Any, existing: Any) -> bool:
    """Same DB-None-vs-new-value asymmetry as `_floats_differ`."""
    if new is None:
        return False
    if existing is None:
        return True
    return int(new) != int(existing)


def _parse_signature(s: Any) -> tuple[int, int]:
    """Parse a `"N/D"` signature string. Raises ValueError on malformed input."""
    parts = str(s).split("/")
    if len(parts) != 2:
        raise ValueError(f"expected 'N/D', got {s!r}")
    num, den = int(parts[0]), int(parts[1])
    if num <= 0 or den <= 0:
        raise ValueError(f"signature {s!r}: numerator/denominator must be positive")
    return num, den


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

    Shape: ``{return_index, name, color, volume, panning, mute, solo}``.
    We diff each present field against the DB row and emit the union of
    changes through ``update_return``.
    """
    ret_row = Q.get_return(conn, return_id)
    if ret_row is None:
        out.warnings.append(
            f"link points at missing return row {return_id!r}; skipping"
        )
        return

    changes: dict[str, Any] = {}
    if "name" in result and result["name"] != ret_row["name"]:
        changes["name"] = result["name"]
    if "volume" in result and _floats_differ(result["volume"], ret_row["volume"]):
        changes["volume"] = float(result["volume"])
    if "panning" in result and _floats_differ(result["panning"], ret_row["pan"]):
        changes["pan"] = float(result["panning"])
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

    for return_name, level in result.items():
        if level is None:
            continue
        seen_names.add(return_name)
        ret_row = Q.get_return_by_name(conn, song_id=song_id, name=return_name)
        if ret_row is None:
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


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Inverse helper to `push._beats_per_bar`: Live counts a beat as a quarter
    note regardless of meter, so beats-per-bar = numerator * (4 / denominator)."""
    return numerator * (4.0 / denominator)


def _join_bar_beat(
    bar: int,
    beat: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Inverse of `push._split_bar`: combine a 1-based bar int + 0-based beat
    float into a fractional `position_bar` using the song's time-signature
    map. Empty `ts_points` defaults to 4/4."""
    num, den = (4, 4)
    if ts_points:
        # Use the latest signature at-or-before this bar.
        chosen = ts_points[0]
        for p in ts_points:
            if p["start_bar"] <= bar:
                chosen = p
            else:
                break
        num, den = (chosen["numerator"], chosen["denominator"])
    return float(bar) + (float(beat) / _beats_per_bar(num, den))


def _is_numeric_id_name(s: Any) -> bool:
    """MCP gap #13: `get_cue_points` returns numeric strings ('1', '2', ...)
    instead of the real names. Detect so we don't clobber DB names with these."""
    return isinstance(s, str) and s.isdigit()


def _apply_cue_points_list(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    result: list[dict[str, Any]],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest Ableton's cue points by position.

    Matching: `(position_bar)` with float tolerance. Names are not pulled
    into the DB (MCP gap #13). Three diff classes:
      - position present in Ableton, absent in DB -> add_cue_point
      - position present in both -> no-op (with a name-mismatch warning if
        the pulled name is non-numeric and differs from DB)
      - position present in DB, absent in Ableton -> remove_cue_point
    """
    ts_points = Q.get_time_signature_map(conn, song_id)
    db_cues = list(Q.get_cue_points(conn, song_id))
    # Round to fixed precision for tolerant matching (1/1000 of a bar — way
    # finer than any musically meaningful cue placement).
    pos_key = lambda pb: round(float(pb), 3)
    db_by_pos: dict[float, sqlite3.Row] = {pos_key(c["position_bar"]): c for c in db_cues}
    seen: set[float] = set()

    for entry in result:
        # Accept either {position_bar: float} or {bar: int, beat: float}.
        if "position_bar" in entry:
            position_bar = float(entry["position_bar"])
        elif "bar" in entry:
            position_bar = _join_bar_beat(
                int(entry["bar"]), float(entry.get("beat", 0.0)), ts_points
            )
        else:
            out.warnings.append(
                f"cue_points_list entry missing position: {entry!r}"
            )
            continue
        k = pos_key(position_bar)
        seen.add(k)
        existing = db_by_pos.get(k)
        name_in = entry.get("name")
        if existing is None:
            # New from Ableton — add. Drop numeric-ID names (gap #13).
            stored_name = None if _is_numeric_id_name(name_in) else name_in
            M.add_cue_point(
                conn, song_id=song_id, position_bar=position_bar,
                name=stored_name,
                actor=actor, request_id=request_id, reason=reason,
            )
            out.mutations += 1
            out.details.append(
                f"cue: added at bar {position_bar:g}"
                + (f" (name={stored_name!r})" if stored_name else "")
            )
            continue
        # Position matches. Flag name diffs but don't mutate (gap #13).
        if (name_in
            and not _is_numeric_id_name(name_in)
            and name_in != existing["name"]):
            out.warnings.append(
                f"cue at bar {position_bar:g}: name mismatch "
                f"(DB={existing['name']!r}, Ableton={name_in!r}); "
                "names not pulled (MCP gap #13)"
            )
        out.no_ops += 1

    # Removals: DB cues not seen in Ableton.
    for c in db_cues:
        if pos_key(c["position_bar"]) in seen:
            continue
        M.remove_cue_point(
            conn, cue_id=c["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"cue: removed at bar {c['position_bar']:g}"
            + (f" (was {c['name']!r})" if c["name"] else "")
        )


# Dispatch table: key kind -> (handler, expects-db-id)
_HANDLERS = {
    "session_info":     ("session_info",     False),
    "returns_list":     ("returns_list",     False),
    "return_info":      ("return_info",      True),   # Wave M-2: per-return mixer state
    "track_info":       ("track_info",       True),
    "track_sends":      ("track_sends",      True),
    "cue_points_list":  ("cue_points_list",  False),
}


def apply_pull_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    song_id: str,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> ApplyResult:
    """Ingest MCP probe results, diff against DB, write mutations.

    Each result dict shape:
        {
          "key":   "<the PullCall.key from the plan>",
          "ok":    bool,
          "tool":  "<canonical tool name>",
          "result": { ... per-key-kind shape, see PullCall docstring ... },
          "error": "...optional, only if ok=False ..."
        }

    Failed results (`ok=False`) are recorded as warnings and skipped — the
    agent layer is the source of truth for tool-side errors. Unknown key
    kinds raise `ValueError` so a new planner-emitted key can't silently
    no-op past this layer.
    """
    out = ApplyResult()
    with transaction(conn):
        for r in results:
            key = r.get("key", "")
            if not r.get("ok", False):
                out.warnings.append(
                    f"probe {key!r} failed: {r.get('error', 'no error message')}"
                )
                continue

            kind, _, db_id = key.partition(":")
            if not kind:
                raise ValueError(f"pull result missing 'key': {r!r}")
            if kind not in _HANDLERS:
                raise ValueError(
                    f"unknown pull result key kind {kind!r} (full key={key!r}). "
                    f"Declare it in _HANDLERS in sync/pull.py."
                )

            handler_name, needs_db_id = _HANDLERS[kind]
            if needs_db_id and not db_id:
                raise ValueError(
                    f"pull result key {key!r} missing db_id after {kind!r}:"
                )

            result_payload = r.get("result")
            if result_payload is None:
                out.warnings.append(f"probe {key!r} ok=True but missing 'result'")
                continue

            if handler_name == "session_info":
                _apply_session_info(
                    conn, song_id=song_id, session_id=session_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "returns_list":
                _apply_returns_list(
                    conn, song_id=song_id, session_id=session_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "return_info":
                _apply_return_info(
                    conn, session_id=session_id, return_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_info":
                _apply_track_info(
                    conn, session_id=session_id, track_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_sends":
                _apply_track_sends(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "cue_points_list":
                _apply_cue_points_list(
                    conn, song_id=song_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )

    return out
