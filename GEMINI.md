# GEMINI.md — Gemini CLI guide

**Roo Voice** is a local, single-voice TTS **desktop app**. As of **v3.0.0** it's a native app
(Tauri), not a clone-and-run script. Full detail — architecture, build, troubleshooting, the locked
voice contract — is in [`AGENTS.md`](AGENTS.md); read it. The essentials:

## Helping a user
There's no build step for users — point them at a signed installer:
- Releases (Latest = v3.0.0): <https://github.com/abliter8-ai/roo-voice-tts/releases/latest>

The installer bundles Qwen3-TTS 0.6B Base and the complete Roo2 Full Clone reference. No model
download or Python install is required. Supported targets are macOS 14+ arm64, Windows x64, and
Linux x64. GPU paths, CPU fallback, hardware requirements, and timings remain pending packaged
release validation.

## Working on the code
- `app/` = Tauri project: `app/src/` (React UI), `app/src-tauri/` (Rust shell that supervises the
  sidecar), `app/engine/roo_engine/` (frozen sidecar supervising native Qwen `tts-server`),
  `app/engine/freeze/` (per-OS freeze + bundled asset manifest).
- Build: `app/engine/freeze/build-<os>.sh` then `cd app && npm ci && npm run tauri build`.
  CI: `.github/workflows/build-v2.yml` (tag push → signed/notarized draft release, all 3 OSes).

## If a user says it's broken
Get the report first, don't theorise: **Settings → Save diagnostics report** (or
`GET /diagnostics`, or the engine log under `~/Library/Application Support/ai.abliter8.roo-voice/`).
Status pill: `loading → warming → ready`. Mid-clip garble = the chunker fragmenting
short input (fixed v2.0.0 in `split_text`; never emit tiny chunks — the model rambles on OOD
fragments).

## Do NOT
- Remove any Roo2 Full Clone reference component or add a model download fallback; missing bundled
  assets must fail clearly.
- Re-introduce aggressive per-sentence chunking; add `torch`/transformers or a user-side environment
  (the native Qwen runtime is frozen and venv-free); make it multi-speaker; or point users at the retired
  v1 launcher (`start.sh` / `server/`).

Model: <https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF>.
