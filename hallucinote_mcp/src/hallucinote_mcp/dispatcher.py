"""Dispatcher — validate, route, execute.

Lives on both sides of the wire:
  - **MCP server side**: incoming MCP tool call → wire.Request → forward to
    the Remote Script over TCP → wire.Response back to the MCP caller. The
    server-side dispatcher mostly hands off; param validation happens
    pre-wire to give the LLM a fast, structured error.
  - **Remote Script side**: incoming wire.Request from the socket → look up
    the action in the shared registry → execute (declarative op via the
    Live API walker, or handler function with a Live context) → wire.Response
    back over the socket.

The same code runs both places because both sides agree on the same
``schema._REGISTRY``.

**Threading discipline.** The dispatcher is called from worker threads
(server-side from the MCP transport, Remote-Script-side from per-client TCP
threads). Live's API requires all access to ``Live.Song.*`` to run on Live's
main thread. The ``LiveContext`` Protocol exposes ``run_on_main`` for that
purpose; the dispatcher wraps the entire executor invocation in a single
``run_on_main`` call so the whole declarative op (walk + property/method
access) is atomic on the main thread. Handlers run on the main thread too
and can call ``context.song`` directly without further marshaling.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Protocol

from . import schema
from .wire import Request, Response, error, ok


logger = logging.getLogger("hallucinote_mcp.dispatcher")


# ---------------------------------------------------------------------------
# LiveContext protocol
# ---------------------------------------------------------------------------


class LiveContext(Protocol):
    """The dispatcher sees the Live API through this Protocol.

    Four members:

      - ``song``: the Live Song object (``Live.Song.Song`` in real Live).
        Accessed from inside ``run_on_main`` callbacks so it's always
        touched on the main thread.

      - ``application``: the Live Application object
        (``Live.Application.Application`` in real Live). Used for
        view-state reads/writes (``set_view`` / ``focused_view``) and
        browser access. Live's ``Song`` does NOT expose ``get_application``
        — the canonical accessor is ``Live.Application.get_application()``
        (module-level), surfaced here so handlers don't import Live
        directly.

      - ``run_on_main(fn)``: invoke a zero-arg callable on Live's main
        thread, block the calling worker thread until it returns, return
        the result (or re-raise the exception). Tests substitute a synchronous
        identity function; real Live uses ``schedule_message``.

      - ``live_state_lock``: a context-manager-shaped lock that serializes
        operations whose correctness depends on shared Live transport
        state (``Song.current_song_time``). Required for every handler
        that writes the playhead — currently ``cue_create``,
        ``cue_create_batch``, ``cue_delete``, ``cue_jump``, and ``seek``.
        Each ``with context.live_state_lock:`` block covers the
        seek + audio-thread-settle + toggle window so concurrent
        callers don't observe each other's intermediate playhead
        writes. See ``handlers/arrangement.py`` for the empirical race
        this guards against (B-21). Re-entrant — a batch handler holds
        it across multiple inner ops without deadlocking.
    """

    @property
    def song(self) -> Any: ...  # pragma: no cover - structural only

    @property
    def application(self) -> Any: ...  # pragma: no cover - structural only

    @property
    def live_state_lock(self) -> Any: ...  # pragma: no cover - structural only

    def run_on_main(self, fn: Callable[[], Any]) -> Any: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------


class ParamValidationError(Exception):
    """Raised when params fail validation. Carries the diagnosis fields."""

    def __init__(self, message: str, *, missing: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing


_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),  # ints are valid floats
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}


def validate_params(action: schema.Action, params: dict[str, Any]) -> dict[str, Any]:
    """Validate params against an action's schema; return a clean param dict.

    Raises ``ParamValidationError`` with structured diagnostics on failure.
    Unknown params are rejected to fail loudly on typos rather than silently
    dropping data.
    """
    spec_by_name = {p.name: p for p in action.params}
    missing = tuple(
        p.name for p in action.params if p.required and p.name not in params
    )
    if missing:
        raise ParamValidationError(
            f"missing required param(s) for {action.tool}({action.name!r}): "
            f"{', '.join(missing)}",
            missing=missing,
        )

    unknown = sorted(set(params) - set(spec_by_name))
    if unknown:
        raise ParamValidationError(
            f"unknown param(s) for {action.tool}({action.name!r}): "
            f"{', '.join(unknown)}"
        )

    cleaned: dict[str, Any] = {}
    for name, value in params.items():
        spec = spec_by_name[name]
        expected = _TYPE_MAP[spec.type]
        # bool is a subclass of int in Python — special-case so int param doesn't
        # accept True/False silently.
        if spec.type == "int" and isinstance(value, bool):
            raise ParamValidationError(
                f"{action.tool}({action.name!r}): param {name!r} must be int, got bool"
            )
        if not isinstance(value, expected):
            raise ParamValidationError(
                f"{action.tool}({action.name!r}): param {name!r} must be "
                f"{spec.type}, got {type(value).__name__}"
            )
        if spec.enum is not None and value not in spec.enum:
            raise ParamValidationError(
                f"{action.tool}({action.name!r}): param {name!r}={value!r} "
                f"not in enum {list(spec.enum)}"
            )
        if spec.minimum is not None and value < spec.minimum:
            raise ParamValidationError(
                f"{action.tool}({action.name!r}): param {name!r}={value} "
                f"below minimum {spec.minimum}"
            )
        if spec.maximum is not None and value > spec.maximum:
            raise ParamValidationError(
                f"{action.tool}({action.name!r}): param {name!r}={value} "
                f"above maximum {spec.maximum}"
            )
        cleaned[name] = value
    return cleaned


# ---------------------------------------------------------------------------
# Help generation
# ---------------------------------------------------------------------------


def help_for_tool(tool: str) -> dict[str, Any]:
    """Generate ``action='help'`` output for a tool from its registered actions."""
    actions = schema.actions_for(tool)
    return {
        "tool": tool,
        "actions": [_action_to_help_entry(a) for a in actions if a.name != "help"],
    }


def _action_to_help_entry(action: schema.Action) -> dict[str, Any]:
    return {
        "name": action.name,
        "description": action.description,
        "required": list(action.required_params()),
        "optional": list(action.optional_params()),
        "params": [
            {
                "name": p.name,
                "type": p.type,
                "required": p.required,
                "enum": list(p.enum) if p.enum is not None else None,
                "minimum": p.minimum,
                "maximum": p.maximum,
                "description": p.description,
            }
            for p in action.params
        ],
        "example": action.example,
        "tips": list(action.tips),
    }


# ---------------------------------------------------------------------------
# Declarative-op execution
# ---------------------------------------------------------------------------


# Placeholder pattern: ``{name}`` or ``{name-N}`` where ``name`` is a Python
# identifier and ``N`` is an integer offset. Tighter than a free regex —
# param names containing ``-`` (which Python identifiers don't allow) can't
# accidentally trigger offset parsing.
_TEMPLATE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9]*)(?:\s*-\s*(\d+))?\}")


def resolve_target(target: str, params: dict[str, Any]) -> str:
    """Substitute ``{param_name}`` and ``{param_name-1}`` placeholders.

    Supports a single arithmetic shape ``{name-1}`` for 1-based-to-0-based
    index conversion — the most common transformation needed when walking
    the Live API. Bigger transforms belong in handler functions.
    """

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        offset_str = match.group(2)
        value = params[name]
        if offset_str is None:
            return str(value)
        return str(int(value) - int(offset_str))

    return _TEMPLATE_PATTERN.sub(repl, target)


_NAV_SEGMENT = re.compile(r"^([a-zA-Z_][a-zA-Z_0-9]*)(?:\[(-?\d+)\])?$")


def walk_song(song: Any, expression: str) -> Any:
    """Walk a navigation expression starting from a Live Song object.

    The dispatcher calls this from inside a ``run_on_main`` callback, so the
    walk happens on Live's main thread (the only thread allowed to touch
    ``Live.Song.*``).
    """
    if expression in ("", "song"):
        return song
    if not expression.startswith("song"):
        raise ValueError(
            f"navigation expression must start with 'song', got {expression!r}"
        )
    tail = expression[len("song") :].lstrip(".")
    current: Any = song
    if not tail:
        return current
    for segment in tail.split("."):
        match = _NAV_SEGMENT.match(segment)
        if match is None:
            raise ValueError(
                f"invalid navigation segment {segment!r} in expression "
                f"{expression!r}"
            )
        attr, index_str = match.group(1), match.group(2)
        current = getattr(current, attr)
        if index_str is not None:
            current = current[int(index_str)]
    return current


def _render_result_template(
    template: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Build a result dict from a LiveOp.result_template + validated params.

    String values starting with ``$`` are resolved as param refs
    (``"$bpm"`` → ``params["bpm"]``); other values are literal. Used by
    declarative ops whose natural return value is ``None`` to populate a
    structured response instead of forcing every action to write a
    handler (Wave-2 W2-D / B-15).
    """
    out: dict[str, Any] = {}
    for key, source in template.items():
        if isinstance(source, str) and source.startswith("$"):
            param_name = source[1:]
            if param_name in params:
                out[key] = params[param_name]
            # If the template references an unsupplied optional param,
            # omit the key from the result rather than emit a None.
        else:
            out[key] = source
    return out


