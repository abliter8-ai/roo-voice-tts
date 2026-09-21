"""Resident Qwen3-TTS adapter and Roo sidecar generation pipeline."""
import base64
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

import numpy as np

SAMPLE_RATE = 24000
SENTENCE_JOIN_SILENCE_S = 0.15
QWEN_MODEL = "Qwen3-TTS-12Hz-0.6B-Base"
QWEN_ALIAS = "qwen3-tts-base"
QWEN_VOICE = "roo"
QWEN_RUNTIME_COMMIT = "0bfb9237c1aae55f6d279fc7e32b3416a6dbb93a"
SAMPLES_PER_TOKEN = 1920


class EngineError(RuntimeError):
    pass


def pick_port(preferred=()):
    def free(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            sock.close()
    for port in preferred:
        if free(port):
            return port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def split_text(text: str, max_chars: int = 600) -> list:
    """Pack complete sentences and hard-split only an overlong sentence."""
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]
    chunks, current = [], ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            while len(sentence) > max_chars:
                cut = sentence.rfind(",", 0, max_chars)
                if cut < max_chars // 2:
                    cut = sentence.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                chunks.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            current = sentence
        elif current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        chunks.append(current)
    return chunks


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_assets(manifest_path: str, native_bin: str = None) -> dict:
    """Resolve and verify every local asset in the v3 manifest. No downloads."""
    if not manifest_path or not os.path.isfile(manifest_path):
        raise EngineError(f"bundled asset manifest not found: {manifest_path or '<unset>'}")
    try:
        with open(manifest_path, encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, ValueError) as exc:
        raise EngineError(f"cannot read bundled asset manifest: {exc}") from exc
    if manifest.get("schema") != 3:
        raise EngineError("unsupported bundled asset manifest schema; expected 3")
    if manifest.get("model") != QWEN_MODEL or manifest.get("mode") != "full":
        raise EngineError("bundled manifest is not the Qwen Roo2 Full Clone contract")
    entries = manifest.get("assets")
    required = ("talker", "codec", "speaker", "reference_codes", "reference_text")
    if not isinstance(entries, dict) or any(key not in entries for key in required):
        raise EngineError("bundled asset manifest is missing a required asset entry")
    root = os.path.dirname(os.path.abspath(manifest_path))
    resolved = {"manifest": os.path.abspath(manifest_path)}
    for key in required:
        entry = entries[key]
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise EngineError(f"invalid manifest entry for {key}")
        path = os.path.abspath(os.path.join(root, entry["path"]))
        if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
            raise EngineError(f"bundled asset missing for {key}: {entry['path']}")
        expected_bytes = entry.get("bytes")
        expected_hash = entry.get("sha256")
        actual_bytes = os.path.getsize(path)
        actual_hash = _sha256(path)
        if actual_bytes != expected_bytes or actual_hash.lower() != str(expected_hash).lower():
            raise EngineError(f"bundled asset verification failed for {key}: expected "
                              f"{expected_bytes} bytes/{expected_hash}, got "
                              f"{actual_bytes} bytes/{actual_hash}")
        resolved[key] = path
    if native_bin:
        resolved["native_bin"] = native_bin
    return resolved


