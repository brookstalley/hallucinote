"""Envelope pull (W7-A) — planner, per-kind read-addressing emitters, and apply.

The pull-side mirror of `plan_push_envelopes`. The push side iterates DB
`envelopes` rows and emits one `write_envelope` ToolCall per envelope; pull
does the same, emitting one `read_envelope` PullCall per DB envelope. Per-
kind addressing matches push exactly (note_expression by note pitch+start,
device_parameter via covering session-clip + device, mixer/send via covering
session-clip on the target track).

**Skip symmetry with push is load-bearing**: when push would skip an
envelope with a warn (no covering placement, unlinked target, nested-rack
device, return-side device_parameter, clip_cc/clip_pitch_bend LOM gap), the
pull-side MUST also skip — otherwise reading a never-pushed envelope would
return `exists=False`, and the apply path would delete the DB row that
represents the user's authored intent. The same skip-with-warn shape is the
right behavior for both halves: "we have no Live-side wire for this DB row."

Existence detection follows W6-G/H's contract: `exists=False` means Live
has ≤1 distinct sample across the clip's range — no real envelope. When
`exists=True` but breakpoints match the DB within tolerance (modulo curve),
it's a no-op; when breakpoints differ, the merged result is committed via
`M.replace_breakpoints` (atomic). When `exists=False`, the envelope is
deleted from the DB via `M.delete_envelope` (cascades breakpoints).

Curve preservation: Live 12.4 returns every breakpoint as `curve='hold'`
because `Envelope.insert_step` is the only API exposed (W6-C). On read, we
match each Live breakpoint to a DB breakpoint by (time within tolerance,
value within tolerance). If matched, the DB's `curve_kind` is preserved
(linear/fast/slow intent recorded in the DB survives the round-trip). If
only time matches (value differs), Live overwrote the value — the new
breakpoint inherits `curve='hold'` because Live can't tell us otherwise.
This rule prevents pull churn on songs whose DB-authored envelopes carry
non-hold curves that push has already warned about being lossy (W5-E).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

# Cross-module address-resolution reuse: pull's per-envelope read addressing
# mirrors push's per-envelope write addressing (covering session-clip lookup,
# clip-local time translation). These helpers are direction-neutral, so they
# live in the leaf `sync.geometry` module that both push and pull import from —
# pull no longer reaches into push for them. Any change to the covering-placement
# geometry applies to both halves automatically, keeping pull and push exactly
# symmetric on routing semantics.
from ..geometry import (
    _envelope_beat_range,
    _resolve_envelope_session_clip,
)

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _FLOAT_EPS,
)


# Time-match tolerance for envelope diff. read_envelope samples at
# `resolution_beats` (default 1/96 beat); a step transition can land anywhere
# within that window. Tolerance is the sampling resolution + a small float
# slack so we don't churn on Live's quantum. The apply path reads the actual
# resolution from the response and scales tolerance accordingly.
_ENVELOPE_TIME_EPS_SLACK = _FLOAT_EPS

# Value-match tolerance for envelope diff. Same scale as device-parameter
# diffing — Live's display rounding is ~0.1% of full range.
_ENVELOPE_VALUE_EPS = _FLOAT_EPS

# clip_cc / clip_pitch_bend are LOM-gap-blocked on both the write and read
# sides (W6-G handler raises NotImplementedError). Pull skips them with the
# same shape as push.
_ENVELOPE_KINDS_READ_BLOCKED = frozenset({"clip_cc", "clip_pitch_bend"})


def plan_pull_envelopes(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan the pull of every envelope in a song. One read_envelope per
    DB envelope (W7-A — closes the round-trip gap left by W5-E's warn-only
    push behavior).

    Iterates DB envelopes rather than enumerating Live-side surfaces, so
    this is a *round-trip* pull: it catches user-edits to envelopes that
    already exist in the DB. Discovering envelopes authored only in Live
    is a backlog item — would require enumerating every linked clip ×
    target_kind, every linked device parameter, etc., which explodes
    the call surface.

    Skip-with-warn (symmetric with `plan_push_envelopes`):
      - `clip_cc` / `clip_pitch_bend`: read_envelope_handler raises
        NotImplementedError for these kinds (Live 12.4 LOM gap).
      - Unlinked target / clip / device / track / return.
      - No covering arrangement_clip placement for the envelope's beat
        range (mixer / send / device_parameter need session-clip routing).
      - Nested-rack device_parameter (W6-I/J shipped probe but pull
        routing still flat — W7-B unblocks).
      - Return-side device_parameter (no return-clip schema in DB).
    """
    plan = PullPlan()
    envelopes = Q.get_envelopes_for_song(conn, song_id)
    if not envelopes:
        plan.warn("no envelopes for this song; nothing to pull")
        return plan

    for env in envelopes:
        kind = env["target_kind"]
        if kind in _ENVELOPE_KINDS_READ_BLOCKED:
            plan.warn(
                f"envelope {env['id']} ({kind}): Live 12.4 LOM doesn't "
                "expose envelope read for MIDI CC / pitch-bend targets; "
                "skipping pull (symmetric with push)"
            )
            continue

        if kind == "note_expression":
            _emit_pull_note_expression(plan, conn, session_id=session_id, envelope=env)
        elif kind == "device_parameter":
            _emit_pull_device_parameter(
                plan, conn, song_id=song_id, session_id=session_id, envelope=env,
            )
        elif kind in ("mixer_volume", "mixer_pan"):
            _emit_pull_mixer(
                plan, conn, song_id=song_id, session_id=session_id, envelope=env,
            )
        elif kind == "send_level":
            _emit_pull_send(
                plan, conn, song_id=song_id, session_id=session_id, envelope=env,
            )
        else:
            # Belt-and-suspenders — schema CHECK already constrains target_kind.
            raise ValueError(
                f"plan_pull_envelopes: target_kind {kind!r} has no emitter "
                "branch — add one alongside the schema entry"
            )
    return plan


