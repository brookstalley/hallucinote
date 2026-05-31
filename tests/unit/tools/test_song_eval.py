"""Tests for `tools.song_eval` — the musical-work eval harness (testable core).

The deterministic substrate is the testable core; the user/compose/judge
subagents are the ad hoc part (see tests/scenarios/works/README.md). Covers:
work-brief schema validation (every rejection branch), the shipped corpus,
the two-surface rubric prefix guard, capability/axes controlled-vocab guards,
prompt + intent-doc rendering (and the rubric/expectation leak guard), reuse of
the shared judge-result schema, and the CLI.
"""
from __future__ import annotations

import json

import pytest

from tools.scenario_eval import ScenarioError, validate_result, write_result
from tools.song_eval import (
    CAPABILITY_DIMENSIONS,
    EXPECTATIONS,
    SOPHISTICATION,
    SPECIFICITY,
    WORKS_DIR,
    Capability,
    WorkBrief,
    _result_skeleton,
    load_all_briefs,
    load_brief,
    main,
    parse_brief,
    render_intent_doc,
    render_judge_prompt,
    render_request_prompt,
)

SHIPPED_WORKS = {
    "lofi-study",
    "pop-hook",
    "synthwave-chase",
    "soul-ballad",
    "reich-phase",
    "art-song",
}


