# Map Overlay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a translucent location mini-map overlay to the TV slideshow that shows where each GPS-tagged photo was taken, with a user-configurable position setting.

**Architecture:** When a photo with GPS data is displayed, a small translucent map overlay appears in a user-chosen corner showing the location on dark CartoDB tiles. Uses a 2×2 smart-quadrant tile grid (4 HTTP requests, browser-cached) with the GPS point always centered. The overlay fades in 300ms after the photo transition to avoid competing for attention. A new `MAP_OVERLAY_POSITION` setting (off/top-left/top-right/bottom-left/bottom-right) controls placement, with "off" as default.

**Tech Stack:** CartoDB dark_matter tiles (free, no API key), Preact signals, CSS animations, Flask settings API

**Design Principles Applied:**
- Tufte data-ink ratio: map is supplementary, photo is primary — 0.75 opacity cap
- Sweller cognitive load: 300ms entrance delay prevents attention-split during transition
- Cleveland & McGill perceptual hierarchy: dark tiles + phosphor accent subordinate to photo
- `prefers-reduced-motion`: instant show/hide, no fade animation
- Progressive disclosure: off by default, opt-in via settings

---

## Batch 1: Backend — Add Setting (Tasks 1–5)

### Task 1: Write failing test for MAP_OVERLAY_POSITION setting

**Files:**
- Create: `tests/test_api_settings.py`

**Step 1: Create test file**

```python
"""Tests for MAP_OVERLAY_POSITION setting in the API."""

import json
import os
import sys
from unittest import mock

import pytest

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


@pytest.fixture
def fake_config(tmp_path):
    """Provide a fake config module that reads/writes a temp .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("MAP_OVERLAY_POSITION=off\n")

    _cache = {}

    def fake_get(key, default=""):
        if not _cache:
            _cache.update(_parse_env(env_file))
        return os.environ.get(key, _cache.get(key, default))

    def _parse_env(path):
        env = {}
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip("'\"")
        return env

    return fake_get


def test_map_overlay_position_in_settings(fake_config):
    """MAP_OVERLAY_POSITION appears in _current_settings() output."""
    with mock.patch("modules.config.get", fake_config):
        from api import _current_settings
        settings = _current_settings()
        assert "map_overlay_position" in settings
        assert settings["map_overlay_position"] == "off"


def test_map_overlay_position_valid_values():
    """Only valid position values are accepted."""
    from api import _VALID_MAP_OVERLAY_POSITIONS
    assert _VALID_MAP_OVERLAY_POSITIONS == {
        "off", "top-left", "top-right", "bottom-left", "bottom-right",
    }


def test_map_overlay_position_in_env_map():
    """MAP_OVERLAY_POSITION is wired in _SETTINGS_ENV_MAP."""
    from api import _SETTINGS_ENV_MAP
    assert "map_overlay_position" in _SETTINGS_ENV_MAP
    env_key, converter = _SETTINGS_ENV_MAP["map_overlay_position"]
    assert env_key == "MAP_OVERLAY_POSITION"
    assert converter("bottom-left") == "bottom-left"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/justin/Documents/projects/framecast && python3 -m pytest tests/test_api_settings.py -v`
Expected: FAIL — `_VALID_MAP_OVERLAY_POSITIONS` not defined, `map_overlay_position` not in settings

### Task 2: Add MAP_OVERLAY_POSITION to backend settings

**Files:**
- Modify: `app/api.py`

**Step 3: Add validation constant** (after `_VALID_PHOTO_ORDERS` ~line 87)

```python
_VALID_MAP_OVERLAY_POSITIONS = {"off", "top-left", "top-right", "bottom-left", "bottom-right"}
```

**Step 4: Add to `_current_settings()`** (after `web_port` ~line 125)

```python
        "map_overlay_position": config.get("MAP_OVERLAY_POSITION", "off"),
```

**Step 5: Add to `_SETTINGS_ENV_MAP`** (after `pin_length` ~line 151)

```python
    "map_overlay_position": ("MAP_OVERLAY_POSITION", str),
```

**Step 6: Add validation** in `update_settings()` (after the `pin_length` validation block ~line 280)

