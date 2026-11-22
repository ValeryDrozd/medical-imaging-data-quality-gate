#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

# Older Compose releases emit build progress on stdout.
docker compose build gate >&2
exec docker compose run --rm -T gate "$@"
