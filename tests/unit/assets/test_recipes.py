"""Recipes as values; verify tells the truth about each derived file; prune lists, never deletes."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import derived as D
from hallucinote.assets import recipes as R
from hallucinote.assets.transforms import normalize, reverse, trim
from hallucinote.assets.types import Source
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


def _statuses(results: list[R.VerifyResult]) -> dict[str, str]:
    return {r.path.name: r.status for r in results}


# --- Recipe ----------------------------------------------------------------


def test_recipe_resolves_to_the_same_address_derive_uses(song):
    song_dir, src = song
    recipe = R.Recipe("rivers-01", [trim(0.2, 0.8), normalize()])
    assert recipe.chain == (trim(0.2, 0.8), normalize())
    assert recipe.address(src) == D.address(src, recipe.chain)
    d = recipe.derive(src, song_dir=song_dir)
    assert d.address == recipe.address(src) and d.path.is_file()
    assert recipe.address(src, reference_fingerprint="fp") != recipe.address(src)


def test_recipe_refuses_a_source_of_another_name_and_a_bad_chain(song):
    _, src = song
    recipe = R.Recipe("other-line", [reverse()])
    with pytest.raises(ValueError, match="other-line"):
        recipe.address(src)
    with pytest.raises(ValueError, match="at least one transform"):
        R.Recipe("rivers-01", [])
    with pytest.raises(ValueError, match="not a Transform"):
        R.Recipe("rivers-01", ["reverse"])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="source_name"):
        R.Recipe("", [reverse()])


# --- verify ----------------------------------------------------------------


def test_verify_on_a_song_with_no_derived_dir_is_empty(tmp_path):
    assert R.verify(tmp_path) == []
    assert R.prune(tmp_path, []) == []


def test_verify_reports_intact_files_as_valid(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    results = R.verify(song_dir)
    assert len(results) == 1
    assert results[0].path == d.path and results[0].address == d.address
    assert results[0].status == R.VALID and results[0].ok


def test_a_modified_derived_file_fails_verify(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    sf.write(str(d.path), np.zeros((10, 2), dtype=np.float32), SR, subtype="FLOAT")
    (result,) = R.verify(song_dir)
    assert result.status == R.MODIFIED and not result.ok
    assert "edited" in result.detail


def test_verify_reports_a_missing_output_and_an_unrecorded_file(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    d.path.unlink()
    stray = d.path.parent / ("f" * 64 + "-stray.wav")
    sf.write(str(stray), np.zeros((10, 2), dtype=np.float32), SR, subtype="FLOAT")
    statuses = _statuses(R.verify(song_dir))
    assert statuses == {d.path.name: R.MISSING_OUTPUT, stray.name: R.UNRECORDED}
    assert all(not r.ok for r in R.verify(song_dir))


def test_verify_reports_an_edited_record_as_corrupt(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    text = d.record_path.read_text().replace('"kind": "reverse"', '"kind": "trim"')
    d.record_path.write_text(text)
    results = R.verify(song_dir)
    assert _statuses(results) == {d.record_path.name: R.CORRUPT_RECORD, d.path.name: R.UNRECORDED}
    assert "do not hash to its address" in results[0].detail
    d.record_path.write_text("{not json")
    (record_result, _) = R.verify(song_dir)
    assert record_result.status == R.CORRUPT_RECORD and "not valid JSON" in record_result.detail


def test_verify_reports_a_misnamed_record_as_corrupt(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    misnamed = d.record_path.with_name("e" * 64 + ".json")
    d.record_path.rename(misnamed)
    results = R.verify(song_dir)
    assert results[0].path == misnamed and results[0].status == R.CORRUPT_RECORD


def test_a_file_made_by_another_backend_version_is_valid_never_stale(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    record = D.DerivedRecord.read(d.record_path)
    old_address = D.address(src, [reverse()], backend_version_override="0.0.1")
    old_wav = d.path.with_name(d.path.name.replace(d.address, old_address))
    d.path.rename(old_wav)
    D.DerivedRecord(
        address=old_address, source_name=record.source_name, source_checksum=record.source_checksum,
        chain=record.chain, backend=record.backend, backend_version="0.0.1",
        reference_fingerprint=None, outputs=(D.OutputRecord(old_wav.name, record.outputs[0].checksum),),
        created_at=record.created_at, library_versions=record.library_versions,
    ).write(d.record_path.with_name(f"{old_address}.json"))
    d.record_path.unlink()
    (result,) = R.verify(song_dir)
    assert result.status == R.MADE_BY_OLDER_BACKEND and result.ok
    assert "0.0.1" in result.detail and D.backend_version() in result.detail


# --- prune -----------------------------------------------------------------


def test_prune_lists_what_no_current_recipe_addresses(song):
    song_dir, src = song
    keep = D.derive(src, [reverse()], song_dir=song_dir)
    orphan = D.derive(src, [trim(0.1, 0.5)], song_dir=song_dir)
    stray = keep.path.parent / "notes.txt"
    stray.write_text("not a derived file")
    (keep.path.parent / ".gitkeep").write_text("")
    interrupted = keep.path.with_name(keep.path.name + ".tmp")
    interrupted.write_bytes(b"")
    orphans = R.prune(song_dir, [keep])
    assert orphans == sorted([orphan.path, orphan.record_path, stray, interrupted])
    assert orphan.path.is_file() and orphan.record_path.is_file()


def test_prune_accepts_addresses_and_paths_as_well_as_derived_values(song):
    song_dir, src = song
    keep = D.derive(src, [reverse()], song_dir=song_dir)
    orphan = D.derive(src, [normalize()], song_dir=song_dir)
    expected = [orphan.path, orphan.record_path]
    assert R.prune(song_dir, [keep.address]) == expected
    assert R.prune(song_dir, [keep.path]) == expected
    assert R.prune(song_dir, [str(keep.path)]) == expected
    assert R.prune(song_dir, [keep, orphan]) == []
    with pytest.raises(ValueError, match="neither a derived address nor"):
        R.prune(song_dir, ["some-clip.wav"])
