"""UDP feature-frame sidecar.

The analyzer's outbound emitter sends ~30 Hz frames of
``/hallucinote/track/<track_id>/features [lufs_m, peak_dbfs, low_mid_power]``
to ``127.0.0.1:11001`` (configurable per-instance via the analyzer's
``EmitPort`` Live parameter; default is shared 11001 so one sidecar
collects everyone's frames).

The sidecar:

- binds a single UDP socket;
- decodes incoming OSC frames (3-float payload at a documented address shape);
- routes by ``track_id`` to a per-track ring buffer holding the last
  N frames (default N = ~900 ≈ 30 s at 30 Hz);
- exposes ``read(track_id)`` / ``read_all()`` for in-process consumers.

Lazy spawn: ``OSCSidecar.shared()`` returns the process-wide instance,
starting it on the first call. ``ableton_render`` instantiates it before
arming analyzers; Chunk 3 reads from it for any feature-derived
analysis that benefits from streaming data (the MVP analysis pipeline
works from the WAV stems, so streaming consumption is optional).

Process model: **thread, not subprocess.** UDP sockets are cheap and
the receiver only does a small struct-unpack + dict-append per frame.
Subprocess isolation would buy nothing here and would force a second
IPC hop to surface the buffer back to the MCP server. If the receiver
ever does heavy work (e.g. on-the-fly LUFS-S derivation across analyzers)
that can be revisited.
"""
from __future__ import annotations

import socket
import struct
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable


_DEFAULT_LISTEN_HOST = "127.0.0.1"
_DEFAULT_LISTEN_PORT = 11001
# 30 Hz * 30 seconds; trimmed to keep memory bounded under e.g. a 50-track
# session. ~12 KB/track at this depth — 600 KB for 50 tracks is fine.
_DEFAULT_BUFFER_DEPTH = 900
_OSC_ADDRESS_PREFIX = "/hallucinote/track/"
_OSC_ADDRESS_SUFFIX = "/features"
_EXPECTED_TYPE_TAG = ",fff"


