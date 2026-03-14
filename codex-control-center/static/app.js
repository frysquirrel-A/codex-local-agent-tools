const byId = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "codex-command-center-theme";

const state = {
  snapshot: null,
  optimisticMessages: [],
  recording: false,
  toasts: [],
  lastRenderedMessageId: "",
  isRefreshing: false,
  refreshTimer: null,
  activeTab: "home",
  theme: "light",
  auth: {
    authenticated: false,
    setupRequired: false,
    codeOnly: true,
    codeLabel: "접속 코드",
    csrfToken: "",
    sessionExpiresAt: "",
  },
};

const elements = {
  generatedAt: byId("generatedAt"),
  sessionExpiresAt: byId("sessionExpiresAt"),
  themeToggle: byId("themeToggle"),
  heroMetrics: byId("heroMetrics"),
  globalBanner: byId("globalBanner"),
  chatLog: byId("chatLog"),
  composerForm: byId("composerForm"),
  promptInput: byId("promptInput"),
  sendButton: byId("sendButton"),
  micButton: byId("micButton"),
  toastHost: byId("toastHost"),
  overviewCards: byId("overviewCards"),
  homeAlerts: byId("homeAlerts"),
  homeFlows: byId("homeFlows"),
  homeThreads: byId("homeThreads"),
  conversationStatusCards: byId("conversationStatusCards"),
  statusCards: byId("statusCards"),
  statusDetails: byId("statusDetails"),
  alerts: byId("alerts"),
  messageFlows: byId("messageFlows"),
  threadGrid: byId("threadGrid"),
  paths: byId("paths"),
  pathCards: byId("pathCards"),
  messageTemplate: byId("messageTemplate"),
  overviewCardTemplate: byId("overviewCardTemplate"),
  alertTemplate: byId("alertTemplate"),
  flowTemplate: byId("flowTemplate"),
  threadTemplate: byId("threadTemplate"),
  detailTemplate: byId("detailTemplate"),
  toastTemplate: byId("toastTemplate"),
  authGate: byId("authGate"),
  authTitle: byId("authTitle"),
  authDescription: byId("authDescription"),
  authHint: byId("authHint"),
  authForm: byId("authForm"),
  authSubmit: byId("authSubmit"),
  authMode: byId("authMode"),
  codeInput: byId("codeInput"),
  logoutButton: byId("logoutButton"),
};

const tabButtons = Array.from(document.querySelectorAll("[data-tab-target]"));
const tabPanels = Array.from(document.querySelectorAll("[data-tab-panel]"));
const jumpButtons = Array.from(document.querySelectorAll("[data-jump-tab]"));

function formatTimestamp(value, options = {}) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...options,
  }).format(date);
}

function autosizeTextarea() {
  elements.promptInput.style.height = "auto";
  elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 160)}px`;
}

function makeMetricChip(label, value) {
  const node = document.createElement("div");
  node.className = "metric-chip";
  node.innerHTML = `<span class="status-label">${label}</span><strong>${value}</strong>`;
  return node;
}

function showToast(title, detail = "", timeoutMs = 4200) {
  const id = `toast-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
  state.toasts.push({ id, title, detail });
  renderToasts();
  window.setTimeout(() => dismissToast(id), timeoutMs);
}

function dismissToast(id) {
  state.toasts = state.toasts.filter((toast) => toast.id !== id);
  renderToasts();
}

function renderToasts() {
  elements.toastHost.innerHTML = "";
  for (const toast of state.toasts.slice(-3)) {
    const node = elements.toastTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".toast-title").textContent = toast.title;
    node.querySelector(".toast-detail").textContent = toast.detail;
    node.querySelector(".toast-close").addEventListener("click", () => dismissToast(toast.id));
    elements.toastHost.appendChild(node);
  }
}

function smoothScrollToBottom(force = false) {
  const shouldFollow =
    force ||
    elements.chatLog.scrollHeight - elements.chatLog.scrollTop - elements.chatLog.clientHeight < 160;
  if (!shouldFollow) return;
  window.requestAnimationFrame(() => {
    elements.chatLog.scrollTo({
      top: elements.chatLog.scrollHeight,
      behavior: "smooth",
    });
  });
}