```python
    if "map_overlay_position" in data and data["map_overlay_position"] not in _VALID_MAP_OVERLAY_POSITIONS:
        return jsonify({
            "error": f"Invalid map_overlay_position: must be one of {sorted(_VALID_MAP_OVERLAY_POSITIONS)}",
        }), 400
```

### Task 3: Run tests, verify pass

**Step 7: Run the new tests**

Run: `cd /home/justin/Documents/projects/framecast && python3 -m pytest tests/test_api_settings.py -v`
Expected: 3 PASSED

### Task 4: Run full test suite

**Step 8: Verify no regressions**

Run: `cd /home/justin/Documents/projects/framecast && python3 -m pytest tests/ -v --timeout=120`
Expected: All 129+ tests pass (new tests add 3)

### Task 5: Commit backend changes

**Step 9: Commit**

```bash
git add tests/test_api_settings.py app/api.py
git commit -m "feat: add MAP_OVERLAY_POSITION setting to backend API

New setting controls where the location mini-map appears on the TV
slideshow. Values: off (default), top-left, top-right, bottom-left,
bottom-right. Includes validation, env map wiring, and tests."
```

---

## Batch 2: Frontend CSS — Map Overlay Styles (Tasks 6–8)

### Task 6: Add map overlay CSS to slideshow.css

**Files:**
- Modify: `app/frontend/src/styles/slideshow.css`

**Step 1: Append map overlay styles** after the "On This Day" section (~line 159):

```css
/* --- Map overlay --- */

.fc-map-overlay {
  position: fixed;
  z-index: 15;
  overflow: hidden;
  border-radius: 6px;
  border: 1px solid var(--sh-phosphor);
  box-shadow: 0 0 12px var(--sh-phosphor-glow);
  opacity: 0;
  transition: opacity 400ms ease-in;
  pointer-events: none;
  width: clamp(120px, 12vw, 200px);
  aspect-ratio: 4 / 3;
  background: #0d1117;
}

.fc-map-overlay.fc-map-visible {
  opacity: 0.75;
}

/* Position variants — data attribute driven */
.fc-map-overlay[data-position="top-left"]     { top: 24px; left: 24px; }
.fc-map-overlay[data-position="top-right"]    { top: 24px; right: 24px; }
.fc-map-overlay[data-position="bottom-left"]  { bottom: 24px; left: 24px; }
.fc-map-overlay[data-position="bottom-right"] { bottom: 24px; right: 24px; }

/* Tile grid container (positioned by JS to center on GPS point) */
.fc-map-tiles {
  position: absolute;
  width: 512px;
  height: 512px;
  image-rendering: auto;
}

.fc-map-tiles img {
  position: absolute;
  display: block;
  width: 256px;
  height: 256px;
}

/* Green phosphor location dot */
.fc-map-dot {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--sh-phosphor);
  box-shadow: 0 0 6px var(--sh-phosphor-glow), 0 0 12px var(--sh-phosphor-glow);
  transform: translate(-50%, -50%);
  z-index: 1;
}

/* Subtle pulse on the dot */
@keyframes fcMapDotPulse {
  0%, 100% { box-shadow: 0 0 6px var(--sh-phosphor-glow), 0 0 12px var(--sh-phosphor-glow); }
  50%      { box-shadow: 0 0 10px var(--sh-phosphor-glow), 0 0 20px var(--sh-phosphor-glow); }
}

.fc-map-dot {
  animation: fcMapDotPulse 3s ease-in-out infinite;
}
```

**Design notes for the implementer:**
- `z-index: 15` slots between slideshow layers (z:1-3) and OTD overlay (z:20)
- `aspect-ratio: 4/3` ensures consistent shape regardless of clamp width
- `opacity: 0.75` on `.fc-map-visible` — NOT on the container. The container transitions from 0 to 0.75.
- `#0d1117` background matches CartoDB dark_matter tile background (prevents flash of black before tiles load)
- Dot pulse is slow (3s) and subtle — diegetic, not decorative (superhot-ui rule)

### Task 7: Add reduced-motion rule to motion.css

**Files:**
- Modify: `app/frontend/src/styles/motion.css`

**Step 2: Add inside the `@media (prefers-reduced-motion: reduce)` block** (before the closing `}`):

