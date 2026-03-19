# FrameCast Custom OS Image — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform FrameCast from a manual-install Pi photo frame into a flash-and-go OS image with a superhot-ui web interface, browser-based slideshow with CSS transitions, WiFi captive portal, and OTA updates.

**Architecture:** One Flask app serves two surfaces — phone UI (upload, settings, map) and TV display (slideshow, boot sequence, QR codes) — via a kiosk browser (cage + GTK-WebKit on Wayland). No VLC, no X11. WiFi provisioning forked from comitup. OTA via git-pull with health-check rollback.

**Tech Stack:** Python/Flask/gunicorn, Preact/esbuild/superhot-ui, SSE (Server-Sent Events), NetworkManager (D-Bus), cage/Wayland, pi-gen, GitHub Actions

**Design Doc:** `docs/plans/2026-03-19-framecast-image-design.md`

---

## Batch Overview

| Batch | Name | Tasks | Dependencies |
|-------|------|-------|--------------|
| 1 | Backend API Refactor | 5 | — |
| 2 | Frontend Shell | 4 | Batch 1 |
| 3 | Upload Page | 5 | Batch 2 |
| 4 | TV Display — Slideshow | 5 | Batch 2 |
| 5 | TV Display — State Screens | 4 | Batch 4 |
| 6 | Settings & Map Pages | 4 | Batch 2 |
| 7 | WiFi Manager & Onboarding | 5 | Batch 2 |
| 8 | OTA Update System | 4 | Batch 6 |
| 9 | Security & PIN Auth | 3 | Batch 1 |
| 10 | Kiosk & Systemd | 5 | Batch 1 |
| 11 | Pi-Gen Build | 5 | Batch 10 |
| 12 | CI/CD & Release | 4 | Batch 11 |

**Parallelizable:** Batches 3, 4, 6, 7 can run in parallel after Batch 2. Batch 9 can run in parallel with 3-8.

---

## Batch 1: Backend API Refactor

Transform Flask from server-rendered templates to JSON API endpoints. Keep existing `modules/config.py` and `modules/media.py` — they're solid. Refactor `web_upload.py` into an API-first structure. Add gunicorn and SSE support.

### Task 1.1: Add gunicorn and SSE dependencies

**Files:**
- Modify: `requirements.txt`
- Create: `app/gunicorn.conf.py`
- Modify: `app/.env.example`

**Step 1: Update requirements.txt**

```
flask>=2.3
Pillow>=9.0
gunicorn>=21.2
```

**Step 2: Create gunicorn config**

```python
# app/gunicorn.conf.py
"""Gunicorn configuration for FrameCast."""
import multiprocessing
import os

# Workers: 2 on Pi 4/5, 1 on Pi 3 (configurable via .env)
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count(), 2)))
threads = 2 if workers == 1 else 1  # Threads compensate for single worker on Pi 3
bind = "0.0.0.0:" + os.environ.get("WEB_PORT", "8080")
worker_class = "gthread"  # Threaded workers for SSE support
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
```

**Step 3: Add new env vars to .env.example**

Append to `app/.env.example`:
```
# === Performance ===
# Number of gunicorn workers. Default: min(cpu_count, 2)
# Set to 1 on Pi 3 (1GB RAM) to save memory.
GUNICORN_WORKERS=

# === Security ===
# Optional 4-digit PIN for web UI access.
# Displayed on the TV screen. Leave empty for open access.
ACCESS_PIN=

# === Display (TV) ===
# Transition type: fade, slide, zoom, dissolve, none
TRANSITION_TYPE=fade
# Photo ordering: shuffle, newest, oldest, alphabetical
PHOTO_ORDER=shuffle
# QR overlay duration on boot (seconds). 0 to disable.
QR_DISPLAY_SECONDS=30
```

**Step 4: Verify gunicorn runs**

Run: `cd app && gunicorn -c gunicorn.conf.py web_upload:app --check-config`
Expected: No errors

**Step 5: Commit**

```bash
git add requirements.txt app/gunicorn.conf.py app/.env.example
git commit -m "feat: add gunicorn config and new env vars"
```

---

### Task 1.2: Refactor web_upload.py — extract API endpoints

**Files:**
- Modify: `app/web_upload.py`
- Create: `app/api.py`

**Step 1: Create `app/api.py` with JSON API endpoints**

Extract the data-serving logic from `web_upload.py` into pure JSON API endpoints. The existing template-rendering routes stay in `web_upload.py` temporarily (removed in Batch 2).

```python
# app/api.py
"""JSON API endpoints for FrameCast."""
import logging
import shutil
from pathlib import Path

from flask import Blueprint, jsonify, request

from modules import config, media

log = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")


@api.route("/photos")
def list_photos():
    """List all media files with metadata."""
    files = media.list_media()
    return jsonify(files)


@api.route("/status")
def system_status():
    """System status: disk, wifi, version, settings."""
    disk = media.get_disk_usage()
    photo_count = sum(1 for f in media.list_media() if not f["is_video"])
    video_count = sum(1 for f in media.list_media() if f["is_video"])
    return jsonify({
        "disk": disk,
        "photo_count": photo_count,
        "video_count": video_count,
        "version": _read_version(),
        "settings": _current_settings(),
    })


@api.route("/settings", methods=["GET"])
def get_settings():
    """Return current settings."""
    return jsonify(_current_settings())


@api.route("/settings", methods=["POST"])
def update_settings():
    """Update settings from JSON body."""
    updates = request.get_json()
    if not updates:
        return jsonify({"error": "No data provided"}), 400
    config.save(updates)
    config.reload()
    _notify("settings:changed", updates)
    return jsonify({"status": "ok"})


@api.route("/locations")
def photo_locations():
    """GPS locations for all photos."""
    return jsonify(media.get_photo_locations())


def _current_settings():
    """Build settings dict from config."""
    return {
        "photo_duration": int(config.get("PHOTO_DURATION", "10")),
        "shuffle": config.get("SHUFFLE", "yes") == "yes",
        "transition_type": config.get("TRANSITION_TYPE", "fade"),
        "photo_order": config.get("PHOTO_ORDER", "shuffle"),
        "qr_display_seconds": int(config.get("QR_DISPLAY_SECONDS", "30")),
        "hdmi_schedule_enabled": config.get("HDMI_SCHEDULE_ENABLED", "no") == "yes",
        "hdmi_off_time": config.get("HDMI_OFF_TIME", "22:00"),
        "hdmi_on_time": config.get("HDMI_ON_TIME", "08:00"),
        "max_upload_mb": int(config.get("MAX_UPLOAD_MB", "200")),
        "auto_resize_max": int(config.get("AUTO_RESIZE_MAX", "1920")),
        "auto_update_enabled": config.get("AUTO_UPDATE_ENABLED", "no") == "yes",
        "web_port": int(config.get("WEB_PORT", "8080")),
    }


def _read_version():
    """Read version from VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "dev"


def _notify(event, data=None):
    """Push SSE event to connected displays. Implemented in Task 1.3."""
    pass  # Placeholder — wired in Task 1.3
```

**Step 2: Register blueprint in web_upload.py**

