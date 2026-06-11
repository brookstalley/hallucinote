"""Read a captures dir + manifest from disk into in-memory arrays.

The manifest schema is produced by ``hallucinote_mcp.handlers.render``
— see that module for the canonical writer. We refuse to read shapes
we don't recognize (schema version, sample format, channel count) so
the analysis pipeline never sees coerced / lossy data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf

SurfaceKind = Literal["track", "return", "master"]

# Manifest schema version this loader understands. Bump (and add a
# migration branch) when handlers/render.py bumps its writer.
_SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({"1"})

# Required WAV format. ``sfrecord~`` writes float32 stereo per the
# analyzer spec (`m4l/HallucinoteAnalyzer.amxd.spec.md`). Coercion is
# refused — analysis math depends on this.
_REQUIRED_SUBTYPE = "FLOAT"
_REQUIRED_CHANNELS = 2


@dataclass(frozen=True)
class Surface:
    """One loaded WAV — stem, return, or master."""
    track_id: str
    surface_kind: SurfaceKind
    surface_name: str
    audio: np.ndarray  # (n_samples, 2) float32
    sample_rate: int


@dataclass(frozen=True)
class CaptureSet:
    """A loaded capture — manifest metadata + audio for every surface.

    ``stems`` and ``returns`` are kept separate from ``master`` because
    the master is structurally required (attribution needs it) and the
    contribution math treats it differently. Returns are separate from
    stems because they're wet-side signal flow — reverb verification
    consumes (dry_stem, wet_return) pairs.
    """
    song_slug: str
    captured_at: str
    analyzer_signature: str
    captures_dir: Path
    manifest_path: Path
    sample_rate: int
    start_at_beat: float
    stop_at_beat: float
    # Beats of pure reverb ring-out captured AFTER stop_at_beat (the render's
    # ``ring_out_beats``). The recorded audio spans [start_at_beat,
    # stop_at_beat + ring_out_beats]; the dry input stops at stop_at_beat, so
    # this trailing region is where RT60 is measured. 0.0 for captures made
    # before ring-out capture landed (no usable tail → honest RT60 skip).
    ring_out_beats: float
    master: Surface
    stems: list[Surface] = field(default_factory=list)
    returns: list[Surface] = field(default_factory=list)
    # Song audit-log seq the capture reflects (manifest.db_seq, written by
    # the render path at trigger time — AUD-4W7K). None for captures made
    # before seq tagging landed or when provenance couldn't be read; such
    # captures can't serve as seq-keyed baselines but stay fully loadable.
    db_seq: int | None = None


def load_capture(manifest_path: Path | str) -> CaptureSet:
    """Read a captures manifest + its WAVs into a ``CaptureSet``.

    Raises:
        FileNotFoundError: a manifest-referenced WAV is missing on disk
            (the track_id is included in the message for triage).
        ValueError: schema version mismatch, missing master, or any WAV
            is not float32 stereo.
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in _SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise ValueError(
            f"manifest schema_version={schema_version!r} not supported; "
            f"this loader understands {sorted(_SUPPORTED_MANIFEST_SCHEMA_VERSIONS)} "
            f"(see hallucinote_mcp/.../handlers/render.py for the writer)"
        )

    captures_dir = manifest_path.parent

    master_entry = manifest.get("master")
    if master_entry is None:
        raise ValueError(
            f"manifest at {manifest_path} has no master entry — captures "
            f"without a master are structurally incomplete (the master "
            f"is the attribution baseline; without it the contribution "
            f"math has nothing to compare stems against)"
        )

    master = _load_surface(master_entry, "master", captures_dir)
    sample_rate = master.sample_rate

    stems = [
        _load_surface(entry, "track", captures_dir)
        for entry in manifest.get("tracks", [])
    ]
    returns = [
        _load_surface(entry, "return", captures_dir)
        for entry in manifest.get("returns", [])
    ]

    _check_consistent_sample_rate(master, stems, returns)

    return CaptureSet(
        song_slug=manifest["song_slug"],
        captured_at=manifest["captured_at"],
        analyzer_signature=manifest["analyzer_signature"],
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        sample_rate=sample_rate,
        start_at_beat=float(manifest["start_at_beat"]),
        stop_at_beat=float(manifest["stop_at_beat"]),
        ring_out_beats=float(manifest.get("ring_out_beats", 0.0)),
        master=master,
        stems=stems,
        returns=returns,
        db_seq=(
            int(manifest["db_seq"])
            if manifest.get("db_seq") is not None
            else None
        ),
    )


def _load_surface(
    entry: dict,
    surface_kind: SurfaceKind,
    captures_dir: Path,
) -> Surface:
    track_id = entry["track_id"]
    # Prefer the absolute path the manifest captured (renders to the
    # actual on-disk location); fall back to filename-relative for
    # portability across moved capture dirs.
    candidate_paths = []
    abs_path = entry.get("absolute_path")
    if abs_path:
        candidate_paths.append(Path(abs_path))
    filename = entry.get("filename")
    if filename:
        candidate_paths.append(captures_dir / filename)
    wav_path = next((p for p in candidate_paths if p.exists()), None)
    if wav_path is None:
        raise FileNotFoundError(
            f"capture WAV missing for {track_id} (surface_kind={surface_kind}); "
            f"checked: {[str(p) for p in candidate_paths]}"
        )

    info = sf.info(str(wav_path))
    if info.subtype != _REQUIRED_SUBTYPE:
        raise ValueError(
            f"capture WAV {wav_path} is subtype={info.subtype!r}, "
            f"expected {_REQUIRED_SUBTYPE!r} (float32). sfrecord~ in the "
            f"analyzer patch is configured for float32; analysis math "
            f"depends on this — coercion is refused"
        )
    if info.channels != _REQUIRED_CHANNELS:
        raise ValueError(
            f"capture WAV {wav_path} is {info.channels}-channel, "
            f"expected stereo ({_REQUIRED_CHANNELS}-channel). Live's "
            f"stem captures are always stereo per the analyzer spec"
        )

    audio, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
    return Surface(
        track_id=track_id,
        surface_kind=surface_kind,
        surface_name=entry.get("surface_name", track_id),
        audio=audio.astype(np.float32, copy=False),
        sample_rate=int(sample_rate),
    )


def _check_consistent_sample_rate(
    master: Surface,
    stems: list[Surface],
    returns: list[Surface],
) -> None:
    """All surfaces from a single render share Live's session sample rate.
    A mismatch indicates a manifest or files got mixed across capture
    dirs — refuse rather than producing garbage attribution math."""
    expected = master.sample_rate
    for surface in (*stems, *returns):
        if surface.sample_rate != expected:
            raise ValueError(
                f"sample-rate mismatch: master={expected} Hz, "
                f"{surface.track_id}={surface.sample_rate} Hz. "
                f"All surfaces in one render must share the session SR"
            )


__all__ = [
    "CaptureSet",
    "Surface",
    "load_capture",
]