def _read_wav(data: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != SAMPLE_RATE:
                raise EngineError("native response is not mono 24 kHz PCM16 WAV")
            frames = wav.getnframes()
            payload = wav.readframes(frames)
            if len(payload) != frames * 2:
                raise EngineError("native WAV response is truncated")
    except (wave.Error, EOFError) as exc:
        raise EngineError(f"invalid native WAV response: {exc}") from exc
    if not payload:
        raise EngineError("native server returned an empty WAV")
    return np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32767.0


class NativeTTSServer:
    """Supervise one loopback qwentts.cpp server and its registered voice."""
    def __init__(self, bin_path, talker_path, codec_path, speaker_path,
                 reference_codes_path, reference_text_path, log_path,
                 runtime_commit=QWEN_RUNTIME_COMMIT):
        self.bin_path = bin_path
        self.talker_path = talker_path
        self.codec_path = codec_path
        self.speaker_path = speaker_path
        self.reference_codes_path = reference_codes_path
        self.reference_text_path = reference_text_path
        self.log_path = log_path
        self.runtime_commit = runtime_commit
        self.port = None
        self.proc = None
        self._log = None
        self.voice_registered = False

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _request(self, path, body=None, timeout=30):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self._url(path), data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise EngineError(f"native {path} returned HTTP {exc.code}: {detail[:400]}") from exc
        except OSError as exc:
            raise EngineError(f"native server request failed: {exc}") from exc

    def start(self, timeout_s=180):
        if self.proc is not None:
            self.stop()
        if not os.path.isfile(self.bin_path):
            raise EngineError(f"native tts-server binary not found: {self.bin_path}")
        self.port = pick_port()
        args = [self.bin_path, "--model", self.talker_path, "--codec", self.codec_path,
                "--alias", QWEN_ALIAS, "--port", str(self.port), "--host", "127.0.0.1"]
        env = os.environ.copy()
        if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
            # The system Vulkan driver needs host libraries, not PyInstaller's copies.
            if "LD_LIBRARY_PATH_ORIG" in env:
                env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            else:
                env.pop("LD_LIBRARY_PATH", None)
        self._log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(args, stdout=self._log, stderr=self._log, env=env)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise EngineError(f"tts-server exited rc={self.proc.returncode}; see {self.log_path}")
            try:
                status, _, _ = self._request("/health", timeout=2)
            except EngineError:
                status = 0
            if status == 200:
                # Registration is initialization, not a readiness probe. A
                # bad reference must fail immediately and visibly.
                self.register_voice()
                return
            time.sleep(0.25)
        self.stop()
        raise EngineError(f"native tts-server not healthy within {timeout_s}s; see {self.log_path}")

    def register_voice(self):
        with open(self.speaker_path, "rb") as stream:
            speaker = base64.b64encode(stream.read()).decode()
        with open(self.reference_codes_path, "rb") as stream:
            codes = base64.b64encode(stream.read()).decode()
        with open(self.reference_text_path, encoding="utf-8") as stream:
            reference_text = stream.read().strip()
        if not reference_text:
            raise EngineError("bundled Roo2 reference text is empty")
        self._request("/v1/audio/voices", {
            "name": QWEN_VOICE, "spk_b64": speaker, "rvq_b64": codes,
            "ref_text": reference_text,
        }, timeout=60)
        self.voice_registered = True

    def synthesize(self, text, seed=42, max_new_tokens=2048):
        if not self.voice_registered:
            raise EngineError("native Roo voice is not registered")
        _, data, headers = self._request("/v1/audio/speech", {
            "input": text, "voice": QWEN_VOICE, "response_format": "wav",
            "seed": seed, "max_new_tokens": max_new_tokens,
        }, timeout=600)
        content_length = headers.get("Content-Length")
        if content_length is not None and int(content_length) != len(data):
            raise EngineError("native response body is truncated")
        audio = _read_wav(data)
        if len(audio) >= max_new_tokens * SAMPLES_PER_TOKEN:
            raise EngineError("native generation reached max_new_tokens; output may be truncated")
        return audio

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def backend_evidence(self):
        """Return the backend reported by the native runtime log."""
        try:
            with open(self.log_path, "rb") as stream:
                text = stream.read(1024 * 1024).decode(errors="replace")
        except OSError:
            return "qwentts.cpp native (backend evidence unavailable)"
        matches = []
        for line in text.splitlines():
            match = re.search(r"\[Load\] (Talker|Codec) backend:\s*([^\s(]+)", line)
            if match:
                matches.append(f"{match.group(1)}={match.group(2)}")
        if matches:
            return "; ".join(dict.fromkeys(matches))
        return "qwentts.cpp native (backend evidence unavailable)"

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self._log:
            self._log.close()
            self._log = None
        self.proc = None
        self.voice_registered = False


class Engine:
    """Serialize synthesis and join sentence-aware native WAV responses."""
    def __init__(self, native):
        self.native = native
        self.gen_lock = threading.Lock()
        self.progress = {"phase": "idle", "chunk": 0, "chunks": 0, "started": None}
        self.guard_events = []

    def _gap(self):
        return np.zeros(int(SENTENCE_JOIN_SILENCE_S * SAMPLE_RATE), dtype=np.float32)

    def generate(self, text):
        chunks = split_text(text)
        if not chunks:
            raise EngineError("no speakable text in input")
        pieces = []
        with self.gen_lock:
            self.progress = {"phase": "generating", "chunk": 0,
                             "chunks": len(chunks), "started": time.time()}
            try:
                for index, chunk in enumerate(chunks):
                    self.progress["chunk"] = index + 1
                    pieces.append(self.native.synthesize(chunk))
                    if index < len(chunks) - 1:
                        pieces.append(self._gap())
            finally:
                self.progress = {"phase": "idle", "chunk": 0, "chunks": 0, "started": None}
        return np.concatenate(pieces)


def wav_bytes(samples: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()
