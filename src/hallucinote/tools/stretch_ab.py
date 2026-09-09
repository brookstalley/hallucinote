#!/usr/bin/env python3
"""Render one stretch/pitch transform through every available backend so the
formant question can be settled by ear.

librosa's phase vocoder and Rubber Band's formant-aware engine disagree most
audibly on speech: a shifted line either keeps its vowel colour or turns into a
chipmunk. This harness renders the same `--rate` / `--semitones` move through
each backend that is installed, writes the results side by side, and prints one
number per file — the spectral-centroid delta against the source, which is the
cheapest hint that formants moved with the pitch instead of staying put.

The number is a hint, not a verdict, and it is never a threshold: a pitch shift
moves the centroid *by design*, so the backends are read against each other
rather than against zero. Which one ships is the listener's call; the harness
only makes the two hearable.

Renders are mono (the question is timbral, not spatial) and are written as
float WAV, so a transform that pushes peaks past full scale is audible as
itself rather than as clipping.

Usage:
    python3 -m hallucinote.tools.stretch_ab line.wav --semitones -3
    python3 -m hallucinote.tools.stretch_ab line.wav --rate 0.85 --out /tmp/ab
    python3 -m hallucinote.tools.stretch_ab line.wav --semitones 4 --no-formant

Rubber Band needs both the `pyrubberband` package (`uv sync --extra
audio-stretch-ab`) and the `rubberband` binary on PATH; when either is missing
the table says which one and renders librosa alone.

Exit codes: 0 = table printed · 2 = the source cannot be read · 3 = the
requested transform is not a transform (nothing to compare).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from hallucinote.audio.timbre import spectral_centroid_hz

# The optional backend is the `rubberband` command-line tool, driven directly:
# every flag it takes is on its own usage screen, and driving the binary means
# the formant switch is a real argument rather than a value smuggled through a
# wrapper. Flags used, from `rubberband --help` (Rubber Band Library 3.x CLI;
# the binary was not installed on the machine this was written on, so the
# shapes are from the documented usage and chunk 17's listening session is
# the first real run): `-t <X>` time ratio (output length / input length),
# `-p <N>` pitch shift in semitones, `-F` formant preservation, `-q` quiet.
_RUBBERBAND_BINARY = "rubberband"

# Float WAV: no quantisation and no clipping, so what the listener hears is the
# backend's output and nothing else.
_OUTPUT_SUBTYPE = "FLOAT"


@dataclass(frozen=True)
class BackendRender:
    """One backend's line in the table — either a written file with its
    centroid, or the reason it could not run. Absence is reported, never
    silently skipped, because "Rubber Band was never tried" and "Rubber Band
    sounded the same" are opposite answers to R6.2."""

    backend: str
    path: Path | None = None
    centroid_hz: float | None = None
    centroid_delta_hz: float | None = None
    absent_reason: str | None = None


def load_mono(source: Path) -> tuple[np.ndarray, int]:
    """Read a source file down to one channel, raising a teaching error rather
    than a libsndfile stack trace when the path is wrong or the format is not
    one soundfile can open."""
    if not source.is_file():
        raise FileNotFoundError(
            f"stretch-ab: no readable source at {source} — pass the path to a "
            f"WAV of the line you want to hear stretched or shifted."
        )
    try:
        data, sample_rate = sf.read(str(source), dtype="float32", always_2d=True)
    except RuntimeError as exc:
        raise OSError(
            f"stretch-ab: could not decode {source} ({exc}). The harness reads "
            f"what libsndfile reads — WAV, AIFF, FLAC; convert an MP3 first."
        ) from exc
    return np.asarray(data, dtype=np.float32).mean(axis=1), int(sample_rate)


def render_librosa(
    mono: np.ndarray, sample_rate: int, *, rate: float, semitones: float
) -> np.ndarray:
    """Phase-vocoder stretch then resampling shift — the always-present
    baseline. Each half is skipped when its parameter is the identity so a pure
    pitch A/B costs one vocoder pass, not two."""
    import librosa

    out = mono
    if rate != 1.0:
        out = librosa.effects.time_stretch(out, rate=rate)
    if semitones != 0.0:
        out = librosa.effects.pitch_shift(
            out, sr=sample_rate, n_steps=semitones
        )
    return np.asarray(out, dtype=np.float32)


def render_rubberband(
    mono: np.ndarray,
    sample_rate: int,
    *,
    rate: float,
    semitones: float,
    formant: bool,
) -> np.ndarray:
    """The same move through the Rubber Band CLI, optionally preserving formants.

    One invocation carries both the stretch and the shift. ``rate`` follows
    librosa's convention (``> 1`` shortens), so the CLI's time ratio is its
    inverse. Files go through a temporary directory; the binary reads and
    writes WAV only, which is why the source is handed over as float WAV.
    """
    binary = shutil.which(_RUBBERBAND_BINARY)
    if binary is None:
        raise RuntimeError(f"the {_RUBBERBAND_BINARY} binary is not on PATH")
    with tempfile.TemporaryDirectory(prefix="stretch-ab-") as tmp:
        src = Path(tmp) / "in.wav"
        dst = Path(tmp) / "out.wav"
        sf.write(str(src), mono, sample_rate, subtype=_OUTPUT_SUBTYPE)
        args = [binary, "-q"]
        if rate != 1.0:
            args += ["-t", f"{1.0 / rate:g}"]
        if semitones != 0.0:
            args += ["-p", f"{semitones:g}"]
        if formant:
            args.append("-F")
        args += [str(src), str(dst)]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0 or not dst.exists():
            raise RuntimeError(
                f"{_RUBBERBAND_BINARY} exited {proc.returncode}: {proc.stderr.strip()}"
            )
        out, _ = sf.read(str(dst), dtype="float32")
    return np.asarray(out, dtype=np.float32).reshape(-1) if np.ndim(out) == 1 else np.asarray(out, dtype=np.float32).mean(axis=1)


