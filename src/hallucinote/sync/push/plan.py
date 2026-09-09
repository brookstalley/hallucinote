"""Master orchestration (``plan_push_song`` / ``PushPhase``) + result application."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from hallucinote.db import mutations as M
from hallucinote.db.connection import transaction

from ._core import PushPlan
from .arrangement import plan_push_arrangement, plan_push_cue_points
from .clips import plan_push_clips
from .devices import plan_push_devices, plan_push_device_sidechain
from .envelopes import plan_push_envelopes
from .mix import plan_push_mix
from .perform import (
    PERFORM_OUTCOME_RECORDED,
    plan_push_performed_automation,
    record_perform_result,
)
from .routing import plan_push_routing
from .scenes import plan_push_scenes
from .tempo import plan_push_tempo_map, plan_push_time_signature_map
from .tracks import plan_push_song_returns, plan_push_song_tracks


# PSH-ARRPROBE: the arrangement probe map is either an already-materialized
# ``{track_index: [clip, ...]}`` dict (tests / non-execute callers) or a
# ZERO-ARG THUNK the arrangement phase calls at PLAN time. The thunk form is the
# one the execute path uses, and it is load-bearing: the probe must run AFTER
# the `tracks` phase, because a first push CREATES the song's Live tracks and a
# map probed before that names entirely different track indices (see
# :func:`plan_push_song`). ``None`` (either directly, or returned by the thunk)
# keeps the pre-existing "no probe → no clear, loud alert" contract.
LiveArrangementProbe = (
    dict[int, list[dict[str, Any]]]
    | Callable[[], dict[int, list[dict[str, Any]]] | None]
    | None
)


# SMP-6V2K: the session-clip probe is either an already-materialized
# ``{track_index: [clip, ...]}`` dict (tests / non-execute callers) or a ZERO-ARG
# THUNK the clips phase calls at PLAN time, for the same reason the two below are
# lazy: on a first push the Live tracks don't exist until the `tracks` phase has
# run, so a map probed before it names different indices.
#
# The degradation direction is the OPPOSITE of the arrangement probe's, because
# the two phases fail differently. Arrangement CLEARS, so "state unknown" must
# not become "clear anyway" — an empty map blocks per track. The clips phase does
# not clear: without a probe it conforms in place and plans no create and no
# delete, which is already the non-destructive answer. So ``None`` — "no probe
# taken" — is the safe degradation here, and it costs only the changed-file
# detection and zero-call idempotency, both of which announce themselves with an
# alert rather than acting on a guess.
LiveSessionClipProbe = (
    dict[int, list[dict[str, Any]]]
    | Callable[[], dict[int, list[dict[str, Any]]] | None]
    | None
)


# PSH-DEVDUP: the device-chain probe is either an already-materialized
# ``{(parent_kind, parent_index): [live device, ...]}`` dict (tests / callers
# that probed themselves) or a ZERO-ARG THUNK the devices phase calls at PLAN
# time. The thunk form is what the execute path passes, and the laziness is
# load-bearing: the map is keyed by the Live indices recorded in
# ``ableton_links``, and on a FIRST push those don't exist until the `tracks` /
# `returns` phases have run. ``None`` (directly, or returned by the thunk) keeps
# the pre-PSH-DEVDUP "no Live truth → load on faith" contract for pure-planner
# callers.
LiveDeviceProbe = (
    dict[tuple[str, int], list[dict[str, Any]]]
    | Callable[[], dict[tuple[str, int], list[dict[str, Any]]] | None]
    | None
)


def resolve_live_arrangement_probe(
    probe: LiveArrangementProbe,
) -> dict[int, list[dict[str, Any]]] | None:
    """Materialize an arrangement probe map, calling it if it's a thunk.

    Called from inside the arrangement phase's ``plan_fn``, i.e. once the
    `tracks` phase has created + linked every track, so the probe map is keyed
    by the SAME Live indices the planner resolves from ``ableton_links``.
    """
    if probe is None or isinstance(probe, dict):
        return probe
    return probe()


def resolve_live_session_clip_probe(
    probe: LiveSessionClipProbe,
) -> dict[int, list[dict[str, Any]]] | None:
    """Materialize a session-clip probe map, calling it if it's a thunk.

    Called from inside the clips phase's ``plan_fn``, i.e. once the `tracks`
    phase has created + linked every track, so the map is keyed by the SAME Live
    indices the planner resolves from ``ableton_links``.
    """
    if probe is None or isinstance(probe, dict):
        return probe
    return probe()


def resolve_live_device_probe(
    probe: LiveDeviceProbe,
) -> dict[tuple[str, int], list[dict[str, Any]]] | None:
    """Materialize a device-chain probe map, calling it if it's a thunk.

    Called from inside the devices phase's ``plan_fn``, i.e. once `tracks` and
    `returns` have created + linked every parent, so the probe map is keyed by
    the SAME Live indices the planner resolves from ``ableton_links``.
    """
    if probe is None or isinstance(probe, dict):
        return probe
    return probe()


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

    ``depends_on`` (SYN-8Q3F) is the phase's DECLARED dependency set —
    the names of the phases whose applied results this phase's planner
    assumes (link rows, provisioned scenes, materialized arrangement).
    Populated from :data:`_PHASE_DEPS`; :func:`validate_phase_order`
    proves the execution order satisfies it. Dependencies live in data,
    not prose — see ``.prawduct/artifacts/sync-boundary-contract.md``
    for each phase's full ASSUME / RE-PROBE contract.
    """
    name: str
    plan_fn: Callable[[], PushPlan]
    description: str
    depends_on: frozenset[str] = frozenset()


