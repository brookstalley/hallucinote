"""Post-sync advisory infrastructure — store, registry, and sync-diff.

Implements Phase 1 of ``documentation/post-sync-advisory-spec.md`` (v0.2): the
shared mechanism by which sync probes surface "this project should probably do
X, but we won't force it" nudges to the user at session start.

Two stores, sharply distinct (spec §3.5):
  - ``.prawduct/.advisories.json`` (gitignored, per-clone) — the *nag log*.
    Holds active triggers and per-developer dismissal/resolution state. Owned
    by this module.
  - ``.prawduct/project-state.yaml`` (committed, shared) — the *answer store*.
    Holds settled facts probes consult (read-only here, via ``ProjectState``).

Deviations from the spec's illustrative ``tools/lib/probes/__init__.py`` layout
(reasoned in the build plan): the registry lives in this plain module — no
import-time registration in an ``__init__`` (avoids the re-export shadowing
documented in learnings) — and the CLI lands in ``advisory_cmd.py`` per the
``*_cmd.py`` convention. The spec's *semantics* (registry, ``(feature, type)``
keying, deterministic candidates, evidence-hash id) are preserved.

**Phase 1 scope.** The store, registry, id-hash, ProjectState/Codebase
wrappers, the sync diff covering ``active``/``resolved`` states (Ch 01),
sticky dismissal (Ch 02), probe-version supersession (Ch 03), and
retention/compaction/schema-migration (Ch 04). The CLI surface
(``advisory_cmd.py``) lands in Ch 05. The production probe roster is **empty**
— nothing is registered at import time — so a real sync produces an empty store
and no briefing section (no-op infrastructure ship).

Conventions (project-preferences): functions are return-value based — they
return dicts/values and never raise within tool internals; disk reads/writes
catch ``OSError``/``json.JSONDecodeError`` and degrade to a safe default so a
sync can never crash on a malformed store.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

# Schema version of the on-disk store. Incremented only on breaking changes;
# read-tolerance / forward-migration is implemented by ``_migrate_store`` (A7).
SCHEMA_VERSION = 1

# Relative location of the per-clone nag log (gitignored).
ADVISORY_STORE_REL = ".prawduct/.advisories.json"

# In-store evidence cap (spec §3.3, Q5 lean): keep the array short so the
# briefing stays scannable; the full list is reconstructible on demand via
# ``/prawduct-advisory show <id>`` (Chunk 05).
EVIDENCE_CAP = 5

# Retention policy (spec §3.4, Q4) — applied at sync-persist time by
# :func:`apply_retention`. Resolved entries are kept for reporting then GC'd;
# dismissed entries are kept forever (the dismissal is the load-bearing fact).
# The caps are *soft*: bound the store so it can't grow without limit in a
# long-running project. The active cap is a defensive guard — a real project
# never approaches 100 simultaneous live advisories (Phase 1 ships zero probes).
RESOLVED_TTL_DAYS = 30
ACTIVE_CAP = 100
RESOLVED_CAP = 50
DISMISSED_CAP = 200

# Priority vocabulary and briefing ordering (spec §3.3, §5.1).
VALID_PRIORITIES = ("info", "warn", "urgent")
PRIORITY_ORDER = {"urgent": 0, "warn": 1, "info": 2}

# Directories skipped by the Codebase scanner — cheap read-only scans only
# (spec §7.1: probes run on every sync).
_SCAN_SKIP_DIRS = {".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".prawduct"}


# =============================================================================
# Value objects (lock the probe signature for Phase 2/3)
# =============================================================================


@dataclass(frozen=True)
class AdvisoryCandidate:
    """One advisory a probe wants to raise.

    A probe sets ``type``, ``evidence``, ``trigger_summary``,
    ``recommended_action`` (and optionally ``priority`` / ``alternative_actions``).
    ``feature`` and ``probe_version`` are stamped from the registration by
    :func:`run_all_probes`, so a probe body need not repeat them. The ``id`` and
    ``triggered_at`` are computed by the store at write time, not by the probe.
    """

    type: str
    evidence: tuple[str, ...] = ()
    trigger_summary: str = ""
    recommended_action: str = ""
    alternative_actions: tuple[str, ...] = ()
    priority: str = "info"
    feature: str = ""
    probe_version: int = 0


class ProjectState:
    """Read-only view of top-level scalar facts from ``project-state.yaml``.

    The *answer store* (spec §3.5). Probes read resolution-condition facts here
    (e.g. ``uses_llm_inference``) — never from local code state — so a
    teammate's committed answer resolves the advisory for everyone on next sync.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def as_dict(self) -> dict:
        return dict(self._data)


