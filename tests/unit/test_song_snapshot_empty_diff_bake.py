"""Doc-drift lock for /song-snapshot's empty-diff path (BAK-7D2V).

The skill IS the deliverable here — the agent copies these commands verbatim,
so a wrong command in the prose is a live bug no unit test of `capture.py`
would catch. (Project learning: "when a doc IS the deliverable, lock it with a
drift test".)

The regression this locks: the empty-diff path once ran `capture restamp`,
moving `captured_at` forward on the STALE on-disk snapshot. An empty
`capture diff` does not prove the snapshot is current — the diff never compares
device sidechain sources, drum-pad mappings, or per-chain authored props, all of
which `replay_capture` re-asserts (pinned in
`tests/unit/capture/test_diff_snapshots.py::test_diff_is_blind_to_replay_asserted_fields`).
So a pull touching only those fields diffed clean, the re-stamp disarmed the
replay guard over old values, and the next build silently reverted the pulled
by-ear work — precisely the failure the guard exists to prevent. The fix is to
bake the fresh capture (`capture merge`), which carries those fields AND a fresh
stamp.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SNAPSHOT_SKILL = _REPO / "skills" / "song-snapshot" / "SKILL.md"


def _empty_diff_section() -> str:
    """The prose between the exit-0 branch and the exit-1 branch — the block the
    agent follows when `capture diff` reports no changes."""
    text = _SNAPSHOT_SKILL.read_text(encoding="utf-8")
    start = text.index("**If exit 0")
    end = text.index("**If exit 1")
    assert start < end, "song-snapshot skill: exit-0 branch must precede exit-1"
    return text[start:end]


def test_empty_diff_path_bakes_the_refresh_instead_of_restamping():
    """The offered command must write the fresh capture, not just the stamp."""
    section = _empty_diff_section()

    assert "capture merge" in section, (
        "song-snapshot's empty-diff path must bake the fresh capture with "
        "`capture merge` — it carries the fields the diff never compared"
    )
    assert "capture restamp" not in section, (
        "song-snapshot's empty-diff path must NOT use `capture restamp`: an "
        "empty diff does not prove the on-disk snapshot is current, so moving "
        "`captured_at` forward disarms the replay guard over stale values and "
        "the next build silently reverts the pulled edits (BAK-7D2V)"
    )


def test_empty_diff_path_explains_why_the_stamp_alone_is_unsafe():
    """The reasoning has to travel with the command — an agent that understands
    only 'run merge' will re-derive the re-stamp shortcut the next time this
    prose is edited."""
    section = _empty_diff_section()

    for field in ("sidechain", "drum-pad", "authored props"):
        assert field in section, (
            f"song-snapshot's empty-diff path must name {field!r} among the "
            "replay-asserted fields the diff cannot see — that gap is the whole "
            "reason the bake (not a re-stamp) is required"
        )
    assert "re-assert" in section or "replay" in section.lower(), (
        "song-snapshot's empty-diff path must tie the blind spot to what "
        "`replay_capture` re-asserts"
    )
