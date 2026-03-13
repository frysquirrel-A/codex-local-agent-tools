# Codex Control Center

Codex 메인 오케스트레이터, helper 스레드, LLM 웹 스레드, handoff 메시지 흐름, watchdog/중앙 스케줄러 상태를 한 화면에서 볼 수 있는 Windows용 로컬 관제 UI입니다.

## 특징

- 메인 오케스트레이터와 helper 역할 한눈에 보기
- ChatGPT/Gemini 웹 스레드 레지스트리 표시
- 최근 handoff 메시지와 helper 응답 흐름 추적
- watchdog, 중앙 스케줄러, helper queue, Gmail 채널 상태 요약
- 5초 자동 새로고침
- 별도 패키지 설치 없이 Python 표준 라이브러리만 사용

## 실행

PowerShell:

```powershell
Set-Location "C:\Users\Ryzen\Desktop\codex-agent\codex-control-center"
.\start_control_center.ps1
```

또는 `launch_control_center.cmd`를 더블클릭하세요.

기본 주소:

- [http://127.0.0.1:8787](http://127.0.0.1:8787)

## 데이터 소스

- [codex_helper_thread_roster.json](C:\Users\Ryzen\Desktop\codex-agent\00_Codex_도구\03_로컬_에이전트_런타임\config\codex_helper_thread_roster.json)
- [llm_thread_registry.json](C:\Users\Ryzen\Desktop\codex-agent\00_Codex_도구\03_로컬_에이전트_런타임\config\llm_thread_registry.json)
- [helper_handoffs/status.json](C:\Users\Ryzen\Desktop\codex-agent\00_Codex_도구\03_로컬_에이전트_런타임\state\helper_handoffs\status.json)
- [central_scheduler/status.json](C:\Users\Ryzen\Desktop\codex-agent\00_Codex_도구\03_로컬_에이전트_런타임\state\central_scheduler\status.json)
- [turn_continuation_watchdog/status.json](C:\Users\Ryzen\Desktop\codex-agent\00_Codex_도구\03_로컬_에이전트_런타임\state\turn_continuation_watchdog\status.json)

## GitHub 메모

현재 `origin`은 이미 연결돼 있습니다. 다만 GitHub Project 보드 자동 생성은 API 인증 상태에 따라 추가 조정이 필요할 수 있습니다. 저장소 push는 일반 `git push`로 시도할 수 있습니다.
