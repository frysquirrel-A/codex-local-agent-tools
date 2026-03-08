Codex 전용 도구 모음

구조:
- 01_브라우저_자동화: Live Chrome DOM 제어 도구
- 02_데스크톱_KVM_제어: 마우스, 키보드, 창 포커스, 화면 캡처 도구
- 03_로컬_에이전트_런타임: 브라우저 자동화와 KVM 제어를 묶어 실제 작업 단위로 실행하는 오케스트레이터
  - 통합 실행기: scripts\invoke_agent_orchestrator.ps1
  - EXE 런처: bin\CodexLocalAgentLauncher.exe
- 99_공용_유틸: 여러 요청에서 재사용할 공통 실행 파일과 보조 유틸
  - Git 체크포인트: 99_공용_유틸\scripts\checkpoint_tool_repo.ps1
- docs: GitHub Pages 기반 원격 명령 포털
- .github\ISSUE_TEMPLATE: 원격 명령용 GitHub Issue 템플릿

메모:
- 공부용 루트에는 브라우저 자동화 호환 링크가 숨김 처리되어 있을 수 있습니다.
- 실제 관리 대상은 이 폴더 아래의 각 번호별 도구입니다.
- 무과금 원칙: 로컬 스크립트와 사용 중인 웹 UI만 사용합니다.
- 고위험 작업 원칙: 금융 거래, 결제, 송금, 대량 삭제 같은 작업은 자동 자율 실행 대상으로 열어두지 않습니다.
- 원격 명령 원칙: 무료 호스팅은 GitHub Pages, 입력 채널은 GitHub Issue, 로컬 알림은 poller로 처리합니다.
