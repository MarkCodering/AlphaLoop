#!/usr/bin/env bash
# run.sh — Start AlphaLoop
# Usage: ./run.sh [mode] [options]
#   modes: start (default), tui, send "<message>", status
# Examples:
#   ./run.sh
#   ./run.sh tui
#   ./run.sh start --sandbox
#   ./run.sh start --sandbox --docker
#   ./run.sh send "What are your current goals?"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults (override via env or CLI args)
: "${ALPHALOOP_PROVIDER:=ollama}"
: "${ALPHALOOP_MODEL:=lfm2.5-thinking:1.2b}"
: "${ALPHALOOP_HEARTBEAT_INTERVAL:=30}"
: "${ALPHALOOP_THREAD_ID:=alphaloop-main}"

export ALPHALOOP_PROVIDER
export ALPHALOOP_MODEL
export ALPHALOOP_HEARTBEAT_INTERVAL
export ALPHALOOP_THREAD_ID

MODE="${1:-start}"
shift || true

# Check uv is available
if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' not found. Install it from https://docs.astral.sh/uv/" >&2
  exit 1
fi

# Check Ollama is reachable only when using the local Ollama provider
if [[ "$ALPHALOOP_PROVIDER" == "ollama" ]]; then
  if ! curl -sf "${OLLAMA_BASE_URL:-http://localhost:11434}/api/tags" &>/dev/null; then
    echo "WARNING: Ollama doesn't appear to be running at ${OLLAMA_BASE_URL:-http://localhost:11434}" >&2
    echo "         Start it with: ollama serve" >&2
  fi
fi

echo "==> AlphaLoop | provider=$ALPHALOOP_PROVIDER | model=$ALPHALOOP_MODEL | mode=$MODE"

case "$MODE" in
  start)
    uv run python -m main start "$@"
    ;;
  tui)
    uv run python -m main tui "$@"
    ;;
  send)
    uv run python -m main send "$@"
    ;;
  status)
    uv run python -m main status
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [start|tui|send|status] [options]"
    exit 1
    ;;
esac
