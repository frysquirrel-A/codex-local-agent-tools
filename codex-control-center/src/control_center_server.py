from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import secrets
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


RECENT_HANDOFF_LIMIT = 12
RECENT_MESSAGE_LIMIT = 80
PBKDF2_ITERATIONS = 240_000
SESSION_TTL_SECONDS = 60 * 60 * 12
LOGIN_WINDOW_SECONDS = 60 * 10
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 60 * 15
SESSION_COOKIE_NAME = "cc_session"
CLOSED_STATUSES = {
    "closed",
    "done",
    "completed",
    "failed",
    "abandoned",
    "cancelled",
    "canceled",
    "skipped",
}


class ApiError(Exception):
    def __init__(
        self,
        status: HTTPStatus,
        code: str,
        detail: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = dict(extra or {})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(read_text_with_fallback(path))
    except Exception:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in read_text_with_fallback(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def trim_text(value: str | None, limit: int = 320) -> str:
    if not value:
        return ""
    compact = " ".join(str(value).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def parse_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def safe_get(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def build_message(
    role: str,
    kind: str,
    text: str,
    *,
    handoff_id: str = "",
    created_at: str | None = None,
    message_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": message_id or f"msg-{uuid.uuid4().hex[:12]}",
        "role": role,
        "kind": kind,
        "text": text,
        "createdAt": created_at or utc_now_iso(),
        "handoffId": handoff_id,
        "meta": dict(meta or {}),
    }


def hash_password(password: str, salt_hex: str) -> str:
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    )
    return derived.hex()


def make_setup_code() -> str:
    return "CC-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))


@dataclass
class RuntimePaths:
    repo_root: Path
    runtime_root: Path
    state_root: Path
    config_root: Path
    helper_handoff_inbox: Path
    helper_reports_root: Path
    dispatch_script: Path
    helper_async_start_script: Path
    helper_async_status_path: Path

    @classmethod
    def detect(cls, explicit_runtime_root: str | None) -> "RuntimePaths":
        current = Path(__file__).resolve()
        repo_root = current.parents[2]
        tool_root = repo_root / "00_Codex_도구"
        runtime_root = (
            Path(explicit_runtime_root).resolve()
            if explicit_runtime_root
            else tool_root / "03_로컬_에이전트_런타임"
        )
        if not runtime_root.exists():
            fallback = next((item for item in tool_root.glob("03_*") if item.is_dir()), runtime_root)
            runtime_root = fallback
        return cls(
            repo_root=repo_root,
            runtime_root=runtime_root,
            state_root=runtime_root / "state",
            config_root=runtime_root / "config",
            helper_handoff_inbox=runtime_root / "state" / "helper_handoffs" / "inbox",
            helper_reports_root=runtime_root / "state" / "helper_handoffs" / "reports",
            dispatch_script=runtime_root / "scripts" / "dispatch_codex_helper_handoffs.py",
            helper_async_start_script=runtime_root / "scripts" / "start_helper_async_runtime.ps1",
            helper_async_status_path=runtime_root / "state" / "helper_async_runtime" / "status.json",
        )


@dataclass
class CommandCenterPaths:
    root: Path
    messages_path: Path
    ptt_path: Path
    auth_path: Path
    bootstrap_path: Path
    public_tunnel_status_path: Path

    @classmethod
    def detect(cls, repo_root: Path) -> "CommandCenterPaths":
        root = repo_root / "codex-control-center" / "state"
        root.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            messages_path=root / "messages.jsonl",
            ptt_path=root / "ptt.json",
            auth_path=root / "auth.json",
            bootstrap_path=root / "bootstrap_setup.json",
            public_tunnel_status_path=root / "public_tunnel_status.json",
        )


class AuthManager:
    def __init__(self, command_paths: CommandCenterPaths) -> None:
        self.command_paths = command_paths
        self.sessions: dict[str, dict[str, Any]] = {}
        self.login_attempts: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.ensure_bootstrap_code()

    def ensure_bootstrap_code(self) -> None:
        if self.command_paths.auth_path.exists():
            return
        existing = read_json(self.command_paths.bootstrap_path, {})
        if existing.get("setupCode"):
            return
        payload = {
            "setupCode": make_setup_code(),
            "createdAt": utc_now_iso(),
            "note": "Use this one-time code to finish first-time setup for Codex Command Center.",
        }
        write_json(self.command_paths.bootstrap_path, payload)

    def setup_required(self) -> bool:
        return not self.command_paths.auth_path.exists()

    def auth_state(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.read_session(handler)
        return {
            "ok": True,
            "authenticated": bool(session),
            "setupRequired": self.setup_required(),
            "csrfToken": session.get("csrfToken", "") if session else "",
            "sessionExpiresAt": session.get("expiresAt", "") if session else "",
        }

    def read_session(self, handler: "ControlCenterHandler") -> dict[str, Any] | None:
        cookie_header = handler.headers.get("Cookie", "")
        if not cookie_header:
            return None
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        morsel = cookies.get(SESSION_COOKIE_NAME)
        if morsel is None:
            return None
        session_id = morsel.value
        now = time.time()
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            if float(session.get("expiresAtEpoch", 0)) <= now:
                self.sessions.pop(session_id, None)
                return None
            session["expiresAtEpoch"] = now + SESSION_TTL_SECONDS
            session["expiresAt"] = datetime.fromtimestamp(
                session["expiresAtEpoch"], tz=timezone.utc
            ).astimezone().isoformat(timespec="seconds")
            session["lastSeenAt"] = utc_now_iso()
            return dict(session)

    def require_session(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.read_session(handler)
        if not session:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "auth_required", "로그인이 필요합니다.")
        return session

    def require_csrf(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.require_session(handler)
        csrf_token = handler.headers.get("X-CSRF-Token", "").strip()
        if not csrf_token or not hmac.compare_digest(csrf_token, str(session.get("csrfToken", ""))):
            raise ApiError(
                HTTPStatus.FORBIDDEN,
                "invalid_csrf",
                "요청을 확인할 수 없습니다. 다시 로그인해 주세요.",
            )
        return session

    def setup(self, handler: "ControlCenterHandler", setup_code: str, password: str) -> tuple[dict[str, Any], str]:
        if not self.setup_required():
            raise ApiError(HTTPStatus.CONFLICT, "setup_complete", "이미 초기 설정이 완료되었습니다.")
        if len(password) < 12:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "weak_password",
                "비밀번호는 12자 이상으로 설정해 주세요.",
            )
        bootstrap = read_json(self.command_paths.bootstrap_path, {})
        expected = str(bootstrap.get("setupCode") or "")
        if not expected:
            self.ensure_bootstrap_code()
            bootstrap = read_json(self.command_paths.bootstrap_path, {})
            expected = str(bootstrap.get("setupCode") or "")
        if not hmac.compare_digest(expected, setup_code.strip()):
            self._register_failed_attempt(self.client_identity(handler))
            raise ApiError(
                HTTPStatus.UNAUTHORIZED,
                "invalid_setup_code",
                "설정 코드가 맞지 않습니다.",
            )

        salt_hex = secrets.token_hex(16)
        auth_payload = {
            "salt": salt_hex,
            "passwordHash": hash_password(password, salt_hex),
            "createdAt": utc_now_iso(),
            "passwordChangedAt": utc_now_iso(),
        }
        write_json(self.command_paths.auth_path, auth_payload)
        if self.command_paths.bootstrap_path.exists():
            self.command_paths.bootstrap_path.unlink()

        self._clear_failed_attempts(self.client_identity(handler))
        session, cookie = self._create_session(handler)
        return (
            {
                "ok": True,
                "auth": {
                    "authenticated": True,
                    "setupRequired": False,
                    "csrfToken": session["csrfToken"],
                    "sessionExpiresAt": session["expiresAt"],
                },
            },
            cookie,
        )

    def login(self, handler: "ControlCenterHandler", password: str) -> tuple[dict[str, Any], str]:
        if self.setup_required():
            raise ApiError(
                HTTPStatus.CONFLICT,
                "setup_required",
                "먼저 최초 설정을 완료해 주세요.",
            )

        self._check_login_allowed(self.client_identity(handler))
        auth_payload = read_json(self.command_paths.auth_path, {})
        salt_hex = str(auth_payload.get("salt") or "")
        expected_hash = str(auth_payload.get("passwordHash") or "")
        provided_hash = hash_password(password, salt_hex) if salt_hex else ""
        if not expected_hash or not hmac.compare_digest(expected_hash, provided_hash):
            self._register_failed_attempt(self.client_identity(handler))
            raise ApiError(
                HTTPStatus.UNAUTHORIZED,
                "invalid_credentials",
                "비밀번호가 맞지 않습니다.",
            )

        self._clear_failed_attempts(self.client_identity(handler))
        session, cookie = self._create_session(handler)
        return (
            {
                "ok": True,
                "auth": {
                    "authenticated": True,
                    "setupRequired": False,
                    "csrfToken": session["csrfToken"],
                    "sessionExpiresAt": session["expiresAt"],
                },
            },
            cookie,
        )

    def logout(self, handler: "ControlCenterHandler") -> tuple[dict[str, Any], str]:
        cookie_header = handler.headers.get("Cookie", "")
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        morsel = cookies.get(SESSION_COOKIE_NAME)
        if morsel is not None:
            with self.lock:
                self.sessions.pop(morsel.value, None)
        return (
            {"ok": True, "auth": {"authenticated": False, "setupRequired": self.setup_required()}},
            self._build_clear_cookie(handler),
        )

    # Code-only auth overrides: keep session/CSRF/lockout protections, remove password prompts.
    def ensure_bootstrap_code(self) -> None:
        existing = read_json(self.command_paths.bootstrap_path, {})
        if existing.get("setupCode"):
            return
        payload = {
            "setupCode": make_setup_code(),
            "createdAt": utc_now_iso(),
            "note": "Use this access code to sign in to Codex Command Center.",
        }
        write_json(self.command_paths.bootstrap_path, payload)

    def setup_required(self) -> bool:
        return False

    def current_access_code(self) -> tuple[str, dict[str, Any]]:
        self.ensure_bootstrap_code()
        bootstrap = read_json(self.command_paths.bootstrap_path, {})
        code = str(bootstrap.get("setupCode") or "").strip()
        if code:
            return code, bootstrap
        bootstrap = {
            "setupCode": make_setup_code(),
            "createdAt": utc_now_iso(),
            "note": "Use this access code to sign in to Codex Command Center.",
        }
        write_json(self.command_paths.bootstrap_path, bootstrap)
        return str(bootstrap["setupCode"]), bootstrap

    def _auth_payload(self, session: dict[str, Any] | None) -> dict[str, Any]:
        _, bootstrap = self.current_access_code()
        return {
            "authenticated": bool(session),
            "setupRequired": False,
            "codeOnly": True,
            "codeLabel": "접속 코드",
            "codeIssuedAt": str(bootstrap.get("createdAt") or ""),
            "csrfToken": session.get("csrfToken", "") if session else "",
            "sessionExpiresAt": session.get("expiresAt", "") if session else "",
        }

    def auth_state(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.read_session(handler)
        return {"ok": True, **self._auth_payload(session)}

    def setup(self, handler: "ControlCenterHandler", setup_code: str, password: str) -> tuple[dict[str, Any], str]:
        return self.login(handler, setup_code or password)

    def login(self, handler: "ControlCenterHandler", access_code: str) -> tuple[dict[str, Any], str]:
        self._check_login_allowed(self.client_identity(handler))
        expected_code, _bootstrap = self.current_access_code()
        if not expected_code or not hmac.compare_digest(expected_code, access_code.strip()):
            self._register_failed_attempt(self.client_identity(handler))
            raise ApiError(
                HTTPStatus.UNAUTHORIZED,
                "invalid_credentials",
                "접속 코드가 맞지 않습니다.",
            )

        self._clear_failed_attempts(self.client_identity(handler))
        session, cookie = self._create_session(handler)
        return (
            {
                "ok": True,
                "auth": self._auth_payload(session),
            },
            cookie,
        )

    def logout(self, handler: "ControlCenterHandler") -> tuple[dict[str, Any], str]:
        cookie_header = handler.headers.get("Cookie", "")
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        morsel = cookies.get(SESSION_COOKIE_NAME)
        if morsel is not None:
            with self.lock:
                self.sessions.pop(morsel.value, None)
        return (
            {"ok": True, "auth": self._auth_payload(None)},
            self._build_clear_cookie(handler),
        )

    def client_identity(self, handler: "ControlCenterHandler") -> str:
        forwarded = handler.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
        return str(handler.client_address[0] if handler.client_address else "unknown")

    def request_is_https(self, handler: "ControlCenterHandler") -> bool:
        forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_proto:
            return forwarded_proto == "https"
        forwarded = handler.headers.get("Forwarded", "").lower()
        return "proto=https" in forwarded

    def _create_session(self, handler: "ControlCenterHandler") -> tuple[dict[str, Any], str]:
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        expires_epoch = now + SESSION_TTL_SECONDS
        session = {
            "sessionId": session_id,
            "csrfToken": secrets.token_urlsafe(24),
            "createdAt": utc_now_iso(),
            "lastSeenAt": utc_now_iso(),
            "expiresAtEpoch": expires_epoch,
            "expiresAt": datetime.fromtimestamp(expires_epoch, tz=timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds"),
            "client": self.client_identity(handler),
        }
        with self.lock:
            self.sessions[session_id] = dict(session)
        return session, self._build_session_cookie(session_id, handler)

    def _build_session_cookie(self, session_id: str, handler: "ControlCenterHandler") -> str:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE_NAME] = session_id
        cookie[SESSION_COOKIE_NAME]["path"] = "/"
        cookie[SESSION_COOKIE_NAME]["httponly"] = True
        cookie[SESSION_COOKIE_NAME]["samesite"] = "Strict"
        if self.request_is_https(handler):
            cookie[SESSION_COOKIE_NAME]["secure"] = True
        return cookie.output(header="").strip()

    def _build_clear_cookie(self, handler: "ControlCenterHandler") -> str:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE_NAME] = ""
        cookie[SESSION_COOKIE_NAME]["path"] = "/"
        cookie[SESSION_COOKIE_NAME]["httponly"] = True
        cookie[SESSION_COOKIE_NAME]["samesite"] = "Strict"
        cookie[SESSION_COOKIE_NAME]["max-age"] = 0
        cookie[SESSION_COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        if self.request_is_https(handler):
            cookie[SESSION_COOKIE_NAME]["secure"] = True
        return cookie.output(header="").strip()

    def _check_login_allowed(self, client_id: str) -> None:
        with self.lock:
            record = self.login_attempts.get(client_id, {})
            lock_until = float(record.get("lockUntilEpoch", 0))
            if lock_until > time.time():
                remaining = int(lock_until - time.time())
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "login_locked",
                    f"로그인 시도가 많아 잠시 잠겼습니다. {remaining}초 후 다시 시도해 주세요.",
                )

    def _register_failed_attempt(self, client_id: str) -> None:
        now = time.time()
        with self.lock:
            record = self.login_attempts.setdefault(client_id, {"attempts": [], "lockUntilEpoch": 0})
            attempts = [ts for ts in record.get("attempts", []) if now - float(ts) <= LOGIN_WINDOW_SECONDS]
            attempts.append(now)
            record["attempts"] = attempts
            if len(attempts) >= LOGIN_MAX_ATTEMPTS:
                record["lockUntilEpoch"] = now + LOGIN_LOCK_SECONDS
            self.login_attempts[client_id] = record

    def _clear_failed_attempts(self, client_id: str) -> None:
        with self.lock:
            self.login_attempts.pop(client_id, None)


class SnapshotBuilder:
    def __init__(self, runtime_paths: RuntimePaths, command_paths: CommandCenterPaths) -> None:
        self.runtime_paths = runtime_paths
        self.command_paths = command_paths

    def build(self) -> dict[str, Any]:
        roster = read_json(self.runtime_paths.config_root / "codex_helper_thread_roster.json", {})
        registry = read_json(self.runtime_paths.config_root / "llm_thread_registry.json", {})
        helper_status = read_json(self.runtime_paths.state_root / "helper_handoffs" / "status.json", {})
        scheduler_status = read_json(self.runtime_paths.state_root / "central_scheduler" / "status.json", {})
        watchdog_status = read_json(
            self.runtime_paths.state_root / "turn_continuation_watchdog" / "status.json", {}
        )
        gmail_status = read_json(self.runtime_paths.state_root / "gmail_command_channel_status.json", {})
        async_status = read_json(self.runtime_paths.helper_async_status_path, {})
        ptt_state = read_json(
            self.command_paths.ptt_path,
            {"recording": False, "updatedAt": "", "source": "idle"},
        )

        helper_by_title = {
            thread.get("title"): thread for thread in roster.get("threads", []) if thread.get("title")
        }
        helper_by_responsibility = {
            thread.get("responsibility"): thread
            for thread in roster.get("threads", [])
            if thread.get("responsibility")
        }

        handoffs = self._load_recent_handoffs()

        return {
            "generatedAt": utc_now_iso(),
            "paths": {
                "repoRoot": str(self.runtime_paths.repo_root),
                "runtimeRoot": str(self.runtime_paths.runtime_root),
                "helperInbox": str(self.runtime_paths.helper_handoff_inbox),
                "helperReports": str(self.runtime_paths.helper_reports_root),
                "commandCenterState": str(self.command_paths.root),
                "publicTunnelStatus": str(self.command_paths.public_tunnel_status_path),
            },
            "overview": {
                "watchdog": {
                    "taskId": watchdog_status.get("taskId", ""),
                    "status": watchdog_status.get("status", ""),
                    "decision": watchdog_status.get("decision", ""),
                    "queueDecision": watchdog_status.get("queueDecision", ""),
                    "heartbeatAgeSeconds": watchdog_status.get("heartbeatAgeSeconds", 0),
                    "heartbeatStale": watchdog_status.get("heartbeatStale", False),
                    "queueEmpty": safe_get(watchdog_status, "queueReview", "queueEmpty", default=False),
                    "reasons": safe_get(
                        watchdog_status, "resourceGuardStatus", "reasons", default=[]
                    ),
                },
                "helpers": {
                    "handoffCount": helper_status.get("handoffCount", 0),
                    "pendingAssignmentCount": helper_status.get("pendingAssignmentCount", 0),
                    "staleAssignmentCount": helper_status.get("staleAssignmentCount", 0),
                },
                "scheduler": {
                    "jobCount": scheduler_status.get("jobCount", 0),
                    "openJobCount": scheduler_status.get("openJobCount", 0),
                },
                "gmail": {
                    "running": gmail_status.get("running"),
                    "skipReason": gmail_status.get("skipReason", ""),
                    "updatedAt": gmail_status.get("updatedAt") or gmail_status.get("lastCycleAt", ""),
                },
                "asyncRuntime": {
                    "running": async_status.get("running", False),
                    "updatedAt": async_status.get("updatedAt", ""),
                    "notifiedCount": async_status.get("notifiedCount", 0),
                },
            },
            "ptt": ptt_state,
            "conversation": self._build_conversation(handoffs),
            "threads": self._build_threads(roster, registry, helper_status),
            "messageFlows": self._build_flows(handoffs, helper_by_title, helper_by_responsibility),
            "alerts": self._build_alerts(helper_status, scheduler_status, watchdog_status, gmail_status, async_status),
        }

    def _load_recent_handoffs(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.runtime_paths.helper_handoff_inbox.exists():
            return items
        files = sorted(
            self.runtime_paths.helper_handoff_inbox.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:RECENT_HANDOFF_LIMIT]
        for path in files:
            handoff = read_json(path, {})
            if not handoff:
                continue
            handoff["_path"] = str(path)
            items.append(handoff)
        return items

    def _build_threads(
        self, roster: dict[str, Any], registry: dict[str, Any], helper_status: dict[str, Any]
    ) -> list[dict[str, Any]]:
        helper_summary = {
            item.get("responsibility"): item
            for item in helper_status.get("helperSummary", [])
            if item.get("responsibility")
        }
        threads: list[dict[str, Any]] = []

        leader = roster.get("leader", {})
        threads.append(
            {
                "kind": "main",
                "displayName": leader.get("title", "main:orchestrator"),
                "title": leader.get("title", "main:orchestrator"),
                "role": leader.get("role", ""),
                "stats": {},
            }
        )

        for thread in roster.get("threads", []):
            summary = helper_summary.get(thread.get("responsibility"), {})
            threads.append(
                {
                    "kind": "helper",
                    "displayName": thread.get("title", ""),
                    "title": thread.get("title", ""),
                    "role": thread.get("role", ""),
                    "stats": {
                        "responsibility": thread.get("responsibility", ""),
                        "queued": summary.get("queued", 0),
                        "running": summary.get("running", 0),
                        "pending": summary.get("pending", 0),
                        "oldestPendingMinutes": summary.get("oldestPendingMinutes", 0),
                    },
                }
            )

        for provider_name, provider in registry.get("providers", {}).items():
            default_title = provider.get("defaultThreadTitle")
            if default_title:
                threads.append(
                    {
                        "kind": "provider",
                        "displayName": default_title,
                        "title": f"{provider_name}:default",
                        "role": f"{provider_name} 기본 스레드",
                        "stats": {"url": provider.get("defaultThreadUrl", "")},
                    }
                )
            for route in provider.get("routes", []):
                threads.append(
                    {
                        "kind": "provider-route",
                        "displayName": route.get("title", ""),
                        "title": f"{provider_name}:route",
                        "role": f"{provider_name} 라우팅 스레드",
                        "stats": {
                            "url": route.get("url", ""),
                            "keywords": route.get("keywords", []),
                        },
                    }
                )
        return threads

    def _build_flows(
        self,
        handoffs: list[dict[str, Any]],
        helper_by_title: dict[str, dict[str, Any]],
        helper_by_responsibility: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        flows: list[dict[str, Any]] = []
        for handoff in handoffs:
            assignments = []
            for assignment in handoff.get("assignments", []):
                roster_thread = helper_by_responsibility.get(assignment.get("responsibility")) or helper_by_title.get(
                    assignment.get("helperTitle")
                )
                assignments.append(
                    {
                        "assignmentId": assignment.get("assignmentId", ""),
                        "helperTitle": roster_thread.get("title") if roster_thread else assignment.get("helperTitle", ""),
                        "helperRole": roster_thread.get("role") if roster_thread else assignment.get("helperRole", ""),
                        "helperThreadId": assignment.get("helperThreadId", ""),
                        "status": assignment.get("status", ""),
                        "step": assignment.get("step", ""),
                        "updatedAt": assignment.get("updatedAt", ""),
                        "requestPreview": trim_text(assignment.get("handoffPrompt", ""), 180),
                        "responsePreview": trim_text(assignment.get("responseText", ""), 240),
                    }
                )

            flows.append(
                {
                    "handoffId": handoff.get("handoffId", ""),
                    "createdAt": handoff.get("createdAt", ""),
                    "route": safe_get(handoff, "route", "route", default=""),
                    "routeLabel": safe_get(handoff, "route", "routeLabel", default=""),
                    "sourceTitle": safe_get(handoff, "source", "title", default=""),
                    "sourceNotes": safe_get(handoff, "source", "notes", default=""),
                    "taskPreview": trim_text(handoff.get("taskText", ""), 180),
                    "path": handoff.get("_path", ""),
                    "assignments": assignments,
                }
            )

        flows.sort(
            key=lambda item: max(
                parse_timestamp(item.get("createdAt")),
                *[parse_timestamp(entry.get("updatedAt")) for entry in item.get("assignments", [])],
            ),
            reverse=True,
        )
        return flows

    def _build_conversation(self, handoffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = read_jsonl(self.command_paths.messages_path)[-RECENT_MESSAGE_LIMIT:]
        handoff_map = {str(item.get("handoffId") or ""): item for item in handoffs}
        conversation: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for message in messages:
            message_id = str(message.get("id") or "")
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            conversation.append(
                {
                    "id": message_id,
                    "role": str(message.get("role") or "system"),
                    "kind": str(message.get("kind") or "status"),
                    "text": str(message.get("text") or ""),
                    "createdAt": str(message.get("createdAt") or ""),
                    "handoffId": str(message.get("handoffId") or ""),
                }
            )

            handoff_id = str(message.get("handoffId") or "")
            handoff = handoff_map.get(handoff_id)
            if not handoff or not self._handoff_is_closed(handoff):
                continue

            result_text = self._summarize_handoff_result(handoff)
            if not result_text:
                continue

            synthetic_id = f"result:{handoff_id}"
            if synthetic_id in seen_ids:
                continue
            seen_ids.add(synthetic_id)
            conversation.append(
                {
                    "id": synthetic_id,
                    "role": "assistant",
                    "kind": "result",
                    "text": result_text,
                    "createdAt": self._handoff_latest_timestamp(handoff)
                    or str(message.get("createdAt") or ""),
                    "handoffId": handoff_id,
                }
            )

        conversation.sort(
            key=lambda item: (parse_timestamp(item.get("createdAt")), item.get("id", "")),
        )
        return conversation[-RECENT_MESSAGE_LIMIT:]

    def _handoff_is_closed(self, handoff: dict[str, Any]) -> bool:
        assignments = list(handoff.get("assignments") or [])
        return bool(assignments) and all(
            str(item.get("status") or "").strip().lower() in CLOSED_STATUSES for item in assignments
        )

    def _handoff_latest_timestamp(self, handoff: dict[str, Any]) -> str:
        timestamps = [str(handoff.get("createdAt") or "")]
        timestamps.extend(str(item.get("updatedAt") or "") for item in handoff.get("assignments", []))
        timestamps = [item for item in timestamps if item]
        if not timestamps:
            return ""
        return max(timestamps, key=parse_timestamp)

    def _summarize_handoff_result(self, handoff: dict[str, Any]) -> str:
        for assignment in handoff.get("assignments", []):
            response = trim_text(str(assignment.get("responseText") or ""), 320)
            if response:
                return response
        return trim_text(str(handoff.get("taskText") or ""), 220)

    def _build_alerts(
        self,
        helper_status: dict[str, Any],
        scheduler_status: dict[str, Any],
        watchdog_status: dict[str, Any],
        gmail_status: dict[str, Any],
        async_status: dict[str, Any],
    ) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []

        stale = int(helper_status.get("staleAssignmentCount", 0) or 0)
        if stale:
            alerts.append(
                {
                    "level": "warn",
                    "title": "정리되지 않은 helper assignment가 있습니다",
                    "detail": f"현재 stale helper assignment가 {stale}건 남아 있습니다.",
                }
            )

        open_jobs = int(scheduler_status.get("openJobCount", 0) or 0)
        if open_jobs:
            alerts.append(
                {
                    "level": "info",
                    "title": "중앙 스케줄러에 열린 작업이 있습니다",
                    "detail": f"현재 open job 수는 {open_jobs}건입니다.",
                }
            )

        if watchdog_status.get("heartbeatStale"):
            alerts.append(
                {
                    "level": "critical",
                    "title": "watchdog heartbeat가 stale 상태입니다",
                    "detail": "자동 이어가기 감시 상태를 다시 확인해야 합니다.",
                }
            )

        reasons = list(safe_get(watchdog_status, "resourceGuardStatus", "reasons", default=[]))
        if reasons:
            alerts.append(
                {
                    "level": "info",
                    "title": "자원 가드가 일부 작업을 보류 중입니다",
                    "detail": ", ".join(str(item) for item in reasons),
                }
            )

        skip_reason = str(gmail_status.get("skipReason") or "").strip()
        if skip_reason:
            alerts.append(
                {
                    "level": "warn",
                    "title": "Gmail 채널이 일부 주기를 건너뛰었습니다",
                    "detail": skip_reason,
                }
            )

        if not async_status.get("running", False):
            alerts.append(
                {
                    "level": "warn",
                    "title": "async helper 런타임이 꺼져 있습니다",
                    "detail": "백그라운드 결과 팝업과 보고서 생성이 멈출 수 있습니다.",
                }
            )

        return alerts


class ControlCenterHandler(SimpleHTTPRequestHandler):
    static_root: Path
    snapshot_builder: SnapshotBuilder
    runtime_paths: RuntimePaths
    command_paths: CommandCenterPaths
    auth_manager: AuthManager

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed == "/":
            parsed = "/index.html"
        return str(self.static_root / parsed.lstrip("/"))

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for key, value in headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0").strip()
        content_length = int(raw_length) if raw_length.isdigit() else 0
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if not raw:
            return {}
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_body", f"본문을 읽을 수 없습니다: {exc}") from exc
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json", f"JSON 형식이 올바르지 않습니다: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json", "객체 형태의 JSON 본문이 필요합니다.")
        return parsed

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, {"ok": True, "generatedAt": utc_now_iso()})
                return
            if parsed.path == "/api/auth/state":
                self._send_json(HTTPStatus.OK, self.auth_manager.auth_state(self))
                return
            if parsed.path == "/api/snapshot":
                self.auth_manager.require_session(self)
                self._send_json(HTTPStatus.OK, self.snapshot_builder.build())
                return
            return super().do_GET()
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.code, "detail": exc.detail, **exc.extra})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/login":
                body = self._read_json_body()
                password = str(body.get("password") or "")
                if not password:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "password_required", "비밀번호를 입력해 주세요.")
                payload, cookie = self.auth_manager.login(self, password)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/auth/setup":
                body = self._read_json_body()
                setup_code = str(body.get("setupCode") or "")
                password = str(body.get("password") or "")
                confirm = str(body.get("confirmPassword") or "")
                if not setup_code:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "setup_code_required", "설정 코드를 입력해 주세요.")
                if not password:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "password_required", "비밀번호를 입력해 주세요.")
                if password != confirm:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "password_mismatch", "비밀번호 확인이 맞지 않습니다.")
                payload, cookie = self.auth_manager.setup(self, setup_code, password)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/auth/logout":
                self.auth_manager.require_csrf(self)
                payload, cookie = self.auth_manager.logout(self)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/commands":
                self.auth_manager.require_csrf(self)
                self._send_json(HTTPStatus.OK, self._handle_command_submit())
                return
            if parsed.path == "/api/ptt":
                self.auth_manager.require_csrf(self)
                self._send_json(HTTPStatus.OK, self._handle_ptt_toggle())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.code, "detail": exc.detail, **exc.extra})
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "internal_error", "detail": str(exc)},
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/login":
                body = self._read_json_body()
                access_code = str(body.get("code") or body.get("setupCode") or body.get("password") or "")
                if not access_code:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "code_required", "접속 코드를 입력해 주세요.")
                payload, cookie = self.auth_manager.login(self, access_code)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/auth/setup":
                body = self._read_json_body()
                access_code = str(body.get("setupCode") or body.get("code") or body.get("password") or "")
                if not access_code:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "setup_code_required", "접속 코드를 입력해 주세요.")
                payload, cookie = self.auth_manager.setup(self, access_code, "")
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/auth/logout":
                self.auth_manager.require_csrf(self)
                payload, cookie = self.auth_manager.logout(self)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/commands":
                self.auth_manager.require_csrf(self)
                self._send_json(HTTPStatus.OK, self._handle_command_submit())
                return
            if parsed.path == "/api/ptt":
                self.auth_manager.require_csrf(self)
                self._send_json(HTTPStatus.OK, self._handle_ptt_toggle())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.code, "detail": exc.detail, **exc.extra})
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "internal_error", "detail": str(exc)},
            )

    def _handle_command_submit(self) -> dict[str, Any]:
        body = self._read_json_body()
        text = str(body.get("text") or "").strip()
        if not text:
            raise ApiError(HTTPStatus.BAD_REQUEST, "text_required", "명령을 입력해 주세요.")
        user_message = build_message("user", "command", text)
        append_jsonl(self.command_paths.messages_path, user_message)
        dispatch_result = dispatch_background_command(text, self.runtime_paths)
        handoff = dict(dispatch_result.get("handoff") or {})
        handoff_id = str(handoff.get("handoffId") or "")
        status_message = build_message(
            "assistant",
            "status",
            "명령을 접수했고, 백그라운드 서브에이전트에 전달했습니다.",
            handoff_id=handoff_id,
            meta={"route": safe_get(handoff, "route", "routeLabel", default="")},
        )
        append_jsonl(self.command_paths.messages_path, status_message)
        return {
            "ok": True,
            "handoffId": handoff_id,
            "userMessage": user_message,
            "statusMessage": status_message,
            "generatedAt": utc_now_iso(),
        }

    def _handle_ptt_toggle(self) -> dict[str, Any]:
        body = self._read_json_body()
        ptt_state = {
            "recording": bool(body.get("recording")),
            "updatedAt": utc_now_iso(),
            "source": "command-center-ui",
        }
        write_json(self.command_paths.ptt_path, ptt_state)
        return {"ok": True, "ptt": ptt_state}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "font-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def guess_type(self, path: str) -> str:
        mime, _ = mimetypes.guess_type(path)
        return mime or "application/octet-stream"


