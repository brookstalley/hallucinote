"""cache_ascl: writes under songs/<slug>/tunings/ and returns a song-relative ref."""
from __future__ import annotations

from hallucinote.tuning.cache import cache_ascl

from .fixtures import EDO_19, parse_scl


def test_writes_file_and_returns_relative_ref(tmp_path):
    ref = cache_ascl(tmp_path, EDO_19)
    assert ref == "tunings/19-edo.ascl"            # POSIX, song-relative, slugged
    written = tmp_path / "tunings" / "19-edo.ascl"
    assert written.is_file()
    # The cached file is the writer's output, re-readable.
    _, count, _ = parse_scl(written.read_text(encoding="utf-8"))
    assert count == EDO_19.step_count


def test_creates_tunings_dir_if_absent(tmp_path):
    assert not (tmp_path / "tunings").exists()
    cache_ascl(tmp_path, EDO_19)
    assert (tmp_path / "tunings").is_dir()


def test_is_idempotent_byte_identical(tmp_path):
    ref1 = cache_ascl(tmp_path, EDO_19)
    first = (tmp_path / ref1).read_bytes()
    ref2 = cache_ascl(tmp_path, EDO_19)
    second = (tmp_path / ref2).read_bytes()
    assert ref1 == ref2
    assert first == second  # deterministic content → immutable in practice


def test_written_as_utf8(tmp_path):
    from hallucinote.tuning.model import TuningData

    t = TuningData(
        name="Pélog ♯", step_count=1, period_cents=1200.0,
        reference_note=60, step_cents=(1200.0,),
    )
    ref = cache_ascl(tmp_path, t)
    # Decodes as UTF-8 without error and preserves the glyphs.
    text = (tmp_path / ref).read_text(encoding="utf-8")
    assert "♯" in text


def test_degenerate_name_still_yields_a_valid_filename(tmp_path):
    from hallucinote.tuning.model import TuningData

    t = TuningData(
        name="///", step_count=1, period_cents=1200.0,
        reference_note=60, step_cents=(1200.0,),
    )
    ref = cache_ascl(tmp_path, t)
    assert ref == "tunings/tuning.ascl"
    assert (tmp_path / ref).is_file()
