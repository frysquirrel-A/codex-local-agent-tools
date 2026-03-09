const HEARTBEAT_MS = 250;
const CLIENT_ID_KEY = "study-live-bridge-client-id";
const LLM_RESPONSE_STATE = new Map();
const PAGE_RELAY_ALLOWED_ORIGIN = "https://frysquirrel-a.github.io";
const PAGE_RELAY_ALLOWED_PATH_PREFIX = "/codex-local-agent-tools";
const PAGE_RELAY_REQUEST_SOURCE = "codex-page-relay";
const PAGE_RELAY_RESPONSE_SOURCE = "study-live-relay-bridge";

function getClientId() {
  let value = sessionStorage.getItem(CLIENT_ID_KEY);
  if (!value) {
    value = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(CLIENT_ID_KEY, value);
  }
  return value;
}

function pageState() {
  return {
    clientId: getClientId(),
    url: location.href,
    title: document.title,
    active: document.visibilityState === "visible" && document.hasFocus(),
    focused: document.hasFocus(),
    timestamp: Date.now()
  };
}

function isVisible(el) {
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
}

function findEditable(selector) {
  if (selector) {
    const direct = document.querySelector(selector);
    if (direct) {
      return direct;
    }
  }

  const active = document.activeElement;
  if (active && active !== document.body) {
    const editable =
      active.tagName === "TEXTAREA" ||
      active.tagName === "INPUT" ||
      active.isContentEditable ||
      active.getAttribute("role") === "textbox";
    if (editable) {
      return active;
    }
  }

  const all = Array.from(document.querySelectorAll("textarea, input, [contenteditable='true'], [role='textbox']"));
  const visible = all.filter((el) => isVisible(el) && !el.disabled && !el.readOnly);
  return visible[0] || null;
}

function setElementText(el, text) {
  el.focus();
  if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) {
      setter.call(el, text);
    } else {
      el.value = text;
    }
  } else {
    el.textContent = "";
    el.appendChild(document.createTextNode(text));
  }

  el.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    cancelable: true,
    data: text,
    inputType: "insertText"
  }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function domSummary() {
  const clickable = Array.from(document.querySelectorAll("button, a, [role='button']"))
    .filter((el) => isVisible(el))
    .slice(0, 30)
    .map((el) => ({
      tag: el.tagName,
      text: (el.innerText || el.textContent || "").trim().slice(0, 80),
      selector: el.id ? `#${el.id}` : ""
    }));

  const inputs = Array.from(document.querySelectorAll("textarea, input, [contenteditable='true'], [role='textbox']"))
    .filter((el) => isVisible(el))
    .slice(0, 20)
    .map((el) => ({
      tag: el.tagName,
      placeholder: el.getAttribute("placeholder") || "",
      aria: el.getAttribute("aria-label") || "",
      role: el.getAttribute("role") || ""
    }));

  return {
    title: document.title,
    url: location.href,
    clickable,
    inputs
  };
}

function queryElements(selector, maxElements) {
  const nodes = Array.from(document.querySelectorAll(selector || "*"))
    .filter((el) => isVisible(el))
    .slice(0, Math.max(Number(maxElements || 20), 1));

  return nodes.map((el) => ({
    tag: el.tagName,
    id: el.id || "",
    className: typeof el.className === "string" ? el.className : "",
    text: normalizeText(el.innerText || el.textContent || "").slice(0, 200),
    aria: el.getAttribute("aria-label") || "",
    title: el.getAttribute("title") || "",
    role: el.getAttribute("role") || "",
    placeholder: el.getAttribute("placeholder") || "",
    dataTooltip: el.getAttribute("data-tooltip") || ""
  }));
}

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function clipText(text, maxChars, preferStart = false) {
  if (!maxChars || text.length <= maxChars) {
    return text;
  }
  return preferStart ? text.slice(0, maxChars) : text.slice(-maxChars);
}