function stopRefreshLoop() {
  if (state.refreshTimer) {
    window.clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

function startRefreshLoop() {
  if (state.refreshTimer) return;
  state.refreshTimer = window.setInterval(refreshSnapshot, 5000);
}

function readTabFromLocation() {
  const raw = window.location.hash.replace(/^#/, "").trim();
  const known = new Set(["home", "conversation", "status", "flows", "threads"]);
  return known.has(raw) ? raw : "home";
}

function readPreferredTheme() {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") {
      return saved;
    }
  } catch {
    // Ignore localStorage access issues and fall back to system preference.
  }

  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme, { persist = true } = {}) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = state.theme;

  if (elements.themeToggle) {
    const pressed = state.theme === "dark";
    elements.themeToggle.setAttribute("aria-pressed", pressed ? "true" : "false");
    const stateNode = elements.themeToggle.querySelector(".theme-toggle-state");
    if (stateNode) {
      stateNode.textContent = pressed ? "On" : "Off";
    }
  }

  if (!persist) return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  } catch {
    // Ignore localStorage access issues.
  }
}

function toggleTheme() {
  const next = state.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  showToast(
    next === "dark" ? "?쇨컙 紐⑤뱶 耳쒖쭅" : "?쇨컙 紐⑤뱶 醫낅즺",
    next === "dark" ? "?댁두 ?쇱긽 ?뚯뒪濡?諛붽퓭 ?쒖빞 ?덊뵾濡쒕? ?쟾?섑했습니다." : "?묒? ?뚯뒪濡?蹂듭썝?섏뿬 ?쇰갑 ?댁쁺 ?붾뱶濡??뚮┰?덈떎.",
    2200,
  );
}

function setActiveTab(tabName, { updateHistory = true } = {}) {
  state.activeTab = tabName;
  for (const button of tabButtons) {
    button.classList.toggle("active", button.dataset.tabTarget === tabName);
  }
  for (const panel of tabPanels) {
    const active = panel.dataset.tabPanel === tabName;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  }
  if (updateHistory && window.location.hash !== `#${tabName}`) {
    window.history.replaceState(null, "", `#${tabName}`);
  }
}

function resetAuthState() {
  state.auth = {
    authenticated: false,
    setupRequired: false,
    codeOnly: true,
    codeLabel: "접속 코드",
    csrfToken: "",
    sessionExpiresAt: "",
  };
}

function renderAuthGate() {
  const auth = state.auth;
  const authenticated = Boolean(auth.authenticated);
  document.body.classList.toggle("auth-locked", !authenticated);
  elements.authGate.hidden = authenticated;
  elements.logoutButton.hidden = !authenticated;
  elements.promptInput.disabled = !authenticated;
  elements.sendButton.disabled = !authenticated;
  elements.micButton.disabled = !authenticated;
  elements.sessionExpiresAt.textContent = authenticated
    ? formatTimestamp(auth.sessionExpiresAt)
    : "-";

  if (authenticated) {
    elements.authMode.textContent = "Protected";
    elements.codeInput.value = "";
    return;
  }

  elements.authMode.textContent = "Code Only";
  elements.authTitle.textContent = "접속 코드로 로그인";
  elements.authDescription.textContent =
    "지금부터는 비밀번호 없이 접속 코드 하나로 로그인합니다. 세션 쿠키, CSRF 보호, 로그인 시도 제한은 그대로 유지됩니다.";
  elements.authHint.textContent =
    "데스크톱에서 발급된 접속 코드를 입력해 주세요. 로그인 후에는 탭 기반 Command Center를 사용할 수 있습니다.";
  elements.authSubmit.textContent = "들어가기";
}

async function fetchJson(url, options = {}, { includeCsrf = false } = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (includeCsrf && state.auth.csrfToken) {
    headers.set("X-CSRF-Token", state.auth.csrfToken);
  }
  const response = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
    credentials: "same-origin",
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (response.status === 401) {
    resetAuthState();
    stopRefreshLoop();
    renderAuthGate();
    throw new Error(payload.detail || payload.error || "로그인이 필요합니다.");
  }

  if (!response.ok || payload.ok === false) {
    throw new Error(payload.detail || payload.error || `request failed: ${response.status}`);
  }

  return payload;
}

async function syncAuthState() {
  const authState = await fetchJson("/api/auth/state");
  state.auth = {
    authenticated: Boolean(authState.authenticated),
    setupRequired: Boolean(authState.setupRequired),
    codeOnly: authState.codeOnly !== false,
    codeLabel: authState.codeLabel || "접속 코드",
    csrfToken: authState.csrfToken || "",
    sessionExpiresAt: authState.sessionExpiresAt || "",
  };
  renderAuthGate();
  if (state.auth.authenticated) {
    startRefreshLoop();
  } else {
    stopRefreshLoop();
  }
}

