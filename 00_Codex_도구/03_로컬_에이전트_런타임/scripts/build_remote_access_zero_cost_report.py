from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parent
ARTIFACT_ROOT = PACKAGE_ROOT / "artifacts"
REPO_ROOT = PACKAGE_ROOT.parent.parent
CONTROL_CENTER_ROOT = REPO_ROOT / "codex-control-center"
CONTROL_CENTER_STATE = CONTROL_CENTER_ROOT / "state"
CONTROL_CENTER_STATIC = CONTROL_CENTER_ROOT / "static"


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def extract_trycloudflare_url(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    try:
        for line in reversed(log_path.read_text(encoding="utf-8", errors="ignore").splitlines()):
            if "https://" in line and ".trycloudflare.com" in line:
                start = line.find("https://")
                if start >= 0:
                    candidate = line[start:].strip().split()[0]
                    if candidate.endswith("|"):
                        candidate = candidate[:-1].rstrip()
                    return candidate
    except Exception:
        return ""
    return ""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def build_state() -> dict[str, Any]:
    tunnel = read_json(CONTROL_CENTER_STATE / "public_tunnel_status.json", {})
    bootstrap = read_json(CONTROL_CENTER_STATE / "bootstrap_setup.json", {})
    supervisor = read_json(CONTROL_CENTER_STATE / "cloudflared_supervisor_status.json", {})
    log_path = CONTROL_CENTER_STATE / "cloudflared_tunnel.log"
    public_url = str(tunnel.get("publicUrl") or "").strip()
    if not public_url:
        public_url = extract_trycloudflare_url(log_path)
    return {
        "generatedAt": iso_now(),
        "repoRoot": str(REPO_ROOT),
        "controlCenterRoot": str(CONTROL_CENTER_ROOT),
        "serverPath": str(CONTROL_CENTER_ROOT / "src" / "control_center_server.py"),
        "htmlPath": str(CONTROL_CENTER_STATIC / "index.html"),
        "cssPath": str(CONTROL_CENTER_STATIC / "styles.css"),
        "jsPath": str(CONTROL_CENTER_STATIC / "app.js"),
        "cloudflaredPath": str(CONTROL_CENTER_ROOT / "bin" / "cloudflared.exe"),
        "tunnelSupervisorPath": str(CONTROL_CENTER_ROOT / "cloudflared_tunnel_supervisor.py"),
        "publicUrl": public_url,
        "publicTunnelUpdatedAt": str(tunnel.get("updatedAt") or ""),
        "healthOk": bool(tunnel.get("healthOk")),
        "healthDetail": str(tunnel.get("healthDetail") or ""),
        "provider": str(tunnel.get("provider") or ""),
        "setupCode": str(bootstrap.get("setupCode") or ""),
        "setupCreatedAt": str(bootstrap.get("createdAt") or ""),
        "supervisorFailures": int(supervisor.get("consecutiveFailures") or 0),
    }


def component_rows(report: dict[str, Any]) -> str:
    rows = [
        (
            "로컬 API 서버",
            report["serverPath"],
            "PC에서 직접 실행되며 HTML, 상태 API, 명령 처리 API를 함께 제공합니다.",
        ),
        (
            "프론트엔드 UI",
            report["htmlPath"],
            "브라우저에서 열리는 Command Center 화면입니다.",
        ),
        (
            "스타일 및 상호작용",
            f"{report['cssPath']}\n{report['jsPath']}",
            "탭형 홈페이지, 채팅 패널, 야간 모드, 상태 렌더링 로직을 담당합니다.",
        ),
        (
            "공개 링크 브리지",
            f"{report['cloudflaredPath']}\n{report['tunnelSupervisorPath']}",
            "내 PC의 8787 포트를 외부 HTTPS 주소로 잠시 중계합니다.",
        ),
    ]
    return "".join(
        f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td><td>{esc(note)}</td></tr>"
        for name, path, note in rows
    )


def build_html(report: dict[str, Any]) -> str:
    current_access = ""
    if report["publicUrl"]:
        current_access = f"""
        <div class="callout ok">
          <strong>현재 접속 정보</strong><br />
          링크: <a href="{esc(report['publicUrl'])}">{esc(report['publicUrl'])}</a><br />
          접속 코드: <code>{esc(report['setupCode'] or '-')}</code><br />
          최근 health: {esc(report['healthDetail'] or '-')} / 최신 갱신: {esc(report['publicTunnelUpdatedAt'] or '-')}
        </div>
        """

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Codex 원격 프로그램 무과금 구축 보고서</title>
  <style>
    :root {{
      --bg: #f5f5f7;
      --paper: rgba(255,255,255,0.94);
      --ink: #1d1d1f;
      --muted: #6e6e73;
      --line: #d7d9de;
      --accent: #007aff;
      --accent-soft: rgba(0, 122, 255, 0.1);
      --ok: #34c759;
      --ok-soft: rgba(52, 199, 89, 0.12);
      --warn: #ff9f0a;
      --warn-soft: rgba(255, 159, 10, 0.14);
      --shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(0, 122, 255, 0.15), transparent 28%),
        radial-gradient(circle at bottom right, rgba(255, 159, 10, 0.12), transparent 25%),
        linear-gradient(180deg, #fafafc 0%, var(--bg) 100%);
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Pretendard", "Malgun Gothic", sans-serif;
      line-height: 1.68;
    }}
    .page {{
      width: 1120px;
      margin: 0 auto;
      padding: 40px 40px 60px;
    }}
    .hero {{
      background: linear-gradient(135deg, #123863 0%, #007aff 100%);
      color: #fff;
      border-radius: 28px;
      padding: 38px 40px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 12px;
      font-size: 34px;
      line-height: 1.2;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 0;
      font-size: 16px;
      color: rgba(255,255,255,0.92);
    }}
    .meta {{
      margin-top: 14px;
      font-size: 13px;
      color: rgba(255,255,255,0.78);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 20px;
      margin-top: 22px;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px 26px;
      box-shadow: var(--shadow);
      break-inside: avoid;
    }}
    .wide {{
      margin-top: 20px;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 24px;
      line-height: 1.35;
      letter-spacing: -0.02em;
    }}
    h3 {{
      margin: 18px 0 8px;
      font-size: 18px;
      line-height: 1.4;
    }}
    p, li {{
      font-size: 15px;
    }}
    ul, ol {{
      margin: 10px 0 0 22px;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 12px 14px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      width: 22%;
      background: #f3f7ff;
      font-weight: 700;
    }}
    code {{
      font-family: "Cascadia Mono", "Consolas", monospace;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .callout {{
      margin-top: 14px;
      padding: 16px 18px;
      border-radius: 16px;
      border-left: 6px solid var(--accent);
      background: var(--accent-soft);
    }}
    .callout.ok {{
      border-left-color: var(--ok);
      background: var(--ok-soft);
    }}
    .callout.warn {{
      border-left-color: var(--warn);
      background: var(--warn-soft);
    }}
    .pill {{
      display: inline-block;
      margin: 0 8px 8px 0;
      padding: 7px 11px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ width: auto; padding: 0; }}
      .hero, .card {{ box-shadow: none; }}
      a {{ color: inherit; text-decoration: none; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Codex 원격 프로그램 무과금 구축 보고서</h1>
      <p>현재 원격 Command Center가 어떤 구조로 동작하는지, 왜 추가 서비스 비용 없이 운영 가능한지, 정적 홈페이지 배포와 무엇이 다른지 정리한 보고서입니다.</p>
      <div class="meta">생성 시각: {esc(report["generatedAt"])}</div>
    </section>

    <section class="grid">
      <article class="card">
        <h2>1. 결론</h2>
        <p>지금 구조는 <strong>내 PC에서 직접 웹 서버를 띄우고</strong>, 그 서버를 <strong>무과금 공개 터널</strong>로 외부 HTTPS 주소에 연결하는 방식입니다. 따라서 Firebase, GitHub Pages, Vercel 같은 별도 정적 호스팅이나 앱 서버를 추가로 쓰지 않아도 외부 접속 링크를 만들 수 있습니다.</p>
        <div>
          <span class="pill">추가 호스팅 비용 0원</span>
          <span class="pill">도메인 비용 0원</span>
          <span class="pill">정적 배포 비용 0원</span>
          <span class="pill">현재는 PC와 인터넷만 사용</span>
        </div>
        <div class="callout">
          즉 “홈페이지를 어딘가에 따로 올렸다”기보다, <strong>내 PC에서 실행 중인 프로그램을 외부에서 잠깐 접속 가능하게 만든 구조</strong>에 가깝습니다.
        </div>
        {current_access}
      </article>

      <article class="card">
        <h2>2. 왜 무과금인가</h2>
        <ul>
          <li>웹 서버는 내 PC에서 직접 실행됩니다.</li>
          <li>UI 파일도 로컬 디스크에서 바로 서빙됩니다.</li>
          <li>공개 링크는 무료 Quick Tunnel을 통해 생성됩니다.</li>
          <li>로그인도 자체 접속 코드 방식이라 별도 인증 서비스 비용이 없습니다.</li>
        </ul>
        <div class="callout warn">
          여기서 “무과금”은 <strong>추가 서비스 이용료가 0원</strong>이라는 뜻입니다. 대신 PC 전원, 인터넷 회선, 그리고 PC가 켜져 있어야 한다는 운영 조건은 있습니다.
        </div>
      </article>
    </section>

    <section class="card wide">
      <h2>3. 실제 구성 요소</h2>
      <table>
        <thead>
          <tr>
            <th>구성</th>
            <th>파일</th>
            <th>역할</th>
          </tr>
        </thead>
        <tbody>
          {component_rows(report)}
        </tbody>
      </table>
    </section>

    <section class="grid">
      <article class="card">
        <h2>4. 링크가 만들어지는 원리</h2>
        <ol>
          <li>로컬 서버가 PC에서 <code>127.0.0.1:8787</code> 또는 <code>0.0.0.0:8787</code>로 떠 있습니다.</li>
          <li>공개 터널 프로세스가 그 로컬 포트를 외부 HTTPS 주소에 연결합니다.</li>
          <li>폰이나 외부 브라우저가 그 주소로 접속하면, 요청은 터널을 통해 다시 내 PC의 8787 포트로 전달됩니다.</li>
          <li>결과적으로 HTML, CSS, JS, API 응답은 모두 내 PC가 직접 반환합니다.</li>
        </ol>
        <div class="callout">
          그래서 이 링크는 “정적 홈페이지 URL”이 아니라 <strong>내 PC로 들어오는 임시 원격 입구</strong>라고 이해하면 가장 정확합니다.
        </div>
      </article>

      <article class="card">
        <h2>5. 이전 방식과 현재 방식</h2>
        <h3>이전</h3>
        <p><code>localhost.run</code> SSH reverse tunnel로 <code>*.lhr.life</code> 링크를 받았습니다.</p>
        <h3>현재</h3>
        <p><code>cloudflared tunnel --url http://127.0.0.1:8787</code> 기반 Quick Tunnel로 <code>*.trycloudflare.com</code> 링크를 받습니다.</p>
        <div class="callout ok">
          현재는 별도 supervisor가 터널 상태와 health check를 감시하므로, 이전보다 끊김 복구가 더 안정적입니다.
        </div>
      </article>
    </section>

    <section class="grid">
      <article class="card">
        <h2>6. 장점</h2>
        <ul>
          <li>추가 계정 과금 없이 즉시 외부 접속 링크를 만들 수 있습니다.</li>
          <li>지금 로컬에서 만든 프로그램을 거의 그대로 외부에 노출할 수 있습니다.</li>
          <li>배포 준비 없이 빠르게 테스트하고 반복 개선할 수 있습니다.</li>
          <li>URL이 바뀌어도 메일이나 보고서로 최신 링크를 다시 전달하면 됩니다.</li>
        </ul>
      </article>

      <article class="card">
        <h2>7. 한계</h2>
        <ul>
          <li>PC가 꺼지면 링크도 같이 죽습니다.</li>
          <li>Quick Tunnel은 재시작 시 주소가 바뀔 수 있습니다.</li>
          <li>무료 터널은 고정 URL이나 정식 운영 SLA를 보장하지 않습니다.</li>
          <li>장기 서비스라면 나중엔 고정 도메인, 정식 인증, 안정적인 배포 구조가 필요합니다.</li>
        </ul>
      </article>
    </section>

    <section class="card wide">
      <h2>8. 왜 지금 단계에 적합한가</h2>
      <p>현재 목표는 휴대폰에서 바로 접속해 Codex에게 프롬프트를 보내고, 상태를 보고, 간단히 제어할 수 있는 개인용 원격 Command Center를 빠르게 만드는 것입니다. 이 단계에서는 “비용 없이 바로 열어보고 고칠 수 있는 구조”가 가장 중요하므로, 지금의 로컬 서버 + 무료 터널 구조가 효율이 가장 좋습니다.</p>
      <div class="callout warn">
        다만 이 구조는 빠른 검증과 개인 운영에 최적화된 형태입니다. 장기 운영이나 다중 사용자 서비스로 갈 경우에는 정식 배포 구조로 넘어가는 편이 맞습니다.
      </div>
    </section>
  </div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a zero-cost remote access report for Codex Command Center.")
    parser.add_argument("--tag", default=(datetime.now().strftime("%Y-%m-%d") + "-remote-zero-cost"))
    parser.add_argument("--output-dir", default=str(ARTIFACT_ROOT))
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report = build_state()
    html_path = output_dir / f"remote_access_zero_cost_report_{args.tag}.html"
    data_path = output_dir / f"remote_access_zero_cost_report_data_{args.tag}.json"

    html_path.write_text(build_html(report), encoding="utf-8")
    data_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        f"원격 프로그램 무과금 구축 보고서를 생성했습니다. "
        f"현재 공개 URL은 '{report['publicUrl'] or '-'}', "
        f"터널 provider는 '{report['provider'] or '-'}' 입니다."
    )

    print(
        json.dumps(
            {
                "ok": True,
                "tag": args.tag,
                "htmlPath": str(html_path),
                "dataPath": str(data_path),
                "summary": summary,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
