<p align="center"><img src="assets/app-v2.png" alt="Roo Voice v3" width="820"></p>

# Roo Voice

A desktop text-to-speech app for **one voice — Roo's**: that signature baritone with the estuary
accent, delivered by the bundled Qwen3-TTS model and Roo2 Full Clone reference. Type, hear Roo.
Everything runs on your machine: no account, no cloud, no telemetry, no configuration.

**v3.0.0** is a single native app for **macOS, Windows, and Linux**. Qwen3-TTS 0.6B Base, the
complete Roo2 Full Clone reference, and the native runtime are bundled in the installer. Speech
works offline after installation; updates remain separate.

---

## Download

| Platform | File | Notes |
|---|---|---|
| **macOS** (Apple Silicon, macOS 14+) | `Roo Voice_x.x.x_aarch64.dmg` | Signed & notarized. Runs on Metal |
| **Windows 10/11** (x64) | `Roo Voice_x.x.x_x64-setup.exe` | GPU via Vulkan (NVIDIA / AMD / Intel), CPU fallback |
| **Linux** (x64, Ubuntu 22.04+ / glibc 2.35+) | `.AppImage` or `.deb` | GPU via Vulkan candidate, CPU fallback |

⬇️ **[Latest release](https://github.com/abliter8-ai/roo-voice-tts/releases/latest)**

The raw bundled model assets total **1,283,766,112 bytes** before installer compression and runtime
files. No first-run model download is required.

## What you get

- **Generate** — type up to a few paragraphs; long text is split into sentences and joined
  automatically into one clip.
- **History** — every clip is kept locally; replay, save, or delete. Survives restarts.
- **Compose** — merge clips into one longer WAV: reorder, set the gap after each clip, optional
  crossfade, export.
- **Live visualizer** — an audio-reactive energy field, driven by the actual playback.
- **Updates** — download new installers from GitHub Releases.

## Speed — measured, not promised

Generation speed will be reported from packaged release validation. Preliminary local measurements
are not installer evidence and are intentionally omitted here:

| Hardware | Path | Speed |
|---|---|---|
| macOS 14+ Apple Silicon | Metal candidate | Qualification in progress |
| Windows x64 / Linux x64 | Vulkan candidate | Qualification in progress |
| Supported x64 systems | CPU fallback | Qualification in progress |

The packaged runtime includes a CPU fallback. Final RAM, disk, CPU feature, and platform coverage
requirements will be stated from release validation. Raw model assets are 1,283,766,112 bytes;
the final installer size is still pending.

## How it works

```
your text ─→ Qwen3-TTS 0.6B Base + Roo2 Full Clone reference ─→ native tts-server
          ─→ 24 kHz WAV
```

The voice is the fixed Roo2 Full Clone reference: bundled speaker values, all 16 codebooks, and
the reference transcript are required together. A partial reference is an installation error.
The Q8 model files are from [Qwen3-TTS-GGUF](https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF).

Everything is served from a local engine on a loopback port the app manages for you. Remote access
is not required for model loading or first synthesis; your text and audio never leave the machine.

## Troubleshooting

- The status pill under the visualizer tells the truth: `loading` → `warming` → `ready`.
- `warming` exists so your **first generation is fast** — the app pre-compiles the GPU pipelines at
  startup instead of during your first request.
- If the pill says `failed`, the message beside it is the actual reason. File it in
  [Issues](https://github.com/abliter8-ai/roo-voice-tts/issues) together with your OS and hardware.

## Building from source

```bash
# engine (frozen sidecar and native Qwen runtime)
app/engine/freeze/build-macos.sh        # or build-linux.sh / build-windows.ps1
# app shell + UI
cd app && npm ci && npm run tauri build
```

CI builds all three platforms from `.github/workflows/build-v2.yml`; releases are cut from tags.
Supported targets are macOS 14+ Apple Silicon with Metal, Windows x64 and Linux x64 with Vulkan
candidate paths plus CPU fallback. Linux needs the Vulkan loader (`libvulkan1`) and OpenMP
runtime (`libgomp1`), plus Tauri's GTK/WebKit libraries. The Debian package declares these
dependencies. Vulkan acceleration also needs a compatible installed GPU driver.

## Component licenses

The bundled Qwen3-TTS and native runtime carry their upstream licenses. Tauri is MIT/Apache-2.0.

---

<sub>Existing v2 installations retain their history and settings. v3 replaces the old NeuTTS
download path with bundled Qwen3-TTS and the complete Roo2 Full Clone reference.</sub>
