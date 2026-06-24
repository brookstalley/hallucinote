"""Read ``song.tuning_system`` off the Live LOM → a :class:`TuningData`.

Two branches:

- **None / 12-TET.** A fresh Set reads ``song.tuning_system == None``; through
  ``ableton_probe`` that surfaces as ``{"type": "NoneType", "value": None}``.
  Either shape → :data:`None`, a clean "no alternate tuning loaded" no-op — the
  path the 99.99% of songs hit.
- **Loaded tuning.** The ``/tuning-pull`` skill walks the LOM (the probe path
  grammar reaches every field, incl. ``reference_pitch.octave``) and hands this
  function the assembled scalars/list as a plain dict. Closed against the
  verify-api shapes captured live off **Wendy Carlos gamma** (2026-06-19) — see
  ``.prawduct/artifacts/plans/MICROTUNE/api-notes-tuning.md``.

LOM → :class:`TuningData` mapping (verify-api confirmed):

==========================================  ==========================================
``TuningSystem`` field (live shape)         ``TuningData`` field
==========================================  ==========================================
``name`` (str)                              ``name``
``number_of_notes_in_pseudo_octave`` (int)  ``step_count`` (== ``len(note_tunings)``)
``pseudo_octave_in_cents`` (float)          ``period_cents``
``note_tunings`` (``list[float]``)          ``step_cents`` = ``note_tunings[1:] + [period]``
``reference_pitch`` ``{octave, index}``     ``reference_note`` = ``(octave+2)*12 + index``
==========================================  ==========================================

``note_tunings`` is a **flat** ``list[float]`` of cents, degree-indexed
``0..n-1``, with index 0 the unison (``0.0`` cents) and the period **not**
included (it lives in ``pseudo_octave_in_cents``). So ``step_cents`` drops the
implicit unison and appends the period as the final degree (Scala convention).

``reference_pitch`` is a **standard 12-key MIDI anchor** — its ``octave`` /
``index_in_octave`` use Ableton's C3=60 numbering (MIDI ``(octave+2)*12+index``,
the same convention the ASCL ``REFERENCE_PITCH`` directive uses). This is
distinct from ``lowest_note`` / ``highest_note``, whose ``index_in_octave`` can
exceed 11 because they express the playable range in the tuning's **own
pseudo-octave degree** coordinates — not needed for the blob, so not read here.

This module reads only — it never mutates Live (the LOM tuning surface is
read-only anyway), so it is safe under ``allow_version_mismatch=true``.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from hallucinote.tuning_probe import is_no_tuning_loaded

from .model import TuningData

logger = logging.getLogger("hallucinote.tuning.read")

# Tolerance (cents) for the "degree 0 is the unison" invariant. ``note_tunings[0]``
# is ``0.0`` by tuning convention (the reference pitch sits at 0 cents); a
# materially non-zero degree 0 means the read isn't the shape verify-api
# confirmed, so we fail loud rather than emit a tuning offset by that amount.
_UNISON_TOLERANCE_CENTS = 1e-3


class TuningReadError(ValueError):
    """A loaded ``song.tuning_system`` read was missing or malformed.

    Raised when the assembled LOM dict lacks a required field or violates a
    verify-api-confirmed invariant (``note_tunings`` not a non-empty list, degree
    0 not the unison, or a declared step count that disagrees with
    ``note_tunings``). A :class:`ValueError` subclass so a caller can degrade to a
    clear "couldn't read the loaded tuning" message while generic value-error
    handling still catches it.
    """


def read_tuning_system(raw: object) -> TuningData | None:
    """Derive :class:`TuningData` from a read of ``song.tuning_system``.

    ``raw`` is either a no-tuning signal (unwrapped ``None`` or the
    ``ableton_probe`` ``{"type": "NoneType", ...}`` wrapper) → :data:`None`, or
    the assembled LOM scalars/list of a loaded tuning (see the module docstring
    for the required keys) → a :class:`TuningData`. Raises
    :class:`TuningReadError` when a loaded read is missing a field or violates a
    confirmed-shape invariant.
    """
    if is_no_tuning_loaded(raw):
        logger.info(
            "song.tuning_system is None — 12-TET (no alternate tuning loaded); "
            "nothing to pull."
        )
        return None
    return _extract_loaded_tuning(raw)


def _require(raw: Mapping, key: str) -> object:
    try:
        return raw[key]
    except (KeyError, TypeError) as exc:
        raise TuningReadError(
            f"loaded tuning read is missing required field {key!r}: {raw!r}"
        ) from exc


def _extract_loaded_tuning(raw: object) -> TuningData:
    """Map an assembled ``song.tuning_system`` read to a :class:`TuningData`.

    See the module docstring for the field mapping (verify-api confirmed against
    Wendy Carlos gamma, 2026-06-19). Validates the confirmed-shape invariants and
    raises :class:`TuningReadError` on any violation rather than emit a wrong
    tuning.
    """
    if not isinstance(raw, Mapping):
        raise TuningReadError(
            "loaded tuning read must be a mapping of TuningSystem fields, got "
            f"{type(raw).__name__}: {raw!r}"
        )

    note_tunings = _require(raw, "note_tunings")
    if isinstance(note_tunings, (str, bytes)) or not isinstance(note_tunings, Sequence):
        raise TuningReadError(
            f"note_tunings must be a list of cents (degree-indexed), got {note_tunings!r}"
        )
    if len(note_tunings) < 1:
        raise TuningReadError("note_tunings is empty; a loaded tuning has at least the unison")
    try:
        cents = [float(c) for c in note_tunings]
    except (TypeError, ValueError) as exc:
        raise TuningReadError(f"note_tunings has a non-numeric entry: {note_tunings!r}") from exc
    if abs(cents[0]) > _UNISON_TOLERANCE_CENTS:
        raise TuningReadError(
            f"note_tunings[0] must be the 0-cent unison, got {cents[0]!r}; the "
            "read shape is not the verify-api-confirmed degree-indexed list"
        )

    # number_of_notes_in_pseudo_octave is a redundant cross-check (== len): when
    # present it must agree, so a misread that changes one but not the other fails
    # loud instead of silently storing a mismatched scale.
    declared = raw.get("number_of_notes_in_pseudo_octave")
    if declared is not None and int(declared) != len(cents):
        raise TuningReadError(
            f"number_of_notes_in_pseudo_octave ({declared}) disagrees with "
            f"len(note_tunings) ({len(cents)})"
        )

    period_cents = float(_require(raw, "pseudo_octave_in_cents"))

    ref = _require(raw, "reference_pitch")
    if not isinstance(ref, Mapping):
        raise TuningReadError(
            f"reference_pitch must be a mapping with octave + index_in_octave, got {ref!r}"
        )
    octave = int(_require(ref, "octave"))
    index_in_octave = int(_require(ref, "index_in_octave"))
    # Ableton C3=60 numbering (MIDI = (octave+2)*12 + index), matching the ASCL
    # REFERENCE_PITCH directive. TuningData enforces the 0–127 MIDI range.
    reference_note = (octave + 2) * 12 + index_in_octave

    # Drop the implicit unison (degree 0) and append the period as the final
    # degree — the Scala convention TuningData.step_cents stores.
    step_cents = tuple(cents[1:]) + (period_cents,)

    return TuningData(
        name=str(_require(raw, "name")),
        step_count=len(step_cents),
        period_cents=period_cents,
        reference_note=reference_note,
        step_cents=step_cents,
    )


__all__ = ["read_tuning_system", "TuningReadError"]
