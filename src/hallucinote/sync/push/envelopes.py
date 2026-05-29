"""Mix-half planner: automation envelopes.

Wave M-4: all seven envelope target families flow through one unified
tool: `ableton_automation(action='write_envelope', target_kind=...)`.
One ToolCall per envelope, breakpoints inline.

  target_kind='clip_cc'           track_index, location='session', clip_index,
                                  cc_number, breakpoints
  target_kind='clip_pitch_bend'   track_index, location='session', clip_index,
                                  breakpoints
  target_kind='note_expression'   track_index, location='session', clip_index,
                                  note_pitch, note_start_beats, axis,
                                  note_duration (optional tail anchor),
                                  breakpoints
  target_kind='device_parameter'  (track_index | return_index), device_index,
                                  parameter_name, breakpoints
  target_kind='mixer_volume'      track_index, breakpoints
  target_kind='mixer_pan'         track_index, breakpoints
  target_kind='send_level'        track_index, return_index, breakpoints

Breakpoint shape (inline list): {time_beats, value, curve}. The DB stores
`curve_kind`; the wire field is `curve` to match the MCP-side handler's
enum naming. The rename happens in `_breakpoints_for_mcp`.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import queries as Q

from ..geometry import (
    _CoveringPlacement,
    _envelope_beat_range,
    _resolve_envelope_session_clip,
)
from ._core import (
    PushPlan,
    ToolCall,
    _breakpoints_for_mcp,
)


def plan_push_envelopes(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of every envelope in a song. One canonical call per
    envelope with breakpoints inline.

    Skip-with-warn paths (W4-B):
      - ``clip_cc`` / ``clip_pitch_bend``: Live 12.4 LOM doesn't expose
        ``Clip.create_automation_envelope`` for these targets
        (push-findings #12). Warn cites the MIDI control-change-note
        workaround for clip_cc; pitch_bend has no auto-encode path.
      - ``mixer_volume`` / ``mixer_pan`` / ``send_level`` /
        ``device_parameter``: routed through a session clip on the target
        track (Live 12.4 LOM accepts these only on session clips). When
        no arrangement_clip placement on the target track covers the
        envelope's beat range, the envelope can't be hosted; warn + skip.
      - Return-side ``device_parameter``: DB has no return-track session-
        clip model; warn + skip (backlog).

    Other skip-with-warn paths (legacy):
      - target/clip/device not linked in the session
      - zero breakpoints (nothing to push)
      - nested-rack devices (MCP gap)
    """
    plan = PushPlan()
    envelopes = Q.get_envelopes_for_song(conn, song_id)
    if not envelopes:
        plan.warn("no envelopes for this song; nothing to push")
        return plan

    for env in envelopes:
        breakpoints = Q.get_breakpoints(conn, env["id"])
        if not breakpoints:
            plan.warn(
                f"envelope {env['id']} ({env['target_kind']}) has no "
                "breakpoints; skipping"
            )
            continue
        target_kind = env["target_kind"]
        bps_mcp = _breakpoints_for_mcp(breakpoints)

        if target_kind == "clip_cc":
            # W4-B: Live 12.4's LOM doesn't expose
            # ``Clip.create_automation_envelope`` for MIDI CC targets —
            # the call raises ``ArgumentError`` (push-findings #12). The
            # canonical workaround is to encode the CC ride as MIDI
            # control-change notes via ``ableton_clip(action='replace_notes')``.
            plan.warn(
                f"envelope {env['id']} (clip_cc CC{env['parameter_path']}): "
                "Live 12.4 LOM doesn't expose Clip.create_automation_envelope "
                "for MIDI CC targets; encode as control-change notes via "
                "ableton_clip(action='replace_notes') instead. Skipping."
            )
            continue
        if target_kind == "clip_pitch_bend":
            # W4-B: same LOM gap as clip_cc (push-findings #12). No
            # auto-encode path exists for pitch bend — author manually
            # in Live.
            plan.warn(
                f"envelope {env['id']} (clip_pitch_bend): Live 12.4 LOM "
                "doesn't expose Clip.create_automation_envelope for "
                "pitch-bend targets; author manually in Live. Skipping."
            )
            continue
        if target_kind == "note_expression":
            _emit_note_expression_envelope(
                plan, conn,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind == "device_parameter":
            _emit_device_parameter_envelope(
                plan, conn, song_id=song_id,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind in ("mixer_volume", "mixer_pan"):
            _emit_mixer_envelope(
                plan, conn, song_id=song_id,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind == "send_level":
            _emit_send_envelope(
                plan, conn, song_id=song_id,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        else:
            # Schema CHECK already enforces target_kind ∈ allowlist; this is a
            # belt-and-suspenders guard for future kinds added to the schema
            # without a matching planner branch.
            raise ValueError(
                f"plan_push_envelopes: target_kind {target_kind!r} has no "
                "emitter branch — add one alongside the schema entry"
            )
    return plan


def _track_kind_for_envelope(
    conn: sqlite3.Connection, track_id: str | None,
) -> str | None:
    """Look up a track's `kind` column, or None when track_id is None / unknown.

    W10-F planner-side safety net for D2/D3. The DB mutator now refuses to
    create envelopes for session-clip-routed kinds (mixer / pan / send /
    device_parameter) on non-MIDI tracks (master / audio / group). This
    helper backs the parallel planner refusal, which catches legacy rows
    that pre-date the mutator check or pulled state that bypassed it.
    """
    if track_id is None:
        return None
    row = Q.get_track(conn, track_id)
    return None if row is None else row["kind"]


def _warn_unreachable_track_kind(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    host_track_id: str,
    host_kind: str,
) -> bool:
    """Emit a teaching warn + return True when the envelope's host track
    can't host the v1 routing surface.

    Mirrors the DB-mutator refusal phrasing (mutations.py
    `_envelope_track_kind_refusal`) but in plan-warn shape — the planner
    is the second layer of the W10-F dual-layer defense.
    """
    if host_kind == "midi":
        return False
    target_kind = envelope["target_kind"]
    if host_kind == "master":
        msg = (
            f"envelope {envelope['id']} ({target_kind}): host track "
            f"{host_track_id} is the master, which Live 12.4's LOM can't "
            "host envelopes on (Clip.create_automation_envelope lives only "
            "on Clip; master can't host clips). Route source(s) to a "
            "sub-bus group track and author on the group's mixer instead "
            "(see ableton://guides/gaps). Skipping."
        )
    elif host_kind == "audio":
        msg = (
            f"envelope {envelope['id']} ({target_kind}): host track "
            f"{host_track_id} is an audio track, which v1 can't host "
            "mixer/send/device_parameter envelopes on — Hallucinote routes "
            "these through MIDI session clips, and audio tracks can't host "
            "them. Route the source to a sub-bus group track and automate "
            "the group's mixer instead. Audio-clip envelopes are v1.1 "
            "scope. Skipping."
        )
    elif host_kind == "group":
        msg = (
            f"envelope {envelope['id']} ({target_kind}): host track "
            f"{host_track_id} is a group track, which can't host MIDI "
            "session clips in Live. Author the envelope on a member track "
            "or on the group's parent sub-bus. Skipping."
        )
    else:
        msg = (
            f"envelope {envelope['id']} ({target_kind}): host track "
            f"{host_track_id} has kind={host_kind!r}, which v1 doesn't "
            "route envelopes through (only kind='midi' tracks host them). "
            "Skipping."
        )
    plan.warn(msg)
    return True


def _clip_and_track_indices(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    clip_id: str,
) -> tuple[int | None, int | None]:
    """Resolve (track_index, clip_index) for a clip in a session, or (None, None)
    if either isn't linked yet."""
    clip_row = Q.get_clip(conn, clip_id)
    if clip_row is None:
        return None, None
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=clip_row["track_id"]
    )
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id
    )
    return track_at, clip_at


def _clip_local_breakpoints(
    breakpoints_mcp: list[dict[str, Any]],
    offset_beats: float,
) -> list[dict[str, Any]]:
    """Translate arrangement-time breakpoint times to clip-local by
    subtracting the placement offset. Other fields pass through."""
    return [
        {**bp, "time_beats": float(bp["time_beats"]) - offset_beats}
        for bp in breakpoints_mcp
    ]


def _emit_note_expression_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """note_expression emission — MPE per-note envelopes addressed by
    (clip, pitch, start_beats). Note links aren't tracked, so the canonical
    args identify the note in-band."""
    note_row = Q.get_note(conn, envelope["target_note_id"])
    if note_row is None:
        plan.warn(
            f"envelope {envelope['id']} (note_expression): note "
            f"{envelope['target_note_id']} not found; skipping"
        )
        return
    track_at, clip_at = _clip_and_track_indices(
        conn, session_id=session_id, clip_id=note_row["clip_id"]
    )
    if track_at is None or clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} (note_expression): clip not linked "
            f"(track={track_at}, clip={clip_at}); skipping"
        )
        return
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": "note_expression",
            "track_index": track_at,
            "location": "session",
            "clip_index": clip_at,
            "note_pitch": note_row["pitch"],
            "note_start_beats": float(note_row["start_beats"]),
            "note_duration": float(note_row["duration_beats"]),
            "axis": envelope["parameter_path"],
            "breakpoints": breakpoints_mcp,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"note_expression {envelope['parameter_path']} on note "
            f"pitch={note_row['pitch']} @ beat {note_row['start_beats']:g}: "
            f"{len(breakpoints_mcp)} breakpoint(s)"
        ),
    ))
    _warn_lossy_curve_hints(plan, envelope=envelope, breakpoints_mcp=breakpoints_mcp)


