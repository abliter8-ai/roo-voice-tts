#!/usr/bin/env python3
"""Roo Voice — batch compose.

Generate several short lines through a running Roo Voice server (one request each,
queued), then stitch them into a single longer WAV with ffmpeg. This is how you
make long audio while keeping each generation short (~1 sentence, ~15 s), which is
where the voice sounds best.

Examples
--------
    # one line per line of a text file, 0.35 s pause between lines
    python tools/compose.py --infile script.txt --out story.wav

    # inline lines
    python tools/compose.py --text "After the last dance class..." "Could you ask Sarah..." --out out.wav

    # point at a remote server / tweak the gap
    python tools/compose.py --server http://localhost:8080 --infile script.txt --out out.wav --gap 0.5

Requires: ffmpeg on PATH (https://ffmpeg.org/download.html).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path


def read_lines(args) -> list[str]:
    if args.text:
        return [t.strip() for t in args.text if t.strip()]
    if args.infile:
        return [ln.strip() for ln in Path(args.infile).read_text(encoding="utf-8").splitlines() if ln.strip()]
    sys.exit("Provide --text \"...\" \"...\" or --infile script.txt")


def synth(server: str, text: str, out_path: Path) -> float:
    body = ('{"input": %s}' % _json_str(text)).encode("utf-8")
    req = urllib.request.Request(server.rstrip("/") + "/v1/audio/speech",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = resp.read()
        gen_s = resp.headers.get("X-Roo-Gen-Seconds")
    out_path.write_bytes(data)
    return float(gen_s) if gen_s else round(time.time() - t0, 1)


def _json_str(s: str) -> str:
    import json
    return json.dumps(s)


def silence_wav(path: Path, seconds: float, sample_rate: int = 24000) -> None:
    n = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-generate + ffmpeg-compose Roo audio")
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--infile")
    ap.add_argument("--text", nargs="*")
    ap.add_argument("--out", default="roo-composed.wav")
    ap.add_argument("--gap", type=float, default=0.35, help="pause between lines, seconds")
    ap.add_argument("--keep-parts", action="store_true", help="keep the per-line WAVs")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH. Install it: https://ffmpeg.org/download.html")

    lines = read_lines(args)
    print(f"Composing {len(lines)} line(s) via {args.server} -> {args.out}")

    work = Path(tempfile.mkdtemp(prefix="roo-compose-"))
    parts: list[Path] = []
    total_gen = 0.0
    gap = work / "_gap.wav"
    if args.gap > 0:
        silence_wav(gap, args.gap)

    for i, line in enumerate(lines, 1):
        p = work / f"part-{i:03d}.wav"
        print(f"  [{i}/{len(lines)}] {line[:60]}{'…' if len(line) > 60 else ''}", flush=True)
        gs = synth(args.server, line, p)
        total_gen += gs
        print(f"        {gs:.1f}s", flush=True)
        parts.append(p)
        if args.gap > 0 and i < len(lines):
            parts.append(gap)

    # ffmpeg concat demuxer
    listfile = work / "concat.txt"
    listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c", "copy", str(args.out)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with wave.open(args.out) as w:
        dur = w.getnframes() / w.getframerate()
    print(f"\nDone: {args.out}  ({dur:.1f}s audio, {total_gen:.0f}s to generate)")
    if args.keep_parts:
        print(f"Per-line WAVs kept in: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
