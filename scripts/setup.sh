#!/usr/bin/env bash
set -euo pipefail

echo "Setting up Atlas..."

PYTHON_BIN="${PYTHON_BIN:-python3}"
MODEL="${ATLAS_LLM_MODEL:-llama3.1:8b}"

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

echo "Setup complete. Run: source .venv/bin/activate && atlas"