```css
  /* Map overlay — instant show/hide, no fade or dot pulse */
  .fc-map-overlay {
    transition: none;
  }

  .fc-map-dot {
    animation: none;
  }
```

### Task 8: Add responsive scaling to responsive.css

**Files:**
- Modify: `app/frontend/src/styles/responsive.css`

**Step 3: Add inside the `@media (min-width: 1400px)` block** (TV/wide, after qr-overlay):

```css
  .fc-map-overlay {
    width: clamp(160px, 10vw, 240px);
  }

  .fc-map-overlay[data-position="top-left"],
  .fc-map-overlay[data-position="top-right"]    { top: 48px; }
  .fc-map-overlay[data-position="bottom-left"],
  .fc-map-overlay[data-position="bottom-right"] { bottom: 48px; }
  .fc-map-overlay[data-position="top-left"],
  .fc-map-overlay[data-position="bottom-left"]  { left: 48px; }
  .fc-map-overlay[data-position="top-right"],
  .fc-map-overlay[data-position="bottom-right"] { right: 48px; }
```

**Step 4: Build CSS to verify**

Run: `cd /home/justin/Documents/projects/framecast/app/frontend && npm run prebuild`
Expected: No errors. Check `app/static/css/app.css` contains the new rules.

**Step 5: Commit**

```bash
git add app/frontend/src/styles/slideshow.css app/frontend/src/styles/motion.css app/frontend/src/styles/responsive.css
git commit -m "style: add map overlay CSS with position variants, motion, responsive

Dark translucent overlay with phosphor border/dot. Four corner positions
via data-position attribute. Respects prefers-reduced-motion. Scales up
on TV/wide displays (1400px+)."
```

---

## Batch 3: Frontend JS — MapOverlay Component (Tasks 9–13)

### Task 9: Add tile math utilities to Slideshow.jsx

**Files:**
- Modify: `app/frontend/src/display/Slideshow.jsx`

**Step 1: Add constants and tile math** after the existing `KB_ANCHORS` array (~line 35):

```javascript
// --- Map overlay tile math ---
const MAP_ZOOM = 11; // ~30km per tile — city-level context
const TILE_SIZE = 256;
const TILE_SERVERS = ["a", "b", "c", "d"];

/** Convert lat/lon to tile coordinates and pixel offset within the tile. */
function tileCoords(lat, lon, zoom) {
  const n = Math.pow(2, zoom);
  const latRad = lat * Math.PI / 180;
  const x = (lon + 180) / 360 * n;
  const y = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n;
  const xTile = Math.floor(x);
  const yTile = Math.floor(y);
  const xFrac = x - xTile;
  const yFrac = y - yTile;
  return { xTile, yTile, xFrac, yFrac };
}

/**
 * Select a 2x2 tile quadrant that keeps the GPS point in the inner region.
 * Returns the top-left tile coords and the marker's pixel position within
 * the 512x512 grid.
 */
function getMapTiles(lat, lon) {
  const { xTile, yTile, xFrac, yFrac } = tileCoords(lat, lon, MAP_ZOOM);

  // Smart quadrant: pick the 2x2 that centers the marker
  const xStart = xFrac >= 0.5 ? xTile : xTile - 1;
  const yStart = yFrac >= 0.5 ? yTile : yTile - 1;

  // Marker pixel within the 512x512 grid
  const markerX = (xTile - xStart) * TILE_SIZE + Math.round(xFrac * TILE_SIZE);
  const markerY = (yTile - yStart) * TILE_SIZE + Math.round(yFrac * TILE_SIZE);

  // Build tile URLs (CartoDB dark_matter — free, no API key)
  const tiles = [];
  for (let dy = 0; dy < 2; dy++) {
    for (let dx = 0; dx < 2; dx++) {
      const s = TILE_SERVERS[(dy * 2 + dx) % 4];
      tiles.push({
        url: `https://${s}.basemaps.cartocdn.com/dark_all/${MAP_ZOOM}/${xStart + dx}/${yStart + dy}.png`,
        left: dx * TILE_SIZE,
        top: dy * TILE_SIZE,
      });
    }
  }

  return { tiles, markerX, markerY };
}
```

### Task 10: Add mapOverlayData signal

**Files:**
- Modify: `app/frontend/src/display/Slideshow.jsx`

**Step 2: Add signal** with the other module-level signals (~line 21):

```javascript
const mapOverlayData = signal(null); // { lat, lon } or null
```

**Step 3: Update `setLayerContent()`** to set the map overlay signal.

Find the block at the end of `setLayerContent()` that sets `onThisDayText` (~line 204-208). Add map overlay data update **before** the OTD block:

```javascript
  // Update map overlay data
  if (photo.gps_lat != null && photo.gps_lon != null) {
    mapOverlayData.value = { lat: photo.gps_lat, lon: photo.gps_lon };
  } else {
    mapOverlayData.value = null;
  }