def _valid_brief_dict(**overrides) -> dict:
    data = {
        "id": "lofi-study",
        "request": "A chill lo-fi beat to study to — cozy, not distracting.",
        "response_character": "Casual, low music vocabulary, reacts by feel.",
        "axes": {"specificity": "loose", "sophistication": "simple"},
        "expected_capabilities": [
            {"dimension": "rhythm", "expectation": "deliver", "note": "dusty swung kit"},
            {"dimension": "melody", "expectation": "caveat", "note": "topline is a start"},
        ],
        "rubric": {
            "must": [
                "framing: build-and-show a concrete first pass.",
                "artifact: the DB reads as lo-fi — swung kit, mellow keys.",
            ],
            "must_not": ["framing: interrogate the user with questions."],
        },
        "tags": ["thin-slice"],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Happy path + shipped corpus
# ---------------------------------------------------------------------------


def test_parse_valid_brief_roundtrips_fields():
    brief = parse_brief(_valid_brief_dict())
    assert isinstance(brief, WorkBrief)
    assert brief.id == "lofi-study"
    assert brief.specificity == "loose"
    assert brief.sophistication == "simple"
    assert brief.expected_capabilities[0] == Capability("rhythm", "deliver", "dusty swung kit")
    assert brief.rubric.must[0].startswith("framing:")
    assert brief.tags == ("thin-slice",)


def test_shipped_corpus_loads_and_validates():
    briefs = load_all_briefs()
    ids = {b.id for b in briefs}
    assert ids == SHIPPED_WORKS  # exact corpus — a missing/extra brief is a failure
    for b in briefs:
        # Controlled vocabularies hold for every shipped brief.
        assert b.specificity in SPECIFICITY
        assert b.sophistication in SOPHISTICATION
        for c in b.expected_capabilities:
            assert c.dimension in CAPABILITY_DIMENSIONS
            assert c.expectation in EXPECTATIONS


def test_corpus_exercises_every_expectation_kind():
    """The suite's value is the cliffs — assert each outcome is actually tested."""
    seen = {c.expectation for b in load_all_briefs() for c in b.expected_capabilities}
    assert seen == set(EXPECTATIONS), f"corpus misses expectation kinds: {set(EXPECTATIONS) - seen}"


def test_corpus_spans_the_specificity_sophistication_grid():
    briefs = load_all_briefs()
    assert {b.specificity for b in briefs} == set(SPECIFICITY)
    assert {b.sophistication for b in briefs} == set(SOPHISTICATION)


def test_known_gap_cliff_is_present_and_uses_raw_db_tier():
    """reich-phase is the brief that proves the raw-DB artifact tier — guard it."""
    brief = load_brief(WORKS_DIR / "reich-phase.json")
    assert any(c.expectation == "known-gap" for c in brief.expected_capabilities)
    # Its artifact rubric must point the judge at the raw DB extract, since the
    # analyzers are blind to phase relationships.
    artifact_lines = [t for k, t in brief.rubric.lines() if t.startswith("artifact:")]
    assert any("RAW DB EXTRACT" in t for t in artifact_lines)


def test_load_brief_reads_shipped_file():
    brief = load_brief(WORKS_DIR / "lofi-study.json")
    assert brief.id == "lofi-study"
    assert any(c.expectation == "deliver" for c in brief.expected_capabilities)


# ---------------------------------------------------------------------------
# Rejection branches — schema teeth
# ---------------------------------------------------------------------------


def test_reject_non_object():
    with pytest.raises(ScenarioError, match="must be a JSON object"):
        parse_brief(["not", "a", "dict"])


def test_reject_bad_id():
    with pytest.raises(ScenarioError, match="lowercase slug"):
        parse_brief(_valid_brief_dict(id="Not A Slug"))


def test_reject_blank_request():
    with pytest.raises(ScenarioError, match="'request' must be a non-empty string"):
        parse_brief(_valid_brief_dict(request="  "))


def test_reject_missing_axes():
    with pytest.raises(ScenarioError, match="'axes' must be an object"):
        parse_brief(_valid_brief_dict(axes="loose"))


def test_reject_unknown_axes_key():
    with pytest.raises(ScenarioError, match="axes has unknown keys"):
        parse_brief(_valid_brief_dict(axes={"specificity": "loose", "sophistication": "simple", "x": 1}))


def test_reject_bad_specificity():
    with pytest.raises(ScenarioError, match="axes.specificity: must be one of"):
        parse_brief(_valid_brief_dict(axes={"specificity": "vague", "sophistication": "simple"}))


def test_reject_bad_sophistication():
    with pytest.raises(ScenarioError, match="axes.sophistication: must be one of"):
        parse_brief(_valid_brief_dict(axes={"specificity": "loose", "sophistication": "galaxy-brained"}))


def test_reject_empty_capabilities():
    with pytest.raises(ScenarioError, match="non-empty list of capability objects"):
        parse_brief(_valid_brief_dict(expected_capabilities=[]))


def test_reject_unknown_capability_dimension():
    with pytest.raises(ScenarioError, match="dimension: must be one of"):
        parse_brief(
            _valid_brief_dict(
                expected_capabilities=[{"dimension": "telepathy", "expectation": "deliver", "note": "x"}]
            )
        )


def test_reject_bad_expectation():
    with pytest.raises(ScenarioError, match="expectation: must be one of"):
        parse_brief(
            _valid_brief_dict(
                expected_capabilities=[{"dimension": "rhythm", "expectation": "maybe", "note": "x"}]
            )
        )


def test_reject_duplicate_capability_dimension():
    with pytest.raises(ScenarioError, match="duplicate dimension"):
        parse_brief(
            _valid_brief_dict(
                expected_capabilities=[
                    {"dimension": "rhythm", "expectation": "deliver", "note": "a"},
                    {"dimension": "rhythm", "expectation": "caveat", "note": "b"},
                ]
            )
        )


def test_reject_capability_unknown_key():
    with pytest.raises(ScenarioError, match="unknown keys"):
        parse_brief(
            _valid_brief_dict(
                expected_capabilities=[
                    {"dimension": "rhythm", "expectation": "deliver", "note": "a", "extra": 1}
                ]
            )
        )


def test_reject_rubric_line_without_surface_prefix():
    with pytest.raises(ScenarioError, match="must start with one of"):
        parse_brief(
            _valid_brief_dict(
                rubric={"must": ["build-and-show without a surface prefix."], "must_not": []}
            )
        )


def test_reject_empty_must():
    with pytest.raises(ScenarioError, match="rubric.must: must not be empty"):
        parse_brief(_valid_brief_dict(rubric={"must": [], "must_not": []}))


def test_reject_unknown_rubric_key():
    with pytest.raises(ScenarioError, match="rubric has unknown keys"):
        parse_brief(
            _valid_brief_dict(rubric={"must": ["framing: x"], "must_not": [], "maybe": ["y"]})
        )


def test_reject_unknown_top_level_key():
    with pytest.raises(ScenarioError, match="unknown top-level keys"):
        parse_brief(_valid_brief_dict(surprise="boo"))


def test_load_brief_id_must_match_stem(tmp_path):
    p = tmp_path / "mismatch.json"
    p.write_text(json.dumps(_valid_brief_dict(id="lofi-study")), encoding="utf-8")
    with pytest.raises(ScenarioError, match="must match filename stem"):
        load_brief(p)


def test_load_brief_invalid_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError, match="invalid JSON"):
        load_brief(p)


