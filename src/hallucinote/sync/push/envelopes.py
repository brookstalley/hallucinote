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
    build_node_addr,
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
        ``device_parameter`` on midi or audio hosts: routed through a
        session clip on the target track (Live 12.4 LOM accepts these
        only on session clips — an ARRANGEMENT clip raises "Not a session
        clip"). When no arrangement_clip placement on the target track
        covers the envelope's beat range, the ride is clip-independent
        and routes to perform instead (see below).

    Perform-routed (ENV-7G4K — `classify_envelope_route`): master/group
    hosts, return-side devices, and ``return_mixer_volume`` /
    ``return_mixer_pan`` are NOT emitted here — the performed-automation
    push phase gesture-records them into arrangement automation. This
    phase notes the routing and moves on. ENV-9P4T extends this: a plain
    midi or audio track whose envelope no single session clip covers also
    routes to perform (a continuous, clip-independent ride). A covered
    ride rides its session clip whether that clip is midi or AUDIO —
    ``Clip.create_automation_envelope`` works on an audio session clip
    (probe row 3: written and read back on a real one).

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
        elif target_kind in ("return_mixer_volume", "return_mixer_pan"):
            # A return track's own mixer (ENV-7G4K): always perform-routed —
            # returns host no clips, and the gesture-recording mechanism is
            # probe-verified on return tracks (probe 4b).
            _warn_non_session_route(
                plan, envelope=env, route="perform", host_kind="return",
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

    The host kind is what the route depends on (:func:`_route_for_host_kind`),
    so the planner reads it for every track-hosted envelope. A kind outside
    the canonical vocabulary — a legacy row, or pulled state that bypassed
    the create-time gate — falls through to 'unroutable' and is warned about
    rather than emitted as a guaranteed-fail wire call.
    """
    if track_id is None:
        return None
    row = Q.get_track(conn, track_id)
    return None if row is None else row["kind"]


def _route_for_host_kind(host_kind: str | None) -> str:
    """Map a host track's kind to its PER-CLIP / no-inference push route.

    This is the covered-case map (ENV-7G4K eligibility): master/group are
    always performed (they own no session clips to ride); a midi OR audio
    host's per-clip ride routes through a covering session clip, because
    ``Clip.create_automation_envelope`` accepts an audio session clip just
    as it does a midi one (probe row 3 wrote a track-volume envelope onto a
    real audio session clip and read the value back). What Live refuses is
    an ARRANGEMENT clip ("Not a session clip", probe row 2) — and no route
    here ever addresses one: every emitter writes ``location='session'``.
    ENV-9P4T's ``_route_track_hosted`` wraps this with infer-from-span so a
    clip-INDEPENDENT (e.g. song-spanning) ride on a midi/audio host routes
    to ``perform`` instead.
    """
    if host_kind in ("midi", "audio"):
        return "session_clip"
    if host_kind in ("master", "group"):
        return "perform"
    return "unroutable"


def _envelope_span(
    conn: sqlite3.Connection, envelope_id: str,
) -> tuple[float, float] | None:
    """(min, max) breakpoint ``time_beats`` for an envelope, or None when it
    has no breakpoints (degenerate — infer-from-span can't apply; the coarse
    host-kind route is used and the envelope is skipped upstream anyway)."""
    bps = Q.get_breakpoints(conn, envelope_id)
    if not bps:
        return None
    times = [float(b["time_beats"]) for b in bps]
    return min(times), max(times)


def _route_track_hosted(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    envelope: sqlite3.Row,
    host_track_id: str | None,
    host_kind: str | None,
) -> str:
    """ENV-9P4T infer-from-span for a track-hosted mixer / device envelope.

    master/group hosts → ``perform`` with NO inference (they own no session
    clips to ride). A midi or audio host → ``perform`` when no single
    session clip on the host track covers the envelope's beat span — a
    continuous, clip-independent arrangement ride (the 10+-track use case
    and the song-spanning send across tacet gaps). Otherwise the per-clip
    route, ``session_clip``, for a midi or an audio host alike. A degenerate
    no-breakpoint envelope falls back to the coarse host-kind route.
    """
    base = _route_for_host_kind(host_kind)
    if base != "session_clip":
        # master/group → perform; unknown/unresolved kind → unroutable. No
        # session-clip notion applies, so infer-from-span is a no-op.
        return base
    span = _envelope_span(conn, envelope["id"])
    if span is None:
        return base
    env_min, env_max = span
    covered = _resolve_envelope_session_clip(
        conn, song_id=song_id, target_track_id=host_track_id,
        env_min=env_min, env_max=env_max,
    ) is not None
    return base if covered else "perform"


def classify_envelope_route(
    conn: sqlite3.Connection, envelope: sqlite3.Row, *, song_id: str,
) -> str:
    """Partition an envelope into its push route (ENV-7G4K; ENV-9P4T
    infer-from-span for plain midi/audio track hosts).

    Returns one of:
      'clip_scoped'    clip_cc / clip_pitch_bend / note_expression — hosted
                       by the authored clip itself; existing emitters own
                       their LOM-gap teaching.
      'session_clip'   midi- OR audio-track host whose envelope is COVERED
                       by a single session clip — a per-clip ride routed
                       through Clip.create_automation_envelope. The clip
                       addressed is always a SESSION clip; Live refuses the
                       call on an arrangement clip (probe row 2).
      'perform'        master/group host, return-side mixer or device, OR a
                       plain midi/audio track host whose envelope is NOT
                       covered by a single session clip (a continuous,
                       clip-independent arrangement ride — ENV-9P4T).
                       Gesture-recorded into arrangement automation by the
                       performed-automation push phase (write-only surface).
      'unroutable'     unresolvable host (missing device/chain), nested-rack
                       device (no addressable surface on either route), or
                       an unknown kind — caller warns with specifics.

    Single source of truth for the partition: the session-clip emitters,
    the performed-automation phase selector, and the planner warns all key
    off this. ``song_id`` is required for the infer-from-span covering-clip
    lookup.
    """
    kind = envelope["target_kind"]
    if kind in ("clip_cc", "clip_pitch_bend", "note_expression"):
        return "clip_scoped"
    if kind in ("return_mixer_volume", "return_mixer_pan"):
        return "perform"
    if kind in ("mixer_volume", "mixer_pan", "send_level"):
        host_track_id = envelope["target_track_id"]
        host_kind = _track_kind_for_envelope(conn, host_track_id)
        if kind == "send_level" and host_kind == "master":
            # The master strip has no sends — the mutator refuses this
            # combination semantically, so a row here bypassed it. Route
            # nowhere rather than emit a guaranteed-fail wire call.
            return "unroutable"
        return _route_track_hosted(
            conn, song_id=song_id, envelope=envelope,
            host_track_id=host_track_id, host_kind=host_kind,
        )
    if kind == "device_parameter":
        chain_row = Q.get_device_parent_chain(conn, envelope["target_device_id"])
        if chain_row is None:
            return "unroutable"
        if chain_row["parent_rack_device_id"] is not None:
            # DEEP-RACK-ADDR: a nested-rack device parameter routes to PERFORM —
            # the perform handler addresses it via the canonical device_path
            # (get_device_nesting_path). The session-clip route stays
            # unavailable for nested params (Live 12.4 Clip.create_automation_
            # envelope can't address them), so a nested ride is always the
            # continuous performed arc, never a per-clip envelope.
            return "perform"
        if chain_row["parent_return_id"] is not None:
            return "perform"
        parent_track_id = chain_row["parent_track_id"]
        return _route_track_hosted(
            conn, song_id=song_id, envelope=envelope,
            host_track_id=parent_track_id,
            host_kind=_track_kind_for_envelope(conn, parent_track_id),
        )
    return "unroutable"


def _session_clip_host_track(
    conn: sqlite3.Connection, envelope: sqlite3.Row,
) -> str | None:
    """The track whose covering session clip a ``session_clip``-routed envelope
    rides — ``target_track_id`` for mixer/pan/send, the device's PARENT track
    for device_parameter (device_parameter rows carry no ``target_track_id``).
    Mirrors :func:`classify_envelope_route`'s host-track resolution so the two
    never drift."""
    kind = envelope["target_kind"]
    if kind in ("mixer_volume", "mixer_pan", "send_level"):
        return envelope["target_track_id"]
    if kind == "device_parameter":
        chain_row = Q.get_device_parent_chain(conn, envelope["target_device_id"])
        return chain_row["parent_track_id"] if chain_row is not None else None
    return None


def envelope_hosting_clip_ids(
    conn: sqlite3.Connection, song_id: str,
) -> set[str]:
    """ARR-PROJ §5/§9: the set of session-clip ids that HOST a clip-bound
    envelope — i.e. clips whose envelopes ``duplicate_to_arrangement``
    snapshot-copies into the arrangement (W4-A).

    An arrangement placement of such a clip MUST materialize via the duplicate
    path, NOT create+fill: create+fill writes notes only and would silently
    drop the clip envelope (the §9 routing risk). The arrangement planner routes
    every placement whose ``clip_id`` is in this set to duplicate-onto-cleared,
    and every other (note-only) placement to create+fill.

    A clip hosts an envelope when the envelope routes ``session_clip``
    (:func:`classify_envelope_route`) and a covering placement resolves to it,
    or for a materialized clip-scoped kind (``note_expression`` rides its note's
    clip). ``clip_cc`` / ``clip_pitch_bend`` are LOM-skipped by the envelopes
    phase today, but their authored clip is included defensively (harmless — if
    the envelope isn't on the session clip there is nothing for duplicate to
    carry and nothing for create+fill to lose). Reuses the authoritative
    classifier so routing never drifts from the envelopes phase.
    """
    hosts: set[str] = set()
    for env in Q.get_envelopes_for_song(conn, song_id):
        route = classify_envelope_route(conn, env, song_id=song_id)
        if route == "session_clip":
            host_track_id = _session_clip_host_track(conn, env)
            span = _envelope_span(conn, env["id"])
            if host_track_id and span:
                cov = _resolve_envelope_session_clip(
                    conn, song_id=song_id, target_track_id=host_track_id,
                    env_min=span[0], env_max=span[1],
                )
                if cov is not None:
                    hosts.add(cov.clip_id)
        elif route == "clip_scoped":
            if env["target_clip_id"]:
                hosts.add(env["target_clip_id"])
            elif env["target_note_id"]:
                note = Q.get_note(conn, env["target_note_id"])
                if note is not None:
                    hosts.add(note["clip_id"])
    return hosts


def _warn_non_session_route(
    plan: PushPlan,
    *,
    envelope: sqlite3.Row,
    route: str,
    host_track_id: str | None = None,
    host_kind: str | None = None,
) -> None:
    """Note why the session-clip envelope phase isn't emitting this
    envelope. 'perform' is routing information (the performed-automation
    phase owns the arc), the rest are skip-with-teaching warns."""
    target_kind = envelope["target_kind"]
    if route == "perform":
        plan.warn(
            f"envelope {envelope['id']} ({target_kind}): "
            f"host kind={host_kind!r} routes to the performed-automation "
            "phase (gesture-recorded arrangement automation), not the "
            "session-clip envelope phase."
        )
    else:
        plan.warn(
            f"envelope {envelope['id']} ({target_kind}): host track "
            f"{host_track_id} has kind={host_kind!r}, which has no push "
            "route (midi/audio hosts route per-clip when a session clip "
            "covers the span, else perform; master/group → perform). "
            "Skipping."
        )


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
        # ENV-9P4T: classify_envelope_route routes a track-hosted envelope
        # that NO single session clip covers to 'perform' (a continuous
        # arrangement ride) — such an envelope never reaches this
        # session-clip emitter. A None here means classify returned
        # 'session_clip' yet no covering placement exists: an internal
        # contract break between the two functions, which call
        # _resolve_envelope_session_clip on identical inputs. (This
        # supersedes the former no-cover skip-with-"partition-by-hand"
        # teaching — that deferred capability is now the perform route.)
        raise RuntimeError(
            f"envelope {envelope['id']} ({target_kind}): classify_envelope_"
            f"route returned 'session_clip' but no session clip on track "
            f"{host_track_at} covers beat range [{env_min:g}, {env_max:g}] "
            "— infer-from-span disagreement between classify_envelope_route "
            "and _resolve_and_translate_to_session_clip"
        )
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
    """device_parameter emission for the session-clip route — reached only
    when classify_envelope_route returns 'session_clip' (a covered midi- or
    audio-host device parameter; W4-A / W4-B). Master/group/return-side
    devices and uncovered rides route to the performed-automation phase
    (ENV-7G4K / ENV-9P4T)."""
    device_id = envelope["target_device_id"]
    chain_row = Q.get_device_parent_chain(conn, device_id)
    if chain_row is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): device "
            f"{device_id} not found; skipping"
        )
        return
    route = classify_envelope_route(conn, envelope, song_id=song_id)
    if route != "session_clip":
        # DEEP-RACK-ADDR: nested-rack params route to 'perform' (the perform
        # phase rides them via device_path); master/return hosts and
        # clip-independent (uncovered) rides also land here. The session-clip
        # phase owns none of them, so note the real route and return.
        if chain_row["parent_rack_device_id"] is not None:
            host_track_id = None
            host_kind = "nested-rack device"
        elif chain_row["parent_return_id"] is not None:
            host_track_id = None
            host_kind = "return"
        else:
            host_track_id = chain_row["parent_track_id"]
            host_kind = _track_kind_for_envelope(conn, host_track_id)
        _warn_non_session_route(
            plan, envelope=envelope, route=route,
            host_track_id=host_track_id, host_kind=host_kind,
        )
        return
    # session_clip route — a top-level midi-host device (nested params can't
    # reach here; classify routes them to perform).
    device_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device_id,
    )
    parent_track_id = chain_row["parent_track_id"]
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
            # NODE-ADDR: the device address is a `node` (top-level — nested
            # device_parameter envelopes are routed to perform by classify, so
            # this path is always a top-level track-hosted device). The clip is
            # on the same track (node.parent).
            "node": build_node_addr({"track_index": parent_at}, device_index=device_at),
            "location": "session",
            "clip_index": clip_at,
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
    route = classify_envelope_route(conn, envelope, song_id=song_id)
    if route != "session_clip":
        _warn_non_session_route(
            plan, envelope=envelope, route=route,
            host_track_id=track_id, host_kind=host_kind,
        )
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
    if host_kind == "master":
        # Safety net for legacy rows: the mutator refuses this shape (the
        # master has no sends), so it's invalid on every route.
        plan.warn(
            f"envelope {envelope['id']} (send_level): host track "
            f"{track_id} is the master, which has no sends — unauthorable "
            "on any route. Author the send ride on the source track or "
            "group instead. Skipping."
        )
        return
    route = classify_envelope_route(conn, envelope, song_id=song_id)
    if route != "session_clip":
        _warn_non_session_route(
            plan, envelope=envelope, route=route,
            host_track_id=track_id, host_kind=host_kind,
        )
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
