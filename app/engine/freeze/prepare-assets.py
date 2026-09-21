#!/usr/bin/env python3
"""Build-time asset staging. The installed app never calls this downloader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request

HERE = Path(__file__).resolve().parent


def verify(path, spec):
    if not path.is_file() or path.stat().st_size != spec["bytes"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == spec["sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Verify the installed bundle without network access")
    args = parser.parse_args()
    manifest_path = args.output / "manifest.json" if args.check else HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["schema"] != 3 or manifest["mode"] != "full":
        raise ValueError("Expected the complete Roo2 Full Clone manifest")
    cache = Path(os.environ.get("ROO_ASSET_CACHE", str(Path.home() / ".cache/roo-voice-v3"))) / manifest["model_revision"]
    for key, spec in manifest["assets"].items():
        relative = Path(spec["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Asset path must remain inside the bundle")
        destination = args.output / relative
        if verify(destination, spec):
            print(f"Verified {key}: {spec['bytes']} bytes", flush=True)
            continue
        if args.check:
            raise ValueError(f"Missing or corrupt bundled asset: {relative}")
        if key in ("talker", "codec"):
            source = args.model_dir / relative.name if args.model_dir else cache / relative.name
            if not verify(source, spec):
                if args.model_dir:
                    raise ValueError(f"Supplied model failed checksum: {source}")
                source.parent.mkdir(parents=True, exist_ok=True)
                part = source.with_suffix(source.suffix + ".part")
                print(f"Downloading pinned build asset: {relative.name}", flush=True)
                request = urllib.request.Request(spec["url"], headers={"User-Agent": "roo-voice-build/3.0.0"})
                with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as output:
                    shutil.copyfileobj(response, output, 4 * 1024 * 1024)
                if not verify(part, spec):
                    raise ValueError(f"Downloaded model failed checksum: {part}")
                if source.exists():
                    source.rename(source.with_name(source.name + f".invalid-{time.time_ns()}"))
                part.replace(source)
        else:
            source = HERE.parent / relative
            if not verify(source, spec):
                raise ValueError(f"Packaged voice source failed checksum: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if not verify(destination, spec):
            raise ValueError(f"Staged asset failed checksum: {relative}")
        print(f"Staged {key}: {spec['bytes']} bytes", flush=True)
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
        # Runtime manifest has no URLs: missing installed files cannot trigger a download.
        for spec in manifest["assets"].values():
            spec.pop("url", None)
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("All Qwen weights and Full Clone assets verified.", flush=True)


if __name__ == "__main__":
    main()
