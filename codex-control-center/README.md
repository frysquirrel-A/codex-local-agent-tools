# Codex Command Center

Codex와 직접 대화하고, 서브에이전트 handoff, watchdog, 중앙 스케줄러, Gmail 채널 상태를 한 화면에서 보는 Windows용 로컬 관제 프로그램입니다.

기존 대시보드형 화면을 채팅 중심 Command Center로 바꿔서 아래 흐름을 바로 사용할 수 있게 만들었습니다.

- 명령 입력
- 백그라운드 서브에이전트 위임
- helper handoff 추적
- 완료 시 팝업/보고서 확인
- watchdog, queue, Gmail 상태 관찰

## 주요 기능

- iMessage 스타일의 채팅형 작업 로그
- `/api/commands`로 명령 접수 후 helper async runtime에 백그라운드 위임
- `/api/ptt`로 PTT 상태 토글
- 최초 1회 설정 코드 + 비밀번호 기반 로그인
- 세션 쿠키, CSRF, 로그인 실패 제한을 적용한 보호 모드
- watchdog, helper queue, scheduler, Gmail 상태 요약 카드
- 최근 handoff와 helper 응답 흐름 표시
- runtime 경로와 스레드 레지스트리 표시
- 5초 자동 새로고침
- Python 표준 라이브러리만으로 실행

## 폴더 구조

- 프론트엔드
  - [index.html](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/static/index.html)
  - [styles.css](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/static/styles.css)
  - [app.js](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/static/app.js)
- 백엔드
  - [control_center_server.py](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/src/control_center_server.py)
- 실행 스크립트
  - [start_control_center.ps1](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/start_control_center.ps1)
  - [launch_control_center.cmd](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/launch_control_center.cmd)
- 로컬 상태 저장
  - [state](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/state)

## 실행

PowerShell:

```powershell
Set-Location "C:\Users\Ryzen\Desktop\codex-agent\codex-control-center"
.\start_control_center.ps1
```

또는 [launch_control_center.cmd](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/launch_control_center.cmd)를 더블클릭하면 됩니다.

기본 주소:

- [http://127.0.0.1:8787](http://127.0.0.1:8787)

## 최초 로그인과 보안

- 처음 접속하면 `최초 설정` 화면이 먼저 열립니다.
- 서버가 생성한 1회용 설정 코드는 [bootstrap_setup.json](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/state/bootstrap_setup.json)에 저장됩니다.
- 이 코드를 한 번만 사용해 비밀번호를 정한 뒤부터는 일반 로그인 화면으로 바뀝니다.
- 보호된 API는 세션 쿠키와 CSRF 검증이 있어야만 접근됩니다.
- 로그인 실패가 누적되면 잠시 잠금이 걸립니다.

## 외부 접속

- 공개 터널 실행 스크립트:
  - [start_public_tunnel.ps1](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/start_public_tunnel.ps1)
  - [start_public_tunnel.py](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/start_public_tunnel.py)
- 최신 공개 URL 상태:
  - [public_tunnel_status.json](C:/Users/Ryzen/Desktop/codex-agent/codex-control-center/state/public_tunnel_status.json)
- 외부 URL은 바뀔 수 있으므로, 최신 주소는 상태 파일이나 메일 안내를 확인하는 방식이 안전합니다.

## API

- `GET /api/health`
  서버 생존 확인
- `GET /api/auth/state`
  현재 로그인 상태와 최초 설정 필요 여부 조회
- `GET /api/snapshot`
  로그인 후에만 채팅, watchdog, helper queue, Gmail, 경로, handoff 흐름 조회
- `POST /api/auth/setup`
  최초 1회 설정 코드로 비밀번호를 만들고 로그인 세션 발급
- `POST /api/auth/login`
  비밀번호로 로그인
- `POST /api/auth/logout`
  현재 세션 종료
- `POST /api/commands`
  로그인 후 새 명령을 채팅 로그에 추가하고 helper handoff를 백그라운드로 전송
- `POST /api/ptt`
  로그인 후 PTT 녹음 상태 토글

## 연결되는 런타임 데이터

- [codex_helper_thread_roster.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/config/codex_helper_thread_roster.json)
- [llm_thread_registry.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/config/llm_thread_registry.json)
- [helper_handoffs/status.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/state/helper_handoffs/status.json)
- [central_scheduler/status.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/state/central_scheduler/status.json)
- [turn_continuation_watchdog/status.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/state/turn_continuation_watchdog/status.json)
- [gmail_command_channel_status.json](C:/Users/Ryzen/Desktop/codex-agent/00_Codex_도구/03_로컬_에이전트_런타임/state/gmail_command_channel_status.json)

## 사용 메모

- 채팅창에서 명령을 보내면 즉시 로컬 로그에 기록되고 helper handoff가 생성됩니다.
- 결과가 준비되면 helper async runtime이 팝업과 보고서를 띄우는 구조입니다.
- 메인 UI는 브라우저에서 열리지만, 작업 실행은 로컬 런타임과 helper 스레드가 담당합니다.
