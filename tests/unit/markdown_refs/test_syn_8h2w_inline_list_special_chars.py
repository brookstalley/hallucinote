"""SYN-8H2W — inline-list items containing ',' / '[' / ']' must survive the
serialize -> parse round-trip. Before the fix, ``_serialize_markdown`` joined
items with ', ' and ``_parse_value`` split on every comma, so a tag/related
value containing a comma silently split into two items (and bracket chars were
ambiguous). The serializer now quotes such items and the parser splits on
commas outside quoted spans.
"""
from __future__ import annotations

from hallucinote.markdown_refs import (
    _serialize_list_item,
    _serialize_markdown,
    _split_inline_list,
    parse_frontmatter,
)


def _round_trip(fm: dict) -> "tuple":
    text = _serialize_markdown(fm, body="body text")
    parsed, _ = parse_frontmatter(text)
    return parsed


def test_tag_with_comma_round_trips_as_one_item():
    fm = {"kind": "annotation", "scope": "song", "tags": ["a,b", "c"]}
    parsed = _round_trip(fm)
    assert parsed.tags == ["a,b", "c"]


def test_related_with_brackets_round_trips():
    fm = {
        "kind": "annotation",
        "scope": "song",
        "related": ["motif[A]", "section]end", "plain"],
    }
    parsed = _round_trip(fm)
    assert parsed.related == ["motif[A]", "section]end", "plain"]


def test_plain_items_still_serialize_unquoted():
    # No special chars -> no quoting, output format unchanged from before.
    fm = {"kind": "annotation", "scope": "song", "tags": ["dim7", "bridge"]}
    text = _serialize_markdown(fm, body="b")
    assert "tags: [dim7, bridge]" in text
    assert _round_trip(fm).tags == ["dim7", "bridge"]


def test_mixed_plain_and_special_items_round_trip():
    fm = {
        "kind": "annotation",
        "scope": "song",
        "tags": ["plain", "has,comma", "ok"],
    }
    parsed = _round_trip(fm)
    assert parsed.tags == ["plain", "has,comma", "ok"]


def test_serialize_list_item_quotes_only_when_needed():
    assert _serialize_list_item("plain") == "plain"
    assert _serialize_list_item("a,b") == '"a,b"'
    assert _serialize_list_item("x[y]") == '"x[y]"'


def test_split_inline_list_respects_quoted_commas():
    assert _split_inline_list('"a,b", c') == ['"a,b"', "c"]
    assert _split_inline_list("a, b, c") == ["a", "b", "c"]
    assert _split_inline_list("solo") == ["solo"]
