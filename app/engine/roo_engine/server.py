"""HTTP surface of roo-engine (loopback only).

Starts serving IMMEDIATELY so the UI can watch model download / load progress
(v1.1.1 lesson: the server must exist before it is ready — 503 while warming).

  GET  /healthz            {status: starting|downloading|loading|warming|ready|failed, ...}
  GET  /progress           generation progress for the visualizer
  POST /v1/audio/speech    {"input": text} -> audio/wav (X-History-Id header)
  GET  /history            newest-first JSON list
  GET  /history/<id>.wav   stored clip
  DELETE /history/<id>     remove clip
  GET  /diagnostics        support bundle (no secrets; paths + versions + log tail)
"""
import hashlib
import json
import os
import platform
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .engine import EngineError, wav_bytes, SAMPLE_RATE

STATE = {
    "status": "starting", "detail": "", "version": __version__,
    "model": "", "backend": "", "download": None,
}
_STATE_LOCK = threading.Lock()


def set_state(**kw):
    with _STATE_LOCK:
        STATE.update(kw)


def get_state():
    with _STATE_LOCK:
        return dict(STATE)


def download(url: str, dest: str, sha256: str = None, label: str = ""):
    """Resumable download with HONEST byte progress in STATE (symlink-free sizing
    and real bytes — the IP-176 '19.1 GB of 9 GB' lesson) + sha256 verification."""
    tmp = dest + ".part"
    got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    req = urllib.request.Request(url)
    if got:
        req.add_header("Range", f"bytes={got}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = got + int(r.headers.get("Content-Length", 0))
        mode = "ab" if got and r.status == 206 else "wb"
        if mode == "wb":
            got = 0
        with open(tmp, mode) as f:
            while True:
                block = r.read(1024 * 512)
                if not block:
                    break
                f.write(block)
                got += len(block)
                set_state(status="downloading",
                          download={"label": label, "got": got, "total": total})
    if sha256:
        h = hashlib.sha256()
        with open(tmp, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != sha256:
            os.remove(tmp)
            raise EngineError(f"sha256 mismatch for {label}: got {h.hexdigest()}")
    os.replace(tmp, dest)
    set_state(download=None)


class History:
    """Flat store: <data>/history/<id>.wav + index.jsonl. No DB (host doctrine)."""

    def __init__(self, root: str):
        self.dir = os.path.join(root, "history")
        os.makedirs(self.dir, exist_ok=True)
        self.index = os.path.join(self.dir, "index.jsonl")
        self._lock = threading.Lock()

    def add(self, text: str, wav: bytes, duration_s: float, gen_s: float,
            title: str = "") -> dict:
        entry = {
            "id": f"{int(time.time() * 1000):x}",
            "text": text, "ts": time.time(),
            "duration_s": round(duration_s, 2), "gen_s": round(gen_s, 2),
        }
        if title:
            entry["title"] = title[:120]
        with self._lock:
            with open(os.path.join(self.dir, entry["id"] + ".wav"), "wb") as f:
                f.write(wav)
            with open(self.index, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def list(self) -> list:
        if not os.path.exists(self.index):
            return []
        with self._lock, open(self.index) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        live = [e for e in entries
                if os.path.exists(os.path.join(self.dir, e["id"] + ".wav"))]
        return list(reversed(live))

    def wav_path(self, hid: str) -> str:
        if not hid.replace(".wav", "").isalnum():
            raise EngineError("bad history id")
        return os.path.join(self.dir, hid if hid.endswith(".wav") else hid + ".wav")

    def delete(self, hid: str):
        p = self.wav_path(hid)
        if os.path.exists(p):
            os.remove(p)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # keep stdout clean (port announce line only)
            pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Expose-Headers",
                             "X-History-Id, X-Duration-S, X-Gen-S")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj, extra=None):
            self._send(code, json.dumps(obj).encode(), extra=extra)

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            if self.path == "/healthz":
                self._json(200 if get_state()["status"] == "ready" else 503, get_state())
            elif self.path == "/progress":
                self._json(200, app["engine"].progress if app.get("engine")
                           else {"phase": "idle"})
            elif self.path == "/history":
                self._json(200, app["history"].list())
            elif self.path.startswith("/history/"):
                try:
                    p = app["history"].wav_path(self.path.split("/history/", 1)[1])
                    with open(p, "rb") as f:
                        self._send(200, f.read(), "audio/wav")
                except (OSError, EngineError):
                    self._json(404, {"error": "not found"})
            elif self.path == "/diagnostics":
                self._json(200, app["diagnostics"]())
            else:
                self._json(404, {"error": "unknown path"})

        def do_POST(self):
            if self.path == "/shutdown":
                # Loopback-only surface; the Tauri shell calls this on app exit so
                # the llama-server child is never orphaned (then falls back to kill).
                self._json(200, {"ok": True})
                threading.Thread(target=app["shutdown"], daemon=True).start()
                return
            if self.path != "/v1/audio/speech":
                return self._json(404, {"error": "unknown path"})
            st = get_state()
            if st["status"] != "ready":
                return self._json(503, {"error": f"engine {st['status']}", "state": st})
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode())
                text = body.get("input", "").strip()
                if not text:
                    return self._json(400, {"error": "empty input"})
                t0 = time.time()
                wave = app["engine"].generate(text)
                gen_s = time.time() - t0
                wav = wav_bytes(wave)
                entry = app["history"].add(text, wav, len(wave) / SAMPLE_RATE, gen_s,
                                           title=str(body.get("title", "")).strip())
                self._send(200, wav, "audio/wav", extra={
                    "X-History-Id": entry["id"],
                    "X-Duration-S": str(entry["duration_s"]),
                    "X-Gen-S": str(entry["gen_s"]),
                })
            except EngineError as e:
                self._json(500, {"error": str(e)})
            except Exception as e:  # surface, never swallow (IP-176 doctrine)
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def do_DELETE(self):
            if self.path.startswith("/history/"):
                try:
                    app["history"].delete(self.path.split("/history/", 1)[1])
                    self._json(200, {"ok": True})
                except EngineError as e:
                    self._json(400, {"error": str(e)})
            else:
                self._json(404, {"error": "unknown path"})

    return Handler


def diagnostics_factory(data_dir: str, llama, app=None):
    def diagnostics():
        log_tail = ""
        try:
            with open(os.path.join(data_dir, "llama-server.log"), "rb") as f:
                f.seek(max(0, os.fstat(f.fileno()).st_size - 8192))
                log_tail = f.read().decode(errors="replace")
        except OSError:
            pass
        return {
            "state": get_state(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "data_dir": data_dir,
            "llama_alive": bool(llama and llama.alive()),
            "llama_log_tail": log_tail,
            # Derail-guard activity: empty on a healthy run. A "dropped" entry
            # means a span was replaced by silence rather than a sustained tone —
            # the one case where output is knowingly incomplete, so it must be
            # visible in a user's report and not just inferred from the audio.
            "guard_events": list(getattr(app.get("engine"), "guard_events", []))
                            if app else [],
        }
    return diagnostics


def serve(app, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
