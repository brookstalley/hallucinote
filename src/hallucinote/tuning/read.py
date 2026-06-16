"""Read ``song.tuning_system`` off the Live LOM → a :class:`TuningData`.

Two branches, by design at different maturity (see the build plan, Chunk 1):

- **None / 12-TET (built + live-confirmed).** A fresh Set reads
  ``song.tuning_system == None``; through ``ableton_probe`` that surfaces as
  ``{"type": "NoneType", "value": None}``. Either shape → :data:`None`, a clean
  "no alternate tuning loaded" no-op. This is the path the 99.99% of songs hit
  and it is fully implemented + tested.
- **Loaded tuning (STUB — pending verify-api).** Extracting the cents array /
  period / reference from a *loaded* ``TuningSystem`` needs its exact LOM dict
  shapes, which the Cycling '74 reference types only as "dictionary". The
  verify-api probe (Chunk 1, step 0) is **PARTIAL**: the None branch is
  confirmed live but no tuning could be loaded to capture the loaded shapes. So
  extraction raises :class:`TuningExtractionNotReady` rather than guess a shape —
  closing this stub (and flipping Chunk 1 to High confidence) is the last step.
  See ``.prawduct/artifacts/plans/MICROTUNE/api-notes-tuning.md``.

This module reads only — it never mutates Live (the LOM tuning surface is
read-only anyway), so it is safe under ``allow_version_mismatch=true``.
"""
from __future__ import annotations

import logging

from hallucinote.tuning_probe import is_no_tuning_loaded

from .model import TuningData

logger = logging.getLogger("hallucinote.tuning.read")


class TuningExtractionNotReady(NotImplementedError):
    """Raised when a *loaded* tuning is read before verify-api locks its shapes.

    A ``NotImplementedError`` subclass so callers can catch it specifically (to
    degrade to 12-TET with a clear message) while it still reads as "not built
    yet" to anything catching the base class.
    """


def read_tuning_system(raw: object) -> TuningData | None:
    """Derive :class:`TuningData` from a read of ``song.tuning_system``.

    ``raw`` is the value returned by reading ``song.tuning_system`` (e.g. via
    ``ableton_probe(action='get', path='song.tuning_system')``). Returns
    :data:`None` when no alternate tuning is loaded (the 12-TET no-op). Raises
    :class:`TuningExtractionNotReady` for a loaded tuning until the verify-api
    dict shapes are captured.
    """
    if is_no_tuning_loaded(raw):
        logger.info(
            "song.tuning_system is None — 12-TET (no alternate tuning loaded); "
            "nothing to pull."
        )
        return None
    return _extract_loaded_tuning(raw)


def _extract_loaded_tuning(raw: object) -> TuningData:
    """STUB: extract a loaded ``TuningSystem`` once its LOM dict shapes are known.

    Deliberately raises instead of guessing. The fields to map (per the Cycling
    '74 reference) are ``name``, ``note_tunings`` (relative cents → ``step_cents``),
    ``pseudo_octave_in_cents`` (→ ``period_cents``), and ``reference_pitch`` /
    ``lowest_note`` (→ ``reference_note``). The shape-independent assembly is
    already done: :class:`TuningData` validates the result. Only this LOM-dict →
    fields step is held; close it after probing a real loaded tuning and
    recording the shapes in ``api-notes-tuning.md``.
    """
    raise TuningExtractionNotReady(
        "Reading a *loaded* Live tuning is not implemented yet: the "
        "TuningSystem LOM dict shapes (note_tunings / reference_pitch / "
        "lowest_note / highest_note) must be captured against a real loaded "
        "tuning first (verify-api, Chunk 1 step 0). See "
        ".prawduct/artifacts/plans/MICROTUNE/api-notes-tuning.md. The None / "
        "12-TET path is fully supported."
    )


__all__ = ["read_tuning_system", "TuningExtractionNotReady"]