def _emit_pull_note_expression(
    plan: PullPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
) -> None:
    """Refuse a note_expression row at plan time — there is nothing to read.

    Mirrors push. Live's Python API exposes no per-note expression surface
    under any name, so no envelope of this kind can exist in Live to be read
    back; the read this used to emit is refused at the MCP boundary. A row
    reaching here comes from a DB predating that.
    """
    plan.warn(
        f"envelope {envelope['id']} (note_expression): Live's Python API has "
        "no per-note expression surface under any name, so there is no "
        "envelope in Live to read back; skipping. Drop the row from build.py."
    )


def _emit_pull_device_parameter(
    plan: PullPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
) -> None:
    """device_parameter read addressing — mirrors push (session-clip routed
    on Live 12.4; return-side and nested-rack still gap-blocked)."""
    device_id = envelope["target_device_id"]
    device_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device_id,
    )
    chain_row = conn.execute(
        """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE d.id = ?""",
        (device_id,),
    ).fetchone()
    if chain_row is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): device "
            f"{device_id} not found; skipping"
        )
        return
    if chain_row["parent_rack_device_id"] is not None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): nested-rack "
            f"device {device_id} — pull not yet routed (W7-B closes capture; "
            "pull-side ingest in same chunk)"
        )
        return
    if chain_row["parent_return_id"] is not None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): return-side "
            f"device {device_id} — Live 12.4 requires session-clip routing "
            "for device_parameter envelopes, but DB has no return-side "
            "session-clip model; skipping (symmetric with push)"
        )
        return
    parent_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track",
        db_id=chain_row["parent_track_id"],
    )
    if parent_at is None or device_at is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): track or "
            f"device not linked (track={parent_at}, device={device_at}); "
            "skipping"
        )
        return
    breakpoints = Q.get_breakpoints(conn, envelope["id"])
    if not breakpoints:
        # No DB breakpoints means push would have skipped this row, so Live
        # has nothing to read back. Don't emit — and don't warn (an envelope
        # row with zero breakpoints is a no-op on push by design).
        return
    bps_mcp = [
        {"time_beats": float(bp["time_beats"]), "value": float(bp["value"])}
        for bp in breakpoints
    ]
    env_min, env_max = _envelope_beat_range(bps_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=chain_row["parent_track_id"],
        env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): no arrangement "
            f"clip on track {parent_at} covers beat range [{env_min:g}, "
            f"{env_max:g}]; symmetric skip with push (no session-clip route)"
        )
        return
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=placement.clip_id,
    )
    if clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): session clip "
            f"{placement.clip_id} (covering placement) not linked; skipping"
        )
        return
    plan.add(PullCall(
        tool="ableton_automation",
        args={
            "action": "read_envelope",
            "target_kind": "device_parameter",
            "track_index": parent_at,
            "location": "session",
            "clip_index": clip_at,
            "device_index": device_at,
            "parameter_name": envelope["parameter_path"],
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"pull device_parameter {envelope['parameter_path']} on track "
            f"{parent_at} session clip {clip_at} (offset {placement.start_beats:g})"
        ),
    ))


