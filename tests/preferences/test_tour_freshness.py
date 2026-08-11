"""Freshness tests for the tour — a worked example that rots is worse than none.

`docs/tour.md` quotes real artifacts: code snippets from the demo song's
`build.py`, mix-report numbers from the committed analysis JSONs, and media
under `docs/assets/`. Each of those claims is locked here so it cannot drift
quietly.

Design constraints (tour-walkthrough-design.md §Capture tooling item 5, and
the TOUR build plan's D1 chunk):

- **Assert only over content the test controls** — committed files read by
  path. No mtimes, no `git log` recency: CI checks PRs out detached, and an
  ambient-state assertion is green on `push:` and red on `pull_request:`.
- **Deliberately one-directional.** doc → source is asserted (every quoted
  snippet appears verbatim in `build.py`); source → doc is NOT, because the
  tour shows a curated subset by design — the concision rule is the point. A
  future reviewer applying the repo's usual both-directions rule: this is why
  this one departs from it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TOUR = _REPO / "docs" / "tour.md"
_README = _REPO / "README.md"
_QUICKSTART = _REPO / "docs" / "quickstart.md"
_ASSETS = _REPO / "docs" / "assets"
_BUILD = _REPO / "examples" / "punk-fate" / "build.py"
_ANALYSIS = _REPO / "examples" / "punk-fate" / "analysis"

# The committed-media byte cap — the repo is public and its history
# permanent, so media weight is a one-way door.
_MEDIA_BUDGET_BYTES = 12 * 1024 * 1024

# The evidence budget's ITEM half (tour-walkthrough-design.md §The concision
# rule), accounted per editing session: chapter 1 (composing) spent
# 4 screenshots · 1 hero · 3 audio clips; chapter 2 (the listening session)
# spends 2 screenshots · 1 clip — one artifact per move, and chapter 1's
# full-song render doubles as its before/after "before". The hero and each
# clip ship with the still that stands in for them. This manifest IS the cap:
# adding media means consciously editing this set, and a stray file under
# docs/assets/ fails the suite instead of riding along.
_EXPECTED_ASSETS = {
    # the one lifecycle diagram (TOUR A4) and the hero still
    "lifecycle.svg",
    "hero.png",
    # chapter 1's 4 screenshots
    "tour-offgrid-midi.png",
    "tour-arrangement.png",
    "tour-session-render.png",
    "tour-drum-rack.png",
    # chapter 1's 3 audio items, each an mp3 + its waveform still. The
    # full-song render is numbered per editing session — chapter 1 is the
    # composing session.
    "tour-chapter1.mp3",
    "tour-chapter1.png",
    "tour-chorus-before.mp3",
    "tour-chorus-before.png",
    "tour-chorus-after.mp3",
    "tour-chorus-after.png",
    # chapter 2's 2 screenshots — the garage-kit vocabulary in the clip
    # editor, and the drum saturator read back at its dialed values
    "tour-garage-drums.png",
    "tour-drum-saturation.png",
    # chapter 2's 1 audio item: the full-song render after the punk passes
    "tour-chapter2.mp3",
    "tour-chapter2.png",
}

# A fenced block whose first line is this marker claims its remaining lines
# appear verbatim in the demo song's build.py.
_SNIPPET_MARKER = "# examples/punk-fate/build.py"

_FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_ASSET_REF = re.compile(r"\(((?:docs/)?assets/[^)\s]+)\)")


def _tour_snippets() -> list[str]:
    blocks = _FENCE.findall(_TOUR.read_text(encoding="utf-8"))
    out = []
    for block in blocks:
        lines = block.splitlines()
        if lines and lines[0].strip() == _SNIPPET_MARKER:
            out.append("\n".join(lines[1:]))
    return out


def test_tour_quotes_at_least_three_build_snippets():
    """The marker convention only guards blocks that carry it — this guards
    the convention itself. If a rewrite drops the markers, the verbatim test
    below would pass vacuously; this one fails instead."""
    assert len(_tour_snippets()) >= 3, (
        "docs/tour.md is expected to quote the demo build.py in at least "
        f"three fenced blocks whose first line is '{_SNIPPET_MARKER}'"
    )


def test_every_quoted_snippet_appears_verbatim_in_build_py():
    source = _BUILD.read_text(encoding="utf-8")
    for snippet in _tour_snippets():
        assert snippet.strip("\n") in source, (
            "docs/tour.md quotes a snippet that no longer appears verbatim in "
            f"examples/punk-fate/build.py:\n---\n{snippet}\n---\n"
            "Update the tour to match the source (never the reverse — the "
            "source is the truth the tour documents)."
        )


def _referenced_assets(doc: Path) -> set[Path]:
    text = doc.read_text(encoding="utf-8")
    refs = set()
    for ref in _ASSET_REF.findall(text):
        rel = ref if ref.startswith("docs/") else f"docs/{ref}"
        refs.add(_REPO / rel)
    return refs


def test_every_referenced_asset_exists():
    missing = [
        str(p.relative_to(_REPO))
        for doc in (_TOUR, _README, _QUICKSTART)
        for p in sorted(_referenced_assets(doc))
        if not p.is_file()
    ]
    assert not missing, f"referenced media missing from docs/assets/: {missing}"


def test_committed_media_matches_the_evidence_manifest():
    actual = {p.name for p in _ASSETS.rglob("*") if p.is_file()}
    stray = actual - _EXPECTED_ASSETS
    missing = _EXPECTED_ASSETS - actual
    assert not stray and not missing, (
        f"docs/assets/ diverges from the tour's evidence manifest — "
        f"stray: {sorted(stray)}, missing: {sorted(missing)}. The manifest "
        "in this test is the item cap, accounted per editing session (see "
        "the comment on _EXPECTED_ASSETS); adding media is a conscious "
        "edit to the manifest, not a drive-by."
    )


def test_committed_media_stays_under_the_byte_budget():
    total = sum(p.stat().st_size for p in _ASSETS.rglob("*") if p.is_file())
    assert total <= _MEDIA_BUDGET_BYTES, (
        f"docs/assets/ holds {total / 1024 / 1024:.1f} MB of committed media; "
        f"the budget is {_MEDIA_BUDGET_BYTES / 1024 / 1024:.0f} MB. Re-encode "
        "or drop an asset — do not raise the budget without an owner decision "
        "(public repo, permanent history)."
    )


def test_readme_has_no_hero_placeholder():
    assert "HERO:" not in _README.read_text(encoding="utf-8"), (
        "README.md carries a 'HERO:' placeholder comment — the real hero "
        "shipped; the placeholder must not return."
    )


def _measurement(name: str) -> dict:
    path = _REPO / "examples" / "punk-fate" / "measurements" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _stem(report: dict, surface_name: str) -> dict:
    for stem in report["stems"]:
        if stem["surface_name"] == surface_name:
            return stem
    raise AssertionError(f"no stem named {surface_name!r} in the report")


def test_quoted_chapter2_numbers_match_the_committed_measurements():
    """Chapter 2 closes on "every number ships next to the song in
    `measurements/`" — so recompute the chapter's quoted figures from those
    committed JSONs and require the tour to carry exactly them. This lock
    exists because chapter 2's "before" figures once shipped from a
    superseded in-session analysis run (taken while a deleted drum-bus
    device invalidated the render) instead of from the committed captures —
    the chapter-1 lock above not covering chapter 2 is exactly how that got
    through."""
    tour = _TOUR.read_text(encoding="utf-8")
    punk = _measurement("2026-08-11-punk-pass-full-song.json")
    sound = _measurement("2026-08-11-sound-punk-full-song.json")
    lead = _measurement("2026-08-11-lead-guitar-full-song.json")

    def flat(report: dict) -> str:
        return f"{report['master']['timbre']['spectral_flatness']:.3f}"

    def dbtp(value: float) -> str:
        return f"{value:.2f}".replace("-", "−") + " dBTP"

    expectations = [
        # beat 14 — the guitar stem's flatness jump, before → after
        f"**{_stem(punk, '03 Guitar')['timbre']['spectral_flatness']:.3f} → "
        f"{_stem(sound, '03 Guitar')['timbre']['spectral_flatness']:.3f}**",
        # beat 14 — the sound pass's delivered peak (fader at unity, so the
        # bus true peak IS the delivered figure; decision 10 records why)
        dbtp(sound["master"]["loudness"]["true_peak_dbtp"]),
        # beat 15 — the square lead's spectral-centroid tell
        f"**{round(_stem(sound, '04 Voice')['timbre']['spectral_centroid_hz'])} Hz**",
        # beat 15 — master flatness, square lead → lead guitar
        f"**{flat(sound)} → {flat(lead)}**",
        # beat 16 — master flatness across the tone passes
        f"**{flat(punk)} → {flat(lead)}**",
        # beat 16 — the final delivered true peak
        dbtp(lead["delivered_true_peak_dbtp"]),
    ]
    for expected in expectations:
        assert expected in tour, (
            f"docs/tour.md does not carry the measured value {expected!r} "
            "from the committed chapter-2 measurement JSONs — the quoted "
            "numbers and the committed evidence have drifted apart."
        )


def test_quoted_mix_numbers_match_the_committed_reports():
    """The tour's beat-8/9 story quotes the measured before/after. Recompute
    those numbers from the committed analysis JSONs and require the tour to
    carry exactly them."""
    tour = _TOUR.read_text(encoding="utf-8")
    reports = sorted(_ANALYSIS.glob("*.json"))
    assert len(reports) == 2, (
        f"expected the before and after analysis reports in {_ANALYSIS}, "
        f"found {[p.name for p in reports]}"
    )
    before = json.loads(reports[0].read_text(encoding="utf-8"))
    after = json.loads(reports[1].read_text(encoding="utf-8"))
    expectations = [
        f"+{before['delivered_true_peak_dbtp']:.2f} dBTP",  # +5.51 dBTP
        f"{len(before['overshoots'])} true-peak overshoots",  # 257
        f"+{before['delivered_true_peak_dbtp']:.2f} → "
        f"+{after['delivered_true_peak_dbtp']:.2f} dBTP",  # +5.51 → +1.29
        f"{len(before['overshoots'])} → {len(after['overshoots'])}",  # 257 → 1
    ]
    for expected in expectations:
        assert expected in tour, (
            f"docs/tour.md does not carry the measured value {expected!r} "
            "from the committed analysis reports — the quoted mix numbers "
            "and the committed evidence have drifted apart."
        )
