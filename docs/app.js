const REPO_OWNER = "frysquirrel-A";
const REPO_NAME = "codex-local-agent-tools";
const ISSUE_LABEL = "remote-command";
const TITLE_PREFIX = "[remote]";
const RELAY_BASES = ["http://127.0.0.1:8767", "http://localhost:8767"];
const RELAY_POLL_MS = 2500;
const FALLBACK_POLL_MS = 15000;
const RELAY_STATUS_TIMEOUT_MS = 3500;
const RELAY_STATUS_RETRIES = 3;
const RELAY_RETRY_DELAY_MS = 350;
const RELAY_PAGE_REQUEST_SOURCE = "codex-page-relay";
const RELAY_PAGE_RESPONSE_SOURCE = "study-live-relay-bridge";
const RELAY_PAGE_TIMEOUT_MS = 1500;
const SESSION_KEY = "codex-chat-session-id";
const THREAD_LIMIT = 14;

const state = {
  relayBase: null,
  relayConnected: false,
  relayEntries: [],
  fallbackEntries: [],
  loading: false,
  sending: false,
  sessionId: getOrCreateSessionId(),
  selectedTarget: "other",
  selectedPriority: "normal",
  toolsOpen: false,
  pollHandle: null,
  fallbackHandle: null,
  relayError: "",
  relayProbePromise: null,
  relayBridgeReady: false
};

function getOrCreateSessionId() {
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) {
    return existing;
  }

  const created = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `sid-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  window.localStorage.setItem(SESSION_KEY, created);
  return created;
}

function resetSessionId() {
  const created = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `sid-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  window.localStorage.setItem(SESSION_KEY, created);
  state.sessionId = created;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseSection(body, heading) {
  if (!body) {
    return "";
  }

  const pattern = new RegExp(`###\\s+${heading}\\s*\\n([\\s\\S]*?)(?=\\n###\\s+|$)`, "m");
  const match = body.match(pattern);
  return match ? match[1].trim() : "";
}

function parseMaybeJson(command) {
  try {
    return JSON.parse(command);
  } catch {
    return null;
  }
}

function summarizeCommand(command, target) {
  const normalized = normalizeText(command);
  if (!normalized) {
    return "내용 없음";
  }

  const parsed = parseMaybeJson(normalized);
  if (!parsed || typeof parsed !== "object") {
    return normalized;
  }

  const parts = [];
  if (parsed.mode) {
    parts.push(parsed.mode);
  }
  if (parsed.action) {
    parts.push(parsed.action);
  }
  if (parsed.provider) {
    parts.push(parsed.provider);
  }
  if (parsed.url) {
    parts.push(parsed.url);
  }
  if (!parts.length && target) {
    parts.push(target);
  }
  if (parsed.text) {
    parts.push(normalizeText(parsed.text).slice(0, 80));
  }

  return normalizeText(parts.join(" · ")) || normalized;
}

function parseExecutorComment(body) {
  if (!body) {
    return null;
  }

  const details = {};
  const bulletPattern = /^-\s+([^:]+):\s*(.+)$/gm;
  let match = bulletPattern.exec(body);
  while (match) {
    details[match[1].trim().toLowerCase()] = match[2].trim();
    match = bulletPattern.exec(body);
  }

  const paragraphs = body
    .split(/\n\s*\n/)
    .map((part) => normalizeText(part))
    .filter(Boolean)
    .filter((part) => !part.startsWith("## Codex Remote Executor") && !part.startsWith("- "));

  const status = (details.status || "").toLowerCase();
  const finalLine = paragraphs.length ? paragraphs[paragraphs.length - 1] : "";

  return {
    status: status || "update",
    title: normalizeText([details.mode || "", details.action || ""].filter(Boolean).join(" · ")) || "Codex 응답",
    text: finalLine || "작업 상태가 업데이트되었습니다.",
    createdAt: details.timestamp || ""
  };
}

function timeLabel(value) {
  if (!value) {
    return "";
  }

  return new Date(value).toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit"
  });
}

function dayLabel(value) {
  if (!value) {
    return "";
  }

  return new Date(value).toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short"
  });
}

function issueMatches(issue) {
  const labels = Array.isArray(issue.labels) ? issue.labels.map((item) => item.name) : [];
  return labels.includes(ISSUE_LABEL) || (issue.title || "").startsWith(TITLE_PREFIX);
}

