"""Import-graph lock for the sampling packages.

``assets/``, ``features/`` and ``spectral/`` are consumed by generators (which
are pure) and by ``build.py`` (which must open without Live). Locking the
import GRAPH rather than the source text is what makes the rule hold — a
function-local ``from hallucinote.db import ...`` passes a grep and still
couples the packages at run time. The two field builders that read the DB and
the capture set by design are named here, not exempted by pattern.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Modules that read the score or the capture set on purpose. Anything else
# under these packages that pulls in db / sync / mcp is a leak.
_ALLOWED_TO_READ_STATE = {
    "hallucinote.spectral.symbolic",
    "hallucinote.spectral.measured",
}

_PROBE = """
import importlib, pkgutil, sys, json
pkg = importlib.import_module({pkg!r})
leaks = {{}}
for m in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + '.'):
    before = set(sys.modules)
    importlib.import_module(m.name)
    pulled = sorted(
        x for x in set(sys.modules) - before
        if x.startswith('hallucinote.db') or x.startswith('hallucinote.sync')
        or x.startswith('hallucinote_mcp')
    )
    if pulled:
        leaks[m.name] = pulled
    for x in set(sys.modules) - before:
        sys.modules.pop(x, None)
print(json.dumps(leaks))
"""


@pytest.mark.parametrize("pkg", ["hallucinote.assets", "hallucinote.features", "hallucinote.spectral"])
def test_sampling_package_imports_no_state_code(pkg: str) -> None:
    import json

    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(pkg=pkg)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(_REPO),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    leaks = json.loads(out.stdout)
    unexpected = {m: v for m, v in leaks.items() if m not in _ALLOWED_TO_READ_STATE}
    assert not unexpected, (
        f"{pkg} modules pulled in DB / sync / MCP code: {unexpected}. "
        "A field builder that must read state is listed in _ALLOWED_TO_READ_STATE by name."
    )
