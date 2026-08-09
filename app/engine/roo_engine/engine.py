"""Core pipeline: text -> phonemes -> speech codes (llama-server) -> waveform (ONNX).

The generation contract is the one proven in IP-177 eval (gguf_e2e.py) and locked
by David's ear: GREEDY (temperature 0, top_k 1), en-gb espeak phonemes with the
exact training-time phonemizer settings, stop at <|SPEECH_GENERATION_END|>.

Two engine-side robustness passes sit around that contract (added after the
elevated field-issue reports, measured on the shipped Q4_K_M path):
  * INPUT normalization (normalize.py) — rewrites only the STRUCTURE espeak
    mangles (ISO dates/timestamps, hyphenated ranges and IDs, currency order,
    broken abbreviations) and leaves digits for espeak to read. It never
    converts numbers to words and it can never raise; see normalize.py.
  * BUDGET guard (_audio_for below) — a generation that stops on the 1024-code
    cap instead of <|SPEECH_GENERATION_END|> did not finish. Either it derailed
    (locked into a repeating code, droning "EEEE"), or it was simply truncated:
    split_text caps chunks by CHARACTERS while the budget is in TIME, so slow
    content silently lost the end of its sentence. Both are re-split and
    regenerated so each piece gets its own budget.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np

from .normalize import normalize

SPEECH0 = 151671          # token id of <|speech_0|>
GEN_END = 151670          # token id of <|SPEECH_GENERATION_END|>
SAMPLE_RATE = 24000
MAX_CODES_PER_CHUNK = 1024   # ~20.5 s of audio; matches the trained envelope
SENTENCE_JOIN_SILENCE_S = 0.15

# Derail guard: a healthy chunk terminates on <|SPEECH_GENERATION_END|> with
# diverse codes; a greedy derail runs to the length cap AND its tail collapses to
# a handful of repeating codes (measured Q8 drone: 5 unique values in the last 200
# codes, one code repeated 50x = the sustained "EEEE" tone). Both conditions
# together are the signature we act on.
#
# The cap half of that test comes from llama-server's own stop reason
# (stop_type == "limit"), NOT from len(codes): complete() drops any non-speech
# token, so a capped generation carrying one stray token yields 1023 codes and
# would slip a length check.
DERAIL_TAIL = 200            # codes at the end to inspect
DERAIL_TAIL_UNIQ_MIN = 20    # fewer unique than this in the tail => collapsed
DRONE_TRIM_WIN = 100         # sliding window for locating the drone
DRONE_TRIM_RATIO = 0.30      # unique/len below this marks a collapsed window
DRONE_MIN_KEEP = 25          # ~0.5 s; below this there is no speech worth keeping

# Re-chunk caps for a span that hit the code budget, tightest last. Splitting a
# capped span gives each piece its own MAX_CODES_PER_CHUNK budget, which is the
# fix for BOTH capped failures (see _audio_for): a derail, and a chunk that
# simply holds more speech than 1024 codes can carry. split_text still merges
# short sentences inside each cap, so these do not produce tiny fragments.
RESPLIT_CHARS = (120, 80)


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

    _preloaded: list = []   # keep bundled dylib handles alive for the process

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
                    # Preload bundled deps (pcaudio) by absolute path so the
                    # TEMP COPY phonemizer makes of the espeak lib can resolve
                    # its bare-name dependency from the already-loaded image.
                    import ctypes
                    import glob as _glob
                    for dep in _glob.glob(os.path.join(root, "libpcaudio*")):
                        try:
                            Phonemizer._preloaded.append(
                                ctypes.CDLL(dep, mode=ctypes.RTLD_GLOBAL))
                        except OSError:
                            pass
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

    def complete(self, prompt: str) -> tuple:
        """One greedy generation. Returns (speech code ids, capped) where `capped`
        is llama-server's own stop reason — True when generation was cut off by
        n_predict rather than ending on <|SPEECH_GENERATION_END|>."""
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
        # Newer llama.cpp reports stop_type ("limit" | "eos" | "word"); older
        # builds used a stopped_limit bool. Accept either, and fall back to the
        # length test if neither field is present.
        capped = (d.get("stop_type") == "limit"
                  or bool(d.get("stopped_limit"))
                  or ("stop_type" not in d and "stopped_limit" not in d
                      and len(codes) >= MAX_CODES_PER_CHUNK))
        return codes, capped


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


def split_text(text: str, max_chars: int = 240) -> list:
    """Chunk long input to stay inside the trained per-utterance envelope, while
    MERGING short sentences so no chunk is a tiny out-of-distribution fragment.

    The model was trained on whole utterances; feeding it a 2-word fragment like
    "What's up?" makes it ramble and hallucinate (pseudo-foreign gibberish) to
    fill space — the mid-sentence garble reported on v2.0.0. So we greedily pack
    consecutive sentences up to max_chars (intra-utterance punctuation gives
    natural pauses), and only hard-split a single sentence that alone exceeds the
    cap. "Hey lads. What's up? Are you ready?" -> ONE chunk, not three."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    chunks = []
    cur = ""
    for sent in sentences:
        if len(sent) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            while len(sent) > max_chars:
                cut = sent.rfind(",", 0, max_chars)
                if cut < max_chars // 2:
                    cut = sent.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                chunks.append(sent[:cut + 1].strip())
                sent = sent[cut + 1:].strip()
            cur = sent
        elif cur and len(cur) + 1 + len(sent) > max_chars:
            chunks.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip() if cur else sent
    if cur:
        chunks.append(cur)
    return chunks


