# Test image for testament's container runners (see .testament.toml).
# Mirrors CI (.github/workflows/ci.yml): Python 3.12 + the uv release CI pins.
# The workspace venv is NOT baked in: testament's [setup] runs `uv sync` per
# tree, so this image only changes when the interpreter or uv moves.
# Both bases are pinned by digest so every rebuild gets the same base; move a
# pin on purpose, not by a floating tag.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

COPY --from=ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /uvx /usr/local/bin/

# git + tar: required by testament runners (checkout, plugin unpack).
# procps: `ps`, which tests/unit/tools/test_capture_live_shot.py shells out to
# (CI's ubuntu-latest image has it; slim does not).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git tar procps \
    && rm -rf /var/lib/apt/lists/*

# Use the image's interpreter; never let uv download a different one.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

# Runners refuse an image that runs as root.
RUN useradd --create-home --uid 1000 tester
USER tester
