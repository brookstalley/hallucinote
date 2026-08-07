"""Tests for the deterministic Ableton Live screenshot tool.

Two properties carry the weight. **Never photograph the wrong window** — Live
opens plug-in editors and Preferences alongside its main window, and a capture
that silently picks one of them commits a wrong screenshot that nobody notices
until a reader does. And **never leave an unusable file on disk**, because an
empty PNG in `docs/assets/` renders as a broken image in the published tour.

The window server and the two macOS binaries are faked. What is *not* faked is
the shape of the window-list entries: the fixtures below mirror the real
``CGWindowListCopyWindowInfo`` output — including the nested ``kCGWindowBounds``
dict and the float values it really contains — because a parser tested against a
tidied-up shape passes while failing on the real one.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from tools.capture_live_shot import (
    DEFAULT_OWNER,
    DEFAULT_WIDTH,
    AmbiguousWindowError,
    CaptureError,
    CaptureFailed,
    NoWindowError,
    ScreenRecordingDenied,
    UnsupportedPlatformError,
    Window,
    _run_capturing,
    assert_capture_permission,
    capture,
    find_window,
    main,
    on_screen_windows,
    require_macos,
    resample_argv,
    screencapture_argv,
)


def window_entry(
    window_id: int,
    owner: str = DEFAULT_OWNER,
    layer: int = 0,
    width: float = 1576.0,
    height: float = 949.0,
) -> dict:
    """One entry shaped exactly like the window server's, floats included."""
    return {
        "kCGWindowNumber": window_id,
        "kCGWindowOwnerName": owner,
        "kCGWindowLayer": layer,
        "kCGWindowBounds": {"X": 273.0, "Y": 107.0, "Width": width, "Height": height},
    }


# --- choosing a window -------------------------------------------------------


def test_find_window_returns_the_single_normal_live_window() -> None:
    found = find_window([window_entry(56749)], DEFAULT_OWNER)
    assert found == Window(window_id=56749, owner="Live", width=1576, height=949)


def test_find_window_ignores_windows_owned_by_other_applications() -> None:
    windows = [window_entry(11, owner="Code"), window_entry(56749)]
    assert find_window(windows, DEFAULT_OWNER).window_id == 56749


def test_find_window_ignores_menus_and_overlays_above_the_normal_layer() -> None:
    """A dropdown open over Live must not become the screenshot."""
    windows = [window_entry(999, layer=8, width=200, height=90), window_entry(56749)]
    assert find_window(windows, DEFAULT_OWNER).window_id == 56749


def test_find_window_errors_when_live_has_no_window() -> None:
    with pytest.raises(NoWindowError, match="is Live running"):
        find_window([window_entry(11, owner="Code")], DEFAULT_OWNER)


def test_find_window_refuses_to_guess_between_two_live_windows() -> None:
    """A plug-in editor beside the main window is a refusal, not a coin flip."""
    windows = [window_entry(56749), window_entry(56800, width=600.0, height=400.0)]
    with pytest.raises(AmbiguousWindowError) as excinfo:
        find_window(windows, DEFAULT_OWNER)
    message = str(excinfo.value)
    assert "56749" in message and "56800" in message
    assert "600x400" in message, "the listing must be usable to pick --window-id"


def test_find_window_truncates_float_bounds_to_whole_pixels() -> None:
    found = find_window([window_entry(1, width=1576.7, height=948.2)], DEFAULT_OWNER)
    assert (found.width, found.height) == (1576, 948)


def test_on_screen_windows_parses_the_window_server_plist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = plistlib.dumps([window_entry(56749), window_entry(11, owner="Code")])
    monkeypatch.setattr("tools.capture_live_shot._window_list_plist", lambda: payload)
    entries = on_screen_windows()
    assert [e["kCGWindowNumber"] for e in entries] == [56749, 11]


# --- argv --------------------------------------------------------------------


def test_screencapture_argv_targets_one_window_without_its_shadow() -> None:
    argv = screencapture_argv(56749, Path("shot.png"))
    assert argv[argv.index("-l") + 1] == "56749"
    assert "-o" in argv, "the drop shadow would frame the window in a grey halo"
    assert "-x" in argv
    assert argv[-1] == "shot.png"


def test_resample_argv_pins_the_width_which_is_the_determinism_promised() -> None:
    argv = resample_argv(Path("shot.png"), 1600)
    assert argv[argv.index("--resampleWidth") + 1] == "1600"
    assert argv[argv.index("--out") + 1] == "shot.png"


