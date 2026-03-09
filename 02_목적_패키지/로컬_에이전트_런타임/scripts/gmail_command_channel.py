import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


RESULT_POLL_INTERVAL = 0.1
FRESH_CLIENT_SECONDS = 15.0
AUTO_CLIENT_ATTEMPT_TIMEOUT = 3.0
CLIENT_DEADLINE_SLACK_SECONDS = 0.5
MAX_AUTO_CLIENTS = 6
BRIDGE_BASE_URL = "http://127.0.0.1:8765"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChannelRuntimeError(RuntimeError):
    pass


class StateStore:
    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root
        self.state_dir = package_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "gmail_command_channel_state.json"
        self.status_path = self.state_dir / "gmail_command_channel_status.json"
        self.pid_path = self.state_dir / "gmail_command_channel.pid"
        self.lock_path = self.state_dir / "gmail_command_channel.lock"

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {"requests": {}}
        return json.loads(self.state_path.read_text(encoding="utf-8-sig"))

    def save_state(self, payload: dict) -> None:
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_status(self) -> dict:
        if not self.status_path.exists():
            return {}
        return json.loads(self.status_path.read_text(encoding="utf-8-sig"))

    def save_status(self, payload: dict) -> None:
        self.status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def running_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        raw = self.pid_path.read_text(encoding="ascii").strip()
        if not raw.isdigit():
            return None
        return int(raw)


