"""Post-sync advisory management CLI — ``/prawduct-advisory`` (spec §6).

Phase 1 Chunk 05. The user-facing surface over the nag log managed by
:mod:`advisory_store`. Five subcommands (spec §6.1):

  - ``list [--state=active|dismissed|resolved|all] [--feature=<name>]``
  - ``show <id>``      — full detail; reconstructs evidence for compact entries (Q5)
  - ``dismiss <id> [--reason "..."]``
  - ``undismiss <id>``
  - ``resolve <id>``   — action-driven resolution (spec §4.3)

Per the ``*_cmd.py`` convention this module holds the CLI; all *state
transitions* delegate to :mod:`advisory_store` (``dismiss``/``undismiss``/
``resolve``) — this module never mutates the store directly, it reads it for
``list``/``show`` and calls the store's transition functions for the verbs.

Two layers, mirroring the project's return-value convention:
  - The per-subcommand functions (:func:`list_advisories`, :func:`show_advisory`,
    :func:`dismiss_advisory`, :func:`undismiss_advisory`, :func:`resolve_advisory`)
    are pure-ish library calls returning ``{status, ...}`` dicts — tested
    directly, never raising.
  - :func:`run` is the argv dispatcher invoked from ``product-hook advisory`` —
    it parses flags, calls the right function, prints a human-readable summary,
    and returns a Unix exit code (the CLI boundary, where exit codes are the
    contract).
"""

from __future__ import annotations

import sys

from . import advisory_store as store_mod

# Valid ``--state`` filter values. ``all`` means "no state filter".
_LIST_STATES = ("active", "dismissed", "resolved", "all")


# =============================================================================
# Subcommand implementations (return-value based — never raise)
# =============================================================================


def _matches_feature(advisory: dict, feature: str) -> bool:
    """True if ``advisory`` belongs to ``feature``.

    Active advisories carry an explicit ``feature`` field; compacted
    (resolved/dismissed) entries drop it (spec §3.4), but the ``feature`` token
    is the literal id prefix (``compute_id`` builds ``<feature>-<type>-v<n>-<hash>``),
    so an id-prefix match recovers the association for compact entries too. This
    keeps ``--feature`` filtering correct across every state (A6).
    """
    if advisory.get("feature") == feature:
        return True
    return str(advisory.get("id") or "").startswith(f"{feature}-")


def list_advisories(product_dir, *, state: str = "active", feature: str | None = None) -> dict:
    """List advisories filtered by ``state`` and ``feature`` (spec §6.1, A6).

    Defaults: ``state="active"``, all features. ``state="all"`` applies no state
    filter. Returns ``{status, state, feature, count, advisories}`` — the
    advisories are the raw store dicts (active in full form, non-active compact),
    order preserved. Never raises.
    """
    store = store_mod.read_store(product_dir)
    advisories = [a for a in store.get("advisories", []) if isinstance(a, dict)]
    if state != "all":
        advisories = [a for a in advisories if a.get("state") == state]
    if feature:
        advisories = [a for a in advisories if _matches_feature(a, feature)]
    return {
        "status": "ok",
        "state": state,
        "feature": feature,
        "count": len(advisories),
        "advisories": advisories,
    }


