#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Create Atlas's virtual environment first: ./scripts/setup.sh" >&2
  exit 1
fi

VOICE_DIR="$("$PYTHON_BIN" -c 'from pathlib import Path; print(Path.home() / ".atlas" / "voices")')"
mkdir -p "$VOICE_DIR"

echo "Installing the local neural speech engine..."
"$PYTHON_BIN" -m pip install "piper-tts>=1.3,<2"

VOICE_MODELS=(
  en_US-ryan-high
  en_US-joe-medium
  en_US-hfc_male-medium
  en_US-amy-medium
  en_US-hfc_female-medium
)

echo "Downloading five Atlas neural voice models..."
for voice_model in "${VOICE_MODELS[@]}"; do
  "$PYTHON_BIN" -m piper.download_voices --download-dir "$VOICE_DIR" "$voice_model"
done

for voice_model in "${VOICE_MODELS[@]}"; do
  if [ ! -f "$VOICE_DIR/$voice_model.onnx" ]; then
    echo "The $voice_model download did not create the expected model file." >&2
    exit 1
  fi
done

echo "Neural voices ready. Restart Atlas, then choose Local Neural in Settings > Voice."