Add near the top of `web_upload.py`, after `app = Flask(...)`:
```python
from api import api
app.register_blueprint(api)
```

**Step 3: Test API endpoints**

Run: `cd app && python3 -c "from web_upload import app; client = app.test_client(); r = client.get('/api/status'); print(r.status_code, r.get_json())"`
Expected: `200 {...}`

**Step 4: Commit**

```bash
git add app/api.py app/web_upload.py
git commit -m "feat: extract JSON API endpoints into api.py blueprint"
```

---

### Task 1.3: Add SSE (Server-Sent Events) support

**Files:**
- Create: `app/sse.py`
- Modify: `app/api.py`

**Step 1: Create SSE module**

```python
# app/sse.py
"""Server-Sent Events for real-time display updates."""
import json
import logging
import queue
import threading
import time

log = logging.getLogger(__name__)

# Connected SSE clients. Each is a queue.Queue.
_clients = []
_clients_lock = threading.Lock()


def subscribe():
    """Create a new SSE subscription. Returns a generator for Flask Response."""
    q = queue.Queue(maxsize=50)
    with _clients_lock:
        _clients.append(q)
    try:
        while True:
            try:
                event, data = q.get(timeout=30)
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
            except queue.Empty:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
    finally:
        with _clients_lock:
            _clients.remove(q)


def notify(event, data=None):
    """Push an event to all connected SSE clients."""
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait((event, data or {}))
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)
            log.warning("Dropped SSE client (queue full)")


def client_count():
    """Number of connected SSE clients."""
    with _clients_lock:
        return len(_clients)
```

**Step 2: Add SSE endpoint to api.py**

```python
# Add to api.py
from flask import Response
from sse import subscribe, notify

@api.route("/events")
def sse_stream():
    """SSE endpoint for real-time display updates."""
    return Response(
        subscribe(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

**Step 3: Wire notify() into existing upload/delete handlers**

In `web_upload.py`, after successful upload:
```python
from sse import notify
# After uploaded += 1 in _do_upload():
notify("photo:added", {"filename": filename})
```

After successful delete:
```python
notify("photo:deleted", {"filename": filename})
```

**Step 4: Update _notify placeholder in api.py**

Replace the placeholder `_notify` function to call `sse.notify`:
```python
from sse import notify as _notify
```
(Remove the placeholder function.)

**Step 5: Commit**

```bash
git add app/sse.py app/api.py app/web_upload.py
git commit -m "feat: add SSE for real-time display updates"
```

---

### Task 1.4: Update services.py for new service names

**Files:**
- Modify: `app/modules/services.py`

**Step 1: Update service names**

Replace `slideshow` with `framecast-kiosk` throughout. Add functions for the new services.

```python
# app/modules/services.py
"""System service control for FrameCast."""
import logging
import subprocess

log = logging.getLogger(__name__)

SERVICES = {
    "app": "framecast",
    "kiosk": "framecast-kiosk",
    "wifi": "wifi-manager",
    "update": "framecast-update",
}


def is_service_active(name):
    """Check if a systemd service is active."""
    service = SERVICES.get(name, name)
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def restart_service(name):
    """Restart a systemd service. Returns (success, message)."""
    service = SERVICES.get(name, name)
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", service],
            check=True, capture_output=True, timeout=10,
        )
        log.info("Restarted %s", service)
        return True, f"{service} restarted"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("Failed to restart %s: %s", service, exc)
        return False, f"Failed to restart {service}"


def all_service_status():
    """Return status dict for all managed services."""
    return {name: is_service_active(name) for name in SERVICES}
```

**Step 2: Commit**

```bash
git add app/modules/services.py
git commit -m "refactor: update services.py for new FrameCast service names"
```

---

### Task 1.5: Add SPA template and display routes

**Files:**
- Create: `app/templates/spa.html`
- Modify: `app/web_upload.py`

**Step 1: Create minimal SPA HTML template**

This single template serves both phone and TV surfaces. Preact mounts here.

```html
<!-- app/templates/spa.html -->
<!DOCTYPE html>
<html lang="en" data-sh-monitor="green">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FrameCast</title>
    <link rel="stylesheet" href="/static/css/superhot.css">
    <link rel="stylesheet" href="/static/css/app.css">
</head>
<body class="sh-terminal-bg">
    <div id="app"></div>
    <script type="module" src="/static/js/app.js"></script>
</body>
</html>
```

**Step 2: Add SPA catch-all and display routes to web_upload.py**

```python
# Add to web_upload.py — SPA routes (serves same template, Preact handles routing)

@app.route("/display")
@app.route("/display/<path:subpath>")
def display(subpath=None):
    """TV display routes — served to kiosk browser."""
    return render_template("spa.html")

@app.route("/setup")
@app.route("/update")
def spa_pages():
    """Phone SPA routes."""
    return render_template("spa.html")
```

Keep existing template routes (`/`, `/settings`, `/map`) for now — they'll be replaced
when the Preact SPA is ready in Batch 2. The old routes serve as a working fallback
during development.

**Step 3: Commit**

```bash
git add app/templates/spa.html app/web_upload.py
git commit -m "feat: add SPA template and display/phone routes"
```

---

## Batch 2: Frontend Shell

Set up the Preact app with superhot-ui, routing, and the green phosphor theme. This is the foundation all UI pages build on.

### Task 2.1: Install frontend dependencies and build

**Files:**
- Modify: `app/frontend/package.json` (already scaffolded)
- Create: `app/frontend/src/app.jsx`

**Step 1: Install dependencies**

Run: `cd app/frontend && npm install`
Expected: `node_modules/` created with preact, @preact/signals, superhot-ui, esbuild

**Step 2: Verify superhot-ui symlink**

Run: `ls -la app/frontend/node_modules/superhot-ui/dist/superhot.css`
Expected: File exists (if not, check `file:` path in package.json)

**Step 3: Copy superhot-ui CSS to static**

Add to `app/frontend/package.json` scripts:
```json
"postbuild": "cp node_modules/superhot-ui/dist/superhot.css ../static/css/superhot.css"
```

**Step 4: Build and verify output**

Run: `cd app/frontend && npm run build`
Expected: `app/static/js/app.js` and `app/static/css/superhot.css` created

**Step 5: Commit**

```bash
git add app/frontend/package.json app/static/css/ app/static/js/
git commit -m "feat: install frontend deps and configure build"
```

---

### Task 2.2: Implement app router

**Files:**
- Rewrite: `app/frontend/src/app.jsx`
- Create: `app/frontend/src/components/Router.jsx`

**Step 1: Create simple hash router**

```jsx
// app/frontend/src/components/Router.jsx
import { signal, effect } from "@preact/signals";

export const route = signal(window.location.pathname);

// Update on popstate (back/forward)
window.addEventListener("popstate", () => {
  route.value = window.location.pathname;
});

export function navigate(path) {
  window.history.pushState(null, "", path);
  route.value = path;
}