def is_derailed(codes: list, capped: bool) -> bool:
    """Greedy-drone detector: True when generation was cut off by the length cap
    AND the tail has collapsed to a few repeating values. A chunk that terminates
    on its own, or caps while still diverse, is not a derail."""
    if not capped or len(codes) < DERAIL_TAIL:
        return False
    return len(set(codes[-DERAIL_TAIL:])) < DERAIL_TAIL_UNIQ_MIN


def drone_onset(codes: list):
    """Index where the sustained tone at the END of `codes` begins, or None if
    the tail is not droning.

    Two passes, because a single sliding window is not precise enough on its own:
      1. Walk BACK from the end while windows stay collapsed. This finds the
         start of the collapsed region — but a window straddling the boundary
         goes collapsed while it still holds real speech, so this over-reaches
         by up to DRONE_TRIM_WIN codes.
      2. Walk FORWARD from there to the first window drawn entirely from the
         drone's own value set — taken from the FINAL window, which is pure tone,
         not from the collapsed region, which still holds the speech that ran
         into it. That is the true onset, so the speech before it stays intact."""
    n = len(codes)
    if n < DRONE_TRIM_WIN:
        return None

    def collapsed(i):
        w = codes[i:i + DRONE_TRIM_WIN]
        return len(set(w)) / len(w) < DRONE_TRIM_RATIO

    i = n - DRONE_TRIM_WIN
    if not collapsed(i):
        return None
    while i > 0 and collapsed(i - 1):
        i -= 1

    drone_values = set(codes[-DRONE_TRIM_WIN:])
    for j in range(i, n):
        if set(codes[j:j + DRONE_TRIM_WIN]) <= drone_values:
            return j
    return i        # cycle longer than the window — fall back to the region start


def trim_drone(codes: list) -> list:
    """Cut the sustained tone off the end, keeping the speech before it. Returns
    the codes unchanged when no drone is found; may return a very short list (or
    an empty one) when the chunk droned from the start — the caller decides what
    is too short to be worth decoding (DRONE_MIN_KEEP)."""
    onset = drone_onset(codes)
    return codes if onset is None else codes[:onset]


