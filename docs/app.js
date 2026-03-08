const REPO_OWNER = "frysquirrel-A";
const REPO_NAME = "codex-local-agent-tools";
const ISSUE_TEMPLATE = "remote-command.md";
const ISSUE_LABEL = "remote-command";
const TITLE_PREFIX = "[remote]";
const RECENT_LIMIT = 14;
const POLL_INTERVAL_MS = 15000;
const THREAD_LIMIT = 10;

let loading = false;

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseSection(body, heading) {
  if (!body) {
    return "";
  }

  const pattern = new RegExp(`###\\s+${heading}\\s*\\n([\\s\\S]*?)(?=\\n###\\s+|$)`, "m");
  const match = body.match(pattern);
  return match ? match[1].trim() : "";
}

function deriveTitle(text) {
  const compact = normalizeText(text);
  if (!compact) {
    return "remote command";
  }
  return compact.length > 52 ? `${compact.slice(0, 52)}...` : compact;
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
    return "명령 내용 없음";
  }

  const parsed = parseMaybeJson(normalized);
  if (!parsed || typeof parsed !== "object") {
    return normalized.length > 140 ? `${normalized.slice(0, 140)}...` : normalized;
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
  if (!parts.length && target) {
    parts.push(target);
  }
  if (parsed.url) {
    parts.push(parsed.url);
  }
  if (parsed.text) {
    parts.push(normalizeText(parsed.text).slice(0, 80));
  }

  const summary = normalizeText(parts.join(" · "));
  return summary || normalized;
}

function formatIssueNotes(message, notes, hasStructuredCommand) {
  const pieces = [];
  const compactMessage = normalizeText(message);
  const compactNotes = normalizeText(notes);

  if (hasStructuredCommand && compactMessage) {
    pieces.push(`Message: ${compactMessage}`);
  }
  if (compactNotes) {
    pieces.push(compactNotes);
  }

  return pieces.length ? pieces.join("\n\n") : "-";
}

function buildIssuePayload() {
  const message = document.getElementById("message").value.trim();
  const rawCommand = document.getElementById("command").value.trim();
  const notes = document.getElementById("notes").value.trim();
  const command = rawCommand || message;
  const titleInput = document.getElementById("title").value.trim();
  const title = titleInput || deriveTitle(message || rawCommand);

  return {
    title,
    priority: document.getElementById("priority").value,
    target: document.getElementById("target").value,
    message,
    command,
    notes: formatIssueNotes(message, notes, Boolean(rawCommand))
  };
}

function buildIssueBody(payload) {
  return [
    "## Remote Command",
    "",
    "### Command",
    payload.command || "",
    "",
    "### Priority",
    payload.priority || "normal",
    "",
    "### Target",
    payload.target || "other",
    "",
    "### Notes",
    payload.notes || "-",
    "",
    "### Requested At",
    new Date().toLocaleString("ko-KR")
  ].join("\n");
}

function buildIssueUrl(payload) {
  const url = new URL(`https://github.com/${REPO_OWNER}/${REPO_NAME}/issues/new`);
  url.searchParams.set("template", ISSUE_TEMPLATE);
  url.searchParams.set("title", `${TITLE_PREFIX} ${payload.title}`);
  url.searchParams.set("labels", ISSUE_LABEL);
  url.searchParams.set("body", buildIssueBody(payload));
  return url.toString();
}

function issueMatches(issue) {
  const labels = Array.isArray(issue.labels) ? issue.labels.map((item) => item.name) : [];
  return labels.includes(ISSUE_LABEL) || (issue.title || "").startsWith(TITLE_PREFIX);
}

function timeLabel(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString("ko-KR");
}

