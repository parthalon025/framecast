# FrameCast API Consolidation + superhot-ui Maximization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate all API endpoints into the `api.py` blueprint, retire the legacy v1 template interface, activate the phone SPA at `/`, and maximize superhot-ui component usage from 32% to 68%.

**Architecture:** Three-phase approach: (1) backend API migration — move misplaced routes, make upload/delete JSON-only, serve SPA at `/`, delete dead templates; (2) app infrastructure — centralized toast, heartbeat, incident state; (3) page-by-page superhot-ui uplift + atmosphere validation. No new API routes except quarantine. Frontend build validates each batch.

**Tech Stack:** Preact, JSX, esbuild, superhot-ui (0.4.0), Flask, SQLite

**Design doc:** `docs/plans/2026-03-20-api-ui-integration-design.md`

**Build command:** `cd app/frontend && npm run build`
**Test command:** `cd app && python3 -m pytest ../tests/ -v --timeout=120`

**IMPORTANT conventions:**
- NEVER use `h` or `Fragment` as callback parameter names in JSX (esbuild shadows `h`)
- All labels: UPPERCASE, terse, no prose (piOS voice)
- All touch targets: ≥44px, 8px spacing between interactive elements
- All inputs: ≥16px font-size (prevents iOS auto-zoom)
- All imports from superhot-ui: `from "superhot-ui/preact"` for components, `from "superhot-ui/js/<module>.js"` for utilities
- Stage specific files only (`git add <files>`) — never `git add -A`

---

## Batch 0: API Consolidation — Backend Migration

### Task 0.1: Move 3 misplaced /api/* routes from web_upload.py to api.py

**Files:**
- Modify: `app/web_upload.py` (remove lines 918-951)
- Modify: `app/api.py` (add after OTA update section, before line 1220)
- Test: `tests/test_api_integration.py`

**Step 1: Write failing test for the moved routes**

In `tests/test_api_integration.py`, add after existing tests:
```python
def test_restart_slideshow_in_api_blueprint(client):
    """POST /api/restart-slideshow should be handled by the API blueprint."""
    with mock.patch("modules.services.restart_slideshow", return_value=(True, "restarted")):
        resp = client.post("/api/restart-slideshow")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_reboot_in_api_blueprint(client):
    """POST /api/reboot should be handled by the API blueprint."""
    with mock.patch("subprocess.Popen"):
        resp = client.post("/api/reboot")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_shutdown_in_api_blueprint(client):
    """POST /api/shutdown should be handled by the API blueprint."""
    with mock.patch("subprocess.Popen"):
        resp = client.post("/api/shutdown")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
```

**Step 2: Run tests to verify they pass with current code**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py -k "restart_slideshow_in_api or reboot_in_api or shutdown_in_api" -v`
Expected: PASS (routes exist in web_upload.py, still accessible)

**Step 3: Cut the 3 routes from web_upload.py**

Remove from `app/web_upload.py` (lines 918-951):
- `restart_slideshow()` route
- `api_reboot()` route
- `api_shutdown()` route

Also remove the `services` import from line 36 (`from modules import config, db, media, services, wifi` → `from modules import config, db, media, wifi`).

**Step 4: Add the 3 routes to api.py**

In `app/api.py`, add a new section before the OTA Update section (before line 1187):
```python
# ---------------------------------------------------------------------------
# System control endpoints (migrated from web_upload.py)
# ---------------------------------------------------------------------------


@api.route("/restart-slideshow", methods=["POST"])
@require_pin
def restart_slideshow():
    """Restart the slideshow service."""
    from modules import services
    success, message = services.restart_slideshow()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 500


@api.route("/reboot", methods=["POST"])
@require_pin
def api_reboot():
    """Reboot the device."""
    try:
        log.info("Reboot requested via web UI")
        subprocess.Popen(["sudo", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "ok", "message": "Device is rebooting..."})
    except Exception:
        log.error("Failed to reboot", exc_info=True)
        return jsonify({"error": "Failed to reboot"}), 500


@api.route("/shutdown", methods=["POST"])
@require_pin
def api_shutdown():
    """Shut down the device."""
    try:
        log.info("Shutdown requested via web UI")
        subprocess.Popen(["sudo", "shutdown", "-h", "now"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "ok", "message": "Device is shutting down..."})
    except Exception:
        log.error("Failed to shut down", exc_info=True)
        return jsonify({"error": "Failed to shut down"}), 500
