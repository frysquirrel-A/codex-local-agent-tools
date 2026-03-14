from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen


URL_PATTERN = re.compile(r"https://[A-Za-z0-9.-]+trycloudflare\.com")


def read_public_url(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = URL_PATTERN.findall(text)
    return matches[-1] if matches else ""


def stop_existing_tunnels() -> None:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "($_.Name -eq 'ssh.exe' -and $_.CommandLine -like '*localhost.run*') -or "
        "($_.Name -eq 'cloudflared.exe' -and $_.CommandLine -like '*8787*') "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
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
                timeout=20,
            )


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def http_ok(url: str) -> tuple[bool, str]:
    if not url:
        return False, "empty_url"
    try:
        request = Request(url.rstrip("/") + "/api/auth/state", headers={"User-Agent": "CodexTunnelSupervisor/1.0"})
        with urlopen(request, timeout=12) as response:
            return 200 <= int(response.status) < 300, str(response.status)
    except Exception as exc:
        return False, str(exc)


def start_cloudflared(bin_path: Path, target: str, log_path: Path) -> subprocess.Popen:
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                str(bin_path),
                "tunnel",
                "--url",
                f"http://{target}",
                "--no-autoupdate",
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=0x00000008,
        )
    return process


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep a cloudflared quick tunnel alive for Codex Control Center.")
    parser.add_argument("--target", default="127.0.0.1:8787")
    parser.add_argument("--check-seconds", type=int, default=20)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    bin_path = root / "bin" / "cloudflared.exe"
    if not bin_path.exists():
        raise SystemExit("cloudflared.exe not found under codex-control-center/bin")

    state_root = root / "state"
    log_path = state_root / "cloudflared_tunnel.log"
    pid_path = state_root / "public_tunnel.pid"
    status_path = state_root / "public_tunnel_status.json"
    supervisor_status_path = state_root / "cloudflared_supervisor_status.json"

    stop_existing_tunnels()

    process = None
    last_url = ""
    consecutive_failures = 0

    while True:
        if process is None or process.poll() is not None:
            process = start_cloudflared(bin_path, args.target, log_path)
            pid_path.write_text(str(process.pid), encoding="utf-8")
            consecutive_failures = 0
            last_url = ""
            time.sleep(3)

        public_url = read_public_url(log_path)
        if public_url:
            last_url = public_url

        ok, health = http_ok(last_url)
        if ok:
            consecutive_failures = 0
        else:
            consecutive_failures += 1

        status = {
            "ok": bool(last_url),
            "provider": "cloudflared",
            "pid": process.pid,
            "target": args.target,
            "publicUrl": last_url,
            "logPath": str(log_path),
            "pidPath": str(pid_path),
            "healthOk": ok,
            "healthDetail": health,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        write_status(status_path, status)
        write_status(
            supervisor_status_path,
            {
                **status,
                "consecutiveFailures": consecutive_failures,
            },
        )

        if consecutive_failures >= 3:
            try:
                process.kill()
            except Exception:
                pass
            process = None
            time.sleep(2)
            continue

        time.sleep(max(args.check_seconds, 5))


if __name__ == "__main__":
    main()