function relativeTime(value) {
  if (!value) {
    return "";
  }

  const delta = Date.now() - new Date(value).getTime();
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) {
    return "방금 전";
  }
  if (minutes < 60) {
    return `${minutes}분 전`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}시간 전`;
  }
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
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
    status,
    mode: details.mode || "",
    action: details.action || "",
    timestamp: details.timestamp || "",
    summary: finalLine || (status === "success" ? "실행이 완료되었습니다." : "실행 상태가 업데이트되었습니다.")
  };
}

function extractLatestComment(comments) {
  if (!Array.isArray(comments) || comments.length === 0) {
    return null;
  }
  return comments[comments.length - 1];
}

async function fetchLatestComments(issues) {
  const targets = issues.filter((issue) => Number(issue.comments || 0) > 0).slice(0, THREAD_LIMIT);
  const entries = await Promise.all(
    targets.map(async (issue) => {
      try {
        const response = await fetch(issue.comments_url, {
          headers: {
            Accept: "application/vnd.github+json"
          }
        });
        const comments = await response.json();
        return [issue.number, extractLatestComment(comments)];
      } catch {
        return [issue.number, null];
      }
    })
  );

  return new Map(entries);
}

function buildIssueView(issue, latestComment) {
  const command = parseSection(issue.body, "Command");
  const priority = parseSection(issue.body, "Priority") || "normal";
  const target = parseSection(issue.body, "Target") || "other";
  const notes = parseSection(issue.body, "Notes");
  const executorSummary = parseExecutorComment(latestComment?.body || "");
  const commandSummary = summarizeCommand(command, target);

  const assistant = (() => {
    if (executorSummary) {
      return {
        tone: executorSummary.status === "success" ? "success" : "alert",
        state: executorSummary.status === "success" ? "완료" : "업데이트",
        title: normalizeText([executorSummary.mode, executorSummary.action].filter(Boolean).join(" · ")) || "Codex 실행 결과",
        body: executorSummary.summary,
        timestamp: executorSummary.timestamp || latestComment.created_at || issue.updated_at
      };
    }

    if (issue.state === "closed") {
      return {
        tone: "success",
        state: "완료",
        title: "작업 종료",
        body: issue.state_reason === "completed" ? "작업이 완료되어 닫혔습니다." : "이슈가 닫혔습니다.",
        timestamp: issue.closed_at || issue.updated_at
      };
    }

    return {
      tone: "pending",
      state: "대기",
      title: "Codex가 확인 중",
      body: "접수된 명령입니다. 실행이 끝나면 핵심 결과만 짧게 올립니다.",
      timestamp: issue.updated_at
    };
  })();

  return {
    issue,
    command,
    commandSummary,
    priority,
    target,
    notes,
    assistant
  };
}

function bubbleMeta(parts) {
  return parts.filter(Boolean).map((part) => `<span>${escapeHtml(part)}</span>`).join("");
}

function renderThreadBubble(view) {
  const userMeta = bubbleMeta([
    `#${view.issue.number}`,
    view.priority,
    view.target,
    relativeTime(view.issue.created_at)
  ]);
  const assistantMeta = bubbleMeta([
    view.assistant.state,
    relativeTime(view.assistant.timestamp),
    view.assistant.timestamp ? timeLabel(view.assistant.timestamp) : ""
  ]);
  const noteLine = normalizeText(view.notes && view.notes !== "-" ? view.notes : "");

  return `
    <article class="chat-row is-user">
      <div class="avatar avatar-user">You</div>
      <div class="bubble bubble-user">
        <div class="bubble-label">사용자 명령</div>
        <h3 class="bubble-title">${escapeHtml(view.issue.title.replace(TITLE_PREFIX, "").trim() || "remote command")}</h3>
        <p class="bubble-body">${escapeHtml(view.commandSummary)}</p>
        ${noteLine ? `<p class="bubble-note">${escapeHtml(noteLine)}</p>` : ""}
        <div class="bubble-meta">${userMeta}</div>
      </div>
    </article>
    <article class="chat-row is-bot">
      <div class="avatar avatar-bot">CX</div>
      <div class="bubble bubble-bot bubble-${escapeHtml(view.assistant.tone)}">
        <div class="bubble-label">Codex 요약</div>
        <h3 class="bubble-title">${escapeHtml(view.assistant.title)}</h3>
        <p class="bubble-body">${escapeHtml(view.assistant.body)}</p>
        <div class="bubble-meta">${assistantMeta}</div>
      </div>
    </article>
  `;
}

