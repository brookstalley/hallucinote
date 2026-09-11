"""Normalize a dropped audio file into the store, and record what it is.

Ingest is the whole of "acquire": Hallucinote does not extract from media and
does not fetch from the internet — the entry point is an already-cut clip the
user drops in. What happens to it here is two things and no more. **Normalize**
— decode whatever container arrived into one canonical float32 WAV at
``assets/sources/<name>.wav``, keeping the sample rate and channel count it came
with (resampling is a transform, and the analysis loader resamples on read, so
an ingest that resampled would throw away information nothing asked it to
throw away). **Record provenance** — what the line is, where it is from, and
the checksum that makes it identifiable, into ``assets/manifest.json``.

Two decode routes, one output. ``soundfile`` reads WAV, FLAC and AIFF
directly. Everything else — MP3, M4A, and anything ``soundfile`` refuses —
goes through ``ffmpeg``, invoked as a list-argument subprocess with no shell
(the dropped path is an argument, never text interpolated into a command).

The ffmpeg invocation, confirmed against ffmpeg 8.0.1 on 2026-09-09::

    subprocess.run(["ffmpeg", "-i", "<path>", "-f", "wav", "-"], capture_output=True)

On success it exits ``0`` and writes a complete RIFF/WAVE stream to stdout —
``pcm_s16le`` at the input's own rate and channel count, with the RIFF size
field set to ``0xFFFFFFFF`` because the output is a pipe of unknown length.
``soundfile`` reads that stream from a ``BytesIO`` without complaint;
diagnostics go to stderr and are never mixed into stdout. On failure it exits
non-zero (``254`` for a missing input file) with the reason on stderr.
"""
from __future__ import annotations

import io
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from hallucinote.assets import store
from hallucinote.assets.manifest import ManifestEntry, validate_name
from hallucinote.assets.types import Source, validate_audio_array

# D9's binary policy: sources are committed to the songs repo, so ingest is
# where the repo's size is decided. Warn where a file is unusual for a line of
# dialogue; refuse where it is large enough that the author should say out loud
# that they mean it.
WARN_BYTES = 25 * 1024 * 1024
REFUSE_BYTES = 100 * 1024 * 1024

# Read directly; anything else is handed to ffmpeg. The list is what
# ``soundfile`` reads losslessly and reliably, not everything libsndfile will
# open — a container outside it costs one subprocess and is never wrong.
SOUNDFILE_SUFFIXES = frozenset({".wav", ".wave", ".flac", ".aif", ".aiff", ".aifc"})

