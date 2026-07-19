"""Core pipeline: text -> phonemes -> speech codes (llama-server) -> waveform (ONNX).

The generation contract is the one proven in IP-177 eval (gguf_e2e.py) and locked
by David's ear: GREEDY (temperature 0, top_k 1), en-gb espeak phonemes with the
exact training-time phonemizer settings, stop at <|SPEECH_GENERATION_END|>.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request

import numpy as np

SPEECH0 = 151671          # token id of <|speech_0|>
GEN_END = 151670          # token id of <|SPEECH_GENERATION_END|>
SAMPLE_RATE = 24000
MAX_CODES_PER_CHUNK = 1024   # ~20.5 s of audio; matches the trained envelope
SENTENCE_JOIN_SILENCE_S = 0.15


class EngineError(RuntimeError):
    pass


def pick_port(preferred=()):
    """Free-port pick that tests BOTH address families (IP-176 lesson: a port can
    be free on IPv4 and taken on IPv6, and a browser may resolve to either)."""
    def ok(p):
        for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            s = socket.socket(fam, socket.SOCK_STREAM)
            try:
                s.bind((addr, p))
            except OSError:
                return False
            finally:
                s.close()
        return True

    for p in preferred:
        if ok(p):
            return p
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Phonemizer:
    """en-gb espeak backend with the EXACT training settings — parity is a ship
    gate (IP-178 §6), so these kwargs must never drift from finetune_roo.py."""

    @staticmethod
    def _locate_espeak():
        """ctypes.util.find_library misses Homebrew and frozen-bundle paths, so
        probe explicitly: bundle dir first (frozen app ships the lib + data),
        then system locations. Sets the library AND its data dir."""
        import sys
        if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
            return
        here = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__))
        names = ("libespeak-ng.dylib", "libespeak-ng.so.1", "libespeak-ng.so",
                 "libespeak-ng.dll", "espeak-ng.dll")
        roots = (here, os.path.join(here, "espeak"),
                 "/opt/homebrew/lib", "/usr/local/lib", "/usr/lib",
                 "/usr/lib/x86_64-linux-gnu")
        for root in roots:
            for name in names:
                lib = os.path.join(root, name)
                if os.path.exists(lib):
                    from phonemizer.backend.espeak.wrapper import EspeakWrapper
                    EspeakWrapper.set_library(lib)
                    data = os.path.join(root, "espeak-ng-data")
                    if not os.path.isdir(data):
                        share = os.path.join(os.path.dirname(root),
                                             "share", "espeak-ng-data")
                        data = share if os.path.isdir(share) else None
                    if data and not os.environ.get("ESPEAK_DATA_PATH"):
                        os.environ["ESPEAK_DATA_PATH"] = data
                    return
        raise EngineError("espeak-ng library not found (set PHONEMIZER_ESPEAK_LIBRARY)")

    def __init__(self):
        self._locate_espeak()
        from phonemizer.backend import EspeakBackend
        self._backend = EspeakBackend(
            language="en-gb",
            preserve_punctuation=True,
            with_stress=True,
            words_mismatch="ignore",
            language_switch="remove-flags",
        )

    def __call__(self, text: str) -> str:
        phones = self._backend.phonemize([text])
        if not phones or not phones[0].strip():
            raise EngineError(f"empty phonemization for: {text!r}")
        return " ".join(phones[0].split())


class LlamaServer:
    """Supervises one llama-server child on a loopback port."""

    def __init__(self, bin_path: str, gguf_path: str, log_path: str):
        self.bin_path = bin_path
        self.gguf_path = gguf_path
        self.log_path = log_path
        self.port = None
        self.proc = None

    def start(self, timeout_s: int = 180):
        self.port = pick_port()
        args = [
            self.bin_path, "-m", self.gguf_path,
            "--host", "127.0.0.1", "--port", str(self.port),
            "-c", "2048", "-ngl", "99",
        ]
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(args, stdout=log, stderr=log)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise EngineError(
                    f"llama-server exited rc={self.proc.returncode} — see {self.log_path}")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if b'"ok"' in r.read():
                        return
            except OSError:
                pass
            time.sleep(0.5)
        self.stop()
        raise EngineError(f"llama-server not healthy within {timeout_s}s — see {self.log_path}")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def complete(self, prompt: str) -> list:
        """One greedy generation; returns speech code ids (ints)."""
        body = json.dumps({
            "prompt": prompt,
            "temperature": 0, "top_k": 1,
            "n_predict": MAX_CODES_PER_CHUNK,
            "return_tokens": True, "cache_prompt": True,
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/completion",
            body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read().decode())
        codes = []
        for t in d.get("tokens", []):
            if t == GEN_END:
                break
            if SPEECH0 <= t <= SPEECH0 + 65535:
                codes.append(t - SPEECH0)
        if not codes:
            raise EngineError("model produced no speech tokens")
        return codes


class OnnxDecoder:
    """NeuCodec int8 decoder via raw onnxruntime (parity vs torch decoder verified:
    aligned corr 0.9913, log-spec corr 0.9971; input is int32 [B,1,F])."""

    def __init__(self, onnx_path: str):
        import onnxruntime
        so = onnxruntime.SessionOptions()
        so.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = onnxruntime.InferenceSession(onnx_path, sess_options=so)

    def decode(self, codes: list) -> np.ndarray:
        arr = np.array(codes, dtype=np.int32)[None, None, :]
        wav = self.session.run(None, {"codes": arr})[0].astype(np.float32)
        return wav[0, 0, :]


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_text(text: str, max_chars: int = 300) -> list:
    """Sentence-level chunking so arbitrary-length input stays inside the trained
    per-utterance envelope; long sentences fall back to comma/space splits."""
    out = []
    for sent in _SENTENCE_SPLIT.split(text.strip()):
        sent = sent.strip()
        if not sent:
            continue
        while len(sent) > max_chars:
            cut = sent.rfind(",", 0, max_chars)
            if cut < max_chars // 2:
                cut = sent.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            out.append(sent[:cut + 1].strip())
            sent = sent[cut + 1:].strip()
        if sent:
            out.append(sent)
    return out


class Engine:
    """Owns the full pipeline and a serialized generation slot."""

    def __init__(self, llama: LlamaServer, decoder: OnnxDecoder, phonemizer: Phonemizer):
        self.llama = llama
        self.decoder = decoder
        self.phonemize = phonemizer
        self.gen_lock = threading.Lock()
        self.progress = {"phase": "idle", "chunk": 0, "chunks": 0, "started": None}

    def generate(self, text: str) -> np.ndarray:
        chunks = split_text(text)
        if not chunks:
            raise EngineError("no speakable text in input")
        gap = np.zeros(int(SENTENCE_JOIN_SILENCE_S * SAMPLE_RATE), dtype=np.float32)
        pieces = []
        with self.gen_lock:
            self.progress = {"phase": "generating", "chunk": 0,
                             "chunks": len(chunks), "started": time.time()}
            try:
                for i, chunk in enumerate(chunks):
                    self.progress["chunk"] = i + 1
                    phones = self.phonemize(chunk)
                    prompt = (
                        "user: Convert the text to speech:"
                        f"<|TEXT_PROMPT_START|>{phones}<|TEXT_PROMPT_END|>\n"
                        "assistant:<|SPEECH_GENERATION_START|>"
                    )
                    codes = self.llama.complete(prompt)
                    pieces.append(self.decoder.decode(codes))
                    if i < len(chunks) - 1:
                        pieces.append(gap)
            finally:
                self.progress = {"phase": "idle", "chunk": 0, "chunks": 0, "started": None}
        return np.concatenate(pieces)


def wav_bytes(x: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    import io
    import wave
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
