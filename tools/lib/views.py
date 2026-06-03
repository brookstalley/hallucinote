"""Derived-view builders for the prawduct work-log canonical store.

When `.prawduct/project-state.yaml` has `views_enabled: true`, the build-plan
`## Status` block becomes a derived view of `.prawduct/change-log.md` tagged
entries — `product-hook regen-views` rewrites the checkboxes from
`status=shipped` tags. Chunk titles, the `## Status` heading, the introductory
HTML comment, and the freeform `Context:` line are author-curated; regen never
touches them.

Tagged-entry format (in change-log.md, on a line after each ``## YYYY-MM-DD:``
header — blank lines between are tolerated):

    <!-- prawduct: chunks=00,01,02 | release=v1.3.18 | status=shipped | scope=v1.4 -->

Recognized keys:

* ``chunks``  comma-separated chunk IDs (zero-padded, matching build-plan headers)
* ``release`` version string (used by release-notes view, Chunk 06)
* ``status``  ``shipped`` | ``in-progress`` | ``deferred``
* ``scope``   rollup identifier, e.g., ``v1.4``

Entries without a tag line are ignored — untagged historical entries coexist
with tagged ones. Only chunks with a ``status=shipped`` tag flip to ``[x]``;
all other Chunk lines flip to ``[ ]`` so the view is fully derived.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .core import resolve_build_plan_path


TAG_LINE_RE = re.compile(r"<!--\s*prawduct:\s*(.+?)\s*-->")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
CHUNK_LINE_RE = re.compile(
    r"^(?P<prefix>\s*-\s+)\[(?P<state>[ xX])\](?P<rest>\s+Chunk\s+(?P<id>[A-Za-z0-9_-]+):.*)$"
)


@dataclass
class ChangeLogEntry:
    """A change-log entry with optional tagged metadata."""

    title: str
    tags: dict[str, object] = field(default_factory=dict)
    line_number: int = 0  # 1-indexed line of the H2 header

    @property
    def shipped_chunks(self) -> list[str]:
        """Chunk IDs marked shipped by this entry, or []."""
        if self.tags.get("status") != "shipped":
            return []
        chunks = self.tags.get("chunks")
        if isinstance(chunks, list):
            return [c for c in chunks if isinstance(c, str)]
        return []


def parse_tag_line(tag_body: str) -> dict[str, object]:
    """Parse the body of a tag-line (between ``prawduct:`` and ``-->``).

    Pipe-delimited ``key=value`` pairs. ``chunks`` is split on commas into a list;
    other keys are kept as plain strings. Unknown keys are preserved as-is so
    future views can read them without a schema bump.
    """
    tags: dict[str, object] = {}
    for part in tag_body.split("|"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if k == "chunks":
            tags[k] = [c.strip() for c in v.split(",") if c.strip()]
        else:
            tags[k] = v
    return tags


def parse_change_log(content: str) -> list[ChangeLogEntry]:
    """Parse change-log markdown into a list of entries.

    An entry is ``## YYYY-MM-DD: title`` followed (after up to a few blank
    lines) by ``<!-- prawduct: key=value | ... -->``. The tag line, if present,
    must appear before the next non-blank content line under the H2.
    """
    entries: list[ChangeLogEntry] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        m = H2_RE.match(lines[i])
        if not m:
            i += 1
            continue
        entry = ChangeLogEntry(title=m.group(1), line_number=i + 1)
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if not stripped:
                j += 1
                continue
            tag_match = TAG_LINE_RE.search(lines[j])
            if tag_match:
                entry.tags = parse_tag_line(tag_match.group(1))
            # First non-blank line settles the question — tag line or not.
            break
        entries.append(entry)
        i += 1
    return entries


def collect_shipped_chunks(
    entries: list[ChangeLogEntry], scope: str | None = None
) -> set[str]:
    """Aggregate shipped chunk IDs across all entries.

    When ``scope`` is set, only entries whose ``scope=`` tag equals ``scope``
    contribute — this prevents cross-version chunk-ID collisions (e.g., v1.4's
    ``chunks=05 | scope=v1.4`` flipping v1.5's chunk 05). When ``scope`` is
    ``None``, all shipped entries contribute (legacy unfiltered behavior).
    """
    shipped: set[str] = set()
    for entry in entries:
        if scope is not None and entry.tags.get("scope") != scope:
            continue
        shipped.update(entry.shipped_chunks)
    return shipped


def _parse_build_plan_frontmatter_scope(content: str) -> str | None:
    """Parse ``scope:`` from a build-plan's YAML frontmatter block.

    The frontmatter is the block bounded by ``---`` on its own line. A leading
    HTML comment block (``<!-- ... -->``) and blank lines before the opening
    ``---`` are tolerated — every real build-plan in the codebase begins with a
    comment header before the frontmatter, so requiring ``---`` on line 1 would
    make the field inert in practice.

    Returns the bare string value (quotes stripped) or ``None`` if the field is
    absent, empty, set to the YAML null literal (``null`` / ``~``), nested
    inside another key, outside the frontmatter, or the file lacks a
    frontmatter entirely.
    """
    lines = content.splitlines()
    i = 0
    # Skip leading blank lines, then any leading HTML comment block (possibly
    # multi-line). Build-plans conventionally start with a comment header.
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith("<!--"):
        # Walk to the closing `-->` (inclusive).
        while i < len(lines) and "-->" not in lines[i]:
            i += 1
        if i < len(lines):
            i += 1  # consume the line containing `-->`
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None
    for j in range(i + 1, len(lines)):
        line = lines[j]
        if line.strip() == "---":
            return None
        if line[:1] in (" ", "\t"):
            continue
        stripped = line.split("#", 1)[0].rstrip()
        if not stripped.startswith("scope:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        if not value or value.lower() in ("null", "~"):
            return None
        return value
    return None


def _detect_active_scope(
    build_plan_content: str, change_log_content: str | None = None
) -> str | None:
    """Detect the active scope for filtering change-log entries.

    Resolution order (highest precedence first):

    1. ``scope:`` field in build-plan YAML frontmatter — explicit, preferred.
    2. Most recent change-log entry's ``scope=`` tag — inferred.
    3. ``None`` — no scope detected; fail-safe to legacy unfiltered union.
    """
    fm_scope = _parse_build_plan_frontmatter_scope(build_plan_content)
    if fm_scope:
        return fm_scope
    if change_log_content:
        entries = parse_change_log(change_log_content)
        for entry in entries:
            scope = entry.tags.get("scope")
            if isinstance(scope, str) and scope:
                return scope
    return None


def extract_status_section(content: str) -> tuple[int, int, list[str]]:
    """Find the ``## Status`` section.

    Returns ``(start_idx, end_idx_exclusive, section_lines)``. Section runs from
    the ``## Status`` line to (but not including) the next ``## `` H2 — matching
    the conventional build-plan layout. Returns ``(-1, -1, [])`` if absent.
    """
    lines = content.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("## Status"):
            start = i
            break
    if start < 0:
        return (-1, -1, [])
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return (start, end, lines[start:end])


def regenerate_status_section(
    section_lines: list[str], shipped_chunks: set[str]
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Rewrite Chunk checkbox lines from the shipped-chunks set.

    Returns ``(new_lines, changes)`` where each change is
    ``(chunk_id, old_state, new_state)`` with ``state`` in ``{" ", "x"}``.
    Non-chunk lines (the ``## Status`` heading, HTML comments, blanks, the
    ``Context:`` line) pass through unchanged. Order is preserved.
    """
    out: list[str] = []
    changes: list[tuple[str, str, str]] = []
    for line in section_lines:
        m = CHUNK_LINE_RE.match(line)
        if not m:
            out.append(line)
            continue
        chunk_id = m.group("id")
        current = m.group("state")
        new_state = "x" if chunk_id in shipped_chunks else " "
        if current.lower() != new_state:
            changes.append((chunk_id, current, new_state))
        out.append(f"{m.group('prefix')}[{new_state}]{m.group('rest')}")
    return out, changes


def build_status_view(
    change_log_content: str, build_plan_content: str
) -> tuple[str | None, list[tuple[str, str, str]]]:
    """Produce updated build-plan content with regenerated Status section.

    Returns ``(new_content, changes)``. ``new_content`` is ``None`` when no
    checkbox flips were needed (idempotent no-op). ``changes`` is empty in
    that case.
    """
    entries = parse_change_log(change_log_content)
    active_scope = _detect_active_scope(build_plan_content, change_log_content)
    shipped = collect_shipped_chunks(entries, scope=active_scope)
    start, end, section = extract_status_section(build_plan_content)
    if start < 0:
        return None, []
    new_section, changes = regenerate_status_section(section, shipped)
    if not changes:
        return None, []
    lines = build_plan_content.splitlines()
    new_lines = lines[:start] + new_section + lines[end:]
    trailing = "\n" if build_plan_content.endswith("\n") else ""
    return "\n".join(new_lines) + trailing, changes


YAML_TOP_LEVEL_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*")


def extract_yaml_top_level_block(
    content: str, key: str
) -> tuple[int, int, list[str]]:
    """Find a column-0 YAML key and its body block.

    Returns ``(start_idx, end_idx_exclusive, block_lines)``. The block starts at
    the ``key:`` line and continues across all subsequent indented or blank
    lines, ending at the first column-0 non-blank line (next key or comment
    header). Trailing blank lines are excluded so they belong to the next
    block's leading whitespace. Returns ``(-1, -1, [])`` if the key is absent.
    """
    lines = content.splitlines()
    start = -1
    key_re = re.compile(rf"^{re.escape(key)}:\s*")
    for i, line in enumerate(lines):
        if key_re.match(line):
            start = i
            break
    if start < 0:
        return (-1, -1, [])
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        if line[:1] in (" ", "\t"):
            continue
        end = j
        break
    # Drop trailing blank lines so they stay with the following block.
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return (start, end, lines[start:end])


def _collect_scope_rollups(
    entries: list[ChangeLogEntry],
) -> dict[str, dict[str, list[str]]]:
    """Aggregate shipped entries by ``scope`` tag.

    Returns ``{scope_id: {"chunks": [...], "releases": [...]}}`` with chunks
    sorted, releases sorted, scope IDs sorted alphabetically. Only entries with
    ``status=shipped`` AND a non-empty ``scope=`` tag contribute.
    """
    raw: dict[str, dict[str, set[str]]] = {}
    for entry in entries:
        if entry.tags.get("status") != "shipped":
            continue
        scope = entry.tags.get("scope")
        if not isinstance(scope, str) or not scope:
            continue
        rec = raw.setdefault(scope, {"chunks": set(), "releases": set()})
        chunks = entry.tags.get("chunks")
        if isinstance(chunks, list):
            rec["chunks"].update(c for c in chunks if isinstance(c, str))
        release = entry.tags.get("release")
        if isinstance(release, str) and release:
            rec["releases"].add(release)
    return {
        scope: {
            "chunks": sorted(raw[scope]["chunks"]),
            "releases": sorted(raw[scope]["releases"]),
        }
        for scope in sorted(raw)
    }


def _format_scope_rollups_block(scopes: dict[str, dict[str, list[str]]]) -> str:
    """Format the ``scope_rollups:`` YAML block from the aggregated dict.

    Chunk IDs are quoted to preserve leading zeros (unquoted ``00`` is the
    integer 0 in YAML's octal/leading-zero handling).
    """
    if not scopes:
        return "scope_rollups: {}"
    lines = ["scope_rollups:"]
    for scope_id in scopes:
        rec = scopes[scope_id]
        lines.append(f"  {scope_id}:")
        chunks_yaml = ", ".join(f'"{c}"' for c in rec["chunks"])
        lines.append(f"    chunks: [{chunks_yaml}]")
        releases_yaml = ", ".join(f'"{r}"' for r in rec["releases"])
        lines.append(f"    releases: [{releases_yaml}]")
    return "\n".join(lines)


SCOPE_ROLLUPS_HEADER = (
    "# =============================================================================\n"
    "# SCOPE ROLLUPS (derived view, v1.4+)\n"
    "# =============================================================================\n"
    "# Auto-generated by `python3 tools/product-hook regen-views` from\n"
    "# .prawduct/change-log.md `scope=` tags. Do not hand-edit — edits will be\n"
    "# overwritten on next regen.\n"
)


def build_scope_view(
    change_log_content: str, project_state_content: str
) -> tuple[str | None, dict[str, dict[str, list[str]]]]:
    """Regenerate the ``scope_rollups:`` block in project-state.yaml.

    Returns ``(new_content, scopes)``. ``new_content`` is ``None`` when the
    existing block already matches (idempotent no-op). ``scopes`` is the
    computed mapping so callers can render human-readable diffs.

    If no ``scope_rollups:`` block exists, one is appended at end-of-file with
    a comment header. If the block exists, only the key + body is replaced;
    surrounding comments and other keys are preserved verbatim.
    """
    entries = parse_change_log(change_log_content)
    scopes = _collect_scope_rollups(entries)
    new_block = _format_scope_rollups_block(scopes)
    new_block_lines = new_block.splitlines()

    start, end, existing_block = extract_yaml_top_level_block(
        project_state_content, "scope_rollups"
    )

    if start < 0:
        # No existing block — append at end of file with header comment.
        sep = "" if project_state_content.endswith("\n") else "\n"
        appended = (
            project_state_content
            + sep
            + "\n"
            + SCOPE_ROLLUPS_HEADER
            + "\n"
            + new_block
            + "\n"
        )
        return appended, scopes

    if existing_block == new_block_lines:
        return None, scopes

    lines = project_state_content.splitlines()
    new_lines = lines[:start] + new_block_lines + lines[end:]
    trailing = "\n" if project_state_content.endswith("\n") else ""
    return "\n".join(new_lines) + trailing, scopes


def _collect_releases(
    entries: list[ChangeLogEntry],
) -> list[dict[str, object]]:
    """Aggregate shipped entries by ``release`` tag, preserving change-log order.

    Returns a list of ``{release, title, chunks, scope}`` dicts in the order
    releases first appear in the change-log (which by convention is
    newest-first). Multiple entries sharing a release are merged; chunks union
    and dedupe; ``title`` and ``scope`` come from the first entry seen.
    """
    seen: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for entry in entries:
        if entry.tags.get("status") != "shipped":
            continue
        release = entry.tags.get("release")
        if not isinstance(release, str) or not release:
            continue
        if release not in seen:
            seen[release] = {
                "release": release,
                "title": entry.title,
                "chunks": set(),
                "scope": entry.tags.get("scope")
                if isinstance(entry.tags.get("scope"), str)
                else None,
            }
            order.append(release)
        chunks = entry.tags.get("chunks")
        if isinstance(chunks, list):
            seen[release]["chunks"].update(
                c for c in chunks if isinstance(c, str)
            )
    out: list[dict[str, object]] = []
    for release in order:
        rec = dict(seen[release])
        rec["chunks"] = sorted(rec["chunks"])
        out.append(rec)
    return out


RELEASE_NOTES_HEADER = (
    "# Release Notes\n"
    "\n"
    "<!-- Auto-generated by `python3 tools/product-hook regen-views` from\n"
    "     .prawduct/change-log.md `release=` tags. Do not hand-edit — edits will\n"
    "     be overwritten on next regen. See change-log.md for full per-release\n"
    "     bodies; this file is a digest. -->\n"
)


def build_release_notes_view(change_log_content: str) -> str | None:
    """Generate release-notes.md content from release-tagged shipped entries.

    Returns the full desired file content, or ``None`` if no shipped+released
    entries exist (caller decides whether to create an empty placeholder or
    leave any existing file alone).
    """
    entries = parse_change_log(change_log_content)
    releases = _collect_releases(entries)
    if not releases:
        return None
    out: list[str] = [RELEASE_NOTES_HEADER]
    for rec in releases:
        out.append(f"## {rec['release']}\n")
        out.append(f"**Entry:** {rec['title']}\n")
        chunks = rec["chunks"]
        if chunks:
            out.append(f"**Chunks shipped:** {', '.join(chunks)}\n")
        if rec["scope"]:
            out.append(f"**Scope:** {rec['scope']}\n")
        out.append("See `.prawduct/change-log.md` for full details.\n")
    return "\n".join(out).rstrip() + "\n"


@dataclass
class ViewRegenResult:
    """Outcome of one view's regen pass."""

    name: str  # "status" | "release-notes" | "scope-rollups"
    action: str  # "noop" | "write" | "create"
    summary: str  # human-readable detail
    new_content: str | None = None  # new file content (None for noop)
    path_relative: str = ""  # path relative to prawduct_dir, for caller to write


def plan_regen(prawduct_dir: Path) -> tuple[bool, list[ViewRegenResult]]:
    """Compute what regen-views would do; do NOT write.

    Returns ``(enabled, results)``. ``enabled`` is False when views_enabled is
    not set — in that case results is empty. Otherwise results contains one
    entry per view (status, release-notes, scope-rollups) describing the
    intended action and the new content to write.

    Callers (product-hook regen-views, prawduct-setup.py views) decide whether
    to apply the changes.
    """
    state_path = prawduct_dir / "project-state.yaml"
    if not is_views_enabled(state_path):
        return False, []

    change_log_path = prawduct_dir / "change-log.md"
    # Resolve the active plan via the optional `active_build_plan:` pointer
    # (supports scope-named plans); falls back to artifacts/build-plan.md.
    build_plan_path = resolve_build_plan_path(prawduct_dir)
    build_plan_rel = build_plan_path.relative_to(prawduct_dir).as_posix()
    release_notes_path = prawduct_dir / "release-notes.md"
    if not change_log_path.exists():
        raise FileNotFoundError(f"change-log not found at {change_log_path}")
    if not build_plan_path.exists():
        raise FileNotFoundError(f"build-plan not found at {build_plan_path}")

    change_log = change_log_path.read_text(encoding="utf-8")
    build_plan = build_plan_path.read_text(encoding="utf-8")
    project_state = state_path.read_text(encoding="utf-8")

    results: list[ViewRegenResult] = []

    # --- Status view ---
    status_new, status_changes = build_status_view(change_log, build_plan)
    if status_new is None:
        results.append(
            ViewRegenResult(
                name="status",
                action="noop",
                summary="Status: up to date",
                path_relative=build_plan_rel,
            )
        )
    else:
        shipped = sorted(cid for cid, _, new in status_changes if new == "x")
        unshipped = sorted(cid for cid, _, new in status_changes if new == " ")
        parts = []
        if shipped:
            parts.append(f"shipped [{', '.join(shipped)}]")
        if unshipped:
            parts.append(f"unshipped [{', '.join(unshipped)}]")
        results.append(
            ViewRegenResult(
                name="status",
                action="write",
                summary=(
                    f"Status: {len(status_changes)} chunk(s) flipped — "
                    + "; ".join(parts)
                ),
                new_content=status_new,
                path_relative=build_plan_rel,
            )
        )

    # --- Release-notes view ---
    rn_new = build_release_notes_view(change_log)
    if rn_new is None:
        results.append(
            ViewRegenResult(
                name="release-notes",
                action="noop",
                summary="Release notes: no release-tagged shipped entries",
                path_relative="release-notes.md",
            )
        )
    else:
        existing_rn = (
            release_notes_path.read_text(encoding="utf-8")
            if release_notes_path.exists()
            else None
        )
        if existing_rn == rn_new:
            results.append(
                ViewRegenResult(
                    name="release-notes",
                    action="noop",
                    summary="Release notes: up to date",
                    path_relative="release-notes.md",
                )
            )
        else:
            action = "write" if existing_rn is not None else "create"
            results.append(
                ViewRegenResult(
                    name="release-notes",
                    action=action,
                    summary=f"Release notes: {action} release-notes.md",
                    new_content=rn_new,
                    path_relative="release-notes.md",
                )
            )

    # --- Scope-rollups view ---
    scope_new, scopes = build_scope_view(change_log, project_state)
    if scope_new is None:
        results.append(
            ViewRegenResult(
                name="scope-rollups",
                action="noop",
                summary="Scope rollups: up to date",
                path_relative="project-state.yaml",
            )
        )
    else:
        if scopes:
            scope_summary = ", ".join(
                f"{s}={len(scopes[s]['chunks'])} chunk(s)" for s in scopes
            )
            summary = f"Scope rollups: {scope_summary}"
        else:
            summary = "Scope rollups: empty (no scope tags)"
        results.append(
            ViewRegenResult(
                name="scope-rollups",
                action="write",
                summary=summary,
                new_content=scope_new,
                path_relative="project-state.yaml",
            )
        )

    return True, results


def apply_regen(prawduct_dir: Path, results: list[ViewRegenResult]) -> None:
    """Write the new content for each result whose action is not 'noop'."""
    for r in results:
        if r.action == "noop" or r.new_content is None:
            continue
        target = prawduct_dir / r.path_relative
        target.write_text(r.new_content, encoding="utf-8")


def is_views_enabled(project_state_path: Path) -> bool:
    """True if project-state.yaml has top-level ``views_enabled: true``.

    Scans for a column-0 ``views_enabled:`` key, ignoring comments. Returns
    False on any error or missing key — opt-in by design.
    """
    if not project_state_path.exists():
        return False
    try:
        content = project_state_path.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in content.splitlines():
        if raw[:1] in (" ", "\t"):
            continue
        line = raw.split("#", 1)[0].rstrip()
        if not line.startswith("views_enabled:"):
            continue
        value = line.split(":", 1)[1].strip().lower()
        return value == "true"
    return False
