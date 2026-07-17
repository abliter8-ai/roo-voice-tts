# Roo Voice — desktop installers

One-click installers that bundle a standalone Python so users need **nothing preinstalled**. On first
launch the app creates a private virtualenv, installs the right dependencies for the machine (MLX on
Apple Silicon, transformers + bitsandbytes on NVIDIA), downloads the model, then serves the UI and opens
the browser. Later launches are near-instant. Shared first-run logic lives in
[`common/bootstrap.py`](common/bootstrap.py).

> **macOS signing — set up, not yet applied to a build.** A Developer ID Application certificate is
> provisioned and the notary credential validates against Apple, but **the signing step has not been
> run against a build yet** — the bundle currently in `build/` is unsigned (`spctl` → `rejected`).
> Run it before shipping:
>
> ```bash
> bash installers/macos/build_dmg.sh          # build
> bash installers/macos/sign_and_notarize.sh  # sign -> notarize -> staple -> assert spctl accepted
> ```
>
> That script must run in a **user-domain keychain session**; it re-execs itself via
> `launchctl asuser` and prompts for sudo once. It aborts rather than producing a silently unsigned
> release (see IP-176 §9.3). Only after `spctl -a -vv` reports **accepted** is this section's claim true.
>
> **Always drag the app to Applications and open it from there — don't run it from the disk image.**
> A quarantined app launched from the DMG gets *translocated*: macOS runs it from a random read-only
> mount, which breaks the app's private virtualenv. v1.1.0 detects this and tells the user to move it.
> Signing + notarizing removes this class of problem entirely.
>
> **Windows: unsigned** — and it stays that way until there's a registered business entity.
> SmartScreen → **More info** → **Run anyway**.
>
> Not a cost decision, an eligibility one: Azure Artifact Signing (the cheapest option at ~€120/yr)
> limits **individual** developers to the USA/Canada, and its **organization** path — which does cover
> the EU/UK — needs a registered legal entity. An individual OV cert costs more (~€200–400/yr **plus a
> hardware token**) and, per Microsoft's own docs, **no code-signing option grants instant SmartScreen
> trust** — reputation accrues with download volume either way. See IP-176 §9.4.
>
> **If you ship an unsigned macOS build:** the old "right-click → Open" advice is stale. On
> **macOS 15+ (incl. 26)** that no longer bypasses Gatekeeper — the user must go to
> **System Settings → Privacy & Security → Open Anyway**.


## Build & release topology — READ THIS FIRST

**This directory is a working copy of a PUBLIC repo.** Nothing here is internal.

| What | Where |
|---|---|
| **Source of truth** | `github.com/abliter8-ai/roo-voice-tts` (public) — `origin` of this checkout |
| **Distribution** | GitHub **Releases** on that repo. v1.0.0 (2026-07-15) shipped `Roo-Voice-Setup.exe` (43 MB) + `Roo-Voice.dmg` (53 MB) |
| **macOS build host** | **ruin-max** — `installers/macos/build_dmg.sh`, then `sign_and_notarize.sh` (Developer ID + notarize; must run in a user-domain keychain session, see IP-176 §9.3) |
| **Windows build host** | **snap2** — `C:\Users\hi\roo-build\…`, Inno Setup 6 at `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` |

### Why the Windows installer is built on an ARM64 machine

snap2 is **ARM64** Windows; the app targets **x64** NVIDIA machines. This is fine, and deliberate:
`build.ps1` downloads an **x86_64** python-build-standalone tarball and repackages it — the payload's
architecture comes from that URL, not from the build host. Inno Setup itself runs under emulation.
(Verified 2026-07-17: the staged `python.exe` in snap2's tree is `PE MACHINE: x64 (AMD64)`.)

**What snap2 can and cannot do:**
- ✅ **Build** the x64 installer.
- ✅ **Verify PyTorch wheel resolution** — the bundled x64 Python runs under emulation, so
  `pip install torch --index-url …/cu128` resolves the same `win_amd64` wheels a real user gets.
  This is the check that would have caught the v1.0 CPU-only-torch bug (IP-176 RC2).
- ❌ **Test generation** — no NVIDIA GPU. End-to-end CUDA is proven on **ruin-ultra** (Linux, sm_120)
  instead. No node on the fleet is both Windows *and* NVIDIA; CR-176 §4 records that gap honestly.

### Release procedure (both artifacts must be at parity)

```bash
# 1. commit + push the source (this checkout IS the public repo)
git push origin main

# 2. macOS — on ruin-max
bash installers/macos/build_dmg.sh
bash installers/macos/sign_and_notarize.sh          # sign -> notarize -> staple -> assert spctl accepted

# 3. Windows — on snap2 (must pull the SAME commit; a stale tree ships old bugs)
ssh snap2  # then, in the roo-build tree: git pull && powershell -File installers\windows\build.ps1

# 4. publish
gh release create vX.Y.Z --repo abliter8-ai/roo-voice-tts \
   "installers/macos/build/Roo-Voice.dmg" "<exe fetched from snap2>"
```

> **Parity is not optional.** The two installers are built on different machines from separate
> checkouts. If snap2's tree is stale, Windows users get a build without the current fixes while macOS
> users get the fix — which is indistinguishable from "the app is broken on Windows". Always confirm
> both hosts are on the same commit before releasing.


## macOS — `Roo Voice.app` / `Roo-Voice.dmg`

**Apple-Silicon only** (MLX requires it). Build on any Apple-Silicon Mac:

```bash
bash installers/macos/build_dmg.sh
# → installers/macos/build/Roo Voice.app  and  Roo-Voice.dmg
```

The script downloads a standalone Python (cached), assembles the `.app` (bundled Python + app + a Tk
progress launcher), generates the icon, and packages a drag-to-Applications `.dmg`. ~50 MB.

## Windows — `Roo-Voice-Setup.exe`

For **NVIDIA** Windows machines. Build on a Windows box with [Inno Setup 6](https://jrsoftware.org/isdl.php):

```powershell
powershell -ExecutionPolicy Bypass -File installers\windows\build.ps1
# → installers\windows\dist\Roo-Voice-Setup.exe
```

`build.ps1` downloads a standalone Python (cached), stages the app, and compiles `roo-voice.iss`. The
installer drops into `%LOCALAPPDATA%\Roo Voice` (no admin), adds Start-Menu/Desktop shortcuts that run
`pythonw.exe bootstrap.py`, and cleanly uninstalls (including the per-user env + model cache).

## Icon

Both builds prefer a **square `assets/app-icon.png`** (1024×1024+). If absent they fall back to the
(landscape) cover art, which looks cropped — so add a square icon before shipping. The Windows `.ico`
is regenerated from the same source.

## What ships vs. downloads on first run

The installer bundles **Python + the app code + `reference.wav`** (small). The heavy, machine-specific
parts — the ML dependencies and the ~3.6–4.3 GB model — are fetched on **first launch**, so one small
installer works correctly on every supported machine. Requires internet on first run only.
