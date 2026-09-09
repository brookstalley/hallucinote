"""The provenance record for a song's sources — its shape, and what it refuses.

``assets/manifest.json`` is one file per song, keyed by source name, and it is
source in git: nothing re-derives it, so a manifest that cannot be read is a
loss of the only record of what a sample *is*. This module is the parsing and
validation half — it turns JSON into value objects and back, and refuses a
shape it does not understand rather than guessing, so a manifest written by a
later version is never silently half-read. Nothing here touches the
filesystem; ``store.py`` owns the reading and the atomic writing.

The questions the entries answer, and therefore the fields: *what is this
line* (``note``), *where is it from* (``origin`` — a title, a medium, a scene,
never a path to a media file), *has the file changed* (``checksum``), *can I
trust the normalized copy* (``sample_rate``, ``channels``, ``duration_s``,
``original_filename``, ``original_format``, ``original_lossy``), *when did it
arrive* (``ingested_at``), and *what stood in this slot before* (``superseded``).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from hallucinote.assets.types import Source
from hallucinote.paths import resolve_audio_path

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"

# Sources are addressed by name and the name becomes a filename, so the two
# have to survive each other: no separators, no traversal, no spaces to quote.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_FIELDS = (
    "path",
    "checksum",
    "sample_rate",
    "channels",
    "duration_s",
    "note",
    "origin",
    "original_filename",
    "original_format",
    "original_lossy",
    "ingested_at",
)


def validate_name(name: str) -> str:
    """Refuse a source name that cannot safely become a filename.

    The manifest key and ``assets/sources/<name>.wav`` are the same string; a
    name carrying a separator would write outside the store, and one carrying
    a space would need quoting at every command line that names it.
    """
    if not _NAME.match(name):
        raise ValueError(
            f"source name {name!r} is not usable: a name becomes both the "
            "manifest key and the filename assets/sources/<name>.wav, so it "
            "must start with a letter or digit and contain only letters, "
            "digits, '.', '_' and '-' (e.g. 'rivers-01')."
        )
    return name


@dataclass(frozen=True)
class ManifestEntry:
    """One source's provenance, exactly as the manifest records it.

    ``path`` is the song-relative POSIX reference — the same form
    ``clips.audio_file`` carries — so a manifest diffs identically on every
    machine and resolves through :func:`hallucinote.paths.resolve_audio_path`.
    """

    name: str
    path: str
    checksum: str
    sample_rate: int
    channels: int
    duration_s: float
    note: str
    origin: str
    original_filename: str
    original_format: str
    original_lossy: bool
    ingested_at: str
    superseded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_name(self.name)
        if PurePosixPath(self.path).is_absolute() or "\\" in self.path:
            raise ValueError(
                f"manifest entry {self.name!r} has path {self.path!r}: a source "
                "path is stored song-relative and POSIX-separated (e.g. "
                "'assets/sources/rivers-01.wav') so the song stays portable."
            )
        if not _SHA256_HEX.match(self.checksum):
            raise ValueError(
                f"manifest entry {self.name!r} has checksum {self.checksum!r}: "
                "expected 64 lowercase hex chars (sha256 of the normalized WAV)."
            )
        for prior in self.superseded:
            if not _SHA256_HEX.match(prior):
                raise ValueError(
                    f"manifest entry {self.name!r} lists superseded checksum "
                    f"{prior!r}: every superseded value is a sha256 hex digest."
                )
        if self.sample_rate <= 0:
            raise ValueError(
                f"manifest entry {self.name!r} has sample_rate "
                f"{self.sample_rate}: expected a positive rate in Hz."
            )
        if self.channels < 1:
            raise ValueError(
                f"manifest entry {self.name!r} has channels {self.channels}: "
                "expected at least one channel."
            )
        if self.duration_s < 0:
            raise ValueError(
                f"manifest entry {self.name!r} has duration_s "
                f"{self.duration_s}: a duration is never negative."
            )

    def to_dict(self) -> dict[str, Any]:
        """The JSON object for this entry — the name is the key, not a field."""
        return {
            "path": self.path,
            "checksum": self.checksum,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_s": self.duration_s,
            "note": self.note,
            "origin": self.origin,
            "original_filename": self.original_filename,
            "original_format": self.original_format,
            "original_lossy": self.original_lossy,
            "ingested_at": self.ingested_at,
            "superseded": list(self.superseded),
        }

    def as_source(self, song_dir: Path | str) -> Source:
        """The store's value object for this entry, path resolved for reading."""
        return Source(
            name=self.name,
            path=resolve_audio_path(song_dir, self.path),
            checksum=self.checksum,
            sample_rate=self.sample_rate,
            channels=self.channels,
            duration_s=self.duration_s,
        )