```

**Step 5: Run tests to verify routes still work**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py -k "restart_slideshow_in_api or reboot_in_api or shutdown_in_api" -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All pass

**Step 7: Commit**
```bash
git add app/api.py app/web_upload.py tests/test_api_integration.py
git commit -m "refactor: move restart-slideshow, reboot, shutdown routes to api.py blueprint"
```

---

### Task 0.2: Make upload/delete/delete-all JSON-only

**Files:**
- Modify: `app/web_upload.py`

**Step 1: Remove `_is_xhr()` helper**

Delete the `_is_xhr()` function (lines 424-429 in web_upload.py).

**Step 2: Make `POST /upload` JSON-only**

In the `upload()` function:
- Replace `if not _upload_semaphore.acquire(blocking=False):` block — remove the `if _is_xhr():`/`else:` branching, keep only the JSON response path:
  ```python
  if not _upload_semaphore.acquire(blocking=False):
      return jsonify({"error": "Another upload is in progress"}), 429
  ```

In `_do_upload()`:
- Remove `xhr = _is_xhr()` (first line of function).
- Replace every `if xhr:` / `if not xhr:` branch with just the JSON response. Remove all `flash()` calls and `redirect(url_for("index"))` returns.
- At the end, remove the `if xhr:` check — always return JSON:
  ```python
  return jsonify({
      "uploaded": uploaded_names,
      "uploaded_count": uploaded,
      "skipped": skipped,
  }), 200 if uploaded > 0 else 400
  ```

**Step 3: Make `POST /delete` JSON-only**

Remove all `_is_xhr()` checks and `flash()`/`redirect()` branches. Keep only JSON responses.

**Step 4: Make `POST /delete-all` JSON-only**

Remove the `_is_xhr()` check at the end (line 758). Always return JSON:
```python
return jsonify({"status": "ok", "deleted": count})
```

Remove the `flash` and `redirect` fallbacks.

**Step 5: Clean up imports**

Remove unused imports from web_upload.py:
- Remove `flash` from the Flask import line
- Remove `redirect` from the Flask import line
- Remove `url_for` from the Flask import line

The import line should become:
```python
from flask import (
    Flask,
    abort,
    jsonify,
    request,
    send_from_directory,
)
```

**Step 6: Run full test suite**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All pass

**Step 7: Commit**
```bash
git add app/web_upload.py
git commit -m "refactor: make upload/delete/delete-all JSON-only — remove dual-mode _is_xhr branching"
```

---

### Task 0.3: Serve SPA at / — retire dead template routes

**Files:**
- Modify: `app/web_upload.py`
- Test: `tests/test_api_integration.py`

**Step 1: Write test for SPA at /**

In `tests/test_api_integration.py`, add:
```python
def test_root_serves_spa_shell(client):
    """GET / should serve the SPA shell (spa.html), not the legacy index.html."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'id="app"' in html
    assert "superhot.css" in html
```

**Step 2: Run test to verify it fails**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py::test_root_serves_spa_shell -v`
Expected: FAIL — currently serves `index.html` which doesn't have `id="app"` or `superhot.css`

**Step 3: Replace the index route and delete dead routes**

In `app/web_upload.py`:

Replace the existing `GET /` route (the `index()` function at ~line 402) with:
```python
@app.route("/")
def index():
    return render_template("spa.html", version=_read_version())
```

Delete these dead routes entirely:
- `GET /map` — `map_page()` function
- `GET /settings` — `settings_page()` function
- `POST /settings` — `settings_save()` function (entire function including all validation)

Also delete the `config.load_env` import reference if `config` is no longer needed for template data (it's still needed for other functions, so keep the import).

**Step 4: Add SPA catch-all for client-side routes**

The SPA uses pushState routing for `/albums`, `/settings`, `/map`, `/stats`, `/users`. Flask needs to serve `spa.html` for these too. Add after the existing `/update` route:

```python
@app.route("/albums")
@app.route("/stats")
@app.route("/users")
def spa_phone_routes():
    """Serve SPA shell for all phone client-side routes."""
    return render_template("spa.html", version=_read_version())
```

Note: `/map` and `/settings` are removed above (were legacy template routes), so add them here:
```python
@app.route("/map")
@app.route("/settings")
@app.route("/albums")
@app.route("/stats")
@app.route("/users")
def spa_phone_routes():
    """Serve SPA shell for all phone client-side routes."""
    return render_template("spa.html", version=_read_version())
```

**Step 5: Run test to verify SPA is served at /**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py::test_root_serves_spa_shell -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All pass

**Step 7: Commit**
```bash
git add app/web_upload.py tests/test_api_integration.py
git commit -m "refactor: serve SPA at / — retire legacy index/map/settings templates, add catch-all"
```

---

### Task 0.4: Delete dead template files

**Files:**
- Delete: `app/templates/index.html`
- Delete: `app/templates/map.html`
- Delete: `app/templates/settings.html`

**Step 1: Verify the templates are no longer referenced**

Run: `grep -rn "index.html\|map.html\|settings.html" app/web_upload.py app/api.py`
Expected: No matches (all references removed in previous tasks)

**Step 2: Delete the files**

```bash
rm app/templates/index.html app/templates/map.html app/templates/settings.html
```

**Step 3: Verify only spa.html remains**

Run: `ls app/templates/`
Expected: `spa.html` only

**Step 4: Run full test suite**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All pass

**Step 5: Commit**
```bash
git add -u app/templates/
git commit -m "chore: delete dead legacy templates (index.html, map.html, settings.html)"
```

---

## Batch 1: Backend — Quarantine Endpoint

### Task 1.1: Add POST /api/photos/<id>/quarantine

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api_integration.py`

**Step 1: Write failing test**

In `tests/test_api_integration.py`, add:
```python
def test_quarantine_photo_from_localhost(client, sample_photo_id):
    """POST /api/photos/<id>/quarantine from localhost should succeed."""
    resp = client.post(
        f"/api/photos/{sample_photo_id}/quarantine",
        json={"reason": "corrupt image"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
```

**Step 2: Run test to verify it fails**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py::test_quarantine_photo_from_localhost -v`
Expected: FAIL — 404 Not Found

**Step 3: Implement the endpoint**

In `app/api.py`, add after the favorite toggle route (~line 511):
```python
@api.route("/photos/<int:photo_id>/quarantine", methods=["POST"])
def quarantine_photo(photo_id):
    """Quarantine a photo (localhost only — called from TV display)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "LOCALHOST ONLY"}), 403

    photo = db.get_photo_by_id(photo_id)
    if not photo:
        return jsonify({"error": "Photo not found"}), 404

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "auto-quarantined")
    db.update_photo_quarantine(photo_id, True, reason)
    log.info("Photo %d quarantined: %s", photo_id, reason)
    return jsonify({"status": "ok", "photo_id": photo_id})
```

**Step 4: Run test to verify it passes**

Run: `cd app && python3 -m pytest ../tests/test_api_integration.py::test_quarantine_photo_from_localhost -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All pass

**Step 6: Commit**
```bash
git add app/api.py tests/test_api_integration.py
git commit -m "feat: add POST /api/photos/<id>/quarantine — localhost-only, for TV display"
```

---

## Batch 2: App Infrastructure — Toast Manager + Heartbeat + Incident State

### Task 2.1: Create shared toast manager

**Files:**
- Create: `app/frontend/src/lib/toast.js`

**Step 1: Create the module**

```javascript
/** @fileoverview Centralized toast manager — single stack for entire app. */
import { signal } from "@preact/signals";

/** Current toast state: { type, message } or null */
export const toast = signal(null);

/** Show a toast — auto-clears after duration (0 = persistent). */
export function showToast(message, type = "info", duration = 4000) {
  toast.value = { type, message };
  if (duration > 0) {
    setTimeout(() => {
      if (toast.value?.message === message) toast.value = null;
    }, duration);
  }
}

/** Clear the current toast. */
export function clearToast() {
  toast.value = null;
}
```

**Step 2: Build**

Run: `cd app/frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**
```bash
git add app/frontend/src/lib/toast.js
git commit -m "feat: centralized toast manager — single stack for entire app"
```

---

### Task 2.2: Create incident state manager

**Files:**
- Create: `app/frontend/src/lib/incident.js`

**Step 1: Create the module**

```javascript
/** @fileoverview Incident state — tracks active device-level incidents. */
import { signal } from "@preact/signals";

/** Active incident: { severity, message, startedAt } or null */
export const incident = signal(null);

/** Set an active incident. */
export function raiseIncident(message, severity = "warning") {
  if (!incident.value) {
    incident.value = { severity, message, startedAt: Date.now() };
  }
}

/** Clear the active incident. */
export function clearIncident() {
  incident.value = null;
}
```

**Step 2: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/lib/incident.js
git commit -m "feat: incident state manager for device-level alerts"
```

---

### Task 2.3: Wire heartbeat + recovery into app.jsx

**Files:**
- Modify: `app/frontend/src/app.jsx`

**Step 1: Add heartbeat monitoring**

Add imports at top of app.jsx (after existing superhot-ui imports on line 15):
```jsx
import { startHeartbeat } from "superhot-ui/js/heartbeat.js";
import { triggerRecovery } from "superhot-ui/js/recovery.js";
import { raiseIncident, clearIncident } from "./lib/incident.js";
```

Add after the theme restoration block (after the `detectCapability`/`applyCapability`/`setFacilityState` calls):
```jsx
let consecutiveFailures = 0;

startHeartbeat(30000, async () => {
  try {
    const res = await fetch("/api/status");
    if (res.ok) {
      if (consecutiveFailures >= 3) {
        clearIncident();
        setFacilityState("normal");
        triggerRecovery(document.getElementById("app"));
      }
      consecutiveFailures = 0;
      return true;
    }
  } catch (_err) { /* network error */ }
  consecutiveFailures++;
  if (consecutiveFailures >= 3) {
    raiseIncident("NETWORK UNREACHABLE", "error");
    setFacilityState("alert");
  }
  return false;
});
```

**Step 2: Build and verify**