```

### Task 11: Add MapOverlay component

**Files:**
- Modify: `app/frontend/src/display/Slideshow.jsx`

**Step 4: Add component** after the `Slideshow` component function (before `export default`), or before `Slideshow` — either works since it's a child component:

Add this **before** the `export function Slideshow()` line:

```javascript
/**
 * Translucent mini-map overlay showing the current photo's GPS location.
 * Uses CartoDB dark_matter tiles in a 2x2 grid, centered on the GPS point.
 * Fades in 300ms after photo loads to avoid competing for attention.
 */
function MapOverlay({ lat, lon, position }) {
  const containerRef = useRef(null);
  const tilesLoadedRef = useRef(0);
  const fadeTimerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || lat == null || lon == null) return;

    // Clear previous content
    while (container.firstChild) container.removeChild(container.firstChild);
    container.classList.remove("fc-map-visible");
    tilesLoadedRef.current = 0;
    if (fadeTimerRef.current) {
      clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = null;
    }

    const { tiles, markerX, markerY } = getMapTiles(lat, lon);

    // Read container size (CSS clamp resolves at layout time)
    const cw = container.clientWidth || 160;
    const ch = container.clientHeight || 120;

    // Create tile grid, translated so marker is at container center
    const grid = document.createElement("div");
    grid.className = "fc-map-tiles";
    grid.style.left = `${Math.round(cw / 2 - markerX)}px`;
    grid.style.top = `${Math.round(ch / 2 - markerY)}px`;

    for (const tile of tiles) {
      const img = document.createElement("img");
      img.src = tile.url;
      img.style.left = `${tile.left}px`;
      img.style.top = `${tile.top}px`;
      img.alt = "";
      img.draggable = false;
      img.onload = () => {
        tilesLoadedRef.current++;
        if (tilesLoadedRef.current >= 4) {
          // All tiles loaded — fade in after delay
          fadeTimerRef.current = setTimeout(() => {
            if (container) container.classList.add("fc-map-visible");
          }, 300);
        }
      };
      img.onerror = () => {
        // Tile failed — don't show partial overlay
        container.classList.remove("fc-map-visible");
      };
      grid.appendChild(img);
    }

    // Green phosphor dot at center
    const dot = document.createElement("div");
    dot.className = "fc-map-dot";
    container.appendChild(grid);
    container.appendChild(dot);

    return () => {
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    };
  }, [lat, lon]);

  return (
    <div
      ref={containerRef}
      class="fc-map-overlay"
      data-position={position}
      role="img"
      aria-label="Photo location"
    />
  );
}
```

### Task 12: Integrate MapOverlay into Slideshow render

**Files:**
- Modify: `app/frontend/src/display/Slideshow.jsx`

**Step 5: Add MapOverlay to the JSX return** in `Slideshow()`.

Find the return block (~line 437-461). Add the MapOverlay between the layer divs and the OTD overlay. The new return should be:

```jsx
  const mapPosition = settingsData.value?.map_overlay_position;
  const showMap = mapOverlayData.value && mapPosition && mapPosition !== "off";

  return (
    <div class="slideshow-container">
      {isEmpty && (
        <div class="boot-screen">
          <div class="boot-status">STANDBY</div>
          <div class="boot-status" style="opacity:0.5">NO PHOTOS</div>
        </div>
      )}
      <div
        ref={layerARef}
        class="slideshow-layer"
        style="position:absolute;inset:0;z-index:1;opacity:0;"
      />
      <div
        ref={layerBRef}
        class="slideshow-layer"
        style="position:absolute;inset:0;z-index:1;opacity:0;"
      />
      {showMap && (
        <MapOverlay
          lat={mapOverlayData.value.lat}
          lon={mapOverlayData.value.lon}
          position={mapPosition}
        />
      )}
      {onThisDayText.value && (
        <div class="fc-otd-overlay" ref={otdOverlayRef}>
          <span class="fc-otd-label">{onThisDayText.value}</span>
        </div>
      )}
    </div>
  );
