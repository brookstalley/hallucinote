"""Feature streams — what can be known about a sample, as generator input.

A feature stream is a time series measured off an audio file in seconds and
mapped to beats at consumption, through the clip's placement and the song's
tempo map, so a generator sees musical time and a re-tempo does not invalidate
the extraction. The streams themselves (F0, formants, energy, segments) and the
detectors that turn them into events are built in the sibling modules; the
shapes they all share are in ``types.py``.

This package imports nothing from ``hallucinote.db``, ``hallucinote.sync`` or
``hallucinote_mcp`` — a generator consumes its output, and generators are pure.
"""
from __future__ import annotations
