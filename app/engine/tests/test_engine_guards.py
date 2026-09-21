import base64
import hashlib
import json
import os
import tempfile
import unittest
import wave
from io import BytesIO
from unittest import mock

import numpy as np

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from roo_engine.engine import (Engine, EngineError, NativeTTSServer, QWEN_MODEL,
                               _read_wav, resolve_assets, split_text, wav_bytes)


def wav_fixture(samples=24):
    return wav_bytes(np.ones(samples, dtype=np.float32) * 0.1)


class TestBundledAssets(unittest.TestCase):
    def test_resolves_and_verifies_relative_assets(self):
        with tempfile.TemporaryDirectory() as root:
            names = {"talker": "models/talker.gguf", "codec": "models/codec.gguf",
                     "speaker": "voice/roo2/reference.spk",
                     "reference_codes": "voice/roo2/reference.rvq",
                     "reference_text": "voice/roo2/reference.txt"}
            entries = {}
            for key, rel in names.items():
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                data = (key + "-fixture").encode()
                with open(path, "wb") as stream:
                    stream.write(data)
                entries[key] = {"path": rel, "bytes": len(data),
                                "sha256": hashlib.sha256(data).hexdigest()}
            manifest = os.path.join(root, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump({"schema": 3, "model": QWEN_MODEL, "mode": "full",
                           "assets": entries}, stream)
            resolved = resolve_assets(manifest, "/tmp/tts-server")
            self.assertEqual(resolved["talker"], os.path.normpath(os.path.join(root, names["talker"])))
            self.assertEqual(resolved["native_bin"], "/tmp/tts-server")
            with open(os.path.join(root, names["codec"]), "ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaisesRegex(EngineError, "verification failed"):
                resolve_assets(manifest)

    def test_missing_asset_fails_without_download(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = os.path.join(root, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump({"schema": 3, "model": QWEN_MODEL, "mode": "full",
                           "assets": {"talker": {"path": "missing"}}}, stream)
            with self.assertRaisesRegex(EngineError, "missing a required"):
                resolve_assets(manifest)


class FakeNative(NativeTTSServer):
    def __init__(self, files):
        super().__init__("/fake/tts-server", "talker", "codec", *files, "/tmp/fake-tts.log")
        self.requests = []
        self.voice_registered = False

    def _request(self, path, body=None, timeout=30):
        self.requests.append((path, body))
        if path == "/v1/audio/voices":
            return 200, b"{}", {}
        if path == "/v1/audio/speech":
            return 200, wav_fixture(48), {"Content-Length": str(len(wav_fixture(48)))}
        return 200, b"{}", {}


class TestNativeAdapter(unittest.TestCase):
    def test_native_child_uses_host_libraries_outside_frozen_linux_runtime(self):
        cases = [
            ("linux", True, {"LD_LIBRARY_PATH": "/bundle/_internal"}, None),
            ("linux", True, {"LD_LIBRARY_PATH": "/bundle/_internal:/host/lib",
                             "LD_LIBRARY_PATH_ORIG": "/host/lib"}, "/host/lib"),
            ("linux", False, {"LD_LIBRARY_PATH": "/developer/lib"}, "/developer/lib"),
            ("darwin", True, {"LD_LIBRARY_PATH": "/unchanged"}, "/unchanged"),
        ]
        for platform, frozen, library_env, expected in cases:
            with self.subTest(platform=platform, frozen=frozen, library_env=library_env):
                with tempfile.TemporaryDirectory() as root:
                    binary = os.path.join(root, "tts-server")
                    with open(binary, "wb") as stream:
                        stream.write(b"fixture")
                    native = NativeTTSServer(binary, "talker", "codec", "spk", "rvq", "txt",
                                             os.path.join(root, "tts.log"))
                    native._request = mock.Mock(return_value=(200, b"{}", {}))
                    native.register_voice = mock.Mock()
                    original = {**library_env, "GGML_BACKEND": "Vulkan0"}
                    with mock.patch.dict(os.environ, original, clear=True), \
                         mock.patch("sys.platform", platform), \
                         mock.patch("sys.frozen", frozen, create=True), \
                         mock.patch("roo_engine.engine.subprocess.Popen") as launch:
                        launch.return_value.poll.return_value = None
                        try:
                            native.start()
                            child_env = launch.call_args.kwargs.get("env", os.environ)
                            self.assertEqual(child_env.get("LD_LIBRARY_PATH"), expected)
                            self.assertEqual(child_env["GGML_BACKEND"], "Vulkan0")
                            self.assertEqual(dict(os.environ), original)
                        finally:
                            native.stop()

    def test_registers_full_reference_and_synthesizes_expected_request(self):
        with tempfile.TemporaryDirectory() as root:
            paths = []
            for name, data in (("spk", b"speaker"), ("rvq", b"codes"), ("txt", b"Roo reference.")):
                path = os.path.join(root, name)
                with open(path, "wb") as stream:
                    stream.write(data)
                paths.append(path)
            native = FakeNative(paths)
            native.register_voice()
            audio = native.synthesize("Hello world.")
            registration = native.requests[0][1]
            request = native.requests[1][1]
            self.assertEqual(registration["name"], "roo")
            self.assertEqual(base64.b64decode(registration["spk_b64"]), b"speaker")
            self.assertEqual(base64.b64decode(registration["rvq_b64"]), b"codes")
            self.assertEqual(registration["ref_text"], "Roo reference.")
            self.assertEqual(request, {"input": "Hello world.", "voice": "roo",
                                       "response_format": "wav", "seed": 42,
                                       "max_new_tokens": 2048})
            self.assertEqual(len(audio), 48)

    def test_rejects_truncated_or_invalid_wav(self):
        with self.assertRaisesRegex(EngineError, "truncated"):
            _read_wav(wav_fixture()[:-2])
        with self.assertRaisesRegex(EngineError, "24 kHz"):
            bad = BytesIO()
            with wave.open(bad, "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0")
            _read_wav(bad.getvalue())

    def test_rejects_generation_at_native_token_cap(self):
        native = NativeTTSServer("/fake", "talker", "codec", "spk", "rvq", "txt", "/tmp/log")
        native.voice_registered = True
        capped = wav_fixture(2048 * 1920)
        native._request = mock.Mock(return_value=(200, capped, {"Content-Length": str(len(capped))}))
        with self.assertRaisesRegex(EngineError, "max_new_tokens"):
            native.synthesize("This may be truncated.")

    def test_backend_evidence_reads_load_lines_only(self):
        with tempfile.TemporaryDirectory() as root:
            log = os.path.join(root, "tts.log")
            with open(log, "w", encoding="utf-8") as stream:
                stream.write("[Load] Talker backend: Metal (CPU threads: 8)\n")
                stream.write("[Load] Codec backend: Vulkan (CPU threads: 8)\n")
                stream.write("[Server] request backend: CPU\n")
            native = NativeTTSServer("/fake", "talker", "codec", "spk", "rvq", "txt", log)
            self.assertEqual(native.backend_evidence(), "Talker=Metal; Codec=Vulkan")

    def test_lifecycle_stops_child(self):
        native = NativeTTSServer("/fake", "talker", "codec", "spk", "rvq", "txt", "/tmp/log")
        native.proc = mock.Mock()
        process = native.proc
        process.poll.return_value = None
        native.voice_registered = True
        native.stop()
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)
        self.assertIsNone(native.proc)
        self.assertFalse(native.voice_registered)


class TestEngine(unittest.TestCase):
    def test_sentence_aware_merge_and_complete_join(self):
        native = mock.Mock()
        native.synthesize.side_effect = [np.ones(24, dtype=np.float32),
                                          np.ones(24, dtype=np.float32) * 2]
        engine = Engine(native)
        output = engine.generate("First sentence. Second sentence.")
        self.assertEqual(native.synthesize.call_count, 1)
        self.assertEqual(len(output), 24)

        native.synthesize.reset_mock()
        native.synthesize.side_effect = lambda _text: np.ones(24, dtype=np.float32)
        output = engine.generate("First sentence. " + "x " * 400)
        self.assertGreaterEqual(native.synthesize.call_count, 2)
        self.assertGreater(len(output), 48)

    def test_split_text_keeps_short_sentences_together(self):
        self.assertEqual(split_text("One. Two. Three."), ["One. Two. Three."])


if __name__ == "__main__":
    unittest.main()
