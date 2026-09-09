"""Where a song's sources live on disk, and the only writer of the manifest.

The store is the read-and-write half of the asset store: it locates
``assets/sources/`` and ``assets/manifest.json`` under a song directory, hands
out :class:`~hallucinote.assets.types.Source` value objects, and writes the
manifest atomically (temp sibling + ``os.replace``) so an interrupted ingest
leaves either the old record or the new one, never half of either.

The discipline the rest of the wave depends on: **a source is immutable.**
Ingest writes ``assets/sources/<name>.wav`` once; nothing here edits one in
place, and :func:`verify` is how a reader finds out that something did — the
manifest's checksum is the identity every derived address is built from, so a
silently edited source would poison the cache rather than invalidate it.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hallucinote.assets.manifest import (
    MANIFEST_FILENAME,
    Manifest,
    ManifestEntry,
    parse_manifest,
)
from hallucinote.assets.types import Source

ASSETS_DIRNAME = "assets"
SOURCES_DIRNAME = "sources"

# The song-relative POSIX reference form the manifest stores and
# ``clips.audio_file`` carries (hallucinote.paths).
SOURCE_REF_TEMPLATE = f"{ASSETS_DIRNAME}/{SOURCES_DIRNAME}/{{name}}.wav"

_CHECKSUM_CHUNK_BYTES = 1 << 20

ProblemKind = Literal["missing", "checksum-mismatch"]


@dataclass(frozen=True)
class SourceProblem:
    """One manifest entry that the files on disk no longer back.

    Carried rather than raised because ``verify`` answers about a whole song:
    the caller (``compat``, an ingest that wants to warn) wants every problem
    at once, not the first one.
    """

    name: str
    path: Path
    kind: ProblemKind
    detail: str


def assets_dir(song_dir: Path | str) -> Path:
    return Path(song_dir) / ASSETS_DIRNAME


def sources_dir(song_dir: Path | str) -> Path:
    return assets_dir(song_dir) / SOURCES_DIRNAME


def manifest_path(song_dir: Path | str) -> Path:
    return assets_dir(song_dir) / MANIFEST_FILENAME


def source_ref(name: str) -> str:
    """The song-relative reference a manifest entry and a clip both store."""
    return SOURCE_REF_TEMPLATE.format(name=name)


def source_path(song_dir: Path | str, name: str) -> Path:
    """Where the normalized WAV for ``name`` lives under ``song_dir``."""
    return sources_dir(song_dir) / f"{name}.wav"


def file_checksum(path: Path | str) -> str:
    """sha256 of a file's bytes — the identity the manifest records.

    Read in chunks because a source is arbitrary length and the ingest guard
    admits files up to 100 MB.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHECKSUM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(song_dir: Path | str) -> Manifest:
    """The song's manifest, or an empty one when no source has been ingested.

    A missing file is not an error: a song has no manifest until its first
    ingest, and every reader here wants "no sources" rather than a traceback.
    Malformed JSON *is* an error — the file is source in git, so a parse
    failure means something to fix, never something to overwrite.
    """
    path = manifest_path(song_dir)
    if not path.is_file():
        return Manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}: not valid JSON ({exc}). The manifest is source in git — "
            "restore it from a commit rather than deleting it; deleting loses "
            "the record of what every source is."
        ) from exc
    return parse_manifest(data, where=path)


def write_manifest(song_dir: Path | str, manifest: Manifest) -> Path:
    """Write the manifest atomically, creating ``assets/`` if it is the first.

    Temp sibling + ``os.replace``: a reader either sees the previous manifest
    or the new one. A trailing newline keeps the file diff-friendly in git,
    where it lives.
    """
    path = manifest_path(song_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def sources(song_dir: Path | str) -> list[Source]:
    """Every source the manifest records, in name order.

    Reports what the manifest says; it does not check the files. Ask
    :func:`verify` for that — a caller listing sources should not pay a
    whole-store hash to do it.
    """
    return [entry.as_source(song_dir) for entry in load_manifest(song_dir).entries]


def source(song_dir: Path | str, name: str) -> Source:
    """One source by name, or a KeyError naming what the song does have."""
    manifest = load_manifest(song_dir)
    entry = manifest.get(name)
    if entry is None:
        known = ", ".join(e.name for e in manifest.entries) or "none"
        raise KeyError(
            f"no source named {name!r} in {manifest_path(song_dir)} "
            f"(this song has: {known}). Ingest it with "
            f"`hallucinote asset add <file> --name {name}`."
        )
    return entry.as_source(song_dir)


def verify(song_dir: Path | str) -> list[SourceProblem]:
    """Every manifest entry whose file is missing or no longer its checksum.

    An empty list means the store is trustworthy: each recorded source is on
    disk and byte-identical to what was ingested. A mismatch is worth
    reporting rather than repairing — the file may be the edited-in-place
    mistake, or the manifest may be the stale half, and only the author knows
    which.
    """
    problems: list[SourceProblem] = []
    for entry in load_manifest(song_dir).entries:
        path = entry.as_source(song_dir).path
        if not path.is_file():
            problems.append(
                SourceProblem(
                    name=entry.name,
                    path=path,
                    kind="missing",
                    detail=(
                        f"{entry.path} is recorded in the manifest but is not on "
                        "disk. Restore it from git, or re-ingest the original "
                        f"with `hallucinote asset add <file> --name {entry.name} "
                        "--replace`."
                    ),
                )
            )
            continue
        actual = file_checksum(path)
        if actual != entry.checksum:
            problems.append(
                SourceProblem(
                    name=entry.name,
                    path=path,
                    kind="checksum-mismatch",
                    detail=(
                        f"{entry.path} has changed since it was ingested "
                        f"(manifest {entry.checksum[:12]}…, file "
                        f"{actual[:12]}…). A source is immutable — every derived "
                        "asset is addressed from its checksum. Restore the file "
                        "from git, or re-ingest with `--replace` so the new "
                        "bytes get a new record."
                    ),
                )
            )
    return problems


def entry_for(song_dir: Path | str, name: str) -> ManifestEntry | None:
    """The raw manifest entry — provenance a :class:`Source` does not carry."""
    return load_manifest(song_dir).get(name)
