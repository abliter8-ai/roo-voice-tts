#!/usr/bin/env python3
"""Run freeze/smoke.py with external networking denied."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile

PROBE = (
    "import json,os,socket,sys; result={'target':'1.1.1.1:443'}; "
    "s=socket.socket(); s.settimeout(2); "
    "\ntry: s.connect(('1.1.1.1',443)); result['denied']=False; rc=17 "
    "\nexcept OSError as exc: result['denied']=True; result['error']=type(exc).__name__; rc=0 "
    "\nfinally: s.close(); open(os.environ['ROO_PROBE_EVIDENCE'],'w').write(json.dumps(result)+'\\n')\n"
    "if rc: sys.exit(rc)\n"
    "import runpy; smoke=sys.argv.pop(1); runpy.run_path(smoke, run_name='__main__')"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", required=True)
    return parser.parse_args()


def mac_profile(path: Path, resource_dir: Path | None = None) -> None:
    readonly = ""
    if resource_dir:
        quoted = str(resource_dir).replace("\\", "\\\\").replace('"', '\\"')
        readonly = f'(deny file-write* (subpath "{quoted}"))\n'
    rules = (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        + readonly
        + '(allow network-outbound (remote tcp "localhost:*"))\n'
        + '(allow network-outbound (remote udp "localhost:*"))\n'
        + '(allow network-inbound (local tcp "localhost:*"))\n'
        + '(allow network-inbound (local udp "localhost:*"))\n'
    )
    path.write_text(rules, encoding="utf-8")


def launcher(smoke: Path, smoke_args: list[str]) -> list[str]:
    return [sys.executable, "-c", PROBE, str(smoke), *smoke_args]


def run_mac(smoke: Path, smoke_args: list[str], env: dict[str, str], evidence: dict,
            resource_dir: Path) -> subprocess.Popen:
    profile_path = Path(tempfile.mkstemp(prefix="roo-offline-", suffix=".sb")[1])
    mac_profile(profile_path, resource_dir)
    evidence["restriction"] = {"kind": "sandbox-exec", "profile": str(profile_path),
                                "readonly_resource_dir": str(resource_dir)}
    return subprocess.Popen(["sandbox-exec", "-f", str(profile_path), *launcher(smoke, smoke_args)], env=env)


def run_linux(smoke: Path, smoke_args: list[str], env: dict[str, str], evidence: dict) -> subprocess.Popen:
    required = subprocess.run(["sh", "-c", "command -v unshare && command -v ip"], capture_output=True)
    if required.returncode:
        raise RuntimeError("Linux offline smoke requires unshare and ip")
    evidence["restriction"] = {"kind": "unshare", "namespace": "user+net", "loopback": "ip link set lo up"}
    return subprocess.Popen(
        ["unshare", "--user", "--map-root-user", "--net", "sh", "-c",
         "ip link set lo up; exec \"$@\"", "offline-smoke", *launcher(smoke, smoke_args)], env=env)


def firewall(program: Path, name: str, add: bool) -> None:
    action = "add" if add else "delete"
    command = ["netsh", "advfirewall", "firewall", action, "rule", f"name={name}"]
    if add:
        command += ["dir=out", "action=block", f"program={program}", "enable=yes", "profile=any",
                    "protocol=any", "remoteip=0.0.0.0-126.255.255.255,128.0.0.0-255.255.255.255,"
                    "0:0:0:0:0:0:0:0-0:ffff:ffff:ffff:ffff:ffff:ffff:ffff,"
                    "::/0"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "netsh failed")


def run_windows(smoke: Path, smoke_args: list[str], env: dict[str, str], evidence: dict,
                engine: Path) -> tuple[subprocess.Popen, list[str]]:
    native = engine.with_name("tts-server.exe")
    programs = [engine, native, Path(sys.executable)] if native.exists() else [engine, Path(sys.executable)]
    names = [f"RooVoiceOfflineSmoke-{os.getpid()}-{n}" for n in range(len(programs))]
    try:
        for name, program in zip(names, programs):
            firewall(program, name, True)
        evidence["restriction"] = {"kind": "windows-firewall", "programs": [str(p) for p in programs],
                                    "rules": names, "loopback": "127.0.0.0/8 and ::1 excluded"}
        return subprocess.Popen(launcher(smoke, smoke_args), env=env), names
    except Exception:
        for name in names:
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                           capture_output=True)
        raise


def main() -> int:
    opts = parse_args()
    smoke = Path(__file__).with_name("smoke.py").resolve()
    output = opts.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    probe_evidence = output / "offline-network.json"
    env = os.environ.copy()
    env["ROO_PROBE_EVIDENCE"] = str(probe_evidence)
    env["GGML_BACKEND"] = opts.backend
    smoke_args = ["--engine", str(opts.engine.resolve()), "--manifest", str(opts.manifest.resolve()),
                  "--output", str(output), "--backend", opts.backend]
    evidence = {"platform": platform.platform(), "backend": opts.backend, "engine": str(opts.engine),
                "manifest": str(opts.manifest), "smoke": str(smoke)}
    baseline = socket.socket()
    baseline.settimeout(3)
    try:
        baseline.connect(("1.1.1.1", 443))
        evidence["baseline_external_reachable"] = True
    except OSError as exc:
        evidence["baseline_external_reachable"] = False
        evidence["baseline_error"] = type(exc).__name__
        raise RuntimeError("baseline external endpoint is unreachable; denial is unproven") from exc
    finally:
        baseline.close()
    child = None
    names: list[str] = []
    try:
        if sys.platform == "darwin":
            child = run_mac(smoke, smoke_args, env, evidence, opts.engine.resolve().parent)
        elif sys.platform.startswith("linux"):
            child = run_linux(smoke, smoke_args, env, evidence)
        elif os.name == "nt":
            child, names = run_windows(smoke, smoke_args, env, evidence, opts.engine.resolve())
        else:
            raise RuntimeError(f"unsupported platform: {sys.platform}")
        code = child.wait()
        evidence["smoke_exit_code"] = code
        evidence["probe"] = json.loads(probe_evidence.read_text(encoding="utf-8"))
        if code:
            raise RuntimeError(f"packaged smoke exited with {code}")
        if not evidence["probe"].get("denied"):
            raise RuntimeError("external-network probe was not denied")
        return 0
    finally:
        for name in names:
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                           capture_output=True)
        (output / "offline-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n",
                                                       encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
