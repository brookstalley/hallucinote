"""Encode the tour's committed media from real render output.

The end-to-end tour leads with the song, so its evidence has to be produced from
a real capture directory rather than exported by hand — a re-shoot after the
music changes must be a re-run of this tool, not an afternoon in an audio editor.

Two jobs:

``clip``
    A capture directory already holds per-track and master WAVs (float32, 48 kHz,
    tens of megabytes each). This takes the master, optionally bounded to a time
    range, and emits an mp3 plus a **waveform still** that links to it.

``hero``
    Post-production for the hero take: crop a two-window screen recording to the
    region worth showing, speed it up, and emit the mp4 with its poster PNG.

**Why a waveform still and not the scrolling waveform video.** GitHub's markdown
sanitizer removes the ``<video>`` element outright — relative and absolute ``src``
alike, verified against both of GitHub's own render endpoints on 2026-08-06. So
*nothing* plays inline on the repo page, and a waveform video would be a
megabytes-large download behind a click that shows a line moving. A
``showwavespic`` PNG renders inline, shows the whole arrangement's dynamics at a
glance, and costs single-digit kilobytes. It ships with a transparent background
(rgba), so one file reads correctly on both the light and dark GitHub themes.

The same finding is why ``hero`` emits a poster: the mp4 is reached by clicking
the still, because there is no form in which it plays in place.

**Sizes are reported on every run, deliberately.** This media is committed to a
repo whose history is permanent, under a total budget the docs tests enforce. A
tool that silently writes a 40 MB file is how that budget gets blown, so each
output prints its size and the run prints a total.

Requires ``ffmpeg`` and ``ffprobe`` on PATH (verified against ffmpeg 8.0.1).
Neither is needed to *consume* the results — a reader cloning the repo gets the
media as committed files.

Usage::

    python tools/make_demo_media.py clip --capture-dir songs/x/captures/<ts> \\
        --out-dir docs/assets --name full-song
    python tools/make_demo_media.py clip --capture-dir songs/x/captures/<ts> \\
        --out-dir docs/assets --name beat9-before --start 24 --end 32
    python tools/make_demo_media.py hero --source take.mov --out-dir docs/assets \\
        --name hero --crop 2560:1440:0:200 --speed 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Waveform stills are drawn on a transparent background (showwavespic outputs
# rgba), so a single file reads on both GitHub themes. The colour is GitHub's
# accent blue, which clears the contrast bar against both backgrounds.
WAVEFORM_SIZE = "1200x200"
WAVEFORM_COLOR = "0x1f6feb"

# ~1 MB/minute. High enough that the demo is not what a skeptical listener
# blames, low enough that three clips fit the committed-media budget.
DEFAULT_BITRATE = "128k"

# Hero output width. A screen recording of two 4K windows is downscaled to
# something a README can load; the crop chooses *what* is shown, this chooses
# how many pixels it costs.
DEFAULT_HERO_WIDTH = 1280
DEFAULT_HERO_SPEED = 4.0

# Clip bounds are compared against the source duration with this slack. ffprobe
# reports container duration, which can differ from the decoded stream by a
# frame or so; refusing a clip that ends at "the end" over a millisecond of
# rounding would be a false failure.
DURATION_SLACK_S = 0.05

# The encoded clip is re-probed and must match what was asked for within this.
# One mp3 frame is 1152 samples — 24 ms at 48 kHz — so the tolerance is about
# two frames; observed error on real captures is under a millisecond.
ENCODED_DURATION_SLACK_S = 0.05

# Video is compared more loosely than audio: `setpts` re-times whole frames, so
# a 4x speed-up of an 8s take lands a frame past 2s rather than exactly on it.
VIDEO_DURATION_SLACK_S = 0.25

# Kept in step with `audio/io.py`'s `_SUPPORTED_MANIFEST_SCHEMA_VERSIONS`, the
# in-`src` consumer of the same contract surface. Deliberately duplicated rather
# than imported: these tools do not import the engine, so that the doc pipeline
# does not break whenever the engine moves (see the plan's Module Boundaries).
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({"1"})


class MediaError(Exception):
    """Base class for refusals — every one of these means nothing usable was written."""


class MissingToolError(MediaError):
    """ffmpeg or ffprobe is not on PATH."""


class CaptureDirError(MediaError):
    """The capture directory is not one this tool can read a master from."""


class ClipBoundsError(MediaError):
    """A requested time extent is unusable — a clip range outside the source, or a
    speed factor that would not produce a playable duration."""


class EncodeError(MediaError):
    """An ffmpeg/ffprobe invocation failed."""


@dataclass(frozen=True)
class Output:
    """One written file, with the size that has to fit the committed budget."""

    path: Path
    size_bytes: int

    def describe(self) -> str:
        return f"{self.path} ({self.size_bytes / 1024:.0f} KB)"


def require_tools() -> None:
    """Fail before doing any work if the encoders are absent.

    Checked up front rather than at first use: discovering ffprobe is missing
    *after* a two-minute mp3 encode wastes the encode and leaves a half-built
    output set behind.
    """
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise MissingToolError(
            f"{' and '.join(missing)} not found on PATH — needed to produce the tour's "
            f"media (not to read it; committed assets need no encoder)"
        )


def run_command(argv: list[str]) -> str:
    """Run a subprocess and return stdout, raising :class:`EncodeError` on failure.

    The single subprocess boundary in this module, so tests can replace exactly
    one thing and every argv builder stays pure.
    """
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise EncodeError(f"could not run {argv[0]}: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {completed.returncode}"
        raise EncodeError(f"{argv[0]} failed: {detail}")
    return completed.stdout


def untrustworthy(manifest: dict) -> list[str]:
    """Reasons this capture must not become the tour's audio, in the producer's own terms.

    The render writes three flags for exactly one purpose — so a reader "never
    trusts an under-measured stem as if it were faithful", in its words. Honouring
    them matters more here than anywhere, because **none of the other guards can
    see this class of failure**: an incomplete render yields a *short but
    perfectly valid* master, so open bounds are derived from the truncated
    length, the post-encode duration check compares against that same derived
    number, and the mp3 plays. Every check agrees, and the tour ships a truncated
    take as its central evidence.

    Absence is not failure. Captures predating these flags omit them, and one
    such directory is what this tool was verified against — so only an explicit
    bad value refuses.
    """
    reasons = []
    status = manifest.get("status")
    if status is not None and status != "ok":
        reasons.append(f"the render reported status {status!r}, not 'ok'")

    # Listed by track_id, and the master's is the string "master".
    not_terminal = manifest.get("analyzer_not_terminal")
    if isinstance(not_terminal, list) and "master" in not_terminal:
        reasons.append(
            "the analyzer was not last in the master chain, so the WAV misses whatever "
            "sits past it — the mix would be missing its own master processing"
        )
    entry = manifest.get("master")
    if isinstance(entry, dict) and entry.get("terminal") is False:
        reasons.append("the master's analyzer tap is flagged non-terminal")
    return reasons


def master_wav(capture_dir: Path, allow_incomplete: bool = False) -> Path:
    """Locate the master WAV in a render's capture directory.

    Resolved through ``manifest.json``'s ``master.filename`` — **not** its
    ``absolute_path``, which records the authoring machine's path and is wrong
    the moment the directory is moved, copied, or read from a clone.

    Refuses a capture the manifest itself flags as untrustworthy; pass
    ``allow_incomplete`` to override deliberately (see :func:`untrustworthy`).
    """
    manifest_path = capture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise CaptureDirError(f"no manifest.json in {capture_dir} — not a capture directory")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureDirError(f"could not read {manifest_path}: {exc}") from exc

    # Gate the schema the same way the in-`src` consumer does
    # (`audio/io.py` `load_capture`). A manifest this tool cannot read correctly
    # must not be read *approximately*: the fields below are exactly the ones a
    # future version could re-shape, and reading a v2 manifest with v1
    # assumptions is how a wrong file quietly becomes the tour's audio.
    schema_version = manifest.get("schema_version")
    if schema_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise CaptureDirError(
            f"{manifest_path} has schema_version={schema_version!r}; this tool understands "
            f"{sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)} (writer: "
            f"hallucinote_mcp/.../handlers/render.py)"
        )

    entry = manifest.get("master")
    if not isinstance(entry, dict) or not entry.get("filename"):
        raise CaptureDirError(
            f"{manifest_path} has no master entry — a capture without a master mix "
            f"cannot produce the tour's audio"
        )
    if not allow_incomplete:
        reasons = untrustworthy(manifest)
        if reasons:
            raise CaptureDirError(
                f"{manifest_path} flags this capture as unfaithful: "
                + "; ".join(reasons)
                + " — re-render, or pass --allow-incomplete to publish it anyway"
            )
    wav = capture_dir / str(entry["filename"])
    if not wav.is_file():
        raise CaptureDirError(f"{wav} is listed in the manifest but does not exist")
    return wav


def probe_duration(path: Path) -> float:
    """Duration of a media file in seconds, via ffprobe."""
    out = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
    )
    try:
        return float(out.strip())
    except ValueError as exc:
        raise EncodeError(f"ffprobe reported no duration for {path}") from exc


def clip_bounds(start: float | None, end: float | None, source_duration: float) -> tuple[float, float]:
    """Validate a requested range and return ``(start, duration)``.

    Bounds are checked against the real source rather than trusted, because the
    failure this prevents is silent and does *not* look like a failure. Asked to
    seek past the end of a file, ffmpeg exits **0** with an **empty stderr** and
    writes a headers-only mp3 — 428 bytes on the capture this was measured
    against, not zero. So neither the exit code nor a file-is-non-empty check
    catches it; the range has to be rejected before the encode, and the encoded
    result re-measured after it (see :func:`_assert_encoded_duration`).
    """
    begin = 0.0 if start is None else float(start)
    finish = source_duration if end is None else float(end)
    if begin < 0:
        raise ClipBoundsError(f"start {begin}s is negative")
    if finish <= begin:
        raise ClipBoundsError(f"end {finish}s is not after start {begin}s")
    if begin >= source_duration:
        raise ClipBoundsError(
            f"start {begin}s is at or past the end of a {source_duration:.2f}s source"
        )
    if finish > source_duration + DURATION_SLACK_S:
        raise ClipBoundsError(
            f"end {finish}s is past the end of a {source_duration:.2f}s source"
        )
    return begin, min(finish, source_duration) - begin


def mp3_argv(src: Path, dst: Path, start: float, duration: float, bitrate: str) -> list[str]:
    """ffmpeg argv for a (possibly bounded) mp3 encode.

    ``-ss`` precedes ``-i`` so the seek happens on the input and costs no decode
    of the skipped audio — these masters are ~40 MB of float32.
    """
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-y",
        str(dst),
    ]


def waveform_argv(src: Path, dst: Path, size: str = WAVEFORM_SIZE, color: str = WAVEFORM_COLOR) -> list[str]:
    """ffmpeg argv for the waveform still.

    Drawn from the *encoded clip* rather than from the source WAV, so the
    picture and the audio behind it cannot disagree about where the clip starts.
    """
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-filter_complex",
        f"showwavespic=s={size}:colors={color}",
        "-frames:v",
        "1",
        "-y",
        str(dst),
    ]


def hero_argv(
    src: Path,
    dst: Path,
    crop: str | None,
    speed: float,
    width: int = DEFAULT_HERO_WIDTH,
) -> list[str]:
    """ffmpeg argv for the hero mp4: crop, speed up, scale, drop audio.

    Audio is dropped rather than sped up with the video. A screen recording at
    4× has no usable soundtrack, and the song is already presented properly as
    its own clip — a chipmunked version of it under the hero would undercut the
    one thing the tour is trying to demonstrate.
    """
    if speed <= 0:
        raise ClipBoundsError(f"speed {speed}× must be positive")
    filters = []
    if crop:
        filters.append(f"crop={crop}")
    filters.append(f"setpts=PTS/{speed:g}")
    # -2 keeps the height even, which yuv420p requires.
    filters.append(f"scale={width}:-2")
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-filter_complex",
        ",".join(filters),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        str(dst),
    ]


def poster_argv(src: Path, dst: Path, at: float) -> list[str]:
    """ffmpeg argv for the poster still pulled out of the finished mp4.

    Taken from the encoded hero, not the raw take, so the poster shows exactly
    the framing the video does — a poster cropped differently from the clip it
    fronts is a visible seam.
    """
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{at:.3f}",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-y",
        str(dst),
    ]


def _emit(dst: Path, argv: list[str]) -> Output:
    """Run an encode and confirm it produced a non-empty file.

    ffmpeg can exit 0 having written nothing usable, so the result is checked
    rather than assumed, and a failed output is *removed* — leaving it behind is
    worse than never writing it, because the next step would commit a
    plausible-looking file that plays silence.

    This is the coarse half of that check. It catches an empty file; it does not
    catch a short one, because an out-of-range seek yields a few hundred bytes of
    valid-looking mp3 header. Audio outputs get :func:`_assert_encoded_duration`
    on top for exactly that reason.
    """
    run_command(argv)
    if not dst.is_file() or dst.stat().st_size == 0:
        if dst.is_file():
            dst.unlink()
        raise EncodeError(f"{argv[0]} exited 0 but wrote no usable data to {dst}")
    return Output(dst, dst.stat().st_size)


def _assert_encoded_duration(dst: Path, expected: float) -> None:
    """Re-measure an encoded clip and refuse one that is not the length requested.

    The guarantee the tour needs is that a clip *contains* the seconds it claims
    to. Neither ffmpeg's exit code nor its file size can give that — so the
    length is measured back off the finished file, and a mismatch deletes it.
    """
    actual = probe_duration(dst)
    if abs(actual - expected) > ENCODED_DURATION_SLACK_S:
        dst.unlink(missing_ok=True)
        raise EncodeError(
            f"{dst.name} encoded to {actual:.3f}s but {expected:.3f}s was requested — "
            f"the clip does not contain the audio it claims to"
        )


@contextmanager
def _all_or_nothing(targets: list[Path]) -> Iterator[None]:
    """Make a set of outputs appear only if *every* one of them succeeded.

    Both halves matter. Stale files are cleared **before** the run, because a
    failure that leaves the previous take in place is the trap this tool feeds
    directly: the operator reads the error, fixes it, and `git add docs/assets/`
    picks up an asset that looks fresh and is not. And a partial set is cleared
    **after** a failure, because the sibling outputs of a rejected file are just
    as wrong — a waveform still fronting audio that was deleted for being the
    wrong length is worse than no waveform, since it looks like evidence.
    """
    for target in targets:
        target.unlink(missing_ok=True)
    try:
        yield
    except BaseException:
        # Every failure, not only MediaError. An unexpected exception is exactly
        # when a half-written asset is most likely to be left behind, and the
        # cost of the broad clause is nil because it re-raises rather than
        # swallowing — the caller still sees the original error.
        for target in targets:
            target.unlink(missing_ok=True)
        raise


def _assert_video_shape(path: Path, width: int, expected_duration: float | None) -> None:
    """Re-measure an encoded video against what was asked for.

    The visual outputs promise checkable post-conditions — a fixed width, a
    duration implied by the speed-up — and ffmpeg's exit code proves neither.
    Measuring them is the same discipline :func:`_assert_encoded_duration`
    applies to audio, and the reason is identical: the file is committed to a
    permanent history, so "it encoded" is not the same claim as "it is right".
    """
    reported = run_command(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width", "-of", "default=nw=1:nk=1", str(path)]
    ).strip()
    try:
        actual_width = int(reported or 0)
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise EncodeError(f"ffprobe reported no usable width for {path.name}") from exc
    if actual_width != width:
        path.unlink(missing_ok=True)
        raise EncodeError(f"{path.name} encoded {actual_width}px wide but {width}px was requested")
    if expected_duration is not None:
        actual = probe_duration(path)
        if abs(actual - expected_duration) > VIDEO_DURATION_SLACK_S:
            path.unlink(missing_ok=True)
            raise EncodeError(
                f"{path.name} encoded to {actual:.3f}s but the crop and {expected_duration:.3f}s "
                f"speed-up implied a different length"
            )


def make_clip(
    capture_dir: Path,
    out_dir: Path,
    name: str,
    start: float | None = None,
    end: float | None = None,
    bitrate: str = DEFAULT_BITRATE,
    allow_incomplete: bool = False,
) -> list[Output]:
    """Master WAV → ``<name>.mp3`` plus ``<name>.png``, its inline waveform."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / f"{name}.mp3"
    png = out_dir / f"{name}.png"
    # Opened BEFORE the manifest and bounds are resolved, not after: a refusal
    # there is still a failed run, and leaving the previous take at these paths
    # is the same `git add docs/assets/` trap as leaving a partial one.
    with _all_or_nothing([mp3, png]):
        src = master_wav(capture_dir, allow_incomplete)
        begin, duration = clip_bounds(start, end, probe_duration(src))
        outputs = [_emit(mp3, mp3_argv(src, mp3, begin, duration, bitrate))]
        _assert_encoded_duration(mp3, duration)
        outputs.append(_emit(png, waveform_argv(mp3, png)))
    return outputs