def show_advisory(product_dir, advisory_id: str) -> dict:
    """Full detail on one advisory; reconstruct evidence for compact entries (Q5).

    The in-store evidence array is capped at ``EVIDENCE_CAP`` and dropped
    entirely when an entry is compacted (resolved/dismissed). To surface the
    full forensic list on demand, ``show`` re-runs the probe roster and, if a
    fresh candidate's id matches this advisory, attaches that candidate's
    *uncapped* evidence (spec Q5 lean). When the probe no longer fires (e.g. the
    advisory resolved because its answer-store fact was set), evidence can't be
    reconstructed and the stored (possibly empty) form is returned with
    ``evidence_reconstructed=False``.

    Returns ``{status: "ok", advisory, evidence_reconstructed}`` or
    ``{status: "not_found", id}``. Never raises.
    """
    store = store_mod.read_store(product_dir)
    match = None
    for advisory in store.get("advisories", []):
        if isinstance(advisory, dict) and advisory.get("id") == advisory_id:
            match = advisory
            break
    if match is None:
        return {"status": "not_found", "id": advisory_id}

    advisory = dict(match)
    reconstructed = False
    # A compacted entry has no evidence array (the field was dropped). Re-run
    # the probes and recover the full citation list if the probe still fires.
    if not advisory.get("evidence"):
        state = store_mod.load_project_state(product_dir)
        codebase = store_mod.make_codebase(product_dir)
        for cand in store_mod.run_all_probes(state, codebase):
            cand_id = store_mod.compute_id(cand.feature, cand.type, cand.probe_version, cand.evidence)
            if cand_id == advisory_id:
                advisory["evidence"] = list(cand.evidence)  # uncapped — full forensic list
                advisory["feature"] = advisory.get("feature") or cand.feature
                advisory["type"] = advisory.get("type") or cand.type
                advisory["trigger_summary"] = advisory.get("trigger_summary") or cand.trigger_summary
                advisory["recommended_action"] = advisory.get("recommended_action") or cand.recommended_action
                reconstructed = True
                break

    return {"status": "ok", "advisory": advisory, "evidence_reconstructed": reconstructed}


def dismiss_advisory(product_dir, advisory_id: str, reason: str | None = None) -> dict:
    """Dismiss an advisory (sticky). Delegates to :func:`advisory_store.dismiss`."""
    return store_mod.dismiss(product_dir, advisory_id, reason)


def undismiss_advisory(product_dir, advisory_id: str) -> dict:
    """Clear a dismissal. Delegates to :func:`advisory_store.undismiss`."""
    return store_mod.undismiss(product_dir, advisory_id)


def resolve_advisory(product_dir, advisory_id: str) -> dict:
    """Manually resolve an advisory now. Delegates to :func:`advisory_store.resolve`
    with ``resolved_by="action"`` (spec §4.3 immediate path)."""
    return store_mod.resolve(product_dir, advisory_id, resolved_by="action")


# =============================================================================
# argv dispatcher (the CLI boundary — exit codes, human-readable output)
# =============================================================================


_USAGE = (
    "Usage: product-hook advisory "
    "{list [--state=active|dismissed|resolved|all] [--feature=<name>] | "
    "show <id> | dismiss <id> [--reason <text>] | undismiss <id> | resolve <id>}"
)


def _split_flag(arg: str) -> tuple[str, str | None]:
    """Split ``--key=value`` → ``("--key", "value")``; bare ``--key`` → value None."""
    if "=" in arg:
        key, _, value = arg.partition("=")
        return key, value
    return arg, None


def _render_advisory_line(advisory: dict) -> str:
    feature = advisory.get("feature")
    prefix = f"[{feature}] " if feature else ""
    summary = advisory.get("trigger_summary") or advisory.get("type") or ""
    return f"  • {advisory.get('id')}  {prefix}{summary}".rstrip()


def _print_list(result: dict) -> None:
    advisories = result.get("advisories", [])
    state = result.get("state")
    feature = result.get("feature")
    scope = f"state={state}" + (f", feature={feature}" if feature else "")
    if not advisories:
        print(f"No advisories ({scope}).")
        return
    print(f"{len(advisories)} advisory(ies) ({scope}):")
    for advisory in advisories:
        print(_render_advisory_line(advisory))
        action = advisory.get("recommended_action")
        if action and advisory.get("state") == "active":
            print(f"      → {action}")


