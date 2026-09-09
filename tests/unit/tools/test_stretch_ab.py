"""tools/stretch_ab.py — the R6.2 listening harness.

Covers what the harness owes its reader: it renders every backend that is
present, it names the missing half of an absent one rather than skipping it, the
table lists exactly the files that were written, and it refuses a request that
is not a transform. Rubber Band is exercised through an injected fake — the real
package is an optional extra plus a non-Python binary, so a test that needed
either would be a test that never runs.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import soundfile as sf

from hallucinote.tools.stretch_ab import (
    main,
    params_slug,
    render_all,
    render_table,
    rubberband_absence,
)

from tests.unit.audio import fixtures

# The harness loads librosa; keep it selectable with the rest of the DSP suite.
pytestmark = pytest.mark.audio


def _write_source(tmp_path: Path) -> Path:
    """A short two-tone source — enough spectral movement for a centroid to be
    a real number rather than a single bin."""
    audio = fixtures.concat(
        fixtures.sine(220.0, 0.4), fixtures.sine(660.0, 0.4)
    )
    path = tmp_path / "line.wav"
    sf.write(str(path), audio, fixtures.SAMPLE_RATE, subtype="PCM_24")
    return path


def _install_fake_rubberband(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, object]]
) -> None:
    """A binary on PATH and a ``subprocess.run`` that records its argv and
    copies the input to the output — the identity keeps its centroid
    distinguishable from librosa's."""
    real_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, *a, **kw: (
            "/usr/local/bin/rubberband"
            if name == "rubberband"
            else real_which(name, *a, **kw)
        ),
    )

    def fake_run(args, **kwargs):
        calls.append({"args": list(args)})
        shutil.copyfile(args[-2], args[-1])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _absent_rubberband(monkeypatch: pytest.MonkeyPatch) -> None:
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which",
        lambda name, *a, **kw: None if name == "rubberband" else real_which(name, *a, **kw),
    )


def test_librosa_alone_renders_one_file_and_reports_rubberband_absent(
    tmp_path, monkeypatch
):
    _absent_rubberband(monkeypatch)
    out = tmp_path / "ab"
    source_centroid, rows = render_all(
        _write_source(tmp_path), out, rate=1.0, semitones=-3.0, formant=True
    )

    written = sorted(p.name for p in out.iterdir())
    assert written == [f"librosa-{params_slug(rate=1.0, semitones=-3.0)}.wav"]
    assert source_centroid > 0.0

    librosa_row, rubberband_row = rows
    assert librosa_row.backend == "librosa"
    assert librosa_row.path is not None and librosa_row.path.is_file()
    assert librosa_row.centroid_hz is not None
    assert rubberband_row.path is None
    # The absence names WHICH half is missing, so the reader knows what to do.
    assert "rubberband binary is not on PATH" in (rubberband_row.absent_reason or "")
    assert "brew install rubberband" in (rubberband_row.absent_reason or "")


def test_a_present_rubberband_renders_a_second_file_with_formants_preserved(
    tmp_path, monkeypatch
):
    calls: list[dict[str, object]] = []
    _install_fake_rubberband(monkeypatch, calls)
    out = tmp_path / "ab"
    _, rows = render_all(
        _write_source(tmp_path), out, rate=0.8, semitones=2.0, formant=True
    )

    slug = params_slug(rate=0.8, semitones=2.0)
    assert sorted(p.name for p in out.iterdir()) == [
        f"librosa-{slug}.wav",
        f"rubberband-{slug}-formant.wav",
    ]
    assert all(row.path is not None for row in rows)
    assert len(calls) == 1, "one invocation carries both the stretch and the shift"
    args = calls[0]["args"]
    assert "-F" in args and "-t" in args and "-p" in args
    assert args[args.index("-t") + 1] == f"{1.0 / 0.8:g}"
    assert args[args.index("-p") + 1] == "2"


