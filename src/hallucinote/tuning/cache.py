"""Write the reconstructed ``.ascl`` into the song's ``tunings/`` directory.

The cached file lives per-song at ``songs/<slug>/tunings/<name>.ascl`` so the
song is self-contained and the push re-load instruction can name an exact file
(decision 3). It is treated as immutable: the content is a deterministic function
of the :class:`TuningData`, so re-caching the same tuning rewrites byte-identical
content. The returned ref is the **song-relative POSIX path** stored in
``songs.tuning_ref`` — the same relative-ref convention ``clips.audio_file`` uses
(see ``hallucinote.paths``).
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .ascl import write_ascl
from .model import TuningData

_TUNINGS_DIRNAME = "tunings"
_UNSAFE = re.compile(r"[^a-z0-9_-]+")
_DASH_RUN = re.compile(r"-{2,}")


def _safe_filename(name: str) -> str:
    """Filesystem-safe stem from a tuning name: lowercase ``[a-z0-9_-]``.

    Mirrors the song-slug convention (``[a-z0-9_-]``); spaces, slashes, and
    non-ASCII collapse to ``-``. Never empty (falls back to ``tuning``), so a
    name like ``"19-EDO"`` becomes ``19-edo`` and a degenerate name still yields
    a valid file.
    """
    stem = _UNSAFE.sub("-", name.strip().lower())
    stem = _DASH_RUN.sub("-", stem).strip("-")
    return stem or "tuning"


def cache_ascl(song_dir: str | Path, tuning: TuningData) -> str:
    """Write ``tuning``'s ``.ascl`` under ``<song_dir>/tunings/`` and return the
    song-relative ref (e.g. ``"tunings/19-edo.ascl"``) for ``songs.tuning_ref``.

    ``song_dir`` is the directory holding the song's ``build.py`` (the same
    anchor ``hallucinote.paths.resolve_audio_path`` resolves against). The
    ``tunings/`` directory is created if absent; the file is written UTF-8
    (required for ``@ABL`` directives).
    """
    filename = f"{_safe_filename(tuning.name)}.ascl"
    dest = Path(song_dir) / _TUNINGS_DIRNAME / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(write_ascl(tuning), encoding="utf-8")
    return str(PurePosixPath(_TUNINGS_DIRNAME) / filename)


__all__ = ["cache_ascl"]
