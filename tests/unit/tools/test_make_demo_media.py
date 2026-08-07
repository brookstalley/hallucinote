"""Tests for the tour's media encoder.

The contract under test is that nothing unusable or unbudgeted gets written. Two
failure modes drive most of these: ffmpeg exits 0 while writing a zero-length
file (an out-of-range seek), and a capture directory's ``manifest.json`` records
the *authoring machine's* absolute paths, which are wrong everywhere else. Both
produce plausible-looking output rather than an error, so both are asserted
against directly.

The subprocess boundary is faked at ``run_command`` — the single place the module
shells out — which keeps every argv builder pure and testable without ffmpeg.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.make_demo_media import (
    DEFAULT_BITRATE,
    CaptureDirError,
    ClipBoundsError,
    EncodeError,
    MediaError,
    MissingToolError,
    Output,
    _assert_encoded_duration,
    _emit,
    clip_bounds,
    hero_argv,
    main,
    make_clip,
    make_hero,
    master_wav,
    mp3_argv,
    poster_argv,
    probe_duration,
    require_tools,
    waveform_argv,
)

SOURCE_DURATION = 100.949333


@pytest.fixture
def capture_dir(tmp_path: Path) -> Path:
    """A capture directory shaped like a real one, including the stale absolute path.

    ``absolute_path`` deliberately points at a directory that does not exist:
    that is exactly what a real manifest carries once the capture is read from
    anywhere but the machine that produced it, and a tool that trusted it would
    pass this fixture only by accident.
    """
    directory = tmp_path / "captures" / "20260607T035338Z"
    directory.mkdir(parents=True)
    (directory / "master.wav").write_bytes(b"RIFF....WAVE")
    (directory / "track-01-Drums.wav").write_bytes(b"RIFF....WAVE")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "song_slug": "demo",
                "tracks": [{"track_id": "track:1", "filename": "track-01-Drums.wav"}],
                "master": {
                    "track_id": "master",
                    "surface_name": "Main",
                    "filename": "master.wav",
                    "absolute_path": "/nonexistent/elsewhere/master.wav",
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


class FakeRunner:
    """Records argv and materialises the output files ffmpeg would have written.

    An encode that passed ``-t`` is remembered as producing exactly that many
    seconds, so ffprobe of its output answers honestly. Without that the
    encoded-duration check would be testing the fake rather than the code.
    """

    def __init__(self, duration: float = SOURCE_DURATION, write_bytes: bytes = b"\x00" * 64):
        self.calls: list[list[str]] = []
        self.duration = duration
        self.write_bytes = write_bytes
        self.encoded: dict[str, float] = {}

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        if argv[0] == "ffprobe":
            return f"{self.encoded.get(argv[-1], self.duration)}\n"
        if "-t" in argv:
            self.encoded[argv[-1]] = float(argv[argv.index("-t") + 1])
        Path(argv[-1]).write_bytes(self.write_bytes)
        return ""

    def argv_for(self, suffix: str) -> list[str]:
        """The *encode* that produced ``suffix`` — never the ffprobe that read it back."""
        matching = [c for c in self.calls if c[0] == "ffmpeg" and c[-1].endswith(suffix)]
        assert matching, f"no encode wrote a {suffix} (calls: {self.calls})"
        return matching[-1]


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr("tools.make_demo_media.run_command", fake)
    monkeypatch.setattr("tools.make_demo_media.shutil.which", lambda name: f"/usr/bin/{name}")
    return fake


# --- locating the master -----------------------------------------------------


def test_master_wav_resolves_through_the_directory_not_the_manifests_absolute_path(
    capture_dir: Path,
) -> None:
    """The manifest's absolute_path is the authoring machine's and goes stale."""
    resolved = master_wav(capture_dir)
    assert resolved == capture_dir / "master.wav"
    assert resolved.is_file()


def test_master_wav_rejects_a_directory_with_no_manifest(tmp_path: Path) -> None:
    with pytest.raises(CaptureDirError, match="not a capture directory"):
        master_wav(tmp_path)


def test_master_wav_rejects_a_manifest_with_no_master_entry(capture_dir: Path) -> None:
    manifest = capture_dir / "manifest.json"
    data = json.loads(manifest.read_text())
    del data["master"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CaptureDirError, match="no master entry"):
        master_wav(capture_dir)


def test_master_wav_rejects_a_manifest_naming_a_file_that_is_gone(capture_dir: Path) -> None:
    """The listed WAV missing is the case that would otherwise encode nothing."""
    (capture_dir / "master.wav").unlink()
    with pytest.raises(CaptureDirError, match="does not exist"):
        master_wav(capture_dir)


def test_master_wav_rejects_unreadable_json(capture_dir: Path) -> None:
    (capture_dir / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CaptureDirError, match="could not read"):
        master_wav(capture_dir)


# --- clip arithmetic ---------------------------------------------------------


def test_clip_bounds_defaults_to_the_whole_source() -> None:
    assert clip_bounds(None, None, 100.0) == (0.0, 100.0)


def test_clip_bounds_returns_start_and_duration_not_start_and_end() -> None:
    """ffmpeg's -t takes a duration; passing an end time silently over-runs."""
    assert clip_bounds(24.0, 32.0, 100.0) == (24.0, 8.0)


