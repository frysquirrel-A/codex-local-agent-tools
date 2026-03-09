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
FRESH_CLIENT_SECONDS = 15.0
AUTO_CLIENT_ATTEMPT_TIMEOUT = 3.0
CLIENT_DEADLINE_SLACK_SECONDS = 0.5
MAX_AUTO_CLIENTS = 6


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


def is_fresh_client(client: dict, fresh_seconds: float = FRESH_CLIENT_SECONDS) -> bool:
    try:
        timestamp = float(client.get("timestamp", 0))
    except (TypeError, ValueError):
        return False
    return timestamp >= (time.time() - fresh_seconds)


def client_timestamp(client: dict) -> float:
    try:
        return float(client.get("timestamp", 0))
    except (TypeError, ValueError):
        return 0.0


def sort_clients(clients: list[dict]) -> list[dict]:
    return sorted(
        clients,
        key=lambda item: (
            0 if is_fresh_client(item) else 1,
            0 if item.get("active") else 1,
            0 if item.get("focused") else 1,
            -client_timestamp(item),
        ),
    )


def resolve_target_clients(client_id: str | None, url_hint: str | None, title_hint: str | None) -> tuple[list[str | None], bool]:
    if client_id:
        return [client_id], False

    if not url_hint and not title_hint:
        return [None], False

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

    ordered = sort_clients(filtered)
    client_ids: list[str | None] = []
    for client in ordered:
        candidate_id = client.get("clientId")
        if not candidate_id or candidate_id in client_ids:
            continue
        client_ids.append(candidate_id)
        if len(client_ids) >= MAX_AUTO_CLIENTS:
            break

    if not client_ids:
        raise RuntimeError("No bridge client matched the requested hint.")

    return client_ids, True


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
    elif args.action == "query-elements":
        command["action"] = "query_elements"
        command["selector"] = args.selector
        command["maxElements"] = args.max_elements
    elif args.action == "llm-response-probe":
        command["action"] = "llm_response_probe"
        if args.selector:
            command["selector"] = args.selector
        command["messageSelectors"] = args.message_selectors or []
        command["busySelectors"] = args.busy_selectors or []
        command["quietMs"] = args.quiet_ms
        command["maxChars"] = args.max_chars
        if args.start_marker:
            command["startMarker"] = args.start_marker
        if args.wait_for_text:
            command["waitForText"] = args.wait_for_text
        if args.after_message_id:
            command["afterMessageId"] = args.after_message_id
        if args.after_text_hash:
            command["afterTextHash"] = args.after_text_hash
    elif args.action == "llm-read-response":
        command["action"] = "llm_read_response"
        if args.selector:
            command["selector"] = args.selector
        command["messageSelectors"] = args.message_selectors or []
        command["busySelectors"] = args.busy_selectors or []
        command["quietMs"] = args.quiet_ms
        command["maxChars"] = args.max_chars
        if args.start_marker:
            command["startMarker"] = args.start_marker
        if args.wait_for_text:
            command["waitForText"] = args.wait_for_text
        if args.after_message_id:
            command["afterMessageId"] = args.after_message_id
        if args.after_text_hash:
            command["afterTextHash"] = args.after_text_hash
    elif args.action == "llm-wait-response":
        command["action"] = "llm_wait_response"
        if args.selector:
            command["selector"] = args.selector
        command["messageSelectors"] = args.message_selectors or []
        command["busySelectors"] = args.busy_selectors or []
        command["quietMs"] = args.quiet_ms
        command["pollMs"] = max(int(args.poll_interval * 1000), 100)
        command["timeoutMs"] = max(int(args.timeout * 1000), 500)
        command["maxChars"] = args.max_chars
        if args.start_marker:
            command["startMarker"] = args.start_marker
        if args.wait_for_text:
            command["waitForText"] = args.wait_for_text
        if args.after_message_id:
            command["afterMessageId"] = args.after_message_id
        if args.after_text_hash:
            command["afterTextHash"] = args.after_text_hash
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


def with_deadline(command: dict, timeout: float) -> dict:
    payload = dict(command)
    payload["deadlineTs"] = time.time() + max(timeout + CLIENT_DEADLINE_SLACK_SECONDS, 0.5)
    return payload


