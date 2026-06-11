"""Performed-automation push phase (ENV-7G4K).

Master/group/return-side envelopes can't ride session clips; this phase
gesture-records them into Live's arrangement automation via
``ableton_automation(action='perform')``. The surface is write-only (no
LOM read of arrangement automation), so the phase is fingerprint-gated:
an arc is performed only when its authored fingerprint (target
addressing + parameter_path + ordered breakpoints) differs from the one
recorded at the last successful perform (``performed_automation`` table).

Visible Costs (design.md decision 2): performing is realtime — the
transport PLAYS each arc's span, so every emitted call names its
estimated wall-clock (span integrated across the authored tempo map)
and the plan summary totals it. Skipped-unchanged arcs are listed, not
silent.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

from ..geometry import _position_bar_to_beats
from ._core import (
    PushPlan,
    ToolCall,
    _breakpoints_for_mcp,
)
from .envelopes import classify_envelope_route

_DEFAULT_BPM = 120.0


def _tempo_segments(
    conn: sqlite3.Connection, song_id: str,
) -> list[tuple[float, float]]:
    """Tempo map as [(start_beats, bpm), ...] sorted by start. Empty map →
    a single 120 BPM segment (Live's default for an untouched set)."""
    ts_points = Q.get_time_signature_map(conn, song_id)
    rows = Q.get_tempo_map(conn, song_id)
    segs = [
        (_position_bar_to_beats(float(r["start_bar"]), ts_points),
         float(r["tempo_bpm"]))
        for r in rows
    ]
    segs.sort()
    return segs or [(0.0, _DEFAULT_BPM)]


def _estimate_span_seconds(
    segments: list[tuple[float, float]], start_beats: float, end_beats: float,
) -> float:
    """Integrate beats→seconds across tempo segments.

    Uses the AUTHORED tempo map — the declared intent. (Push can only set
    the bar-1 global tempo — W6-F — so a multi-segment map assumes the
    operator drew the matching tempo automation in Live by hand; the
    estimate stays honest to the authored timeline either way.)
    """
    total = 0.0
    for i, (seg_start, bpm) in enumerate(segments):
        seg_end = (
            segments[i + 1][0] if i + 1 < len(segments) else float("inf")
        )
        lo = max(start_beats, seg_start)
        hi = min(end_beats, seg_end)
        if hi > lo:
            total += (hi - lo) * 60.0 / bpm
    # Span entirely before the first segment (defensive): bill it at the
    # first segment's tempo.
    first_start, first_bpm = segments[0]
    if start_beats < first_start:
        total += (min(end_beats, first_start) - start_beats) * 60.0 / first_bpm
    return total


def _arc_addressing(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
) -> tuple[dict[str, Any], str] | None:
    """Resolve an eligible envelope to (wire args fragment, human label).

    Returns None after warning when a required link is missing — the arc
    stays pending and the next push retries (never a silent skip).
    """
    kind = envelope["target_kind"]
    env_id = envelope["id"]

    if kind in ("return_mixer_volume", "return_mixer_pan"):
        return_id = envelope["target_send_return_id"]
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=return_id,
        )
        if return_at is None:
            plan.warn(
                f"perform {env_id} ({kind}): return {return_id} not linked; "
                "arc pending (next push retries)"
            )
            return None
        ret_row = Q.get_return(conn, return_id)
        label = f"return {ret_row['name'] if ret_row else return_at} " + (
            "volume" if kind == "return_mixer_volume" else "pan"
        )
        wire_kind = (
            "mixer_volume" if kind == "return_mixer_volume" else "mixer_pan"
        )
        return {"target_kind": wire_kind, "return_index": return_at}, label

    if kind in ("mixer_volume", "mixer_pan", "send_level"):
        track_id = envelope["target_track_id"]
        track_row = Q.get_track(conn, track_id)
        if track_row is None:
            plan.warn(
                f"perform {env_id} ({kind}): track {track_id} not found; "
                "arc pending"
            )
            return None
        args: dict[str, Any] = {"target_kind": kind}
        if track_row["kind"] == "master":
            args["master"] = True
            label = f"master {kind.removeprefix('mixer_')}"
        else:
            track_at = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="track", db_id=track_id,
            )
            if track_at is None:
                plan.warn(
                    f"perform {env_id} ({kind}): track {track_id} "
                    f"({track_row['name']}) not linked; arc pending "
                    "(group tracks are not push-creatable — probe-and-link "
                    "an existing group)"
                )
                return None
            args["track_index"] = track_at
            label = f"{track_row['name']} {kind.removeprefix('mixer_')}"
        if kind == "send_level":
            return_at = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="return",
                db_id=envelope["target_send_return_id"],
            )
            if return_at is None:
                plan.warn(
                    f"perform {env_id} (send_level): return "
                    f"{envelope['target_send_return_id']} not linked; "
                    "arc pending"
                )
                return None
            args["return_index"] = return_at
            label = f"{label} -> return {return_at}"
        return args, label

    if kind == "device_parameter":
        device_id = envelope["target_device_id"]
        device_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="device", db_id=device_id,
        )
        if device_at is None:
            plan.warn(
                f"perform {env_id} (device_parameter): device {device_id} "
                "not linked; arc pending (master-chain devices are placed "
                "manually — run probe-and-link after placing)"
            )
            return None
        chain_row = Q.get_device_parent_chain(conn, device_id)
        if chain_row is None:
            plan.warn(
                f"perform {env_id} (device_parameter): device {device_id} "
                "has no chain row; arc pending"
            )
            return None
        args = {
            "target_kind": "device_parameter",
            "device_index": device_at,
            "parameter_name": envelope["parameter_path"],
        }
        if chain_row["parent_return_id"] is not None:
            return_at = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="return",
                db_id=chain_row["parent_return_id"],
            )
            if return_at is None:
                plan.warn(
                    f"perform {env_id} (device_parameter): return "
                    f"{chain_row['parent_return_id']} not linked; arc pending"
                )
                return None
            args["return_index"] = return_at
            label = f"return {return_at} device {device_at} {envelope['parameter_path']}"
        else:
            track_row = Q.get_track(conn, chain_row["parent_track_id"])
            if track_row is not None and track_row["kind"] == "master":
                args["master"] = True
                label = f"master device {device_at} {envelope['parameter_path']}"
            else:
                track_at = Q.get_ableton_link(
                    conn, session_id=session_id, db_kind="track",
                    db_id=chain_row["parent_track_id"],
                )
                if track_at is None:
                    plan.warn(
                        f"perform {env_id} (device_parameter): track "
                        f"{chain_row['parent_track_id']} not linked; "
                        "arc pending"
                    )
                    return None
                args["track_index"] = track_at
                label = (
                    f"{track_row['name'] if track_row else track_at} device "
                    f"{device_at} {envelope['parameter_path']}"
                )
        return args, label

    # classify said 'perform' for a kind this resolver doesn't know —
    # contract drift between the two functions.
    raise ValueError(
        f"perform addressing has no branch for target_kind {kind!r}; "
        "update _arc_addressing alongside classify_envelope_route"
    )