# Containers that are lossy by construction. Recorded because a normalized WAV
# looks lossless whatever it came from, and a reader deciding whether to
# re-acquire a line needs to know the copy in the repo is already generation
# two.
LOSSY_SUFFIXES = frozenset(
    {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma", ".mp4"}
)

FFMPEG = "ffmpeg"


@dataclass(frozen=True)
class Decoded:
    """Audio as it came off disk, plus which route read it."""

    audio: np.ndarray
    sample_rate: int
    decoder: str


@dataclass(frozen=True)
class IngestResult:
    """What one ingest did — the source it wrote and what it wants said.

    ``warnings`` are the messages a caller must show: a size the author should
    know about, or an unusual property of the file. They are not errors; a
    refusal raises.
    """

    source: Source
    entry: ManifestEntry
    replaced: bool
    decoder: str
    warnings: tuple[str, ...] = ()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_2d(audio: np.ndarray) -> np.ndarray:
    """Give mono the explicit channel axis every array in this package has."""
    arr = np.asarray(audio)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return validate_audio_array(arr, where="decoded audio")


def decode_with_soundfile(path: Path) -> Decoded:
    """Read a container ``soundfile`` handles, as float32."""
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    return Decoded(audio=_as_2d(audio), sample_rate=int(sample_rate), decoder="soundfile")


def decode_with_ffmpeg(path: Path) -> Decoded:
    """Decode through ``ffmpeg`` to a WAV stream and read it back in memory.

    A list-argument subprocess with no shell: the dropped path is an argument,
    so a filename full of shell metacharacters is a filename and nothing else.
    """
    try:
        completed = subprocess.run(
            [FFMPEG, "-i", str(path), "-f", "wav", "-"],
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            f"{path.name} needs `ffmpeg` to decode (soundfile does not read "
            f"{path.suffix or 'this container'}), and ffmpeg is not on PATH. "
            "Install it — `brew install ffmpeg` on macOS — or convert the file "
            "to WAV, FLAC or AIFF first."
        ) from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = detail[-1] if detail else "no diagnostic on stderr"
        raise ValueError(
            f"ffmpeg could not decode {path} (exit {completed.returncode}): "
            f"{tail}. Check the file plays, or convert it to WAV before "
            "ingesting."
        )
    audio, sample_rate = sf.read(
        io.BytesIO(completed.stdout), dtype="float32", always_2d=True
    )
    return Decoded(audio=_as_2d(audio), sample_rate=int(sample_rate), decoder="ffmpeg")


def decode(path: Path) -> Decoded:
    """Read any dropped file into float32 audio, by whichever route reads it.

    Extension chooses the route; a ``soundfile`` refusal falls through to
    ffmpeg rather than failing, because a mislabelled extension is a user's
    file being ordinary, not a user's mistake.
    """
    if path.suffix.lower() in SOUNDFILE_SUFFIXES:
        try:
            return decode_with_soundfile(path)
        except RuntimeError:
            # libsndfile's own failure (`LibsndfileError` derives from
            # RuntimeError) — the container is not what its extension claims.
            return decode_with_ffmpeg(path)
    return decode_with_ffmpeg(path)


def _check_size(path: Path, *, allow_large: bool) -> tuple[str, ...]:
    """Apply D9's guard: warn at 25 MB, refuse above 100 MB unbidden."""
    size = path.stat().st_size
    megabytes = size / (1024 * 1024)
    if size > REFUSE_BYTES and not allow_large:
        raise ValueError(
            f"{path.name} is {megabytes:.1f} MB, above the {REFUSE_BYTES // (1024 * 1024)} MB "
            "ingest limit. Sources are committed to the songs repo, so a file "
            "this size is a decision, not a default: trim the clip to the part "
            "the song uses, or pass --allow-large to commit it whole."
        )
    if size > WARN_BYTES:
        return (
            f"{path.name} is {megabytes:.1f} MB — larger than a line of dialogue "
            "usually is, and it goes into the songs repo as-is. Trimming it "
            "before ingest keeps the repo clonable.",
        )
    return ()


def ingest(
    song_dir: Path | str,
    media_path: Path | str,
    *,
    name: str,
    note: str,
    origin: str,
    replace: bool = False,
    allow_large: bool = False,
) -> IngestResult:
    """Normalize ``media_path`` into the song's store and record its provenance.

    Refuses a name the manifest already holds unless ``replace`` — a source is
    immutable, so overwriting one silently would strand every derived asset
    addressed from the old checksum. ``replace`` keeps the slot and records the
    checksum that used to fill it in ``superseded``, which is the record that
    an old derived file was made from something that is no longer here.
    """
    song_dir = Path(song_dir)
    media_path = Path(media_path)
    validate_name(name)
    if not media_path.is_file():
        raise ValueError(
            f"no file at {media_path}. `asset add` takes an already-cut audio "
            "clip on disk; it does not fetch from the internet or extract from "
            "a media file."
        )
    if not note.strip():
        raise ValueError(
            "--note is required and must say what the line IS (\"the pilot's "
            "last transmission\"). For film material the note is the only "
            "record of what the sample is; a filename is not one."
        )
    if not origin.strip():
        raise ValueError(
            "--origin is required and must say where the line is FROM (title, "
            "medium, scene). It is prose, not a path to a media file."
        )

    manifest = store.load_manifest(song_dir)
    existing = manifest.get(name)
    if existing is not None and not replace:
        raise ValueError(
            f"{song_dir / 'assets' / 'manifest.json'} already holds a source "
            f"named {name!r} ({existing.origin}). A source is immutable: choose "
            "another name, or pass --replace to put new bytes in this slot "
            "(the old checksum is kept in the entry's superseded list)."
        )

    warnings = _check_size(media_path, allow_large=allow_large)
    decoded = decode(media_path)

    destination = store.source_path(song_dir, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    # The container is named explicitly: the temp name ends in .tmp, so there
    # is no extension for soundfile to infer the format from.
    sf.write(
        str(tmp), decoded.audio, decoded.sample_rate, subtype="FLOAT", format="WAV"
    )
    tmp.replace(destination)

    checksum = store.file_checksum(destination)
    entry = ManifestEntry(
        name=name,
        path=store.source_ref(name),
        checksum=checksum,
        sample_rate=decoded.sample_rate,
        channels=int(decoded.audio.shape[1]),
        duration_s=float(decoded.audio.shape[0]) / decoded.sample_rate,
        note=note.strip(),
        origin=origin.strip(),
        original_filename=media_path.name,
        original_format=media_path.suffix.lower().lstrip(".") or "unknown",
        original_lossy=media_path.suffix.lower() in LOSSY_SUFFIXES,
        ingested_at=_utc_now_iso(),
        superseded=(
            existing.superseded + (existing.checksum,) if existing is not None else ()
        ),
    )
    store.write_manifest(song_dir, manifest.with_entry(entry))
    return IngestResult(
        source=entry.as_source(song_dir),
        entry=entry,
        replaced=existing is not None,
        decoder=decoded.decoder,
        warnings=warnings,
    )


def ffmpeg_available() -> bool:
    """Whether the ffmpeg decode route can run at all on this machine."""
    return shutil.which(FFMPEG) is not None
