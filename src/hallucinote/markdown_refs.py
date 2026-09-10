"""Markdown corpus parser + projection index.

Composer intent + decision rationale live as atomic markdown files under
`songs/<name>/decisions/` and `songs/<name>/annotations/`; the attempt ledger
(kind: attempt — try → outcome → correction, incl. reverted dead ends; ATL-7K3M)
lives under `songs/<name>/attempts/`. This module:

- Parses a YAML-subset frontmatter at the head of each file.
- Walks the corpus and upserts rows into `markdown_refs` (a rebuildable
  projection that makes the file tree queryable from SQL).
- Refreshes the `markdown_refs_fts` FTS5 index by file.
- Tombstones rows whose file vanished — preserving event-side path
  validity for historical queries.

The mutator-emits-event discipline is intentionally bypassed here: reindex
is a projection rebuild from disk, not a domain mutation. The audit-side
event (`MARKDOWN_REF_RECORDED`, W8-B) fires when an LLM-driven write
produces a new file; reindex is the read-side index.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import warnings
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

from hallucinote.db import mutations as M
from hallucinote.db.connection import transaction

# ---------------------------------------------------------------------------
# Frontmatter schema constants
# ---------------------------------------------------------------------------

KINDS = frozenset({"decision", "annotation", "structural-fact", "attempt"})
SCOPES = frozenset({"song", "time", "track", "track-time"})

# Attempt-ledger (kind: attempt) enums (ATL-7K3M). `outcome` = did the tried
# move achieve its goal; `resolution` = what we did with it. `superseded` pairs
# with a `related` link to the successor attempt (the try → outcome → correction
# chain). Both are REQUIRED on an attempt and FORBIDDEN on every other kind.
ATTEMPT_OUTCOMES = frozenset({"worked", "partial", "failed"})
ATTEMPT_RESOLUTIONS = frozenset({"kept", "reverted", "superseded"})

# Allowed frontmatter keys. Unknown keys raise — catches typos at index time.
_ALLOWED_KEYS = frozenset(
    {"date", "kind", "scope", "track", "bars", "tags", "related",
     "outcome", "resolution"}
)

# Keys whose values must be inline-list literals `[a, b, ...]`.
_LIST_KEYS = frozenset({"bars", "tags", "related"})

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FRONTMATTER_DELIM = "---"
_SONG_PATH_RE = re.compile(r"^songs/([a-z0-9_-]+)/")


def _relpath(path: PurePath, repo_root: PurePath) -> str:
    """Repo-relative path as a POSIX-separated string — the one shape a
    `markdown_refs.path` value ever takes.

    Every stored path and the reindex tombstone prefix are built here, so the
    prefix test (`path.startswith(prefix)`) and `_SONG_PATH_RE` above always
    compare like with like. `str(Path.relative_to(...))` would emit the NATIVE
    separator, which on Windows makes a stored `songs\\slug\\decisions\\x.md`
    and a prefix `songs\\slug/` — a match that silently never fires, so a
    single-song reindex tombstones nothing and stale rows outlive their files.
    `as_posix()` is the normalization; it is a no-op where `/` is native.

    Takes `PurePath` so a Windows-shaped path can be exercised (via
    `PureWindowsPath`) from a POSIX test run.
    """
    return path.relative_to(repo_root).as_posix()


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class Frontmatter:
    kind: str
    scope: str
    date: str | None = None
    track: str | None = None
    bars: list[float] | None = None
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    outcome: str | None = None       # kind: attempt only (worked|partial|failed)
    resolution: str | None = None    # kind: attempt only (kept|reverted|superseded)


@dataclass
class MarkdownDoc:
    path: Path           # absolute on disk
    relpath: str         # relative to repo root; PK in markdown_refs
    frontmatter: Frontmatter
    body: str
    content_hash: str    # SHA-256 hex digest of the full file content


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """Parse frontmatter + body from a markdown file's full text.

    Frontmatter is a YAML subset bounded by `---` lines at the start of the
    file. Supported: scalar strings (optionally quoted), ISO dates, numbers,
    and inline lists `[a, b, c]`. Block lists (`- a\\n- b`) are NOT supported
    — keep authoring simple. Unknown keys raise ValueError (typo detection).

    Returns (frontmatter, body). Raises ValueError on missing/malformed
    frontmatter or schema violations.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        raise ValueError("missing frontmatter delimiter on line 1")
    end_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("frontmatter not terminated with '---'")

    raw_kv: dict[str, Any] = {}
    for line_no, line in enumerate(lines[1:end_idx], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(
                f"line {line_no}: expected 'key: value', got {line!r}"
            )
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in _ALLOWED_KEYS:
            raise ValueError(
                f"line {line_no}: unknown frontmatter key {key!r}; "
                f"allowed: {sorted(_ALLOWED_KEYS)}"
            )
        if key in raw_kv:
            raise ValueError(f"line {line_no}: duplicate key {key!r}")
        raw_kv[key] = _parse_value(key, value.strip(), line_no)

    body = "\n".join(lines[end_idx + 1 :]).strip()
    fm = _build_frontmatter(raw_kv)
    return fm, body


def _parse_value(key: str, raw: str, line_no: int) -> Any:
    if key in _LIST_KEYS:
        if not (raw.startswith("[") and raw.endswith("]")):
            raise ValueError(
                f"line {line_no}: key {key!r} expects inline list like "
                f"'[a, b]', got {raw!r}"
            )
        inner = raw[1:-1].strip()
        if not inner:
            return []
        items = _split_inline_list(inner)
        if key == "bars":
            try:
                return [float(s) for s in items]
            except ValueError as exc:
                raise ValueError(
                    f"line {line_no}: bars must be numeric, got {raw!r}"
                ) from exc
        return [_strip_quotes(s) for s in items]
    return _strip_quotes(raw)


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


# Characters that force an inline-list item to be quoted on serialize so the
# parser does not mis-split (',') or mis-bracket ('[' / ']') on it. (SYN-8H2W)
_LIST_ITEM_SPECIAL = (",", "[", "]", '"', "'")


def _split_inline_list(inner: str) -> list[str]:
    """Split an inline-list body on commas that are NOT inside a quoted span.

    Quote characters are kept in the returned items so the caller's
    ``_strip_quotes`` removes them; a quoted item may therefore carry an
    embedded comma without being split. Round-trip partner of
    ``_serialize_list_item`` (SYN-8H2W: items containing ',' / '[' / ']'
    previously broke the YAML-subset round-trip).
    """
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf).strip())
    return items


