#!/usr/bin/env bash
# run_sync.sh — Environment-safe wrapper for sync_runner.py
#
# Handles the Railway/Nixpacks environment mismatch:
#   - Nixpacks installs Python + packages into /opt/venv
#   - numpy (used by sentence-transformers) needs Nix-provided libstdc++
#   - Default LD_LIBRARY_PATH doesn't include the Nix gcc-lib directory
#
# This script sets up the paths, then invokes sync_runner.py with any CLI args
# passed through unchanged.
#
# Used by:
#   - Railway cron service (start command: bash run_sync.sh)
#   - Manual Railway Console runs: bash run_sync.sh --dry-run --client X
#
# Exit code mirrors sync_runner.py:
#   0 = clean run, 1 = one or more client errors, 2 = fatal config error

set -euo pipefail

# Find the Nix-provided libstdc++ directory dynamically so this doesn't break
# if Nixpacks bumps the gcc version. Falls back to a known path if not found.
NIX_GCC_LIB=$(find /nix/store -maxdepth 2 -name "gcc-*-lib" -type d 2>/dev/null | head -1)
if [ -n "${NIX_GCC_LIB}" ] && [ -d "${NIX_GCC_LIB}/lib" ]; then
    export LD_LIBRARY_PATH="${NIX_GCC_LIB}/lib:${LD_LIBRARY_PATH:-}"
else
    echo "[run_sync.sh] warning: could not locate Nix gcc-lib directory" >&2
fi

# Use the venv Python that Nixpacks set up during build
PYTHON_BIN=/opt/venv/bin/python

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "[run_sync.sh] fatal: ${PYTHON_BIN} not found or not executable" >&2
    exit 2
fi

# Pass all script args through to sync_runner.py
exec "${PYTHON_BIN}" sync_runner.py "$@"
