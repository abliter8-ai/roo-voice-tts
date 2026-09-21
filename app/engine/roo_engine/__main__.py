"""Entry point for the bundled Qwen3-TTS Roo2 sidecar."""
import argparse
import json
import os
import signal
import sys
import threading
import time

from .engine import (Engine, EngineError, NativeTTSServer, QWEN_MODEL,
                     QWEN_RUNTIME_COMMIT, pick_port, resolve_assets)
from .server import History, diagnostics_factory, serve, set_state


def bundle_dir():
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))


def resolve_manifest(args):
    return os.path.abspath(args.manifest) if args.manifest else os.path.join(bundle_dir(), "manifest.json")


def resolve_native_bin(args):
    if args.native_bin:
        return os.path.abspath(args.native_bin)
    root = bundle_dir()
    for name in ("tts-server", "tts-server.exe"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    raise EngineError("native tts-server binary not found; pass --native-bin")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--manifest", help="bundled manifest (defaults beside the binary)")
    parser.add_argument("--native-bin", help="native tts-server path (for tests/dev)")
    args = parser.parse_args()
    os.makedirs(args.data_dir, exist_ok=True)
    native_ref = {"server": None}

    def shutdown(*_):
        if native_ref["server"]:
            native_ref["server"].stop()
        time.sleep(0.2)
        os._exit(0)

    app = {"engine": None, "history": History(args.data_dir),
           "diagnostics": lambda: {"state": "starting"}, "shutdown": shutdown}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    port = args.port or pick_port(preferred=(8321, 8765, 8808))
    serve(app, port)
    print(json.dumps({"port": port}), flush=True)

    def bring_up():
        native = None
        try:
            manifest_path = resolve_manifest(args)
            assets = resolve_assets(manifest_path, resolve_native_bin(args))
            with open(manifest_path, encoding="utf-8") as stream:
                manifest = json.load(stream)
            set_state(status="loading", model=manifest.get("model", QWEN_MODEL))
            native = NativeTTSServer(
                assets["native_bin"], assets["talker"], assets["codec"],
                assets["speaker"], assets["reference_codes"], assets["reference_text"],
                os.path.join(args.data_dir, "tts-server.log"),
                manifest.get("runtime_commit", QWEN_RUNTIME_COMMIT))
            native_ref["server"] = native
            native.start()
            app["diagnostics"] = diagnostics_factory(args.data_dir, native, app)
            engine = Engine(native)
            set_state(status="warming")
            engine.generate("This is the voice engine warming up its compute pipelines.")
            app["engine"] = engine
            set_state(status="ready", detail="", backend=native.backend_evidence())
        except BaseException as exc:
            set_state(status="failed", detail=f"{type(exc).__name__}: {exc}")
            if native:
                native.stop()

    threading.Thread(target=bring_up, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
