"""Recipes as values, and the two questions a song asks of its derived cache.

A ``Recipe`` is a source name and a transform chain — the authored thing,
which lives in ``build.py`` and diffs while a WAV does not. ``verify``
reads every record under ``assets/derived/`` and says whether the file it
vouches for is still the file it describes; ``prune`` lists the files no
current recipe addresses. Both only report: deleting an orphan is the user's
call, because a cache that deletes on its own judgment is a cache nobody
trusts to keep what they meant to keep.

A record made by another backend version is *valid* here, never stale. The
address carries the version that made it, so the record is honest about its
provenance, and re-rendering it would only replace one honest file with a
different honest file the user has not heard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hallucinote.assets.derived import (
    BACKEND,
    DerivedRecord,
    address,
    address_of_filename,
    backend_version,
    chain_spec,
    derive,
    derived_dir,
    sha256_file,
)
from hallucinote.assets.types import Derived, Source, Transform

VALID = "valid"
MADE_BY_OLDER_BACKEND = "made-by-older-backend"
MODIFIED = "modified"
MISSING_OUTPUT = "missing-output"
CORRUPT_RECORD = "corrupt-record"
UNRECORDED = "unrecorded"

# The statuses a file can hold and still be trusted as what its record says.
TRUSTED_STATUSES = frozenset({VALID, MADE_BY_OLDER_BACKEND})

_ADDRESS_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Recipe:
    """A source name and the chain to run over it — what ``build.py`` authors.

    The chain is validated here, not at derive time, so a recipe with a
    non-transform in it fails where it is written.
    """

    source_name: str
    chain: tuple[Transform, ...]

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("Recipe.source_name must be non-empty")
        object.__setattr__(self, "chain", tuple(self.chain))
        chain_spec(self.chain)

    def _check(self, source: Source) -> None:
        if source.name != self.source_name:
            raise ValueError(
                f"recipe is for source {self.source_name!r} but was given {source.name!r}; "
                f"look the recipe's source up by its own name"
            )

    def address(
        self,
        source: Source,
        *,
        reference_fingerprint: str | None = None,
        backend: str = BACKEND,
    ) -> str:
        """The address this recipe resolves to over ``source`` under the running backend."""
        self._check(source)
        return address(source, self.chain, reference_fingerprint, backend)

    def derive(
        self,
        source: Source,
        *,
        song_dir: Path,
        reference_fingerprint: str | None = None,
        backend: str = BACKEND,
    ) -> Derived:
        self._check(source)
        return derive(
            source,
            self.chain,
            song_dir=song_dir,
            reference_fingerprint=reference_fingerprint,
            backend=backend,
        )


@dataclass(frozen=True)
class VerifyResult:
    """One record's (or stray file's) standing, with the reason in words."""

    path: Path
    address: str | None
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status in TRUSTED_STATUSES


def _running_version(backend: str) -> str | None:
    try:
        return backend_version(backend)
    except ValueError:
        return None


def _verify_record(record_path: Path, directory: Path) -> list[VerifyResult]:
    addr_from_name = address_of_filename(record_path.name)
    try:
        record = DerivedRecord.read(record_path)
    except ValueError as exc:
        return [VerifyResult(record_path, addr_from_name, CORRUPT_RECORD, str(exc))]
    if record.address != addr_from_name:
        return [VerifyResult(
            record_path, addr_from_name, CORRUPT_RECORD,
            f"record names address {record.address[:12]}… but the file is {record_path.name}",
        )]
    if record.recomputed_address() != record.address:
        return [VerifyResult(
            record_path, record.address, CORRUPT_RECORD,
            "record's fields do not hash to its address: the record was edited, or the "
            "address was computed from something the record does not say",
        )]
    results: list[VerifyResult] = []
    running = _running_version(record.backend)
    for output in record.outputs:
        path = directory / output.file
        if not path.is_file():
            results.append(VerifyResult(path, record.address, MISSING_OUTPUT, "output file is gone; derive() will re-render it"))
            continue
        if sha256_file(path) != output.checksum:
            results.append(VerifyResult(
                path, record.address, MODIFIED,
                "file bytes differ from the record's checksum: it was edited after it was "
                "derived. A derived file is a cache — regenerate it, or ingest the edit as "
                "a new source.",
            ))
            continue
        if running != record.backend_version:
            made_by = f"{record.backend} {record.backend_version}"
            now = f"{record.backend} {running}" if running is not None else f"{record.backend} (not installed)"
            results.append(VerifyResult(
                path, record.address, MADE_BY_OLDER_BACKEND,
                f"made by {made_by}; running {now}. Still valid — the address carries the "
                f"version that made it.",
            ))
            continue
        results.append(VerifyResult(path, record.address, VALID, "intact"))
    return results


def verify(song_dir: Path) -> list[VerifyResult]:
    """Every derived file's standing: intact, made by another version, modified, or unrecorded."""
    directory = derived_dir(song_dir)
    if not directory.is_dir():
        return []
    results: list[VerifyResult] = []
    recorded_outputs: set[Path] = set()
    for record_path in sorted(directory.glob("*.json")):
        found = _verify_record(record_path, directory)
        results.extend(found)
        for r in found:
            if r.path != record_path:
                recorded_outputs.add(r.path)
    for wav in sorted(directory.glob("*.wav")):
        if wav not in recorded_outputs:
            results.append(VerifyResult(
                wav, address_of_filename(wav.name), UNRECORDED,
                "no record vouches for this file; derive() will overwrite it, or delete it",
            ))
    return results


def _address_of(item: str | Path | Derived) -> str | None:
    """The derived address an item names, or None if it names no derived file.

    None is not an error: ``prune``'s input is everything a song points at,
    and a song points at its sources as well as its derived files. A path
    outside the cache keeps nothing in the cache, which is what None means.
    """
    if isinstance(item, Derived):
        return item.address
    name = item.name if isinstance(item, Path) else item
    if _ADDRESS_RE.match(name):
        return name
    return address_of_filename(Path(name).name)


def prune(song_dir: Path, addressed: Iterable[str | Path | Derived]) -> list[Path]:
    """The files under ``assets/derived/`` that no current recipe addresses.

    ``addressed`` is what the song's recipes resolve to today — the
    ``Derived`` values (or their addresses or paths) the current build
    produced, or the audio paths its clips reference. Those clip paths are a
    mixed set by nature: a song references its ingested sources as well as its
    derived files, and an item naming no derived file simply keeps nothing.
    Everything else in the directory, records included, is an orphan; a stray
    file with no address in its name is one too. Nothing is deleted.
    """
    directory = derived_dir(song_dir)
    if not directory.is_dir():
        return []
    keep = {addr for addr in map(_address_of, addressed) if addr is not None}
    orphans: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith(".") or not entry.is_file():
            continue
        # A .tmp is an interrupted render: never addressed, whatever its name says.
        if entry.suffix == ".tmp" or address_of_filename(entry.name) not in keep:
            orphans.append(entry)
    return orphans


__all__ = [
    "CORRUPT_RECORD",
    "MADE_BY_OLDER_BACKEND",
    "MISSING_OUTPUT",
    "MODIFIED",
    "TRUSTED_STATUSES",
    "UNRECORDED",
    "VALID",
    "Recipe",
    "VerifyResult",
    "prune",
    "verify",
]
