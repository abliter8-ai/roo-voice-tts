#!/usr/bin/env bash
# Roo Voice — one-command local server (macOS / Linux).
# Auto-detects your hardware, installs what it needs, downloads the right model,
# warms it up, and opens the Roo Voice web UI. The voice config (reference +
# decoding) is baked in — you don't configure anything.
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "  ██████  ROO VOICE  ██████   v1.1.0"
echo ""

OS="$(uname -s)"; ARCH="$(uname -m)"
PORT="${PORT:-8080}"
PY="${PYTHON:-python3}"
CUDA_INDEX="https://download.pytorch.org/whl/cu128"
LOGDIR="${ROO_LOG_DIR:-$PWD/logs}"
mkdir -p "$LOGDIR"
INSTALL_LOG="$LOGDIR/install.log"

# ---- pick the runtime for your hardware -----------------------------------
if [ "$OS" = "Darwin" ] && { [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; }; then
  RUNTIME="mlx"
  MODEL="${ROO_MODEL:-abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4}"
  REQ="server/requirements-mlx.txt"
elif command -v nvidia-smi >/dev/null 2>&1; then
  RUNTIME="transformers"
  MODEL="${ROO_MODEL:-abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4}"
  REQ="server/requirements-cuda.txt"
else
  echo "  No supported accelerator found."
  echo "  Roo Voice needs an Apple Silicon Mac (M1–M4) or an NVIDIA GPU."
  echo "  See recipes/ for details."
  exit 1
fi

# Report the model we are ACTUALLY using (IP-176 RC6 — this used to print a
# hardcoded label that disagreed with the model being loaded).
case "$MODEL" in
  *mlx4*) LABEL="MLX 4-bit";;  *mlx8*) LABEL="MLX 8-bit";;
  *int4*) LABEL="INT4 (NF4)";; *int8*) LABEL="INT8";; *bf16*) LABEL="BF16";;
  *)      LABEL="$MODEL";;
esac
echo "  Detected: $([ "$RUNTIME" = mlx ] && echo 'Apple Silicon Mac' || echo 'NVIDIA GPU')  →  $LABEL"
echo "  Model:    $MODEL"

# ---- python check ----------------------------------------------------------
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "  Python 3 not found. Install Python 3.10+ and re-run."
  exit 1
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "?")"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "  Python $PYVER found, but 3.10+ is required."
  echo "  Install a newer Python (or set PYTHON=/path/to/python3.12) and re-run."
  exit 1
fi
# Upper guard: very new interpreters often have no wheels for this stack yet.
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)' 2>/dev/null; then
  echo ""
  echo "  ⚠️  Python $PYVER is newer than this stack is tested against (3.10–3.13)."
  echo "     If dependency installation fails, re-run with an older interpreter, e.g.:"
  echo "       PYTHON=python3.12 ./start.sh"
  echo ""
fi

# ---- venv + deps -----------------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment (.venv) ..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

if [ "$RUNTIME" = "transformers" ]; then
  # IP-176 RC2: torch MUST come from the PyTorch CUDA index. PyPI's wheel is
  # CPU-only on Windows, and this is the bug that made the app "load but never
  # generate". We install from the CUDA index and then prove CUDA is real.
  echo "  Installing PyTorch (CUDA build, ~2.5 GB, first run only) ..."
  python -m pip install -q -U pip
  python -m pip install -q torch torchaudio --index-url "$CUDA_INDEX" 2>&1 | tee -a "$INSTALL_LOG"
fi

echo "  Installing dependencies (first run only, may take a few minutes) ..."
python -m pip install -q -U pip
python -m pip install -q -r "$REQ" 2>&1 | tee -a "$INSTALL_LOG"

if [ "$RUNTIME" = "transformers" ]; then
  if ! python -c 'import torch,sys; sys.exit(0 if torch.version.cuda else 1)' 2>/dev/null; then
    echo ""
    echo "  ✗ A CPU-only PyTorch is installed — Roo Voice needs the CUDA build."
    echo "    Fix:  pip install --force-reinstall torch torchaudio --index-url $CUDA_INDEX"
    echo ""
    exit 1
  fi
fi

# ---- launch ----------------------------------------------------------------
echo ""
echo "  Starting Roo Voice on http://localhost:${PORT}/"
echo "  First start downloads the model, then WARMS IT UP (the first run compiles"
echo "  GPU kernels — up to ~7 min on a MacBook Air, ~1 min on a Mac Studio)."
echo "  The browser opens when it's genuinely ready. Logs: $LOGDIR"
echo ""

python server/roo_serve.py --runtime "$RUNTIME" --model "$MODEL" \
  --reference reference.wav --port "$PORT" --log-dir "$LOGDIR" &
SVPID=$!

# open the browser once the server reports ready:true (not merely listening)
( for _ in $(seq 1 800); do
    if curl -fsS "http://localhost:${PORT}/healthz" 2>/dev/null | grep -q '"ready":true'; then
      (command -v open >/dev/null && open "http://localhost:${PORT}/") \
        || (command -v xdg-open >/dev/null && xdg-open "http://localhost:${PORT}/") || true
      break
    fi
    kill -0 "$SVPID" 2>/dev/null || break
    sleep 3
  done ) &

trap 'kill $SVPID 2>/dev/null || true' INT TERM
wait $SVPID