@dataclass(frozen=True)
class Codebase:
    """Minimal read-only codebase wrapper exposing the two scan primitives the
    spec's example probes name (``has_imports``, ``has_files_matching``).

    Phase 1 implements only what the synthetic test probe exercises — a richer
    content scanner is built by the first feature that needs it (Phase 2/3, see
    Out of Scope). The point here is to *lock the probe signature* so later
    chunks don't churn it.
    """

    root: Path

    def has_imports(self, modules: Iterable[str]) -> bool:
        """True if any ``*.py`` file under ``root`` imports one of ``modules``."""
        mods = [m for m in modules if m]
        if not mods:
            return False
        pattern = re.compile(
            r"^\s*(?:import|from)\s+(?:"
            + "|".join(re.escape(m) for m in mods)
            + r")(?:\.|\s|$)",
            re.MULTILINE,
        )
        for py in self._iter_source_files("*.py"):
            try:
                text = py.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(text):
                return True
        return False

    def has_files_matching(self, *globs: str) -> bool:
        """True if any glob (relative to ``root``) matches at least one path."""
        for g in globs:
            if not g:
                continue
            if any(True for _ in self.root.glob(g)):
                return True
        return False

    def _iter_source_files(self, pattern: str):
        for path in self.root.rglob(pattern):
            if any(part in _SCAN_SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file():
                yield path


ProbeFn = Callable[[ProjectState, Codebase], Iterable[AdvisoryCandidate]]


# =============================================================================
# Probe registry — EMPTY in Phase 1 (no production probes registered)
# =============================================================================

# Keyed by ``f"{feature}:{probe_type}"`` → registration record. Module-level
# mutable state; tests register a synthetic probe and call clear_registry() in
# teardown. No production probe is registered at import time (no-op ship).
_REGISTRY: dict[str, dict] = {}


def register_probe(feature: str, probe_type: str, probe_version: int, fn: ProbeFn) -> None:
    """Register a probe under ``(feature, probe_type)``.

    Re-registering the same key overwrites — a feature owns its probe types.
    """
    _REGISTRY[f"{feature}:{probe_type}"] = {
        "feature": feature,
        "probe_type": probe_type,
        "probe_version": probe_version,
        "fn": fn,
    }


def clear_registry() -> None:
    """Empty the registry. Primarily for test isolation."""
    _REGISTRY.clear()


def run_all_probes(state: ProjectState, codebase: Codebase) -> list[AdvisoryCandidate]:
    """Run every registered probe and return enriched candidates.

    Each candidate is stamped with the ``feature`` and ``probe_version`` from
    its registration (and ``type`` defaults to the registered ``probe_type``
    when the probe left it blank). A probe that raises is skipped — one bad
    probe must not block the others or the sync.
    """
    candidates: list[AdvisoryCandidate] = []
    for record in _REGISTRY.values():
        fn = record["fn"]
        try:
            produced = list(fn(state, codebase))
        except Exception:  # prawduct:ok-broad-except — a faulty probe must not block sync; skip it
            continue
        for cand in produced:
            candidates.append(
                replace(
                    cand,
                    feature=record["feature"],
                    probe_version=record["probe_version"],
                    type=cand.type or record["probe_type"],
                )
            )
    return candidates


# =============================================================================
# Identity
# =============================================================================


def compute_id(feature: str, probe_type: str, probe_version: int, evidence: Iterable[str]) -> str:
    """Stable advisory id: ``<feature>-<probe_type>-v<probe_version>-<hash6>``.

    The hash is a 6-char SHA-256 digest of the *full* evidence list (joined by
    newlines), so the id reflects the true trigger even though the store keeps
    only the first ``EVIDENCE_CAP`` citations (spec Q5). Same evidence + same
    probe version → same id (idempotent, spec §2.2). Bumping ``probe_version``
    yields a new id, enabling clean supersession (spec §2.8, Chunk 03).

    Phase 1 uses the literal ``feature`` token as the id prefix; the spec's
    "feature-prefix" abbreviation (``prompts`` for ``prompt-management``) is
    illustrative and a probe simply chooses a short ``feature`` token.
    """
    joined = "\n".join(evidence)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:6]
    return f"{feature}-{probe_type}-v{probe_version}-{digest}"


