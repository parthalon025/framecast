/** @fileoverview Photo Map — Leaflet map of GPS-tagged photo locations.
 *
 * Tiles are cached via the Cache API (tile-cache.js) so the map works
 * offline with whatever zoom levels were previously viewed. Cache is
 * capped at 500 tiles to protect the Pi's SD card.
 */
import { useState, useEffect, useRef } from "preact/hooks";
import { ShPageBanner } from "superhot-ui/preact";
import L from "leaflet";
import { fetchWithTimeout } from "../lib/fetch.js";
import { cachedTileFetch, pruneTileCache } from "../lib/tile-cache.js";

// Leaflet CSS bundled locally at /static/css/leaflet.css (copied by postbuild)
const LEAFLET_CSS = "/static/css/leaflet.css";

// Green phosphor marker SVG (inline data URI — no external assets)
const MARKER_SVG = `data:image/svg+xml,${encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="36" viewBox="0 0 24 36">
    <path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 24 12 24s12-15 12-24C24 5.4 18.6 0 12 0z" fill="%2340ff40" opacity="0.9"/>
    <circle cx="12" cy="12" r="5" fill="%23000" opacity="0.3"/>
  </svg>`,
)}`;

const markerIcon = L.icon({
  iconUrl: MARKER_SVG,
  iconSize: [24, 36],
  iconAnchor: [12, 36],
  popupAnchor: [0, -36],
});

export function Map() {
  const [locations, setLocations] = useState(null);
  const [error, setError] = useState(null);
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);

  // Inject Leaflet CSS once
  useEffect(() => {
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
  }, []);

  // Fetch locations
  useEffect(() => {
    fetchWithTimeout("/api/locations")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setLocations(data))
      .catch((err) => setError(err.message));
  }, []);

  // Initialize/update map when locations arrive
  useEffect(() => {
    if (!locations || locations.length === 0 || !mapRef.current) return;

    // Destroy previous instance if re-rendering
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }

    const map = L.map(mapRef.current, {
      zoomControl: true,
      attributionControl: true,
    });

    // Cached tile layer — serves from Cache API when available, fetches
    // from network otherwise. Previously-viewed tiles work offline.
    const CachedTileLayer = L.TileLayer.extend({
      createTile: function (coords, done) {
        const tile = document.createElement("img");
        const url = this.getTileUrl(coords);

        cachedTileFetch(url)
          .then((response) => response.blob())
          .then((blob) => {
            tile.src = URL.createObjectURL(blob);
            done(null, tile);
          })
          .catch(() => {
            // Network + cache both failed — let Leaflet show its
            // default broken-tile placeholder.
            tile.src = url;
            done(null, tile);
          });

        return tile;
      },
    });

    new CachedTileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 19,
    }).addTo(map);

    // Prune old tiles in the background (non-blocking)
    pruneTileCache();

    const markers = locations.map((loc) =>
      L.marker([loc.lat, loc.lon], { icon: markerIcon })
        .addTo(map)
        .bindPopup(() => {
          const el = document.createElement("span");
          el.style.cssText = "font-family: monospace; text-transform: uppercase; font-size: 12px;";
          el.textContent = loc.name;
          return el;
        }),
    );

    if (markers.length === 1) {
      map.setView([locations[0].lat, locations[0].lon], 13);
    } else {
      const group = L.featureGroup(markers);
      map.fitBounds(group.getBounds().pad(0.1));
    }

    mapInstanceRef.current = map;

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [locations]);

  if (error) {
    return (
      <div class="sh-frame" data-label="MAP" style="padding: 20px;">
        <span class="sh-label" style="color: var(--status-critical, #ff4444);">
          LOAD FAILED: {error}
        </span>
      </div>
    );
  }

  if (!locations) {
    return (
      <div class="sh-frame" data-label="MAP" style="padding: 20px;">
        <span class="sh-label">STANDBY</span>
      </div>
    );
  }

  if (locations.length === 0) {
    return (
      <div class="sh-frame" data-label="MAP" style="padding: 20px;">
        <span class="sh-label">NO LOCATIONS FOUND</span>
      </div>
    );
  }

  return (
    <div style="display: flex; flex-direction: column; height: calc(100dvh - 72px - env(safe-area-inset-bottom, 0px));">
      <ShPageBanner namespace="FRAMECAST" page="MAP" />
      <div
        ref={mapRef}
        style="flex: 1; min-height: 0; background: #000;"
      />
    </div>
  );
}

export default Map;
