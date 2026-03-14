from __future__ import annotations

import argparse
import csv
import ctypes
import io
import json
import hashlib
import mimetypes
import re
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
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


RECENT_HANDOFF_LIMIT = 16
RECENT_MESSAGE_LIMIT = 120
LEGACY_GMAIL_JOB_MAX_AGE_SECONDS = 60 * 60 * 6
LEGACY_CORRUPTED_MESSAGE_MAX_AGE_SECONDS = 60 * 30
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
    "superseded",
}

AUTH_DELIVERY_EMAIL = "emnogib@icloud.com"

_LAST_CPU_SAMPLE: tuple[int, int] | None = None
_LAST_RESOURCE_SAMPLE: tuple[float, dict[str, Any]] | None = None
_LAST_CPU_CLOCK_SAMPLE: tuple[float, float] | None = None
_LAST_GPU_SAMPLE: tuple[float, dict[str, Any]] | None = None

ROLE_DISPLAY = {
    "main": "관리자",
    "helper": "실무",
    "provider": "외부",
    "provider-route": "외부",
}

RESPONSIBILITY_NAME = {
    "team1-lead": "[1팀] 팀장",
    "team1-staff-1": "[1팀] 직원1",
    "team1-staff-2": "[1팀] 직원2",
    "team1-staff-3": "[1팀] 직원3",
    "team2-lead": "[2팀] 팀장",
    "team2-staff-1": "[2팀] 직원1",
    "team2-staff-2": "[2팀] 직원2",
    "team2-staff-3": "[2팀] 직원3",
    "coop-mail": "[협력01] 메일",
    "coop-kvm": "[협력02] KVM",
    "coop-runtime": "[협력03] 런타임",
    "coop-queue": "[협력04] 큐",
    "coop-resume": "[협력05] 이어가기",
    "coop-attachment": "[협력06] 첨부복구",
    "coop-audit": "[협력07] 상태감사",
    "principal-review": "[협력08] 리뷰",
    "principal-design": "[협력09] 설계",
    "principal-reliability": "[협력10] 성능",
    "principal-triage": "[협력11] 실패분석",
    "llm-routing": "[협력12] LLM 라우팅",
    "desktop-automation": "[협력13] 데스크톱",
    "relay-board-validation": "[협력14] 릴레이 검증",
    "runbook-procedure": "[협력15] 런북",
}

RESPONSIBILITY_ROLE = {
    "team1-lead": "1팀 총괄. 실행 계열 작업을 먼저 배분하고 진행 상태를 요약합니다.",
    "team1-staff-1": "1팀 진단 담당. 로그와 재현 단서를 정리합니다.",
    "team1-staff-2": "1팀 실행 준비 담당. 안전한 다음 단계를 정리합니다.",
    "team1-staff-3": "1팀 검증 담당. 증거와 체크리스트를 정리합니다.",
    "team2-lead": "2팀 총괄. 구조, 라우팅, 정리, 마감 흐름을 총괄합니다.",
    "team2-staff-1": "2팀 설계 담당. 구조와 라우팅 판단을 정리합니다.",
    "team2-staff-2": "2팀 큐 담당. stale, backlog, 우선순위를 정리합니다.",
    "team2-staff-3": "2팀 보고 담당. 요약과 보고서 결과를 정리합니다.",
    "coop-mail": "공통 메일 지원. Gmail 수신, 회신, 전달 상태를 봅니다.",
    "coop-kvm": "공통 KVM 지원. foreground/background 입력 정책을 봅니다.",
    "coop-runtime": "공통 런타임 지원. relay, watchdog, bridge 상태를 봅니다.",
    "coop-queue": "공통 큐 지원. dedupe, stale, assignment 정리를 봅니다.",
    "coop-resume": "공통 이어가기 지원. resume과 stale 감지를 봅니다.",
    "coop-attachment": "공통 첨부 복구 지원. PDF와 첨부 전송 경로를 봅니다.",
    "coop-audit": "공통 상태감사 지원. 현재 상태와 누락을 점검합니다.",
    "principal-review": "공통 리뷰 지원. 리스크와 품질 이슈를 비판적으로 검토합니다.",
    "principal-design": "공통 설계 지원. 구조를 단순하고 오래 가게 만듭니다.",
    "principal-reliability": "공통 성능 지원. 자원, 복구, 안정성 위험을 줄입니다.",
    "principal-triage": "공통 실패분석 지원. 실패 원인과 우선순위를 정리합니다.",
    "llm-routing": "공통 LLM 라우팅 지원. 어떤 스레드에 일을 보낼지 정리합니다.",
    "desktop-automation": "공통 데스크톱 지원. 창, 입력, 자동화 흐름을 정리합니다.",
    "relay-board-validation": "공통 릴레이 검증 지원. 전달 경로와 보드 상태를 점검합니다.",
    "runbook-procedure": "공통 런북 지원. 운영 절차와 마감 흐름을 정리합니다.",
}

DISPLAY_ORDER = [
    "[비서] 보고자",
    "[관리자] 사장",
    "[1팀] 팀장",
    "[1팀] 직원1",
    "[1팀] 직원2",
    "[1팀] 직원3",
    "[2팀] 팀장",
    "[2팀] 직원1",
    "[2팀] 직원2",
    "[2팀] 직원3",
]


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, detail: str, extra: dict[str, Any] | None = None) -> None:
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
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw in read_text_with_fallback(path).splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def resource_guard_reason_label(reason: str) -> str:
    key = str(reason or "").strip().lower()
    mapping = {
        "user_active": "사용 중",
        "high_cpu": "CPU 사용률 높음",
        "low_memory": "메모리 부족",
        "codex_memory_high": "Codex 메모리 사용량 높음",
        "chrome_memory_high": "Chrome 메모리 사용량 높음",
        "gpu_busy": "GPU 사용률 높음",
        "gpu_memory_high": "GPU 메모리 사용량 높음",
    }
    return mapping.get(key, str(reason))


def trim_text(value: str | None, limit: int = 240) -> str:
    if not value:
        return ""
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


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


def make_access_code() -> str:
    return "CC-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))


