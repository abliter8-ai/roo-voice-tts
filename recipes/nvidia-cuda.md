# Recipe — NVIDIA GPU (INT8 or BF16, transformers/PyTorch)

The PC / server path. Runs on Linux or Windows with an NVIDIA CUDA GPU.

## Hardware supported

| | INT8 (default) | BF16 (full precision) |
|---|---|---|
| **GPU** | NVIDIA, Turing / RTX 20-series and newer | NVIDIA, Turing / RTX 20-series and newer |
| **VRAM** | ~6 GB | ~9–10 GB |
| **Needs** | `bitsandbytes` (CUDA) | just PyTorch |

- **NVIDIA CUDA only.** `bitsandbytes` INT8 requires a CUDA GPU; there is no AMD/Apple/CPU-practical path.
- **Blackwell (RTX 50-series, e.g. 5060/5070/5080/5090):** install the CUDA 12.8 PyTorch build first
  (see step 1b) — the default wheels don't yet include Blackwell kernels.
- Older data-center cards (T4, A10, A100, L4, L40) work too.

## One command

```bash
./start.sh            # Linux
start.bat             # Windows
```

Force BF16 instead of INT8:
```bash
ROO_MODEL=abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16 ./start.sh
```

## Manual steps

```bash
# 1. venv
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -U pip

# 1b. (Blackwell / RTX 50-series only) install CUDA 12.8 PyTorch first
# python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# 2. deps  (transformers is pinned to 5.0.0 — required by the model's remote code)
python -m pip install -r server/requirements-cuda.txt

# 3. start (downloads the model + MOSS audio codec on first run)
python server/roo_serve.py \
  --runtime transformers \
  --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8 \
  --codec OpenMOSS-Team/MOSS-Audio-Tokenizer \
  --reference reference.wav \
  --port 8080

# 4. open http://localhost:8080/
```

## Models

- INT8: [`abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8`](https://huggingface.co/abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8) — ~4.3 GB. Backbone INT8; LM heads / embeddings / norms kept fp16 to protect timbre.
- BF16: [`abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16`](https://huggingface.co/abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16) — ~5.8 GB.
- Codec: [`OpenMOSS-Team/MOSS-Audio-Tokenizer`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer) — fetched automatically.

## Notes

- The server keeps the audio codec on **CPU** and the language model on the **GPU** — this fits the
  INT8 model comfortably on a 6 GB card and frees VRAM for generation.
- The reference voice is baked in; you only send text.
- Keep inputs to a sentence or two (~15 s); punctuation drives the pauses; no SSML.

## Troubleshooting

- **`bitsandbytes` import/CUDA error:** you're not on a CUDA GPU, or the CUDA build mismatches your
  driver. Run `nvidia-smi` to confirm a GPU, and on RTX 50-series use the cu128 PyTorch (step 1b).
- **Out of memory:** use the INT8 model (default), close other GPU apps, or add `--device cpu` to
  confirm correctness (slow — not for real use).
- **`transformers` version errors:** keep it pinned at `5.0.0`; newer versions change the generate
  path and break this model's remote code.
