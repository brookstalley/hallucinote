"""Minimal OSC 1.0 sender for HallucinoteAnalyzer control traffic.

Outbound shape only — the sidecar (``sidecar.OSCSidecar``) handles
inbound. We deliberately do not depend on ``python-osc`` here: the
patch listens on a single UDP socket, the wire shape is documented in
``m4l/HallucinoteAnalyzer.amxd.spec.md``, and a hand-rolled 60-line
packer keeps the surface auditable from one file. The
Chunk 1 throwaway harness (``tools/test_capture.py``) carries the
same packer; this is its production home.

Supported OSC types:

- ``s`` — strings (null-terminated, 4-byte-aligned).
- ``i`` — 32-bit big-endian integers.

The analyzer's inbound surface only needs those two: paths and
track_ids are strings; beat positions are integers.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass


_DEFAULT_HOST = "127.0.0.1"


def _osc_string(s: str) -> bytes:
    """OSC 1.0 null-terminated, 4-byte-aligned string."""
    raw = s.encode("utf-8") + b"\x00"
    pad = (-len(raw)) % 4
    return raw + (b"\x00" * pad)


def _osc_int32(n: int) -> bytes:
    """OSC 1.0 big-endian 32-bit signed integer."""
    return struct.pack(">i", int(n))


def _pack(address: str, *args: object) -> bytes:
    """Pack an OSC message. Each arg must be a `str` or `int`."""
    type_chars: list[str] = []
    body = b""
    for a in args:
        if isinstance(a, bool):
            # Bools are ints in Python; reject explicitly so a caller
            # can't accidentally send a 0/1 expecting OSC bool semantics
            # (which the analyzer doesn't speak).
            raise TypeError(
                "OSC sender does not support bool args — pass int(0) / int(1) "
                "explicitly"
            )
        if isinstance(a, str):
            type_chars.append("s")
            body += _osc_string(a)
        elif isinstance(a, int):
            type_chars.append("i")
            body += _osc_int32(a)
        else:
            raise TypeError(
                f"OSC sender only supports str / int args, got {type(a).__name__}"
            )
    type_tag = "," + "".join(type_chars)
    return _osc_string(address) + _osc_string(type_tag) + body


@dataclass(frozen=True)
class AnalyzerOSC:
    """Per-analyzer OSC client. One instance per analyzer port.

    The analyzer's inbound port is the *Live parameter* ``Port`` on the
    device — each instance can listen on its own port so multiple
    analyzers in the same Live set don't collide. ``ensure_analyzers_loaded``
    assigns ports at setup time and bundles the chosen port with the
    instance metadata; this client is then constructed from
    ``AnalyzerInstance.osc_port`` and the host (always 127.0.0.1 for
    same-machine setups, kept configurable for future remote-Live
    experiments).
    """

    host: str = _DEFAULT_HOST
    port: int = 11000

    # --- transport-position-driven recording (Chunk 2) ----------------

    def set_path(self, abs_path: str) -> None:
        """Tell the analyzer where to write its next WAV.

        Must be sent BEFORE the analyzer arms (Live params can't carry
        strings — see spec §"Path delivery"). The patch retains the
        path until the next `/path` overwrites it.
        """
        self._send("/path", abs_path)

    def set_track_id(self, track_id: str) -> None:
        """Tell the analyzer how to label its outbound feature frames.

        The feature emitter prefixes its OSC address with this id:
        ``/hallucinote/track/<track_id>/features [...]``. Without a
        track_id the patch silently holds frames so the sidecar's
        ring buffers don't collect un-routable data.
        """
        if not isinstance(track_id, str) or not track_id:
            raise ValueError("track_id must be a non-empty string")
        self._send("/track_id", track_id)

    def set_start_at_beat(self, beat: int) -> None:
        """Schedule the recording window's start beat (transport-position-sync).

        The patch's beat observer fires on the audio buffer that crosses
        this beat; MCP latency on the wire becomes irrelevant to the
        recording boundary. See spec §"Transport-position-driven timing".
        """
        self._send("/start_at_beat", int(beat))

    def set_stop_at_beat(self, beat: int) -> None:
        """Schedule the recording window's stop beat.

        Must be > start_at_beat. The patch refuses to arm if the
        inequality doesn't hold; this client doesn't enforce it
        (defer to the patch's loud `[print]` error so config drift
        surfaces in one place).
        """
        self._send("/stop_at_beat", int(beat))

    # --- internals -----------------------------------------------------

    def _send(self, address: str, *args: object) -> None:
        packet = _pack(address, *args)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(packet, (self.host, self.port))
        finally:
            sock.close()


__all__ = ["AnalyzerOSC"]