export function Router({ routes }) {
  const path = route.value;

  // Exact match first, then prefix match for /display/*
  const match = routes.find((r) => r.path === path)
    || routes.find((r) => r.prefix && path.startsWith(r.prefix))
    || routes.find((r) => r.path === "*");

  return match ? match.component() : null;
}
```

**Step 2: Create app.jsx with phone/TV surface detection**

```jsx
// app/frontend/src/app.jsx
import { render } from "preact";
import { Router, route } from "./components/Router.jsx";
import { detectCapability, applyCapability } from "superhot-ui";

// Detect surface: TV display vs phone UI
const isDisplay = route.value.startsWith("/display");

// Auto-downgrade effects on low-capability hardware (Pi 3)
if (typeof document !== "undefined") {
  const tier = detectCapability();
  applyCapability(document.documentElement, tier);
}

// Lazy page imports — filled in by later batches
const Placeholder = () => <div class="sh-frame" data-label="LOADING">STANDBY</div>;

const phoneRoutes = [
  { path: "/", component: Placeholder },         // Upload (Batch 3)
  { path: "/settings", component: Placeholder },  // Settings (Batch 6)
  { path: "/map", component: Placeholder },        // Map (Batch 6)
  { path: "/update", component: Placeholder },     // Update (Batch 8)
  { path: "/setup", component: Placeholder },      // Onboarding (Batch 7)
  { path: "*", component: Placeholder },
];

const displayRoutes = [
  { prefix: "/display", component: Placeholder }, // Filled in Batch 4-5
];

function App() {
  const routes = isDisplay ? displayRoutes : phoneRoutes;
  return <Router routes={routes} />;
}

render(<App />, document.getElementById("app"));
```

**Step 3: Build and verify**

Run: `cd app/frontend && npm run build`
Expected: `app/static/js/app.js` updated

**Step 4: Commit**

```bash
git add app/frontend/src/
git commit -m "feat: implement Preact app shell with router and surface detection"
```

---

### Task 2.3: Add ShNav for phone UI

**Files:**
- Create: `app/frontend/src/components/PhoneLayout.jsx`
- Modify: `app/frontend/src/app.jsx`

**Step 1: Create phone layout with ShNav**

```jsx
// app/frontend/src/components/PhoneLayout.jsx
import { ShNav } from "superhot-ui/preact";
import { route, navigate } from "./Router.jsx";

const navItems = [
  { path: "/", label: "UPLOAD", icon: "⬆" },
  { path: "/settings", label: "SETTINGS", icon: "⚙" },
  { path: "/map", label: "MAP", icon: "◎" },
  { path: "/update", label: "SYSTEM", icon: "↻", system: true },
];

export function PhoneLayout({ children }) {
  return (
    <>
      <div style={{ paddingBottom: "72px" }}>{children}</div>
      <ShNav
        items={navItems}
        currentPath={route.value}
        onNavigate={(path) => navigate(path)}
      />
    </>
  );
}
```

**Step 2: Wrap phone routes in PhoneLayout in app.jsx**

Update the phone route components to render inside `PhoneLayout`.

**Step 3: Build and test in browser**

Run: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`
Open: `http://localhost:8080/` in browser
Expected: superhot-ui nav bar at bottom, green phosphor theme, placeholder content

**Step 4: Commit**

```bash
git add app/frontend/src/
git commit -m "feat: add ShNav phone layout with green phosphor theme"
```

---

### Task 2.4: Create app.css with green phosphor overrides and dropzone styles

**Files:**
- Create: `app/frontend/src/app.css`
- Modify: `app/frontend/esbuild.config.js` (add CSS entry point)

**Step 1: Create app.css**

```css
/* app/frontend/src/app.css */

/* Green phosphor monitor variant for appliance terminal aesthetic */
:root {
  --sh-phosphor: oklch(85% 0.18 145);
  --status-healthy: oklch(85% 0.18 145);
  --status-success: oklch(85% 0.18 145);
  --status-active: oklch(85% 0.18 145);
}

/* Dropzone — FrameCast-local component */
.sh-dropzone {
  border: 2px dashed var(--sh-phosphor);
  border-radius: var(--radius);
  padding: var(--space-6);
  text-align: center;
  font-family: var(--font-mono);
  transition: border-color 0.2s, box-shadow 0.2s;
  position: relative;
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
}

.sh-dropzone[data-sh-dropzone="hover"] {
  border-style: solid;
  box-shadow: 0 0 12px var(--sh-phosphor-glow);
}

.sh-dropzone[data-sh-dropzone="receiving"] {
  border-style: solid;
  border-color: var(--sh-phosphor);
}

.sh-dropzone[data-sh-dropzone="error"] {
  border-color: var(--sh-threat);
  box-shadow: 0 0 12px var(--sh-threat-glow, rgba(255, 0, 0, 0.3));
}

/* Slideshow — full viewport for TV display */
.slideshow-container {
  position: fixed;
  inset: 0;
  background: var(--sh-void);
  overflow: hidden;
}

.slideshow-container img,
.slideshow-container video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  image-orientation: from-image;
}

/* Transitions */
.slide-fade-in { animation: fadeIn 1.5s ease forwards; }
.slide-fade-out { animation: fadeOut 1.5s ease forwards; }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }

.slide-slide-in { animation: slideIn 0.8s ease forwards; }
.slide-slide-out { animation: slideOut 0.8s ease forwards; }

@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
@keyframes slideOut { from { transform: translateX(0); } to { transform: translateX(-100%); } }

.slide-zoom {
  animation: kenBurns 12s ease-in-out forwards;
}

@keyframes kenBurns {
  from { transform: scale(1) translate(0, 0); }
  to { transform: scale(1.1) translate(-2%, -1%); }
}

/* QR overlay */
.qr-overlay {
  position: fixed;
  bottom: var(--space-6);
  right: var(--space-6);
  background: rgba(0, 0, 0, 0.8);
  padding: var(--space-4);
  border: 1px solid var(--sh-phosphor);
  border-radius: var(--radius);
  z-index: 100;
  animation: fadeIn 0.5s ease;
}

/* Display: piOS boot text */
.boot-screen {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  padding: var(--space-8);
  height: 100vh;
  background: var(--sh-void);
  font-family: var(--font-mono);
  color: var(--sh-phosphor);
}
```

**Step 2: Add CSS to esbuild config as a copy step**

Add to `package.json` scripts:
```json
"prebuild": "cp src/app.css ../static/css/app.css"
```

**Step 3: Build and verify**

Run: `cd app/frontend && npm run build`
Expected: `app/static/css/app.css` present, green phosphor theme active

**Step 4: Commit**

```bash
git add app/frontend/src/app.css app/static/css/app.css
git commit -m "feat: add green phosphor theme overrides and slideshow CSS"
```

---

## Batch 3: Upload Page

Build the main upload page with ShDropzone, photo grid, disk space indicator, and real-time updates.

### Task 3.1: Create ShDropzone component

**Files:**
- Create: `app/frontend/src/components/ShDropzone.jsx`

**Step 1: Write the dropzone test** (manual browser test — describe expected behavior)

Open `/` in browser. Drag a file over the dropzone area.
Expected: border becomes solid phosphor with glow. Drop the file → progress bar appears → toast on complete.

**Step 2: Implement ShDropzone**

