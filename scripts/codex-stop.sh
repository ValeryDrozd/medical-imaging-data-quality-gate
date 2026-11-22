#!/bin/sh
set -u
cd "$(dirname "$0")/.." || exit 1

if sh scripts/check.sh > .codex-checks.log 2>&1; then
    printf '%s\n' '{"systemMessage":"Ruff and pytest passed. See .codex-checks.log."}'
else
    printf '%s\n' '{"systemMessage":"Quality checks failed. See .codex-checks.log."}'
fi