function createFallbackStatus(issue, queueStateText) {
  return {
    id: `fallback-status-${issue.number}`,
    kind: "status",
    tone: queueStateText === "failed" ? "error" : "queued",
    text: queueStateText === "failed"
      ? "작업은 실패했지만 상세 요약이 아직 없습니다."
      : "Codex가 메시지를 확인 중",
    createdAt: issue.updated_at,
    issueNumber: issue.number
  };
}

function buildFallbackTranscript(issues, commentsByIssue) {
  const entries = [];

  issues.forEach((issue) => {
    const command = parseSection(issue.body, "Command");
    const target = parseSection(issue.body, "Target") || "other";

    entries.push({
      id: `fallback-user-${issue.number}`,
      kind: "message",
      role: "user",
      text: summarizeCommand(command, target),
      createdAt: issue.created_at,
      issueNumber: issue.number
    });

    const latestComment = commentsByIssue.get(issue.number);
    const executor = parseExecutorComment(latestComment?.body || "");
    if (executor) {
      entries.push({
        id: `fallback-assistant-${issue.number}`,
        kind: "message",
        role: "assistant",
        tone: executor.status === "success" ? "done" : "review",
        title: executor.title,
        text: executor.text,
        createdAt: executor.createdAt || latestComment.created_at || issue.updated_at,
        issueNumber: issue.number
      });
    } else {
      entries.push(createFallbackStatus(issue, issue.state === "closed" ? "done" : "queued"));
    }
  });

  return entries.sort((left, right) => {
    if (left.createdAt === right.createdAt) {
      return left.id.localeCompare(right.id);
    }
    return left.createdAt.localeCompare(right.createdAt);
  });
}

async function fetchLatestComments(issues) {
  const targets = issues.filter((issue) => Number(issue.comments || 0) > 0).slice(0, THREAD_LIMIT);
  const entries = await Promise.all(
    targets.map(async (issue) => {
      try {
        const response = await fetch(issue.comments_url, {
          headers: { Accept: "application/vnd.github+json" }
        });
        const comments = await response.json();
        return [issue.number, comments[comments.length - 1] || null];
      } catch {
        return [issue.number, null];
      }
    })
  );

  return new Map(entries);
}

function clearTimer(handle) {
  if (handle) {
    window.clearInterval(handle);
  }
  return null;
}

function relayPageBridgeAllowed() {
  return window.location.origin === "https://frysquirrel-a.github.io";
}