```jsx
// app/frontend/src/components/ShDropzone.jsx
import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { glitchText } from "superhot-ui";

export function ShDropzone({ onUpload, maxSizeMB = 200, disabled = false }) {
  const state = signal("idle"); // idle, hover, receiving, error, complete
  const progress = signal(0);
  const dropRef = useRef(null);

  function handleDragOver(e) {
    e.preventDefault();
    if (!disabled) state.value = "hover";
  }

  function handleDragLeave() {
    state.value = "idle";
  }

  function handleDrop(e) {
    e.preventDefault();
    if (disabled) return;
    const files = [...e.dataTransfer.files];
    if (files.length) uploadFiles(files);
  }

  function handleClick() {
    if (disabled) return;
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = "image/*,video/*";
    input.onchange = () => uploadFiles([...input.files]);
    input.click();
  }

  async function uploadFiles(files) {
    state.value = "receiving";
    progress.value = 0;

    const formData = new FormData();
    for (const file of files) {
      if (file.size > maxSizeMB * 1024 * 1024) {
        state.value = "error";
        onUpload?.({ error: `${file.name} exceeds ${maxSizeMB}MB limit` });
        return;
      }
      formData.append("file", file);
    }

    try {
      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) progress.value = Math.round((e.loaded / e.total) * 100);
      };

      await new Promise((resolve, reject) => {
        xhr.onload = () => xhr.status < 400 ? resolve() : reject(new Error(xhr.statusText));
        xhr.onerror = () => reject(new Error("Network error"));
        xhr.open("POST", "/upload");
        xhr.send(formData);
      });

      state.value = "complete";
      if (dropRef.current) glitchText(dropRef.current, { duration: 300 });
      onUpload?.({ success: true, count: files.length });
      setTimeout(() => { state.value = "idle"; }, 2000);
    } catch (err) {
      state.value = "error";
      onUpload?.({ error: err.message });
      setTimeout(() => { state.value = "idle"; }, 3000);
    }
  }

  const label = {
    idle: "AWAITING INPUT",
    hover: "DROP TO UPLOAD",
    receiving: `RECEIVING... ${progress.value}%`,
    error: "TRANSFER FAILED",
    complete: "RECEIVED",
  }[state.value];

  return (
    <div
      ref={dropRef}
      class="sh-dropzone"
      data-sh-dropzone={state.value}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={handleClick}
    >
      <span class="sh-label">{label}</span>
      {state.value === "receiving" && (
        <span class="sh-progress">{"▓".repeat(Math.floor(progress.value / 5))}{"░".repeat(20 - Math.floor(progress.value / 5))}</span>
      )}
      {state.value === "idle" && (
        <span class="sh-ansi-dim">TAP OR DRAG FILES</span>
      )}
    </div>
  );
}
```

**Step 3: Commit**

```bash
git add app/frontend/src/components/ShDropzone.jsx
git commit -m "feat: implement ShDropzone upload component"
```

---

### Task 3.2: Create PhotoGrid component

**Files:**
- Create: `app/frontend/src/components/PhotoGrid.jsx`

**Step 1: Implement photo grid with thumbnails and delete**

```jsx
// app/frontend/src/components/PhotoGrid.jsx
import { ShModal } from "superhot-ui/preact";
import { signal } from "@preact/signals";

const deleteTarget = signal(null);

export function PhotoGrid({ photos, onDelete }) {
  if (!photos.length) {
    return <div class="sh-frame" data-label="MEDIA"><span class="sh-ansi-dim">NO ACTIVE PHOTOS</span></div>;
  }

  return (
    <>
      <div class="sh-grid sh-grid-3" style={{ gap: "var(--space-2)" }}>
        {photos.map((photo) => (
          <div
            key={photo.filename}
            class="sh-card sh-clickable"
            onClick={() => { deleteTarget.value = photo.filename; }}
            style={{ position: "relative", aspectRatio: "1" }}
          >
            <img
              src={`/thumbnail/${photo.filename}`}
              alt={photo.filename}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
              loading="lazy"
            />
            {photo.is_video && <span class="sh-status-badge" data-sh-status="active">VIDEO</span>}
          </div>
        ))}
      </div>

      {deleteTarget.value && (
        <ShModal
          title="DELETE FILE?"
          onClose={() => { deleteTarget.value = null; }}
          onConfirm={() => {
            onDelete(deleteTarget.value);
            deleteTarget.value = null;
          }}
        >
          <span class="sh-ansi-bold">{deleteTarget.value}</span>
        </ShModal>
      )}
    </>
  );
}
```

**Step 2: Commit**

```bash
git add app/frontend/src/components/PhotoGrid.jsx
git commit -m "feat: implement PhotoGrid with delete confirmation modal"
```

---

### Task 3.3: Create Upload page

**Files:**
- Create: `app/frontend/src/pages/Upload.jsx`

**Step 1: Implement Upload page combining dropzone, grid, and disk status**

```jsx
// app/frontend/src/pages/Upload.jsx
import { signal, effect } from "@preact/signals";
import { ShDropzone } from "../components/ShDropzone.jsx";
import { PhotoGrid } from "../components/PhotoGrid.jsx";
import { createToastManager } from "superhot-ui";

const photos = signal([]);
const status = signal(null);
const toasts = createToastManager();

// Fetch photos on mount
async function loadPhotos() {
  const res = await fetch("/api/photos");
  photos.value = await res.json();
}

async function loadStatus() {
  const res = await fetch("/api/status");
  status.value = await res.json();
}

// SSE listener for real-time updates
function connectSSE() {
  const source = new EventSource("/api/events");
  source.addEventListener("photo:added", (e) => {
    const data = JSON.parse(e.data);
    loadPhotos(); // Refresh list
    toasts.add({ type: "info", message: `[UPLOAD] RECEIVED: ${data.filename}` });
  });
  source.addEventListener("photo:deleted", () => loadPhotos());
  source.onerror = () => setTimeout(connectSSE, 5000); // Reconnect
}

export function Upload() {
  // Load on first render
  if (!photos.value.length) {
    loadPhotos();
    loadStatus();
    connectSSE();
  }

  const disk = status.value?.disk;
  const diskFull = disk && disk.percent_used > 95;

  function handleUploadResult(result) {
    if (result.error) {
      toasts.add({ type: "error", message: `[UPLOAD] ${result.error}`, duration: 0 });
    }
  }

  async function handleDelete(filename) {
    await fetch(`/delete/${filename}`, { method: "POST" });
    loadPhotos();
    toasts.add({ type: "info", message: `[DELETE] ${filename}` });
  }

  return (
    <div style={{ padding: "var(--space-4)" }}>
      {disk && (
        <div class="sh-frame" data-label="STORAGE">
          <span class="sh-progress">
            {"▓".repeat(Math.floor(disk.percent_used / 5))}
            {"░".repeat(20 - Math.floor(disk.percent_used / 5))}
          </span>
          <span class="sh-label"> {disk.used} / {disk.total}</span>
          {disk.percent_used > 90 && (
            <span class="sh-status-badge" data-sh-status="error">LOW DISK</span>
          )}
        </div>
      )}

      <ShDropzone onUpload={handleUploadResult} disabled={diskFull} />

      <PhotoGrid photos={photos.value} onDelete={handleDelete} />
    </div>
  );
}
```

