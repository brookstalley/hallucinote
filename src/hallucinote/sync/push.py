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

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, asdict
from typing import Any

from hallucinote.capture import strip_return_slot_prefix
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

    Pre-conditions (W10-G post-Wave-0): unlinked deps skip-and-warn
    instead of raising. The prior strict-raise contract (W3-C/F) was
    correct in intent but unfriendly in practice — Wave 0's full-band-rock
    canary surfaced this as a Python traceback through the CLI when an
    earlier phase failed partway. W10-G normalizes phase-planner partial-
    state behavior: every planner skips-with-note, matching the existing
    ``plan_push_envelopes`` and ``plan_push_devices`` patterns. The agent
    sees actionable notes per skipped row and continues; nothing in Live
    gets half-built because the row simply isn't emitted as a call.

    Idempotency (W10-A): each row whose ``arrangement_clip`` link is
    already recorded in ``ableton_links`` is silently skipped. Without
    this, re-running a successful push would silently duplicate every
    arrangement placement (the canary triage Group C / C-original). The
    skip count surfaces as a tracking warn so the agent / UI can show
    "nothing to do" instead of going dark.

    Position conversion: each row's 1-based fractional ``start_bar`` is
    converted to cumulative beats from song start via
    :func:`_position_bar_to_beats`. The agent doesn't see bars; the MCP
    surface is meter-agnostic (beats throughout).

    Clear pass: not emitted here. When unlinked rows exist (first push,
    or partial-apply recovery), the agent / push-skill should wipe
    existing arrangement clips on the involved tracks before running
    the plan. The planner can't emit a pre-clear: no MCP
    ``arrangement_clip_delete`` action exists and the planner has no DB
    knowledge of Live's current arrangement state. The idempotent-skip
    above means this only matters for genuinely-new placements; see
    W3-I for the long-term direction.

    Returns N decomposed calls (one per row whose track + clip are both
    linked AND whose arrangement_clip link is NOT yet recorded). Each
    call's result must carry ``arrangement_clip_index`` so
    :func:`apply_push_results` can record the binding under the
    ``arrangement_clip:{db_id}`` key.
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

    already_linked = 0
    for row in arr_rows:
        # W10-A: re-pushes must be idempotent. apply_push_results writes
        # an `arrangement_clip` link after a successful duplicate; if it
        # exists, the placement is already in Live and re-emitting would
        # silently double the clip on every re-run.
        arr_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="arrangement_clip",
            db_id=row["id"],
        )
        if arr_at is not None:
            already_linked += 1
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
        )
        if track_at is None:
            plan.warn(
                f"arrangement_clip {row['id']!r}: track {row['track_id']!r} "
                f"not linked in session {session_id!r}. Run plan_push_song_tracks "
                f"+ apply_push_results before this phase to surface the link. "
                f"Skipping this placement."
            )
            continue
        clip_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="clip", db_id=row["clip_id"]
        )
        if clip_at is None:
            plan.warn(
                f"arrangement_clip {row['id']!r}: session clip {row['clip_id']!r} "
                f"not linked in session {session_id!r}. Run the clip-create "
                f"phase + apply_push_results to surface the link. "
                f"Skipping this placement."
            )
            continue
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

    if already_linked:
        # Surface the idempotent skip so the agent/UI can show
        # "nothing to do" instead of going silent.
        plan.warn(
            f"{already_linked} arrangement placement(s) already linked "
            f"in session {session_id!r} — already in the arrangement, "
            "skipping (idempotent re-push)"
        )
    if plan.calls:
        # Post-W10-A this warn fires for the unlinked-placements path
        # only — first push, or a partial-apply recovery where some
        # placements landed in Live but apply_push_results hadn't yet
        # written their bindings. The agent should ensure those slots
        # are empty in Live before running the duplicates (the planner
        # can't emit a pre-clear: no MCP `arrangement_clip_delete`
        # action exists, and the planner has no DB knowledge of Live's
        # current arrangement state regardless).
        plan.warn(
            "agent must clear existing arrangement clips on the involved tracks "
            "before running these duplicates (planner emits no pre-clear ops "
            "because no MCP arrangement-clip-delete action exists and the "
            "planner has no DB knowledge of Live's current arrangement state)"
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
    """Emit `ableton_session(set_tempo)` for the bar-1 row; warn for the rest.

    Live exposes `Song.tempo` as a single global value (settable via
    `ableton_session(action='set_tempo')`). Per-bar tempo automation is a
    real MCP gap — `ableton_automation` has no `song_tempo` target_kind
    (see hallucinote_mcp/.../guides/gaps.md "Arrangement-level tempo /
    signature automation"). Any tempo_map row at start_bar != 1.0 is
    therefore skipped with a warn.
    """
    plan = PushPlan()
    rows = Q.get_tempo_map(conn, song_id)
    if not rows:
        plan.warn("no tempo_map rows for this song; nothing to push")
        return plan
    bar_1 = next((r for r in rows if float(r["start_bar"]) == 1.0), None)
    if bar_1 is not None:
        plan.add(ToolCall(
            tool="ableton_session",
            args={"action": "set_tempo", "bpm": bar_1["tempo_bpm"]},
            key=f"tempo_point:{bar_1['id']}",
            purpose=f"set global tempo to {bar_1['tempo_bpm']:g} bpm",
        ))
    else:
        plan.warn(
            "tempo_map has no row at start_bar=1.0 — global tempo not set "
            "(Live's set_tempo only addresses the bar-1 value)"
        )
    non_bar_1 = [r for r in rows if float(r["start_bar"]) != 1.0]
    if non_bar_1:
        plan.warn(
            f"per-bar tempo automation is an MCP gap on Live 12.4 — "
            f"ableton_automation has no 'song_tempo' target_kind "
            f"(see hallucinote_mcp/.../guides/gaps.md); "
            f"{len(non_bar_1)} non-bar-1 tempo_map rows skipped"
        )
    return plan


def plan_push_time_signature_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit `ableton_session(set_signature)` for the bar-1 row; warn the rest.

    Symmetric with `plan_push_tempo_map`. Live's `Song.signature_numerator` /
    `signature_denominator` are the global meter (settable via
    `ableton_session(action='set_signature')`). Per-bar meter automation
    is a real MCP gap — `ableton_automation` has no `song_signature`
    target_kind (see hallucinote_mcp/.../guides/gaps.md).
    """
    plan = PushPlan()
    rows = Q.get_time_signature_map(conn, song_id)
    if not rows:
        plan.warn("no time_signature_map rows for this song; nothing to push")
        return plan
    bar_1 = next((r for r in rows if float(r["start_bar"]) == 1.0), None)
    if bar_1 is not None:
        plan.add(ToolCall(
            tool="ableton_session",
            args={
                "action": "set_signature",
                "numerator": bar_1["numerator"],
                "denominator": bar_1["denominator"],
            },
            key=f"time_signature_point:{bar_1['id']}",
            purpose=(
                f"set global meter to "
                f"{bar_1['numerator']}/{bar_1['denominator']}"
            ),
        ))
    else:
        plan.warn(
            "time_signature_map has no row at start_bar=1.0 — global meter "
            "not set (Live's set_signature only addresses the bar-1 value)"
        )
    non_bar_1 = [r for r in rows if float(r["start_bar"]) != 1.0]
    if non_bar_1:
        plan.warn(
            f"per-bar meter automation is an MCP gap on Live 12.4 — "
            f"ableton_automation has no 'song_signature' target_kind "
            f"(see hallucinote_mcp/.../guides/gaps.md); "
            f"{len(non_bar_1)} non-bar-1 time_signature_map rows skipped"
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
    responsible for phase order; a cue past the arrangement's extent
    will surface as a teaching error from the handler at execution time.

    Plan-time visibility (Wave 0 paper-cut, full-band-rock runbook step
    7e): when any cue's ``position_bar`` exceeds ``max(arrangement_clips
    .end_bar)`` — the DB's planned arrangement extent — emit a warn so
    the agent / user sees the prerequisite issue before round-tripping
    to Live. An empty arrangement gets a distinct, more descriptive warn
    naming the missing prereq instead of a generic extent-exceeded
    message.

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

    # Plan-time arrangement-extent check. The DB-side max end_bar is the
    # PLANNED extent — if arrangement is pushed in the same plan_push_song
    # cycle, Live's last_event_time will match this by the time cues run.
    arrangement_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arrangement_rows:
        plan.warn(
            f"{len(rows)} cue point(s) but the DB has no arrangement_clips — "
            "Live's set_or_delete_cue is clamped to [0, last_event_time], so "
            "every cue past bar 1 will fail. Push arrangement first, OR add "
            "arrangement_clips rows covering each cue's position_bar."
        )
    else:
        max_end_bar = max(float(r["end_bar"]) for r in arrangement_rows)
        late_cues = [r for r in rows if float(r["position_bar"]) > max_end_bar]
        if late_cues:
            preview = ", ".join(
                f"{r['name'] or '(unnamed)'}@bar{float(r['position_bar']):.2f}"
                for r in late_cues[:5]
            )
            ellipsis = " ..." if len(late_cues) > 5 else ""
            plan.warn(
                f"{len(late_cues)} of {len(rows)} cue(s) sit past the DB's "
                f"arrangement extent (max end_bar={max_end_bar:.2f}): "
                f"[{preview}{ellipsis}]. Live's set_or_delete_cue is clamped "
                "to [0, last_event_time]; these cues will fail unless "
                "arrangement is extended to cover them first."
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
    # W13-B (v0.9.0): placeholder devices represent an author-intentional
    # empty slot. Push leaves the chain position empty; the consumer
    # picks an instrument/effect to fill it. Skip cleanly with a warn so
    # the agent UI surfaces the gap.
    if device["kind"] == "placeholder":
        plan.warn(
            f"placeholder device {device['display_name']!r} at position "
            f"{device['position']} on {parent_kind} {parent_name!r} — "
            "skipping load (author left this slot intentionally empty; "
            "load any instrument/effect there in Live before producing)"
        )
        return
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
        # Sweep B: preset_query (portable) takes precedence over preset_uri
        # (per-machine). The MCP load handler refuses if both are set, so
        # the planner must pick one. Composer's expressed preference wins.
        preset_query_raw = (
            device["preset_query"] if "preset_query" in device.keys() else None
        )
        if preset_query_raw is not None:
            try:
                load_args["preset_query"] = json.loads(preset_query_raw)
            except (json.JSONDecodeError, TypeError) as exc:
                plan.warn(
                    f"device {device['display_name']!r} on {parent_kind} "
                    f"{parent_name!r}: stored preset_query is not valid JSON "
                    f"({exc}); falling back to preset_uri / kind-only load"
                )
                if device["preset_uri"] is not None:
                    load_args["preset_uri"] = device["preset_uri"]
        elif device["preset_uri"] is not None:
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
    row = conn.execute(
        "SELECT kind FROM tracks WHERE id = ?", (track_id,),
    ).fetchone()
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


@dataclass
class _CoveringPlacement:
    """An arrangement_clip placement that covers an envelope's beat range.

    ``clip_id`` is the source session clip; ``start_beats`` is the
    placement's arrangement-time offset, which becomes the subtractive
    offset for converting envelope time_beats → clip-local time_beats.
    ``other_placement_starts`` lists the arrangement starts of OTHER
    placements of the same source session clip — those will also receive
    the envelope as snapshot copies after ``duplicate_to_arrangement``
    fires (W4-A finding: duplicate is a snapshot copy, not a live link).

    W4-B defensive-warn fields:
      - ``other_covering_clip_ids``: other DISTINCT session clips on the
        same track whose arrangement-time range also covered the envelope.
        Non-empty means the planner had to disambiguate; the warn names
        all overlapping clips so the author can resolve the ambiguity
        DB-side.
      - ``trimmed_end_beats``: when the placement's ``end_bar`` is
        SHORTER than the source clip's natural length, this is the
        arrangement-time end of the trimmed placement. None when the
        placement isn't trimmed. Used to warn when ``env_max`` exceeds
        the trimmed extent (the envelope WOULD fit the un-trimmed clip
        but won't play past the trim point in this placement).
    """
    clip_id: str
    start_beats: float
    other_placement_starts: list[float]
    other_covering_clip_ids: list[str] = field(default_factory=list)
    trimmed_end_beats: float | None = None


def _resolve_envelope_session_clip(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    target_track_id: str,
    env_min: float,
    env_max: float,
) -> _CoveringPlacement | None:
    """Find an arrangement_clip placement on ``target_track_id`` whose
    arrangement-time range covers [env_min, env_max]. Returns the source
    session clip + arrangement offset, or None if no placement covers.

    Coverage uses the SOURCE session clip's ``length_beats`` rather than
    the placement's ``end_bar``: ``duplicate_to_arrangement`` creates an
    arrangement clip of the source's natural length (W4-A finding), and
    envelopes are bound to clip-local [0, length_beats]. A placement
    whose ``end_bar`` trims the clip shorter than its source length
    cannot host envelope breakpoints past ``end_bar``, but the source
    clip's full length is what the session clip exposes for envelope
    addressing.
    """
    rows = conn.execute(
        """SELECT a.id, a.clip_id, a.start_bar, a.end_bar, c.length_beats
           FROM arrangement_clips a
           JOIN clips c ON c.id = a.clip_id
           WHERE a.track_id = ?
           ORDER BY a.start_bar, a.id""",
        (target_track_id,),
    ).fetchall()
    if not rows:
        return None
    ts_points = Q.get_time_signature_map(conn, song_id)
    matched = None
    matched_start = None
    matched_trimmed_end: float | None = None
    other_covering_clip_ids: list[str] = []
    for r in rows:
        start_b = _position_bar_to_beats(r["start_bar"], ts_points)
        source_end_b = start_b + float(r["length_beats"])
        if not (env_min >= start_b and env_max <= source_end_b):
            continue
        if matched is None:
            matched = r
            matched_start = start_b
            placement_end_b = _position_bar_to_beats(r["end_bar"], ts_points)
            if placement_end_b < source_end_b:
                matched_trimmed_end = placement_end_b
        elif r["clip_id"] != matched["clip_id"]:
            # A DIFFERENT distinct session clip on the same track also
            # covers the envelope's range. W4-B defensive warn — the
            # planner picks the earliest by start_bar, but ambiguity is
            # worth surfacing.
            if r["clip_id"] not in other_covering_clip_ids:
                other_covering_clip_ids.append(r["clip_id"])
    if matched is None:
        return None
    others = [
        _position_bar_to_beats(r["start_bar"], ts_points)
        for r in rows
        if r["clip_id"] == matched["clip_id"] and r["id"] != matched["id"]
    ]
    return _CoveringPlacement(
        clip_id=matched["clip_id"],
        start_beats=matched_start,
        other_placement_starts=others,
        other_covering_clip_ids=other_covering_clip_ids,
        trimmed_end_beats=matched_trimmed_end,
    )


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


def _envelope_beat_range(
    breakpoints_mcp: list[dict[str, Any]],
) -> tuple[float, float]:
    """Return (min, max) ``time_beats`` across the breakpoints."""
    times = [float(bp["time_beats"]) for bp in breakpoints_mcp]
    return min(times), max(times)


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
    env_min, env_max = _envelope_beat_range(breakpoints_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=parent_track_id,
        env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} (device_parameter): no arrangement "
            f"clip on track {parent_at} covers beat range [{env_min:g}, "
            f"{env_max:g}]; Live 12.4 requires session-clip routing for "
            "device_parameter envelopes (W4-B). Options: (a) extend or "
            "split an existing session clip on this track to cover the "
            "range, (b) add an arrangement_clip placement that fully spans "
            f"[{env_min:g}, {env_max:g}], or (c) partition the envelope by "
            "hand into per-section sub-envelopes whose ranges each fit a "
            "session clip. Auto-partition is v1.1 scope (W10-F follow-up). "
            "Skipping."
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
    local_bps = _clip_local_breakpoints(breakpoints_mcp, placement.start_beats)
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
    _warn_lossy_curve_hints(plan, envelope=envelope, breakpoints_mcp=local_bps)
    _warn_extra_placements(plan, envelope=envelope, placement=placement)
    _warn_multiple_covering_clips(plan, envelope=envelope, placement=placement)
    _warn_trimmed_placement(
        plan, envelope=envelope, placement=placement, env_max=env_max,
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
    env_min, env_max = _envelope_beat_range(breakpoints_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=track_id,
        env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): no "
            f"arrangement clip on track {track_at} covers beat range "
            f"[{env_min:g}, {env_max:g}]; Live 12.4 requires session-clip "
            f"routing for {envelope['target_kind']} envelopes (W4-B). "
            "Options: (a) extend or split an existing session clip on "
            "this track to cover the range, (b) add an arrangement_clip "
            f"placement that fully spans [{env_min:g}, {env_max:g}], or "
            "(c) partition the envelope by hand into per-section "
            "sub-envelopes whose ranges each fit a session clip. "
            "Auto-partition is v1.1 scope (W10-F follow-up). Skipping."
        )
        return
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=placement.clip_id,
    )
    if clip_at is None:
        plan.warn(
            f"envelope {envelope['id']} ({envelope['target_kind']}): "
            f"session clip {placement.clip_id} (covering placement) not "
            "linked; skipping"
        )
        return
    local_bps = _clip_local_breakpoints(breakpoints_mcp, placement.start_beats)
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
    _warn_lossy_curve_hints(plan, envelope=envelope, breakpoints_mcp=local_bps)
    _warn_extra_placements(plan, envelope=envelope, placement=placement)
    _warn_multiple_covering_clips(plan, envelope=envelope, placement=placement)
    _warn_trimmed_placement(
        plan, envelope=envelope, placement=placement, env_max=env_max,
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
    env_min, env_max = _envelope_beat_range(breakpoints_mcp)
    placement = _resolve_envelope_session_clip(
        conn, song_id=song_id,
        target_track_id=track_id,
        env_min=env_min, env_max=env_max,
    )
    if placement is None:
        plan.warn(
            f"envelope {envelope['id']} (send_level): no arrangement clip "
            f"on track {track_at} covers beat range [{env_min:g}, "
            f"{env_max:g}]; Live 12.4 requires session-clip routing for "
            "send_level envelopes (W4-B). Options: (a) extend or split an "
            "existing session clip on this track to cover the range, "
            "(b) add an arrangement_clip placement that fully spans "
            f"[{env_min:g}, {env_max:g}], or (c) partition the envelope "
            "by hand into per-section sub-envelopes whose ranges each fit "
            "a session clip. Auto-partition is v1.1 scope (W10-F "
            "follow-up). Skipping."
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
    local_bps = _clip_local_breakpoints(breakpoints_mcp, placement.start_beats)
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
    _warn_lossy_curve_hints(plan, envelope=envelope, breakpoints_mcp=local_bps)
    _warn_extra_placements(plan, envelope=envelope, placement=placement)
    _warn_multiple_covering_clips(plan, envelope=envelope, placement=placement)
    _warn_trimmed_placement(
        plan, envelope=envelope, placement=placement, env_max=env_max,
    )


# ---------------------------------------------------------------------------
# Master orchestration: plan_push_song
# ---------------------------------------------------------------------------


def plan_push_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the create/replace of every session clip in a song.

    Aggregates :func:`plan_push_clip` over every ``clips`` row whose
    parent track belongs to this song. Per-clip warnings are prefixed
    with the clip name so the merged plan stays diagnosable.

    Strict precondition (inherited from :func:`plan_push_clip`): every
    clip's track must already be linked in this session. Run
    :func:`plan_push_song_tracks` first, ``apply_push_results``, then
    this. The strict raise surfaces orchestration order bugs loudly —
    a silent skip would leave Live missing clips with no signal.
    """
    plan = PushPlan()
    rows = conn.execute(
        "SELECT id, name FROM clips WHERE track_id IN "
        "(SELECT id FROM tracks WHERE song_id=?) ORDER BY name, id",
        (song_id,),
    ).fetchall()
    for c in rows:
        sub = plan_push_clip(conn, clip_id=c["id"], session_id=session_id)
        plan.calls.extend(sub.calls)
        plan.notes.extend(f"[{c['name']}] {n}" for n in sub.notes)
    if not plan.calls and not plan.notes:
        plan.warn("no clips for this song; nothing to push")
    return plan


@dataclass(frozen=True)
class PushPhase:
    """One phase of the song-level master push.

    Each phase produces a fresh :class:`PushPlan` on demand by calling
    ``plan_fn()``. The thunk pattern (rather than an eager list of
    pre-built ``PushPlan`` objects) is load-bearing: later phases
    inspect ``ableton_links`` written by earlier phases via
    :func:`apply_push_results`. ``plan_push_clip`` raises on unlinked
    deps by design (W3-C); ``plan_push_arrangement`` was W10-G converted
    to skip-with-note for the same reason (phase-planner partial-state
    normalization — Wave 0 E1). Either way, pre-building all phases at
    ``plan_push_song`` time would either fail loudly, skip too much, or
    require re-planning anyway. Thunks make the re-plan-each-phase
    contract explicit.

    ``name`` is the stable identifier the push skill uses for logging
    and for keying status to phases. Don't rename — tests and the
    skill prose pin these strings.
    """
    name: str
    plan_fn: Callable[[], PushPlan]
    description: str


# The ten phases of the master push, in execution order. Order is
# load-bearing — see :func:`plan_push_song` for the dependency
# rationale per phase. This tuple is the single source of truth; tests
# pin both the names and the count.
_PHASE_NAMES: tuple[str, ...] = (
    "tempo_map",
    "time_signature_map",
    "tracks",
    "returns",
    "clips",
    "mix",
    "devices",
    "envelopes",
    "arrangement",
    "cues",
)


def plan_push_song(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> list[PushPhase]:
    """Master orchestration: return the ten phases of a full song push, in order.

    Each :class:`PushPhase` carries a ``plan_fn`` thunk that produces a
    fresh :class:`PushPlan` from current DB state at call time. The
    push skill (W4-E) iterates the list, for each phase calling
    ``plan_fn()`` → executing the calls via MCP → recording results via
    :func:`apply_push_results` → moving to the next phase. Each
    successive phase sees the ``ableton_links`` the prior phase wrote.

    Phase order (load-bearing):

      1. ``tempo_map`` — :func:`plan_push_tempo_map`. No link deps.
      2. ``time_signature_map`` — :func:`plan_push_time_signature_map`.
         No link deps.
      3. ``tracks`` — :func:`plan_push_song_tracks`. Creates+links
         every unlinked non-master track. Prerequisite for clips, mix,
         devices, envelopes, arrangement.
      4. ``returns`` — :func:`plan_push_song_returns`. Creates+links
         every unlinked return. Prerequisite for mix sends, return-side
         devices, return-side envelopes.
      5. ``clips`` — :func:`plan_push_clips`. Creates+links every
         session clip. Needs tracks linked (raises otherwise per W3-C
         strict contract). Prerequisite for envelopes (session-clip
         hosting) and arrangement (duplicate source).
      6. ``mix`` — :func:`plan_push_mix`. Pushes mixer state + sends.
         Needs tracks + returns linked. No clip dep.
      7. ``devices`` — :func:`plan_push_devices`. Loads instruments +
         effects and sets parameters. Needs tracks + returns linked.
         Prerequisite for ``device_parameter`` envelopes (need the
         target device linked).
      8. ``envelopes`` — :func:`plan_push_envelopes`. Writes envelopes
         on the SESSION clip per W4-A: ``duplicate_to_arrangement`` is
         a snapshot copy, so the envelope must exist on the session
         clip BEFORE arrangement runs. Needs tracks + clips + returns
         + devices linked.
      9. ``arrangement`` — :func:`plan_push_arrangement`. Emits
         ``duplicate_to_arrangement`` per arrangement row. Carries
         session-clip envelopes as snapshot copies (W4-A finding).
         Needs clips linked (raises otherwise).
      10. ``cues`` — :func:`plan_push_cue_points`. Creates cue points.
          Must run AFTER arrangement: Live's ``set_or_delete_cue`` is
          clamped to ``[0, song.last_event_time]``; cues placed before
          arrangement exists get rejected.

    Sections (``plan_push_sections``) is NOT included: it emits no
    canonical calls (Live has no section-marker concept distinct from
    cue points). Run it separately to surface its warn if needed.

    Returns 10 phases regardless of whether the song actually has
    content for each phase — empty phases produce a plan with a
    ``no … to push`` warn instead of an empty plan, so the skill's
    progress reporting can distinguish "ran cleanly with nothing to
    do" from "phase skipped". Idempotent: running the full sequence a
    second time produces empty plans (all link prereqs satisfied;
    each planner's already-linked branch is a no-op).
    """
    phases = (
        PushPhase(
            name="tempo_map",
            plan_fn=lambda: plan_push_tempo_map(conn, song_id=song_id),
            description="Write tempo points.",
        ),
        PushPhase(
            name="time_signature_map",
            plan_fn=lambda: plan_push_time_signature_map(conn, song_id=song_id),
            description="Write time-signature points.",
        ),
        PushPhase(
            name="tracks",
            plan_fn=lambda: plan_push_song_tracks(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Create unlinked non-master tracks (pre-pass for clips/mix/devices/envelopes/arrangement).",
        ),
        PushPhase(
            name="returns",
            plan_fn=lambda: plan_push_song_returns(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Create unlinked return tracks (pre-pass for sends/devices/envelopes).",
        ),
        PushPhase(
            name="clips",
            plan_fn=lambda: plan_push_clips(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Create+populate every session clip (atomic create+notes per W3-C / Wave M+1-1).",
        ),
        PushPhase(
            name="mix",
            plan_fn=lambda: plan_push_mix(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Push mixer state (volume/pan/mute/solo/arm/color) + master + sends.",
        ),
        PushPhase(
            name="devices",
            plan_fn=lambda: plan_push_devices(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Load instruments+effects and set parameters on tracks/returns.",
        ),
        PushPhase(
            name="envelopes",
            plan_fn=lambda: plan_push_envelopes(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Write envelopes on session clips (W4-A: must precede arrangement; duplicate_to_arrangement snapshots).",
        ),
        PushPhase(
            name="arrangement",
            plan_fn=lambda: plan_push_arrangement(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Duplicate session clips to the arrangement view (snapshots session-clip envelopes per W4-A).",
        ),
        PushPhase(
            name="cues",
            plan_fn=lambda: plan_push_cue_points(conn, song_id=song_id),
            description="Create cue points (after arrangement so Live's [0, last_event_time] clamp accepts them).",
        ),
    )
    # The tuple-of-names canary keeps tests and the skill agreeing on
    # phase identity without re-traversing this whole function.
    # Runtime raise (not `assert`) so the check survives `python -O`.
    if tuple(p.name for p in phases) != _PHASE_NAMES:
        raise RuntimeError(
            "plan_push_song phase order drifted from _PHASE_NAMES; update both."
        )
    return list(phases)


# ---------------------------------------------------------------------------
# Probe-and-link: bind existing Live tracks/returns to DB rows by name
# ---------------------------------------------------------------------------


# W18-D: Live 12.x's brand-new-set scaffold ships these track names. Detection
# of the "first push onto a fresh default set" case keys off this exact set —
# any drift (rename, locale change, user customization) means the tracks are
# no longer recognisable defaults and we fall back to the standard "continue
# alongside?" confirmation.
CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES: frozenset[str] = frozenset({
    "1-MIDI", "2-MIDI", "3-Audio", "4-Audio",
})


@dataclass
class ProbeAndLinkResult:
    """Outcome of :func:`probe_and_link`. The skill displays the
    matched / unmatched lists so the user can spot rename drift
    (e.g. DB has 'Drums', Live has 'Drum Kit').

    W18-B added ``unlinked_stale_tracks`` / ``unlinked_stale_returns``: links
    whose ``ableton_index`` no longer matches a Live entity in the fresh
    probe and were deleted by strict reconciliation. The skill surfaces the
    counts so the user sees that probe-and-link recovered from a deleted-
    Live-track drift instead of silently leaving stale rows.

    W18-D added ``default_scaffold_unmatched_tracks``: present (non-empty)
    only when the caller passed ``auto_session_created=True`` AND every
    entry in ``unmatched_live_tracks`` matches a canonical Live default
    name. The skill keys its "delete defaults after push?" prompt off this
    field, not off ``unmatched_live_tracks`` directly — that way an unrelated
    set with the same names doesn't trigger destructive cleanup.
    """
    matched_tracks: list[dict[str, Any]] = field(default_factory=list)
    matched_returns: list[dict[str, Any]] = field(default_factory=list)
    unmatched_db_tracks: list[dict[str, Any]] = field(default_factory=list)
    unmatched_db_returns: list[dict[str, Any]] = field(default_factory=list)
    unmatched_live_tracks: list[dict[str, Any]] = field(default_factory=list)
    unmatched_live_returns: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_tracks: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_returns: list[dict[str, Any]] = field(default_factory=list)
    default_scaffold_unmatched_tracks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_and_link(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_tracks: list[dict[str, Any]],
    live_returns: list[dict[str, Any]],
    actor: str = "sync",
    reason: str | None = None,
    auto_session_created: bool = False,
) -> ProbeAndLinkResult:
    """Match Live tracks/returns by name against DB rows; write the
    matches as ``ableton_links`` so subsequent phases skip the
    create call.

    This is the W3-G work that was deferred from Wave 3 — running it
    before the master orchestrator lets the agent push against a
    Live set that already contains some of the song's tracks/returns
    (typical when the user opened a half-built set or is iterating
    against a saved template). Unmatched DB entities still get
    created in phases 3 / 4; unmatched Live entities are NOT
    deleted — push is additive, not destructive.

    Track matching: case-sensitive name equality. Master tracks (DB
    ``kind='master'``) are skipped — Live's track list never
    contains master, and master mixer state is reached via
    ``ableton_session`` rather than a track index.

    Return matching: the live-side name is stripped of Live's
    automatic slot-letter prefix (W4-C) before comparison. So DB
    'Reverb' matches Live 'A-Reverb' (and is linked to return_index
    1, the index Live exposes for slot A).

    Duplicate names on either side warn loudly and link the FIRST
    match; the agent should rename to disambiguate. Returns kind
    drift between DB and Live as a note (informational — kind isn't
    enforced at link time).

    Re-runnable: calling ``probe_and_link`` a second time on the same
    inputs is a no-op for the link upserts (link_db_to_ableton is
    upsert-by-(session, db_kind, db_id)) and a no-op for the strict
    reconciliation (no stale links to delete the second time).

    **W18-B: strict link reconciliation.** After the name-matching pass,
    any ``ableton_links`` row whose ``ableton_index`` no longer appears in
    the fresh probe is deleted (track + return kinds; nested kinds —
    clip / device / envelope — are not validated here, the parent-track
    deletion cascade-invalidates them and the next push re-creates them).
    This closes the punk-fate drift bug where a deleted Live track left a
    stale link pointing at a now-vacant index, causing the next push to
    silently dispatch clip creates against the wrong track.

    **W18-D: default-scaffold detection.** When the caller flags
    ``auto_session_created=True`` AND every entry in
    ``unmatched_live_tracks`` matches a canonical Live-default name
    (``1-MIDI`` / ``2-MIDI`` / ``3-Audio`` / ``4-Audio``), the unmatched
    list is also surfaced as ``default_scaffold_unmatched_tracks`` so the
    skill can offer "delete defaults after push?" as the prompt default
    instead of the generic "continue alongside?" gate.
    """
    result = ProbeAndLinkResult()

    db_tracks = [t for t in Q.get_tracks_for_song(conn, song_id) if t["kind"] != "master"]
    db_returns = list(Q.get_returns_for_song(conn, song_id))

    # ---- Tracks: name-equality match.
    live_track_by_name: dict[str, list[dict[str, Any]]] = {}
    for lt in live_tracks:
        live_track_by_name.setdefault(lt["name"], []).append(lt)
    consumed_live_track_indexes: set[int] = set()
    for dt in db_tracks:
        candidates = live_track_by_name.get(dt["name"], [])
        if not candidates:
            result.unmatched_db_tracks.append({"db_id": dt["id"], "name": dt["name"]})
            continue
        if len(candidates) > 1:
            result.notes.append(
                f"track name {dt['name']!r}: {len(candidates)} Live tracks "
                "match; linking to the first (track_index="
                f"{candidates[0]['track_index']}). Rename in Live to disambiguate."
            )
        chosen = candidates[0]
        if dt["kind"] != chosen.get("kind"):
            result.notes.append(
                f"track {dt['name']!r}: DB kind={dt['kind']!r} but "
                f"Live kind={chosen.get('kind')!r} (informational; link written anyway)"
            )
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="track", db_id=dt["id"],
            ableton_index=chosen["track_index"], actor=actor, reason=reason,
        )
        consumed_live_track_indexes.add(chosen["track_index"])
        result.matched_tracks.append({
            "db_id": dt["id"],
            "name": dt["name"],
            "ableton_index": chosen["track_index"],
        })
    for lt in live_tracks:
        if lt["track_index"] not in consumed_live_track_indexes:
            result.unmatched_live_tracks.append({
                "track_index": lt["track_index"],
                "name": lt["name"],
            })

    _flag_case_near_matches(
        result.unmatched_db_tracks,
        result.unmatched_live_tracks,
        kind="track",
        notes=result.notes,
    )

    # ---- Returns: strip Live's slot-letter prefix, then match by name.
    live_return_by_name: dict[str, list[dict[str, Any]]] = {}
    for lr in live_returns:
        stripped = strip_return_slot_prefix(lr["name"])
        live_return_by_name.setdefault(stripped, []).append(lr)
    consumed_live_return_indexes: set[int] = set()
    for dr in db_returns:
        candidates = live_return_by_name.get(dr["name"], [])
        if not candidates:
            result.unmatched_db_returns.append({"db_id": dr["id"], "name": dr["name"]})
            continue
        if len(candidates) > 1:
            result.notes.append(
                f"return name {dr['name']!r} (suffix): {len(candidates)} Live "
                "returns match; linking to the first (return_index="
                f"{candidates[0]['return_index']})."
            )
        chosen = candidates[0]
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="return", db_id=dr["id"],
            ableton_index=chosen["return_index"], actor=actor, reason=reason,
        )
        consumed_live_return_indexes.add(chosen["return_index"])
        result.matched_returns.append({
            "db_id": dr["id"],
            "name": dr["name"],
            "ableton_index": chosen["return_index"],
        })
    for lr in live_returns:
        if lr["return_index"] not in consumed_live_return_indexes:
            result.unmatched_live_returns.append({
                "return_index": lr["return_index"],
                "name": lr["name"],
            })

    # Returns match by stripped-name; compare against stripped form
    # so DB 'Reverb' vs Live 'A-reverb' surfaces as near-match.
    _flag_case_near_matches(
        result.unmatched_db_returns,
        result.unmatched_live_returns,
        kind="return",
        notes=result.notes,
        live_normalize=strip_return_slot_prefix,
    )

    # W18-B: strict reconciliation — sweep ableton_links for rows whose
    # ableton_index no longer appears in the fresh probe. Only track + return
    # kinds: nested kinds (clip/device/envelope/note/arrangement_clip) are
    # cascade-invalidated when their parent track is deleted, and the next
    # push's create-call path re-establishes them. Iterate over a snapshot of
    # the rows because the unlink mutator deletes from the same table.
    live_track_indexes = {lt["track_index"] for lt in live_tracks}
    live_return_indexes = {lr["return_index"] for lr in live_returns}
    for link in list(Q.get_ableton_links_for_session(conn, session_id)):
        db_kind = link["db_kind"]
        ableton_index = link["ableton_index"]
        if db_kind == "track" and ableton_index not in live_track_indexes:
            M.unlink_db_from_ableton(
                conn,
                session_id=session_id,
                db_kind=db_kind,
                db_id=link["db_id"],
                actor=actor,
                reason=reason or "probe-and-link: stale track link",
            )
            result.unlinked_stale_tracks.append({
                "db_id": link["db_id"],
                "ableton_index": ableton_index,
            })
        elif db_kind == "return" and ableton_index not in live_return_indexes:
            M.unlink_db_from_ableton(
                conn,
                session_id=session_id,
                db_kind=db_kind,
                db_id=link["db_id"],
                actor=actor,
                reason=reason or "probe-and-link: stale return link",
            )
            result.unlinked_stale_returns.append({
                "db_id": link["db_id"],
                "ableton_index": ableton_index,
            })

    # W18-D: detect "first push onto Live's brand-new-set default scaffold."
    # Fires only on auto-session bootstraps where every unmatched Live track
    # is a canonical default — that name set is the unambiguous signature.
    # When ANY unmatched-Live track has a non-canonical name, this is "some
    # other song's tracks" territory and we deliberately don't suggest
    # cleanup; the standard "continue alongside?" gate handles that case.
    if (
        auto_session_created
        and result.unmatched_live_tracks
        and all(
            t["name"] in CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
            for t in result.unmatched_live_tracks
        )
    ):
        result.default_scaffold_unmatched_tracks = list(result.unmatched_live_tracks)

    return result


def _flag_case_near_matches(
    unmatched_db: list[dict[str, Any]],
    unmatched_live: list[dict[str, Any]],
    *,
    kind: str,
    notes: list[str],
    live_normalize: Callable[[str | None], str | None] | None = None,
) -> None:
    """Surface DB×Live pairs that match case-insensitively but not
    case-sensitively. Catches the silent foot-gun where a user renames
    Live's 'Drums' → 'drums' and the probe creates a duplicate 'Drums'
    track right next to it (W4-E real-Live finding, 2026-05-18).

    Returns through ``notes`` rather than the unmatched lists — both
    sides stay genuinely unmatched (the probe doesn't auto-link
    case-variant pairs; the user decides). ``live_normalize`` is
    applied to the Live-side name before comparison (e.g. strip
    Live's return slot-letter prefix so DB 'Reverb' near-matches
    Live 'A-reverb' / 'a-Reverb').
    """
    norm = live_normalize or (lambda s: s)
    for db in unmatched_db:
        db_name = db["name"]
        for live in unmatched_live:
            live_name = norm(live["name"])
            if (
                db_name != live_name
                and db_name.casefold() == live_name.casefold()
            ):
                notes.append(
                    f"DB {kind} {db_name!r} has near-match Live "
                    f"{live['name']!r} (case differs); intentional? "
                    "Rename one to match if not."
                )


# ---------------------------------------------------------------------------
# Coherence check (W18-A)
# ---------------------------------------------------------------------------


@dataclass
class CoherenceResult:
    """Outcome of :func:`check_coherence`. Tri-state: ``ok=True`` with no
    errors means execute is safe; ``ok=False`` with errors means refuse and
    surface recovery hints. ``notes`` carries informational findings (e.g.
    "session has no links yet, push will create from scratch") that don't
    block execute.
    """
    ok: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def add_error(self, *, kind: str, detail: str, recovery: str) -> None:
        self.errors.append({"kind": kind, "detail": detail, "recovery": recovery})
        self.ok = False


def check_coherence(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    live_tracks: list[dict[str, Any]],
    live_returns: list[dict[str, Any]],
) -> CoherenceResult:
    """Validate that ``ableton_sessions`` + ``ableton_links`` rows are
    consistent with a freshly-probed Live snapshot, before ``execute``
    starts mutating Live.

    Closes the punk-fate 2026-05-20 state-drift class: three pieces of
    per-machine state (snapshot file, ``ableton_sessions``, ``ableton_links``)
    with independent invalidation rules and no consistency check. This
    function refuses execute on any of:

    1. **Session row missing.** ``session_id`` doesn't resolve in
       ``ableton_sessions`` (e.g. ``build.py --reset`` wiped it).
    2. **Stale track link.** An ``ableton_links`` row points at a
       ``track_index`` no longer in the live probe (e.g. the user deleted
       the linked Live track).
    3. **Stale return link.** Same shape for ``return_index``.

    Callers pass a FRESH probe (re-run ``ableton_track(action='list')`` +
    ``ableton_return(action='list')`` against Live just before this check).
    The function reads links from the DB and validates against that probe.

    Nested links (clip / device / device_chain) aren't validated directly
    here — a stale parent track link cascade-invalidates them, and the
    parent check is sufficient to refuse the push. Probing every nested
    binding would require deep MCP traffic; the parent-level check buys
    the same safety at a tenth the cost.

    Returns a :class:`CoherenceResult`. Callers should refuse to execute
    when ``ok`` is False and surface the per-error ``recovery`` hints.
    """
    result = CoherenceResult()

    if Q.get_ableton_session(conn, session_id) is None:
        result.add_error(
            kind="session_missing",
            detail=f"no ableton_sessions row with id {session_id!r}",
            recovery=(
                "Mint a fresh session: run "
                "`push_cli probe-and-link --auto-session --song <slug> "
                "--snapshot <path>`. This is the usual repro after "
                "`build.py --reset` wipes the sessions table."
            ),
        )
        # No session → no point checking links; they're orphaned anyway.
        return result

    live_track_indexes = {lt["track_index"] for lt in live_tracks}
    live_return_indexes = {lr["return_index"] for lr in live_returns}

    links = Q.get_ableton_links_for_session(conn, session_id)
    if not links:
        result.notes.append(
            "session has no ableton_links rows — push will create tracks/returns "
            "from scratch (this is fine for a first push, but probe-and-link "
            "should have run if Live already contained any of the song's tracks)"
        )
        return result

    stale_track_links: list[dict[str, Any]] = []
    stale_return_links: list[dict[str, Any]] = []
    for link in links:
        db_kind = link["db_kind"]
        ableton_index = link["ableton_index"]
        if db_kind == "track":
            if ableton_index not in live_track_indexes:
                stale_track_links.append({
                    "db_id": link["db_id"],
                    "ableton_index": ableton_index,
                })
        elif db_kind == "return":
            if ableton_index not in live_return_indexes:
                stale_return_links.append({
                    "db_id": link["db_id"],
                    "ableton_index": ableton_index,
                })
        # Other kinds (clip / device / device_chain) are nested under a
        # track or return; a stale parent link cascade-invalidates them
        # and the parent-level error is sufficient.

    if stale_track_links:
        indexes = sorted({l["ableton_index"] for l in stale_track_links})
        result.add_error(
            kind="stale_track_links",
            detail=(
                f"{len(stale_track_links)} ableton_links row(s) point at "
                f"track_index(es) {indexes} that no longer exist in Live "
                f"(live tracks: {sorted(live_track_indexes)}). "
                "Common cause: user deleted the linked Live track after "
                "probe-and-link wrote the link row."
            ),
            recovery=(
                "Re-run `push_cli probe-and-link --probe` (or supply a fresh "
                "--snapshot). W18-B's strict reconciliation will delete the "
                "stale link rows and re-match anything still present."
            ),
        )

    if stale_return_links:
        indexes = sorted({l["ableton_index"] for l in stale_return_links})
        result.add_error(
            kind="stale_return_links",
            detail=(
                f"{len(stale_return_links)} ableton_links row(s) point at "
                f"return_index(es) {indexes} that no longer exist in Live "
                f"(live returns: {sorted(live_return_indexes)}). "
                "Common cause: user deleted the linked Live return after "
                "probe-and-link wrote the link row."
            ),
            recovery=(
                "Re-run `push_cli probe-and-link --probe` (or supply a fresh "
                "--snapshot) to drop the stale link rows."
            ),
        )

    return result


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
    "tempo_point",           # ableton_session(set_tempo) for bar-1 (W5-A)
    "time_signature_point",  # ableton_session(set_signature) for bar-1 (W5-A)
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
