"""Value objects the asset store, the recipes and the transforms exchange.

These are the contract between modules built separately: a ``Source`` is what
the store hands out, a ``Transform`` is what a recipe is made of, a ``Derived``
is what a recipe returns. Validation lives here so every producer refuses the
same malformed value the same way; behaviour does not — a module that needs
to change these shapes is a sign the partition was drawn wrong, not a reason
to edit them in place.

Audio arrays are always two-dimensional ``(n_samples, n_channels)`` float32.
A source keeps the channel count it was ingested with; conversion to the
analysis loader's stereo shape is the loader's job, not the store's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Source:
    """One immutable source under ``assets/sources/``, as the manifest records it.

    ``checksum`` is the sha256 of the normalized file's bytes — the identity a
    derived asset's address is built from, and the check that tells a reader
    the file on disk is still the one the manifest describes.
    """

    name: str
    path: Path
    checksum: str
    sample_rate: int
    channels: int
    duration_s: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Source.name must be non-empty")
        if not _SHA256_HEX.match(self.checksum):
            raise ValueError(
                f"Source.checksum must be 64 lowercase hex chars (sha256); got "
                f"{self.checksum!r}"
            )
        if self.sample_rate <= 0:
            raise ValueError(f"Source.sample_rate must be > 0; got {self.sample_rate}")
        if self.channels < 1:
            raise ValueError(f"Source.channels must be >= 1; got {self.channels}")
        if self.duration_s < 0:
            raise ValueError(f"Source.duration_s must be >= 0; got {self.duration_s}")


@dataclass(frozen=True)
class TransformContext:
    """What a transform may know beyond the audio it is given.

    ``reference_fingerprint`` is set only for a score-dependent transform (a
    carve against the arrangement as it stood); it enters the derived address
    so the file cannot outlive the notes it was made against.
    """

    song_dir: Path
    source: Source
    reference_fingerprint: str | None = None
    backend: str = "librosa"


@runtime_checkable
class Transform(Protocol):
    """One step of a recipe.

    ``kind`` names the step; ``params()`` returns every parameter, exactly,
    because that dict is hashed into the derived address — a parameter left
    out of it is a parameter that cannot invalidate the cache. ``apply``
    returns one array, or a list of arrays for a transform that splits its
    input (chopping at onsets).
    """

    @property
    def kind(self) -> str: ...

    def params(self) -> dict[str, Any]: ...

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]: ...


@dataclass(frozen=True)
class Derived:
    """A derived file the cache holds, and the recipe that made it.

    ``address`` is the content hash the file and its record are named by;
    ``chain`` is the recipe as applied, in order. The file is a cache — it can
    always be deleted and regenerated from ``source_checksum`` + ``chain``.
    """

    path: Path
    address: str
    record_path: Path
    source_checksum: str
    chain: tuple[Transform, ...]
    reference_fingerprint: str | None = None
    # Every file the recipe wrote, in order. A transform that splits its input
    # (chopping at onsets) writes several; ``path`` is always ``outputs[0]``,
    # so a reader that only knows ``path`` still names a real file and a
    # reader that wants them all never has to guess the naming. Left empty by
    # the writer it defaults to ``(path,)``.
    outputs: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.outputs:
            object.__setattr__(self, "outputs", (self.path,))
        elif self.outputs[0] != self.path:
            raise ValueError(
                f"Derived.path {self.path} must be outputs[0]; got outputs[0]={self.outputs[0]}"
            )
        if not _SHA256_HEX.match(self.address):
            raise ValueError(
                f"Derived.address must be 64 lowercase hex chars (sha256); got "
                f"{self.address!r}"
            )
        if not _SHA256_HEX.match(self.source_checksum):
            raise ValueError("Derived.source_checksum must be a sha256 hex digest")
        if not self.chain:
            raise ValueError("Derived.chain must name at least one transform")


def validate_audio_array(audio: np.ndarray, *, where: str = "audio") -> np.ndarray:
    """The one array shape every transform and loader here agrees on.

    Returns the array as float32 ``(n_samples, n_channels)``; refuses anything
    else rather than guessing whether a 1-D array is mono or a channel-major
    stereo pair.
    """
    arr = np.asarray(audio)
    if arr.ndim != 2:
        raise ValueError(
            f"{where} must be 2-D (n_samples, n_channels); got shape {arr.shape}. "
            "Reshape mono as (n, 1) before passing it."
        )
    if arr.shape[1] < 1 or arr.shape[1] > arr.shape[0]:
        raise ValueError(
            f"{where} has shape {arr.shape}: expected samples on axis 0 and "
            "channels on axis 1"
        )
    return arr.astype(np.float32, copy=False)
