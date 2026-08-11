"""Detect a song overview that has drifted from the song's actual form (DOC-4F8M).

A song's `<slug>.md` **Structure** table and its `build.py` module-docstring
section layout both describe the form. Both are rendered ONCE at scaffold time
from the initial section list, and both are hand-maintained afterwards — so they
rot to the scaffold defaults while the real form triples. Observed on `alien`:
the overview still said "8x8-bar sections / composes Intro + Verse 1 only" long
after the form had tripled and three sections were composed. A reader (or a
fresh session) orienting from the overview gets a stale map, and nothing says so.

**Warn, do not regenerate — decided 2026-08-11.** The obvious alternative is to
generate both surfaces from the form and stop hand-maintaining them. Rejected:
both carry composer prose that generation would destroy. The `<slug>.md` table
has a **Feel** column the scaffold seeds `_TODO: fill in_` precisely so the
composer fills it in, and `build.py`'s docstring is authored text in the
composer's own source file (`docs/song-authoring-conventions.md` treats build.py
as authorship, not as a generated artifact). Rewriting either as a side effect of
a build would clobber real work to fix a bookkeeping problem. So: the song
remains the author's, and the tool reports the divergence and names it.

**The canonical form is the DB.** Not the markdown, not the docstring, and not
the `FORM` list in `build.py` source — the DB's `sections` rows are what
`build.py` actually materialized on its last run, which is what every other
reader (push, the lenses, `/compose-review`) already treats as true. Comparing
prose against the DB therefore asks the right question: *does the map match the
territory the rest of the system sees?*
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from hallucinote.db import queries as Q


# `| `Intro` | 1–8 | some feel |` — the shape `scaffold_song.section_table`
# renders. Bars may use an en-dash (what the scaffold writes) or a hyphen (what
# a hand edit usually types); both are accepted so a human edit doesn't read as
# drift. The Feel column is deliberately not captured — it is the composer's.
_ROW = re.compile(
    r"^\|\s*`?(?P<name>[^`|]+?)`?\s*\|\s*(?P<start>\d+)\s*[–-]\s*(?P<end>\d+)\s*\|"
)


@dataclass(frozen=True)
class OverviewDrift:
    """One divergence between the overview's structure table and the DB form.

    ``missing`` = in the DB, absent from the table (the common rot: sections
    composed after the overview was written). ``extra`` = in the table, absent
    from the DB (usually a renamed or dropped section). ``moved`` = present in
    both under the same name but at a different start bar.
    """

    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    moved: tuple[tuple[str, int, float], ...] = ()  # (name, table_start, db_start)

    def __bool__(self) -> bool:
        return bool(self.missing or self.extra or self.moved)

    def describe(self, *, slug: str) -> str:
        """A stderr-shaped report naming each divergence and what to do."""
        lines = [
            f"{slug}.md's Structure table has drifted from the form build.py "
            f"materialized:"
        ]
        if self.missing:
            lines.append(
                f"  - in the song, missing from the table: "
                f"{', '.join(self.missing)}"
            )
        if self.extra:
            lines.append(
                f"  - in the table, not in the song: {', '.join(self.extra)}"
            )
        for name, table_start, db_start in self.moved:
            lines.append(
                f"  - {name}: table says bar {table_start}, song says "
                f"{db_start:g}"
            )
        lines.append(
            "  The overview is hand-maintained on purpose (its Feel column is "
            "yours) — update the table; nothing rewrites it for you."
        )
        return "\n".join(lines)


def _db_sections(conn: sqlite3.Connection, song_id: str) -> dict[str, float]:
    """The canonical form: what build.py actually materialized.

    `sections.start_bar` is REAL — truncating to int would make a section at
    bar 1.5 falsely agree with a surface saying 1.
    """
    return {
        row["name"]: float(row["start_bar"])
        for row in Q.get_sections_for_song(conn, song_id)
    }


def parse_structure_table(markdown: str) -> dict[str, int]:
    """Section name -> start bar, read from the overview's Structure table.

    Reads only the ``## Structure`` section, so a table elsewhere in the
    overview (an arrangement sketch, a device list) is not mistaken for the
    form. Returns ``{}`` when there is no Structure section or it holds no
    parseable rows — "nothing to compare against" is not drift.
    """
    body = markdown.split("## Structure", 1)
    if len(body) < 2:
        return {}
    # Stop at the next heading of any level so a later section can't leak in.
    rest = re.split(r"^#{1,6} ", body[1], maxsplit=1, flags=re.MULTILINE)[0]
    out: dict[str, int] = {}
    for line in rest.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        name = m.group("name").strip()
        if not name or name.lower() == "section":  # the header row
            continue
        out[name] = int(m.group("start"))
    return out


# `    Intro        bars  1-8    (8 bars)` — the shape
# `scaffold_song.section_layout` renders into build.py's module docstring. Same
# hyphen/en-dash tolerance as the markdown table, for the same reason.
_LAYOUT_LINE = re.compile(
    r"^(?P<name>\S.*?)\s+bars\s+(?P<start>\d+)\s*[–-]\s*(?P<end>\d+)\b"
)


def parse_docstring_layout(source: str) -> dict[str, int]:
    """Section name -> start bar, read from build.py's module docstring.

    The scaffold renders this block under a "Section bar layout" heading and
    then never touches it again, so it rots exactly like the markdown table.
    Only the module docstring is read (the text before the first import), so a
    layout-shaped line in a function docstring further down cannot be mistaken
    for the form. Returns ``{}`` when the block is absent or unparseable —
    "nothing to compare against" is not drift.
    """
    head = re.split(r"^(?:import|from)\s", source, maxsplit=1, flags=re.MULTILINE)[0]
    marker = "Section bar layout"
    if marker not in head:
        return {}
    block = head.split(marker, 1)[1]
    out: dict[str, int] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            # A blank line ends the block — the docstring continues with "Run:".
            if out:
                break
            continue
        m = _LAYOUT_LINE.match(stripped)
        if not m:
            if out:
                break
            continue
        out[m.group("name").strip()] = int(m.group("start"))
    return out


def _compare(table: dict[str, int], db_sections: dict[str, float]) -> "OverviewDrift":
    """Set-difference the two, treating a differing start bar as `moved`."""
    missing = tuple(n for n in db_sections if n not in table)
    extra = tuple(n for n in table if n not in db_sections)
    moved = tuple(
        (n, table[n], db_sections[n])
        for n in table
        if n in db_sections and float(table[n]) != db_sections[n]
    )
    return OverviewDrift(missing=missing, extra=extra, moved=moved)


def detect_overview_drift(
    conn: sqlite3.Connection, *, song_id: str, overview_path: Path,
) -> OverviewDrift | None:
    """Compare the overview's Structure table against the DB's sections.

    Returns ``None`` when there is nothing to say — no overview file, or a
    table with no parseable rows (a freshly-scaffolded song whose form has not
    been authored yet is not "drifted"). Otherwise returns an
    :class:`OverviewDrift`, which is falsey when the two agree.
    """
    try:
        markdown = overview_path.read_text()
    except OSError:
        return None
    table = parse_structure_table(markdown)
    if not table:
        return None

    db_sections = _db_sections(conn, song_id)
    if not db_sections:
        return None

    return _compare(table, db_sections)


@dataclass(frozen=True)
class FormDrift:
    """Both derived surfaces, checked together.

    They rot independently — the `alien` case had both stale — so fixing one
    must not mask the other. Falsey when neither has drifted.
    """

    overview: "OverviewDrift | None" = None
    docstring: "OverviewDrift | None" = None

    def __bool__(self) -> bool:
        return bool(self.overview) or bool(self.docstring)

    def describe(self, *, slug: str) -> str:
        parts = []
        if self.overview:
            parts.append(self.overview.describe(slug=slug))
        if self.docstring:
            parts.append(
                self.docstring.describe(slug=slug).replace(
                    f"{slug}.md's Structure table",
                    "build.py's docstring section layout",
                    1,
                )
            )
        return "\n".join(parts)


def detect_form_drift(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    overview_path: Path,
    build_py_path: Path,
) -> FormDrift:
    """Check BOTH derived surfaces against the DB's sections."""
    return FormDrift(
        overview=detect_overview_drift(
            conn, song_id=song_id, overview_path=overview_path,
        ),
        docstring=_detect_docstring_drift(
            conn, song_id=song_id, build_py_path=build_py_path,
        ),
    )


