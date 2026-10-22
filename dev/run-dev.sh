#!/usr/bin/env bash
# Runs the box on this machine (Mac or Linux) in dev mode: service, player agent and Godot UI.
# The admin app is at http://localhost:8080. Press Ctrl+C to stop everything.
#
# Usage: dev/run-dev.sh [--reset] [--fullscreen]
#   --reset       deletes the dev database, so the first-run setup shows again
#   --fullscreen  runs the UI full screen, like on the box
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
dev_dir="$repo/dev"
venv="$repo/service/.venv"
ui_arguments=()

for argument in "$@"; do
  case "$argument" in
    --reset) rm -rf "$dev_dir/data" ;;
    --fullscreen) ui_arguments+=(--fullscreen) ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done

if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
  "$venv/bin/pip" install -q -e "$repo/service[dev]"
fi
[[ -d "$dev_dir/media" ]] || "$dev_dir/make-test-media.sh" "$dev_dir/media"

export DABOX_DEV=1
export DABOX_MEDIA_DIR="$dev_dir/media"
export DABOX_DATA_DIR="$dev_dir/data"
export DABOX_PORT=8080
export DABOX_PLAY_ROOTS="$dev_dir/media"
export DABOX_AGENT_PORT=8091

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$venv/bin/python" -m dabox.main & pids+=($!)
"$venv/bin/python" -m dabox.agent.main & pids+=($!)

godot --path "$repo/ui" "${ui_arguments[@]}" -- --service=http://127.0.0.1:8080 --agent=http://127.0.0.1:8091
