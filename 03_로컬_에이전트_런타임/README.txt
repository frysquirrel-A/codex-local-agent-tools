Local Agent Runtime

Purpose:
- Orchestrate local browser control, LLM web prompting, and optional screen watch.
- Keep the main flow on one launcher entry point.

Main entry points:
- Console EXE: `bin\CodexLocalAgentLauncher.exe`
- GUI EXE: `bin\CodexLocalAgentLauncherGui.exe`
- Script entry: `scripts\invoke_agent_orchestrator.ps1`

Fast-path improvements applied:
- New-chat flow no longer waits a fixed 4 seconds.
- Browser prompt send now uses a single browser-side `prompt_send` action.
- Normal send mode skips unnecessary `ping` and `dom-summary` preflight calls.
- Bridge result polling is faster and the extension heartbeat is shorter.
- Provider selection skips stale bridge clients and prefers a responsive client per provider.

GUI usage:
- Run `status`, `route`, `consult`, `new-chat`, `watch-start`, and `watch-stop` from buttons.
- Enter task text or prompt override directly in the window.
- Copy JSON output from the GUI after each run.

Recommended usage:
- Quick checks or manual use: GUI EXE
- Scripted use or chaining: console EXE or `invoke_agent_orchestrator.ps1`

Notes:
- This runtime depends on the browser bridge package under `..\01_브라우저_자동화`.
- If Chrome is closed, consult mode cannot reach Gemini or ChatGPT until those tabs are open again.
- Continuous-improvement rules live in `config\continuous_improvement_policy.json`.
- Research notes comparing external agent projects live in `research_notes.md`.
