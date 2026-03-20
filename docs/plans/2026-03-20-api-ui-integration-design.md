# FrameCast API↔UI Full Integration + superhot-ui Maximization Design

**Date:** 2026-03-20
**Goal:** Wire all disconnected API endpoints to the phone SPA, create the missing quarantine endpoint, maximize superhot-ui component usage (from 32% to ~75%), and validate atmosphere coherence.

**Architecture:** Settings Expansion approach — no new routes. Superhot-ui maximization adds 10 components + 6 JS utilities to the existing 9 components + 7 utilities. Every new UI surface uses the design system, not ad-hoc styles.

**Current state:** 9/28 components used (32%), 7/24 JS modules used (29%)
**Target state:** 19/28 components (~68%), 13/24 JS modules (~54%)

---

## Part 1: Backend — New Quarantine API Endpoint

`POST /api/photos/<int:photo_id>/quarantine`

- Body: `{"reason": "corrupt image"}` (optional, defaults to "auto-quarantined")
- Response: `{"status": "ok", "photo_id": 123}`
- Auth: **Localhost only** — `request.remote_addr in ("127.0.0.1", "::1")`. Called from TV browser (cage), not phone. Remote returns 403.
- Implementation: Single route in `api.py` → `db.update_photo_quarantine(photo_id, True, reason)`

---

## Part 2: App-Wide Infrastructure (new superhot-ui wiring)

### 2A: ShPageBanner on every page

Replace plain text headers with `ShPageBanner` on all 8 pages + 4 display views.

```jsx
<ShPageBanner namespace="FRAMECAST" page="UPLOAD" />
<ShPageBanner namespace="FRAMECAST" page="ALBUMS" />
<ShPageBanner namespace="FRAMECAST" page="SETTINGS" />
<ShPageBanner namespace="FRAMECAST" page="MAP" />
<ShPageBanner namespace="FRAMECAST" page="STATS" />
<ShPageBanner namespace="FRAMECAST" page="USERS" />
<ShPageBanner namespace="FRAMECAST" page="ONBOARD" />
<ShPageBanner namespace="FRAMECAST" page="UPDATE" />
```

Display views:
```jsx
<ShPageBanner namespace="FRAMECAST" page="SLIDESHOW" />
<ShPageBanner namespace="FRAMECAST" page="SETUP" />
<ShPageBanner namespace="FRAMECAST" page="WELCOME" />
```

**Component:** ShPageBanner (pixel-art header with namespace + page name + scan-beam animation)

### 2B: Centralized toast manager

Replace per-page toast state with `createToastManager()` from `superhot-ui/js/toastManager.js`.

- Create `lib/toast.js` exporting a shared toast manager instance
- All pages import from `lib/toast.js` instead of managing their own `[toast, setToast]` state
- Single `<ShToast>` rendered in `PhoneLayout.jsx` (one toast stack for the whole app)

### 2C: Heartbeat health monitoring

Wire `startHeartbeat()` from `superhot-ui/js/heartbeat.js` into `app.jsx`:

```jsx
import { startHeartbeat } from "superhot-ui/js/heartbeat.js";

// On mount: check API health every 30s
startHeartbeat(30000, async () => {
  const res = await fetch("/api/status");
  return res.ok;
});
```

On heartbeat failure → `setFacilityState("alert")` + show ShIncidentHUD
On heartbeat recovery → `triggerRecovery()` on layout root + `setFacilityState("normal")`

### 2D: ShMantra for global state watermarks

Wire `ShMantra` on the layout root for three states:

| State | Mantra text | Trigger |
|-------|------------|---------|
| Offline | `OFFLINE` | heartbeat fails 3 consecutive times |
| Uploading | `UPLOADING` | batch upload in progress |
| Shutting down | `SHUTTING DOWN` | after `POST /api/shutdown` confirmed |

```jsx
{facilityState === "alert" && <ShMantra text="OFFLINE" />}
```

### 2E: ShIncidentHUD for persistent alerts

Fixed top banner for active incidents (network down, storage full, thermal):