def make_hero(
    source: Path,
    out_dir: Path,
    name: str,
    crop: str | None = None,
    speed: float = DEFAULT_HERO_SPEED,
    width: int = DEFAULT_HERO_WIDTH,
    poster_at: float = 0.0,
) -> list[Output]:
    """Screen recording → ``<name>.mp4`` plus ``<name>.png``, the poster that links to it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"{name}.mp4"
    png = out_dir / f"{name}.png"
    with _all_or_nothing([mp4, png]):
        if not source.is_file():
            raise MediaError(f"{source} does not exist")
        expected = probe_duration(source) / speed if speed > 0 else None
        outputs = [_emit(mp4, hero_argv(source, mp4, crop, speed, width))]
        _assert_video_shape(mp4, width, expected)
        outputs.append(_emit(png, poster_argv(mp4, png, poster_at)))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    clip = sub.add_parser("clip", help="capture directory → mp3 + waveform still")
    clip.add_argument("--capture-dir", type=Path, required=True, help="a songs/<slug>/captures/<ts> dir")
    clip.add_argument("--out-dir", type=Path, required=True)
    clip.add_argument("--name", required=True, help="basename for the .mp3 and .png")
    clip.add_argument("--start", type=float, help="clip start in seconds (default: 0)")
    clip.add_argument("--end", type=float, help="clip end in seconds (default: end of source)")
    clip.add_argument("--bitrate", default=DEFAULT_BITRATE)
    clip.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="publish even if the manifest flags the render as incomplete or under-tapped",
    )

    hero = sub.add_parser("hero", help="screen recording → mp4 + poster still")
    hero.add_argument("--source", type=Path, required=True, help="the raw screen-recording take")
    hero.add_argument("--out-dir", type=Path, required=True)
    hero.add_argument("--name", required=True, help="basename for the .mp4 and .png")
    hero.add_argument("--crop", help="ffmpeg crop geometry, W:H:X:Y")
    hero.add_argument("--speed", type=float, default=DEFAULT_HERO_SPEED)
    hero.add_argument("--width", type=int, default=DEFAULT_HERO_WIDTH)
    hero.add_argument("--poster-at", type=float, default=0.0, help="poster frame time, in output seconds")

    args = parser.parse_args(argv)
    try:
        require_tools()
        if args.command == "clip":
            outputs = make_clip(
                args.capture_dir,
                args.out_dir,
                args.name,
                args.start,
                args.end,
                args.bitrate,
                args.allow_incomplete,
            )
        else:
            outputs = make_hero(
                args.source, args.out_dir, args.name, args.crop, args.speed, args.width, args.poster_at
            )
    except MediaError as exc:
        print(f"make_demo_media: {exc}", file=sys.stderr)
        return 1

    for output in outputs:
        print(f"wrote {output.describe()}", file=sys.stderr)
    total = sum(o.size_bytes for o in outputs)
    print(f"total {total / 1024:.0f} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
