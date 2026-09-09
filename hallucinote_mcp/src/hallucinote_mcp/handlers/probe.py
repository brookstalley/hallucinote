"""Imperative handlers for ``ableton_probe`` actions — constrained LOM introspection.

The bridge's permanent capability-probing surface. Every "can Live do X?"
question (third-party devices, new-in-12.x API like ``create_audio_clip``,
envelope hosting rules) used to need throwaway Remote Script code plus a
Live quit/reopen per iteration — Live caches Control Surface modules, so
each probe round-trip cost a restart. This tool makes probing a wire call:

  - ``describe(path)`` — what is at this LOM path? Class name, properties
    (with values), methods (with Boost.Python docstrings, which carry the
    authoritative signatures).
  - ``get(path)`` — read one property, serialized.
  - ``set(path, value)`` — write one property; settability is itself a
    finding (read-only properties refuse with a structured error).
  - ``call(path, method, args, kwargs, then)`` — invoke a LOM method. Args
    are JSON values; an arg of shape ``{"$path": "song...."}`` resolves to
    the live LOM object first (e.g. ``create_automation_envelope`` takes a
    DeviceParameter). ``then`` chains follow-up calls on returned objects
    that have no LOM path.

**Path grammar (deliberately not eval).** A path is a root (``song`` |
``application`` | ``app``) followed by ``.attr`` and ``[int]`` steps only,
tokenized by regex. Anything outside the grammar is rejected before any
attribute access happens. This keeps the surface introspection-shaped:
attribute walks and method calls on LOM objects, never arbitrary Python.

**Mutation is allowed by design.** Probing IS calling — the question
"does ``ClipSlot.create_audio_clip`` exist and what does it accept?" is
answered by calling it. Safety comes from the bridge being localhost-only
and single-user, and from probing in scratch Live sets (decision recorded
in `.prawduct/artifacts/plans/AUD-1M4V/archive/build-plan.md`).

Handlers run on Live's main thread (the dispatcher marshals via
``run_on_main``), so plain attribute access here is thread-safe.
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..dispatcher import LiveContext


# Serialization caps — probes want breadth, not unbounded dumps. A Live set
# can hold hundreds of tracks/clips; 100 elements is enough to see the shape
# and the truncation flag says when there is more.
MAX_VECTOR_ITEMS = 100
MAX_REPR_CHARS = 300


_PATH_RE = re.compile(
    r"^(?P<root>song|application|app)"
    r"(?P<steps>(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)$"
)
_STEP_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def resolve_path(context: LiveContext, path: str) -> Any:
    """Walk a LOM path string to the live object it names.

    Raises ``ValueError`` for grammar violations (with the offending path),
    ``AttributeError`` / ``IndexError`` (annotated with how far the walk got)
    when the set doesn't have what the path names.
    """
    match = _PATH_RE.match(path.strip())
    if match is None:
        raise ValueError(
            f"invalid probe path {path!r}: expected root 'song' or "
            f"'application' followed by '.attr' / '[index]' steps only, "
            f"e.g. \"song.tracks[0].clip_slots[2].clip\""
        )

    root_name = match.group("root")
    obj: Any = context.song if root_name == "song" else context.application

    walked = root_name
    for step in _STEP_RE.finditer(match.group("steps")):
        attr, index = step.group(1), step.group(2)
        if attr is not None:
            try:
                obj = getattr(obj, attr)
            except AttributeError:
                raise AttributeError(
                    f"{walked} ({type(obj).__name__}) has no attribute {attr!r}"
                ) from None
            walked += f".{attr}"
        else:
            i = int(index)
            try:
                obj = obj[i]
            except (IndexError, TypeError) as exc:
                raise IndexError(
                    f"{walked} ({type(obj).__name__}): cannot index [{i}]: {exc}"
                ) from None
            walked += f"[{i}]"
    return obj


def serialize(value: Any, *, depth: int = 0) -> Any:
    """JSON-shape a value read off the LOM.

    Primitives pass through; sequences (including Live's Boost.Python
    vectors) become lists capped at ``MAX_VECTOR_ITEMS`` with an explicit
    truncation marker; everything else becomes a ``{"__lom__", "repr"}``
    summary. One level of sequence nesting is followed — elements below
    that summarize — because probes need "what's in this vector," not a
    whole-set dump.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return repr(value)[:MAX_REPR_CHARS]
    if isinstance(value, dict):
        if depth >= 1:
            return _lom_summary(value)
        return {str(k): serialize(v, depth=depth + 1) for k, v in value.items()}
    if _is_sequence(value):
        if depth >= 1:
            return _lom_summary(value)
        items = []
        truncated = False
        for i, item in enumerate(value):
            if i >= MAX_VECTOR_ITEMS:
                truncated = True
                break
            items.append(serialize(item, depth=depth + 1))
        if truncated:
            return {
                "__truncated__": True,
                "shown": MAX_VECTOR_ITEMS,
                "total": _safe_len(value),
                "items": items,
            }
        return items
    return _lom_summary(value)