```

**Step 6: Hide map overlay during transitions** — add to the `advance()` function.

Inside the `advance` callback, after `s.transitioning = true;` (~line 255), add:

```javascript
    // Hide map overlay during transition (prevents overlay lingering on old photo)
    mapOverlayData.value = null;
```

This clears the map immediately when a transition starts. The new photo's GPS data will be set by `setLayerContent()` when it loads the next image into the standby layer.

### Task 13: Build and commit

**Step 7: Build frontend**

Run: `cd /home/justin/Documents/projects/framecast/app/frontend && npm run build`
Expected: Build succeeds with no errors.

**Step 8: Verify built JS contains map overlay code**

Run: `grep -c "basemaps.cartocdn.com" /home/justin/Documents/projects/framecast/app/static/js/app.js`
Expected: At least 1 match.

**Step 9: Commit**

```bash
git add app/frontend/src/display/Slideshow.jsx app/static/js/app.js app/static/css/app.css
git commit -m "feat: add translucent map overlay to TV slideshow

When a photo has GPS data and MAP_OVERLAY_POSITION is not 'off', a
small dark mini-map appears in the configured corner showing the
photo's location. Uses CartoDB dark_matter tiles (free, no API key),
2x2 smart-quadrant grid centered on GPS point, green phosphor dot
marker. Fades in 300ms after photo transition.

