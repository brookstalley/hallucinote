"""The store hands out sources, writes the manifest atomically, and verifies both."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import store
from hallucinote.assets.manifest import MANIFEST_VERSION, Manifest, ManifestEntry


def _write_wav(path, *, seconds: float = 0.5, sample_rate: int = 44_100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    audio = (0.3 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32).reshape(-1, 1)
    sf.write(str(path), audio, sample_rate, subtype="FLOAT")


def _entry(name: str, checksum: str, **over) -> ManifestEntry:
    base = dict(
        name=name,
        path=store.source_ref(name),
        checksum=checksum,
        sample_rate=44_100,
        channels=1,
        duration_s=0.5,
        note=f"what {name} is",
        origin="a film, a scene",
        original_filename=f"{name}.wav",
        original_format="wav",
        original_lossy=False,
        ingested_at="2026-09-09T21:34:00Z",
    )
    base.update(over)
    return ManifestEntry(**base)


def _song_with_source(tmp_path, name: str = "rivers-01"):
    """A song dir holding one real WAV and a manifest that describes it."""
    path = store.source_path(tmp_path, name)
    _write_wav(path)
    entry = _entry(name, store.file_checksum(path))
    store.write_manifest(tmp_path, Manifest(entries=(entry,)))
    return entry


def test_a_song_with_no_manifest_reports_no_sources(tmp_path):
    assert store.load_manifest(tmp_path).entries == ()
    assert store.sources(tmp_path) == []


def test_the_manifest_lands_where_the_store_says_and_reads_back(tmp_path):
    entry = _song_with_source(tmp_path)
    written = store.manifest_path(tmp_path)
    assert written == tmp_path / "assets" / "manifest.json"
    assert store.load_manifest(tmp_path).get(entry.name) == entry


def test_the_manifest_write_leaves_no_temp_file_behind(tmp_path):
    _song_with_source(tmp_path)
    leftovers = list((tmp_path / "assets").glob("*.tmp"))
    assert leftovers == []


def test_the_manifest_is_json_a_human_can_read_and_diff(tmp_path):
    _song_with_source(tmp_path)
    text = store.manifest_path(tmp_path).read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["manifest_version"] == MANIFEST_VERSION
    assert "rivers-01" in data["sources"]
    assert text.endswith("\n")


def test_unreadable_json_is_refused_rather_than_overwritten(tmp_path):
    path = store.manifest_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        store.load_manifest(tmp_path)


def test_sources_come_back_as_value_objects_in_name_order(tmp_path):
    for name in ("zulu", "alpha"):
        path = store.source_path(tmp_path, name)
        _write_wav(path)
    manifest = Manifest(
        entries=tuple(
            _entry(name, store.file_checksum(store.source_path(tmp_path, name)))
            for name in ("zulu", "alpha")
        )
    )
    store.write_manifest(tmp_path, manifest)

    found = store.sources(tmp_path)
    assert [s.name for s in found] == ["alpha", "zulu"]
    assert found[0].path == tmp_path / "assets" / "sources" / "alpha.wav"


def test_one_source_comes_back_by_name(tmp_path):
    _song_with_source(tmp_path)
    source = store.source(tmp_path, "rivers-01")
    assert source.sample_rate == 44_100
    assert source.path.is_file()


def test_an_unknown_name_says_what_the_song_does_have(tmp_path):
    _song_with_source(tmp_path)
    with pytest.raises(KeyError) as excinfo:
        store.source(tmp_path, "nope")
    message = str(excinfo.value)
    assert "rivers-01" in message
    assert "asset add" in message


def test_a_verified_store_reports_no_problems(tmp_path):
    _song_with_source(tmp_path)
    assert store.verify(tmp_path) == []


def test_verify_catches_a_source_edited_in_place(tmp_path):
    _song_with_source(tmp_path)
    _write_wav(store.source_path(tmp_path, "rivers-01"), seconds=0.75)

    problems = store.verify(tmp_path)
    assert [p.kind for p in problems] == ["checksum-mismatch"]
    assert "immutable" in problems[0].detail
    assert "--replace" in problems[0].detail


def test_verify_catches_a_source_that_is_gone(tmp_path):
    _song_with_source(tmp_path)
    store.source_path(tmp_path, "rivers-01").unlink()

    problems = store.verify(tmp_path)
    assert [p.kind for p in problems] == ["missing"]
    assert problems[0].name == "rivers-01"


def test_the_checksum_is_sha256_over_the_files_bytes(tmp_path):
    path = store.source_path(tmp_path, "rivers-01")
    _write_wav(path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert store.file_checksum(path) == expected


def test_the_reference_form_is_the_song_relative_posix_one():
    assert store.source_ref("rivers-01") == "assets/sources/rivers-01.wav"