def test_clip_bounds_open_end_runs_to_the_end_of_the_source() -> None:
    assert clip_bounds(90.0, None, 100.0) == (90.0, 10.0)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (-1.0, 10.0, "negative"),
        (10.0, 10.0, "not after"),
        (10.0, 5.0, "not after"),
        (100.0, 120.0, "at or past the end"),
        (0.0, 200.0, "past the end"),
    ],
)
def test_clip_bounds_rejects_a_range_outside_the_source(
    start: float, end: float, message: str
) -> None:
    with pytest.raises(ClipBoundsError, match=message):
        clip_bounds(start, end, 100.0)


def test_clip_bounds_tolerates_an_end_a_hair_past_the_probed_duration() -> None:
    """Container duration and decoded length differ by ~a frame; that is not an error."""
    start, duration = clip_bounds(0.0, 100.02, 100.0)
    assert (start, duration) == (0.0, 100.0)


# --- argv construction -------------------------------------------------------


def test_mp3_argv_seeks_before_the_input_so_skipped_audio_is_never_decoded() -> None:
    argv = mp3_argv(Path("in.wav"), Path("out.mp3"), 24.0, 8.0, "128k")
    assert argv.index("-ss") < argv.index("-i")
    assert argv[argv.index("-t") + 1] == "8.000"
    assert argv[argv.index("-b:a") + 1] == "128k"
    assert argv[-1] == "out.mp3"


def test_waveform_argv_draws_a_single_transparent_still() -> None:
    argv = waveform_argv(Path("in.mp3"), Path("out.png"))
    filters = argv[argv.index("-filter_complex") + 1]
    assert filters.startswith("showwavespic=")
    assert argv[argv.index("-frames:v") + 1] == "1"


def test_hero_argv_crops_then_speeds_then_scales() -> None:
    """Order matters: cropping after the scale would crop the wrong region."""
    argv = hero_argv(Path("take.mov"), Path("hero.mp4"), "2560:1440:0:200", 4.0, 1280)
    filters = argv[argv.index("-filter_complex") + 1].split(",")
    assert filters == ["crop=2560:1440:0:200", "setpts=PTS/4", "scale=1280:-2"]


def test_hero_argv_omits_the_crop_filter_when_no_crop_is_requested() -> None:
    argv = hero_argv(Path("take.mov"), Path("hero.mp4"), None, 2.0)
    filters = argv[argv.index("-filter_complex") + 1].split(",")
    assert filters == ["setpts=PTS/2", "scale=1280:-2"]


def test_hero_argv_drops_audio() -> None:
    """A 4x screen recording has no usable soundtrack; the song ships as its own clip."""
    assert "-an" in hero_argv(Path("take.mov"), Path("hero.mp4"), None, 4.0)


def test_hero_argv_rejects_a_non_positive_speed() -> None:
    with pytest.raises(ClipBoundsError, match="must be positive"):
        hero_argv(Path("take.mov"), Path("hero.mp4"), None, 0.0)


def test_poster_argv_pulls_one_frame_at_the_requested_time() -> None:
    argv = poster_argv(Path("hero.mp4"), Path("hero.png"), 1.5)
    assert argv[argv.index("-ss") + 1] == "1.500"
    assert argv[argv.index("-frames:v") + 1] == "1"


