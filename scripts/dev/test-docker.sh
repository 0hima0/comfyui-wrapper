#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
image=comfyui-wrapper-tests:local
build=true
if [[ "${1:-}" == --no-build ]]; then
  build=false
  shift
fi
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: bash scripts/dev/test-docker.sh [--no-build] [--python-only | --frontend-only] [-v]'
  exit 0
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker was not found. Start Docker Desktop with Linux containers and reopen Git Bash.' >&2
  exit 1
fi
if "$build"; then
  docker build --file docker/tests/Dockerfile --tag "$image" .
fi
# Git Bash/MSYS must not convert container paths such as /tmp to Windows paths.
MSYS_NO_PATHCONV=1 docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=1g,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  "$image" "$@"
