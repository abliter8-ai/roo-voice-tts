# AGENTS.md — setup guide for coding agents

You are a coding agent helping a user run **Roo Voice** — a local text-to-speech app for a single,
fixed voice — on their own machine. Your job: get it running with the least friction, using the
one-command launcher, and only fall back to manual steps if that fails. Do **not** change the voice
config; it is intentionally baked in.

## What this repo is

A local TTS app that serves one reference-conditioned voice ("Roo") behind a small web UI and an
OpenAI-compatible `POST /v1/audio/speech` endpoint. Two runtimes are supported and the launcher picks
the right one automatically:

- **Apple Silicon Mac** → MLX 4-bit (`abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4`, default) or 8-bit (`…_mlx8`).
- **NVIDIA GPU** (Linux/Windows) → transformers INT4 NF4 (`…_int4`, default), INT8 (`…_int8`), or BF16 (`…_bf16`).
- **AMD / any GPU / CPU** → GGUF Q4_K_M (`…_GGUF`) via llama.cpp (Vulkan/ROCm; experimental on AMD). NPU → ONNX (`…_onnx`).
- The installer launcher has a **Runtime** dropdown (auto-detect, or pick a specific build); env `ROO_RUNTIME`/`ROO_MODEL` override in the CLI flow.

The voice is fixed: the bundled `reference.wav` is served internally and the decoding settings are
locked. Users only send text.

## The happy path (do this first)

```bash
# macOS / Linux
./start.sh
# Windows (NVIDIA)
start.bat
```

That auto-detects hardware, creates a `.venv`, installs the right `server/requirements-*.txt`,
downloads the correct model from Hugging Face on first run, and opens `http://localhost:8080/`.
First run is slow (model download 3–6 GB + deps); afterwards it starts in seconds.

To force a specific NVIDIA model:
```bash
ROO_MODEL=abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16 ./start.sh   # full precision
```
Change the port with `PORT=8090 ./start.sh`.

## Hardware requirements (tell the user if theirs doesn't match)

| Hardware | Model | Approx. memory |
|---|---|---|
| Apple Silicon (M1–M4) | MLX 4-bit, ~2.3 GB (default) | ~4 GB unified |
| NVIDIA Turing+ (RTX 20-series and newer) | INT4 NF4, ~3.5 GB (default) | ~4 GB VRAM |
| NVIDIA, full precision | BF16, ~5.8 GB | ~9–10 GB VRAM |

No Intel-Mac, AMD-GPU, or CPU-practical path — generation on CPU is far too slow to use.

## Manual setup (only if the launcher fails)

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -U pip
# Apple Silicon:
python -m pip install -r server/requirements-mlx.txt
python server/roo_serve.py --runtime mlx \
  --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4 --reference reference.wav --port 8080
# NVIDIA:
python -m pip install -r server/requirements-cuda.txt
python server/roo_serve.py --runtime transformers \
  --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4 \
  --codec OpenMOSS-Team/MOSS-Audio-Tokenizer --reference reference.wav --port 8080
```

## Using the voice (share with the user)

- Keep inputs to a **sentence or two (~15 s)** — it's a short-clip single-voice model; quality drifts on
  long text.
- **Punctuation** shapes the pauses. **No SSML / markup** (it's ignored).
- For **longer audio**: the web UI has a **Compose** button (enter one sentence per line → it stitches
  them in the browser into one WAV). There's also `tools/compose.py` for scripting (that one needs
  `ffmpeg` on PATH; the web UI does not).

## Troubleshooting (common, in order of likelihood)

**Step 1 — get the diagnostics report. Do not theorise from a description.**

- Launcher → **Save report** (it appears automatically on failure) → `~/Desktop/roo-voice-report.txt`
- Or, while running: `curl -s localhost:8080/diagnostics`
- Or the logs: `~/Library/Application Support/Roo Voice/logs/` (macOS) · `%LOCALAPPDATA%\Roo Voice\logs\` (Windows)

It carries hardware, chip, RAM, runtime, model, quantisation, torch/mlx versions,
`torch.cuda.is_available()`, the device actually in use, warm-up seconds, recent generation timings
and full tracebacks. Home paths are redacted to `~`. Both v1.0 field reports were misdiagnosed as
model bugs and would have been obvious from this file.


1. **`transformers` version error / `generate` fails on NVIDIA** — it must be pinned to `5.0.0`
   (the model's remote code). `requirements-cuda.txt` pins it; don't upgrade it.
2. **`bitsandbytes` / CUDA import error** — the user isn't on a CUDA GPU, or the torch/CUDA build
   mismatches. Confirm `nvidia-smi` shows a GPU.
3. **Blackwell (RTX 50-series) fails to use the GPU** — install the CUDA 12.8 PyTorch first:
   `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128`, then re-run.
4. **Out of memory (NVIDIA)** — the INT4 model is the default and the smallest; close other GPU apps.
5. **`ffmpeg not found`** — only affects the CLI `tools/compose.py`. Install ffmpeg
   (`brew install ffmpeg` / `apt install ffmpeg` / `winget install ffmpeg`). The app and UI don't need it.
6. **Port already in use** — set `PORT=...`.
7. **Slow first run** — the server now WARMS UP before reporting ready (IP-176), so the cold
   kernel-compile cost is paid at startup, not on the user's first sentence. Warm-up takes ~4–5 min
   on a MacBook Air, <1 min on a Mac Studio, once (kernels are cached afterwards).
   Measured settled speed per sentence (~4.4 s of audio), 2026-07-17:
   **Mac Studio M1 Max ~10–11 s (2.6×) · MacBook Air M4 ~55 s (12×) · RTX 5060 Ti INT4 ~15 s (3.5×)**.
   ~55 s on an Air-class Mac is normal, not a fault.

## Do NOT

- Don't remove or replace `reference.wav` — it *is* the voice.
- Don't change the decoding contract in `server/roo_serve.py` (`DC`) — it's the accepted setting.
- Don't upgrade `transformers` past 5.0.0 for the NVIDIA runtime.
- Don't try to make it multi-speaker or reference-free — this is a fixed single voice.

## Reference

- Models: <https://huggingface.co/abliter8-ai> (`Roo-Voice_MOSS_TTS_LT_{mlx4,mlx8,int4,int8,bf16,GGUF,onnx}`).
- Recipes with more detail: `recipes/mlx-apple-silicon.md`, `recipes/nvidia-cuda.md`.
