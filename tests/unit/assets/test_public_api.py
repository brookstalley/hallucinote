"""The surface build.py imports: a name becomes a Source, a chain becomes a file."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote import assets
from hallucinote.assets import (
    Source,
    carve,
    derive,
    normalize,
    reference_of,
    reverse,
    song_dir_of,
    source,
    sources,
    trim,
    vocode,
)
from hallucinote.assets import derived as D
from hallucinote.assets import store, transforms
from hallucinote.assets.manifest import Manifest, ManifestEntry

_REPO = Path(__file__).resolve().parents[3]
SR = 44_100


def _write_wav(path: Path, *, seconds: float = 0.5) -> np.ndarray:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * SR), dtype=np.float64) / SR
    audio = (0.3 * np.sin(2.0 * np.pi * 440.0 * t) * np.linspace(0, 1, t.size)).astype(np.float32)
    audio = audio.reshape(-1, 1)
    sf.write(str(path), audio, SR, subtype="FLOAT")
    return audio


def _song_with_source(song_dir: Path, name: str = "rivers-01") -> ManifestEntry:
    path = store.source_path(song_dir, name)
    _write_wav(path)
    entry = ManifestEntry(
        name=name,
        path=store.source_ref(name),
        checksum=store.file_checksum(path),
        sample_rate=SR,
        channels=1,
        duration_s=0.5,
        note=f"what {name} is",
        origin="a film, a scene",
        original_filename=f"{name}.wav",
        original_format="wav",
        original_lossy=False,
        ingested_at="2026-09-09T21:34:00Z",
    )
    store.write_manifest(song_dir, Manifest(entries=(entry,)))
    return entry


# --- source ------------------------------------------------------------------


def test_source_resolves_a_manifest_entry_to_a_source(tmp_path):
    entry = _song_with_source(tmp_path)
    src = source(tmp_path, "rivers-01")
    assert isinstance(src, Source)
    assert src.path == tmp_path / "assets" / "sources" / "rivers-01.wav"
    assert src.checksum == entry.checksum
    assert (src.sample_rate, src.channels, src.duration_s) == (SR, 1, 0.5)
    assert sources(tmp_path) == [src]


def test_an_unknown_name_is_a_key_error_naming_what_the_song_has(tmp_path):
    _song_with_source(tmp_path)
    with pytest.raises(KeyError, match="rivers-01"):
        source(tmp_path, "rivers-02")


# --- derive ------------------------------------------------------------------


def test_derive_infers_the_song_dir_from_a_store_issued_source(tmp_path):
    _song_with_source(tmp_path)
    src = source(tmp_path, "rivers-01")
    d = derive(src, reverse())
    assert d.path.parent == tmp_path / "assets" / "derived"
    assert d.address == D.address(src, [reverse()])
    assert d.reference_fingerprint is None
    audio, _ = sf.read(str(d.path), dtype="float32", always_2d=True)
    original, _ = sf.read(str(src.path), dtype="float32", always_2d=True)
    np.testing.assert_array_equal(audio, original[::-1])


def test_derive_takes_a_chain_spread_or_as_one_list(tmp_path):
    _song_with_source(tmp_path)
    src = source(tmp_path, "rivers-01")
    spread = derive(src, trim(0.1, 0.4), normalize(peak_dbfs=-3.0))
    listed = derive(src, [trim(0.1, 0.4), normalize(peak_dbfs=-3.0)], song_dir=tmp_path)
    assert spread.address == listed.address == D.address(src, [trim(0.1, 0.4), normalize(-3.0)])
    assert spread.chain == (trim(0.1, 0.4), normalize(-3.0))


def test_derive_refuses_an_empty_chain(tmp_path):
    _song_with_source(tmp_path)
    with pytest.raises(ValueError, match="at least one transform"):
        derive(source(tmp_path, "rivers-01"))


def test_derive_needs_song_dir_for_a_source_it_cannot_place(tmp_path):
    stray = Source(
        name="stray", path=tmp_path / "elsewhere" / "stray.wav", checksum="a" * 64,
        sample_rate=SR, channels=1, duration_s=0.5,
    )
    with pytest.raises(ValueError, match="song_dir="):
        derive(stray, reverse())
    with pytest.raises(ValueError, match="song_dir="):
        song_dir_of(stray)
    assert song_dir_of(Source(
        name="placed", path=Path("assets/sources/placed.wav"), checksum="a" * 64,
        sample_rate=SR, channels=1, duration_s=0.5,
    )) == Path(".")


def test_a_score_free_chain_records_no_reference():
    assert reference_of([reverse(), trim(0.1)]) is None


# --- the surface -------------------------------------------------------------


def test_the_public_surface_names_every_transform():
    for name in transforms.__all__:
        assert name in assets.__all__, name
    assert "carve" in assets.__all__ and "vocode" in assets.__all__
    assert assets.carve is carve and assets.vocode is vocode
    for name in assets.__all__:
        assert hasattr(assets, name), name


def test_the_public_module_imports_without_the_db():
    probe = (
        "import sys, json\n"
        "import hallucinote.assets, hallucinote.assets.transforms_spectral\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith("
        "('hallucinote.db', 'hallucinote.sync', 'hallucinote_mcp')))))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, cwd=str(_REPO),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []
