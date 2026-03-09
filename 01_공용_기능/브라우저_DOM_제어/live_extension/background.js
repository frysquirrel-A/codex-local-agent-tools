const SERVER_BASE = "http://127.0.0.1:8765";
async function requestJson(path, payload) {
  const response = await fetch(`${SERVER_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const raw = await response.text();
  let data = {};
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = { ok: false, reason: raw };
    }
  }

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      reason: data.reason || `HTTP ${response.status}`,
      ...data
    };
  }

  return data;
}

async function relayFetch(request) {
  return requestJson("/relay", request || {});
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === "heartbeat") {
      const payload = await requestJson("/heartbeat", message.state || {});
      sendResponse(payload);
      return;
    }

    if (message?.type === "result") {
      const payload = await requestJson("/result", {
        clientId: message.clientId,
        commandId: message.commandId,
        result: message.result
      });
      sendResponse(payload);
      return;
    }

    if (message?.type === "relayFetch") {
      const payload = await relayFetch(message.request || {});
      sendResponse(payload);
      return;
    }

    sendResponse({ ok: false, reason: "Unknown runtime message." });
  })().catch((error) => {
    sendResponse({ ok: false, reason: String(error) });
  });

  return true;
});