```jsx
<ShIncidentHUD
  active={incident !== null}
  message={incident?.message}
  startedAt={incident?.startedAt}
  onAcknowledge={() => clearIncident()}
/>
```

Triggers:
- Heartbeat failure → `NETWORK UNREACHABLE`
- Storage > 95% → `STORAGE CRITICAL`
- DB flush failures → `DATABASE ERROR`

### 2F: Audio feedback (user opt-in)

Wire `playSfx()` from `superhot-ui/js/audio.js`:

| Event | Sound | Condition |
|-------|-------|-----------|
| Upload complete | `playSfx('complete')` | Audio enabled in settings |
| Upload/fetch error | `playSfx('error')` | Audio enabled |
| Device boot | `playSfx('boot')` | Already wired via bootSequence |
| Recovery from offline | `playSfx('recovery')` | Audio enabled |

Add AUDIO toggle to Settings → DISPLAY section (stored in localStorage).

### 2G: Recovery effects

Wire `triggerRecovery()` from `superhot-ui/js/recovery.js`:

- After heartbeat recovers (was offline, now online) → recovery burst on layout root
- After successful reboot poll (device came back) → recovery burst + ShToast `SYSTEM ONLINE`
- After upload batch completes → recovery burst on dropzone

---

## Part 3: Settings Page Enhancements

### 3A: DISPLAY section additions

| Row | Component | API |
|-----|-----------|-----|
| CRT MODE | `ShCrtToggle` — scanline/stripe/flicker toggles | localStorage (client-side pref) |
| AUDIO FEEDBACK | Toggle — enables `playSfx()` on events | localStorage |

### 3B: SCHEDULE section additions

| Row | Component | API |
|-----|-----------|-----|
| TV STATUS | `ShStatusBadge` — `ON` (healthy) / `STANDBY` (warning) / `UNKNOWN` (waiting) | `GET /api/display/status` polled on section expand |

### 3C: MAP section (new ShCollapsible, between NETWORK and SYSTEM)

| Row | Component | API |
|-----|-----------|-----|
| MAP IN NAV | Toggle — show/hide Map tab in bottom nav | localStorage |
| GPS PHOTOS | `ShStatusBadge` count: `247 LOCATED` | `GET /api/locations` count on expand |

### 3D: SYSTEM section additions

| Row | Component | API |
|-----|-----------|-----|
| DOWNLOAD BACKUP | `<a href="/api/backup">` styled as `sh-input sh-clickable` | `GET /api/backup` |
| REBOOT | Button → ShModal (double-confirm) | `POST /api/reboot` |
| SHUT DOWN | Button → ShModal + `ShThreatPulse` wrapper (red pulsing border) | `POST /api/shutdown` |

**Reboot modal:**
- Title: `CONFIRM: REBOOT DEVICE?`
- Body: `SLIDESHOW INTERRUPTS. RESTARTS IN ~30s.`
- On confirm: ShToast `REBOOTING — STANDBY` → poll `/api/status` every 3s → on return: `triggerRecovery()` + ShToast `SYSTEM ONLINE`

**Shutdown modal (wrapped in ShThreatPulse):**
- Title: `CONFIRM: SHUT DOWN?`
- Body: `REQUIRES PHYSICAL ACCESS TO RESTART.`
- On confirm: ShToast `SHUTTING DOWN` → `ShMantra text="SHUTTING DOWN"` → facility state `breach`

---

## Part 4: Stats Page — ShHeroCard + ShTimeChart

Replace the current ShStatCard layout with ShHeroCard for primary KPIs:

### Hero cards (top row)
```jsx
<ShHeroCard label="TOTAL PHOTOS" value={stats.total_photos} />
<ShHeroCard label="STORAGE" value={`${diskPct}%`} status={diskPct > 90 ? "error" : "ok"} />
<ShHeroCard label="TOTAL VIEWS" value={stats.total_views} />
```

### Time chart (below heroes)
```jsx
<ShTimeChart
  data={uploadTrend}
  label="UPLOADS / WEEK"
  color="var(--sh-phosphor)"
/>
```

Data source: derive from existing `GET /api/stats` response (group `by_user` upload counts by week). No new API needed — transform client-side.

---

