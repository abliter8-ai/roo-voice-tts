# GEMINI.md — Gemini CLI guide

**Roo Voice** is a local, single-voice TTS **desktop app**. As of **v2.0.0** it's a native app
(Tauri), not a clone-and-run script. Full detail — architecture, build, troubleshooting, the locked
voice contract — is in [`AGENTS.md`](AGENTS.md); read it. The essentials:

## Helping a user
There's no build step for users — point them at a signed installer:
- Releases (Latest = v2.0.0): <https://github.com/abliter8-ai/roo-voice-tts/releases/latest>
- Mirror: `https://appinstall.ruinpilot.plus/roo-voice-{macos,winx64,linux}-v2_0_0.{dmg,exe,AppImage}`

First launch downloads the voice model (~740 MB, resumable, checksum-verified). No GPU required — a
modern AVX2 CPU runs it at ~real-time. macOS 14+ arm64 / Windows 10-11 x64 / Linux x64. Not
supported: Intel Macs, native Windows-ARM64 (emulated x64 = silence), pre-AVX2 CPUs.

## Working on the code
- `app/` = Tauri project: `app/src/` (React UI), `app/src-tauri/` (Rust shell that supervises the
  sidecar), `app/engine/roo_engine/` (frozen Python sidecar: phonemize en-GB → llama.cpp GGUF greedy
  → NeuCodec ONNX decode), `app/engine/freeze/` (per-OS freeze + `manifest.json` model pin).
- Build: `app/engine/freeze/build-<os>.sh` then `cd app && npm ci && npm run tauri build`.
  CI: `.github/workflows/build-v2.yml` (tag push → signed/notarized draft release, all 3 OSes).

## If a user says it's broken
Get the report first, don't theorise: **Settings → Save diagnostics report** (or
`GET /diagnostics`, or the engine log under `~/Library/Application Support/ai.abliter8.roo-voice/`).
Status pill: `downloading → loading → warming → ready`. Mid-clip garble = the chunker fragmenting
short input (fixed v2.0.0 in `split_text`; never emit tiny chunks — the model rambles on OOD
fragments).

## Do NOT
- Change the decoding contract: **greedy temp 0**, **en-GB** phonemes, **reference-free** (a
  phoneme-parity gate enforces the match to training).
- Re-introduce aggressive per-sentence chunking; add `torch`/transformers to the engine (it's
  llama.cpp + onnxruntime, frozen, venv-free); make it multi-speaker; or point users at the retired
  v1 launcher (`start.sh` / `server/`).

Model: <https://huggingface.co/abliter8-ai/Roo-Voice-NeuTTS> (+ `-GGUF`).
