#!/usr/bin/env python3
"""Roo Voice launcher / first-run bootstrap (shared by the Mac + Windows installers).

Runs under the *bundled* Python that the installer ships. On first launch it
creates a user-data virtualenv, installs the right dependencies for this machine
(MLX on Apple Silicon, transformers+CUDA torch on NVIDIA), then starts the Roo
Voice server (which downloads the model and warms it up) and opens the browser.

IP-176:
  * 4-bit builds (mlx4 / int4) are the default on every platform.
  * torch comes from the PyTorch CUDA index, never PyPI (PyPI's Windows wheel is
    CPU-only) — and we assert CUDA is real before continuing.
  * The venv is health-CHECKED, not existence-checked, so a moved/updated/
    translocated app rebuilds instead of silently reinstalling every launch.
  * The UI matches web/index.html and shows phased progress with honest ETAs.
  * Everything is logged; one button writes a redacted diagnostics report.

Environment overrides: ROO_PORT, ROO_MODEL, ROO_RUNTIME, ROO_DATA_DIR, ROO_APP_DIR.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROO_VOICE_VERSION = "1.1.0"

CUDA_INDEX = "https://download.pytorch.org/whl/cu128"


def _find_app_dir() -> Path:
    if env := os.environ.get("ROO_APP_DIR"):
        return Path(env)
    here = Path(__file__).resolve()
    for cand in (here.parents[2], here.parents[1], here.parents[0]):
        if (cand / "server" / "roo_serve.py").exists():
            return cand
    return here.parents[1]


APP_DIR = _find_app_dir()
PORT = int(os.environ.get("ROO_PORT", "8080"))
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

# Brand tokens — lifted from web/index.html so the launcher and the web UI match.
RED = "#FF093A"
BLACK = "#000000"
INK = "#0a0a0b"
LINE = "#1b1c1f"
MUTED = "#8b8f96"
CARD = "#08080a"


def data_dir() -> Path:
    if override := os.environ.get("ROO_DATA_DIR"):
        return Path(override)
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Roo Voice"
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roo Voice"
    return Path.home() / ".local" / "share" / "roo-voice"


def is_translocated() -> bool:
    """macOS runs quarantined apps from a random read-only mount (IP-176 RC4)."""
    return "/AppTranslocation/" in str(APP_DIR)


def pick_runtime() -> tuple[str, str, str]:
    """(runtime, model_repo, requirements_file) for this machine. 4-bit everywhere."""
    if os.environ.get("ROO_RUNTIME") and os.environ.get("ROO_MODEL"):
        rt = os.environ["ROO_RUNTIME"]
        req = "requirements-mlx.txt" if rt == "mlx" else "requirements-cuda.txt"
        return rt, os.environ["ROO_MODEL"], req
    if IS_MAC and platform.machine() in ("arm64", "aarch64"):
        return "mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4", "requirements-mlx.txt"
    return "transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4", "requirements-cuda.txt"


_MLX = "requirements-mlx.txt"
_CUDA = "requirements-cuda.txt"
RUNTIME_CHOICES = [
    ("Auto-detect (recommended)", None),
    ("Apple Silicon · MLX 4-bit — default", ("mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4", _MLX)),
    ("Apple Silicon · MLX 8-bit — more headroom", ("mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8", _MLX)),
    ("NVIDIA · INT4 (NF4) — default", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4", _CUDA)),
    ("NVIDIA · INT8 — more headroom", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8", _CUDA)),
    ("NVIDIA · BF16 — full precision", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16", _CUDA)),
]

# Measured on the fleet 2026-07-17 (IP-176 §2.1). Honest, per-machine, not a global constant.
WARMUP_HINT_MAC = ("Warming up — the first run compiles GPU kernels for your Mac.\n"
                   "Up to ~7 minutes on a MacBook Air, ~1 minute on a Mac Studio.\n"
                   "This happens once.")
WARMUP_HINT_NV = ("Warming up — the first run compiles CUDA kernels.\n"
                  "Usually well under a minute. This happens once.")


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


class SetupError(RuntimeError):
    """Actionable failure — the message is shown to the user verbatim."""


class Launcher:
    def __init__(self, choice: tuple[str, str, str] | None = None):
        self.data = data_dir()
        self.venv = self.data / "env"
        self.hf = self.data / "hf-cache"
        self.logs = self.data / "logs"
        self.runtime, self.model, self.req = choice if choice else pick_runtime()
        self.proc: subprocess.Popen | None = None
        self.status = "Starting…"
        self.install_log = self.logs / "install.log"
        self.server_log = self.logs / "server.log"

    # ---- helpers ---------------------------------------------------------- #
    def _env(self) -> dict:
        return dict(os.environ, HF_HOME=str(self.hf), PYTHONUNBUFFERED="1")

    def _run(self, args, step: str) -> subprocess.CompletedProcess:
        """Run a child, capturing output to the install log (IP-176 D13)."""
        creationflags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
        p = subprocess.run(args, env=self._env(), creationflags=creationflags,
                           capture_output=True, text=True)
        with open(self.install_log, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"\n===== {step} =====\n$ {' '.join(str(a) for a in args)}\n")
            fh.write(p.stdout or "")
            fh.write(p.stderr or "")
            fh.write(f"\n-> exit {p.returncode}\n")
        if p.returncode != 0:
            tail = "\n".join(((p.stderr or p.stdout or "").strip().splitlines() or ["(no output)"])[-4:])
            raise SetupError(f"{step} failed.\n\n{tail}\n\nFull log: {self.install_log}")
        return p

    # ---- venv health ------------------------------------------------------ #
    def _venv_ok(self, vpy: Path) -> bool:
        """Health-check, not exists() (IP-176 D11).

        The venv symlinks its interpreter at the app bundle. If the app moved,
        updated, or is running translocated, that symlink is dead — and
        Path.exists() on a dangling symlink returns False, which used to trigger
        a full silent dependency reinstall on every launch.
        """
        marker = self.venv / ".roo-ok"
        if not marker.exists():
            return False
        try:
            info = json.loads(marker.read_text())
        except Exception:  # noqa: BLE001
            return False
        if info.get("version") != ROO_VOICE_VERSION or info.get("req") != self.req:
            return False
        try:
            r = subprocess.run([str(vpy), "-c", "import sys; print(sys.prefix)"],
                               capture_output=True, text=True, timeout=30)
            return r.returncode == 0
        except Exception:  # noqa: BLE001
            return False

    def ensure_env(self, set_status):
        for d in (self.data, self.hf, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        vpy = venv_python(self.venv)
        if self._venv_ok(vpy):
            return vpy

        set_status("Creating environment (first run only)…")
        if self.venv.exists():
            # Rebuild rather than reuse a venv pointing at a stale interpreter.
            shutil.rmtree(self.venv, ignore_errors=True)
        self._run([sys.executable, "-m", "venv", str(self.venv)], "create venv")
        self._run([str(vpy), "-m", "pip", "install", "-q", "--upgrade", "pip"], "upgrade pip")

        if self.runtime == "transformers":
            # IP-176 RC2 — torch from the CUDA index, NEVER PyPI.
            set_status("Installing PyTorch with CUDA — 2.5 GB, a few minutes…")
            self._run([str(vpy), "-m", "pip", "install", "-q", "torch", "torchaudio",
                       "--index-url", CUDA_INDEX], "install torch (cu128)")

        set_status("Installing dependencies — 1–3 min, first run only…")
        self._run([str(vpy), "-m", "pip", "install", "-q", "-r",
                   str(APP_DIR / "server" / self.req)], "install requirements")

        if self.runtime == "transformers":
            self._assert_cuda(vpy)

        (self.venv / ".roo-ok").write_text(json.dumps(
            {"version": ROO_VOICE_VERSION, "req": self.req, "python": str(sys.executable)}))
        return vpy

    def _assert_cuda(self, vpy: Path):
        """Prove we got a real CUDA torch, not the 122 MB CPU-only wheel."""
        r = subprocess.run(
            [str(vpy), "-c",
             "import torch,json;print(json.dumps({'v':torch.__version__,"
             "'cuda':torch.version.cuda,'avail':torch.cuda.is_available()}))"],
            capture_output=True, text=True)
        try:
            info = json.loads((r.stdout or "").strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            raise SetupError(f"Could not verify the PyTorch install.\n\n{r.stderr}\n\n"
                             f"Full log: {self.install_log}") from None
        with open(self.install_log, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== torch check =====\n{info}\n")
        if not info.get("cuda"):
            raise SetupError(
                "A CPU-only PyTorch was installed — Roo Voice needs the CUDA build.\n\n"
                f"  torch {info.get('v')}  ·  CUDA build: {info.get('cuda')}\n\n"
                "Fix it with:\n"
                f"  pip install --force-reinstall torch torchaudio --index-url {CUDA_INDEX}")
        if not info.get("avail"):
            raise SetupError(
                "PyTorch has CUDA support but cannot see your GPU.\n\n"
                f"  torch {info.get('v')} (CUDA {info.get('cuda')})\n\n"
                "Check that an NVIDIA driver is installed and `nvidia-smi` works,\n"
                "then restart Roo Voice.")

    # ---- server ----------------------------------------------------------- #
    def start_server(self, vpy: Path, set_status):
        set_status("Downloading Roo's voice — 2.3 GB, 1–5 min, first run only…")
        creationflags = 0x08000000 if IS_WIN else 0
        self._server_fh = open(self.server_log, "a", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(vpy), str(APP_DIR / "server" / "roo_serve.py"),
             "--runtime", self.runtime, "--model", self.model,
             "--reference", str(APP_DIR / "reference.wav"),
             "--log-dir", str(self.logs),
             "--host", "127.0.0.1", "--port", str(PORT)],
            env=self._env(), creationflags=creationflags,
            stdout=self._server_fh, stderr=subprocess.STDOUT)

    def _health(self) -> dict | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            return None

    def wait_ready(self, set_status, timeout=2400) -> bool:
        """Distinguish died / downloading / warming / ready (IP-176 D15)."""
        t0 = time.time()
        phase_seen = None
        while time.time() - t0 < timeout:
            if self.proc and self.proc.poll() is not None:
                raise SetupError(self._server_died_message())
            h = self._health()
            if h:
                if h.get("ready"):
                    return True
                if h.get("phase") == "failed":
                    raise SetupError(f"The voice failed to load.\n\n{h.get('error')}\n\n"
                                     f"Full log: {self.logs / 'roo-voice.log'}")
                if h.get("phase") != phase_seen:
                    phase_seen = h.get("phase")
                    if phase_seen == "warming":
                        set_status(WARMUP_HINT_MAC if self.runtime == "mlx" else WARMUP_HINT_NV)
            time.sleep(2)
        raise SetupError(f"Timed out after {timeout // 60} minutes.\n\n"
                         f"Full log: {self.logs / 'roo-voice.log'}")

    def _server_died_message(self) -> str:
        tail = ""
        try:
            lines = self.server_log.read_text(errors="replace").strip().splitlines()
            tail = "\n".join(lines[-8:])
        except Exception:  # noqa: BLE001
            pass
        return f"The voice server stopped unexpectedly.\n\n{tail}\n\nFull log: {self.server_log}"

    def settled_estimate(self) -> str:
        """Per-machine ready-state hint.

        Prefer REAL observed generations; only fall back to extrapolating from
        this machine's warm-up when nothing has been generated yet.

        The fallback is calibrated against two measured anchors (IP-176 §2.1):
          ruin-max  M1 Max : warm-up  24.3s -> ~10.5s/sentence
          ruin-air  M4 Air : warm-up 267.9s -> ~55.0s/sentence
        A flat multiplier does not fit both (the ratio is 0.43 vs 0.21), so use
        the line through them. An earlier flat-0.45 version predicted ~121s on
        the Air against a real ~55s — wrong on exactly the hardware this hint
        exists to be honest about.
        """
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/diagnostics", timeout=3) as r:
                diag = json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            diag = {}
        gens = [g for g in diag.get("recent_generations", []) if g.get("gen_seconds")]
        if gens:                       # measured on THIS machine — no extrapolation
            est = round(sum(g["gen_seconds"] for g in gens) / len(gens))
            return f"Ready — a sentence takes about {est}s on this machine."
        w = (diag.get("state") or {}).get("warmup_seconds")
        if not w:
            return "Ready — Roo Voice is open in your browser."
        est = max(8, round(6.0 + 0.183 * float(w)))
        return f"Ready — a sentence takes roughly {est}s on this machine."

    def setup_and_launch(self, set_status, on_ready, on_fail):
        try:
            if is_translocated():
                raise SetupError(
                    "macOS is running Roo Voice from a temporary read-only copy.\n\n"
                    "Drag Roo Voice into your Applications folder and open it from "
                    "there — don't run it from the disk image.")
            vpy = self.ensure_env(set_status)
            self.start_server(vpy, set_status)
            self.wait_ready(set_status)
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
            on_ready(f"http://127.0.0.1:{PORT}/")
        except SetupError as e:
            on_fail(str(e))
        except Exception as e:  # noqa: BLE001
            on_fail(f"{type(e).__name__}: {e}\n\nFull log: {self.install_log}")

    # ---- diagnostics report ----------------------------------------------- #
    def write_report(self) -> Path:
        """One redacted file the user can send back (IP-176 D14)."""
        out = Path.home() / "Desktop" / "roo-voice-report.txt"
        if not out.parent.is_dir():
            out = self.logs / "roo-voice-report.txt"
        parts = [f"Roo Voice diagnostics report",
                 f"version : {ROO_VOICE_VERSION}",
                 f"when    : {time.strftime('%Y-%m-%d %H:%M:%S')}",
                 f"platform: {platform.platform()} / {platform.machine()}",
                 f"python  : {sys.version.split()[0]}",
                 f"runtime : {self.runtime}",
                 f"model   : {self.model}",
                 f"app dir : {APP_DIR}",
                 f"translocated: {is_translocated()}", ""]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/diagnostics", timeout=3) as r:
                parts += ["===== /diagnostics =====",
                          json.dumps(json.loads(r.read().decode()), indent=2), ""]
        except Exception as e:  # noqa: BLE001
            parts += [f"===== /diagnostics unavailable: {e} =====", ""]
        for name, p in (("install.log", self.install_log),
                        ("server.log", self.server_log),
                        ("roo-voice.log", self.logs / "roo-voice.log")):
            parts.append(f"===== {name} (tail) =====")
            try:
                parts.append("\n".join(p.read_text(errors="replace").splitlines()[-120:]))
            except Exception as e:  # noqa: BLE001
                parts.append(f"(unavailable: {e})")
            parts.append("")
        text = "\n".join(parts)
        # Redact: home directory -> ~, and anything that smells like a token.
        text = text.replace(str(Path.home()), "~")
        import re
        text = re.sub(r"(hf_|sk-|ghp_)[A-Za-z0-9]{8,}", r"\1<redacted>", text)
        out.write_text(text, encoding="utf-8")
        return out

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        fh = getattr(self, "_server_fh", None)
        if fh and not fh.closed:
            fh.close()


# --------------------------------------------------------------------------- #
# GUI — matches web/index.html (IP-176 §6.1)
# --------------------------------------------------------------------------- #


def _register_bundled_font() -> str | None:
    """Register assets/BebasNeue-Regular.ttf with the OS so Tk can use it."""
    ttf = APP_DIR / "assets" / "BebasNeue-Regular.ttf"
    if not ttf.is_file():
        return None
    try:
        import ctypes
        if IS_MAC:
            from ctypes import util as cu
            ct = ctypes.CDLL(cu.find_library("CoreText"))
            cf = ctypes.CDLL(cu.find_library("CoreFoundation"))
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
            cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                         ctypes.c_long, ctypes.c_bool]
            s = cf.CFStringCreateWithCString(None, str(ttf).encode(), 0x08000100)
            url = cf.CFURLCreateWithFileSystemPath(None, s, 0, False)
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                            ctypes.c_void_p]
            if ct.CTFontManagerRegisterFontsForURL(url, 1, None):   # 1 = process scope
                return "Bebas Neue"
        elif IS_WIN:
            FR_PRIVATE = 0x10
            if ctypes.windll.gdi32.AddFontResourceExW(str(ttf), FR_PRIVATE, 0):
                return "Bebas Neue"
    except Exception:  # noqa: BLE001
        pass
    return None


def _track(s: str, spaces: int = 1) -> str:
    """Tk has no letter-spacing; fake the web UI's tracking with thin spaces."""
    return (" " * spaces).join(list(s))


