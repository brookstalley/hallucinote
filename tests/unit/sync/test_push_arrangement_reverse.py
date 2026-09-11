"""A reversed row's arrangement copy plays the same derived file its session clip does.

The session route (``test_push_clips_reverse.py``) re-points a ``reverse=1``
row at the content-addressed reversed file. The arrangement phase resolves the
same row on its own, so without the same route it would place the line
FORWARD in the timeline while the session clip ran it backwards — two truths
about one row. The forward case stays on the source path.
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push

SAMPLE_RATE = 8000


@pytest.fixture
def song_dir(tmp_path):
    (tmp_path / "assets" / "sources").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def conn(song_dir):
    c = init_db(song_dir / "rev-arr.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    sid = M.create_song(conn, name="dialogue", key="Dm")
    M.add_time_signature_point(conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4)
    return sid


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def audio_track(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Dialogue", kind="audio")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4)
    return tid


@pytest.fixture
def sample(song_dir) -> str:
    """A real, decodable line: a short ramp so reversal is observable."""
    ramp = np.linspace(0.0, 0.5, SAMPLE_RATE // 4, dtype=np.float32)[:, None]
    sf.write(song_dir / "assets" / "line.wav", ramp, SAMPLE_RATE, subtype="FLOAT")
    return "assets/line.wav"


def _plan(conn, *, song, session, track, clip, reverse):
    cid = M.create_audio_clip(
        conn, track_id=track, slot=1, length_beats=8.0,
        audio_file=clip, name="line", reverse=reverse,
    )
    M.add_arrangement_clip(conn, song_id=song, track_id=track, clip_id=cid, start_bar=3.0, end_bar=7.0)
    live = {4: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    return push.plan_push_arrangement(
        conn, song_id=song, session_id=session, live_arrangement_clips_by_track=live,
    )


def test_a_reversed_placement_creates_from_the_derived_file(
    conn, song, session, audio_track, sample, song_dir,
):
    plan = _plan(conn, song=song, session=session, track=audio_track, clip=sample, reverse=1)

    assert plan.blocked_reasons == []
    create = next(c for c in plan.calls if c.args.get("action") == "create")
    path = create.args["audio_path"]
    assert str(song_dir / "assets" / "derived") in path
    assert path != str(song_dir / "assets" / "line.wav")
    played, _ = sf.read(path, dtype="float32")
    source, _ = sf.read(song_dir / "assets" / "line.wav", dtype="float32")
    assert np.allclose(played[::-1].ravel(), source.ravel(), atol=1e-6)


def test_a_forward_placement_still_creates_from_the_source(
    conn, song, session, audio_track, sample, song_dir,
):
    plan = _plan(conn, song=song, session=session, track=audio_track, clip=sample, reverse=0)

    assert plan.blocked_reasons == []
    create = next(c for c in plan.calls if c.args.get("action") == "create")
    assert create.args["audio_path"] == str(song_dir / "assets" / "line.wav")