## Part 5: Empty States — ShEmptyState

Replace blank/loading states with `ShEmptyState` on every page:

| Page | Condition | Message |
|------|-----------|---------|
| Upload | No photos | `NO PHOTOS. DROP FILES TO BEGIN.` |
| Albums | No albums | `NO ALBUMS. CREATE ONE TO ORGANIZE.` |
| Map | No GPS photos | `NO LOCATIONS. UPLOAD PHOTOS WITH GPS.` |
| Stats | No data | `NO DISPLAY DATA. SLIDESHOW NOT YET ACTIVE.` |
| Users | No users | `NO USERS. DEFAULT ACTIVE.` |

```jsx
{photos.length === 0 && !loading && (
  <ShEmptyState message="NO PHOTOS. DROP FILES TO BEGIN." />
)}
```

---

## Part 6: Error States — ShErrorState

Replace console.warn catch blocks with visible `ShErrorState`:

| Page | Error | Current behavior | New behavior |
|------|-------|-----------------|--------------|
| Upload | Photo fetch fails | `fetchError` signal sets text, shows as styled div | `ShErrorState message="PHOTO FETCH FAILED" onRetry={fetchPhotos}` |
| Albums | Album fetch fails | console.warn only | ShErrorState with retry |
| Map | Location fetch fails | Map shows empty | ShErrorState with retry |
| Stats | Stats fetch fails | Fallback to basic stats | ShErrorState with retry |
| Users | User fetch fails | console.warn only | ShErrorState with retry |

```jsx
{error && <ShErrorState message={error} onRetry={refetch} />}
```

---

## Part 7: Lightbox — Album Management + Duplicates

### Add to album
- New action row below tags: `ADD TO ALBUM` button (44px target)
- Tap → dropdown of albums from `GET /api/albums`
- Select → `POST /api/albums/<id>/photos` with `{"photo_id": id}`
- Feedback: ShToast `ADDED TO [ALBUM]`
- If already in album: `ShStatusBadge status="ok"` + album name (dimmed)

### Remove from album
- Album photo grid context menu: `REMOVE` action
- ShModal: `REMOVE FROM [ALBUM]?` / `PHOTO PRESERVED.`
- `DELETE /api/albums/<id>/photos/<photo_id>`
- ShToast `REMOVED`

### Duplicate detection
- On Lightbox open: `GET /api/photos/<id>/duplicates`
- If results: `ShStatusBadge` badge: `N SIMILAR`
- Tap → expandable thumbnail strip
- No results = badge hidden (no empty state for this)

---

## Part 8: Upload — Search Wiring

- SearchModal component exists but needs verified API wiring
- Add magnifying glass icon to Upload header (44px, top-right)
- Tap → SearchModal
- SearchModal calls `GET /api/search?q=...` via `authedFetch`
- Results as PhotoCard grid in modal
- Tap result → Lightbox

---

## Part 9: Atmosphere Validation (superhot-ui atmo agent)

After all UI changes, dispatch the atmosphere-reviewer agent to validate:

1. **piOS voice** — all new labels UPPERCASE, terse, no prose, no apologetic empty states
2. **Failure theater** — 6 coordinated surfaces (ShThreatPulse, ShIncidentHUD, ShMantra, ShToast, ShStatusBadge, facility state)
3. **Emotional arc** — tension→pause→plan→execute→catharsis flow on upload, reboot, recovery
4. **Time-freeze discipline** — ShFrozen on TV status, location count, stats data
5. **Touch targets** — ≥44px on all new interactive elements, 8px spacing
6. **Palette** — only phosphor/void/threat/bright — no new colors
7. **Font sizes** — all inputs ≥16px (iOS auto-zoom prevention)
8. **Safe areas** — env(safe-area-inset-*) on new bottom-positioned elements
9. **CRT coherence** — ShCrtToggle preference applied globally
10. **Audio coherence** — playSfx only when user-enabled, never auto-play
11. **Recovery catharsis** — every error state has a matching recovery transition

---

## Component Addition Summary