def _serialize_list_item(x: Any) -> str:
    """Serialize one inline-list item, quoting it iff it carries a character
    the parser would otherwise mis-handle. Round-trip partner of
    ``_split_inline_list`` + ``_strip_quotes``.

    Tags/related are a controlled vocabulary (kebab tags, file paths, item IDs)
    that does not contain quote characters, so the wrap quote is normally ``"``.
    If the item itself contains a ``"`` we wrap with ``'`` instead (and vice
    versa) since this YAML-subset has no escaping. An item containing BOTH quote
    characters is unrepresentable — we raise loudly rather than silently emit a
    value that would not round-trip (Never Silently Drop)."""
    s = str(x)
    if not any(c in s for c in _LIST_ITEM_SPECIAL):
        return s
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    raise ValueError(
        f"inline-list item {s!r} contains both ' and \" — the markdown "
        "frontmatter YAML-subset cannot represent it without escaping"
    )


def _build_frontmatter(raw: dict[str, Any]) -> Frontmatter:
    if "kind" not in raw:
        raise ValueError("frontmatter missing required key 'kind'")
    if "scope" not in raw:
        raise ValueError("frontmatter missing required key 'scope'")
    kind = raw["kind"]
    scope = raw["scope"]
    if kind not in KINDS:
        raise ValueError(f"invalid kind {kind!r}; allowed: {sorted(KINDS)}")
    if scope not in SCOPES:
        raise ValueError(f"invalid scope {scope!r}; allowed: {sorted(SCOPES)}")

    date_val = raw.get("date")
    if date_val is not None and not _ISO_DATE_RE.match(date_val):
        raise ValueError(f"date must be ISO YYYY-MM-DD, got {date_val!r}")
    if kind == "decision" and date_val is None:
        raise ValueError("decisions require a 'date' field")

    bars = raw.get("bars")
    if scope in ("time", "track-time") and bars is None:
        raise ValueError(f"scope {scope!r} requires 'bars' field")
    if bars is not None and len(bars) not in (1, 2):
        raise ValueError(
            f"bars must be [start] or [start, end], got {bars!r}"
        )
    if bars is not None and len(bars) == 2 and bars[1] <= bars[0]:
        raise ValueError(
            f"bars end must exceed start, got [{bars[0]}, {bars[1]}]"
        )

    track = raw.get("track")
    if scope in ("track", "track-time") and not track:
        raise ValueError(f"scope {scope!r} requires 'track' field")

    outcome = raw.get("outcome")
    resolution = raw.get("resolution")
    if kind == "attempt":
        if outcome is None or resolution is None:
            raise ValueError(
                "attempt requires both 'outcome' and 'resolution' fields"
            )
        if outcome not in ATTEMPT_OUTCOMES:
            raise ValueError(
                f"invalid outcome {outcome!r}; allowed: {sorted(ATTEMPT_OUTCOMES)}"
            )
        if resolution not in ATTEMPT_RESOLUTIONS:
            raise ValueError(
                f"invalid resolution {resolution!r}; "
                f"allowed: {sorted(ATTEMPT_RESOLUTIONS)}"
            )
    else:
        if outcome is not None or resolution is not None:
            raise ValueError(
                f"'outcome'/'resolution' are valid only on kind 'attempt', "
                f"not {kind!r}"
            )

    return Frontmatter(
        kind=kind,
        scope=scope,
        date=date_val,
        track=track,
        bars=bars,
        tags=raw.get("tags", []),
        related=raw.get("related", []),
        outcome=outcome,
        resolution=resolution,
    )