# --- the zero-length trap ----------------------------------------------------


def test_emit_rejects_and_removes_a_zero_length_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg exits 0 on an out-of-range seek, writing an empty, committable file."""
    dst = tmp_path / "empty.mp3"

    def write_nothing(argv: list[str]) -> str:
        Path(argv[-1]).write_bytes(b"")
        return ""

    monkeypatch.setattr("tools.make_demo_media.run_command", write_nothing)
    with pytest.raises(EncodeError, match="no usable data"):
        _emit(dst, ["ffmpeg", str(dst)])
    assert not dst.exists(), "an empty output must not be left behind to be committed"


def test_emit_accepts_a_short_file_which_is_why_the_duration_check_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An out-of-range seek yields ~428 bytes of valid mp3 header, not zero.

    Pinning that here so the size check is never mistaken for the guard against
    a truncated clip — it is not, and cannot be.
    """
    dst = tmp_path / "headers-only.mp3"
    monkeypatch.setattr(
        "tools.make_demo_media.run_command", lambda argv: Path(argv[-1]).write_bytes(b"\xff" * 428)
    )
    assert _emit(dst, ["ffmpeg", str(dst)]).size_bytes == 428


def test_assert_encoded_duration_deletes_a_clip_shorter_than_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dst = tmp_path / "short.mp3"
    dst.write_bytes(b"\xff" * 428)
    monkeypatch.setattr("tools.make_demo_media.run_command", lambda argv: "0.05\n")
    with pytest.raises(EncodeError, match="does not contain the audio it claims to"):
        _assert_encoded_duration(dst, 8.0)
    assert not dst.exists()


def test_assert_encoded_duration_tolerates_sub_frame_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real encodes land within a millisecond; the tolerance must not be brittle."""
    dst = tmp_path / "ok.mp3"
    dst.write_bytes(b"\xff" * 4096)
    monkeypatch.setattr("tools.make_demo_media.run_command", lambda argv: "7.999\n")
    _assert_encoded_duration(dst, 8.0)
    assert dst.exists()


def test_make_clip_refuses_and_removes_a_clip_that_encoded_short(
    capture_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the guarantee is that a shipped clip contains its seconds."""
    fake = FakeRunner()

    def truncating(argv: list[str]) -> str:
        if argv[0] == "ffprobe" and argv[-1].endswith(".mp3"):
            return "0.05\n"
        return fake(argv)

    monkeypatch.setattr("tools.make_demo_media.run_command", truncating)
    with pytest.raises(EncodeError):
        make_clip(capture_dir, tmp_path / "assets", "truncated", start=24.0, end=32.0)
    assert not (tmp_path / "assets" / "truncated.mp3").exists()
    assert not (tmp_path / "assets" / "truncated.png").exists(), (
        "a waveform must never be drawn for a clip that was rejected"
    )


def test_emit_returns_the_size_that_the_media_budget_is_measured_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dst = tmp_path / "clip.mp3"
    monkeypatch.setattr(
        "tools.make_demo_media.run_command", lambda argv: Path(argv[-1]).write_bytes(b"x" * 2048)
    )
    output = _emit(dst, ["ffmpeg", str(dst)])
    assert output == Output(dst, 2048)
    assert "2 KB" in output.describe()


# --- the two pipelines -------------------------------------------------------


