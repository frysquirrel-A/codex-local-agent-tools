from __future__ import annotations

import argparse
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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


def trim_text(value: str | None, limit: int = 300) -> str:
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
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def safe_get(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


@dataclass
class RuntimePaths:
    repo_root: Path
    runtime_root: Path
    state_root: Path
    config_root: Path
    helper_handoff_inbox: Path

    @classmethod
    def detect(cls, explicit_runtime_root: str | None) -> "RuntimePaths":
        current = Path(__file__).resolve()
        repo_root = current.parents[2]
        if explicit_runtime_root:
            runtime_root = Path(explicit_runtime_root).resolve()
        else:
            candidates = [
                repo_root / "00_Codex_도구" / "03_로컬_에이전트_런타임",
                repo_root / "03_로컬_에이전트_런타임",
            ]
            runtime_root = next((path for path in candidates if path.exists()), candidates[0])
        return cls(
            repo_root=repo_root,
            runtime_root=runtime_root,
            state_root=runtime_root / "state",
            config_root=runtime_root / "config",
            helper_handoff_inbox=runtime_root / "state" / "helper_handoffs" / "inbox",
        )


class SnapshotBuilder:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def build(self) -> dict[str, Any]:
        roster = read_json(self.paths.config_root / "codex_helper_thread_roster.json", {})
        registry = read_json(self.paths.config_root / "llm_thread_registry.json", {})
        helper_status = read_json(self.paths.state_root / "helper_handoffs" / "status.json", {})
        scheduler_status = read_json(self.paths.state_root / "central_scheduler" / "status.json", {})
        watchdog_status = read_json(
            self.paths.state_root / "turn_continuation_watchdog" / "status.json", {}
        )
        gmail_status = read_json(self.paths.state_root / "gmail_command_channel_status.json", {})

        helper_by_title = {
            thread.get("title"): thread for thread in roster.get("threads", []) if thread.get("title")
        }
        helper_by_responsibility = {
            thread.get("responsibility"): thread
            for thread in roster.get("threads", [])
            if thread.get("responsibility")
        }

        return {
            "generatedAt": utc_now_iso(),
            "paths": {
                "repoRoot": str(self.paths.repo_root),
                "runtimeRoot": str(self.paths.runtime_root),
                "helperInbox": str(self.paths.helper_handoff_inbox),
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
            },
            "threads": self._build_threads(roster, registry, helper_status),
            "messageFlows": self._build_flows(helper_by_title, helper_by_responsibility),
            "alerts": self._build_alerts(helper_status, scheduler_status, watchdog_status, gmail_status),
        }

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
                        "role": f"{provider_name} 라우트 스레드",
                        "stats": {
                            "url": route.get("url", ""),
                            "keywords": route.get("keywords", []),
                        },
                    }
                )
        return threads

    def _build_flows(
        self,
        helper_by_title: dict[str, dict[str, Any]],
        helper_by_responsibility: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        flows: list[dict[str, Any]] = []
        files = sorted(
            self.paths.helper_handoff_inbox.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:20]

        for path in files:
            handoff = read_json(path, {})
            if not handoff:
                continue
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
                        "requestPreview": trim_text(assignment.get("handoffPrompt", ""), 220),
                        "responsePreview": trim_text(assignment.get("responseText", ""), 420),
                    }
                )

            flows.append(
                {
                    "handoffId": handoff.get("handoffId", path.stem),
                    "createdAt": handoff.get("createdAt", ""),
                    "route": safe_get(handoff, "route", "route", default=""),
                    "routeLabel": safe_get(handoff, "route", "routeLabel", default=""),
                    "sourceTitle": safe_get(handoff, "source", "title", default=""),
                    "sourceNotes": safe_get(handoff, "source", "notes", default=""),
                    "taskPreview": trim_text(handoff.get("taskText", ""), 300),
                    "path": str(path),
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

    def _build_alerts(
        self,
        helper_status: dict[str, Any],
        scheduler_status: dict[str, Any],
        watchdog_status: dict[str, Any],
        gmail_status: dict[str, Any],
    ) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []

        stale = helper_status.get("staleAssignmentCount", 0)
        if stale:
            alerts.append(
                {
                    "level": "warn",
                    "title": "stale helper assignment 존재",
                    "detail": f"{stale}건의 stale helper assignment가 남아 있습니다.",
                }
            )

        open_jobs = scheduler_status.get("openJobCount", 0)
        if open_jobs:
            alerts.append(
                {
                    "level": "info",
                    "title": "중앙 스케줄러 open job 존재",
                    "detail": f"현재 open job은 {open_jobs}건입니다.",
                }
            )

        if watchdog_status.get("heartbeatStale"):
            alerts.append(
                {
                    "level": "critical",
                    "title": "watchdog heartbeat stale",
                    "detail": "watchdog heartbeat가 stale 상태입니다.",
                }
            )

        reasons = safe_get(watchdog_status, "resourceGuardStatus", "reasons", default=[])
        if reasons:
            alerts.append(
                {
                    "level": "info",
                    "title": "자원 가드 보류 사유",
                    "detail": ", ".join(reasons),
                }
            )

        if gmail_status.get("skipReason"):
            alerts.append(
                {
                    "level": "warn",
                    "title": "Gmail 채널 cycle skip",
                    "detail": gmail_status.get("skipReason", ""),
                }
            )

        return alerts


class ControlCenterHandler(SimpleHTTPRequestHandler):
    static_root: Path
    snapshot_builder: SnapshotBuilder

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed == "/":
            parsed = "/index.html"
        return str(self.static_root / parsed.lstrip("/"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            payload = json.dumps({"ok": True, "generatedAt": utc_now_iso()}, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/api/snapshot":
            payload = json.dumps(self.snapshot_builder.build(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        return super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path: str) -> str:
        mime, _ = mimetypes.guess_type(path)
        return mime or "application/octet-stream"


def build_server(host: str, port: int, static_root: Path, snapshot_builder: SnapshotBuilder) -> ThreadingHTTPServer:
    handler_cls = type(
        "BoundControlCenterHandler",
        (ControlCenterHandler,),
        {"static_root": static_root, "snapshot_builder": snapshot_builder},
    )
    return ThreadingHTTPServer((host, port), handler_cls)


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Control Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runtime-root", default=None)
    args = parser.parse_args()

    paths = RuntimePaths.detect(args.runtime_root)
    static_root = Path(__file__).resolve().parents[1] / "static"
    server = build_server(args.host, args.port, static_root, SnapshotBuilder(paths))
    print(
        json.dumps(
            {
                "ok": True,
                "url": f"http://{args.host}:{args.port}",
                "runtimeRoot": str(paths.runtime_root),
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