Run: `cd app/frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**
```bash
git add app/frontend/src/app.jsx
git commit -m "feat: heartbeat health monitor + recovery transitions in app.jsx"
```

---

## Batch 3: PhoneLayout — ShMantra + ShIncidentHUD + Centralized Toast

### Task 3.1: Add ShMantra, ShIncidentHUD, and centralized ShToast to PhoneLayout

**Files:**
- Modify: `app/frontend/src/components/PhoneLayout.jsx`

**Step 1: Add imports**

```jsx
import { ShMantra, ShIncidentHUD, ShToast } from "superhot-ui/preact";
import { toast, clearToast } from "../lib/toast.js";
import { incident, clearIncident } from "../lib/incident.js";
import { getFacilityState } from "superhot-ui/js/facility.js";
```

**Step 2: Add components to the layout render**

Inside the PhoneLayout return, before or after the `<ShNav>`, add:
```jsx
{/* Incident HUD — fixed top banner for active incidents */}
<ShIncidentHUD
  active={incident.value !== null}
  severity={incident.value?.severity || "warning"}
  message={incident.value?.message || ""}
  timestamp={incident.value?.startedAt}
  onAcknowledge={clearIncident}
/>

{/* Mantra watermark — ambient state (OFFLINE, UPLOADING, etc.) */}
{getFacilityState() === "alert" && (
  <ShMantra text="OFFLINE" active={true} />
)}

{/* Centralized toast — one stack for entire app */}
{toast.value && (
  <ShToast
    type={toast.value.type}
    message={toast.value.message}
    onDismiss={clearToast}
  />
)}
```

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/PhoneLayout.jsx
git commit -m "feat: ShMantra + ShIncidentHUD + centralized toast in PhoneLayout"
```

---

## Batch 4: ShPageBanner on All Pages

### Task 4.1: Add ShPageBanner to all pages and display views

**Files:**
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/pages/Albums.jsx`
- Modify: `app/frontend/src/pages/Settings.jsx`
- Modify: `app/frontend/src/pages/Map.jsx`
- Modify: `app/frontend/src/pages/Stats.jsx`
- Modify: `app/frontend/src/pages/Users.jsx`
- Modify: `app/frontend/src/pages/Onboard.jsx`
- Modify: `app/frontend/src/pages/Update.jsx`
- Modify: `app/frontend/src/display/Slideshow.jsx`
- Modify: `app/frontend/src/display/DisplayRouter.jsx`
- Modify: `app/frontend/src/display/Setup.jsx`
- Modify: `app/frontend/src/display/Welcome.jsx`

**Step 1: Add import to each file**

```jsx
import { ShPageBanner } from "superhot-ui/preact";
```

**Step 2: Add banner as first element in each page's return**

```jsx
<ShPageBanner namespace="FRAMECAST" page="UPLOAD" />
```

Page names: `UPLOAD`, `ALBUMS`, `SETTINGS`, `MAP`, `STATS`, `USERS`, `ONBOARD`, `UPDATE`, `SLIDESHOW`, `DISPLAY`, `SETUP`, `WELCOME`.

Replace any existing plain text page headers (e.g., `<h2>` or `<div class="fc-page-title">`) with the ShPageBanner.

**Step 3: Build**

Run: `cd app/frontend && npm run build`
Expected: Build succeeds

**Step 4: Commit**
```bash
git add app/frontend/src/pages/ app/frontend/src/display/
git commit -m "feat: ShPageBanner on all 12 views — diegetic wayfinding"
```

---

## Batch 5: ShEmptyState + ShErrorState on All Data Pages

### Task 5.1: Add ShEmptyState and ShErrorState to Upload, Albums, Map, Stats, Users

**Files:**
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/pages/Albums.jsx`
- Modify: `app/frontend/src/pages/Map.jsx`
- Modify: `app/frontend/src/pages/Stats.jsx`
- Modify: `app/frontend/src/pages/Users.jsx`

**Step 1: Add imports to each file**

```jsx
import { ShEmptyState, ShErrorState } from "superhot-ui/preact";
```

**Step 2: Add empty states**

In each page, find the loading/empty condition and replace blank space with:

| Page | Condition | Component |
|------|-----------|-----------|
| Upload | `photos.length === 0 && !loading` | `<ShEmptyState message="NO PHOTOS" hint="DROP FILES TO BEGIN" />` |
| Albums | `albums.length === 0 && !loading` | `<ShEmptyState message="NO ALBUMS" hint="CREATE ONE TO ORGANIZE" />` |
| Map | `locations.length === 0 && !loading` | `<ShEmptyState message="NO LOCATIONS" hint="UPLOAD PHOTOS WITH GPS" />` |
| Stats | `!stats && !loading` | `<ShEmptyState message="NO DISPLAY DATA" hint="SLIDESHOW NOT YET ACTIVE" />` |
| Users | `users.length === 0 && !loading` | `<ShEmptyState message="NO USERS" hint="DEFAULT ACTIVE" />` |

**Step 3: Add error states**

In each page, find the `catch` blocks that currently log to console.warn and replace with visible errors:

```jsx
// Replace: console.warn("Albums: fetchAlbums failed", err);
// With:
fetchError.value = err.message || "FETCH FAILED";

// In render:
{fetchError.value && (
  <ShErrorState
    title="FAULT"
    message={fetchError.value}
    onRetry={() => { fetchError.value = null; fetchAlbums(); }}
  />
)}
```

Apply this pattern to Albums, Map, Stats, Users. Upload already has a `fetchError` signal — replace its custom error div with `ShErrorState`.

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/
git commit -m "feat: ShEmptyState + ShErrorState on all data pages"
```

---

## Batch 6: Settings Page — System Controls + superhot-ui Uplift

**Note:** Phase 8 already added timezone, SSH/HTTPS toggles, guest upload, dark/light mode, frame discovery, settings import/export, and transition preview to Settings.jsx. This batch adds ONLY what's missing: reboot/shutdown modals, TV status badge, MAP section, CRT toggle, audio pref, and download backup.

### Task 6.1: Add reboot + shutdown with ShThreatPulse modals

**Files:**
- Modify: `app/frontend/src/pages/Settings.jsx`

**Step 1: Add imports**

Add to existing import line (line 8):
```jsx
import { ShCollapsible, ShModal, ShToast, ShSkeleton, ShThreatPulse, ShStatusBadge } from "superhot-ui/preact";
import { playSfx } from "superhot-ui/js/audio.js";
import { showToast } from "../lib/toast.js";
```

**Step 2: Add state variables**

Add to the existing useState block (around line 65):
```jsx
const [rebootOpen, setRebootOpen] = useState(false);
const [shutdownOpen, setShutdownOpen] = useState(false);
```

**Step 3: Add DOWNLOAD BACKUP row in SYSTEM section**

In the SYSTEM section (around line 855, after RESTORE BACKUP row), add:
```jsx
<SettingRow label="DOWNLOAD BACKUP">
  <a
    class="sh-input sh-clickable"
    href="/api/backup"
    style="text-align: center; min-width: 120px; text-decoration: none; display: inline-block;"
  >
    DOWNLOAD
  </a>
</SettingRow>
```

**Step 4: Add REBOOT DEVICE row in SYSTEM section**

After DOWNLOAD BACKUP:
```jsx
<SettingRow label="REBOOT DEVICE">
  <button
    class="sh-input sh-clickable"
    style="text-align: center; min-width: 120px;"
    onClick={() => setRebootOpen(true)}
  >
    REBOOT
  </button>
</SettingRow>
```

**Step 5: Add SHUT DOWN row in SYSTEM section**

```jsx
<SettingRow label="SHUT DOWN">
  <button
    class="sh-input sh-clickable"
    style="text-align: center; min-width: 120px; color: var(--sh-threat);"
    onClick={() => setShutdownOpen(true)}
  >
    SHUT DOWN
  </button>
</SettingRow>
```

**Step 6: Add reboot confirmation modal**

Add near the existing restart modal (around line 969):
```jsx
<ShModal
  open={rebootOpen}
  title="CONFIRM: REBOOT DEVICE?"
  body="SLIDESHOW INTERRUPTS. RESTARTS IN ~30s."
  confirmLabel="REBOOT"
  cancelLabel="CANCEL"
  onConfirm={async () => {
    setRebootOpen(false);
    showToast("REBOOTING — STANDBY", "info", 0);
    try {
      await fetch("/api/reboot", { method: "POST" });
      const poll = setInterval(async () => {
        try {
          const res = await fetch("/api/status");
          if (res.ok) {
            clearInterval(poll);
            showToast("SYSTEM ONLINE", "info");
            window.location.reload();
          }
        } catch (_err) { /* still rebooting */ }
      }, 3000);
    } catch (err) {
      showToast("REBOOT FAILED: " + err.message, "error");
    }
  }}
  onCancel={() => setRebootOpen(false)}
/>
```

**Step 7: Add shutdown modal wrapped in ShThreatPulse**

```jsx
<ShThreatPulse active={shutdownOpen} persistent>
  <ShModal
    open={shutdownOpen}
    title="CONFIRM: SHUT DOWN?"
    body="REQUIRES PHYSICAL ACCESS TO RESTART."
    confirmLabel="SHUT DOWN"
    cancelLabel="CANCEL"
    onConfirm={async () => {
      setShutdownOpen(false);
      showToast("SHUTTING DOWN", "error", 0);
      try {
        await fetch("/api/shutdown", { method: "POST" });
      } catch (_err) { /* expected — device is shutting down */ }
    }}
    onCancel={() => setShutdownOpen(false)}
  />
</ShThreatPulse>
```

**Step 8: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Settings.jsx
git commit -m "feat: Settings SYSTEM — backup download, reboot, shutdown with threat modal"
```

---

### Task 6.2: Add TV status badge, MAP section, CRT toggle, audio pref

**Files:**
- Modify: `app/frontend/src/pages/Settings.jsx`

