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
# Snapshot BEFORE the package import: anything the package __init__ pulls in
# transitively must count against the package, not vanish into the baseline.
baseline = set(sys.modules)
pkg = importlib.import_module({pkg!r})
leaks = {{}}
def pulled_since(before):
    return sorted(
        x for x in set(sys.modules) - before
        if x.startswith('hallucinote.db') or x.startswith('hallucinote.sync')
        or x.startswith('hallucinote_mcp')
    )
init_leak = pulled_since(baseline)
if init_leak:
    leaks[pkg.__name__] = init_leak
for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.'):
    before = set(sys.modules)
    importlib.import_module(m.name)
    pulled = pulled_since(before)
    if pulled:
        leaks[m.name] = pulled
    # Forget only OUR modules between steps so each one is attributed on its
    # own imports; third-party modules (numpy) cannot be re-imported once
    # popped and are never what the lock is looking for.
    for x in set(sys.modules) - before:
        if x.startswith('hallucinote') and x != pkg.__name__:
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
        cwd=str(_REPO),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    # A module that fails to import is the first thing a coordinator meets at
    # integration; name it rather than hiding the traceback in an exit code.
    assert out.returncode == 0, f"walking {pkg} failed:\n{out.stderr}"
    leaks = json.loads(out.stdout)
    unexpected = {m: v for m, v in leaks.items() if m not in _ALLOWED_TO_READ_STATE}
    assert not unexpected, (
        f"{pkg} modules pulled in DB / sync / MCP code: {unexpected}. "
        "A field builder that must read state is listed in _ALLOWED_TO_READ_STATE by name."
    )


def test_the_lock_sees_what_a_package_init_pulls_in(tmp_path: Path) -> None:
    """A package whose __init__ imports the DB must fail the walk — the lock is
    only worth having if the baseline is taken before the package loads."""
    import json

    pkg_dir = tmp_path / "leaky"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("import hallucinote.db\n")
    (pkg_dir / "inner.py").write_text("X = 1\n")
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(pkg="leaky")],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        env={**os.environ, "PYTHONPATH": f"src{os.pathsep}{tmp_path}"},
    )
    assert out.returncode == 0, out.stderr
    leaks = json.loads(out.stdout)
    assert "leaky" in leaks and any(m.startswith("hallucinote.db") for m in leaks["leaky"])