def _is_sequence(value: Any) -> bool:
    """True for list/tuple and LOM vector types; False for strings/objects."""
    if isinstance(value, (list, tuple)):
        return True
    # Live's Boost.Python vectors support len() + iteration but are not
    # list subclasses. Anything len()-able and iterable that isn't a
    # mapping counts as a sequence for probing purposes.
    return (
        hasattr(value, "__len__")
        and hasattr(value, "__iter__")
        and not hasattr(value, "keys")
    )


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:  # prawduct:allow prawduct/broad-except -- len() on an arbitrary LOM vector may raise anything; the length is decoration on a truncation marker, not load-bearing
        return None


def _lom_summary(value: Any) -> dict[str, Any]:
    return {
        "__lom__": type(value).__name__,
        "repr": repr(value)[:MAX_REPR_CHARS],
    }


def describe_handler(context: LiveContext, path: str) -> dict[str, Any]:
    """Full introspection snapshot of the object at ``path``."""
    obj = resolve_path(context, path)

    properties: list[dict[str, Any]] = []
    methods: list[dict[str, Any]] = []
    for name in sorted(dir(obj)):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(obj, name)
        except Exception as exc:  # prawduct:allow prawduct/broad-except -- per-attribute probing must survive arbitrary LOM getter failures (state-dependent raises are themselves findings); the error is recorded in the output
            properties.append(
                {"name": name, "error": f"{exc.__class__.__name__}: {exc}"}
            )
            continue
        if callable(attr):
            doc = getattr(attr, "__doc__", None)
            methods.append(
                {
                    "name": name,
                    # Boost.Python docstrings carry the authoritative
                    # signature — the single most useful probe output.
                    "doc": doc.strip()[:MAX_REPR_CHARS] if doc else None,
                }
            )
        else:
            properties.append(
                {
                    "name": name,
                    "type": type(attr).__name__,
                    "value": serialize(attr),
                }
            )

    return {
        "path": path,
        "class": type(obj).__name__,
        "properties": properties,
        "methods": methods,
    }


def get_handler(context: LiveContext, path: str) -> dict[str, Any]:
    """Read the value at ``path``."""
    obj = resolve_path(context, path)
    return {
        "path": path,
        "type": type(obj).__name__,
        "value": serialize(obj),
    }


def _request_differs(requested: Any, current: Any) -> bool:
    """True when a scalar ``set`` request is genuinely different from the
    current value — used to decide whether an unmoved read-back means Live
    silently ignored the write.

    Numbers compare numerically with a small tolerance so float-repr noise
    (e.g. ``0.1 + 0.2`` requested against a stored ``0.3``) is not misread as
    an ignored write; everything else compares by equality (Python's ``==``
    already treats ``120 == 120.0`` as equal). ``bool`` stays exact — it is an
    ``int`` subclass, but ``True``/``False`` are not numeric near-misses.
    """
    if isinstance(requested, bool) or isinstance(current, bool):
        return requested != current
    if isinstance(requested, (int, float)) and isinstance(current, (int, float)):
        return not math.isclose(
            float(requested), float(current), rel_tol=1e-9, abs_tol=1e-12
        )
    return requested != current


