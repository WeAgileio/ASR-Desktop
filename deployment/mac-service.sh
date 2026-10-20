#!/bin/bash
set -euo pipefail
# uv bootstraps Python without modifying the project's CLI environment.
if ! command -v uv >/dev/null 2>&1; then
  echo '請先執行：brew install uv ffmpeg' >&2
  exit 1
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec uv run --no-project --no-config --python 3.11.15 python "$SCRIPT_DIR/mac_service.py" "$@"
