#!/usr/bin/env bash
set -euo pipefail
# Update this clone from its origin tracking branch, then restart the Wrapper.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
if ! command -v git >/dev/null 2>&1; then
  echo 'Git was not found. Install Git before updating.' >&2
  exit 1
fi
if [[ ! -d .git ]]; then
  echo 'Run this script from a Git clone. See docs/MAINTENANCE.md#migration.' >&2
  exit 1
fi
case "${OSTYPE:-}" in
  msys*|cygwin*) wrapper_python='.venv/Scripts/python.exe' ;;
  *) wrapper_python='.venv/bin/python' ;;
esac
if [[ ! -x "$wrapper_python" ]]; then
  echo "Virtual environment not found: $wrapper_python" >&2
  exit 1
fi
exec "$wrapper_python" tools/internal/update_app.py "$@"
