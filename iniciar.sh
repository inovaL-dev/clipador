#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Instale o FFmpeg antes de continuar:"
  echo "  Mac: brew install ffmpeg"
  echo "  Ubuntu/Debian: sudo apt install ffmpeg"
  exit 1
fi

if [ ! -f .venv/instalado-v3.ok ]; then
  echo "Instalando os componentes do clipador. Isso pode levar alguns minutos..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/instalado-v3.ok
fi

export PATH="$PWD/.venv/bin:$PATH"

exec .venv/bin/python clipador.py "$@"
