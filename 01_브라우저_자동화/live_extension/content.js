const HEARTBEAT_MS = 250;
const CLIENT_ID_KEY = "study-live-bridge-client-id";

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

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
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

  if (command.action === "visible_text") {
    return {
      ok: true,
      action: "visible_text",
      text: visibleText(command.selector || "", command.maxChars || 4000)
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
      const result = await executeCommand(payload.command);
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

setInterval(heartbeat, HEARTBEAT_MS);
heartbeat();
