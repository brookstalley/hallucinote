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

Visible Fidelity is the same principle applied to the route's resolution
(#475): the recorder samples on a fixed ~2.5 Hz grid, so an authored
edge shorter than one tick has no representation on this route at all — it
lands as a step on the grid rather than the ramp that was written. The
planner names every such edge and marks the phase INCOMPLETE, because the
song asked for something it did not get; it does NOT refuse, since the
fidelity-vs-wall-clock trade (``slowdown_factor``) is the operator's to make.
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
    build_node_addr,
)
from .envelopes import classify_envelope_route

_DEFAULT_BPM = 120.0

# The handler's per-arc verdict for an arc it recorded AND verified. Mirrors
# ``hallucinote_mcp.handlers.automation.PERFORM_OUTCOME_RECORDED`` — the engine
# does not import the MCP package (they ship and version separately), so the
# string is the contract and `sync-boundary-contract.md` records it.
PERFORM_OUTCOME_RECORDED = "recorded"

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

# The perform route's fixed record tick. The handler's ramp is scheduling-bound
# at ~2.5 Hz — one breakpoint laid down per 400 ms of WALL-CLOCK — and denser
# authoring cannot make it denser (only a slower transport can, which is what
# ``slowdown_factor`` is for). Mirrors
# ``hallucinote_mcp.handlers.automation``'s ramp scheduler; the engine does not
# import the MCP package (they ship and version separately), so the number is
# the contract, the same way ``PERFORM_OUTCOME_RECORDED`` is.
_PERFORM_TICK_HZ = 2.5
_PERFORM_TICK_SECONDS = 1.0 / _PERFORM_TICK_HZ

# How many offending edges a single sub-tick warning enumerates before it
# summarizes the rest — the message must name segments, not become a dump.
_SUBTICK_NAMED_LIMIT = 3


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


def _subtick_edges(
    segments: list[tuple[float, float]],
    breakpoints: list[sqlite3.Row],
    *,
    tick_seconds: float,
) -> list[tuple[float, float, float]]:
    """The authored edges this route cannot draw: [(start_beats, end_beats,
    seconds), ...] for every consecutive breakpoint pair that CHANGES VALUE
    over a span shorter than one record tick.

    The recorder samples on a fixed wall-clock grid, so a ramp that begins and
    ends between two ticks is never sampled mid-ride — it lands as a step on
    the grid instead of the shape that was written, and nothing downstream can
    tell that apart from a step the author wanted. Two exclusions keep the
    reading honest rather than merely loud:

    - **equal values** — a flat hold loses nothing by being sampled sparsely;
      only an EDGE has a shape to lose.
    - **zero-length pairs** — two breakpoints at one time are a deliberate
      instantaneous step. The route reproduces a step as a step; only its
      placement quantizes, which is a different (and much smaller) claim than
      "the ramp you wrote is gone".
    """
    out: list[tuple[float, float, float]] = []
    for prev, cur in zip(breakpoints, breakpoints[1:]):
        if float(prev["value"]) == float(cur["value"]):
            continue
        start = float(prev["time_beats"])
        end = float(cur["time_beats"])
        seconds = _estimate_span_seconds(segments, start, end)
        if 0.0 < seconds < tick_seconds:
            out.append((start, end, seconds))
    return out


