"""Tests for the centralized analyzer-identity predicate (SNP-8R4K chunk 1).

The HallucinoteAnalyzer is measurement infrastructure, not authored content;
`is_analyzer_device` is the one engine-side predicate that recognizes it at
every Live↔model boundary. These tests pin it across the three device
representations the engine sees, plus the drift-guard against the MCP constant.
"""
from __future__ import annotations

import sqlite3


from hallucinote.analyzer_identity import (
    ANALYZER_DEVICE_NAME,
    is_analyzer_device,
)


def test_constant_is_the_amxd_name():
    assert ANALYZER_DEVICE_NAME == "HallucinoteAnalyzer"


# ---------- the three representations: positive cases ----------


def test_snapshot_device_dict_is_analyzer():
    """Snapshot device dict: {class, name, class_name}. Name is the marker."""
    device = {
        "index": 3,
        "name": "HallucinoteAnalyzer",
        "class": "Max Audio Effect",
        "class_name": "MxDeviceAudioEffect",
    }
    assert is_analyzer_device(device) is True


def test_probed_live_entry_is_analyzer():
    """Pull `ableton_device(action='list')` entry: name is the marker."""
    entry = {
        "device_index": 2,
        "name": "HallucinoteAnalyzer",
        "class_name": "MxDeviceAudioEffect",
        "class_display_name": "Max Audio Effect",
        "is_active": True,
    }
    assert is_analyzer_device(entry) is True


def test_db_row_dict_is_analyzer():
    """DB device row carries the name in `display_name`."""
    row = {
        "kind": "Max Audio Effect",
        "display_name": "HallucinoteAnalyzer",
        "class_name": "MxDeviceAudioEffect",
        "position": 4,
    }
    assert is_analyzer_device(row) is True


def test_sqlite3_row_is_analyzer():
    """A real sqlite3.Row (no .get(), supports `in`/`[]`) is handled."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 'Max Audio Effect' AS kind, "
        "'HallucinoteAnalyzer' AS display_name, "
        "'MxDeviceAudioEffect' AS class_name"
    ).fetchone()
    conn.close()
    assert is_analyzer_device(row) is True


# ---------- negatives: ordinary authored devices are NOT the analyzer ----------


def test_ordinary_compressor_is_not_analyzer():
    device = {"index": 1, "name": "Compressor", "class": "Compressor"}
    assert is_analyzer_device(device) is False


def test_other_m4l_device_is_not_analyzer():
    """class_name/class is generic to all M4L — name discriminates."""
    device = {
        "index": 1,
        "name": "SomeOtherM4LThing",
        "class": "Max Audio Effect",
        "class_name": "MxDeviceAudioEffect",
    }
    assert is_analyzer_device(device) is False


def test_db_row_ordinary_device_is_not_analyzer():
    row = {"kind": "EQ Eight", "display_name": "EQ Eight", "class_name": "Eq8"}
    assert is_analyzer_device(row) is False


def test_device_without_name_field_is_not_analyzer():
    assert is_analyzer_device({"class": "Compressor"}) is False


def test_non_mapping_without_keys_is_not_analyzer():
    """A bare object with no name/keys must not raise — returns False."""
    assert is_analyzer_device(object()) is False


# ---------- drift guard: engine constant == MCP constant ----------


def test_engine_constant_matches_mcp_constant():
    """SNP-8R4K R1: the engine mirrors the MCP analyzer name (the engine can't
    import the MCP package — dependency direction is MCP→engine). This guard
    fails if the two ever diverge so the boundary exclusion can't go blind.
    """
    from hallucinote_mcp.analyzer.setup import (
        ANALYZER_DEVICE_NAME as MCP_ANALYZER_DEVICE_NAME,
    )

    assert ANALYZER_DEVICE_NAME == MCP_ANALYZER_DEVICE_NAME