def execute_declarative(
    op: schema.LiveOp, params: dict[str, Any], song: Any
) -> Any:
    """Run a declarative op against a Live Song object.

    **Must be called from Live's main thread** (the dispatcher arranges that
    via ``context.run_on_main``). Both the navigation walk AND the final
    property read/write or method call happen here atomically, so neither
    half escapes the main thread.

    If ``op.result_template`` is set, the executor builds a result dict
    from it (after the op runs) regardless of the op's natural return
    value. Without a template, ``property_write`` returns ``None`` and
    ``method_call`` returns whatever the underlying method does.
    """
    target_expr = resolve_target(op.target, params)
    target_obj = walk_song(song, target_expr)
    if op.kind == "property_read":
        return getattr(target_obj, op.property)
    if op.kind == "property_write":
        setattr(target_obj, op.property, params[op.value_param])
        if op.result_template is not None:
            return _render_result_template(op.result_template, params)
        return None
    if op.kind == "method_call":
        method = getattr(target_obj, op.method)
        args = [params[name] for name in op.method_args]
        natural = method(*args)
        if op.result_template is not None:
            return _render_result_template(op.result_template, params)
        return natural
    raise ValueError(f"unknown LiveOp kind: {op.kind!r}")


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


def dispatch(request: Request, context: LiveContext | None = None) -> Response:
    """Validate + route + execute. Returns a canonical ``Response``.

    When ``context`` is ``None`` (server-side, pre-forward), this returns:
      - A help response for ``action='help'`` (no Live needed).
      - A validation error if the request is malformed (fast feedback).
      - A "needs Live execution" response with ``Response.needs_remote = True``
        if validation passed but execution requires Live. The caller
        (server.handle_tool_call) checks this flag and forwards.

    When ``context`` is provided (Remote-Script-side), the dispatcher
    executes the action — declarative ops and handlers both run on Live's
    main thread via ``context.run_on_main``.
    """
    # Tool validity.
    if request.tool not in schema.TOOLS:
        return error(
            f"unknown tool {request.tool!r}; expected one of {list(schema.TOOLS)}",
            valid_actions=list(schema.TOOLS),
            hint="Tool names are stable. Check spelling and case.",
        )

    # Action lookup.
    action = schema.get(request.tool, request.action)
    if action is None:
        valid = schema.action_names_for(request.tool)
        return error(
            f"unknown action {request.action!r} on {request.tool}",
            valid_actions=valid,
            example=f"{request.tool}(action='help')",
            hint=(
                f"Use {request.tool}(action='help') to see the full action menu "
                f"with required/optional params and examples."
            ),
        )

    # Help is special-cased: pure metadata, no Live access required.
    if action.name == "help":
        return ok(help_for_tool(request.tool))

    # Param validation.
    try:
        validated = validate_params(action, request.params)
    except ParamValidationError as exc:
        return error(
            str(exc),
            required=action.required_params(),
            optional=action.optional_params(),
            example=action.example,
            hint=(
                f"Use {action.tool}(action='help') to see the full schema "
                f"for {action.name!r}."
            ),
        )

    # Server-side-only actions execute directly on the MCP server side
    # (no Live needed). The handler is responsible for any I/O it needs
    # (filesystem, local DB, etc.) and receives context=None.
    if action.runs_server_side:
        try:
            result = action.handler(None, **validated)  # type: ignore[misc]
        except KeyError as exc:
            logger.warning(
                "schema bug: %s(%r) server-side handler referenced unknown "
                "param %r",
                action.tool, action.name, exc.args[0],
            )
            return error(
                f"{action.tool}({action.name!r}) handler referenced "
                f"unknown param {exc.args[0]!r}; this is a schema bug",
                hint="Report this — the action schema and handler are out of sync.",
            )
        except Exception as exc:  # prawduct:ok-broad-except — dispatcher boundary; structured response > raw traceback
            logger.exception(
                "server-side handler failed: %s(%r) with params=%r",
                action.tool, action.name, validated,
            )
            return error(
                f"{action.tool}({action.name!r}) failed: {exc.__class__.__name__}: {exc}",
                hint=(
                    f"Check {action.tool}(action='help') for the action's "
                    f"preconditions and value ranges."
                ),
            )
        return ok(result)

    # Execution requires a Live context. Signal "forward me" with a
    # structured flag, not by parsing error text downstream.
    if context is None:
        resp = error(
            f"{action.tool}({action.name!r}) requires the Remote Script side "
            f"to execute (no Live context available)",
            hint=(
                "Ensure Ableton Live is running with the Hallucinote Remote "
                "Script installed and selected as a Control Surface, then "
                "retry the call."
            ),
        )
        return Response(
            ok=resp.ok,
            error=resp.error,
            valid_actions=resp.valid_actions,
            required=resp.required,
            optional=resp.optional,
            example=resp.example,
            hint=resp.hint,
            needs_remote=True,
        )

    # Marshal the full executor invocation onto Live's main thread —
    # unless the action opted out via runs_on_worker (W3-F). Worker-thread
    # handlers manage their own main-thread marshaling via repeated
    # ``context.run_on_main(...)`` calls, with worker-side
    # ``time.sleep()`` between to let the main thread pump events
    # between bouts. The default (main-thread-wrapped) path stays
    # the safe choice for every other handler.
    def run_executor() -> Any:
        if action.handler is not None:
            return action.handler(context, **validated)
        assert action.declarative_op is not None  # guaranteed by Action.__post_init__
        return execute_declarative(action.declarative_op, validated, context.song)

    try:
        if action.runs_on_worker:
            # Handler is responsible for its own main-thread marshaling.
            # Invariant (__post_init__): runs_on_worker implies handler-based.
            assert action.handler is not None  # guaranteed by Action.__post_init__
            result = action.handler(context, **validated)
        else:
            result = context.run_on_main(run_executor)
    except KeyError as exc:
        logger.warning(
            "schema bug: %s(%r) executor referenced unknown param %r",
            action.tool, action.name, exc.args[0],
        )
        return error(
            f"{action.tool}({action.name!r}) executor referenced "
            f"unknown param {exc.args[0]!r}; this is a schema bug",
            hint="Report this — the action schema and executor are out of sync.",
        )
    except Exception as exc:  # prawduct:ok-broad-except — dispatcher is a system boundary; we MUST translate any executor exception into a structured wire response or the agent gets a raw traceback
        logger.exception(
            "executor failed: %s(%r) with params=%r",
            action.tool, action.name, validated,
        )
        return error(
            f"{action.tool}({action.name!r}) failed: {exc.__class__.__name__}: {exc}",
            hint=(
                f"Check {action.tool}(action='help') for the action's "
                f"preconditions and value ranges."
            ),
        )

    return ok(result)


__all__ = [
    "LiveContext",
    "ParamValidationError",
    "validate_params",
    "help_for_tool",
    "resolve_target",
    "walk_song",
    "execute_declarative",
    "dispatch",
]
