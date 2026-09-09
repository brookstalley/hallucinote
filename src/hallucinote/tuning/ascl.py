"""Synthesize a re-draggable ``.ascl`` from a :class:`TuningData`.

Ableton's ``.ascl`` is the Scala ``.scl`` scale format plus ``! @ABL`` comment
directives (Live ≥ 12.1). We only ever **write** ``.ascl`` (pull-from-Live-only;
no parser ships) — this module is that writer.

Format (per the Scala spec + Ableton's ASCL spec; see
``.prawduct/artifacts/plans/MICROTUNE/archive/api-notes-tuning.md``):

- ``!``-prefixed lines are comments; every ``@ABL`` directive rides one.
- The first **non-comment** line is the free-text description; the second is the
  integer note count; then one pitch per line.
- A value containing ``.`` is **cents**; ``/`` or a bare integer is a ratio. We
  emit every pitch as cents (uniform, and ``period_cents`` may be non-octave).
- The implicit unison (degree 0, ``0.0`` cents) is **not** listed; the **last**
  pitch line is the period. So ``step_count`` pitch lines are written, the last
  equal to ``period_cents``.
- ``@ABL`` directives go **after** the pitch list; the file is UTF-8.

What we deliberately omit: ``@ABL NOTE_NAMES`` (the LOM exposes no note names)
and ``@ABL REFERENCE_PITCH`` (our blob carries no reference *frequency* — only a
MIDI anchor). Both are optional; when ``REFERENCE_PITCH`` is absent Live
auto-assigns one. The result reproduces the tuning's **interval structure** (its
sonic character) faithfully; the absolute pitch anchor falls to Live's default —
the accepted reconstruction limitation (see :class:`TuningData`).
"""
from __future__ import annotations

from .model import TuningData

# Cents precision when writing pitch lines. Six places matches Scala's idiom and
# is finer than any audible / LOM-reported resolution, so the write→re-read
# round-trip is lossless to well within a thousandth of a cent.
_CENTS_PRECISION = 6


def _description(name: str) -> str:
    """A safe single-line description from the tuning name (never empty)."""
    cleaned = name.strip().replace("\n", " ").replace("\r", " ")
    return cleaned or "Reconstructed tuning"


def write_ascl(tuning: TuningData) -> str:
    """Render ``tuning`` as ``.ascl`` text (UTF-8, trailing newline).

    Inverse-friendly: the emitted cents pitch lines re-read to ``step_cents``.
    """
    description = _description(tuning.name)
    lines: list[str] = [
        f"! {description}.ascl",
        "!",
        "! Reconstructed by Hallucinote from Live's tuning_system. Relative cents",
        "! are preserved exactly; the absolute reference pitch is left to Live's",
        "! default (the LOM read carries no source file or reference frequency).",
        "!",
        description,              # first non-comment line: description
        str(tuning.step_count),   # second non-comment line: note count
        "!",
    ]
    lines.extend(f"{cents:.{_CENTS_PRECISION}f}" for cents in tuning.step_cents)
    lines.append("!")
    lines.append("! @ABL SOURCE Hallucinote (reconstructed from Live tuning_system)")
    return "\n".join(lines) + "\n"


__all__ = ["write_ascl"]
