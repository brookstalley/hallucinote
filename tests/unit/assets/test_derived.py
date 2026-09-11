"""The derived cache: one address per recipe, a hit costs no render, any change moves the file."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import derived as D
from hallucinote.assets.transforms import chop_at_onsets, normalize, reverse, trim
from hallucinote.assets.types import Derived, Source, TransformContext
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE


def _write_source(song_dir: Path, name: str, audio: np.ndarray, sr: int = SR) -> Source:
    path = song_dir / "assets" / "sources" / f"{name}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr, subtype="FLOAT")
    return Source(
        name=name, path=path.relative_to(song_dir), checksum=D.sha256_file(path),
        sample_rate=sr, channels=audio.shape[1], duration_s=audio.shape[0] / sr,
    )


def _pulsed_tone(n_pulses: int, *, lead_s: float = 0.3, period_s: float = 0.5,
                 burst_s: float = 0.1, sr: int = SR) -> np.ndarray:
    total = int(sr * (lead_s + period_s * n_pulses))
    buf = np.zeros((total, 2), dtype=np.float32)
    for k in range(n_pulses):
        start = int(sr * (lead_s + period_s * k))
        n = int(sr * burst_s)
        t = np.arange(n) / sr
        burst = (0.6 * np.sin(2 * np.pi * 440 * t) * np.exp(-t / (burst_s / 4))).astype(np.float32)
        buf[start:start + n, 0] = burst
        buf[start:start + n, 1] = burst
    return buf


@dataclass(frozen=True)
class counting_reverse:
    """A reverse that counts how often the cache made it work."""

    calls: list[int] = field(default_factory=list, compare=False, hash=False)
    kind: str = field(default="reverse", init=False)

    def params(self) -> dict[str, Any]:
        return {}

    def apply(self, audio: np.ndarray, sample_rate: int, ctx: TransformContext) -> np.ndarray:
        self.calls.append(1)
        return np.ascontiguousarray(audio[::-1])


@pytest.fixture
def song(tmp_path: Path) -> tuple[Path, Source]:
    ramp = np.linspace(0, 1, SR, dtype=np.float32)[:, None]
    return tmp_path, _write_source(tmp_path, "rivers-01", sine(220.0, 1.0) * ramp)


# --- address ---------------------------------------------------------------


def test_same_source_and_chain_give_the_same_address(song):
    _, src = song
    a = D.address(src, [trim(0.4, 2.1), normalize(peak_dbfs=-1.0)])
    b = D.address(src, (trim(0.4, 2.1), normalize(peak_dbfs=-1.0)))
    assert a == b and len(a) == 64


def test_any_parameter_change_moves_the_address(song):
    _, src = song
    base = D.address(src, [trim(0.4, 2.1)])
    assert D.address(src, [trim(0.4, 2.2)]) != base
    assert D.address(src, [trim(0.4, 2.1), reverse()]) != base
    assert D.address(src, [trim(0.4, 2.1)], reference_fingerprint="notes-abc") != base
    assert D.address(src, [trim(0.4, 2.1)], backend_version_override="0.0.1") != base
    other = Source(name=src.name, path=src.path, checksum="c" * 64, sample_rate=src.sample_rate,
                   channels=src.channels, duration_s=src.duration_s)
    assert D.address(other, [trim(0.4, 2.1)]) != base


def test_address_is_the_documented_sha256_of_canonical_json(song):
    _, src = song
    payload = {
        "source_checksum": src.checksum,
        "chain": [{"kind": "trim", "params": {"start_s": 0.4, "end_s": None}}],
        "backend": "librosa",
        "backend_version": D.backend_version(),
        "reference_fingerprint": None,
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert D.address(src, [trim(0.4)]) == expected


def test_address_refuses_an_empty_chain_and_a_non_transform(song):
    _, src = song
    with pytest.raises(ValueError, match="at least one transform"):
        D.address(src, [])
    with pytest.raises(ValueError, match="not a Transform"):
        D.address(src, ["reverse"])  # type: ignore[list-item]


def test_unhashable_params_are_refused_with_the_reason(song):
    _, src = song

    class Bad:
        kind = "bad"

        def params(self):
            return {"x": float("nan")}

        def apply(self, audio, sample_rate, ctx):
            return audio

    with pytest.raises(ValueError, match="plain JSON values"):
        D.address(src, [Bad()])


# --- derive: the cache -----------------------------------------------------


def test_derive_writes_the_file_and_record_under_the_address(song):
    song_dir, src = song
    d = D.derive(src, [reverse()], song_dir=song_dir)
    assert isinstance(d, Derived)
    assert d.address == D.address(src, [reverse()])
    assert d.path == song_dir / "assets" / "derived" / f"{d.address}-rivers-01-reverse.wav"
    assert d.record_path == song_dir / "assets" / "derived" / f"{d.address}.json"
    assert d.path.is_file() and d.record_path.is_file()
    assert d.outputs == (d.path,)
    assert d.source_checksum == src.checksum
    assert d.chain == (reverse(),)
    audio, sr = sf.read(str(d.path), dtype="float32", always_2d=True)
    original, _ = sf.read(str(song_dir / src.path), dtype="float32", always_2d=True)
    assert sr == SR
    np.testing.assert_array_equal(audio, original[::-1])
    assert sf.info(str(d.path)).subtype == "FLOAT"


def test_second_derive_returns_identical_bytes_without_running_the_chain(song):
    song_dir, src = song
    spy = counting_reverse()
    first = D.derive(src, [spy], song_dir=song_dir)
    assert spy.calls == [1]
    bytes_before = first.path.read_bytes()
    record_before = first.record_path.read_bytes()
    again = D.derive(src, [counting_reverse()], song_dir=song_dir)
    second_spy = counting_reverse()
    third = D.derive(src, [second_spy], song_dir=song_dir)
    assert spy.calls == [1] and second_spy.calls == []
    assert again.path == first.path == third.path
    assert first.path.read_bytes() == bytes_before
    assert first.record_path.read_bytes() == record_before


def test_reverse_of_reverse_derives_back_to_the_source_audio(song):
    song_dir, src = song
    d = D.derive(src, [reverse(), reverse()], song_dir=song_dir)
    audio, _ = sf.read(str(d.path), dtype="float32", always_2d=True)
    original, _ = sf.read(str(song_dir / src.path), dtype="float32", always_2d=True)
    np.testing.assert_array_equal(audio, original)


def test_a_splitting_transform_yields_one_output_per_pulse(tmp_path):
    src = _write_source(tmp_path, "hits", _pulsed_tone(4))
    d = D.derive(src, [chop_at_onsets(0.2), normalize()], song_dir=tmp_path)
    assert len(d.outputs) == 4
    assert d.path == d.outputs[0]
    assert [p.name for p in d.outputs] == [
        f"{d.address}-hits-chop-at-onsets-normalize-{i:02d}.wav" for i in range(1, 5)
    ]
    for p in d.outputs:
        assert p.is_file()
        audio, _ = sf.read(str(p), dtype="float32", always_2d=True)
        assert float(np.max(np.abs(audio))) == pytest.approx(10 ** (-1 / 20), rel=1e-3)
    record = D.DerivedRecord.read(d.record_path)
    assert [o.file for o in record.outputs] == [p.name for p in d.outputs]


def test_a_modified_output_is_a_miss_and_is_rendered_over(song):
    song_dir, src = song
    spy = counting_reverse()
    d = D.derive(src, [spy], song_dir=song_dir)
    good = d.path.read_bytes()
    sf.write(str(d.path), np.zeros((10, 2), dtype=np.float32), SR, subtype="FLOAT")
    again = D.derive(src, [spy], song_dir=song_dir)
    assert spy.calls == [1, 1]
    assert again.path == d.path and d.path.read_bytes() == good


def test_a_missing_output_with_a_record_is_rendered_over(song):
    song_dir, src = song
    spy = counting_reverse()
    d = D.derive(src, [spy], song_dir=song_dir)
    d.path.unlink()
    D.derive(src, [spy], song_dir=song_dir)
    assert spy.calls == [1, 1] and d.path.is_file()


def _age_record(d: Derived, src: Source, version: str) -> Path:
    """Rewrite a record as if an earlier backend made it, addressed by that version."""
    record = D.DerivedRecord.read(d.record_path)
    old_address = D.address(
        src, d.chain, record.reference_fingerprint, record.backend, backend_version_override=version
    )
    directory = d.record_path.parent
    outputs = []
    for o in record.outputs:
        renamed = o.file.replace(record.address, old_address)
        (directory / o.file).rename(directory / renamed)
        outputs.append(D.OutputRecord(renamed, o.checksum))
    old = D.DerivedRecord(
        address=old_address, source_name=record.source_name, source_checksum=record.source_checksum,
        chain=record.chain, backend=record.backend, backend_version=version,
        reference_fingerprint=record.reference_fingerprint, outputs=tuple(outputs),
        created_at=record.created_at, library_versions=record.library_versions,
    )
    d.record_path.unlink()
    old.write(directory / f"{old_address}.json")
    return directory / f"{old_address}.json"


def test_a_file_made_by_an_older_backend_is_returned_not_re_rendered(song):
    song_dir, src = song
    spy = counting_reverse()
    fresh = D.derive(src, [spy], song_dir=song_dir)
    old_record = _age_record(fresh, src, "0.0.1")
    assert not fresh.record_path.exists()
    again = D.derive(src, [spy], song_dir=song_dir)
    assert spy.calls == [1]
    assert again.record_path == old_record
    assert again.address != fresh.address and again.path.is_file()
    assert D.DerivedRecord.read(old_record).backend_version == "0.0.1"


def test_the_record_round_trips(song):
    song_dir, src = song
    d = D.derive(src, [trim(0.25, 0.75), normalize(peak_dbfs=-3.0)], song_dir=song_dir,
                 reference_fingerprint="clip-fp-123")
    record = D.DerivedRecord.read(d.record_path)
    assert record.address == d.address == record.recomputed_address()
    assert record.source_name == "rivers-01" and record.source_checksum == src.checksum
    assert record.chain == (
        {"kind": "trim", "params": {"start_s": 0.25, "end_s": 0.75}},
        {"kind": "normalize", "params": {"peak_dbfs": -3.0}},
    )
    assert record.backend == "librosa" and record.backend_version == D.backend_version()
    assert record.reference_fingerprint == "clip-fp-123" == d.reference_fingerprint
    assert record.outputs == (D.OutputRecord(d.path.name, D.sha256_file(d.path)),)
    assert record.created_at.endswith("+00:00")
    assert set(record.library_versions) == {"numpy", "soundfile"}
    on_disk = json.loads(d.record_path.read_text())
    assert on_disk["record_version"] == 1
    assert D.DerivedRecord.from_json(record.to_json()) == record
    assert on_disk == record.to_json()


def test_reference_fingerprint_separates_otherwise_equal_recipes(song):
    song_dir, src = song
    a = D.derive(src, [reverse()], song_dir=song_dir, reference_fingerprint="fp-a")
    b = D.derive(src, [reverse()], song_dir=song_dir, reference_fingerprint="fp-b")
    assert a.address != b.address and a.path != b.path


# --- derive: the source ----------------------------------------------------


def test_derive_refuses_a_source_whose_bytes_have_changed(song):
    song_dir, src = song
    sf.write(str(song_dir / src.path), sine(330.0, 1.0), SR, subtype="FLOAT")
    with pytest.raises(ValueError, match="has changed"):
        D.derive(src, [reverse()], song_dir=song_dir)


def test_derive_refuses_a_missing_source_by_name(song):
    song_dir, src = song
    (song_dir / src.path).unlink()
    with pytest.raises(FileNotFoundError, match="rivers-01"):
        D.derive(src, [reverse()], song_dir=song_dir)


def test_derive_refuses_a_manifest_sample_rate_the_file_contradicts(song):
    song_dir, src = song
    lying = Source(name=src.name, path=src.path, checksum=src.checksum, sample_rate=44100,
                   channels=src.channels, duration_s=src.duration_s)
    with pytest.raises(ValueError, match="44100"):
        D.derive(lying, [reverse()], song_dir=song_dir)


def test_an_absolute_source_path_is_used_as_is(song):
    song_dir, src = song
    absolute = Source(name=src.name, path=song_dir / src.path, checksum=src.checksum,
                      sample_rate=src.sample_rate, channels=src.channels, duration_s=src.duration_s)
    d = D.derive(absolute, [reverse()], song_dir=song_dir / "elsewhere")
    assert d.path.is_file() and d.path.parent == song_dir / "elsewhere" / "assets" / "derived"


def test_a_transform_error_leaves_no_record_behind(song):
    song_dir, src = song
    with pytest.raises(ValueError, match="past the end"):
        D.derive(src, [trim(5.0)], song_dir=song_dir)
    assert list((song_dir / "assets" / "derived").glob("*.json")) == []


def test_backend_version_names_an_uninstalled_backend():
    with pytest.raises(ValueError, match="not installed"):
        D.backend_version("no-such-backend-xyz")


def test_slug_is_a_readable_hint_after_the_hash():
    assert D.slug_for("Rivers 01 (take 2)", [trim(0.1), reverse()]) == "rivers-01-take-2-trim-reverse"
    assert D.slug_for("", []) == "derived"
    assert len(D.slug_for("x" * 200, [reverse()])) <= 60
    assert D.address_of_filename("a" * 64 + "-rivers-reverse.wav") == "a" * 64
    assert D.address_of_filename("a" * 64 + ".json") == "a" * 64
    assert D.address_of_filename("notes.txt") is None
