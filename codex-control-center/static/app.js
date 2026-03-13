const byId = (id) => document.getElementById(id);

function makeStatItem(key, value) {
  const wrapper = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = key;
  dd.textContent = Array.isArray(value) ? value.join(", ") : String(value);
  wrapper.append(dt, dd);
  return wrapper;
}

function renderOverview(snapshot) {
  const container = byId("overviewCards");
  const template = byId("overviewCardTemplate");
  container.innerHTML = "";

  const cards = [
    {
      label: "Watchdog",
      value: snapshot.overview.watchdog.status || "-",
      detail: `task=${snapshot.overview.watchdog.taskId || "-"} / decision=${snapshot.overview.watchdog.decision || "-"}`,
    },
    {
      label: "Queue",
      value: snapshot.overview.watchdog.queueEmpty ? "비어 있음" : "작업 있음",
      detail: `queueDecision=${snapshot.overview.watchdog.queueDecision || "-"}`,
    },
    {
      label: "Helpers",
      value: `${snapshot.overview.helpers.pendingAssignmentCount} pending`,
      detail: `stale=${snapshot.overview.helpers.staleAssignmentCount}, handoff=${snapshot.overview.helpers.handoffCount}`,
    },
    {
      label: "Scheduler",
      value: `${snapshot.overview.scheduler.openJobCount} open`,
      detail: `jobCount=${snapshot.overview.scheduler.jobCount}`,
    },
    {
      label: "Gmail",
      value: snapshot.overview.gmail.running ? "running" : "idle",
      detail: snapshot.overview.gmail.skipReason || snapshot.overview.gmail.updatedAt || "-",
    },
  ];

  for (const card of cards) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".card-label").textContent = card.label;
    node.querySelector(".card-value").textContent = card.value;
    node.querySelector(".card-detail").textContent = card.detail;
    container.appendChild(node);
  }
}

function renderAlerts(snapshot) {
  const container = byId("alerts");
  container.innerHTML = "";

  if (!snapshot.alerts.length) {
    const empty = document.createElement("div");
    empty.className = "alert";
    empty.innerHTML = "<strong>현재 즉시 조치 경고 없음</strong><p>watchdog와 queue는 현재 읽기 기준으로 안정 상태입니다.</p>";
    container.appendChild(empty);
    return;
  }

  for (const alert of snapshot.alerts) {
    const node = document.createElement("div");
    node.className = `alert ${alert.level || ""}`;
    node.innerHTML = `<strong>${alert.title}</strong><p>${alert.detail}</p>`;
    container.appendChild(node);
  }
}

function renderThreads(snapshot) {
  const container = byId("threadGrid");
  const template = byId("threadCardTemplate");
  container.innerHTML = "";

  for (const thread of snapshot.threads) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".thread-kind").textContent = thread.kind;
    node.querySelector(".thread-title").textContent = thread.displayName || thread.title;
    node.querySelector(".thread-role").textContent = thread.role || "-";

    const stats = node.querySelector(".thread-stats");
    const entries = Object.entries(thread.stats || {});
    if (!entries.length) {
      stats.appendChild(makeStatItem("상태", "추가 통계 없음"));
    } else {
      for (const [key, value] of entries.slice(0, 6)) {
        stats.appendChild(makeStatItem(key, value));
      }
    }
    container.appendChild(node);
  }
}

function renderFlows(snapshot) {
  const container = byId("messageFlows");
  const flowTemplate = byId("flowTemplate");
  const assignmentTemplate = byId("assignmentTemplate");
  container.innerHTML = "";

  for (const flow of snapshot.messageFlows) {
    const node = flowTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".flow-id").textContent = flow.handoffId;
    node.querySelector(".flow-title").textContent = flow.sourceTitle || "최근 handoff";
    node.querySelector(".flow-route").textContent = flow.routeLabel || flow.route || "route 없음";
    node.querySelector(".flow-task").textContent = flow.taskPreview || "-";
    node.querySelector(".flow-notes").textContent = flow.sourceNotes || flow.path;

    const assignmentList = node.querySelector(".assignment-list");
    for (const assignment of flow.assignments) {
      const item = assignmentTemplate.content.firstElementChild.cloneNode(true);
      item.querySelector(".assignment-helper").textContent = assignment.helperTitle || "helper";
      item.querySelector(".assignment-status").textContent = `${assignment.status || "-"} / ${assignment.step || "-"}`;
      item.querySelector(".assignment-role").textContent = assignment.helperRole || "-";
      item.querySelector(".assignment-response").textContent = assignment.responsePreview || assignment.requestPreview || "-";
      item.querySelector(".assignment-meta").textContent = `thread=${assignment.helperThreadId || "-"} / updatedAt=${assignment.updatedAt || "-"}`;
      assignmentList.appendChild(item);
    }

    container.appendChild(node);
  }
}

function renderPaths(snapshot) {
  const container = byId("paths");
  container.innerHTML = "";
  for (const [label, path] of Object.entries(snapshot.paths || {})) {
    const li = document.createElement("li");
    li.textContent = `${label}: ${path}`;
    container.appendChild(li);
  }
}

async function loadSnapshot() {
  const response = await fetch("/api/snapshot", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`snapshot request failed: ${response.status}`);
  }
  return response.json();
}

async function refresh() {
  try {
    const snapshot = await loadSnapshot();
    byId("generatedAt").textContent = snapshot.generatedAt;
    renderOverview(snapshot);
    renderAlerts(snapshot);
    renderThreads(snapshot);
    renderFlows(snapshot);
    renderPaths(snapshot);
  } catch (error) {
    byId("alerts").innerHTML = `<div class="alert critical"><strong>데이터 로드 실패</strong><p>${error.message}</p></div>`;
  }
}

refresh();
setInterval(refresh, 5000);
