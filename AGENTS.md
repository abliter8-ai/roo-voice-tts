# AGENTS.md — guide for coding agents

You are a coding agent working on **Roo Voice** — a local, single-voice text-to-speech desktop app.
As of **v2.0.0** this is a **native app** (Tauri), not a clone-and-run script. Two audiences below:
helping a **user** install it, or working on the **codebase**. Don't change the locked voice contract
(§ Do NOT).

## What this repo is (v2)

A cross-platform desktop app (macOS / Windows / Linux) that runs one fixed voice ("Roo") entirely
on-device. Architecture:

```
Tauri shell (Rust) ── supervises ──► roo-engine sidecar (one frozen binary, no venv)
  window · tray · updater · model download        phonemize(espeak-ng, en-GB)
  · sidecar lifecycle · signing                   → speech codes (llama.cpp, GGUF, GREEDY)
        │ loopback HTTP                            → waveform (NeuCodec int8 ONNX, CPU)
  WebView UI (React): Generate · Listen · Studio   → 24 kHz WAV  ·  /v1/audio/speech + /healthz
  (compose/join) · live visualizer · Settings
```

The voice model downloads on first run per `app/engine/freeze/manifest.json` (HF URL + **sha256**);
it is not bundled. Everything is on a loopback port the shell manages. The only network traffic is
the one-time model download (Hugging Face) and the update check (GitHub).

**v1 (MOSS-TTS, Python launcher + browser) is retired** but kept in-repo for reference
(`installers/`, `server/`, `web/`, `start.sh`) and as release `v1.1.1`. Do not send users there.

## Helping a USER install it

There is no build step for users — point them at a signed installer:

- **GitHub Releases** (Latest = v2.1.0): <https://github.com/abliter8-ai/roo-voice-tts/releases/latest>
- **Direct mirror**: `https://appinstall.ruinpilot.plus/roo-voice-{macos,winx64,linux}-v2_1_0.{dmg,exe,AppImage}`

| Platform | File | Notes |
|---|---|---|
| macOS 14+ (Apple Silicon) | `…_aarch64.dmg` | signed & notarized; Metal |
| Windows 10/11 (x64) | `…_x64-setup.exe` / `.msi` | GPU via Vulkan, CPU fallback |
| Linux x64 (glibc 2.35+) | `.AppImage` (self-updating) / `.deb` / `.rpm` | GPU via Vulkan, CPU fallback |

First launch downloads the voice model (~740 MB, resumable, checksum-verified); later launches take
seconds. **No GPU required** — a modern x86-64 CPU with **AVX2** (≈2013+) runs it at ~real-time;
~2 GB free RAM. Not supported: Intel Macs, native Windows-ARM64 (the x64 build under emulation
produces silence — numerics diverge), pre-AVX2 CPUs.

## Working on the CODEBASE

