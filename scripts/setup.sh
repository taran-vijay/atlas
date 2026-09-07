#!/usr/bin/env bash
set -euo pipefail

echo "Setting up Atlas..."

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODEL="${ATLAS_LLM_MODEL:-llama3.1:8b}"

cd "$PROJECT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.11+ is required but was not found." >&2
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama was not found. Install it from https://ollama.com and re-run this script." >&2
  exit 1
fi

echo "Creating virtual environment (.venv)..."
"$PYTHON_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing Atlas in editable mode..."
pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

echo "Pulling default model ($MODEL) via Ollama -- this may take a while..."
ollama pull "$MODEL"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example -- edit it to customize your setup."
fi

LAUNCHER_DIR="${ATLAS_LAUNCHER_DIR:-$HOME/.local/bin}"
LAUNCHER_PATH="$LAUNCHER_DIR/atlas"
TARGET_PATH="$PROJECT_DIR/.venv/bin/atlas"

mkdir -p "$LAUNCHER_DIR"
if [ -e "$LAUNCHER_PATH" ] || [ -L "$LAUNCHER_PATH" ]; then
  if [ "$(readlink "$LAUNCHER_PATH" 2>/dev/null || true)" != "$TARGET_PATH" ]; then
    echo "Did not replace existing launcher: $LAUNCHER_PATH"
    echo "Use: source .venv/bin/activate && atlas local"
    exit 0
  fi
else
  ln -s "$TARGET_PATH" "$LAUNCHER_PATH"
fi

case "${SHELL:-}" in
  */zsh) SHELL_PROFILE="${ZDOTDIR:-$HOME}/.zprofile" ;;
  */bash) SHELL_PROFILE="$HOME/.bash_profile" ;;
  *) SHELL_PROFILE="" ;;
esac

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if [ -n "$SHELL_PROFILE" ] && ! grep -Fqx "$PATH_LINE" "$SHELL_PROFILE" 2>/dev/null; then
  printf '\n# Atlas command launcher\n%s\n' "$PATH_LINE" >> "$SHELL_PROFILE"
fi

echo "Setup complete. Open a new Terminal, then run: atlas local"