def _osc_unpack_string(buf: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated, 4-byte-padded OSC string starting at ``offset``.

    Returns (decoded, new_offset). Raises on malformed strings.
    """
    end = buf.find(b"\x00", offset)
    if end < 0:
        raise ValueError("OSC string not null-terminated")
    s = buf[offset:end].decode("utf-8", errors="replace")
    # Advance past the null + alignment padding.
    new_offset = end + 1
    pad = (4 - ((new_offset - offset) % 4)) % 4
    return s, new_offset + pad


@dataclass(frozen=True)
class FeatureFrame:
    """One decoded feature frame.

    Fields mirror the wire shape documented in the analyzer spec:
      - ``lufs_m`` — momentary loudness (LUFS, K-weighted, 400 ms integration)
      - ``peak_dbfs`` — sample-peak in dBFS (NOT true-peak)
      - ``low_mid_power`` — 200–500 Hz band power, dB relative to full scale
    """

    track_id: str
    lufs_m: float
    peak_dbfs: float
    low_mid_power: float


def _parse_feature_frame(packet: bytes) -> FeatureFrame | None:
    """Decode one OSC packet into a FeatureFrame. None if it doesn't match.

    Lenient by design — feature streams are best-effort UDP, and a
    malformed frame should never take the sidecar down. Returns
    ``None`` for any packet that doesn't parse as a 3-float frame at
    the documented address; the caller treats that as "dropped frame".
    """
    try:
        address, offset = _osc_unpack_string(packet, 0)
    except ValueError:
        return None
    if not address.startswith(_OSC_ADDRESS_PREFIX):
        return None
    if not address.endswith(_OSC_ADDRESS_SUFFIX):
        return None
    track_id = address[len(_OSC_ADDRESS_PREFIX):-len(_OSC_ADDRESS_SUFFIX)]
    if not track_id:
        return None
    try:
        type_tag, offset = _osc_unpack_string(packet, offset)
    except ValueError:
        return None
    if type_tag != _EXPECTED_TYPE_TAG:
        return None
    # Three big-endian 32-bit floats.
    if len(packet) - offset < 12:
        return None
    lufs_m, peak_dbfs, low_mid_power = struct.unpack(
        ">fff", packet[offset:offset + 12],
    )
    return FeatureFrame(
        track_id=track_id,
        lufs_m=float(lufs_m),
        peak_dbfs=float(peak_dbfs),
        low_mid_power=float(low_mid_power),
    )


@dataclass
class _TrackBuffer:
    """Per-track_id ring buffer. Deque is naturally bounded + thread-safe
    for append + iterate (CPython GIL covers the atomic ops we use)."""

    depth: int
    frames: deque[FeatureFrame] = field(default_factory=deque)

    def append(self, frame: FeatureFrame) -> None:
        if len(self.frames) >= self.depth:
            self.frames.popleft()
        self.frames.append(frame)


class OSCSidecar:
    """UDP receiver + ring buffer.

    Lifecycle:
      1. ``start()`` binds the socket and spawns a daemon thread.
      2. The thread loops on ``recvfrom``, parses + routes incoming frames.
      3. ``stop()`` closes the socket; the thread sees ``OSError`` on the
         next recv, breaks the loop, and exits. ``join()`` blocks until
         the thread is fully done — call this in tests for determinism.

    The sidecar is process-wide by default (``shared()``), but tests
    construct fresh instances on per-test ports so they don't collide.
    """

    def __init__(
        self,
        *,
        host: str = _DEFAULT_LISTEN_HOST,
        port: int = _DEFAULT_LISTEN_PORT,
        buffer_depth: int = _DEFAULT_BUFFER_DEPTH,
    ) -> None:
        self._host = host
        self._port = port
        self._buffer_depth = buffer_depth
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._buffers: dict[str, _TrackBuffer] = {}
        self._lock = threading.Lock()
        # `_running` is read by the recv loop without the lock; the GIL
        # covers the boolean atomic read.
        self._running = False
        # Total frames received (including parse failures) and dropped
        # (parse failures). Surfaces sidecar health in render results
        # without forcing the caller to inspect buffers.
        self._frames_received = 0
        self._frames_dropped = 0

    # --- lifecycle -----------------------------------------------------

    @property
    def port(self) -> int:
        """The actual bound port — useful when constructed with port=0 in
        tests so the OS picks a free port and the test reads it back."""
        if self._sock is None:
            return self._port
        return self._sock.getsockname()[1]

    def start(self) -> None:
        """Bind socket + spawn receiver thread. Idempotent — second call
        is a no-op so ``ableton_render`` can call ``ensure_started`` per
        invocation without worrying about double-spawning."""
        if self._running:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SO_REUSEADDR so tests + dev restarts don't hit TIME_WAIT
        # bind failures on rapid cycles.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.settimeout(0.25)
        self._sock = sock
        self._running = True
        thread = threading.Thread(
            target=self._recv_loop,
            name="hallucinote-osc-sidecar",
            daemon=True,
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        """Stop receiver thread + close socket. Idempotent."""
        if not self._running:
            return
        self._running = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def join(self, timeout: float | None = None) -> None:
        """Block until the receiver thread finishes. Tests use this for
        deterministic teardown."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    # --- reading -------------------------------------------------------

    def read(self, track_id: str) -> list[FeatureFrame]:
        """Snapshot of the ring buffer for one track_id. Empty if none."""
        with self._lock:
            buf = self._buffers.get(track_id)
            if buf is None:
                return []
            return list(buf.frames)

    def read_all(self) -> dict[str, list[FeatureFrame]]:
        """Snapshot of every populated ring buffer."""
        with self._lock:
            return {tid: list(buf.frames) for tid, buf in self._buffers.items()}

    def known_track_ids(self) -> Iterable[str]:
        with self._lock:
            return tuple(self._buffers.keys())

    @property
    def frames_received(self) -> int:
        return self._frames_received

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    # --- recv loop -----------------------------------------------------

    def _recv_loop(self) -> None:
        while self._running:
            sock = self._sock
            if sock is None:
                break
            try:
                packet, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                # Socket closed under us — `stop()` did this; break cleanly.
                break
            self._frames_received += 1
            frame = _parse_feature_frame(packet)
            if frame is None:
                self._frames_dropped += 1
                continue
            with self._lock:
                buf = self._buffers.get(frame.track_id)
                if buf is None:
                    buf = _TrackBuffer(depth=self._buffer_depth)
                    self._buffers[frame.track_id] = buf
                buf.append(frame)


# --- process-wide singleton -------------------------------------------

_shared_lock = threading.Lock()
_shared_sidecar: OSCSidecar | None = None


def shared_sidecar() -> OSCSidecar:
    """The process-wide sidecar. Lazily started on first call.

    `ableton_render` calls this in its preamble. Subsequent calls return
    the same instance — stopping + restarting is intentionally not
    supported through this surface (tests construct their own).
    """
    global _shared_sidecar  # noqa: PLW0603 — module-level singleton
    with _shared_lock:
        if _shared_sidecar is None:
            sidecar = OSCSidecar()
            sidecar.start()
            _shared_sidecar = sidecar
        return _shared_sidecar


def reset_shared_sidecar_for_tests() -> None:
    """Tear down the process-wide sidecar. Tests only — production never
    needs this."""
    global _shared_sidecar  # noqa: PLW0603
    with _shared_lock:
        if _shared_sidecar is not None:
            _shared_sidecar.stop()
            _shared_sidecar.join(timeout=2.0)
            _shared_sidecar = None


__all__ = [
    "FeatureFrame",
    "OSCSidecar",
    "shared_sidecar",
    "reset_shared_sidecar_for_tests",
]
