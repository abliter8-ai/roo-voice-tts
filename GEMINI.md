# GEMINI.md — Gemini CLI setup guide

You're helping a user run **Roo Voice** (a local single-voice TTS app) on their machine. Get it running
with the least friction and don't change the baked-in voice config.

**Do this first:** run the one-command launcher, which auto-detects the user's hardware, installs deps
into a `.venv`, downloads the right model, **warms it up**, and opens the web UI at `http://localhost:8080/`:

```bash
./start.sh            # macOS / Linux
start.bat             # Windows (NVIDIA GPU)
```

- **Apple Silicon Mac** → MLX **4-bit** (`…_mlx4`, default, ~2.3 GB). 8-bit (`…_mlx8`) is opt-in headroom.
- **NVIDIA GPU** → transformers **INT4 NF4** (`…_int4`, default, ~3.5 GB). INT8 / BF16 are opt-in.
- No Intel-Mac / AMD / CPU-practical path. **CPU is refused, not fallen back to.**

**Voice usage:** short inputs (a sentence or two, ~15 s); punctuation drives pauses; no SSML. Longer
audio = the UI's **Compose** button (browser-side, no extra tools) or `tools/compose.py` (needs ffmpeg).

## If a user says it's broken — read this before debugging

**Get the diagnostics report first; don't theorise.** `Save report` in the launcher, or
`http://localhost:8080/diagnostics`, or the logs in `~/Library/Application Support/Roo Voice/logs/`
(macOS) / `%LOCALAPPDATA%\Roo Voice\logs\` (Windows). It carries hardware, runtime, versions,
timings and the real traceback.

The two reports that motivated v1.1.0, both of which looked like model bugs and were not (IP-176):

1. **"The installer never completes"** — it was warming up. The first run compiles GPU kernels:
   **~4–5 min on a MacBook Air**, <1 min on a Mac Studio. v1.1.0 does this behind a progress bar
   *before* opening the UI. Measured settled speed per sentence: **M1 Max ~10–11 s · M4 Air ~55 s ·
   RTX 5060 Ti INT4 ~15 s**. ~55 s on an Air-class Mac is normal.
2. **"Loads but never generates" (Windows/NVIDIA)** — `pip install torch` on Windows yields a
   **CPU-only** wheel (~122 MB; the CUDA build is ~2.5 GB and only on PyTorch's index). The app then
   silently ran on CPU. Fix:
   `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128`

**Do not:**
- remove `reference.wav`, or change the `DC` decoding contract in `server/roo_serve.py` (IP-172)
- upgrade `transformers` (pinned `==5.0.0`; the model's remote code targets it)
- try to make it reference-free/multi-speaker
- **re-introduce a silent CPU fallback** — if the accelerator is missing the server must refuse to
  start with an actionable message. A server that looks healthy and never generates is the bug.
- **add `torch` to `requirements-cuda.txt`** — it must come from the cu128 index, never PyPI
- hardcode a runtime label — derive it from the loaded model (v1.0 reported `MLX-8bit` while serving
  mlx4, and `INT8` while serving int4)

📄 **Full detail, hardware table, and troubleshooting: see [`AGENTS.md`](AGENTS.md).**
