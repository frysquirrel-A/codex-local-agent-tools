const byId = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "codex-command-center-theme";
const DRAFT_STORAGE_KEY = "codex-command-center-draft";

const state = {
  snapshot: null,
  auth: {
    authenticated: false,
    requiresLogin: false,
    mode: "code-login",
    csrfToken: "",
    sessionExpiresAt: "",
    message: "",
    codeIssuedAt: "",
    deliveryPrimary: "",
    deliveryTarget: "",
    deliveryFallback: "",
  },
  theme: "light",
  uiVersion: "",
  toasts: [],
  selectedMemberTitle: "[비서] 보고자",
  selectedFlowId: "",
  queueFilter: "all",
  selectedTab: "board",
  focusedBoardPane: "",
  expandedMemberGroups: {
    secretary: true,
    manager: false,
    team1: false,
    team2: false,
    coop: false,
    external: false,
  },
  expandedOrgMemberTitle: "",
  refreshTimer: null,
  isRefreshing: false,
  recording: false,
  inputComposing: false,
  resourceHistory: {
    cpu: [],
    memory: [],
    gpu: [],
    quota: [],
  },
  lastRenderError: "",
};

const elements = {
  authGate: byId("authGate"),
  authForm: byId("authForm"),
  authSubmit: byId("authSubmit"),
  codeInput: byId("codeInput"),
  authHint: byId("authHint"),
  generatedAt: byId("generatedAt"),
  accessMode: byId("accessMode"),
  sessionExpiresAt: byId("sessionExpiresAt"),
  syncState: byId("syncState"),
  resourceUpdatedAt: byId("resourceUpdatedAt"),
  cpuValue: byId("cpuValue"),
  memoryValue: byId("memoryValue"),
  gpuValue: byId("gpuValue"),
  quotaValue: byId("quotaValue"),
  cpuChart: byId("cpuChart"),
  memoryChart: byId("memoryChart"),
  gpuChart: byId("gpuChart"),
  quotaChart: byId("quotaChart"),
  logoutButton: byId("logoutButton"),
  themeToggle: byId("themeToggle"),
  summaryCards: byId("summaryCards"),
  globalBanner: byId("globalBanner"),
  boardGrid: byId("boardGrid"),
  boardPaneMembers: byId("boardPaneMembers"),
  boardPaneQueue: byId("boardPaneQueue"),
  boardPaneConversation: byId("boardPaneConversation"),
  memberCount: byId("memberCount"),
  memberMode: byId("memberMode"),
  memberList: byId("memberList"),
  orgTree: byId("orgTree"),
  selectedMemberName: byId("selectedMemberName"),
  selectedMemberStatus: byId("selectedMemberStatus"),
  selectedMemberRole: byId("selectedMemberRole"),
  selectedMemberStats: byId("selectedMemberStats"),
  queueCount: byId("queueCount"),
  queueFilters: byId("queueFilters"),
  queueList: byId("queueList"),
  progressRoute: byId("progressRoute"),
  progressPanel: byId("progressPanel"),
  reportFocus: byId("reportFocus"),
  chatLog: byId("chatLog"),
  composerForm: byId("composerForm"),
  composerTargetTitle: byId("composerTargetTitle"),
  composerTargetMeta: byId("composerTargetMeta"),
  composerHint: byId("composerHint"),
  promptInput: byId("promptInput"),
  sendButton: byId("sendButton"),
  micButton: byId("micButton"),
  directiveHistory: byId("directiveHistory"),
  flowTimeline: byId("flowTimeline"),
  reportLibrary: byId("reportLibrary"),
  settingsPanel: byId("settingsPanel"),
  toastHost: byId("toastHost"),
  toastTemplate: byId("toastTemplate"),
  tabs: Array.from(document.querySelectorAll(".tab")),
  panels: Array.from(document.querySelectorAll(".tab-panel")),
  paneToggles: Array.from(document.querySelectorAll(".pane-head-toggle")),
};

function formatTimestamp(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function parseTimestamp(value) {
  if (!value) return 0;
  const date = new Date(value);
  const time = date.getTime();
  return Number.isFinite(time) ? time : 0;
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${numeric.toFixed(numeric >= 10 ? 0 : 1)}%`;
}

function formatMemoryMb(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  if (numeric >= 1024) return `${(numeric / 1024).toFixed(1)} GB`;
  return `${numeric.toFixed(0)} MB`;
}

function toneClassForLabel(value) {
  const text = String(value || "").toLowerCase();
  if (!text) return "tone-neutral";
  if (text.includes("running") || text.includes("active") || text.includes("in progress")) return "tone-running";
  if (text.includes("pending") || text.includes("waiting") || text.includes("hold")) return "tone-pending";
  if (text.includes("queued") || text.includes("route") || text.includes("handoff") || text.includes("received") || text.includes("chatgpt")) return "tone-queued";
  if (text.includes("complete") || text.includes("completed") || text.includes("closed") || text.includes("done")) return "tone-complete";
  return "tone-neutral";
}

function pillHtml(baseClass, label, value = "", preferredTone = "") {
  const tone = preferredTone || toneClassForLabel(label);
  const text = [label, value].filter(Boolean).join(" ");
  return `<span class="${baseClass} ${tone}">${text}</span>`;
}

function looksCorrupted(text) {
  const value = String(text || "");
  if (!value) return false;
  const questionCount = (value.match(/\?/g) || []).length;
  const replacementCharCount = value.includes("�") ? 1 : 0;
  return replacementCharCount > 0 || questionCount >= Math.max(4, Math.floor(value.length * 0.18));
}

function safeLabel(text, fallback = "원문 복구 필요") {
  const value = String(text || "").trim();
  if (!value) return fallback;
  return looksCorrupted(value) ? fallback : value;
}

function stripInternalRoutingPrefix(text) {
  const value = String(text || "");
  if (!value) return "";
  return value
    .replace(/^\s*\[대상:\s*.*?\[큐:[^\]]+\]\s*/u, "")
    .replace(/^\s*\[대상:\s*.*?\]\s*/u, "")
    .replace(/^\s*\[큐:\s*[^\]]+\]\s*/u, "")
    .replace(/^\s*\[[^\]]*->[^\]]*\]\s*/u, "")
    .trim();
}

function rewriteVisibleSystemText(text) {
  const value = String(text || "");
  if (!value) return "";
  return value
    .replace(
      "명령을 접수했습니다. [관리자] 사장이 먼저 검토한 뒤, 직접 처리 또는 팀 위임을 결정합니다.",
      "명령을 접수했습니다. [비서] 보고자가 먼저 정리하고 스킬 후보를 고른 뒤, [관리자] 사장이 직접 처리 또는 팀 위임을 결정합니다.",
    )
    .replace("[대표님 -> 관리자 접수]", "[대표님 -> 비서 접수]");
}

function extractRepresentativeDirective(text) {
  const value = rewriteVisibleSystemText(String(text || ""));
  if (!value) return "";
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const cleanedLines = [];
  for (const line of lines) {
    if (/^\[(대표님\s*->|비서 지침|관리자 지침|참고 큐|참고 대상)/u.test(line)) continue;
    const cleaned = stripInternalRoutingPrefix(
      line
        .replace(/^\s*대표님 지시[:：]\s*/u, "")
        .replace(/^\s*\[비서 보고\]\s*/u, "")
        .trim(),
    );
    if (!cleaned) continue;
    cleanedLines.push(cleaned);
  }
  if (cleanedLines.length) return cleanedLines[0];
  return stripInternalRoutingPrefix(value);
}

function showToast(title, detail = "", timeoutMs = 4200) {
  const id = `toast-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
  state.toasts.push({ id, title, detail });
  renderToasts();
  window.setTimeout(() => dismissToast(id), timeoutMs);
}

function recordClientError(error) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error || "unknown error");
  state.lastRenderError = message;
  if (elements.syncState) {
    elements.syncState.textContent = "재연결 필요";
    elements.syncState.className = "sync-stale";
  }
  showToast("상태 갱신 실패", message, 6000);
  try {
    console.error("[command-center]", message);
  } catch {
    // ignore
  }
  try {
    fetch("/api/client-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        source: "browser",
        href: window.location.href,
        userAgent: navigator.userAgent,
      }),
    }).catch(() => {});
  } catch {
    // ignore
  }
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

