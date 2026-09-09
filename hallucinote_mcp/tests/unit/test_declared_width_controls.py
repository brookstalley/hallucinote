"""``_collect_declared_width_controls`` — the DB walk behind width realization.

This walk is the half of STR-4C8N that cannot live in ``analyze_mix`` (which is
DB-agnostic by contract), and a real defect shipped inside it: it originally
walked only tracks, making a width control on a return INVISIBLE rather than
skipped — which the report would then render as "none recognised" when one was
authored. These tests pin the walk itself.
"""
from __future__ import annotations

from pathlib import Path

from hallucinote.db import mutations as M
from hallucinote.db.connection import init_db
from hallucinote_mcp.server_side.analysis import _collect_declared_width_controls


def _song_with_devices(tmp_path: Path):
    conn = init_db(tmp_path / "s.db")
    conn.execute("INSERT INTO songs (id, name) VALUES (?, ?)", ("song-1", "s"))

    track = M.create_track(conn, song_id="song-1", track_index=3, name="Rhythm Gtr")
    t_chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    utility = M.create_device(
        conn, chain_id=t_chain, position=1, kind="Utility",
        display_name="Utility", class_name="StereoGain",
    )
    M.set_device_parameter(
        conn, device_id=utility, name="Stereo Width", value_display="165 %",
    )
    # A non-width parameter on the SAME device must not be collected.
    M.set_device_parameter(
        conn, device_id=utility, name="Gain", value_display="0.0 dB",
    )
    # A device with no width control at all.
    other = M.create_device(
        conn, chain_id=t_chain, position=2, kind="Saturator",
        display_name="Saturator", class_name="Saturator",
    )
    M.set_device_parameter(
        conn, device_id=other, name="Drive", value_display="12.0 dB",
    )

    ret = M.create_return(conn, song_id="song-1", name="B-Room", position=2)
    r_chain = M.create_device_chain(conn, parent_return_id=ret, position=0)
    r_utility = M.create_device(
        conn, chain_id=r_chain, position=1, kind="Utility",
        display_name="Utility", class_name="StereoGain",
    )
    M.set_device_parameter(
        conn, device_id=r_utility, name="Stereo Width", value_display="140 %",
    )
    conn.commit()
    return conn


def test_collects_only_width_parameters(tmp_path: Path):
    conn = _song_with_devices(tmp_path)
    controls = _collect_declared_width_controls(conn, "song-1")
    assert {c.parameter_name for c in controls} == {"Stereo Width"}
    # Gain and Drive sit on collected/adjacent devices and must not appear.
    assert len(controls) == 2


def test_translates_db_uuids_to_capture_surface_ids(tmp_path: Path):
    """The whole reason this lives in the handler: the DB is keyed by UUID and
    captures by surface index, so an untranslated id would silently join nothing.
    """
    conn = _song_with_devices(tmp_path)
    controls = _collect_declared_width_controls(conn, "song-1")
    by_surface = {c.surface_id: c for c in controls}
    assert set(by_surface) == {"track:3", "return:2"}
    assert by_surface["track:3"].declared_display == "165 %"
    assert by_surface["return:2"].declared_display == "140 %"
    assert by_surface["track:3"].device_name == "Utility"


def test_a_return_side_control_is_collected(tmp_path: Path):
    """The regression for the defect that shipped: returns were not walked, so a
    width control on a reverb bus produced no record at all."""
    conn = _song_with_devices(tmp_path)
    controls = _collect_declared_width_controls(conn, "song-1")
    assert any(c.surface_id == "return:2" for c in controls)


def test_song_with_no_width_controls_collects_nothing(tmp_path: Path):
    conn = init_db(tmp_path / "empty.db")
    conn.execute("INSERT INTO songs (id, name) VALUES (?, ?)", ("song-2", "e"))
    track = M.create_track(conn, song_id="song-2", track_index=1, name="Drums")
    chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    dev = M.create_device(
        conn, chain_id=chain, position=1, kind="Saturator",
        display_name="Saturator", class_name="Saturator",
    )
    M.set_device_parameter(conn, device_id=dev, name="Drive", value_display="6.0 dB")
    conn.commit()
    assert _collect_declared_width_controls(conn, "song-2") == []


def test_a_control_left_at_unity_is_not_a_declaration(tmp_path: Path):
    """Presence in the DB is not evidence of intent.

    A pull writes a row for EVERY parameter Live reports, not only the ones an
    author touched, so every untouched Utility in a song carries a ``Stereo
    Width`` at Live's default ``100 %``. Collecting those would hand /mix-review
    a "declared 100 %" for a width nobody set — and a naturally wide stem
    carrying one then presents as ``declared 100 % / measured -3 dB``, a
    contradiction with an intent that was never expressed.
    """
    conn = init_db(tmp_path / "s.db")
    conn.execute("INSERT INTO songs (id, name) VALUES (?, ?)", ("song-1", "s"))
    track = M.create_track(conn, song_id="song-1", track_index=0, name="Pad")
    chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    untouched = M.create_device(
        conn, chain_id=chain, position=1, kind="Utility",
        display_name="Utility", class_name="StereoGain",
    )
    M.set_device_parameter(
        conn, device_id=untouched, name="Stereo Width", value_display="100 %",
    )
    conn.commit()

    assert _collect_declared_width_controls(conn, "song-1") == []

    # The same device, dialled — now it IS a declaration.
    M.set_device_parameter(
        conn, device_id=untouched, name="Stereo Width", value_display="165 %",
    )
    conn.commit()
    controls = _collect_declared_width_controls(conn, "song-1")
    assert [c.declared_display for c in controls] == ["165 %"]
