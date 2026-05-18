"""Shared action schemas — single source of truth for both the MCP server side
and the Live Remote Script side.

The dispatcher (``hallucinote_mcp.dispatcher``) reads this registry to validate
requests, route to declarative ops or handler functions, and generate
``action='help'`` output. Subsequent chunks (M-1 onward) populate it; M-0
leaves it empty.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal


# The ten unified tools. Stable surface — never rename, only alias.
TOOLS: tuple[str, ...] = (
    "ableton_session",
    "ableton_track",
    "ableton_return",
    "ableton_clip",
    "ableton_note",
    "ableton_device",
    "ableton_automation",
    "ableton_arrangement",
    "ableton_scene",
    "ableton_browser",
)


ParamType = Literal["str", "int", "float", "bool", "list", "dict"]
LiveOpKind = Literal["property_read", "property_write", "method_call"]


@dataclass(frozen=True)
class ParamSpec:
    """One parameter on an action.

    The dispatcher uses ``type``, ``required``, ``enum``, ``minimum``,
    ``maximum`` to validate before routing. ``description`` is for
    ``action='help'`` and error responses.
    """

    name: str
    type: ParamType
    required: bool = True
    enum: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""


@dataclass(frozen=True)
class LiveOp:
    """Declarative description of a single Live API operation.

    ``target`` is a navigation expression with ``{param_name}`` placeholders
    that get substituted from validated params at dispatch time. Examples::

        target="song.tracks[{track_index-1}]"
        target="song.tracks[{track_index-1}].mixer_device.volume"

    For ``property_read`` and ``property_write``, ``property`` is the final
    attribute name. ``value_param`` names the validated param that holds the
    value to write (default ``"value"``) — this lets domain-specific names
    (``bpm``, ``volume``) sit in the wire request without forcing a handler.

    For ``method_call``, ``method`` is the method name and ``method_args``
    is a tuple of param-name templates resolved at call time.

    ``result_template`` OVERRIDES the op's natural return value with a
    structured dict — useful for actions where the natural value is
    ``None`` (every ``property_write`` and several ``method_call`` cases
    — ``start_playing`` / ``stop_playing`` / etc). Values starting with
    ``$`` are param references — ``"$bpm"`` means "look up the validated
    'bpm' param and use its value". Other values are literals. Example:
    ``{"is_playing": True}`` for ``play``, ``{"tempo": "$bpm"}`` for
    ``set_tempo``. When ``result_template`` is ``None`` the executor
    returns the op's natural value (``None`` for ``property_write``;
    whatever the method returned for ``method_call``). Avoid setting
    ``result_template`` on a ``method_call`` whose natural return value
    is meaningful — the template would discard it.
    """

    kind: LiveOpKind
    target: str
    property: str = ""
    method: str = ""
    method_args: tuple[str, ...] = ()
    value_param: str = "value"
    result_template: dict[str, Any] | None = None


@dataclass(frozen=True)
class Action:
    """One action on one unified tool.

    Exactly one of ``declarative_op`` or ``handler`` must be set (validated by
    ``__post_init__``). ``help`` actions are special-cased by the dispatcher
    and do not require either.
    """

    tool: str
    name: str
    description: str
    params: tuple[ParamSpec, ...] = ()
    example: str = ""
    tips: tuple[str, ...] = ()
    declarative_op: LiveOp | None = None
    handler: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if self.tool not in TOOLS:
            raise ValueError(
                f"Action.tool={self.tool!r} not in TOOLS; "
                f"unified tool names are stable — add to TOOLS or fix the typo"
            )
        if self.name == "help":
            # Help is dispatcher-special; it must have NEITHER executor field
            # set. A future typo could otherwise silently attach a handler to
            # a 'help' action and confuse the dispatcher's special-casing.
            if self.declarative_op is not None or self.handler is not None:
                raise ValueError(
                    f"Action {self.tool}(help): help actions must not set "
                    f"declarative_op or handler — they are dispatcher-special"
                )
            return
        has_op = self.declarative_op is not None
        has_handler = self.handler is not None
        if has_op == has_handler:
            raise ValueError(
                f"Action {self.tool}({self.name!r}): exactly one of "
                f"declarative_op or handler must be set"
            )

    def required_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.required)

    def optional_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if not p.required)


# Module-level registry. Keyed by ``(tool, action_name)`` for O(1) dispatch.
_REGISTRY: dict[tuple[str, str], Action] = {}


def register(action: Action) -> Action:
    """Register an action. Raises if the (tool, action) pair already exists.

    Returns the action so chunks can do ``X = register(Action(...))`` if they
    want a handle, but typical usage is just ``register(Action(...))``.
    """
    key = (action.tool, action.name)
    if key in _REGISTRY:
        raise ValueError(f"Action already registered: {action.tool}({action.name!r})")
    _REGISTRY[key] = action
    return action


def register_help_actions() -> None:
    """Add a ``help`` action to every tool that doesn't have one yet.

    Idempotent — safe to call from server initialization. Help is purely
    metadata-driven, so the description is generic and the dispatcher
    generates the actual menu from the registry at call time.
    """
    for tool in TOOLS:
        if (tool, "help") in _REGISTRY:
            continue
        _REGISTRY[(tool, "help")] = Action(
            tool=tool,
            name="help",
            description=(
                f"List all actions on {tool}, with required/optional params, "
                f"examples, and tips."
            ),
            example=f"{tool}(action='help')",
        )


def get(tool: str, action: str) -> Action | None:
    """Look up an action. Returns ``None`` if not registered."""
    return _REGISTRY.get((tool, action))


def actions_for(tool: str) -> list[Action]:
    """All registered actions for a tool, sorted by name. ``help`` first."""
    actions = [a for (t, _), a in _REGISTRY.items() if t == tool]
    actions.sort(key=lambda a: (0 if a.name == "help" else 1, a.name))
    return actions


def action_names_for(tool: str) -> list[str]:
    """Just the action names (used in error responses for valid_actions)."""
    return [a.name for a in actions_for(tool)]


def all_actions() -> list[Action]:
    """Every registered action. Mostly useful for introspection / tests."""
    return list(_REGISTRY.values())


def _clear_registry_for_tests() -> None:
    """Test helper — never call from production code."""
    _REGISTRY.clear()


__all__ = [
    "TOOLS",
    "ParamType",
    "LiveOpKind",
    "ParamSpec",
    "LiveOp",
    "Action",
    "register",
    "register_help_actions",
    "get",
    "actions_for",
    "action_names_for",
    "all_actions",
]
