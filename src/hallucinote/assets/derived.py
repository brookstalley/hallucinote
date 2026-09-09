"""The content-addressed derived cache — a file's name is the whole answer to "is it stale?".

A derived file lives at ``assets/derived/<address>-<slug>.wav`` beside its
record ``assets/derived/<address>.json``, and the address is a sha256 over
everything that made it: the source's checksum, the transform chain with
every parameter, the backend and its version, and — for a score-dependent
recipe — the fingerprint of the notes it was made against. Change any of
those and the address changes, so nothing can reference a stale file by a
current name; the old file is an orphan for ``recipes.prune`` to list.

The cache is a tolerance for DSP that is not bit-reproducible across library
versions: a record whose backend version differs from the running one
is still valid, because its address carries the version that made it and the
file is checked in precisely so a version bump does not force a re-render.
``derive`` therefore looks up the running-version address first and, missing
that, an intact record of the same source, chain, backend and reference made
by another version — and only renders when neither exists.

Every write here is atomic (temp file, then rename) and the record is written
last, so an interrupted render leaves at worst an unrecorded WAV that the
next run overwrites — never a record vouching for a file that is not there.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import soundfile as sf

from hallucinote.assets.types import (
    Derived,
    ScoreDependent,
    Source,
    Transform,
    TransformContext,
    validate_audio_array,
)

BACKEND = "librosa"
RECORD_VERSION = 1
DERIVED_SUBDIR = Path("assets") / "derived"

# Derived WAVs are float32 like the analyzer's captures: normalize and fade
# leave no headroom question, and the sample loader takes them unchanged.
_WAV_SUBTYPE = "FLOAT"

_ADDRESS_RE = re.compile(r"^[0-9a-f]{64}$")
_LEADING_ADDRESS_RE = re.compile(r"^([0-9a-f]{64})(?:-|\.json$)")
_SLUG_JUNK_RE = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 60


@lru_cache(maxsize=None)
def backend_version(backend: str = BACKEND) -> str:
    """The installed version of the backend that will render, read once per process."""
    try:
        return importlib.metadata.version(backend)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError(
            f"backend {backend!r} is not installed, so nothing can be derived through it "
            f"or addressed by its version. Install it, or use the default {BACKEND!r}."
        ) from exc


def library_versions() -> dict[str, str]:
    """What else touched the samples — recorded for provenance, never hashed."""
    return {name: importlib.metadata.version(name) for name in ("numpy", "soundfile")}


def chain_spec(chain: Sequence[Transform]) -> list[dict[str, Any]]:
    """The chain as the record and the address see it: kind and every parameter."""
    if not chain:
        raise ValueError("a recipe needs at least one transform; an empty chain derives nothing")
    spec: list[dict[str, Any]] = []
    for step in chain:
        if not isinstance(step, Transform):
            raise ValueError(
                f"{step!r} is not a Transform: a recipe step needs `kind`, `params()` and "
                f"`apply()`. Use the transforms in hallucinote.assets.transforms, or build "
                f"one that implements the protocol."
            )
        spec.append({"kind": step.kind, "params": dict(step.params())})
    return spec


def canonical_json(payload: Any) -> bytes:
    """One byte sequence per value: sorted keys, no whitespace, no NaN."""
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"a transform's params() must be plain JSON values (numbers, strings, bools, "
            f"None, lists, dicts) so they can be hashed into the address; got {exc}"
        ) from exc


REFERENCE_JOIN = "+"


def reference_of(chain: Sequence[Transform]) -> str | None:
    """The reference fingerprint a chain's score-dependent steps carry, or None.

    The derived record has one field for what a file was made against; a
    chain with no score-dependent step in it was made against nothing.
    """
    prints = [step.fingerprint() for step in chain if isinstance(step, ScoreDependent)]
    return REFERENCE_JOIN.join(prints) if prints else None


def address(
    source: Source,
    chain: Sequence[Transform],
    reference_fingerprint: str | None = None,
    backend: str = BACKEND,
    *,
    backend_version_override: str | None = None,
) -> str:
    """The sha256 that names a derived file — over everything that made it.

    ``backend_version_override`` lets a verifier recompute the address a
    record was made under; a caller deriving new audio leaves it unset and
    gets the running version.

    ``reference_fingerprint`` is INFERRED from the chain when not given, here
    rather than in any one caller, because three routes reach an address —
    the ``assets`` facade, ``Recipe.address``/``Recipe.derive``, and this
    module's own ``derive`` — and a route that skipped the inference would
    name a second file for identical content and record nothing about what it
    was carved against. An explicit value still wins, for a caller that
    resolved the reference itself.
    """
    version = backend_version_override if backend_version_override is not None else backend_version(backend)
    if reference_fingerprint is None:
        reference_fingerprint = reference_of(chain)
    payload = {
        "source_checksum": source.checksum,
        "chain": chain_spec(chain),
        "backend": backend,
        "backend_version": version,
        "reference_fingerprint": reference_fingerprint,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def slug_for(source_name: str, chain: Sequence[Transform]) -> str:
    """A human hint after the hash so a directory listing reads as recipes."""
    raw = "-".join([source_name, *(step.kind for step in chain)]).lower()
    slug = _SLUG_JUNK_RE.sub("-", raw).strip("-")
    return slug[:_SLUG_MAX].rstrip("-") or "derived"


def derived_dir(song_dir: Path) -> Path:
    return Path(song_dir) / DERIVED_SUBDIR


def address_of_filename(name: str) -> str | None:
    """The address a derived file or record is named by, or None for a stray file."""
    match = _LEADING_ADDRESS_RE.match(name)
    return match.group(1) if match else None


@dataclass(frozen=True)
class OutputRecord:
    """One output file of a derived record, named relative to the derived directory."""

    file: str
    checksum: str

    def to_json(self) -> dict[str, str]:
        return {"file": self.file, "checksum": self.checksum}


@dataclass(frozen=True)
class DerivedRecord:
    """What a ``<address>.json`` says: what produced the file, from what, against what.

    The chain is stored as its spec (kind + params), not as transform objects,
    because the record must be readable by a verifier that has no recipe in
    hand — and because the spec is exactly what was hashed.
    """

    address: str
    source_name: str
    source_checksum: str
    chain: tuple[dict[str, Any], ...]
    backend: str
    backend_version: str
    reference_fingerprint: str | None
    outputs: tuple[OutputRecord, ...]
    created_at: str
    library_versions: dict[str, str]

    def __post_init__(self) -> None:
        if not _ADDRESS_RE.match(self.address):
            raise ValueError(f"record address must be a sha256 hex digest; got {self.address!r}")
        if not self.chain:
            raise ValueError("record chain must name at least one transform")
        if not self.outputs:
            raise ValueError("record must name at least one output file")

    def recomputed_address(self) -> str:
        """The address this record's own fields hash to — equal to ``address`` iff it is honest."""
        payload = {
            "source_checksum": self.source_checksum,
            "chain": list(self.chain),
            "backend": self.backend,
            "backend_version": self.backend_version,
            "reference_fingerprint": self.reference_fingerprint,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()

    def matches_recipe(
        self,
        source: Source,
        chain: Sequence[Transform],
        reference_fingerprint: str | None,
        backend: str,
    ) -> bool:
        """Same source, chain, backend and reference — the version is deliberately not compared."""
        return (
            self.source_checksum == source.checksum
            and list(self.chain) == chain_spec(chain)
            and self.backend == backend
            and self.reference_fingerprint == reference_fingerprint
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "record_version": RECORD_VERSION,
            "address": self.address,
            "source": {"name": self.source_name, "checksum": self.source_checksum},
            "chain": list(self.chain),
            "backend": self.backend,
            "backend_version": self.backend_version,
            "library_versions": dict(self.library_versions),
            "reference_fingerprint": self.reference_fingerprint,
            "outputs": [o.to_json() for o in self.outputs],
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DerivedRecord:
        try:
            source = data["source"]
            return cls(
                address=data["address"],
                source_name=source["name"],
                source_checksum=source["checksum"],
                chain=tuple(data["chain"]),
                backend=data["backend"],
                backend_version=data["backend_version"],
                reference_fingerprint=data.get("reference_fingerprint"),
                outputs=tuple(OutputRecord(o["file"], o["checksum"]) for o in data["outputs"]),
                created_at=data["created_at"],
                library_versions=dict(data.get("library_versions", {})),
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"derived record is missing or mis-shapes a field: {exc!r}") from exc

    def write(self, path: Path) -> None:
        _atomic_write_bytes(path, (json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n").encode("utf-8"))

    @classmethod
    def read(cls, path: Path) -> DerivedRecord:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"derived record {path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"derived record {path} must be a JSON object")
        return cls.from_json(data)

    def output_paths(self, directory: Path) -> tuple[Path, ...]:
        return tuple(directory / o.file for o in self.outputs)

    def intact(self, directory: Path) -> bool:
        """Every output is where the record says, with the bytes the record checksummed."""
        return all(
            (directory / o.file).is_file() and sha256_file(directory / o.file) == o.checksum
            for o in self.outputs
        )

    def to_derived(self, directory: Path, chain: Sequence[Transform]) -> Derived:
        paths = self.output_paths(directory)
        return Derived(
            path=paths[0],
            address=self.address,
            record_path=directory / f"{self.address}.json",
            source_checksum=self.source_checksum,
            chain=tuple(chain),
            reference_fingerprint=self.reference_fingerprint,
            outputs=paths,
        )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    tmp = path.with_name(path.name + ".tmp")
    sf.write(str(tmp), audio, sample_rate, subtype=_WAV_SUBTYPE, format="WAV")
    os.replace(tmp, path)


def resolve_source_path(source: Source, song_dir: Path) -> Path:
    """A manifest records the source relative to the song so a clone still finds it."""
    return source.path if source.path.is_absolute() else Path(song_dir) / source.path


def load_source_audio(source: Source, song_dir: Path) -> tuple[np.ndarray, int]:
    """Read the source, refusing if it is no longer the file its checksum names.

    The address is built from ``source.checksum``; rendering from bytes that
    hash differently would file the result under a name that lies.
    """
    path = resolve_source_path(source, song_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"source {source.name!r} is missing at {path}; re-ingest it, or fix the "
            f"manifest path"
        )
    actual = sha256_file(path)
    if actual != source.checksum:
        raise ValueError(
            f"source {source.name!r} at {path} has changed: its bytes hash to "
            f"{actual[:12]}…, the manifest says {source.checksum[:12]}…. Sources are "
            f"immutable — re-ingest the new file under a new name rather than editing "
            f"one in place."
        )
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if int(sample_rate) != source.sample_rate:
        raise ValueError(
            f"source {source.name!r} is {sample_rate} Hz on disk but the manifest says "
            f"{source.sample_rate} Hz; re-ingest it"
        )
    return validate_audio_array(audio, where=f"source {source.name!r}"), int(sample_rate)


def run_chain(
    audio: np.ndarray, sample_rate: int, chain: Sequence[Transform], ctx: TransformContext
) -> list[np.ndarray]:
    """Apply the chain in order; a splitting step fans out and later steps run per piece."""
    pieces: list[np.ndarray] = [audio]
    for step in chain:
        produced: list[np.ndarray] = []
        for piece in pieces:
            out = step.apply(piece, sample_rate, ctx)
            outs = out if isinstance(out, list) else [out]
            if not outs:
                raise ValueError(f"transform {step.kind!r} produced no audio")
            produced.extend(validate_audio_array(o, where=f"{step.kind} output") for o in outs)
        pieces = produced
    return pieces


def _find_cached(
    directory: Path,
    addr: str,
    source: Source,
    chain: Sequence[Transform],
    reference_fingerprint: str | None,
    backend: str,
) -> DerivedRecord | None:
    """The running-version record if intact; else an intact one another version made."""
    exact = directory / f"{addr}.json"
    if exact.is_file():
        try:
            record = DerivedRecord.read(exact)
        except ValueError:
            record = None
        if record is not None and record.address == addr and record.intact(directory):
            return record
    for record_path in sorted(directory.glob("*.json")):
        if record_path == exact:
            continue
        try:
            record = DerivedRecord.read(record_path)
        except ValueError:
            continue
        if (
            record.matches_recipe(source, chain, reference_fingerprint, backend)
            and record.recomputed_address() == record.address
            and record.intact(directory)
        ):
            return record
    return None


def derive(
    source: Source,
    chain: Sequence[Transform],
    *,
    song_dir: Path,
    reference_fingerprint: str | None = None,
    backend: str = BACKEND,
) -> Derived:
    """Return the derived file for ``chain`` over ``source``, rendering only on a cache miss.

    A hit is a record whose outputs are still the bytes it checksummed; a
    record with a modified or missing output is a miss and is re-rendered
    over. The returned ``Derived.chain`` is the caller's transforms, so the
    recipe travels with the file it names.

    ``reference_fingerprint`` is inferred from the chain when not given, so
    the record says what the file was carved against whichever route reached
    here — the ``assets`` facade, a ``Recipe``, or this function directly.
    """
    chain = tuple(chain)
    # Resolve once, then pass it explicitly: a score-dependent step reads the
    # DB afresh on every fingerprint() call, so letting address() infer it a
    # second time would both cost a re-read and risk two different answers
    # naming the record and the file.
    if reference_fingerprint is None:
        reference_fingerprint = reference_of(chain)
    addr = address(source, chain, reference_fingerprint, backend)
    directory = derived_dir(song_dir)
    directory.mkdir(parents=True, exist_ok=True)

    cached = _find_cached(directory, addr, source, chain, reference_fingerprint, backend)
    if cached is not None:
        return cached.to_derived(directory, chain)

    audio, sample_rate = load_source_audio(source, song_dir)
    ctx = TransformContext(
        song_dir=Path(song_dir),
        source=source,
        reference_fingerprint=reference_fingerprint,
        backend=backend,
    )
    pieces = run_chain(audio, sample_rate, chain, ctx)

    slug = slug_for(source.name, chain)
    if len(pieces) == 1:
        names = [f"{addr}-{slug}.wav"]
    else:
        names = [f"{addr}-{slug}-{i:02d}.wav" for i in range(1, len(pieces) + 1)]
    outputs: list[OutputRecord] = []
    for name, piece in zip(names, pieces):
        path = directory / name
        _atomic_write_wav(path, piece, sample_rate)
        outputs.append(OutputRecord(file=name, checksum=sha256_file(path)))

    record = DerivedRecord(
        address=addr,
        source_name=source.name,
        source_checksum=source.checksum,
        chain=tuple(chain_spec(chain)),
        backend=backend,
        backend_version=backend_version(backend),
        reference_fingerprint=reference_fingerprint,
        outputs=tuple(outputs),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        library_versions=library_versions(),
    )
    record.write(directory / f"{addr}.json")
    return record.to_derived(directory, chain)


__all__ = [
    "BACKEND",
    "DERIVED_SUBDIR",
    "RECORD_VERSION",
    "DerivedRecord",
    "OutputRecord",
    "address",
    "address_of_filename",
    "backend_version",
    "canonical_json",
    "chain_spec",
    "derive",
    "derived_dir",
    "library_versions",
    "load_source_audio",
    "resolve_source_path",
    "run_chain",
    "sha256_file",
    "slug_for",
]