function mergeConversation() {
  const snapshotConversation = Array.isArray(state.snapshot?.conversation)
    ? state.snapshot.conversation
    : [];
  const merged = [...snapshotConversation];
  const known = new Set(snapshotConversation.map((item) => item.id));

  for (const optimistic of state.optimisticMessages) {
    if (!known.has(optimistic.id)) {
      merged.push(optimistic);
    }
  }

  merged.sort((a, b) => {
    const at = new Date(a.createdAt || 0).getTime();
    const bt = new Date(b.createdAt || 0).getTime();
    if (at !== bt) return at - bt;
    return String(a.id || "").localeCompare(String(b.id || ""));
  });

  return merged;
}

function normalizeMessageKind(message) {
  if (message.role === "system") return "system";
  if (message.kind === "warning") return "warning";
  return message.role || "assistant";
}

function renderConversation() {
  const conversation = mergeConversation();
  const lastMessageId = conversation.length ? conversation[conversation.length - 1].id : "";
  const shouldScroll = state.lastRenderedMessageId !== lastMessageId;

  elements.chatLog.innerHTML = "";

  if (!conversation.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "아직 대화가 없습니다. 대화 탭에서 명령을 보내면 서브 에이전트에 비동기로 전달됩니다.";
    elements.chatLog.appendChild(empty);
    state.lastRenderedMessageId = "";
    return;
  }

  for (const message of conversation) {
    const node = elements.messageTemplate.content.firstElementChild.cloneNode(true);
    const kind = normalizeMessageKind(message);
    node.classList.add(kind);
    node.querySelector(".message-kind").textContent = message.kind || message.role || "status";
    node.querySelector(".message-time").textContent = formatTimestamp(message.createdAt);
    node.querySelector(".bubble").textContent = message.text || "";
    elements.chatLog.appendChild(node);
  }

  state.lastRenderedMessageId = lastMessageId;
  smoothScrollToBottom(shouldScroll);
}

function getOverviewEntries(snapshot) {
  const overview = snapshot?.overview || {};
  return [
    {
      label: "Watchdog",
      value: overview.watchdog?.status || "-",
      detail: `task=${overview.watchdog?.taskId || "-"} / decision=${overview.watchdog?.decision || "-"}`,
    },
    {
      label: "Queue",
      value: overview.watchdog?.queueEmpty ? "비어 있음" : "작업 있음",
      detail: `queueDecision=${overview.watchdog?.queueDecision || "-"}`,
    },
    {
      label: "Helpers",
      value: `${overview.helpers?.pendingAssignmentCount ?? 0} pending`,
      detail: `stale=${overview.helpers?.staleAssignmentCount ?? 0}, handoff=${overview.helpers?.handoffCount ?? 0}`,
    },
    {
      label: "Scheduler",
      value: `${overview.scheduler?.openJobCount ?? 0} open`,
      detail: `jobCount=${overview.scheduler?.jobCount ?? 0}`,
    },
    {
      label: "Gmail",
      value: overview.gmail?.running ? "running" : "idle",
      detail: overview.gmail?.skipReason || overview.gmail?.updatedAt || "-",
    },
    {
      label: "Async",
      value: overview.asyncRuntime?.running ? "ready" : "offline",
      detail: `popup=${overview.asyncRuntime?.notifiedCount ?? 0}, updatedAt=${overview.asyncRuntime?.updatedAt || "-"}`,
    },
  ];
}

function renderOverviewCards(target, cards) {
  target.innerHTML = "";
  for (const card of cards) {
    const node = elements.overviewCardTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".overview-label").textContent = card.label;
    node.querySelector(".overview-value").textContent = card.value;
    node.querySelector(".overview-detail").textContent = card.detail;
    target.appendChild(node);
  }
}

function renderAlerts(target, alerts, limit = alerts.length) {
  target.innerHTML = "";
  const items = Array.isArray(alerts) ? alerts.slice(0, limit) : [];
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "즉시 조치가 필요한 경고는 없습니다.";
    target.appendChild(empty);
    return;
  }
  for (const alert of items) {
    const node = elements.alertTemplate.content.firstElementChild.cloneNode(true);
    node.classList.add(alert.level || "info");
    node.querySelector(".alert-title").textContent = alert.title || "알림";
    node.querySelector(".alert-detail").textContent = alert.detail || "-";
    target.appendChild(node);
  }
}