function renderQueueItem(view) {
  return `
    <article class="queue-item">
      <div class="queue-topline">
        <strong>#${view.issue.number}</strong>
        <span class="queue-priority priority-${escapeHtml(view.priority)}">${escapeHtml(view.priority)}</span>
      </div>
      <p>${escapeHtml(view.commandSummary)}</p>
      <small>${escapeHtml(view.target)} · ${escapeHtml(relativeTime(view.issue.created_at))}</small>
    </article>
  `;
}

function renderEmptyState(title, body) {
  return `
    <div class="thread-empty">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(body)}</p>
    </div>
  `;
}

function updateStats(views) {
  const total = views.length;
  const open = views.filter((item) => item.issue.state === "open").length;
  const done = views.filter((item) => item.issue.state === "closed").length;
  const urgent = views.filter((item) => item.priority === "urgent").length;

  document.getElementById("stat-total").textContent = String(total);
  document.getElementById("stat-open").textContent = String(open);
  document.getElementById("stat-done").textContent = String(done);
  document.getElementById("stat-urgent").textContent = String(urgent);
}

function updateSyncState(text) {
  document.getElementById("sync-state").textContent = text;
  document.getElementById("last-sync").textContent = relativeTime(new Date().toISOString()) || "방금 전";
}

function renderViews(views) {
  const threadRoot = document.getElementById("command-thread");
  const queueRoot = document.getElementById("queue-list");
  const threadViews = [...views].slice(0, THREAD_LIMIT).reverse();
  const queueViews = views.filter((item) => item.issue.state === "open").slice(0, 6);

  threadRoot.innerHTML = threadViews.length
    ? threadViews.map(renderThreadBubble).join("")
    : renderEmptyState("대화 없음", "아직 remote-command issue가 없습니다.");

  queueRoot.innerHTML = queueViews.length
    ? queueViews.map(renderQueueItem).join("")
    : '<p class="empty-note">현재 대기 중인 명령이 없습니다.</p>';
}

async function loadIssues() {
  if (loading) {
    return;
  }

  loading = true;
  updateSyncState("GitHub와 동기화 중");

  try {
    const response = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/issues?state=all&sort=updated&direction=desc&per_page=${RECENT_LIMIT}`,
      {
        headers: {
          Accept: "application/vnd.github+json"
        }
      }
    );
    const issues = await response.json();
    const filtered = Array.isArray(issues) ? issues.filter(issueMatches) : [];
    const commentsByIssue = await fetchLatestComments(filtered);
    const views = filtered.map((issue) => buildIssueView(issue, commentsByIssue.get(issue.number)));

    renderViews(views);
    updateStats(views);
    updateSyncState("GitHub와 동기화됨");
  } catch (error) {
    document.getElementById("command-thread").innerHTML = renderEmptyState(
      "불러오지 못함",
      "GitHub issue 또는 comment를 읽지 못했습니다. 잠시 후 다시 시도해 주세요."
    );
    document.getElementById("queue-list").innerHTML = '<p class="empty-note">큐를 읽지 못했습니다.</p>';
    updateSyncState("동기화 실패");
  } finally {
    loading = false;
  }
}

function applyQuickMenu(button) {
  const message = button.dataset.message || "";
  const command = button.dataset.command || "";
  const target = button.dataset.target || "other";
  const priority = button.dataset.priority || "normal";

  if (message) {
    document.getElementById("message").value = message;
  }
  if (command) {
    document.getElementById("command").value = command;
  }
  document.getElementById("target").value = target;
  document.getElementById("priority").value = priority;
}

document.getElementById("quick-menu").addEventListener("click", (event) => {
  const button = event.target.closest(".menu-chip");
  if (!button) {
    return;
  }
  applyQuickMenu(button);
});

document.getElementById("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = buildIssuePayload();
  if (!payload.title || !payload.command) {
    return;
  }
  window.open(buildIssueUrl(payload), "_blank", "noopener,noreferrer");
});

document.getElementById("copy-body").addEventListener("click", async () => {
  const payload = buildIssuePayload();
  await navigator.clipboard.writeText(buildIssueBody(payload));
});

document.getElementById("manual-refresh").addEventListener("click", () => {
  loadIssues();
});

loadIssues();
window.setInterval(loadIssues, POLL_INTERVAL_MS);
