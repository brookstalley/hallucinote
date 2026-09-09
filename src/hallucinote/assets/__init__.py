"""Asset store — sources a song keeps, and the derived audio it can regenerate.

A sample is the third leg of a song's authorship (``authorship-model.md``): a
recorded asset whose reproducibility means *retaining* it. Sources live under
``assets/sources/`` and are never edited in place; every derived file under
``assets/derived/`` is the output of a recorded recipe and is addressed by the
content of what made it, so nothing can reference a stale file by a current
address. The manifest beside them is source in git; the DB references files by
path and gains no table for any of this.

This is the one module a song's ``build.py`` imports::

    from hallucinote.assets import source, derive, trim, normalize, carve

    line = source(SONG_DIR, "rivers-01")
    hit = derive(line, trim(0.4, 2.1), normalize(peak_dbfs=-1.0))
    create_audio_clip(..., audio_file=hit.path)

``source`` looks a name up in the manifest; ``derive`` runs a chain of
transforms over it and returns the cached or freshly rendered file. A
recipe that reads the score — ``carve`` / ``vocode`` — needs a schedule and
mask parameters, so those shapes are re-exported here too. The order of
``derive`` calls in ``build.py`` is the declared order of any circular
derivation (a part followed from a sample, then carved against that part).

The value objects every module here exchanges are in ``types.py``; the
store, the cache and the transforms are the modules beside it, importable
on their own by the tools that need one of them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from hallucinote.assets.derived import BACKEND, reference_of
from hallucinote.assets.derived import derive as _derive_chain
from hallucinote.assets.store import ASSETS_DIRNAME, SOURCES_DIRNAME, source, sources
from hallucinote.assets.transforms import (
    STRETCH_AB_COMMAND,
    chop_at_onsets,
    fade,
    normalize,
    pitch_shift,
    reverse,
    stretch_to_bars,
    trim,
)
from hallucinote.assets.transforms_spectral import carve, vocode
from hallucinote.assets.types import Derived, Source, Transform, TransformContext
from hallucinote.spectral.schedule import (
    constant_schedule,
    schedule_from_sections,
    schedule_from_spans,
)
from hallucinote.spectral.types import MaskParams, ReferenceSchedule

def song_dir_of(source: Source) -> Path:
    """The song directory a store-issued ``Source`` belongs to.

    The store resolves a source to ``<song>/assets/sources/<name>.wav``, so
    the song is two directories up; a source whose path does not have that
    shape came from somewhere else and the caller must say where the song is.
    """
    path = Path(source.path)
    if path.parent.name == SOURCES_DIRNAME and path.parent.parent.name == ASSETS_DIRNAME:
        return path.parent.parent.parent
    raise ValueError(
        f"derive needs song_dir=...: source {source.name!r} at {path} is not under "
        f"<song>/{ASSETS_DIRNAME}/{SOURCES_DIRNAME}/, so the song directory cannot be "
        "inferred from it. Pass song_dir=SONG_DIR, or look the source up with "
        "source(SONG_DIR, name)"
    )


def _steps(chain: tuple[Transform | Sequence[Transform], ...]) -> tuple[Transform, ...]:
    """The chain as written — spread, or handed over as one list."""
    if len(chain) == 1 and isinstance(chain[0], (list, tuple)):
        return tuple(chain[0])
    return tuple(chain)  # type: ignore[arg-type]


def derive(
    source: Source,
    *chain: Transform | Sequence[Transform],
    song_dir: Path | str | None = None,
    reference_fingerprint: str | None = None,
    backend: str = BACKEND,
) -> Derived:
    """Run ``chain`` over ``source`` and return the derived file, cached by content.

    ``song_dir`` is inferred from a store-issued source; pass it for a source
    built by hand. ``reference_fingerprint`` is filled from the chain's
    ``carve`` / ``vocode`` steps when not given — by ``address`` itself, so
    this facade, ``Recipe`` and ``derived.derive`` all name the same file for
    the same content; an explicit value wins, for a caller that resolved the
    reference itself.
    """
    steps = _steps(chain)
    directory = Path(song_dir) if song_dir is not None else song_dir_of(source)
    return _derive_chain(
        source,
        steps,
        song_dir=directory,
        reference_fingerprint=reference_fingerprint,
        backend=backend,
    )


__all__ = [
    "BACKEND",
    "STRETCH_AB_COMMAND",
    "Derived",
    "MaskParams",
    "ReferenceSchedule",
    "Source",
    "Transform",
    "TransformContext",
    "carve",
    "chop_at_onsets",
    "constant_schedule",
    "derive",
    "fade",
    "normalize",
    "pitch_shift",
    "reference_of",
    "reverse",
    "schedule_from_sections",
    "schedule_from_spans",
    "song_dir_of",
    "source",
    "sources",
    "stretch_to_bars",
    "trim",
    "vocode",
]