def normalize_access_code(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def summary_lines(text: str, limit: int = 3) -> list[str]:
    lines = [trim_text(item.strip(), 120) for item in str(text or "").replace("\r", "\n").splitlines() if item.strip()]
    unique: list[str] = []
    for line in lines:
        if line and line not in unique:
            unique.append(line)
        if len(unique) >= limit:
            break
    if unique:
        return unique
    fallback = trim_text(text, 120)
    return [fallback] if fallback else []


TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("운영 조직도 · 역할 구조", ("조직도", "팀장", "직원", "협력", "사장", "비서", "대표")),
    ("Command Center UI · 사용성", ("ui", "ux", "디자인", "가시성", "레이아웃", "카드", "탭", "대화창", "입력창", "필터")),
    ("자원 모니터링 · 성능", ("cpu", "메모리", "gpu", "성능", "자원", "클록", "한도")),
    ("외부 LLM 협업", ("llm", "chatgpt", "gemini", "외부", "상담", "검토", "첨부")),
    ("메일 · Gmail 자동화", ("메일", "gmail", "첨부", "회신", "수신", "발송")),
    ("인증 · 접속 · 보안", ("로그인", "접속", "코드", "보안", "세션", "권한", "터널")),
    ("보고 · 결과 정리", ("보고", "결과", "요약", "설명서", "pdf", "보고서")),
    ("브라우저 · 입력 제어", ("브라우저", "kvm", "foreground", "background", "클릭", "새로고침", "드래그")),
]


def _collapse_topic_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", "\n").split())


def explicit_topic_title(text: str) -> str:
    compact = str(text or "")
    match = re.search(r"\[(?:대주제|주제)\s*:\s*([^\]]+)\]", compact)
    return trim_text(match.group(1).strip(), 40) if match else ""


def infer_topic_title(text: str) -> str:
    explicit = explicit_topic_title(text)
    if explicit:
        return explicit
    compact = _collapse_topic_text(text)
    lowered = compact.lower()
    for title, keywords in TOPIC_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return title
    first_line = ""
    for line in str(text or "").splitlines():
        cleaned = trim_text(line.strip(), 40)
        if cleaned:
            first_line = cleaned
            break
    if first_line:
        first_line = re.sub(r"^\[[^\]]+\]\s*", "", first_line).strip()
        return trim_text(first_line, 40)
    return "일반 운영"


def topic_id_for_title(title: str) -> str:
    base = title.strip() or "일반 운영"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"topic-{digest}"


def text_looks_corrupted(value: str | None) -> bool:
    text = str(value or "")
    if not text:
        return False
    question_count = text.count("?")
    replacement_count = text.count("\ufffd")
    return (
        "占" in text
        or replacement_count > 0
        or question_count >= max(4, int(len(text) * 0.18))
    )


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _filetime_to_int(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _probe_cpu_percent() -> float:
    global _LAST_CPU_SAMPLE
    kernel = FILETIME()
    user = FILETIME()
    idle = FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return 0.0
    idle_now = _filetime_to_int(idle)
    total_now = _filetime_to_int(kernel) + _filetime_to_int(user)
    previous = _LAST_CPU_SAMPLE
    _LAST_CPU_SAMPLE = (idle_now, total_now)
    if not previous:
        return 0.0
    idle_delta = max(0, idle_now - previous[0])
    total_delta = max(0, total_now - previous[1])
    if total_delta <= 0:
        return 0.0
    busy_ratio = max(0.0, min(1.0, (total_delta - idle_delta) / total_delta))
    return round(busy_ratio * 100.0, 1)


def _probe_cpu_clock_ghz() -> float:
    global _LAST_CPU_CLOCK_SAMPLE
    now = time.time()
    if _LAST_CPU_CLOCK_SAMPLE and now - _LAST_CPU_CLOCK_SAMPLE[0] < 30:
        return _LAST_CPU_CLOCK_SAMPLE[1]
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor | Measure-Object -Property CurrentClockSpeed -Average).Average",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            check=False,
        )
    except Exception:
        return _LAST_CPU_CLOCK_SAMPLE[1] if _LAST_CPU_CLOCK_SAMPLE else 0.0

    if completed.returncode != 0:
        return _LAST_CPU_CLOCK_SAMPLE[1] if _LAST_CPU_CLOCK_SAMPLE else 0.0

    raw = (completed.stdout or "").strip()
    try:
        mhz = float(raw)
    except ValueError:
        return _LAST_CPU_CLOCK_SAMPLE[1] if _LAST_CPU_CLOCK_SAMPLE else 0.0
    ghz = round(mhz / 1000.0, 2)
    _LAST_CPU_CLOCK_SAMPLE = (now, ghz)
    return ghz


def _probe_memory() -> dict[str, float]:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {
            "memoryLoadPercent": 0.0,
            "totalPhysicalMb": 0.0,
            "availablePhysicalMb": 0.0,
            "usedPhysicalMb": 0.0,
        }
    total_mb = round(status.ullTotalPhys / (1024 * 1024), 1)
    avail_mb = round(status.ullAvailPhys / (1024 * 1024), 1)
    used_mb = round(max(0, total_mb - avail_mb), 1)
    return {
        "memoryLoadPercent": float(status.dwMemoryLoad),
        "totalPhysicalMb": total_mb,
        "availablePhysicalMb": avail_mb,
        "usedPhysicalMb": used_mb,
    }


def _probe_named_working_set_mb(name_fragment: str) -> float:
    target = name_fragment.lower()
    total_bytes = 0
    if psutil is not None:
        for process in psutil.process_iter(["name", "memory_info", "cmdline"]):
            try:
                name = str(process.info.get("name") or "").lower()
                cmdline = " ".join(process.info.get("cmdline") or []).lower()
                if target not in name and target not in cmdline:
                    continue
                memory_info = process.info.get("memory_info")
                rss = int(getattr(memory_info, "rss", 0) or 0)
                if rss <= 0:
                    rss = int(getattr(memory_info, "wset", 0) or 0)
                total_bytes += max(0, rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                continue
        return round(total_bytes / (1024 * 1024), 1)

    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="cp949",
            errors="replace",
            timeout=6,
            check=False,
        )
    except Exception:
        return 0.0
    if completed.returncode != 0:
        return 0.0

    total_kb = 0
    reader = csv.reader(io.StringIO(completed.stdout))
    for row in reader:
        if len(row) < 5:
            continue
        image_name = str(row[0] or "").lower()
        if target not in image_name:
            continue
        memory_cell = str(row[4] or "")
        digits = "".join(ch for ch in memory_cell if ch.isdigit())
        if not digits:
            continue
        total_kb += int(digits)
    return round(total_kb / 1024, 1)


