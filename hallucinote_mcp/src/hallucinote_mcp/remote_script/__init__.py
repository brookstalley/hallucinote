"""Hallucinote Remote Script — installed into Ableton Live's Remote Scripts
folder by the ``ableton-mcp-install`` skill.

Ableton Live's Python embedding (Python 3.7 in Live 11, 3.11 in Live 12)
imports this package as a Control Surface when the user selects "Hallucinote"
in Preferences → Link, Tempo & MIDI → Control Surface. ``create_instance``
is the conventional entry point Live looks for.

Threading model:
  - Live's main thread owns the Live API. Touching ``Live.Song.*`` from any
    other thread crashes the engine.
  - The TCP server runs on a background thread (``server.py``). When a
    request arrives, the worker enqueues it for execution on Live's main
    thread via ``schedule_message`` (a ``_Framework`` primitive).
  - The dispatcher result is then written back to the client socket from
    the worker thread.

This module is intentionally thin. The substantive logic lives in
``server.py`` (TCP) and ``dispatch.py`` (Live-API marshaling). Both are
testable without Live in the loop because they take a ``LiveContext`` and
the test substitutes a mock.
"""
from __future__ import annotations

# Live's Python is not on our local sys.path, so we cannot import _Framework
# at module-load time during testing. The actual ControlSurface subclass and
# create_instance() are defined inside a function that's only called when
# running inside Live.

__all__ = ["create_instance"]


def create_instance(c_instance):  # type: ignore[no-untyped-def]
    """Live's entry point. Returns a Control Surface instance.

    Live calls this once when the user enables the "Hallucinote" control
    surface in preferences. We construct the ControlSurface subclass lazily
    so importing this module outside Live (e.g. in tests) does not require
    Live's ``_Framework`` package.
    """
    from ._control_surface import HallucinoteControlSurface

    return HallucinoteControlSurface(c_instance)
