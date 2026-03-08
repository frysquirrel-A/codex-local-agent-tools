import argparse
from datetime import datetime, timezone
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8765"
SCRIPT_ROOT = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_ROOT / "logs"
LOG_PATH = LOG_DIR / "commands.jsonl"
RESULT_POLL_INTERVAL = 0.1


def http_json(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def append_log(event: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_target_client(client_id: str | None, url_hint: str | None, title_hint: str | None) -> str | None:
    if client_id:
        return client_id

    if not url_hint and not title_hint:
        return None

    status = http_json("GET", "/status")
    clients = status.get("clients", [])
    filtered = []
    for client in clients:
        url = client.get("url", "")
        title = client.get("title", "")
        if url_hint and url_hint not in url:
            continue
        if title_hint and title_hint not in title:
            continue
        filtered.append(client)

    if not filtered:
        raise RuntimeError("No bridge client matched the requested hint.")

    active = [client for client in filtered if client.get("active")]
    pool = active or filtered
    pool.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return pool[0]["clientId"]


def wait_for_result(command_id: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            payload = http_json("GET", f"/result/{command_id}")
            if payload.get("ready"):
                return payload["result"]
        except HTTPError as exc:
            if exc.code != 404:
                raise
        time.sleep(RESULT_POLL_INTERVAL)
    raise TimeoutError("Timed out waiting for page result.")


def make_command(args: argparse.Namespace) -> dict:
    command = {"id": str(uuid.uuid4())}
    if args.action == "ping":
        command["action"] = "ping"
    elif args.action == "dom-summary":
        command["action"] = "dom_summary"
    elif args.action == "visible-text":
        command["action"] = "visible_text"
        if args.selector:
            command["selector"] = args.selector
        command["maxChars"] = args.max_chars
    elif args.action == "navigate":
        command["action"] = "navigate"
        command["url"] = args.url
    elif args.action == "set-text":
        command["action"] = "set_text"
        command["text"] = args.text
        if args.selector:
            command["selector"] = args.selector
    elif args.action == "prompt-send":
        command["action"] = "prompt_send"
        command["text"] = args.text
        if args.selector:
            command["selector"] = args.selector
        command["sendSelectors"] = args.send_selectors or []
    elif args.action == "click-text":
        command["action"] = "click_text"
        command["text"] = args.text
        command["contains"] = args.contains
    elif args.action == "click":
        command["action"] = "click"
        command["selector"] = args.selector
    else:
        raise ValueError(f"Unsupported action: {args.action}")
    return command


def execute_remote_command(command: dict, timeout: float, client_id: str | None = None) -> dict:
    append_log({"phase": "request", "action": command["action"], "commandId": command["id"]})
    payload = {"command": command}
    if client_id:
        payload["clientId"] = client_id
    accepted = http_json("POST", "/command", payload)
    if not accepted.get("ok"):
        append_log(
            {
                "phase": "rejected",
                "action": command["action"],
                "commandId": command["id"],
                "reason": accepted.get("reason", "Command rejected."),
            }
        )
        raise RuntimeError(accepted.get("reason", "Command rejected."))

    result = wait_for_result(accepted["commandId"], timeout)
    append_log({"phase": "result", "action": command["action"], "commandId": command["id"], "ok": result.get("ok", False)})
    return result


def wait_for_text(args: argparse.Namespace, client_id: str | None) -> dict:
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        command = {
            "id": str(uuid.uuid4()),
            "action": "visible_text",
            "maxChars": args.max_chars,
        }
        if args.selector:
            command["selector"] = args.selector

        result = execute_remote_command(command, min(15.0, args.timeout), client_id=client_id)
        text = result.get("text", "")
        matched = args.text in text if args.contains else text == args.text
        if matched:
            return {
                "ok": True,
                "action": "wait_text",
                "matched": args.text,
                "contains": args.contains,
                "text": text,
            }
        time.sleep(args.poll_interval)
    raise TimeoutError("Timed out waiting for text.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "ping", "dom-summary", "visible-text", "wait-text", "navigate", "set-text", "prompt-send", "click-text", "click"])
    parser.add_argument("--text")
    parser.add_argument("--url")
    parser.add_argument("--selector")
    parser.add_argument("--send-selector", dest="send_selectors", action="append")
    parser.add_argument("--contains", action="store_true")
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--client-id")
    parser.add_argument("--url-hint")
    parser.add_argument("--title-hint")
    args = parser.parse_args()

    if args.action == "status":
        result = http_json("GET", "/status")
    else:
        target_client = resolve_target_client(args.client_id, args.url_hint, args.title_hint)
        if args.action == "wait-text":
            result = wait_for_text(args, target_client)
        else:
            command = make_command(args)
            result = execute_remote_command(command, args.timeout, client_id=target_client)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