function hashText(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function visibleText(selector, maxChars) {
  const root = selector ? document.querySelector(selector) : document.body;
  if (!root) {
    return "";
  }

  const text = normalizeText(root.innerText || root.textContent || "");
  if (!maxChars || text.length <= maxChars) {
    return text;
  }
  return text.slice(-maxChars);
}

function findMatchingElements(selectors, root = document) {
  const list = Array.isArray(selectors) ? selectors.filter(Boolean) : [];
  const seen = new Set();
  const matches = [];

  for (const selector of list) {
    try {
      const nodes = root.querySelectorAll(selector);
      for (const node of nodes) {
        if (seen.has(node) || !isVisible(node)) {
          continue;
        }
        seen.add(node);
        matches.push(node);
      }
    } catch {
      // Ignore invalid selectors and continue to the next candidate.
    }
  }

  return matches;
}

function hasVisibleSelector(selectors, root = document) {
  return findMatchingElements(selectors, root).length > 0;
}

function extractResponseText(node, startMarker) {
  const raw = normalizeText(node?.innerText || node?.textContent || "");
  if (!startMarker) {
    return raw;
  }

  const index = raw.lastIndexOf(startMarker);
  if (index < 0) {
    return "";
  }
  return raw.slice(index).trim();
}

function responseNodeId(node, fallbackIndex) {
  if (!node) {
    return "";
  }

  const container = node.closest("[data-message-id], [data-testid], [data-response-id], article, model-response") || node;
  return (
    container.getAttribute("data-message-id") ||
    container.getAttribute("data-testid") ||
    container.getAttribute("data-response-id") ||
    container.id ||
    `${container.tagName}:${fallbackIndex}`
  );
}

function llmResponseWatchKey(command) {
  const rootSelector = command.selector || "";
  const messageSelectors = Array.isArray(command.messageSelectors) ? command.messageSelectors.join("|") : "";
  const busySelectors = Array.isArray(command.busySelectors) ? command.busySelectors.join("|") : "";
  const startMarker = command.startMarker || "";
  return `${location.hostname}::${rootSelector}::${messageSelectors}::${busySelectors}::${startMarker}`;
}

function llmResponseMatchesBaseline(snapshot, command) {
  const baselineMessageId = command.afterMessageId || "";
  const baselineTextHash = command.afterTextHash || "";
  if (!baselineMessageId && !baselineTextHash) {
    return false;
  }
  if (baselineMessageId && snapshot.messageId !== baselineMessageId) {
    return false;
  }
  if (baselineTextHash && snapshot.textHash !== baselineTextHash) {
    return false;
  }
  return true;
}

function llmResponseSnapshot(command) {
  const root = command.selector ? document.querySelector(command.selector) : document.body;
  if (!root) {
    return {
      rootFound: false,
      found: false,
      busy: false,
      messageCount: 0,
      messageId: "",
      fullText: "",
      text: "",
      textHash: hashText("")
    };
  }

  const matches = findMatchingElements(command.messageSelectors, root);
  const node = matches.length ? matches[matches.length - 1] : null;
  const fullText = node ? extractResponseText(node, command.startMarker || "") : "";
  const preferStart = Boolean(command.startMarker);

  return {
    rootFound: true,
    found: Boolean(node),
    busy: hasVisibleSelector(command.busySelectors, root),
    messageCount: matches.length,
    messageId: responseNodeId(node, matches.length),
    fullText,
    text: clipText(fullText, command.maxChars || 0, preferStart),
    textHash: hashText(fullText)
  };
}

function probeLlmResponse(command) {
  const now = Date.now();
  const quietMsTarget = Math.max(Number(command.quietMs || 0), 250);
  const waitForText = normalizeText(command.waitForText || "");
  const snapshot = llmResponseSnapshot(command);
  const key = llmResponseWatchKey(command);
  const state = LLM_RESPONSE_STATE.get(key) || {
    messageId: "",
    textHash: "",
    busy: false,
    lastChangeTs: now
  };

  const changed =
    snapshot.messageId !== state.messageId ||
    snapshot.textHash !== state.textHash ||
    snapshot.busy !== state.busy;

  if (changed) {
    state.lastChangeTs = now;
  }

  state.messageId = snapshot.messageId;
  state.textHash = snapshot.textHash;
  state.busy = snapshot.busy;
  LLM_RESPONSE_STATE.set(key, state);

  const quietMs = now - state.lastChangeTs;
  const baselineMatched = llmResponseMatchesBaseline(snapshot, command);
  const textMatched = !waitForText || snapshot.fullText.includes(waitForText);
  const done =
    snapshot.found &&
    !baselineMatched &&
    textMatched &&
    !snapshot.busy &&
    quietMs >= quietMsTarget &&
    snapshot.fullText.length > 0;

  const response = {
    ok: true,
    action: "llm_response_probe",
    rootFound: snapshot.rootFound,
    found: snapshot.found,
    busy: snapshot.busy,
    done,
    baselineMatched,
    textMatched,
    quietMs,
    quietMsTarget,
    messageCount: snapshot.messageCount,
    messageId: snapshot.messageId,
    textLength: snapshot.fullText.length,
    textHash: snapshot.textHash,
    updatedAt: state.lastChangeTs
  };

  if (command.includeText) {
    response.text = snapshot.text;
  }

  return response;
}

function findClickableByText(text, contains) {
  const target = normalizeText(text);
  const all = Array.from(document.querySelectorAll("button, a, [role='button']"));
  const visible = all.filter((el) => isVisible(el));

  return visible.find((el) => {
    const current = normalizeText(el.innerText || el.textContent || el.getAttribute("aria-label") || "");
    if (!current) {
      return false;
    }
    return contains ? current.includes(target) : current === target;
  }) || null;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function commandExpired(command) {
  const deadline = Number(command?.deadlineTs || 0);
  if (!Number.isFinite(deadline) || deadline <= 0) {
    return false;
  }
  return (Date.now() / 1000) >= deadline;
}

async function waitForSendTarget(selectors, timeoutMs = 800) {
  const list = Array.isArray(selectors) ? selectors.filter(Boolean) : [];
  if (!list.length) {
    return null;
  }

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of list) {
      const candidate = document.querySelector(selector);
      if (candidate && isVisible(candidate) && !candidate.disabled) {
        return { element: candidate, selector };
      }
    }
    await sleep(50);
  }

  return null;
}

function sendRuntimeMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, reason: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, reason: "No runtime response." });
    });
  });
}

function pageRelayBridgeAllowed() {
  return location.origin === PAGE_RELAY_ALLOWED_ORIGIN &&
    location.pathname.startsWith(PAGE_RELAY_ALLOWED_PATH_PREFIX);
}

function postPageRelayMessage(payload) {
  window.postMessage({
    source: PAGE_RELAY_RESPONSE_SOURCE,
    ...payload
  }, location.origin);
}

async function handlePageRelayMessage(event) {
  if (event.source !== window || !pageRelayBridgeAllowed()) {
    return;
  }

  const message = event.data;
  if (!message || message.source !== PAGE_RELAY_REQUEST_SOURCE || message.type !== "relay-request") {
    return;
  }

  const requestId = String(message.requestId || "").trim();
  if (!requestId) {
    return;
  }

  const payload = await sendRuntimeMessage({
    type: "relayFetch",
    request: message.request || {}
  });

  postPageRelayMessage({
    type: "relay-response",
    requestId,
    payload
  });
}

function installPageRelayBridge() {
  if (!pageRelayBridgeAllowed()) {
    return;
  }

  window.addEventListener("message", (event) => {
    handlePageRelayMessage(event).catch((error) => {
      const message = event?.data || {};
      const requestId = String(message.requestId || "").trim();
      if (!requestId) {
        return;
      }
      postPageRelayMessage({
        type: "relay-response",
        requestId,
        payload: {
          ok: false,
          reason: String(error)
        }
      });
    });
  });

  postPageRelayMessage({
    type: "relay-ready"
  });
}