# ---------------------------------------------------------------------------
# Disk walk + reindex
# ---------------------------------------------------------------------------

_DECISIONS_GLOB = "decisions/*.md"
_ANNOTATIONS_GLOB = "annotations/*.md"
_ATTEMPTS_GLOB = "attempts/*.md"

# Corpus dir name -> kind for a frontmatter-LESS file. ONLY decisions qualify:
# decisions are conventionally authored as a bare `# NN — Title` body (no `---`
# header), so a missing header there is a supported shape, not a parse error.
# annotations and attempts conventionally CARRY frontmatter — and an attempt's
# REQUIRED `outcome`/`resolution` (enforced by `_build_frontmatter`) can't be
# inferred from a bare body — so a missing header under those dirs is a genuine
# authoring error: it falls through to `reindex_corpus`'s skip-and-warn rather
# than minting a half-valid row the strict authoring path would reject.
_KIND_BY_CORPUS_DIR = {
    "decisions": "decision",
}


def _infer_kind_from_corpus_dir(path: Path) -> str | None:
    """The `kind` for a frontmatter-less file, from its immediate parent dir.
    None unless the file is directly under a dir where a missing header is a
    SUPPORTED shape (only `decisions/` today) — see `_KIND_BY_CORPUS_DIR`."""
    return _KIND_BY_CORPUS_DIR.get(path.parent.name)


def discover_corpus(songs_root: Path) -> list[Path]:
    """Walk decisions/, annotations/, and attempts/ `*.md` for every song.

    Returns absolute paths sorted for determinism.
    """
    paths: list[Path] = []
    if not songs_root.exists():
        return paths
    for song_dir in sorted(songs_root.iterdir()):
        if not song_dir.is_dir():
            continue
        paths.extend(discover_song_corpus(song_dir))
    return paths