@dataclass(frozen=True)
class Manifest:
    """Every source a song holds, in name order.

    Entries are kept sorted so the file's diff reflects what changed rather
    than the order ingests happened to run in.
    """

    entries: tuple[ManifestEntry, ...] = ()
    manifest_version: int = MANIFEST_VERSION

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.name in seen:
                raise ValueError(
                    f"manifest lists {entry.name!r} twice: a source name is the "
                    "key and names exactly one slot."
                )
            seen.add(entry.name)
        object.__setattr__(
            self, "entries", tuple(sorted(self.entries, key=lambda e: e.name))
        )

    def get(self, name: str) -> ManifestEntry | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def with_entry(self, entry: ManifestEntry) -> Manifest:
        """This manifest with ``entry`` in its slot, replacing any occupant."""
        kept = tuple(e for e in self.entries if e.name != entry.name)
        return replace(self, entries=kept + (entry,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "sources": {e.name: e.to_dict() for e in self.entries},
        }


def parse_manifest(data: Any, *, where: Path | str) -> Manifest:
    """Turn a loaded JSON document into a :class:`Manifest`, or teach why not.

    ``where`` names the file in every error because the caller reading a
    manifest is usually several layers from the person who has to fix it.
    """
    if not isinstance(data, Mapping):
        raise ValueError(
            f"{where}: a manifest is a JSON object with 'manifest_version' and "
            f"'sources'; got {type(data).__name__}."
        )
    version = data.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"{where}: manifest_version {version!r} is not readable by this "
            f"version of Hallucinote, which writes and reads version "
            f"{MANIFEST_VERSION}. Update Hallucinote if the manifest is newer; "
            "the file is source in git, so check it out from a commit that "
            "matches if it is older."
        )
    raw_sources = data.get("sources", {})
    if not isinstance(raw_sources, Mapping):
        raise ValueError(
            f"{where}: 'sources' must be an object keyed by source name; got "
            f"{type(raw_sources).__name__}."
        )
    entries = tuple(
        _parse_entry(name, raw, where=where) for name, raw in raw_sources.items()
    )
    return Manifest(entries=entries, manifest_version=MANIFEST_VERSION)


def _parse_entry(name: Any, raw: Any, *, where: Path | str) -> ManifestEntry:
    if not isinstance(name, str):
        raise ValueError(f"{where}: source keys are strings; got {name!r}.")
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"{where}: source {name!r} must be an object; got "
            f"{type(raw).__name__}."
        )
    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError(
            f"{where}: source {name!r} is missing {', '.join(missing)}. Every "
            "field is written at ingest; re-ingest the file with "
            "`hallucinote asset add --replace` if the entry was hand-edited."
        )
    superseded = raw.get("superseded", [])
    if not isinstance(superseded, (list, tuple)):
        raise ValueError(
            f"{where}: source {name!r} has a non-list 'superseded'; it is the "
            "list of checksums that previously held this slot."
        )
    return ManifestEntry(
        name=name,
        path=str(raw["path"]),
        checksum=str(raw["checksum"]),
        sample_rate=int(raw["sample_rate"]),
        channels=int(raw["channels"]),
        duration_s=float(raw["duration_s"]),
        note=str(raw["note"]),
        origin=str(raw["origin"]),
        original_filename=str(raw["original_filename"]),
        original_format=str(raw["original_format"]),
        original_lossy=bool(raw["original_lossy"]),
        ingested_at=str(raw["ingested_at"]),
        superseded=tuple(str(s) for s in superseded),
    )
