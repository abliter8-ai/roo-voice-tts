# CLAUDE.md — Claude Code setup guide

You're helping a user run **Roo Voice** (a local single-voice TTS app) on their machine. Get it running
with the least friction and don't change the baked-in voice config.

**Do this first:** run the one-command launcher, which auto-detects the user's hardware, installs deps
into a `.venv`, downloads the right model, and opens the web UI at `http://localhost:8080/`:

```bash
./start.sh            # macOS / Linux
start.bat             # Windows (NVIDIA GPU)
```

- **Apple Silicon Mac** → MLX 8-bit model (fast, ~3.6 GB).
- **NVIDIA GPU** → transformers INT8 (default, ~4.3 GB) or BF16 (`ROO_MODEL=abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16 ./start.sh`).
- No Intel-Mac / AMD / CPU-practical path.

**Voice usage:** short inputs (a sentence or two, ~15 s); punctuation drives pauses; no SSML. Longer
audio = the UI's **Compose** button (browser-side, no extra tools) or `tools/compose.py` (needs ffmpeg).

**Most common fixes:** keep `transformers==5.0.0` (NVIDIA); RTX 50-series needs the cu128 PyTorch
(`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128`); `ffmpeg` only
matters for the CLI compose tool.

**Do not:** remove `reference.wav`, change the `DC` decoding contract in `server/roo_serve.py`, upgrade
`transformers`, or try to make it reference-free/multi-speaker.

📄 **Full detail, hardware table, and troubleshooting: see [`AGENTS.md`](AGENTS.md).**
