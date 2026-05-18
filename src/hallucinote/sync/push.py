"""DB -> Ableton planner.

Produces a list of `ToolCall` objects describing what the agent should run.
After the agent executes the plan, it calls `apply_push_results` to write
Ableton-side IDs back into the DB.

Why a plan rather than direct calls: MCP tools are invoked by the agent, not
by Python. Returning a plan keeps this layer pure, testable, and reorder-safe.

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Bindings live in `ableton_links`, not on core rows — so a song can be bound
to multiple Live sets at the same time without aliasing. Open one with
`mutations.create_ableton_session`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

from hallucinote.db import mutations as M, queries as Q
from hallucinote.db.connection import transaction

# Live's default meter when a song has no `time_signature_map` rows.
_DEFAULT_NUMERATOR = 4
_DEFAULT_DENOMINATOR = 4


@dataclass
class ToolCall:
    """One MCP tool invocation. `key` lets results be matched back to ops.

    Names are *canonical* (post-Wave-1). Agent uses `mcp_names.resolve` to
    map onto today's surface.
    """
    tool: str
    args: dict[str, Any]
    key: str  # caller-chosen identifier; used in apply_push_results
    purpose: str = ""  # human-readable hint for the agent


@dataclass
class PushPlan:
    calls: list[ToolCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # human notes / warnings

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Note conversion: DB -> MCP
# ---------------------------------------------------------------------------


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Live counts a beat as a quarter note regardless of meter, so the beat
    count per bar is `numerator * (4 / denominator)` (e.g., 6/8 -> 3 beats,
    7/4 -> 7 beats, 4/4 -> 4 beats)."""
    return numerator * (4.0 / denominator)


def _meter_at_bar(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, int]:
    """Return (numerator, denominator) effective at a 1-based bar position.

    Empty ts_points fall back to 4/4. Bars before the first map point use the
    first point's meter — matches Live's behavior for unmarked regions.
    """
    if not ts_points:
        return (_DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR)
    chosen = ts_points[0]
    for p in ts_points:
        if p["start_bar"] <= bar:
            chosen = p
        else:
            break
    return (chosen["numerator"], chosen["denominator"])


def _split_bar(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, float]:
    """Split a 1-based fractional bar position into (bar_int, beat_within_bar).

    Matches the `(bar: int 1-based, beat: float 0-based-within-bar)` shape that
    Live's MCP tools use throughout. `bar_pos=4.5` in 4/4 -> (4, 2.0).
    """
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    bar_int = int(bar_pos)
    frac = bar_pos - bar_int
    num, den = _meter_at_bar(bar_pos, ts_points)
    return bar_int, frac * _beats_per_bar(num, den)


