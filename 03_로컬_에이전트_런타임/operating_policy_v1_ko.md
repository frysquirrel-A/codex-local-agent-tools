# 로컬 Codex 에이전트 운영정책 v1

## 1. 목적
- 유료 API 없이 로컬 스크립트, 브라우저 DOM 제어, 필요 시 KVM을 결합해 Codex를 지속 개선한다.
- Codex는 실행기, Gemini와 ChatGPT는 자문기 역할로 둔다.
- 브라우저 자동화는 DOM 우선, KVM은 예외 처리와 복구 수단으로만 쓴다.

## 2. 역할 분담
- Codex:
  - 파일 수정, 스크립트 실행, 테스트, Git 체크포인트, 로그 기록
  - 안정적인 DOM 제어, 로컬 시스템 작업, 재현 가능한 수정
- Gemini:
  - 현재 웹 UI 구조 해석, 스크린샷 기반 판단, Google 서비스 동작 맥락
  - 긴 텍스트 요약, 구조 발산, 여러 UX 초안 비교
- ChatGPT:
  - 운영 규칙 문서화, 예외 기준, 리스크 분류, 테스트/보고 체계 설계
  - 스크립트 구조화, 리팩터링 방향, 변경 요약

## 3. 누구에게 물을지
### Codex 단독
- 성공 기준이 `exit code`, `test`, `DOM selector`, `diff`로 판정되는 작업
- 파일 정리, 코드 수정, 로그 기반 버그 수정, 재현 가능한 자동화 수정
- 15분 내 해결 가능하고 롤백이 쉬운 작업

### Gemini에 질문
- 셀렉터가 흔들리거나 화면 상태 해석이 필요한 작업
- Google/Gemini 페이지 구조, 현재 웹 UI 흐름이 중요한 작업
- 요구사항이 애매해서 여러 화면/UX 초안을 비교해야 하는 작업

### ChatGPT에 질문
- 운영정책, 승인 기준, 실패 분류, 보고서 구조를 정해야 하는 작업
- 여러 수정안을 글로 정리하고 기준표로 바꿔야 하는 작업
- 긴 문맥을 압축해 체크리스트/정책으로 바꾸는 작업

### 둘 다 질문
- 런타임 구조 변경처럼 고위험 설계가 걸린 작업
- 웹 UI 해석과 코드 구조 판단이 동시에 필요한 작업
- 앞으로 반복 사용할 정책을 만드는 작업

## 4. 언제 기존 채팅을 쓰고 언제 새 채팅을 여는가
- 기존 채팅 유지:
  - 같은 버그, 같은 페이지, 같은 보고서를 이어서 작업할 때
  - 바로 직전 답변의 맥락이 다음 액션에 직접 연결될 때
- 새 채팅 시작:
  - 주제가 바뀌었을 때
  - 독립 검토가 필요할 때
  - 기존 스레드가 길어져 답이 흐려질 때
  - 공급자 탭이 죽어서 새 클라이언트가 필요할 때

## 5. 기술 구조 원칙
- 단일 orchestrator 유지
  - planner / executor / verifier / reporter 역할을 내부적으로 나눈다.
- DOM 우선
  - `navigate`, `prompt-send`, `click-text`, `visible-text` 같은 구조화 액션을 먼저 쓴다.
- KVM 후순위
  - DOM 실패 후 화면 확인을 거친 다음에만 쓴다.
- Observe -> Act -> Verify
  - 한 번에 여러 UI 액션을 몰아서 하지 않는다.
- 공급자 건강 상태 확인
  - Gemini/ChatGPT를 선택할 때는 먼저 살아 있는 bridge client를 찾는다.

## 6. 외부 프로젝트에서 가져올 구조
- OpenClaw:
  - 세션과 라우팅의 단일 게이트웨이
- Claude computer use:
  - 스크린샷/키보드/마우스를 도구 루프로 다루는 방식
- browser-use:
  - 브라우저를 구조화된 액션 표면으로 다루는 방식
- Stagehand:
  - `act`, `extract` 같은 상위 액션 계층
- Open Interpreter:
  - 로컬 실행 -> 출력 수집 -> 재시도 루프
- Agent Zero:
  - 역할 분리와 컨텍스트 정리

## 7. 작업 체크포인트
- 시작 전:
  - 목표, 범위, 위험도, 롤백 방법 기록
- 실행 중:
  - `timestamp | step | tool | target | action | result | evidence`
- 종료 시:
  - 변경 파일, 테스트 결과, 남은 리스크, 다음 작업 제안 기록
- Git:
  - 의미 있는 개선이 끝나면 커밋
  - 가능하면 바로 원격 푸시

## 8. 실패 시 규칙
- 같은 방법 3회 반복 금지
- DOM 실패 -> 화면 캡처 -> KVM 여부 결정
- 한 공급자 장애 시 다른 공급자 + 공식 문서로 진행
- 불확실한 고위험 작업은 자동 실행 금지

## 9. 다음 개선 백로그
1. 공급자 health 상태를 GUI에 표시
2. 응답 완료 감지 추가
3. DOM `extract` 액션 추가
4. 내부 작업 큐와 재시도 정책 분리
5. 장기 루프용 stop file / pause signal 추가
6. 세션 스냅샷과 재현 패키지 추가

## 10. 참고한 외부 자료
- [OpenClaw Docs](https://docs.openclaw.ai/index)
- [Anthropic Computer Use Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [browser-use GitHub](https://github.com/browser-use/browser-use)
- [Stagehand GitHub](https://github.com/browserbase/stagehand)
- [Open Interpreter GitHub](https://github.com/OpenInterpreter/open-interpreter)
- [Agent Zero GitHub](https://github.com/frdel/agent-zero)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