**Step 2: Wire into app.jsx router**

Replace the Upload placeholder:
```jsx
import { Upload } from "./pages/Upload.jsx";
// In phoneRoutes:
{ path: "/", component: () => <PhoneLayout><Upload /></PhoneLayout> },
```

**Step 3: Build, run, test in browser**

Run: `cd app/frontend && npm run build && cd .. && gunicorn -c gunicorn.conf.py web_upload:app`
Open: `http://localhost:8080/`
Expected: Upload page with dropzone, storage bar, photo grid

**Step 4: Commit**

```bash
git add app/frontend/src/pages/Upload.jsx app/frontend/src/app.jsx
git commit -m "feat: implement Upload page with dropzone, grid, disk status"
```

---

### Task 3.4: Update Flask upload endpoint for API responses

**Files:**
- Modify: `app/web_upload.py`

**Step 1: Make upload endpoint return JSON when requested**

Add to the `_do_upload()` function — if the request is XHR (XMLHttpRequest from the dropzone),
return JSON instead of redirect:

```python
# At the end of _do_upload(), replace the redirect:
if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.content_type.startswith("multipart"):
    return jsonify({"uploaded": uploaded, "errors": error_messages})
# Keep existing redirect as fallback for non-JS browsers
return redirect(url_for("index"))
```

**Step 2: Test upload via curl**

Run: `curl -X POST -F "file=@test.jpg" http://localhost:8080/upload`
Expected: JSON response `{"uploaded": 1, "errors": []}`

**Step 3: Commit**

```bash
git add app/web_upload.py
git commit -m "feat: upload endpoint returns JSON for XHR requests"
```

---

### Task 3.5: Build and integration test Batch 3

**Step 1: Full frontend build**

Run: `cd app/frontend && npm run build`

**Step 2: Run Flask with gunicorn**

Run: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`

**Step 3: Browser test checklist**

- [ ] Upload page loads at `/`
- [ ] Drag file → dropzone highlights (phosphor glow)
- [ ] Drop file → progress bar → toast "RECEIVED"
- [ ] Photo appears in grid
- [ ] Tap photo → delete modal
- [ ] Confirm delete → photo removed, toast "DELETE"
- [ ] Storage bar shows disk usage

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: Batch 3 complete — Upload page with dropzone, grid, SSE"
```

---

## Batch 4: TV Display — Slideshow

Build the browser-based slideshow with CSS transitions, image preloading, and SSE-driven updates.

### Task 4.1: Create Slideshow component

**Files:**
- Create: `app/frontend/src/display/Slideshow.jsx`

**Step 1: Implement slideshow with dual-image stack and CSS transitions**

```jsx
// app/frontend/src/display/Slideshow.jsx
import { signal, effect } from "@preact/signals";
import { useRef, useEffect } from "preact/hooks";

const photos = signal([]);
const currentIndex = signal(0);
const settings = signal({ transition_type: "fade", photo_duration: 10, photo_order: "shuffle" });
const showQR = signal(true);

export function Slideshow() {
  const currentRef = useRef(null);
  const nextRef = useRef(null);
  const timerRef = useRef(null);

  // Fetch photos and settings
  useEffect(() => {
    loadData();
    connectSSE();
    return () => clearTimeout(timerRef.current);
  }, []);

  // Start slideshow timer
  useEffect(() => {
    if (photos.value.length > 1) {
      scheduleNext();
    }
    // QR overlay auto-hide
    const qrTimeout = settings.value.qr_display_seconds || 30;
    if (qrTimeout > 0) {
      setTimeout(() => { showQR.value = false; }, qrTimeout * 1000);
    }
  }, [photos.value]);

  async function loadData() {
    const [photosRes, settingsRes] = await Promise.all([
      fetch("/api/photos"),
      fetch("/api/settings"),
    ]);
    const photoList = await photosRes.json();
    settings.value = await settingsRes.json();

    // Apply ordering
    photos.value = orderPhotos(photoList, settings.value.photo_order);

    // Preload first two
    if (photoList.length > 0) preloadImage(photoList[0]);
    if (photoList.length > 1) preloadImage(photoList[1]);
  }

  function orderPhotos(list, order) {
    const sorted = [...list];
    switch (order) {
      case "shuffle":
        for (let i = sorted.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [sorted[i], sorted[j]] = [sorted[j], sorted[i]];
        }
        return sorted;
      case "newest": return sorted.reverse();
      case "oldest": return sorted;
      case "alphabetical": return sorted.sort((a, b) => a.filename.localeCompare(b.filename));
      default: return sorted;
    }
  }

  function preloadImage(photo) {
    if (!photo.is_video) {
      const img = new Image();
      img.src = `/media/${photo.filename}`;
    }
  }

  function scheduleNext() {
    clearTimeout(timerRef.current);
    const duration = (settings.value.photo_duration || 10) * 1000;
    timerRef.current = setTimeout(advance, duration);
  }

  function advance() {
    const list = photos.value;
    if (list.length <= 1) return;

    const nextIdx = (currentIndex.value + 1) % list.length;
    const transition = settings.value.transition_type || "fade";

    // Apply transition classes
    if (currentRef.current) currentRef.current.className = `slide-${transition}-out`;
    if (nextRef.current) {
      nextRef.current.src = `/media/${list[nextIdx].filename}`;
      nextRef.current.className = `slide-${transition}-in`;
    }

    // After transition ends, swap
    setTimeout(() => {
      currentIndex.value = nextIdx;
      // Preload next+1
      const preloadIdx = (nextIdx + 1) % list.length;
      preloadImage(list[preloadIdx]);
      scheduleNext();
    }, 1500); // Match CSS transition duration
  }

  function connectSSE() {
    const source = new EventSource("/api/events");
    source.addEventListener("photo:added", () => loadData());
    source.addEventListener("photo:deleted", () => loadData());
    source.addEventListener("settings:changed", () => loadData());
    source.onerror = () => setTimeout(connectSSE, 5000);
  }

  const current = photos.value[currentIndex.value];
  if (!current) return null;

  const isVideo = current.is_video;

  return (
    <div class="slideshow-container">
      {isVideo ? (
        <video
          ref={currentRef}
          src={`/media/${current.filename}`}
          autoplay
          muted
          onEnded={advance}
          style={{ zIndex: 2 }}
        />
      ) : (
        <>
          <img
            ref={currentRef}
            src={`/media/${current.filename}`}
            style={{ zIndex: 2 }}
          />
          <img ref={nextRef} style={{ zIndex: 1, opacity: 0 }} />
        </>
      )}

      {showQR.value && (
        <div class="qr-overlay">
          <canvas id="qr-canvas" width="128" height="128" />
          <div class="sh-label" style={{ marginTop: "var(--space-2)", textAlign: "center" }}>
            FRAMECAST
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add app/frontend/src/display/Slideshow.jsx
git commit -m "feat: implement browser-based slideshow with CSS transitions"
```

---

