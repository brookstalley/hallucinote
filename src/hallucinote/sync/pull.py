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

from hallucinote.capture import strip_return_slot_prefix

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
      - `track_arrangement_clips:<track_id>`
                                 -> {track_index, location: 'arrangement',
                                     clips: [{arrangement_clip_index, name,
                                              start_beats, length}, ...]}
                                    (W3-4 / M+1-3b — per-track placements)
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


def plan_pull_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan a single `ableton_arrangement(action='cue_list')` probe.

    Wave M-5: retargeted from the legacy fork's `get_cue_points` to the
    unified arrangement tool. Cue identity is `(position_beats)` with
    float-tolerance — matching by position is the only stable handle.
    Names round-trip cleanly in the greenfield server (gap #13 doesn't
    apply); apply layer still treats name diffs as informational since
    DB-side cue names are user-authoritative.
    """
    plan = PullPlan()
    plan.add(PullCall(
        tool="ableton_arrangement",
        args={"action": "cue_list"},
        key="cue_points_list",
        purpose="pull arrangement cue points (position_beats + names)",
    ))
    return plan


def plan_pull_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull the top-level device chain for each linked
    track and return (Wave M+1-2 / W3-3).

    Emits one ``ableton_device(action='list')`` per linked parent. The
    ``list`` probe returns positional device identity (``device_index``,
    ``class_name``, ``name``, ``is_active``) for the top-level chain
    only — nested rack chains are not traversed (Live's API constraint,
    tracked as gap #17b).

    Out of scope (separate backlog items):
      - Nested rack chains (gap #17b)
      - Master-strip device chain (separate parent kind / planner)
      - Per-device parameter values (gated on gap #17b)
      - ``is_active`` flag (no DB column today; the field rides along in
        the probe but apply currently ignores it)

    Skips ``master`` track rows in the ``tracks`` iteration the same way
    ``plan_pull_mix`` does — master devices are reached via a future
    master-chain planner. Real returns live in the separate ``returns``
    table (the legacy ``tracks.kind='return'`` reservation was dropped
    V1 close-out 2026-05-17).
    """
    plan = PullPlan()
    any_emitted = False

    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
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
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_device",
            args={"action": "list", "track_index": track_at},
            key=f"track_devices:{t['id']}",
            purpose=f"pull device chain for track {t['name']!r}",
        ))

    for r in Q.get_returns_for_song(conn, song_id):
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            plan.warn(
                f"return {r['name']!r} ({r['id']}) not linked in session — skipping"
            )
            continue
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_device",
            args={"action": "list", "return_index": return_at},
            key=f"return_devices:{r['id']}",
            purpose=f"pull device chain for return {r['name']!r}",
        ))

    if not any_emitted:
        plan.warn(
            "no linked tracks or returns for this session — device-chain "
            "pull will be empty"
        )
    return plan


def plan_pull_arrangement_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull per-track arrangement-clip placements (W3-4 / M+1-3b).

    Emits one ``ableton_clip(action='list', location='arrangement',
    track_index=N)`` per linked authoring track. The probe returns dense
    placements `{arrangement_clip_index, name, start_beats, length}`; the
    apply layer converts beats -> bars via the song's time-signature map and
    diffs positionally against `arrangement_clips` table rows.

    Skips `master` track rows: master has no arrangement of its own.
    Real returns live in the `returns` table and don't appear in the
    `tracks` iteration this planner walks (the legacy
    `tracks.kind='return'` reservation was dropped V1 close-out
    2026-05-17).

    Per `docs/terminology.md`, this is exclusively about arrangement-clip
    *placements* (rows in the `arrangement_clips` table).
    Arrangement-VIEW state (loop region, view zoom) is a separate concern
    with no DB home today (backlog).
    """
    plan = PullPlan()
    any_emitted = False
    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
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
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_clip",
            args={
                "action": "list",
                "location": "arrangement",
                "track_index": track_at,
            },
            key=f"track_arrangement_clips:{t['id']}",
            purpose=f"pull arrangement-clip placements for track {t['name']!r}",
        ))
    if not any_emitted:
        plan.warn(
            "no linked authoring tracks for this session — "
            "arrangement-clip pull will be empty"
        )
    return plan


def plan_pull_session_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull per-track session-view clip-slot contents
    (V1 close-out Chunk C).

    Emits one ``ableton_clip(action='list', location='session',
    track_index=N)`` per linked authoring track. The probe returns dense
    per-slot entries — populated slots carry
    ``{clip_index, empty: False, name, length}``; empty slots carry
    ``{clip_index, empty: True}``. The apply layer diffs by slot
    (``clips.slot``, which Ableton calls ``clip_index``), the most
    stable identity available for session-view clips.

    Skips `master` track rows: master has no session-view clip grid.
    Real returns live in the `returns` table and don't appear in the
    `tracks` iteration this planner walks.

    Symmetric with `plan_pull_arrangement_clips`. The MCP read side
    shipped in M+1-3a; this planner closes the sync-layer half so
    edits made in Ableton's Session View round-trip back to the DB.
    """
    plan = PullPlan()
    any_emitted = False
    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
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
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_clip",
            args={
                "action": "list",
                "location": "session",
                "track_index": track_at,
            },
            key=f"track_session_clips:{t['id']}",
            purpose=f"pull session-view clip slots for track {t['name']!r}",
        ))
    if not any_emitted:
        plan.warn(
            "no tracks linked in this session — "
            "session-clip pull will be empty"
        )
    return plan


