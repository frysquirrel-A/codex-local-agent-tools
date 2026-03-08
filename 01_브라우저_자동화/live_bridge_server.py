import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


STATE_LOCK = threading.Lock()
CLIENTS: dict[str, dict[str, Any]] = {}
PENDING_COMMANDS: dict[str, list[dict[str, Any]]] = {}
COMMAND_RESULTS: dict[str, dict[str, Any]] = {}


def now() -> float:
    return time.time()


def choose_target_client() -> str | None:
    cutoff = now() - 10
    fresh_clients = [item for item in CLIENTS.values() if item.get("timestamp", 0) >= cutoff]
    active_clients = [item for item in fresh_clients if item.get("active")]
    selected_pool = active_clients or fresh_clients
    if not selected_pool:
        return None
    selected_pool.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return selected_pool[0]["clientId"]


class BridgeHandler(BaseHTTPRequestHandler):
    def _write_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        return json.loads(body.decode("utf-8"))

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._write_cors_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._write_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/heartbeat":
            payload = self._read_json()
            client_id = payload["clientId"]
            payload["timestamp"] = now()
            with STATE_LOCK:
                CLIENTS[client_id] = payload
                queue = PENDING_COMMANDS.get(client_id, [])
                command = queue.pop(0) if queue else None
                if not queue and client_id in PENDING_COMMANDS:
                    del PENDING_COMMANDS[client_id]
            self._write_json({"ok": True, "command": command})
            return

        if self.path == "/result":
            payload = self._read_json()
            with STATE_LOCK:
                COMMAND_RESULTS[payload["commandId"]] = payload["result"]
            self._write_json({"ok": True})
            return

        if self.path == "/command":
            payload = self._read_json()
            command = payload["command"]
            command_id = command["id"]
            explicit_client = payload.get("clientId")
            with STATE_LOCK:
                target_client = explicit_client or choose_target_client()
                if not target_client:
                    self._write_json({"ok": False, "reason": "No active page bridge connected."}, status=404)
                    return
                PENDING_COMMANDS.setdefault(target_client, []).append(command)
            self._write_json({"ok": True, "clientId": target_client, "commandId": command_id})
            return

        self._write_json({"ok": False, "reason": "Unknown POST path."}, status=404)

    def do_GET(self) -> None:
        if self.path == "/status":
            with STATE_LOCK:
                clients = list(CLIENTS.values())
            self._write_json({"ok": True, "clients": clients})
            return

        if self.path.startswith("/result/"):
            command_id = self.path.rsplit("/", 1)[-1]
            with STATE_LOCK:
                if command_id not in COMMAND_RESULTS:
                    self._write_json({"ok": False, "ready": False}, status=404)
                    return
                result = COMMAND_RESULTS.pop(command_id)
            self._write_json({"ok": True, "ready": True, "result": result})
            return

        self._write_json({"ok": False, "reason": "Unknown GET path."}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