# The fourteen phases of the master push, in execution order. Order is
# load-bearing — the dependency rationale per phase is DECLARED in
# :data:`_PHASE_DEPS` below (and validated against this tuple by
# :func:`validate_phase_order`). This tuple is the single source of
# truth for order; tests pin both the names and the count.
_PHASE_NAMES: tuple[str, ...] = (
    "tempo_map",
    "time_signature_map",
    "tracks",
    "returns",
    "scenes",
    "clips",
    "mix",
    "devices",
    "routing",
    "device_sidechain",
    "envelopes",
    "performed_automation",
    "arrangement",
    "cues",
)


# SYN-8Q3F: the declared dependency graph — the ordering constraints that used
# to live only in plan_push_song's docstring, as data. ``phase -> the phases
# whose APPLIED results its planner assumes``. Only real dependencies are
# declared (a planner reading link rows / provisioned state another phase
# creates); pure convention (tempo before tracks) is carried by the tuple
# order alone. Rationale per edge:
#
#   clips        <- tracks (W3-C strict raise on unlinked track),
#                   scenes (slot N needs >= N scenes — SYN-4P2D).
#   mix          <- tracks, returns (set_property/set_send address by link).
#   devices      <- tracks, returns (chains hang off linked parents).
#   routing      <- tracks (source + track-route target links),
#                   devices (a MIDI track exposes AUDIO output routing — the
#                   only kind that targets a submaster bus — only once its
#                   instrument is loaded; RTE-2P9X fresh-push fix).
#   device_sidechain <- tracks (source resolved to a track that must exist),
#                   devices (the device must exist + be linked — SDC-7K3M).
#   envelopes    <- tracks, returns, clips (session-clip hosting), devices
#                   (device_parameter targets).
#   performed_automation <- tracks, returns, devices (arc addressing).
#   arrangement  <- tracks (placement lanes), clips (duplicate source for
#                   envelope-bearing placements), envelopes (W4-A: the clip
#                   envelope must exist on the session clip BEFORE
#                   duplicate_to_arrangement snapshots it).
#   cues         <- arrangement (Live clamps set_or_delete_cue to
#                   [0, song.last_event_time] — W3-I).
#
# performed_automation vs arrangement have NO declared edge (arrangement
# clears CLIPS only; perform writes automation lanes), and routing-after-mix
# is likewise undeclared (the routing planner reads nothing mix applies) —
# both are tuple-order convention (RTE-1K9T chose the order), not dependency.
_PHASE_DEPS: dict[str, frozenset[str]] = {
    "tempo_map": frozenset(),
    "time_signature_map": frozenset(),
    "tracks": frozenset(),
    "returns": frozenset(),
    "scenes": frozenset(),
    "clips": frozenset({"tracks", "scenes"}),
    "mix": frozenset({"tracks", "returns"}),
    "devices": frozenset({"tracks", "returns"}),
    "routing": frozenset({"tracks", "devices"}),
    "device_sidechain": frozenset({"tracks", "devices"}),
    "envelopes": frozenset({"tracks", "returns", "clips", "devices"}),
    "performed_automation": frozenset({"tracks", "returns", "devices"}),
    "arrangement": frozenset({"tracks", "clips", "envelopes"}),
    "cues": frozenset({"arrangement"}),
}


