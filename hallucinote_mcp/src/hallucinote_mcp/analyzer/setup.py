"""Silent analyzer auto-load orchestration.

``ensure_analyzers_loaded(context)`` is the idempotent sweep that
guarantees every audio track + every return + the master strip carries
a HallucinoteAnalyzer instance. It is the **entry point** for every
analyzer-aware MCP action — ``ableton_render`` calls it in its
preamble; the ``/song-new`` / ``/track-new-with-instrument`` /
``/return-new`` skills call it as a postlude after structural mutations
so the user never thinks about analyzer placement.

**Pre-2B failure mode (intentional).** After loading the analyzer,
``_ensure_on_surface`` writes the per-instance ``Port`` + ``EmitPort``
Live params (so per-analyzer OSC ports actually take effect — see the
test ``test_sweep_writes_per_instance_port_via_live_param``). Until
sub-chunk 2B authors those params into ``HallucinoteAnalyzer.amxd``
per the spec, ``set_parameter_handler`` will raise a teaching error
from the param-not-found path. This is deliberate — silent fallback
would let two analyzers collide on port 11000 and cross-contaminate
render targets. The 2A/2B split owns this gap per the
"Human-authoring boundaries split the chunk" learning.

Idempotency is the load-bearing property. Two consecutive sweeps on
the same session must produce identical layouts (no duplicate
analyzer instances, no port re-shuffles). The detection key is the
device's ``class_display_name`` — for M4L devices Live surfaces this
as the ``.amxd`` filename (without extension), so a present analyzer
shows up as ``HallucinoteAnalyzer``. The OSC `/signature?` query is
the second-level check for distinguishing patch versions; the MVP
trusts the name match.

Port assignment is deterministic per surface kind + index so the next
sweep recovers the same layout without inspecting prior state:

- track ``N`` → inbound port ``11020 + (N - 1)`` (up to 100 audio tracks)
- return ``N`` → inbound port ``11120 + (N - 1)`` (up to 100 returns)
- master      → inbound port ``11220``

Outbound emit port is a shared singleton (default ``11221``) so the
sidecar opens one UDP socket. Multiple emitters fanning into one
listener is the expected shape.

The base is 11020 (not the obvious 11000) to clear AbletonOSC, the most
common community Remote Script for Live: AbletonOSC binds 11000 + 11001
by convention, so Hallucinote's track 1 + 2 analyzers would collide.
Shifting 20 ports up clears the conflict and leaves room (11002-11019)
for future community Remote Scripts following similar conventions.

The whole 11020-11221 layout fits inside the .amxd's `Port` parameter
range (declared 11000-11400 in HallucinoteAnalyzer.amxd) with headroom
above for future expansion.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..dispatcher import LiveContext
from ..handlers import device as device_handlers


ANALYZER_DEVICE_NAME = "HallucinoteAnalyzer"
"""The M4L device file (without extension). Live surfaces this as
``device.class_display_name`` for M4L devices, so a present analyzer
matches by exact string."""

ANALYZER_BROWSER_PATH_PREFIX = ("Presets", "Audio Effects", "Max Audio Effect")
"""Browser path under the ``user_library`` root where the install
skill places the .amxd. Used by the analyzer-load ``preset_query`` —
narrowing to this exact location prevents a user-saved preset named
``HallucinoteAnalyzer`` elsewhere in their library from shadowing the
canonical device. Match: ``user_library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer``.

This MUST stay in sync with ``install_paths.analyzer_install_target`` —
that's where the install skill writes the file."""

ANALYZER_SIGNATURE = "hallucinote-analyzer-v1"
"""Version-tagged identity reported by the patch in reply to OSC
`/signature/query`. The MVP doesn't query — name matching is enough —
but the constant lives here for use in tests + future v2 patches."""

DEFAULT_EMIT_PORT = 11221
"""Sidecar listen port. Every analyzer's ``EmitPort`` Live parameter
defaults to this so one shared UDP socket receives all feature frames.
Sits past the master analyzer's inbound port (11220) — can't be 11021
with stride-1 inbound because that's track 2's inbound port."""

