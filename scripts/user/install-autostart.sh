#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
APP_DIR="$(pwd -P)"
if [[ "$(id -u)" == 0 ]]; then
  echo '通常の実行ユーザーで起動してください。サービス登録時のみsudoを使用します。' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo '先に.venvを作成し、requirements.txtを導入してください。' >&2
  exit 1
fi
if [[ ! -f config.json ]]; then
  cp -- config/config.example.json config.json
fi
.venv/bin/python -c 'import flask, waitress, numpy, onnxruntime; import sys; sys.path.insert(0, "tools/user"); from webui import parse_args; parse_args(["--config", "config.json"])'
service_dir="$(mktemp -d)"
service_file="$service_dir/comfyui-wrapper.service"
trap 'rm -f -- "$service_file"; rmdir -- "$service_dir"' EXIT
.venv/bin/python tools/internal/render_service.py --app-dir "$APP_DIR" --user "$(id -un)" --output "$service_file"
# Validate before changing registered services.
if ! command -v systemd-analyze >/dev/null 2>&1; then
  echo 'systemd-analyze was not found. Run this script on Ubuntu.' >&2
  exit 1
fi
if ! systemd-analyze verify "$service_file"; then
  echo 'Service validation failed. Existing services were not changed.' >&2
  exit 1
fi
# Disable the previous unit before enabling the new name to avoid duplicate servers.
if systemctl cat llmpc-image-webui.service >/dev/null 2>&1; then
  sudo systemctl disable --now llmpc-image-webui.service
fi
sudo install -m 644 -- "$service_file" /etc/systemd/system/comfyui-wrapper.service
sudo systemctl daemon-reload
sudo systemctl enable comfyui-wrapper.service
sudo systemctl restart comfyui-wrapper.service
sudo systemctl --no-pager --full status comfyui-wrapper.service
