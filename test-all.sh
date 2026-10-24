#!/usr/bin/env bash
# One process per test; one second after each exit by default.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python "$ROOT/test-all.py" "$@"
