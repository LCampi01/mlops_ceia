/**
 * content.js – Content script injected into Gmail pages.
 *
 * Responsibilities:
 *  1. Listen for messages from the background service worker.
 *  2. Render a modal overlay with the prediction result (or error).
 *  3. Provide a "Send feedback" button that calls POST /predictions/{id}/feedback.
 */

(function () {
  "use strict";

  // ── Inject extension stylesheet once ───────────────────────────────────────

  if (!document.getElementById("phishing-detector-style")) {
    const style = document.createElement("style");
    style.id = "phishing-detector-style";
    style.textContent = `
      #phishing-detector-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
        z-index: 2147483647;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: "Google Sans", Roboto, Arial, sans-serif;
      }

      #phishing-detector-modal {
        background: #fff;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.28);
        padding: 28px 32px 24px;
        max-width: 420px;
        width: 90vw;
        position: relative;
        animation: pd-slide-in 0.18s ease;
      }

      @keyframes pd-slide-in {
        from { transform: translateY(-18px); opacity: 0; }
        to   { transform: translateY(0);     opacity: 1; }
      }

      #phishing-detector-modal h2 {
        margin: 0 0 16px;
        font-size: 17px;
        font-weight: 600;
        color: #202124;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      #phishing-detector-modal .pd-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 15px;
        font-weight: 600;
        margin-bottom: 14px;
      }

      #phishing-detector-modal .pd-badge.phishing {
        background: #fce8e6;
        color: #c5221f;
      }

      #phishing-detector-modal .pd-badge.legitimate {
        background: #e6f4ea;
        color: #137333;
      }

      #phishing-detector-modal .pd-detail {
        font-size: 13px;
        color: #5f6368;
        margin-bottom: 18px;
        line-height: 1.5;
      }

      #phishing-detector-modal .pd-detail span {
        font-weight: 500;
        color: #202124;
      }

      #phishing-detector-modal .pd-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
      }

      #phishing-detector-modal button {
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: filter 0.15s;
      }

      #phishing-detector-modal button:hover {
        filter: brightness(0.93);
      }

      #phishing-detector-modal .pd-btn-close {
        background: #e8eaed;
        color: #202124;
      }

      #phishing-detector-modal .pd-btn-ok {
        background: #1a73e8;
        color: #fff;
      }

      #phishing-detector-modal .pd-btn-no {
        background: #ea4335;
        color: #fff;
      }

      #phishing-detector-modal .pd-btn-ok:disabled,
      #phishing-detector-modal .pd-btn-no:disabled {
        opacity: 0.55;
        cursor: default;
        filter: none;
      }

      #phishing-detector-modal .pd-feedback-sent {
        font-size: 12px;
        color: #137333;
        align-self: center;
      }

      #phishing-detector-modal .pd-loading {
        display: flex;
        align-items: center;
        gap: 12px;
        color: #5f6368;
        font-size: 14px;
      }

      #phishing-detector-modal .pd-spinner {
        width: 22px;
        height: 22px;
        border: 3px solid #e8eaed;
        border-top-color: #1a73e8;
        border-radius: 50%;
        animation: pd-spin 0.7s linear infinite;
        flex-shrink: 0;
      }

      @keyframes pd-spin {
        to { transform: rotate(360deg); }
      }

      #phishing-detector-modal .pd-error {
        color: #c5221f;
        font-size: 13px;
        line-height: 1.5;
      }

      #phishing-detector-modal .pd-close-x {
        position: absolute;
        top: 12px;
        right: 14px;
        background: none;
        border: none;
        font-size: 18px;
        color: #5f6368;
        cursor: pointer;
        padding: 2px 6px;
        border-radius: 4px;
        line-height: 1;
      }

      #phishing-detector-modal .pd-close-x:hover {
        background: #f1f3f4;
      }
    `;
    document.head.appendChild(style);
  }

  // ── Modal helpers ──────────────────────────────────────────────────────────

  function removeModal() {
    document.getElementById("phishing-detector-overlay")?.remove();
  }

  function createOverlay(innerHtml) {
    removeModal();
    const overlay = document.createElement("div");
    overlay.id = "phishing-detector-overlay";
    overlay.innerHTML = `<div id="phishing-detector-modal">${innerHtml}</div>`;
    // Click outside → close.
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) removeModal();
    });
    document.body.appendChild(overlay);
    return overlay;
  }

  // ── Show loading state ─────────────────────────────────────────────────────

  function showLoading() {
    createOverlay(`
      <button class="pd-close-x" title="Cerrar">✕</button>
      <h2>🔍 Phishing Detector</h2>
      <div class="pd-loading">
        <div class="pd-spinner"></div>
        Analizando el texto seleccionado…
      </div>
    `);
    document
      .querySelector("#phishing-detector-modal .pd-close-x")
      ?.addEventListener("click", removeModal);
  }

  // ── Show result ────────────────────────────────────────────────────────────

  function showResult(result) {
    const isPhishing = result.prediction_code === 1;
    const badgeClass = isPhishing ? "phishing" : "legitimate";
    const badgeIcon = isPhishing ? "🚨" : "✅";
    const badgeText = isPhishing ? "Phishing detectado" : "Correo legítimo";
    const pct = (result.phishing_probability * 100).toFixed(1);

    const overlay = createOverlay(`
      <button class="pd-close-x" title="Cerrar">✕</button>
      <h2>🔍 Phishing Detector</h2>
      <div class="pd-badge ${badgeClass}">${badgeIcon} ${badgeText}</div>
      <div class="pd-detail">
        Probabilidad de phishing: <span>${pct}%</span><br>
        Versión del modelo: <span>${result.model_version}</span><br>
        ID de predicción: <span>${result.prediction_id}</span>
      </div>
      <div class="pd-actions">
        <span class="pd-feedback-sent" style="display:none">¡Gracias por tu feedback!</span>
        <button class="pd-btn-ok"  title="La predicción fue correcta">👍 Correcto</button>
        <button class="pd-btn-no"  title="La predicción fue incorrecta">👎 Incorrecto</button>
        <button class="pd-btn-close">Cerrar</button>
      </div>
    `);

    overlay.querySelector(".pd-close-x").addEventListener("click", removeModal);
    overlay.querySelector(".pd-btn-close").addEventListener("click", removeModal);

    async function sendFeedback(value) {
      const okBtn = overlay.querySelector(".pd-btn-ok");
      const noBtn = overlay.querySelector(".pd-btn-no");
      okBtn.disabled = true;
      noBtn.disabled = true;

      try {
        const { apiUrl, apiKey } = await new Promise((resolve) =>
          chrome.storage.sync.get({ apiUrl: "http://localhost:8800/", apiKey: "" }, resolve)
        );
        const base = apiUrl.replace(/\/?$/, "/");
        const endpoint = `${base}predictions/${result.prediction_id}/feedback`;
        const headers = { "Content-Type": "application/json" };
        if (apiKey) headers["X-API-Key"] = apiKey;

        const resp = await fetch(endpoint, {
          method: "POST",
          headers,
          body: JSON.stringify({ feedback: value }),
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        overlay.querySelector(".pd-feedback-sent").style.display = "inline";
      } catch (err) {
        okBtn.disabled = false;
        noBtn.disabled = false;
        alert(`Error al enviar feedback: ${err.message}`);
      }
    }

    overlay.querySelector(".pd-btn-ok").addEventListener("click", () => sendFeedback("OK"));
    overlay.querySelector(".pd-btn-no").addEventListener("click", () => sendFeedback("NO"));
  }

  // ── Show error ─────────────────────────────────────────────────────────────

  function showError(message) {
    const overlay = createOverlay(`
      <button class="pd-close-x" title="Cerrar">✕</button>
      <h2>🔍 Phishing Detector</h2>
      <p class="pd-error">
        ⚠️ No se pudo obtener la predicción:<br><br>
        <strong>${escapeHtml(message)}</strong><br><br>
        Verificá que la API esté en línea y que la URL esté bien configurada en las opciones de la extensión.
      </p>
      <div class="pd-actions">
        <button class="pd-btn-close">Cerrar</button>
      </div>
    `);
    overlay.querySelector(".pd-close-x").addEventListener("click", removeModal);
    overlay.querySelector(".pd-btn-close").addEventListener("click", removeModal);
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Message listener ───────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((message) => {
    switch (message.type) {
      case "PHISHING_LOADING":
        showLoading();
        break;
      case "PHISHING_RESULT":
        showResult(message.result);
        break;
      case "PHISHING_ERROR":
        showError(message.error);
        break;
    }
  });
})();