def _subtick_reason(
    *,
    env_id: str,
    label: str,
    edges: list[tuple[float, float, float]],
    tick_seconds: float,
    slowdown_factor: float,
) -> str:
    """The operator-facing sentence for one arc's sub-tick edges: what was
    authored, what the tick is, and the exact dial setting that would carry it.
    """
    named = "; ".join(
        f"beats {s:g}-{e:g} (~{sec * 1000:.0f} ms)"
        for (s, e, sec) in edges[:_SUBTICK_NAMED_LIMIT]
    )
    more = (
        f"; +{len(edges) - _SUBTICK_NAMED_LIMIT} more"
        if len(edges) > _SUBTICK_NAMED_LIMIT else ""
    )
    shortest = min(sec for (_, _, sec) in edges)
    # tick_seconds = _PERFORM_TICK_SECONDS / slowdown_factor, so the factor that
    # makes the SHORTEST edge span a full tick is an absolute setting, not a
    # multiplier on the current one.
    needed = _PERFORM_TICK_SECONDS / shortest
    at_factor = (
        f" at {slowdown_factor:g}x slowdown" if slowdown_factor > 1.0 else ""
    )
    return (
        f"performed-automation: arc {env_id} ({label}) authors {len(edges)} "
        f"edge(s) shorter than one record tick "
        f"(~{tick_seconds * 1000:.0f} ms{at_factor}): {named}{more}. The "
        f"perform route records on a fixed ~{_PERFORM_TICK_HZ:g} Hz grid, so an "
        "edge under one tick is never sampled mid-ride — it lands as a step on "
        "the grid, NOT as the ramp that was authored, and this pass reports "
        "nothing wrong about it. Raise slowdown_factor to "
        f"{needed:.3g} or more (the pass then costs {needed:.3g}x wall-clock) "
        "to record it, or lengthen the edge."
    )


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
        # DEEP-RACK-ADDR: resolve the TOP-LEVEL ancestor — the device that
        # actually carries the ableton_links binding — and the positional
        # device_path to the (possibly nested) target param. For a top-level
        # device, top_level IS the device and device_path is [].
        top_level = Q.get_top_level_device(conn, device_id)
        if top_level is None:
            plan.warn(
                f"perform {env_id} (device_parameter): device {device_id} "
                "not found; arc pending"
            )
            return None
        device_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="device",
            db_id=top_level["id"],
        )
        if device_at is None:
            plan.warn(
                f"perform {env_id} (device_parameter): device {device_id} "
                "not linked; arc pending (master-chain devices are placed "
                "manually — run probe-and-link after placing)"
            )
            return None
        device_path = Q.get_device_nesting_path(conn, device_id)
        # The parent SURFACE (track/return/master) is the top-level device's
        # chain, not the nested device's chain.
        chain_row = Q.get_device_parent_chain(conn, top_level["id"])
        if chain_row is None:
            plan.warn(
                f"perform {env_id} (device_parameter): device {device_id} "
                "has no chain row; arc pending"
            )
            return None
        # NODE-ADDR: device_parameter rides a single `node` (the perform surface
        # addresses the Parameter object directly, so nested params are reachable
        # — device_path becomes the node's `path`). Collect the parent surface
        # into parent_kv, then build the node.
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
            parent_kv: dict[str, Any] = {"return_index": return_at}
            label = f"return {return_at} device {device_at} {envelope['parameter_path']}"
        else:
            track_row = Q.get_track(conn, chain_row["parent_track_id"])
            if track_row is not None and track_row["kind"] == "master":
                parent_kv = {"master": True}
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
                parent_kv = {"track_index": track_at}
                label = (
                    f"{track_row['name'] if track_row else track_at} device "
                    f"{device_at} {envelope['parameter_path']}"
                )
        args = {
            "target_kind": "device_parameter",
            "node": build_node_addr(
                parent_kv, device_index=device_at, device_path=device_path,
            ),
            "parameter_name": envelope["parameter_path"],
        }
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

    DEEP-RACK-ADDR: ``device_path`` is part of the identity — two arcs on
    different nested devices share a top-level ``device_index`` but differ by
    path, so the path (as a hashable tuple of steps) must be in the key or they
    would falsely collide.

    NODE-ADDR: device_parameter arcs carry a ``node`` object; the handler
    translates it back to flat fields on ``_PreparedArc`` before keying, so this
    side extracts the same flat fields from the node to keep the keys identical.
    mixer / send arcs keep their flat master / track_index / return_index.
    """
    node = args.get("node")
    if node is not None:
        parent = node.get("parent", {})
        pkind = parent.get("kind")
        master = pkind == "master"
        track_index = parent.get("index") if pkind == "track" else None
        return_index = parent.get("index") if pkind == "return" else None
        device_index = node.get("device_index")
        device_path = node.get("path")
    else:
        master = bool(args.get("master"))
        track_index = args.get("track_index")
        return_index = args.get("return_index")
        device_index = args.get("device_index")
        device_path = args.get("device_path")
    return (
        args.get("target_kind"), master,
        track_index, return_index,
        device_index, args.get("parameter_name"),
        tuple(
            (int(s["chain_index"]), int(s["device_position"]))
            for s in (device_path or ())
        ),
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

    Sub-tick fidelity (#475): every queued arc is also read against the
    route's fixed ~2.5 Hz record tick (``_PERFORM_TICK_SECONDS``, divided by
    ``slowdown_factor`` — a slower transport buys proportionally finer authored
    resolution). An authored edge shorter than one effective tick cannot be
    represented, so each offending arc raises a ``blocked()`` reason naming the
    segments, the tick they fell under, and the ``slowdown_factor`` that would
    carry the shortest of them. Blocked, not refused: the pass still records
    every arc, but the phase reports INCOMPLETE rather than a clean ok over a
    ramp that did not materialize.

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
    # #475: authored edges the fixed record grid cannot draw, one
    # reason per queued arc. Collected during pass B, raised after the
    # overwrite alert so the operator reads what WILL be recorded first, then
    # what will not survive it.
    subtick_reasons: list[str] = []
    tick_seconds = _PERFORM_TICK_SECONDS / slowdown_factor
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

        edges = _subtick_edges(
            segments, breakpoints, tick_seconds=tick_seconds,
        )
        if edges:
            subtick_reasons.append(_subtick_reason(
                env_id=env["id"], label=label, edges=edges,
                tick_seconds=tick_seconds, slowdown_factor=slowdown_factor,
            ))

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
        # #475: blocked(), not alert(). The pass still runs and every
        # arc still records — refusing would reject songs that already carry
        # sub-tick edges, and the operator, not the planner, owns the
        # fidelity-vs-wall-clock trade the dial exists for. But the authored
        # ramp did NOT materialize, so the run must not report a clean ok over
        # it: that clean success line is the defect being fixed here, not the
        # flattening itself.
        for reason in subtick_reasons:
            plan.blocked(reason)
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
    session) ONLY when the handler reported ``outcome == "recorded"`` —
    its own verdict, computed where the pass happened; anything else leaves
    the fingerprint unwritten so the next push retries the arc.
    ``automation_state == 1`` plus a non-zero ``updates_written`` remain the
    floor for a server predating the field, never the gate: the flag reads 1
    whenever ANY lane exists on the parameter, so after the first iteration
    it says yes regardless of what the pass did.
    Returns None when state was recorded, else a human-readable warning
    naming the arc and why — the caller surfaces it (never a silent skip).

    The fingerprint is recomputed from current DB rows — identical to the
    planner's within one plan→execute→apply cycle, and self-healing if
    the arc was edited mid-cycle (the stored print then reflects neither
    old nor new Live state, forcing a re-perform next push).
    """
    # The handler states its own verdict per arc. Prefer it — it is computed
    # where the pass actually happened — but keep the two field checks below as
    # the floor, because an older server predates the field and a result with
    # no `outcome` must not be read as an absent objection.
    outcome = result.get("outcome")
    if outcome is not None and outcome != PERFORM_OUTCOME_RECORDED:
        reason_text = result.get("outcome_reason") or "no reason given"
        return (
            f"perform {envelope_id}: the handler reported outcome="
            f"{outcome!r} — {reason_text} Fingerprint left unwritten; the "
            "next push retries this arc."
        )
    state = result.get("automation_state")
    if state != 1:
        return (
            f"perform {envelope_id}: handler returned "
            f"automation_state={state!r} (not 1 — the write is unverified); "
            "fingerprint left unwritten, the next push retries this arc. "
            "If it never verifies, check the parameter isn't "
            "automation-overridden or locked in Live."
        )
    # A verified state with zero value writes means this pass wrote nothing for
    # the arc — either the playhead crossed its whole span between ramp ticks
    # (a degenerate sub-tick window) or the transport never entered the span at
    # all. Either way ``automation_state=1`` is answering about a lane an
    # EARLIER pass wrote: the property reads 1 whenever any lane exists on the
    # parameter, so it cannot distinguish this pass's work from last week's.
    # Leave the fingerprint unwritten so the next push re-performs.
    # (updates_written absent → a caller that doesn't report it; don't
    # second-guess that case.)
    if result.get("updates_written") == 0:
        return (
            f"perform {envelope_id}: automation_state=1 but updates_written=0 "
            "— no value was recorded this pass, so the '1' reflects a stale "
            "lane from an earlier one. "
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