function formatRelayError(error, base) {
  const source = (base || "").replace(/^https?:\/\//, "");
  if (!error) {
    return source || "relay probe failed";
  }

  if (error.name === "AbortError") {
    return `${source}: relay status timeout`;
  }

  const message = String(error.message || error || "relay probe failed").trim();
  return source ? `${source}: ${message}` : message;
}

function buildRelayUrl(base, path, query = {}) {
  const url = new URL(`${base}${path}`);
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function requestRelayJsonViaPageBridge(path, options = {}) {
  return new Promise((resolve, reject) => {
    const requestId = `relay-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", handleMessage);
      reject(new Error("relay bridge timeout"));
    }, options.timeoutMs || RELAY_PAGE_TIMEOUT_MS);

    function handleMessage(event) {
      if (event.source !== window) {
        return;
      }

      const message = event.data;
      if (!message || message.source !== RELAY_PAGE_RESPONSE_SOURCE || message.type !== "relay-response") {
        return;
      }
      if (message.requestId !== requestId) {
        return;
      }

      window.clearTimeout(timeout);
      window.removeEventListener("message", handleMessage);

      const payload = message.payload || {};
      if (!payload.ok) {
        reject(new Error(payload.reason || `relay bridge HTTP ${payload.status || "error"}`));
        return;
      }

      resolve(payload.body || {});
    }

    window.addEventListener("message", handleMessage);
    window.postMessage({
      source: RELAY_PAGE_REQUEST_SOURCE,
      type: "relay-request",
      requestId,
      request: {
        method: options.method || "GET",
        path,
        query: options.query || {},
        body: options.body || {}
      }
    }, window.location.origin);
  });
}

async function requestRelayJsonDirect(base, path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || RELAY_STATUS_TIMEOUT_MS);

  try {
    const response = await fetch(buildRelayUrl(base, path, options.query || {}), {
      method: options.method || "GET",
      mode: "cors",
      cache: "no-store",
      credentials: "omit",
      headers: {
        Accept: "application/json",
        ...(options.method === "POST" ? { "Content-Type": "application/json" } : {})
      },
      body: options.method === "POST" ? JSON.stringify(options.body || {}) : undefined,
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }

    return response.json();
  } finally {
    window.clearTimeout(timeout);
  }
}

async function requestRelayJson(path, options = {}) {
  const errors = [];

  if (relayPageBridgeAllowed()) {
    try {
      const payload = await requestRelayJsonViaPageBridge(path, options);
      state.relayBase = "extension-bridge";
      state.relayBridgeReady = true;
      return payload;
    } catch (error) {
      errors.push(formatRelayError(error, "extension-bridge"));
    }
  }

  const bases = [];
  if (options.base && options.base !== "extension-bridge") {
    bases.push(options.base);
  }
  RELAY_BASES.forEach((base) => {
    if (!bases.includes(base)) {
      bases.push(base);
    }
  });

  for (const base of bases) {
    try {
      const payload = await requestRelayJsonDirect(base, path, options);
      state.relayBase = base;
      return payload;
    } catch (error) {
      errors.push(formatRelayError(error, base));
    }
  }

  throw new Error(errors.join(" | ") || "relay request failed");
}

async function discoverRelay(options = {}) {
  if (state.relayProbePromise) {
    return state.relayProbePromise;
  }

  const attempts = Math.max(Number(options.attempts || RELAY_STATUS_RETRIES), 1);
  state.relayProbePromise = (async () => {
    let lastError = "";

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      for (const base of RELAY_BASES) {
        try {
          const payload = await requestRelayJson("/status", { base });
          if (payload?.ok) {
            state.relayConnected = true;
            state.relayError = "";
            return true;
          }
          lastError = `${base.replace(/^https?:\/\//, "")}: invalid status payload`;
        } catch (error) {
          lastError = formatRelayError(error, base);
        }
      }

      if (attempt < attempts - 1) {
        await sleep(RELAY_RETRY_DELAY_MS);
      }
    }

    state.relayBase = null;
    state.relayConnected = false;
    state.relayError = lastError || "relay probe failed";
    return false;
  })();

  try {
    return await state.relayProbePromise;
  } finally {
    state.relayProbePromise = null;
  }
}

function ensureRelayPolling() {
  state.fallbackHandle = clearTimer(state.fallbackHandle);
  if (!state.pollHandle) {
    state.pollHandle = window.setInterval(loadRelaySession, RELAY_POLL_MS);
  }
}

function ensureFallbackPolling() {
  if (state.fallbackHandle) {
    return;
  }

  state.pollHandle = clearTimer(state.pollHandle);
  state.fallbackHandle = window.setInterval(async () => {
    const relayReady = await discoverRelay();
    if (relayReady) {
      await recoverRelay();
      return;
    }
    await loadFallbackTranscript();
  }, FALLBACK_POLL_MS);
}

async function loadRelaySession() {
  if (!state.relayBase || state.loading) {
    return;
  }

  state.loading = true;
  try {
    const payload = await requestRelayJson("/api/session", {
      query: {
        sessionId: state.sessionId
      }
    });
    state.relayEntries = Array.isArray(payload.entries) ? payload.entries : [];
    state.relayConnected = true;
    renderThread();
    setConnectionState("live");
  } catch (error) {
    state.relayConnected = false;
    state.relayError = formatRelayError(error, state.relayBase || RELAY_BASES[0]);
    setConnectionState("fallback");
    await loadFallbackTranscript();
    ensureFallbackPolling();
  } finally {
    state.loading = false;
  }
}

async function recoverRelay() {
  const relayReady = await discoverRelay();
  if (!relayReady) {
    return false;
  }

  setConnectionState("live");
  await loadRelaySession();
  ensureRelayPolling();
  return true;
}

async function loadFallbackTranscript() {
  try {
    const response = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/issues?state=all&sort=updated&direction=desc&per_page=${THREAD_LIMIT}`,
      {
        headers: { Accept: "application/vnd.github+json" }
      }
    );
    const issues = await response.json();
    const filtered = Array.isArray(issues) ? issues.filter(issueMatches).slice(0, THREAD_LIMIT).reverse() : [];
    const commentsByIssue = await fetchLatestComments(filtered);
    state.fallbackEntries = buildFallbackTranscript(filtered, commentsByIssue);
  } catch {
    state.fallbackEntries = [];
  }

  renderThread();
}

function setConnectionState(mode) {
  const chip = document.getElementById("connection-chip");
  const copy = document.getElementById("connection-copy");
  const hint = document.getElementById("composer-hint");
  const sendButton = document.getElementById("send-button");
  const detail = state.relayError ? ` 최근 오류: ${state.relayError}` : "";

  chip.className = "connection-chip";

  if (mode === "live") {
    chip.classList.add("is-live");
    chip.textContent = "실시간 연결";
    copy.textContent = "localhost relay가 연결되어 이 채팅방에서 바로 Codex에게 전달됩니다.";
    hint.textContent = "여기서 바로 명령을 보내면 상태와 결과가 이 대화방으로 돌아옵니다.";
    sendButton.disabled = false;
    return;
  }

  if (mode === "sending") {
    chip.classList.add("is-working");
    chip.textContent = "전송 중";
    copy.textContent = "메시지를 로컬 relay로 전달하는 중입니다.";
    hint.textContent = "응답이 돌아올 때까지 잠시 기다려 주세요.";
    sendButton.disabled = true;
    return;
  }

  chip.classList.add("is-fallback");
  chip.textContent = "재연결 필요";
  copy.textContent = `아직 localhost relay를 확인하지 못해 공개 GitHub 로그를 읽는 상태입니다.${detail} 같은 PC에서는 http://127.0.0.1:8767/ 로 열면 바로 연결됩니다.`;
  hint.textContent = "실시간 채팅은 이 PC에서 http://127.0.0.1:8767/ 를 열면 바로 사용할 수 있습니다.";
  sendButton.disabled = false;
}

function renderEntry(entry) {
  if (entry.kind === "status") {
    return `
      <div class="status-lane">
        <div class="status-chip tone-${escapeHtml(entry.tone || "queued")}">
          <span class="status-dot"></span>
          <span>${escapeHtml(entry.text)}</span>
        </div>
      </div>
    `;
  }

  const isUser = entry.role === "user";
  const tone = entry.tone || "done";
  const meta = timeLabel(entry.createdAt);
  const title = entry.title ? `<p class="message-title">${escapeHtml(entry.title)}</p>` : "";

  return `
    <article class="msg-row ${isUser ? "is-user" : "is-assistant"}">
      <div class="msg-avatar ${isUser ? "avatar-user" : "avatar-assistant"}">${isUser ? "나" : "CX"}</div>
      <div class="msg-stack">
        <div class="msg-bubble ${isUser ? "bubble-user" : `bubble-assistant tone-${escapeHtml(tone)}`}">
          ${title}
          <p class="msg-text">${escapeHtml(entry.text).replace(/\n/g, "<br>")}</p>
        </div>
        <p class="msg-meta">${escapeHtml(meta)}</p>
      </div>
    </article>
  `;
}

function renderThread() {
  const thread = document.getElementById("room-thread");
  const entries = state.relayConnected ? state.relayEntries : state.fallbackEntries;

  if (!entries.length) {
    thread.innerHTML = `
      <div class="welcome-card">
        <p class="welcome-kicker">${state.relayConnected ? "Live Chat" : "Read Only"}</p>
        <strong>${state.relayConnected ? "여기서 바로 Codex에게 말하면 됩니다." : "relay 연결을 다시 확인하는 중입니다."}</strong>
        <p>${state.relayConnected
          ? "아래 입력창에 작업을 채팅처럼 보내면 상태와 결과를 같은 방에서 받습니다."
          : "같은 PC의 localhost relay가 확인되면 이 페이지가 실시간 채팅방으로 전환됩니다."}</p>
      </div>
    `;
    return;
  }

  let previousDay = "";
  const parts = [];

  if (!state.relayConnected) {
    parts.push(`
      <div class="status-lane">
        <div class="status-chip tone-review">
          <span class="status-dot"></span>
          <span>실시간 채팅은 http://127.0.0.1:8767/ 에서 바로 사용할 수 있습니다.</span>
        </div>
      </div>
    `);
  }

  entries.forEach((entry) => {
    const currentDay = dayLabel(entry.createdAt);
    if (currentDay && currentDay !== previousDay) {
      parts.push(`<div class="day-divider"><span>${escapeHtml(currentDay)}</span></div>`);
      previousDay = currentDay;
    }
    parts.push(renderEntry(entry));
  });

  thread.innerHTML = parts.join("");
  thread.scrollTop = thread.scrollHeight;
}

function selectChip(containerId, attributeName, selectedValue) {
  document.querySelectorAll(`#${containerId} .option-chip`).forEach((button) => {
    button.classList.toggle("is-active", button.dataset[attributeName] === selectedValue);
  });
}

function autoResizeTextarea() {
  const textarea = document.getElementById("message");
  textarea.style.height = "0px";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function toggleTools(forceOpen) {
  state.toolsOpen = typeof forceOpen === "boolean" ? forceOpen : !state.toolsOpen;
  document.getElementById("composer-tools").classList.toggle("is-collapsed", !state.toolsOpen);
  document.getElementById("toggle-tools").classList.toggle("is-open", state.toolsOpen);
}

async function sendMessage(event) {
  event.preventDefault();

  const message = document.getElementById("message").value.trim();
  const command = document.getElementById("command-json").value.trim();
  if (!message && !command) {
    return;
  }

  if (!state.relayConnected || !state.relayBase) {
    const recovered = await recoverRelay();
    if (!recovered || !state.relayConnected || !state.relayBase) {
      setConnectionState("fallback");
      renderThread();
      return;
    }
  }

  state.sending = true;
  setConnectionState("sending");

  try {
    await requestRelayJson("/api/message", {
      method: "POST",
      body: {
        sessionId: state.sessionId,
        text: message,
        command,
        target: state.selectedTarget,
        priority: state.selectedPriority
      },
      timeoutMs: 5000
    });

    document.getElementById("message").value = "";
    document.getElementById("command-json").value = "";
    autoResizeTextarea();
    toggleTools(false);
    await loadRelaySession();
  } catch (error) {
    state.relayConnected = false;
    state.relayError = formatRelayError(error, state.relayBase || RELAY_BASES[0]);
    await loadFallbackTranscript();
    ensureFallbackPolling();
  } finally {
    state.sending = false;
    setConnectionState(state.relayConnected ? "live" : "fallback");
  }
}

function installRelayWakeHooks() {
  const tryWakeRelay = async () => {
    if (!state.relayConnected && !state.sending) {
      await recoverRelay();
    }
  };

  window.addEventListener("focus", tryWakeRelay);
  window.addEventListener("message", (event) => {
    if (event.source !== window) {
      return;
    }

    const message = event.data;
    if (!message || message.source !== RELAY_PAGE_RESPONSE_SOURCE || message.type !== "relay-ready") {
      return;
    }

    state.relayBridgeReady = true;
  });
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible") {
      await tryWakeRelay();
    }
  });
  document.getElementById("message").addEventListener("focus", tryWakeRelay);
}