def envelope_fingerprint(
    envelope: sqlite3.Row, breakpoints: list[sqlite3.Row],
) -> str:
    """The arc's content fingerprint from its DB rows (shared by the
    planner's gate and the apply layer's success recording)."""
    return M.performed_automation_fingerprint(
        target_kind=envelope["target_kind"],
        target_track_id=envelope["target_track_id"],
        target_device_id=envelope["target_device_id"],
        target_send_return_id=envelope["target_send_return_id"],
        parameter_path=envelope["parameter_path"],
        breakpoints=breakpoints,
    )


def plan_push_performed_automation(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the perform pass: one ``ableton_automation(action='perform')``
    call per perform-routed envelope whose fingerprint changed since the
    last successful perform. Unchanged arcs are listed as skipped.

    Every emitted call's purpose names the arc and its estimated
    wall-clock; the summary note states the transport will play and
    totals the cost (Visible Costs).
    """
    plan = PushPlan()
    envelopes = Q.get_envelopes_for_song(conn, song_id)
    eligible = [
        env for env in envelopes
        if classify_envelope_route(conn, env) == "perform"
    ]
    if not eligible:
        plan.warn("no perform-routed envelopes for this song; nothing to perform")
        return plan

    segments = _tempo_segments(conn, song_id)
    total_seconds = 0.0
    skipped: list[str] = []

    for env in eligible:
        breakpoints = Q.get_breakpoints(conn, env["id"])
        if not breakpoints:
            plan.warn(
                f"perform {env['id']} ({env['target_kind']}) has no "
                "breakpoints; skipping"
            )
            continue
        span_start = float(breakpoints[0]["time_beats"])
        span_end = float(breakpoints[-1]["time_beats"])
        if span_end <= span_start:
            plan.warn(
                f"perform {env['id']} ({env['target_kind']}): span is empty "
                f"({span_start:g}..{span_end:g}) — a single-point arc is a "
                "static value, not an automation ride; dial the parameter "
                "instead. Skipping."
            )
            continue

        addressing = _arc_addressing(
            plan, conn, session_id=session_id, envelope=env,
        )
        if addressing is None:
            continue
        args, label = addressing

        fingerprint = envelope_fingerprint(env, breakpoints)
        performed = Q.get_performed_automation(conn, env["id"], session_id)
        if performed is not None and performed["fingerprint"] == fingerprint:
            skipped.append(label)
            continue

        seconds = _estimate_span_seconds(segments, span_start, span_end)
        total_seconds += seconds
        plan.add(ToolCall(
            tool="ableton_automation",
            args={
                "action": "perform",
                **args,
                "breakpoints": _breakpoints_for_mcp(breakpoints),
            },
            key=f"perform:{env['id']}",
            purpose=(
                f"perform {label}: beats {span_start:g}-{span_end:g} "
                f"(~{seconds:.1f}s transport playback), "
                f"{len(breakpoints)} breakpoint(s)"
            ),
        ))

    if plan.calls:
        plan.warn(
            f"performed-automation: {len(plan.calls)} arc(s) to perform — "
            f"the transport WILL PLAY for ~{total_seconds:.1f}s total "
            f"(realtime gesture recording); {len(skipped)} unchanged arc(s) "
            "skipped"
        )
    for label in skipped:
        plan.warn(f"performed-automation: skipped (unchanged): {label}")
    return plan


def record_perform_result(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    session_id: str,
    result: dict[str, Any],
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> str | None:
    """Apply-layer hook for a successful ``perform:`` result. Records the
    performed-state fingerprint for this (envelope, session) ONLY when the
    handler verified the write (``automation_state == 1``); anything else
    leaves the fingerprint unwritten so the next push retries the arc.
    Returns None when state was recorded, else a human-readable warning
    naming the arc and why — the caller surfaces it (never a silent skip).

    The fingerprint is recomputed from current DB rows — identical to the
    planner's within one plan→execute→apply cycle, and self-healing if
    the arc was edited mid-cycle (the stored print then reflects neither
    old nor new Live state, forcing a re-perform next push).
    """
    state = result.get("automation_state")
    if state != 1:
        return (
            f"perform {envelope_id}: handler returned "
            f"automation_state={state!r} (not 1 — the write is unverified); "
            "fingerprint left unwritten, the next push retries this arc. "
            "If it never verifies, check the parameter isn't "
            "automation-overridden or locked in Live."
        )
    env = Q.get_envelope(conn, envelope_id)
    if env is None:
        return (
            f"perform {envelope_id}: envelope no longer exists in the DB "
            "(deleted mid-cycle?); performed state not recorded."
        )
    M.record_performed_automation(
        conn,
        envelope_id=envelope_id,
        session_id=session_id,
        fingerprint=envelope_fingerprint(env, Q.get_breakpoints(conn, envelope_id)),
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return None