function readPreferredTheme() {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    // ignore
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme, { persist = true } = {}) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = state.theme;
  elements.themeToggle.setAttribute("aria-pressed", state.theme === "dark" ? "true" : "false");
  elements.themeToggle.textContent = state.theme === "dark" ? "주간 모드" : "야간 모드";
  if (!persist) return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  } catch {
    // ignore
  }
}

function saveDraft(value) {
  try {
    window.localStorage.setItem(DRAFT_STORAGE_KEY, value || "");
  } catch {
    // ignore
  }
}

function loadDraft() {
  try {
    return window.localStorage.getItem(DRAFT_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function autosizeTextarea() {
  elements.promptInput.style.height = "auto";
  elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 280)}px`;
}

async function fetchJson(url, options = {}, { includeCsrf = false } = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  if (includeCsrf && state.auth.csrfToken && state.auth.mode === "code-login") {
    headers.set("X-CSRF-Token", state.auth.csrfToken);
  }
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (response.status === 401) {
    state.auth.authenticated = false;
    state.auth.requiresLogin = true;
    state.auth.csrfToken = "";
    state.auth.sessionExpiresAt = "";
    stopRefreshLoop();
    renderAuthGate();
    throw new Error(payload.detail || "접속 코드 로그인이 필요합니다.");
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.detail || payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

function getThreads() {
  return Array.isArray(state.snapshot?.threads) ? state.snapshot.threads : [];
}

function groupKeyForThread(thread) {
  const name = String(thread?.displayName || thread?.title || "");
  if (name === "[비서] 보고자") return "secretary";
  if (name === "[관리자] 사장") return "manager";
  if (name.startsWith("[1팀]")) return "team1";
  if (name.startsWith("[2팀]")) return "team2";
  if (name.startsWith("[협력")) return "coop";
  return "external";
}

function expandGroupForMember(title) {
  const thread = getThreads().find((item) => (item.displayName || item.title) === title);
  if (!thread) return;
  state.expandedMemberGroups[groupKeyForThread(thread)] = true;
}

function getThreadStats(member) {
  const stats = member?.stats || {};
  return {
    queued: Number(stats.queued || 0),
    running: Number(stats.running || 0),
    pending: Number(stats.pending || 0),
    oldestPendingMinutes: Number(stats.oldestPendingMinutes || 0),
  };
}

function memberOperatingMode(member) {
  const title = member?.displayName || member?.title || "";
  if (title === "[관리자] 사장") return "오케스트레이터";
  if (title === "[비서] 보고자") return "비서 접수";
  if (title.includes("팀장")) return "팀 리드";
  if (title.startsWith("[협력")) return "전문 협력";
  if (member?.kind === "provider") return "외부 채널";
  return "실무 담당";
}

function memberRoleSummary(member) {
  const title = member?.displayName || member?.title || "";
  if (title === "[관리자] 사장") {
    return "비서가 올린 브리프를 기준으로 우선순위, 위임, 승인, 최종 확인을 맡는 오케스트레이터입니다.";
  }
  if (title === "[비서] 보고자") {
    return "대표님 지시 원문을 먼저 받고, 사장이 판단하기 좋게 요약과 스킬 후보를 정리하는 비서입니다.";
  }
  return String(member?.role || "").trim();
}

function buildMemberCard(thread, groupKey = "") {
  const title = thread.displayName || thread.title;
  const activity = getMemberActivity(thread);
  const node = document.createElement("button");
  node.type = "button";
  node.className = `member-card${title === state.selectedMemberTitle ? " active" : ""}`;
  node.innerHTML = `
    <div class="member-card-header">
      <div class="member-card-header-main">
        <div class="member-title-row">
          <span class="member-title">${title}</span>
          <span class="member-activity ${activity.tone}">${activity.label}</span>
        </div>
      </div>
      <span class="member-tag tone-neutral">${memberOperatingMode(thread)}</span>
    </div>
  `;
  node.addEventListener("click", () => {
    state.selectedMemberTitle = title;
    state.selectedFlowId = "";
    if (groupKey) {
      state.expandedMemberGroups[groupKey] = true;
    }
    renderWorkspace();
  });
  return node;
}

function memberFlowCounts(member) {
  return memberQueueItems(member).reduce(
    (acc, flow) => {
      const stateName = flowStateForMember(flow, member);
      acc.all += 1;
      if (stateName === "active") acc.active += 1;
      else if (stateName === "waiting") acc.waiting += 1;
      else acc.closed += 1;
      return acc;
    },
    { all: 0, active: 0, waiting: 0, closed: 0 },
  );
}

function memberRunningCount(member, counts = memberFlowCounts(member)) {
  const stats = getThreadStats(member);
  return Math.max(counts.active, stats.running);
}

function memberWaitingCount(member, counts = memberFlowCounts(member)) {
  const stats = getThreadStats(member);
  return Math.max(counts.waiting, stats.pending + stats.queued);
}

function memberRecentFlows(member, limit = 2) {
  return memberQueueItems(member).slice(0, limit);
}

function buildOrgTreeMember(thread, { primary = false } = {}) {
  const title = safeLabel(thread.displayName || thread.title, "이름 복구 필요");
  const activity = getMemberActivity(thread);
  const counts = memberFlowCounts(thread);
  const stats = getThreadStats(thread);
  const runningCount = memberRunningCount(thread, counts);
  const waitingCount = memberWaitingCount(thread, counts);
  const isExpanded = state.expandedOrgMemberTitle === title;
  const isSelected = state.selectedMemberTitle === title;
  const recentFlows = memberRecentFlows(thread, 2);
  const pendingOutsideBoard = Math.max(0, waitingCount - counts.waiting);
  const detailBody = recentFlows.length
    ? `
      <div class="tree-member-detail-list">
        ${recentFlows
          .map((flow) => {
            const flowState = flowStateForMember(flow, thread);
            const tone = flowState === "active" ? "tone-running" : flowState === "waiting" ? "tone-pending" : "tone-complete";
            const label = flowState === "active" ? "진행중" : flowState === "waiting" ? "대기중" : "완료";
            return `
              <article class="tree-member-detail-item">
                <div class="tree-member-detail-meta">
                  ${pillHtml("queue-chip", flow.topicTitle || "일반 운영", "", "tone-neutral")}
                  ${pillHtml("queue-chip", label, "", tone)}
                </div>
                <div class="tree-member-detail-text">${safeLabel(flow.taskPreview, "예상 작업 원문")}</div>
              </article>
            `;
          })
          .join("")}
      </div>
    `
    : `
      <p class="queue-subtitle">
        ${pendingOutsideBoard > 0
          ? `최근 보드 밖에 아직 풀어야 할 대기 큐가 ${pendingOutsideBoard}건 있습니다.`
          : activity.detail || "현재 연결된 최근 작업이 없습니다."}
      </p>
    `;

  return `
    <article class="tree-member${isExpanded ? " expanded" : ""}">
      <button class="tree-leaf${primary ? " tree-leaf-primary" : ""}${isSelected ? " active" : ""}" type="button" data-tree-member="${title}">
        <div class="tree-leaf-copy">
          <span class="tree-leaf-name">${title}</span>
          <span class="tree-leaf-role">${memberOperatingMode(thread)}</span>
        </div>
        <div class="tree-leaf-meta">
          <span class="tree-leaf-state ${activity.tone}">${activity.label}</span>
          <span class="tree-leaf-chevron" aria-hidden="true">${isExpanded ? "접기" : "역할 보기"}</span>
        </div>
      </button>
      <div class="tree-member-detail" ${isExpanded ? "" : "hidden"}>
        <div class="tree-member-detail-head">
          <p class="eyebrow">${memberOperatingMode(thread)}</p>
          <strong>${safeLabel(memberRoleSummary(thread), "역할 정보 없음")}</strong>
        </div>
        <div class="stat-pills">
          ${pillHtml("stat-pill", "진행중", `${runningCount}`, runningCount > 0 ? "tone-running" : "tone-neutral")}
          ${pillHtml("stat-pill", "배정대기", `${waitingCount}`, waitingCount > 0 ? "tone-pending" : "tone-neutral")}
          ${pillHtml("stat-pill", "보드", `${counts.all}`, "tone-neutral")}
          ${pillHtml("stat-pill", "완료", `${counts.closed}`, counts.closed > 0 ? "tone-complete" : "tone-neutral")}
          ${stats.oldestPendingMinutes > 0 ? pillHtml("stat-pill", "최대 지연", `${stats.oldestPendingMinutes}분`, "tone-pending") : ""}
        </div>
        ${detailBody}
      </div>
    </article>
  `;
}

function renderOrgTree(threads) {
  if (!elements.orgTree) return;
  const secretary = threads.find((item) => (item.displayName || item.title) === "[비서] 보고자");
  const manager = threads.find((item) => (item.displayName || item.title) === "[관리자] 사장");
  const team1 = threads.filter((item) => String(item.displayName || "").startsWith("[1팀]"));
  const team2 = threads.filter((item) => String(item.displayName || "").startsWith("[2팀]"));
  const coop = threads.filter((item) => String(item.displayName || "").startsWith("[협력"));
  const external = threads.filter((item) => {
    const name = String(item.displayName || "");
    return !name.startsWith("[") || name.startsWith("[외부]");
  });
  const sections = [
    { label: "[1팀] 실행 조직", items: team1 },
    { label: "[2팀] 전략 조직", items: team2 },
    { label: "[협력] 전문 지원", items: coop },
    { label: "[외부] 연결 채널", items: external },
  ].filter((section) => section.items.length);

  const renderLeaf = (thread) => {
    return buildOrgTreeMember(thread);
  };

  elements.orgTree.innerHTML = `
    <section class="org-tree-root">
      <div class="tree-node tree-root">
        <div class="tree-label tree-label-root">대표님</div>
      </div>
      <div class="tree-trunk">
        ${secretary ? buildOrgTreeMember(secretary, { primary: true }) : ""}
        ${manager ? buildOrgTreeMember(manager, { primary: true }) : ""}
      </div>
      <div class="tree-branches">
        ${sections
          .map(
            (section) => `
              <article class="tree-branch">
                <div class="tree-label tree-label-branch">${section.label}</div>
                <div class="tree-leaves">
                  ${section.items.map((thread) => renderLeaf(thread)).join("")}
                </div>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;

  elements.orgTree.querySelectorAll("[data-tree-member]").forEach((node) => {
    node.addEventListener("click", () => {
      const title = node.getAttribute("data-tree-member") || "";
      state.selectedMemberTitle = title;
      state.selectedFlowId = "";
      state.expandedOrgMemberTitle = state.expandedOrgMemberTitle === title ? "" : title;
      expandGroupForMember(title);
      renderWorkspace();
    });
  });
}

function getFlows() {
  return Array.isArray(state.snapshot?.messageFlows) ? state.snapshot.messageFlows : [];
}

function getConversation() {
  return Array.isArray(state.snapshot?.conversation) ? state.snapshot.conversation : [];
}

function ensureConversation() {
  if (!state.snapshot) {
    state.snapshot = { conversation: [] };
    return state.snapshot.conversation;
  }
  if (!Array.isArray(state.snapshot.conversation)) {
    state.snapshot.conversation = [];
  }
  return state.snapshot.conversation;
}

function upsertConversationMessage(message) {
  if (!message || !message.id) return;
  const conversation = ensureConversation();
  if (conversation.some((item) => item.id === message.id)) return;
  conversation.push(message);
}

function topicTitleForItem(item) {
  return safeLabel(item?.topicTitle || item?.meta?.topicTitle || "", "일반 운영");
}

function topicIdForItem(item) {
  return String(item?.topicId || item?.meta?.topicId || topicTitleForItem(item));
}

function groupItemsByTopic(items) {
  const groups = [];
  const lookup = new Map();
  for (const item of items) {
    const topicId = topicIdForItem(item);
    const topicTitle = topicTitleForItem(item);
    if (!lookup.has(topicId)) {
      const group = { topicId, topicTitle, items: [] };
      lookup.set(topicId, group);
      groups.push(group);
    }
    lookup.get(topicId).items.push(item);
  }
  return groups;
}

function visibleReportLinks(report) {
  const links = Array.isArray(report?.links) ? report.links : [];
  return links.filter((link) => String(link?.kind || "").toLowerCase() !== "pdf");
}

function normalizeMemberTitle(title) {
  const text = String(title || "").trim();
  if (!text || text.includes("???") || text.includes("[???]") || text.includes("[愿")) {
    return "[비서] 보고자";
  }
  return text;
}

function selectedMember() {
  state.selectedMemberTitle = normalizeMemberTitle(state.selectedMemberTitle);
  return getThreads().find((item) => item.displayName === state.selectedMemberTitle || item.title === state.selectedMemberTitle) || null;
}

function getAssignmentState(assignment) {
  const status = String(assignment?.status || "").trim().toLowerCase();
  const step = String(assignment?.step || "").trim().toLowerCase();
  if (["completed", "done", "closed", "failed", "abandoned", "cancelled", "canceled", "skipped", "superseded"].includes(status)) {
    return "closed";
  }
  if (["queued", "pending", "accepted", "assigned"].includes(status)) {
    return "waiting";
  }
  if (["in_progress", "running", "working"].includes(status)) {
    return "active";
  }
  if (["feedback_received"].includes(step) || ["feedback_received"].includes(status)) {
    return "closed";
  }
  return assignment ? "active" : "idle";
}

function getMemberActivity(member) {
  const title = member?.displayName || member?.title || "";
  if (!title) return { tone: "idle", label: "대기", detail: "" };
  const counts = memberFlowCounts(member);
  const runningCount = memberRunningCount(member, counts);
  const waitingCount = memberWaitingCount(member, counts);
  const closedCount = counts.closed;

  if (title === "[관리자] 사장") {
    if (runningCount > 0) {
      return { tone: "active", label: "오케스트레이션 중", detail: `열린 흐름 ${Math.max(counts.active + counts.waiting, runningCount)}건` };
    }
    if (waitingCount > 0) {
      return { tone: "waiting", label: "배정 조율 중", detail: `열린 흐름 ${Math.max(counts.active + counts.waiting, waitingCount)}건` };
    }
    if (closedCount > 0) {
      return { tone: "idle", label: "최근 승인 완료", detail: `${closedCount}건 정리` };
    }
    return { tone: "idle", label: "대기", detail: "지금은 새 지시를 기다리는 중입니다." };
  }
  if (title === "[비서] 보고자") {
    if (runningCount > 0) {
      return { tone: "active", label: "브리핑 중", detail: `${runningCount}건 정리 중` };
    }
    if (waitingCount > 0) {
      return { tone: "waiting", label: "접수 대기", detail: `${waitingCount}건 접수됨` };
    }
    if (closedCount > 0) {
      return { tone: "idle", label: "최근 접수 완료", detail: `${closedCount}건 보고 완료` };
    }
    return { tone: "idle", label: "대기", detail: "현재 새 지시를 기다리는 중입니다." };
  }

  if (runningCount > 0) {
    const label = title.includes("팀장") ? "분업 진행 중" : title.startsWith("[협력") ? "지원 중" : "일 중";
    return { tone: "active", label, detail: `${runningCount}건 진행 중` };
  }
  if (waitingCount > 0) {
    const label = title.includes("팀장") ? "배정 대기" : title.startsWith("[협력") ? "호출 대기" : "대기 중";
    return { tone: "waiting", label, detail: `${waitingCount}건 대기 중` };
  }
  if (closedCount > 0) {
    return { tone: "idle", label: "최근 완료", detail: `${closedCount}건 완료` };
  }
  return { tone: "idle", label: "대기", detail: "현재 맡은 일이 없습니다." };
}

function memberQueueItems(member) {
  const title = member?.displayName || member?.title || "";
  if (!title) return [];
  if (title === "[비서] 보고자" || title === "[관리자] 사장") return getFlows();
  return getFlows().filter((flow) => {
    if (flow.sourceTitle === title) return true;
    return Array.isArray(flow.assignments) && flow.assignments.some((entry) => entry.helperTitle === title);
  });
}

function selectedFlow(member) {
  const items = memberQueueItems(member);
  if (!items.length) return null;
  return items.find((item) => item.handoffId === state.selectedFlowId) || items[0];
}

function flowStateForMember(flow, member) {
  if (!flow || !member) return "waiting";
  const title = member.displayName || member.title || "";
  const assignments = Array.isArray(flow.assignments) ? flow.assignments : [];
  const relevant = title === "[관리자] 사장" || title === "[비서] 보고자"
    ? assignments
    : assignments.filter((entry) => entry.helperTitle === title);

  if (!relevant.length) {
    return title === "[관리자] 사장" || title === "[비서] 보고자" ? "waiting" : "closed";
  }
  if (relevant.some((entry) => getAssignmentState(entry) === "active")) return "active";
  if (relevant.some((entry) => getAssignmentState(entry) === "waiting")) return "waiting";
  return "closed";
}

function flowOverallState(flow) {
  const assignments = Array.isArray(flow?.assignments) ? flow.assignments : [];
  if (!assignments.length) return "waiting";
  if (assignments.some((entry) => getAssignmentState(entry) === "active")) return "active";
  if (assignments.some((entry) => getAssignmentState(entry) === "waiting")) return "waiting";
  return "closed";
}

function setActiveTab(tabId) {
  state.selectedTab = tabId;
  elements.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === tabId));
  elements.panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === tabId));
}

function buildSummaryCards() {
  const flows = getFlows();
  const reports = getConversation().filter((item) => item.kind === "result" && visibleReportLinks(item.report).length);
  const activeCount = flows.filter((flow) => flowOverallState(flow) === "active").length;
  const waitingCount = flows.filter((flow) => flowOverallState(flow) === "waiting").length;
  const closedCount = flows.filter((flow) => flowOverallState(flow) === "closed").length;
  const cards = [
    {
      label: "진행중/대기",
      value: `${activeCount + waitingCount}건`,
      detail: `진행중 ${activeCount} · 대기 ${waitingCount}`,
    },
    {
      label: "배정대기",
      value: `${waitingCount}건`,
      detail: waitingCount
        ? "비서 접수 뒤 사장 배정이나 협력 호출을 기다리는 흐름입니다."
        : "지금 배정 대기 중인 흐름은 없습니다.",
    },
    {
      label: "완료",
      value: `${closedCount}건`,
      detail: closedCount
        ? "최근 완료되었거나 닫힌 흐름입니다."
        : "아직 완료로 정리된 흐름이 없습니다.",
    },
    {
      label: "보고서",
      value: `${reports.length}개`,
      detail: reports.length
        ? "완료 카드에서 HTML 또는 MD 결과를 바로 열 수 있습니다."
        : "완료 보고서가 아직 연결되지 않았습니다.",
    },
  ];

  elements.summaryCards.innerHTML = "";
  for (const card of cards) {
    const node = document.createElement("article");
    node.className = "summary-card";
    node.innerHTML = `
      <p class="eyebrow">${card.label}</p>
      <strong>${card.value}</strong>
      <p class="queue-subtitle">${card.detail}</p>
    `;
    elements.summaryCards.appendChild(node);
  }
}

function renderBanner() {
  const alerts = Array.isArray(state.snapshot?.alerts) ? state.snapshot.alerts : [];
  const resourceReasons = Array.isArray(state.snapshot?.watchdog?.reasons) ? state.snapshot.watchdog.reasons : [];
  if (!alerts.length && !resourceReasons.length) {
    elements.globalBanner.hidden = true;
    elements.globalBanner.textContent = "";
    return;
  }

  if (resourceReasons.length) {
    const reasonLabels = {
      user_active: "사용 중",
      high_cpu: "CPU 사용률 높음",
      low_memory: "메모리 부족",
      codex_memory_high: "Codex 메모리 사용량 높음",
      chrome_memory_high: "Chrome 메모리 사용량 높음",
      gpu_busy: "GPU 사용률 높음",
      gpu_memory_high: "GPU 메모리 사용량 높음",
    };
    const detail = resourceReasons
      .map((reason) => reasonLabels[String(reason).toLowerCase()] || reason)
      .filter(Boolean)
      .join(", ");
    const message = detail ? `${detail} · 조건이 풀리면 자동 실행됩니다.` : "조건이 풀리면 자동 실행됩니다.";
    elements.globalBanner.hidden = false;
    elements.globalBanner.textContent = `자원 사용량 때문에 대기: ${message}`;
    return;
  }

  const resourceGuard = alerts.find(
    (item) =>
      String(item?.title || "").includes("자원") ||
      String(item?.title || "").toLowerCase().includes("resource") ||
      String(item?.detail || "").toLowerCase().includes("user_active"),
  );
  const levelRank = { critical: 3, warn: 2, info: 1 };
  const sorted = [...alerts].sort(
    (left, right) => (levelRank[right.level] || 0) - (levelRank[left.level] || 0),
  );
  const alert = resourceGuard || sorted[0];
  elements.globalBanner.hidden = false;
  elements.globalBanner.textContent = `${alert.title}: ${alert.detail}`;
}

function pushResourceSample(bucket, value) {
  const list = state.resourceHistory[bucket];
  if (!Array.isArray(list)) return;
  const numeric = Number(value);
  list.push(Number.isFinite(numeric) ? numeric : 0);
  while (list.length > 24) {
    list.shift();
  }
}

function renderMiniChart(target, samples, maxValue) {
  if (!target) return;
  const values = Array.isArray(samples) ? samples.slice(-24) : [];
  const upperBound = Math.max(1, Number(maxValue) || 1, ...values);
  target.innerHTML = "";
  const padded = new Array(Math.max(0, 24 - values.length)).fill(null).concat(values);
  for (const sample of padded) {
    const bar = document.createElement("span");
    bar.className = `mini-bar${sample === null ? " empty" : ""}`;
    const ratio = sample === null ? 0.08 : Math.max(0.08, Math.min(1, Number(sample || 0) / upperBound));
    bar.style.height = `${Math.round(ratio * 100)}%`;
    target.appendChild(bar);
  }
}

function renderResourceCard() {
  const resource = state.snapshot?.overview?.resources || {};
  const cpuPercent = Number(resource.cpuPercent || 0);
  const cpuClockGhz = Number(resource.cpuClockGhz || 0);
  const memoryPercent = Number(resource.memoryLoadPercent || 0);
  const gpu = resource.gpu || {};
  const quota = resource.codexQuota || {};
  const gpuPercent = Number(gpu.gpuPercent || 0);
  const gpuMemoryUsedMb = Number(gpu.memoryUsedMb || 0);
  const gpuMemoryTotalMb = Number(gpu.memoryTotalMb || 0);
  const quotaPercent = Number.isFinite(Number(quota.remainingPercent)) ? Number(quota.remainingPercent) : 0;

  pushResourceSample("cpu", cpuPercent);
  pushResourceSample("memory", memoryPercent);
  pushResourceSample("gpu", gpuPercent);
  pushResourceSample("quota", quotaPercent);

  elements.resourceUpdatedAt.textContent = formatTimestamp(gpu.updatedAt || quota.updatedAt || resource.updatedAt);
  elements.cpuValue.textContent = cpuClockGhz > 0 ? `${formatPercent(cpuPercent)} / ${cpuClockGhz.toFixed(2)} GHz` : formatPercent(cpuPercent);
  elements.memoryValue.textContent = `${formatPercent(memoryPercent)} / ${formatMemoryMb(resource.usedPhysicalMb || 0)}`;
  elements.gpuValue.textContent = gpu.available
    ? `${formatPercent(gpuPercent)} / ${formatMemoryMb(gpuMemoryUsedMb)}`
    : "미감지";
  elements.quotaValue.textContent = quota.available
    ? `${formatPercent(quotaPercent)}`
    : (quota.label || "미연동");

  renderMiniChart(elements.cpuChart, state.resourceHistory.cpu, 100);
  renderMiniChart(elements.memoryChart, state.resourceHistory.memory, 100);
  renderMiniChart(elements.gpuChart, state.resourceHistory.gpu, 100);
  renderMiniChart(elements.quotaChart, state.resourceHistory.quota, 100);
}

function renderMembers() {
  const threads = getThreads();
  elements.memberCount.textContent = `${threads.length}명`;
  elements.memberList.innerHTML = "";
  renderOrgTree(threads);
  const focusMembers = state.focusedBoardPane === "members";
  if (elements.boardPaneMembers) {
    elements.boardPaneMembers.classList.toggle("tree-mode", focusMembers);
  }
  if (elements.memberMode) {
    elements.memberMode.textContent = focusMembers ? "조직도 보기" : "카드 보기";
  }
  if (elements.orgTree) {
    elements.orgTree.hidden = !focusMembers;
  }
  elements.memberList.hidden = focusMembers;
  const secretary = threads.find((item) => item.displayName === "[비서] 보고자");
  const manager = threads.find((item) => item.displayName === "[관리자] 사장");
  if (secretary) {
    elements.memberList.appendChild(buildMemberCard(secretary, "secretary"));
  }
  if (manager) {
    elements.memberList.appendChild(buildMemberCard(manager));
  }
  const groups = [
    {
      key: "team1",
      label: "[1팀] 실행 조직",
      items: threads.filter((item) => String(item.displayName).startsWith("[1팀]")),
    },
    {
      key: "team2",
      label: "[2팀] 전략 조직",
      items: threads.filter((item) => String(item.displayName).startsWith("[2팀]")),
    },
    {
      key: "coop",
      label: "[협력] 전문 지원",
      items: threads.filter((item) => String(item.displayName).startsWith("[협력")),
    },
    {
      key: "external",
      label: "[외부] 연결 채널",
      items: threads.filter((item) => !String(item.displayName).startsWith("[")),
    },
  ];

  for (const group of groups) {
    if (!group.items.length) continue;
    const totals = group.items.reduce(
      (acc, item) => {
        const counts = memberFlowCounts(item);
        acc.running += memberRunningCount(item, counts);
        acc.pending += memberWaitingCount(item, counts);
        return acc;
      },
      { running: 0, pending: 0 }
    );
    const isExpanded = !!state.expandedMemberGroups[group.key];
    const section = document.createElement("section");
    section.className = `member-group-card${isExpanded ? " expanded" : ""}`;
    section.innerHTML = `
      <button class="member-group-toggle" type="button" aria-expanded="${isExpanded}">
        <div class="member-group-copy">
          <p class="member-group-title">${group.label}</p>
        </div>
        <div class="member-group-meta">
          <span class="member-group-count">${group.items.length}명</span>
          <span class="member-group-summary">진행 ${totals.running} · 배정대기 ${totals.pending}</span>
          <span class="member-group-chevron" aria-hidden="true">${isExpanded ? "−" : "+"}</span>
        </div>
      </button>
      <div class="member-group-body"></div>
    `;
    const toggle = section.querySelector(".member-group-toggle");
    const body = section.querySelector(".member-group-body");
    if (!(toggle instanceof HTMLElement) || !(body instanceof HTMLElement)) {
      elements.memberList.appendChild(section);
      continue;
    }
    toggle.addEventListener("click", () => {
      state.expandedMemberGroups[group.key] = !state.expandedMemberGroups[group.key];
      renderMembers();
    });

    for (const thread of group.items) {
      body.appendChild(buildMemberCard(thread, group.key));
    }
    elements.memberList.appendChild(section);
  }
}

function renderDirectiveHistory() {
  if (!elements.directiveHistory) return;
  const directives = getConversation()
    .filter((item) => item.role === "user")
    .sort((left, right) => parseTimestamp(right.createdAt) - parseTimestamp(left.createdAt))
    .slice(0, 6);
  if (!directives.length) {
    elements.directiveHistory.innerHTML = `<div class="detail-empty">최근 지시 이력은 아직 없습니다.</div>`;
    return;
  }
  const groups = groupItemsByTopic(directives);
  elements.directiveHistory.innerHTML = `
    <div class="directive-history-head">
      <h3>최근 지시</h3>
      <span>${directives.length}건</span>
    </div>
    <div class="directive-history-list topic-stack">
      ${groups
        .map(
          (group) => `
            <section class="topic-group">
              <div class="topic-group-head">
                <strong>${group.topicTitle}</strong>
                <span>${group.items.length}건</span>
              </div>
              <div class="topic-group-list">
                ${group.items
                  .map(
                    (message) => `
                      <article class="directive-history-card">
                        <div class="directive-history-meta">대표님 지시 · ${formatTimestamp(message.createdAt)}</div>
                        <div class="directive-history-text">${safeLabel(extractRepresentativeDirective(message.text), "원문 복구 필요")}</div>
                      </article>
                    `,
                  )
                  .join("")}
              </div>
            </section>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderBoardPaneFocus() {
  if (!elements.boardGrid) return;
  const focus = state.focusedBoardPane || "";
  elements.boardGrid.dataset.focus = focus;
  const panes = [
    elements.boardPaneMembers,
    elements.boardPaneQueue,
    elements.boardPaneConversation,
  ];
  for (const pane of panes) {
    if (!(pane instanceof HTMLElement)) continue;
    const isFocused = focus && pane.dataset.pane === focus;
    const isDimmed = focus && pane.dataset.pane !== focus;
    pane.classList.toggle("is-focused", Boolean(isFocused));
    pane.classList.toggle("is-dimmed", Boolean(isDimmed));
  }
  for (const toggle of elements.paneToggles) {
    const paneName = toggle.dataset.paneToggle || "";
    toggle.setAttribute("aria-expanded", focus === paneName ? "true" : "false");
  }
}

function renderMemberSummary(member) {
  if (!member) return;
  const counts = memberFlowCounts(member);
  const stats = getThreadStats(member);
  const active = selectedFlow(member);
  const activity = getMemberActivity(member);
  elements.selectedMemberName.textContent = member.displayName || member.title;
  if (elements.selectedMemberRole) {
    elements.selectedMemberRole.textContent = memberRoleSummary(member);
  }
  elements.selectedMemberStatus.textContent = active
    ? `${activity.label} · ${active.routeLabel || active.route || "진행 중"}`
    : `${activity.label}${activity.detail ? ` · ${activity.detail}` : ""}`;
  elements.selectedMemberStats.innerHTML = "";
  const chips = [
    ["역할", memberOperatingMode(member)],
    ["보드", `${counts.all}건`],
    ["진행중", `${Math.max(counts.active, stats.running)}`],
    ["배정대기", `${Math.max(counts.waiting, stats.pending + stats.queued)}`],
    ["완료", `${counts.closed}`],
  ];
  for (const [label, value] of chips) {
    const node = document.createElement("span");
    node.className = `stat-pill ${toneClassForLabel(label)}`;
    node.textContent = `${label} ${value}`;
    elements.selectedMemberStats.appendChild(node);
  }
}

function renderQueueList(member) {
  const items = memberQueueItems(member);
  const filterOptions = [
    { key: "all", label: "전체" },
    { key: "active", label: "진행중" },
    { key: "waiting", label: "대기중" },
    { key: "closed", label: "완료" },
  ];
  const counts = items.reduce(
    (acc, flow) => {
      const stateName = flowStateForMember(flow, member);
      acc.all += 1;
      acc[stateName] += 1;
      return acc;
    },
    { all: 0, active: 0, waiting: 0, closed: 0 },
  );
  if (elements.queueFilters) {
    elements.queueFilters.innerHTML = filterOptions
      .map((option) => {
        const activeClass = state.queueFilter === option.key ? " active" : "";
        return `
          <button class="queue-filter${activeClass}" type="button" data-filter="${option.key}">
            <span>${option.label}</span>
            <strong>${counts[option.key] ?? 0}</strong>
          </button>
        `;
      })
      .join("");
    elements.queueFilters.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.queueFilter = button.getAttribute("data-filter") || "all";
        renderQueueList(member);
      });
    });
  }
  const visibleItems = items.filter((flow) => state.queueFilter === "all" || flowStateForMember(flow, member) === state.queueFilter);
  elements.queueCount.textContent = `${visibleItems.length}건`;
  elements.queueList.innerHTML = "";
  if (!visibleItems.length) {
    elements.queueList.innerHTML = `<div class="queue-empty">선택한 구성원에게 연결된 현재 큐가 없습니다.</div>`;
    return;
  }
  const active = selectedFlow(member);
  state.selectedFlowId = active?.handoffId || "";
  for (const flow of visibleItems) {
    const flowState = flowStateForMember(flow, member);
    const node = document.createElement("button");
    node.type = "button";
    node.className = `queue-card${flow.handoffId === state.selectedFlowId ? " active" : ""}`;
    node.innerHTML = `
      <div class="queue-meta-row">
        ${pillHtml("queue-chip", flow.topicTitle || "일반 운영", "", "tone-neutral")}
        ${pillHtml("queue-chip", flow.routeLabel || flow.route || "-", "", "tone-queued")}
        ${pillHtml("queue-chip", flowState === "active" ? "진행중" : flowState === "waiting" ? "대기중" : "완료", "", flowState === "active" ? "tone-running" : flowState === "waiting" ? "tone-pending" : "tone-complete")}
        ${pillHtml("queue-chip", formatTimestamp(flow.createdAt), "", "tone-neutral")}
        ${pillHtml("queue-chip", "배정", `${Array.isArray(flow.assignments) ? flow.assignments.length : 0}`, "tone-neutral")}
      </div>
      <div class="queue-card-title">${safeLabel(flow.taskPreview, "예상 작업 원문")}</div>
      <p class="queue-subtitle">출발: ${safeLabel(flow.sourceTitle, "-")}</p>
    `;
    node.addEventListener("click", () => {
      state.selectedFlowId = flow.handoffId;
      renderWorkspace();
    });
    elements.queueList.appendChild(node);
  }
}

function renderProgress(member) {
  const flow = selectedFlow(member);
  elements.progressPanel.innerHTML = "";
  elements.progressRoute.textContent = flow ? (flow.routeLabel || flow.route || "-") : "-";
  if (!flow) {
    elements.progressPanel.innerHTML = `<div class="detail-empty">선택된 작업이 없습니다.</div>`;
    return;
  }
  const taskFullText = safeLabel(flow.taskText || flow.taskPreview, "원문 복구 필요");
  const top = document.createElement("article");
  top.className = "detail-card";
  top.innerHTML = `
    <p class="eyebrow">작업 요약</p>
    <strong>${safeLabel(flow.taskPreview, "예상 작업 원문")}</strong>
    <div class="detail-topic-row">${pillHtml("queue-chip", flow.topicTitle || "일반 운영", "", "tone-neutral")}</div>
    <dl class="detail-list">
      <div class="detail-row"><dt>생성 시각</dt><dd>${formatTimestamp(flow.createdAt)}</dd></div>
      <div class="detail-row"><dt>출발 스레드</dt><dd>${safeLabel(flow.sourceTitle, "-")}</dd></div>
      <div class="detail-row"><dt>메모</dt><dd>${safeLabel(flow.sourceNotes, "-")}</dd></div>
    </dl>
    <pre class="detail-fulltext">${taskFullText}</pre>
  `;
  elements.progressPanel.appendChild(top);

  const promptChain = document.createElement("article");
  promptChain.className = "detail-card";
  promptChain.innerHTML = `
    <p class="eyebrow">전달 체인</p>
    <strong>대표님 -> 비서 -> 사장 -> 팀/협력</strong>
    <p class="detail-copy">아래에서 각 대상에게 실제로 전달된 전체 프롬프트를 바로 볼 수 있습니다.</p>
    <div class="prompt-chain-list"></div>
  `;
  const promptChainList = promptChain.querySelector(".prompt-chain-list");
  for (const assignment of flow.assignments || []) {
    if (!(promptChainList instanceof HTMLElement)) break;
    const requestText = safeLabel(assignment.requestText || assignment.requestPreview, "전달 프롬프트 복구 필요");
    const item = document.createElement("details");
    item.className = "detail-expand prompt-chain-item";
    item.innerHTML = `
      <summary>${safeLabel(assignment.helperTitle || "배정 대상", "배정 대상")} 전달 프롬프트 전체 보기</summary>
      <pre class="detail-fulltext">${requestText}</pre>
    `;
    promptChainList.appendChild(item);
  }
  elements.progressPanel.appendChild(promptChain);

  for (const assignment of flow.assignments || []) {
    const responseText = safeLabel(assignment.responseText || assignment.responsePreview, "응답 원문 복구 필요");
    const card = document.createElement("article");
    card.className = "detail-card";
    card.innerHTML = `
      <p class="eyebrow">${assignment.helperTitle || "배정 대상"}</p>
      <strong>${assignment.status || "-"}</strong>
      <dl class="detail-list">
        <div class="detail-row"><dt>역할</dt><dd>${assignment.helperRole || "-"}</dd></div>
        <div class="detail-row"><dt>업데이트</dt><dd>${formatTimestamp(assignment.updatedAt)}</dd></div>
      </dl>
      ${assignment.responsePreview ? `<p class="detail-copy">${safeLabel(assignment.responsePreview, "응답 원문 복구 필요")}</p>` : ""}
      ${assignment.responseText ? `
        <details class="detail-expand">
          <summary>진행사항 전체 보기</summary>
          <pre class="detail-fulltext">${responseText}</pre>
        </details>
      ` : ""}
    `;
    elements.progressPanel.appendChild(card);
  }
}

function renderReportFocus(member) {
  const flow = selectedFlow(member);
  elements.reportFocus.innerHTML = "";
  if (!flow) {
    elements.reportFocus.innerHTML = `<div class="detail-empty">작업을 선택하면 3줄 요약과 보고서 링크를 보여줍니다.</div>`;
    return;
  }
  const resultMessage = getConversation().find((item) => item.handoffId === flow.handoffId && item.kind === "result");
  const lines = resultMessage?.summaryLines?.length
    ? resultMessage.summaryLines
    : ["아직 최종 요약이 없고, helper가 배경 분석 중입니다.", "완료되면 HTML 또는 MD 결과 링크가 나타납니다."];
  const report = resultMessage?.report || {};
  const links = visibleReportLinks(report);
  elements.reportFocus.innerHTML = `
    <div class="report-topic">${pillHtml("queue-chip", flow.topicTitle || "일반 운영", "", "tone-neutral")}</div>
    <div class="report-title">${safeLabel(report.title || flow.handoffId, flow.handoffId || "보고서")}</div>
    <ol class="report-lines">${lines.slice(0, 3).map((line) => `<li>${safeLabel(line, "원문 복구 필요")}</li>`).join("")}</ol>
    <div class="report-links">${links.map((link) => `<a class="report-link" target="_blank" rel="noopener" href="${link.url}">${link.label}</a>`).join("")}</div>
  `;
}

function renderConversation() {
  const conversation = [...getConversation()].sort(
    (left, right) => parseTimestamp(right.createdAt) - parseTimestamp(left.createdAt)
  );
  elements.chatLog.innerHTML = "";
  if (!conversation.length) {
    elements.chatLog.innerHTML = `<div class="chat-empty">아직 대화 기록이 없습니다.</div>`;
    return;
  }
  const groups = groupItemsByTopic(conversation);
  for (const group of groups) {
    const groupNode = document.createElement("section");
    groupNode.className = "chat-topic-group";
    groupNode.innerHTML = `
      <div class="chat-topic-head">
        <strong>${group.topicTitle}</strong>
        <span>${group.items.length}건</span>
      </div>
    `;
    for (const message of group.items) {
      const roleClass = message.role === "user" ? "user" : "assistant";
      const node = document.createElement("article");
      node.className = `chat-item ${roleClass}`;
      const label = message.role === "user" ? "대표님 지시" : message.kind === "result" ? "결과 보고" : "상태 보고";
      const lines = Array.isArray(message.summaryLines) && message.summaryLines.length
        ? message.summaryLines.map((line) => rewriteVisibleSystemText(line))
        : [message.role === "user" ? extractRepresentativeDirective(message.text) || "" : stripInternalRoutingPrefix(rewriteVisibleSystemText(message.text)) || ""];
      node.innerHTML = `
        <div class="chat-meta">${label} · ${formatTimestamp(message.createdAt)}</div>
        <div class="chat-bubble">
          <ol class="chat-lines">${lines.slice(0, 3).map((line) => `<li>${safeLabel(line, "원문 복구 필요")}</li>`).join("")}</ol>
        </div>
      `;
      groupNode.appendChild(node);
    }
    elements.chatLog.appendChild(groupNode);
  }
  elements.chatLog.scrollTo({ top: 0, behavior: "smooth" });
}

function renderComposer(member) {
  const title = member?.displayName || "[비서] 보고자";
  const flow = selectedFlow(member);
  const contextTitle = title === "[비서] 보고자" ? "비서 선접수" : `참고 중 ${title}`;
  elements.composerTargetTitle.textContent = "[비서] 보고자에게 바로 지시";
  elements.composerTargetMeta.textContent = `${contextTitle}${flow ? ` · 대주제 ${flow.topicTitle || "일반 운영"} · 참고 큐 ${flow.handoffId}` : ""}`;
  elements.composerHint.textContent = "대표님 지시는 먼저 [비서] 보고자가 받습니다. 비서가 스킬 후보와 요약을 고른 뒤 [관리자] 사장이 직접 처리할지, 팀장이나 협력 스레드에 위임할지 결정합니다.";
}

function renderFlowTimeline() {
  const flows = getFlows();
  elements.flowTimeline.innerHTML = "";
  if (!flows.length) {
    elements.flowTimeline.innerHTML = `<div class="detail-empty">최근 흐름이 없습니다.</div>`;
    return;
  }
  for (const flow of flows) {
    const node = document.createElement("article");
    node.className = "timeline-card";
    node.innerHTML = `
      <div class="timeline-meta">
        ${pillHtml("queue-chip", flow.topicTitle || "일반 운영", "", "tone-neutral")}
        ${pillHtml("queue-chip", flow.routeLabel || flow.route || "-", "", "tone-queued")}
        ${pillHtml("queue-chip", formatTimestamp(flow.createdAt), "", "tone-neutral")}
        ${pillHtml("queue-chip", safeLabel(flow.sourceTitle, "-"), "", "tone-neutral")}
      </div>
      <div class="timeline-title">${safeLabel(flow.taskPreview, "예상 작업 원문")}</div>
      <p class="queue-subtitle">${(flow.assignments || []).map((item) => `${safeLabel(item.helperTitle, "대상")}: ${safeLabel(item.status, "-")}`).join(" · ") || "배정 없음"}</p>
    `;
    node.addEventListener("click", () => {
      state.selectedFlowId = flow.handoffId;
      state.selectedMemberTitle = "[비서] 보고자";
      setActiveTab("board");
      renderWorkspace();
    });
    elements.flowTimeline.appendChild(node);
  }
}

function renderReportLibrary() {
  const results = getConversation().filter((item) => item.kind === "result" && visibleReportLinks(item.report).length);
  elements.reportLibrary.innerHTML = "";
  if (!results.length) {
    elements.reportLibrary.innerHTML = `<div class="detail-empty">연결된 보고서가 아직 없습니다.</div>`;
    return;
  }
  for (const result of results) {
    const links = visibleReportLinks(result.report);
    const node = document.createElement("article");
    node.className = "report-card";
    node.innerHTML = `
      <div class="report-title-text">${safeLabel(result.report.title || result.handoffId, result.handoffId || "보고서")}</div>
      <p class="queue-subtitle">대주제 · ${topicTitleForItem(result)}</p>
      <p class="queue-subtitle">${(result.summaryLines || []).slice(0, 3).map((line) => safeLabel(line, "원문 복구 필요")).join(" / ")}</p>
      <div class="report-links">${links.map((link) => `<a class="report-link" target="_blank" rel="noopener" href="${link.url}">${link.label}</a>`).join("")}</div>
    `;
    elements.reportLibrary.appendChild(node);
  }
}

function renderSettings() {
  const publicTunnel = state.snapshot?.paths?.publicTunnelStatus || "";
  const overview = state.snapshot?.overview || {};
  const accessPolicyLabel = state.auth.mode === "trusted-local"
    ? "로컬 신뢰 접속 / 원격 코드 로그인"
    : "접속 코드 로그인";
  elements.settingsPanel.innerHTML = `
    <article class="setting-card">
      <p class="eyebrow">접속 정책</p>
      <strong>${accessPolicyLabel}</strong>
      <p class="setting-copy">${state.auth.message || ""}</p>
      <dl>
        <div><dt>전달 메일</dt><dd>${state.auth.deliveryTarget || "-"}</dd></div>
        <div><dt>코드 백업 파일</dt><dd>${state.auth.deliveryFallback || "-"}</dd></div>
        <div><dt>public tunnel 상태 파일</dt><dd>${publicTunnel || "-"}</dd></div>
        <div><dt>runtime root</dt><dd>${state.snapshot?.paths?.runtimeRoot || "-"}</dd></div>
      </dl>
    </article>
    <article class="setting-card">
      <p class="eyebrow">운영 상태</p>
      <strong>watchdog / scheduler / gmail</strong>
      <dl>
        <div><dt>watchdog</dt><dd>${overview.watchdog?.status || "-"} · ${overview.watchdog?.decision || "-"}</dd></div>
        <div><dt>scheduler</dt><dd>open ${overview.scheduler?.openJobCount ?? 0}</dd></div>
        <div><dt>gmail</dt><dd>${overview.gmail?.running ? "running" : "stopped"}${overview.gmail?.skipReason ? ` · ${overview.gmail.skipReason}` : ""}</dd></div>
      </dl>
    </article>
  `;
}

function renderWorkspace() {
  const threads = getThreads();
  const secretary = threads.find((item) => (item.displayName || item.title) === "[비서] 보고자") || null;
  const manager = threads.find((item) => (item.displayName || item.title) === "[관리자] 사장") || null;
  const member = selectedMember() || secretary || manager || threads[0] || null;
  if (member) {
    state.selectedMemberTitle = member.displayName || member.title;
    expandGroupForMember(state.selectedMemberTitle);
  }
  renderResourceCard();
  buildSummaryCards();
  renderBanner();
  renderBoardPaneFocus();
  renderMembers();
  renderMemberSummary(member);
  renderQueueList(member);
  renderProgress(member);
  renderDirectiveHistory();
  renderReportFocus(member);
  renderConversation();
  renderComposer(member);
  renderFlowTimeline();
  renderReportLibrary();
  renderSettings();
}

function renderAuthGate() {
  const gateVisible = state.auth.requiresLogin && !state.auth.authenticated;
  const isCodeLogin = state.auth.mode === "code-login";
  elements.authGate.hidden = !gateVisible;
  elements.logoutButton.hidden = !isCodeLogin || !state.auth.authenticated;
  elements.sendButton.disabled = gateVisible;
  elements.micButton.disabled = gateVisible;
  elements.promptInput.disabled = gateVisible;
  elements.accessMode.textContent = isCodeLogin ? "접속 코드 로그인" : "로컬 신뢰 접속";
  elements.sessionExpiresAt.textContent =
    isCodeLogin && state.auth.sessionExpiresAt ? formatTimestamp(state.auth.sessionExpiresAt) : "-";
  const hintParts = [
    state.auth.message || "",
    isCodeLogin && state.auth.deliveryTarget ? `대표님 메일: ${state.auth.deliveryTarget}` : "",
    isCodeLogin && state.auth.codeIssuedAt ? `발급: ${formatTimestamp(state.auth.codeIssuedAt)}` : "",
  ].filter(Boolean);
  elements.authHint.textContent = hintParts.join(" · ");
  if (gateVisible) {
    window.setTimeout(() => elements.codeInput.focus(), 60);
  }
}

async function syncAuthState() {
  const payload = await fetchJson("/api/auth/state");
  state.auth = {
    authenticated: Boolean(payload.authenticated),
    requiresLogin: Boolean(payload.requiresLogin),
    mode: payload.mode || "code-login",
    csrfToken: payload.csrfToken || "",
    sessionExpiresAt: payload.sessionExpiresAt || "",
    message: payload.message || "",
    codeIssuedAt: payload.codeIssuedAt || "",
    deliveryPrimary: payload.deliveryPrimary || "",
    deliveryTarget: payload.deliveryTarget || "",
    deliveryFallback: payload.deliveryFallback || "",
  };
  renderAuthGate();
}

async function refreshSnapshot() {
  if (state.isRefreshing) return;
  if (state.auth.requiresLogin && !state.auth.authenticated) return;
  state.isRefreshing = true;
  try {
    const snapshot = await fetchJson("/api/snapshot");
    if (state.uiVersion && snapshot.uiVersion && state.uiVersion !== snapshot.uiVersion) {
      window.location.reload();
      return;
    }
    state.uiVersion = snapshot.uiVersion || state.uiVersion;
    state.snapshot = snapshot;
    state.recording = Boolean(snapshot.ptt?.recording);
    elements.generatedAt.textContent = formatTimestamp(snapshot.generatedAt);
    elements.micButton.classList.toggle("recording", state.recording);
    elements.micButton.setAttribute("aria-pressed", state.recording ? "true" : "false");
    if (elements.syncState) {
      elements.syncState.textContent = "실시간 연결";
      elements.syncState.className = "sync-live";
    }
    try {
      renderWorkspace();
    } catch (renderError) {
      recordClientError(renderError);
    }
  } catch (error) {
    recordClientError(error);
  } finally {
    state.isRefreshing = false;
  }
}

function startRefreshLoop() {
  if (state.refreshTimer) return;
  state.refreshTimer = window.setInterval(refreshSnapshot, 5000);
}

function stopRefreshLoop() {
  if (!state.refreshTimer) return;
  window.clearInterval(state.refreshTimer);
  state.refreshTimer = null;
}

async function submitAuth(event) {
  event.preventDefault();
  const code = elements.codeInput.value.trim();
  if (!code) {
    showToast("접속 코드가 비어 있습니다", "메일이나 안내 메시지에서 받은 코드를 입력해 주세요.");
    return;
  }
  elements.authSubmit.disabled = true;
  try {
    const payload = await fetchJson("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    state.auth.authenticated = Boolean(payload.auth?.authenticated);
    state.auth.mode = payload.auth?.mode || "code-login";
    state.auth.requiresLogin = Boolean(payload.auth?.requiresLogin ?? true);
    state.auth.csrfToken = payload.auth?.csrfToken || "";
    state.auth.sessionExpiresAt = payload.auth?.sessionExpiresAt || "";
    state.auth.codeIssuedAt = payload.auth?.codeIssuedAt || "";
    state.auth.deliveryPrimary = payload.auth?.deliveryPrimary || "";
    state.auth.deliveryTarget = payload.auth?.deliveryTarget || "";
    state.auth.deliveryFallback = payload.auth?.deliveryFallback || "";
    renderAuthGate();
    startRefreshLoop();
    showToast("로그인 완료", "이제 폰과 PC 모두 같은 접속 코드로 관제 화면을 사용할 수 있습니다.");
    await refreshSnapshot();
  } catch (error) {
    showToast("로그인 실패", error.message);
  } finally {
    elements.authSubmit.disabled = false;
  }
}

async function logout() {
  try {
    await fetchJson("/api/auth/logout", { method: "POST" }, { includeCsrf: true });
  } catch {
    // ignore
  }
  stopRefreshLoop();
  await syncAuthState();
}

async function togglePtt() {
  const next = !state.recording;
  try {
    const payload = await fetchJson(
      "/api/ptt",
      {
        method: "POST",
        body: JSON.stringify({ recording: next }),
      },
      { includeCsrf: true },
    );
    state.recording = Boolean(payload.ptt?.recording);
    elements.micButton.classList.toggle("recording", state.recording);
    elements.micButton.setAttribute("aria-pressed", state.recording ? "true" : "false");
    showToast(
      state.recording ? "PTT 시작" : "PTT 종료",
      state.recording ? "음성 트리거를 켰습니다." : "음성 트리거를 껐습니다.",
    );
    await refreshSnapshot();
  } catch (error) {
    showToast("PTT 전환 실패", error.message);
  }
}

async function submitCommand(event) {
  event.preventDefault();
  if (state.inputComposing) return;
  const rawText = elements.promptInput.value.trim();
  if (!rawText) {
    showToast("보낼 내용이 없습니다", "추가 지시나 확인 내용을 입력해 주세요.");
    return;
  }
  const member = selectedMember();
  const flow = selectedFlow(member);
  const title = member?.displayName || "[관리자] 사장";
  elements.sendButton.disabled = true;
  try {
    const payload = await fetchJson(
      "/api/commands",
      {
        method: "POST",
        body: JSON.stringify({
          text: rawText,
          contextMemberTitle: title,
          contextFlowId: flow?.handoffId || "",
          intakeMode: "secretary-first",
        }),
      },
      { includeCsrf: true },
    );
    if (payload?.userMessage) upsertConversationMessage(payload.userMessage);
    if (payload?.statusMessage) upsertConversationMessage(payload.statusMessage);
    elements.promptInput.value = "";
    saveDraft("");
    autosizeTextarea();
    renderConversation();
    showToast("지시 전달 완료", "[비서] 보고자가 먼저 접수하고 스킬을 정리한 뒤, [관리자] 사장이 내부 위임 여부를 판단합니다.");
    await refreshSnapshot();
  } catch (error) {
    showToast("지시 전달 실패", error.message);
  } finally {
    elements.sendButton.disabled = false;
  }
}

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
});

elements.themeToggle.addEventListener("click", () => applyTheme(state.theme === "dark" ? "light" : "dark"));
elements.authForm.addEventListener("submit", submitAuth);
elements.logoutButton.addEventListener("click", logout);
elements.micButton.addEventListener("click", togglePtt);
elements.composerForm.addEventListener("submit", submitCommand);
elements.promptInput.addEventListener("input", () => {
  saveDraft(elements.promptInput.value);
  autosizeTextarea();
});
elements.promptInput.addEventListener("compositionstart", () => {
  state.inputComposing = true;
});
elements.promptInput.addEventListener("compositionend", () => {
  state.inputComposing = false;
});
elements.promptInput.addEventListener("keydown", (event) => {
  if (event.isComposing || state.inputComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composerForm.requestSubmit();
  }
});

elements.paneToggles.forEach((toggle) => {
  const applyToggle = () => {
    const paneName = toggle.dataset.paneToggle || "";
    state.focusedBoardPane = state.focusedBoardPane === paneName ? "" : paneName;
    renderWorkspace();
  };
  toggle.addEventListener("click", (event) => {
    if (event.target.closest("#micButton")) return;
    applyToggle();
  });
  toggle.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      applyToggle();
    }
  });
});

applyTheme(readPreferredTheme(), { persist: false });
elements.promptInput.value = loadDraft();
autosizeTextarea();
renderAuthGate();
setActiveTab("board");

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    syncAuthState()
      .then(() => refreshSnapshot())
      .catch(() => {});
  }
});

syncAuthState()
  .then(async () => {
    startRefreshLoop();
    await refreshSnapshot();
  })
  .catch((error) => {
    recordClientError(error);
  });

window.addEventListener("error", (event) => {
  recordClientError(event.error || event.message || "window error");
});

window.addEventListener("unhandledrejection", (event) => {
  recordClientError(event.reason || "unhandled rejection");
});
