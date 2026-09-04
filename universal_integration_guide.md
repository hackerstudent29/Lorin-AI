# Universal Chatbot Integration Guide

To connect your MSAJCE RAG chatbot (which has a React frontend and a FastAPI backend) to an external website (like the main college portal), you can use one of three "Universal Connector" techniques. They range from zero-code drop-ins to fully custom API integrations.

---

## 1. The Iframe Overlay (Presentation Layer Connect)
**Best for:** Fastest integration, keeping the exact same UI, zero backend changes.
**How it works:** You host your React app on a domain. The main college website injects an HTML `<iframe>` that loads your React app as a floating window.

### Requirements & Keys:
*   **Hosted Frontend URL:** (e.g., `https://chat.msajce.edu.in`)
*   **CORS:** Not required for the iframe itself, but your React app needs CORS access to your FastAPI backend (which you already have enabled via `allow_origins=["*"]`).
*   **Keys needed:** None for the main website.

### Implementation on Main Website:
Drop this snippet before the `</body>` tag on the college website.
```html
<style>
  #msajce-bot-btn { position: fixed; bottom: 20px; right: 20px; width: 60px; height: 60px; background: #00d26a; border-radius: 50%; cursor: pointer; z-index: 9999; }
  #msajce-bot-frame { position: fixed; bottom: 90px; right: 20px; width: 380px; height: 600px; border: none; border-radius: 12px; display: none; z-index: 9999; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
</style>

<iframe id="msajce-bot-frame" src="https://YOUR_REACT_FRONTEND_URL.com"></iframe>
<div id="msajce-bot-btn" onclick="document.getElementById('msajce-bot-frame').style.display = document.getElementById('msajce-bot-frame').style.display === 'none' ? 'block' : 'none'">
   <!-- Add chat icon SVG here -->
</div>
```

---

## 2. REST API Headless Connection (Data Layer Connect)
**Best for:** When the main college website wants to build its *own* chat UI matching their exact theme, bypassing your React frontend entirely.
**How it works:** The main college website's JavaScript talks directly to your FastAPI backend (`api_server.py`).

### Requirements & Keys:
*   **FastAPI Backend URL:** (e.g., `https://api.msajce.edu.in`)
*   **CORS Configuration:** Your FastAPI backend MUST allow requests from the college website's domain.
    *   *Security Tip:* Change `allow_origins=["*"]` to `allow_origins=["https://msajce.edu.in"]` in production.
*   **API Security Key (Highly Recommended):** Since the API is exposed, anyone could hit it and drain your LLM credits. You should implement a simple header check in FastAPI.

### Backend Security Update (FastAPI):
Add this to your `api_server.py` to protect the API:
```python
from fastapi import Security, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-Chatbot-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def verify_client_key(api_key: str = Security(api_key_header)):
    if api_key != "your_super_secret_client_key_123":
        raise HTTPException(status_code=403, detail="Could not validate credentials")
```

### Implementation on Main Website (JavaScript Fetch):
The college website developers will write this code to send messages to your backend.
```javascript
async function sendQuery(userMessage, sessionId = null) {
    const response = await fetch("https://YOUR_FASTAPI_BACKEND_URL/api/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Chatbot-Key": "your_super_secret_client_key_123" // The key you defined above
        },
        body: JSON.stringify({ 
            message: userMessage, 
            session_id: sessionId || crypto.randomUUID() 
        })
    });
    const data = await response.json();
    console.log("Lorin AI replied:", data.answer);
    // They will write JS to append 'data.answer' to their custom UI
}
```

---

## 3. Web Component / Injectable Script (Hybrid Connect)
**Best for:** Professional SaaS-style distribution (like Intercom/Zendesk). You provide a single `<script>` tag, and it injects both the UI and the logic.
**How it works:** You compile your React frontend into a single `bundle.js` file. The main website loads this script, which mounts the React app into a dynamic `<div>`.

### Requirements & Keys:
*   **Bundler configuration:** Modify your Vite/Webpack config to output a single JS file without random hashing.
*   **Client Key / Origin validation:** The script will talk to your backend, so you still need CORS enabled for the domains where the script is embedded.

### React / Vite Setup (To create the widget):
1. In your React project's `main.tsx`, change how it renders. Instead of looking for `root`, have it create the root dynamically.
```javascript
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'

// Universal mount function
window.MSAJCE_Chatbot_Init = function(config) {
    const chatDiv = document.createElement('div');
    chatDiv.id = 'msajce-chat-widget-root';
    document.body.appendChild(chatDiv);
    
    // Pass config (like API keys or theme) into your React App
    ReactDOM.createRoot(chatDiv).render(<App config={config} />);
}
```

### Implementation on Main Website:
They add two lines to their website. That's it.
```html
<!-- Load the bundled React App from your hosting -->
<script src="https://YOUR_REACT_FRONTEND_URL/dist/bundle.js"></script>

<!-- Initialize the widget -->
<script>
    window.MSAJCE_Chatbot_Init({
        theme: "light",
        apiUrl: "https://YOUR_FASTAPI_BACKEND_URL",
        clientKey: "your_super_secret_client_key_123"
    });
</script>
```

---

## Summary Recommendation
*   **If you need it done today:** Use **Method 1 (Iframe)**. It requires zero backend changes and zero security setups, as the iframe acts as an isolated browser window.
*   **If the college wants their own UI:** Use **Method 2 (REST API)** and implement the `X-Chatbot-Key` to protect your LLM endpoints from abuse.
*   **If you want a professional, distributable widget:** Use **Method 3 (Injectable Script)**, though this requires modifying your Vite build configuration.