class PhaseOrderError(ValueError):
    """The declared phase order contradicts the declared dependency graph
    (or the graph itself is malformed: unknown phase, undeclared phase, a
    dependency naming no known phase, or a cycle — which, for a total order,
    always surfaces as a dep-after-dependent violation)."""


def validate_phase_order(
    names: tuple[str, ...] | list[str],
    deps: dict[str, frozenset[str]],
) -> None:
    """Prove ``names`` (the declared execution order) satisfies ``deps``.

    SYN-8Q3F: the executor runs the declared tuple order (stable, human-chosen);
    this validator is the machine check that the tuple is a valid topological
    order of the declared graph. Checks, in order:

    1. ``deps`` declares exactly the phases in ``names`` (no missing, no stale
       entries — a new phase MUST declare its dependency set, even if empty).
    2. Every dependency names a known phase.
    3. Every dependency appears BEFORE its dependent. For a total order this
       also rejects cycles: a cycle cannot be linearized, so at least one of
       its edges must point forward.

    Raises :class:`PhaseOrderError` with a teaching message on any violation.
    """
    name_list = list(names)
    name_set = set(name_list)
    if len(name_list) != len(name_set):
        raise PhaseOrderError(f"duplicate phase name in order: {name_list!r}")

    undeclared = name_set - set(deps)
    if undeclared:
        raise PhaseOrderError(
            f"phase(s) {sorted(undeclared)} declare no dependency set — add "
            "an entry (frozenset() if none) to _PHASE_DEPS."
        )
    stale = set(deps) - name_set
    if stale:
        raise PhaseOrderError(
            f"_PHASE_DEPS declares unknown phase(s) {sorted(stale)} — not in "
            "the phase order; remove or rename the entries."
        )

    index = {name: i for i, name in enumerate(name_list)}
    for name in name_list:
        for dep in sorted(deps[name]):
            if dep not in name_set:
                raise PhaseOrderError(
                    f"phase {name!r} depends on unknown phase {dep!r} "
                    f"(known: {name_list!r})."
                )
            if index[dep] >= index[name]:
                raise PhaseOrderError(
                    f"phase {name!r} depends on {dep!r}, which does not run "
                    f"before it (order: {name_list!r}). Reorder the phases, "
                    "or fix the declared dependency — a cycle can never be "
                    "ordered."
                )


