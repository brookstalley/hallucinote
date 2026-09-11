"""The manifest refuses a shape it cannot read rather than half-reading it."""
from __future__ import annotations

import pytest

from hallucinote.assets.manifest import (
    MANIFEST_VERSION,
    Manifest,
    ManifestEntry,
    parse_manifest,
    validate_name,
)

_SHA = "b" * 64
_OTHER_SHA = "c" * 64


def _entry(**over) -> ManifestEntry:
    base = dict(
        name="rivers-01",
        path="assets/sources/rivers-01.wav",
        checksum=_SHA,
        sample_rate=44_100,
        channels=1,
        duration_s=2.5,
        note="the pilot's last transmission",
        origin="Rivers of Sand (1974), reel 3",
        original_filename="rivers.mp3",
        original_format="mp3",
        original_lossy=True,
        ingested_at="2026-09-09T21:34:00Z",
    )
    base.update(over)
    return ManifestEntry(**base)


def test_a_manifest_round_trips_through_its_json_shape():
    manifest = Manifest(entries=(_entry(),))
    reparsed = parse_manifest(manifest.to_dict(), where="test")
    assert reparsed == manifest


def test_the_entry_carries_every_provenance_question_the_consumers_ask():
    data = _entry().to_dict()
    assert set(data) == {
        "path", "checksum", "sample_rate", "channels", "duration_s", "note",
        "origin", "original_filename", "original_format", "original_lossy",
        "ingested_at", "superseded",
    }


def test_entries_are_kept_in_name_order_whatever_order_they_arrive_in():
    manifest = Manifest(
        entries=(
            _entry(name="zulu", path="assets/sources/zulu.wav"),
            _entry(name="alpha", path="assets/sources/alpha.wav"),
        )
    )
    assert [e.name for e in manifest.entries] == ["alpha", "zulu"]


def test_with_entry_replaces_the_occupant_of_a_slot():
    manifest = Manifest(entries=(_entry(),))
    updated = manifest.with_entry(_entry(checksum=_OTHER_SHA))
    assert len(updated.entries) == 1
    assert updated.entries[0].checksum == _OTHER_SHA


def test_an_unknown_manifest_version_is_refused_with_what_to_do():
    with pytest.raises(ValueError) as excinfo:
        parse_manifest(
            {"manifest_version": MANIFEST_VERSION + 1, "sources": {}},
            where="assets/manifest.json",
        )
    message = str(excinfo.value)
    assert "manifest_version" in message
    assert "Update Hallucinote" in message


def test_a_manifest_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError, match="manifest is a JSON object"):
        parse_manifest([1, 2, 3], where="assets/manifest.json")


def test_a_source_entry_missing_a_field_names_the_field():
    data = {"manifest_version": MANIFEST_VERSION, "sources": {"x": {"path": "a.wav"}}}
    with pytest.raises(ValueError) as excinfo:
        parse_manifest(data, where="assets/manifest.json")
    assert "checksum" in str(excinfo.value)
    assert "note" in str(excinfo.value)


def test_a_non_object_source_entry_is_refused():
    data = {"manifest_version": MANIFEST_VERSION, "sources": {"x": "a.wav"}}
    with pytest.raises(ValueError, match="must be an object"):
        parse_manifest(data, where="assets/manifest.json")


@pytest.mark.parametrize(
    "name", ["", "with space", "../escape", "sub/dir", "-leading-dash"]
)
def test_a_name_that_cannot_be_a_filename_is_refused(name):
    with pytest.raises(ValueError, match="not usable"):
        validate_name(name)


@pytest.mark.parametrize("name", ["rivers-01", "line_2", "a.b", "X9"])
def test_an_ordinary_name_is_accepted(name):
    assert validate_name(name) == name


def test_an_absolute_source_path_is_refused_as_unportable():
    with pytest.raises(ValueError, match="song-relative"):
        _entry(path="/Users/someone/rivers.wav")


def test_a_malformed_checksum_is_refused():
    with pytest.raises(ValueError, match="sha256"):
        _entry(checksum="not-a-digest")


def test_a_malformed_superseded_checksum_is_refused():
    with pytest.raises(ValueError, match="superseded"):
        _entry(superseded=("short",))


@pytest.mark.parametrize(
    "field,value", [("sample_rate", 0), ("channels", 0), ("duration_s", -0.5)]
)
def test_impossible_audio_properties_are_refused(field, value):
    with pytest.raises(ValueError, match=field):
        _entry(**{field: value})


def test_as_source_resolves_the_song_relative_path(tmp_path):
    source = _entry().as_source(tmp_path)
    assert source.path == tmp_path / "assets" / "sources" / "rivers-01.wav"
    assert source.name == "rivers-01"
