#!/bin/sh
set -u
cd "$(dirname "$0")/.." || exit 1

python_bin=.venv/bin/python
if [ ! -x "$python_bin" ]; then
    printf '%s\n' "Create .venv and install .[dev] before running checks." >&2
    exit 1
fi

status=0
"$python_bin" -m ruff check . || status=1
"$python_bin" -m ruff format --check . || status=1
"$python_bin" -m pytest -q || status=1
exit "$status"