function renderFlows(target, flows, limit = flows.length) {
  target.innerHTML = "";
  const items = Array.isArray(flows) ? flows.slice(0, limit) : [];
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "표시할 최근 handoff가 없습니다.";
    target.appendChild(empty);
    return;
  }

  for (const flow of items) {
    const node = elements.flowTemplate.content.firstElementChild.cloneNode(true);
    const latestAssignment = Array.isArray(flow.assignments) && flow.assignments.length
      ? flow.assignments[flow.assignments.length - 1]
      : null;
    node.querySelector(".flow-id").textContent = flow.handoffId || flow.id || "-";
    node.querySelector(".flow-title").textContent = flow.sourceTitle || flow.title || "최근 handoff";
    node.querySelector(".flow-route").textContent = flow.routeLabel || flow.route || "route";
    node.querySelector(".flow-task").textContent =
      latestAssignment?.requestPreview || flow.taskText || flow.sourceNotes || "-";
    node.querySelector(".flow-response").textContent =
      latestAssignment?.responsePreview || latestAssignment?.requestPreview || flow.path || "-";
    target.appendChild(node);
  }
}

function makeStatItem(key, value) {
  const wrapper = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = key;
  dd.textContent = value;
  wrapper.appendChild(dt);
  wrapper.appendChild(dd);
  return wrapper;
}

function renderThreads(target, threads, limit = threads.length) {
  target.innerHTML = "";
  const items = Array.isArray(threads) ? threads.slice(0, limit) : [];
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "표시할 스레드가 없습니다.";
    target.appendChild(empty);
    return;
  }

  for (const thread of items) {
    const node = elements.threadTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".thread-kind").textContent = thread.kind || "-";
    node.querySelector(".thread-title").textContent = thread.displayName || thread.title || "-";
    node.querySelector(".thread-role").textContent = thread.role || thread.responsibility || "-";
    const stats = node.querySelector(".thread-stats");
    stats.appendChild(makeStatItem("state", thread.state || "-"));
    stats.appendChild(makeStatItem("updated", formatTimestamp(thread.updatedAt)));
    stats.appendChild(makeStatItem("threadId", thread.threadId || thread.id || "-"));
    stats.appendChild(makeStatItem("route", thread.routeLabel || thread.route || "-"));
    target.appendChild(node);
  }
}

function renderDetailCards(target, groups) {
  target.innerHTML = "";
  for (const group of groups) {
    const node = elements.detailTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".detail-label").textContent = group.label;
    node.querySelector(".detail-title").textContent = group.title;
    const list = node.querySelector(".detail-list");
    for (const [key, value] of Object.entries(group.items || {})) {
      list.appendChild(makeStatItem(key, String(value ?? "-")));
    }
    target.appendChild(node);
  }
}

function renderPaths(snapshot) {
  const paths = snapshot?.paths || {};
  elements.paths.innerHTML = "";
  for (const [label, path] of Object.entries(paths)) {
    const li = document.createElement("li");
    li.textContent = `${label}: ${path}`;
    elements.paths.appendChild(li);
  }

  const groups = Object.entries(paths).map(([label, path]) => ({
    label: "Path",
    title: label,
    items: {
      location: path,
    },
  }));
  renderDetailCards(elements.pathCards, groups);
}

function renderHeroMetrics(snapshot) {
  elements.heroMetrics.innerHTML = "";
  const overview = snapshot?.overview || {};
  const metrics = [
    { label: "watchdog", value: overview.watchdog?.status || "idle" },
    { label: "helpers", value: `${overview.helpers?.pendingAssignmentCount ?? 0} pending` },
    { label: "gmail", value: overview.gmail?.running ? "running" : "idle" },
    { label: "async", value: overview.asyncRuntime?.running ? "ready" : "offline" },
  ];
  for (const metric of metrics) {
    elements.heroMetrics.appendChild(makeMetricChip(metric.label, metric.value));
  }
}

function renderGlobalBanner(snapshot) {
  const alerts = Array.isArray(snapshot?.alerts) ? snapshot.alerts : [];
  const primary = alerts.find((item) => item.level === "error") || alerts.find((item) => item.level === "warn") || alerts[0];
  if (!primary) {
    elements.globalBanner.hidden = true;
    elements.globalBanner.textContent = "";
    elements.globalBanner.className = "global-banner";
    return;
  }
  elements.globalBanner.hidden = false;
  elements.globalBanner.className = `global-banner ${primary.level || "info"}`;
  elements.globalBanner.textContent = `${primary.title || "알림"} - ${primary.detail || ""}`;
}