def rubberband_absence() -> str | None:
    """The reason Rubber Band cannot run, or ``None`` when it can."""
    if shutil.which(_RUBBERBAND_BINARY) is None:
        return f"the {_RUBBERBAND_BINARY} binary is not on PATH — brew install rubberband"
    return None


def params_slug(*, rate: float, semitones: float) -> str:
    """The transform, spelled into the filename, so a directory of renders from
    several runs stays readable without a manifest."""
    return f"rate{rate:g}-pitch{semitones:+g}"


def render_all(
    source: Path,
    out_dir: Path,
    *,
    rate: float,
    semitones: float,
    formant: bool,
) -> tuple[float, list[BackendRender]]:
    """Render every available backend into ``out_dir`` and measure each against
    the source. Returns the source centroid and one row per backend, present or
    not — the caller prints them; nothing here decides anything."""
    if rate <= 0.0:
        raise ValueError(
            f"stretch-ab: --rate must be greater than 0 (got {rate:g}). "
            f"A rate below 1 stretches the line longer, above 1 shortens it."
        )
    if rate == 1.0 and semitones == 0.0:
        raise ValueError(
            "stretch-ab: rate 1 and 0 semitones is not a transform, so there is "
            "nothing to compare. Pass --rate and/or --semitones."
        )

    mono, sample_rate = load_mono(source)
    source_centroid = spectral_centroid_hz(mono, sample_rate)
    slug = params_slug(rate=rate, semitones=semitones)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[BackendRender] = [
        _write_render(
            "librosa",
            render_librosa(mono, sample_rate, rate=rate, semitones=semitones),
            sample_rate,
            out_dir / f"librosa-{slug}.wav",
            source_centroid,
        )
    ]

    absence = rubberband_absence()
    if absence is not None:
        rows.append(BackendRender("rubberband", absent_reason=absence))
    else:
        suffix = "-formant" if formant else ""
        rows.append(
            _write_render(
                "rubberband",
                render_rubberband(
                    mono,
                    sample_rate,
                    rate=rate,
                    semitones=semitones,
                    formant=formant,
                ),
                sample_rate,
                out_dir / f"rubberband-{slug}{suffix}.wav",
                source_centroid,
            )
        )
    return source_centroid, rows


def _write_render(
    backend: str,
    rendered: np.ndarray,
    sample_rate: int,
    path: Path,
    source_centroid: float,
) -> BackendRender:
    """Write one backend's output and measure it. The centroid is taken from the
    in-memory buffer, which is what the backend actually produced."""
    sf.write(str(path), rendered, sample_rate, subtype=_OUTPUT_SUBTYPE)
    centroid = spectral_centroid_hz(rendered, sample_rate)
    return BackendRender(
        backend=backend,
        path=path,
        centroid_hz=centroid,
        centroid_delta_hz=centroid - source_centroid,
    )


def render_table(
    source: Path,
    source_centroid: float,
    rows: list[BackendRender],
    *,
    rate: float,
    semitones: float,
) -> str:
    """The whole output: what was rendered, what it measures, and what the
    number does and does not mean."""
    lines = [
        f"stretch/pitch A/B — {source.name}",
        f"  rate {rate:g} · pitch {semitones:+g} st · "
        f"source centroid {source_centroid:.0f} Hz",
        "",
        f"  {'backend':<12}{'centroid Hz':>13}{'Δ vs source':>14}  file",
    ]
    for row in rows:
        if row.path is None or row.centroid_hz is None:
            lines.append(
                f"  {row.backend:<12}{'—':>13}{'—':>14}  "
                f"absent: {row.absent_reason}"
            )
            continue
        delta = row.centroid_delta_hz or 0.0
        lines.append(
            f"  {row.backend:<12}{row.centroid_hz:>13.0f}"
            f"{delta:>+14.0f}  {row.path.name}"
        )
    lines += [
        "",
        "  Δ hints at formant smear. A pitch shift moves the centroid by "
        "design, so",
        "  read the backends against each other, not against zero — then "
        "listen to the",
        "  files and decide. The harness has no opinion.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", type=Path, help="the WAV to transform")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("stretch-ab"),
        help="directory the renders are written to (created if absent)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="time-stretch ratio; below 1 is slower, above 1 is faster",
    )
    parser.add_argument(
        "--semitones",
        type=float,
        default=0.0,
        help="pitch shift in semitones, positive or negative",
    )
    parser.add_argument(
        "--formant",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="preserve formants in the Rubber Band render (the thing librosa "
        "cannot do, and the point of the comparison)",
    )
    args = parser.parse_args(argv)

    try:
        source_centroid, rows = render_all(
            args.source,
            args.out,
            rate=args.rate,
            semitones=args.semitones,
            formant=args.formant,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 3
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(
        render_table(
            args.source,
            source_centroid,
            rows,
            rate=args.rate,
            semitones=args.semitones,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