_TRACK_PORT_BASE = 11020
_RETURN_PORT_BASE = 11120
_MASTER_PORT = 11220
_PORT_STRIDE = 1
# Stride 1 packs tracks tightly (track N at 11020+N-1, return N at
# 11120+N-1) and supports 100 tracks + 100 returns + master + sidecar
# emit comfortably within 11020-11221. The `Port` / `EmitPort`
# `live.numbox` Live parameters declare Type=Float with Unit Style=Int
# to render as integers in the UI without hitting M4L's 256-step Int
# parameter cap (Live encodes Int automation as a byte; max-min > 255
# silently clamps in Max). See learnings.md "M4L Int parameter range
# capped at 256 — use Float + Unit Style Int".
#
# Why 11020+, not 11000+? AbletonOSC (a popular community Remote Script)
# binds ports 11000 + 11001 by convention — track 1's analyzer at 11000
# can't bind because AbletonOSC owns it; track 2's analyzer at 11001
# collides with AbletonOSC's outbound socket. Shifting the base 20 ports
# clears the AbletonOSC collision and leaves room (11002-11019) for
# future community Remote Scripts that follow similar conventions.

_INTER_SURFACE_YIELD_S = 0.05
# Worker-thread sleep between per-surface load+configure bouts. Without
# this, packing N surfaces × 3 ops (load + 2 set_param) into one
# Remote-Script request-thread call deadlocks Live's main thread on the
# M4L runtime — empirically observed 2026-05-27 trying to load 9
# analyzers in a single ensure_loaded MCP call (Live's beachball for
# minutes). Same shape as the cue_create batch's settle pattern in
# handlers/arrangement.py: each Live touch is its own
# context.run_on_main bout; wall-clock waits between bouts on the
# WORKER thread free the main thread to pump notifications + M4L
# runtime events (browser.load_item triggers a device-add cascade Live
# needs to flush before the next load can succeed).


@dataclass(frozen=True)
class AnalyzerInstance:
    """One HallucinoteAnalyzer placement.

    The address triple (``surface_kind``, ``surface_index``, ``device_index``)
    identifies where the analyzer lives in Live's chain layout. The
    ``track_id`` is the opaque string the patch echoes into its
    outbound feature frames — sidecar consumers route by this.
    """

    surface_kind: str  # 'track' | 'return' | 'master'
    surface_index: int  # 1-based; 0 for master
    surface_name: str
    device_index: int  # 1-based position in the chain
    track_id: str
    osc_port: int
    osc_emit_port: int
    was_loaded: bool  # True if this sweep loaded it; False if pre-existing


@dataclass(frozen=True)
class AnalyzerLayout:
    """Result of one ensure_analyzers_loaded sweep."""

    instances: tuple[AnalyzerInstance, ...]

    def by_track_id(self) -> dict[str, AnalyzerInstance]:
        return {inst.track_id: inst for inst in self.instances}

    def by_surface(
        self,
    ) -> dict[tuple[str, int], AnalyzerInstance]:
        return {
            (inst.surface_kind, inst.surface_index): inst
            for inst in self.instances
        }

    @property
    def loaded_count(self) -> int:
        return sum(1 for i in self.instances if i.was_loaded)

    @property
    def existing_count(self) -> int:
        return sum(1 for i in self.instances if not i.was_loaded)


# --- public API ------------------------------------------------------


