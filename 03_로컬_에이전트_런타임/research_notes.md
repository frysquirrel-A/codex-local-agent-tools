Local Agent Research Notes

Consultation summary:
- Gemini emphasized minimizing LLM round trips and reserving consultation for ambiguous web state, large-context interpretation, and externally changing services.
- ChatGPT emphasized keeping Codex as the primary executor, treating Gemini and ChatGPT as secondary advisors, and writing explicit operating rules after each improvement.

What to borrow:
- OpenClaw: one gateway as the source of truth for sessions, routing, and channel state.
- Claude computer use: screenshot, mouse, and keyboard are part of an agent loop, not a separate uncontrolled path.
- browser-use: reduce pages into agent-friendly action surfaces instead of shipping whole raw DOMs around.
- Stagehand: expose high-level actions such as act, extract, and agent-level tasks on top of a low-level browser engine.
- Open Interpreter: close the loop by running local code, collecting output, and using the result for the next repair step.
- Agent Zero: keep context clean with subordinate specialization, but avoid uncontrolled multi-agent sprawl.
- Codex app guidance: multiple agents are useful when isolated, but each thread should stay focused and reviewable.

Immediate local decisions:
- Keep a single orchestrator as the controlling entry point.
- Prefer DOM control first, KVM second, screenshot review before blind retries.
- Health-check provider tabs before selecting them for consult mode.
- Save a git checkpoint whenever a runtime behavior improvement lands.

Current improvement targets:
1. Provider health reporting and stale-client avoidance.
2. Response completion detection without fixed sleeps.
3. Structured extraction from active tabs.
4. Better launcher visibility into active sessions, retries, and last successful provider.