_LOSSY_CURVE_HINTS = frozenset({"linear", "fast", "slow"})


def _warn_lossy_curve_hints(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """Emit one warn per envelope when any breakpoint carries a curve
    hint Live 12.4 cannot apply.

    Live 12.4 exposes only ``Envelope.insert_step``; the MCP handler
    converts every breakpoint to a stepped region (see
    ``hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py::_write_breakpoints_as_steps``).
    Curves ``linear`` / ``fast`` / ``slow`` are recorded in the DB
    faithfully but discarded on push — the MCP handler returns a note
    after the fact (``_stepped_envelope_note``). Surfacing the same
    truth at plan time lets the user see round-trip lossiness BEFORE
    dispatch instead of discovering it in MCP responses.

    Only ``hold`` (and absent) curves are preserved on push. Dedup is
    per-envelope: many lossy breakpoints in one envelope produce one
    warn, not N.
    """
    if not any(bp.get("curve") in _LOSSY_CURVE_HINTS for bp in breakpoints_mcp):
        return
    plan.warn(
        f"envelope {envelope['id']} ({envelope['target_kind']}): Live 12.4 "
        "applies all envelope curves as steps (Envelope.insert_step); "
        "'linear'/'fast'/'slow' curve hints are recorded in the DB but "
        "lossy on push. Use 'hold' to model the same behavior the DB "
        "stores."
    )


def _warn_multiple_covering_clips(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    placement: _CoveringPlacement,
) -> None:
    """W4-B defensive warn: when more than one distinct session clip on
    the same track covers the envelope's beat range, the planner picks
    the earliest by ``start_bar``. The choice may not match the
    author's intent — surface the alternatives so they can resolve the
    ambiguity DB-side (trim a clip, move one, or split the envelope)."""
    if not placement.other_covering_clip_ids:
        return
    others = ", ".join(placement.other_covering_clip_ids)
    plan.warn(
        f"envelope {envelope['id']} ({envelope['target_kind']}): multiple "
        f"distinct session clips cover the envelope's beat range on this "
        f"track. Planner routed through {placement.clip_id!r}; other "
        f"covering clips: [{others}]. Resolve the ambiguity DB-side "
        "(adjust placements or split the envelope) if the routing "
        "choice is wrong."
    )


def _warn_trimmed_placement(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    placement: _CoveringPlacement,
    env_max: float,
) -> None:
    """W4-B defensive warn: the matched placement is trimmed shorter
    than its source session clip's natural length, AND the envelope
    extends past the trimmed end. The envelope will play correctly
    in the session view (the session clip is intact) but won't sound
    past the trim point in this arrangement placement — Live truncates
    playback at ``end_bar``.

    No-op when the placement isn't trimmed OR the envelope fits within
    the trimmed extent.
    """
    trimmed_end = placement.trimmed_end_beats
    if trimmed_end is None:
        return
    if env_max <= trimmed_end:
        return
    plan.warn(
        f"envelope {envelope['id']} ({envelope['target_kind']}): the "
        f"matched arrangement placement of clip {placement.clip_id!r} "
        f"is trimmed shorter than the source clip; the envelope extends "
        f"to time_beats={env_max:g} but the placement ends at "
        f"time_beats={trimmed_end:g}. Breakpoints past the trim point "
        "won't sound in this arrangement placement (session-view "
        "playback is unaffected)."
    )


def _warn_extra_placements(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    placement: _CoveringPlacement,
) -> None:
    """When the session clip is placed multiple times in the arrangement,
    ``duplicate_to_arrangement`` snapshot-copies the session-clip
    envelope to every placement (W4-A finding). The DB models the
    envelope as fixed to one arrangement range; the planner can't avoid
    the extra firings without cloning the session clip. Warn loudly so
    the author knows their envelope will also fire at the listed
    arrangement positions."""
    if not placement.other_placement_starts:
        return
    others = ", ".join(f"{s:g}" for s in placement.other_placement_starts)
    plan.warn(
        f"envelope {envelope['id']} ({envelope['target_kind']}): source "
        f"session clip {placement.clip_id} is placed at multiple "
        f"arrangement positions; the envelope will also fire at "
        f"start_beats=[{others}] after duplicate_to_arrangement "
        "(W4-A snapshot semantics). Use a uniquely-placed session clip "
        "to localize the envelope."
    )


def _resolve_and_translate_to_session_clip(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
    host_track_id: str,
    host_track_at: int,
) -> tuple[int, list[dict[str, Any]], _CoveringPlacement, float] | None:
    """Resolve the host session clip for a clip-scoped envelope kind
    (mixer / send / device_parameter) and translate breakpoints into the
    clip's local coordinate system.

    Shared core of the three ``_emit_*_envelope`` functions — the same
    placement-resolution + clip-link-resolution + breakpoint-translation
    + skip-with-warn paths fire identically for every clip-scoped kind.
    The kind-specific differences (which device address args to emit,
    which extra fields on the ToolCall) stay in the caller.

    Returns ``(clip_at, local_bps, placement, env_max)`` on success.
    Returns ``None`` after emitting a target_kind-aware skip-with-warn
    when either:
      - no arrangement_clip on ``host_track_id`` covers the envelope's
        beat range (Live 12.4 LOM requires session-clip routing for
        clip-scoped envelope kinds), or
      - the matched session clip has no Ableton link in this session.
    """
    target_kind = envelope["target_kind"]
    env_min, env_max = _envelope_beat_range(breakpoints_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=host_track_id,
        env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} ({target_kind}): no arrangement "
            f"clip on track {host_track_at} covers beat range [{env_min:g}, "
            f"{env_max:g}]; Live 12.4 requires session-clip routing for "
            f"{target_kind} envelopes (W4-B). Options: (a) extend or split "
            "an existing session clip on this track to cover the range, "
            "(b) add an arrangement_clip placement that fully spans "
            f"[{env_min:g}, {env_max:g}], or (c) partition the envelope by "
            "hand into per-section sub-envelopes whose ranges each fit a "
            "session clip. Auto-partition is v1.1 scope (W10-F follow-up). "
            "Skipping."
        )
        return None
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=placement.clip_id,
    )
    if clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({target_kind}): session clip "
            f"{placement.clip_id} (covering placement) not linked; skipping"
        )
        return None
    local_bps = _clip_local_breakpoints(breakpoints_mcp, placement.start_beats)
    return clip_at, local_bps, placement, env_max


