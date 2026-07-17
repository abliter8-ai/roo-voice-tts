#!/usr/bin/env python3
"""Roo Voice — unified serving backend + web UI.

One server for both runtimes:

  Apple Silicon (MLX):
      python roo_serve.py --runtime mlx \
        --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx4

  NVIDIA GPU (transformers, INT4/INT8/BF16):
      python roo_serve.py --runtime transformers \
        --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4 \
        --codec OpenMOSS-Team/MOSS-Audio-Tokenizer

Serves the Roo Voice web UI at  http://<host>:<port>/  and an OpenAI-compatible
POST /v1/audio/speech endpoint. The voice is fixed: the reference is baked in
server-side (bundled reference.wav), so callers supply only text.

IP-176 contract:
  * The accelerator is REQUIRED. If it is unavailable we refuse to start rather
    than silently falling back to CPU (--allow-cpu opts in, and is never automatic).
  * The model is WARMED UP at startup, so the first user-visible request does not
    pay the kernel-compile cost. /healthz reports ready=false until that is done.
  * Runtime labels are DERIVED from the loaded model, never hardcoded.
  * Everything is logged to <data-dir>/logs/roo-voice.log and surfaced at /diagnostics.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import wave
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

ROO_VOICE_VERSION = "1.1.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
ASSETS_DIR = REPO_ROOT / "assets"
DEFAULT_REF = REPO_ROOT / "reference.wav"

# Locked IP-172 decoding contract.
DC = dict(seed=42, text_temperature=1.0, audio_temperature=1.0, top_p=0.95,
          top_k=50, repetition_penalty=1.1, n_vq=32, sampling_rate=24000)

WARMUP_TEXT = "Warm up."
WARMUP_MAX_TOKENS = 8

log = logging.getLogger("roo")

# Rolling diagnostics state (bounded — never grows without limit).
STATE: dict = {
    "phase": "starting",       # starting -> loading -> warming -> ready | failed
    "ready": False,
    "warmup_seconds": None,
    "error": None,
}
GENERATIONS: deque = deque(maxlen=20)
ERRORS: deque = deque(maxlen=10)
GEN_LOCK = threading.Lock()   # both runtimes are serial; queue requests rather than interleave


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "roo-voice.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers[:] = [fh, sh]
    log.propagate = False
    return path


def record_error(where: str, exc: BaseException) -> None:
    tb = traceback.format_exc()
    ERRORS.append({"where": where, "error": f"{type(exc).__name__}: {exc}",
                   "traceback": tb, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    log.error("%s failed: %s: %s\n%s", where, type(exc).__name__, exc, tb)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def resolve_model(path_or_repo: str) -> str:
    p = Path(path_or_repo)
    if p.exists():
        return str(p)
    from huggingface_hub import snapshot_download
    return snapshot_download(path_or_repo)


def _wav_bytes(audio, sr: int):
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue(), len(a)


def load_reference(path: str, target_sr: int) -> np.ndarray:
    """Load the identity reference as (1, N) mono float32 at target_sr.

    IP-176 RC5: the shipped reference.wav is 48 kHz *stereo*. `sf.read` returns
    (frames, channels); the codec wants (channels, samples). The old code only
    unsqueezed when ndim==1, so a stereo file was handed over transposed — the
    codec saw N "channels" of 2 samples. Normalise explicitly here so both
    runtimes get an identical, contract-shaped reference.
    """
    import soundfile as sf
    wav, sr = sf.read(path, always_2d=True, dtype="float32")   # (frames, channels)
    wav = np.ascontiguousarray(wav.T)                          # -> (channels, frames)
    if wav.shape[0] > 1:                                       # downmix to mono
        wav = wav.mean(axis=0, keepdims=True)
    if sr != target_sr:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(int(sr), int(target_sr))
        wav = resample_poly(wav, int(target_sr) // g, int(sr) // g, axis=1).astype(np.float32)
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    assert wav.ndim == 2 and wav.shape[0] == 1, f"reference must be (1, N), got {wav.shape}"
    log.info("reference: %s -> shape=%s sr=%d (%.2fs mono)",
             path, wav.shape, target_sr, wav.shape[1] / target_sr)
    return wav


def write_wav_mono(path: Path, audio: np.ndarray, sr: int) -> Path:
    data, _ = _wav_bytes(audio.reshape(-1), sr)
    path.write_bytes(data)
    return path


class AcceleratorUnavailable(RuntimeError):
    """Raised instead of silently degrading to CPU (IP-176 RC2)."""


# --------------------------------------------------------------------------- #
# Runtime backends
# --------------------------------------------------------------------------- #


class MlxBackend:
    def __init__(self, model: str, reference: str, allow_cpu: bool = False):
        if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
            raise AcceleratorUnavailable(
                "The MLX runtime requires an Apple Silicon Mac (M1-M4).\n"
                f"This machine reports {platform.system()}/{platform.machine()}.\n"
                "On an NVIDIA GPU use:  --runtime transformers")
        os.environ.setdefault("HF_HUB_OFFLINE", "0")
        from mlx_audio.tts.utils import load_model
        self.device = "metal"
        model_dir = Path(resolve_model(model))
        self.model_dir = model_dir
        log.info("loading MLX model from %s", model_dir)
        self.model = load_model(model_dir, lazy=False, strict=True)
        import mlx.core as mx
        self._mx = mx
        self.runtime = self._derive_label(model_dir)

        # Normalise the reference once, then hand MLX a contract-shaped file so
        # both runtimes condition on byte-identical audio (IP-176 D4).
        import tempfile
        ref = load_reference(reference, DC["sampling_rate"])
        self._ref_dir = tempfile.TemporaryDirectory(prefix="roo-voice-")
        self.ref = str(write_wav_mono(Path(self._ref_dir.name) / "reference-24k-mono.wav",
                                      ref, DC["sampling_rate"]))

    @staticmethod
    def _derive_label(model_dir: Path) -> str:
        """IP-176 RC6: read the quantisation off the model, never hardcode it."""
        try:
            cfg = json.loads((model_dir / "config.json").read_text())
            q = cfg.get("quantization") or cfg.get("quantization_config") or {}
            bits = q.get("bits")
            if bits:
                return f"MLX-{int(bits)}bit"
        except Exception:  # noqa: BLE001
            log.warning("could not read quantisation from config.json", exc_info=True)
        return "MLX"

    def _gen(self, text: str, seed: int, max_tokens: int):
        self._mx.random.seed(seed)
        result = None
        for r in self.model.generate(
            text=text, ref_audio=self.ref, ref_text=None, mode="generation",
            max_tokens=max_tokens, n_vq_for_inference=DC["n_vq"],
            text_temperature=DC["text_temperature"], text_top_p=DC["top_p"],
            text_top_k=DC["top_k"], text_repetition_penalty=1.0,
            audio_temperature=DC["audio_temperature"], audio_top_p=DC["top_p"],
            audio_top_k=DC["top_k"], audio_repetition_penalty=DC["repetition_penalty"],
        ):
            result = r
        return result

    def warmup(self):
        self._gen(WARMUP_TEXT, DC["seed"], WARMUP_MAX_TOKENS)

    def generate(self, text: str, seed: int):
        result = self._gen(text, seed, 4096)
        return (np.asarray(result.audio, dtype=np.float32).reshape(-1),
                int(getattr(result, "sample_rate", DC["sampling_rate"])))


class TransformersBackend:
    def __init__(self, model: str, codec: str, reference: str, allow_cpu: bool = False):
        import torch
        from transformers import AutoProcessor, AutoModel
        self.torch = torch

        cuda_ok = torch.cuda.is_available()
        if not cuda_ok and not allow_cpu:
            # IP-176 RC2: this is the Windows "loads but never generates" bug.
            # PyPI's win_amd64 torch wheel is CPU-only (~122 MB); the CUDA build
            # (~2.5 GB) only exists on the PyTorch index. Refuse, loudly.
            raise AcceleratorUnavailable(
                "No CUDA GPU is available to PyTorch, so Roo Voice will not start.\n"
                f"  torch {torch.__version__}  |  torch.version.cuda = {torch.version.cuda}\n"
                "\n"
                "This almost always means a CPU-only PyTorch was installed. PyPI's Windows\n"
                "torch wheel has no CUDA. Install the CUDA build:\n"
                "\n"
                "    pip install --force-reinstall torch torchaudio \\\n"
                "        --index-url https://download.pytorch.org/whl/cu128\n"
                "\n"
                "Then restart Roo Voice. (CPU generation is far too slow to be usable;\n"
                "pass --allow-cpu only if you want to prove that to yourself.)")
        self.device = "cuda" if cuda_ok else "cpu"
        if not cuda_ok:
            log.warning("CUDA unavailable and --allow-cpu given: running on CPU. "
                        "This is not a usable configuration; expect minutes per sentence.")

        model_dir = resolve_model(model)
        codec_dir = resolve_model(codec)
        log.info("loading transformers model from %s (codec %s)", model_dir, codec_dir)
        proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True, codec_path=codec_dir)
        proc.audio_tokenizer = proc.audio_tokenizer.to("cpu")  # light; frees GPU for the LM + KV
        kw = {"trust_remote_code": True}
        if self.device == "cuda":
            kw["device_map"] = {"": 0}
        m = AutoModel.from_pretrained(model_dir, **kw)
        if self.device != "cuda":
            m = m.to(self.device)
        m.eval()
        # Mirror backbone dims onto the top config so generate()'s cache init works.
        lc = m.config.language_config
        lc_get = (lambda a: lc.get(a)) if isinstance(lc, dict) else (lambda a: getattr(lc, a, None))
        for attr in ("num_hidden_layers", "num_attention_heads", "num_key_value_heads",
                     "head_dim", "hidden_size", "max_position_embeddings"):
            v = lc_get(attr)
            if v is not None and getattr(m.config, attr, None) is None:
                setattr(m.config, attr, v)

        # Pre-encode the reference to codes once (bypasses torchcodec).
        ref = load_reference(reference, DC["sampling_rate"])       # (1, N) mono @24k
        wav = torch.from_numpy(ref)                                # (channels, samples) — correct axis
        self.ref_codes = proc.encode_audios_from_wav(
            [wav], sampling_rate=DC["sampling_rate"], n_vq=DC["n_vq"])[0]
        self.proc, self.model = proc, m
        self.runtime = self._derive_label(m)
        self.gpu_name = torch.cuda.get_device_name(0) if self.device == "cuda" else None

    @staticmethod
    def _derive_label(m) -> str:
        """IP-176 RC6: 'INT8 if quantized else BF16' reported INT8 for the int4 build."""
        q = getattr(m.config, "quantization_config", None)
        if q is None:
            return "BF16"
        g = (lambda k: q.get(k)) if isinstance(q, dict) else (lambda k: getattr(q, k, None))
        if g("load_in_4bit"):
            qt = g("bnb_4bit_quant_type") or "nf4"
            return f"INT4-{str(qt).upper()}"
        if g("load_in_8bit"):
            return "INT8"
        return "quantized"

    def _gen(self, text: str, seed: int, max_new_tokens: int):
        torch = self.torch
        with torch.inference_mode():
            torch.manual_seed(seed)
            if self.device == "cuda":
                torch.cuda.manual_seed_all(seed)
            conv = [[self.proc.build_user_message(text=text, reference=[self.ref_codes])]]
            batch = self.proc(conv, mode="generation")
            outputs = self.model.generate(
                input_ids=batch["input_ids"].to(self.device),
                attention_mask=batch["attention_mask"].to(self.device),
                max_new_tokens=max_new_tokens, n_vq_for_inference=DC["n_vq"],
                text_temperature=DC["text_temperature"], text_top_p=DC["top_p"],
                text_top_k=DC["top_k"], text_repetition_penalty=1.0,
                audio_temperature=DC["audio_temperature"], audio_top_p=DC["top_p"],
                audio_top_k=DC["top_k"], audio_repetition_penalty=DC["repetition_penalty"],
            )
            return self.proc.decode(outputs)[0]

    def warmup(self):
        self._gen(WARMUP_TEXT, DC["seed"], WARMUP_MAX_TOKENS)

    def generate(self, text: str, seed: int):
        message = self._gen(text, seed, 4096)
        audio = message.audio_codes_list[0].detach().to(self.torch.float32).cpu().numpy().reshape(-1)
        mc = getattr(self.proc, "model_config", None)
        sr = int(getattr(mc, "sampling_rate", DC["sampling_rate"])) if mc else DC["sampling_rate"]
        return audio, sr


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #


def _sysinfo() -> dict:
    info = {
        "app_version": ROO_VOICE_VERSION,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }
    try:
        if platform.system() == "Darwin":
            info["chip"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                          capture_output=True, text=True, timeout=5).stdout.strip()
            mem = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            info["ram_gb"] = round(int(mem) / 1073741824) if mem.isdigit() else None
            info["macos"] = platform.mac_ver()[0]
        else:
            info["processor"] = platform.processor()
    except Exception:  # noqa: BLE001
        pass
    return info


def _runtime_info(backend) -> dict:
    d = {"runtime": getattr(backend, "runtime", "?"),
         "device": getattr(backend, "device", "?"),
         "model_dir": str(getattr(backend, "model_dir", "")) or None}
    try:
        import torch  # noqa: PLC0415
        d["torch"] = torch.__version__
        d["torch_cuda_build"] = torch.version.cuda
        d["torch_cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            d["gpu"] = torch.cuda.get_device_name(0)
    except Exception:  # noqa: BLE001
        pass
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    for pkg, key in (("mlx", "mlx"), ("mlx-audio", "mlx_audio"),
                     ("transformers", "transformers"), ("bitsandbytes", "bitsandbytes")):
        try:
            d[key] = _pkg_version(pkg)
        except PackageNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            pass
    return d


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


class Speech(BaseModel):
    input: str
    model: str = "roo"
    voice: str = "roo"
    response_format: str = "wav"
    seed: int | None = None


def build_app(backend, log_path: str, diag_log: Path) -> FastAPI:
    app = FastAPI(title="Roo Voice", version=ROO_VOICE_VERSION)

    @app.on_event("startup")
    def _start_warmup():
        def run():
            STATE["phase"] = "warming"
            t0 = time.time()
            log.info("warm-up starting (first run compiles GPU kernels — this is the slow one)")
            try:
                with GEN_LOCK:
                    backend.warmup()
                STATE["warmup_seconds"] = round(time.time() - t0, 2)
                STATE["phase"] = "ready"
                STATE["ready"] = True
                log.info("warm-up complete in %ss — server is ready", STATE["warmup_seconds"])
            except Exception as e:  # noqa: BLE001
                STATE["phase"] = "failed"
                STATE["error"] = f"{type(e).__name__}: {e}"
                record_error("warmup", e)
        threading.Thread(target=run, name="roo-warmup", daemon=True).start()

    @app.get("/")
    def root():
        return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/assets/{name}")
    def asset(name: str):
        f = ASSETS_DIR / name
        if not f.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(f))

    @app.get("/healthz")
    def healthz():
        # IP-176 D1: ready means *warm*, not merely loaded.
        return {"ready": STATE["ready"], "phase": STATE["phase"],
                "warmup_seconds": STATE["warmup_seconds"], "error": STATE["error"]}

    @app.get("/info")
    def info():
        return {"runtime": backend.runtime, "device": backend.device,
                "version": ROO_VOICE_VERSION, "voice": "roo",
                "ready": STATE["ready"], "phase": STATE["phase"],
                "decoding_contract": DC}

    @app.get("/diagnostics")
    def diagnostics():
        return {"version": ROO_VOICE_VERSION,
                "state": dict(STATE),
                "system": _sysinfo(),
                "runtime": _runtime_info(backend),
                "decoding_contract": DC,
                "log_file": str(diag_log),
                "recent_generations": list(GENERATIONS),
                "recent_errors": list(ERRORS)}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": "roo", "object": "model", "owned_by": "abliter8"}]}

    @app.post("/v1/audio/speech")
    def speech(req: Speech):
        if req.voice != "roo":
            return JSONResponse({"error": "fixed voice is 'roo'"}, status_code=422)
        if STATE["phase"] == "failed":
            return JSONResponse({"error": f"server failed to warm up: {STATE['error']}"},
                                status_code=503)
        if not STATE["ready"]:
            # "ready means warm" is the contract (D1) — enforce it, don't rely on
            # the warm-up thread winning the race for GEN_LOCK.
            return JSONResponse({"error": "still warming up — the first run compiles GPU kernels",
                                 "phase": STATE["phase"]}, status_code=503)
        try:
            seed = DC["seed"] if req.seed is None else int(req.seed)
            t0 = time.time()
            with GEN_LOCK:          # serial runtime: queue rather than interleave
                audio, sr = backend.generate(req.input, seed)
            data, nsamp = _wav_bytes(audio, sr)
            gen_s = round(time.time() - t0, 2)
            audio_s = round(nsamp / float(sr), 2)
            rtf = round(gen_s / audio_s, 2) if audio_s > 0 else None
            rec = {"runtime": backend.runtime, "device": backend.device,
                   "gen_seconds": gen_s, "audio_seconds": audio_s,
                   "rtf": rtf, "chars": len(req.input),
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            GENERATIONS.append(rec)
            log.info("generated %.2fs audio in %.2fs (RTF %.2fx) for %d chars",
                     audio_s, gen_s, rtf or 0, len(req.input))
            try:
                with open(log_path, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
            except Exception:  # noqa: BLE001
                pass
            return Response(content=data, media_type="audio/wav",
                            headers={"X-Roo-Gen-Seconds": str(gen_s), "X-Roo-Audio-Seconds": str(audio_s),
                                     "X-Roo-RTF": str(rtf), "X-Roo-Sample-Rate": str(sr),
                                     "X-Roo-Runtime": backend.runtime, "X-Roo-Version": ROO_VOICE_VERSION})
        except Exception as e:  # noqa: BLE001
            record_error("generate", e)     # IP-176 D7: to the log file, not a lost stdout
            return JSONResponse({"error": f"{type(e).__name__}: {e}",
                                 "diagnostics": "/diagnostics"}, status_code=500)

    return app


def default_log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Roo Voice" / "logs"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roo Voice" / "logs"
    return Path.home() / ".local" / "share" / "roo-voice" / "logs"


def main():
    ap = argparse.ArgumentParser(description="Roo Voice serving backend + UI")
    ap.add_argument("--runtime", required=True, choices=["mlx", "transformers"])
    ap.add_argument("--model", required=True, help="local path or HF repo id")
    ap.add_argument("--codec", default="OpenMOSS-Team/MOSS-Audio-Tokenizer",
                    help="audio codec (transformers runtime only)")
    ap.add_argument("--reference", default=str(DEFAULT_REF))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--log", default=str(REPO_ROOT / "roo-gen.jsonl"))
    ap.add_argument("--log-dir", default=None, help="where roo-voice.log is written")
    ap.add_argument("--allow-cpu", action="store_true",
                    help="permit CPU execution (unusably slow; never automatic)")
    args = ap.parse_args()

    log_dir = Path(args.log_dir) if args.log_dir else default_log_dir()
    diag_log = setup_logging(log_dir)
    log.info("Roo Voice %s starting — runtime=%s model=%s", ROO_VOICE_VERSION, args.runtime, args.model)
    log.info("python=%s platform=%s", sys.version.split()[0], platform.platform())

    STATE["phase"] = "loading"
    try:
        if args.runtime == "mlx":
            backend = MlxBackend(args.model, args.reference, allow_cpu=args.allow_cpu)
        else:
            backend = TransformersBackend(args.model, args.codec, args.reference,
                                          allow_cpu=args.allow_cpu)
    except AcceleratorUnavailable as e:
        STATE["phase"] = "failed"
        STATE["error"] = str(e)
        log.error("refusing to start:\n%s", e)
        print(f"\n[roo] CANNOT START\n\n{e}\n", file=sys.stderr)
        print(f"[roo] full log: {diag_log}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        STATE["phase"] = "failed"
        STATE["error"] = f"{type(e).__name__}: {e}"
        record_error("startup", e)
        print(f"\n[roo] CANNOT START: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"[roo] full log: {diag_log}", file=sys.stderr)
        sys.exit(2)

    log.info("loaded: runtime=%s device=%s", backend.runtime, backend.device)
    print(f"[roo] runtime={backend.runtime} device={backend.device} v{ROO_VOICE_VERSION} "
          f"— http://{args.host}:{args.port}/ (warming up…)")
    uvicorn.run(build_app(backend, args.log, diag_log), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