def _emit_pull_mixer(
    plan: PullPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
) -> None:
    """mixer_volume / mixer_pan read addressing — session-clip routed."""
    track_id = envelope["target_track_id"]
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    )
    if track_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): track "
            f"{track_id} not linked; skipping"
        )
        return
    breakpoints = Q.get_breakpoints(conn, envelope["id"])
    if not breakpoints:
        return
    bps_mcp = [
        {"time_beats": float(bp["time_beats"]), "value": float(bp["value"])}
        for bp in breakpoints
    ]
    env_min, env_max = _envelope_beat_range(bps_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=track_id, env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): no "
            f"arrangement clip on track {track_at} covers beat range "
            f"[{env_min:g}, {env_max:g}]; symmetric skip with push"
        )
        return
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=placement.clip_id,
    )
    if clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): session "
            f"clip {placement.clip_id} (covering placement) not linked; skipping"
        )
        return
    plan.add(PullCall(
        tool="ableton_automation",
        args={
            "action": "read_envelope",
            "target_kind": envelope["target_kind"],
            "track_index": track_at,
            "location": "session",
            "clip_index": clip_at,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"pull {envelope['target_kind']} on track {track_at} "
            f"session clip {clip_at} (offset {placement.start_beats:g})"
        ),
    ))


def _emit_pull_send(
    plan: PullPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
) -> None:
    """send_level read addressing — session-clip routed, return_index
    identifies destination."""
    track_id = envelope["target_track_id"]
    return_id = envelope["target_send_return_id"]
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    )
    return_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="return", db_id=return_id,
    )
    if track_at is None or return_at is None:
        plan.warn(
            f"envelope {envelope['id']} (send_level): track or return not "
            f"linked (track={track_at}, return={return_at}); skipping"
        )
        return
    breakpoints = Q.get_breakpoints(conn, envelope["id"])
    if not breakpoints:
        return
    bps_mcp = [
        {"time_beats": float(bp["time_beats"]), "value": float(bp["value"])}
        for bp in breakpoints
    ]
    env_min, env_max = _envelope_beat_range(bps_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=track_id, env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} (send_level): no arrangement clip "
            f"on track {track_at} covers beat range [{env_min:g}, "
            f"{env_max:g}]; symmetric skip with push"
        )
        return
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=placement.clip_id,
    )
    if clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} (send_level): session clip "
            f"{placement.clip_id} (covering placement) not linked; skipping"
        )
        return
    plan.add(PullCall(
        tool="ableton_automation",
        args={
            "action": "read_envelope",
            "target_kind": "send_level",
            "track_index": track_at,
            "return_index": return_at,
            "location": "session",
            "clip_index": clip_at,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"pull send_level on track {track_at} → return {return_at} "
            f"session clip {clip_at} (offset {placement.start_beats:g})"
        ),
    ))


# Envelope-specific time-translation: pull responses come back in clip-local
# beats for envelopes that push routed through a session clip (mixer / send /
# device_parameter). The DB stores those breakpoints in arrangement-time, so
# the apply layer translates clip-local → arrangement-time by adding the
# placement's offset before diffing. note_expression breakpoints are clip-
# local on both sides; no translation needed.
def _envelope_needs_arrangement_translation(target_kind: str) -> bool:
    return target_kind in (
        "device_parameter", "mixer_volume", "mixer_pan", "send_level",
    )


def _arrangement_time_breakpoints(
    live_bps: list[dict[str, Any]],
    *,
    offset_beats: float,
) -> list[dict[str, Any]]:
    """Translate Live's clip-local breakpoint times to DB arrangement-time
    by adding the covering placement's offset. Inverse of push.py's
    `_clip_local_breakpoints`."""
    return [
        {**bp, "time_beats": float(bp["time_beats"]) + offset_beats}
        for bp in live_bps
    ]