def ensure_analyzers_loaded(
    context: LiveContext,
    *,
    emit_port: int = DEFAULT_EMIT_PORT,
) -> AnalyzerLayout:
    """Idempotent silent sweep — guarantee one analyzer on every surface.

    Walks Live's audio tracks, return tracks, and master, loading
    HallucinoteAnalyzer where absent. Group tracks and MIDI tracks are
    skipped — group tracks are routing aggregations (no audio output of
    their own) and MIDI tracks have no audio inlet to tap. Audio tracks,
    returns, and master are the surfaces that produce audio worth
    capturing.

    Returns an ``AnalyzerLayout`` describing every placement. Repeated
    calls on the same Live session produce equivalent layouts (port
    assignment is a pure function of the surface address).

    Worker-thread caller invariant. The two registered actions that
    invoke this (``ableton_render(action='ensure_loaded')`` and
    ``ableton_render(action='render')``) both run with
    ``runs_on_worker=True``. Each per-surface load + 2× set_parameter
    bout marshals onto Live's main thread via ``context.run_on_main``;
    between surfaces, we sleep on the worker thread to let Live's main
    thread pump the device-add notification cascade that ``load_item``
    triggers. Without this yield the request-thread call deadlocks the
    M4L runtime.
    """
    instances: list[AnalyzerInstance] = []
    # Read the surface lists on the main thread — touching ``song.tracks``
    # / ``song.return_tracks`` / ``song.master_track`` from the worker is
    # unsafe in real Live (the lists may mutate under the read). Capture
    # what we need into worker-local data before iterating.
    surface_plan = context.run_on_main(lambda: _plan_surfaces(context.song))

    for plan in surface_plan:
        if plan.surface_kind == "track":
            osc_port = _TRACK_PORT_BASE + (plan.surface_index - 1) * _PORT_STRIDE
        elif plan.surface_kind == "return":
            osc_port = _RETURN_PORT_BASE + (plan.surface_index - 1) * _PORT_STRIDE
        else:
            osc_port = _MASTER_PORT
        inst = _ensure_on_surface(
            context,
            surface_kind=plan.surface_kind,
            surface_index=plan.surface_index,
            surface_name=plan.surface_name,
            track_address=plan.track_address,
            osc_port=osc_port,
            osc_emit_port=emit_port,
        )
        instances.append(inst)
        # Yield between surfaces so Live's main thread can flush the
        # device-add notification cascade triggered by browser.load_item.
        # Skipping this is what causes the deadlock when N surfaces are
        # swept inside one MCP request.
        time.sleep(_INTER_SURFACE_YIELD_S)

    return AnalyzerLayout(instances=tuple(instances))


@dataclass(frozen=True)
class _SurfacePlan:
    """One surface to sweep, captured on the main thread before the
    worker-side load loop iterates. Decouples the iteration order from
    Live's live track-list mutation."""

    surface_kind: str
    surface_index: int
    surface_name: str
    track_address: dict[str, Any]


def _plan_surfaces(song: Any) -> list[_SurfacePlan]:
    """Snapshot every surface that needs an analyzer. Called once on the
    main thread; result drives the worker-side per-surface load loop."""
    plan: list[_SurfacePlan] = []
    for i, track in enumerate(song.tracks, start=1):
        if not _track_carries_audio(track):
            continue
        plan.append(_SurfacePlan(
            surface_kind="track",
            surface_index=i,
            surface_name=_track_name(track),
            track_address={"track_index": i},
        ))
    for i, ret in enumerate(song.return_tracks, start=1):
        plan.append(_SurfacePlan(
            surface_kind="return",
            surface_index=i,
            surface_name=_track_name(ret),
            track_address={"return_index": i},
        ))
    plan.append(_SurfacePlan(
        surface_kind="master",
        surface_index=0,
        surface_name=_track_name(song.master_track),
        track_address={"master": True},
    ))
    return plan


def track_id_for_surface(surface_kind: str, surface_index: int) -> str:
    """Deterministic, structurally-stable track_id.

    Used as the opaque string the patch echoes into its outbound
    feature frames. Stability matters because the sidecar's ring
    buffers are keyed by this — re-keying between renders would
    lose continuity. The format is intentionally machine-readable
    (consumers can split on ``:``) but not enforced as schema —
    sidecar consumers treat it as opaque.
    """
    if surface_kind == "master":
        return "master"
    if surface_kind == "track":
        return f"track:{surface_index}"
    if surface_kind == "return":
        return f"return:{surface_index}"
    raise ValueError(
        f"unknown surface_kind {surface_kind!r}; "
        "expected 'track', 'return', or 'master'"
    )


# --- internals -------------------------------------------------------