- **`app/`** — the Tauri v2 project.
  - `app/src/` — React UI (`App.tsx`, `screens/`, `design/` = the ported Claude Design system,
    `engine.ts` = the loopback client + audio player, `compose.ts` = Studio's offline WAV render).
  - `app/src-tauri/` — Rust shell (`src/lib.rs` spawns/supervises the sidecar, hands its port to the
    WebView, tears it down cleanly), `tauri.conf.json`, `entitlements.plist`.
  - `app/engine/roo_engine/` — the Python sidecar: `engine.py` (pipeline + `split_text` chunker),
    `server.py` (HTTP surface, history, `/diagnostics`), `__main__.py` (entrypoint, model resolve).
  - `app/engine/freeze/` — PyInstaller freeze per OS (`build-macos.sh` / `build-linux.sh` /
    `build-windows.ps1`), `presign-macos.sh`, and `manifest.json` (the model pin).
- **Build locally**: `app/engine/freeze/build-<os>.sh` then `cd app && npm ci && npm run tauri build`.
  The freeze bundles espeak-ng + the NeuCodec ONNX decoder + a prebuilt `llama-server`; the engine
  is a single binary — no runtime pip/venv.
- **CI**: `.github/workflows/build-v2.yml` builds all three OSes on tag push, signs/notarizes macOS
  (incl. DMG staple), emits the updater `latest.json`, and creates a draft release. Public repo →
  free runners.
- **The model contract is locked** (from IP-177): **GREEDY** (temperature 0, top_k 1), espeak-ng
  **en-GB** phonemes with `preserve_punctuation, with_stress` — this MUST match training byte-for-byte
  (a parity gate enforces it), **reference-free** single voice, NeuCodec 24 kHz decode.

## Troubleshooting

**Get the diagnostics report first — don't theorise.** In the app: **Settings → Save diagnostics
report** (a redacted JSON: platform, versions, model, timings, last error), or
`GET http://127.0.0.1:<port>/diagnostics`, or the engine log in the app-data dir
(`~/Library/Application Support/ai.abliter8.roo-voice/` on macOS,
`%APPDATA%\ai.abliter8.roo-voice\` on Windows).

- The status pill tells the truth: `downloading` (honest bytes) → `loading` → `warming` → `ready`.
  First launch spends a while in `downloading` (~740 MB). `warming` pre-compiles GPU pipelines so the
  **first** generation is fast (a full-sentence warm-up, since cold Vulkan prefill was ~13 tok/s vs
  ~18k warm).
- **Garbled / rambling / pseudo-foreign gibberish mid-clip** — historically caused by the chunker
  fragmenting short input into out-of-distribution pieces (the model was trained on whole utterances;
  a 2-word prompt makes it ramble to fill space). Fixed in v2.0.0 by merging sentences
  (`split_text`); if it recurs, that's the place to look — never emit tiny chunks.
- **Wrong reading of dates / numbers / IDs** (v2.1.0) — `roo_engine/normalize.py` rewrites the
  structure espeak mangles (ISO dates, hyphenated ranges/IDs, currency order, broken abbreviations)
  and leaves digits for espeak to read. **It performs no number-to-word conversion, deliberately**:
  espeak's en-GB front-end already reads integers, decimals, ordinals, percentages and clock times
  correctly, and reimplementing those only replaces a correct reading with a buggy one. Before
  adding a rule, measure the failure through the **library** phonemizer (`Phonemizer()`), not the
  espeak CLI — they disagree, and the library is what the engine runs (that difference is why
  `09:45` needed a rule at all). Rules are covered by `app/engine/tests/`.
- **Clip ends mid-sentence / last words missing** (fixed v2.1.0) — a generation that stops on the
  1024-code budget rather than `<|SPEECH_GENERATION_END|>` did not finish. `split_text` caps chunks
  by CHARACTERS but the budget is TIME, so slow content (spelled digits, long numbers) overran it
  and the tail was silently dropped. `Engine._audio_for` now re-splits any capped span so each
  piece gets its own budget. Guard activity is reported in `/diagnostics` as `guard_events` — a
  `dropped` entry is the one case where output is knowingly incomplete.
- **"App can't be opened" on macOS** — the DMG is notarized+stapled as of v2.0.0; if a hand-built DMG
  isn't, staple it (`xcrun stapler staple`) or the app inside will still launch (it's separately
  notarized).

## Do NOT

- Don't change the decoding contract: **greedy temp 0**, **en-GB** phonemes, **reference-free**. The
  model was trained for exactly this; changing any of it breaks the voice or the phoneme-parity gate.
- Don't re-introduce aggressive per-sentence chunking — merge short sentences (§ Troubleshooting).
- Don't add `torch`/transformers to the engine — inference is **llama.cpp** (GGUF) now, decode is
  onnxruntime. The engine ships as a frozen binary; keep it venv-free.
- Don't try to make it multi-speaker or reference-conditioned — it is a fixed single voice.
- Don't point users at the v1 launcher (`start.sh` / `server/`) — it's retired.

## Reference

- Model: <https://huggingface.co/abliter8-ai/Roo-Voice-NeuTTS> (+ `-GGUF` for the quants).
- Base: [NeuTTS-Air](https://huggingface.co/neuphonic/neutts-air) · decoder
  [NeuCodec](https://huggingface.co/neuphonic/neucodec).
