# FrameCast API↔UI + superhot-ui Maximization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire all disconnected API endpoints to the phone SPA UI and maximize superhot-ui component usage from 32% to 68%, validated by the atmosphere-reviewer agent.

**Architecture:** Settings Expansion + component uplift across all pages. No new routes. 10 new superhot-ui Preact components + 6 JS utilities added. Backend adds 1 new endpoint. Atmosphere reviewer validates the entire UI at the end.

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

In `app/api.py`, add after the favorite toggle route:
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

Add imports at top:
```jsx
import { startHeartbeat } from "superhot-ui/js/heartbeat.js";
import { triggerRecovery } from "superhot-ui/js/recovery.js";
import { raiseIncident, clearIncident } from "./lib/incident.js";
```

Add to the app init (inside the existing `useEffect` or at module level after capability detection):
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
  } catch (_) { /* network error */ }
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

**Step 3: Add map nav visibility toggle**

Read localStorage pref to show/hide Map tab:
```jsx
const showMap = localStorage.getItem("fc_show_map") !== "false";
```

Filter the nav items array to conditionally include/exclude the Map tab based on this preference.

**Step 4: Build and commit**
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

## Batch 6: Settings Page — Full API Coverage

### Task 6.1: Add SYSTEM rows (backup download, reboot, shutdown)

**Files:**
- Modify: `app/frontend/src/pages/Settings.jsx`

**Step 1: Add imports**

```jsx
import { ShThreatPulse, ShStatusBadge, ShCrtToggle } from "superhot-ui/preact";
import { playSfx } from "superhot-ui/js/audio.js";
import { showToast } from "../lib/toast.js";
```

**Step 2: Add DOWNLOAD BACKUP row after RESTORE BACKUP**

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

**Step 3: Add REBOOT DEVICE row**

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

Add state: `const [rebootOpen, setRebootOpen] = useState(false);`

Add modal (near existing restart modal):
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
      // Poll for recovery
      const poll = setInterval(async () => {
        try {
          const res = await fetch("/api/status");
          if (res.ok) {
            clearInterval(poll);
            showToast("SYSTEM ONLINE", "info");
            window.location.reload();
          }
        } catch (_) { /* still rebooting */ }
      }, 3000);
    } catch (err) {
      showToast("REBOOT FAILED: " + err.message, "error");
    }
  }}
  onCancel={() => setRebootOpen(false)}
/>
```

**Step 4: Add SHUT DOWN row**

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

Add state: `const [shutdownOpen, setShutdownOpen] = useState(false);`

Add modal with ShThreatPulse:
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
      } catch (_) { /* expected — device is shutting down */ }
    }}
    onCancel={() => setShutdownOpen(false)}
  />
</ShThreatPulse>
```

**Step 5: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Settings.jsx
git commit -m "feat: Settings SYSTEM — backup download, reboot, shutdown with threat modal"
```

---

### Task 6.2: Add SCHEDULE TV status + MAP section + DISPLAY prefs

**Files:**
- Modify: `app/frontend/src/pages/Settings.jsx`

**Step 1: Add TV STATUS row to SCHEDULE section**

After the DISPLAY POWER toggle row:
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

// Fetch on SCHEDULE section expand
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
  <ShCrtToggle
    intensity={crtIntensity}
    onIntensityChange={(val) => {
      setCrtIntensity(val);
      localStorage.setItem("fc_crt_intensity", val);
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
// Fetch albums for add-to-album feature
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

**Step 1: Add remove action to album photo context menu**

When browsing an album's photos, add a "REMOVE" context menu item to each PhotoCard. The exact implementation depends on how the existing context menu works in PhotoCard — look for the existing pattern (favorite, tags, etc.) and follow it.

```jsx
// When viewing album photos, pass an onRemove handler:
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

## Batch 9: Upload — Search Wiring

### Task 9.1: Wire search icon to SearchModal

**Files:**
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/components/SearchModal.jsx` (verify API wiring)

**Step 1: Add search icon to Upload header**

```jsx
import SearchModal from "../components/SearchModal.jsx";

// Add state:
const [searchOpen, setSearchOpen] = useState(false);

// In the header area, add search button:
<button
  class="sh-input sh-clickable"
  style="min-width: 44px; min-height: 44px; padding: 8px; background: none; border: none; color: var(--sh-phosphor); font-size: 1.2rem;"
  onClick={() => setSearchOpen(true)}
  aria-label="Search photos"
>
  &#x1F50D;
</button>

// After the header, add modal:
<SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
```

**Step 2: Verify SearchModal uses authedFetch**

Read `app/frontend/src/components/SearchModal.jsx` and verify it calls `/api/search?q=...`. If it uses raw `fetch`, change to `fetchWithTimeout` or `authedFetch`.

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Upload.jsx app/frontend/src/components/SearchModal.jsx
git commit -m "feat: search icon in Upload header → wired to SearchModal + /api/search"
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
Expected: All tests pass (including new quarantine test)

**Step 3: Verify all new imports resolve**

Run: `cd app/frontend && node -e "require('./node_modules/superhot-ui/preact/ShPageBanner.jsx')" 2>&1 | head -3`
Expected: No errors

**Step 4: Final commit if any uncommitted changes**
```bash
git add -A
git commit -m "chore: final build artifacts + cleanup"
```

---

## Summary

| Batch | Focus | Files | New Components |
|-------|-------|-------|----------------|
| 1 | Quarantine endpoint | api.py, tests | — |
| 2 | Toast + incident + heartbeat infra | lib/toast.js, lib/incident.js, app.jsx | toastManager, heartbeat, recovery |
| 3 | PhoneLayout (mantra, HUD, toast) | PhoneLayout.jsx | ShMantra, ShIncidentHUD |
| 4 | ShPageBanner on all 12 views | 12 files | ShPageBanner |
| 5 | Empty + error states on 5 pages | 5 page files | ShEmptyState, ShErrorState |
| 6 | Settings full API coverage | Settings.jsx | ShThreatPulse, ShStatusBadge, ShCrtToggle |
| 7 | Stats page hero cards + chart | Stats.jsx | ShHeroCard, ShTimeChart |
| 8 | Lightbox albums + duplicates | Lightbox.jsx, Albums.jsx | ShStatusBadge (reuse) |
| 9 | Search wiring | Upload.jsx, SearchModal.jsx | — |
| 10 | Atmosphere review | All frontend | — |
| 11 | Final verification | All | — |

**Total: 11 batches, ~20 files, 10 new components, 6 new JS utilities**
**superhot-ui coverage: 32% → 68% components, 29% → 54% JS modules**