def _ensure_on_surface(
    context: LiveContext,
    *,
    surface_kind: str,
    surface_index: int,
    surface_name: str,
    track_address: dict[str, Any],
    osc_port: int,
    osc_emit_port: int,
) -> AnalyzerInstance:
    """Place (or detect) an analyzer on one surface, then assert its
    per-instance OSC ports via Live parameters. Returns the instance.

    Caller invariant: runs on the WORKER thread. Each Live touch
    (detect-existing read + load_handler + 2× set_parameter_handler)
    is its own ``context.run_on_main`` bout. This is required because
    the calling action is registered ``runs_on_worker=True`` — the
    dispatcher does NOT wrap the handler in a main-thread bout, so the
    handler is responsible for marshaling every Live access itself.
    """
    track_id = track_id_for_surface(surface_kind, surface_index)
    existing_idx = context.run_on_main(
        lambda: _find_analyzer_index(_existing_devices_for(context, track_address))
    )
    if existing_idx is None:
        # Load via preset_query, NOT kind=. The .amxd is placed under
        # ``user_library/Presets/Audio Effects/Max Audio Effect/`` by
        # the install skill, but ``kind=`` triggers a walk that only
        # covers the built-in browser roots (instruments / audio_effects
        # / midi_effects / drums per ``_BROWSER_LOAD_ROOTS``). The
        # User Library is reachable via ``preset_uri`` or ``preset_query``
        # — we use ``preset_query`` because the URI is per-machine
        # (Live's FileId varies). The ``path_prefix`` pins the exact
        # location so a user-saved preset named "HallucinoteAnalyzer"
        # elsewhere in their library can't shadow the canonical device.
        # If the .amxd is absent, ``_resolve_preset_query`` raises a
        # teaching error ("preset_query found no loadable matches").
        result = context.run_on_main(lambda: device_handlers.load_handler(
            context,
            kind=ANALYZER_DEVICE_NAME,  # required by signature; preset_query takes precedence
            preset_query={
                "root": "user_library",
                "pattern": ANALYZER_DEVICE_NAME,
                "path_prefix": list(ANALYZER_BROWSER_PATH_PREFIX),
                "mode": "substring",
            },
            **track_address,
        ))
        device_index = int(result.get("device_index", 0))
        if device_index < 1:
            raise RuntimeError(
                f"ensure_analyzers_loaded: load_handler returned "
                f"device_index {device_index!r} for {surface_kind} "
                f"{surface_index} ({surface_name!r}); expected a 1-based index"
            )
        was_loaded = True
    else:
        device_index = existing_idx
        was_loaded = False

    # Assert per-instance ports via Live params. The `Port` parameter
    # drives `[udpreceive]` so two analyzers listening on the same port
    # would both receive every `/path` (cross-contamination of write
    # destinations). `EmitPort` drives `[udpsend]` to the sidecar; the
    # default (DEFAULT_EMIT_PORT) is correct for the MVP one-sidecar
    # shape, but we set it explicitly to make per-instance overrides
    # straightforward in future. Both writes are idempotent — Live's
    # set_parameter on an already-equal value is a no-op event.
    context.run_on_main(lambda: device_handlers.set_parameter_handler(
        context,
        device_index=device_index,
        parameter_name="Port",
        value=str(float(osc_port)),
        value_type="continuous",
        **track_address,
    ))
    context.run_on_main(lambda: device_handlers.set_parameter_handler(
        context,
        device_index=device_index,
        parameter_name="EmitPort",
        value=str(float(osc_emit_port)),
        value_type="continuous",
        **track_address,
    ))

    return AnalyzerInstance(
        surface_kind=surface_kind,
        surface_index=surface_index,
        surface_name=surface_name,
        device_index=device_index,
        track_id=track_id,
        osc_port=osc_port,
        osc_emit_port=osc_emit_port,
        was_loaded=was_loaded,
    )