**Step 1: Add TV STATUS row to SCHEDULE section**

After the DISPLAY POWER toggle row (line 674), add:
```jsx
<SettingRow label="TV STATUS">
  <ShStatusBadge
    status={tvStatus === "on" ? "healthy" : tvStatus === "standby" ? "warning" : "waiting"}
    label={tvStatus ? tvStatus.toUpperCase() : "STANDBY"}
  />
</SettingRow>
```

Add state and fetch:
```jsx
const [tvStatus, setTvStatus] = useState(null);

const fetchTvStatus = () => {
  fetch("/api/display/status")
    .then((res) => res.json())
    .then((data) => setTvStatus(data.power))
    .catch(() => setTvStatus("unknown"));
};
```

Wire `fetchTvStatus` to the SCHEDULE `ShCollapsible` `onToggle` or first expand.

**Step 2: Add MAP section (new ShCollapsible between NETWORK and SYSTEM)**

```jsx
{/* ── MAP ── */}
<section aria-label="Map settings">
  <ShCollapsible title="MAP" defaultOpen={false}>
    <div class="fc-settings-section">
      <SettingRow label="SHOW IN NAV">
        <Toggle
          on={showMapNav}
          onToggle={(val) => {
            setShowMapNav(val);
            localStorage.setItem("fc_show_map", val ? "true" : "false");
          }}
        />
      </SettingRow>
      <SettingRow label="GPS PHOTOS">
        <ShStatusBadge
          status={gpsCount > 0 ? "ok" : "waiting"}
          label={gpsCount !== null ? `${gpsCount} LOCATED` : "STANDBY"}
        />
      </SettingRow>
    </div>
  </ShCollapsible>
</section>
```

Add state:
```jsx
const [showMapNav, setShowMapNav] = useState(localStorage.getItem("fc_show_map") !== "false");
const [gpsCount, setGpsCount] = useState(null);
```

Fetch GPS count on section expand:
```jsx
fetchWithTimeout("/api/locations").then((res) => res.json()).then((locs) => setGpsCount(locs.length));
```

**Step 3: Add CRT MODE and AUDIO to DISPLAY section**

```jsx
<SettingRow label="CRT EFFECT">
  <Toggle
    on={crtEnabled}
    onToggle={(val) => {
      setCrtEnabled(val);
      localStorage.setItem("fc_crt_enabled", val ? "true" : "false");
    }}
  />
</SettingRow>

<SettingRow label="AUDIO FEEDBACK">
  <Toggle
    on={audioEnabled}
    onToggle={(val) => {
      setAudioEnabled(val);
      localStorage.setItem("fc_audio_enabled", val ? "true" : "false");
    }}
  />
</SettingRow>
```

Add state:
```jsx
const [crtEnabled, setCrtEnabled] = useState(localStorage.getItem("fc_crt_enabled") !== "false");
const [audioEnabled, setAudioEnabled] = useState(localStorage.getItem("fc_audio_enabled") === "true");
```

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Settings.jsx
git commit -m "feat: Settings — TV status badge, MAP section, CRT toggle, audio pref"
```

---

## Batch 7: Stats Page — ShHeroCard + ShTimeChart

### Task 7.1: Replace stat cards with ShHeroCard + add ShTimeChart

**Files:**
- Modify: `app/frontend/src/pages/Stats.jsx`

**Step 1: Add imports**

```jsx
import { ShHeroCard, ShTimeChart } from "superhot-ui/preact";
```

**Step 2: Replace top stat cards with ShHeroCard**

Find the existing ShStatsGrid + ShStatCard section and replace the primary KPIs:
```jsx
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px;">
  <ShHeroCard label="TOTAL PHOTOS" value={stats.total_photos - stats.videos} />
  <ShHeroCard label="VIDEOS" value={stats.videos} />
  <ShHeroCard label="STORAGE" value={`${diskPct}%`} warning={diskPct > 85} />
  <ShHeroCard label="TOTAL VIEWS" value={stats.total_views} />
</div>
```

Keep the existing ShStatsGrid/ShStatCard for secondary stats (by_user, most_shown, least_shown).

**Step 3: Add upload trend chart**

If stats have temporal data, add:
```jsx
{uploadTrend && uploadTrend.length > 1 && (
  <ShTimeChart
    data={uploadTrend}
    label="UPLOADS / WEEK"
    color="var(--sh-phosphor)"
    compact
  />
)}
```

Derive `uploadTrend` from existing data — group uploads by week from `by_user` data or photo upload dates.

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Stats.jsx
git commit -m "feat: Stats page — ShHeroCard KPIs + ShTimeChart upload trend"
```

---

## Batch 8: Lightbox — Album Management + Duplicate Detection

### Task 8.1: Add album management to Lightbox

**Files:**
- Modify: `app/frontend/src/components/Lightbox.jsx`

**Step 1: Add imports**