class Engine:
    """Owns the full pipeline and a serialized generation slot."""

    def __init__(self, llama: LlamaServer, decoder: OnnxDecoder, phonemizer: Phonemizer):
        self.llama = llama
        self.decoder = decoder
        self.phonemize = phonemizer
        self.gen_lock = threading.Lock()
        self.progress = {"phase": "idle", "chunk": 0, "chunks": 0, "started": None}
        self.guard_events = []   # derail guard activity, surfaced in /diagnostics

    def _gap(self) -> np.ndarray:
        return np.zeros(int(SENTENCE_JOIN_SILENCE_S * SAMPLE_RATE), dtype=np.float32)

    def _codes_for(self, text: str) -> tuple:
        """Phonemize one span and run one greedy generation -> (codes, capped)."""
        phones = self.phonemize(text)
        prompt = (
            "user: Convert the text to speech:"
            f"<|TEXT_PROMPT_START|>{phones}<|TEXT_PROMPT_END|>\n"
            "assistant:<|SPEECH_GENERATION_START|>"
        )
        return self.llama.complete(prompt)

    def _note(self, action: str, text: str, **extra):
        ev = {"action": action, "text": text[:80], "at": time.time()}
        ev.update(extra)
        self.guard_events.append(ev)
        del self.guard_events[:-20]      # keep the last 20 only
        print(f"[derail-guard] {action}: {ev}", file=sys.stderr, flush=True)

    def _audio_for(self, text: str, depth: int = 0) -> list:
        """Waveform pieces for one chunk, guarded against both ways a generation
        can hit the code budget instead of finishing.

        A chunk that stops on <|SPEECH_GENERATION_END|> is healthy and ships as
        is. A chunk that stops on the budget did NOT finish, in one of two ways:

          * DERAILED — greedy decoding locked into a repeating code and was
            droning ("EEEE"); it would never have stopped on its own.
          * TRUNCATED — genuine speech that simply needs more than 1024 codes.
            split_text caps chunks by CHARACTERS, but the budget is in TIME, and
            the two disagree on slow content (spelled digits, long numbers). The
            tail of the sentence is then silently missing from the audio.

        Both have the same fix: re-split the span tighter and regenerate, which
        gives each piece its own full budget (and, for a derail, a shorter prompt
        that shifts the deterministic argmax path off the drone).

        Only when the span can no longer be split do the two diverge — a derail's
        tone is trimmed off, or dropped for silence if nothing survives, because
        twenty seconds of sustained tone is what users actually complain about;
        a truncation keeps the real speech it managed to produce."""
        codes, capped = self._codes_for(text)
        if not capped:
            return [self.decoder.decode(codes)]

        derailed = is_derailed(codes, capped)
        if depth < len(RESPLIT_CHARS):
            subs = split_text(text, max_chars=RESPLIT_CHARS[depth])
            if len(subs) > 1:
                self._note("resplit", text, pieces=len(subs),
                           reason="derail" if derailed else "truncated")
                out = []
                for k, s in enumerate(subs):
                    if k:
                        out.append(self._gap())
                    out.extend(self._audio_for(s, depth + 1))
                return out

        if derailed:
            kept = trim_drone(codes)
            if len(kept) < DRONE_MIN_KEEP:
                self._note("dropped", text, codes=len(codes))
                return [self._gap()]
            self._note("trimmed", text, kept=len(kept), of=len(codes))
            return [self.decoder.decode(kept)]

        self._note("truncated", text, codes=len(codes))
        return [self.decoder.decode(codes)]

    def generate(self, text: str) -> np.ndarray:
        text = normalize(text)
        chunks = split_text(text)
        if not chunks:
            raise EngineError("no speakable text in input")
        pieces = []
        with self.gen_lock:
            self.progress = {"phase": "generating", "chunk": 0,
                             "chunks": len(chunks), "started": time.time()}
            try:
                for i, chunk in enumerate(chunks):
                    self.progress["chunk"] = i + 1
                    pieces.extend(self._audio_for(chunk))
                    if i < len(chunks) - 1:
                        pieces.append(self._gap())
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
