"""Verify a scaffolded song in-process — the shape checks, without a test runner.

`/song-new` resolves ONE interpreter (`$PY`, from `ableton://server/info`) and runs
every step with it. That interpreter is the plugin's inline uv env, which ships the
engine and nothing else — no pytest, no pip — so the stage's old step 4
(`pytest songs/<slug>/tests/ -v`) could not be run with the interpreter the skill
itself tells you to use, and the stage's exit criterion ("the scaffold builds and its
shape tests pass") was unmeetable as written.

This module removes the dependency instead of documenting around it: it runs the same
shape checks the scaffolded test file runs, in-process, so `"$PY" -m hallucinote.cli
verify-scaffold <slug>` closes the criterion with the one interpreter already in hand.
The scaffolded `tests/test_<slug>_build.py` is untouched and still ships — it is the
song's own regression suite, run from an env that HAS pytest as the song matures.

**The build runs against a throwaway DB.** `build(reset=True)` wipes build.py-authored
content, so pointing it at the song's real DB would make verification destructive. The
module redirects the build module's ``DB_PATH`` into a temp dir first — the same
redirect the scaffolded test does with ``monkeypatch`` — and the song's own DB is never
opened.

**Declared values are the caller's to supply.** The scaffolded test compares the DB
against literals baked in at scaffold time; here the equivalent comparison is against
``--expect-sections`` / ``--expect-tempo`` / ``--expect-signature``, which `/song-new`
passes from the brief it just scaffolded from. Without them those three checks report
``skipped`` and say so — the structural half still runs, and nothing pretends to have
checked a value it was never given.

CLI:
    python -m hallucinote.tools.verify_scaffold <slug> [--root songs] \
        [--expect-sections intro,verse,chorus] [--expect-tempo 120] \
        [--expect-signature 4/4]

Exit codes: 0 every check passed (or was skipped), 1 a check failed, 2 the song could
not be verified at all (bad slug, missing directory, no build.py).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hallucinote.tools.scaffold_song import (
    parse_sections,
    parse_signature,
    slug_to_python,
    validate_slug,
)

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

# 4 MIDI tracks from the synthetic snapshot + master. The scaffolded test asserts
# `>= 5` for the same reason: authoring adds tracks, it never removes the floor.
MIN_TRACKS = 5

_STATE_EVENT_SQL = (
    "SELECT COUNT(*) AS n FROM events "
    "WHERE kind NOT IN ('request_created', 'request_closed')"
)


@dataclass(frozen=True)
class Check:
    """One named check and how it came out. ``detail`` is shown either way."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class VerifyReport:
    slug: str
    song_dir: Path
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        """A skipped check is not a failure — it is a check nobody asked for."""
        return not any(c.status == FAILED for c in self.checks)

    def describe(self) -> str:
        width = max((len(c.name) for c in self.checks), default=0)
        mark = {OK: "PASS", FAILED: "FAIL", SKIPPED: "SKIP"}
        lines = [f"verify-scaffold {self.slug}  ({self.song_dir})"]
        for c in self.checks:
            lines.append(f"  {mark[c.status]}  {c.name.ljust(width)}  {c.detail}")
        failed = [c.name for c in self.checks if c.status == FAILED]
        if failed:
            lines.append(f"FAILED: {', '.join(failed)}")
        else:
            lines.append("scaffold verified: it builds and its shape checks pass")
        return "\n".join(lines)


# The files the scaffolder writes. A missing one is worth naming before the build
# fails on it with a stack trace three frames deep.
def _required_paths(slug: str) -> list[str]:
    return [
        "build.py",
        "captured_session.json",
        f"{slug}.md",
        f"tests/test_{slug_to_python(slug)}_build.py",
        "decisions",
        "annotations",
        "attempts",
    ]