def _emit_session_clip_envelope_post_warnings(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    local_bps: list[dict[str, Any]],
    placement: _CoveringPlacement,
    env_max: float,
) -> None:
    """Fire the four after-the-fact warnings every clip-scoped emitter
    runs after ``plan.add()``: lossy curve hints, extra arrangement
    placements (W4-A duplicate_to_arrangement snapshot semantics),
    multiple covering clips, and trimmed placements. Pulled out of the
    three emitter shells to keep behavior identical across kinds."""
    _warn_lossy_curve_hints(plan, envelope=envelope, breakpoints_mcp=local_bps)
    _warn_extra_placements(plan, envelope=envelope, placement=placement)
    _warn_multiple_covering_clips(plan, envelope=envelope, placement=placement)
    _warn_trimmed_placement(
        plan, envelope=envelope, placement=placement, env_max=env_max,
    )


def _emit_device_parameter_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """device_parameter emission — track-side only on Live 12.4. Routes
    through a session clip on the parent track (W4-A / W4-B).

    Return-side device_parameter envelopes are blocked: returns have no
    DB session-clip model, and Live 12.4 only accepts mixer/pan/send/
    device_parameter envelopes on session clips. Warn and skip.
    """
    device_id = envelope["target_device_id"]
    device_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device_id,
    )
    chain_row = Q.get_device_parent_chain(conn, device_id)
    if chain_row is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): device "
            f"{device_id} not found; skipping"
        )
        return
    if chain_row["parent_rack_device_id"] is not None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): nested-rack "
            f"device {device_id} — push not yet supported (MCP gap)"
        )
        return
    if chain_row["parent_return_id"] is not None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): return-side "
            f"device {device_id} — Live 12.4 requires session-clip routing "
            "for device_parameter envelopes, but the DB has no return-side "
            "session-clip model; skipping (backlog: return-track clip "
            "domain)"
        )
        return
    parent_track_id = chain_row["parent_track_id"]
    host_kind = _track_kind_for_envelope(conn, parent_track_id)
    if host_kind is not None and _warn_unreachable_track_kind(
        plan, envelope=envelope, host_track_id=parent_track_id,
        host_kind=host_kind,
    ):
        return
    parent_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track",
        db_id=parent_track_id,
    )
    if parent_at is None or device_at is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): track or "
            f"device not linked (track={parent_at}, device={device_at}); "
            "skipping"
        )
        return
    routing = _resolve_and_translate_to_session_clip(
        plan, conn, song_id=song_id, session_id=session_id,
        envelope=envelope, breakpoints_mcp=breakpoints_mcp,
        host_track_id=parent_track_id, host_track_at=parent_at,
    )
    if routing is None:
        return
    clip_at, local_bps, placement, env_max = routing
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": "device_parameter",
            "track_index": parent_at,
            "location": "session",
            "clip_index": clip_at,
            "device_index": device_at,
            "parameter_name": envelope["parameter_path"],
            "breakpoints": local_bps,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"device_parameter {envelope['parameter_path']} on track "
            f"{parent_at} session clip {clip_at} (offset {placement.start_beats:g}): "
            f"{len(local_bps)} breakpoint(s)"
        ),
    ))
    _emit_session_clip_envelope_post_warnings(
        plan, envelope=envelope, local_bps=local_bps,
        placement=placement, env_max=env_max,
    )