# =============================================================================
# Store I/O
# =============================================================================


def _store_path(product_dir) -> Path:
    return Path(product_dir) / ADVISORY_STORE_REL


def _empty_store() -> dict:
    return {"schema_version": SCHEMA_VERSION, "advisories": []}


def _migrate_store(data: dict) -> dict:
    """Forward-migrate an on-disk store to the current schema (spec A7).

    A lower or absent ``schema_version`` is normalized up to ``SCHEMA_VERSION``
    in place — at v1 there are no field renames, so migration is a relabel;
    future breaking versions add per-version transforms here keyed on the
    starting ``version``. A *higher* version (a store written by a newer
    prawduct) is read as-is rather than crashing — unknown fields round-trip
    untouched. Either way the read never raises (return-value convention).
    """
    version = data.get("schema_version")
    if not isinstance(version, int):
        version = 0  # absent / garbage → treat as pre-v1
    if version < SCHEMA_VERSION:
        data["schema_version"] = SCHEMA_VERSION
    return data


def read_store(product_dir) -> dict:
    """Read the nag log. Missing/unreadable/malformed → empty default (no raise).

    A lower/absent ``schema_version`` is migrated forward on read (spec A7);
    the migrated version persists on the next :func:`write_store`.
    """
    path = _store_path(product_dir)
    if not path.is_file():
        return _empty_store()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("advisories"), list):
        return _empty_store()
    return _migrate_store(data)


def write_store(product_dir, store: dict) -> dict:
    """Write the nag log as pretty JSON. Returns ``{status, ...}`` (no raise)."""
    path = _store_path(product_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2) + "\n")
    except OSError as exc:
        return {"status": "error", "reason": str(exc)}
    return {"status": "ok", "path": str(path)}


# =============================================================================
# ProjectState / Codebase loaders
# =============================================================================


def _coerce_scalar(value: str):
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", "none"):
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def load_project_state(product_dir) -> ProjectState:
    """Parse top-level scalar fields from ``project-state.yaml`` (column-0 scan).

    No PyYAML dependency — mirrors the column-0 pattern used elsewhere
    (``_read_sync_config``, ``views_enabled``). Only top-level ``key: value``
    scalars are captured; nested-block headers (``key:`` with no value) are
    skipped. Resolution-condition facts probes consult (e.g.
    ``uses_llm_inference``) live at the top level.
    """
    path = Path(product_dir) / ".prawduct" / "project-state.yaml"
    data: dict = {}
    if not path.is_file():
        return ProjectState(data)
    try:
        text = path.read_text()
    except OSError:
        return ProjectState(data)
    for line in text.splitlines():
        if not line or line[0] in (" ", "\t", "#"):
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        val = rest.split("#", 1)[0].strip().strip("\"'")
        if val == "":
            continue  # nested-block header, not a scalar
        data[key] = _coerce_scalar(val)
    return ProjectState(data)


def make_codebase(product_dir) -> Codebase:
    """Build the read-only Codebase wrapper rooted at ``product_dir``."""
    return Codebase(root=Path(product_dir))


