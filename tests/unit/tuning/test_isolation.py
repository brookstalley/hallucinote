"""FR-6: the core path imports nothing from ``hallucinote.tuning``.

The whole MICROTUNE bet is "isolation over integration" — alternate-tuning logic
is a bolt-on the 99.99% never pay for. The structural guarantee is one-directional:
``tuning`` may import the core (mutators, queries — see ``store.py``), but **no
core module may import ``tuning``**. This test grep-asserts that across the entire
engine package, so a future accidental ``from hallucinote.tuning import ...`` in a
generator / theory / sync module fails CI instead of silently coupling the core.
"""
from __future__ import annotations

import re
from pathlib import Path

import hallucinote

_PKG_ROOT = Path(hallucinote.__file__).parent
_TUNING_DIR = _PKG_ROOT / "tuning"

# Any way a module could pull in the tuning package: absolute, from-import, or
# relative (`from .tuning`, `from . import tuning`, `from ..tuning`).
_TUNING_IMPORT = re.compile(
    r"^\s*(?:"
    r"import\s+hallucinote\.tuning"
    r"|from\s+hallucinote\.tuning\b"
    r"|from\s+hallucinote\s+import\s+(?:[^\n]*\b)?tuning\b"
    r"|from\s+\.+tuning\b"
    r"|from\s+\.+\s+import\s+(?:[^\n]*\b)?tuning\b"
    r")",
    re.MULTILINE,
)


def _core_py_files() -> list[Path]:
    return [
        p
        for p in _PKG_ROOT.rglob("*.py")
        if _TUNING_DIR not in p.parents and "__pycache__" not in p.parts
    ]


def test_core_files_exist_and_exclude_tuning():
    files = _core_py_files()
    assert files, "expected to find core hallucinote modules to scan"
    assert all(_TUNING_DIR not in p.parents for p in files)


def test_no_core_module_imports_tuning():
    offenders = []
    for path in _core_py_files():
        if _TUNING_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(_PKG_ROOT)))
    assert not offenders, (
        "core modules must not import hallucinote.tuning (isolation invariant, "
        f"FR-6); offenders: {offenders}"
    )


def test_tuning_regex_actually_catches_imports():
    # Guard the guard: the pattern must match the very imports tuning/store.py
    # uses in reverse, so a real offender can't slip past a broken regex.
    for sample in (
        "import hallucinote.tuning",
        "from hallucinote.tuning import mapper",
        "from hallucinote.tuning.mapper import degree_to_midi",
        "from hallucinote import tuning",
        "from .tuning import model",
        "from . import tuning",
    ):
        assert _TUNING_IMPORT.search(sample), sample
