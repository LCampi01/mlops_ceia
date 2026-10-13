/**
 * background.js – Service Worker (Manifest V3)
 *
 * Responsibilities:
 *  1. Create the "Detect phishing" context-menu entry (only on Gmail).
 *  2. On click, read the selected text forwarded by the content script,
 *     call POST /predictions on the configured API, and send the result
 *     back to the content script so it can render the modal.
 */

const MENU_ITEM_ID = "phishing-detector-check";
const DEFAULT_API_URL = "http://localhost:8800/";

// ── Context-menu setup ────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ITEM_ID,
    title: "Detectar phishing",
    contexts: ["selection"],
    documentUrlPatterns: ["https://mail.google.com/*"],
  });
});

// ── Helper: normalise base URL (ensure trailing slash) ───────────────────────

function buildEndpoint(base) {
  return base.replace(/\/?$/, "/") + "predictions";
}

// ── Context-menu click handler ────────────────────────────────────────────────

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ITEM_ID) return;

  const selectedText = info.selectionText?.trim();
  if (!selectedText) return;

  // Notify the content script that a request is in-flight so it can show a
  // loading indicator immediately (before the fetch resolves).
  chrome.tabs.sendMessage(tab.id, { type: "PHISHING_LOADING" });

  // Read settings from storage.
  const { apiUrl, apiKey } = await chrome.storage.sync.get({
    apiUrl: DEFAULT_API_URL,
    apiKey: "",
  });

  const endpoint = buildEndpoint(apiUrl);
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;

  let payload;
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({ email_text: selectedText }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorBody}`);
    }

    payload = await response.json();
  } catch (err) {
    chrome.tabs.sendMessage(tab.id, {
      type: "PHISHING_ERROR",
      error: err.message,
    });
    return;
  }

  chrome.tabs.sendMessage(tab.id, {
    type: "PHISHING_RESULT",
    result: payload,
  });
});
