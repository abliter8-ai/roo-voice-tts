#!/usr/bin/env python3
"""Exercise the frozen sidecar with fresh data, real audio and persisted history."""
import argparse
import array
import io
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import wave

SHORT = "Hello. This is Roo, speaking from the model included with this application."
PARAGRAPH = ("Version A has the exact same information as version B, but it is harder "
             "to read because it is less cohesive. Each sentence in version B begins "
             "with old information and bridges to new information. The first sentence "
             "establishes the key idea of balance theory. The next sentence begins with "
             "balance theory and ends with social ties, which is the focus of the third "
             "sentence. The concept of weak ties connects the third and fourth sentences "
             "and the concept of cliques the fifth and sixth sentences. In Version A, "
             "in contrast, the first sentence focuses on balance theory, but then the "
             "second sentence makes a new point about social ties before telling the "
             "reader that the point comes from balance theory.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backend", default="CPU")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / "fresh profile with spaces"
    if data.exists():
        raise RuntimeError("Smoke output must contain a fresh profile; choose a new output directory")
    data.mkdir()
    # A legacy cache and history entry must survive, and must never select v2 weights.
    (data / "models").mkdir()
    legacy_model = data / "models" / "roo-neutts-q4.gguf"
    legacy_model.write_bytes(b"legacy cache preserved, never opened for inference")
    (data / "history").mkdir()
    legacy_wav = io.BytesIO()
    with wave.open(legacy_wav, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 2400)
    (data / "history" / "legacy.wav").write_bytes(legacy_wav.getvalue())
    (data / "history" / "index.jsonl").write_text(json.dumps({
        "id": "legacy", "text": "Existing saved clip", "ts": 1,
        "duration_s": 0.1, "gen_s": 1}) + "\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env["GGML_BACKEND"] = args.backend
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = env["NO_PROXY"]
    command = [str(Path(args.engine).resolve()), "--manifest",
               str(Path(args.manifest).resolve()), "--data-dir", str(data),
               "--port", str(port)]
    evidence = {"backendRequested": args.backend, "runs": [], "command": command}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            response = opener.open(req, timeout=600)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read(), dict(response.headers)

    process = None
    log = open(output / "sidecar.log", "wb")

    def start():
        nonlocal process
        before = time.monotonic()
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        deadline = before + 600
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Sidecar exited {process.returncode}; see sidecar.log")
            try:
                code, body, _ = request("/healthz")
                state = json.loads(body)
                if state["status"] == "failed":
                    raise RuntimeError(str(state))
                if code == 200:
                    assert state["version"] == "3.0.0", state
                    assert state["model"] == "Qwen3-TTS-12Hz-0.6B-Base", state
                    assert args.backend.lower() in state["backend"].lower(), state
                    return {"seconds": time.monotonic() - before, "state": state}
            except (ConnectionError, urllib.error.URLError):
                pass
            time.sleep(0.25)
        raise RuntimeError("Sidecar did not become ready within 600 seconds")

    def stop():
        nonlocal process
        if process is None:
            return
        if process.poll() is None:
            request("/shutdown", {})
            process.wait(timeout=20)
        assert process.returncode == 0, process.returncode
        process = None

    try:
        evidence["firstLoad"] = start()
        for name, text in (("short", SHORT), ("short-repeat", SHORT), ("paragraph", PARAGRAPH)):
            before = time.monotonic()
            code, body, headers = request("/v1/audio/speech", {"input": text, "title": name})
            seconds = time.monotonic() - before
            assert code == 200, (code, body[:500])
            with wave.open(io.BytesIO(body), "rb") as wav:
                assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
                count = wav.getnframes()
                samples = array.array("h", wav.readframes(count))
                assert len(samples) == count
                duration = count / 24000
                assert 1 < duration < 100, duration
                rms = math.sqrt(sum(float(x) ** 2 for x in samples) / count) / 32768
                assert rms > 0.002, rms
            (output / f"{name}.wav").write_bytes(body)
            hid = headers["X-History-Id"]
            assert request(f"/history/{hid}.wav")[1] == body
            result = {"name": name, "text": text, "generationSeconds": seconds,
                      "audioSeconds": duration, "rtf": seconds / duration, "rms": rms,
                      "historyId": hid}
            evidence["runs"].append(result)
            print(json.dumps(result), flush=True)
        evidence["diagnostics"] = json.loads(request("/diagnostics")[1])
        assert evidence["diagnostics"]["native_alive"]
        before_history = json.loads(request("/history")[1])
        assert len(before_history) == 4
        stop()
        # The native listener address is in the native log. It must be closed.
        native_log = (data / "tts-server.log").read_text(errors="replace")
        assert "icl=yes" in native_log, "Native log did not confirm full reference conditioning"
        import re
        listeners = re.findall(r"127\.0\.0\.1:(\d+)", native_log)
        for native_port in set(listeners):
            with socket.socket() as sock:
                sock.settimeout(1)
                assert sock.connect_ex(("127.0.0.1", int(native_port))) != 0, "Orphan native listener"
        evidence["restart"] = start()
        assert json.loads(request("/history")[1]) == before_history
        assert legacy_model.read_bytes() == b"legacy cache preserved, never opened for inference"
        assert (data / "history" / "legacy.wav").read_bytes() == legacy_wav.getvalue()
        evidence["historyPreserved"] = True
        evidence["passed"] = True
    finally:
        try:
            stop()
        finally:
            log.close()
            (output / "timings.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
