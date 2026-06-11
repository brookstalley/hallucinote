"""Master orchestration (``plan_push_song`` / ``PushPhase``) + result application."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hallucinote.db import mutations as M
from hallucinote.db.connection import transaction

from ._core import PushPlan
from .arrangement import plan_push_arrangement, plan_push_cue_points
from .clips import plan_push_clips
from .devices import plan_push_devices
from .envelopes import plan_push_envelopes
from .mix import plan_push_mix
from .perform import plan_push_performed_automation, record_perform_result
from .scenes import plan_push_scenes
from .tempo import plan_push_tempo_map, plan_push_time_signature_map
from .tracks import plan_push_song_returns, plan_push_song_tracks


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


# The twelve phases of the master push, in execution order. Order is
# load-bearing — see :func:`plan_push_song` for the dependency
# rationale per phase. This tuple is the single source of truth; tests
# pin both the names and the count.
_PHASE_NAMES: tuple[str, ...] = (
    "tempo_map",
    "time_signature_map",
    "tracks",
    "returns",
    "scenes",
    "clips",
    "mix",
    "devices",
    "envelopes",
    "performed_automation",
    "arrangement",
    "cues",
)


def plan_push_song(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> list[PushPhase]:
    """Master orchestration: return the twelve phases of a full song push, in order.

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
      5. ``scenes`` — :func:`plan_push_scenes`. Ensures the set has at
         least ``max session-clip slot`` scenes (= clip slots per track)
         before ``clips`` creates section clips. Emits one idempotent
         ``ableton_scene(action='ensure_count')`` call; deficit math runs
         Live-side. No link deps. Prerequisite for ``clips`` — without it,
         a song with more sections than the set has scenes hits a raw
         per-clip ``IndexError`` at clip-create (SYN-4P2D).
      6. ``clips`` — :func:`plan_push_clips`. Creates+links every
         session clip. Needs tracks linked (raises otherwise per W3-C
         strict contract). Prerequisite for envelopes (session-clip
         hosting) and arrangement (duplicate source).
      7. ``mix`` — :func:`plan_push_mix`. Pushes mixer state + sends.
         Needs tracks + returns linked. No clip dep.
      8. ``devices`` — :func:`plan_push_devices`. Loads instruments +
         effects and sets parameters. Needs tracks + returns linked.
         Prerequisite for ``device_parameter`` envelopes (need the
         target device linked).
      9. ``envelopes`` — :func:`plan_push_envelopes`. Writes envelopes
         on the SESSION clip per W4-A: ``duplicate_to_arrangement`` is
         a snapshot copy, so the envelope must exist on the session
         clip BEFORE arrangement runs. Needs tracks + clips + returns
         + devices linked.
      10. ``performed_automation`` — :func:`plan_push_performed_automation`.
          Gesture-records master/group/return-side arcs into arrangement
          automation (ENV-7G4K), fingerprint-gated. Needs tracks +
          returns + devices linked. Realtime: the transport plays each
          changed arc's span (the plan names the wall-clock cost).
      11. ``arrangement`` — :func:`plan_push_arrangement`. Emits
          ``duplicate_to_arrangement`` per arrangement row. Carries
          session-clip envelopes as snapshot copies (W4-A finding).
          Needs clips linked (raises otherwise).
      12. ``cues`` — :func:`plan_push_cue_points`. Creates cue points.
          Must run AFTER arrangement: Live's ``set_or_delete_cue`` is
          clamped to ``[0, song.last_event_time]``; cues placed before
          arrangement exists get rejected.

    Sections (``plan_push_sections``) is NOT included: it emits no
    canonical calls (Live has no section-marker concept distinct from
    cue points). Run it separately to surface its warn if needed.

    Returns 12 phases regardless of whether the song actually has
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
            name="scenes",
            plan_fn=lambda: plan_push_scenes(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Ensure the set has >= max session-clip slot scenes (pre-pass for clips; session clip slots are scene rows).",
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
            name="performed_automation",
            plan_fn=lambda: plan_push_performed_automation(
                conn, song_id=song_id, session_id=session_id,
            ),
            description=(
                "Gesture-record master/group/return-side automation arcs "
                "(fingerprint-gated; transport plays each changed span)."
            ),
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
# MUST appear in `_LINK_KINDS`, `_ACK_ONLY_KINDS`, or the explicit `perform`
# branch in `apply_push_results` (ENV-7G4K performed-state recording), or
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
    # SYN-4P2D (scenes): ableton_scene(action='ensure_count') provisions
    # session clip slots before the clips phase. Scenes are a Live-set
    # structural property, not a Hallucinote entity — there's no per-scene DB
    # row to link, so the key is ack-only.
    "scene",
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

            if kind == "perform":
                # ENV-7G4K performed automation: success records the
                # arc's fingerprint so the next push skips it. Gated on
                # the handler's automation_state == 1 verification — the
                # perform handler RETURNS a non-1 state rather than
                # raising, and an unverified write must leave the
                # fingerprint unwritten so the next push retries
                # (record_perform_result owns that policy).
                if not db_id:
                    raise ValueError(
                        f"push result key {key!r} missing envelope id "
                        "after 'perform:'"
                    )
                record_perform_result(
                    conn,
                    envelope_id=db_id,
                    result=r.get("result") or {},
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
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
