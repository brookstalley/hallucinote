"""The reference schedule: built from spans, from sections, or from a wire address."""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.spectral.schedule import (
    constant_schedule,
    node_ref_from_addr,
    schedule_digest,
    schedule_from_sections,
    schedule_from_spans,
)
from hallucinote.spectral.types import ReferenceSchedule

TRACK_A = ("track", "a")
TRACK_B = ("track", "b")


def test_spans_build_an_ordered_schedule():
    sched = schedule_from_spans([(8.0, 16.0, [TRACK_B]), (0.0, 8.0, [TRACK_A])])
    assert isinstance(sched, ReferenceSchedule)
    assert [s.start_beat for s in sched.spans] == [0.0, 8.0]
    assert sched.nodes_at(4.0) == (TRACK_A,)
    assert sched.nodes_at(12.0) == (TRACK_B,)
    assert sched.nodes_at(16.0) == ()


def test_overlapping_spans_refuse():
    with pytest.raises(ValueError, match="overlap"):
        schedule_from_spans([(0.0, 8.0, [TRACK_A]), (4.0, 12.0, [TRACK_B])])


def test_empty_span_list_teaches():
    with pytest.raises(ValueError, match="at least one"):
        schedule_from_spans([])


def test_span_without_nodes_refuses():
    with pytest.raises(ValueError, match="at least one node"):
        schedule_from_spans([(0.0, 4.0, [])])


def test_constant_schedule_is_one_span():
    sched = constant_schedule(0.0, 32.0, [("master",)])
    assert len(sched.spans) == 1
    assert sched.nodes_at(31.0) == (("master",),)


def _sections():
    return [
        {"name": "verse", "start_bar": 1.0, "end_bar": 5.0},
        {"name": "chorus", "start_bar": 5.0, "end_bar": 9.0},
        {"name": "verse", "start_bar": 9.0, "end_bar": 13.0},
        {"name": "bridge", "start_bar": 13.0, "end_bar": 15.0},
    ]


def test_sections_become_beat_spans_on_the_uniform_ruler():
    sched = schedule_from_sections(
        _sections(), {"verse": [TRACK_A], "chorus": [("master",)]}, default=[TRACK_B]
    )
    assert [(s.start_beat, s.end_beat) for s in sched.spans] == [
        (0.0, 16.0), (16.0, 32.0), (32.0, 48.0), (48.0, 56.0),
    ]
    # A repeated name applies to every section carrying it; the default
    # covers the one nobody named.
    assert sched.nodes_at(2.0) == (TRACK_A,)
    assert sched.nodes_at(40.0) == (TRACK_A,)
    assert sched.nodes_at(20.0) == (("master",),)
    assert sched.nodes_at(50.0) == (TRACK_B,)


def test_sections_without_a_reference_are_gaps():
    sched = schedule_from_sections(_sections(), {"chorus": [TRACK_A]})
    assert len(sched.spans) == 1
    assert sched.nodes_at(2.0) == ()
    assert sched.nodes_at(20.0) == (TRACK_A,)


def test_sections_unknown_name_refuses_naming_the_real_ones():
    with pytest.raises(ValueError, match="outro.*bridge"):
        schedule_from_sections(_sections(), {"outro": [TRACK_A]})


def test_sections_nobody_referenced_refuses():
    with pytest.raises(ValueError, match="no section received"):
        schedule_from_sections(_sections(), {})


def test_overlapping_sections_refuse_by_name():
    sections = [
        {"name": "verse", "start_bar": 1.0, "end_bar": 6.0},
        {"name": "chorus", "start_bar": 5.0, "end_bar": 9.0},
    ]
    with pytest.raises(ValueError, match="'verse'.*'chorus'.*overlap"):
        schedule_from_sections(sections, {"verse": [TRACK_A]}, default=[TRACK_B])


def test_sections_take_a_custom_bar_ruler():
    # 7/8: 3.5 beats per bar, delivered as a callable the way the song's
    # meter walk would be.
    sched = schedule_from_sections(
        _sections()[:1], {"verse": [TRACK_A]}, bar_to_beat=lambda bar: (bar - 1.0) * 3.5
    )
    assert (sched.start_beat, sched.end_beat) == (0.0, 14.0)


def test_sections_refuse_a_nonpositive_ruler():
    with pytest.raises(ValueError, match="beats_per_bar"):
        schedule_from_sections(_sections(), {"verse": [TRACK_A]}, beats_per_bar=0.0)


