"""roo-engine entrypoint.

    python -m roo_engine --data-dir DIR [--port 0] [--llama-bin PATH]
                         [--gguf PATH] [--onnx PATH]

Announces `{"port": N}` on stdout once the HTTP surface is listening (the Tauri
shell reads that line), then brings the pipeline up in the background:
download (if a manifest is present) -> load -> warm -> ready. The UI polls
/healthz and never sees a dead socket (v1.1.1 warm-up doctrine: first request
must not pay the backend compile).
"""
import argparse
import json
import os
import signal
import sys
import threading
import time

from .engine import Engine, LlamaServer, OnnxDecoder, Phonemizer, pick_port
from .server import History, diagnostics_factory, download, serve, set_state


def resolve_models(args):
    """Explicit paths win; otherwise look in data-dir/models; otherwise download
    per manifest ({gguf: {url, sha256}, onnx: {url, sha256}}) — the data-dir copy
    wins over the app-bundled one (--manifest) so users can pin models."""
    mdir = os.path.join(args.data_dir, "models")
    os.makedirs(mdir, exist_ok=True)
    paths = {"gguf": args.gguf, "onnx": args.onnx}
    defaults = {"gguf": os.path.join(mdir, "roo-neutts.gguf"),
                "onnx": os.path.join(mdir, "neucodec-decoder.onnx")}
    manifest = {}
    mpath = os.path.join(mdir, "manifest.json")
    if not os.path.exists(mpath) and args.manifest and os.path.exists(args.manifest):
        mpath = args.manifest
    if os.path.exists(mpath):
        with open(mpath) as f:
            manifest = json.load(f)
    for key in ("gguf", "onnx"):
        if paths[key]:
            continue
        if os.path.exists(defaults[key]):
            paths[key] = defaults[key]
        elif key in manifest and manifest[key].get("url"):
            download(manifest[key]["url"], defaults[key],
                     manifest[key].get("sha256"), label=key)
            paths[key] = defaults[key]
        else:
            raise SystemExit(f"no {key} model: pass --{key}, place {defaults[key]}, "
                             f"or provide {mpath}")
    return paths


def find_llama_bin(explicit):
    if explicit:
        return explicit
    # Frozen layout: llama-server ships beside the engine binary.
    here = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    for cand in (os.path.join(here, "llama-server"),
                 os.path.join(here, "llama-server.exe"),
                 "/opt/homebrew/bin/llama-server"):
        if os.path.exists(cand):
            return cand
    raise SystemExit("llama-server binary not found; pass --llama-bin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--llama-bin")
    ap.add_argument("--gguf")
    ap.add_argument("--onnx")
    ap.add_argument("--manifest", help="bundled model-manifest fallback (see resolve_models)")
    ap.add_argument("--phonemize", metavar="TEXT",
                    help="print en-gb phonemes for TEXT and exit "
                         "(the IP-178 phoneme-parity gate probes this)")
    args = ap.parse_args()

    if args.phonemize is not None:
        print(Phonemizer()(args.phonemize))
        return
    if not args.data_dir:
        ap.error("--data-dir is required")
    os.makedirs(args.data_dir, exist_ok=True)

    port = args.port or pick_port(preferred=(8321, 8765, 8808))
    llama_ref = {"llama": None}

    def shutdown(*_):
        if llama_ref["llama"]:
            llama_ref["llama"].stop()
        time.sleep(0.2)
        os._exit(0)

    app = {"engine": None, "history": History(args.data_dir),
           "diagnostics": lambda: {"state": "starting"}, "shutdown": shutdown}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    serve(app, port)
    print(json.dumps({"port": port}), flush=True)

    def bring_up():
        llama = None
        try:
            paths = resolve_models(args)
            set_state(status="loading", model=os.path.basename(paths["gguf"]))
            phonemizer = Phonemizer()          # fails fast if espeak is missing
            decoder = OnnxDecoder(paths["onnx"])
            llama = LlamaServer(find_llama_bin(args.llama_bin), paths["gguf"],
                                os.path.join(args.data_dir, "llama-server.log"))
            llama_ref["llama"] = llama   # visible to shutdown BEFORE start
            llama.start()
            app["diagnostics"] = diagnostics_factory(args.data_dir, llama)
            engine = Engine(llama, decoder, phonemizer)
            set_state(status="warming")
            # Pay ALL backend compile before ready. A short warm-up only builds
            # decode-shaped pipelines; batched-prefill pipelines compile on the
            # first real-sized prompt (ultra/Vulkan: 13 tok/s cold vs 18k warm —
            # a 13 s stall on the user's first request). Warm with a full
            # sentence so prefill compiles here, behind the progress UI.
            engine.generate("This is the voice engine warming up its compute "
                            "pipelines so your first request starts instantly.")
            app["engine"] = engine
            set_state(status="ready", detail="")
        except BaseException as e:
            set_state(status="failed", detail=f"{type(e).__name__}: {e}")
            if llama:
                llama.stop()

    threading.Thread(target=bring_up, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