### Task 4.2: Create QR code component

**Files:**
- Create: `app/frontend/src/components/QRCode.jsx`

**Step 1: Install qrcode library**

Run: `cd app/frontend && npm install qrcode-generator`

**Step 2: Create QR component**

```jsx
// app/frontend/src/components/QRCode.jsx
import { useRef, useEffect } from "preact/hooks";
import qrcode from "qrcode-generator";

export function QRCode({ url, size = 128 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !url) return;
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const modules = qr.getModuleCount();
    const cellSize = size / modules;

    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, size, size);

    ctx.fillStyle = "#00ff88"; // Phosphor green QR
    for (let row = 0; row < modules; row++) {
      for (let col = 0; col < modules; col++) {
        if (qr.isDark(row, col)) {
          ctx.fillRect(col * cellSize, row * cellSize, cellSize, cellSize);
        }
      }
    }
  }, [url, size]);

  return <canvas ref={canvasRef} width={size} height={size} />;
}
```

**Step 3: Commit**

```bash
git add app/frontend/src/components/QRCode.jsx app/frontend/package.json
git commit -m "feat: add QR code component with phosphor green rendering"
```

---

### Task 4.3: Create DisplayRouter — state-based routing for TV

**Files:**
- Create: `app/frontend/src/display/DisplayRouter.jsx`

**Step 1: Implement state-based display router**

The display router fetches system state and shows the appropriate screen:
no WiFi → Setup, no photos → Welcome, photos → Slideshow.

```jsx
// app/frontend/src/display/DisplayRouter.jsx
import { signal, effect } from "@preact/signals";
import { Slideshow } from "./Slideshow.jsx";

// Lazy imports — filled in Batch 5
const Boot = () => <div class="boot-screen">INITIALIZING...</div>;
const Welcome = () => <div>AWAITING INPUT</div>;
const Setup = () => <div>SETUP REQUIRED</div>;

const displayState = signal("boot"); // boot, setup, welcome, slideshow

export function DisplayRouter() {
  // Check system state on mount
  if (displayState.value === "boot") {
    checkState();
  }

  switch (displayState.value) {
    case "boot": return <Boot />;
    case "setup": return <Setup />;
    case "welcome": return <Welcome />;
    case "slideshow": return <Slideshow />;
    default: return <Boot />;
  }
}

async function checkState() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();

    if (status.photo_count > 0) {
      displayState.value = "slideshow";
    } else {
      displayState.value = "welcome";
    }
  } catch {
    // No server yet — stay on boot
    setTimeout(checkState, 2000);
  }
}

// Export for SSE updates
export { displayState };
```

**Step 2: Wire into app.jsx display routes**

```jsx
import { DisplayRouter } from "./display/DisplayRouter.jsx";
// In displayRoutes:
{ prefix: "/display", component: () => <DisplayRouter /> },
```

**Step 3: Commit**

```bash
git add app/frontend/src/display/DisplayRouter.jsx app/frontend/src/app.jsx
git commit -m "feat: add state-based DisplayRouter for TV surface"
```

---

### Task 4.4: Build and test slideshow

**Step 1: Full build**

Run: `cd app/frontend && npm run build`

**Step 2: Test in browser**

Open: `http://localhost:8080/display`
Expected: If photos exist → slideshow with fade transitions. If no photos → welcome screen.

**Step 3: Test transitions**

Upload 3+ photos, verify transitions work (fade between images).

**Step 4: Commit**

```bash
git commit -m "feat: Batch 4 complete — browser-based slideshow with transitions"
```

---

### Task 4.5: Test SSE real-time updates on display

**Step 1: Open display in one browser tab, upload page in another**

- Display tab: `http://localhost:8080/display`
- Upload tab: `http://localhost:8080/`

**Step 2: Upload a photo from the upload tab**

Expected: Display tab adds the photo to rotation without page reload.

**Step 3: Delete a photo from upload tab**

Expected: Display tab removes it from rotation.

**Step 4: Commit** (if any fixes needed)

```bash
git commit -m "fix: SSE integration between upload and display"
```

---

## Batch 5: TV Display — State Screens

Build the Boot, Welcome, and Setup screens for the TV display.

### Task 5.1: Create Boot screen with bootSequence()

**Files:**
- Create: `app/frontend/src/display/Boot.jsx`

**Step 1: Implement boot screen**

```jsx
// app/frontend/src/display/Boot.jsx
import { useRef, useEffect } from "preact/hooks";
import { bootSequence } from "superhot-ui";

export function Boot({ onComplete }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    bootSequence(containerRef.current, [
      "piOS v1.0",
      "FRAMECAST PHOTO SYSTEM",
      "INITIALIZING...",
      "CHECKING NETWORK...",
      "LOADING MEDIA...",
    ]).then(() => {
      onComplete?.();
    });
  }, []);

  return (
    <div class="boot-screen">
      <div ref={containerRef} class="sh-boot-container" />
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add app/frontend/src/display/Boot.jsx
git commit -m "feat: add Boot screen with bootSequence() typewriter animation"
```

---

### Task 5.2: Create Welcome screen (no photos)

**Files:**
- Create: `app/frontend/src/display/Welcome.jsx`

**Step 1: Implement welcome screen with QR code and mantra**