def _position_bar_to_beats(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Convert a 1-based fractional bar position to cumulative beats from song start.

    Live's arrangement time is measured in BEATS (quarter notes) regardless of
    meter — `position_beats` on every ableton_arrangement / ableton_clip
    arrangement-side action. Inverse-ish of :func:`_split_bar`: that returns
    ``(bar_int, beat_within_bar)``; this returns the total beats from bar 1's
    downbeat to the requested fractional bar.

    Walks the time_signature_map so meter changes accumulate correctly. Bars
    before ``ts_points[0].start_bar`` use ``ts_points[0]``'s meter (matches
    :func:`_meter_at_bar`'s fallback). Empty map → 4/4 throughout.

    Examples (in 4/4):
      - ``bar_pos=1.0`` -> 0.0
      - ``bar_pos=17.0`` -> 64.0    (16 bars × 4 beats)
      - ``bar_pos=17.5`` -> 66.0    (16 bars × 4 + half-bar = 2 beats)
    """
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    if not ts_points:
        return (bar_pos - 1.0) * _beats_per_bar(
            _DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR,
        )

    beats = 0.0
    current_bar = 1.0
    current_bpb = _beats_per_bar(
        ts_points[0]["numerator"], ts_points[0]["denominator"],
    )

    for p in ts_points:
        change_at = float(p["start_bar"])
        if change_at <= current_bar:
            # Already at or past this point's bar (the canonical case for
            # ts_points[0] when its start_bar == 1.0). Adopt this point's
            # meter; nothing to accumulate.
            current_bpb = _beats_per_bar(p["numerator"], p["denominator"])
            continue
        if bar_pos < change_at:
            return beats + (bar_pos - current_bar) * current_bpb
        beats += (change_at - current_bar) * current_bpb
        current_bar = change_at
        current_bpb = _beats_per_bar(p["numerator"], p["denominator"])

    return beats + (bar_pos - current_bar) * current_bpb


def _notes_for_mcp(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB notes carry tags + extra fields; MCP wants the bare quartet."""
    return [
        {
            "pitch": n["pitch"],
            "start_time": n["start_beats"],
            "duration": n["duration_beats"],
            "velocity": n["velocity"],
            "mute": bool(n["mute"]),
        }
        for n in notes
    ]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_push_song_tracks(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Pre-pass: emit one ``ableton_track(action='create')`` call per
    unique unlinked non-master track for this song.

    W3-C — replaces the per-clip track-create emit that
    :func:`plan_push_clip` used to do. A song with 8 tracks and 32 clips
    used to produce 32 ``ableton_track(create)`` calls (with identical
    ``key=track:{track_id}`` values for each track), all of which had to
    be deduplicated by the agent. This planner emits exactly N calls for
    N unique unlinked tracks — dedupe is structural, not behavioral.

    Caller flow:
        1. ``plan = plan_push_song_tracks(conn, song_id, session_id)``
        2. Agent executes ``plan.calls`` (parallelizable — each is
           independent), captures results.
        3. ``apply_push_results(conn, results, session_id=session_id)``
           records each new ``track_index`` via ``ableton_links``.
        4. Now :func:`plan_push_clip`, :func:`plan_push_arrangement`,
           and :func:`plan_push_mix` can run — every track they touch
           is linked.

    Master tracks are skipped: master has no Live-side "create" — it
    exists implicitly in every Live set and is reached via
    ``ableton_session(set_master_property)``.

    Returns an empty plan when every non-master track is already linked
    (idempotent — safe to re-run after partial pushes).
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    for t in tracks:
        if t["kind"] == "master":
            continue
        existing = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"],
        )
        if existing is not None:
            continue
        create_args: dict[str, Any] = {
            "action": "create",
            "kind": t["kind"],
            "name": t["name"],
        }
        if t["instrument_uri"]:
            # Round-trips in the result as `instrument_uri_deferred`; agent
            # follows up with ableton_device(action='load') separately.
            create_args["instrument_uri"] = t["instrument_uri"]
        plan.add(ToolCall(
            tool="ableton_track",
            args=create_args,
            key=f"track:{t['id']}",
            purpose=(
                f"create unlinked track '{t['name']}' "
                f"(kind={t['kind']}, db_id={t['id']})"
            ),
        ))
    return plan


def plan_push_song_returns(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Pre-pass: emit one ``ableton_return(action='create')`` call per
    unique unlinked return for this song.

    Mirror of :func:`plan_push_song_tracks` for return tracks. The same
    dedupe-at-the-planner-level rationale applies: returns are
    referenced by sends and by send_level envelopes — without a
    song-level pre-pass, every per-element planner would re-emit the
    create. Idempotent across re-runs.
    """
    plan = PushPlan()
    returns = Q.get_returns_for_song(conn, song_id)
    for r in returns:
        existing = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"],
        )
        if existing is not None:
            continue
        plan.add(ToolCall(
            tool="ableton_return",
            args={"action": "create", "name": r["name"]},
            key=f"return:{r['id']}",
            purpose=f"create unlinked return '{r['name']}' (db_id={r['id']})",
        ))
    return plan


def plan_push_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of a single session clip to Ableton.

    Two cases (W3-C narrowed from three; track-creation moved to
    :func:`plan_push_song_tracks`):
      1. Clip not yet linked  -> ``ableton_clip(action='create',
         location='session', kind=…, replace=True, notes=…)``  — atomic
         single-call create+populate (Wave M+1-1).
      2. Clip already linked  -> ``ableton_clip(action='replace_notes')``
         (in-place; gap #1's renamed action, unified via Wave M-3).

    Precondition (W3-C — strict): the clip's track must already be
    linked in this session. Run :func:`plan_push_song_tracks` first to
    create+link all unlinked tracks, ``apply_push_results``, then call
    this planner. The strict raise replaces the prior silent-redundant-
    emit behavior that produced N duplicate ``ableton_track(create)``
    calls for N clips on the same unlinked track (32 calls for an
    8-track / 32-clip song; one per CLIP, not one per TRACK).
    """
    plan = PushPlan()

    clip = Q.get_clip(conn, clip_id)
    if clip is None:
        raise ValueError(f"clip {clip_id} not found")

    track_row = Q.get_track(conn, clip["track_id"])
    if track_row is None:
        raise ValueError(f"track {clip['track_id']} not found for clip {clip_id}")
    notes = Q.get_notes_for_clip(conn, clip_id)

    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_row["id"]
    )
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id
    )

    if track_at is None:
        raise ValueError(
            f"plan_push_clip: track {track_row['id']!r} ('{track_row['name']}') "
            f"is not linked in session {session_id!r}. Call "
            f"plan_push_song_tracks(conn, song_id=..., session_id=...) first "
            f"to create and link any unlinked tracks (one call per unique "
            f"track, not per clip), apply_push_results, then re-run "
            f"plan_push_clip."
        )

    if clip_at is None:
        # Wave M+1-1: atomic single-call create+populate. `replace=True`
        # makes the handler delete an occupied slot before creating, so the
        # planner doesn't have to know the slot's current state. The handler
        # returns `clip_index`, which `_LINK_KINDS["clip"]` reads to record
        # the binding via the generic apply path.
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "create",
                "location": "session",
                "kind": "midi",
                "track_index": track_at,
                "clip_index": clip["slot"],
                "length": clip["length_beats"],
                "name": clip["name"],
                "notes": _notes_for_mcp(notes),
                "replace": True,
            },
            key=f"clip:{clip_id}",
            purpose=f"create+populate session clip slot {clip['slot']} on track {track_at}",
        ))
    else:
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "replace_notes",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"replace notes in existing clip ({len(notes)} notes)",
        ))

    return plan