def _detect_docstring_drift(
    conn: sqlite3.Connection, *, song_id: str, build_py_path: Path,
) -> "OverviewDrift | None":
    try:
        source = build_py_path.read_text()
    except OSError:
        return None
    layout = parse_docstring_layout(source)
    if not layout:
        return None
    db_sections = _db_sections(conn, song_id)
    if not db_sections:
        return None
    return _compare(layout, db_sections)


def warn_on_form_drift(
    conn: sqlite3.Connection, *, song_id: str, slug: str, song_dir: Path,
) -> bool:
    """Print a drift report to stderr if either derived surface has rotted.

    The build-close hook: scaffolded `build.py` calls this at the end of its
    run, which is the moment the DB's form is freshly authoritative and the
    author is present. Returns True when something was reported.

    Never raises and never rewrites — a bookkeeping check must not be able to
    fail a build, and both surfaces carry composer prose (see the module
    docstring for why generation was rejected).
    """
    import sys

    try:
        drift = detect_form_drift(
            conn,
            song_id=song_id,
            overview_path=song_dir / f"{slug}.md",
            build_py_path=song_dir / "build.py",
        )
    except Exception:  # prawduct:allow prawduct/broad-except -- an overview bookkeeping check must never fail the build that ran it; a rotted map is a smaller problem than a build that won't finish
        return False
    if not drift:
        return False
    print(drift.describe(slug=slug), file=sys.stderr)
    return True


