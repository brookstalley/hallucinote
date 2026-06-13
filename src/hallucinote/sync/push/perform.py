"""Performed-automation push phase (ENV-7G4K; ENV-9P4T single-pass batch).

Master/group/return-side envelopes can't ride session clips; this phase
gesture-records them into Live's arrangement automation via ONE
``ableton_automation(action='perform_batch')`` call that records every
changed arc in a single transport pass (per-parameter gesture windowing).
The surface is write-only (no LOM read of arrangement automation), so the
phase is fingerprint-gated: an arc enters the batch only when its authored
fingerprint (target addressing + parameter_path + ordered breakpoints)
differs from the one recorded at the last successful perform
(``performed_automation`` table). Gating is data-safety as well as speed —
an unchanged arc is never re-recorded, so a hand-edited Live lane survives.

Visible Costs (design.md decision 2): performing is realtime — the
transport PLAYS once over the UNION span of the changed arcs, so the
batched call names that union-span wall-clock (integrated across the
authored tempo map) and a loud ``alert()`` enumerates every span the pass
will record/overwrite. Skipped-unchanged arcs are listed, not silent.
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

# Client-side read ceiling for the perform_batch wire call (ENV-8K2R #5). The
# read-timeout POLICY leaves perform_batch unbounded on purpose — a fixed socket
# timeout would sever the per-arc ``automation_state`` verification this
# write-only surface depends on. But a worker that dies mid-pass while the TCP
# socket stays open would block ``push_cli`` forever, so the planner derives a
# ceiling from the union-span realtime estimate it already computes. The bound
# must comfortably clear the HANDLER's own wall-clock budget
# (≈ union_seconds × _PERFORM_WALL_CLOCK_FACTOR(3) + a 10s floor + ~2× the
# record-settle + the post-pass verification poll), so factor 3 + a generous
# fixed buffer keeps a legitimately-long pass alive while still bounding a dead
# worker. A false timeout only costs a fingerprint-gated re-perform next push
# (no corruption), so we err toward the generous side.
_PERFORM_READ_CEILING_FACTOR = 3.0
_PERFORM_READ_CEILING_BUFFER_S = 90.0


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


def perform_target_key(args: dict[str, Any]) -> tuple:
    """Identity of the Live parameter a perform arc rides, from its wire
    addressing args — the key the planner's duplicate-target preflight dedups
    on. MUST stay field-for-field identical to the handler's
    ``_PreparedArc.addressing_key()`` (the mcp side): the planner preflight and
    the handler's collision guard are two halves of one contract, and if they
    drift the planner silently stops matching and a collision halts the whole
    phase. A cross-package parity test pins them together.
    """
    return (
        args.get("target_kind"), bool(args.get("master")),
        args.get("track_index"), args.get("return_index"),
        args.get("device_index"), args.get("parameter_name"),
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
    slowdown_factor: float = 1.0,
) -> PushPlan:
    """Plan the perform pass: ONE
    ``ableton_automation(action='perform_batch')`` call carrying every
    perform-routed arc whose fingerprint changed since the last successful
    perform (ENV-9P4T). The transport plays once over the union span with
    per-parameter gesture windowing, instead of one playthrough per arc.
    Unchanged arcs are fingerprint-gated out and listed as skipped — a
    data-safety feature, not just a speed one: an unchanged authored arc is
    never re-recorded, so a hand-edited Live lane survives.

    ``slowdown_factor`` (ENV-2T9K, default 1.0 = off) is forwarded to the
    handler, which lowers the transport tempo for the record pass to lay down
    factor× more breakpoints per beat (fidelity). It costs factor× wall-clock,
    so the cost estimates below — the purpose string, the overwrite alert, and
    the #5 read ceiling — are all scaled by it, keeping Visible Costs honest.

    Visible Costs: the call's purpose names the union-span wall-clock (one
    pass, NOT the per-arc sum), and a loud operator-facing ``alert()``
    enumerates every span the pass will record/overwrite.
    """
    if slowdown_factor < 1.0:
        raise ValueError(
            f"slowdown_factor must be >= 1.0 (1.0 = song tempo), got "
            f"{slowdown_factor}"
        )
    plan = PushPlan()
    envelopes = Q.get_envelopes_for_song(conn, song_id)
    eligible = [
        env for env in envelopes
        if classify_envelope_route(conn, env, song_id=song_id) == "perform"
    ]
    if not eligible:
        plan.warn("no perform-routed envelopes for this song; nothing to perform")
        return plan

    segments = _tempo_segments(conn, song_id)
    skipped: list[str] = []
    arcs: list[dict[str, Any]] = []
    # Parallel to `arcs`: (label, span_start, span_end) for the overwrite
    # alert and the union-span cost.
    spans: list[tuple[str, float, float]] = []
    # Addressing identity → envelope id that OWNS the target's single arrangement
    # lane. Two envelopes addressing ONE Live parameter can't both ride a single
    # transport pass, so the planner keeps ONE and loudly defers the rest.
    # Data-safety priority (ENV-8K2R #3): an already-recorded (skipped-unchanged)
    # lane is claimed in a dedicated pre-pass BEFORE any changed arc, so a changed
    # arc on the same target is always the one deferred — never recorded over the
    # correct lane (which used to corrupt the skipped arc's stored fingerprint
    # with no warning, and was visit-order-dependent in the single-pass version).
    # Among changed arcs (no recorded lane to protect) the first visited wins.
    claimed_targets: dict[tuple, str] = {}

    # Validate + classify every eligible arc once (span / addressing warnings
    # fire here, in eligible order); the claim/queue decision is deferred to the
    # two ordered passes below so skipped lanes are claimed first.
    skipped_candidates: list[tuple[tuple, str, str]] = []  # key, label, eid
    changed_candidates: list[tuple] = []  # env, args, label, key, start, end, bps
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
        target_key = perform_target_key(args)

        fingerprint = envelope_fingerprint(env, breakpoints)
        performed = Q.get_performed_automation(conn, env["id"], session_id)
        if performed is not None and performed["fingerprint"] == fingerprint:
            skipped_candidates.append((target_key, label, env["id"]))
        else:
            changed_candidates.append(
                (env, args, label, target_key, span_start, span_end, breakpoints)
            )

    # Pass A — claim every already-recorded lane FIRST so the next pass can't
    # queue a changed arc over it. Two recorded lanes on one parameter is a
    # pre-existing authoring ambiguity (only one can actually exist in Live);
    # surface it, keep the first.
    for (target_key, label, eid) in skipped_candidates:
        if target_key in claimed_targets:
            plan.alert(
                f"performed-automation: skipped (unchanged) arc {eid} ({label}) "
                f"shares its parameter with already-recorded arc "
                f"{claimed_targets[target_key]} — two envelopes on one "
                "parameter; merge them into one envelope."
            )
            continue
        claimed_targets[target_key] = eid
        skipped.append(label)

    # Pass B — queue changed arcs against the fully-claimed skipped lanes.
    for (env, args, label, target_key, span_start, span_end, breakpoints) in (
        changed_candidates
    ):
        if target_key in claimed_targets:
            owner = claimed_targets[target_key]
            plan.alert(
                f"performed-automation: arc {env['id']} ({label}) targets the "
                f"same parameter as already-claimed arc {owner} — keeping "
                f"{owner} and deferring this one (two performed arcs can't ride "
                "one parameter in a single pass; an already-recorded lane is "
                "always kept). Merge them into one envelope."
            )
            continue
        claimed_targets[target_key] = env["id"]

        arcs.append({
            "arc_id": env["id"],
            **args,
            "breakpoints": _breakpoints_for_mcp(breakpoints),
        })
        spans.append((label, span_start, span_end))

    if arcs:
        union_start = min(s for (_, s, _) in spans)
        union_end = max(e for (_, _, e) in spans)
        union_seconds = _estimate_span_seconds(segments, union_start, union_end)
        # ENV-2T9K: at a >1 slowdown the transport plays factor× slower, so the
        # ACTUAL pass wall-clock — and everything derived from it (the operator
        # cost, the #5 read ceiling) — is the realtime estimate × factor.
        pass_seconds = union_seconds * slowdown_factor
        slow_note = (
            f" at {slowdown_factor:g}× slowdown for fidelity"
            if slowdown_factor > 1.0 else ""
        )
        batch_args: dict[str, Any] = {"action": "perform_batch", "arcs": arcs}
        if slowdown_factor > 1.0:
            batch_args["slowdown_factor"] = slowdown_factor
        plan.add(ToolCall(
            tool="ableton_automation",
            args=batch_args,
            key=f"perform_batch:{song_id}",
            purpose=(
                f"perform {len(arcs)} arc(s) in ONE transport pass over "
                f"beats {union_start:g}-{union_end:g} "
                f"(~{pass_seconds:.1f}s realtime playback{slow_note})"
            ),
            # ENV-8K2R #5: cap the otherwise-unbounded read so a dead worker
            # can't block push_cli forever, scaled to the ACTUAL pass duration
            # (slowdown included) so a legitimately-long pass is never falsely
            # timed out.
            read_timeout=round(
                pass_seconds * _PERFORM_READ_CEILING_FACTOR
                + _PERFORM_READ_CEILING_BUFFER_S,
                1,
            ),
        ))
        span_list = "; ".join(
            f"{label} [{s:g}-{e:g}]" for (label, s, e) in spans
        )
        plan.alert(
            f"performed-automation: ONE transport pass over beats "
            f"{union_start:g}-{union_end:g} (~{pass_seconds:.1f}s realtime"
            f"{slow_note}) WILL RECORD/OVERWRITE {len(arcs)} arc(s): "
            f"{span_list}. {len(skipped)} unchanged arc(s) skipped."
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
    """Apply-layer hook for a single arc of a successful ``perform_batch``
    result. Records the performed-state fingerprint for this (envelope,
    session) ONLY when the handler verified the write
    (``automation_state == 1``); anything else
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
    # A verified state with zero value writes means the playhead crossed the
    # arc's whole span between ramp ticks (sub-tick / degenerate window): the
    # gesture opened and closed but nothing was recorded, so automation_state=1
    # reflects the STALE pre-edit lane, not this arc. Don't trust it — leave
    # the fingerprint unwritten so the next push re-performs. (updates_written
    # absent → a caller that doesn't report it; don't second-guess that case.)
    if result.get("updates_written") == 0:
        return (
            f"perform {envelope_id}: automation_state=1 but updates_written=0 "
            "— the playhead crossed the arc's span between ticks, so no value "
            "was recorded this pass and the '1' reflects a stale lane. "
            "Fingerprint left unwritten; the next push retries this arc."
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
