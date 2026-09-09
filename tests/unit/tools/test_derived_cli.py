"""`hallucinote derived verify|prune` — the CLI over the derived cache's lifecycle.

The subject is the CLI's own judgement, not the cache's: which exit code each
outcome earns, and — the reason this file exists — that `prune` refuses to
answer when it could not read what the song references. An empty reference set
condemns every file in the cache, so "the song references nothing" and "I could
not find the song's database" must never take the same branch.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import derived as D
from hallucinote.assets.transforms import normalize, reverse
from hallucinote.assets.types import Source
from hallucinote.db.connection import init_db
from hallucinote.tools import derived_cli
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE


def _write_source(song_dir: Path, name: str, audio: np.ndarray) -> Source:
    path = song_dir / "assets" / "sources" / f"{name}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, SR, subtype="FLOAT")
    return Source(
        name=name, path=path.relative_to(song_dir), checksum=D.sha256_file(path),
        sample_rate=SR, channels=audio.shape[1], duration_s=audio.shape[0] / SR,
    )


@pytest.fixture
def song(tmp_path: Path) -> tuple[Path, Source]:
    return tmp_path, _write_source(tmp_path, "rivers-01", sine(220.0, 1.0))


def _song_db(song_dir: Path, slug: str, audio_files: list[str]) -> Path:
    """A minimal song DB whose clips point at `audio_files` — what prune reads."""
    db_path = song_dir / f"{slug}.db"
    conn = init_db(db_path)
    try:
        conn.execute("INSERT INTO songs (id, name) VALUES ('s1', ?)", (slug,))
        conn.execute(
            "INSERT INTO tracks (id, song_id, track_index, name, kind) "
            "VALUES ('t1', 's1', 0, 'sampler', 'audio')"
        )
        for i, audio_file in enumerate(audio_files):
            conn.execute(
                "INSERT INTO clips (id, track_id, slot, length_beats, name, kind, audio_file) "
                "VALUES (?, 't1', ?, 4.0, ?, 'audio', ?)",
                (f"c{i}", i + 1, f"clip-{i}", audio_file),
            )
    finally:
        conn.close()
    return db_path


# --- verify ----------------------------------------------------------------


def test_verify_reports_nothing_when_the_cache_is_empty(song, capsys):
    song_dir, _ = song
    assert derived_cli.main(["verify", "--song-dir", str(song_dir)]) == 0
    assert "nothing under" in capsys.readouterr().out


def test_verify_exits_zero_when_every_file_is_intact(song, capsys):
    song_dir, src = song
    D.derive(src, [reverse()], song_dir=song_dir)
    assert derived_cli.main(["verify", "--song-dir", str(song_dir)]) == 0
    out = capsys.readouterr().out
    assert "valid" in out and "0 with a problem" in out


def test_verify_exits_three_when_a_file_was_edited_after_it_was_derived(song, capsys):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    sf.write(str(d.path), sine(440.0, 1.0), SR, subtype="FLOAT")
    assert derived_cli.main(["verify", "--song-dir", str(song_dir)]) == 3
    out = capsys.readouterr().out
    assert "modified" in out and "1 with a problem" in out


# --- prune -----------------------------------------------------------------


def test_prune_keeps_what_the_song_references_and_lists_the_rest(song, capsys):
    """The ordinary case: a DB holding BOTH a source path and a derived path.

    The source row is why this CLI shipped broken — it reached `_address_of`,
    which raised, so `prune` traceback'd on any song with an ingested source.
    """
    song_dir, src = song
    keep = D.derive(src, [reverse()], song_dir=song_dir)
    orphan = D.derive(src, [normalize()], song_dir=song_dir)
    _song_db(song_dir, "rivers", [
        "assets/sources/rivers-01.wav",
        str(keep.path.relative_to(song_dir)),
    ])

    code = derived_cli.main(["prune", "--song", "rivers", "--song-dir", str(song_dir)])

    out = capsys.readouterr().out
    assert code == 0
    assert orphan.path.name in out and orphan.record_path.name in out
    assert keep.path.name not in out
    assert orphan.path.is_file(), "prune lists; the deletion is the user's"


def test_prune_refuses_without_a_song_rather_than_condemning_the_cache(song, capsys):
    song_dir, src = song
    D.derive(src, [reverse()], song_dir=song_dir)

    code = derived_cli.main(["prune", "--song-dir", str(song_dir)])

    captured = capsys.readouterr()
    assert code == 2
    assert "no --song was given" in captured.err
    assert "--song <slug>" in captured.err
    assert captured.out == "", "a refusal must not also print an orphan list"


def test_prune_refuses_when_the_songs_database_is_missing(song, capsys):
    song_dir, src = song
    D.derive(src, [reverse()], song_dir=song_dir)

    code = derived_cli.main(["prune", "--song", "rivers", "--song-dir", str(song_dir)])

    captured = capsys.readouterr()
    assert code == 2
    assert "no database for song 'rivers'" in captured.err
    assert captured.out == ""


def test_prune_reports_a_fully_referenced_cache_as_nothing_to_remove(song, capsys):
    song_dir, src = song
    keep = D.derive(src, [reverse()], song_dir=song_dir)
    _song_db(song_dir, "rivers", [str(keep.path.relative_to(song_dir))])

    code = derived_cli.main(["prune", "--song", "rivers", "--song-dir", str(song_dir)])

    assert code == 0
    assert "nothing to remove" in capsys.readouterr().out


def test_prune_reads_the_db_in_the_directory_it_is_pruning(song, tmp_path, capsys):
    """--song-dir wins over wherever the workspace resolves the slug.

    A same-slug song elsewhere must not decide what is an orphan here: the
    cache being pruned and the clips deciding what it keeps have to be the
    same song, or prune lists files the song is still using.
    """
    song_dir, src = song
    keep = D.derive(src, [reverse()], song_dir=song_dir)
    # The song being pruned keeps its derived file...
    _song_db(song_dir, "rivers", [str(keep.path.relative_to(song_dir))])
    # ...while a same-slug song elsewhere references nothing of the sort.
    other = tmp_path.parent / "elsewhere"
    other.mkdir(exist_ok=True)
    _song_db(other, "rivers", ["assets/sources/unrelated.wav"])

    code = derived_cli.main(["prune", "--song", "rivers", "--song-dir", str(song_dir)])

    assert code == 0
    assert "nothing to remove" in capsys.readouterr().out
    assert keep.path.is_file()
