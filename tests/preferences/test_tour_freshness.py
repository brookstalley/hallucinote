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

# The evidence budget's ITEM half, per tour-walkthrough-design.md §The concision
# rule *as amended 2026-08-11* ("the item cap is per editing session") — the
# artifact carries that rule, this manifest only enumerates what it permits.
# Chapter 1 (composing) spent 4 screenshots · 1 hero · 3 audio clips; chapter 2
# (the listening session) spends 2 screenshots · 1 clip — one artifact per move,
# and chapter 1's full-song render doubles as its before/after "before". The hero
# and each clip ship with the still that stands in for them. This manifest IS the
# cap:
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
    # Whitespace-normalized: these are number locks, and a paragraph reflow
    # must not break one (nor let a multi-word anchor silently stop matching
    # because the line happened to wrap mid-phrase).
    tour = " ".join(_TOUR.read_text(encoding="utf-8").split())
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
        # beat 14 — the sound pass's master-BUS peak. NOT the report's
        # `delivered_true_peak_dbtp`, which reads 4 dB lower off a stale fader;
        # `test_the_delivered_peak_is_derived_not_measured` asserts that premise
        # rather than asserting it in a comment here.
        dbtp(sound["master"]["loudness"]["true_peak_dbtp"]),
        # beat 15 — the square lead's spectral-centroid tell
        f"**{round(_stem(sound, '04 Voice')['timbre']['spectral_centroid_hz'])} Hz**",
        # beat 15 — master flatness, square lead → lead guitar
        f"**{flat(sound)} → {flat(lead)}**",
        # beat 16 — master flatness across the tone passes
        f"**{flat(punk)} → {flat(lead)}**",
        # beat 16 — the final delivered true peak
        dbtp(lead["delivered_true_peak_dbtp"]),
        # beat 14's own qualification quotes the two figures that expose the
        # stale-fader artifact. They shipped unlocked in the commit that fixed
        # the mislabel — the same drift the rest of this test exists to stop.
        f"−{abs(sound['delivered_true_peak_dbtp']):.2f}",
        # Anchored to the surrounding phrase, NOT the bare number: "−4.0" also
        # appears at tour.md:259 in an unrelated chapter-1 fader row, so a bare
        # substring assertion passes on that line and can never fail here —
        # coverage that looks real and is not.
        f"reported as −{abs(sound['master_fader_db']):.1f} when the fader",
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


# --------------------------------------------------------------------------
# Structure locks — the tour grows by chapters, so its shape is a drift
# surface of its own.
# --------------------------------------------------------------------------

_DOCS_INDEX = _REPO / "docs" / "README.md"

_HEADING = re.compile(r"^(#{1,6}) (.+)$")
_BEAT_HEADING = re.compile(r"^#{2,3} (\d+) · ")

# Structural counts decay the moment a chapter lands: "one session, ten
# beats" was true of the tour for exactly one editing session. Per
# project-preferences ("numbers that drift are not restated in prose; point
# at the canonical source"), an index row describes what a doc is FOR, not
# how many parts it currently has.
_COUNT_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+"
)
_SHAPE_NOUNS = (
    "beats?|chapters?|sessions?|sections?|stages?|phases?|steps?|parts?"
)
_SHAPE_CLAIM = re.compile(
    rf"\b({_COUNT_WORDS})\s+({_SHAPE_NOUNS})\b", re.IGNORECASE
)


def _headings(text: str) -> list[tuple[int, str, int]]:
    """(level, title, line-number) for every heading OUTSIDE a code fence.

    Fenced Python carries `# examples/punk-fate/build.py` comment lines that
    a naive scan reads as H1s — which is exactly how a heading-structure
    assertion goes quietly green on the wrong thing.
    """
    out, in_fence = [], False
    for lineno, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), lineno))
    return out


