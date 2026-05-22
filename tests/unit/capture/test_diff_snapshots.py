"""Tests for `capture.diff_snapshots` and `format_diff_summary` (W12-B).

The diff drives the `/song-snapshot` skill — it surfaces what changed between
the on-disk snapshot and a fresh capture so the user can confirm overwrite.
Coverage focuses on the matching invariants (track/return/device matched by
index, not name) and on the not-empty / is-empty boundary the skill branches
on.
"""
from __future__ import annotations

import copy

import pytest

from hallucinote.capture import diff_snapshots, format_diff_summary


def _base_snapshot() -> dict:
    """Minimal-but-realistic snapshot used as both sides of the diff. Tests
    deep-copy and mutate it."""
    return {
        "song": {
            "tempo": 120.0,
            "signature": "4/4",
            "master": {"volume": 0.85, "panning": 0.0},
        },
        "returns": [
            {
                "index": 1, "name": "Reverb", "volume": 0.85, "panning": 0.0,
                "devices": [
                    {"index": 1, "name": "Reverb", "class": "Reverb"},
                ],
            },
            {
                "index": 2, "name": "Delay", "volume": 0.85, "panning": 0.0,
                "devices": [
                    {"index": 1, "name": "Delay", "class": "Delay"},
                ],
            },
        ],
        "tracks": [
            {
                "index": 1, "name": "Drums", "type": "midi",
                "volume": 0.65, "panning": 0.0,
                "sends": {"Reverb": 0.0, "Delay": 0.0},
                "devices": [
                    {
                        "index": 1, "name": "Kit", "class": "Drum Rack",
                        "params_dialed": {
                            "Volume": {"value": "0 dB", "normalized": 0.85},
                        },
                    },
                    {"index": 2, "name": "EQ Eight", "class": "EQ Eight"},
                ],
            },
            {
                "index": 2, "name": "Bass", "type": "midi",
                "volume": 0.6, "panning": -0.1,
                "sends": {"Reverb": 0.0},
                "devices": [
                    {"index": 1, "name": "Operator", "class": "Operator"},
                ],
            },
        ],
    }


# ---------- identity boundary: empty diff ----------


def test_identical_snapshots_yield_empty_diff() -> None:
    snap = _base_snapshot()
    assert diff_snapshots(snap, copy.deepcopy(snap)) == {}


def test_format_summary_handles_empty_diff() -> None:
    assert format_diff_summary({}) == "No changes — snapshot is up to date."


# ---------- song / master ----------


def test_song_tempo_change_surfaces() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["song"]["tempo"] = 132.0
    diff = diff_snapshots(old, new)
    assert diff == {"song": {"tempo": {"old": 120.0, "new": 132.0}}}


def test_master_volume_change_surfaces() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["song"]["master"]["volume"] = 0.7
    diff = diff_snapshots(old, new)
    assert diff == {"master": {"volume": {"old": 0.85, "new": 0.7}}}


def test_song_field_unchanged_when_both_missing() -> None:
    """A field absent from both sides shouldn't show up (None-vs-missing
    parity matters because the snapshot writer sometimes omits null fields)."""
    old = {"song": {"tempo": 120.0}, "returns": [], "tracks": []}
    new = {"song": {"tempo": 120.0}, "returns": [], "tracks": []}
    assert diff_snapshots(old, new) == {}


# ---------- returns ----------


def test_return_added_and_removed_by_index() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    # remove return 2 (Delay), add return 3 (Compressor)
    new["returns"] = [
        new["returns"][0],
        {"index": 3, "name": "Compressor", "volume": 0.85, "panning": 0.0},
    ]
    diff = diff_snapshots(old, new)
    assert list(diff.keys()) == ["returns"]
    assert len(diff["returns"]["added"]) == 1
    assert diff["returns"]["added"][0]["name"] == "Compressor"
    assert len(diff["returns"]["removed"]) == 1
    assert diff["returns"]["removed"][0]["name"] == "Delay"


def test_return_rename_reported_as_field_change_not_add_remove() -> None:
    """Matching is by index; a rename at the same index is a field change."""
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["returns"][0]["name"] = "Hall Reverb"
    diff = diff_snapshots(old, new)
    assert "returns" in diff
    assert "added" not in diff["returns"]
    assert "removed" not in diff["returns"]
    changed = diff["returns"]["changed"]
    assert len(changed) == 1
    assert changed[0]["field_changes"] == {
        "name": {"old": "Reverb", "new": "Hall Reverb"},
    }


def test_return_volume_change_surfaces() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["returns"][1]["volume"] = 0.7
    diff = diff_snapshots(old, new)
    assert diff["returns"]["changed"][0]["field_changes"] == {
        "volume": {"old": 0.85, "new": 0.7},
    }


# ---------- tracks ----------