### New Preact components (10)
| Component | Where | Purpose |
|-----------|-------|---------|
| ShPageBanner | All 11 views | Diegetic page headers |
| ShStatusBadge | Settings TV/WiFi, Lightbox dupes, Map GPS | Inline status indicators |
| ShErrorState | Upload, Albums, Map, Stats, Users | Non-modal error + retry |
| ShEmptyState | Upload, Albums, Map, Stats, Users | Proper empty states |
| ShMantra | PhoneLayout root | OFFLINE / UPLOADING / SHUTTING DOWN watermark |
| ShIncidentHUD | PhoneLayout root | Persistent alert banner (network, storage, DB) |
| ShHeroCard | Stats page | Primary KPI display |
| ShTimeChart | Stats page | Upload trends over time |
| ShThreatPulse | Shutdown modal, storage critical | Red pulsing border on critical |
| ShCrtToggle | Settings DISPLAY | User-controllable CRT effect |

### New JS utilities (6)
| Utility | Where | Purpose |
|---------|-------|---------|
| toastManager | lib/toast.js (shared) | Centralized toast stack |
| heartbeat | app.jsx | Periodic health monitoring |
| playSfx | Upload, errors, recovery | Optional audio feedback |
| recovery | Layout root, dropzone | Visual recovery burst |
| narrator | System messages | piOS voice personality |
| orchestrate | Offline/error states | Multi-surface threat coordination |

### Result: 19/28 components (68%), 13/24 JS modules (54%)

---

## Files Changed

### Backend
- `app/api.py` — quarantine endpoint

### Frontend — Pages
- `app/frontend/src/pages/Settings.jsx` — SYSTEM (backup, reboot, shutdown), SCHEDULE (TV status), MAP section, CRT toggle, audio toggle
- `app/frontend/src/pages/Stats.jsx` — ShHeroCard, ShTimeChart, ShEmptyState, ShErrorState
- `app/frontend/src/pages/Upload.jsx` — search icon, ShEmptyState, ShErrorState, ShPageBanner
- `app/frontend/src/pages/Albums.jsx` — remove-from-album, ShEmptyState, ShErrorState, ShPageBanner
- `app/frontend/src/pages/Map.jsx` — ShEmptyState, ShErrorState, ShPageBanner
- `app/frontend/src/pages/Users.jsx` — ShEmptyState, ShErrorState, ShPageBanner
- `app/frontend/src/pages/Onboard.jsx` — ShPageBanner
- `app/frontend/src/pages/Update.jsx` — ShPageBanner

### Frontend — Components
- `app/frontend/src/components/Lightbox.jsx` — album management, duplicate detection, ShStatusBadge
- `app/frontend/src/components/PhoneLayout.jsx` — ShMantra, ShIncidentHUD, centralized ShToast, map nav toggle
- `app/frontend/src/components/SearchModal.jsx` — verify/fix API wiring

### Frontend — Display
- `app/frontend/src/display/Slideshow.jsx` — ShPageBanner
- `app/frontend/src/display/DisplayRouter.jsx` — ShPageBanner
- `app/frontend/src/display/Setup.jsx` — ShPageBanner
- `app/frontend/src/display/Welcome.jsx` — ShPageBanner

### Frontend — Lib
- `app/frontend/src/lib/toast.js` — NEW: shared toast manager
- `app/frontend/src/lib/incident.js` — NEW: incident state management

### Frontend — App
- `app/frontend/src/app.jsx` — heartbeat, recovery, orchestrate wiring

### CSS
- `app/frontend/src/styles/settings.css` — threat-border modal variant
- `app/frontend/src/styles/base.css` — ShPageBanner spacing adjustments

---

## Mobile Design Constraints

- All new buttons: 44px minimum touch target, 8px spacing
- ShPageBanner: fixed height, no scroll interference
- ShIncidentHUD: respects safe-area-inset-top
- Lightbox album dropdown: bottom-sheet pattern on mobile
- ShHeroCard: single column on mobile, 2-column on tablet+
- ShTimeChart: responsive, full-width on mobile
- ShCrtToggle: horizontal toggle row, not stacked
- Audio toggle: clear disabled state, no auto-play
- ShMantra: semi-transparent, doesn't block touch targets
