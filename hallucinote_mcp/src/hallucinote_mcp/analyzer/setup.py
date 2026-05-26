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

- track ``N`` → inbound port ``11000 + 2 * (N - 1)``
- return ``N`` → inbound port ``11100 + 2 * (N - 1)``
- master      → inbound port ``11200``

Outbound emit port is a shared singleton (default ``11001``) so the
sidecar opens one UDP socket. Multiple emitters fanning into one
listener is the expected shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..dispatcher import LiveContext
from ..handlers import device as device_handlers


ANALYZER_DEVICE_NAME = "HallucinoteAnalyzer"
"""The M4L device file (without extension). Live surfaces this as
``device.class_display_name`` for M4L devices, so a present analyzer
matches by exact string."""

ANALYZER_SIGNATURE = "hallucinote-analyzer-v1"
"""Version-tagged identity reported by the patch in reply to OSC
`/signature?`. The MVP doesn't query — name matching is enough — but
the constant lives here for use in tests + future v2 patches."""

DEFAULT_EMIT_PORT = 11001
"""Sidecar listen port. Every analyzer's ``EmitPort`` Live parameter
defaults to this so one shared UDP socket receives all feature frames."""

_TRACK_PORT_BASE = 11000
_RETURN_PORT_BASE = 11100
_MASTER_PORT = 11200
_PORT_STRIDE = 2


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
    """
    instances: list[AnalyzerInstance] = []
    song = context.song

    # Tracks. Live's `track.has_audio_output` is the canonical probe for
    # "produces audio." `has_audio_input == False` skips MIDI-only tracks;
    # `is_foldable` would also skip groups but is_grouping logic differs
    # across Live versions, so we lean on the audio attributes instead.
    for i, track in enumerate(song.tracks, start=1):
        if not _track_carries_audio(track):
            continue
        inst = _ensure_on_surface(
            context,
            surface_kind="track",
            surface_index=i,
            surface_name=_track_name(track),
            track_address={"track_index": i},
            existing_devices=list(track.devices),
            osc_port=_TRACK_PORT_BASE + (i - 1) * _PORT_STRIDE,
            osc_emit_port=emit_port,
        )
        instances.append(inst)

    # Returns.
    for i, ret in enumerate(song.return_tracks, start=1):
        inst = _ensure_on_surface(
            context,
            surface_kind="return",
            surface_index=i,
            surface_name=_track_name(ret),
            track_address={"return_index": i},
            existing_devices=list(ret.devices),
            osc_port=_RETURN_PORT_BASE + (i - 1) * _PORT_STRIDE,
            osc_emit_port=emit_port,
        )
        instances.append(inst)

    # Master.
    inst = _ensure_on_surface(
        context,
        surface_kind="master",
        surface_index=0,
        surface_name=_track_name(song.master_track),
        track_address={"master": True},
        existing_devices=list(song.master_track.devices),
        osc_port=_MASTER_PORT,
        osc_emit_port=emit_port,
    )
    instances.append(inst)

    return AnalyzerLayout(instances=tuple(instances))


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
    existing_devices: list[Any],
    osc_port: int,
    osc_emit_port: int,
) -> AnalyzerInstance:
    """Place (or detect) an analyzer on one surface, then assert its
    per-instance OSC ports via Live parameters. Returns the instance."""
    track_id = track_id_for_surface(surface_kind, surface_index)
    existing_idx = _find_analyzer_index(existing_devices)
    if existing_idx is None:
        # Load. The analyzer's `kind` (browser display name) matches the
        # .amxd filename — Live's browser exposes M4L files under
        # `Max Audio Effect` rooted at the User Library; the load
        # handler's name-matching walk finds it by display name. The
        # install skill places the .amxd in User Library; if absent,
        # this load raises a teaching error from the browser-walk path.
        result = device_handlers.load_handler(
            context,
            kind=ANALYZER_DEVICE_NAME,
            **track_address,
        )
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
    device_handlers.set_parameter_handler(
        context,
        device_index=device_index,
        parameter_name="Port",
        value=str(float(osc_port)),
        value_type="continuous",
        **track_address,
    )
    device_handlers.set_parameter_handler(
        context,
        device_index=device_index,
        parameter_name="EmitPort",
        value=str(float(osc_emit_port)),
        value_type="continuous",
        **track_address,
    )

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


def _find_analyzer_index(devices: list[Any]) -> int | None:
    """1-based device_index of the first HallucinoteAnalyzer in the chain.

    Match by ``class_display_name == ANALYZER_DEVICE_NAME``. For M4L
    devices Live surfaces the .amxd filename here, which is what we
    install. Falls through to ``class_name`` (some Live versions
    populate one but not the other for plain Max Audio Effects). If
    multiple are present (a user-side duplicate from a prior buggy
    sweep), we return the FIRST one — subsequent ones are unreachable
    by name addressing and a later cleanup pass can prune; idempotency
    of this function trumps duplicate removal.
    """
    for i, dev in enumerate(devices, start=1):
        if _is_analyzer(dev):
            return i
    return None


def _is_analyzer(device: Any) -> bool:
    display = getattr(device, "class_display_name", None) or ""
    if display == ANALYZER_DEVICE_NAME:
        return True
    name = getattr(device, "name", None) or ""
    class_name = getattr(device, "class_name", None) or ""
    # Fall through to `name` ONLY when class_display_name is empty — name
    # is user-editable, so a user could rename a non-HallucinoteAnalyzer
    # device to "HallucinoteAnalyzer" and we'd false-positive. The
    # class_name path is the safer fallback for older Live versions.
    return class_name == ANALYZER_DEVICE_NAME or (
        not display and not class_name and name == ANALYZER_DEVICE_NAME
    )


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