def ensure_async_worker(runtime_paths: RuntimePaths) -> None:
    if not runtime_paths.helper_async_start_script.exists():
        return
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runtime_paths.helper_async_start_script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def dispatch_background_command(task_text: str, runtime_paths: RuntimePaths) -> dict[str, Any]:
    ensure_async_worker(runtime_paths)
    completed = subprocess.run(
        [
            sys.executable,
            str(runtime_paths.dispatch_script),
            "--task-text",
            task_text,
            "--source-title",
            "command-center",
            "--source-session-id",
            "command-center-ui",
            "--notes",
            "submitted from codex-control-center",
            "--notify-on-complete",
            "--async-return",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raise ApiError(
            HTTPStatus.BAD_GATEWAY,
            "dispatch_failed",
            completed.stderr.strip() or stdout or "dispatch_failed",
        )
    if not stdout:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "empty_dispatch", "handoff 결과가 비어 있습니다.")
    return json.loads(stdout)


def build_server(
    host: str,
    port: int,
    static_root: Path,
    snapshot_builder: SnapshotBuilder,
    runtime_paths: RuntimePaths,
    command_paths: CommandCenterPaths,
    auth_manager: AuthManager,
) -> ThreadingHTTPServer:
    handler_cls = type(
        "BoundControlCenterHandler",
        (ControlCenterHandler,),
        {
            "static_root": static_root,
            "snapshot_builder": snapshot_builder,
            "runtime_paths": runtime_paths,
            "command_paths": command_paths,
            "auth_manager": auth_manager,
        },
    )
    return ThreadingHTTPServer((host, port), handler_cls)


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Control Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runtime-root", default=None)
    args = parser.parse_args()

    runtime_paths = RuntimePaths.detect(args.runtime_root)
    command_paths = CommandCenterPaths.detect(runtime_paths.repo_root)
    snapshot_builder = SnapshotBuilder(runtime_paths, command_paths)
    auth_manager = AuthManager(command_paths)
    static_root = Path(__file__).resolve().parents[1] / "static"
    server = build_server(
        args.host,
        args.port,
        static_root,
        snapshot_builder,
        runtime_paths,
        command_paths,
        auth_manager,
    )
    bootstrap = read_json(command_paths.bootstrap_path, {})
    print(
        json.dumps(
            {
                "ok": True,
                "url": f"http://{args.host}:{args.port}",
                "runtimeRoot": str(runtime_paths.runtime_root),
                "setupRequired": auth_manager.setup_required(),
                "bootstrapCode": bootstrap.get("setupCode", ""),
                "generatedAt": utc_now_iso(),
            },
            ensure_ascii=False,
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