```jsx
// app/frontend/src/display/Welcome.jsx
import { QRCode } from "../components/QRCode.jsx";

export function Welcome() {
  const url = `http://${window.location.hostname}:8080`;

  return (
    <div class="boot-screen" style={{ alignItems: "center", textAlign: "center" }}>
      <h1 style={{ fontSize: "var(--type-display)", color: "var(--sh-phosphor)", marginBottom: "var(--space-6)" }}>
        FRAMECAST
      </h1>

      <div data-sh-mantra="AWAITING INPUT" style={{ marginBottom: "var(--space-8)" }}>
        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          SCAN TO UPLOAD PHOTOS
        </p>
        <QRCode url={url} size={256} />
        <p class="sh-ansi-dim" style={{ marginTop: "var(--space-4)", fontSize: "var(--type-body)" }}>
          {url}
        </p>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add app/frontend/src/display/Welcome.jsx
git commit -m "feat: add Welcome screen with QR code and AWAITING INPUT mantra"
```

---

### Task 5.3: Create Setup screen (AP mode)

**Files:**
- Create: `app/frontend/src/display/Setup.jsx`

**Step 1: Implement AP mode setup screen**

```jsx
// app/frontend/src/display/Setup.jsx
import { QRCode } from "../components/QRCode.jsx";

export function Setup() {
  // AP mode gateway address
  const apUrl = "http://192.168.4.1:8080";

  return (
    <div class="boot-screen" style={{ alignItems: "center", textAlign: "center" }}>
      <h1 style={{ fontSize: "var(--type-display)", color: "var(--sh-phosphor)", marginBottom: "var(--space-4)" }}>
        FRAMECAST
      </h1>

      <div class="sh-frame" data-label="SETUP REQUIRED" style={{ maxWidth: "600px", width: "100%" }}>
        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          1. CONNECT TO WIFI NETWORK:
        </p>
        <p style={{ fontSize: "var(--type-heading)", color: "var(--sh-phosphor)", marginBottom: "var(--space-6)" }}>
          FrameCast-XXXX
        </p>

        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          2. SCAN OR OPEN:
        </p>
        <QRCode url={apUrl} size={200} />
        <p class="sh-ansi-dim" style={{ marginTop: "var(--space-3)" }}>
          {apUrl}
        </p>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add app/frontend/src/display/Setup.jsx
git commit -m "feat: add Setup screen for AP mode WiFi onboarding"
```

---

### Task 5.4: Wire state screens into DisplayRouter

**Files:**
- Modify: `app/frontend/src/display/DisplayRouter.jsx`

**Step 1: Replace placeholders with real components**

Import `Boot`, `Welcome`, `Setup` from their files. Wire `Boot`'s `onComplete` to transition
to the appropriate state based on system status.

**Step 2: Build and test all states**

- No photos: `/display` → Boot animation → Welcome screen
- With photos: `/display` → Boot animation → Slideshow (with QR overlay for 30s)
- No WiFi: Would show Setup (can't test without Pi, but verify component renders)

**Step 3: Commit**

```bash
git add app/frontend/src/display/DisplayRouter.jsx
git commit -m "feat: Batch 5 complete — Boot, Welcome, Setup screens wired into DisplayRouter"
```

---

## Batch 6: Settings & Map Pages

### Task 6.1: Create Settings page

**Files:**
- Create: `app/frontend/src/pages/Settings.jsx`

Implement settings page with `.sh-frame` groups (DISPLAY, NETWORK, SYSTEM), `.sh-toggle`,
`.sh-input`, `.sh-select`, `ShCollapsible` for advanced. Reads from `/api/settings`,
saves via `POST /api/settings`. See design doc § Web UI → Pages → Settings for full field list.

**Step 1: Implement Settings page**
**Step 2: Wire into app.jsx**
**Step 3: Test settings changes persist**
**Step 4: Commit**

---

### Task 6.2: Create Map page

**Files:**
- Create: `app/frontend/src/pages/Map.jsx`

Port the existing Leaflet/OpenStreetMap map from `templates/map.html` to Preact.
Use existing `/api/locations` endpoint. Pin markers at GPS coordinates from photo EXIF.

**Step 1: Install Leaflet** — `cd app/frontend && npm install leaflet`
**Step 2: Implement Map.jsx**
**Step 3: Wire into app.jsx**
**Step 4: Commit**

---

### Task 6.3: Create Update page

**Files:**
- Create: `app/frontend/src/pages/Update.jsx`

`.sh-progress-steps` for DOWNLOAD → INSTALL → VERIFY → REBOOT.
`.sh-progress` for download progress. Calls `/api/update/check` and `/api/update/apply`.
See Batch 8 for the backend updater module.

**Step 1: Implement Update.jsx** (stub — wired to real backend in Batch 8)
**Step 2: Commit**

---

### Task 6.4: Build and test Batch 6

**Step 1: Full build + test each page in browser**
**Step 2: Commit**

```bash
git commit -m "feat: Batch 6 complete — Settings, Map, Update pages"
```

---

## Batch 7: WiFi Manager & Onboarding

### Task 7.1: Create wifi.py — NetworkManager D-Bus integration

**Files:**
- Create: `app/modules/wifi.py`

Fork comitup's NetworkManager WiFi provisioning patterns. Use D-Bus (via `dbus-python` or
subprocess calls to `nmcli`) to:
- Check if WiFi is connected
- Scan for available networks (SSID, signal strength, security)
- Connect to a network (SSID + password)
- Create AP hotspot (`FrameCast-XXXX`)
- Switch between AP mode and station mode

**Step 1: Implement wifi.py with nmcli wrapper**
**Step 2: Add API endpoints** — `/api/wifi/status`, `/api/wifi/scan`, `/api/wifi/connect`, `/api/wifi/ap`
**Step 3: Test with `nmcli` on dev machine**
**Step 4: Commit**

---

### Task 7.2: Create boot partition config file reader

**Files:**
- Create: `app/modules/boot_config.py`

On first boot, check `/boot/firmware/framecast-wifi.txt` (or `/boot/framecast-wifi.txt`).
If found, parse SSID and PASSWORD, connect via wifi.py, delete the file.

**Step 1: Implement boot_config.py**
**Step 2: Wire into Flask app startup**
**Step 3: Commit**

---

### Task 7.3: Create Onboard page (WiFi setup wizard)

**Files:**
- Create: `app/frontend/src/pages/Onboard.jsx`

`.sh-progress-steps`: SCAN → SELECT → CONNECT → DONE.
Network list with `.sh-signal-bars`. Password input with `.sh-input`.
Calls `/api/wifi/scan` and `/api/wifi/connect`.

**Step 1: Implement Onboard.jsx**
**Step 2: Wire into app.jsx**
**Step 3: Commit**

---

### Task 7.4: Implement captive portal redirect

**Files:**
- Modify: `app/web_upload.py`
- Create: `scripts/captive-portal-redirect.sh`

When in AP mode, redirect all DNS requests to the Flask server.
Use `dnsmasq` or iptables `REDIRECT` rule to capture port 80/443 → port 8080.
Flask returns redirect to `/setup` for any unrecognized path when in AP mode.

**Step 1: Add captive portal middleware to Flask**
**Step 2: Create iptables setup script**
**Step 3: Commit**

---

### Task 7.5: Create wifi-manager.service

**Files:**
- Create: `systemd/wifi-manager.service`

Systemd service that runs on boot: checks WiFi state, starts AP if needed,
manages transitions between AP and station mode.

**Step 1: Create service file**
**Step 2: Test start/stop**
**Step 3: Commit**

```bash
git commit -m "feat: Batch 7 complete — WiFi manager, onboarding wizard, captive portal"
```

---

## Batch 8: OTA Update System

### Task 8.1: Create updater.py module

**Files:**
- Create: `app/modules/updater.py`

Checks GitHub Releases API for newer versions. Downloads via git fetch + checkout.
Returns progress for the UI.

**Step 1: Implement updater.py** — `check_for_update()`, `apply_update()`, `get_current_version()`
**Step 2: Add API endpoints** — `/api/update/check`, `/api/update/apply`
**Step 3: Commit**

---

### Task 8.2: Create health-check.sh

**Files:**
- Create: `scripts/health-check.sh`

Post-reboot health check: wait 90s, verify `framecast` and `framecast-kiosk` are active.
If not, rollback to previous git tag and reboot.

**Step 1: Implement health-check.sh**
**Step 2: Make executable**
**Step 3: Commit**

---

### Task 8.3: Create framecast-update service and timer

**Files:**
- Create: `systemd/framecast-update.service`
- Create: `systemd/framecast-update.timer`

Timer runs daily at 3:00 AM (configurable). Service calls the updater module.

**Step 1: Create service and timer files**
**Step 2: Commit**

---

### Task 8.4: Wire Update page to real backend

**Files:**
- Modify: `app/frontend/src/pages/Update.jsx`

Replace stubs with real `/api/update/*` calls. SSE for progress updates.

**Step 1: Implement**
**Step 2: Commit**

```bash
git commit -m "feat: Batch 8 complete — OTA update system with health check rollback"
```

---

## Batch 9: Security & PIN Auth

### Task 9.1: Generate PIN on first boot

**Files:**
- Modify: `app/web_upload.py`

On startup, if `ACCESS_PIN` is empty in `.env`, generate a random 4-digit PIN and save it.

**Step 1: Implement PIN generation in _heal_env_file()**
**Step 2: Commit**

---

### Task 9.2: Add PIN middleware to Flask

**Files:**
- Create: `app/modules/auth.py`

Flask `before_request` decorator that checks for PIN cookie on non-display routes.
If no valid cookie, redirect to `/pin` entry page. Skip for `/display/*` routes
(TV doesn't need PIN) and `/api/events` (SSE).

**Step 1: Implement auth.py**
**Step 2: Create PIN entry page component**
**Step 3: Commit**

---

### Task 9.3: Show PIN on TV display screens

**Files:**
- Modify: `app/frontend/src/display/Welcome.jsx`
- Modify: `app/frontend/src/display/Setup.jsx`

Add `ACCESS PIN: XXXX` text below the QR code on Welcome and Setup screens.
Fetch from `/api/status` which includes the PIN.

**Step 1: Add PIN display**
**Step 2: Commit**

```bash
git commit -m "feat: Batch 9 complete — PIN auth with TV display"
```

---

## Batch 10: Kiosk & Systemd

### Task 10.1: Create GJS/WebKit kiosk browser script

**Files:**
- Create: `kiosk/browser.js`

GJS script that opens a fullscreen GTK-WebKit window pointed at `http://localhost:8080/display`.
Reference: kiosk.pi's `bin/browser` script.

**Step 1: Implement browser.js**
**Step 2: Commit**

---

### Task 10.2: Create kiosk.sh launcher

**Files:**
- Create: `kiosk/kiosk.sh`

Wrapper script: waits for Flask to be ready, then launches `cage -- gjs browser.js`.

**Step 1: Implement kiosk.sh**
**Step 2: Make executable**
**Step 3: Commit**

---

### Task 10.3: Create all systemd service files

**Files:**
- Create: `systemd/framecast.service` — gunicorn + Flask
- Create: `systemd/framecast-kiosk.service` — cage + GJS browser
- Modify: `systemd/wifi-manager.service` (if not done in Batch 7)

**Step 1: Implement all service files with hardening** (MemoryMax, NoNewPrivileges, etc.)
**Step 2: Commit**

---

### Task 10.4: Create HDMI schedule scripts

**Files:**
- Create: `scripts/hdmi-control.sh` (replace existing with Wayland version)

Uses `wlr-randr --output HDMI-A-1 --off/--on` with proper WAYLAND_DISPLAY and XDG_RUNTIME_DIR.

**Step 1: Implement hdmi-control.sh**
**Step 2: Commit**

---

### Task 10.5: Update Makefile

**Files:**
- Modify: `Makefile`

Add targets: `build-frontend`, `dev`, `run` (gunicorn), `build-image` (pi-gen).
Update service names in `status` and `logs` targets.

**Step 1: Update Makefile**
**Step 2: Commit**

```bash
git commit -m "feat: Batch 10 complete — kiosk browser, systemd services, HDMI schedule"
```

---

## Batch 11: Pi-Gen Build

### Task 11.1: Create pi-gen config and wrapper

**Files:**
- Create: `pi-gen/config`
- Create: `pi-gen/build.sh`

**Step 1: Create config** (from design doc § Build Config)
**Step 2: Create build.sh wrapper that clones pi-gen and runs build-docker.sh**
**Step 3: Commit**

---

### Task 11.2: Create stage2-framecast packages

**Files:**
- Create: `pi-gen/stage2-framecast/prerun.sh`
- Create: `pi-gen/stage2-framecast/EXPORT_IMAGE`
- Create: `pi-gen/stage2-framecast/00-packages/00-packages`

**Step 1: Create stage files** (package list from design doc)
**Step 2: Commit**

---

### Task 11.3: Create stage2-framecast config substage

**Files:**
- Create: `pi-gen/stage2-framecast/01-config/01-run.sh`
- Create: `pi-gen/stage2-framecast/01-config/files/config.txt`
- Create: `pi-gen/stage2-framecast/01-config/files/cmdline.txt`

Boot config: GPU mem, quiet boot, `vc4.force_hotplug=1`.

**Step 1: Create config files**
**Step 2: Commit**

---

### Task 11.4: Create stage2-framecast app substage

**Files:**
- Create: `pi-gen/stage2-framecast/02-app/01-run.sh`
- Create: `pi-gen/stage2-framecast/02-app/01-run-chroot.sh`

Copies app files, builds frontend, enables services, sets up auto-login, creates sudoers.

**Step 1: Create install scripts**
**Step 2: Commit**

---

### Task 11.5: Create stage2-framecast system substage

**Files:**
- Create: `pi-gen/stage2-framecast/03-system/01-run.sh`
- Create: `pi-gen/stage2-framecast/03-system/files/`

SD card longevity (journal, tmpfs, noatime), watchdog config, avahi service file.

**Step 1: Create system config files**
**Step 2: Test build** — `cd pi-gen && bash build.sh` (takes 20-60min)
**Step 3: Commit**

```bash
git commit -m "feat: Batch 11 complete — pi-gen build system"
```

---

## Batch 12: CI/CD & Release

### Task 12.1: Create test.yml GitHub Action

**Files:**
- Create: `.github/workflows/test.yml`

On PR: lint Python (ruff), lint JS (eslint), run pytest, build frontend.

**Step 1: Implement test.yml**
**Step 2: Commit**

---

### Task 12.2: Create build-image.yml GitHub Action

**Files:**
- Create: `.github/workflows/build-image.yml`

On release tag: clone pi-gen, run Docker build, produce `.img.xz`, upload as artifact.

**Step 1: Implement build-image.yml**
**Step 2: Commit**

---

### Task 12.3: Create release.yml GitHub Action

**Files:**
- Create: `.github/workflows/release.yml`

On build success: create GitHub Release, attach `.img.xz` + SHA256 checksum, generate notes.

**Step 1: Implement release.yml**
**Step 2: Commit**

---

### Task 12.4: Update README, CHANGELOG, CLAUDE.md

**Files:**
- Modify: `README.md` — rewrite for the image-based workflow (flash instructions, screenshots)
- Modify: `CHANGELOG.md` — add v2.0.0 entry
- Modify: `CLAUDE.md` — update for new architecture

**Step 1: Update all docs**
**Step 2: Final commit**

```bash
git commit -m "feat: Batch 12 complete — CI/CD, release workflow, updated docs"
```

---

## Post-Implementation

After all batches complete:

1. **Smoke test on real Pi** — flash image, verify full boot flow
2. **Tag release** — `git tag v2.0.0 && git push --tags`
3. **Verify GitHub Actions** — image builds and publishes to Releases
4. **Test on Pi 3, 4, and 5** — verify multi-model support
5. **Close old issues** — superseded by the image approach
