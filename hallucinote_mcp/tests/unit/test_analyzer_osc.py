"""Tests for hallucinote_mcp.analyzer.osc — outbound OSC packer."""
from __future__ import annotations

import socket
import struct
import threading

import pytest

from hallucinote_mcp.analyzer.osc import AnalyzerOSC, _pack


def test_pack_string_arg_layout():
    """OSC 1.0: address (null-padded to 4) + type tag (null-padded to 4)
    + null-padded string body."""
    packet = _pack("/path", "/tmp/foo.wav")
    # Address "/path" + null + 2 pad bytes = 8 bytes.
    assert packet[:8] == b"/path\x00\x00\x00"
    # Type tag ",s" + null + 1 pad byte = 4 bytes.
    assert packet[8:12] == b",s\x00\x00"
    # Body "/tmp/foo.wav" + null + 3 pad bytes (length 13 → align to 16).
    body = packet[12:]
    assert body.startswith(b"/tmp/foo.wav\x00")
    assert len(body) % 4 == 0


def test_pack_int_arg_big_endian():
    """Beats go on the wire as big-endian 32-bit signed integers."""
    packet = _pack("/start_at_beat", 256)
    # The body should be 4 bytes representing 256 big-endian.
    body = packet[-4:]
    assert struct.unpack(">i", body)[0] == 256


def test_pack_rejects_bool():
    with pytest.raises(TypeError, match="bool"):
        _pack("/anything", True)


def test_pack_rejects_unsupported_type():
    with pytest.raises(TypeError, match="str / int"):
        _pack("/anything", 1.5)  # float not supported in outbound packer


def test_pack_address_alignment():
    """Address strings of various lengths must always pad to a 4-byte
    boundary, otherwise the receiver can't parse the type tag."""
    for addr in ("/a", "/ab", "/abc", "/abcd", "/abcde"):
        packet = _pack(addr, "x")
        # The string ends with a null and is padded to a 4-byte boundary.
        # Find the first null byte — that ends the address string.
        end = packet.index(b"\x00")
        # Bytes from `end` onward should be `\x00` until alignment.
        assert end + 1 <= len(packet)
        padded_len = ((end // 4) + 1) * 4
        assert padded_len <= len(packet)


# --- live socket round-trip ------------------------------------------


def _capture_one_packet(port: int, holder: list[bytes]) -> threading.Thread:
    """Spawn a daemon receiver that captures one UDP packet then exits."""
    def _run():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.settimeout(2.0)
            try:
                packet, _addr = sock.recvfrom(4096)
                holder.append(packet)
            except socket.timeout:
                pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _free_udp_port() -> int:
    """Ask the OS for a free port. The port is returned to the pool when
    the socket is closed, so the caller must bind it quickly."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_analyzer_osc_set_path_round_trip():
    port = _free_udp_port()
    holder: list[bytes] = []
    thread = _capture_one_packet(port, holder)
    # Tiny settle so the receiver is bound before we send.
    import time
    time.sleep(0.05)

    client = AnalyzerOSC(port=port)
    client.set_path("/var/folders/abc/track.wav")

    thread.join(timeout=2.0)
    assert holder, "receiver didn't capture any packet"
    packet = holder[0]
    # Address starts the packet, null-terminated + padded.
    assert packet.startswith(b"/path\x00")
    # The path appears somewhere in the body.
    assert b"/var/folders/abc/track.wav" in packet


def test_analyzer_osc_set_start_at_beat_int_payload():
    port = _free_udp_port()
    holder: list[bytes] = []
    thread = _capture_one_packet(port, holder)
    import time
    time.sleep(0.05)

    client = AnalyzerOSC(port=port)
    client.set_start_at_beat(64)

    thread.join(timeout=2.0)
    assert holder
    packet = holder[0]
    assert packet.startswith(b"/start_at_beat\x00")
    # Last 4 bytes are the int payload.
    assert struct.unpack(">i", packet[-4:])[0] == 64


def test_analyzer_osc_set_track_id_rejects_empty():
    client = AnalyzerOSC()
    with pytest.raises(ValueError, match="non-empty"):
        client.set_track_id("")