class BridgeClient:
    def __init__(self, url_hint: str, bootstrap_url: str) -> None:
        self.url_hint = url_hint
        self.bootstrap_url = bootstrap_url

    def http_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{BRIDGE_BASE_URL}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def is_fresh_client(self, client: dict) -> bool:
        try:
            timestamp = float(client.get("timestamp", 0))
        except (TypeError, ValueError):
            return False
        return timestamp >= (time.time() - FRESH_CLIENT_SECONDS)

    @staticmethod
    def client_timestamp(client: dict) -> float:
        try:
            return float(client.get("timestamp", 0))
        except (TypeError, ValueError):
            return 0.0

    def sort_clients(self, clients: list[dict]) -> list[dict]:
        return sorted(
            clients,
            key=lambda item: (
                0 if self.is_fresh_client(item) else 1,
                0 if item.get("active") else 1,
                0 if item.get("focused") else 1,
                -self.client_timestamp(item),
            ),
        )

    def resolve_target_clients(self, auto_open_url: str | None = None) -> tuple[list[str], bool]:
        status = self.http_json("GET", "/status")
        clients = status.get("clients", [])
        filtered = [client for client in clients if self.url_hint in str(client.get("url", ""))]
        if not filtered:
            if auto_open_url:
                if clients:
                    candidate = self.sort_clients(clients)[0]
                    candidate_id = str(candidate.get("clientId", "")).strip()
                    if candidate_id:
                        command = {
                            "id": str(uuid.uuid4()),
                            "action": "navigate",
                            "url": auto_open_url,
                            "deadlineTs": time.time() + 12.0,
                        }
                        self.dispatch_command(command, 10.0, candidate_id)
                else:
                    self.launch_url(auto_open_url)

                for _ in range(12):
                    time.sleep(1.0)
                    status = self.http_json("GET", "/status")
                    clients = status.get("clients", [])
                    filtered = [client for client in clients if self.url_hint in str(client.get("url", ""))]
                    if filtered:
                        break

        if not filtered:
            raise ChannelRuntimeError(f"No bridge client matched url hint '{self.url_hint}'.")

        ordered = self.sort_clients(filtered)
        client_ids: list[str] = []
        for client in ordered:
            candidate_id = str(client.get("clientId", "")).strip()
            if candidate_id and candidate_id not in client_ids:
                client_ids.append(candidate_id)
            if len(client_ids) >= MAX_AUTO_CLIENTS:
                break

        if not client_ids:
            raise ChannelRuntimeError(f"No responsive client candidates matched url hint '{self.url_hint}'.")
        return client_ids, True

    def wait_for_result(self, command_id: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                payload = self.http_json("GET", f"/result/{command_id}")
                if payload.get("ready"):
                    return payload["result"]
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            time.sleep(RESULT_POLL_INTERVAL)
        raise TimeoutError("Timed out waiting for browser command result.")

    def dispatch_command(self, command: dict, timeout: float, client_id: str | None = None) -> dict:
        payload = {"command": command}
        if client_id:
            payload["clientId"] = client_id

        accepted = self.http_json("POST", "/command", payload)
        if not accepted.get("ok"):
            raise ChannelRuntimeError(accepted.get("reason", "Browser command was rejected."))
        return self.wait_for_result(accepted["commandId"], timeout)

    def execute(self, command: dict, timeout: float = 20.0, auto_open_url: str | None = None) -> dict:
        candidates, fast_fail = self.resolve_target_clients(auto_open_url=auto_open_url)
        failures: list[str] = []
        started_at = time.time()

        for candidate in candidates:
            remaining = timeout - (time.time() - started_at)
            if remaining <= 0:
                break

            attempt_timeout = min(remaining, AUTO_CLIENT_ATTEMPT_TIMEOUT if fast_fail else remaining)
            attempt = dict(command)
            attempt["deadlineTs"] = time.time() + max(attempt_timeout + CLIENT_DEADLINE_SLACK_SECONDS, 0.5)
            try:
                return self.dispatch_command(attempt, attempt_timeout, candidate)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{candidate}: {exc}")

        if failures:
            raise ChannelRuntimeError(" | ".join(failures))
        raise ChannelRuntimeError("No Gmail bridge client completed the request.")

    @staticmethod
    def launch_url(url: str) -> None:
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        for candidate in chrome_candidates:
            if candidate.exists():
                subprocess.Popen([str(candidate), url])  # noqa: S603
                return
        raise ChannelRuntimeError("Google Chrome executable was not found.")

    def navigate(self, url: str, timeout: float = 20.0) -> dict:
        return self.execute({"id": str(uuid.uuid4()), "action": "navigate", "url": url}, timeout=timeout, auto_open_url=url)

    def visible_text(self, selector: str | None = None, max_chars: int = 12000, timeout: float = 20.0) -> str:
        command = {"id": str(uuid.uuid4()), "action": "visible_text", "maxChars": max_chars}
        if selector:
            command["selector"] = selector
        result = self.execute(command, timeout=timeout, auto_open_url=self.bootstrap_url)
        return str(result.get("text", ""))

    def set_text(self, selector: str, text: str, timeout: float = 20.0) -> dict:
        return self.execute(
            {"id": str(uuid.uuid4()), "action": "set_text", "selector": selector, "text": text},
            timeout=timeout,
            auto_open_url=self.bootstrap_url,
        )

    def prompt_send(self, selector: str, text: str, send_selectors: list[str] | None = None, timeout: float = 20.0) -> dict:
        command = {"id": str(uuid.uuid4()), "action": "prompt_send", "selector": selector, "text": text}
        if send_selectors:
            command["sendSelectors"] = send_selectors
        return self.execute(command, timeout=timeout, auto_open_url=self.bootstrap_url)

    def click(self, selector: str, timeout: float = 20.0) -> dict:
        return self.execute(
            {"id": str(uuid.uuid4()), "action": "click", "selector": selector},
            timeout=timeout,
            auto_open_url=self.bootstrap_url,
        )

    def click_text(self, text: str, contains: bool = False, timeout: float = 20.0) -> dict:
        command = {"id": str(uuid.uuid4()), "action": "click_text", "text": text, "contains": contains}
        return self.execute(command, timeout=timeout, auto_open_url=self.bootstrap_url)


class RelayClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def http_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def ensure_ready(self) -> dict:
        return self.http_json("GET", "/status")

    def post_message(self, session_id: str, text: str, command: str, notes: str) -> dict:
        return self.http_json(
            "POST",
            "/api/message",
            {
                "sessionId": session_id,
                "text": text,
                "command": command,
                "notes": notes,
                "target": "other",
                "priority": "normal",
            },
        )

    def get_session(self, session_id: str) -> dict:
        encoded = urllib.parse.quote(session_id, safe="")
        return self.http_json("GET", f"/api/session?sessionId={encoded}")


class GmailCommandChannel:
    def __init__(self) -> None:
        self.script_root = Path(__file__).resolve().parent
        self.package_root = self.script_root.parent
        self.package_group_root = self.package_root.parent
        self.tool_root = self.package_group_root.parent
        self.config = json.loads((self.package_root / "config" / "email_command_channel.json").read_text(encoding="utf-8"))
        self.state_store = StateStore(self.package_root)
        self.bridge = BridgeClient(self.config["gmail"]["urlHint"], "https://mail.google.com/mail/u/0/#inbox")
        self.relay = RelayClient(self.config["relay"]["baseUrl"])
        self.browser_wrapper = self.tool_root / "01_공용_기능" / "브라우저_DOM_제어" / "send_live_page_command.ps1"

    def acquire_lock(self, timeout_seconds: float = 30.0) -> int:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                handle = os.open(self.state_store.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(handle, str(os.getpid()).encode("ascii"))
                return handle
            except FileExistsError:
                lock_pid = None
                try:
                    raw_pid = self.state_store.lock_path.read_text(encoding="ascii").strip()
                    if raw_pid.isdigit():
                        lock_pid = int(raw_pid)
                    age_seconds = time.time() - self.state_store.lock_path.stat().st_mtime
                    if (lock_pid and not self.process_exists(lock_pid)) or (not lock_pid and age_seconds > 5) or age_seconds > 120:
                        self.state_store.lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                time.sleep(0.25)
        raise ChannelRuntimeError("Timed out waiting for the Gmail channel lock.")

    def release_lock(self, lock_handle: int | None) -> None:
        if lock_handle is None:
            return
        try:
            os.close(lock_handle)
        finally:
            try:
                self.state_store.lock_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass

    @staticmethod
    def process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def normalize_text(value: str) -> str:
        return " ".join((value or "").split())

    def request_id(self) -> str:
        return f"MAIL-{datetime.now().strftime('%y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    def search_query_for_sender(self, sender: str) -> str:
        return self.config["mailbox"]["searchQueryTemplate"].format(
            sender=sender,
            prefix=self.config["mailbox"]["subjectPrefix"],
        )

    def gmail_search(self, query: str) -> str:
        search_url = f"https://mail.google.com/mail/u/0/#search/{urllib.parse.quote(query, safe='')}"
        self.bridge.navigate(search_url, timeout=20.0)
        time.sleep(2.0)
        return self.bridge.visible_text(max_chars=self.config["channel"]["maxMailChars"], timeout=20.0)

    def no_search_results(self, text: str) -> bool:
        for phrase in self.config["mailbox"]["noResultsPhrases"]:
            if phrase in text:
                return True
        return False

    def open_first_search_result(self) -> None:
        self.bridge.click(self.config["gmail"]["searchResultRowSelector"], timeout=20.0)
        time.sleep(2.0)

    def extract_between(self, text: str, start_marker: str, end_marker: str) -> str:
        start = text.find(start_marker)
        if start < 0:
            return ""
        start += len(start_marker)
        end = text.find(end_marker, start)
        if end < 0:
            return ""
        return text[start:end].strip()

    def parse_command_mail(self, visible_text: str, sender: str) -> dict:
        normalized = self.normalize_text(visible_text)
        markers = self.config["markers"]
        command_text = self.extract_between(normalized, markers["commandStart"], markers["commandEnd"])
        command_json = self.extract_between(normalized, markers["jsonStart"], markers["jsonEnd"])
        if not command_text and not command_json:
            raise ChannelRuntimeError("No command markers were found in the email body.")

        body_for_key = command_json or command_text
        message_key = hashlib.sha1(f"{sender}|{body_for_key}".encode("utf-8")).hexdigest()
        return {
            "sender": sender,
            "messageKey": message_key,
            "commandText": command_text,
            "commandJson": command_json,
            "rawVisibleText": normalized,
        }

    def compose_subject(self, prefix: str, request_id: str, summary: str) -> str:
        compact = self.normalize_text(summary)
        if len(compact) > 70:
            compact = compact[:67] + "..."
        return f"{prefix} [{request_id}] {compact}".strip()

    def _send_mail_unlocked(self, to_address: str, subject: str, body: str, verify: bool = False) -> dict:
        gmail_cfg = self.config["gmail"]
        self.invoke_bridge_wrapper(["navigate", "--url-hint", "mail.google.com", "--url", gmail_cfg["composeUrl"]])
        time.sleep(2.0)
        self.invoke_bridge_wrapper(["set-text", "--url-hint", "mail.google.com", "--selector", gmail_cfg["recipientSelector"], "--text", to_address])
        time.sleep(1.0)
        self.invoke_bridge_wrapper(["set-text", "--url-hint", "mail.google.com", "--selector", gmail_cfg["subjectSelector"], "--text", subject])
        time.sleep(0.8)
        self.invoke_bridge_wrapper(["set-text", "--url-hint", "mail.google.com", "--selector", gmail_cfg["bodySelector"], "--text", body])
        time.sleep(1.0)
        try:
            self.invoke_bridge_wrapper(["click-text", "--url-hint", "mail.google.com", "--text", "\uBCF4\uB0B4\uAE30"])
        except Exception:  # noqa: BLE001
            self.invoke_bridge_wrapper(["click-text", "--url-hint", "mail.google.com", "--text", "Send"])
        time.sleep(2.0)

        verified = False
        if verify:
            query = f'in:sent to:{to_address} subject:"{subject}" newer_than:1d'
            text = self.gmail_search(query)
            verified = subject in text

        return {
            "ok": True,
            "to": to_address,
            "subject": subject,
            "verified": verified,
        }

    def invoke_bridge_wrapper(self, arguments: list[str]) -> dict:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.browser_wrapper),
            *arguments,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise ChannelRuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Bridge wrapper command failed.")
        raw = (completed.stdout or "").strip()
        return json.loads(raw) if raw else {"ok": True}

    def send_mail(self, to_address: str, subject: str, body: str, verify: bool = False) -> dict:
        lock_handle = self.acquire_lock()
        try:
            return self._send_mail_unlocked(to_address, subject, body, verify=verify)
        finally:
            self.release_lock(lock_handle)

    def submit_request(self, parsed: dict) -> dict:
        self.relay.ensure_ready()
        request_id = self.request_id()
        session_id = f"{self.config['channel']['sessionPrefix']}:{parsed['messageKey']}"
        natural_text = parsed["commandText"] or parsed["commandJson"]
        command_value = parsed["commandJson"] or parsed["commandText"]
        notes = f"Request-ID: {request_id}\nSender: {parsed['sender']}\nSubmitted-Via: gmail-command-channel"
        relay_result = self.relay.post_message(session_id, natural_text, command_value, notes)
        return {
            "requestId": request_id,
            "sessionId": session_id,
            "issueNumber": relay_result.get("issueNumber"),
            "createdAt": relay_result.get("createdAt") or now_iso(),
            "issueUrl": relay_result.get("issueUrl", ""),
        }

    def acceptance_body(self, request_id: str, parsed: dict) -> str:
        summary = parsed["commandText"] or parsed["commandJson"]
        return "\n".join(
            [
                "Codex accepted your email command.",
                "",
                f"Request-ID: {request_id}",
                "Status: accepted",
                "",
                "Command summary:",
                summary,
                "",
                "I will send a short completion email after execution.",
            ]
        )

    def rejection_body(self) -> str:
        markers = self.config["markers"]
        prefix = self.config["mailbox"]["subjectPrefix"]
        return "\n".join(
            [
                "Codex could not accept this email command because the body format was invalid.",
                "",
                f"Subject format: {prefix} short title",
                "Body format:",
                f"{markers['commandStart']}",
                "your plain command here",
                f"{markers['commandEnd']}",
                "",
                "Optional JSON block:",
                f"{markers['jsonStart']}",
                "{\"mode\":\"desktop-command\",\"action\":\"screen-size\"}",
                f"{markers['jsonEnd']}",
            ]
        )

    def result_body(self, request_id: str, assistant_entry: dict) -> str:
        status = assistant_entry.get("status", "update")
        title = assistant_entry.get("title", "Codex result")
        text = assistant_entry.get("text", "")
        return "\n".join(
            [
                "Codex finished your email command.",
                "",
                f"Request-ID: {request_id}",
                f"Status: {status}",
                f"Summary: {title}",
                "",
                text,
            ]
        )

    def process_inbox_once(self, state: dict) -> list[dict]:
        accepted: list[dict] = []
        allow_senders = list(self.config["mailbox"]["allowSenders"])

        for sender in allow_senders:
            search_text = self.gmail_search(self.search_query_for_sender(sender))
            if self.no_search_results(search_text):
                continue

            self.open_first_search_result()
            visible = self.bridge.visible_text(max_chars=self.config["channel"]["maxMailChars"], timeout=20.0)
            fallback_key = hashlib.sha1(f"{sender}|{self.normalize_text(visible)}".encode("utf-8")).hexdigest()

            requests = state.setdefault("requests", {})
            if fallback_key in requests:
                continue

            try:
                parsed = self.parse_command_mail(visible, sender)
            except ChannelRuntimeError:
                request_id = self.request_id()
                rejection_subject = self.compose_subject(
                    f"{self.config['channel']['replySubjectPrefix']} rejected",
                    request_id,
                    "invalid email command format",
                )
                rejection_mail = self._send_mail_unlocked(sender, rejection_subject, self.rejection_body(), verify=False)
                requests[fallback_key] = {
                    "requestId": request_id,
                    "sessionId": "",
                    "issueNumber": None,
                    "issueUrl": "",
                    "sender": sender,
                    "status": "rejected",
                    "acceptedAt": now_iso(),
                    "commandText": "",
                    "commandJson": "",
                    "rawVisibleTextHash": hashlib.sha1(self.normalize_text(visible).encode("utf-8")).hexdigest(),
                    "acceptanceMail": None,
                    "resultMail": rejection_mail,
                }
                continue

            submission = self.submit_request(parsed)
            acceptance_subject = self.compose_subject(
                f"{self.config['channel']['replySubjectPrefix']} accepted",
                submission["requestId"],
                parsed["commandText"] or parsed["commandJson"],
            )
            acceptance_mail = self._send_mail_unlocked(
                sender,
                acceptance_subject,
                self.acceptance_body(submission["requestId"], parsed),
                verify=False,
            )

            requests[parsed["messageKey"]] = {
                "requestId": submission["requestId"],
                "sessionId": submission["sessionId"],
                "issueNumber": submission["issueNumber"],
                "issueUrl": submission["issueUrl"],
                "sender": sender,
                "status": "accepted",
                "acceptedAt": now_iso(),
                "commandText": parsed["commandText"],
                "commandJson": parsed["commandJson"],
                "rawVisibleTextHash": hashlib.sha1(parsed["rawVisibleText"].encode("utf-8")).hexdigest(),
                "acceptanceMail": acceptance_mail,
                "resultMail": None,
            }
            accepted.append(requests[parsed["messageKey"]])
            break

        return accepted

    def latest_assistant_entry(self, session_payload: dict) -> dict | None:
        entries = session_payload.get("entries", [])
        assistants = [entry for entry in entries if entry.get("kind") == "message" and entry.get("role") == "assistant"]
        return assistants[-1] if assistants else None

    def process_results_once(self, state: dict) -> list[dict]:
        completed: list[dict] = []
        requests = state.setdefault("requests", {})

        for record in requests.values():
            if record.get("status") != "accepted":
                continue

            session_payload = self.relay.get_session(record["sessionId"])
            assistant = self.latest_assistant_entry(session_payload)
            if not assistant:
                continue

            subject = self.compose_subject(
                f"{self.config['channel']['replySubjectPrefix']} completed",
                record["requestId"],
                assistant.get("title", assistant.get("text", "completed")),
            )
            result_mail = self._send_mail_unlocked(
                record["sender"],
                subject,
                self.result_body(record["requestId"], assistant),
                verify=False,
            )
            record["status"] = "completed"
            record["completedAt"] = now_iso()
            record["assistantResult"] = assistant
            record["resultMail"] = result_mail
            completed.append(record)

        return completed

    def _run_once_unlocked(self) -> dict:
        state = self.state_store.load_state()
        self.relay.ensure_ready()
        self.bridge.resolve_target_clients(auto_open_url=self.bridge.bootstrap_url)

        accepted = self.process_inbox_once(state)
        completed = self.process_results_once(state)
        self.state_store.save_state(state)

        result = {
            "ok": True,
            "mode": "run-once",
            "acceptedCount": len(accepted),
            "completedCount": len(completed),
            "accepted": accepted,
            "completed": completed,
            "checkedAt": now_iso(),
        }
        self.state_store.save_status(
            {
                "ok": True,
                "running": False,
                "lastCycleAt": now_iso(),
                "lastResult": result,
            }
        )
        return result

    def run_once(self) -> dict:
        lock_handle = self.acquire_lock()
        try:
            return self._run_once_unlocked()
        finally:
            self.release_lock(lock_handle)

    def serve_forever(self) -> None:
        poll_seconds = float(self.config["channel"]["pollSeconds"])
        while True:
            try:
                result = self.run_once()
                self.state_store.save_status(
                    {
                        "ok": True,
                        "running": True,
                        "lastCycleAt": now_iso(),
                        "lastResult": result,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.state_store.save_status(
                    {
                        "ok": False,
                        "running": True,
                        "lastCycleAt": now_iso(),
                        "error": str(exc),
                    }
                )
            time.sleep(poll_seconds)

    def status(self) -> dict:
        pid = self.state_store.running_pid()
        running = False
        if pid is not None:
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'yes' }} else {{ 'no' }}"],
                capture_output=True,
                text=True,
                check=False,
            )
            running = process.stdout.strip() == "yes"
        status = self.state_store.load_status()
        return {
            "ok": True,
            "running": running,
            "pid": pid,
            "pidPath": str(self.state_store.pid_path),
            "statePath": str(self.state_store.state_path),
            "statusPath": str(self.state_store.status_path),
            "status": status,
            "allowSenders": self.config["mailbox"]["allowSenders"],
            "subjectPrefix": self.config["mailbox"]["subjectPrefix"],
            "markers": self.config["markers"],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["serve", "run-once", "status", "send-mail"])
    parser.add_argument("--to")
    parser.add_argument("--subject")
    parser.add_argument("--body")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    channel = GmailCommandChannel()

    if args.mode == "serve":
        channel.serve_forever()
        return

    if args.mode == "run-once":
        print(json.dumps(channel.run_once(), ensure_ascii=False, indent=2))
        return

    if args.mode == "status":
        print(json.dumps(channel.status(), ensure_ascii=False, indent=2))
        return

    if args.mode == "send-mail":
        if not args.to or not args.subject or args.body is None:
            raise SystemExit("--to, --subject, and --body are required for send-mail mode.")
        print(json.dumps(channel.send_mail(args.to, args.subject, args.body, verify=args.verify), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