def test_track_mixer_drift_surfaces() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["volume"] = 0.5
    new["tracks"][0]["mute"] = True
    diff = diff_snapshots(old, new)
    track_changes = diff["tracks"]["changed"][0]["field_changes"]
    assert track_changes == {
        "volume": {"old": 0.65, "new": 0.5},
        "mute": {"old": None, "new": True},
    }


def test_track_rename_reported_as_field_change() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["name"] = "Kit"
    diff = diff_snapshots(old, new)
    fc = diff["tracks"]["changed"][0]["field_changes"]
    assert fc == {"name": {"old": "Drums", "new": "Kit"}}


def test_track_index_change_reads_as_remove_plus_add() -> None:
    """Reorders surface as removed-from-old-index + added-at-new-index — Live
    track names aren't unique enough to use as identity, so we don't try."""
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["index"] = 5
    diff = diff_snapshots(old, new)
    assert {it["index"] for it in diff["tracks"]["added"]} == {5}
    assert {it["index"] for it in diff["tracks"]["removed"]} == {1}


# ---------- sends ----------


def test_send_added_removed_changed() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    # On Drums: change Reverb level, drop Delay
    new["tracks"][0]["sends"] = {"Reverb": 0.5}
    # On Bass: add Delay send
    new["tracks"][1]["sends"] = {"Reverb": 0.0, "Delay": 0.3}
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    assert drums["sends"] == {
        "changed": {"Reverb": {"old": 0.0, "new": 0.5}},
        "removed": {"Delay": 0.0},
    }
    bass = next(t for t in diff["tracks"]["changed"] if t["index"] == 2)
    assert bass["sends"] == {"added": {"Delay": 0.3}}


# ---------- devices ----------


def test_device_added_at_same_chain_position() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["devices"].append(
        {"index": 3, "name": "Glue", "class": "Glue Compressor"}
    )
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    assert drums["devices"]["added"][0]["name"] == "Glue"


def test_device_removed_at_position() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    # remove the EQ Eight at index 2
    new["tracks"][0]["devices"] = [new["tracks"][0]["devices"][0]]
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    assert drums["devices"]["removed"][0]["name"] == "EQ Eight"


def test_device_param_value_change_surfaces() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["devices"][0]["params_dialed"]["Volume"] = {
        "value": "-3 dB", "normalized": 0.6,
    }
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    dev_changed = drums["devices"]["changed"][0]
    assert dev_changed["params"] == {
        "changed": {
            "Volume": {
                "old": {"value": "0 dB", "normalized": 0.85},
                "new": {"value": "-3 dB", "normalized": 0.6},
            },
        },
    }


def test_device_param_added_and_removed() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["devices"][0]["params_dialed"] = {
        "Filter": {"value": "12 kHz", "normalized": 0.93},
    }
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    params = drums["devices"]["changed"][0]["params"]
    assert "added" in params
    assert "Filter" in params["added"]
    assert "removed" in params
    assert "Volume" in params["removed"]


def test_device_class_change_surfaces() -> None:
    """Device class drift (someone swapped Reverb for Echo) is a field-change,
    not add/remove (matching is by position, not class)."""
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["returns"][0]["devices"][0] = {
        "index": 1, "name": "Echo", "class": "Echo",
    }
    diff = diff_snapshots(old, new)
    ret = diff["returns"]["changed"][0]
    dev_changed = ret["devices"]["changed"][0]
    assert dev_changed["field_changes"] == {
        "name": {"old": "Reverb", "new": "Echo"},
        "class": {"old": "Reverb", "new": "Echo"},
    }


# ---------- nested rack chains ----------


def test_nested_rack_chain_device_added() -> None:
    old = _base_snapshot()
    old["tracks"][0]["devices"][0]["chains"] = [
        {
            "chain_index": 1, "name": "Kick",
            "devices": [{"index": 1, "name": "Kick Drum", "class": "Sampler"}],
        },
    ]
    new = copy.deepcopy(old)
    new["tracks"][0]["devices"][0]["chains"][0]["devices"].append(
        {"index": 2, "name": "EQ", "class": "EQ Eight"}
    )
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    chain_change = drums["devices"]["changed"][0]["chains"]["changed"][0]
    assert chain_change["devices"]["added"][0]["name"] == "EQ"


def test_nested_chain_added_whole_chain() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["devices"][0]["chains"] = [
        {
            "chain_index": 1, "name": "Snare",
            "devices": [{"index": 1, "name": "Snare", "class": "Sampler"}],
        },
    ]
    diff = diff_snapshots(old, new)
    drums = next(t for t in diff["tracks"]["changed"] if t["index"] == 1)
    chain_diff = drums["devices"]["changed"][0]["chains"]
    assert len(chain_diff["added"]) == 1


# ---------- format summary smoke ----------


def test_format_summary_lists_track_and_return_changes() -> None:
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["song"]["tempo"] = 132.0
    new["tracks"][0]["volume"] = 0.5
    new["returns"][0]["name"] = "Hall Reverb"
    summary = format_diff_summary(diff_snapshots(old, new))
    # Doesn't lock format strictly; just checks the user sees what changed.
    assert "tempo" in summary
    assert "track 1" in summary or "track" in summary.lower()
    assert "return 1" in summary or "return" in summary.lower()