# =============================================================================
# Reconcile (the sync diff) + orchestration
# =============================================================================


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_advisory(candidate: AdvisoryCandidate, *, advisory_id: str, now: str, sync_version: str) -> dict:
    priority = candidate.priority if candidate.priority in VALID_PRIORITIES else "info"
    return {
        "id": advisory_id,
        "feature": candidate.feature,
        "type": candidate.type,
        "probe_version": candidate.probe_version,
        "triggered_at": now,
        "triggered_by_sync_version": sync_version,
        "trigger_summary": candidate.trigger_summary,
        "evidence": list(candidate.evidence[:EVIDENCE_CAP]),
        "recommended_action": candidate.recommended_action,
        "alternative_actions": list(candidate.alternative_actions),
        "priority": priority,
        "state": "active",
        "superseded_by": None,
        "dismissed_at": None,
        "dismissed_reason": None,
        "resolved_at": None,
        "resolved_by": None,
    }


def _supersession_targets(
    cand_by_id: dict[str, AdvisoryCandidate], existing_ids: set[str]
) -> dict[tuple[str, str], tuple[int, str]]:
    """Map ``(feature, type)`` → ``(version, id)`` of the highest-version *new*
    candidate for that tuple (spec §2.8, Q1).

    Only candidates whose id is absent from the store count as supersession
    *sources* — an id already present is an idempotent re-fire, not a probe
    refinement. When a probe-version bump fires, the bumped candidate carries a
    new id (version is in the hash), so the prior active advisory for the same
    ``(feature, type)`` drops out of the candidate set and is superseded *by*
    this entry rather than plainly resolved.
    """
    targets: dict[tuple[str, str], tuple[int, str]] = {}
    for advisory_id, cand in cand_by_id.items():
        if advisory_id in existing_ids:
            continue
        key = (cand.feature, cand.type)
        prev = targets.get(key)
        if prev is None or cand.probe_version > prev[0]:
            targets[key] = (cand.probe_version, advisory_id)
    return targets


