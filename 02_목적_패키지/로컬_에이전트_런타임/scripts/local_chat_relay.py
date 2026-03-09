import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8767
CACHE_TTL_SECONDS = 2.0
SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parent
PACKAGE_GROUP_ROOT = PACKAGE_ROOT.parent
TOOL_ROOT = PACKAGE_GROUP_ROOT.parent
DOCS_ROOT = TOOL_ROOT / "docs"
TRUSTED_ORIGINS = {
    "https://frysquirrel-a.github.io",
    "https://frysquirrel-a.github.io/codex-local-agent-tools/",
    "http://127.0.0.1:8767",
    "http://localhost:8767",
    "null",
}
STATIC_FILES = {
    "/": (DOCS_ROOT / "index.html", "text/html; charset=utf-8"),
    "/index.html": (DOCS_ROOT / "index.html", "text/html; charset=utf-8"),
    "/app.js": (DOCS_ROOT / "app.js", "application/javascript; charset=utf-8"),
    "/styles.css": (DOCS_ROOT / "styles.css", "text/css; charset=utf-8"),
}


def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RelayState:
    def __init__(self) -> None:
        self.script_root = Path(__file__).resolve().parent
        self.package_root = self.script_root.parent
        self.config_dir = self.package_root / "config"
        self.state_dir = self.package_root / "state"
        self.channel_path = self.config_dir / "remote_command_channel.json"
        self.queue_path = self.state_dir / "remote_command_queue.json"
        self.sessions_path = self.state_dir / "chat_portal_sessions.json"
        self.check_script = self.script_root / "check_remote_commands.ps1"
        self.execute_script = self.script_root / "execute_remote_command_inbox.ps1"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.channel = self.read_json_file(self.channel_path)
        self.session_lock = threading.Lock()
        self.issue_cache: dict[int, tuple[float, dict]] = {}
        self.comment_cache: dict[int, tuple[float, list]] = {}

    @staticmethod
    def read_json_file(path: Path, default=None):
        if not path.exists():
            return {} if default is None else default
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def read_sessions(self) -> dict:
        return self.read_json_file(self.sessions_path, {"sessions": {}})

    def write_sessions(self, payload: dict) -> None:
        self.sessions_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def ensure_session(self, session_id: str) -> dict:
        session_id = (session_id or "").strip()
        if not session_id:
            raise ValueError("sessionId is required.")

        with self.session_lock:
            payload = self.read_sessions()
            sessions = payload.setdefault("sessions", {})
            session = sessions.get(session_id)
            if not session:
                session = {
                    "sessionId": session_id,
                    "createdAt": now_iso(),
                    "updatedAt": now_iso(),
                    "issueNumbers": [],
                }
                sessions[session_id] = session
                self.write_sessions(payload)
            return session

    def append_issue_to_session(self, session_id: str, issue_number: int) -> None:
        with self.session_lock:
            payload = self.read_sessions()
            sessions = payload.setdefault("sessions", {})
            session = sessions.setdefault(
                session_id,
                {
                    "sessionId": session_id,
                    "createdAt": now_iso(),
                    "updatedAt": now_iso(),
                    "issueNumbers": [],
                },
            )
            issue_numbers = [int(value) for value in session.get("issueNumbers", [])]
            if issue_number not in issue_numbers:
                issue_numbers.append(issue_number)
            session["issueNumbers"] = issue_numbers
            session["updatedAt"] = now_iso()
            self.write_sessions(payload)

    def get_github_headers(self) -> dict:
        completed = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("GitHub credentials were not available from git credential fill.")

        token = ""
        for line in completed.stdout.splitlines():
            if line.startswith("password="):
                token = line.partition("=")[2].strip()
                break

        if not token:
            raise RuntimeError("GitHub token was empty.")

        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodexLocalChatRelay",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def github_request(self, method: str, path: str, body=None):
        url = f"{self.channel['apiBase']}{path}"
        data = None
        headers = self.get_github_headers()
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)

    def get_issue(self, issue_number: int) -> dict:
        cached = self.issue_cache.get(issue_number)
        if cached and time.time() - cached[0] <= CACHE_TTL_SECONDS:
            return cached[1]
        issue = self.github_request(
            "GET",
            f"/repos/{self.channel['owner']}/{self.channel['repo']}/issues/{issue_number}",
        )
        self.issue_cache[issue_number] = (time.time(), issue)
        return issue

    def get_comments(self, issue_number: int) -> list:
        cached = self.comment_cache.get(issue_number)
        if cached and time.time() - cached[0] <= CACHE_TTL_SECONDS:
            return cached[1]
        comments = self.github_request(
            "GET",
            f"/repos/{self.channel['owner']}/{self.channel['repo']}/issues/{issue_number}/comments",
        )
        comments = comments or []
        self.comment_cache[issue_number] = (time.time(), comments)
        return comments

    def create_issue(self, title: str, body: str) -> dict:
        return self.github_request(
            "POST",
            f"/repos/{self.channel['owner']}/{self.channel['repo']}/issues",
            {
                "title": f"{self.channel['titlePrefix']} {title}",
                "body": body,
                "labels": [self.channel["label"]],
            },
        )

    def load_queue_map(self) -> dict[int, dict]:
        payload = self.read_json_file(self.queue_path, [])
        return {int(item["number"]): item for item in payload}

    def trigger_pipeline(self, issue_number: int) -> None:
        def worker():
            base = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
            subprocess.run(base + [str(self.check_script)], capture_output=True, text=True, check=False)
            subprocess.run(
                base + [str(self.execute_script), "-Number", str(issue_number)],
                capture_output=True,
                text=True,
                check=False,
            )

        threading.Thread(target=worker, daemon=True).start()


