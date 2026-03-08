---
name: local-pc-agent-runtime
description: Use this skill when Codex needs to coordinate local browser DOM automation, Windows desktop KVM control, and web LLM prompting from the user's existing PC session without paid APIs.
---

# Local PC Agent Runtime

Use this runtime when a task spans multiple local control layers:
- browser DOM control in the user's existing Chrome session
- desktop KVM fallback for focus, clicks, and keyboard input
- prompting Gemini or ChatGPT through their web UI instead of paid APIs
- periodic screen capture for near-real-time screen awareness
- printed approval reports for paid actions
- collaboration routing for when Codex should stay solo vs consult Gemini or ChatGPT
- a unified launcher that wraps the runtime into one entrypoint and an optional EXE

## Core rules

1. Keep all generated artifacts under `공부용`.
2. Prefer browser DOM control before desktop KVM.
3. Use `scripts/send_web_llm_prompt.ps1` for Gemini and ChatGPT web UI prompting.
4. Use `scripts/invoke_local_agent_task.ps1` as the main orchestrator for task-level execution and logging.
5. Do not execute irreversible or high-risk actions autonomously.
6. If continuous visual awareness is needed, prefer the screen watch loop over manual one-off screenshots.
7. Before consulting a web LLM for planning or explanation work, read `config/llm_collaboration_policy.json` or run `scripts/select_collaboration_route.ps1`.
8. Use the same policy to decide whether to continue in the current Gemini/ChatGPT thread or start a new chat for a clean review.

## High-risk boundary

Treat these as blocked or manual-only unless the user explicitly narrows the request and a guarded workflow exists:
- stock trading, brokerage actions, crypto trading
- money transfer, payment, purchase confirmation
- credential changes, security settings, account recovery
- destructive file deletion outside the approved workspace

Paid software or subscription decisions can use the printed spend approval workflow, but market trading and money movement stay blocked.
The approval workflow is asynchronous: create a pending request, print the queue report, and wait for the user to approve by chat later.

## Workflow

1. Read `config/agent_policy.json` for risk gates.
2. If deciding whether to consult Gemini or ChatGPT, read `config/llm_collaboration_policy.json`.
3. If the task is Gemini or ChatGPT prompting, read `config/web_llm_profiles.json`.
4. Start with `scripts/invoke_local_agent_task.ps1`.
5. For browser tasks, ensure the bridge server is running and the target tab is the active page.
6. For desktop tasks, go through the guarded KVM wrapper instead of calling low-level scripts directly.

## Entrypoints

- Main orchestrator: `scripts/invoke_local_agent_task.ps1`
- Web LLM prompt helper: `scripts/send_web_llm_prompt.ps1`
- Unified orchestrator: `scripts/invoke_agent_orchestrator.ps1`
- Launcher builder: `scripts/build_agent_launcher.ps1`
- Screen watch start: `scripts/start_screen_watch.ps1`
- Screen watch stop: `scripts/stop_screen_watch.ps1`
- Spend approval report builder: `scripts/build_spend_approval_report.ps1`
- Spend approval printer: `scripts/print_spend_approval_report.ps1`
- Policy: `config/agent_policy.json`
- Collaboration policy: `config/llm_collaboration_policy.json`
- LLM selectors: `config/web_llm_profiles.json`
- Collaboration router: `scripts/select_collaboration_route.ps1`

## Examples

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode browser-command -BrowserAction ping
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode llm-prompt -Provider gemini -ValidateOnly
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode desktop-command -DesktopArgs @('screen-size')
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode screen-watch-start -IntervalSeconds 0.1
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode spend-approval -SpendTitle "VS Code Pro 확장 검토" -SpendSubject "월 구독 결제" -EstimatedCostKRW 29000 -ExpectedBenefit "반복 작업 절감, 품질 향상" -Reason "로컬 환경에서 필요한 경우에만 승인 후 사용"
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_local_agent_task.ps1 -Mode spend-approve -RequestId "SREQ-260307-230500-01"
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\select_collaboration_route.ps1 -TaskText "현재 Chrome의 Gemini 셀렉터가 바뀌어서 다시 찾아야 하고, 결과를 사용자 가이드로 정리해줘."
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\invoke_agent_orchestrator.ps1 -Mode consult -TaskText "새 채팅으로 독립 검토를 받고 싶은 고위험 자동화 설계를 비교해줘." -Send
```
