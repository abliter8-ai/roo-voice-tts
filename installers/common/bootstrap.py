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

ROO_VOICE_VERSION = "1.1.1"

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
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")


def _pick_port() -> int:
    """A port we can actually bind (IP-176.1 — ruinwork already ran node on 8080).

    Must test BOTH address families: ruinwork's node listens on IPv6 (::8080), and
    an IPv4-only check (the v1.1.0 first cut) wrongly saw 8080 as free and bound it
    on 127.0.0.1 — two servers on one port, split by family, and `localhost:8080`
    could resolve to either. A port counts as free only if it binds clean on IPv4
    *and* IPv6, and we do NOT set SO_REUSEADDR (that would mask a live listener).
    The launcher opens the browser to whatever we bound — the user never sees a port.
    """
    import socket
    if env := os.environ.get("ROO_PORT"):
        return int(env)

    def free(p: int) -> bool:
        for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                s = socket.socket(fam, socket.SOCK_STREAM)
            except OSError:
                continue  # family unsupported on this host — ignore it
            try:
                s.bind((addr, p))
            except OSError:
                s.close()
                return False
            s.close()
        return True

    for p in (8080, 8081, 8188, 8321, 8765, 8808):
        if free(p):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # let the OS choose
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _pick_port()

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

    # ---- download accounting ---------------------------------------------- #
    def cache_gb(self) -> float:
        """Symlink-SAFE size of the HF cache in GB.

        The HF cache stores each file once as a content-addressed blob, then
        builds snapshot dirs out of symlinks to those blobs. Counting both (the
        v1.1.0 bug) double-counts — 9.6 GB real showed as 19.1 GB. Skip symlinks.
        """
        try:
            total = 0
            for f in self.hf.rglob("*"):
                if f.is_symlink() or not f.is_file():
                    continue
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
            return total / 1e9
        except Exception:  # noqa: BLE001
            return 0.0

    # Rough full-download size per runtime (voice model + its audio codec), GB.
    DOWNLOAD_TARGET_GB = {"mlx": 9.5, "transformers": 10.5}

    # ---- server ----------------------------------------------------------- #
    def start_server(self, vpy: Path, set_status):
        # Baseline the cache so we measure THIS run's download, not absolute size
        # (a pre-cached machine must not show a phantom "downloading 90%").
        self.cache_baseline = self.cache_gb()
        self.download_target = self.DOWNLOAD_TARGET_GB.get(self.runtime, 9.5)
        if self.cache_baseline >= self.download_target * 0.9:
            set_status("Loading Roo's voice (already downloaded)…")
        else:
            set_status(f"Downloading Roo's voice — a {self.download_target:.0f} GB voice model "
                       "and audio codec, first run only. Several minutes on a home connection.")
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
    """Canvas-only launcher.

    IP-176.1 — macOS Tk renders native widgets (Button, OptionMenu) in default
    system chrome and ignores bg/fg, so v1.1.0 shipped a white dropdown and a grey
    Start button on a black theme. EVERYTHING here is drawn on the Canvas — buttons
    are rectangles + text + click bindings — so brand colours actually apply.

    It also AUTO-STARTS (auto-detect = the 4-bit default), so there is no dropdown
    and no Start click: launch → setup → the browser opens itself when ready, and a
    large "Open Roo Voice" button appears as a fallback. Manual runtime selection is
    via ROO_RUNTIME / ROO_MODEL for power users.
    """
    import tkinter as tk

    root = tk.Tk()
    root.title("Roo Voice")
    root.configure(bg=BLACK)
    W, H = 620, 440
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 3}")
    except Exception:  # noqa: BLE001
        root.geometry(f"{W}x{H}")
    root.resizable(False, False)

    display = _register_bundled_font()
    fam_display = display or ("Helvetica Neue" if IS_MAC else "Segoe UI")
    fam_sans = "Helvetica Neue" if IS_MAC else "Segoe UI"

    canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0, bg=BLACK)
    canvas.pack(fill="both", expand=True)

    bg_img = None
    bgp = APP_DIR / "assets" / "background-16x9.png"
    if bgp.is_file():
        try:
            src = tk.PhotoImage(file=str(bgp))
            factor = max(1, int(src.width() / W) or 1)
            bg_img = src.subsample(factor, factor)
            canvas.create_image(W // 2, H // 2, image=bg_img)
            canvas.create_rectangle(0, 0, W, H, fill=BLACK, stipple="gray75", outline="")
        except Exception:  # noqa: BLE001
            bg_img = None

    # Brand lockup: ● abliter8 · voice
    canvas.create_oval(46, 39, 54, 47, fill=RED, outline="")
    canvas.create_text(64, 43, anchor="w", text=_track("ABLITER8 · VOICE"),
                       fill=RED, font=(fam_sans, 10, "bold"))
    # Wordmark: ROO.VOICE, stop in red
    wm = 64
    canvas.create_text(W // 2 - 10, 108, text="ROO", anchor="e", fill="#ffffff",
                       font=(fam_display, wm))
    canvas.create_text(W // 2 - 9, 112, text=".", anchor="w", fill=RED, font=(fam_display, wm))
    canvas.create_text(W // 2 + 14, 108, text="VOICE", anchor="w", fill="#ffffff",
                       font=(fam_display, wm))
    canvas.create_text(W // 2, 152, text="the local voice of Roo", fill=MUTED,
                       font=(fam_sans, 11))

    # Card
    CT, CB = 182, H - 34
    canvas.create_rectangle(40, CT, W - 40, CB, fill=CARD, outline=LINE, width=1)

    phase_id = canvas.create_text(W // 2, CT + 26, text=_track("STARTING"), fill=RED,
                                  font=(fam_sans, 10, "bold"))
    status_id = canvas.create_text(W // 2, CT + 78, text="Preparing…", fill="#e9eaec",
                                   font=(fam_sans, 12), width=W - 130, justify="center")

    BX0, BX1, BY = 78, W - 78, CB - 96
    canvas.create_rectangle(BX0, BY, BX1, BY + 6, fill=LINE, outline="")
    bar_id = canvas.create_rectangle(BX0, BY, BX0, BY + 6, fill=RED, outline="")
    pct_id = canvas.create_text(W // 2, BY + 24, text="", fill=MUTED, font=(fam_sans, 9))

    state = {"L": None, "target": 0.0, "shown": 0.0, "running": True, "t0": time.time(),
             "phase": "starting"}

    # Phase -> bar floor. Download is the long pole; the watcher below fills it live.
    PHASES = [("environment", 0.05), ("installing pytorch", 0.14),
              ("installing dependencies", 0.30), ("downloading", 0.40),
              ("warming", 0.90)]

    def set_bar(frac: float):
        state["target"] = max(state["target"], min(frac, 1.0))

    def animate():
        if state["shown"] < state["target"]:
            state["shown"] += max(0.004, (state["target"] - state["shown"]) * 0.08)
            state["shown"] = min(state["shown"], state["target"])
        w = BX0 + (BX1 - BX0) * state["shown"]
        canvas.coords(bar_id, BX0, BY, w, BY + 6)
        if state["running"]:
            el = int(time.time() - state["t0"])
            canvas.itemconfig(pct_id, text=f"{int(state['shown']*100)}%   ·   {el//60}m {el%60:02d}s")
        root.after(33, animate)

    def set_status(msg: str):
        if state["L"]:
            state["L"].status = msg
        low = msg.lower()
        for key, frac in PHASES:
            if key in low:
                set_bar(frac)
                label = ("WARMING UP" if key == "warming" else
                         "DOWNLOADING" if key == "downloading" else key.upper())
                root.after(0, lambda t=label: canvas.itemconfig(phase_id, text=_track(t)))
                if key == "downloading":
                    state["phase"] = "downloading"
                elif key == "warming":
                    state["phase"] = "warming"
                break
        root.after(0, lambda: canvas.itemconfig(status_id, text=msg, fill="#e9eaec"))

    def watch_download():
        # Real byte-progress during the download phase — SYMLINK-SAFE (v1.1.0
        # counted HF's blobs and their snapshot symlinks, so 9.6 GB showed as
        # "19.1 GB of 9 GB"). Also skips cleanly when the model is already cached
        # (a pre-cached machine must not show a phantom download).
        L = state["L"]
        if L and getattr(L, "cache_baseline", None) is not None and not state.get("dl_done"):
            target = getattr(L, "download_target", 9.5)
            cached = L.cache_baseline >= target * 0.9
            gb = L.cache_gb()
            if cached:
                # Nothing to download — briefly show loading, let /healthz take over.
                set_bar(0.86)
                root.after(0, lambda: canvas.itemconfig(phase_id, text=_track("LOADING")))
                root.after(0, lambda: canvas.itemconfig(
                    status_id, text="Loading Roo's voice — already downloaded.", fill="#e9eaec"))
            elif state["phase"] in ("downloading", "starting"):
                frac = min(gb / target, 1.0)
                set_bar(0.40 + 0.48 * frac)
                root.after(0, lambda: canvas.itemconfig(phase_id, text=_track("DOWNLOADING")))
                root.after(0, lambda g=gb, t=target: canvas.itemconfig(
                    status_id, text=f"Downloading Roo's voice — {g:.1f} GB of ~{t:.0f} GB.\n"
                                    "First run only; several minutes on a home connection.",
                    fill="#e9eaec"))
            if state["phase"] in ("warming", "ready"):
                state["dl_done"] = True
        root.after(1500, watch_download)

    def rounded_button(cx, cy, text, cmd, primary=True, w=220, h=46):
        x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
        fill = RED if primary else CARD
        tag = f"btn{len(btn_tags)}"
        rect = canvas.create_rectangle(x0, y0, x1, y1, fill=fill,
                                       outline=RED if primary else "#3a3b40", width=1, tags=tag)
        txt = canvas.create_text(cx, cy, text=text, fill="#ffffff",
                                 font=(fam_display, 17) if display else (fam_sans, 13, "bold"),
                                 tags=tag)
        def enter(_): canvas.itemconfig(rect, fill="#c60830" if primary else LINE); canvas.config(cursor="hand2")
        def leave(_): canvas.itemconfig(rect, fill=fill); canvas.config(cursor="")
        canvas.tag_bind(tag, "<Enter>", enter)
        canvas.tag_bind(tag, "<Leave>", leave)
        canvas.tag_bind(tag, "<Button-1>", lambda _: cmd())
        btn_tags.append((rect, txt))
        return tag

    btn_tags: list = []

    def clear_buttons():
        for rect, txt in btn_tags:
            canvas.delete(rect); canvas.delete(txt)
        btn_tags.clear()

    def on_ready(url):
        def apply():
            state["running"] = False
            set_bar(1.0)
            canvas.itemconfig(phase_id, text=_track("READY"), fill="#3ddc84")
            canvas.itemconfig(status_id, text=state["L"].settled_estimate() +
                              "\nYour browser should have opened. If not, click below.",
                              fill="#e9eaec")
            canvas.itemconfig(pct_id, text="")
            clear_buttons()
            rounded_button(W // 2 - 118, BY + 48, "Open Roo Voice", lambda: webbrowser.open(url), primary=True)
            rounded_button(W // 2 + 118, BY + 48, "Save report", save_report, primary=False, w=180)
        root.after(0, apply)
        webbrowser.open(url)   # open for the user; the button is a fallback

    def on_fail(msg):
        def apply():
            state["running"] = False
            canvas.itemconfig(phase_id, text=_track("PROBLEM"), fill="#ff6b6b")
            canvas.itemconfig(status_id, text=msg, fill="#ff9a9a")
            canvas.itemconfig(pct_id, text="")
            clear_buttons()
            rounded_button(W // 2, BY + 48, "Save diagnostics report", save_report, primary=True, w=260)
        root.after(0, apply)

    def save_report():
        L = state["L"]
        if not L:
            return
        try:
            p = L.write_report()
            canvas.itemconfig(status_id, text=f"Report saved to your Desktop:\n{p.name}\n"
                                              "Send that file to David.", fill="#e9eaec")
            if IS_MAC:
                subprocess.run(["open", "-R", str(p)], check=False)
            elif IS_WIN:
                subprocess.run(["explorer", "/select,", str(p)], check=False)
        except Exception as e:  # noqa: BLE001
            canvas.itemconfig(status_id, text=f"Could not write the report: {e}", fill="#ff9a9a")

    def on_close():
        L = state["L"]
        if L:
            canvas.itemconfig(status_id, text="Stopping…", fill="#e9eaec")
            threading.Thread(target=lambda: (L.stop(), root.after(0, root.destroy)),
                             daemon=True).start()
        else:
            root.destroy()

    # ---- auto-start: no dropdown, no Start click ----
    L = Launcher()                      # auto-detect (4-bit default)
    state["L"] = L
    canvas.itemconfig(status_id, text=f"Setting up the {L.runtime.upper()} voice for your machine…")
    threading.Thread(target=L.setup_and_launch,
                     args=(set_status, on_ready, on_fail), daemon=True).start()

    root.protocol("WM_DELETE_WINDOW", on_close)
    animate()
    watch_download()
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
