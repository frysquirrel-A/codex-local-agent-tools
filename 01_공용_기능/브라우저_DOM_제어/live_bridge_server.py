import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


STATE_LOCK = threading.Lock()
CLIENTS: dict[str, dict[str, Any]] = {}
PENDING_COMMANDS: dict[str, list[dict[str, Any]]] = {}
COMMAND_RESULTS: dict[str, dict[str, Any]] = {}
COMPLETED_COMMANDS: dict[str, float] = {}
CLIENT_TTL_SECONDS = 20.0
COMMAND_RESULT_TTL_SECONDS = 300.0
LOCAL_RELAY_BASE = "http://127.0.0.1:8767"
LOCAL_RELAY_ALLOWED_PATHS = {"/status", "/api/session", "/api/message"}


def now() -> float:
    return time.time()


def mark_command_complete(command_id: str, result: dict[str, Any]) -> None:
    timestamp = now()
    COMMAND_RESULTS[command_id] = {"timestamp": timestamp, "result": result}
    COMPLETED_COMMANDS[command_id] = timestamp


def command_expired(command: dict[str, Any], reference_time: float | None = None) -> bool:
    deadline = command.get("deadlineTs")
    if deadline in (None, ""):
        return False
    try:
        deadline_value = float(deadline)
    except (TypeError, ValueError):
        return False
    return deadline_value <= (reference_time or now())


def expire_command(command: dict[str, Any], reason: str, **extra: Any) -> None:
    command_id = command.get("id")
    if not command_id or command_id in COMPLETED_COMMANDS:
        return
    result: dict[str, Any] = {"ok": False, "expired": True, "reason": reason}
    result.update(extra)
    mark_command_complete(str(command_id), result)


def prune_state_locked() -> None:
    reference_time = now()

    stale_clients = [client_id for client_id, payload in CLIENTS.items() if (reference_time - float(payload.get("timestamp", 0))) > CLIENT_TTL_SECONDS]
    for client_id in stale_clients:
        CLIENTS.pop(client_id, None)
        queued = PENDING_COMMANDS.pop(client_id, [])
        for command in queued:
            expire_command(command, "Target client became stale before executing.", staleClientId=client_id)

    for client_id, queue in list(PENDING_COMMANDS.items()):
        active_queue = []
        for command in queue:
            if command_expired(command, reference_time):
                expire_command(command, "Command expired before execution.", targetClientId=client_id)
                continue
            active_queue.append(command)
        if active_queue:
            PENDING_COMMANDS[client_id] = active_queue
        else:
            PENDING_COMMANDS.pop(client_id, None)

    for command_id, payload in list(COMMAND_RESULTS.items()):
        if (reference_time - float(payload.get("timestamp", reference_time))) > COMMAND_RESULT_TTL_SECONDS:
            COMMAND_RESULTS.pop(command_id, None)

    for command_id, timestamp in list(COMPLETED_COMMANDS.items()):
        if (reference_time - float(timestamp)) > COMMAND_RESULT_TTL_SECONDS:
            COMPLETED_COMMANDS.pop(command_id, None)


def choose_target_client() -> str | None:
    cutoff = now() - 10
    fresh_clients = [item for item in CLIENTS.values() if item.get("timestamp", 0) >= cutoff]
    active_clients = [item for item in fresh_clients if item.get("active")]
    selected_pool = active_clients or fresh_clients
    if not selected_pool:
        return None
    selected_pool.sort(key=lambda item: (0 if item.get("focused") else 1, -float(item.get("timestamp", 0))))
    return selected_pool[0]["clientId"]


def proxy_local_relay(request_payload: dict[str, Any]) -> dict[str, Any]:
    method = str(request_payload.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"Relay method is not allowed: {method}")

    relay_path = str(request_payload.get("path") or "").strip()
    if relay_path not in LOCAL_RELAY_ALLOWED_PATHS:
        raise ValueError(f"Relay path is not allowed: {relay_path}")

    url = urllib.parse.urljoin(LOCAL_RELAY_BASE, relay_path)
    query = request_payload.get("query") or {}
    if isinstance(query, dict):
        encoded_query = urllib.parse.urlencode(
            {
                str(key): str(value)
                for key, value in query.items()
                if value not in (None, "")
            }
        )
        if encoded_query:
            url = f"{url}?{encoded_query}"

    headers = {"Accept": "application/json"}
    body = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = json.dumps(request_payload.get("body") or {}, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(url, data=body, headers=headers, method=method)

    status = 0
    raw_text = ""
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = getattr(response, "status", 200)
            raw_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status = error.code
        raw_text = error.read().decode("utf-8")

    parsed_body = None
    if raw_text:
        try:
            parsed_body = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed_body = None

    return {
        "ok": 200 <= status < 300,
        "status": status,
        "body": parsed_body,
        "text": raw_text,
    }


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
        if self.path == "/relay":
            try:
                payload = proxy_local_relay(self._read_json())
            except Exception as error:
                self._write_json({"ok": False, "reason": str(error)})
                return
            self._write_json(payload)
            return

        if self.path == "/heartbeat":
            payload = self._read_json()
            client_id = payload["clientId"]
            payload["timestamp"] = now()
            with STATE_LOCK:
                CLIENTS[client_id] = payload
                prune_state_locked()
                queue = PENDING_COMMANDS.get(client_id, [])
                command = None
                while queue:
                    candidate = queue.pop(0)
                    if command_expired(candidate):
                        expire_command(candidate, "Command expired before pickup.", targetClientId=client_id)
                        continue
                    command = candidate
                    break
                if queue:
                    PENDING_COMMANDS[client_id] = queue
                elif client_id in PENDING_COMMANDS:
                    del PENDING_COMMANDS[client_id]
            self._write_json({"ok": True, "command": command})
            return

        if self.path == "/result":
            payload = self._read_json()
            with STATE_LOCK:
                prune_state_locked()
                command_id = str(payload["commandId"])
                if command_id not in COMPLETED_COMMANDS:
                    mark_command_complete(command_id, payload["result"])
            self._write_json({"ok": True})
            return

        if self.path == "/command":
            payload = self._read_json()
            command = payload["command"]
            command_id = command["id"]
            explicit_client = payload.get("clientId")
            with STATE_LOCK:
                prune_state_locked()
                if explicit_client and explicit_client not in CLIENTS:
                    self._write_json({"ok": False, "reason": "Requested page bridge is no longer active."}, status=404)
                    return
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
                prune_state_locked()
                clients = list(CLIENTS.values())
            self._write_json({"ok": True, "clients": clients})
            return

        if self.path.startswith("/result/"):
            command_id = self.path.rsplit("/", 1)[-1]
            with STATE_LOCK:
                prune_state_locked()
                if command_id not in COMMAND_RESULTS:
                    self._write_json({"ok": False, "ready": False}, status=404)
                    return
                result = COMMAND_RESULTS.pop(command_id)["result"]
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
