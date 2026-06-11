"""Audio file-reference resolution (CLP-AUD1).

``clips.audio_file`` stores the reference exactly as authored: a
song-relative POSIX path (canonically under ``assets/``, where
AUD-9R3V's recorded takes will also land) or an absolute path. This
module is the single resolution point — push (CLP-AUD2) and analysis
ingest resolve through it; the DB never stores a resolved path, so the
private songs repo stays portable across machines and collaborators.

Lives at the package top level rather than under ``hallucinote.audio``
because that package eagerly imports the numpy-bound analysis stack at
``__init__`` time; path resolution must stay importable from
stdlib-only contexts (the MCP server is stdlib-only at startup and the
sync layer carries no heavy deps).
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath


def resolve_audio_path(song_dir: str | Path, ref: str) -> Path:
    """Resolve a ``clips.audio_file`` reference against a song directory.

    Relative refs are POSIX-separated by contract and resolve under
    ``song_dir`` — the directory containing the song's ``build.py``;
    the helper takes it as an explicit argument so the policy stays
    caller-owned. Absolute refs pass through unchanged (stored
    as-given; the push-time existence check is CLP-AUD2 scope).
    """
    posix_ref = PurePosixPath(ref)
    if posix_ref.is_absolute() or Path(ref).is_absolute():
        return Path(ref)
    return Path(song_dir).joinpath(*posix_ref.parts)
