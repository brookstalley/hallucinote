"""Capture a deterministic screenshot of the Ableton Live window.

The tour spends a hard budget of four screenshots, and every one of them is a
maintenance liability: a Live UI change, a theme change, or a differently-sized
window means re-shooting. That is only sustainable if a re-shoot is one command
rather than a manual re-composition, so this tool raises Live, captures its
window alone, and downscales to a fixed width — same framing, same width, every
time.

macOS-only. That is sufficient: it exists to produce assets that are committed to
the repo, and a reader consuming them needs nothing.

**Live has no accessibility windows, so the obvious approach does not work.**
Asking System Events for ``window 1 of process "Live"`` fails with *Invalid
index* — ``count of windows`` is ``0`` and the ``AXWindows`` attribute is empty,
because Live draws its interface on a custom surface rather than as standard
AX windows. Live's *own* AppleScript dictionary is no better: ``id of window 1``
never returns a value — it blocks for **120 seconds** and then fails with an
AppleEvent timeout (error ``-1712``), measured twice against a running Live.
Both dead ends were probed against real Live, so neither is worth re-trying, and
an approach that stalls two minutes before failing belongs nowhere near a tool
meant to make re-shooting cheap.

What does work is the window server's own list. :func:`on_screen_windows` calls
``CGWindowListCopyWindowInfo`` through ``ctypes`` — no PyObjC, no compiled
helper, nothing added to the dependency set — and serialises the result through
``CFPropertyListCreateData`` so the answer arrives as a plist that
:mod:`plistlib` can parse. Accessibility is not involved, which is exactly why it
works here.

Live is raised with ``open -a`` rather than ``osascript … activate``: both work,
but ``open`` returns in ~0.1 s against AppleScript's ~2 s, and AppleScript talks
to the same AppleEvent interface that hangs for a minute on other queries.

**Screen Recording permission is required**, and its absence does not look like a
permission problem — ``screencapture`` prints "could not create image from
window" and exits 1, and window *names* silently read as ``None``. So the
permission is preflighted and reported as itself, before anything is raised or
captured.

Usage::

    python tools/capture_live_shot.py --out docs/assets/session-view.png
    python tools/capture_live_shot.py --out shot.png --width 1200 --settle 2
    python tools/capture_live_shot.py --list
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# The .app to raise, and the window-server owner name it reports. They differ:
# the bundle is version-stamped ("Ableton Live 12 Suite"), the process is not
# ("Live"), so a single name cannot serve both and both are configurable.
DEFAULT_APP = "Ableton Live 12 Suite"
DEFAULT_OWNER = "Live"

# Committed screenshots are downscaled to this width. Fixed width is the
# determinism the tour needs — height follows the window's aspect ratio, because
# forcing that too would distort the UI being documented.
DEFAULT_WIDTH = 1600

# Seconds between raising Live and capturing. Raising is asynchronous: `open`
# returns as soon as the request is queued, well before the window is composited
# at the front, and capturing too early gets whatever was on top before.
DEFAULT_SETTLE_S = 1.5

# CGWindowListCopyWindowInfo options. On-screen windows only, minus the desktop
# icon layer, which is not a window anyone wants to photograph.
_LIST_ON_SCREEN_ONLY = 1
_LIST_EXCLUDE_DESKTOP = 16
_NULL_WINDOW_ID = 0
_PLIST_XML_V1 = 100

# Normal application windows live on layer 0. Menus, tooltips, floating palettes
# and overlays sit above it, and one of those being frontmost is precisely how a
# capture ends up showing the wrong thing.
_NORMAL_WINDOW_LAYER = 0


class CaptureError(Exception):
    """Base class for refusals — every one of these means no image was written."""


class UnsupportedPlatformError(CaptureError):
    """Not macOS."""


class ScreenRecordingDenied(CaptureError):
    """Screen Recording permission has not been granted to the host application."""


class NoWindowError(CaptureError):
    """Live is not running, or is running with no capturable window."""


class AmbiguousWindowError(CaptureError):
    """More than one candidate window — refuse rather than photograph the wrong one."""


class CaptureFailed(CaptureError):
    """screencapture or sips failed."""


@dataclass(frozen=True)
class Window:
    """One on-screen window, as the window server describes it."""

    window_id: int
    owner: str
    width: int
    height: int

    def describe(self) -> str:
        return f"id {self.window_id} ({self.width}x{self.height})"


def require_macos() -> None:
    if sys.platform != "darwin":
        raise UnsupportedPlatformError(
            f"this tool drives macOS screencapture and sips; platform is {sys.platform}"
        )


def _window_list_plist() -> bytes:
    """Ask the window server for its on-screen window list, as plist bytes.

    The whole ctypes surface is confined here. Serialising through
    ``CFPropertyListCreateData`` rather than walking ``CFDictionary`` by hand is
    what keeps that surface to four calls: the structure crosses the boundary as
    a byte string, and :mod:`plistlib` does the parsing.
    """
    cg_path = ctypes.util.find_library("CoreGraphics")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not cg_path or not cf_path:
        raise CaptureError("could not locate CoreGraphics/CoreFoundation")
    core_graphics = ctypes.cdll.LoadLibrary(cg_path)
    core_foundation = ctypes.cdll.LoadLibrary(cf_path)

    core_graphics.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    core_graphics.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    core_foundation.CFPropertyListCreateData.restype = ctypes.c_void_p
    core_foundation.CFPropertyListCreateData.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    core_foundation.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)
    core_foundation.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    core_foundation.CFDataGetLength.restype = ctypes.c_long
    core_foundation.CFDataGetLength.argtypes = [ctypes.c_void_p]
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

    window_list = core_graphics.CGWindowListCopyWindowInfo(
        _LIST_ON_SCREEN_ONLY | _LIST_EXCLUDE_DESKTOP, _NULL_WINDOW_ID
    )
    if not window_list:
        raise CaptureError("the window server returned no window list")
    data = None
    try:
        data = core_foundation.CFPropertyListCreateData(
            None, window_list, _PLIST_XML_V1, 0, None
        )
        if not data:
            raise CaptureError("could not serialise the window list")
        length = core_foundation.CFDataGetLength(data)
        return bytes(bytearray(core_foundation.CFDataGetBytePtr(data)[:length]))
    finally:
        if data:
            core_foundation.CFRelease(data)
        core_foundation.CFRelease(window_list)


def on_screen_windows() -> list[dict]:
    """Every on-screen window the window server knows about."""
    parsed = plistlib.loads(_window_list_plist())
    return [entry for entry in parsed if isinstance(entry, dict)]


def find_window(windows: list[dict], owner: str) -> Window:
    """The one normal window belonging to ``owner``.

    Two windows is an error, not a coin flip. Live legitimately opens secondary
    windows — a plug-in editor, Preferences — and silently capturing whichever
    the window server happened to list first is how a screenshot of the wrong
    thing gets committed and not noticed until someone reads the docs.
    """
    candidates = [
        Window(
            window_id=int(entry["kCGWindowNumber"]),
            owner=str(entry.get("kCGWindowOwnerName", "")),
            width=int(entry.get("kCGWindowBounds", {}).get("Width", 0)),
            height=int(entry.get("kCGWindowBounds", {}).get("Height", 0)),
        )
        for entry in windows
        if str(entry.get("kCGWindowOwnerName", "")) == owner
        and int(entry.get("kCGWindowLayer", -1)) == _NORMAL_WINDOW_LAYER
        and "kCGWindowNumber" in entry
    ]
    if not candidates:
        raise NoWindowError(
            f"no on-screen window owned by {owner!r} — is Live running with a set open?"
        )
    if len(candidates) > 1:
        listing = ", ".join(window.describe() for window in candidates)
        raise AmbiguousWindowError(
            f"{len(candidates)} windows owned by {owner!r} ({listing}) — close the extra "
            f"window or pass --window-id to choose one"
        )
    return candidates[0]


def _host_app_hint() -> str:
    """Best guess at which application must be granted the permission.

    The grant is per *hosting application*, not per script, and the name is not
    obvious from inside a terminal — so the ancestry is walked to name it.
    """
    pid = os.getpid()
    for _ in range(10):
        try:
            parent = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, check=True
            ).stdout.strip()
            pid = int(parent)
            if pid <= 1:
                break
            command = subprocess.run(
                ["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, check=True
            ).stdout.strip()
        except (subprocess.CalledProcessError, ValueError):
            break
        if ".app/" in command:
            return command.split(".app/")[0].split("/")[-1] + ".app"
    return "the application hosting this terminal"


def assert_capture_permission() -> None:
    """Refuse before raising anything if Screen Recording is not granted.

    Checked with the API rather than inferred from a failed capture, because the
    failure mode is genuinely misleading: ``screencapture`` reports "could not
    create image from window", which reads like a bad window id.
    """
    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        raise CaptureError("could not locate CoreGraphics")
    core_graphics = ctypes.cdll.LoadLibrary(cg_path)
    try:
        core_graphics.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        granted = core_graphics.CGPreflightScreenCaptureAccess()
    except AttributeError as exc:  # very old macOS without the preflight API
        raise CaptureError("this macOS has no screen-capture preflight API") from exc
    if not granted:
        raise ScreenRecordingDenied(
            f"Screen Recording permission is not granted to {_host_app_hint()}. Grant it in "
            f"System Settings > Privacy & Security > Screen Recording, then restart that "
            f"application — the permission is read at launch"
        )


def raise_app(app: str) -> None:
    """Bring Live to the front."""
    try:
        subprocess.run(["open", "-a", app], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise CaptureError(f"could not raise {app!r}: {(exc.stderr or '').strip()}") from exc
    except OSError as exc:
        raise CaptureError(f"could not run open: {exc}") from exc


def screencapture_argv(window_id: int, dst: Path) -> list[str]:
    """argv for the window capture.

    ``-o`` drops the drop-shadow, so the image is the window and not a window on
    a soft grey halo of whatever was behind it. ``-x`` silences the shutter.

    ``-l`` is absent from ``screencapture``'s usage text on macOS 26 but is still
    accepted — passing it produces a capability error, not an "illegal option",
    which is how that was established.
    """
    return ["screencapture", "-x", "-o", "-l", str(window_id), str(dst)]


def resample_argv(path: Path, width: int) -> list[str]:
    """argv for the downscale to a fixed width, in place.

    ``sips`` rather than ffmpeg: this tool is macOS-only already, so the
    OS-provided image tool costs nothing, and screenshots then do not drag in
    the encoder that only the audio pipeline needs.
    """
    return ["sips", "--resampleWidth", str(width), str(path), "--out", str(path)]


def _assert_width(path: Path, width: int) -> None:
    """Read the width back off the finished PNG.

    A fixed width is the entire determinism this tool promises, and ``sips``
    exiting 0 does not establish it. Measuring is one call, and the alternative
    is discovering at review time that four committed screenshots disagree.
    """
    reported = _run_capturing(["sips", "-g", "pixelWidth", str(path)])
    actual = next(
        (int(part) for line in reported.splitlines() if "pixelWidth" in line
         for part in [line.rsplit(":", 1)[-1].strip()] if part.isdigit()),
        None,
    )
    if actual != width:
        raise CaptureFailed(
            f"{path.name} is {actual}px wide but {width}px was requested — the fixed "
            f"width is the determinism this tool exists to provide"
        )


def _run_capturing(argv: list[str]) -> str:
    """Run a subprocess and return its stdout, raising on failure."""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise CaptureFailed(f"could not run {argv[0]}: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise CaptureFailed(f"{argv[0]} failed: {detail[-1] if detail else 'no output'}")
    return completed.stdout


def _run(argv: list[str]) -> None:
    """Run a subprocess for its effect, discarding stdout."""
    _run_capturing(argv)


def capture(
    out: Path,
    app: str = DEFAULT_APP,
    owner: str = DEFAULT_OWNER,
    width: int = DEFAULT_WIDTH,
    window_id: int | None = None,
    raise_first: bool = True,
    settle: float = DEFAULT_SETTLE_S,
) -> Window | None:
    """Raise Live, capture its window, downscale. Returns the window captured."""
    require_macos()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Clear any previous take first, and remove whatever this run produced if it
    # fails. Otherwise a failed re-shoot leaves the *old* image sitting at the
    # path looking fresh, and the next `git add docs/assets/` commits it — and a
    # capture that succeeded but failed to downscale is the worse version of
    # that, since it is a valid PNG silently violating the fixed width this tool
    # exists to guarantee.
    #
    # The clear happens before the *pre-flight* checks too, not just the capture:
    # a denied permission or an ambiguous window is equally a failed run, and
    # leaving the old image behind for those is the same trap.
    out.unlink(missing_ok=True)
    try:
        for tool in ("screencapture", "sips"):
            if shutil.which(tool) is None:
                raise CaptureError(f"{tool} not found on PATH")
        assert_capture_permission()

        if raise_first:
            raise_app(app)
            time.sleep(settle)

        window = None
        if window_id is None:
            window = find_window(on_screen_windows(), owner)
            window_id = window.window_id

        _run(screencapture_argv(window_id, out))
        if not out.is_file() or out.stat().st_size == 0:
            # screencapture can exit 0 having written nothing when the target
            # window disappears mid-capture. An empty PNG is committable and
            # renders as a broken image.
            raise CaptureFailed(f"screencapture exited 0 but wrote no image to {out}")
        _run(resample_argv(out, width))
        _assert_width(out, width)
    except BaseException:
        # Broad on purpose, and it re-raises rather than swallowing: an
        # unexpected failure is exactly when a half-written PNG is most likely
        # to survive at a path something is about to commit.
        out.unlink(missing_ok=True)
        raise
    return window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="where to write the PNG")
    parser.add_argument("--app", default=DEFAULT_APP, help="the .app to raise")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="window-server owner name")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--window-id", type=int, help="capture this window instead of resolving one")
    parser.add_argument("--no-raise", action="store_true", help="capture without raising Live first")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S)
    parser.add_argument(
        "--list", action="store_true", help="list candidate windows and exit, capturing nothing"
    )
    args = parser.parse_args(argv)

    try:
        require_macos()
        if args.list:
            for entry in on_screen_windows():
                if str(entry.get("kCGWindowOwnerName", "")) == args.owner:
                    bounds = entry.get("kCGWindowBounds", {})
                    print(
                        f"id {entry.get('kCGWindowNumber')} "
                        f"layer {entry.get('kCGWindowLayer')} "
                        f"{int(bounds.get('Width', 0))}x{int(bounds.get('Height', 0))}"
                    )
            return 0
        if args.out is None:
            parser.error("--out is required unless --list is given")
        window = capture(
            args.out,
            args.app,
            args.owner,
            args.width,
            args.window_id,
            not args.no_raise,
            args.settle,
        )
    except CaptureError as exc:
        print(f"capture_live_shot: {exc}", file=sys.stderr)
        return 1

    captured = f" from {window.describe()}" if window else ""
    print(f"wrote {args.out} at width {args.width}{captured}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
