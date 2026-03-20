/** @fileoverview Phone layout shell — wraps page content with ShNav bottom bar. */
import { ShNav, ShMantra, ShIncidentHUD, ShToast } from "superhot-ui/preact";
import { route, navigate } from "./Router.jsx";
import { uploadProgress } from "../pages/Upload.jsx";
import { SearchModal, openSearch } from "./SearchModal.jsx";
import { openLightbox } from "./Lightbox.jsx";
import { ConnectionBanner, tvConnected } from "./ConnectionBanner.jsx";
import { toast, clearToast } from "../lib/toast.js";
import { incident, clearIncident } from "../lib/incident.js";

// --- Nav icons (inline SVG, 20x20) ---
function UploadIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function MapIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
      <line x1="8" y1="2" x2="8" y2="18" />
      <line x1="16" y1="6" x2="16" y2="22" />
    </svg>
  );
}

function StatsIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function AlbumsIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

const navItems = [
  { path: "/", label: "Upload", icon: UploadIcon },
  { path: "/albums", label: "Albums", icon: AlbumsIcon },
  { path: "/map", label: "Map", icon: MapIcon },
  { path: "/settings", label: "Settings", icon: SettingsIcon },
];

/** Open lightbox when a search result is selected. */
function handleSearchSelect(photo) {
  openLightbox([photo], 0);
}

/**
 * PhoneLayout — page content wrapper with bottom ShNav.
 * Adds 72px bottom padding so content doesn't hide behind the fixed nav bar.
 */
export function PhoneLayout({ children }) {
  const offline = !tvConnected.value;

  return (
    <ShMantra text="OFFLINE" active={offline}>
      <div style="min-height: 100dvh;">
        <ShIncidentHUD
          active={incident.value !== null}
          severity={incident.value?.severity || "warning"}
          message={incident.value?.message || ""}
          timestamp={incident.value?.startedAt}
          onAcknowledge={clearIncident}
        />
        <ConnectionBanner />
        {/* Header bar with search */}
        <div
          class="fc-header"
          style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; padding-top: calc(8px + env(safe-area-inset-top, 0px));"
        >
          <span
            style="font-family: var(--font-mono, monospace); font-size: 0.8rem; letter-spacing: 0.12em; color: var(--sh-phosphor, #39ff14);"
          >
            FRAMECAST
          </span>
          <button
            type="button"
            onClick={openSearch}
            aria-label="Search photos"
            style="background: none; border: 1px solid var(--border-subtle, rgba(255,255,255,0.15)); color: var(--sh-phosphor, #39ff14); cursor: pointer; padding: 6px 10px; min-width: 44px; min-height: 44px; display: flex; align-items: center; gap: 6px; font-family: var(--font-mono, monospace); font-size: 0.75rem; border-radius: 3px;"
          >
            <SearchIcon />
            SEARCH
          </button>
        </div>
        <div>
          {children}
        </div>
        {uploadProgress.value && (
          <div class="fc-upload-toast">
            UPLOADING {uploadProgress.value.current}/{uploadProgress.value.total}
            <div
              class="fc-upload-toast-bar"
              style={{ width: `${(uploadProgress.value.current / uploadProgress.value.total) * 100}%` }}
            />
          </div>
        )}
        {toast.value && (
          <ShToast
            type={toast.value.type}
            message={toast.value.message}
            onDismiss={clearToast}
          />
        )}
        <SearchModal onSelect={handleSearchSelect} />
        <ShNav
          items={navItems}
          currentPath={route.value}
        />
      </div>
    </ShMantra>
  );
}
