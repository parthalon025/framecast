/** @fileoverview Upload page — dropzone + photo grid + disk space indicator. */
import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { ShDropzone } from "../components/ShDropzone.jsx";
import { PhotoGrid } from "../components/PhotoGrid.jsx";

/** Reactive state */
const photos = signal([]);
const disk = signal({ percent: 0, used: "—", total: "—", free: "—" });
const loading = signal(true);

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
 * Combines ShDropzone, PhotoGrid, and disk space display.
 * Subscribes to SSE for real-time photo:added/photo:deleted events.
 */
export function Upload() {
  const sseRef = useRef(null);
  const reconnectTimer = useRef(null);

  /** Connect to SSE endpoint with auto-reconnect. */
  function connectSSE() {
    if (sseRef.current) {
      sseRef.current.close();
    }

    const es = new EventSource("/api/events");
    sseRef.current = es;

    es.addEventListener("photo:added", () => {
      fetchPhotos();
      fetchStatus();
    });

    es.addEventListener("photo:deleted", () => {
      fetchPhotos();
      fetchStatus();
    });

    es.onerror = () => {
      es.close();
      sseRef.current = null;
      // Auto-reconnect after 3 seconds
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = setTimeout(connectSSE, 3000);
    };
  }

  useEffect(() => {
    // Initial data fetch
    Promise.all([fetchPhotos(), fetchStatus()]).then(() => {
      loading.value = false;
    });

    // Connect SSE
    connectSSE();

    // Cleanup on unmount
    return () => {
      if (sseRef.current) sseRef.current.close();
      clearTimeout(reconnectTimer.current);
    };
  }, []);

  function handleUpload() {
    // SSE will trigger refresh, but fetch eagerly for responsiveness
    fetchPhotos();
    fetchStatus();
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

  if (isLoading) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">LOADING...</div>
      </div>
    );
  }

  return (
    <div class="sh-animate-page-enter fc-page">
      {/* Dropzone */}
      <ShDropzone
        onUpload={handleUpload}
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

      {/* Photo grid */}
      <PhotoGrid photos={photos.value} onDelete={handleDelete} />
    </div>
  );
}