STATE = RelayState()


SECTION_PATTERN = r"###\s+{heading}\s*\n([\s\S]*?)(?=\n###\s+|$)"


def parse_section(body: str, heading: str) -> str:
    if not body:
        return ""
    match = re.search(SECTION_PATTERN.format(heading=re.escape(heading)), body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def derive_title(text: str) -> str:
    compact = normalize_text(text)
    if not compact:
        return "chat message"
    return compact[:52] + ("..." if len(compact) > 52 else "")


def build_issue_body(command: str, priority: str, target: str, notes: str) -> str:
    return "\n".join(
        [
            "## Remote Command",
            "",
            "### Command",
            command,
            "",
            "### Priority",
            priority,
            "",
            "### Target",
            target,
            "",
            "### Notes",
            notes or "-",
            "",
            "### Requested At",
            now_local(),
        ]
    )


def build_status_entry(issue_number: int, queue_item: dict | None, issue: dict) -> dict:
    state = (queue_item or {}).get("status", "")
    if state == "new":
        text = "Codex가 메시지를 받아 큐에 올리는 중"
        tone = "queued"
    elif state == "pending":
        text = "Codex가 작업을 실행 중"
        tone = "running"
    elif state == "failed":
        text = normalize_text((queue_item or {}).get("result", "")) or "작업이 실패했지만 상세 요약이 아직 오지 않았습니다."
        tone = "error"
    elif issue.get("state") == "closed":
        text = "작업이 종료되었습니다."
        tone = "done"
    else:
        text = "Codex가 메시지를 확인 중"
        tone = "queued"

    timestamp = (queue_item or {}).get("processedAt") or issue.get("updated_at") or issue.get("created_at")
    return {
        "id": f"status-{issue_number}",
        "kind": "status",
        "tone": tone,
        "text": text,
        "createdAt": timestamp,
        "issueNumber": issue_number,
    }


def parse_executor_comment(body: str) -> dict | None:
    if not body:
        return None

    details = {}
    for key, value in re.findall(r"^- ([^:]+):\s*(.+)$", body, re.MULTILINE):
        details[key.strip().lower()] = value.strip()

    paragraphs = [
        normalize_text(part)
        for part in re.split(r"\n\s*\n", body)
        if normalize_text(part)
    ]
    paragraphs = [
        part for part in paragraphs if not part.startswith("## Codex Remote Executor") and not part.startswith("- ")
    ]

    status = details.get("status", "").lower()
    summary = paragraphs[-1] if paragraphs else ""
    tone = "done" if status == "success" else ("error" if status in {"failed", "blocked"} else "review")
    title = normalize_text(" · ".join(value for value in [details.get("mode", ""), details.get("action", "")] if value))
    if not title:
        title = "Codex 응답"

    return {
        "status": status or "update",
        "tone": tone,
        "title": title,
        "text": summary or "작업 상태가 업데이트되었습니다.",
        "timestamp": details.get("timestamp", ""),
    }


def build_transcript(issue_numbers: list[int]) -> list[dict]:
    entries = []
    queue_map = STATE.load_queue_map()

    for issue_number in issue_numbers:
        issue = STATE.get_issue(issue_number)
        command_text = parse_section(issue.get("body", ""), "Command") or issue.get("title", "")
        created_at = issue.get("created_at") or now_iso()
        entries.append(
            {
                "id": f"user-{issue_number}",
                "kind": "message",
                "role": "user",
                "text": command_text,
                "createdAt": created_at,
                "issueNumber": issue_number,
            }
        )

        comments = STATE.get_comments(issue_number) if int(issue.get("comments", 0) or 0) > 0 else []
        executor_entry = None
        for comment in reversed(comments):
            parsed = parse_executor_comment(comment.get("body", ""))
            if parsed:
                executor_entry = {
                    "id": f"assistant-{issue_number}",
                    "kind": "message",
                    "role": "assistant",
                    "tone": parsed["tone"],
                    "title": parsed["title"],
                    "text": parsed["text"],
                    "createdAt": parsed["timestamp"] or comment.get("created_at") or issue.get("updated_at") or created_at,
                    "issueNumber": issue_number,
                    "status": parsed["status"],
                }
                break

        if executor_entry:
            entries.append(executor_entry)
        else:
            entries.append(build_status_entry(issue_number, queue_map.get(issue_number), issue))

    kind_order = {"message": 0, "status": 1}
    role_order = {"user": 0, "assistant": 1}
    entries.sort(
        key=lambda item: (
            item.get("createdAt") or "",
            kind_order.get(item.get("kind", ""), 9),
            role_order.get(item.get("role", ""), 9),
            item["id"],
        )
    )
    return entries


class Handler(BaseHTTPRequestHandler):
    server_version = "CodexLocalChatRelay/1.0"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin", "*")
        if origin not in TRUSTED_ORIGINS:
            origin = "*"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in STATIC_FILES:
            path, content_type = STATIC_FILES[parsed.path]
            if not path.exists():
                self.write_json(404, {"ok": False, "error": f"Static file not found: {path.name}"})
                return
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if parsed.path == "/status":
            payload = {
                "ok": True,
                "relay": "local-chat",
                "host": HOST,
                "port": PORT,
                "siteUrl": STATE.channel["siteUrl"],
                "localUiUrl": f"http://{HOST}:{PORT}/",
                "checkedAt": now_iso(),
            }
            self.write_json(200, payload)
            return

        if parsed.path == "/api/session":
            params = urllib.parse.parse_qs(parsed.query)
            session_id = (params.get("sessionId", [""])[0] or "").strip()
            session = STATE.ensure_session(session_id)
            issue_numbers = [int(value) for value in session.get("issueNumbers", [])]
            payload = {
                "ok": True,
                "relayAvailable": True,
                "sessionId": session_id,
                "issueNumbers": issue_numbers,
                "entries": build_transcript(issue_numbers),
                "updatedAt": now_iso(),
                "siteUrl": STATE.channel["siteUrl"],
            }
            self.write_json(200, payload)
            return

        self.write_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/message":
            self.write_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            raw_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(raw_length) if raw_length > 0 else b"{}"
            data = json.loads(raw_body.decode("utf-8"))
            session_id = (data.get("sessionId") or "").strip()
            text = (data.get("text") or "").strip()
            command = (data.get("command") or "").strip() or text
            notes = (data.get("notes") or "").strip()
            target = (data.get("target") or "other").strip() or "other"
            priority = (data.get("priority") or "normal").strip() or "normal"
            if not session_id:
                raise ValueError("sessionId is required.")
            if not command:
                raise ValueError("text is required.")

            STATE.ensure_session(session_id)
            notes_parts = []
            if notes:
                notes_parts.append(notes)
            if text and command != text:
                notes_parts.append(f"Message: {text}")
            notes_parts.append(f"Session-ID: {session_id}")
            notes_parts.append("Submitted-Via: local-chat-relay")
            issue_body = build_issue_body(command, priority, target, "\n\n".join(notes_parts))
            issue = STATE.create_issue(derive_title(text or command), issue_body)
            issue_number = int(issue["number"])
            STATE.append_issue_to_session(session_id, issue_number)
            STATE.trigger_pipeline(issue_number)

            payload = {
                "ok": True,
                "sessionId": session_id,
                "issueNumber": issue_number,
                "createdAt": issue.get("created_at"),
                "issueUrl": issue.get("html_url"),
            }
            self.write_json(200, payload)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self.write_json(error.code, {"ok": False, "error": detail or str(error)})
        except Exception as error:  # noqa: BLE001
            self.write_json(400, {"ok": False, "error": str(error)})

    def log_message(self, format_: str, *args) -> None:
        return

    def write_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
