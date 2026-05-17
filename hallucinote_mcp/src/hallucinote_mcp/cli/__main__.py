"""Enable ``python -m hallucinote_mcp.cli ...``.

The install / uninstall skills use this form rather than the
``hallucinote-mcp`` console script, because the console script may not be
on the user's PATH yet (that's one of the things preflight checks for).
"""
from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