def discover_song_corpus(song_dir: Path) -> list[Path]:
    """The decisions + annotations + attempts of a SINGLE song (`songs/<name>/`).

    Returns absolute paths sorted for determinism. Used by per-song
    reindex (recall-on-read) so one song's DB only ever indexes its own
    corpus — ``find_markdown_refs`` in ``/song-context`` does not filter by
    song, so a single-song DB must contain only that song's refs.
    """
    paths: list[Path] = []
    if not song_dir.is_dir():
        return paths
    for sub in (_DECISIONS_GLOB, _ANNOTATIONS_GLOB, _ATTEMPTS_GLOB):
        paths.extend(sorted(song_dir.glob(sub)))
    return paths


def load_markdown_doc(path: Path, *, repo_root: Path) -> MarkdownDoc:
    """Read + parse one file. `repo_root` is used to compute the relative
    path stored in `markdown_refs.path`.

    Frontmatter is OPTIONAL for DECISIONS ONLY. A `decisions/*.md` that does not
    open with a `---` header (the conventional bare `# NN — Title` body) is
    indexed with a default Frontmatter — `kind` 'decision', `scope` 'song' — and
    its FULL text as the searchable body, so `/song-context` FTS works over
    frontmatter-less decisions. Every OTHER kind (annotation, attempt) requires
    frontmatter — a missing header there raises (and `reindex_corpus` turns that
    into a skip-and-warn). A file that DOES open with `---` is parsed strictly: a
    malformed header or unknown key still raises (typo detection), and
    `reindex_corpus` isolates that one bad file rather than aborting the corpus.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == _FRONTMATTER_DELIM:
        try:
            fm, body = parse_frontmatter(text)
        except ValueError as exc:
            raise ValueError(f"failed to parse {path}: {exc}") from exc
    else:
        kind = _infer_kind_from_corpus_dir(path)
        if kind is None:
            raise ValueError(
                f"failed to parse {path}: file has no '---' frontmatter. Only "
                "decisions/ may omit it (indexed as a bare body); annotations "
                "and attempts require frontmatter"
            )
        fm = Frontmatter(kind=kind, scope="song")
        body = text.strip()
    relpath = _relpath(path, repo_root)
    return MarkdownDoc(
        path=path,
        relpath=relpath,
        frontmatter=fm,
        body=body,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def write_markdown_ref(
    conn: sqlite3.Connection,
    *,
    path: Path,
    repo_root: Path,
    body: str,
    frontmatter: dict[str, Any],
    actor: str = "llm",
    request_id: str | None = None,
    reason: str | None = None,
) -> MarkdownDoc:
    """Write a new corpus markdown file (decision / annotation / structural-fact
    / attempt) and emit the audit event.

    This is the LLM-facing one-call surface for "I want to record this" — a
    deliberate choice (`decision`), a scoped intent (`annotation`), or a tried
    move and how it turned out, incl. a reverted dead end (`attempt`). It:

      1. Serializes `frontmatter` into the file's YAML-subset header.
      2. Writes `path` to disk (parents created as needed; UTF-8).
      3. Parses + validates the written file (so schema errors surface
         immediately, not on next reindex).
      4. Upserts the `markdown_refs` row + refreshes FTS5 in one transaction.
      5. Emits `MARKDOWN_REF_RECORDED` via `M.record_markdown_ref`, threaded
         to the active `request_id` so cross-reference queries link this
         record back to the compose session that produced it.

    Returns the parsed `MarkdownDoc`. Reindex of pre-existing files (via
    `reindex_corpus`) is a separate path that does NOT emit this event —
    projection rebuild is not a domain mutation.
    """
    if path.is_absolute():
        # Validation only: raises ValueError when the absolute path escapes
        # the repo root. The relative form itself is recomputed by
        # load_markdown_doc below.
        path.relative_to(repo_root)
    else:
        path = repo_root / path
    text = _serialize_markdown(frontmatter, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    doc = load_markdown_doc(path, repo_root=repo_root)
    song_id = _resolve_song_id(conn, doc.relpath)
    track_id = _resolve_track_id(conn, song_id, doc.frontmatter.track)
    with transaction(conn):
        _upsert_markdown_ref(conn, doc, song_id=song_id, track_id=track_id)
        _refresh_fts(conn, doc)
        M.record_markdown_ref(
            conn,
            path=doc.relpath,
            content_hash=doc.content_hash,
            song_id=song_id,
            frontmatter=frontmatter,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
    return doc


def _serialize_markdown(fm: dict[str, Any], body: str) -> str:
    """Serialize frontmatter dict + body to the YAML-subset format the
    parser accepts. Keys emit in a stable order; lists serialize inline.
    """
    field_order = (
        "date", "kind", "scope", "track", "bars", "tags", "related",
        "outcome", "resolution",
    )
    lines = ["---"]
    for k in field_order:
        if k not in fm or fm[k] is None or fm[k] == []:
            continue
        v = fm[k]
        if isinstance(v, list):
            inner = ", ".join(_serialize_list_item(x) for x in v)
            lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def reindex_corpus(
    conn: sqlite3.Connection,
    *,
    songs_root: Path | None = None,
    repo_root: Path,
    song_dir: Path | None = None,
) -> dict[str, int]:
    """Rebuild the `markdown_refs` + `markdown_refs_fts` projection from disk.

    Pass EITHER ``songs_root`` (walk every song — the whole-corpus reindex used
    by the CLI) OR ``song_dir`` (a single ``songs/<name>/`` — the per-song
    reindex used by recall-on-read). When ``song_dir`` is given, tombstoning is
    scoped to that song's path prefix so reindexing one song never tombstones
    another song's rows in a shared DB.

    Returns counts: {'upserted', 'tombstoned', 'unchanged', 'skipped'} for
    caller logging. A file that fails to parse (a malformed `---` header, an
    unknown key) is SKIPPED with a `warnings.warn` — one bad doc must not blind
    search to all the good ones — and is left out of tombstoning (it exists, it
    is just unparseable, so its stale row stays put rather than being marked
    deleted). The DB writes for the parseable docs happen atomically in one
    transaction. (A frontmatter-less DECISION is NOT a skip — it indexes fine;
    a frontmatter-less annotation/attempt IS a skip, since those kinds require
    frontmatter. See `load_markdown_doc`.)
    """
    if (songs_root is None) == (song_dir is None):
        raise ValueError("pass exactly one of songs_root / song_dir")
    if song_dir is not None:
        corpus = discover_song_corpus(song_dir)
        tombstone_prefix = f"{_relpath(song_dir, repo_root)}/"
    else:
        corpus = discover_corpus(songs_root)  # type: ignore[arg-type]
        tombstone_prefix = None
    docs: list[MarkdownDoc] = []
    skipped: list[str] = []
    for p in corpus:
        try:
            docs.append(load_markdown_doc(p, repo_root=repo_root))
        except ValueError as exc:
            relpath = _relpath(p, repo_root)
            skipped.append(relpath)
            warnings.warn(
                f"reindex_corpus: skipping unparseable corpus file {relpath}: "
                f"{exc} — search will not cover it until it is fixed "
                "(the rest of the corpus still indexed)",
                stacklevel=2,
            )
    # A skipped file EXISTS (it is just unparseable), so keep its path in the
    # on-disk set: it must not be tombstoned as if it had vanished.
    on_disk_paths = {doc.relpath for doc in docs} | set(skipped)

    existing_rows = conn.execute(
        "SELECT path, content_hash, tombstoned_at FROM markdown_refs"
    ).fetchall()
    existing_by_path: dict[str, tuple[str, str | None]] = {
        r["path"]: (r["content_hash"], r["tombstoned_at"])
        for r in existing_rows
    }

    counts = {"upserted": 0, "tombstoned": 0, "unchanged": 0, "skipped": len(skipped)}

    with transaction(conn):
        for doc in docs:
            prev = existing_by_path.get(doc.relpath)
            if (
                prev is not None
                and prev[0] == doc.content_hash
                and prev[1] is None
            ):
                counts["unchanged"] += 1
                continue
            song_id = _resolve_song_id(conn, doc.relpath)
            track_id = _resolve_track_id(
                conn, song_id, doc.frontmatter.track
            )
            _upsert_markdown_ref(
                conn, doc, song_id=song_id, track_id=track_id
            )
            _refresh_fts(conn, doc)
            counts["upserted"] += 1

        for path, (_, tombstoned_at) in existing_by_path.items():
            if path in on_disk_paths or tombstoned_at is not None:
                continue
            # Single-song reindex must not tombstone other songs' rows.
            if tombstone_prefix is not None and not path.startswith(
                tombstone_prefix
            ):
                continue
            conn.execute(
                "UPDATE markdown_refs "
                "SET tombstoned_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE path = ?",
                (path,),
            )
            conn.execute(
                "DELETE FROM markdown_refs_fts WHERE path = ?",
                (path,),
            )
            counts["tombstoned"] += 1

    return counts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_song_id(conn: sqlite3.Connection, relpath: str) -> str | None:
    """Resolve `songs/<slug>/...` → songs.id. None if no matching row."""
    m = _SONG_PATH_RE.match(relpath)
    if not m:
        return None
    row = conn.execute(
        "SELECT id FROM songs WHERE name = ?", (m.group(1),)
    ).fetchone()
    return row["id"] if row else None


def _resolve_track_id(
    conn: sqlite3.Connection,
    song_id: str | None,
    track_name: str | None,
) -> str | None:
    """Resolve frontmatter `track` → tracks.id for this song.

    falling-walking track names are like '01 Drums' / '03 Synth Bass' —
    match by `tracks.name` within the song. Returns None if not found;
    the absence is silent here (caller can decide to warn).
    """
    if not song_id or not track_name:
        return None
    row = conn.execute(
        "SELECT id FROM tracks WHERE song_id = ? AND name = ?",
        (song_id, track_name),
    ).fetchone()
    return row["id"] if row else None


def _upsert_markdown_ref(
    conn: sqlite3.Connection,
    doc: MarkdownDoc,
    *,
    song_id: str | None,
    track_id: str | None,
) -> None:
    fm = doc.frontmatter
    conn.execute(
        """INSERT INTO markdown_refs
              (path, kind, scope, song_id, track_id,
               bars_json, tags_json, related_json, outcome, resolution,
               frontmatter_date, content_hash, indexed_at, tombstoned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL)
           ON CONFLICT(path) DO UPDATE SET
             kind             = excluded.kind,
             scope            = excluded.scope,
             song_id          = excluded.song_id,
             track_id         = excluded.track_id,
             bars_json        = excluded.bars_json,
             tags_json        = excluded.tags_json,
             related_json     = excluded.related_json,
             outcome          = excluded.outcome,
             resolution       = excluded.resolution,
             frontmatter_date = excluded.frontmatter_date,
             content_hash     = excluded.content_hash,
             indexed_at       = excluded.indexed_at,
             tombstoned_at    = NULL""",
        (
            doc.relpath,
            fm.kind,
            fm.scope,
            song_id,
            track_id,
            json.dumps(fm.bars, separators=(",", ":")) if fm.bars is not None else None,
            json.dumps(fm.tags, separators=(",", ":")) if fm.tags else None,
            json.dumps(fm.related, separators=(",", ":")) if fm.related else None,
            fm.outcome,
            fm.resolution,
            fm.date,
            doc.content_hash,
        ),
    )


def _refresh_fts(conn: sqlite3.Connection, doc: MarkdownDoc) -> None:
    tags_str = " ".join(doc.frontmatter.tags) if doc.frontmatter.tags else ""
    conn.execute(
        "DELETE FROM markdown_refs_fts WHERE path = ?", (doc.relpath,)
    )
    conn.execute(
        "INSERT INTO markdown_refs_fts (path, body, tags) VALUES (?, ?, ?)",
        (doc.relpath, doc.body, tags_str),
    )
