"""Onboarding C0: tests for `tools.scenario_eval`.

The deterministic substrate is the testable core; the persona/judge subagents
are the ad hoc part (see tests/scenarios/README.md). Covers: brief schema
validation, loading the shipped six-persona corpus, prompt rendering (and the
rubric-leak guard), and the judge-result schema — completeness, per-line shape,
and verdict/findings consistency — plus the recorder.
"""
from __future__ import annotations

import json

import pytest

from tools.scenario_eval import (
    BRIEFS_DIR,
    Brief,
    Rubric,
    ScenarioError,
    _result_skeleton,
    derive_verdict,
    load_all_briefs,
    load_brief,
    main,
    parse_brief,
    render_judge_prompt,
    render_persona_prompt,
    validate_result,
    write_result,
)

# The six create-flow personas (C1/C2/C3 gates) plus the compose-stage
# evaluation briefs (C4 gates). The corpus grows as chunks add gating scenarios.
CREATE_FLOW_PERSONAS = {"maya", "dev", "elena", "theo", "priya", "sam"}
EVALUATE_BRIEFS = {"maya-evaluate", "sam-evaluate"}
EXPECTED_PERSONAS = CREATE_FLOW_PERSONAS | EVALUATE_BRIEFS


def _valid_brief_dict(**overrides) -> dict:
    data = {
        "id": "theo",
        "persona": "A gigging drummer, expert rhythm, novice harmony.",
        "goal": "A breakbeat track with chords that feel like Bach.",
        "response_character": "Crisp on drums, vague on harmony; defers when pushed.",
        "rubric": {
            "must": ["Execute the drum direction.", "Treat 'Bach' as under-articulated."],
            "must_not": ["Silently auto-accompany."],
        },
        "tags": ["C2", "third-register"],
    }
    data.update(overrides)
    return data


def _fill(skeleton: dict) -> dict:
    """Turn a _result_skeleton into a concrete, valid result (real rationales)."""
    out = dict(skeleton)
    out["summary"] = "The agent met every rubric line."
    out["rubric_findings"] = [
        {**f, "rationale": "cited from transcript"} for f in skeleton["rubric_findings"]
    ]
    return out


# ---------------------------------------------------------------------------
# The shipped corpus
# ---------------------------------------------------------------------------


def test_all_personas_load_and_validate():
    briefs = load_all_briefs()
    ids = {b.id for b in briefs}
    assert CREATE_FLOW_PERSONAS <= ids, "all six create-flow personas must exist"
    assert ids == EXPECTED_PERSONAS


def test_every_shipped_brief_is_well_formed():
    for brief in load_all_briefs():
        assert brief.persona and brief.goal and brief.response_character
        assert brief.rubric.must, f"{brief.id}: must-rubric is empty"
        assert brief.tags, f"{brief.id}: expected at least one chunk tag"


def test_brief_id_matches_filename():
    brief = load_brief(BRIEFS_DIR / "theo.json")
    assert brief.id == "theo"


# ---------------------------------------------------------------------------
# Brief schema validation
# ---------------------------------------------------------------------------


def test_parse_brief_happy_path():
    brief = parse_brief(_valid_brief_dict())
    assert isinstance(brief, Brief)
    assert brief.rubric.must_not == ("Silently auto-accompany.",)


@pytest.mark.parametrize("field", ["persona", "goal", "response_character"])
def test_parse_brief_rejects_empty_prose(field):
    with pytest.raises(ScenarioError, match=field):
        parse_brief(_valid_brief_dict(**{field: "  "}))


@pytest.mark.parametrize("bad_id", ["Theo", "the o", "-theo", "théo", ""])
def test_parse_brief_rejects_bad_id(bad_id):
    with pytest.raises(ScenarioError):
        parse_brief(_valid_brief_dict(id=bad_id))


def test_parse_brief_rejects_empty_must():
    with pytest.raises(ScenarioError, match="must not be empty"):
        parse_brief(_valid_brief_dict(rubric={"must": [], "must_not": []}))


def test_parse_brief_allows_empty_must_not():
    brief = parse_brief(_valid_brief_dict(rubric={"must": ["do a thing"], "must_not": []}))
    assert brief.rubric.must_not == ()


def test_parse_brief_rejects_non_string_rubric_entry():
    with pytest.raises(ScenarioError):
        parse_brief(_valid_brief_dict(rubric={"must": ["ok", 7], "must_not": []}))


def test_parse_brief_rejects_unknown_rubric_key():
    with pytest.raises(ScenarioError, match="unknown keys"):
        parse_brief(_valid_brief_dict(rubric={"must": ["x"], "should": ["y"]}))


def test_parse_brief_rejects_unknown_top_level_key():
    with pytest.raises(ScenarioError, match="unknown top-level"):
        parse_brief(_valid_brief_dict(extra="nope"))