```jsx
import { ShStatusBadge } from "superhot-ui/preact";
import { showToast } from "../lib/toast.js";
```

**Step 2: Fetch albums on Lightbox open**

In the existing `useEffect` that runs on photo change, add:
```jsx
fetch("/api/albums").then((res) => res.json()).then(setAlbums).catch(() => {});
```

**Step 3: Add "ADD TO ALBUM" UI**

Below the tag section in Lightbox, add:
```jsx
{/* Album management */}
<div style="margin-top: 12px;">
  <span class="sh-ansi-dim" style="font-size: 0.75rem; letter-spacing: 0.1em;">ALBUM</span>
  <select
    class="sh-input"
    style="margin-top: 4px; width: 100%; font-size: max(16px, 1rem);"
    onChange={async (evt) => {
      const albumId = evt.target.value;
      if (!albumId) return;
      try {
        await fetch(`/api/albums/${albumId}/photos`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ photo_id: photo.id }),
        });
        showToast("ADDED TO ALBUM", "info");
      } catch (err) {
        showToast("FAULT: " + err.message, "error");
      }
      evt.target.value = "";
    }}
  >
    <option value="">ADD TO ALBUM...</option>
    {albums.map((album) => (
      <option key={album.id} value={album.id}>{album.name}</option>
    ))}
  </select>
</div>
```

**Step 4: Add duplicate detection**

```jsx
{duplicates.length > 0 && (
  <div style="margin-top: 12px;">
    <ShStatusBadge status="warning" label={`${duplicates.length} SIMILAR`} />
    <div style="display: flex; gap: 4px; margin-top: 8px; overflow-x: auto;">
      {duplicates.map((dupe) => (
        <img
          key={dupe.id}
          src={`/thumbnail/${dupe.filename}`}
          alt={dupe.filename}
          style="width: 48px; height: 48px; object-fit: cover; cursor: pointer; border: 1px solid var(--sh-dim);"
          onClick={() => props.onNavigate?.(dupe)}
          loading="lazy"
        />
      ))}
    </div>
  </div>
)}
```

Fetch duplicates in the photo-change effect:
```jsx
fetch(`/api/photos/${photo.id}/duplicates`)
  .then((res) => res.json())
  .then((data) => setDuplicates(data.duplicates || []))
  .catch(() => setDuplicates([]));
```

**Step 5: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/Lightbox.jsx
git commit -m "feat: Lightbox — add-to-album dropdown + duplicate detection badge"
```

---

### Task 8.2: Add remove-from-album to Albums page

**Files:**
- Modify: `app/frontend/src/pages/Albums.jsx`

**Step 1: Add remove action to album photo view**

When browsing an album's photos, add a "REMOVE" context menu item to each PhotoCard. Follow the existing context menu pattern (favorite, tags, etc.):

```jsx
<PhotoGrid
  photos={albumPhotos}
  onRemove={selectedAlbum.value ? (photo) => {
    if (confirm("REMOVE FROM " + selectedAlbum.value.name + "?")) {
      fetch(`/api/albums/${selectedAlbum.value.id}/photos/${photo.id}`, { method: "DELETE" })
        .then(() => {
          fetchAlbumPhotos(selectedAlbum.value.id);
          showToast("REMOVED", "info");
        })
        .catch((err) => showToast("FAULT: " + err.message, "error"));
    }
  } : undefined}
/>
```

**Step 2: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Albums.jsx
git commit -m "feat: remove-from-album action in album photo view"
```

---

## Batch 9: Upload — Search Wiring + Bulk Bar superhot-ui Uplift

### Task 9.1: Wire search icon to SearchModal

**Files:**
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/components/SearchModal.jsx` (verify API wiring)

**Step 1: Verify SearchModal API wiring**

Read `app/frontend/src/components/SearchModal.jsx` and verify it calls `/api/search?q=...`. If it uses raw `fetch`, change to `fetchWithTimeout`.

**Step 2: Verify search integration**

Check if SearchModal is already wired in Upload.jsx (Phase 3 commit `3100e90` may have done this). If already wired, skip this task. If not:

Add search button in the Upload header and wire SearchModal:
```jsx
import SearchModal from "../components/SearchModal.jsx";

const [searchOpen, setSearchOpen] = useState(false);

// In header area:
<button
  class="sh-input sh-clickable"
  style="min-width: 44px; min-height: 44px; padding: 8px; background: none; border: none; color: var(--sh-phosphor); font-size: 1.2rem;"
  onClick={() => setSearchOpen(true)}
  aria-label="Search photos"
>
  &#x1F50D;
</button>

<SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
```

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Upload.jsx app/frontend/src/components/SearchModal.jsx
git commit -m "feat: search icon in Upload header → wired to SearchModal + /api/search"
```

---

### Task 9.2: superhot-ui uplift for Phase 8 bulk action bar

**Files:**
- Modify: `app/frontend/src/pages/Upload.jsx`

**Step 1: Add imports**

