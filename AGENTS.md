# AGENTS.md — guide for coding agents

You are a coding agent working on **Roo Voice** — a local, single-voice text-to-speech desktop app.
As of **v3.0.0** this is a **native app** (Tauri), not a clone-and-run script. Two audiences below:
helping a **user** install it, or working on the **codebase**. Don't change the locked voice contract
(§ Do NOT).

## What this repo is (v3)

A cross-platform desktop app (macOS / Windows / Linux) that runs one fixed voice ("Roo") entirely
on-device. Architecture:

```
Tauri shell (Rust) ── supervises ──► roo-engine sidecar (one frozen binary, no venv)
  window · tray · updater · bundled models        Qwen3-TTS native tts-server
  · sidecar lifecycle · signing                   → Roo2 Full Clone conditioning
        │ loopback HTTP                            → 24 kHz WAV
  WebView UI (React): Generate · Listen · Studio   → 24 kHz WAV  ·  /v1/audio/speech + /healthz
  (compose/join) · live visualizer · Settings
```

Qwen3-TTS and the complete Roo2 Full Clone reference are bundled per `app/engine/freeze/manifest.json`
(relative paths + **sha256**). Missing or corrupt assets fail clearly; old user models are never
selected and no model download fallback exists. Everything is on a loopback port the shell manages.

**v1 (MOSS-TTS, Python launcher + browser) is retired** but kept in-repo for reference
(`installers/`, `server/`, `web/`, `start.sh`) and as release `v1.1.1`. Do not send users there.

## Helping a USER install it

There is no build step for users — point them at a signed installer:

- **GitHub Releases** (Latest = v3.0.0): <https://github.com/abliter8-ai/roo-voice-tts/releases/latest>
- Release mirrors are published with the measured v3.0.0 installer names.

| Platform | File | Notes |
|---|---|---|
| macOS 14+ (Apple Silicon) | `…_aarch64.dmg` | signed & notarized; Metal |
| Windows 10/11 (x64) | `…_x64-setup.exe` / `.msi` | GPU via Vulkan, CPU fallback |
| Linux x64 (glibc 2.35+) | `.AppImage` / `.deb` / `.rpm` | GPU via Vulkan candidate, CPU fallback |

The installer bundles Qwen3-TTS 0.6B Base, all Roo2 Full Clone reference components, and the native
runtime. No model download or Python install is required. Supported targets are macOS 14+ Apple
Silicon, Windows x64, and Linux x64; GPU paths and CPU fallback require measured qualification.
Native Windows ARM64 and Intel macOS are outside this release.

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
  The freeze bundles the native Qwen runtime, Q8 model assets, and Roo2 reference files; the engine
  is a single binary — no runtime pip/venv.
- **Checks from the repo root**: `python3 -m unittest discover -s app/engine/tests -v` and
  `npm --prefix app run build`. After freezing, run
  `python3 app/engine/freeze/offline-smoke.py --engine app/engine/dist/roo-engine/roo-engine --manifest app/engine/dist/roo-engine/manifest.json --output /tmp/roo-v3-smoke --backend MTL0`
  on macOS; use `CPU` and the `.exe` engine on Windows. Choose a fresh output directory each run.
- **CI**: `.github/workflows/build-v2.yml` builds all three OSes on tag push, signs/notarizes macOS
  (incl. DMG staple), emits the updater `latest.json`, and creates a draft release. Public repo →
  free runners.
- **The v3 voice contract is fixed** Qwen3-TTS 0.6B Base plus all Roo2 Full Clone reference
  components: speaker values, 16 codebooks, and transcript. All components are mandatory and bundled.

## Troubleshooting

**Get the diagnostics report first — don't theorise.** In the app: **Settings → Save diagnostics
report** (a redacted JSON: platform, versions, model, timings, last error), or
`GET http://127.0.0.1:<port>/diagnostics`, or the engine log in the app-data dir
(`~/Library/Application Support/ai.abliter8.roo-voice/` on macOS,
`%APPDATA%\ai.abliter8.roo-voice\` on Windows).

- The status pill reports `loading` → `warming` → `ready`. A full-sentence warmup prepares
  the runtime before the first user request. Measure Qwen timings on the packaged target.
- **Generation failure** — use the diagnostic error and packaged asset manifest first. A missing or
  corrupt model/reference asset must be reported as an initialization error.
- **"App can't be opened" on macOS** — validate signing, notarization, and stapling on the release
  artifact; local unsigned builds are not release evidence.

## Do NOT

- Don't remove any Roo2 Full Clone reference component or add a model download fallback. Missing
  packaged assets must be a readable initialization error.
- Don't re-introduce aggressive per-sentence chunking — merge short sentences (§ Troubleshooting).
- Don't add `torch`/transformers or a user-side environment. The native Qwen runtime ships inside
  the frozen application; keep it venv-free.
- Don't make it multi-speaker or add a model selector — it is a fixed Roo2 voice.
- Don't point users at the v1 launcher (`start.sh` / `server/`) — it's retired.

## Reference

- Model: <https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF> (Q8 Base and 12 Hz tokenizer).
