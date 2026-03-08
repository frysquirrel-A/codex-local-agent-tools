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
- Remote command channel config lives in `config\remote_command_channel.json`.
- Remote command scripts are `scripts\check_remote_commands.ps1`, `scripts\start_remote_command_poller.ps1`, `scripts\stop_remote_command_poller.ps1`, `scripts\get_remote_command_queue.ps1`, `scripts\mark_remote_command_processed.ps1`, `scripts\summarize_remote_command_inbox.ps1`, and `scripts\execute_remote_command_inbox.ps1`.
- The normalized inbox digest is written to `state\remote_command_inbox.json` on each poll cycle.

Remote command inbox:
- `check_remote_commands.ps1` pulls GitHub issues into the local queue and uses the local git credential token to avoid anonymous API rate limits.
- `summarize_remote_command_inbox.ps1` maps queued items to a safe mode, risk level, approval requirement, and suggested consultation providers.
- `execute_remote_command_inbox.ps1` handles owner-only structured commands, writes dry-run artifacts, posts GitHub issue comments through the local git credential token, and closes successful issues.
- The executor uses per-issue lock files under `state\remote_command_locks` so the worker and manual runs do not process the same command twice at the same time.
- The worker keeps `remote_command_inbox.json` fresh and then runs the executor each poll cycle.

Structured remote command v1:
- The `Command` field should contain JSON, not free-form natural language.
- Example browser command: `{"mode":"browser-command","action":"navigate","url":"https://example.com"}`
- Example LLM command: `{"mode":"llm-prompt","provider":"chatgpt","prompt":"Summarize the current page.","send":true}`
- Example desktop command: `{"mode":"desktop-command","action":"screen-size"}`
- Non-JSON commands stay in manual review.
