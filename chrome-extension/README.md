# Phishing Detector – Chrome Extension

Chrome extension that integrates with the **Phishing Detector FastAPI** service to analyse email text directly from Gmail via a right-click context menu.

---

## Features

| Feature | Detail |
|---|---|
| **Gmail-only** | The context menu entry and modal only appear on `mail.google.com`. |
| **Right-click → Detect** | Select any text in an email, right-click, and choose **"Detectar phishing"**. |
| **Result modal** | Shows whether the text is *Phishing* or *Legítimo*, the probability, model version, and prediction ID. |
| **Feedback buttons** | Send 👍 *Correcto* / 👎 *Incorrecto* feedback directly to the API (`POST /predictions/{id}/feedback`). |
| **Configurable** | API URL and API Key are stored in `chrome.storage.local` (only in this browser). |

---

## Project structure

```
chrome-extension/
├── manifest.json        # MV3 manifest
├── background.js        # Service worker – context menu + API calls
├── content.js           # Content script – modal UI injected into Gmail
├── options.html         # Settings page (popup + standalone tab)
├── options.js           # Settings page logic
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

---

## Installation (developer mode)

1. Open Chrome and navigate to `chrome://extensions`.

2. Enable **Developer mode** (toggle in the top-right corner).

3. Click **Load unpacked** and select the `chrome-extension/` directory.

4. The extension icon appears in the toolbar. Click it (or go to **Options**) to configure the API URL.

---

## Configuration

| Setting | Default | Description |
|---|---|---|
| **API URL** | `http://localhost:8800/` | Base URL of the FastAPI server. The extension appends `predictions` to build the full endpoint. |
| **API Key** | *(empty)* | **Required.** Sent as the `X-API-Key` request header. Use the `API_KEY` value from the project's `.env`. |

Settings are saved with `chrome.storage.local`, so the API Key is not synced to the Google account.

---

## API contract

The extension uses two endpoints from `app.py`:

### `POST /predictions`
**Request body**
```json
{ "email_text": "<selected text>" }
```
**Response (201)**
```json
{
  "prediction_id": "abc123",
  "prediction_code": 1,
  "label": "Phishing",
  "phishing_probability": 0.9731,
  "model_version": "3"
}
```

### `POST /predictions/{prediction_id}/feedback`
**Request body**
```json
{ "feedback": "OK" }
```
`"OK"` = prediction was correct · `"NO"` = prediction was wrong.

---

## Development tips

* **Reload the extension** after editing any JS/JSON file: go to `chrome://extensions` and click the ↺ button next to the extension.
* **Inspect the service worker** logs: click the *"service worker"* link on the extension card in `chrome://extensions`.
* **Inspect the content script** logs: open DevTools on any Gmail tab (Console → filter by `content.js`).
