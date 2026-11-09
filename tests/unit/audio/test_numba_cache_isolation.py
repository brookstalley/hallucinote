"""The root conftest gives every pytest process its own numba cache dir.

numba's on-disk JIT cache corrupts under concurrent writers sharing one venv
(see the NUMBA_CACHE_DIR block in the repo-root conftest.py), and the symptom is
a SIGSEGV in some unrelated later audio test. This pins the guard: numba must
actually be reading the directory the conftest exported, which only holds when
the conftest ran before anything imported numba.
"""

from __future__ import annotations

import os


def test_numba_reads_the_process_cache_dir_the_conftest_exported() -> None:
    import numba.core.config as numba_config

    exported = os.environ.get("NUMBA_CACHE_DIR")
    assert exported, "root conftest did not export NUMBA_CACHE_DIR"
    assert numba_config.CACHE_DIR == exported
