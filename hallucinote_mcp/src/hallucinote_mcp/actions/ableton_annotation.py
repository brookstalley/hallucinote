"""``ableton_annotation`` action schema.

Wraps the W8-C annotations DB layer through MCP so compose-time agents
can read AND write annotations during a session. Without this surface
(or an equivalent), W8-C's annotations table is storage without
affordance — visible from Python, invisible from the agent loop.

Actions:
  - ``add``        — create one annotation (song / time / track scoping
                     falls out of which optional params are set)
  - ``list``       — all annotations on a song (optional ``kind`` filter)
  - ``get_at_bar`` — annotations active at a specific bar
  - ``update``     — patch one annotation in-place (any of body / kind /
                     start_bar / end_bar)
  - ``delete``     — remove one annotation by id

All actions take ``song_slug`` (the directory name under ``songs/``);
the handler resolves it to the per-song DB file and the song row inside.

Importing this module registers all actions; happens once at server boot
via ``actions/__init__.py``.
"""
from __future__ import annotations

from ..handlers import ableton_annotation as annotation_handlers
from ..schema import Action, ParamSpec, register


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="help",
        description=(
            "List all actions on ableton_annotation, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_annotation(action='help')",
    )
)


# Shared kind enum (mirrors db.mutations.ANNOTATION_KINDS).
_KIND_ENUM = ("intent", "stylistic", "structure", "reference", "todo")


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="add",
        description=(
            "Create one annotation. Scope falls out of which optional params "
            "are set: omit all three (track_index/start_bar/end_bar) for a "
            "song-scoped annotation; set start_bar (optionally end_bar) for "
            "a time-range; set track_index for a track-scoped annotation."
        ),
        params=(
            ParamSpec(
                name="song_slug",
                type="str",
                description="Directory name under songs/ (e.g. 'falling-walking').",
            ),
            ParamSpec(
                name="kind",
                type="str",
                enum=_KIND_ENUM,
                description="One of intent/stylistic/structure/reference/todo.",
            ),
            ParamSpec(
                name="body",
                type="str",
                description="The annotation text. No length cap; keep concise.",
            ),
            ParamSpec(
                name="start_bar",
                type="float",
                required=False,
                description=(
                    "Time scoping (1-based bar). If set without end_bar, the "
                    "annotation is open-ended forward from this bar."
                ),
            ),
            ParamSpec(
                name="end_bar",
                type="float",
                required=False,
                description=(
                    "Time scoping. Requires start_bar; must be > start_bar."
                ),
            ),
            ParamSpec(
                name="track_index",
                type="int",
                required=False,
                minimum=1,
                description="1-based track index for track-scoped annotations.",
            ),
        ),
        handler=annotation_handlers.add_handler,
        runs_server_side=True,
        example=(
            "ableton_annotation(action='add', song_slug='falling-walking', "
            "kind='intent', body='verse is sad; weight getting worse')"
        ),
        tips=(
            "Three scopes coexist: song (omit time/track), time-range "
            "(start_bar +/- end_bar), track (track_index +/- time). "
            "track-scoped + time-scoped is valid — both restrict.",
            "Returns the created annotation as a dict including the new id, "
            "useful for a follow-up update/delete.",
        ),
    )
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="list",
        description=(
            "List all annotations on a song, optionally filtered by kind. "
            "Ordered: song-scoped first, then time-scoped by start_bar, "
            "then created_at."
        ),
        params=(
            ParamSpec(name="song_slug", type="str"),
            ParamSpec(
                name="kind",
                type="str",
                required=False,
                enum=_KIND_ENUM,
            ),
        ),
        handler=annotation_handlers.list_handler,
        runs_server_side=True,
        example="ableton_annotation(action='list', song_slug='falling-walking')",
    )
)


# ---------------------------------------------------------------------------
# get_at_bar
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="get_at_bar",
        description=(
            "All annotations active at a given bar. Song-scoped are always "
            "active; time-scoped match [start_bar, end_bar) — or "
            "[start_bar, ∞) if end_bar is open."
        ),
        params=(
            ParamSpec(name="song_slug", type="str"),
            ParamSpec(name="bar", type="float", minimum=0),
        ),
        handler=annotation_handlers.get_at_bar_handler,
        runs_server_side=True,
        example=(
            "ableton_annotation(action='get_at_bar', "
            "song_slug='falling-walking', bar=17.0)"
        ),
    )
)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="update",
        description=(
            "Patch one annotation in-place. At least one of body/kind/"
            "start_bar/end_bar must be set; unset params leave the field "
            "alone. To change the scope to song-level (clear bars), delete "
            "and re-create instead."
        ),
        params=(
            ParamSpec(name="song_slug", type="str"),
            ParamSpec(name="annotation_id", type="str"),
            ParamSpec(name="body", type="str", required=False),
            ParamSpec(
                name="kind",
                type="str",
                required=False,
                enum=_KIND_ENUM,
            ),
            ParamSpec(name="start_bar", type="float", required=False),
            ParamSpec(name="end_bar", type="float", required=False),
        ),
        handler=annotation_handlers.update_handler,
        runs_server_side=True,
        example=(
            "ableton_annotation(action='update', song_slug='falling-walking', "
            "annotation_id='<id from list>', body='updated text')"
        ),
    )
)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_annotation",
        name="delete",
        description=(
            "Remove one annotation by id. Idempotent: deleting a missing "
            "id is a no-op (no error)."
        ),
        params=(
            ParamSpec(name="song_slug", type="str"),
            ParamSpec(name="annotation_id", type="str"),
        ),
        handler=annotation_handlers.delete_handler,
        runs_server_side=True,
        example=(
            "ableton_annotation(action='delete', song_slug='falling-walking', "
            "annotation_id='<id from list>')"
        ),
    )
)
