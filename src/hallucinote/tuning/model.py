"""The derived tuning blob — the single source the mapper, writer, and verify read.

``TuningData`` is the compact, parser-free representation we persist (as JSON in
``songs.tuning_data``) and reconstruct the ``.ascl`` from. It is deliberately
*derived* from the LOM read, not a mirror of Live's ``TuningSystem`` dict shapes:
those shapes are foreign and (as of the verify-api probe) only partly known, so
everything downstream depends on this shape instead, which we control and lock.

Field semantics (the locked persisted format — see
``.prawduct/artifacts/alternate-tunings.md`` §6):

- ``name`` — the tuning's display name (the ``.ascl`` description / filename seed).
- ``step_count`` — scale steps per period == ``len(step_cents)``. For an N-EDO
  tuning this is N. The implicit unison (degree 0, 0 cents) is **not** counted.
- ``step_cents`` — cents of degrees ``1..step_count`` relative to the unison, in
  ascending order. The implicit ``0.0`` for degree 0 is **not** listed (Scala
  convention). The **last entry is the period** — never assume 1200 (non-octave
  tunings like Bohlen-Pierce repeat at a non-octave).
- ``period_cents`` — the period (pseudo-octave) in cents == ``step_cents[-1]``.
  Kept explicit (it mirrors the LOM's ``pseudo_octave_in_cents``) for the
  push-time drift compare; validated consistent with ``step_cents[-1]``.
- ``reference_note`` — the MIDI note (0–127) anchoring scale degree 0. The
  mapper's only other input besides ``step_count``. Live's active tuning makes
  consecutive MIDI numbers consecutive scale degrees, so degree ``d`` of period
  ``p`` sounds at MIDI ``reference_note + p*step_count + d``.

What this intentionally does **not** carry: the reference *frequency* (Hz). The
reconstruction preserves the tuning's interval structure (its sonic character),
not its absolute pitch anchor — an accepted "lesser experience" for the
microtonal composer (FR/decision 4). A future chunk can add a ``reference_hz``
field additively (JSON blobs tolerate new keys) once verify-api confirms the LOM
``reference_pitch`` shape, without breaking already-stored songs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

# Tolerance (in cents) for the period == step_cents[-1] consistency invariant.
# Generous enough to absorb float-formatting noise from the LOM read / JSON
# round-trip, tight enough that a genuinely wrong period is still caught.
_PERIOD_TOLERANCE_CENTS = 1e-3


@dataclass(frozen=True)
class TuningData:
    """A derived, persistable alternate-tuning description. See module docstring."""

    name: str
    step_count: int
    period_cents: float
    reference_note: int
    step_cents: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.step_count, int) or self.step_count < 1:
            raise ValueError(
                f"step_count must be a positive int, got {self.step_count!r}"
            )
        if len(self.step_cents) != self.step_count:
            raise ValueError(
                f"step_cents has {len(self.step_cents)} entries but step_count is "
                f"{self.step_count}; they must agree (the implicit 0-cent unison "
                "is not listed, so the count equals the number of pitch lines)"
            )
        if not (0 <= self.reference_note <= 127):
            raise ValueError(
                f"reference_note must be a MIDI note 0–127, got {self.reference_note!r}"
            )
        if abs(self.step_cents[-1] - self.period_cents) > _PERIOD_TOLERANCE_CENTS:
            raise ValueError(
                "period_cents must equal the last step's cents (the period is the "
                f"final scale degree): period_cents={self.period_cents!r} vs "
                f"step_cents[-1]={self.step_cents[-1]!r}"
            )

    def to_blob(self) -> str:
        """Serialize to the compact JSON string persisted in ``songs.tuning_data``."""
        return json.dumps(
            {
                "name": self.name,
                "step_count": self.step_count,
                "period_cents": self.period_cents,
                "reference_note": self.reference_note,
                "step_cents": list(self.step_cents),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_blob(cls, blob: str) -> "TuningData":
        """Reconstruct from a ``songs.tuning_data`` JSON string. Inverse of
        :meth:`to_blob`; ``from_blob(d.to_blob()) == d``."""
        raw = json.loads(blob)
        try:
            return cls(
                name=raw["name"],
                step_count=raw["step_count"],
                period_cents=raw["period_cents"],
                reference_note=raw["reference_note"],
                step_cents=tuple(raw["step_cents"]),
            )
        except KeyError as exc:
            raise ValueError(
                f"tuning_data blob is missing required key {exc.args[0]!r}: {blob!r}"
            ) from exc


__all__ = ["TuningData"]