def _existing_devices_for(
    context: LiveContext, track_address: dict[str, Any],
) -> list[Any]:
    """Return the device-chain list for the surface named by track_address.
    Called from inside ``run_on_main`` — touches Live's track objects."""
    song = context.song
    if track_address.get("master"):
        return list(song.master_track.devices)
    if "track_index" in track_address:
        return list(song.tracks[track_address["track_index"] - 1].devices)
    if "return_index" in track_address:
        return list(song.return_tracks[track_address["return_index"] - 1].devices)
    raise ValueError(
        f"track_address {track_address!r} has no recognized surface key "
        "(expected one of: master, track_index, return_index)"
    )


_M4L_AUDIO_EFFECT_CLASS = "Max Audio Effect"
"""Live's ``device.class_display_name`` for any M4L audio-effect device.
Every .amxd of type ``amxd~ audioeffect`` surfaces under this single
class. The .amxd filename (sans extension) is in ``device.name``."""


def _find_analyzer_index(devices: list[Any]) -> int | None:
    """1-based device_index of the first HallucinoteAnalyzer in the chain.

    M4L identity surface in Live's device-object API:
      - ``class_display_name`` is ``"Max Audio Effect"`` for every
        M4L audio effect — does NOT distinguish individual .amxd files.
      - ``name`` is the .amxd filename without extension
        (``"HallucinoteAnalyzer"`` for our device), though it's
        user-renameable in Live's session.

    Strategy: require BOTH ``class_display_name == "Max Audio Effect"``
    (proves it's an M4L device, not a similarly-named user preset)
    AND ``name == ANALYZER_DEVICE_NAME`` (proves it's specifically our
    .amxd). The combination is robust against name collisions with
    user-saved non-M4L presets, and a user who renames the analyzer
    in their session will get a duplicate on the next sweep — that's
    a known limitation; for canonical identity the spec defines the
    OSC ``/signature/query`` round-trip, but that's heavier and not
    needed for the MVP idempotency surface.

    Earlier versions of this function compared only against
    ``class_display_name``, which is permanently ``"Max Audio Effect"``
    for any M4L device — so detection was always False and
    ``ensure_loaded`` added a duplicate on every call.

    If multiple analyzers are present (user-side duplicate from a
    prior buggy sweep), we return the FIRST one — subsequent ones
    are unreachable by name addressing and a later cleanup pass
    can prune; idempotency of this function trumps duplicate
    removal.
    """
    for i, dev in enumerate(devices, start=1):
        if (
            getattr(dev, "class_display_name", None) == _M4L_AUDIO_EFFECT_CLASS
            and getattr(dev, "name", None) == ANALYZER_DEVICE_NAME
        ):
            return i
    return None


def _track_carries_audio(track: Any) -> bool:
    """Skip MIDI-only tracks (no audio inlet) and Group tracks.

    Live exposes ``has_audio_output`` on every track. Group tracks
    return True but they're routing aggregations of their members —
    capturing the group AND each member would double-count audio.
    For MVP we capture only leaf audio tracks; Chunk 3+ can revisit
    group-aware bus capture if needed.
    """
    if not getattr(track, "has_audio_output", True):
        return False
    if getattr(track, "is_foldable", False):
        # is_foldable is Live's "this is a group / has a fold open/close
        # affordance" flag — True for groups, False for plain audio /
        # MIDI / return / master.
        return False
    # MIDI tracks: has_midi_input=True AND has_audio_input=False (the
    # instrument generates audio internally but the inlet is MIDI). Even
    # so, MIDI-with-instrument DOES emit audio at the device chain's
    # tail — and the analyzer at chain-end will catch it. So include MIDI
    # tracks that have an instrument loaded; skip the ones that don't.
    has_midi = getattr(track, "has_midi_input", False)
    if has_midi:
        # Loaded instrument = at least one device producing audio. Check
        # `has_audio_output` (above already True) is sufficient — Live
        # sets it False on tracks with no instrument loaded.
        return True
    return True


def _track_name(track: Any) -> str:
    return getattr(track, "name", "") or "<unnamed>"


__all__ = [
    "ANALYZER_DEVICE_NAME",
    "ANALYZER_SIGNATURE",
    "AnalyzerInstance",
    "AnalyzerLayout",
    "DEFAULT_EMIT_PORT",
    "ensure_analyzers_loaded",
    "track_id_for_surface",
]
