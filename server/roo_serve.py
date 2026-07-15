#!/usr/bin/env python3
"""Roo Voice — unified serving backend + web UI.

One server for both runtimes:

  Apple Silicon (MLX):
      python roo_serve.py --runtime mlx \
        --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_mlx8

  NVIDIA GPU (transformers, INT8 or BF16):
      python roo_serve.py --runtime transformers \
        --model abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8 \
        --codec OpenMOSS-Team/MOSS-Audio-Tokenizer

Serves the Roo Voice web UI at  http://<host>:<port>/  and an OpenAI-compatible
POST /v1/audio/speech endpoint. The voice is fixed: the reference is baked in
server-side (bundled reference.wav), so callers supply only text.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import wave
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
ASSETS_DIR = REPO_ROOT / "assets"
DEFAULT_REF = REPO_ROOT / "reference.wav"

# Locked IP-172 decoding contract.
DC = dict(seed=42, text_temperature=1.0, audio_temperature=1.0, top_p=0.95,
          top_k=50, repetition_penalty=1.1, n_vq=32, sampling_rate=24000)


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


# --------------------------------------------------------------------------- #
# Runtime backends
# --------------------------------------------------------------------------- #


class MlxBackend:
    runtime = "MLX-8bit"

    def __init__(self, model: str, reference: str):
        os.environ.setdefault("HF_HUB_OFFLINE", "0")
        from mlx_audio.tts.utils import load_model
        self.device = "metal"
        self.ref = reference
        self.model = load_model(Path(resolve_model(model)), lazy=False, strict=True)
        import mlx.core as mx
        self._mx = mx

    def generate(self, text: str, seed: int):
        self._mx.random.seed(seed)
        result = None
        for r in self.model.generate(
            text=text, ref_audio=self.ref, ref_text=None, mode="generation",
            max_tokens=4096, n_vq_for_inference=DC["n_vq"],
            text_temperature=DC["text_temperature"], text_top_p=DC["top_p"],
            text_top_k=DC["top_k"], text_repetition_penalty=1.0,
            audio_temperature=DC["audio_temperature"], audio_top_p=DC["top_p"],
            audio_top_k=DC["top_k"], audio_repetition_penalty=DC["repetition_penalty"],
        ):
            result = r
        return np.asarray(result.audio, dtype=np.float32).reshape(-1), int(getattr(result, "sample_rate", DC["sampling_rate"]))


class TransformersBackend:
    def __init__(self, model: str, codec: str, reference: str, device: str = "cuda"):
        import torch
        import soundfile as sf
        from transformers import AutoProcessor, AutoModel
        self.torch = torch
        self.device = device if torch.cuda.is_available() else "cpu"
        model_dir = resolve_model(model)
        codec_dir = resolve_model(codec)
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
        wav_np, sr = sf.read(reference)
        wav = torch.tensor(wav_np, dtype=torch.float32)
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)
        self.ref_codes = proc.encode_audios_from_wav([wav], sampling_rate=int(sr), n_vq=DC["n_vq"])[0]
        self.proc, self.model = proc, m
        q = getattr(m.config, "quantization_config", None)
        self.runtime = "INT8" if q else "BF16"

    def generate(self, text: str, seed: int):
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
                max_new_tokens=4096, n_vq_for_inference=DC["n_vq"],
                text_temperature=DC["text_temperature"], text_top_p=DC["top_p"],
                text_top_k=DC["top_k"], text_repetition_penalty=1.0,
                audio_temperature=DC["audio_temperature"], audio_top_p=DC["top_p"],
                audio_top_k=DC["top_k"], audio_repetition_penalty=DC["repetition_penalty"],
            )
            message = self.proc.decode(outputs)[0]
            audio = message.audio_codes_list[0].detach().to(torch.float32).cpu().numpy().reshape(-1)
        sr = int(getattr(self.proc, "model_config", None).sampling_rate) if getattr(self.proc, "model_config", None) else DC["sampling_rate"]
        return audio, sr


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


class Speech(BaseModel):
    input: str
    model: str = "roo"
    voice: str = "roo"
    response_format: str = "wav"
    seed: int | None = None


def build_app(backend, log_path: str) -> FastAPI:
    app = FastAPI(title="Roo Voice")

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
        return {"ready": True}

    @app.get("/info")
    def info():
        return {"runtime": backend.runtime, "device": backend.device,
                "voice": "roo", "decoding_contract": DC}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": "roo", "object": "model", "owned_by": "abliter8"}]}

    @app.post("/v1/audio/speech")
    def speech(req: Speech):
        if req.voice != "roo":
            return JSONResponse({"error": "fixed voice is 'roo'"}, status_code=422)
        try:
            seed = DC["seed"] if req.seed is None else int(req.seed)
            t0 = time.time()
            audio, sr = backend.generate(req.input, seed)
            data, nsamp = _wav_bytes(audio, sr)
            gen_s = round(time.time() - t0, 2)
            audio_s = round(nsamp / float(sr), 2)
            rtf = round(gen_s / audio_s, 2) if audio_s > 0 else None
            try:
                with open(log_path, "a") as fh:
                    fh.write(json.dumps({"runtime": backend.runtime, "device": backend.device,
                                         "gen_seconds": gen_s, "audio_seconds": audio_s,
                                         "rtf": rtf, "chars": len(req.input)}) + "\n")
            except Exception:
                pass
            return Response(content=data, media_type="audio/wav",
                            headers={"X-Roo-Gen-Seconds": str(gen_s), "X-Roo-Audio-Seconds": str(audio_s),
                                     "X-Roo-RTF": str(rtf), "X-Roo-Sample-Rate": str(sr)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    return app


def main():
    ap = argparse.ArgumentParser(description="Roo Voice serving backend + UI")
    ap.add_argument("--runtime", required=True, choices=["mlx", "transformers"])
    ap.add_argument("--model", required=True, help="local path or HF repo id")
    ap.add_argument("--codec", default="OpenMOSS-Team/MOSS-Audio-Tokenizer",
                    help="audio codec (transformers runtime only)")
    ap.add_argument("--reference", default=str(DEFAULT_REF))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--log", default=str(REPO_ROOT / "roo-gen.jsonl"))
    args = ap.parse_args()

    if args.runtime == "mlx":
        backend = MlxBackend(args.model, args.reference)
    else:
        backend = TransformersBackend(args.model, args.codec, args.reference, device=args.device)
    print(f"[roo] runtime={backend.runtime} device={backend.device} — http://{args.host}:{args.port}/")
    uvicorn.run(build_app(backend, args.log), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