def dispatch_command(command: dict, timeout: float, client_id: str | None = None) -> tuple[dict, str | None]:
    append_log(
        {
            "phase": "request",
            "action": command["action"],
            "commandId": command["id"],
            "clientId": client_id or "",
            "deadlineTs": command.get("deadlineTs"),
        }
    )
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
                "clientId": client_id or "",
                "reason": accepted.get("reason", "Command rejected."),
            }
        )
        raise RuntimeError(accepted.get("reason", "Command rejected."))

    result = wait_for_result(accepted["commandId"], timeout)
    selected_client = accepted.get("clientId") or client_id
    append_log(
        {
            "phase": "result",
            "action": command["action"],
            "commandId": command["id"],
            "clientId": selected_client or "",
            "ok": result.get("ok", False),
            "expired": result.get("expired", False),
        }
    )
    return result, selected_client


def execute_remote_command(command: dict, timeout: float, client_candidates: list[str | None] | None = None, fast_fail: bool = False) -> dict:
    candidates = client_candidates or [None]
    failures: list[str] = []
    started_at = time.time()

    for index, candidate in enumerate(candidates):
        remaining = timeout - (time.time() - started_at)
        if remaining <= 0:
            break

        attempt_timeout = remaining
        if fast_fail and candidate is not None:
            attempt_timeout = min(remaining, AUTO_CLIENT_ATTEMPT_TIMEOUT)

        attempt_command = with_deadline(command, attempt_timeout)
        try:
            result, selected_client = dispatch_command(attempt_command, attempt_timeout, candidate)
        except Exception as exc:
            message = str(exc)
            failures.append(f"{candidate or 'auto'}: {message}")
            append_log(
                {
                    "phase": "candidate_failed",
                    "action": command["action"],
                    "commandId": command["id"],
                    "clientId": candidate or "",
                    "attempt": index + 1,
                    "reason": message,
                }
            )
            continue

        if result.get("ok", False) or not fast_fail or index == (len(candidates) - 1):
            return result

        retry_reason = result.get("reason") or "Command returned ok=false."
        failures.append(f"{selected_client or candidate or 'auto'}: {retry_reason}")
        append_log(
            {
                "phase": "candidate_retry",
                "action": command["action"],
                "commandId": command["id"],
                "clientId": selected_client or candidate or "",
                "attempt": index + 1,
                "reason": retry_reason,
            }
        )

    if failures:
        raise RuntimeError(f"Bridge command failed after trying {len(failures)} candidate(s): {' | '.join(failures)}")
    raise TimeoutError("Timed out waiting for page result.")


def wait_for_text(args: argparse.Namespace, client_candidates: list[str | None], fast_fail: bool) -> dict:
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        command = {
            "id": str(uuid.uuid4()),
            "action": "visible_text",
            "maxChars": args.max_chars,
        }
        if args.selector:
            command["selector"] = args.selector

        remaining = max(0.5, deadline - time.time())
        result = execute_remote_command(command, min(15.0, remaining), client_candidates=client_candidates, fast_fail=fast_fail)
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
    parser.add_argument("action", choices=["status", "ping", "dom-summary", "visible-text", "query-elements", "llm-response-probe", "llm-read-response", "llm-wait-response", "wait-text", "navigate", "set-text", "prompt-send", "click-text", "click"])
    parser.add_argument("--text")
    parser.add_argument("--url")
    parser.add_argument("--selector")
    parser.add_argument("--message-selector", dest="message_selectors", action="append")
    parser.add_argument("--busy-selector", dest="busy_selectors", action="append")
    parser.add_argument("--send-selector", dest="send_selectors", action="append")
    parser.add_argument("--contains", action="store_true")
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--max-elements", type=int, default=20)
    parser.add_argument("--quiet-ms", type=int, default=1200)
    parser.add_argument("--start-marker")
    parser.add_argument("--wait-for-text")
    parser.add_argument("--after-message-id")
    parser.add_argument("--after-text-hash")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--client-id")
    parser.add_argument("--url-hint")
    parser.add_argument("--title-hint")
    args = parser.parse_args()

    if args.action == "status":
        result = http_json("GET", "/status")
    else:
        target_clients, fast_fail = resolve_target_clients(args.client_id, args.url_hint, args.title_hint)
        if args.action == "wait-text":
            result = wait_for_text(args, target_clients, fast_fail)
        else:
            command = make_command(args)
            result = execute_remote_command(command, args.timeout, client_candidates=target_clients, fast_fail=fast_fail)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
