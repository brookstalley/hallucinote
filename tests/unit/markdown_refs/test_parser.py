"""Frontmatter parser tests — schema validation, typo detection, body split."""
from __future__ import annotations

import pytest

from hallucinote.markdown_refs import parse_frontmatter


def test_parses_minimal_annotation():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: song\n"
        "---\n"
        "Verse is sad, like weight getting worse.\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm.kind == "annotation"
    assert fm.scope == "song"
    assert fm.date is None
    assert fm.tags == []
    assert body == "Verse is sad, like weight getting worse."


def test_parses_decision_with_full_frontmatter():
    text = (
        "---\n"
        "date: 2026-05-26\n"
        "kind: decision\n"
        "scope: track-time\n"
        "track: 03 Synth Bass\n"
        "bars: [33, 40]\n"
        "tags: [dim7, bridge, dynamics]\n"
        "related: [decisions/2026-05-19-bridge.md]\n"
        "---\n"
        "We brought the backbeats down to contrast with the chorus.\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm.kind == "decision"
    assert fm.scope == "track-time"
    assert fm.date == "2026-05-26"
    assert fm.track == "03 Synth Bass"
    assert fm.bars == [33.0, 40.0]
    assert fm.tags == ["dim7", "bridge", "dynamics"]
    assert fm.related == ["decisions/2026-05-19-bridge.md"]
    assert "backbeats" in body


def test_quoted_strings_are_unquoted():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: song\n"
        'track: "01 Drums"\n'
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    # scope=song doesn't require track, but quote-stripping should still work
    assert fm.track == "01 Drums"


def test_empty_inline_list():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: song\n"
        "tags: []\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    assert fm.tags == []


def test_missing_delimiter_raises():
    text = "kind: annotation\nscope: song\n---\nbody\n"
    with pytest.raises(ValueError, match="missing frontmatter delimiter"):
        parse_frontmatter(text)


def test_unterminated_frontmatter_raises():
    text = "---\nkind: annotation\nscope: song\n"
    with pytest.raises(ValueError, match="not terminated"):
        parse_frontmatter(text)


def test_unknown_key_raises():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: song\n"
        "feeling: sad\n"  # typo / unknown key
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="unknown frontmatter key 'feeling'"):
        parse_frontmatter(text)


def test_invalid_kind_raises():
    text = "---\nkind: rumination\nscope: song\n---\nbody\n"
    with pytest.raises(ValueError, match="invalid kind"):
        parse_frontmatter(text)


def test_invalid_scope_raises():
    text = "---\nkind: annotation\nscope: galactic\n---\nbody\n"
    with pytest.raises(ValueError, match="invalid scope"):
        parse_frontmatter(text)


def test_decision_requires_date():
    text = "---\nkind: decision\nscope: song\n---\nbody\n"
    with pytest.raises(ValueError, match="decisions require a 'date' field"):
        parse_frontmatter(text)


def test_invalid_date_format_raises():
    text = "---\nkind: decision\nscope: song\ndate: 5/26/2026\n---\nbody\n"
    with pytest.raises(ValueError, match="ISO YYYY-MM-DD"):
        parse_frontmatter(text)


def test_time_scope_requires_bars():
    text = "---\nkind: annotation\nscope: time\n---\nbody\n"
    with pytest.raises(ValueError, match="scope 'time' requires 'bars'"):
        parse_frontmatter(text)


def test_track_scope_requires_track():
    text = "---\nkind: annotation\nscope: track\n---\nbody\n"
    with pytest.raises(ValueError, match="scope 'track' requires 'track'"):
        parse_frontmatter(text)


def test_bars_must_be_numeric():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: time\n"
        "bars: [intro, chorus]\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="bars must be numeric"):
        parse_frontmatter(text)


def test_bars_three_elements_raises():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: time\n"
        "bars: [1, 2, 3]\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match=r"\[start\] or \[start, end\]"):
        parse_frontmatter(text)


def test_bars_end_must_exceed_start():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: time\n"
        "bars: [40, 40]\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="bars end must exceed start"):
        parse_frontmatter(text)


def test_duplicate_key_raises():
    text = (
        "---\n"
        "kind: annotation\n"
        "kind: decision\n"
        "scope: song\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="duplicate key"):
        parse_frontmatter(text)


def test_list_value_requires_brackets():
    text = (
        "---\n"
        "kind: annotation\n"
        "scope: song\n"
        "tags: dim7, bridge\n"  # missing brackets
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="expects inline list"):
        parse_frontmatter(text)


def test_blank_lines_and_comments_in_frontmatter_ignored():
    text = (
        "---\n"
        "# a comment line\n"
        "\n"
        "kind: annotation\n"
        "scope: song\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    assert fm.kind == "annotation"
