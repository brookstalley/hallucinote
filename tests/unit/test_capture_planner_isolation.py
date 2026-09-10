"""``capture.py`` does not import the push PLANNER package.

The edge already runs the other way: ``sync/pull/devices.py`` imports
``hallucinote.capture``, so a capture→planner import closes a cycle the moment
any planner needs something from capture. It is also the wrong home for the
knowledge — capture once reached into ``sync.push.probe`` for the four-element
frozenset naming Live's default scaffold, which put the canonical definition of
a *Live* fact inside the push planner and made a capture maintainer read planner
internals to find it. The cost was not only conceptual: importing
``sync.push.probe`` executes ``sync/push/__init__.py``, which pulls in every
planner module.

Shared predicates about Live go in neutral modules that both sides import —
:mod:`hallucinote.default_scaffold` for the scaffold names,
:mod:`hallucinote.analyzer_identity` for the other half of the same capture
filter. This test is the structural guard; without it the import comes back the
next time capture needs a planner constant, because that is the shortest path.
"""
from __future__ import annotations

import re
from pathlib import Path

import hallucinote

_PKG_ROOT = Path(hallucinote.__file__).parent
_CAPTURE = _PKG_ROOT / "capture.py"

_PLANNER_IMPORT = re.compile(
    r"^\s*(?:"
    r"import\s+hallucinote\.sync\.push\b"
    r"|from\s+hallucinote\.sync\.push\b"
    r"|from\s+hallucinote\.sync\s+import\s+(?:[^\n]*\b)?push\b"
    r"|from\s+\.+sync\.push\b"
    r")",
    re.MULTILINE,
)


def test_capture_does_not_import_the_push_planner_package():
    source = _CAPTURE.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if _PLANNER_IMPORT.match(line)
    ]
    assert not offenders, (
        "capture.py must not import hallucinote.sync.push — put the shared "
        "predicate in a neutral module (see hallucinote.default_scaffold) and "
        f"import it from both sides; offenders: {offenders}"
    )


def test_the_scaffold_names_come_from_the_neutral_module_on_both_sides():
    """Guard the guard: both readers must resolve to the SAME object, or the
    regex above passes over a second, drifting copy."""
    from hallucinote import capture, default_scaffold
    from hallucinote.sync.push import probe

    assert (
        capture.CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
        is default_scaffold.CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
    )
    assert (
        probe.CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
        is default_scaffold.CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
    )


def test_the_planner_import_regex_catches_the_import_it_replaced():
    for sample in (
        "from hallucinote.sync.push.probe import CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES",
        "import hallucinote.sync.push",
        "from hallucinote.sync.push import probe",
        "from hallucinote.sync import push",
        "from .sync.push.probe import anything",
    ):
        assert _PLANNER_IMPORT.match(sample), sample
