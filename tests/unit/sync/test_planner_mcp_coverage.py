"""Drift canary — planner ↔ hallucinote-mcp surface coverage.

W3-A (2026-05-18). The 2026-05-18 falling-walking push exposed silent
drift: ``plan_push_cue_points`` emitted ``create_cue_point(bar, beat, name)``
while the actual MCP surface had moved to
``ableton_arrangement(action='cue_create', position_beats=…)``. No test
caught it because the planner is unit-tested against its own emitted
shape, never validated against the canonical MCP surface.

This canary makes the planner↔MCP coupling structural. For every
``plan_push_*`` emitter we:

1. **Name check** — assert every emitted ``ToolCall.tool`` either:
   - matches a hallucinote-mcp tool (``schema.TOOLS``), OR
   - is one of the explicit emulator placeholders in
     :data:`KNOWN_EMULATORS` — kept tiny and audited.

2. **Argument-shape check** — for tools registered in the MCP, build a
   ``wire.Request`` and call the local dispatcher with ``context=None``.
   The dispatcher validates tool / action / params shape and returns
   either ``ok=True`` (server-side-only actions, e.g. help) or
   ``ok=False`` with ``needs_remote=True`` (validated but requires
   Live). Any other response means we drifted on names, actions, or
   param shapes — fail the test with the dispatcher's own teaching
   error.

The fixture (``_synthetic_song``) seeds at least one row in every
domain the planners read, so every plan-push entry point returns a
non-empty plan and contributes calls to the cross-check. A planner
that emits zero calls is itself a regression — caught by the
``test_<planner>_emits_calls`` parametrized assertion below.

When a new planner ships, register it in :data:`_ALL_PLANNERS`. When a
new MCP tool ships, no change needed (it's discovered automatically).
When a new emulator placeholder ships, add it to :data:`KNOWN_EMULATORS`
WITH A COMMENT explaining why a single MCP call can't express it — the
allowlist is the audit trail of acknowledged gaps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push
from hallucinote.sync.mcp_names import resolve

from hallucinote_mcp import schema, wire
from hallucinote_mcp import actions as _actions  # noqa: F401 — side-effect: populates schema._REGISTRY
from hallucinote_mcp.dispatcher import dispatch

# Match `hallucinote_mcp.server.create_server` boot order: actions register
# first (above), then help is grafted onto every tool. Without this the
# dispatcher reports "unknown action 'help'" — not a real drift, just a
# registry-incomplete artifact of the test environment.
schema.register_help_actions()


# Emulator placeholders the planner is allowed to emit when no single
# MCP primitive exists. Adding to this list requires explaining WHY:
# the comment is the structural rationale that lets a future reader
# evaluate whether the gap is still real.
KNOWN_EMULATORS: frozenset[str] = frozenset({
    # Live exposes Song.tempo (global) + per-bar tempo automation envelopes,
    # but no single "set tempo at this bar" primitive. The agent must
    # decompose: ableton_session(set_tempo) for the global value; envelope
    # writes for ramps; tempo automation at arbitrary (bar, beat) remains a
    # hard MCP gap blocked on Live's tempo-envelope target_kind.
    "_emulate_write_tempo_point",
    # Live has NO arrangement-level meter-change API exposed. The
    # planner emits the canonical (bar, beat, numerator, denominator)
    # shape; the emulator is a no-op-with-warn until the Live gap closes.
    "_emulate_write_time_signature_point",
})


# Every plan_push_* entry point the canary exercises. The CALLABLE takes
# `(conn, *, song_id, session_id)` and returns a `PushPlan`. Planners
# with a different signature (e.g. `plan_push_clip(clip_id=…)`) get a
# small adapter below so the iteration stays uniform.
@dataclass(frozen=True)
class PlannerEntry:
    name: str
    invoke: Callable  # (conn, song_id, session_id) -> PushPlan
    must_emit_calls: bool  # if False, an empty plan is acceptable


# ---------------------------------------------------------------------------
# Synthetic song fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "canary.db")
    yield c
    c.close()


@pytest.fixture
def synthetic_song(conn) -> dict:
    """One row in every domain the planners query.

    Returns a dict carrying the IDs the planners and their adapters
    need: ``song_id``, ``session_id``, ``track_id``, ``clip_id``,
    ``return_id``. The shape is fixed; tests below thread it through.
    """
    song_id = M.create_song(conn, name="canary", title="Canary Song")

    # Globals: tempo + meter + a cue + a section so the score-half
    # planners emit something.
    M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(
        conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
    )
    M.add_cue_point(conn, song_id=song_id, position_bar=1.0, name="intro")
    M.create_section(
        conn, song_id=song_id, name="intro", start_bar=1.0, end_bar=5.0,
    )

    # One MIDI track + one return + one send (mix planner).
    track_id = M.create_track(
        conn, song_id=song_id, track_index=1, name="Lead", kind="midi",
    )
    return_id = M.create_return(
        conn, song_id=song_id, name="A-Reverb", position=1, volume=0.85,
    )
    M.set_send_level(
        conn, from_track_id=track_id, to_return_id=return_id, level=0.3,
    )

    # One session clip + one arrangement placement (clip + arrangement planners).
    clip_id = M.create_clip(
        conn, track_id=track_id, slot=1, length_beats=8.0, name="Lead-1",
    )
    M.add_arrangement_clip(
        conn, song_id=song_id, track_id=track_id, clip_id=clip_id,
        start_bar=1.0, end_bar=3.0,
    )

    # One device on the track's top-level chain (devices planner).
    chain_id = M.create_device_chain(conn, parent_track_id=track_id, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Reverb", display_name="Reverb",
    )

    # One envelope (envelopes planner). DB-side model for mixer_volume is
    # track-scoped (target_track_id only) — the planner is what resolves
    # this to a session-clip-scoped MCP write under W3-E.
    env_id = M.create_envelope(
        conn, song_id=song_id, target_kind="mixer_volume",
        target_track_id=track_id,
    )
    M.add_breakpoint(conn, envelope_id=env_id, time_beats=0.0, value=0.5)
    M.add_breakpoint(conn, envelope_id=env_id, time_beats=4.0, value=0.85)

    # Session + link the track & clip & return so plan_push_clip,
    # plan_push_mix, plan_push_arrangement see them as already-linked.
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="canary-session", actor="sync",
    )
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="track", db_id=track_id, ableton_index=1,
        actor="sync",
    )
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id, ableton_index=1,
        actor="sync",
    )
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="return", db_id=return_id, ableton_index=1,
        actor="sync",
    )

    return {
        "song_id": song_id,
        "session_id": session_id,
        "track_id": track_id,
        "clip_id": clip_id,
        "return_id": return_id,
    }


# ---------------------------------------------------------------------------
# Planner registry
# ---------------------------------------------------------------------------


def _plan_clip(conn, *, song_id, session_id, clip_id, **_):
    """Adapter — plan_push_clip is per-clip; emit for our canary clip."""
    return push.plan_push_clip(conn, clip_id=clip_id, session_id=session_id)


_ALL_PLANNERS: tuple[PlannerEntry, ...] = (
    PlannerEntry(
        name="plan_push_tempo_map",
        invoke=lambda conn, **kw: push.plan_push_tempo_map(conn, song_id=kw["song_id"]),
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_time_signature_map",
        invoke=lambda conn, **kw: push.plan_push_time_signature_map(conn, song_id=kw["song_id"]),
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_cue_points",
        invoke=lambda conn, **kw: push.plan_push_cue_points(conn, song_id=kw["song_id"]),
        must_emit_calls=True,
    ),
    PlannerEntry(
        # Sections are DB-only — Live has no section primitive. Planner
        # emits zero calls by design; canary asserts that's still true.
        name="plan_push_sections",
        invoke=lambda conn, **kw: push.plan_push_sections(conn, song_id=kw["song_id"]),
        must_emit_calls=False,
    ),
    PlannerEntry(
        name="plan_push_clip",
        invoke=_plan_clip,
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_arrangement",
        invoke=lambda conn, **kw: push.plan_push_arrangement(
            conn, song_id=kw["song_id"], session_id=kw["session_id"],
        ),
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_mix",
        invoke=lambda conn, **kw: push.plan_push_mix(
            conn, song_id=kw["song_id"], session_id=kw["session_id"],
        ),
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_devices",
        invoke=lambda conn, **kw: push.plan_push_devices(
            conn, song_id=kw["song_id"], session_id=kw["session_id"],
        ),
        must_emit_calls=True,
    ),
    PlannerEntry(
        name="plan_push_envelopes",
        invoke=lambda conn, **kw: push.plan_push_envelopes(
            conn, song_id=kw["song_id"], session_id=kw["session_id"],
        ),
        must_emit_calls=True,
    ),
)


# ---------------------------------------------------------------------------
# Per-planner: must emit calls (catches "planner silently returns nothing")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("planner", _ALL_PLANNERS, ids=lambda p: p.name)
def test_planner_emits_calls(conn, synthetic_song, planner):
    """Every must_emit_calls planner produces at least one ToolCall on
    the fully-populated synthetic song. A planner silently returning an
    empty plan is itself a regression."""
    plan = planner.invoke(conn, **synthetic_song)
    if planner.must_emit_calls:
        assert plan.calls, (
            f"{planner.name} returned zero calls on the fully-populated "
            "canary fixture — either the planner regressed or the fixture "
            "missed a row it queries"
        )


# ---------------------------------------------------------------------------
# Canary: every emitted ToolCall resolves to a callable MCP shape
# ---------------------------------------------------------------------------


def _check_call_shape(call) -> str | None:
    """Validate one ToolCall. Returns None on pass, error string on fail.

    Three failure modes:
      1. Emitted tool is neither MCP-registered nor in KNOWN_EMULATORS.
      2. Tool is MCP-registered but ``args`` lacks 'action'.
      3. Tool+action+params don't pass server-side dispatch validation.
    """
    resolved = resolve(call.tool)

    # Emulator placeholders: allowed iff in the explicit allowlist.
    if resolved.startswith("_emulate_"):
        if resolved not in KNOWN_EMULATORS:
            return (
                f"emulator placeholder {resolved!r} is not in KNOWN_EMULATORS — "
                "either register it in test_planner_mcp_coverage.KNOWN_EMULATORS "
                "with a rationale comment, or refactor the planner to emit a "
                "real hallucinote-mcp call"
            )
        return None

    # Otherwise must be a registered hallucinote-mcp tool.
    if resolved not in schema.TOOLS:
        return (
            f"emitted tool {resolved!r} is not in hallucinote_mcp.schema.TOOLS "
            f"({list(schema.TOOLS)}) — planner drifted from the MCP surface. "
            "Either rename the planner's emit or add a mcp_names.ALIASES_TODAY "
            "entry pointing to an _emulate_* placeholder"
        )

    # Server-side dispatch must accept the (tool, action, params) triple.
    args = dict(call.args)
    action = args.pop("action", None)
    if not action:
        return (
            f"call to {resolved!r} has no 'action' in args — every unified-tool "
            "call must include action=<name>"
        )

    req = wire.Request(tool=resolved, action=action, params=args)
    resp = dispatch(req, context=None)

    if resp.ok:
        # Action handled entirely server-side (e.g. action='help'). Fine.
        return None
    if resp.needs_remote:
        # Validated; would forward to Live. Fine.
        return None

    # Dispatcher rejected the call shape — exactly the drift we're hunting.
    return (
        f"server-side dispatch rejected {resolved}(action={action!r}): "
        f"{resp.error!r}"
        + (f" — hint: {resp.hint}" if resp.hint else "")
    )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "W3-A introduces the canary with 2 known drift cases pending fixes:\n"
        "  1. plan_push_cue_points emits stale `create_cue_point` "
        "(W3-B fixes; switch to ableton_arrangement(cue_create_batch)).\n"
        "  2. plan_push_arrangement emits `_emulate_batch_arrangement_layout` "
        "(W3-D fixes; decomposes into N ableton_clip(duplicate_to_arrangement)).\n"
        "Remove this xfail marker in W3-D once both land — the canary should be "
        "GREEN going forward as the contract that prevents future drift."
    ),
)
def test_every_planner_emit_passes_dispatcher_validation(conn, synthetic_song):
    """The canary. Every ToolCall every planner emits must:
      - Name-resolve to either schema.TOOLS or KNOWN_EMULATORS.
      - For schema.TOOLS entries: pass server-side dispatch validation
        (i.e. dispatcher returns ok=True or needs_remote=True).

    Failures are collected and reported in one shot so the wave-3
    chunks can see every drift case at once instead of fix-then-rerun.
    """
    failures: list[tuple[str, str, str]] = []  # (planner_name, key, error)

    for planner in _ALL_PLANNERS:
        plan = planner.invoke(conn, **synthetic_song)
        for call in plan.calls:
            err = _check_call_shape(call)
            if err is not None:
                failures.append((planner.name, call.key, err))

    if failures:
        lines = [f"planner↔MCP drift in {len(failures)} call(s):", ""]
        for planner_name, key, err in failures:
            lines.append(f"  [{planner_name}] {key}")
            lines.append(f"      {err}")
        pytest.fail("\n".join(lines))


def test_known_emulators_allowlist_stays_audited():
    """The KNOWN_EMULATORS allowlist is small and audited. If a future
    chunk silently grows it past the documented set, this test fails so
    a reviewer notices."""
    # Every entry must have an _emulate_ prefix (structural marker).
    for name in KNOWN_EMULATORS:
        assert name.startswith("_emulate_"), (
            f"KNOWN_EMULATORS entry {name!r} lacks '_emulate_' prefix"
        )

    # The allowlist size is part of the contract — if you genuinely
    # added a new gap-blocked emulator, bump this assertion deliberately.
    assert len(KNOWN_EMULATORS) == 2, (
        f"KNOWN_EMULATORS has {len(KNOWN_EMULATORS)} entries (expected 2). "
        "Every emulator placeholder represents an acknowledged Live gap — "
        "bumping this requires confirming the gap is real and adding a "
        "rationale comment to KNOWN_EMULATORS itself."
    )
