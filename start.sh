#!/usr/bin/env bash
# Roo Voice — one-command local server (macOS / Linux).
# Auto-detects your hardware, installs what it needs, downloads the right model,
# and opens the Roo Voice web UI. The voice config (reference + decoding) is baked
# in — you don't configure anything.
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "  ██████  ROO VOICE  ██████"
echo ""

OS="$(uname -s)"; ARCH="$(uname -m)"
PORT="${PORT:-8080}"
PY="${PYTHON:-python3}"

# ---- pick the runtime for your hardware -----------------------------------
if [ "$OS" = "Darwin" ] && { [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; }; then
  RUNTIME="mlx"
  MODEL="${ROO_MODEL:-abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8}"
  REQ="server/requirements-mlx.txt"
  echo "  Detected: Apple Silicon Mac  →  MLX 8-bit"
elif command -v nvidia-smi >/dev/null 2>&1; then
  RUNTIME="transformers"
  # INT8 by default (smaller); set ROO_MODEL to the BF16 repo for full precision.
  MODEL="${ROO_MODEL:-abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8}"
  REQ="server/requirements-cuda.txt"
  echo "  Detected: NVIDIA GPU  →  transformers ($( [ "${MODEL}" = *bf16* ] && echo BF16 || echo INT8 ))"
else
  echo "  No supported accelerator found."
  echo "  Roo Voice needs an Apple Silicon Mac (M1–M4) or an NVIDIA GPU."
  echo "  See recipes/ for details."
  exit 1
fi

# ---- python check ----------------------------------------------------------
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "  Python 3 not found. Install Python 3.10+ and re-run."
  exit 1
fi

# ---- venv + deps -----------------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment (.venv) ..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
echo "  Installing dependencies (first run only, may take a few minutes) ..."
python -m pip install -q -U pip
python -m pip install -q -r "$REQ"

# ---- launch ----------------------------------------------------------------
echo ""
echo "  Starting Roo Voice on http://localhost:${PORT}/"
echo "  (first start also downloads the model — please wait for 'runtime=' below)"
echo ""

python server/roo_serve.py --runtime "$RUNTIME" --model "$MODEL" \
  --reference reference.wav --port "$PORT" &
SVPID=$!

# open the browser once the server answers
( for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1; then
      (command -v open >/dev/null && open "http://localhost:${PORT}/") \
        || (command -v xdg-open >/dev/null && xdg-open "http://localhost:${PORT}/") || true
      break
    fi; sleep 3
  done ) &

trap 'kill $SVPID 2>/dev/null || true' INT TERM
wait $SVPID
