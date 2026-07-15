# Roo Voice — desktop installers

One-click installers that bundle a standalone Python so users need **nothing preinstalled**. On first
launch the app creates a private virtualenv, installs the right dependencies for the machine (MLX on
Apple Silicon, transformers + bitsandbytes on NVIDIA), downloads the model, then serves the UI and opens
the browser. Later launches are near-instant. Shared first-run logic lives in
[`common/bootstrap.py`](common/bootstrap.py).

> **Unsigned (for now).** These aren't code-signed/notarized yet, so the OS will warn on first launch:
> - **macOS:** right-click the app → **Open** → **Open** (or `xattr -dr com.apple.quarantine "/Applications/Roo Voice.app"`).
> - **Windows:** SmartScreen → **More info** → **Run anyway**.

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
