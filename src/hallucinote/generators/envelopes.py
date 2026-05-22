"""Envelope-producing generators.

Pure functions that emit `GeneratorOutput` whose `envelopes` field carries
envelope specs ready to be persisted via `mutations.create_envelope` +
`mutations.replace_breakpoints`. No DB access.

Volume values are in Live's normalized 0.0–1.0 range (matches
`captured_session.json`).
"""
from __future__ import annotations

from typing import Sequence

from hallucinote.generators.output import EnvelopeDict, GeneratorOutput

_VOLUME_BOUNDS = (0.0, 1.0)


def _check_unit(name: str, value: float) -> None:
    lo, hi = _VOLUME_BOUNDS
    if not lo <= value <= hi:
        raise ValueError(
            f"{name}={value} out of normalized range [{lo}, {hi}]"
        )


def volume_swell(
    *,
    target_track_id: str,
    start_beat: float,
    length_beats: float,
    peak_value: float,
    floor_value: float = 0.0,
    curve_kind: str = "linear",
    return_to_floor: bool = False,
    fall_length_beats: float | None = None,
) -> GeneratorOutput:
    """Rising volume envelope on a track from `floor_value` to `peak_value`.

    Produces 2 breakpoints by default (floor → peak across `length_beats`).
    When `return_to_floor=True`, adds a third breakpoint falling back to floor
    over `fall_length_beats` (defaults to `length_beats`).

    `curve_kind` applies to every breakpoint (whole-envelope curve).
    """
    if length_beats <= 0:
        raise ValueError(f"length_beats must be > 0 (got {length_beats})")
    if start_beat < 0:
        raise ValueError(f"start_beat must be >= 0 (got {start_beat})")
    _check_unit("floor_value", floor_value)
    _check_unit("peak_value", peak_value)

    breakpoints = [
        {"time_beats": float(start_beat), "value": float(floor_value),
         "curve_kind": curve_kind},
        {"time_beats": float(start_beat + length_beats), "value": float(peak_value),
         "curve_kind": curve_kind},
    ]
    if return_to_floor:
        fall = float(fall_length_beats if fall_length_beats is not None else length_beats)
        if fall <= 0:
            raise ValueError(f"fall_length_beats must be > 0 (got {fall})")
        breakpoints.append({
            "time_beats": float(start_beat + length_beats + fall),
            "value": float(floor_value),
            "curve_kind": curve_kind,
        })

    env: EnvelopeDict = {
        "target_kind": "mixer_volume",
        "target_track_id": target_track_id,
        "breakpoints": breakpoints,
    }
    return GeneratorOutput(envelopes=[env])


def sidechain_trigger(
    *,
    target_track_id: str,
    at_beats: Sequence[float],
    rest_value: float = 1.0,
    duck_value: float = 0.3,
    attack_beats: float = 0.02,
    recovery_beats: float = 0.5,
    envelope_start_beats: float | None = None,
) -> GeneratorOutput:
    """Volume envelope that ducks at each hit and recovers.

    Emulates a sidechain compressor when no real one is wired. Each hit makes
    the track dip from `rest_value` down to `duck_value` over `attack_beats`,
    then recover back to `rest_value` over `recovery_beats`.

    Hits closer together than `attack_beats + recovery_beats` are coalesced —
    the next attack inherits whatever value the previous recovery had reached.
    Hits arriving in any order are sorted before emission.

    `envelope_start_beats` clamps the first attack window's rest anchor to the
    given beat (e.g. the section's session-clip start), so the envelope's beat
    range stays inside the section. Without it, a hit at the section's first
    downbeat would emit a pre-attack rest anchor at `hit - attack_beats`,
    landing outside the session clip and getting refused by Live's
    session-clip-only envelope routing. When the clamped attack_start equals
    or exceeds the hit's time, the rest anchor is dropped entirely (no room
    for a leading ramp — the duck is the first breakpoint).
    """
    if not at_beats:
        raise ValueError("at_beats must not be empty")
    if attack_beats <= 0:
        raise ValueError(f"attack_beats must be > 0 (got {attack_beats})")
    if recovery_beats <= 0:
        raise ValueError(f"recovery_beats must be > 0 (got {recovery_beats})")
    if any(b < 0 for b in at_beats):
        raise ValueError("at_beats values must be >= 0")
    _check_unit("rest_value", rest_value)
    _check_unit("duck_value", duck_value)
    if duck_value > rest_value:
        raise ValueError(
            f"duck_value ({duck_value}) must be <= rest_value ({rest_value})"
        )
    if len(set(at_beats)) != len(at_beats):
        raise ValueError(
            "at_beats contains duplicate values; each hit must have a unique time"
        )
    floor = 0.0 if envelope_start_beats is None else float(envelope_start_beats)
    if envelope_start_beats is not None and any(b < floor for b in at_beats):
        raise ValueError(
            f"at_beats values must be >= envelope_start_beats ({floor}) when "
            "envelope_start_beats is set"
        )

    sorted_hits = sorted(float(b) for b in at_beats)
    breakpoints: list[dict] = []
    prev_recovery_end = -1.0

    for hit in sorted_hits:
        attack_start = hit - attack_beats
        # Anchor rest before the attack only when there's a gap (the previous
        # recovery already landed at `rest_value`, so we only need a fresh
        # anchor when this hit's attack starts after the last recovery ended).
        if attack_start > prev_recovery_end:
            clamped_start = max(floor, attack_start)
            # Drop the rest anchor when clamping would push it to (or past)
            # the hit itself — no leading-ramp room means the duck is the
            # envelope's first breakpoint.
            if clamped_start < hit:
                breakpoints.append({
                    "time_beats": clamped_start,
                    "value": float(rest_value),
                    "curve_kind": "linear",
                })
        # Attack landing — the duck floor.
        breakpoints.append({
            "time_beats": hit,
            "value": float(duck_value),
            "curve_kind": "linear",
        })
        # Recovery — back to rest.
        recovery_end = hit + recovery_beats
        breakpoints.append({
            "time_beats": recovery_end,
            "value": float(rest_value),
            "curve_kind": "linear",
        })
        prev_recovery_end = recovery_end

    env: EnvelopeDict = {
        "target_kind": "mixer_volume",
        "target_track_id": target_track_id,
        "breakpoints": breakpoints,
    }
    return GeneratorOutput(envelopes=[env])