def test_load_brief_rejects_id_filename_mismatch(tmp_path):
    p = tmp_path / "maya.json"
    p.write_text(json.dumps(_valid_brief_dict(id="theo")), encoding="utf-8")
    with pytest.raises(ScenarioError, match="must match filename"):
        load_brief(p)


def test_load_brief_rejects_invalid_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError, match="invalid JSON"):
        load_brief(p)


def test_load_all_briefs_missing_dir(tmp_path):
    with pytest.raises(ScenarioError, match="not found"):
        load_all_briefs(tmp_path / "nope")


# ---------------------------------------------------------------------------
# Rubric ordering
# ---------------------------------------------------------------------------


def test_rubric_lines_order_is_must_then_must_not():
    rubric = Rubric(must=("a", "b"), must_not=("c",))
    assert rubric.lines() == [("must", "a"), ("must", "b"), ("must_not", "c")]


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_persona_prompt_carries_character_but_not_rubric():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_persona_prompt(brief)
    assert brief.persona in prompt
    assert brief.goal in prompt
    assert brief.response_character in prompt
    # The persona must not see what it's being graded on — no rubric leak.
    for _, text in brief.rubric.lines():
        assert text not in prompt


def test_judge_prompt_includes_every_rubric_line_and_transcript():
    brief = parse_brief(_valid_brief_dict())
    prompt = render_judge_prompt(brief, "USER: hi\nAGENT: hello")
    for _, text in brief.rubric.lines():
        assert text in prompt
    assert "USER: hi" in prompt
    assert "brief_id" in prompt  # carries the result skeleton


# ---------------------------------------------------------------------------
# Verdict derivation + result validation
# ---------------------------------------------------------------------------


def test_derive_verdict():
    assert derive_verdict([{"satisfied": True}, {"satisfied": True}]) == "pass"
    assert derive_verdict([{"satisfied": True}, {"satisfied": False}]) == "fail"


def test_validate_result_happy_path():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    assert validate_result(result, brief) is result


def test_validate_result_rejects_brief_id_mismatch():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["brief_id"] = "maya"
    with pytest.raises(ScenarioError, match="brief_id"):
        validate_result(result, brief)


def test_validate_result_rejects_bad_verdict():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["verdict"] = "maybe"
    with pytest.raises(ScenarioError, match="verdict"):
        validate_result(result, brief)


def test_validate_result_requires_summary():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["summary"] = ""
    with pytest.raises(ScenarioError, match="summary"):
        validate_result(result, brief)


def test_validate_result_rejects_wrong_finding_count():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"].pop()
    with pytest.raises(ScenarioError, match="score every line"):
        validate_result(result, brief)


def test_validate_result_rejects_mismatched_finding_text():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"][0]["item"] = "something the rubric never said"
    with pytest.raises(ScenarioError, match="must match rubric line"):
        validate_result(result, brief)


def test_validate_result_rejects_non_bool_satisfied():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"][0]["satisfied"] = "yes"
    with pytest.raises(ScenarioError, match="satisfied"):
        validate_result(result, brief)


def test_validate_result_requires_per_line_rationale():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"][0]["rationale"] = ""
    with pytest.raises(ScenarioError, match="rationale"):
        validate_result(result, brief)


def test_validate_result_rejects_inconsistent_verdict():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"][0]["satisfied"] = False  # now a fail
    result["verdict"] = "pass"  # ...but claims pass
    with pytest.raises(ScenarioError, match="inconsistent"):
        validate_result(result, brief)


def test_fail_verdict_is_consistent_when_a_line_fails():
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"][0]["satisfied"] = False
    result["verdict"] = "fail"
    assert validate_result(result, brief) is result


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


def test_write_result_validates_stamps_and_records(tmp_path):
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    out = write_result(result, brief, results_dir=tmp_path)
    assert out.parent == tmp_path
    assert out.name.startswith("theo-") and out.name.endswith(".json")
    recorded = json.loads(out.read_text(encoding="utf-8"))
    assert "timestamp" in recorded
    validate_result(recorded, brief)  # round-trips


def test_write_result_rejects_invalid(tmp_path):
    brief = parse_brief(_valid_brief_dict())
    result = _fill(_result_skeleton(brief))
    result["rubric_findings"].pop()
    with pytest.raises(ScenarioError):
        write_result(result, brief, results_dir=tmp_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_list_and_show(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    for pid in EXPECTED_PERSONAS:
        assert pid in out
    assert main(["show", "theo"]) == 0
    assert "RUBRIC" in capsys.readouterr().out


def test_cli_validate_result_roundtrip(tmp_path, capsys):
    brief = load_brief(BRIEFS_DIR / "theo.json")
    result = _fill(_result_skeleton(brief))
    path = tmp_path / "r.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    assert main(["validate-result", str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_reports_error_on_bad_brief(tmp_path, capsys):
    assert main(["--briefs-dir", str(tmp_path), "show", "ghost"]) == 2
    assert "error:" in capsys.readouterr().err