function renderStatusDetails(snapshot) {
  const overview = snapshot?.overview || {};
  const groups = [
    {
      label: "Runtime",
      title: "Watchdog",
      items: {
        status: overview.watchdog?.status || "-",
        taskId: overview.watchdog?.taskId || "-",
        decision: overview.watchdog?.decision || "-",
        queueEmpty: String(Boolean(overview.watchdog?.queueEmpty)),
        queueDecision: overview.watchdog?.queueDecision || "-",
      },
    },
    {
      label: "Helpers",
      title: "Helper Queue",
      items: {
        pending: overview.helpers?.pendingAssignmentCount ?? 0,
        stale: overview.helpers?.staleAssignmentCount ?? 0,
        handoffs: overview.helpers?.handoffCount ?? 0,
        updatedAt: overview.helpers?.updatedAt || "-",
      },
    },
    {
      label: "Dispatch",
      title: "Scheduler",
      items: {
        openJobs: overview.scheduler?.openJobCount ?? 0,
        jobs: overview.scheduler?.jobCount ?? 0,
        updatedAt: overview.scheduler?.updatedAt || "-",
      },
    },
    {
      label: "Channel",
      title: "Gmail",
      items: {
        running: overview.gmail?.running ? "true" : "false",
        skipReason: overview.gmail?.skipReason || "-",
        updatedAt: overview.gmail?.updatedAt || "-",
      },
    },
    {
      label: "Async",
      title: "Popup & Reports",
      items: {
        running: overview.asyncRuntime?.running ? "true" : "false",
        notifiedCount: overview.asyncRuntime?.notifiedCount ?? 0,
        updatedAt: overview.asyncRuntime?.updatedAt || "-",
      },
    },
    {
      label: "PTT",
      title: "Microphone Trigger",
      items: {
        recording: snapshot?.ptt?.recording ? "true" : "false",
        updatedAt: snapshot?.ptt?.updatedAt || "-",
        source: snapshot?.ptt?.source || "-",
      },
    },
  ];
  renderDetailCards(elements.statusDetails, groups);
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  state.recording = Boolean(snapshot.ptt?.recording);
  elements.generatedAt.textContent = formatTimestamp(snapshot.generatedAt);
  elements.sessionExpiresAt.textContent = state.auth.authenticated
    ? formatTimestamp(state.auth.sessionExpiresAt)
    : "-";
  elements.micButton.classList.toggle("recording", state.recording);
  elements.micButton.setAttribute("aria-pressed", state.recording ? "true" : "false");

  const overviewCards = getOverviewEntries(snapshot);
  renderGlobalBanner(snapshot);
  renderHeroMetrics(snapshot);
  renderConversation();
  renderOverviewCards(elements.overviewCards, overviewCards);
  renderOverviewCards(elements.conversationStatusCards, overviewCards.slice(0, 4));
  renderOverviewCards(elements.statusCards, overviewCards);
  renderAlerts(elements.homeAlerts, snapshot.alerts || [], 3);
  renderAlerts(elements.alerts, snapshot.alerts || []);
  renderFlows(elements.homeFlows, snapshot.messageFlows || [], 3);
  renderFlows(elements.messageFlows, snapshot.messageFlows || []);
  renderThreads(elements.homeThreads, snapshot.threads || [], 4);
  renderThreads(elements.threadGrid, snapshot.threads || []);
  renderStatusDetails(snapshot);
  renderPaths(snapshot);
}

async function loadSnapshot() {
  return fetchJson("/api/snapshot");
}

async function refreshSnapshot() {
  if (!state.auth.authenticated || state.isRefreshing) return;
  state.isRefreshing = true;
  try {
    const snapshot = await loadSnapshot();
    renderSnapshot(snapshot);
  } catch (error) {
    showToast("데이터를 불러오지 못했습니다", error.message);
  } finally {
    state.isRefreshing = false;
  }
}

function addOptimisticMessage(text) {
  const optimistic = {
    id: `local-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`,
    role: "user",
    kind: "command",
    text,
    createdAt: new Date().toISOString(),
    optimistic: true,
  };
  state.optimisticMessages.push(optimistic);
  renderConversation();
  return optimistic.id;
}

function removeOptimisticMessage(id) {
  state.optimisticMessages = state.optimisticMessages.filter((item) => item.id !== id);
}