def test_require_macos_rejects_other_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.capture_live_shot.sys.platform", "linux")
    with pytest.raises(UnsupportedPlatformError, match="linux"):
        require_macos()


# --- permission --------------------------------------------------------------


class FakeCoreGraphics:
    def __init__(self, granted: bool):
        self._granted = granted
        self.CGPreflightScreenCaptureAccess = _Preflight(granted)


class _Preflight:
    def __init__(self, granted: bool):
        self._granted = granted
        self.restype = None

    def __call__(self) -> bool:
        return self._granted


def _patch_preflight(monkeypatch: pytest.MonkeyPatch, granted: bool) -> None:
    monkeypatch.setattr(
        "tools.capture_live_shot.ctypes.util.find_library", lambda name: f"/fake/{name}"
    )
    monkeypatch.setattr(
        "tools.capture_live_shot.ctypes.cdll.LoadLibrary", lambda path: FakeCoreGraphics(granted)
    )


def test_assert_capture_permission_passes_when_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_preflight(monkeypatch, True)
    assert_capture_permission()


def test_assert_capture_permission_names_the_app_and_the_settings_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real failure reads like a bad window id, so this error must not."""
    _patch_preflight(monkeypatch, False)
    monkeypatch.setattr("tools.capture_live_shot._host_app_hint", lambda: "Some Terminal.app")
    with pytest.raises(ScreenRecordingDenied) as excinfo:
        assert_capture_permission()
    message = str(excinfo.value)
    assert "Some Terminal.app" in message
    assert "Screen Recording" in message
    assert "restart" in message, "the grant does not take effect until relaunch"


# --- the capture pipeline ----------------------------------------------------


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake every side effect and record the order they happen in."""
    events: list[str] = []
    monkeypatch.setattr("tools.capture_live_shot.require_macos", lambda: None)
    monkeypatch.setattr("tools.capture_live_shot.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "tools.capture_live_shot.assert_capture_permission", lambda: events.append("permission")
    )
    monkeypatch.setattr(
        "tools.capture_live_shot.raise_app", lambda app: events.append(f"raise:{app}")
    )
    monkeypatch.setattr("tools.capture_live_shot.time.sleep", lambda s: events.append(f"settle:{s}"))
    monkeypatch.setattr(
        "tools.capture_live_shot.on_screen_windows", lambda: [window_entry(56749)]
    )

    # `_run_capturing` is the single subprocess seam — `_run` delegates to it —
    # so patching this one name routes every external call through the fake.
    def fake_run(argv: list[str]) -> str:
        events.append(argv[0])
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"\x89PNG" + b"\x00" * 64)
        if argv[0] == "sips" and "-g" in argv:
            return f"{argv[-1]}\n  pixelWidth: {DEFAULT_WIDTH}\n"
        return ""

    monkeypatch.setattr("tools.capture_live_shot._run_capturing", fake_run)
    return events


def test_capture_writes_a_downscaled_shot_of_the_resolved_window(
    tmp_path: Path, pipeline: list[str]
) -> None:
    out = tmp_path / "shots" / "session.png"
    window = capture(out)
    assert window is not None and window.window_id == 56749
    assert out.is_file() and out.stat().st_size > 0
    assert "screencapture" in pipeline and "sips" in pipeline


def test_capture_checks_permission_before_raising_anything(
    tmp_path: Path, pipeline: list[str]
) -> None:
    """Raising Live steals focus; doing that only to fail on permission is rude."""
    capture(tmp_path / "shot.png")
    assert pipeline.index("permission") < pipeline.index(f"raise:{'Ableton Live 12 Suite'}")


def test_capture_downscales_after_capturing_not_before(
    tmp_path: Path, pipeline: list[str]
) -> None:
    capture(tmp_path / "shot.png")
    assert pipeline.index("screencapture") < pipeline.index("sips")


def test_capture_settles_after_raising_because_open_returns_early(
    tmp_path: Path, pipeline: list[str]
) -> None:
    capture(tmp_path / "shot.png", settle=2.0)
    assert pipeline.index("raise:Ableton Live 12 Suite") < pipeline.index("settle:2.0")
    assert pipeline.index("settle:2.0") < pipeline.index("screencapture")


def test_capture_with_no_raise_leaves_the_front_window_alone(
    tmp_path: Path, pipeline: list[str]
) -> None:
    capture(tmp_path / "shot.png", raise_first=False)
    assert not any(event.startswith("raise:") for event in pipeline)
    assert "screencapture" in pipeline