def test_digest_is_stable_and_sensitive():
    a = schedule_from_spans([(0.0, 8.0, [TRACK_A]), (8.0, 16.0, [TRACK_B])])
    b = schedule_from_spans([(8.0, 16.0, [TRACK_B]), (0.0, 8.0, [TRACK_A])])
    c = schedule_from_spans([(0.0, 8.0, [TRACK_A]), (8.0, 16.0, [("minus", "b")])])
    assert schedule_digest(a) == schedule_digest(b)
    assert schedule_digest(a) != schedule_digest(c)
    assert len(schedule_digest(a)) == 64


# --------------------------------------------------------------------------- #
# node_ref_from_addr — the wire address becomes a DB id
# --------------------------------------------------------------------------- #

def _song_with_nodes(tmp_path: Path):
    conn = init_db(tmp_path / "sched.db")
    sid = str(M.create_song(conn, name="sched-song", key="C"))
    t1 = str(M.create_track(conn, song_id=sid, track_index=1, name="bass"))
    t2 = str(M.create_track(conn, song_id=sid, track_index=2, name="lead"))
    r1 = str(M.create_return(conn, song_id=sid, name="verb", position=1))
    return conn, sid, t1, t2, r1


def test_track_return_and_master_addresses_resolve(tmp_path: Path):
    conn, sid, t1, t2, r1 = _song_with_nodes(tmp_path)
    track = {"parent": {"kind": "track", "index": 2}, "terminal": "track"}
    ret = {"parent": {"kind": "return", "index": 1}, "terminal": "return"}
    master = {"parent": {"kind": "master"}, "terminal": "master"}
    assert node_ref_from_addr(track, conn=conn, song_id=sid) == ("track", t2)
    assert node_ref_from_addr(ret, conn=conn, song_id=sid) == ("return", r1)
    assert node_ref_from_addr(master, conn=conn, song_id=sid) == ("master",)
    assert node_ref_from_addr(track, conn=conn, song_id=sid, complement=True) == ("minus", t2)


def test_device_address_refuses_and_names_the_host_node(tmp_path: Path):
    conn, sid, *_ = _song_with_nodes(tmp_path)
    device = {"parent": {"kind": "track", "index": 1}, "terminal": "device", "device_index": 1}
    with pytest.raises(ValueError, match="terminal 'device'.*'terminal': 'track'"):
        node_ref_from_addr(device, conn=conn, song_id=sid)
    # On the wire a missing terminal means a device too.
    with pytest.raises(ValueError, match="no terminal"):
        node_ref_from_addr({"parent": {"kind": "track", "index": 1}}, conn=conn, song_id=sid)


def test_unknown_index_refuses_listing_the_real_ones(tmp_path: Path):
    conn, sid, *_ = _song_with_nodes(tmp_path)
    with pytest.raises(ValueError, match=r"track_index 7.*\[1, 2\]"):
        node_ref_from_addr(
            {"parent": {"kind": "track", "index": 7}, "terminal": "track"}, conn=conn, song_id=sid
        )
    with pytest.raises(ValueError, match=r"position 3.*\[1\]"):
        node_ref_from_addr(
            {"parent": {"kind": "return", "index": 3}, "terminal": "return"}, conn=conn, song_id=sid
        )


def test_complement_is_only_the_mix_minus_a_track(tmp_path: Path):
    conn, sid, *_ = _song_with_nodes(tmp_path)
    with pytest.raises(ValueError, match="complement"):
        node_ref_from_addr(
            {"parent": {"kind": "master"}, "terminal": "master"},
            conn=conn, song_id=sid, complement=True,
        )
    with pytest.raises(ValueError, match="complement"):
        node_ref_from_addr(
            {"parent": {"kind": "return", "index": 1}, "terminal": "return"},
            conn=conn, song_id=sid, complement=True,
        )


def test_malformed_addresses_teach(tmp_path: Path):
    conn, sid, *_ = _song_with_nodes(tmp_path)
    with pytest.raises(ValueError, match="parent"):
        node_ref_from_addr({"terminal": "track"}, conn=conn, song_id=sid)
    with pytest.raises(ValueError, match="does not match"):
        node_ref_from_addr(
            {"parent": {"kind": "track", "index": 1}, "terminal": "return"}, conn=conn, song_id=sid
        )
    with pytest.raises(ValueError, match="positive int"):
        node_ref_from_addr(
            {"parent": {"kind": "track", "index": 0}, "terminal": "track"}, conn=conn, song_id=sid
        )
