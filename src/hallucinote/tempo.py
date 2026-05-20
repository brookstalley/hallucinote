"""Tempo conversion helpers (DB-side authoring math).

Live's BPM is always the **quarter-note pulse**, regardless of meter. When
an author thinks of tempo in a different pulse — e.g. "168 BPM eighth pulse
in 7/8", a common convention for fast odd-meter music — they need to convert
to the quarter pulse before writing to ``tempo_map`` via ``M.add_tempo_point``.

The Wave-0 ``odd-meter-experimental`` canary surfaced this every time it
authored a non-4/4 section (runbook step 7a); previously authors did the math
by hand (168 / 2 = 84). This module is the canonical helper.

The pure-math nature (no DB, no MCP) and the convention's prevalence in
odd-meter writing make this a first-class hallucinote primitive. The
``time_signature`` argument is accepted but currently informational — the
pulse-to-quarter ratio is meter-independent. It's kept in the signature so
callers don't have to drop and re-add it if a future variant DOES need the
meter (e.g. a "treat the dotted-quarter pulse in compound meter as the
displayed BPM" convention surfaces).
"""
from __future__ import annotations


# Pulse name -> duration in quarter notes. Standard Western notation.
# (dotted-X = 1.5x base; triplet-X = base / 1.5 i.e. 2/3 of base).
_PULSE_TO_QUARTER: dict[str, float] = {
    "whole":             4.0,
    "half":              2.0,
    "dotted_half":       3.0,
    "quarter":           1.0,
    "dotted_quarter":    1.5,
    "triplet_quarter":   2.0 / 3.0,
    "eighth":            0.5,
    "dotted_eighth":     0.75,
    "triplet_eighth":    1.0 / 3.0,
    "sixteenth":         0.25,
    "dotted_sixteenth":  0.375,
    "triplet_sixteenth": 1.0 / 6.0,
}


def to_live_bpm(
    pulse_bpm: float,
    pulse_kind: str,
    time_signature: str | None = None,
) -> float:
    """Convert a pulse-of-meter BPM to Live's quarter-note BPM.

    Live's ``Song.tempo`` is always the quarter-note pulse. Authors who think
    of tempo in another pulse (eighth pulse in 7/8, dotted-quarter pulse in
    6/8, etc.) call this helper before writing the value to ``tempo_map``::

        # 168 BPM eighth-pulse in 7/8 -> 84 BPM quarter-pulse (Live)
        bpm = to_live_bpm(168.0, "eighth")  # -> 84.0
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=bpm)

    ``pulse_kind`` accepts the keys of ``_PULSE_TO_QUARTER`` (plain + dotted
    + triplet of whole / half / quarter / eighth / sixteenth). Unknown
    values raise ``ValueError`` listing the accepted set, so callers
    discover the canonical names without docs drift.

    ``time_signature`` is informational and currently unused — it's part of
    the signature so callers don't have to refactor if a future convention
    needs it. A live BPM value is the same number regardless of meter; the
    pulse-to-quarter ratio is what does the work here.
    """
    if pulse_bpm <= 0:
        raise ValueError(f"pulse_bpm must be > 0, got {pulse_bpm}")
    ratio = _PULSE_TO_QUARTER.get(pulse_kind)
    if ratio is None:
        raise ValueError(
            f"unknown pulse_kind {pulse_kind!r}; accepted: "
            f"{sorted(_PULSE_TO_QUARTER)}"
        )
    # quarter_bpm = pulse_bpm * (pulse_duration_in_quarters)
    # An eighth lasts 0.5 quarters, so 168 eighth-pulses/min = 84 quarter-pulses/min.
    return pulse_bpm * ratio


__all__ = ["to_live_bpm"]
