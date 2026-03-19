/** @fileoverview Upload page — dropzone + photo grid + disk space + user filter. */
import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { ShDropzone } from "../components/ShDropzone.jsx";
import { PhotoGrid } from "../components/PhotoGrid.jsx";
import { createSSE } from "../lib/sse.js";
import {
  currentUser,
  ensureUserIdentified,
  UserSelectModal,
} from "./Users.jsx";

/** Reactive state */
const photos = signal([]);
const disk = signal({ percent: 0, used: "\u2014", total: "\u2014", free: "\u2014" });
const loading = signal(true);
const userFilter = signal("all");
const availableUsers = signal([]);

/** Build ASCII storage bar: [▓▓▓░░░] */
function storageBar(pct) {
  const width = 20;
  const filled = Math.round((pct / 100) * width);
  const empty = width - filled;
  return "[" + "\u2593".repeat(filled) + "\u2591".repeat(empty) + "]";
}

/** Fetch photos list from API. */
function fetchPhotos() {
  return fetch("/api/photos")
    .then((resp) => resp.json())
    .then((data) => {
      photos.value = data;
      // Extract unique uploaders for filter dropdown
      const uploaders = [...new Set(data.map((p) => p.uploaded_by).filter(Boolean))];
      availableUsers.value = uploaders.sort();
    })
    .catch((err) => {
      console.warn("Upload: fetchPhotos failed", err);
    });
}

/** Fetch system status (disk usage) from API. */
function fetchStatus() {
  return fetch("/api/status")
    .then((resp) => resp.json())
    .then((data) => {
      if (data.disk) disk.value = data.disk;
    })
    .catch((err) => {
      console.warn("Upload: fetchStatus failed", err);
    });
}

/**
 * Upload — main upload page.
 * Combines ShDropzone, PhotoGrid, disk space display, and user filter.
 * Prompts "WHO IS UPLOADING?" on first upload if no cookie set.
 * Subscribes to SSE for real-time photo:added/photo:deleted events.
 */
export function Upload() {
  const sseRef = useRef(null);

  function handleRefresh() {
    fetchPhotos();
    fetchStatus();
  }

  useEffect(() => {
    // Initial data fetch
    Promise.all([fetchPhotos(), fetchStatus()]).then(() => {
      loading.value = false;
    });

    // Connect SSE with shared backoff utility
    const sse = createSSE("/api/events", {
      listeners: {
        "photo:added": handleRefresh,
        "photo:deleted": handleRefresh,
      },
    });
    sseRef.current = sse;

    return () => sse.close();
  }, []);

  function handleUploadAttempt() {
    // Check if user needs to identify before upload
    if (ensureUserIdentified()) return;
    // SSE will trigger refresh, but fetch eagerly for responsiveness
    fetchPhotos();
    fetchStatus();
  }

  function handleUserSelected() {
    // User just identified — refresh to proceed
    fetchPhotos();
  }

  function handleDelete() {
    // SSE will trigger refresh, but fetch eagerly
    fetchPhotos();
    fetchStatus();
  }

  const currentDisk = disk.value;
  const isLoading = loading.value;
  const diskPct = currentDisk.percent || 0;
  const isLowDisk = diskPct >= 90;
  const isUploadBlocked = diskPct >= 95;

  // Apply user filter
  const allPhotos = photos.value;
  const filterValue = userFilter.value;
  const filteredPhotos = filterValue === "all"
    ? allPhotos
    : allPhotos.filter((p) => p.uploaded_by === filterValue);

  if (isLoading) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">STANDBY</div>
      </div>
    );
  }

  return (
    <div class="sh-animate-page-enter fc-page">
      {/* User select modal (shown on first upload if no cookie) */}
      <UserSelectModal onSelected={handleUserSelected} />

      {/* Current user indicator */}
      {currentUser.value && (
        <div class="sh-ansi-dim" style="font-size: 0.75rem; padding: 4px 0; text-align: right;">
          UPLOADING AS: <strong>{currentUser.value.toUpperCase()}</strong>
          <button
            class="sh-btn sh-btn-sm"
            style="margin-left: 8px; font-size: 0.65rem; padding: 1px 4px;"
            onClick={() => {
              document.cookie = "framecast_user=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT";
              currentUser.value = null;
            }}
          >
            SWITCH
          </button>
        </div>
      )}

      {/* Dropzone */}
      <ShDropzone
        onUpload={handleUploadAttempt}
        disabled={isUploadBlocked}
      />

      {/* Storage indicator */}
      <div class="sh-frame" data-label="STORAGE">
        <div style="padding: 12px;">
          <div style="font-family: var(--font-mono, monospace); display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span>{storageBar(diskPct)}</span>
            <span>{diskPct}%</span>
            {isLowDisk && (
              <span class="sh-status-badge" data-sh-status="critical">LOW DISK</span>
            )}
          </div>
          <div class="sh-ansi-dim" style="margin-top: 6px; font-size: 0.8rem;">
            {currentDisk.used} USED / {currentDisk.total} TOTAL / {currentDisk.free} FREE
          </div>
        </div>
      </div>

      {/* User filter dropdown */}
      {availableUsers.value.length > 1 && (
        <div style="padding: 4px 0;">
          <select
            class="sh-select"
            value={filterValue}
            onChange={(evt) => { userFilter.value = evt.target.value; }}
            aria-label="Filter photos by user"
          >
            <option value="all">ALL PHOTOS</option>
            {availableUsers.value.map((name) => (
              <option key={name} value={name}>{name.toUpperCase()}</option>
            ))}
          </select>
        </div>
      )}

      {/* Photo grid */}
      <PhotoGrid photos={filteredPhotos} onDelete={handleDelete} />
    </div>
  );
}