def test_capture_with_an_explicit_window_id_skips_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    """--window-id is the escape hatch when two Live windows are legitimately open."""

    def explode() -> list[dict]:  # pragma: no cover - must never run
        raise AssertionError("resolution ran despite an explicit window id")

    monkeypatch.setattr("tools.capture_live_shot.on_screen_windows", explode)
    assert capture(tmp_path / "shot.png", window_id=4242) is None


def test_capture_removes_an_empty_png_rather_than_leaving_it_to_be_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    out = tmp_path / "shot.png"

    def writes_nothing(argv: list[str]) -> str:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"")
        return ""

    monkeypatch.setattr("tools.capture_live_shot._run_capturing", writes_nothing)
    with pytest.raises(CaptureFailed, match="wrote no image"):
        capture(out)
    assert not out.exists()


def test_capture_errors_when_a_required_binary_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    monkeypatch.setattr("tools.capture_live_shot.shutil.which", lambda name: None)
    with pytest.raises(CaptureError, match="screencapture not found"):
        capture(tmp_path / "shot.png")


def test_capture_propagates_an_ambiguous_window_without_capturing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    monkeypatch.setattr(
        "tools.capture_live_shot.on_screen_windows",
        lambda: [window_entry(1), window_entry(2)],
    )
    with pytest.raises(AmbiguousWindowError):
        capture(tmp_path / "shot.png")
    assert "screencapture" not in pipeline


# --- CLI ---------------------------------------------------------------------


def test_main_writes_and_reports(
    tmp_path: Path, pipeline: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "shot.png"
    assert main(["--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert str(out) in err and str(DEFAULT_WIDTH) in err and "56749" in err


def test_main_list_prints_candidates_and_captures_nothing(
    monkeypatch: pytest.MonkeyPatch, pipeline: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "tools.capture_live_shot.on_screen_windows",
        lambda: [window_entry(56749), window_entry(11, owner="Code")],
    )
    assert main(["--list"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["id 56749 layer 0 1576x949"], "only the requested owner is listed"
    assert "screencapture" not in pipeline


def test_main_requires_an_output_path_unless_listing(pipeline: list[str]) -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_reports_a_refusal_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("tools.capture_live_shot.on_screen_windows", lambda: [])
    assert main(["--out", str(tmp_path / "shot.png")]) == 1
    assert "is Live running" in capsys.readouterr().err


# --- outputs are all-or-nothing ----------------------------------------------


def test_capture_removes_a_previous_take_when_the_capture_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    """A failed re-shoot must not leave the old image looking fresh for `git add`."""
    out = tmp_path / "shot.png"
    out.write_bytes(b"previous take")

    def failing(argv: list[str]) -> str:
        if argv[0] == "screencapture":
            raise CaptureFailed("screencapture failed: could not create image from window")
        return ""

    monkeypatch.setattr("tools.capture_live_shot._run_capturing", failing)
    with pytest.raises(CaptureFailed):
        capture(out)
    assert not out.exists()


def test_capture_removes_the_full_size_image_when_the_downscale_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    """A captured-but-undownscaled PNG is valid and silently violates the fixed width."""
    out = tmp_path / "shot.png"

    def failing(argv: list[str]) -> str:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"\x89PNG" + b"\x00" * 64)
            return ""
        raise CaptureFailed("sips failed")

    monkeypatch.setattr("tools.capture_live_shot._run_capturing", failing)
    with pytest.raises(CaptureFailed):
        capture(out)
    assert not out.exists()


def test_capture_refuses_an_image_that_is_not_the_requested_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: list[str]
) -> None:
    """sips exiting 0 does not establish the width, which is the whole promise."""
    out = tmp_path / "shot.png"

    def wrong_width(argv: list[str]) -> str:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"\x89PNG" + b"\x00" * 64)
        if argv[0] == "sips" and "-g" in argv:
            return f"{argv[-1]}\n  pixelWidth: 900\n"
        return ""

    monkeypatch.setattr("tools.capture_live_shot._run_capturing", wrong_width)
    with pytest.raises(CaptureFailed, match="900px wide but 1600px was requested"):
        capture(out)
    assert not out.exists()


# --- the subprocess seam itself ----------------------------------------------


def test_run_capturing_returns_stdout_from_a_real_process() -> None:
    assert _run_capturing(["echo", "hello"]).strip() == "hello"


def test_run_capturing_raises_with_the_tool_name_on_a_real_failure() -> None:
    with pytest.raises(CaptureFailed, match="false failed"):
        _run_capturing(["false"])


def test_run_capturing_raises_when_the_binary_does_not_exist() -> None:
    with pytest.raises(CaptureFailed, match="could not run"):
        _run_capturing(["definitely-not-a-real-binary-xyz"])