async function submitCommand(event) {
  event.preventDefault();
  const text = elements.promptInput.value.trim();
  if (!text) {
    showToast("명령이 비어 있습니다", "보낼 내용을 입력해 주세요.");
    return;
  }

  const optimisticId = addOptimisticMessage(text);
  elements.promptInput.value = "";
  autosizeTextarea();
  setActiveTab("conversation");

  try {
    await fetchJson(
      "/api/commands",
      {
        method: "POST",
        body: JSON.stringify({ text }),
      },
      { includeCsrf: true },
    );
    removeOptimisticMessage(optimisticId);
    showToast("백그라운드 전달 완료", "서브 에이전트에 작업을 넘겼고, 결과가 준비되면 팝업으로 알려드립니다.");
    await refreshSnapshot();
  } catch (error) {
    removeOptimisticMessage(optimisticId);
    renderConversation();
    showToast("명령 전송 실패", error.message);
  }
}

async function togglePtt() {
  const nextRecording = !state.recording;
  elements.micButton.classList.toggle("recording", nextRecording);
  elements.micButton.setAttribute("aria-pressed", nextRecording ? "true" : "false");

  try {
    const payload = await fetchJson(
      "/api/ptt",
      {
        method: "POST",
        body: JSON.stringify({ recording: nextRecording }),
      },
      { includeCsrf: true },
    );
    state.recording = Boolean(payload.ptt?.recording);
    elements.micButton.classList.toggle("recording", state.recording);
    elements.micButton.setAttribute("aria-pressed", state.recording ? "true" : "false");
    showToast(
      state.recording ? "PTT 대기 시작" : "PTT 대기 종료",
      state.recording ? "지금은 녹음 트리거를 보내는 상태입니다." : "마이크 트리거를 끈 상태입니다.",
      2600,
    );
    await refreshSnapshot();
  } catch (error) {
    elements.micButton.classList.toggle("recording", state.recording);
    elements.micButton.setAttribute("aria-pressed", state.recording ? "true" : "false");
    showToast("PTT 상태 전환 실패", error.message);
  }
}

async function submitAuth(event) {
  event.preventDefault();
  const code = elements.codeInput.value.trim();
  if (!code) {
    showToast("접속 코드가 비어 있습니다", "데스크톱에서 받은 접속 코드를 입력해 주세요.");
    return;
  }

  try {
    const payload = await fetchJson("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    state.auth = {
      authenticated: Boolean(payload.auth?.authenticated),
      setupRequired: Boolean(payload.auth?.setupRequired),
      codeOnly: payload.auth?.codeOnly !== false,
      codeLabel: payload.auth?.codeLabel || "접속 코드",
      csrfToken: payload.auth?.csrfToken || "",
      sessionExpiresAt: payload.auth?.sessionExpiresAt || "",
    };
    renderAuthGate();
    startRefreshLoop();
    showToast("로그인 완료", "접속 코드로 Command Center에 들어왔습니다.");
    await refreshSnapshot();
  } catch (error) {
    showToast("인증 실패", error.message);
  }
}

async function logout() {
  try {
    await fetchJson("/api/auth/logout", { method: "POST" }, { includeCsrf: true });
  } catch {
    // Even if logout request fails, force local auth reset.
  }
  resetAuthState();
  stopRefreshLoop();
  renderAuthGate();
  showToast("로그아웃됨", "다시 접속 코드를 입력해야 합니다.");
}

for (const button of tabButtons) {
  button.addEventListener("click", () => setActiveTab(button.dataset.tabTarget));
}

for (const button of jumpButtons) {
  button.addEventListener("click", () => setActiveTab(button.dataset.jumpTab));
}

elements.promptInput.addEventListener("input", autosizeTextarea);
elements.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composerForm.requestSubmit();
  }
});
elements.themeToggle?.addEventListener("click", toggleTheme);
elements.composerForm.addEventListener("submit", submitCommand);
elements.micButton.addEventListener("click", togglePtt);
elements.authForm.addEventListener("submit", submitAuth);
elements.logoutButton.addEventListener("click", logout);

applyTheme(readPreferredTheme(), { persist: false });
autosizeTextarea();
renderAuthGate();
setActiveTab(readTabFromLocation(), { updateHistory: false });
window.addEventListener("hashchange", () => setActiveTab(readTabFromLocation(), { updateHistory: false }));
syncAuthState()
  .then(async () => {
    if (state.auth.authenticated) {
      await refreshSnapshot();
    }
  })
  .catch((error) => {
    showToast("인증 상태 확인 실패", error.message);
  });
