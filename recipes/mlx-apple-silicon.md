# Recipe — Apple Silicon (MLX 4-bit (default) / 8-bit)

The fleet-native, fastest, smallest way to run Roo on a Mac.

## Hardware supported

- **Apple Silicon only**: M1, M1 Pro/Max/Ultra, M2, M3, M4 (any variant).
- macOS 13+ recommended.
- ~5 GB of free unified memory while running.
- **Not supported:** Intel Macs, iPhones/iPads, PCs. (Use the NVIDIA recipe on a PC.)

## One command

```bash
./start.sh
```

Everything below is what that does — run it manually only if you prefer.

## Manual steps

```bash
# 1. Python 3.10+ (comes with macOS, or `brew install python`)
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r server/requirements-mlx.txt

# 2. Start the server (downloads the MLX model on first run)
python server/roo_serve.py \
  --runtime mlx \
  --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4 \
  --reference reference.wav \
  --port 8080

# 3. Open the UI
open http://localhost:8080/
```

## Model

- **Default:** [`abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4`](https://huggingface.co/abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4) — MLX 4-bit, ~2.3 GB. Ear-checked; same voice as the 8-bit.
- Opt-in headroom: [`abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8`](https://huggingface.co/abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8)
  — MLX, 8-bit affine, ~3.6 GB.
- The MOSS audio codec is fetched automatically by `mlx-audio` on first use.

## Notes

- Speed depends heavily on **GPU core count**, not Mac generation. Measured 2026-07-17 for a
  one-sentence clip (~4.4 s of audio): **Mac Studio M1 Max ~10–11 s (2.6× RT)**, **MacBook Air M4
  ~55 s (12× RT)**. ~55 s on an Air-class Mac is expected, not a fault.
- The server **warms up before reporting ready** (IP-176): the first run compiles Metal kernels
  (~4–5 min on an Air, <1 min on a Studio), once — kernels are cached afterwards. `/healthz`
  returns `ready:false, phase:"warming"` until that finishes.
- The reference voice is baked into the server — you only send text.
- Keep inputs to a sentence or two (~15 s) for best quality; punctuation drives the pauses; no SSML.