def reconcile(store: dict, candidates: Iterable[AdvisoryCandidate], *, now: str | None = None, sync_version: str = "") -> dict:
    """Diff fresh probe candidates against the existing store (spec §4.2, §2.8).

    Decides advisory *states* — ``active``, ``resolved``, ``dismissed``, and
    probe-version supersession. The complementary question of *what form to
    keep non-active entries in* (compaction, TTL GC, soft caps) belongs to the
    sync-persist pass :func:`apply_retention`, kept separate so this function
    stays a clean state-diff. The six cases:

      - id in candidates, not in store        → new ``active`` advisory
      - id in candidates, ``active`` in store  → no-op (idempotent; ``triggered_at`` unchanged)
      - id in candidates, ``resolved`` in store → re-activate (the answer was un-set)
      - id in candidates, ``dismissed`` in store → kept dismissed (sticky, A4)
      - id ``active`` in store, superseded by a higher-version new candidate for
        the same ``(feature, type)`` → ``resolved`` / ``resolved_by: probe-update`` /
        ``superseded_by: <new-id>`` (spec §2.8, A8)
      - id ``active`` in store, not in candidates and not superseded → ``resolved`` / ``resolved_by: sync``
      - non-active in store, not in candidates → kept as-is (compaction/GC is
        a separate sync-persist pass, :func:`apply_retention`)

    A ``dismissed`` advisory whose probe bumps version is *not* superseded: its
    dismissal is the load-bearing per-clone fact (kept), and the new id is a
    distinct condition that surfaces as a fresh ``active`` advisory — the user
    dismissed the old probe's finding, so a materially-refined probe gets a new
    chance to nag (recorded in the change-log / A8 test).

    Pure function — does not touch disk. Existing-entry order is preserved and
    new advisories append, for a deterministic store.
    """
    now = now or _utcnow_iso()
    cand_by_id: dict[str, AdvisoryCandidate] = {}
    for cand in candidates:
        advisory_id = compute_id(cand.feature, cand.type, cand.probe_version, cand.evidence)
        cand_by_id[advisory_id] = cand

    existing_ids = {a.get("id") for a in store.get("advisories", [])}
    supersedes = _supersession_targets(cand_by_id, existing_ids)

    result: list[dict] = []
    seen: set[str] = set()
    for advisory in store.get("advisories", []):
        advisory_id = advisory.get("id")
        seen.add(advisory_id)
        state = advisory.get("state")
        if advisory_id in cand_by_id:
            if state == "dismissed":
                # Sticky dismissal (spec §2.4, A4): a dismissed id never
                # re-triggers, even though its probe still fires. Kept as-is;
                # only undismiss() returns it to active.
                result.append(advisory)
            elif state == "resolved":
                # The probe fires again — the resolution fact was removed. Return
                # to active, preserving the original first-seen metadata.
                result.append(
                    _new_advisory(
                        cand_by_id[advisory_id],
                        advisory_id=advisory_id,
                        now=advisory.get("triggered_at") or now,
                        sync_version=advisory.get("triggered_by_sync_version") or sync_version,
                    )
                )
            elif not advisory.get("triggered_at"):
                # A compacted entry that was undismissed (Chunk 05): undismiss
                # flips state→active on the compact stub, but compaction had
                # already dropped feature/evidence/trigger_summary/action. The
                # probe still fires, so rehydrate the full advisory from the
                # fresh candidate (fresh triggered_at — it resurfaces as a new
                # occurrence). Without this it would render in the briefing with
                # a blank summary and no action indefinitely. A normal active
                # entry always carries triggered_at, so this never disturbs the
                # idempotent path below.
                result.append(
                    _new_advisory(cand_by_id[advisory_id], advisory_id=advisory_id, now=now, sync_version=sync_version)
                )
            else:
                result.append(advisory)  # active → idempotent no-op
        elif state == "active":
            target = supersedes.get((advisory.get("feature"), advisory.get("type")))
            resolved = dict(advisory)
            resolved["state"] = "resolved"
            resolved["resolved_at"] = now
            if target is not None and target[0] > (advisory.get("probe_version") or 0):
                # Probe-version bump: link old → new instead of a plain resolve.
                resolved["resolved_by"] = "probe-update"
                resolved["superseded_by"] = target[1]
            else:
                # Plain resolution — the probe stopped firing (resolution fact
                # landed). The strict ``>`` also routes a version *downgrade*
                # here (versions are monotonic per spec §3.3, so this is a
                # defensive default, not an expected path).
                resolved["resolved_by"] = "sync"
            result.append(resolved)
        else:
            result.append(advisory)  # already non-active — compaction/GC happens in apply_retention

    for advisory_id, cand in cand_by_id.items():
        if advisory_id not in seen:
            result.append(_new_advisory(cand, advisory_id=advisory_id, now=now, sync_version=sync_version))

    return {"schema_version": SCHEMA_VERSION, "advisories": result}


# =============================================================================
# Retention: compaction, TTL garbage-collection, soft caps (spec §3.4, Q4) — Chunk 04
# =============================================================================