def plan_push_arrangement(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the arrangement build for a song.

    Strategy: for each ``arrangement_clips`` row, emit one
    ``ableton_clip(action='duplicate_to_arrangement', track_index,
    clip_index, start_beats)`` call. The agent / push-skill is responsible
    for executing them — they're reorder-safe within the planner output
    (each call addresses an independent (track, slot, position) triple)
    and Live's underlying API handles them serially.

    Pre-conditions (planner warns; doesn't fix):
      - All involved tracks have a ``track`` link in this session.
      - All involved session clips have a ``clip`` link in this session.

    Position conversion: each row's 1-based fractional ``start_bar`` is
    converted to cumulative beats from song start via
    :func:`_position_bar_to_beats`. The agent doesn't see bars; the MCP
    surface is meter-agnostic (beats throughout).

    Clear pass: not emitted here. The agent / push-skill should wipe
    existing arrangement clips on the involved tracks before running the
    plan. Adding explicit delete ops requires probing Live first (no DB
    knowledge of what's currently in the arrangement) — out of scope for
    pure-DB planners; see W3-I.

    Returns N decomposed calls. Each call's result must carry
    ``arrangement_clip_index`` so :func:`apply_push_results` can record
    the binding under the ``arrangement_clip:{db_id}`` key.
    """
    plan = PushPlan()
    arr_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arr_rows:
        plan.warn("no arrangement rows for this song")
        return plan

    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for arrangement bar→beats conversion"
        )

    emitted = 0
    track_indices_seen: set[int] = set()
    for row in arr_rows:
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
        )
        if track_at is None:
            plan.warn(
                f"arrangement_clip {row['id']}: track {row['track_id']} not linked "
                "in this session — skipping"
            )
            continue
        clip_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="clip", db_id=row["clip_id"]
        )
        if clip_at is None:
            plan.warn(
                f"arrangement_clip {row['id']}: clip {row['clip_id']} not linked "
                "in this session — skipping"
            )
            continue
        track_indices_seen.add(track_at)
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "duplicate_to_arrangement",
                "track_index": track_at,
                "clip_index": clip_at,
                "start_beats": _position_bar_to_beats(row["start_bar"], ts_points),
            },
            key=f"arrangement_clip:{row['id']}",
            purpose=(
                f"duplicate session slot {clip_at} on track {track_at} → "
                f"arrangement bar {row['start_bar']:g}"
            ),
        ))
        emitted += 1

    if emitted:
        plan.warn(
            "agent must clear existing arrangement clips on the involved tracks "
            "before running these duplicates (planner emits no pre-clear ops "
            "because it has no DB knowledge of Live's current arrangement state)"
        )
    return plan


# ---------------------------------------------------------------------------
# Score-half planners: tempo / meter / cue points / sections
# ---------------------------------------------------------------------------


def plan_push_tempo_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_tempo_point` calls — one per row in `tempo_map`.

    Positions are emitted as `(bar, beat)` matching the rest of the MCP surface
    (see mcp-requirements.md). The (bar, beat) pair is computed via the song's
    time_signature_map (defaulting to 4/4 if empty, with a warning).
    """
    plan = PushPlan()
    rows = Q.get_tempo_map(conn, song_id)
    if not rows:
        plan.warn("no tempo_map rows for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for tempo-map bar/beat split"
        )
    for r in rows:
        bar, beat = _split_bar(r["start_bar"], ts_points)
        plan.add(ToolCall(
            tool="write_tempo_point",
            args={
                "bar": bar,
                "beat": beat,
                "bpm": r["tempo_bpm"],
                "ramp": r["ramp"],
            },
            key=f"tempo_point:{r['id']}",
            purpose=f"set tempo to {r['tempo_bpm']:g} bpm at bar {r['start_bar']:g} "
                    f"(ramp={r['ramp']})",
        ))
    if len(rows) > 1 or any(r["ramp"] == "linear" for r in rows):
        plan.warn(
            "multi-point or ramped tempo maps require full tempo-automation MCP "
            "support (see docs/mcp-requirements.md, P2)"
        )
    return plan


def plan_push_time_signature_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_time_signature_point` calls — one per meter change.

    Live exposes no MCP tool for arrangement-level meter changes today; the
    planner produces canonical (bar, beat, numerator, denominator) calls and
    warns about the MCP gap so apply can no-op until support lands.
    """
    plan = PushPlan()
    rows = Q.get_time_signature_map(conn, song_id)
    if not rows:
        plan.warn("no time_signature_map rows for this song; nothing to push")
        return plan
    for r in rows:
        # A time-signature point's own position is in its own meter context —
        # use `rows` (the map itself) as the time-sig reference.
        bar, beat = _split_bar(r["start_bar"], rows)
        plan.add(ToolCall(
            tool="write_time_signature_point",
            args={
                "bar": bar,
                "beat": beat,
                "numerator": r["numerator"],
                "denominator": r["denominator"],
            },
            key=f"time_signature_point:{r['id']}",
            purpose=f"set meter to {r['numerator']}/{r['denominator']} "
                    f"at bar {r['start_bar']:g}",
        ))
    plan.warn(
        "time-signature change writes are an MCP gap "
        "(see docs/mcp-requirements.md, P2)"
    )
    return plan


def plan_push_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit a single batched ``ableton_arrangement(cue_create_batch)`` call.

    Live's MCP exposes per-cue ``ableton_arrangement(action='cue_create',
    position_beats=…, name=…)`` and a batched ``cue_create_batch`` that
    submits multiple cues in one round-trip. The batch is strictly more
    efficient (one TCP exchange instead of N) and matches the underlying
    Live API's per-cue settle cost, so the planner emits the batch form.

    Position conversion: each row's 1-based fractional ``position_bar`` is
    converted to cumulative beats from song start via
    :func:`_position_bar_to_beats`, walking the song's time_signature_map.
    Cues at bar 1.0 → ``position_beats=0.0``; downstream meter changes
    accumulate correctly.

    Sequencing precondition (W3-I): cue creation must run AFTER
    arrangement-clip placement, because Live's ``set_or_delete_cue`` is
    clamped to ``[0, song.last_event_time]``. The agent / push-skill is
    responsible for phase order; this planner emits no internal warn —
    a cue past the arrangement's extent surfaces as a teaching error
    from the handler at execution time.

    Result key: ``cue_batch:{song_id}``. The batch handler returns a list
    of per-cue results; ``apply_push_results`` consumes it via the
    existing batched-result path.
    """
    plan = PushPlan()
    rows = Q.get_cue_points(conn, song_id)
    if not rows:
        plan.warn("no cue_points for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for cue-point beat conversion"
        )

    cues = [
        {
            "position_beats": _position_bar_to_beats(r["position_bar"], ts_points),
            "name": r["name"] or "",
        }
        for r in rows
    ]
    plan.add(ToolCall(
        tool="ableton_arrangement",
        args={"action": "cue_create_batch", "cues": cues},
        key=f"cue_batch:{song_id}",
        purpose=f"create {len(cues)} cue point(s) in one batched call",
    ))
    return plan


def plan_push_sections(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Sections are DB-only metadata today — Live has no section-marker concept
    distinct from cue points. The planner emits no calls; it surfaces the
    section count as a warn so callers can decide whether to mirror sections
    as cue points themselves."""
    plan = PushPlan()
    rows = Q.get_sections_for_song(conn, song_id)
    if rows:
        plan.warn(
            f"{len(rows)} section(s) are DB-only; Live exposes no section-marker "
            "tool. Consider creating matching cue_points for visibility."
        )
    return plan


# ---------------------------------------------------------------------------
# Mix-half planner: track mixer + returns + sends
# ---------------------------------------------------------------------------


# Wave M-2 collapsed the per-property mixer surface to a single
# ableton_track(action='set_property', property=..., value=...) emitter. No
# more dict of tool-name lookups; all 6 properties go through the same shape.
# DB column → action property name (only 'pan' → 'panning' differs).
_MIXER_FIELDS: tuple[tuple[str, str], ...] = (
    ("volume",  "volume"),
    ("pan",     "panning"),
    ("mute",    "mute"),
    ("solo",    "solo"),
    ("arm",     "arm"),
    ("color",   "color"),
)


def plan_push_mix(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of mix state — track mixer + return tracks + master + sends.

    Under Wave M-2, every per-track mixer write emits a single unified
    ``ableton_track(action='set_property', property=..., value=...)`` call —
    the mute/solo/arm/color "MCP gap" disappears because the new surface
    exposes them all. Master mixer state goes through ``ableton_session``
    (Wave M-1). Returns go through ``ableton_return``.

    Pre-conditions (planner warns; doesn't fix):
      - Tracks not yet linked in this session are flagged. Track creation
        lives in ``plan_push_clip``; the agent typically pushes clips first
        to create+link tracks, then pushes mix state.
      - Unlinked returns are emitted as ``ableton_return(action='create')``
        with the recorded name; apply records the new return_index when the
        call returns.
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    returns = Q.get_returns_for_song(conn, song_id)
    sends = Q.get_sends_for_song(conn, song_id)

    if not tracks and not returns and not sends:
        plan.warn("no mix state to push for this song")
        return plan

    # ---- Tracks: every mixer field goes through ableton_track(set_property).
    for t in tracks:
        if t["kind"] == "master":
            # Master strip: no track_index. Master mixer state lives at
            # ableton_session(action='set_master_property') (Wave M-1).
            if t["volume"] is not None:
                plan.add(ToolCall(
                    tool="ableton_session",
                    args={
                        "action": "set_master_property",
                        "property": "volume",
                        "value": t["volume"],
                    },
                    key=f"master_volume:{t['id']}",
                    purpose=f"set master volume to {t['volume']:g}",
                ))
            if t["pan"] is not None:
                plan.add(ToolCall(
                    tool="ableton_session",
                    args={
                        "action": "set_master_property",
                        "property": "panning",
                        "value": t["pan"],
                    },
                    key=f"master_pan:{t['id']}",
                    purpose=f"set master pan to {t['pan']:g}",
                ))
            continue

        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "create it via plan_push_clip first, then re-run plan_push_mix"
            )
            continue

        for db_field, property_name in _MIXER_FIELDS:
            value = t[db_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool="ableton_track",
                args={
                    "action": "set_property",
                    "track_index": track_at,
                    "property": property_name,
                    "value": value,
                },
                key=f"track_{db_field}:{t['id']}",
                purpose=f"set {t['name']} {property_name} to {value}",
            ))

    # ---- Returns: create unlinked, then push mixer state.
    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            plan.add(ToolCall(
                tool="ableton_return",
                args={"action": "create", "name": r["name"]},
                key=f"return:{r['id']}",
                purpose=f"create return track '{r['name']}'",
            ))
            plan.warn(
                f"return {r['name']!r} not linked yet; apply_push_results will "
                "record the new return_index when the call returns"
            )
            continue

        for db_field, property_name in _MIXER_FIELDS:
            # Returns have no 'arm' — schema enum on ableton_return excludes it.
            if property_name == "arm":
                continue
            if db_field not in r.keys():
                continue
            value = r[db_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool="ableton_return",
                args={
                    "action": "set_property",
                    "return_index": return_at,
                    "property": property_name,
                    "value": value,
                },
                key=f"return_{db_field}:{r['id']}",
                purpose=f"set return '{r['name']}' {property_name} to {value}",
            ))

    # ---- Sends: cross product of (linked track) x (linked return).
    for s in sends:
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=s["from_track_id"]
        )
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=s["to_return_id"]
        )
        if track_at is None or return_at is None:
            plan.warn(
                f"send {s['from_track_name']} -> {s['return_name']}: missing link "
                f"(track={track_at}, return={return_at}); skipping"
            )
            continue
        plan.add(ToolCall(
            tool="ableton_track",
            args={
                "action": "set_send",
                "track_index": track_at,
                "return_index": return_at,
                "value": s["level"],
            },
            key=f"send:{s['from_track_id']}:{s['to_return_id']}",
            purpose=f"send {s['from_track_name']} -> {s['return_name']} = {s['level']:g}",
        ))

    return plan


# ---------------------------------------------------------------------------
# Mix-half planner: device chains
# ---------------------------------------------------------------------------


def plan_push_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of device chains — instruments + effects on tracks/returns
    plus their dialed parameters.

    Strategy (Wave M-4: unified ableton_device tool):
      1. For each linked track / return, walk its top-level device chain in
         position order.
      2. For each device, check the `ableton_links` projection for a 'device'
         binding. If missing, emit `ableton_device(action='load', ...)` with
         the parent-addressing (`track_index` OR `return_index`) and warn —
         parameter writes for that device have to wait for a second pass
         after the link lands.
      3. For each linked device, emit
         `ableton_device(action='set_parameter', ...)` per dialed param
         that carries a continuous `value_normalized` (`value_type='continuous'`,
         value stringified on the wire for schema uniformity between
         continuous and enum). Discrete-enum params (Filter Type = "Lowpass"
         etc.) have no normalized form — surface them as a warn so the
         agent / UI knows the gap. Nested rack chains aren't pushed in
         chunk 4a (snapshot doesn't capture them).
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    returns = Q.get_returns_for_song(conn, song_id)

    if not tracks and not returns:
        plan.warn("no devices to push for this song")
        return plan

    for t in tracks:
        if t["kind"] == "master":
            # Master tracks don't carry devices via the tracks table; real
            # returns are handled in the loop below.
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            chains = Q.get_device_chains_for_track(conn, t["id"])
            if chains:
                plan.warn(
                    f"track {t['name']!r} not linked in session — "
                    f"{len(chains)} chain(s) skipped; create the track first"
                )
            continue
        for chain in Q.get_device_chains_for_track(conn, t["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_device_calls(
                    plan, conn,
                    session_id=session_id,
                    parent_kind="track",
                    parent_at=track_at,
                    parent_name=t["name"],
                    device=device,
                )

    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            chains = Q.get_device_chains_for_return(conn, r["id"])
            if chains:
                plan.warn(
                    f"return {r['name']!r} not linked in session — "
                    f"{len(chains)} chain(s) skipped; create the return first"
                )
            continue
        for chain in Q.get_device_chains_for_return(conn, r["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_device_calls(
                    plan, conn,
                    session_id=session_id,
                    parent_kind="return",
                    parent_at=return_at,
                    parent_name=r["name"],
                    device=device,
                )

    return plan


def _emit_device_calls(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    parent_kind: str,         # 'track' | 'return'
    parent_at: int,
    parent_name: str,
    device: sqlite3.Row,
) -> None:
    """Emit load + parameter calls for a single device. If the device isn't
    yet linked in this session, emit the load and skip parameter writes —
    the agent must call apply_push_results to record the new device_index
    before parameters can be addressed."""
    device_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device["id"]
    )
    parent_arg = "track_index" if parent_kind == "track" else "return_index"
    if device_at is None:
        # Wave M-4: unified ableton_device(action='load') replaces the
        # legacy fork's load_device / load_device_on_return narrow tools.
        # The handler accepts a Live device class name as `kind` and an
        # optional Live browser URI as `preset_uri`. Live 12.4 has no
        # public reorder API — devices always land at the END of the
        # destination chain, so the planner does not emit `position`.
        # If the DB chain order needs to be enforced, push devices in the
        # order they appear in the chain (position-asc) and Live's
        # tail-append will match.
        load_args = {
            parent_arg: parent_at,
            "action": "load",
            "kind": device["kind"],
        }
        if device["preset_uri"] is not None:
            load_args["preset_uri"] = device["preset_uri"]
        plan.add(ToolCall(
            tool="ableton_device",
            args=load_args,
            key=f"device:{device['id']}",
            purpose=(
                f"load {device['kind']} '{device['display_name']}' "
                f"at position {device['position']} on {parent_kind} {parent_name!r}"
            ),
        ))
        plan.warn(
            f"device {device['display_name']!r} on {parent_kind} {parent_name!r} "
            "not linked yet; rerun plan_push_devices after apply_push_results "
            "records the device_index"
        )
        return

    params = Q.get_device_parameters(conn, device["id"])
    enum_skipped: list[str] = []
    for p in params:
        if p["value_normalized"] is None:
            enum_skipped.append(p["name"])
            continue
        # Wave M-4: unified ableton_device(action='set_parameter') replaces
        # set_device_parameter / set_return_device_parameter narrow tools.
        # value goes on the wire as a string so enum and continuous share
        # one type (handler coerces back per value_type).
        plan.add(ToolCall(
            tool="ableton_device",
            args={
                "action": "set_parameter",
                parent_arg: parent_at,
                "device_index": device_at,
                "parameter_name": p["name"],
                "value": str(p["value_normalized"]),
                "value_type": "continuous",
            },
            key=f"device_parameter:{device['id']}:{p['name']}",
            purpose=(
                f"{parent_name} / {device['display_name']} / "
                f"{p['name']} = {p['value_display']} "
                f"(normalized {p['value_normalized']:g})"
            ),
        ))
    if enum_skipped:
        plan.warn(
            f"device {device['display_name']!r} on {parent_kind} {parent_name!r}: "
            f"{len(enum_skipped)} enum-only param(s) skipped "
            f"({', '.join(enum_skipped[:3])}{'...' if len(enum_skipped) > 3 else ''}) "
            "— no normalized form, MCP can't write discrete enums"
        )


# ---------------------------------------------------------------------------
# Mix-half planner: automation envelopes
# ---------------------------------------------------------------------------
#
# Wave M-4: all seven envelope target families flow through one unified
# tool: `ableton_automation(action='write_envelope', target_kind=...)`.
# One ToolCall per envelope, breakpoints inline.
#
#   target_kind='clip_cc'           track_index, location='session', clip_index,
#                                   cc_number, breakpoints
#   target_kind='clip_pitch_bend'   track_index, location='session', clip_index,
#                                   breakpoints
#   target_kind='note_expression'   track_index, location='session', clip_index,
#                                   note_pitch, note_start_beats, axis,
#                                   breakpoints
#   target_kind='device_parameter'  (track_index | return_index), device_index,
#                                   parameter_name, breakpoints
#   target_kind='mixer_volume'      track_index, breakpoints
#   target_kind='mixer_pan'         track_index, breakpoints
#   target_kind='send_level'        track_index, return_index, breakpoints
#
# Breakpoint shape (inline list): {time_beats, value, curve}. The DB stores
# `curve_kind`; the wire field is `curve` to match the MCP-side handler's
# enum naming. The rename happens in `_breakpoints_for_mcp`.


def _breakpoints_for_mcp(bps: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert DB breakpoint rows to the wire shape that
    ``ableton_automation(action='write_envelope')`` expects.

    Field renames: ``curve_kind`` → ``curve`` (the MCP-side handler uses
    ``curve`` to match its enum naming). DB-side keeps ``curve_kind`` since
    it disambiguates from other "kind" columns; the rename happens at the
    wire boundary.
    """
    return [
        {
            "time_beats": float(bp["time_beats"]),
            "value": float(bp["value"]),
            "curve": bp["curve_kind"],
        }
        for bp in bps
    ]


def plan_push_envelopes(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of every envelope in a song. One canonical call per
    envelope with breakpoints inline. Envelopes whose target isn't linked in
    the session yet are skipped with a warning; envelopes with zero
    breakpoints are skipped with a warning (nothing to push)."""
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

        if target_kind in ("clip_cc", "clip_pitch_bend"):
            _emit_clip_envelope(
                plan, conn,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind == "note_expression":
            _emit_note_expression_envelope(
                plan, conn,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind == "device_parameter":
            _emit_device_parameter_envelope(
                plan, conn,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind in ("mixer_volume", "mixer_pan"):
            _emit_mixer_envelope(
                plan, conn,
                session_id=session_id,
                envelope=env,
                breakpoints_mcp=bps_mcp,
            )
        elif target_kind == "send_level":
            _emit_send_envelope(
                plan, conn,
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


def _emit_clip_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """clip_cc + clip_pitch_bend emission."""
    clip_id = envelope["target_clip_id"]
    track_at, clip_at = _clip_and_track_indices(
        conn, session_id=session_id, clip_id=clip_id
    )
    if track_at is None or clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): "
            f"clip {clip_id} not linked in session (track={track_at}, "
            f"clip={clip_at}); skipping"
        )
        return
    if envelope["target_kind"] == "clip_cc":
        # Mutator validated parameter_path as an int in [0,127] at create time.
        cc_number = int(envelope["parameter_path"])
        plan.add(ToolCall(
            tool="ableton_automation",
            args={
                "action": "write_envelope",
                "target_kind": "clip_cc",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
                "cc_number": cc_number,
                "breakpoints": breakpoints_mcp,
            },
            key=f"envelope:{envelope['id']}",
            purpose=(
                f"clip_cc CC{cc_number} on clip {clip_at}: "
                f"{len(breakpoints_mcp)} breakpoint(s)"
            ),
        ))
    else:
        plan.add(ToolCall(
            tool="ableton_automation",
            args={
                "action": "write_envelope",
                "target_kind": "clip_pitch_bend",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
                "breakpoints": breakpoints_mcp,
            },
            key=f"envelope:{envelope['id']}",
            purpose=(
                f"clip_pitch_bend on clip {clip_at}: "
                f"{len(breakpoints_mcp)} breakpoint(s)"
            ),
        ))


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
    note_row = conn.execute(
        """SELECT n.pitch, n.start_beats, n.clip_id
           FROM notes n WHERE n.id = ?""",
        (envelope["target_note_id"],),
    ).fetchone()
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


def _emit_device_parameter_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """device_parameter emission — track-side or return-side depending on the
    device's parent chain. Requires both the parent (track/return) AND the
    device itself to be linked."""
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
            f"device {device_id} — push not yet supported (MCP gap)"
        )
        return
    if chain_row["parent_track_id"] is not None:
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
        plan.add(ToolCall(
            tool="ableton_automation",
            args={
                "action": "write_envelope",
                "target_kind": "device_parameter",
                "track_index": parent_at,
                "device_index": device_at,
                "parameter_name": envelope["parameter_path"],
                "breakpoints": breakpoints_mcp,
            },
            key=f"envelope:{envelope['id']}",
            purpose=(
                f"device_parameter {envelope['parameter_path']} on track "
                f"device {device_at}: {len(breakpoints_mcp)} breakpoint(s)"
            ),
        ))
    else:
        # parent_return_id is set (CHECK ensures one of the three).
        parent_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return",
            db_id=chain_row["parent_return_id"],
        )
        if parent_at is None or device_at is None:
            plan.warn(
                f"envelope {envelope['id']} (device_parameter): return or "
                f"device not linked (return={parent_at}, device={device_at}); "
                "skipping"
            )
            return
        plan.add(ToolCall(
            tool="ableton_automation",
            args={
                "action": "write_envelope",
                "target_kind": "device_parameter",
                "return_index": parent_at,
                "device_index": device_at,
                "parameter_name": envelope["parameter_path"],
                "breakpoints": breakpoints_mcp,
            },
            key=f"envelope:{envelope['id']}",
            purpose=(
                f"device_parameter {envelope['parameter_path']} on return "
                f"device {device_at}: {len(breakpoints_mcp)} breakpoint(s)"
            ),
        ))


def _emit_mixer_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """mixer_volume + mixer_pan emission."""
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
    # Wave M-4: mixer_volume / mixer_pan collapse into one
    # ableton_automation(action='write_envelope', target_kind=...) shape.
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": envelope["target_kind"],
            "track_index": track_at,
            "breakpoints": breakpoints_mcp,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"{envelope['target_kind']} on track {track_at}: "
            f"{len(breakpoints_mcp)} breakpoint(s)"
        ),
    ))


def _emit_send_envelope(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    envelope: sqlite3.Row,
    breakpoints_mcp: list[dict[str, Any]],
) -> None:
    """send_level emission — addressed by (track, return) pair."""
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track",
        db_id=envelope["target_track_id"],
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
    plan.add(ToolCall(
        tool="ableton_automation",
        args={
            "action": "write_envelope",
            "target_kind": "send_level",
            "track_index": track_at,
            "return_index": return_at,
            "breakpoints": breakpoints_mcp,
        },
        key=f"envelope:{envelope['id']}",
        purpose=(
            f"send_level track {track_at} -> return {return_at}: "
            f"{len(breakpoints_mcp)} breakpoint(s) (MCP gap)"
        ),
    ))


# ---------------------------------------------------------------------------
# Result application
# ---------------------------------------------------------------------------


# Key kinds that record an `ableton_links` binding when the agent reports
# success. Each entry maps the `ToolCall.key` prefix to (db_kind, result field
# the agent's result dict must carry).
_LINK_KINDS: dict[str, tuple[str, str]] = {
    "track":            ("track",            "track_index"),
    "clip":             ("clip",             "clip_index"),
    "arrangement_clip": ("arrangement_clip", "arrangement_clip_index"),
    "return":           ("return",           "return_index"),
    "device":           ("device",           "device_index"),
    # Envelopes (Wave M-4: unified ableton_automation(action='write_envelope')).
    # The handler returns an `envelope_index` so the planner can re-address
    # the envelope on subsequent pushes (clear-and-rewrite vs. update-in-
    # place). When the result dict omits the field, apply_push_results
    # skips the link.
    "envelope":         ("envelope",         "envelope_index"),
}

# Key kinds that have no DB binding to record but are valid acks — the planner
# emits them and the agent reports success/failure, but hallucinote has nothing
# to write. Membership here is a contract: every key kind the planner emits
# MUST appear in either `_LINK_KINDS` or `_ACK_ONLY_KINDS`, or
# `apply_push_results` raises. This makes the dispatch surface auditable: when
# a planner grows a new key kind, the developer is forced to declare its
# resolution here, which surfaces silent-drop bugs at write time.
_ACK_ONLY_KINDS: frozenset[str] = frozenset({
    # Chunk 2 (score). W3-D dropped `arrangement_batch` (the planner now
    # emits N `arrangement_clip:` calls directly; each has its own
    # binding via _LINK_KINDS). W3-B dropped per-cue `cue_point` in
    # favor of the single batched `cue_batch:` key.
    "cue_batch",             # ableton_arrangement(cue_create_batch) — handler returns list of per-cue results
    "tempo_point",           # write_tempo_point (emulator placeholder)
    "time_signature_point",  # write_time_signature_point (emulator placeholder)
    # Chunk 3 (mix) → Wave M-2: all six mixer fields go through the unified
    # ableton_track(action='set_property') call. The key prefixes here stay
    # the same (volume/pan/mute/solo/arm/color) so apply matches by what the
    # planner emits, but the underlying tool is now uniform.
    "track_volume",
    "track_pan",
    "track_mute",
    "track_solo",
    "track_arm",
    "track_color",
    # Wave M-2 return-track mixer state — ack-only (no binding to record;
    # the return's index is already known once linked). All five fields go
    # through ableton_return(set_property) with the same shape as the
    # track equivalents. `return_mute`/`return_solo` enabled M+1-4 with
    # the schema growing nullable mute/solo columns.
    "return_volume",
    "return_pan",
    "return_mute",
    "return_solo",
    "return_color",
    # Master is reached via ableton_session(set_master_property) — M-1.
    "master_volume",
    "master_pan",
    "send",
    # Chunk 4a (devices)
    "device_parameter",      # ableton_device(action='set_parameter') for tracks + returns (Wave M-4)
})


def apply_push_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """After the agent runs the plan, feed structured results back here so the
    DB knows what's now in Ableton. Bindings are recorded in `ableton_links`
    for `session_id`, not on core rows.

    Each result dict shape:
        {
          "key": "<the ToolCall.key from the plan>",
          "ok": bool,
          "tool": "<canonical tool name>",
          "result": { ... tool-specific shape ... },
          "error": "...optional..."
        }

    Dispatch is table-driven: see `_LINK_KINDS` (writes a link binding) and
    `_ACK_ONLY_KINDS` (no DB write). An unknown kind raises `ValueError` so a
    new planner-emitted key kind can't silently no-op past this layer.

    Failed results (`ok=False`) are skipped — the agent layer is the source
    of truth for tool-side errors; hallucinote records nothing for them.
    """
    with transaction(conn):
        for r in results:
            if not r.get("ok"):
                continue
            key = r.get("key", "")
            kind, _, db_id = key.partition(":")
            if not kind:
                raise ValueError(f"push result missing 'key': {r!r}")

            if kind in _ACK_ONLY_KINDS:
                continue

            if kind in _LINK_KINDS:
                if not db_id:
                    raise ValueError(
                        f"push result key {key!r} missing db_id after {kind!r}:"
                    )
                db_kind, result_field = _LINK_KINDS[kind]
                res = r.get("result") or {}
                if result_field not in res:
                    # Tool ran but didn't return the binding field (e.g.
                    # ableton_clip(action='replace_notes') for `clip:` keys —
                    # no new index to record). Skip; nothing to link.
                    continue
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind=db_kind,
                    db_id=db_id,
                    ableton_index=res[result_field],
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
                continue

            raise ValueError(
                f"unknown push result key kind {kind!r} (full key={key!r}). "
                f"Declare it in _LINK_KINDS or _ACK_ONLY_KINDS in sync/push.py."
            )
