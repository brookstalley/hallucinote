"""Drift guard for the discoverable authoring-API surface (build-plan B2).

`/compose-part` tells the agent to author notes against the helper set indexed
in ``docs/song-authoring-conventions.md`` → *Authoring API*. That index is the
progressive-disclosure entry point, so it must stay true to the actual
``hallucinote.generators`` modules in BOTH directions:

  - every ``module.function`` the doc names must be importable + callable
    (a stale doc that points at a renamed/removed helper is worse than none);
  - every public generator function in the documented modules must appear in
    the doc (a new helper nobody can discover is invisible expressivity).

Living Documentation as a test, not a hope. Update the doc and this passes.
"""
from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "song-authoring-conventions.md"

# Modules indexed by the Authoring API section. Keep in sync with the doc's
# module headings; the test below asserts the doc covers each module's surface.
DOCUMENTED_MODULES = ("drums", "bass", "harmony", "primitives")

# ``module.function`` tokens (e.g. `drums.kick_stumble`) inside backticks.
_REF_RE = re.compile(
    r"`(" + "|".join(DOCUMENTED_MODULES) + r")\.([a-z_][a-z0-9_]*)`"
)


def _authoring_api_section() -> str:
    """The text of the '## Authoring API' section (header → next '## ')."""
    text = DOC_PATH.read_text(encoding="utf-8")
    start = text.find("## Authoring API")
    assert start != -1, "docs/song-authoring-conventions.md lost its Authoring API section"
    rest = text[start + len("## Authoring API"):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _documented_refs() -> set[tuple[str, str]]:
    return {(m, f) for m, f in _REF_RE.findall(_authoring_api_section())}


def _public_functions(module_name: str) -> set[str]:
    """Public functions DEFINED in the module (not re-imported into it)."""
    mod = importlib.import_module(f"hallucinote.generators.{module_name}")
    return {
        name
        for name in dir(mod)
        if not name.startswith("_")
        and inspect.isfunction(getattr(mod, name))
        and getattr(mod, name).__module__ == mod.__name__
    }


def test_doc_references_resolve_to_callables():
    """Every helper the Authoring API index names is importable + callable."""
    refs = _documented_refs()
    assert refs, "Authoring API section names no module.function helpers — index is empty"
    for module_name, func_name in sorted(refs):
        mod = importlib.import_module(f"hallucinote.generators.{module_name}")
        assert hasattr(mod, func_name), (
            f"docs name `{module_name}.{func_name}` but it's not in "
            f"hallucinote.generators.{module_name} — fix the doc or the import"
        )
        assert callable(getattr(mod, func_name)), (
            f"`{module_name}.{func_name}` is documented as a helper but isn't callable"
        )


@pytest.mark.parametrize("module_name", DOCUMENTED_MODULES)
def test_every_public_helper_is_documented(module_name):
    """No undiscoverable expressivity: each public generator fn is in the index."""
    documented = {f for m, f in _documented_refs() if m == module_name}
    actual = _public_functions(module_name)
    missing = actual - documented
    assert not missing, (
        f"hallucinote.generators.{module_name} exposes {sorted(missing)} but the "
        f"Authoring API index in {DOC_PATH.name} doesn't list them — add a row so "
        f"the agent can discover them via /compose-part"
    )
