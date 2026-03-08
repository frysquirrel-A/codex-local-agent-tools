const REPO_OWNER = "frysquirrel-A";
const REPO_NAME = "codex-local-agent-tools";
const ISSUE_TEMPLATE = "remote-command.md";
const ISSUE_LABEL = "remote-command";

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
  url.searchParams.set("title", `[remote] ${payload.title}`);
  url.searchParams.set("labels", ISSUE_LABEL);
  url.searchParams.set("body", buildIssueBody(payload));
  return url.toString();
}

async function loadIssues() {
  const issueList = document.getElementById("issue-list");
  try {
    const response = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/issues?state=open&labels=${ISSUE_LABEL}&per_page=10`);
    const issues = await response.json();
    if (!Array.isArray(issues) || issues.length === 0) {
      issueList.innerHTML = '<p class="muted">현재 열려 있는 원격 명령이 없습니다.</p>';
      return;
    }

    issueList.innerHTML = "";
    issues.forEach((issue) => {
      const card = document.createElement("article");
      card.className = "issue-card";
      card.innerHTML = `
        <h3><a href="${issue.html_url}" target="_blank" rel="noreferrer">#${issue.number} ${issue.title}</a></h3>
        <p>${(issue.body || "").slice(0, 220).replace(/\n/g, " ")}</p>
        <div class="meta">
          <span>opened by ${issue.user.login}</span>
          <span>${new Date(issue.created_at).toLocaleString("ko-KR")}</span>
        </div>
      `;
      issueList.appendChild(card);
    });
  } catch (error) {
    issueList.innerHTML = '<p class="muted">이슈 목록을 불러오지 못했습니다.</p>';
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