def set_handler(context: LiveContext, path: str, value: Any) -> dict[str, Any]:
    """Write a property at ``path``; return old + read-back + a ``changed`` flag.

    Settability is itself a probe finding (e.g. "is ``count_in_duration``
    read-only?") — a refusal from Live propagates as a structured error,
    which IS the result. ``value`` may be ``{"$path": ...}`` for LOM-object
    properties (e.g. ``song.view.highlighted_clip_slot``).

    Some LOM properties accept a ``setattr`` without raising yet **silently
    ignore it** (``song.back_to_arranger`` can only be cleared by Live's GUI
    button; ``song.current_song_time`` only moves via the transport). Those
    writes used to return a bare ``old==new`` that was indistinguishable from
    a successful set-to-the-same-value. We now always report ``changed``
    (``old != new``), and when a *scalar* write asked for a value different
    from the current one but the read-back did not move, we flag
    ``applied: False`` with a teaching ``warning`` so the no-op is observable.
    """
    parent_path, sep, attr = path.strip().rpartition(".")
    if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", attr):
        raise ValueError(
            f"invalid set path {path!r}: must end in '.attribute' "
            f"(indexes cannot be assigned)"
        )
    parent = resolve_path(context, parent_path)
    try:
        old = getattr(parent, attr)
    except AttributeError:
        raise AttributeError(
            f"{parent_path} ({type(parent).__name__}) has no attribute {attr!r}"
        ) from None
    setattr(parent, attr, _resolve_arg(context, value))
    new = getattr(parent, attr)
    old_s, new_s = serialize(old), serialize(new)
    result: dict[str, Any] = {
        "path": path,
        "old": old_s,
        "new": new_s,
        "changed": old_s != new_s,
    }
    # A silently-ignored write: the caller asked for a scalar value that
    # differs from the current one, but the read-back did not move. Live
    # accepted the setattr without raising and then dropped it. ``$path`` /
    # collection writes are skipped — a meaningful "did it change?" compare
    # needs scalars (a set-to-the-same-value legitimately reports old==new).
    is_scalar_request = not isinstance(value, (dict, list))
    if is_scalar_request and old_s == new_s and _request_differs(value, old):
        result["applied"] = False
        result["warning"] = (
            f"Write did not land as requested: read-back ({new_s!r}) is "
            f"unchanged and still differs from the requested value "
            f"({value!r}). Live accepted the setattr without error but did "
            f"not store the request — it either silently ignored the write "
            f"or clamped it back to the current value. Some properties cannot "
            f"be set via probe at all: e.g. song.back_to_arranger clears only "
            f"via Live's Back to Arrangement button, and song.current_song_time "
            f"moves only via ableton_session(action='seek'). Prefer the "
            f"dedicated action or the GUI for those."
        )
    return result


def call_handler(
    context: LiveContext,
    path: str,
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    then: list[Any] | None = None,
) -> dict[str, Any]:
    """Invoke ``method`` on the object at ``path`` with JSON (or $path) args.

    ``then`` chains further calls on each successive RETURN value — the only
    way to reach objects that have no LOM path. The motivating probe:
    ``create_automation_envelope`` returns an AutomationEnvelope that is not
    addressable from ``song``; ``insert_step``/``value_at_time`` must be
    called on that returned object. Each step is
    ``{"method": str[, "args": list][, "kwargs": dict]}``; a step's target is
    the previous step's return value.
    """
    obj = resolve_path(context, path)
    result = _invoke(context, obj, method, args, kwargs, where=path)
    out: dict[str, Any] = {
        "path": path,
        "method": method,
        "result": serialize(result),
    }

    if then:
        steps_out: list[dict[str, Any]] = []
        target = result
        for i, step in enumerate(then):
            if not isinstance(step, dict) or "method" not in step:
                raise ValueError(
                    f"then[{i}] must be an object with a 'method' key, "
                    f"got {step!r}"
                )
            if target is None:
                raise ValueError(
                    f"then[{i}] ({step['method']!r}): previous step returned "
                    f"None — nothing to call on"
                )
            target = _invoke(
                context,
                target,
                str(step["method"]),
                step.get("args"),
                step.get("kwargs"),
                where=f"{path}.{method}(...) then[{i}]",
            )
            steps_out.append(
                {"method": step["method"], "result": serialize(target)}
            )
        out["then"] = steps_out

    return out


def _invoke(
    context: LiveContext,
    obj: Any,
    method: str,
    args: list[Any] | None,
    kwargs: dict[str, Any] | None,
    *,
    where: str,
) -> Any:
    """Shared invoke for ``call`` and its ``then`` steps."""
    try:
        fn = getattr(obj, method)
    except AttributeError:
        raise AttributeError(
            f"{where} ({type(obj).__name__}) has no attribute {method!r}"
        ) from None
    if not callable(fn):
        raise TypeError(
            f"{where}.{method} is a property ({type(fn).__name__}), not a "
            f"method — use action='get'"
        )
    resolved_args = [_resolve_arg(context, a) for a in (args or [])]
    resolved_kwargs = {
        str(k): _resolve_arg(context, v) for k, v in (kwargs or {}).items()
    }
    return fn(*resolved_args, **resolved_kwargs)


def _resolve_arg(context: LiveContext, value: Any) -> Any:
    """``{"$path": "song...."}`` args become live LOM objects; rest pass through.

    Resolution recurses through lists and dicts (warp-marker calls take dict
    args; future probes may take lists of parameters), so a ``$path`` works
    at any nesting depth. A dict whose ONLY key is ``$path`` is the marker;
    any other dict is plain data whose values are resolved recursively.
    """
    if isinstance(value, dict):
        if set(value.keys()) == {"$path"}:
            return resolve_path(context, value["$path"])
        return {str(k): _resolve_arg(context, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_arg(context, v) for v in value]
    return value


__all__ = [
    "MAX_REPR_CHARS",
    "MAX_VECTOR_ITEMS",
    "call_handler",
    "describe_handler",
    "get_handler",
    "resolve_path",
    "serialize",
    "set_handler",
]
