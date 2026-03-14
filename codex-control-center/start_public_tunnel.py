from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path


URL_PATTERN = re.compile(r"https://[A-Za-z0-9.-]+")
SSH_PATH = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")


def stop_existing_localhost_run_tunnels() -> None:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'ssh.exe' -and $_.CommandLine -like '*localhost.run*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    for token in completed.stdout.split():
        if token.isdigit():
            subprocess.run(
                ["taskkill", "/PID", token, "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )


def read_public_url(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "tunneled with tls termination" not in line:
            continue
        match = URL_PATTERN.search(line)
        if match:
            return match.group(0)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Start localhost.run public tunnel for Codex Control Center")
    parser.add_argument("--target", default="127.0.0.1:8787")
    parser.add_argument("--wait-seconds", type=int, default=15)
    args = parser.parse_args()

    state_root = Path(__file__).resolve().parent / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    log_path = state_root / "public_tunnel.log"
    pid_path = state_root / "public_tunnel.pid"
    status_path = state_root / "public_tunnel_status.json"

    stop_existing_localhost_run_tunnels()
    if log_path.exists():
        log_path.unlink()

    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                str(SSH_PATH),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ServerAliveInterval=30",
                "-R",
                f"80:{args.target}",
                "nokey@localhost.run",
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=0x00000008,
        )

    pid_path.write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + max(args.wait_seconds, 1)
    public_url = ""
    while time.time() < deadline:
        public_url = read_public_url(log_path)
        if public_url:
            break
        time.sleep(1)

    status = {
        "ok": bool(public_url),
        "pid": proc.pid,
        "target": args.target,
        "publicUrl": public_url,
        "logPath": str(log_path),
        "pidPath": str(pid_path),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
