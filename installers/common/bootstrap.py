#!/usr/bin/env python3
"""Roo Voice launcher / first-run bootstrap (shared by the Mac + Windows installers).

Runs under the *bundled* Python that the installer ships. On first launch it
creates a user-data virtualenv, installs the right dependencies for this machine
(MLX on Apple Silicon, transformers+bitsandbytes on NVIDIA), then starts the Roo
Voice server (which downloads the model on first load) and opens the browser.
A small always-visible window shows progress and lets the user quit (which stops
the server). Later launches skip straight to starting the server.

Environment overrides: ROO_PORT, ROO_MODEL, ROO_RUNTIME, ROO_DATA_DIR.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

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


def data_dir() -> Path:
    if override := os.environ.get("ROO_DATA_DIR"):
        return Path(override)
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Roo Voice"
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roo Voice"
    return Path.home() / ".local" / "share" / "roo-voice"


def pick_runtime() -> tuple[str, str, str]:
    """(runtime, model_repo, requirements_file) for this machine."""
    if os.environ.get("ROO_RUNTIME") and os.environ.get("ROO_MODEL"):
        rt = os.environ["ROO_RUNTIME"]
        req = "requirements-mlx.txt" if rt == "mlx" else "requirements-cuda.txt"
        return rt, os.environ["ROO_MODEL"], req
    if IS_MAC and platform.machine() in ("arm64", "aarch64"):
        return "mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4", "requirements-mlx.txt"
    # Windows / Linux: assume NVIDIA GPU, NF4 4-bit (smallest bnb build).
    return "transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4", "requirements-cuda.txt"


# User-selectable runtime configs (label -> (runtime, model_repo, requirements) | None=auto).
# Only the runtimes this app can serve directly (MLX on Apple, transformers on NVIDIA).
# GGUF / ONNX are documented manual paths (llama.cpp / onnxruntime), not auto-served here.
_MLX = "requirements-mlx.txt"
_CUDA = "requirements-cuda.txt"
RUNTIME_CHOICES = [
    ("Auto-detect (recommended)", None),
    ("Apple Silicon · MLX 4-bit — smallest", ("mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4", _MLX)),
    ("Apple Silicon · MLX 8-bit — more headroom", ("mlx", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8", _MLX)),
    ("NVIDIA · INT4 (NF4) — smallest", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4", _CUDA)),
    ("NVIDIA · INT8 — more headroom", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8", _CUDA)),
    ("NVIDIA · BF16 — full precision", ("transformers", "abliter8-ai/Roo-Voice_MOSS_TTS_LT_bf16", _CUDA)),
]


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


class Launcher:
    def __init__(self, choice: tuple[str, str, str] | None = None):
        self.data = data_dir()
        self.venv = self.data / "env"
        self.hf = self.data / "hf-cache"
        self.runtime, self.model, self.req = choice if choice else pick_runtime()
        self.proc: subprocess.Popen | None = None
        self.status = "Starting…"

    # ---- setup steps (run on a worker thread) ----------------------------- #
    def _run(self, args, **kw):
        env = dict(os.environ, HF_HOME=str(self.hf), PYTHONUNBUFFERED="1")
        creationflags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
        return subprocess.run(args, env=env, creationflags=creationflags, **kw)

    def ensure_env(self, set_status):
        self.data.mkdir(parents=True, exist_ok=True)
        self.hf.mkdir(parents=True, exist_ok=True)
        vpy = venv_python(self.venv)
        marker = self.venv / ".deps-ok"
        if vpy.exists() and marker.exists():
            return vpy
        set_status("Creating environment (first run only)…")
        if not vpy.exists():
            self._run([sys.executable, "-m", "venv", str(self.venv)], check=True)
        set_status("Installing dependencies — this can take a few minutes…")
        self._run([str(vpy), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        self._run([str(vpy), "-m", "pip", "install", "-q", "-r",
                   str(APP_DIR / "server" / self.req)], check=True)
        marker.write_text("ok")
        return vpy

    def start_server(self, vpy: Path, set_status):
        set_status("Loading the Roo voice (first run also downloads the model)…")
        env = dict(os.environ, HF_HOME=str(self.hf), PYTHONUNBUFFERED="1")
        creationflags = 0x08000000 if IS_WIN else 0
        self.proc = subprocess.Popen(
            [str(vpy), str(APP_DIR / "server" / "roo_serve.py"),
             "--runtime", self.runtime, "--model", self.model,
             "--reference", str(APP_DIR / "reference.wav"),
             "--host", "127.0.0.1", "--port", str(PORT)],
            env=env, creationflags=creationflags)

    def wait_ready(self, set_status, timeout=1800) -> bool:
        url = f"http://127.0.0.1:{PORT}/healthz"
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc and self.proc.poll() is not None:
                return False  # server died
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def setup_and_launch(self, set_status, on_ready, on_fail):
        try:
            vpy = self.ensure_env(set_status)
            self.start_server(vpy, set_status)
            if self.wait_ready(set_status):
                webbrowser.open(f"http://127.0.0.1:{PORT}/")
                on_ready(f"http://127.0.0.1:{PORT}/")
            else:
                on_fail("The server did not start. See the log window / try again.")
        except subprocess.CalledProcessError as e:
            on_fail(f"Setup failed (exit {e.returncode}). Check your internet connection.")
        except Exception as e:  # noqa: BLE001
            on_fail(f"{type(e).__name__}: {e}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except Exception:
                self.proc.kill()


def gui_main():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Roo Voice")
    root.configure(bg="#000000")
    root.geometry("470x320")
    RED = "#FF093A"
    tk.Label(root, text="ROO VOICE", fg=RED, bg="#000000",
             font=("Helvetica", 26, "bold")).pack(pady=(24, 2))
    tk.Label(root, text="the local voice of Roo", fg="#8a8f96", bg="#000000",
             font=("Helvetica", 11)).pack()

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
        style.configure("R.Horizontal.TProgressbar", background=RED, troughcolor="#1b1c1f")
    except Exception:
        pass

    # ---- runtime selector (shown first) ----
    sel = tk.Frame(root, bg="#000000")
    sel.pack(pady=(20, 4))
    tk.Label(sel, text="Runtime", fg="#ffffff", bg="#000000",
             font=("Helvetica", 11, "bold")).pack(anchor="w")
    combo = ttk.Combobox(sel, values=[c[0] for c in RUNTIME_CHOICES],
                         state="readonly", width=40)
    combo.current(0)
    combo.pack(pady=(3, 3))
    tk.Label(sel, text="Auto-detect picks the right build for your machine.\n"
                       "Choose manually only if you know your hardware.",
             fg="#6a6f76", bg="#000000", font=("Helvetica", 9), justify="left").pack(anchor="w")

    status = tk.Label(root, text="", fg="#ffffff", bg="#000000",
                      font=("Helvetica", 12), wraplength=420, justify="center")
    bar = ttk.Progressbar(root, mode="indeterminate", length=350,
                          style="R.Horizontal.TProgressbar")
    state = {"L": None}

    def set_status(msg):
        if state["L"]:
            state["L"].status = msg
        root.after(0, lambda: status.config(text=msg))

    def on_ready(url):
        def apply():
            bar.stop(); bar.pack_forget()
            status.config(text="Running — Roo Voice opened in your browser.")
            tk.Button(root, text="Open Roo Voice", command=lambda: webbrowser.open(url),
                      bg=RED, fg="#ffffff", relief="flat", font=("Helvetica", 12, "bold"),
                      padx=16, pady=6, activebackground="#c60830", activeforeground="#fff").pack(pady=6)
        root.after(0, apply)

    def on_fail(msg):
        def apply():
            bar.stop(); bar.pack_forget()
            status.config(text=msg, fg="#ff6b6b")
        root.after(0, apply)

    def start():
        choice = RUNTIME_CHOICES[combo.current()][1]
        L = Launcher(choice); state["L"] = L
        sel.pack_forget(); start_btn.pack_forget()
        tk.Label(root, text=f"{L.runtime.upper()} · one-time setup", fg="#8a8f96",
                 bg="#000000", font=("Helvetica", 10)).pack()
        status.pack(pady=12); bar.pack(pady=4); bar.start(14)
        threading.Thread(target=L.setup_and_launch,
                         args=(set_status, on_ready, on_fail), daemon=True).start()

    start_btn = tk.Button(root, text="Start", command=start, bg=RED, fg="#ffffff",
                          relief="flat", font=("Helvetica", 12, "bold"), padx=28, pady=6,
                          activebackground="#c60830", activeforeground="#fff")
    start_btn.pack(pady=12)

    def on_close():
        L = state["L"]
        if L:
            set_status("Stopping…")
            threading.Thread(target=lambda: (L.stop(), root.after(0, root.destroy)), daemon=True).start()
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def headless_main():
    L = Launcher()
    print(f"[roo] runtime={L.runtime} model={L.model} data={L.data}")
    L.setup_and_launch(lambda m: print("[roo]", m),
                       lambda u: print("[roo] ready:", u),
                       lambda m: print("[roo] FAILED:", m, file=sys.stderr))
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
