"""Doctor `views` subcommand — inspect or refresh derived views.

Wraps `tools/lib/views.py`'s shared `plan_regen` + `apply_regen` helpers so
the `prawduct-setup.py views <dir>` (and its `--refresh` form) and the
`tools/product-hook regen-views` subcommand reach the same regen logic.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import views as _views


def run_views_command(product_dir: str, *, refresh: bool) -> dict:
    """Inspect (or, with refresh=True, apply) derived-view regeneration.

    Returns a dict shape suitable for both human and JSON output:

        {
          "product_dir": "/abs/path",
          "enabled": bool,
          "refresh": bool,
          "views": [
            {"name": "status", "action": "noop|write|create", "summary": "..."},
            ...
          ],
        }

    On error returns ``{"error": "..."}`` with no other keys.
    """
    product_path = Path(os.path.abspath(product_dir))
    prawduct_dir = product_path / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "error": f"Not a prawduct product: {product_path} has no .prawduct/ directory"
        }

    try:
        enabled, results = _views.plan_regen(prawduct_dir)
    except FileNotFoundError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"I/O error reading view inputs: {e}"}

    payload: dict = {
        "product_dir": str(product_path),
        "enabled": enabled,
        "refresh": refresh,
        "views": [
            {"name": r.name, "action": r.action, "summary": r.summary}
            for r in results
        ],
    }

    if not enabled or not refresh:
        return payload

    try:
        _views.apply_regen(prawduct_dir, results)
    except OSError as e:
        payload["error"] = f"I/O error writing view output: {e}"

    return payload