def test_no_formant_drops_the_flag_and_the_filename_says_so(
    tmp_path, monkeypatch
):
    calls: list[dict[str, object]] = []
    _install_fake_rubberband(monkeypatch, calls)
    out = tmp_path / "ab"
    render_all(
        _write_source(tmp_path), out, rate=1.0, semitones=5.0, formant=False
    )

    slug = params_slug(rate=1.0, semitones=5.0)
    assert (out / f"rubberband-{slug}.wav").is_file()
    assert not (out / f"rubberband-{slug}-formant.wav").exists()
    assert all("-F" not in call["args"] for call in calls)


def test_an_identity_parameter_costs_no_backend_pass(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []
    _install_fake_rubberband(monkeypatch, calls)
    render_all(
        _write_source(tmp_path),
        tmp_path / "ab",
        rate=1.0,
        semitones=3.0,
        formant=True,
    )
    # rate 1.0 is the identity, so only the pitch half runs.
    assert len(calls) == 1 and "-p" in calls[0]["args"] and "-t" not in calls[0]["args"]


def test_the_table_lists_exactly_the_files_written(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []
    _install_fake_rubberband(monkeypatch, calls)
    source = _write_source(tmp_path)
    out = tmp_path / "ab"
    source_centroid, rows = render_all(
        source, out, rate=1.25, semitones=-1.0, formant=True
    )

    table = render_table(
        source, source_centroid, rows, rate=1.25, semitones=-1.0
    )
    written = {p.name for p in out.iterdir()}
    body = table.split("file\n", 1)[1]
    listed = {
        word
        for line in body.splitlines()
        for word in line.split()
        if word.endswith(".wav")
    }
    assert listed == written
    assert "line.wav" in table  # the source is named in the header, not listed
    assert "The harness has no opinion." in table


def test_the_table_carries_the_absence_and_no_verdict(tmp_path, monkeypatch):
    _absent_rubberband(monkeypatch)
    source = _write_source(tmp_path)
    source_centroid, rows = render_all(
        source, tmp_path / "ab", rate=1.0, semitones=-4.0, formant=True
    )
    table = render_table(
        source, source_centroid, rows, rate=1.0, semitones=-4.0
    )

    assert "absent: the rubberband binary is not on PATH" in table
    # The centroid is framed as a hint to read across backends, never a threshold.
    assert "not against zero" in table


def test_rubberband_absence_names_the_missing_binary(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **kw: None)
    reason = rubberband_absence()
    assert reason is not None
    assert "binary is not on PATH" in reason


def test_a_non_transform_is_refused_rather_than_rendered(tmp_path):
    with pytest.raises(ValueError, match="nothing to compare"):
        render_all(
            _write_source(tmp_path),
            tmp_path / "ab",
            rate=1.0,
            semitones=0.0,
            formant=True,
        )


def test_a_non_positive_rate_is_refused(tmp_path):
    with pytest.raises(ValueError, match="greater than 0"):
        render_all(
            _write_source(tmp_path),
            tmp_path / "ab",
            rate=0.0,
            semitones=1.0,
            formant=True,
        )


def test_main_prints_the_table_and_exits_zero(tmp_path, monkeypatch, capsys):
    _absent_rubberband(monkeypatch)
    source = _write_source(tmp_path)
    out = tmp_path / "ab"
    code = main([str(source), "--out", str(out), "--semitones", "-2"])

    assert code == 0
    printed = capsys.readouterr().out
    assert "stretch/pitch A/B — line.wav" in printed
    assert f"librosa-{params_slug(rate=1.0, semitones=-2.0)}.wav" in printed


def test_main_refuses_a_missing_source_with_a_teaching_message(
    tmp_path, capsys
):
    code = main(
        [
            str(tmp_path / "absent.wav"),
            "--out",
            str(tmp_path / "ab"),
            "--semitones",
            "2",
        ]
    )
    assert code == 2
    assert "no readable source" in capsys.readouterr().err


def test_main_separates_a_bad_parameter_from_an_unreadable_source(
    tmp_path, capsys
):
    source = _write_source(tmp_path)
    code = main([str(source), "--out", str(tmp_path / "ab")])
    assert code == 3
    assert "nothing to compare" in capsys.readouterr().err
