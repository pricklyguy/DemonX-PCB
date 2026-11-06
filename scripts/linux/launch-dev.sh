#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ELECTRON="$ROOT/desktop/node_modules/electron/dist/electron"
PYTHON="$ROOT/desktop/.venv/bin/python"
LOG_DIR="$ROOT/desktop/logs"
mkdir -p "$LOG_DIR"
if [[ ! -x "$ELECTRON" ]]; then printf 'Electron runtime missing. Run the explicit setup command first.\n' | tee -a "$LOG_DIR/dev-launch.log"; exit 1; fi
if [[ ! -x "$PYTHON" ]]; then printf 'PCB Prep Python environment missing. Run the explicit setup command first.\n' | tee -a "$LOG_DIR/dev-launch.log"; exit 1; fi
cd "$ROOT"
"$ELECTRON" "$ROOT/desktop/electron/main.mjs" >>"$LOG_DIR/electron.log" 2>&1 &