@pytest.mark.parametrize("mutator", [
    lambda s: s["song"].__setitem__("tempo", 99.0),
    lambda s: s["returns"].pop(0),
    lambda s: s["tracks"][0].__setitem__("volume", 0.1),
])
def test_diff_truthy_when_any_change(mutator) -> None:
    """Skill branches on `if diff:` — confirm the empty-vs-non-empty contract
    holds for any of the change categories."""
    old = _base_snapshot()
    new = copy.deepcopy(old)
    mutator(new)
    assert diff_snapshots(old, new), "expected diff to be truthy after mutation"


# ---------- merge_snapshots: browser_path stickiness (G1-C) ----------


def test_merge_preserves_track_device_browser_path_when_new_omits_it() -> None:
    """Refresh probes use list-time tools (ableton_track(action='info'),
    ableton_device(action='get_parameters')) which don't surface
    browser_path — only the load-time response carries `resolved_path`.
    Without stickiness, every snapshot refresh would wipe the cross-
    machine fallback identity captured at load time. Merge keeps it.
    """
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    old["tracks"][1]["devices"][0]["browser_path"] = [
        "instruments", "Operator", "Bass",
    ]
    new = copy.deepcopy(old)
    # Refresh probe forgot browser_path on the Operator (the realistic case).
    del new["tracks"][1]["devices"][0]["browser_path"]
    merged = merge_snapshots(old, new)
    assert merged["tracks"][1]["devices"][0]["browser_path"] == [
        "instruments", "Operator", "Bass",
    ]


def test_merge_lets_new_browser_path_overwrite_when_present() -> None:
    """If the refresh DOES carry browser_path (e.g. a future load-time
    autonomous capture lands), the new value wins — merge isn't a one-way
    accretion path. Drift toward fresher state, not toward older."""
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    old["tracks"][1]["devices"][0]["browser_path"] = [
        "instruments", "Operator", "OldPreset",
    ]
    new = copy.deepcopy(old)
    new["tracks"][1]["devices"][0]["browser_path"] = [
        "instruments", "Operator", "NewPreset",
    ]
    merged = merge_snapshots(old, new)
    assert merged["tracks"][1]["devices"][0]["browser_path"] == [
        "instruments", "Operator", "NewPreset",
    ]


def test_merge_preserves_return_device_browser_path() -> None:
    """Returns get the same stickiness as tracks — symmetric paths."""
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    old["returns"][0]["devices"][0]["browser_path"] = [
        "audio_effects", "Reverb", "Hall",
    ]
    new = copy.deepcopy(old)
    del new["returns"][0]["devices"][0]["browser_path"]
    merged = merge_snapshots(old, new)
    assert merged["returns"][0]["devices"][0]["browser_path"] == [
        "audio_effects", "Reverb", "Hall",
    ]


def test_merge_preserves_browser_path_inside_nested_rack_chain() -> None:
    """Devices inside a rack's nested chain get the same stickiness —
    the depth-1 walk mirrors capture / replay / diff."""
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    old["tracks"][0]["devices"][0]["chains"] = [
        {
            "chain_index": 1, "name": "Lead", "devices": [
                {
                    "index": 1, "name": "Compressor", "class": "Compressor",
                    "browser_path": ["audio_effects", "Compressor"],
                },
            ],
        },
    ]
    new = copy.deepcopy(old)
    del new["tracks"][0]["devices"][0]["chains"][0]["devices"][0]["browser_path"]
    merged = merge_snapshots(old, new)
    nested = merged["tracks"][0]["devices"][0]["chains"][0]["devices"][0]
    assert nested["browser_path"] == ["audio_effects", "Compressor"]


def test_merge_doesnt_resurrect_devices_dropped_from_new() -> None:
    """If new omits a device that old had, the merge follows new — old
    isn't allowed to resurrect dropped state. Same shape for tracks /
    returns / chains."""
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    old["tracks"][0]["devices"][0]["browser_path"] = ["x"]
    new = copy.deepcopy(old)
    # User deleted the Drum Rack between snapshots.
    new["tracks"][0]["devices"] = [d for d in new["tracks"][0]["devices"]
                                    if d["index"] != 1]
    merged = merge_snapshots(old, new)
    assert [d["index"] for d in merged["tracks"][0]["devices"]] == [2]


def test_merge_non_sticky_fields_use_new_value() -> None:
    """A knob move captured in the fresh probe must overwrite the on-disk
    value — only declared sticky fields are special. Volume drift through.
    """
    from hallucinote.capture import merge_snapshots
    old = _base_snapshot()
    new = copy.deepcopy(old)
    new["tracks"][0]["volume"] = 0.5
    merged = merge_snapshots(old, new)
    assert merged["tracks"][0]["volume"] == 0.5