def gui_main():
    import tkinter as tk

    root = tk.Tk()
    root.title("Roo Voice")
    root.configure(bg=BLACK)
    W, H = 560, 460
    root.geometry(f"{W}x{H}")
    root.resizable(False, False)

    display = _register_bundled_font()
    fam_display = display or ("Helvetica Neue" if IS_MAC else "Segoe UI")
    fam_sans = "Helvetica Neue" if IS_MAC else "Segoe UI"

    canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0, bg=BLACK)
    canvas.pack(fill="both", expand=True)

    # Background image + scrim (Tk 9 reads PNG natively).
    bg_img = None
    bgp = APP_DIR / "assets" / "background-16x9.png"
    if bgp.is_file():
        try:
            src = tk.PhotoImage(file=str(bgp))
            factor = max(1, int(src.width() / W) or 1)
            bg_img = src.subsample(factor, factor)
            canvas.create_image(W // 2, H // 2, image=bg_img)
        except Exception:  # noqa: BLE001
            bg_img = None
    canvas.create_rectangle(0, 0, W, H, fill=BLACK, stipple="gray50", outline="")

    # Brand lockup: ● abliter8 · voice
    canvas.create_oval(40, 33, 47, 40, fill=RED, outline="")
    canvas.create_text(56, 36, anchor="w", text=_track("ABLITER8 · VOICE"),
                       fill=RED, font=(fam_sans, 9, "bold"))
    # Wordmark: ROO.VOICE with the stop in red
    canvas.create_text(W // 2 - 8, 92, text="ROO", anchor="e",
                       fill="#ffffff", font=(fam_display, 54))
    canvas.create_text(W // 2 - 6, 92, text=".", anchor="w",
                       fill=RED, font=(fam_display, 54))
    canvas.create_text(W // 2 + 8, 92, text="VOICE", anchor="w",
                       fill="#ffffff", font=(fam_display, 54))

    # Card
    canvas.create_rectangle(34, 140, W - 34, H - 74, fill=CARD, outline=LINE)

    status_id = canvas.create_text(W // 2, 250, text="", fill="#ffffff",
                                   font=(fam_sans, 11), width=W - 110, justify="center")
    phase_id = canvas.create_text(W // 2, 174, text="", fill=MUTED, font=(fam_sans, 9))

    # Determinate progress bar, drawn by hand in brand colours
    BX0, BX1, BY = 70, W - 70, 320
    canvas.create_rectangle(BX0, BY, BX1, BY + 5, fill=LINE, outline="")
    bar_id = canvas.create_rectangle(BX0, BY, BX0, BY + 5, fill=RED, outline="")
    pct_id = canvas.create_text(W // 2, BY + 24, text="", fill=MUTED, font=(fam_sans, 9))

    state = {"L": None, "target": 0.0, "shown": 0.0, "running": False, "t0": time.time()}

    PHASES = [("Environment", 0.06), ("Dependencies", 0.34),
              ("Downloading the voice", 0.62), ("Warming up", 0.97)]

    def set_bar(frac: float):
        state["target"] = max(state["target"], min(frac, 1.0))

    def animate():
        if state["shown"] < state["target"]:
            state["shown"] += min(0.012, state["target"] - state["shown"])
        w = BX0 + (BX1 - BX0) * state["shown"]
        canvas.coords(bar_id, BX0, BY, w, BY + 5)
        if state["running"]:
            el = int(time.time() - state["t0"])
            canvas.itemconfig(pct_id, text=f"{int(state['shown']*100)}%   ·   {el//60}m {el%60}s elapsed")
        root.after(40, animate)

    def set_status(msg: str):
        if state["L"]:
            state["L"].status = msg
        low = msg.lower()
        for name, frac in PHASES:
            if name.lower().split()[0] in low:
                set_bar(frac)
                root.after(0, lambda n=name: canvas.itemconfig(phase_id, text=_track(n.upper())))
                break
        root.after(0, lambda: canvas.itemconfig(status_id, text=msg))

    widgets: list = []

    def clear_widgets():
        for w in widgets:
            w.destroy()
        widgets.clear()

    def brand_button(text, cmd, x, y, primary=True):
        b = tk.Button(root, text=text, command=cmd,
                      bg=RED if primary else CARD, fg="#ffffff",
                      activebackground="#c60830" if primary else LINE,
                      activeforeground="#ffffff",
                      relief="flat", bd=0, highlightthickness=0,
                      font=(fam_display, 15) if display else (fam_sans, 11, "bold"),
                      padx=22, pady=7, cursor="hand2")
        w = canvas.create_window(x, y, window=b)
        widgets.append(b)
        return b, w

    def on_ready(url):
        def apply():
            state["running"] = False
            set_bar(1.0)
            canvas.itemconfig(phase_id, text=_track("READY"))
            canvas.itemconfig(status_id, text=state["L"].settled_estimate())
            canvas.itemconfig(pct_id, text="")
            clear_widgets()
            brand_button("Open Roo Voice", lambda: webbrowser.open(url), W // 2 - 78, H - 42)
            brand_button("Save report", save_report, W // 2 + 84, H - 42, primary=False)
        root.after(0, apply)

    def on_fail(msg):
        def apply():
            state["running"] = False
            canvas.itemconfig(phase_id, text=_track("PROBLEM"))
            canvas.itemconfig(status_id, text=msg, fill="#ff6b6b")
            canvas.itemconfig(pct_id, text="")
            canvas.coords(bar_id, BX0, BY, BX0, BY + 5)
            clear_widgets()
            # On failure the report button is the point of the whole screen.
            brand_button("Save diagnostics report", save_report, W // 2, H - 42)
        root.after(0, apply)

    def save_report():
        L = state["L"]
        if not L:
            return
        try:
            p = L.write_report()
            canvas.itemconfig(status_id, text=f"Report saved to:\n{p}\n\nSend that file to David.",
                              fill="#ffffff")
            if IS_MAC:
                subprocess.run(["open", "-R", str(p)], check=False)
            elif IS_WIN:
                subprocess.run(["explorer", "/select,", str(p)], check=False)
        except Exception as e:  # noqa: BLE001
            canvas.itemconfig(status_id, text=f"Could not write the report: {e}", fill="#ff6b6b")

    # ---- selector screen ----
    sel_label = canvas.create_text(W // 2, 176, text=_track("CHOOSE YOUR RUNTIME"),
                                   fill="#ffffff", font=(fam_sans, 9, "bold"))
    var = tk.StringVar(value=RUNTIME_CHOICES[0][0])
    om = tk.OptionMenu(root, var, *[c[0] for c in RUNTIME_CHOICES])
    om.configure(bg=CARD, fg="#ffffff", activebackground=LINE, activeforeground="#fff",
                 relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                 font=(fam_sans, 11), width=34, cursor="hand2")
    om["menu"].configure(bg=CARD, fg="#ffffff", activebackground=RED, font=(fam_sans, 11))
    om_win = canvas.create_window(W // 2, 210, window=om)
    hint_id = canvas.create_text(W // 2, 248,
                                 text="Auto-detect picks the 4-bit build for your machine.\n"
                                      "Choose manually only if you know your hardware.",
                                 fill=MUTED, font=(fam_sans, 9), justify="center")

    def start():
        label = var.get()
        choice = dict(RUNTIME_CHOICES)[label]
        L = Launcher(choice)
        state["L"] = L
        state["running"] = True
        state["t0"] = time.time()
        canvas.delete(sel_label); canvas.delete(hint_id)
        canvas.delete(om_win); om.destroy()
        clear_widgets()
        canvas.itemconfig(status_id, text="Starting…")
        threading.Thread(target=L.setup_and_launch,
                         args=(set_status, on_ready, on_fail), daemon=True).start()

    brand_button("Start", start, W // 2, H - 42)

    def on_close():
        L = state["L"]
        if L:
            canvas.itemconfig(status_id, text="Stopping…")
            threading.Thread(target=lambda: (L.stop(), root.after(0, root.destroy)),
                             daemon=True).start()
        else:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    animate()
    root.mainloop()


def headless_main():
    L = Launcher()
    print(f"[roo] Roo Voice {ROO_VOICE_VERSION}")
    print(f"[roo] runtime={L.runtime} model={L.model} data={L.data}")
    done = {"ok": False}
    L.setup_and_launch(lambda m: print("[roo]", m.replace("\n", " ")),
                       lambda u: (print("[roo] ready:", u), print("[roo]", L.settled_estimate()),
                                  done.__setitem__("ok", True)),
                       lambda m: print("[roo] FAILED:", m, file=sys.stderr))
    if not done["ok"]:
        try:
            print(f"[roo] diagnostics report: {L.write_report()}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
    if L.proc:
        try:
            L.proc.wait()
        except KeyboardInterrupt:
            L.stop()


if __name__ == "__main__":
    if "--headless" in sys.argv or os.environ.get("ROO_HEADLESS"):
        headless_main()
    else:
        try:
            gui_main()
        except Exception:  # no display / tkinter missing → headless
            headless_main()