def test_make_clip_writes_an_mp3_and_its_waveform(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    outputs = make_clip(capture_dir, tmp_path / "assets", "full-song")
    assert [o.path.name for o in outputs] == ["full-song.mp3", "full-song.png"]
    assert all(o.size_bytes > 0 for o in outputs)
    assert all(o.path.is_file() for o in outputs)


def test_make_clip_draws_the_waveform_from_the_encoded_clip_not_the_source_wav(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    """Otherwise a bounded clip's picture shows the whole song it was cut from."""
    make_clip(capture_dir, tmp_path / "assets", "beat9-before", start=24.0, end=32.0)
    waveform = runner.argv_for(".png")
    assert waveform[waveform.index("-i") + 1].endswith("beat9-before.mp3")


def test_make_clip_passes_the_requested_bounds_through_to_ffmpeg(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    make_clip(capture_dir, tmp_path / "assets", "beat9-after", start=24.0, end=32.0)
    mp3 = runner.argv_for(".mp3")
    assert mp3[mp3.index("-ss") + 1] == "24.000"
    assert mp3[mp3.index("-t") + 1] == "8.000"


def test_make_clip_refuses_a_range_past_the_end_of_the_real_source(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    """The bounds are checked against the probed duration, not against the request."""
    with pytest.raises(ClipBoundsError):
        make_clip(capture_dir, tmp_path / "assets", "too-long", start=0.0, end=500.0)
    assert not (tmp_path / "assets" / "too-long.mp3").exists()


def test_make_clip_creates_the_output_directory(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    out = tmp_path / "deep" / "assets"
    make_clip(capture_dir, out, "full-song")
    assert out.is_dir()


def test_make_hero_writes_an_mp4_and_a_poster_taken_from_it(
    tmp_path: Path, runner: FakeRunner
) -> None:
    """The poster comes from the encoded mp4, so its framing cannot disagree."""
    source = tmp_path / "take.mov"
    source.write_bytes(b"\x00" * 16)
    outputs = make_hero(source, tmp_path / "assets", "hero", crop="100:100:0:0")
    assert [o.path.name for o in outputs] == ["hero.mp4", "hero.png"]
    poster = runner.argv_for(".png")
    assert poster[poster.index("-i") + 1].endswith("hero.mp4")


def test_make_hero_rejects_a_missing_source(tmp_path: Path, runner: FakeRunner) -> None:
    with pytest.raises(MediaError, match="does not exist"):
        make_hero(tmp_path / "nope.mov", tmp_path / "assets", "hero")


def test_probe_duration_reads_ffprobes_number(runner: FakeRunner) -> None:
    assert probe_duration(Path("x.wav")) == pytest.approx(SOURCE_DURATION)


def test_probe_duration_errors_when_ffprobe_returns_nothing_parseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tools.make_demo_media.run_command", lambda argv: "N/A\n")
    with pytest.raises(EncodeError, match="no duration"):
        probe_duration(Path("x.wav"))


# --- CLI ---------------------------------------------------------------------


def test_require_tools_names_every_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.make_demo_media.shutil.which", lambda name: None)
    with pytest.raises(MissingToolError, match="ffmpeg and ffprobe"):
        require_tools()


def test_require_tools_passes_when_both_are_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.make_demo_media.shutil.which", lambda name: f"/usr/bin/{name}")
    require_tools()


def test_main_clip_succeeds_and_reports_sizes(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "clip",
            "--capture-dir",
            str(capture_dir),
            "--out-dir",
            str(tmp_path / "assets"),
            "--name",
            "full-song",
        ]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "full-song.mp3" in err and "full-song.png" in err
    assert "total" in err


def test_main_defaults_the_bitrate_to_the_documented_one(
    capture_dir: Path, tmp_path: Path, runner: FakeRunner
) -> None:
    main(
        ["clip", "--capture-dir", str(capture_dir), "--out-dir", str(tmp_path), "--name", "x"]
    )
    mp3 = runner.argv_for(".mp3")
    assert mp3[mp3.index("-b:a") + 1] == DEFAULT_BITRATE


def test_main_returns_one_and_explains_rather_than_tracebacking(
    tmp_path: Path, runner: FakeRunner, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["clip", "--capture-dir", str(tmp_path), "--out-dir", str(tmp_path), "--name", "x"]
    )
    assert code == 1
    assert "not a capture directory" in capsys.readouterr().err


def test_main_reports_a_missing_encoder_before_doing_any_work(
    capture_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("tools.make_demo_media.shutil.which", lambda name: None)

    def explode(argv: list[str]) -> str:  # pragma: no cover - must never run
        raise AssertionError("encoding started despite a missing encoder")

    monkeypatch.setattr("tools.make_demo_media.run_command", explode)
    code = main(
        [
            "clip",
            "--capture-dir",
            str(capture_dir),
            "--out-dir",
            str(tmp_path),
            "--name",
            "x",
        ]
    )
    assert code == 1
    assert "not found on PATH" in capsys.readouterr().err