def test_tour_is_one_document_with_contiguous_beats():
    """Two locks on the tour's shape, both regressions that already happened
    once: chapter 2 arrived as a second `#` heading (a page with three H1s
    reads as three documents to a screen reader and to GitHub's outline), and
    its beats continue chapter 1's numbering, so a gap or a repeat means a
    beat was dropped or double-numbered in an edit."""
    headings = _headings(_TOUR.read_text(encoding="utf-8"))

    h1s = [(t, ln) for lvl, t, ln in headings if lvl == 1]
    assert len(h1s) == 1, (
        f"docs/tour.md has {len(h1s)} top-level (`#`) headings, expected 1 — "
        f"{[t for t, _ in h1s]}. Chapters are `##`, beats are `###`; one H1 "
        "is the document's title."
    )

    prev = 1
    for lvl, title, lineno in headings:
        assert lvl <= prev + 1, (
            f"docs/tour.md line {lineno} jumps from h{prev} to h{lvl} "
            f"({title!r}) — skipped levels break the document outline."
        )
        prev = lvl

    beats = [
        int(m.group(1))
        for m in (_BEAT_HEADING.match(line) for line in
                  _TOUR.read_text(encoding="utf-8").split("\n"))
        if m
    ]
    assert beats == list(range(len(beats))), (
        f"docs/tour.md beat numbers are {beats} — expected a contiguous run "
        "from 0. A gap or repeat means an edit dropped or double-numbered a "
        "beat."
    )


def test_docs_index_does_not_restate_the_shape_of_what_it_describes():
    """`docs/README.md`'s tour row read "one session, ten beats" for the whole
    of chapter 2's development — the parity test next door checks a row
    EXISTS, not that it is true, so the stale shape shipped. An index row that
    counts a doc's parts has to be re-edited every time that doc grows; one
    that says what the doc is for does not."""
    offenders = []
    for lineno, line in enumerate(
        _DOCS_INDEX.read_text(encoding="utf-8").split("\n"), 1
    ):
        if not line.startswith("|") or "](" not in line:
            continue
        for m in _SHAPE_CLAIM.finditer(line):
            offenders.append(f"  docs/README.md:{lineno} — {m.group(0)!r}")
    assert not offenders, (
        "docs/README.md index rows claim a structural count of the doc they "
        "describe:\n" + "\n".join(offenders) + "\n\nDescribe what the doc is "
        "for instead — counts go stale the next time that doc grows."
    )


def test_the_delivered_peak_is_derived_not_measured():
    """Beat 14 publishes the sound pass's master-BUS peak; the same report's
    `delivered_true_peak_dbtp` sits 4 dB lower. Which one is honest rested on a
    COMMENT ("fader at unity, so the bus peak IS delivered") that the loaded
    file contradicts (`master_fader_db: -4.0`) — and a comment cannot fail, so
    an analyzer fix + regenerated JSONs would leave the published label silently
    wrong with the suite still green.

    Assert the shape that makes the call, instead:

    1. `delivered` is ARITHMETIC over a reported fader, not a measurement — so a
       stale fader corrupts it while the bus figure stays true.
    2. The sound pass's fader reads NON-unity, which is exactly why its two
       figures disagree and why beat 14 quotes the bus.
    3. The lead pass's fader really IS at unity and its two figures agree — which
       is what makes beat 16's "delivered true peak" label literally true, and
       makes −0.34 → −0.40 a comparison between like measures.
    """
    sound = _measurement("2026-08-11-sound-punk-full-song.json")
    lead = _measurement("2026-08-11-lead-guitar-full-song.json")

    def bus(report: dict) -> float:
        return report["master"]["loudness"]["true_peak_dbtp"]

    # 1 — derived, to the floating-point bit
    assert abs(
        sound["delivered_true_peak_dbtp"] - (bus(sound) + sound["master_fader_db"])
    ) < 1e-6, (
        "delivered_true_peak_dbtp is no longer bus + master_fader_db — the "
        "premise behind quoting the bus figure in tour.md beat 14 was that "
        "delivered is derived from a fader the analyzer reported stale. If the "
        "analyzer now measures delivery directly, re-read beat 14."
    )

    # 2 — the disagreement beat 14 navigates is still present
    assert abs(sound["master_fader_db"]) > 0.5, (
        "the sound pass's master_fader_db now reads ~unity, so bus and "
        "delivered agree and tour.md beat 14's paragraph about the 4 dB "
        "discrepancy no longer describes this file — update the beat."
    )

    # 3 — beat 16's "delivered" label is literally true
    assert abs(lead["master_fader_db"]) < 0.01, (
        f"the lead pass's fader reads {lead['master_fader_db']} dB, not unity — "
        "tour.md beat 16 calls its figure the DELIVERED true peak, which only "
        "holds at unity."
    )
    assert abs(bus(lead) - lead["delivered_true_peak_dbtp"]) < 0.01, (
        "the lead pass's bus and delivered peaks have diverged; beat 16 quotes "
        "them as one number."
    )