```jsx
import { ShThreatPulse, ShStatusBadge } from "superhot-ui/preact";
import { showToast } from "../lib/toast.js";
```

**Step 2: Upgrade bulk action bar**

Find the existing `fc-bulk-bar` div (around line 690) and upgrade:
- Replace the raw count span with `ShStatusBadge`:
  ```jsx
  <ShStatusBadge status="warning" label={`${selectedIds.value.size} SELECTED`} />
  ```
- Wrap the DELETE button in `ShThreatPulse`:
  ```jsx
  <ShThreatPulse active={selectedIds.value.size > 0}>
    <button
      class="fc-bulk-bar__btn fc-bulk-bar__btn--danger"
      onClick={handleBatchDelete}
      type="button"
    >
      DELETE
    </button>
  </ShThreatPulse>
  ```
- Add toast feedback to batch operations — in `handleBatchDelete`, after `fetchPhotos()`:
  ```jsx
  showToast(`${ids.length} QUARANTINED`, "info");
  ```
- In `handleBatchFavorite`, after `fetchPhotos()`:
  ```jsx
  showToast(`${ids.length} TOGGLED`, "info");
  ```

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Upload.jsx
git commit -m "feat: superhot-ui uplift for bulk action bar — ShThreatPulse, ShStatusBadge, toast"
```

---

## Batch 10: Atmosphere Validation

### Task 10.1: Run atmosphere reviewer agent

**Action:** Dispatch the superhot-ui atmosphere-reviewer agent against the entire `app/frontend/src/` directory.

The atmosphere reviewer checks:
1. piOS voice on all labels
2. Failure theater coordination (6 surfaces)
3. Emotional arc (tension→catharsis)
4. Time-freeze discipline (ShFrozen usage)
5. Touch targets (≥44px)
6. Palette compliance (phosphor/void/threat/bright only)
7. Font sizes (≥16px on inputs)
8. Safe area compliance
9. CRT coherence
10. Audio coherence
11. Recovery catharsis

**After review:** Fix any findings, rebuild, and commit:
```bash
cd app/frontend && npm run build
git add app/frontend/src/
git commit -m "atmosphere: fix findings from superhot-ui atmosphere review"
```

---

## Batch 11: Final Build + Test Verification

### Task 11.1: Full build + test + verify

**Step 1: Frontend build**

Run: `cd app/frontend && npm run build`
Expected: Build succeeds with no errors

**Step 2: Backend tests**

Run: `cd app && python3 -m pytest ../tests/ -v --timeout=120`
Expected: All tests pass (including new quarantine test + API migration tests)

**Step 3: Verify all new imports resolve**

Run: `cd app/frontend && node -e "import('superhot-ui/preact')" 2>&1 | head -3`
Expected: No errors

**Step 4: Verify SPA serves at /**

Run: `cd app && python3 -c "from web_upload import app; c = app.test_client(); r = c.get('/'); assert b'id=\"app\"' in r.data, 'SPA not served at /'; print('OK: SPA at /')"`
Expected: `OK: SPA at /`

**Step 5: Final commit if any uncommitted changes**
```bash
git add app/ tests/
git commit -m "chore: final build artifacts + cleanup"
```

---

## Summary

| Batch | Focus | Files | Key Changes |
|-------|-------|-------|-------------|
| 0 | **API consolidation** | api.py, web_upload.py, templates, tests | Move 3 routes, JSON-only upload/delete, SPA at /, delete dead templates |
| 1 | Quarantine endpoint | api.py, tests | New localhost-only quarantine route |
| 2 | Toast + incident + heartbeat infra | lib/toast.js, lib/incident.js, app.jsx | Shared state managers, health monitoring |
| 3 | PhoneLayout (mantra, HUD, toast) | PhoneLayout.jsx | ShMantra, ShIncidentHUD, centralized ShToast |
| 4 | ShPageBanner on all 12 views | 12 files | Diegetic page headers |
| 5 | Empty + error states on 5 pages | 5 page files | ShEmptyState, ShErrorState |
| 6 | Settings system controls | Settings.jsx | Reboot/shutdown ShThreatPulse modals, TV status, MAP, CRT, audio |
| 7 | Stats page hero cards + chart | Stats.jsx | ShHeroCard, ShTimeChart |
| 8 | Lightbox albums + duplicates | Lightbox.jsx, Albums.jsx | Album management, duplicate detection |
| 9 | Search + bulk bar uplift | Upload.jsx, SearchModal.jsx | Search wiring, ShThreatPulse on bulk delete |
| 10 | Atmosphere review | All frontend | Validation against 11 criteria |
| 11 | Final verification | All | Build + tests + SPA verification |

**Total: 12 batches, ~25 files, 10 new superhot-ui components, 6 new JS utilities**
**API consolidation: web_upload.py drops from 981 → ~500 lines, api.py becomes single source of truth**
**superhot-ui coverage: 32% → 68% components, 29% → 54% JS modules**
