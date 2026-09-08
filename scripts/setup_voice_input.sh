#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="${ATLAS_VOICE_INPUT_MODELS_DIR:-$HOME/.atlas/speech-models}"
MODEL_PATH="$MODEL_DIR/ggml-tiny.en.bin"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install the local Whisper engine: https://brew.sh" >&2
  exit 1
fi

echo "Installing local whisper.cpp and microphone support..."
brew install whisper-cpp
"$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR[voice-input]"
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_PATH" ]; then
  curl -L --fail --progress-bar \
    -o "$MODEL_PATH" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin"
fi
echo "Voice input is ready. Restart Atlas, then hold the TRANSMIT VOICE button while speaking."