async function bootstrap() {
  document.getElementById("chat-form").addEventListener("submit", sendMessage);
  document.getElementById("message").addEventListener("input", autoResizeTextarea);
  document.getElementById("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("chat-form").requestSubmit();
    }
  });

  document.getElementById("toggle-tools").addEventListener("click", () => {
    toggleTools();
  });

  document.getElementById("new-session").addEventListener("click", async () => {
    resetSessionId();
    state.relayEntries = [];
    state.fallbackEntries = [];
    renderThread();
    if (state.relayConnected) {
      await loadRelaySession();
    }
  });

  document.getElementById("target-chips").addEventListener("click", (event) => {
    const chip = event.target.closest(".option-chip");
    if (!chip) {
      return;
    }
    state.selectedTarget = chip.dataset.target || "other";
    selectChip("target-chips", "target", state.selectedTarget);
  });

  document.getElementById("priority-chips").addEventListener("click", (event) => {
    const chip = event.target.closest(".option-chip");
    if (!chip) {
      return;
    }
    state.selectedPriority = chip.dataset.priority || "normal";
    selectChip("priority-chips", "priority", state.selectedPriority);
  });

  autoResizeTextarea();
  installRelayWakeHooks();

  const relayReady = await recoverRelay();
  if (relayReady) {
    return;
  }

  setConnectionState("fallback");
  await loadFallbackTranscript();
  ensureFallbackPolling();
}

bootstrap();