def plan_push_song(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    perform_slowdown_factor: float = 1.0,
    live_arrangement_clips_by_track: LiveArrangementProbe = None,
    live_device_chains: LiveDeviceProbe = None,
    live_session_clips_by_track: LiveSessionClipProbe = None,
) -> list[PushPhase]:
    """Master orchestration: return the fourteen phases of a full song push, in order.

    Each :class:`PushPhase` carries a ``plan_fn`` thunk that produces a
    fresh :class:`PushPlan` from current DB state at call time. The
    push skill (W4-E) iterates the list, for each phase calling
    ``plan_fn()`` -> executing the calls via MCP -> recording results via
    :func:`apply_push_results` -> moving to the next phase. Each
    successive phase sees the ``ableton_links`` the prior phase wrote.

    Ordering is DECLARED DATA (SYN-8Q3F): the execution order is
    :data:`_PHASE_NAMES`; the dependencies each phase asserts (with
    per-edge rationale) are :data:`_PHASE_DEPS`; :func:`validate_phase_order`
    proves at construction time that the order satisfies the graph. Each
    phase's full boundary contract -- what it ASSUMES from prior phases vs
    what it RE-PROBES from Live, and its failure/halt policy -- lives in
    ``.prawduct/artifacts/sync-boundary-contract.md``.

    ``live_arrangement_clips_by_track`` (PSH-ARRPROBE) may be a dict OR a
    zero-arg thunk (:data:`LiveArrangementProbe`). The execute path passes a
    THUNK, and that laziness is a correctness requirement, not an optimization:
    the arrangement projection matches probe keys against the Live track indices
    recorded in ``ableton_links``, and on a FIRST push those indices don't exist
    until the `tracks` phase has run. A map probed before the phase loop
    (the pre-fix behavior) described a different set — a fresh song pushed into
    a Live set holding the 4 default scaffold tracks probed lanes 1-4 while the
    song's tracks landed at 5-13, so EVERY track read as "probe failed" and the
    whole arrangement silently no-op'd. Resolving the thunk inside the
    arrangement ``plan_fn`` probes after tracks exist. (It also stops non-
    arrangement scoped runs, e.g. ``--only devices``, from paying for the probe
    at all.)
    ``live_device_chains`` (PSH-DEVDUP) may be a dict OR a zero-arg thunk
    (:data:`LiveDeviceProbe`), resolved inside the devices ``plan_fn``. It is
    what lets the devices planner tell a device that is MISSING from Live apart
    from one that is PRESENT but unlinked. Without it the planner treated both
    as "load", and since Live 12.4 tail-appends, a push onto a set that already
    carried the chain silently doubled every effect.

    Sections (``plan_push_sections``) is NOT a phase: it emits no
    canonical calls (Live has no section-marker concept distinct from
    cue points). Run it separately to surface its warn if needed.

    Returns all 14 phases regardless of whether the song actually has
    content for each phase -- an empty phase's plan is either bare-empty
    or carries a ``no ... to push`` warn; the executor reports both as
    SKIPPED. Idempotent: running the full sequence a second time
    produces empty plans (all link prereqs satisfied; each planner's
    already-linked branch is a no-op).
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
                # Resolved HERE (inside the thunk), not at plan_push_song time —
                # the probe must see the tracks the `tracks` phase created.
                live_session_clips_by_track=resolve_live_session_clip_probe(
                    live_session_clips_by_track,
                ),
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
                # PSH-DEVDUP: resolved HERE (inside the thunk), not at
                # plan_push_song time — the probe must see the parents the
                # `tracks` / `returns` phases created, and its result is what
                # tells the planner "already present" from "genuinely missing".
                live_devices_by_parent=resolve_live_device_probe(
                    live_device_chains,
                ),
            ),
            description="Load instruments+effects and set parameters on tracks/returns.",
        ),
        PushPhase(
            name="routing",
            plan_fn=lambda: plan_push_routing(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Materialize per-track output/input routing + monitor state (RTE-1K9T PRE-MAIN submaster pattern). AFTER devices: a MIDI track exposes audio output routing only once an instrument is loaded.",
        ),
        PushPhase(
            name="device_sidechain",
            plan_fn=lambda: plan_push_device_sidechain(
                conn, song_id=song_id, session_id=session_id,
            ),
            description="Materialize device sidechain SOURCE routing (SDC-7K3M) — after devices, since the device must exist before its input routing can be set.",
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
                slowdown_factor=perform_slowdown_factor,
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
                # Resolved HERE (inside the thunk), not at plan_push_song time —
                # the probe must see the tracks the `tracks` phase created.
                live_arrangement_clips_by_track=resolve_live_arrangement_probe(
                    live_arrangement_clips_by_track,
                ),
            ),
            description="Project the DB onto the arrangement: clear each track then create+fill (envelope-bearing clips duplicate onto the cleared region) — ARR-PROJ.",
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
    # SYN-8Q3F: prove the declared order satisfies the declared dependency
    # graph (unknown phase / undeclared phase / dep-after-dependent / cycle
    # all raise PhaseOrderError), then stamp each phase with its declared
    # deps so downstream consumers (executor, skills, tests) read ordering
    # constraints as data, not prose.
    validate_phase_order(_PHASE_NAMES, _PHASE_DEPS)
    return [replace(p, depends_on=_PHASE_DEPS[p.name]) for p in phases]


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
# MUST appear in `_LINK_KINDS`, `_ACK_ONLY_KINDS`, or the explicit
# `perform_batch` branch in `apply_push_results` (ENV-9P4T per-arc
# performed-state recording), or `apply_push_results` raises. This makes the
# dispatch surface auditable: when
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
    # RTE-1K9T (routing): per-track output/input routing + monitor go through
    # ableton_track(set_output_routing / set_input_routing / set_monitoring_state).
    # Ack-only — the routing state already lives in the DB (the push ORIGINATES
    # from it, same as the mixer set_property keys above); there's no Live-side
    # index to record back.
    "track_output_routing",
    "track_input_routing",
    "track_monitor",
    # SDC-7K3M: device sidechain SOURCE via ableton_device(set_input_routing).
    # Ack-only — same rationale as the track-routing keys (state originates from
    # the DB FK; no Live-side index to record back).
    "device_sidechain",
    # Chunk 4a (devices)
    "device_parameter",      # ableton_device(action='set_parameter') for tracks + returns (Wave M-4)
    # Nested preset param override (DEV-4P7R `param_overrides`, e.g. a `value_raw`
    # on a rack's nested Wavetable LFO). The push planner emits this kind once the
    # override is applied; ack-only because the intended value ORIGINATES in the
    # snapshot/DB (same rationale as `device_parameter` above) — there is no
    # Live-side index to record back. Without this case the devices phase HALTS
    # mid-run on any song whose snapshot carries a `value_raw` override, so the
    # full push never finishes (no routing/envelopes/automation/arrangement/cues).
    # See backlog PSH-8K3D
    "device_param_override",
    # NODE-ADDR Chunk C/F: per-chain mixer state (mute/solo/volume/pan) +
    # choke_group/out_note, emitted by the devices planner as
    # `device_chain_props:{chain_id}` via ableton_device(set_chain_property)
    # (devices.py). Ack-only — the chain state ORIGINATES in the snapshot/DB and
    # a chain has no Live-side index to record back (it is addressed by
    # chain_index, not a linkable handle), exactly like device_param_override
    # above. The DIRECT TWIN of the 2026-06-18 device_param_override bug, one key
    # kind over: without this case a full push of any rack-preset song carrying
    # non-default per-chain volume/mute/choke CRASHES in the devices-phase apply
    # — but only once the rack actually LOADS POPULATED (the rack-preset load fix
    # newly exposed it; before, these calls failed at dispatch on an empty-shell
    # rack and never reached apply).
    # See bug report "Push apply crashes on unknown result kind `device_chain_props` → full push of a rack-preset song never completes"
    "device_chain_props",
    # SYN-4P2D (scenes): ableton_scene(action='ensure_count') provisions
    # session clip slots before the clips phase. Scenes are a Live-set
    # structural property, not a Hallucinote entity — there's no per-scene DB
    # row to link, so the key is ack-only.
    "scene",
    # PSH-6W2J: refresh notes on an ALREADY-linked arrangement clip via
    # ableton_clip(action='replace_notes', location='arrangement'). The
    # placement's `arrangement_clip` binding already exists (recorded when the
    # duplicate landed); this op only rewrites content, so there's no new index
    # to record — ack-only. Distinct from the `arrangement_clip:` duplicate key.
    "arrangement_clip_notes",
    # ARR-PROJ Chunk 2: the projection planner CLEARS a track's existing
    # arrangement clips before create+filling from the DB, emitting
    # ableton_clip(action='delete', location='arrangement') keyed
    # `arrangement_clip_clear:{track}:{idx}`. Ack-only — a delete removes a clip
    # (and its link, which the rebuild re-records under `arrangement_clip:`);
    # the delete result carries no index to bind. Without this case
    # apply_push_results raises on the unknown key prefix and HALTS the
    # arrangement phase before any clip is rebuilt.
    "arrangement_clip_clear",
    # SMP-6V2K (audio clips): the conform surface an audio clip is
    # materialized with — gain / pitch_coarse / pitch_fine / warping /
    # warp_mode / start_marker / end_marker — written one property at a time
    # via ableton_clip(action='set_property') and keyed
    # `clip_conform:{clip_id}:{property}` (clips.py). Ack-only: the value
    # ORIGINATES in the DB and a conform write records no Live-side index,
    # exactly like the mixer `track_volume` / `device_parameter` keys above.
    # The clip's own binding is recorded under `clip:` by the create.
    "clip_conform",
})


# SYN-8Q3F (c): the ONE registry of result key kinds the apply layer resolves —
# `_LINK_KINDS` (binding writes) + `_ACK_ONLY_KINDS` (no DB write) + the
# dedicated `perform_batch` branch. Three layers keep this exhaustive so the
# twice-shipped unknown-kind halt class (`device_param_override` 2026-06-18,
# `device_chain_props` 2026-06-20) stays closed:
#   1. the static emitted-kind guard (test_push.py
#      test_every_emitted_push_key_kind_is_declared) fails the suite when any
#      planner emits a kind outside this registry;
#   2. apply_push_results raises ValueError (fail-loud, teaching message) on a
#      kind outside it — reachable only from a non-planner result source or
#      cross-version skew once (1) holds;
#   3. the executor converts that raise into a CONTROLLED phase halt
#      (push_execute._apply_results) — state file written, request closed —
#      instead of the raw traceback it used to be (contract artifact, V4).
KNOWN_RESULT_KEY_KINDS: frozenset[str] = (
    frozenset(_LINK_KINDS) | _ACK_ONLY_KINDS | frozenset({"perform_batch"})
)


def _describe_arc_outcome(arc: dict[str, Any], *, fingerprinted: bool) -> str:
    """One perform arc, as a line an author can act on: which envelope, over
    which beats, what happened to it, and how many values the pass actually
    wrote. The write count is there because it is the number that separates a
    real recording from a stale lane answering for one.

    The verdict comes from the handler's own ``outcome`` where it is present,
    not from whether a warning came back. Those two answer different questions:
    an envelope deleted mid-cycle also produces a warning, and printing
    UNVERIFIED for it would send the reader hunting a recording fault that
    never happened. ``fingerprinted`` is the fallback for a server predating
    the field, and is named for what it actually observed.
    """
    span = arc.get("span_beats") or []
    where = (
        f"[{float(span[0]):g}-{float(span[1]):g}] " if len(span) == 2 else ""
    )
    outcome = arc.get("outcome")
    if outcome is None:
        verdict = "recorded" if fingerprinted else "UNVERIFIED"
    elif outcome == PERFORM_OUTCOME_RECORDED:
        verdict = "recorded" if fingerprinted else "recorded, NOT FINGERPRINTED"
    else:
        verdict = str(outcome).upper()
    return (
        f"{arc.get('arc_id')} {where}{verdict} "
        f"({arc.get('updates_written')} value writes)"
    )


def apply_push_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
    notes_sink: Callable[[str], None] | None = None,
) -> list[str]:
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

    Dispatch is table-driven: see `_LINK_KINDS` (writes a link binding),
    `_ACK_ONLY_KINDS` (no DB write), and the `perform_batch` branch (per-arc
    performed-automation state). An unknown kind raises `ValueError` so a new
    planner-emitted key kind can't silently no-op past this layer.

    Failed results (`ok=False`) are skipped — the agent layer is the source
    of truth for tool-side errors; hallucinote records nothing for them.

    ``notes_sink`` receives operator-facing lines that are NOT problems — the
    perform phase's per-arc roll-up, which is worth reading precisely when
    nothing went wrong. The returned warnings ride the errors file, so a clean
    push must not put anything there; without a second channel the choice is
    between an accurate report that looks failed and a phase that spends
    minutes of realtime and says only "ok (1 call)". The caller supplies the
    benign channel it already has.

    Returns apply-layer warnings (empty when everything recorded cleanly).
    Today these come from the `perform_batch` branch: for any arc the handler
    could not confirm it recorded, the apply layer records nothing for that
    arc and the warning says so (never a silent skip; the next push retries
    just that arc). `record_perform_result` states the gate that decides
    that — restating it here is how this paragraph went stale once already.
    A degraded locate is warned about on the same channel. Callers must
    surface them.
    """
    warnings: list[str] = []
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

            if kind == "perform_batch":
                # ENV-9P4T single-pass batched performed automation: the
                # handler returns a per-arc result list, each arc carrying
                # its opaque `arc_id` (the envelope id the planner stamped)
                # and its own `automation_state`. Each arc records its
                # fingerprint INDEPENDENTLY, gated on ITS automation_state
                # == 1 — one unverified arc must not block the others, and
                # an unverified write leaves that arc's fingerprint
                # unwritten so the next push retries just that arc
                # (record_perform_result owns the per-arc policy). The
                # perform_batch handler RETURNS a non-1 state, not a raise.
                res = r.get("result") or {}
                # A restore failure means the pass may have left the set
                # ARMED (record_mode / a gesture / playhead not restored) —
                # operator-actionable, never swallowed.
                for failure in res.get("restore_failures", []):
                    warnings.append(
                        f"perform_batch: a transport-state restore step "
                        f"FAILED ({failure}) — the Live set may be left armed "
                        "or the playhead moved; check record_mode in Live."
                    )
                processed = 0
                outcomes: list[str] = []
                for arc in res.get("arcs", []):
                    arc_eid = arc.get("arc_id")
                    if not arc_eid:
                        raise ValueError(
                            f"perform_batch result arc missing 'arc_id' "
                            f"(key={key!r}): {arc!r}"
                        )
                    perform_warning = record_perform_result(
                        conn,
                        envelope_id=arc_eid,
                        session_id=session_id,
                        result=arc,
                        actor=actor,
                        request_id=request_id,
                        reason=reason,
                    )
                    if perform_warning is not None:
                        warnings.append(perform_warning)
                    outcomes.append(
                        _describe_arc_outcome(
                            arc, fingerprinted=perform_warning is None
                        )
                    )
                    processed += 1
                # A realtime phase that spends minutes of wall clock and
                # reports "ok (1 call)" gives the author nothing to act on —
                # the divergence this names was found by ear, three passes
                # late. Say what happened to every arc, not just the ones that
                # failed, and say it on the benign channel so a clean push
                # still reads as clean.
                if outcomes and notes_sink is not None:
                    notes_sink(
                        "performed-automation: " + "; ".join(outcomes)
                    )
                # How the transport was positioned. A pass that ran on a
                # degraded locate recorded against a start position nothing
                # moved — it may well be right, and a per-arc verdict cannot
                # say. The handler logs it, but that log is in Live; this is
                # where the author looks.
                if res.get("start_position_moved") is False:
                    warnings.append(
                        "perform_batch: the transport was positioned by "
                        f"{res.get('locate_method')!r}, which moves the "
                        "playhead but NOT Live's start playing position — "
                        "playback was not guaranteed to begin at the span. "
                        + (
                            f"Reason: {res['locate_detail']} "
                            if res.get("locate_detail") else ""
                        )
                        + "The arcs above recorded, but check the lanes "
                        "landed where you authored them."
                    )
                # ENV-8K2R #4: planned-vs-returned cross-check. The handler
                # reports `arc_count` = how many arcs it prepared (== the
                # planner's queued count on the success path). If fewer per-arc
                # entries came back — a truncated wire payload, or an empty arcs
                # list — the missing arcs recorded NOTHING and would re-perform
                # every push with no signal. Surface the disagreement instead of
                # silently trusting a short result.
                expected = res.get("arc_count")
                if expected is not None and processed != expected:
                    warnings.append(
                        f"perform_batch: handler reported arc_count={expected} "
                        f"but the result carried {processed} per-arc "
                        f"entr{'y' if processed == 1 else 'ies'} — the counts "
                        "disagree, so some arcs may have recorded nothing (they "
                        "re-perform next push). Suspect a truncated wire payload."
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
                f"unknown push result key kind {kind!r} (full key={key!r}); "
                f"known kinds: {sorted(KNOWN_RESULT_KEY_KINDS)}. "
                "Declare it in _LINK_KINDS / _ACK_ONLY_KINDS (or add a "
                "dedicated branch like 'perform_batch') in sync/push/plan.py."
            )
    return warnings