async function executeCommand(command) {
  if (!command || !command.action) {
    return { ok: false, reason: "Missing action." };
  }

  if (command.action === "ping") {
    return { ok: true, action: "ping", page: pageState() };
  }

  if (command.action === "dom_summary") {
    return { ok: true, action: "dom_summary", summary: domSummary() };
  }

  if (command.action === "query_elements") {
    if (!command.selector) {
      return { ok: false, reason: "query_elements requires selector." };
    }
    return {
      ok: true,
      action: "query_elements",
      elements: queryElements(command.selector, command.maxElements || 20)
    };
  }

  if (command.action === "visible_text") {
    return {
      ok: true,
      action: "visible_text",
      text: visibleText(command.selector || "", command.maxChars || 4000)
    };
  }

  if (command.action === "llm_response_probe") {
    if (!Array.isArray(command.messageSelectors) || command.messageSelectors.length === 0) {
      return { ok: false, reason: "llm_response_probe requires messageSelectors." };
    }
    return probeLlmResponse(command);
  }

  if (command.action === "llm_read_response") {
    if (!Array.isArray(command.messageSelectors) || command.messageSelectors.length === 0) {
      return { ok: false, reason: "llm_read_response requires messageSelectors." };
    }
    return {
      ...probeLlmResponse({ ...command, includeText: true }),
      action: "llm_read_response"
    };
  }

  if (command.action === "llm_wait_response") {
    if (!Array.isArray(command.messageSelectors) || command.messageSelectors.length === 0) {
      return { ok: false, reason: "llm_wait_response requires messageSelectors." };
    }

    const timeoutMs = Math.max(Number(command.timeoutMs || 0), 500);
    const pollMs = Math.max(Number(command.pollMs || 0), 100);
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      const probe = probeLlmResponse({ ...command, includeText: true });
      if (probe.done) {
        return {
          ...probe,
          action: "llm_wait_response"
        };
      }
      await sleep(pollMs);
    }

    return {
      ...probeLlmResponse({ ...command, includeText: true }),
      ok: false,
      action: "llm_wait_response",
      reason: "Timed out waiting for the last assistant response to stabilize."
    };
  }

  if (command.action === "navigate") {
    location.href = command.url;
    return { ok: true, action: "navigate", url: command.url };
  }

  if (command.action === "set_text") {
    const target = findEditable(command.selector || "");
    if (!target) {
      return { ok: false, reason: "No editable element found." };
    }
    setElementText(target, command.text || "");
    return {
      ok: true,
      action: "set_text",
      tag: target.tagName,
      placeholder: target.getAttribute("placeholder") || "",
      aria: target.getAttribute("aria-label") || ""
    };
  }

  if (command.action === "prompt_send") {
    const target = findEditable(command.selector || "");
    if (!target) {
      return { ok: false, reason: "No editable element found." };
    }

    setElementText(target, command.text || "");

    const sendSelectors = Array.isArray(command.sendSelectors) ? command.sendSelectors : [];
    const sendTarget = await waitForSendTarget(sendSelectors, command.sendTimeoutMs || 800);

    if (sendTarget) {
      sendTarget.element.click();
      return {
        ok: true,
        action: "prompt_send",
        tag: target.tagName,
        placeholder: target.getAttribute("placeholder") || "",
        aria: target.getAttribute("aria-label") || "",
        sendSelector: sendTarget.selector
      };
    }

    target.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Enter",
      code: "Enter",
      bubbles: true,
      cancelable: true
    }));
    target.dispatchEvent(new KeyboardEvent("keyup", {
      key: "Enter",
      code: "Enter",
      bubbles: true,
      cancelable: true
    }));

    return {
      ok: true,
      action: "prompt_send",
      tag: target.tagName,
      placeholder: target.getAttribute("placeholder") || "",
      aria: target.getAttribute("aria-label") || "",
      sendSelector: ""
    };
  }

  if (command.action === "click") {
    const target = document.querySelector(command.selector || "");
    if (!target) {
      return { ok: false, reason: "Selector not found." };
    }
    target.click();
    return { ok: true, action: "click", selector: command.selector };
  }

  if (command.action === "click_text") {
    const target = findClickableByText(command.text || "", Boolean(command.contains));
    if (!target) {
      return { ok: false, reason: "Clickable text not found." };
    }
    target.click();
    return {
      ok: true,
      action: "click_text",
      text: normalizeText(target.innerText || target.textContent || target.getAttribute("aria-label") || "")
    };
  }

  return { ok: false, reason: `Unsupported action: ${command.action}` };
}

async function heartbeat() {
  try {
    const payload = await sendRuntimeMessage({
      type: "heartbeat",
      state: pageState()
    });
    if (!payload?.ok) {
      return;
    }
    if (payload.command) {
      let result;
      try {
        result = commandExpired(payload.command)
          ? { ok: false, expired: true, reason: "Command expired before page execution." }
          : await executeCommand(payload.command);
      } catch (error) {
        result = {
          ok: false,
          errorType: "page_exception",
          reason: String(error),
          action: payload.command.action || ""
        };
      }
      await sendRuntimeMessage({
        type: "result",
        clientId: getClientId(),
        commandId: payload.command.id,
        result
      });
    }
  } catch (error) {
    // Server is optional; retry on next interval.
  }
}

installPageRelayBridge();
setInterval(heartbeat, HEARTBEAT_MS);
heartbeat();