def test_load_brief_missing_file(tmp_path):
    with pytest.raises(ScenarioError, match="brief file not found"):
        load_brief(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# Prompt + intent-doc rendering
# ---------------------------------------------------------------------------


def test_request_prompt_withholds_rubric_and_expectations():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_request_prompt(brief)
    assert brief.request in prompt
    assert brief.response_character in prompt
    # The user subagent must not see what it is graded on, nor the expectations.
    assert "framing:" not in prompt
    assert "artifact:" not in prompt
    assert "deliver" not in prompt
    assert "caveat" not in prompt


def test_intent_doc_is_request_only_no_rubric():
    brief = parse_brief(_valid_brief_dict())
    doc = render_intent_doc(brief)
    assert brief.request in doc
    assert brief.specificity in doc
    # Intent that /compose-review recalls must not carry harness grading metadata.
    assert "framing:" not in doc
    assert "artifact:" not in doc
    assert "expectation" not in doc


def test_judge_prompt_includes_both_surfaces_and_expectations():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_judge_prompt(brief, "the transcript", "the compose review")
    assert "the transcript" in prompt
    assert "the compose review" in prompt
    assert "framing:" in prompt and "artifact:" in prompt
    # The judge DOES see the capability backbone.
    assert "deliver" in prompt
    for kind, text in brief.rubric.lines():
        assert text in prompt


def test_judge_prompt_includes_raw_db_extract_surface():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_judge_prompt(brief, "the transcript", None, "raw db rows")
    assert "RAW DB EXTRACT" in prompt
    assert "raw db rows" in prompt
    # The fall-back guidance for when analyzers go blind is present.
    assert "analyzers cannot understand" in prompt


def test_judge_prompt_no_artifact_surface_marks_unscored():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_judge_prompt(brief, "the transcript", None, None)
    assert "no song was produced to score" in prompt
    assert "satisfied=false" in prompt


# ---------------------------------------------------------------------------
# Shared judge-result schema reuse — a work result is a persona result by shape
# ---------------------------------------------------------------------------


def _passing_result(brief: WorkBrief) -> dict:
    skel = _result_skeleton(brief)
    for f in skel["rubric_findings"]:
        f["satisfied"] = True
        f["rationale"] = "ok"
    skel["summary"] = "all good"
    return skel


def test_validate_result_accepts_consistent_pass():
    brief = parse_brief(_valid_brief_dict())
    assert validate_result(_passing_result(brief), brief) is not None


def test_validate_result_rejects_inconsistent_verdict():
    brief = parse_brief(_valid_brief_dict())
    result = _passing_result(brief)
    result["rubric_findings"][0]["satisfied"] = False  # now should derive 'fail'
    with pytest.raises(ScenarioError, match="inconsistent with findings"):
        validate_result(result, brief)


def test_write_result_validates_and_stamps(tmp_path):
    brief = parse_brief(_valid_brief_dict())
    out = write_result(_passing_result(brief), brief, results_dir=tmp_path)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["brief_id"] == brief.id
    assert "timestamp" in written
    assert out.name.startswith("lofi-study-")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "lofi-study" in out
    assert "[loose/simple]" in out


def test_cli_show(capsys):
    assert main(["show", "lofi-study"]) == 0
    out = capsys.readouterr().out
    assert "EXPECTED CAPABILITIES" in out
    assert "RUBRIC" in out


def test_cli_request_prompt(capsys):
    assert main(["request-prompt", "lofi-study"]) == 0
    assert "WHAT YOU WANT" in capsys.readouterr().out


def test_cli_intent_doc(capsys):
    assert main(["intent-doc", "lofi-study"]) == 0
    assert "# Intent — lofi-study" in capsys.readouterr().out


def test_cli_judge_prompt(tmp_path, capsys):
    t = tmp_path / "t.txt"
    t.write_text("transcript body", encoding="utf-8")
    c = tmp_path / "c.txt"
    c.write_text("compose review body", encoding="utf-8")
    d = tmp_path / "d.txt"
    d.write_text("db extract body", encoding="utf-8")
    assert main([
        "judge-prompt", "lofi-study",
        "--transcript", str(t), "--compose-review", str(c), "--db-extract", str(d),
    ]) == 0
    out = capsys.readouterr().out
    assert "transcript body" in out and "compose review body" in out and "db extract body" in out


def test_cli_validate_result(tmp_path, capsys):
    brief = load_brief(WORKS_DIR / "lofi-study.json")
    result_path = tmp_path / "lofi-study-test.json"
    result_path.write_text(json.dumps(_passing_result(brief)), encoding="utf-8")
    assert main(["validate-result", str(result_path)]) == 0
    assert "is a valid pass result" in capsys.readouterr().out


def test_cli_unknown_brief_errors(capsys):
    assert main(["show", "does-not-exist"]) == 2
    assert "not found" in capsys.readouterr().err