def _load_build_module(build_path: Path, slug: str):
    """Import `songs/<slug>/build.py` as a module object, without installing it."""
    spec = importlib.util.spec_from_file_location(
        f"{slug_to_python(slug)}_build_verify", build_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        raise ImportError(f"cannot load {build_path} as a module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_scaffold(
    slug: str,
    *,
    songs_root: Path = Path("songs"),
    expect_sections: tuple[str, ...] | None = None,
    expect_tempo: float | None = None,
    expect_signature: tuple[int, int] | None = None,
) -> VerifyReport:
    """Run the scaffold's shape checks against `songs_root/<slug>/`.

    Raises ``ValueError`` on a malformed slug and ``FileNotFoundError`` when there is
    no song (or no ``build.py``) to verify — those are refusals, not failed checks.
    """
    validate_slug(slug)
    song_dir = songs_root / slug
    if not song_dir.is_dir():
        raise FileNotFoundError(
            f"no song at {song_dir}/ — scaffold it first "
            f"(hallucinote scaffold {slug} …), or pass --root."
        )
    build_path = song_dir / "build.py"
    if not build_path.is_file():
        raise FileNotFoundError(
            f"{build_path} is missing — this is not a scaffolded song directory."
        )

    checks: list[Check] = []

    missing = [p for p in _required_paths(slug) if not (song_dir / p).exists()]
    checks.append(
        Check("files", FAILED, f"missing from the scaffold: {', '.join(missing)}")
        if missing
        else Check("files", OK, f"{len(_required_paths(slug))} scaffold paths present")
    )

    from hallucinote.db import init_db, queries as Q

    with tempfile.TemporaryDirectory(prefix=f"verify-scaffold-{slug}-") as tmp:
        db_path = Path(tmp) / f"{slug}.db"
        song_id: str | None = None
        build_error: Exception | None = None
        module = None
        # build.py's own chatter is diagnostic, not the report — send it to stderr so
        # stdout carries only the check results.
        with contextlib.redirect_stdout(sys.stderr):
            try:
                module = _load_build_module(build_path, slug)
                module.DB_PATH = db_path
                song_id = module.build(reset=True)
            except Exception as e:  # prawduct:allow prawduct/broad-except -- build.py is user code; any failure is a reportable check failure, not a crash
                build_error = e

        if build_error is not None:
            checks.append(
                Check(
                    "build",
                    FAILED,
                    f"build.py --reset raised "
                    f"{type(build_error).__name__}: {build_error}",
                )
            )
            for name in ("sections", "tracks", "tempo", "signature", "converger"):
                checks.append(Check(name, SKIPPED, "the build did not complete"))
            return VerifyReport(slug=slug, song_dir=song_dir, checks=tuple(checks))

        if not song_id:
            checks.append(
                Check("build", FAILED, "build.py --reset returned no song_id")
            )
            for name in ("sections", "tracks", "tempo", "signature", "converger"):
                checks.append(Check(name, SKIPPED, "the build produced no song"))
            return VerifyReport(slug=slug, song_dir=song_dir, checks=tuple(checks))

        checks.append(Check("build", OK, f"build.py --reset → song_id {song_id}"))

        conn = init_db(db_path)
        try:
            section_names = [s["name"] for s in Q.get_sections_for_song(conn, song_id)]
            checks.append(_check_sections(section_names, expect_sections))

            tracks = Q.get_tracks_for_song(conn, song_id)
            checks.append(
                Check("tracks", OK, f"{len(tracks)} tracks (>= {MIN_TRACKS})")
                if len(tracks) >= MIN_TRACKS
                else Check(
                    "tracks",
                    FAILED,
                    f"{len(tracks)} tracks — expected at least {MIN_TRACKS} "
                    f"(4 synthetic MIDI tracks + master)",
                )
            )

            checks.append(_check_tempo(Q.get_tempo_map(conn, song_id), expect_tempo))
            checks.append(
                _check_signature(
                    Q.get_time_signature_map(conn, song_id), expect_signature
                )
            )
            events_first = conn.execute(_STATE_EVENT_SQL).fetchone()["n"]
        finally:
            conn.close()

        checks.append(_check_converger(module, db_path, song_id, events_first))

    return VerifyReport(slug=slug, song_dir=song_dir, checks=tuple(checks))


def _check_sections(
    section_names: list[str], expected: tuple[str, ...] | None
) -> Check:
    if not section_names:
        return Check("sections", FAILED, "the build materialized no sections")
    if expected is None:
        return Check(
            "sections",
            SKIPPED,
            f"built {len(section_names)} sections "
            f"({', '.join(section_names)}); pass --expect-sections to compare",
        )
    if list(expected) != section_names:
        return Check(
            "sections",
            FAILED,
            f"expected {list(expected)}, built {section_names}",
        )
    return Check("sections", OK, f"{', '.join(section_names)}")


def _check_tempo(tempo_map, expected: float | None) -> Check:
    if not tempo_map:
        return Check("tempo", FAILED, "the build wrote no tempo point")
    actual = float(tempo_map[0]["tempo_bpm"])
    if expected is None:
        return Check(
            "tempo",
            SKIPPED,
            f"built {actual:g} BPM; pass --expect-tempo to compare",
        )
    if abs(actual - expected) > 1e-6:
        return Check("tempo", FAILED, f"expected {expected:g} BPM, built {actual:g}")
    return Check("tempo", OK, f"{actual:g} BPM")


def _check_signature(sig_map, expected: tuple[int, int] | None) -> Check:
    if not sig_map:
        return Check("signature", FAILED, "the build wrote no time-signature point")
    actual = (int(sig_map[0]["numerator"]), int(sig_map[0]["denominator"]))
    shown = f"{actual[0]}/{actual[1]}"
    if expected is None:
        return Check(
            "signature",
            SKIPPED,
            f"built {shown}; pass --expect-signature to compare",
        )
    if actual != expected:
        return Check(
            "signature",
            FAILED,
            f"expected {expected[0]}/{expected[1]}, built {shown}",
        )
    return Check("signature", OK, shown)


def _check_converger(module, db_path: Path, song_id: str, events_first: int) -> Check:
    """The load-bearing promise: a re-run over an existing DB is a no-op."""
    from hallucinote.db import init_db

    with contextlib.redirect_stdout(sys.stderr):
        try:
            song_id_2 = module.build(reset=False)
        except Exception as e:  # prawduct:allow prawduct/broad-except -- build.py is user code; a re-run failure is a reportable check failure
            return Check(
                "converger",
                FAILED,
                f"re-running build.py raised {type(e).__name__}: {e}",
            )

    if song_id_2 != song_id:
        return Check(
            "converger",
            FAILED,
            f"re-run returned a different song_id ({song_id_2} != {song_id})",
        )
    conn = init_db(db_path)
    try:
        events_after = conn.execute(_STATE_EVENT_SQL).fetchone()["n"]
    finally:
        conn.close()
    if events_after != events_first:
        return Check(
            "converger",
            FAILED,
            f"re-running the build produced {events_after - events_first} extra "
            f"state-change events — converger discipline broken",
        )
    return Check("converger", OK, "re-run produced zero net state-change events")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hallucinote verify-scaffold",
        description=(
            "Verify a scaffolded song's shape in-process — no pytest needed. "
            "Builds it against a throwaway DB; the song's own DB is untouched."
        ),
    )
    parser.add_argument("slug", help="the song's slug (e.g. 'punk-fate')")
    parser.add_argument(
        "--root", default="songs", help="root songs directory (default: songs)"
    )
    parser.add_argument(
        "--expect-sections",
        default=None,
        help="comma-separated section names the build must materialize, in order",
    )
    parser.add_argument(
        "--expect-tempo", type=float, default=None, help="BPM the build must write"
    )
    parser.add_argument(
        "--expect-signature",
        default=None,
        help="time signature the build must write (e.g. '4/4')",
    )

    args = parser.parse_args(argv)

    try:
        expect_sections = (
            tuple(parse_sections(args.expect_sections))
            if args.expect_sections is not None
            else None
        )
        expect_signature = (
            parse_signature(args.expect_signature)
            if args.expect_signature is not None
            else None
        )
        report = verify_scaffold(
            args.slug,
            songs_root=Path(args.root),
            expect_sections=expect_sections,
            expect_tempo=args.expect_tempo,
            expect_signature=expect_signature,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"verify-scaffold: {e}", file=sys.stderr)
        return 2

    print(report.describe())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