def _emit_mixer_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """mixer_volume + mixer_pan emission. Routes through a session clip
    on the target track (W4-A / W4-B): Live 12.4 only accepts these
    envelopes on session clips, then ``duplicate_to_arrangement``
    snapshot-copies them to the arrangement."""
    track_id = envelope["target_track_id"]
    host_kind = _track_kind_for_envelope(conn, track_id)
    if host_kind is not None and _warn_unreachable_track_kind(
        plan, envelope=envelope, host_track_id=track_id, host_kind=host_kind,
    ):
        return
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    )
    if track_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): track "
            f"{track_id} not linked; skipping"
        )
        return
    routing = _resolve_and_translate_to_session_clip(
        plan, conn, song_id=song_id, session_id=session_id,
        envelope=envelope, breakpoints_mcp=breakpoints_mcp,
        host_track_id=track_id, host_track_at=track_at,
    )
    if routing is None:
        return
    clip_at, local_bps, placement, env_max = routing
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": envelope["target_kind"],
            "track_index": track_at,
            "location": "session",
            "clip_index": clip_at,
            "breakpoints": local_bps,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"{envelope['target_kind']} on track {track_at} session clip "
            f"{clip_at} (offset {placement.start_beats:g}): "
            f"{len(local_bps)} breakpoint(s)"
        ),
    ))
    _emit_session_clip_envelope_post_warnings(
        plan, envelope=envelope, local_bps=local_bps,
        placement=placement, env_max=env_max,
    )


