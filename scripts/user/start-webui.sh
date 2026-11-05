#!/usr/bin/env bash
# Run in the foreground; Ctrl+C stops the Wrapper.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

case "${OSTYPE:-}" in
  msys*|cygwin*)
    wrapper_python='.venv/Scripts/python.exe'
    ;;
  *)
    wrapper_python='.venv/bin/python'
    ;;
esac

if [[ ! -x "$wrapper_python" ]]; then
  echo "Python virtual environment not found: $wrapper_python" >&2
  echo 'Create it in the application directory:' >&2
  echo '  python -m venv .venv' >&2
  echo "  \"$wrapper_python\" -m pip install -r requirements.txt" >&2
  exit 1
fi

# webui.py loads the default config.json; all supplied arguments are forwarded.
# Do not install dependencies, modify configuration, or start other services here.
exec "$wrapper_python" tools/user/webui.py "$@"
