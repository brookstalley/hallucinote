"""Control Surface subclass — instantiated by Live via ``create_instance``.

Kept in a separate module from ``__init__.py`` so the package is importable
outside Live (for tests) without depending on Live's ``_Framework`` package.
"""
from __future__ import annotations

from _Framework.ControlSurface import ControlSurface  # type: ignore[import-not-found]

from .. import schema
from .dispatch import LiveLiveContext
from .server import RemoteScriptServer


class HallucinoteControlSurface(ControlSurface):
    """Hallucinote-MCP's Ableton Live Control Surface.

    Owns the TCP server lifecycle (start on construction, stop on
    ``disconnect``). All Live API access goes through ``LiveLiveContext``,
    which marshals onto Live's main thread via ``schedule_message``.
    """

    def __init__(self, c_instance):  # type: ignore[no-untyped-def]
        ControlSurface.__init__(self, c_instance)
        self.log_message("Hallucinote MCP Remote Script initializing")
        schema.register_help_actions()

        self._live_context = LiveLiveContext(
            song_factory=self.song,
            schedule_on_main=lambda fn: self.schedule_message(0, fn),
        )
        self._server = RemoteScriptServer(
            live_context=self._live_context,
            log=self.log_message,
        )
        self._server.start()
        self.show_message(
            "Hallucinote MCP listening on port {}".format(self._server.port)
        )

    def disconnect(self):  # type: ignore[no-untyped-def]
        self.log_message("Hallucinote MCP Remote Script disconnecting")
        try:
            self._server.stop()
        finally:
            ControlSurface.disconnect(self)


__all__ = ["HallucinoteControlSurface"]