def _emit_send_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """send_level emission — addressed by (track, return) pair. Routes
    through a session clip on the source track (W4-A / W4-B)."""
    track_id = envelope["target_track_id"]
    host_kind = _track_kind_for_envelope(conn, track_id)
    if host_kind is not None and _warn_unreachable_track_kind(
        plan, envelope=envelope, host_track_id=track_id, host_kind=host_kind,
    ):
        return
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    )
    return_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="return",
        db_id=envelope["target_send_return_id"],
    )
    if track_at is None or return_at is None:
        plan.warn(
            f"envelope {envelope['id']} (send_level): missing link "
            f"(track={track_at}, return={return_at}); skipping"
        )
        return
    routing = _resolve_and_translate_to_session_clip(
        plan, conn, song_id=song_id, session_id=session_id,
        envelope=envelope, breakpoints_mcp=breakpoints_mcp,
        host_track_id=track_id, host_track_at=track_at,
    )
    if routing is None:
        return
    clip_at, local_bps, placement, env_max = routing
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": "send_level",
            "track_index": track_at,
            "location": "session",
            "clip_index": clip_at,
            "return_index": return_at,
            "breakpoints": local_bps,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"send_level track {track_at} -> return {return_at} via "
            f"session clip {clip_at} (offset {placement.start_beats:g}): "
            f"{len(local_bps)} breakpoint(s)"
        ),
    ))
    _emit_session_clip_envelope_post_warnings(
        plan, envelope=envelope, local_bps=local_bps,
        placement=placement, env_max=env_max,
    )
