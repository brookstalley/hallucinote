"""Handler functions for imperative actions.

The dispatcher routes here when an ``Action`` has a ``handler`` field set
(rather than a ``declarative_op``). Handlers receive the Live context as
their first positional argument and validated keyword arguments matching
the action's ``params`` schema.

Empty in M-0; populated as each tool's actions land in subsequent chunks.
"""
from __future__ import annotations
