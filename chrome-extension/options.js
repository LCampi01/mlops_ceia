/**
 * options.js – Settings page logic.
 *
 * Saves / restores API URL and API Key using chrome.storage.sync so that
 * settings are shared across devices when the user is signed into Chrome.
 */

const DEFAULT_API_URL = "http://localhost:8800/";

const apiUrlInput = document.getElementById("api-url");
const apiKeyInput = document.getElementById("api-key");
const btnSave     = document.getElementById("btn-save");
const btnReset    = document.getElementById("btn-reset");
const statusEl    = document.getElementById("status");

// ── Load saved settings on page open ─────────────────────────────────────────

chrome.storage.sync.get({ apiUrl: DEFAULT_API_URL, apiKey: "" }, ({ apiUrl, apiKey }) => {
  apiUrlInput.value = apiUrl;
  apiKeyInput.value = apiKey;
});

// ── Save ──────────────────────────────────────────────────────────────────────

btnSave.addEventListener("click", () => {
  const apiUrl = apiUrlInput.value.trim();
  const apiKey = apiKeyInput.value.trim();

  if (!apiUrl) {
    showStatus("La URL de la API no puede estar vacía.", true);
    return;
  }

  try {
    new URL(apiUrl);
  } catch {
    showStatus("La URL ingresada no es válida.", true);
    return;
  }

  chrome.storage.sync.set({ apiUrl, apiKey }, () => {
    showStatus("✓ Configuración guardada.");
  });
});

// ── Reset to defaults ─────────────────────────────────────────────────────────

btnReset.addEventListener("click", () => {
  apiUrlInput.value = DEFAULT_API_URL;
  apiKeyInput.value = "";
  chrome.storage.sync.set({ apiUrl: DEFAULT_API_URL, apiKey: "" }, () => {
    showStatus("✓ Valores restablecidos.");
  });
});

// ── Status helper ─────────────────────────────────────────────────────────────

function showStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className   = isError ? "error" : "";
  statusEl.style.display = "inline";
  clearTimeout(showStatus._timer);
  showStatus._timer = setTimeout(() => {
    statusEl.style.display = "none";
  }, 3000);
}
