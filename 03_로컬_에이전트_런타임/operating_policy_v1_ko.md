# 로컬 Codex 에이전트 운영정책 v1

## 1. 목적
- 유료 API 없이 로컬 스크립트, 브라우저 DOM 제어, 필요 시 KVM 보조 제어를 결합해 Codex를 지속적으로 개선한다.
- Codex는 실행과 검증을 맡고, Gemini와 ChatGPT는 자문 역할로 사용한다.
- 브라우저 자동화는 DOM 우선, 화면 확인과 KVM은 예외 처리와 복구 수단으로만 사용한다.

## 2. 역할 분담
### Codex
- 파일 수정, 스크립트 실행, 테스트, Git 체크포인트, 로그 기록
- 안정적인 DOM 제어, 로컬 오케스트레이션, 재현 가능한 수정

### Gemini
- 현재 웹 UI 구조 해석, 셀렉터 드리프트 점검, 화면 상태 해석
- Google 서비스 동작 이해, 화면 기반 요약과 비교

### ChatGPT
- 운영 규칙 문서화, 구조 설명, 변경 요약, 보고서 구조화
- 리팩터링 방향, 체크리스트, 정책 초안

## 3. 언제 누구에게 물을지
### Codex 단독
- 로컬 파일 수정, 스크립트 실행, 테스트, 로그 분석
- `exit code`, `diff`, `DOM selector`, `stdout/stderr`로 바로 검증 가능한 작업

### Gemini 자문
- 지금 열려 있는 웹 UI의 구조나 화면 상태가 핵심인 작업
- Gemini, Google 계열 웹페이지, 시각적 흐름이 중요한 작업

### ChatGPT 자문
- 운영 정책, 보고서 구조, 설명 품질, 리팩터링 논의
- 여러 대안을 비교해 장단점을 정리해야 하는 작업

### 둘 다 자문
- 장기 운영 규칙처럼 나중에도 반복 적용될 정책 변경
- 웹 UI 해석과 코드 구조 판단이 동시에 필요한 작업

## 4. 기존 채팅과 새 채팅 기준
- 기존 채팅 유지:
  - 같은 버그, 같은 페이지, 같은 보고서를 이어서 다듬는 경우
  - 직전 응답이 다음 액션에 바로 연결되는 경우
- 새 채팅 시작:
  - 주제가 바뀌었을 때
  - 독립 검토가 필요할 때
  - 기존 스레드가 길어져 응답 품질이 흐려질 때

## 5. 기술 구조 원칙
- 단일 orchestrator 우선:
  - planner, executor, verifier, reporter를 내부 모듈로 분리하되 진입점은 하나로 유지한다.
- DOM 우선:
  - `navigate`, `prompt-send`, `click-text`, `visible-text`, `extract` 같은 구조화된 액션을 먼저 사용한다.
- KVM은 보조 수단:
  - DOM 제어 실패 후 화면 확인을 거친 뒤에만 사용한다.
- Observe -> Act -> Verify:
  - 한 번에 너무 많은 UI 액션을 묶지 않고, 관찰 후 실행하고 즉시 검증한다.
- Provider health 확인:
  - Gemini/ChatGPT 중 응답 가능한 브리지 클라이언트를 먼저 고른다.

## 6. 외부 프로젝트에서 가져온 패턴
- OpenClaw:
  - 세션 상태와 라우팅을 한 게이트웨이에서 관리한다.
- Claude computer use:
  - 모든 액션은 관찰 가능한 결과를 남기고, 루프는 제한 조건을 둔다.
- browser-use, Stagehand:
  - 자유형 UI 조작보다 구조화된 고수준 액션을 선호한다.
- Open Interpreter:
  - 로컬 실행 결과를 수집하고, 실패 문맥만 최소한으로 다시 피드백한다.
- Agent Zero, Codex app:
  - 거대한 단일 문맥보다 내부 작업 분리와 컨텍스트 정리를 우선한다.

## 7. 작업 체크포인트
- 시작 전:
  - 목표, 범위, 위험, 복구 방법 기록
- 실행 중:
  - `timestamp | step | tool | target | action | result | evidence`
- 종료 시:
  - 변경 파일, 테스트 결과, 남은 리스크, 다음 작업 제안 기록
- Git:
  - 의미 있는 개선이 끝나면 체크포인트 커밋과 푸시를 남긴다.

## 8. 보고서 작성 규칙
- 사용자에게 보여 주는 보고서, 매뉴얼, PDF, 인쇄물은 읽는 사람이 기술 용어를 몰라도 이해할 수 있어야 한다.
- 보고서 본문에 기술 용어가 들어가면 반드시 `부록 A. 용어 설명`을 붙인다.
- 각 용어 항목에는 최소한 다음 내용을 넣는다.
  - 용어
  - 정확한 의미
  - 쉽게 풀어쓴 설명
  - 이 보고서에서 왜 중요한지
  - 이 시스템 또는 이번 작업에서 어떤 맥락으로 쓰였는지
- 기술 용어가 많아 부록이 길어져도 생략하지 않는다.
- 본문은 빠르게 읽히게 쓰고, 자세한 설명은 부록으로 내린다.
- 공통 규칙은 `config/reporting_policy.json`에 둔다.
- 공통 용어 카탈로그는 `config/technical_terms_glossary.json`에 둔다.

## 9. 실패 규칙
- 같은 방법을 세 번 반복해도 안 되면 경로를 바꾼다.
- DOM 실패 -> 화면 캡처 -> KVM 사용 여부 결정 순서를 지킨다.
- 고비용 또는 고위험 작업은 공식 문서와 승인 흐름을 우선한다.
- 불확실한 고위험 작업은 자동 실행하지 않는다.

## 10. 다음 개선 백로그
1. provider health를 GUI에 더 명확히 표시
2. 응답 완료 감지 추가
3. DOM `extract` 액션 확장
4. 내부 작업 큐와 재시도 정책 분리
5. 장기 루프용 stop file / pause signal 추가
6. 재현 가능한 세션 스냅샷과 버그 보고 패키지 강화

## 11. 참고 자료
- [OpenClaw Docs](https://docs.openclaw.ai/index)
- [Anthropic Computer Use Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [browser-use GitHub](https://github.com/browser-use/browser-use)
- [Stagehand GitHub](https://github.com/browserbase/stagehand)
- [Open Interpreter GitHub](https://github.com/OpenInterpreter/open-interpreter)
- [Agent Zero GitHub](https://github.com/frdel/agent-zero)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