def probe_resource_usage() -> dict[str, Any]:
    global _LAST_RESOURCE_SAMPLE
    now = time.time()
    if _LAST_RESOURCE_SAMPLE and now - _LAST_RESOURCE_SAMPLE[0] < 5:
        return dict(_LAST_RESOURCE_SAMPLE[1])
    memory = _probe_memory()
    cpu_percent = _probe_cpu_percent()
    cpu_clock_ghz = _probe_cpu_clock_ghz()
    codex_mb = _probe_named_working_set_mb("codex")
    chrome_mb = _probe_named_working_set_mb("chrome")
    result = {
        "cpuPercent": cpu_percent,
        "cpuClockGhz": cpu_clock_ghz,
        "memoryLoadPercent": memory["memoryLoadPercent"],
        "totalPhysicalMb": memory["totalPhysicalMb"],
        "availablePhysicalMb": memory["availablePhysicalMb"],
        "usedPhysicalMb": memory["usedPhysicalMb"],
        "codexWorkingSetMb": codex_mb,
        "chromeWorkingSetMb": chrome_mb,
        "updatedAt": utc_now_iso(),
    }
    _LAST_RESOURCE_SAMPLE = (now, result)
    return result


def probe_gpu_usage() -> dict[str, Any]:
    global _LAST_GPU_SAMPLE
    now = time.time()
    if _LAST_GPU_SAMPLE and now - _LAST_GPU_SAMPLE[0] < 15:
        return dict(_LAST_GPU_SAMPLE[1])
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception:
        result = {
            "available": False,
            "gpuPercent": 0.0,
            "memoryUsedMb": 0.0,
            "memoryTotalMb": 0.0,
            "name": "",
            "updatedAt": utc_now_iso(),
        }
        _LAST_GPU_SAMPLE = (now, result)
        return result
    if completed.returncode != 0:
        result = {
            "available": False,
            "gpuPercent": 0.0,
            "memoryUsedMb": 0.0,
            "memoryTotalMb": 0.0,
            "name": "",
            "updatedAt": utc_now_iso(),
        }
        _LAST_GPU_SAMPLE = (now, result)
        return result

    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    if not first_line:
        result = {
            "available": False,
            "gpuPercent": 0.0,
            "memoryUsedMb": 0.0,
            "memoryTotalMb": 0.0,
            "name": "",
            "updatedAt": utc_now_iso(),
        }
        _LAST_GPU_SAMPLE = (now, result)
        return result

    parts = [item.strip() for item in first_line.split(",")]
    try:
        gpu_percent = float(parts[0])
        memory_used = float(parts[1])
        memory_total = float(parts[2])
        name = parts[3] if len(parts) > 3 else "GPU"
    except (ValueError, IndexError):
        gpu_percent = 0.0
        memory_used = 0.0
        memory_total = 0.0
        name = ""
    result = {
        "available": bool(name or gpu_percent or memory_total),
        "gpuPercent": gpu_percent,
        "memoryUsedMb": memory_used,
        "memoryTotalMb": memory_total,
        "name": name,
        "updatedAt": utc_now_iso(),
    }
    _LAST_GPU_SAMPLE = (now, result)
    return result


