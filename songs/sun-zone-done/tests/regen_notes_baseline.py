"""Regenerate the note preservation baseline for sun-zone-done.

The baseline (`fixtures/notes_baseline.json`) locks every clip's note array
so the generator migration (build-plan Chunks 2-3) is provably
behavior-preserving — see `test_notes_match_baseline`.

Run this ONLY to establish the initial baseline, or to re-baseline after an
INTENTIONAL musical change (and say why in the commit). Never run it to
silence a failing preservation test.

    python songs/sun-zone-done/tests/regen_notes_baseline.py
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

_SONG_DIR = Path(__file__).resolve().parent.parent
_BUILD_PATH = _SONG_DIR / "build.py"
_TEST_PATH = Path(__file__).resolve().parent / "test_sun_zone_done_build.py"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "notes_baseline.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    build_mod = _load("sun_zone_done_build", _BUILD_PATH)
    test_mod = _load("sun_zone_done_test", _TEST_PATH)

    from hallucinote.db import init_db, queries as Q

    with tempfile.TemporaryDirectory() as tmp:
        build_mod.DB_PATH = Path(tmp) / "baseline.db"
        song_id = build_mod.build(reset=True)
        conn = init_db(build_mod.DB_PATH)
        try:
            snapshot = test_mod.extract_notes(conn, song_id)
        finally:
            conn.close()

    _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    _FIXTURE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

    total = sum(len(c["notes"]) for clips in snapshot.values()
                for c in clips.values())
    print(f"Wrote {_FIXTURE.relative_to(_SONG_DIR.parent.parent)}")
    print(f"  tracks={len(snapshot)} "
          f"clips={sum(len(c) for c in snapshot.values())} notes={total}")


if __name__ == "__main__":
    main()
