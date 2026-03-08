const REPO_OWNER = "frysquirrel-A";
const REPO_NAME = "codex-local-agent-tools";
const ISSUE_TEMPLATE = "remote-command.md";
const ISSUE_LABEL = "remote-command";
const TITLE_PREFIX = "[remote]";
const RECENT_LIMIT = 20;

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

function parseSection(body, heading) {
  if (!body) {
    return "";
  }

  const pattern = new RegExp(`###\\s+${heading}\\s*\\n([\\s\\S]*?)(?=\\n###\\s+|$)`, "m");
  const match = body.match(pattern);
  return match ? match[1].trim() : "";
}

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function stateLabel(state) {
  if (state === "closed") {
    return "완료/종료";
  }
  return "열림";
}

function issueMatches(issue) {
  const labels = Array.isArray(issue.labels) ? issue.labels.map((item) => item.name) : [];
  return labels.includes(ISSUE_LABEL) || (issue.title || "").startsWith(TITLE_PREFIX);
}

function buildMetaPill(text, extraClass = "") {
  return `<span class="pill ${extraClass}">${text}</span>`;
}

function renderIssueCard(issue) {
  const priority = parseSection(issue.body, "Priority") || "normal";
  const target = parseSection(issue.body, "Target") || "other";
  const command = normalizeText(parseSection(issue.body, "Command"));
  const preview = command || normalizeText(issue.body).slice(0, 220) || "내용 없음";
  const stateClass = issue.state === "closed" ? "is-closed" : "is-open";
  const comments = Number(issue.comments || 0);

  const pills = [
    buildMetaPill(stateLabel(issue.state), `state-pill ${stateClass}`),
    buildMetaPill(`priority ${priority}`),
    buildMetaPill(`target ${target}`),
    buildMetaPill(`comments ${comments}`)
  ].join("");

  return `
    <article class="issue-card">
      <div class="issue-head">
        <h3><a href="${issue.html_url}" target="_blank" rel="noreferrer">#${issue.number} ${issue.title}</a></h3>
        <div class="pill-row">${pills}</div>
      </div>
      <p class="issue-preview">${preview}</p>
      <div class="meta">
        <span>opened by ${issue.user.login}</span>
        <span>created ${new Date(issue.created_at).toLocaleString("ko-KR")}</span>
        <span>updated ${new Date(issue.updated_at).toLocaleString("ko-KR")}</span>
      </div>
    </article>
  `;
}

async function loadIssues() {
  const issueList = document.getElementById("issue-list");
  try {
    const response = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/issues?state=all&sort=created&direction=desc&per_page=${RECENT_LIMIT}`);
    const issues = await response.json();
    const filtered = Array.isArray(issues) ? issues.filter(issueMatches) : [];

    if (filtered.length === 0) {
      issueList.innerHTML = '<p class="muted">최근 원격 명령 이슈가 아직 없습니다.</p>';
      return;
    }

    issueList.innerHTML = filtered.map(renderIssueCard).join("");
  } catch (error) {
    issueList.innerHTML = '<p class="muted">원격 명령 목록을 불러오지 못했습니다.</p>';
  }
}

document.getElementById("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = {
    title: document.getElementById("title").value.trim(),
    priority: document.getElementById("priority").value,
    target: document.getElementById("target").value,
    command: document.getElementById("command").value.trim(),
    notes: document.getElementById("notes").value.trim()
  };

  if (!payload.title || !payload.command) {
    return;
  }

  window.open(buildIssueUrl(payload), "_blank", "noopener,noreferrer");
});

document.getElementById("copy-body").addEventListener("click", async () => {
  const payload = {
    title: document.getElementById("title").value.trim() || "remote command",
    priority: document.getElementById("priority").value,
    target: document.getElementById("target").value,
    command: document.getElementById("command").value.trim(),
    notes: document.getElementById("notes").value.trim()
  };

  await navigator.clipboard.writeText(buildIssueBody(payload));
});

loadIssues();