def _resolve_envelope_offset(
    conn: sqlite3.Connection,
    *,
    envelope: sqlite3.Row,
    song_id: str,
) -> float | None:
    """Recompute the placement offset for an envelope's covering session clip.
    Mirrors the lookup the planner did when emitting the read; if the
    placement disappeared between plan and apply, return None so the apply
    layer can warn-skip rather than mutate against stale routing."""
    if envelope["target_kind"] == "device_parameter":
        chain_row = conn.execute(
            """SELECT dc.parent_track_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (envelope["target_device_id"],),
        ).fetchone()
        if chain_row is None or chain_row["parent_track_id"] is None:
            return None
        target_track_id = chain_row["parent_track_id"]
    else:  # mixer_volume / mixer_pan / send_level
        target_track_id = envelope["target_track_id"]
    breakpoints = Q.get_breakpoints(conn, envelope["id"])
    if not breakpoints:
        return None
    bps_mcp = [
        {"time_beats": float(bp["time_beats"]), "value": float(bp["value"])}
        for bp in breakpoints
    ]
    env_min, env_max = _envelope_beat_range(bps_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=target_track_id, env_min=env_min, env_max=env_max,
    )
    return placement.start_beats if placement is not None else None


def _merge_envelope_breakpoints(
    db_bps: list[sqlite3.Row],
    live_bps: list[dict[str, Any]],
    *,
    time_eps: float,
    value_eps: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Compute the merged breakpoint set under V1 conflict policy
    (Ableton-authoritative) with curve preservation.

    For each Live breakpoint, find the closest DB breakpoint by time
    within `time_eps`:
      - matched + value within `value_eps`  -> inherit DB's curve_kind
      - matched + value differs              -> Live overwrote; curve='hold'
      - unmatched                            -> new in Live; curve='hold'

    DB breakpoints that no Live breakpoint matched are dropped (Live
    removed them).

    Returns `(merged_bps, changed)` where `changed` is True iff the merged
    set differs from `db_bps` (length, ordering, or any per-bp field).

    `merged_bps` is in {time_beats, value, curve_kind} dict shape ready
    to pass to `M.replace_breakpoints`.

    Each DB breakpoint can match at most one Live breakpoint (smallest
    time delta wins on ties), so a stretched-Live timeline doesn't
    inflate apparent matches.
    """
    db_used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for lbp in live_bps:
        t_live = float(lbp["time_beats"])
        v_live = float(lbp["value"])
        best_idx: int | None = None
        best_dt = float("inf")
        for i, dbp in enumerate(db_bps):
            if i in db_used:
                continue
            dt = abs(float(dbp["time_beats"]) - t_live)
            if dt <= time_eps and dt < best_dt:
                best_dt = dt
                best_idx = i
        if best_idx is not None:
            db_used.add(best_idx)
            dbp = db_bps[best_idx]
            value_match = abs(float(dbp["value"]) - v_live) <= value_eps
            curve = dbp["curve_kind"] if value_match else "hold"
            merged.append({
                "time_beats": t_live,
                "value": v_live,
                "curve_kind": curve,
            })
        else:
            merged.append({
                "time_beats": t_live,
                "value": v_live,
                "curve_kind": "hold",
            })

    # Detect change: count mismatch or any field difference. Use the
    # same epsilon scales as the per-breakpoint matching above — time
    # comparisons use `time_eps` (sampling resolution + slack), not the
    # tighter `value_eps`, so Live's quantum doesn't churn a no-op into
    # a write on every pull.
    changed = len(merged) != len(db_bps)
    if not changed:
        for m, dbp in zip(merged, db_bps):
            if (
                abs(m["time_beats"] - float(dbp["time_beats"])) > time_eps
                or abs(m["value"] - float(dbp["value"])) > value_eps
                or m["curve_kind"] != dbp["curve_kind"]
            ):
                changed = True
                break
    return merged, changed


def _apply_envelope(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    song_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff a single envelope's Live state against the DB; mutate to converge
    (Ableton-authoritative under V1 conflict policy).

    Three diff outcomes:
      - `exists=False` -> Live has no envelope here; delete the DB row.
      - `exists=True`, breakpoints match within tolerance -> no-op (curve
        preservation lets DB-side `linear`/`fast`/`slow` curves stay even
        though Live reports them as `hold`).
      - `exists=True`, breakpoints differ -> atomic `replace_breakpoints`
        with the merged set (curve preservation for matched, `hold` for
        new/changed-value).
    """
    envelope = Q.get_envelope(conn, envelope_id)
    if envelope is None:
        out.warnings.append(
            f"envelope {envelope_id!r}: DB row not found; skipping "
            "(envelope deleted between plan and apply?)"
        )
        return

    live_bps = result.get("breakpoints")
    if not isinstance(live_bps, list):
        out.warnings.append(
            f"envelope {envelope_id!r} ({envelope['target_kind']}): result "
            "missing 'breakpoints' field; skipping"
        )
        return
    # Delete-gate: an envelope is "absent in Live" iff the read returned ZERO
    # breakpoints. The handler's `exists` field is informational and uses a
    # `len > 1` heuristic that can't distinguish (a) "no envelope ever bound"
    # (Live default sample at t=0) from (b) "single-breakpoint envelope held
    # at a constant value" — both yield exactly one sampled breakpoint. Trusting
    # `exists` for the delete decision would round-trip-delete case (b)
    # (W7-0 cumulative-Critic warning 2026-05-19).
    resolution = float(result.get("resolution_beats", 1.0 / 96.0))
    # Tolerance derived from the actual sampling resolution Live used —
    # transitions can localize anywhere within that window. Slack added on
    # top to absorb display rounding.
    time_eps = resolution + _ENVELOPE_TIME_EPS_SLACK

    db_bps = Q.get_breakpoints(conn, envelope_id)

    if not live_bps:
        # Live reports no envelope here. If the DB row has breakpoints
        # (representing the user's authored intent), it means the user
        # removed the envelope in Live. Cascade-delete the DB row.
        if db_bps:
            M.delete_envelope(
                conn, envelope_id=envelope_id,
                actor=actor, request_id=request_id, reason=reason,
            )
            out.mutations += 1
            out.details.append(
                f"envelope {envelope_id[:8]} ({envelope['target_kind']}): "
                f"removed (Live reports no envelope; {len(db_bps)} DB "
                "breakpoint(s) cascaded)"
            )
        else:
            # DB row exists but already empty; Live agrees. No-op.
            out.no_ops += 1
        return

    # Translate clip-local Live times back to arrangement-time for kinds
    # that push routes through a session clip.
    if _envelope_needs_arrangement_translation(envelope["target_kind"]):
        offset = _resolve_envelope_offset(
            conn, envelope=envelope, song_id=song_id,
        )
        if offset is None:
            out.warnings.append(
                f"envelope {envelope_id!r} ({envelope['target_kind']}): "
                "covering session-clip placement no longer resolves; "
                "skipping (re-run pull after re-pushing arrangement)"
            )
            return
        live_bps_arrangement = _arrangement_time_breakpoints(
            live_bps, offset_beats=offset,
        )
    else:
        # note_expression — clip-local on both sides.
        live_bps_arrangement = [
            {"time_beats": float(bp["time_beats"]), "value": float(bp["value"])}
            for bp in live_bps
        ]

    merged, changed = _merge_envelope_breakpoints(
        db_bps, live_bps_arrangement,
        time_eps=time_eps, value_eps=_ENVELOPE_VALUE_EPS,
    )
    if not changed:
        out.no_ops += 1
        return

    M.replace_breakpoints(
        conn, envelope_id=envelope_id, breakpoints=merged,
        actor=actor, request_id=request_id, reason=reason,
    )
    out.mutations += 1
    out.details.append(
        f"envelope {envelope_id[:8]} ({envelope['target_kind']}): "
        f"breakpoints replaced ({len(db_bps)} -> {len(merged)})"
    )


__all__ = [
    "_ENVELOPE_TIME_EPS_SLACK",
    "_ENVELOPE_VALUE_EPS",
    "_ENVELOPE_KINDS_READ_BLOCKED",
    "plan_pull_envelopes",
    "_emit_pull_note_expression",
    "_emit_pull_device_parameter",
    "_emit_pull_mixer",
    "_emit_pull_send",
    "_envelope_needs_arrangement_translation",
    "_arrangement_time_breakpoints",
    "_resolve_envelope_offset",
    "_merge_envelope_breakpoints",
    "_apply_envelope",
]
