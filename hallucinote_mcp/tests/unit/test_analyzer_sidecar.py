"""Tests for hallucinote_mcp.analyzer.sidecar — UDP feature-frame receiver."""
from __future__ import annotations

import socket
import struct
import time

import pytest

from hallucinote_mcp.analyzer.sidecar import (
    FeatureFrame,
    OSCSidecar,
    _parse_feature_frame,
    reset_shared_sidecar_for_tests,
    shared_sidecar,
)


def _osc_string(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\x00"
    pad = (-len(raw)) % 4
    return raw + (b"\x00" * pad)


def _build_feature_frame_packet(
    track_id: str,
    lufs_m: float,
    peak_dbfs: float,
    low_mid_power: float,
) -> bytes:
    address = f"/hallucinote/track/{track_id}/features"
    return (
        _osc_string(address)
        + _osc_string(",fff")
        + struct.pack(">fff", lufs_m, peak_dbfs, low_mid_power)
    )


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _send_one(port: int, packet: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(packet, ("127.0.0.1", port))


# --- frame parsing ---------------------------------------------------


def test_parse_valid_frame_extracts_track_id_and_floats():
    packet = _build_feature_frame_packet("track:1", -23.0, -1.5, -12.3)
    frame = _parse_feature_frame(packet)
    assert frame is not None
    assert frame.track_id == "track:1"
    assert frame.lufs_m == pytest.approx(-23.0)
    assert frame.peak_dbfs == pytest.approx(-1.5)
    assert frame.low_mid_power == pytest.approx(-12.3)


def test_parse_rejects_wrong_address_prefix():
    packet = _osc_string("/foo/bar") + _osc_string(",fff") + struct.pack(">fff", 0, 0, 0)
    assert _parse_feature_frame(packet) is None


def test_parse_rejects_wrong_type_tag():
    """LUFS payload must be 3 floats — anything else is rejected so a
    future ableton-side schema mistake doesn't poison ring buffers."""
    packet = (
        _osc_string("/hallucinote/track/track:1/features")
        + _osc_string(",fi")
        + struct.pack(">fi", 1.0, 2)
    )
    assert _parse_feature_frame(packet) is None


def test_parse_rejects_empty_track_id():
    packet = (
        _osc_string("/hallucinote/track//features")
        + _osc_string(",fff")
        + struct.pack(">fff", 0, 0, 0)
    )
    assert _parse_feature_frame(packet) is None


def test_parse_rejects_truncated_payload():
    """Less than 3 floats of payload — drop, don't crash."""
    packet = (
        _osc_string("/hallucinote/track/track:1/features")
        + _osc_string(",fff")
        + struct.pack(">f", 1.0)
    )
    assert _parse_feature_frame(packet) is None


# --- sidecar lifecycle -----------------------------------------------


def test_sidecar_receives_and_buffers_one_frame():
    port = _free_udp_port()
    sidecar = OSCSidecar(port=port)
    sidecar.start()
    try:
        _send_one(port, _build_feature_frame_packet("track:1", -23.0, -1.5, -12.3))
        # Wait up to 1 s for the receiver thread to drain.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            frames = sidecar.read("track:1")
            if frames:
                break
            time.sleep(0.02)
        frames = sidecar.read("track:1")
        assert len(frames) == 1
        assert frames[0] == FeatureFrame(
            track_id="track:1",
            lufs_m=pytest.approx(-23.0),
            peak_dbfs=pytest.approx(-1.5),
            low_mid_power=pytest.approx(-12.3),
        )
        assert sidecar.frames_received == 1
        assert sidecar.frames_dropped == 0
    finally:
        sidecar.stop()
        sidecar.join(timeout=2.0)


def test_sidecar_buffers_per_track_id():
    """Multiple analyzers' frames route to independent ring buffers."""
    port = _free_udp_port()
    sidecar = OSCSidecar(port=port)
    sidecar.start()
    try:
        _send_one(port, _build_feature_frame_packet("track:1", -20, -2, -10))
        _send_one(port, _build_feature_frame_packet("return:1", -30, -5, -15))
        _send_one(port, _build_feature_frame_packet("master", -10, -0.5, -8))

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if (sidecar.read("track:1")
                    and sidecar.read("return:1")
                    and sidecar.read("master")):
                break
            time.sleep(0.02)

        track_frames = sidecar.read("track:1")
        return_frames = sidecar.read("return:1")
        master_frames = sidecar.read("master")
        assert len(track_frames) == 1
        assert len(return_frames) == 1
        assert len(master_frames) == 1
        assert track_frames[0].lufs_m == pytest.approx(-20)
        assert return_frames[0].lufs_m == pytest.approx(-30)
        assert master_frames[0].lufs_m == pytest.approx(-10)
    finally:
        sidecar.stop()
        sidecar.join(timeout=2.0)


def test_sidecar_ring_buffer_is_bounded():
    """When the buffer fills, oldest frames drop. Keeps memory bounded
    under long runs."""
    port = _free_udp_port()
    sidecar = OSCSidecar(port=port, buffer_depth=3)
    sidecar.start()
    try:
        for i in range(10):
            _send_one(port, _build_feature_frame_packet("track:1", -float(i), 0, 0))
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if sidecar.frames_received >= 10:
                break
            time.sleep(0.02)
        frames = sidecar.read("track:1")
        assert len(frames) == 3
        # The last three sent are the only survivors.
        assert [f.lufs_m for f in frames] == [
            pytest.approx(-7), pytest.approx(-8), pytest.approx(-9),
        ]
    finally:
        sidecar.stop()
        sidecar.join(timeout=2.0)


def test_sidecar_drops_malformed_packets_without_dying():
    port = _free_udp_port()
    sidecar = OSCSidecar(port=port)
    sidecar.start()
    try:
        _send_one(port, b"garbage")
        _send_one(port, _build_feature_frame_packet("track:1", -23, -1, -12))

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if sidecar.frames_received >= 2:
                break
            time.sleep(0.02)
        assert sidecar.frames_received == 2
        assert sidecar.frames_dropped == 1
        assert len(sidecar.read("track:1")) == 1
    finally:
        sidecar.stop()
        sidecar.join(timeout=2.0)


def test_sidecar_start_is_idempotent():
    port = _free_udp_port()
    sidecar = OSCSidecar(port=port)
    sidecar.start()
    try:
        sidecar.start()  # second call must be a no-op, not raise EADDRINUSE
    finally:
        sidecar.stop()
        sidecar.join(timeout=2.0)


def test_sidecar_stop_is_idempotent():
    sidecar = OSCSidecar(port=_free_udp_port())
    sidecar.start()
    sidecar.stop()
    sidecar.stop()  # second stop must be a no-op


def test_shared_sidecar_singleton():
    """``shared_sidecar()`` returns the same instance across calls; the
    test reset helper cleans it up for hermetic test runs."""
    reset_shared_sidecar_for_tests()
    try:
        first = shared_sidecar()
        second = shared_sidecar()
        assert first is second
    finally:
        reset_shared_sidecar_for_tests()
