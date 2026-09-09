"""Asset store — sources a song keeps, and the derived audio it can regenerate.

A sample is the third leg of a song's authorship (``authorship-model.md``): a
recorded asset whose reproducibility means *retaining* it. Sources live under
``assets/sources/`` and are never edited in place; every derived file under
``assets/derived/`` is the output of a recorded recipe and is addressed by the
content of what made it, so nothing can reference a stale file by a current
address. The manifest beside them is source in git; the DB references files by
path and gains no table for any of this.

The value objects every module here exchanges are in ``types.py``. The public
``source`` / ``derive`` surface a song's ``build.py`` imports is composed here
once the store, the recipes and the transforms exist.
"""
from __future__ import annotations
