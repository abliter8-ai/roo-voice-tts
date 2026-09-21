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
| **macOS** (Apple Silicon, macOS 14+) | `Roo.Voice_3.0.0_aarch64.dmg` | Signed & notarized. Runs on Metal |
| **Windows 10/11** (x64) | `Roo.Voice_3.0.0_x64-setup.exe` | Vulkan runtime and CPU fallback; hardware coverage below |
| **Linux** (x64, Ubuntu 22.04+ / glibc 2.35+) | `Roo.Voice_3.0.0_amd64.AppImage` or `.deb` | Vulkan runtime and CPU fallback |

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

## Measured performance

The downloaded v3 release app was tested on an **M1 Max with 64 GB RAM, macOS 26.5**.
External networking was blocked and the installed resources were write-protected.

| Workload | Generation time | Audio duration |
|---|---|---|
| Short clip, warm repeat | 3.17 seconds | 5.36 seconds |
| Longer passage, two joined chunks | 20.24 seconds | 42.63 seconds |

The native server reported **Metal**. Initial load and warmup took 26.55 seconds; a restart took
4.15 seconds. The sampled peak sum of engine and native-server RSS was 3.40 GiB. This does not
measure all GPU memory and is not a minimum-RAM requirement. Other devices will have different
timings.

The installed Windows x64 release also passes offline CPU synthesis, full-reference loading,
repeat generation, history preservation and restart. On the hosted CI runner, a warm request
took 37.22 seconds for 5.20 seconds of audio; the longer passage took 199.34 seconds for 40.71
seconds of audio. These CPU measurements do not describe Vulkan performance. Windows GPU
performance has not been measured. Linux installer qualification is still in progress.

The Windows and Linux x64 builds require an AVX2-capable CPU with FMA, F16C and BMI2 support.
The release build logs confirm these instruction-set targets; older x64 CPUs are not qualified.

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
- During `warming`, the app runs a short synthesis to prepare the compute pipelines before
  accepting your first request. Keep the app open to reuse the loaded model for later clips.
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