def main(argv: list[str] | None = None) -> int:
    """``hallucinote overview-drift <slug>`` — report, never rewrite.

    Exit 0 when the overview matches the form (or there is nothing to compare),
    1 when it has drifted. Non-zero so a caller can gate on it; the report goes
    to stderr and the exit code is the machine half.
    """
    import argparse
    import sys

    from hallucinote.db import queries as _Q
    from hallucinote.db.connection import connect, resolve_db_path
    from hallucinote.workspace import resolve_song_dir

    p = argparse.ArgumentParser(
        prog="hallucinote overview-drift",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("slug", help="song slug")
    args = p.parse_args(argv)

    db_path = resolve_db_path(args.slug)
    if not db_path.exists():
        print(
            f"overview-drift: no DB at {db_path} — run the song's build.py "
            f"first; the DB is what the overview is checked against.",
            file=sys.stderr,
        )
        return 2

    song_dir = resolve_song_dir(args.slug)
    conn = connect(db_path)
    try:
        song = _Q.get_song_by_name(conn, args.slug)
        if song is None:
            print(f"overview-drift: no song row named {args.slug!r}", file=sys.stderr)
            return 2
        drift = detect_overview_drift(
            conn, song_id=song["id"], overview_path=song_dir / f"{args.slug}.md",
        )
    finally:
        conn.close()

    if drift is None:
        print(
            f"overview-drift: nothing to compare for {args.slug} "
            f"(no overview, or its Structure table has no rows yet).",
            file=sys.stderr,
        )
        return 0
    if not drift:
        print(f"overview-drift: {args.slug}.md matches the form.", file=sys.stderr)
        return 0
    print(drift.describe(slug=args.slug), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