def _parse_iso(ts) -> datetime | None:
    """Parse a ``%Y-%m-%dT%H:%M:%SZ`` stamp to an aware UTC datetime, or None."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _compact_advisory(advisory: dict) -> dict:
    """Shrink a non-active advisory to the load-bearing fields (spec §3.4).

    Active entries are returned untouched (full payload kept while live).
    Resolved → ``id``/``state``/``resolved_at``/``resolved_by`` (+ ``superseded_by``
    when set). Dismissed → ``id``/``state``/``dismissed_at``/``dismissed_reason``.
    Idempotent: compacting an already-compact entry yields the same dict.
    """
    state = advisory.get("state")
    if state == "resolved":
        compact = {
            "id": advisory.get("id"),
            "state": "resolved",
            "resolved_at": advisory.get("resolved_at"),
            "resolved_by": advisory.get("resolved_by"),
        }
        if advisory.get("superseded_by"):
            compact["superseded_by"] = advisory["superseded_by"]
        return compact
    if state == "dismissed":
        return {
            "id": advisory.get("id"),
            "state": "dismissed",
            "dismissed_at": advisory.get("dismissed_at"),
            "dismissed_reason": advisory.get("dismissed_reason"),
        }
    return advisory  # active (or unrecognized) — leave full payload intact


def _resolved_expired(advisory: dict, now_dt: datetime | None) -> bool:
    """True if a resolved advisory is older than the 30-day TTL (spec §3.4).

    Unparseable/absent ``resolved_at`` or ``now`` → not expired (keep it; a
    missing timestamp must never silently delete an entry)."""
    if advisory.get("state") != "resolved":
        return False
    resolved_dt = _parse_iso(advisory.get("resolved_at"))
    if resolved_dt is None or now_dt is None:
        return False
    return (now_dt - resolved_dt) > timedelta(days=RESOLVED_TTL_DAYS)


def _over_cap_ids(advisories: list[dict], state: str, ts_field: str, cap: int) -> set[str]:
    """Ids of the oldest entries in ``state`` beyond ``cap`` (by ``ts_field``).

    Entries with a missing/empty timestamp sort oldest and are dropped first."""
    entries = [a for a in advisories if a.get("state") == state]
    if len(entries) <= cap:
        return set()
    newest_first = sorted(entries, key=lambda a: a.get(ts_field) or "", reverse=True)
    return {a.get("id") for a in newest_first[cap:]}


def apply_retention(store: dict, *, now: str | None = None) -> dict:
    """Compact non-active entries, GC expired resolved, and apply soft caps.

    The sync-persist hygiene pass (spec §3.4, Q4), kept separate from
    :func:`reconcile` (which is a pure state-diff): reconcile decides *states*,
    retention decides *what to keep and in what form*. Pure — does not touch
    disk. Order within each state band is preserved; only over-cap and expired
    entries are removed. Idempotent.
    """
    now = now or _utcnow_iso()
    now_dt = _parse_iso(now)
    compacted = [_compact_advisory(a) for a in store.get("advisories", []) if isinstance(a, dict)]
    kept = [a for a in compacted if not _resolved_expired(a, now_dt)]
    drop: set[str] = set()
    drop |= _over_cap_ids(kept, "active", "triggered_at", ACTIVE_CAP)
    drop |= _over_cap_ids(kept, "resolved", "resolved_at", RESOLVED_CAP)
    drop |= _over_cap_ids(kept, "dismissed", "dismissed_at", DISMISSED_CAP)
    final = [a for a in kept if a.get("id") not in drop]
    return {"schema_version": SCHEMA_VERSION, "advisories": final}


def run_sync_advisories(product_dir, *, now: str | None = None, sync_version: str = "") -> dict:
    """Sync entry point: run probes, diff against the store, retain, persist.

    Loads the answer store + codebase, runs the (empty in Phase 1) probe
    roster, reconciles, applies retention (compaction / TTL GC / soft caps),
    and writes the nag log. Returns a summary dict. Never raises — the
    underlying reads/writes/probes all degrade safely.
    """
    product = Path(product_dir)
    now = now or _utcnow_iso()
    state = load_project_state(product)
    codebase = make_codebase(product)
    # Load feature probes before running the roster. Lazy import (avoids a
    # circular import — backlog_probes imports from this module) and idempotent
    # registration (survives clear_registry between syncs). Defensive: a faulty
    # probe module must not break the advisory step.
    try:
        from . import backlog_probes  # noqa: PLC0415 — feature-probe registration point

        backlog_probes.register_backlog_probes()
    except Exception:  # prawduct:ok-broad-except — probe registration must never block sync
        pass
    candidates = run_all_probes(state, codebase)
    store = read_store(product)
    reconciled = reconcile(store, candidates, now=now, sync_version=sync_version)
    new_store = apply_retention(reconciled, now=now)
    write_result = write_store(product, new_store)
    advisories = new_store["advisories"]
    active = [a for a in advisories if a.get("state") == "active"]
    newly_resolved = [
        a["id"]
        for a in advisories
        if a.get("state") == "resolved" and a.get("resolved_by") == "sync" and a.get("resolved_at") == now
    ]
    return {
        "status": write_result.get("status", "ok"),
        "active": len(active),
        "newly_resolved": newly_resolved,
    }


# =============================================================================
# Dismissal lifecycle (spec §2.4, §6.1) — Chunk 02; resolve added Chunk 05
# =============================================================================


def _mutate_advisory(product_dir, advisory_id: str, apply: Callable[[dict], None]) -> dict:
    """Read the store, run ``apply(advisory)`` on the entry matching
    ``advisory_id``, and write back. Returns ``{status: "ok"|"not_found", id}``.

    The shared read-scan-mutate-write skeleton behind :func:`dismiss`,
    :func:`undismiss`, and :func:`resolve` — each verb supplies only its field
    mutation. The store is written only when the id is found; a miss is a no-op
    write. Never raises (the underlying read/write degrade safely).
    """
    store = read_store(product_dir)
    for advisory in store.get("advisories", []):
        if advisory.get("id") == advisory_id:
            apply(advisory)
            write_store(product_dir, store)
            return {"status": "ok", "id": advisory_id}
    return {"status": "not_found", "id": advisory_id}


def dismiss(product_dir, advisory_id: str, reason: str | None = None, *, now: str | None = None) -> dict:
    """Mark an advisory ``dismissed`` (sticky — it won't re-trigger; spec §2.4).

    The dismissal lives only in the per-clone nag log, never in the shared
    ``project-state.yaml`` (spec §3.5). ``dismiss`` writes the full payload
    (cheap, between syncs); the next sync's :func:`apply_retention` shrinks it
    to the load-bearing dismissal fact (spec §3.4). Returns
    ``{status: "ok"|"not_found"}``.
    """
    now = now or _utcnow_iso()

    def _apply(advisory: dict) -> None:
        advisory["state"] = "dismissed"
        advisory["dismissed_at"] = now
        advisory["dismissed_reason"] = reason
        advisory["resolved_at"] = None
        advisory["resolved_by"] = None

    return _mutate_advisory(product_dir, advisory_id, _apply)


def undismiss(product_dir, advisory_id: str) -> dict:
    """Clear a dismissal — the advisory returns to ``active`` (spec §6.1).

    The next sync reconciles it: if the probe still fires it stays active (and
    :func:`reconcile` rehydrates the entry should compaction have shrunk it; see
    the ``triggered_at`` branch there); if not, it auto-resolves. Returns
    ``{status: "ok"|"not_found"}``.
    """

    def _apply(advisory: dict) -> None:
        advisory["state"] = "active"
        advisory["dismissed_at"] = None
        advisory["dismissed_reason"] = None

    return _mutate_advisory(product_dir, advisory_id, _apply)


def resolve(product_dir, advisory_id: str, *, resolved_by: str = "action", now: str | None = None) -> dict:
    """Mark an advisory ``resolved`` immediately (action-driven, spec §4.3, Q3).

    The action-resolution path: when the user runs a ``recommended_action`` the
    action's success can clear the advisory now, without waiting for the next
    sync's probe re-run. ``resolved_by`` defaults to ``"action"`` to distinguish
    it from sync-driven (``"sync"``) and supersession (``"probe-update"``)
    resolutions. Note the authoritative resolution path remains the
    ``project-state.yaml`` fact + probe re-run (spec Q3); this is the immediate-
    feedback shortcut. The next sync's :func:`apply_retention` shrinks the entry
    to compact form. Returns ``{status: "ok"|"not_found"}``.
    """
    now = now or _utcnow_iso()

    def _apply(advisory: dict) -> None:
        advisory["state"] = "resolved"
        advisory["resolved_at"] = now
        advisory["resolved_by"] = resolved_by
        advisory["dismissed_at"] = None
        advisory["dismissed_reason"] = None

    return _mutate_advisory(product_dir, advisory_id, _apply)