def _print_show(result: dict, advisory_id: str) -> int:
    if result.get("status") == "not_found":
        print(f"Advisory not found: {advisory_id}", file=sys.stderr)
        return 1
    advisory = result["advisory"]
    print(f"id:                {advisory.get('id')}")
    print(f"state:             {advisory.get('state')}")
    if advisory.get("feature"):
        print(f"feature:           {advisory.get('feature')}")
    if advisory.get("type"):
        print(f"type:              {advisory.get('type')}")
    if advisory.get("trigger_summary"):
        print(f"trigger:           {advisory.get('trigger_summary')}")
    if advisory.get("recommended_action"):
        print(f"recommended:       {advisory.get('recommended_action')}")
    evidence = advisory.get("evidence") or []
    if evidence:
        suffix = " (reconstructed by re-running the probe)" if result.get("evidence_reconstructed") else ""
        print(f"evidence ({len(evidence)}){suffix}:")
        for item in evidence:
            print(f"  - {item}")
    for field in ("dismissed_at", "dismissed_reason", "resolved_at", "resolved_by", "superseded_by"):
        if advisory.get(field):
            print(f"{field + ':':<19}{advisory.get(field)}")
    return 0


def _print_transition(result: dict, verb: str, advisory_id: str) -> int:
    if result.get("status") == "not_found":
        print(f"Advisory not found: {advisory_id}", file=sys.stderr)
        return 1
    print(f"Advisory {verb}: {advisory_id}")
    return 0


def run(product_dir, argv: list[str]) -> int:
    """Dispatch ``advisory <subcommand> ...``; print a summary, return an exit code.

    Argv is the tokens *after* ``advisory`` (i.e. ``sys.argv[2:]`` from the
    hook). Unknown subcommands / missing ids / bad flags print usage to stderr
    and return 1 (the CLI fail-closed boundary). The underlying lib calls never
    raise, so this never crashes on a malformed store.
    """
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 1
    sub = argv[0]
    rest = argv[1:]

    if sub == "list":
        state = "active"
        feature = None
        for arg in rest:
            key, value = _split_flag(arg)
            if key == "--state":
                if value not in _LIST_STATES:
                    print(f"Invalid --state {value!r}; expected one of {', '.join(_LIST_STATES)}", file=sys.stderr)
                    return 1
                state = value
            elif key == "--feature":
                if not value:
                    print("--feature requires a value (use --feature=<name>)", file=sys.stderr)
                    return 1
                feature = value
            else:
                print(f"Unknown flag for list: {arg}", file=sys.stderr)
                return 1
        _print_list(list_advisories(product_dir, state=state, feature=feature))
        return 0

    if sub == "show":
        if not rest:
            print("show requires an advisory id", file=sys.stderr)
            return 1
        advisory_id = rest[0]
        return _print_show(show_advisory(product_dir, advisory_id), advisory_id)

    if sub == "dismiss":
        if not rest:
            print("dismiss requires an advisory id", file=sys.stderr)
            return 1
        advisory_id = rest[0]
        reason = None
        flags = rest[1:]
        i = 0
        while i < len(flags):
            key, value = _split_flag(flags[i])
            if key == "--reason":
                if value is not None:
                    reason = value
                elif i + 1 < len(flags):
                    reason = flags[i + 1]
                    i += 1
                else:
                    print("--reason requires a value", file=sys.stderr)
                    return 1
            else:
                print(f"Unknown flag for dismiss: {flags[i]}", file=sys.stderr)
                return 1
            i += 1
        return _print_transition(dismiss_advisory(product_dir, advisory_id, reason), "dismissed", advisory_id)

    if sub == "undismiss":
        if not rest:
            print("undismiss requires an advisory id", file=sys.stderr)
            return 1
        advisory_id = rest[0]
        return _print_transition(undismiss_advisory(product_dir, advisory_id), "undismissed", advisory_id)

    if sub == "resolve":
        if not rest:
            print("resolve requires an advisory id", file=sys.stderr)
            return 1
        advisory_id = rest[0]
        return _print_transition(resolve_advisory(product_dir, advisory_id), "resolved", advisory_id)

    print(_USAGE, file=sys.stderr)
    return 1