def plan_pull_notes_for_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull notes per linked clip (V1 close-out Chunk D —
    gap #4 partial resolution).

    Emits one ``ableton_note(action='list', track_index=N, location='session',
    clip_index=M)`` per linked session clip. The probe returns the clip's
    notes with Live's stable per-note IDs (via ``clip.get_notes_extended()``);
    the apply layer content-diffs them against DB notes and emits precise
    `update_note` / `insert_notes` / `delete_notes` mutations.

    Identity strategy: Live note IDs are stable WITHIN a session but
    expire on any note-write, so this layer uses them only for
    debug/dedup within one pull pass. The DB-side note UUID is the
    persistent identity. Matching is content-based on
    `(pitch, start_beats, duration_beats)` within `_FLOAT_EPS`:
      - velocity / mute changes preserve the DB note's UUID via
        `update_note`
      - a note whose pitch/start/duration changes surfaces as
        delete + insert (UUID rotates — known V1 limitation)

    Walks every linked clip in the session. Empty clips (no DB notes
    and presumably no Live notes either) still get a probe — the
    cost is one MCP round-trip, and the structural correctness of
    "all linked clips were checked" is worth the cost at V1 scale.
    """
    plan = PullPlan()
    any_emitted = False
    for link in Q.get_ableton_links_for_session(conn, session_id):
        if link["db_kind"] != "clip":
            continue
        clip_id = link["db_id"]
        clip_at = int(link["ableton_index"])
        clip_row = Q.get_clip(conn, clip_id)
        if clip_row is None:
            plan.warn(
                f"clip link {clip_id} has no clips row — stale link, "
                "skipping. Re-push to re-link."
            )
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id,
            db_kind="track", db_id=clip_row["track_id"],
        )
        if track_at is None:
            plan.warn(
                f"clip {clip_id} is linked but its track "
                f"{clip_row['track_id']} is not — skipping. "
                "Push the track first."
            )
            continue
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_note",
            args={
                "action": "list",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
            },
            key=f"clip_notes:{clip_id}",
            purpose=(
                f"pull notes for clip {clip_row['name']!r} "
                f"(slot {clip_at} on track {track_at})"
            ),
        ))
    if not any_emitted:
        plan.warn(
            "no clips linked in this session — note pull will be empty"
        )
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
            out.warnings.append(
                f"track {track_row['name']!r} send -> {raw_name!r}: "
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
    """MCP gap #13 (legacy fork): `get_cue_points` returned numeric strings
    ('1', '2', ...) instead of the real names. The greenfield M-5 server's
    `ableton_arrangement(action='cue_list')` returns real names, but the
    detector stays as a defense against any agent-layer reformatting that
    might re-introduce numeric IDs.
    """
    return isinstance(s, str) and s.isdigit()


def _beats_to_position_bar(
    beats: float, ts_points: list[sqlite3.Row]
) -> float:
    """Walk the time-signature map to convert a beats-from-song-start
    position into a fractional bar position.

    Wave M-5: the wire format for cue positions is now `position_beats`
    (meter-agnostic, per principle 2). The DB stores `position_bar`. This
    helper bridges. For songs with no ts_points the assumption is 4/4
    throughout — same convention as the rest of the planner's bar math.
    """
    if not ts_points:
        # 4/4 fallback: 4 beats per bar, 1-based.
        return 1.0 + (float(beats) / 4.0)
    # Sort ts points by start_bar to walk forward.
    points = sorted(ts_points, key=lambda r: float(r["start_bar"]))
    # The first ts point should be at bar 1; if not, prepend a synthetic 4/4 at bar 1.
    if float(points[0]["start_bar"]) > 1.0 + 1e-9:
        first_bpb = 4.0  # 4/4 default for bars before the first explicit ts
    else:
        first_bpb = _beats_per_bar(
            int(points[0]["numerator"]), int(points[0]["denominator"])
        )

    cumulative_beats = 0.0
    current_bar = 1.0
    current_bpb = first_bpb

    for i, point in enumerate(points):
        point_bar = float(point["start_bar"])
        # Beats consumed up to this ts boundary (in the *previous* meter)
        bars_in_section = point_bar - current_bar
        beats_in_section = bars_in_section * current_bpb
        if cumulative_beats + beats_in_section > float(beats) - 1e-9:
            # Target beat is in this section.
            remaining = float(beats) - cumulative_beats
            return current_bar + (remaining / current_bpb)
        # Cross into the next section.
        cumulative_beats += beats_in_section
        current_bar = point_bar
        current_bpb = _beats_per_bar(
            int(point["numerator"]), int(point["denominator"])
        )

    # Beyond the last ts point — extrapolate in the current meter.
    remaining = float(beats) - cumulative_beats
    return current_bar + (remaining / current_bpb)


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

    Matching: `(position_bar)` with float tolerance. Three diff classes:
      - position present in Ableton, absent in DB -> add_cue_point (the
        Ableton-side name IS stored on add, since Wave M-5's
        ableton_arrangement(action='cue_list') returns real names rather
        than the legacy fork's numeric IDs)
      - position present in both -> no-op (with a name-mismatch warning
        if the pulled name differs from DB; DB names are user-authoritative
        so pulls do not overwrite them)
      - position present in DB, absent in Ableton -> remove_cue_point

    The numeric-ID-name detector stays as a defense against agent-layer
    reformatting that might re-introduce the legacy fork's numeric shape.
    """
    ts_points = Q.get_time_signature_map(conn, song_id)
    db_cues = list(Q.get_cue_points(conn, song_id))
    # Round to fixed precision for tolerant matching (1/1000 of a bar — way
    # finer than any musically meaningful cue placement).
    pos_key = lambda pb: round(float(pb), 3)
    db_by_pos: dict[float, sqlite3.Row] = {pos_key(c["position_bar"]): c for c in db_cues}
    seen: set[float] = set()

    for entry in result:
        # Accept three shapes (Wave M-5 adds position_beats):
        #   {position_beats: float}            (greenfield arrangement.cue_list)
        #   {position_bar: float}              (legacy / pre-normalized)
        #   {bar: int, beat: float}            (legacy fork shape)
        if "position_beats" in entry:
            position_bar = _beats_to_position_bar(
                float(entry["position_beats"]), ts_points
            )
        elif "position_bar" in entry:
            position_bar = float(entry["position_bar"])
        elif "bar" in entry:
            # Legacy fork shape — dormant since the legacy fork was retired
            # in W3 / Wave M. Guard `bar < 1` because the new
            # `cue_points.position_bar >= 1.0` CHECK (added J-6) would
            # `IntegrityError` on `_join_bar_beat(0, ...)` → 0.0. Warn and
            # skip rather than crashing the whole pull on bad upstream data.
            bar_in = int(entry["bar"])
            if bar_in < 1:
                out.warnings.append(
                    f"cue_points_list entry has legacy bar={bar_in!r} "
                    "(< 1) — schema requires position_bar >= 1.0; skipping"
                )
                continue
            position_bar = _join_bar_beat(
                bar_in, float(entry.get("beat", 0.0)), ts_points
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


def _apply_devices_for_parent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    parent_kind: str,
    parent_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff one top-level device chain against the probe payload (W3-3).

    Identity is *positional*: a (chain, position) slot holding a device
    with the same ``(class_name, name)`` is a no-op; any mismatch is a
    delete + create at that position (cleaner than a hypothetical
    ``update_device`` since per-device parameter rows cascade and a
    different kind at the same slot is structurally a different device).
    Live's API exposes no stable per-device identity across moves, so
    matching by position is the only stable shape.

    Empty-chain handling: if both sides are empty, no-op (don't create
    a stub chain row). If DB has a chain but Ableton is empty, all
    devices are deleted and the empty chain row is kept (cheap and
    avoids churn on the next push).

    ``is_active`` from the probe is ignored — no DB column today
    (tracked as a future schema extension). The mute/solo parity
    reference that used to live here was retired in M+1-4 when
    ``returns`` grew nullable ``mute``/``solo`` columns; the device
    chain's missing ``is_active`` column is now the sole remaining
    "schema doesn't model this yet" gap on the per-device-row level.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind=parent_kind, db_id=parent_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"{parent_kind}_devices for {parent_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    devices_in = result.get("devices")
    if devices_in is None:
        out.warnings.append(
            f"{parent_kind}_devices for {parent_id!r}: result missing "
            "'devices' field"
        )
        return

    if parent_kind == "track":
        chains = Q.get_device_chains_for_track(conn, parent_id)
        parent_kwarg = {"parent_track_id": parent_id}
    elif parent_kind == "return":
        chains = Q.get_device_chains_for_return(conn, parent_id)
        parent_kwarg = {"parent_return_id": parent_id}
    else:
        raise ValueError(
            f"_apply_devices_for_parent: unsupported parent_kind {parent_kind!r}"
        )

    top_chain = next((c for c in chains if c["position"] == 0), None)
    if top_chain is None and not devices_in:
        out.no_ops += 1
        return
    if top_chain is None:
        chain_id = M.create_device_chain(
            conn, position=0,
            actor=actor, request_id=request_id, reason=reason,
            **parent_kwarg,
        )
    else:
        chain_id = top_chain["id"]

    db_devices = list(Q.get_devices_for_chain(conn, chain_id))
    db_by_position = {d["position"]: d for d in db_devices}

    seen_positions: set[int] = set()
    for entry in devices_in:
        idx = entry.get("device_index")
        if not isinstance(idx, int) or idx < 1:
            out.warnings.append(
                f"{parent_kind}_devices for {parent_id!r}: entry missing or "
                f"invalid device_index: {entry!r}"
            )
            continue
        kind_in = entry.get("class_name") or ""
        if not kind_in:
            out.warnings.append(
                f"{parent_kind}_devices for {parent_id!r}: device at index "
                f"{idx} missing class_name; skipping"
            )
            continue
        name_in = entry.get("name") or ""
        seen_positions.add(idx)

        existing = db_by_position.get(idx)
        if existing is not None:
            if existing["kind"] == kind_in and existing["display_name"] == name_in:
                out.no_ops += 1
                continue
            # Different device at the same slot — replace. Cascade clears
            # any device_parameters rows; correct for "this slot now holds
            # something else."
            M.delete_device(
                conn, device_id=existing["id"],
                actor=actor, request_id=request_id, reason=reason,
            )
        M.create_device(
            conn,
            chain_id=chain_id,
            position=idx,
            kind=kind_in,
            display_name=name_in,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        if existing is not None:
            out.details.append(
                f"{parent_kind} device pos {idx}: "
                f"{existing['kind']}/{existing['display_name']!r} -> "
                f"{kind_in}/{name_in!r}"
            )
        else:
            out.details.append(
                f"{parent_kind} device pos {idx}: added {kind_in}/{name_in!r}"
            )

    # Removals: any DB row at a position Ableton didn't report. Iterating the
    # pre-mutation snapshot is safe — we never re-process a position we
    # already handled in the create/replace pass above.
    for d in db_devices:
        if d["position"] in seen_positions:
            continue
        M.delete_device(
            conn, device_id=d["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"{parent_kind} device pos {d['position']}: "
            f"removed {d['kind']}/{d['display_name']!r}"
        )


def _apply_arrangement_clips_for_track(
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
    """Diff arrangement-clip placements on one track against the probe payload
    (W3-4 / M+1-3b).

    Identity is positional: matched by `(start_bar, end_bar)` within bar-
    epsilon tolerance. No `update_arrangement` mutator exists; any field
    change becomes delete + add at the new position — parity with
    `_apply_devices_for_parent` for the same "no stable per-element
    identity" reason. Live's `ableton_link` for arrangement rows binds an
    `arrangement_clip_index` but Live re-numbers those on any delete, so
    the index isn't a stable handle for diff matching either.

    Diff classes handled:
      - `(start, end)` in both DB and Ableton  -> no-op
      - `(start, end)` in DB only              -> `remove_arrangement_clip`
      - `(start, end)` in Ableton only         -> warn + skip
      - duplicate `(start, end)` in DB         -> warn + first-row-wins

    Why warn-and-skip on Ableton-only: positional matching cannot tell
    a *new* placement (user drew/duplicated a clip) from a *moved*
    placement (user dragged an existing one). For a new placement, the
    MCP wire shape carries no DB `clip_id` and V1 can't auto-create a
    `clips` row from name + length + start alone. For a move, the
    underlying `clips` row already exists but the apply layer has no way
    to know which DB row Ableton's placement came from. V1 takes no
    action either way; the user mirrors the change in DB and re-runs
    pull on the next pass. The remove `details` line carries the
    removed row's `clip_id` prefix + `clip_name` so the user can
    correlate the two halves of a move case manually.

    Renames not detected: the `arrangement_clips` table has no `name` column;
    display names live on `clips.name`. Manual renames of an arrangement
    clip in Live are silently lost by this apply. The user can rename via
    the DB-side clip name (clips are shared across placements).

    Defense-in-depth link check parallels `_apply_devices_for_parent`.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_arrangement_clips for {track_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    track_row = Q.get_track(conn, track_id)
    if track_row is None:
        out.warnings.append(
            f"track_arrangement_clips:{track_id} — DB row missing; skipping"
        )
        return

    clips_in = result.get("clips")
    if clips_in is None:
        out.warnings.append(
            f"track_arrangement_clips for {track_id!r}: result missing "
            "'clips' field"
        )
        return

    ts_points = Q.get_time_signature_map(conn, song_id)

    # 1/1000 of a bar — same precision as `_apply_cue_points_list`. Finer
    # than any musically meaningful placement.
    def _pos_key(b: float) -> float:
        return round(float(b), 3)

    db_rows = Q.get_arrangement_for_track(conn, track_id)
    # Build a positional lookup; warn on any duplicate (start_bar, end_bar)
    # key because the dict would otherwise silently keep only the last row
    # at that position and the diff would under-report. Exact-coincidence
    # on the same track is rare in practice (Live permits overlap but two
    # placements with identical start AND end bars is a user-authoring
    # oddity); first-row-wins preserves the diff's no-op/remove behavior
    # for the common case.
    db_by_pos: dict[tuple[float, float], sqlite3.Row] = {}
    for r in db_rows:
        k = (_pos_key(r["start_bar"]), _pos_key(r["end_bar"]))
        if k in db_by_pos:
            kept = db_by_pos[k]
            out.warnings.append(
                f"track {track_row['name']!r}: duplicate arrangement-clip "
                f"placements at bar {r['start_bar']:g}..{r['end_bar']:g} "
                f"(keeping arrangement_clip_id={kept['id'][:8]} "
                f"{kept['clip_name']!r}; the collision with "
                f"arrangement_clip_id={r['id'][:8]} {r['clip_name']!r} "
                f"will not round-trip cleanly — separate them or remove one)"
            )
            continue
        db_by_pos[k] = r
    seen: set[tuple[float, float]] = set()

    for entry in clips_in:
        sb_in = entry.get("start_beats")
        len_in = entry.get("length")
        if sb_in is None or len_in is None:
            out.warnings.append(
                f"track_arrangement_clips for {track_id!r}: entry missing "
                f"start_beats or length: {entry!r}"
            )
            continue
        start_bar = _beats_to_position_bar(float(sb_in), ts_points)
        end_bar = _beats_to_position_bar(
            float(sb_in) + float(len_in), ts_points
        )
        k = (_pos_key(start_bar), _pos_key(end_bar))
        seen.add(k)
        if k in db_by_pos:
            out.no_ops += 1
            continue
        # Ableton has a placement at a (start, end) the DB doesn't
        # know about. Could be a brand-new clip OR an existing
        # placement the user moved — positional matching can't tell
        # the two apart. V1 takes no action either way: it doesn't
        # auto-create `clips` rows and doesn't infer moves.
        out.warnings.append(
            f"track {track_row['name']!r}: arrangement clip "
            f"{entry.get('name')!r} at bar {start_bar:g}..{end_bar:g} "
            "has no matching DB placement — V1 does not auto-add. "
            "Mirror the change in DB (add a new placement, or re-add "
            "a moved one) and re-run pull."
        )

    # Removals: DB rows Ableton didn't report. The detail line carries
    # the clip_id prefix + clip_name so the user can correlate against
    # the "Ableton-only placement" warnings above when a placement was
    # moved (positional matching can't infer the move, but the breadcrumb
    # lets the user join the two halves manually).
    for k, row in db_by_pos.items():
        if k in seen:
            continue
        M.remove_arrangement_clip(
            conn, arrangement_clip_id=row["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"track {track_row['name']!r}: arrangement placement at "
            f"bar {row['start_bar']:g}..{row['end_bar']:g} removed "
            f"(arrangement_clip_id={row['id'][:8]} {row['clip_name']!r})"
        )


def _apply_session_clips_for_track(
    conn: sqlite3.Connection,
    *,
    result: dict[str, Any],
    track_id: str,
    song_id: str,
    session_id: str,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff session-view clip-slot contents on one track against the probe
    payload (V1 close-out Chunk C).

    Identity is slot-positional: matched by `clips.slot` (the 1-based
    clip-slot index Ableton calls `clip_index`). Slots are the stablest
    addressing Live exposes for session clips, so the diff is cleaner
    than arrangement-clip's `(start_bar, end_bar)` matching.

    Diff classes handled:
      - slot populated in both DB and Ableton, name + length match -> no-op
      - slot populated in both, name and/or length drift           -> `update_clip` with the drifted fields
      - slot populated in DB only (Ableton slot empty)             -> `delete_clip`
      - slot populated in Ableton only                             -> warn + skip
        (V1 can't auto-create the DB clip from name + length alone;
         note pull would let us fill in content, but distinguishing a
         brand-new session clip from a moved-into-this-slot existing
         clip is the same identity problem as the arrangement case)

    Note content drift is NOT detected here — that's Chunk D's job
    (note pull via stable-ID read). This planner only diffs the
    container-level fields (`name`, `length`) the MCP read action
    returns.

    Defense-in-depth link check parallels `_apply_arrangement_clips_for_track`.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_session_clips for {track_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    track_row = Q.get_track(conn, track_id)
    if track_row is None:
        out.warnings.append(
            f"track_session_clips:{track_id} — DB row missing; skipping"
        )
        return

    clips_in = result.get("clips")
    if clips_in is None:
        out.warnings.append(
            f"track_session_clips for {track_id!r}: result missing "
            "'clips' field"
        )
        return

    db_by_slot: dict[int, sqlite3.Row] = {
        int(c["slot"]): c for c in Q.get_clips_for_track(conn, track_id)
    }
    seen: set[int] = set()

    for entry in clips_in:
        slot_in = entry.get("clip_index")
        if slot_in is None:
            out.warnings.append(
                f"track_session_clips for {track_id!r}: entry missing "
                f"'clip_index': {entry!r}"
            )
            continue
        slot = int(slot_in)
        seen.add(slot)
        empty = bool(entry.get("empty", False))
        db_clip = db_by_slot.get(slot)

        if empty:
            # Ableton slot empty; if DB has a clip, delete it.
            if db_clip is not None:
                M.delete_clip(
                    conn, clip_id=db_clip["id"],
                    actor=actor, request_id=request_id, reason=reason,
                )
                out.mutations += 1
                out.details.append(
                    f"track {track_row['name']!r}: session slot {slot} "
                    f"cleared in Ableton -> deleted DB clip "
                    f"(clip_id={db_clip['id'][:8]} {db_clip['name']!r})"
                )
            else:
                out.no_ops += 1
            continue

        # Ableton slot populated.
        if db_clip is None:
            # Ableton has content the DB doesn't know about. Same V1
            # limitation as the arrangement-clip case: positional
            # matching can't distinguish a brand-new clip from a
            # session-side move, and the MCP wire shape doesn't carry
            # note content for auto-create.
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} has "
                f"clip {entry.get('name')!r} (length {entry.get('length')}) "
                "with no matching DB clip — V1 does not auto-add. "
                "Mirror the change in DB (create the clip + author notes) "
                "and re-run pull."
            )
            continue

        # Both populated -> check for drift.
        changes: dict[str, Any] = {}
        name_in = entry.get("name")
        if name_in is not None and name_in != db_clip["name"]:
            changes["name"] = name_in
        len_in = entry.get("length")
        if _floats_differ(len_in, db_clip["length_beats"]):
            changes["length_beats"] = float(len_in)
        if changes:
            M.update_clip(
                conn, clip_id=db_clip["id"],
                actor=actor, request_id=request_id, reason=reason,
                **changes,
            )
            out.mutations += 1
            out.details.append(
                f"track {track_row['name']!r}: session slot {slot} updated "
                f"(clip_id={db_clip['id'][:8]}): {changes!r}"
            )
        else:
            out.no_ops += 1

    # Slots present in DB but NOT reported by Ableton's dense list:
    # treat as deletion. Ableton's `list` action returns every slot in
    # the track range, so a "missing" slot means we have a DB clip at
    # a slot index past Ableton's known range (the track was shortened
    # in Live, or the DB rows reference indices that no longer exist).
    for slot, db_clip in db_by_slot.items():
        if slot in seen:
            continue
        M.delete_clip(
            conn, clip_id=db_clip["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"track {track_row['name']!r}: session slot {slot} out of "
            f"Ableton range -> deleted DB clip "
            f"(clip_id={db_clip['id'][:8]} {db_clip['name']!r})"
        )


def _apply_notes_for_clip(
    conn: sqlite3.Connection,
    *,
    result: dict[str, Any],
    clip_id: str,
    # song_id is threaded through the dispatcher for parity with sibling
    # apply helpers (which need it for queries like get_time_signature_map);
    # this helper doesn't currently use it. Kept in the signature so the
    # dispatch site doesn't need a special-case branch.
    song_id: str,
    session_id: str,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff notes on one clip against the probe payload (V1 close-out
    Chunk D — gap #4 partial resolution).

    Identity is content-based: each note keys by
    ``(pitch, round(start_beats, 3), round(duration_beats, 3))``. This
    preserves the DB note's UUID across velocity / mute edits (the
    common compose-time iteration), at the cost of treating a note's
    pitch / start / duration change as delete + insert (UUID rotates —
    documented V1 limitation; the DB-side composer can edit by UUID
    if preservation is required).

    Diff classes handled:
      - key in both DB and Ableton, fields match -> no-op
      - key in both, velocity or mute drift     -> `update_note`
      - key in DB only                          -> queued for `delete_notes` (batched)
      - key in Ableton only                     -> queued for `insert_notes` (batched)
      - duplicate key on DB side                -> warn + first-row-wins
        (mirrors `_apply_arrangement_clips_for_track`'s duplicate
         handling; rare but valid — chord voicings rarely produce
         exact pitch/start/duration coincidence but it can happen)

    Note IDs from the Ableton side (``note_id`` field) are NOT
    persisted — Live regenerates them on every write, so they're
    useful only for this single pull pass (e.g. for debug logs).
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"clip_notes for {clip_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    clip_row = Q.get_clip(conn, clip_id)
    if clip_row is None:
        out.warnings.append(
            f"clip_notes:{clip_id} — DB clips row missing; skipping"
        )
        return

    notes_in = result.get("notes")
    if notes_in is None:
        out.warnings.append(
            f"clip_notes for {clip_id!r}: result missing 'notes' field"
        )
        return

    def _key(pitch: int, start: float, duration: float) -> tuple[int, float, float]:
        # 1/1000-beat precision matches the cue-point + arrangement-clip
        # tolerance elsewhere in this module. Finer than any musically
        # meaningful note placement.
        return (int(pitch), round(float(start), 3), round(float(duration), 3))

    db_by_key: dict[tuple[int, float, float], dict[str, Any]] = {}
    for n in Q.get_notes_for_clip(conn, clip_id):
        k = _key(n["pitch"], n["start_beats"], n["duration_beats"])
        if k in db_by_key:
            kept = db_by_key[k]
            out.warnings.append(
                f"clip {clip_row['name']!r}: duplicate notes at "
                f"pitch={k[0]} start={k[1]:g} duration={k[2]:g} "
                f"(keeping note_id={kept['id'][:8]}; collision with "
                f"note_id={n['id'][:8]} will not round-trip cleanly — "
                f"differentiate the duplicates DB-side or accept the "
                f"velocity/mute reading on the keeper)"
            )
            continue
        db_by_key[k] = n
    seen: set[tuple[int, float, float]] = set()
    to_insert: list[dict[str, Any]] = []

    for entry in notes_in:
        pitch_in = entry.get("pitch")
        sb_in = entry.get("start_time")
        dur_in = entry.get("duration")
        if pitch_in is None or sb_in is None or dur_in is None:
            out.warnings.append(
                f"clip_notes for {clip_id!r}: entry missing pitch / "
                f"start_time / duration: {entry!r}"
            )
            continue
        k = _key(int(pitch_in), float(sb_in), float(dur_in))
        if k in seen:
            # Two Ableton-side notes share the same (pitch, start, duration).
            # Both would match the same DB note (or both would insert as
            # the same key), under-reporting the diff. Warn so the user
            # can fix the upstream duplication; first-Ableton-entry wins
            # the match for this pass.
            out.warnings.append(
                f"clip {clip_row['name']!r}: duplicate Ableton notes at "
                f"pitch={k[0]} start={k[1]:g} duration={k[2]:g} "
                f"(first entry kept for diff; subsequent entry "
                f"note_id={entry.get('note_id')!r} ignored — "
                f"differentiate them by start, duration, or pitch)"
            )
            continue
        seen.add(k)
        db_note = db_by_key.get(k)
        if db_note is None:
            # Ableton has a note the DB doesn't — queue insert.
            to_insert.append({
                "pitch": int(pitch_in),
                "start_beats": float(sb_in),
                "duration_beats": float(dur_in),
                "velocity": int(entry.get("velocity", 100)),
                "mute": 1 if bool(entry.get("mute", False)) else 0,
            })
            continue
        # Match found — check for velocity / mute drift.
        changes: dict[str, Any] = {}
        vel_in = entry.get("velocity")
        if vel_in is not None and int(vel_in) != int(db_note["velocity"]):
            changes["velocity"] = int(vel_in)
        mute_in = entry.get("mute")
        if mute_in is not None:
            mute_db = bool(db_note["mute"])
            if bool(mute_in) != mute_db:
                changes["mute"] = 1 if bool(mute_in) else 0
        if changes:
            M.update_note(
                conn, note_id=db_note["id"],
                actor=actor, request_id=request_id, reason=reason,
                **changes,
            )
            out.mutations += 1
            out.details.append(
                f"clip {clip_row['name']!r}: note "
                f"pitch={k[0]} start={k[1]:g} updated "
                f"(note_id={db_note['id'][:8]}): {changes!r}"
            )
        else:
            out.no_ops += 1

    # Batch insert: one event with all new notes.
    if to_insert:
        new_ids = M.insert_notes(
            conn, clip_id=clip_id, notes=to_insert,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"clip {clip_row['name']!r}: inserted "
            f"{len(new_ids)} note(s) from Ableton-only positions"
        )

    # Batch delete: DB notes whose key Ableton didn't report.
    to_delete = [
        db_note["id"]
        for k, db_note in db_by_key.items()
        if k not in seen
    ]
    if to_delete:
        M.delete_notes(
            conn, note_ids=to_delete,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"clip {clip_row['name']!r}: deleted "
            f"{len(to_delete)} DB note(s) absent from Ableton"
        )


# Dispatch table: key kind -> (handler, expects-db-id)
_HANDLERS = {
    "session_info":              ("session_info",              False),
    "returns_list":              ("returns_list",              False),
    "return_info":               ("return_info",               True),   # Wave M-2: per-return mixer state
    "track_info":                ("track_info",                True),
    "track_sends":               ("track_sends",               True),
    "cue_points_list":           ("cue_points_list",           False),
    "track_devices":             ("track_devices",             True),   # W3-3: top-level chain
    "return_devices":            ("return_devices",            True),   # W3-3: top-level chain
    "track_arrangement_clips":   ("track_arrangement_clips",   True),   # M+1-3b / W3-4
    "track_session_clips":       ("track_session_clips",       True),   # V1 close-out C
    "clip_notes":                ("clip_notes",                True),   # V1 close-out D — gap #4 partial
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
            elif handler_name == "track_devices":
                _apply_devices_for_parent(
                    conn, session_id=session_id,
                    parent_kind="track", parent_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "return_devices":
                _apply_devices_for_parent(
                    conn, session_id=session_id,
                    parent_kind="return", parent_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_arrangement_clips":
                _apply_arrangement_clips_for_track(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_session_clips":
                _apply_session_clips_for_track(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "clip_notes":
                _apply_notes_for_clip(
                    conn, song_id=song_id, session_id=session_id,
                    clip_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )

    return out
