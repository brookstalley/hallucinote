"""Backlog feature probes — registered against the post-sync advisory infra.

Phase 2 (v1.7.0) ships exactly one production probe: ``legacy-backlog-format``,
which nudges a product whose ``.prawduct/backlog.md`` is still in the legacy
unstructured form (no ``[PFX-XXXX]`` ids) to run ``/backlog migrate``. The other
three probes from backlog-system-requirements.md §8.2 (external-detected,
legacy-section-schema, overdue-grooming) are deferred — see the v1.7.0 build
plan's "Out of scope (deferred)".

**Registration model.** Unlike the spec's import-time-side-effect sketch, this
module exposes an *idempotent* ``register_backlog_probes()`` that
``advisory_store.run_sync_advisories`` calls on every sync. Import-time
registration would be wiped by the ``clear_registry()`` that advisory tests run
in teardown and never restored (a cached module's top-level code does not
re-run), so a later sync would silently lose the probe. An explicit idempotent
call sidesteps that entirely (``register_probe`` overwrites the same key).

Conventions (project-preferences): return-value based, no raising in probe
internals — disk reads degrade to a safe default so a sync never crashes on a
malformed or absent backlog file. The probe's evidence is deliberately *stable*
across incidental item-count changes (``compute_id`` hashes the evidence): the
live count lives in ``trigger_summary`` (not hashed), so adding a legacy item
between syncs doesn't churn the advisory id (idempotency, spec A2).
"""

from __future__ import annotations

import re
from pathlib import Path

from .advisory_store import AdvisoryCandidate, Codebase, ProjectState, register_probe

# A structured id token as it appears in an item title: ``**[STH-K7p2]**``.
# PFX = 2–3 uppercase letters; the 4-char suffix is base36 (mixed case allowed).
_ID_RE = re.compile(r"\[[A-Z]{2,3}-[A-Za-z0-9]{4}\]")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Top-level markdown list item (column-0 bullet) — the start of a backlog item.
_TOP_ITEM_RE = re.compile(r"^- ", re.MULTILINE)
_LEGACY_HEADINGS = ("## Active — next up", "## Queue")

# Migration is "done" once the skill writes this fact to project-state.yaml.
_RESOLVED_FORMAT_VERSION = 2
# Trigger floor (requirements §8.2): >5 items, none structured.
_LEGACY_ITEM_FLOOR = 5


def _strip_comments(text: str) -> str:
    """Drop HTML comment blocks so example/instruction bullets inside the
    template's conventions header are not counted as real items."""
    return _COMMENT_RE.sub("", text)


def count_backlog_items(text: str) -> tuple[int, int]:
    """Return ``(total_top_level_items, structured_items)`` for backlog markdown.

    A top-level item is a column-0 ``- `` bullet (after stripping HTML
    comments). ``structured`` counts those whose line carries a ``[PFX-XXXX]``
    id. Public (return-value helper) so it can be unit-tested directly.
    """
    body = _strip_comments(text)
    total = 0
    structured = 0
    for line in body.splitlines():
        if not _TOP_ITEM_RE.match(line):
            continue
        total += 1
        if _ID_RE.search(line):
            structured += 1
    return total, structured


def _has_legacy_headings(text: str) -> bool:
    body = _strip_comments(text)
    return any(h in body for h in _LEGACY_HEADINGS)


def _format_migrated(state: ProjectState) -> bool:
    """True once ``backlog_format_version`` indicates migration is complete."""
    value = state.get("backlog_format_version")
    if value is None:
        return False
    try:
        return int(value) >= _RESOLVED_FORMAT_VERSION
    except (TypeError, ValueError):
        return False


def legacy_backlog_format_probe(
    state: ProjectState, codebase: Codebase
) -> list[AdvisoryCandidate]:
    """Fire when ``.prawduct/backlog.md`` has >5 items, none structured, and the
    project has not recorded ``backlog_format_version: 2``.

    Resolution condition (shared answer store, spec §7.1): reads
    ``backlog_format_version`` from project-state.yaml — set by ``/backlog
    migrate`` on completion — so a teammate's migration auto-resolves the
    advisory for everyone on next sync, decoupled from local code state.
    """
    if _format_migrated(state):
        return []

    backlog_path = Path(codebase.root) / ".prawduct" / "backlog.md"
    try:
        text = backlog_path.read_text(encoding="utf-8")
    except OSError:
        return []  # no backlog file → nothing to nag about

    total, structured = count_backlog_items(text)
    # Trigger only when nothing has been migrated yet (requirements §8.2:
    # ">5 items, none carrying [PFX-XXXX] ids"). A partially-migrated file is
    # mid-flight; the format_version fact is the authoritative "done" signal.
    if total <= _LEGACY_ITEM_FLOOR or structured > 0:
        return []

    # Stable evidence (hashed into the id) — qualitative, count-independent so
    # the id stays put as items come and go. Live count goes in the summary.
    evidence = [".prawduct/backlog.md contains items without [PFX-XXXX] structured ids"]
    if _has_legacy_headings(text):
        evidence.append(
            "legacy section headings present (## Active — next up / ## Queue)"
        )

    summary = (
        f"{total} backlog items lack [PFX-XXXX] structured ids — run "
        "/backlog migrate to add metadata and enable pick/find/list filtering."
    )
    return [
        AdvisoryCandidate(
            type="legacy-backlog-format",
            evidence=tuple(evidence),
            trigger_summary=summary,
            recommended_action="/backlog migrate",
            priority="info",
        )
    ]


def register_backlog_probes() -> None:
    """Register the backlog feature's production probes. Idempotent — safe to
    call on every sync (``register_probe`` overwrites the same ``(feature,
    type)`` key). Called by ``advisory_store.run_sync_advisories``."""
    register_probe("backlog", "legacy-backlog-format", 1, legacy_backlog_format_probe)