Design: Tufte data-ink ratio (photo primary, map supplementary),
Sweller cognitive load delay, prefers-reduced-motion respected."
```

---

## Batch 4: Settings UI — Position Selector (Tasks 14–16)

### Task 14: Add MAP OVERLAY setting to Settings.jsx

**Files:**
- Modify: `app/frontend/src/pages/Settings.jsx`

**Step 1: Add position options constant** after `KENBURNS_OPTIONS` (~line 28):

```javascript
const MAP_OVERLAY_OPTIONS = [
  { value: "off", label: "OFF" },
  { value: "top-left", label: "TOP LEFT" },
  { value: "top-right", label: "TOP RIGHT" },
  { value: "bottom-left", label: "BOTTOM LEFT" },
  { value: "bottom-right", label: "BOTTOM RIGHT" },
];
```

**Step 2: Add setting row** in the DISPLAY section, after the KEN BURNS row (~line 285):

```jsx
            <SettingRow label="MAP OVERLAY">
              <select
                class="sh-select"
                value={settings.map_overlay_position || "off"}
                onChange={(evt) => update("map_overlay_position", evt.target.value)}
              >
                {MAP_OVERLAY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </SettingRow>
```

### Task 15: Build and verify

**Step 3: Build frontend**

Run: `cd /home/justin/Documents/projects/framecast/app/frontend && npm run build`
Expected: Build succeeds.

**Step 4: Verify setting appears in built JS**

Run: `grep -c "MAP OVERLAY" /home/justin/Documents/projects/framecast/app/static/js/app.js`
Expected: At least 1 match.

### Task 16: Commit

**Step 5: Commit**

```bash
git add app/frontend/src/pages/Settings.jsx app/static/js/app.js
git commit -m "feat: add MAP OVERLAY position setting to phone UI

New select in DISPLAY section: OFF, TOP LEFT, TOP RIGHT, BOTTOM LEFT,
BOTTOM RIGHT. Persists to .env as MAP_OVERLAY_POSITION, pushed to
slideshow via SSE settings:changed event."
```

---

## Batch 5: Integration Verification (Tasks 17–18)

### Task 17: Run full test suite

**Step 1: Run all tests**

Run: `cd /home/justin/Documents/projects/framecast && python3 -m pytest tests/ -v --timeout=120`
Expected: All tests pass (129 existing + 3 new = 132).

### Task 18: End-to-end verification checklist

**Step 2: Manual verification** (if running on Pi or dev server):

1. Start dev server: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`
2. Open phone UI → Settings → DISPLAY section
3. Verify MAP OVERLAY selector appears with 5 options
4. Select "BOTTOM LEFT" → tap SAVE → verify "SETTINGS SAVED" toast
5. Verify setting persists: `grep MAP_OVERLAY_POSITION app/.env`
6. Open TV display (`/display`) in a browser
7. Upload a photo with GPS EXIF data (any phone photo with location enabled)
8. Verify: map overlay appears in bottom-left corner after ~300ms
9. Verify: green phosphor dot is at center of overlay
10. Verify: dark map tiles load (CartoDB dark_matter style)
11. Upload a photo WITHOUT GPS data
12. Verify: map overlay does NOT appear
13. Change setting to "OFF" → SAVE → verify overlay disappears on next photo
14. Test `prefers-reduced-motion`: overlay should show/hide instantly with no fade
15. Verify no console errors in browser DevTools

**Step 3: If on Pi — check resource usage**

Run: `systemctl --user status framecast` — confirm memory stays under 512M
Check browser DevTools Network tab — verify tiles are served from cache after first load

---

## File Change Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `app/api.py` | Modify | +8 (constant, settings, env map, validation) |
| `tests/test_api_settings.py` | Create | ~55 (3 tests) |
| `app/frontend/src/styles/slideshow.css` | Modify | +55 (overlay, tiles, dot, pulse) |
| `app/frontend/src/styles/motion.css` | Modify | +6 (reduced-motion) |
| `app/frontend/src/styles/responsive.css` | Modify | +10 (TV scaling) |
| `app/frontend/src/display/Slideshow.jsx` | Modify | +120 (tile math, MapOverlay, signals, integration) |
| `app/frontend/src/pages/Settings.jsx` | Modify | +15 (options constant, select row) |

**Total:** ~270 new lines across 7 files (1 new, 6 modified)

---

## Architecture Decisions

### Why 2×2 tiles, not a single tile or Leaflet instance?

| Approach | Requests | Complexity | Centering | Memory |
|----------|----------|------------|-----------|--------|
| Single tile | 1 | Low | Marker can be at edge | Low |
| 2×2 smart quadrant | 4 | Medium | Always centered | Low |
| 3×3 grid | 9 | Medium | Always centered | Medium |
| Leaflet instance | 4+ | High | Perfect | High (60KB JS) |

**Choice: 2×2 smart quadrant.** The quadrant selection algorithm guarantees the marker falls in the inner [128,383] pixel range of the 512×512 grid. With a viewport of ~160×120, the viewport range [markerX±80, markerY±60] always stays within [48,463], well inside the grid bounds. 4 requests that cache aggressively. No additional JS dependencies.

### Why CartoDB dark_matter tiles?

- Free, no API key required (only attribution — not shown on overlay due to size)
- Dark aesthetic matches the photo frame's black background
- Minimal visual noise — roads and labels are dim gray, water is dark
- Sub-domain load balancing (a/b/c/d) for parallel tile loading

### Why 300ms entrance delay?

Cognitive load research (Sweller, 1988): when two visual elements change simultaneously, the viewer must split attention. A 300ms delay ensures the viewer registers the new photo first, then the map appears as supplementary context. This matches the "Tension → Pause → Plan" emotional arc from superhot-ui's experience design.

### Why z-index 15?

Slideshow layers use z-index 1-3 (during transitions). The "On This Day" overlay uses z-index 20. The map overlay at z-index 15 sits between: above the photo layers, below the OTD badge. This prevents the map from obscuring the OTD text when both appear on the same photo.

### Why zoom 11?

| Zoom | Coverage per tile | Use case |
|------|------------------|----------|
| 9 | ~120km | Country-level (too zoomed out) |
| 10 | ~60km | Region-level |
| **11** | **~30km** | **City-level (ideal for "where was this?")** |
| 12 | ~15km | Neighborhood-level (too detailed for mini-map) |
| 13 | ~8km | Street-level (way too detailed) |

Zoom 11 answers "this was in Paris" or "this was at the Oregon coast" — exactly the right level of geographic context for a photo frame.