def probe_codex_quota_status(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    remaining_percent = payload.get("remainingPercent")
    try:
        remaining_percent = float(remaining_percent)
    except (TypeError, ValueError):
        remaining_percent = None
    return {
        "available": remaining_percent is not None,
        "remainingPercent": remaining_percent,
        "label": str(payload.get("label") or ("미연동" if remaining_percent is None else "남은 한도")),
        "detail": str(payload.get("detail") or ("공식 한도 값을 아직 읽지 못했습니다." if remaining_percent is None else "")),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def current_ui_version() -> str:
    static_root = Path(__file__).resolve().parents[1] / "static"
    candidates = [
        static_root / "index.html",
        static_root / "styles.css",
        static_root / "app.js",
    ]
    latest = 0.0
    for path in candidates:
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return str(int(latest))


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def detect_runtime_root(repo_root: Path, explicit_runtime_root: str | None) -> Path:
    if explicit_runtime_root:
        candidate = Path(explicit_runtime_root).resolve()
        if candidate.exists():
            return candidate
    for candidate in (repo_root / "codex-runtime", repo_root / "00_Codex_도구"):
        if candidate.exists():
            if (candidate / "config").exists():
                return candidate
            matches = [item for item in candidate.glob("03_*") if (item / "config").exists()]
            if matches:
                return matches[0]
    raise FileNotFoundError("Runtime root could not be detected.")


def responsibility_title(responsibility: str, fallback: str = "") -> str:
    return RESPONSIBILITY_NAME.get(responsibility, fallback or responsibility or "미분류 스레드")


def responsibility_role(responsibility: str, fallback: str = "") -> str:
    return RESPONSIBILITY_ROLE.get(responsibility, fallback or "설명 없음")


def display_sort_key(title: str) -> tuple[int, str]:
    if title in DISPLAY_ORDER:
        return (DISPLAY_ORDER.index(title), title)
    if title.startswith("[협력"):
        digits = "".join(ch for ch in title if ch.isdigit())
        return (100 + int(digits or 0), title)
    if title.startswith("chatgpt") or title.startswith("gemini"):
        return (200, title)
    return (999, title)


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
        repo_root = Path(__file__).resolve().parents[2]
        runtime_root = detect_runtime_root(repo_root, explicit_runtime_root)
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
    bootstrap_path: Path
    public_tunnel_status_path: Path
    codex_quota_status_path: Path
    client_errors_path: Path

    @classmethod
    def detect(cls) -> "CommandCenterPaths":
        root = ensure_directory(Path(__file__).resolve().parents[1] / "state")
        return cls(
            root=root,
            messages_path=root / "messages.jsonl",
            ptt_path=root / "ptt.json",
            bootstrap_path=root / "bootstrap_setup.json",
            public_tunnel_status_path=root / "public_tunnel_status.json",
            codex_quota_status_path=root / "codex_quota_status.json",
            client_errors_path=root / "client_errors.jsonl",
        )


class AuthManager:
    def __init__(self, command_paths: CommandCenterPaths) -> None:
        self.command_paths = command_paths
        self.sessions: dict[str, dict[str, Any]] = {}
        self.login_attempts: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.ensure_access_code()

    def ensure_access_code(self) -> None:
        payload = read_json(self.command_paths.bootstrap_path, {})
        changed = False
        if not payload.get("setupCode"):
            payload["setupCode"] = make_access_code()
            payload["createdAt"] = utc_now_iso()
            changed = True
        if not payload.get("note"):
            payload["note"] = "Use this access code to sign in to Codex Command Center."
            changed = True
        delivery = dict(payload.get("delivery") or {})
        if delivery.get("primary") != "email":
            delivery["primary"] = "email"
            changed = True
        if delivery.get("recipient") != AUTH_DELIVERY_EMAIL:
            delivery["recipient"] = AUTH_DELIVERY_EMAIL
            changed = True
        if delivery.get("fallback") != str(self.command_paths.bootstrap_path):
            delivery["fallback"] = str(self.command_paths.bootstrap_path)
            changed = True
        payload["delivery"] = delivery
        if changed:
            write_json(self.command_paths.bootstrap_path, payload)

    def current_access_code(self) -> tuple[str, dict[str, Any]]:
        self.ensure_access_code()
        payload = read_json(self.command_paths.bootstrap_path, {})
        return str(payload.get("setupCode") or ""), payload

    def is_trusted_request(self, handler: "ControlCenterHandler") -> bool:
        forwarded = handler.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return False
        host = str(handler.client_address[0] if handler.client_address else "127.0.0.1")
        try:
            ip = ip_address(host)
            return bool(ip.is_loopback)
        except ValueError:
            return host.lower() in {"localhost", "::1"}

    def auth_state(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.read_session(handler)
        _, bootstrap = self.current_access_code()
        delivery = dict(bootstrap.get("delivery") or {})
        if self.is_trusted_request(handler):
            return {
                "ok": True,
                "authenticated": True,
                "mode": "trusted-local",
                "message": "현재 PC의 localhost 접속은 바로 열립니다. 다른 기기나 외부 접속만 접속 코드 로그인이 필요합니다.",
                "message": "현재 PC의 localhost 접속은 바로 열립니다. 다른 기기나 외부 접속만 접속 코드 로그인이 필요합니다.",
                "csrfToken": "",
                "sessionExpiresAt": "",
                "requiresLogin": False,
                "codeIssuedAt": str(bootstrap.get("createdAt") or ""),
                "deliveryPrimary": str(delivery.get("primary") or ""),
                "deliveryTarget": str(delivery.get("recipient") or ""),
                "deliveryFallback": str(delivery.get("fallback") or ""),
            }
        return {
            "ok": True,
            "authenticated": bool(session),
            "mode": "code-login",
            "message": "모든 접속은 접속 코드 로그인 후 사용합니다. 코드는 대표님 등록 메일로 전달하고, 백업은 로컬 상태 파일에 보관합니다.",
            "message": "다른 기기나 외부에서 접속할 때는 접속 코드 로그인이 필요합니다. 대표님 메일의 코드나 백업 파일을 사용해 들어오시면 됩니다.",
            "csrfToken": session.get("csrfToken", "") if session else "",
            "sessionExpiresAt": session.get("expiresAt", "") if session else "",
            "requiresLogin": True,
            "codeIssuedAt": str(bootstrap.get("createdAt") or ""),
            "deliveryPrimary": str(delivery.get("primary") or ""),
            "deliveryTarget": str(delivery.get("recipient") or ""),
            "deliveryFallback": str(delivery.get("fallback") or ""),
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

    def require_read(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        if self.is_trusted_request(handler):
            return {
                "trustedLocal": True,
                "mode": "trusted-local",
                "client": self.client_identity(handler),
            }
        session = self.read_session(handler)
        if not session:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "auth_required", "접속 코드 로그인이 필요합니다.")
        return session

    def require_write(self, handler: "ControlCenterHandler") -> dict[str, Any]:
        session = self.require_read(handler)
        if bool(session.get("trustedLocal")):
            return session
        csrf_token = handler.headers.get("X-CSRF-Token", "").strip()
        if not csrf_token or csrf_token != str(session.get("csrfToken", "")):
            raise ApiError(HTTPStatus.FORBIDDEN, "invalid_csrf", "요청 확인 토큰이 맞지 않습니다.")
        return session

    def login(self, handler: "ControlCenterHandler", access_code: str) -> tuple[dict[str, Any], str]:
        self._check_login_allowed(self.client_identity(handler))
        expected_code, bootstrap = self.current_access_code()
        if normalize_access_code(expected_code) != normalize_access_code(access_code):
            self._register_failed_attempt(self.client_identity(handler))
            raise ApiError(HTTPStatus.UNAUTHORIZED, "invalid_code", "접속 코드가 맞지 않습니다.")
        self._clear_failed_attempts(self.client_identity(handler))
        session, cookie = self._create_session(handler)
        return (
            {
                "ok": True,
                "auth": {
                    "authenticated": True,
                    "mode": "code-login",
                    "requiresLogin": True,
                    "csrfToken": session["csrfToken"],
                    "sessionExpiresAt": session["expiresAt"],
                    "codeIssuedAt": str(bootstrap.get("createdAt") or ""),
                    "deliveryPrimary": str(safe_get(bootstrap, "delivery", "primary", default="")),
                    "deliveryTarget": str(safe_get(bootstrap, "delivery", "recipient", default="")),
                    "deliveryFallback": str(safe_get(bootstrap, "delivery", "fallback", default="")),
                },
            },
            cookie,
        )

    def logout(self, handler: "ControlCenterHandler") -> tuple[dict[str, Any], str]:
        cookies = SimpleCookie()
        cookies.load(handler.headers.get("Cookie", ""))
        morsel = cookies.get(SESSION_COOKIE_NAME)
        if morsel is not None:
            with self.lock:
                self.sessions.pop(morsel.value, None)
        return (
            {"ok": True, "auth": self.auth_state(handler)},
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
        return False

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
                remaining = max(1, int(lock_until - time.time()))
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "login_locked",
                    f"접속 코드 시도가 많아 잠시 잠겼습니다. {remaining}초 뒤 다시 시도해 주세요.",
                )

    def _register_failed_attempt(self, client_id: str) -> None:
        now = time.time()
        with self.lock:
            record = self.login_attempts.setdefault(client_id, {"attempts": [], "lockUntilEpoch": 0})
            attempts = [item for item in record.get("attempts", []) if now - float(item) <= LOGIN_WINDOW_SECONDS]
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
        scheduler_status = self._sanitize_scheduler_status(
            read_json(self.runtime_paths.state_root / "central_scheduler" / "status.json", {})
        )
        watchdog_status = read_json(self.runtime_paths.state_root / "turn_continuation_watchdog" / "status.json", {})
        gmail_status = read_json(self.runtime_paths.state_root / "gmail_command_channel_status.json", {})
        async_status = read_json(self.runtime_paths.helper_async_status_path, {})
        ptt_state = read_json(self.command_paths.ptt_path, {"recording": False, "updatedAt": "", "source": "idle"})
        resource_usage = probe_resource_usage()
        resource_usage["gpu"] = probe_gpu_usage()
        resource_usage["codexQuota"] = probe_codex_quota_status(self.command_paths.codex_quota_status_path)

        handoffs = self._load_recent_handoffs()
        threads = self._build_threads(roster, registry, helper_status)
        flows = self._build_flows(handoffs)
        conversation = self._build_conversation(handoffs)

        return {
            "generatedAt": utc_now_iso(),
            "uiVersion": current_ui_version(),
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
                    "reasons": safe_get(watchdog_status, "resourceGuardStatus", "reasons", default=[]),
                },
                "helpers": {
                    "handoffCount": helper_status.get("handoffCount", 0),
                    "pendingAssignmentCount": helper_status.get("pendingAssignmentCount", 0),
                    "staleAssignmentCount": helper_status.get("staleAssignmentCount", 0),
                },
                "scheduler": {
                    "jobCount": scheduler_status.get("jobCount", 0),
                    "openJobCount": scheduler_status.get("openJobCount", 0),
                    "hiddenLegacyJobCount": scheduler_status.get("hiddenLegacyJobCount", 0),
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
                "resources": resource_usage,
            },
            "ptt": ptt_state,
            "threads": threads,
            "messageFlows": flows,
            "conversation": conversation,
            "alerts": self._build_alerts(helper_status, scheduler_status, watchdog_status, gmail_status, async_status),
        }

    def _load_recent_handoffs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.runtime_paths.helper_handoff_inbox.exists():
            return rows
        files = sorted(
            self.runtime_paths.helper_handoff_inbox.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:RECENT_HANDOFF_LIMIT]
        for path in files:
            payload = read_json(path, {})
            if not payload:
                continue
            payload["_path"] = str(path)
            rows.append(payload)
        return rows

    def _sanitize_scheduler_status(self, scheduler_status: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(scheduler_status or {})
        jobs = list(sanitized.get("latestJobs") or [])
        now_ts = time.time()
        visible_jobs: list[dict[str, Any]] = []
        hidden_legacy_job_count = 0
        for job in jobs:
            if self._job_is_hidden_legacy_noise(job, now_ts):
                hidden_legacy_job_count += 1
                continue
            visible_jobs.append(job)

        raw_open_job_count = int(sanitized.get("openJobCount", 0) or 0)
        raw_job_count = int(sanitized.get("jobCount", raw_open_job_count) or raw_open_job_count)
        sanitized["latestJobs"] = visible_jobs
        sanitized["rawOpenJobCount"] = raw_open_job_count
        sanitized["hiddenLegacyJobCount"] = hidden_legacy_job_count
        sanitized["openJobCount"] = max(0, raw_open_job_count - hidden_legacy_job_count)
        sanitized["jobCount"] = max(len(visible_jobs), raw_job_count - hidden_legacy_job_count)
        return sanitized

    def _job_is_hidden_legacy_noise(self, job: dict[str, Any], now_ts: float) -> bool:
        if str(job.get("kind") or "") != "gmail_mail_command":
            return False
        status = str(job.get("status") or "").strip().lower()
        if status not in {"waiting", "queued", "pending"}:
            return False

        updated_at = str(job.get("updatedAt") or "") or str(job.get("createdAt") or "")
        updated_ts = parse_timestamp(updated_at)
        if not updated_ts:
            return False
        age_seconds = max(0.0, now_ts - updated_ts)
        if age_seconds < LEGACY_GMAIL_JOB_MAX_AGE_SECONDS:
            return False

        stage = str(job.get("stage") or "").strip().lower()
        noisy_stage = stage in {
            "acceptance_replied",
            "reply_deferred",
            "relay_delayed",
            "queued_for_orchestrator",
        }
        text_candidates = [
            str(job.get("title") or ""),
            str(job.get("summary") or ""),
            str(safe_get(job, "metadata", "commandText", default="") or ""),
            str(safe_get(job, "lastNote", default="") or ""),
        ]
        return noisy_stage or any(text_looks_corrupted(item) for item in text_candidates)

    def _build_threads(
        self,
        roster: dict[str, Any],
        registry: dict[str, Any],
        helper_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        helper_summary = {
            item.get("responsibility"): item
            for item in helper_status.get("helperSummary", [])
            if item.get("responsibility")
        }
        rows: list[dict[str, Any]] = [
            {
                "kind": "main",
                "displayName": "[관리자] 사장",
                "title": "[관리자] 사장",
                "role": "비서 브리프를 바탕으로 우선순위, 위임, 승인, 최종 확인을 맡는 오케스트레이터입니다.",
                "stats": {"queued": 0, "running": 0, "pending": 0},
            }
        ]

        seen_titles = {"[관리자] 사장"}
        for thread in roster.get("threads", []):
            responsibility = str(thread.get("responsibility") or "")
            title = responsibility_title(responsibility, str(thread.get("title") or ""))
            role = responsibility_role(responsibility, str(thread.get("role") or ""))
            summary = helper_summary.get(responsibility, {})
            rows.append(
                {
                    "kind": "helper",
                    "displayName": title,
                    "title": title,
                    "role": role,
                    "stats": {
                        "responsibility": responsibility,
                        "queued": int(summary.get("queued", 0) or 0),
                        "running": int(summary.get("running", 0) or 0),
                        "pending": int(summary.get("pending", 0) or 0),
                        "oldestPendingMinutes": int(summary.get("oldestPendingMinutes", 0) or 0),
                    },
                }
            )
            seen_titles.add(title)

        for responsibility, title in RESPONSIBILITY_NAME.items():
            if title in seen_titles:
                continue
            rows.append(
                {
                    "kind": "helper",
                    "displayName": title,
                    "title": title,
                    "role": responsibility_role(responsibility),
                    "stats": {
                        "responsibility": responsibility,
                        "queued": 0,
                        "running": 0,
                        "pending": 0,
                        "oldestPendingMinutes": 0,
                    },
                }
            )

        for provider_name, provider in registry.get("providers", {}).items():
            default_title = str(provider.get("defaultThreadTitle") or "").strip()
            if default_title:
                rows.append(
                    {
                        "kind": "provider",
                        "displayName": default_title,
                        "title": default_title,
                        "role": f"{provider_name} 웹 스레드",
                        "stats": {"url": provider.get("defaultThreadUrl", "")},
                    }
                )

        rows.sort(key=lambda item: display_sort_key(str(item.get("displayName") or "")))
        return rows

    def _build_flows(self, handoffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        topic_map = self._build_topic_map()
        rows: list[dict[str, Any]] = []
        for handoff in handoffs:
            handoff_id = str(handoff.get("handoffId") or "")
            topic_info = topic_map.get(handoff_id, {})
            topic_title = str(topic_info.get("topicTitle") or infer_topic_title(str(handoff.get("taskText") or "")))
            topic_id = str(topic_info.get("topicId") or topic_id_for_title(topic_title))
            assignments = []
            for assignment in handoff.get("assignments", []):
                responsibility = str(assignment.get("responsibility") or "")
                assignments.append(
                    {
                        "assignmentId": assignment.get("assignmentId", ""),
                        "helperTitle": responsibility_title(responsibility, str(assignment.get("helperTitle") or "")),
                        "helperRole": responsibility_role(responsibility, str(assignment.get("helperRole") or "")),
                        "helperThreadId": assignment.get("helperThreadId", ""),
                        "status": assignment.get("status", ""),
                        "step": assignment.get("step", ""),
                        "updatedAt": assignment.get("updatedAt", ""),
                        "requestPreview": trim_text(assignment.get("handoffPrompt", ""), 180),
                        "requestText": assignment.get("handoffPrompt", ""),
                        "responsePreview": trim_text(assignment.get("responseText", ""), 240),
                        "responseText": assignment.get("responseText", ""),
                    }
                )
            source_title = str(safe_get(handoff, "source", "title", default="") or "")
            rows.append(
                {
                    "handoffId": handoff_id,
                    "createdAt": handoff.get("createdAt", ""),
                    "route": safe_get(handoff, "route", "route", default=""),
                    "routeLabel": safe_get(handoff, "route", "routeLabel", default=""),
                    "sourceTitle": "[비서] 보고자" if source_title == "command-center" else source_title,
                    "sourceNotes": safe_get(handoff, "source", "notes", default=""),
                    "taskPreview": trim_text(handoff.get("taskText", ""), 180),
                    "taskText": handoff.get("taskText", ""),
                    "topicId": topic_id,
                    "topicTitle": topic_title,
                    "path": handoff.get("_path", ""),
                    "assignments": assignments,
                }
            )
        rows.sort(
            key=lambda item: max(
                parse_timestamp(item.get("createdAt")),
                *[parse_timestamp(entry.get("updatedAt")) for entry in item.get("assignments", [])],
            ),
            reverse=True,
        )
        return rows

    def _build_conversation(self, handoffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = read_jsonl(self.command_paths.messages_path)[-RECENT_MESSAGE_LIMIT:]
        handoff_map = {str(item.get("handoffId") or ""): item for item in handoffs}
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        now_ts = time.time()
        for message in messages:
            message_id = str(message.get("id") or "")
            if not message_id or message_id in seen:
                continue
            if self._message_is_hidden_legacy_noise(message, handoff_map, now_ts):
                continue
            seen.add(message_id)
            handoff_id = str(message.get("handoffId") or "")
            text = str(message.get("text") or "")
            topic_title = str(safe_get(message, "meta", "topicTitle", default="") or "")
            topic_id = str(safe_get(message, "meta", "topicId", default="") or (topic_id_for_title(topic_title) if topic_title else ""))
            rows.append(
                {
                    "id": message_id,
                    "role": str(message.get("role") or "system"),
                    "kind": str(message.get("kind") or "status"),
                    "text": text,
                    "createdAt": str(message.get("createdAt") or ""),
                    "handoffId": handoff_id,
                    "topicId": topic_id,
                    "topicTitle": topic_title,
                    "summaryLines": summary_lines(text),
                    "report": self._handoff_report_links(handoff_id),
                }
            )
            handoff = handoff_map.get(handoff_id)
            if not handoff or not self._handoff_is_closed(handoff):
                continue
            result_id = f"result:{handoff_id}"
            if result_id in seen:
                continue
            seen.add(result_id)
            result_text = self._summarize_handoff_result(handoff)
            rows.append(
                {
                    "id": result_id,
                    "role": "assistant",
                    "kind": "result",
                    "text": result_text,
                    "createdAt": self._handoff_latest_timestamp(handoff) or str(message.get("createdAt") or ""),
                    "handoffId": handoff_id,
                    "topicId": topic_id,
                    "topicTitle": topic_title,
                    "summaryLines": summary_lines(result_text),
                    "report": self._handoff_report_links(handoff_id),
                }
            )
        rows.sort(key=lambda item: (parse_timestamp(item.get("createdAt")), item.get("id", "")))
        return rows[-RECENT_MESSAGE_LIMIT:]

    def _build_topic_map(self) -> dict[str, dict[str, str]]:
        topic_map: dict[str, dict[str, str]] = {}
        for message in read_jsonl(self.command_paths.messages_path):
            handoff_id = str(message.get("handoffId") or "").strip()
            topic_title = str(safe_get(message, "meta", "topicTitle", default="") or "").strip()
            if not handoff_id or not topic_title:
                continue
            topic_map[handoff_id] = {
                "topicId": str(safe_get(message, "meta", "topicId", default="") or topic_id_for_title(topic_title)),
                "topicTitle": topic_title,
            }
        return topic_map

    def _message_is_hidden_legacy_noise(
        self,
        message: dict[str, Any],
        handoff_map: dict[str, dict[str, Any]],
        now_ts: float,
    ) -> bool:
        text = str(message.get("text") or "")
        if not text_looks_corrupted(text):
            return False
        created_ts = parse_timestamp(str(message.get("createdAt") or ""))
        if not created_ts:
            return False
        age_seconds = max(0.0, now_ts - created_ts)
        if age_seconds < LEGACY_CORRUPTED_MESSAGE_MAX_AGE_SECONDS:
            return False

        role = str(message.get("role") or "").strip().lower()
        kind = str(message.get("kind") or "").strip().lower()
        handoff_id = str(message.get("handoffId") or "")
        handoff_closed = handoff_id and self._handoff_is_closed(handoff_map.get(handoff_id) or {})
        return kind == "status" or (role != "user" and handoff_closed)

    def _handoff_is_closed(self, handoff: dict[str, Any]) -> bool:
        assignments = list(handoff.get("assignments") or [])
        return bool(assignments) and all(
            str(item.get("status") or "").strip().lower() in CLOSED_STATUSES for item in assignments
        )

    def _handoff_latest_timestamp(self, handoff: dict[str, Any]) -> str:
        timestamps = [str(handoff.get("createdAt") or "")]
        timestamps.extend(str(item.get("updatedAt") or "") for item in handoff.get("assignments", []))
        timestamps = [item for item in timestamps if item]
        return max(timestamps, key=parse_timestamp) if timestamps else ""

    def _summarize_handoff_result(self, handoff: dict[str, Any]) -> str:
        for assignment in handoff.get("assignments", []):
            response = trim_text(str(assignment.get("responseText") or ""), 320)
            if response:
                return response
        return trim_text(str(handoff.get("taskText") or ""), 220)

    def _handoff_report_links(self, handoff_id: str) -> dict[str, Any]:
        handoff_id = str(handoff_id or "").strip()
        if not handoff_id:
            return {}
        links = []
        for kind in ("html", "md"):
            path = self.runtime_paths.helper_reports_root / f"{handoff_id}.{kind}"
            if path.exists():
                links.append(
                    {
                        "kind": kind,
                        "label": kind.upper(),
                        "url": f"/helper-reports/{path.name}",
                        "filename": path.name,
                    }
                )
        if not links:
            return {}
        primary = next((item for item in links if item["kind"] == "html"), links[0])
        return {
            "title": handoff_id,
            "primaryUrl": primary["url"],
            "primaryLabel": "보고서 보기",
            "links": links,
        }

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
            alerts.append({"level": "warn", "title": "stale helper assignment", "detail": f"{stale}건이 남아 있습니다."})
        open_jobs = int(scheduler_status.get("openJobCount", 0) or 0)
        if open_jobs:
            alerts.append({"level": "info", "title": "중앙 스케줄러 작업 대기", "detail": f"열린 작업 {open_jobs}건"})
        if watchdog_status.get("heartbeatStale"):
            alerts.append({"level": "critical", "title": "watchdog stale", "detail": "자동 이어가기 상태를 다시 확인해야 합니다."})
        reasons = list(safe_get(watchdog_status, "resourceGuardStatus", "reasons", default=[]))
        if reasons:
            labels = [resource_guard_reason_label(item) for item in reasons]
            detail = ", ".join(str(item) for item in labels if str(item))
            alerts.append(
                {
                    "level": "warn",
                    "title": "자원 사용량 때문에 대기",
                    "detail": f"{detail} · 조건이 풀리면 자동 실행됩니다." if detail else "조건이 풀리면 자동 실행됩니다.",
                }
            )
        skip_reason = str(gmail_status.get("skipReason") or "").strip()
        if skip_reason:
            alerts.append({"level": "warn", "title": "Gmail 채널 skip", "detail": skip_reason})
        if not async_status.get("running", False):
            alerts.append({"level": "warn", "title": "async worker 중지", "detail": "서브 에이전트 완료 알림이 늦을 수 있습니다."})
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

    def _send_file_response(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        data = file_path.read_bytes()
        content_type = self.guess_type(str(file_path))
        if content_type.startswith("text/"):
            content_type = f"{content_type}; charset=utf-8"
        elif content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

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
                self.auth_manager.require_read(self)
                self._send_json(HTTPStatus.OK, self.snapshot_builder.build())
                return
            if parsed.path.startswith("/helper-reports/"):
                self.auth_manager.require_read(self)
                filename = Path(parsed.path).name
                self._send_file_response(self.runtime_paths.helper_reports_root / filename)
                return
            static_path = self.static_root / (parsed.path.lstrip("/") or "index.html")
            if parsed.path == "/":
                static_path = self.static_root / "index.html"
            self._send_file_response(static_path)
            return
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.code, "detail": exc.detail, **exc.extra})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/login":
                body = self._read_json_body()
                access_code = str(body.get("code") or "").strip()
                if not access_code:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "code_required", "접속 코드를 입력해 주세요.")
                payload, cookie = self.auth_manager.login(self, access_code)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/auth/logout":
                self.auth_manager.require_write(self)
                payload, cookie = self.auth_manager.logout(self)
                self._send_json(HTTPStatus.OK, payload, headers=[("Set-Cookie", cookie)])
                return
            if parsed.path == "/api/commands":
                self.auth_manager.require_write(self)
                self._send_json(HTTPStatus.OK, self._handle_command_submit())
                return
            if parsed.path == "/api/ptt":
                self.auth_manager.require_write(self)
                self._send_json(HTTPStatus.OK, self._handle_ptt_toggle())
                return
            if parsed.path == "/api/client-error":
                self._send_json(HTTPStatus.OK, self._handle_client_error())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.code, "detail": exc.detail, **exc.extra})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal_error", "detail": str(exc)})

    def _handle_command_submit(self) -> dict[str, Any]:
        body = self._read_json_body()
        text = str(body.get("text") or "").strip()
        context_member_title = str(body.get("contextMemberTitle") or "").strip()
        context_flow_id = str(body.get("contextFlowId") or "").strip()
        intake_mode = str(body.get("intakeMode") or "secretary-first").strip() or "secretary-first"
        if not text:
            raise ApiError(HTTPStatus.BAD_REQUEST, "text_required", "명령을 입력해 주세요.")
        topic_title = self._resolve_topic_title(text, context_flow_id)
        topic_id = topic_id_for_title(topic_title)
        user_message = build_message(
            "user",
            "command",
            text,
            meta={
                "intakeMode": intake_mode,
                "contextMemberTitle": context_member_title,
                "contextFlowId": context_flow_id,
                "topicId": topic_id,
                "topicTitle": topic_title,
            },
        )
        append_jsonl(self.command_paths.messages_path, user_message)
        dispatch_lines = [
            "[대표님 -> 비서 접수]",
            text,
            "",
            "[비서 지침] 대표님 요청을 짧게 요약하고 필요한 skill 후보를 고른 뒤 [관리자] 사장에게 전달할 것.",
            "",
            "[관리자 지침] 비서의 요약과 skill 제안을 보고 직접 처리할지, 1팀/2팀/협력 스레드에 위임할지 판단하고 완료 또는 진행 상황을 대표님께 다시 보고할 것.",
        ]
        if context_member_title and context_member_title != "[관리자] 사장":
            dispatch_lines.extend(["", f"[참고 대상] {context_member_title}"])
        if context_flow_id:
            dispatch_lines.extend(["", f"[참고 큐] {context_flow_id}"])
        dispatch_text = "\n".join(line for line in dispatch_lines if line is not None)
        dispatch_result = dispatch_background_command(dispatch_text, self.runtime_paths)
        handoff = dict(dispatch_result.get("handoff") or {})
        handoff_id = str(handoff.get("handoffId") or "")
        route_label = safe_get(handoff, "route", "routeLabel", default="")
        status_message = build_message(
            "assistant",
            "status",
            "명령을 접수했습니다. [비서] 보고자가 먼저 정리하고 스킬 후보를 고른 뒤, [관리자] 사장이 직접 처리 또는 팀 위임을 결정합니다.",
            handoff_id=handoff_id,
            meta={"route": route_label, "intakeMode": intake_mode, "topicId": topic_id, "topicTitle": topic_title},
        )
        summary_list = summary_lines(text, limit=1)
        summary_line = summary_list[0] if summary_list else trim_text(text, 120)
        status_text = (
            "명령을 접수했습니다. [비서] 보고자가 먼저 정리하고 스킬 후보를 고른 뒤, "
            "[관리자] 사장이 직접 처리 또는 팀 위임을 결정합니다.\n"
            f"요약: {summary_line}\n"
            "이대로 진행할까요? 수정할 내용이 있으면 바로 알려주세요."
        )
        status_message = build_message(
            "assistant",
            "status",
            status_text,
            handoff_id=handoff_id,
            meta={"route": route_label, "intakeMode": intake_mode, "topicId": topic_id, "topicTitle": topic_title},
        )
        append_jsonl(self.command_paths.messages_path, status_message)
        return {
            "ok": True,
            "handoffId": handoff_id,
            "userMessage": user_message,
            "statusMessage": status_message,
            "topicId": topic_id,
            "topicTitle": topic_title,
            "generatedAt": utc_now_iso(),
        }

    def _resolve_topic_title(self, text: str, context_flow_id: str) -> str:
        if context_flow_id:
            for message in reversed(read_jsonl(self.command_paths.messages_path)):
                if str(message.get("handoffId") or "").strip() != context_flow_id:
                    continue
                topic_title = str(safe_get(message, "meta", "topicTitle", default="") or "").strip()
                if topic_title:
                    return topic_title
        return infer_topic_title(text)

    def _handle_ptt_toggle(self) -> dict[str, Any]:
        body = self._read_json_body()
        ptt_state = {
            "recording": bool(body.get("recording")),
            "updatedAt": utc_now_iso(),
            "source": "command-center-ui",
        }
        write_json(self.command_paths.ptt_path, ptt_state)
        return {"ok": True, "ptt": ptt_state}

    def _handle_client_error(self) -> dict[str, Any]:
        body = self._read_json_body()
        payload = {
            "createdAt": utc_now_iso(),
            "message": str(body.get("message") or "").strip(),
            "source": str(body.get("source") or "browser"),
            "href": str(body.get("href") or ""),
            "userAgent": str(body.get("userAgent") or ""),
        }
        append_jsonl(self.command_paths.client_errors_path, payload)
        return {"ok": True, "logged": True}

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
        mime = mime or "application/octet-stream"
        if mime.startswith("text/"):
            return f"{mime}; charset=utf-8"
        if mime in {"application/javascript", "application/json"}:
            return f"{mime}; charset=utf-8"
        return mime


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
        raise ApiError(HTTPStatus.BAD_GATEWAY, "dispatch_failed", completed.stderr.strip() or stdout or "dispatch failed")
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
    parser = argparse.ArgumentParser(description="Codex Command Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runtime-root", default=None)
    args = parser.parse_args()

    runtime_paths = RuntimePaths.detect(args.runtime_root)
    command_paths = CommandCenterPaths.detect()
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
    access_code, _bootstrap = auth_manager.current_access_code()
    print(
        json.dumps(
            {
                "ok": True,
                "url": f"http://{args.host}:{args.port}",
                "runtimeRoot": str(runtime_paths.runtime_root),
                "accessCode": access_code,
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
