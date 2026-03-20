/** @fileoverview Upload page — dropzone + batch progress + filter bar + photo grid + lightbox + storage + user filter.
 *
 * Batch upload shows per-file status, auto-retries failed uploads (3 attempts,
 * exponential backoff), and displays a completion summary.
 * piOS voice: UPLOADING 3/12, COMPLETE, FAULT, etc.
 */
import { signal } from "@preact/signals";
import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import { ShToast, ShFrozen, ShPageBanner, ShEmptyState, ShErrorState, ShThreatPulse, ShStatusBadge } from "superhot-ui/preact";
import { applyThreshold } from "superhot-ui";
import { ShDropzone } from "../components/ShDropzone.jsx";
import { PhotoGrid } from "../components/PhotoGrid.jsx";
import { OfflineBanner } from "../components/OfflineBanner.jsx";
import { NowPlaying, nowPlaying } from "../components/NowPlaying.jsx";
import { onHeartbeat } from "../components/ConnectionBanner.jsx";
import { ContextMenu } from "../components/PhotoCard.jsx";
import { Lightbox, openLightbox } from "../components/Lightbox.jsx";
import { SearchModal, openSearch } from "../components/SearchModal.jsx";
import { createSSE } from "../lib/sse.js";
import { fetchWithTimeout } from "../lib/fetch.js";
import { showToast } from "../lib/toast.js";
import {
  currentUser,
  ensureUserIdentified,
  UserSelectModal,
} from "./Users.jsx";

/**
 * usePullToRefresh — touch-based pull-to-refresh for mobile.
 * Tracks touch drag distance when the page is scrolled to the top.
 * Fires onRefresh when the user pulls past THRESHOLD and releases.
 */
function usePullToRefresh(onRefresh, containerRef) {
  const touchStartY = useRef(0);
  const pulling = useRef(false);
  const [pullDistance, setPullDistance] = useState(0);
  const THRESHOLD = 80;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function onTouchStart(evt) {
      // Only start pull if page is scrolled to the very top
      if (window.scrollY === 0 && el.scrollTop === 0) {
        touchStartY.current = evt.touches[0].clientY;
        pulling.current = true;
      }
    }

    function onTouchMove(evt) {
      if (!pulling.current) return;
      const dy = evt.touches[0].clientY - touchStartY.current;
      if (dy > 0 && dy < 150) {
        setPullDistance(dy);
        if (dy > 20) evt.preventDefault();
      }
    }

    function onTouchEnd() {
      if (pulling.current) {
        setPullDistance((current) => {
          if (current >= THRESHOLD && onRefresh) onRefresh();
          return 0;
        });
      }
      pulling.current = false;
    }

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
    };
  }, [onRefresh, containerRef]);

  return pullDistance;
}

/** Reactive state */
const photos = signal([]);
const disk = signal({ percent: 0, used: "\u2014", total: "\u2014", free: "\u2014" });
const loading = signal(true);
const filter = signal("all");
const userFilter = signal("all");
const sortBy = signal("newest");
const availableUsers = signal([]);
const photosLastUpdated = signal(null);
const fetchError = signal(null);

/** Bulk selection state */
const selectionMode = signal(false);
const selectedIds = signal(new Set());

const SORT_OPTIONS = [
  { value: "newest", label: "NEWEST" },
  { value: "oldest", label: "OLDEST" },
  { value: "favorites", label: "FAVORITES FIRST" },
  { value: "name", label: "NAME" },
];

/** Sort photos client-side by the selected criterion. */
function sortPhotos(list, criterion) {
  const sorted = [...list];
  switch (criterion) {
    case "newest": return sorted.sort((a, b) => (b.modified || 0) - (a.modified || 0));
    case "oldest": return sorted.sort((a, b) => (a.modified || 0) - (b.modified || 0));
    case "favorites": return sorted.sort((a, b) => (b.is_favorite ? 1 : 0) - (a.is_favorite ? 1 : 0));
    case "name": return sorted.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    default: return sorted;
  }
}

/** Global upload progress — persists across tab switches. { current, total } or null. */
const uploadProgress = signal(null);
export { uploadProgress };

const MAX_RETRIES = 3;
const RETRY_BASE_MS = 1000;

/** Build ASCII storage bar: [|||...] */
function storageBar(pct) {
  const width = 20;
  const filled = Math.round((pct / 100) * width);
  const empty = width - filled;
  return "[" + "\u2593".repeat(filled) + "\u2591".repeat(empty) + "]";
}

/** Fetch photos list from API with optional filter. */
function fetchPhotos() {
  const currentFilter = filter.value;
  let url = "/api/photos";
  if (currentFilter === "favorites") url += "?filter=favorites";
  else if (currentFilter === "hidden") url += "?filter=hidden";

  return fetchWithTimeout(url)
    .then((resp) => resp.json())
    .then((data) => {
      // Ensure name field exists for PhotoCard compatibility
      for (const photo of data) {
        photo.name = photo.name || photo.filename;
        photo.size_human = photo.size_human || "";
      }
      photos.value = data;
      photosLastUpdated.value = Date.now();
      // Extract unique uploaders for filter dropdown
      const uploaders = [...new Set(data.map((p) => p.uploaded_by).filter(Boolean))];
      availableUsers.value = uploaders.sort();
    })
    .catch((err) => {
      console.warn("Upload: fetchPhotos fault", err);
      fetchError.value = "PHOTO FETCH FAILED";
    });
}

/** Fetch system status (disk usage) from API. */
function fetchStatus() {
  return fetchWithTimeout("/api/status")
    .then((resp) => resp.json())
    .then((data) => {
      if (data.disk) disk.value = data.disk;
    })
    .catch((err) => {
      console.warn("Upload: fetchStatus fault", err);
    });
}

function handleToggleFavorite(photo) {
  fetch(`/api/photos/${photo.id}/favorite`, { method: "POST" })
    .then((resp) => resp.json())
    .then(() => fetchPhotos())
    .catch((err) => {
      console.warn("Favorite toggle error:", err);
      showToast("FAVORITE FAULT", "error");
    });
}

function handlePhotoSelect(photo) {
  const photoList = photos.value;
  const idx = photoList.findIndex((p) => p.id === photo.id);
  openLightbox(photoList, idx >= 0 ? idx : 0);
}

function handleAddTag(photo, tagName) {
  fetch(`/api/photos/${photo.id}/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: tagName }),
  }).catch((err) => console.warn("Add tag error:", err));
}

function handleRemoveTag(photo, tag) {
  fetch(`/api/photos/${photo.id}/tags/${tag.id}`, { method: "DELETE" })
    .catch((err) => console.warn("Remove tag error:", err));
}

// ---------------------------------------------------------------------------
// Bulk selection handlers
// ---------------------------------------------------------------------------

/** Enter selection mode — triggered by long-press on a PhotoCard. */
function handleEnterSelection(photo) {
  selectionMode.value = true;
  selectedIds.value = new Set([photo.id]);
}

/** Toggle a single photo's selection. */
function handleSelectionToggle(photo) {
  const next = new Set(selectedIds.value);
  if (next.has(photo.id)) {
    next.delete(photo.id);
  } else {
    next.add(photo.id);
  }
  selectedIds.value = next;
  // Exit selection mode if nothing selected
  if (next.size === 0) {
    selectionMode.value = false;
  }
}

/** Exit selection mode and clear selections. */
function exitSelectionMode() {
  selectionMode.value = false;
  selectedIds.value = new Set();
}

/** Select all currently visible photos. */
function selectAllVisible(visiblePhotos) {
  const next = new Set();
  for (const photo of visiblePhotos) {
    next.add(photo.id);
  }
  selectedIds.value = next;
}

/** Batch delete selected photos. */
function handleBatchDelete() {
  const ids = [...selectedIds.value];
  if (ids.length === 0) return;
  fetch("/api/photos/batch/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  })
    .then((resp) => resp.json())
    .then((data) => {
      showToast(`${ids.length} QUARANTINED`, "info");
      exitSelectionMode();
      fetchPhotos();
      fetchStatus();
    })
    .catch((err) => console.warn("Batch delete error:", err));
}

/** Batch favorite selected photos. */
function handleBatchFavorite() {
  const ids = [...selectedIds.value];
  if (ids.length === 0) return;
  fetch("/api/photos/batch/favorite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  })
    .then((resp) => resp.json())
    .then(() => {
      showToast(`${ids.length} TOGGLED`, "info");
      fetchPhotos();
    })
    .catch((err) => console.warn("Batch favorite error:", err));
}

/**
 * Upload a single file via XHR with progress + retry.
 * Returns a promise that resolves with { name, status, error? }.
 */
function uploadFileWithRetry(file, onProgress, attempt = 0) {
  return new Promise((resolve) => {
    const form = new FormData();
    form.append("files", file);

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (evt) => {
      if (evt.lengthComputable) {
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({ name: file.name, status: "COMPLETE" });
      } else if (xhr.status === 429 && attempt < MAX_RETRIES) {
        // Rate limited — retry with backoff
        const delay = RETRY_BASE_MS * Math.pow(2, attempt);
        setTimeout(() => {
          uploadFileWithRetry(file, onProgress, attempt + 1).then(resolve);
        }, delay);
      } else if (attempt < MAX_RETRIES) {
        const delay = RETRY_BASE_MS * Math.pow(2, attempt);
        setTimeout(() => {
          uploadFileWithRetry(file, onProgress, attempt + 1).then(resolve);
        }, delay);
      } else {
        let errorMsg = `HTTP ${xhr.status}`;
        try {
          const resp = JSON.parse(xhr.responseText);
          if (resp.error) errorMsg = resp.error;
        } catch (_) {}
        resolve({ name: file.name, status: "FAULT", error: errorMsg });
      }
    });

    xhr.addEventListener("error", () => {
      if (attempt < MAX_RETRIES) {
        const delay = RETRY_BASE_MS * Math.pow(2, attempt);
        setTimeout(() => {
          uploadFileWithRetry(file, onProgress, attempt + 1).then(resolve);
        }, delay);
      } else {
        resolve({ name: file.name, status: "FAULT", error: "NETWORK FAULT" });
      }
    });

    xhr.open("POST", "/upload");
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.send(form);
  });
}

/**
 * Upload — main upload page.
 * Combines ShDropzone, batch upload progress, filter bar, PhotoGrid, Lightbox, disk space display, and user filter.
 * Prompts "WHO IS UPLOADING?" on first upload if no cookie set.
 * Subscribes to SSE for real-time photo:added/photo:deleted events.
 */
export function Upload() {
  const sseRef = useRef(null);
  const storageBarRef = useRef(null);
  const batchClearTimer = useRef(null);
  const pageRef = useRef(null);
  const [toast, setToast] = useState(null);

  /* Batch upload state */
  const [batch, setBatch] = useState(null);
  /* batch shape: { files: [{name, status, progress, error?}], total, completed, failed } */

  function handleRefresh() {
    fetchPhotos();
    fetchStatus();
  }

  const pullDistance = usePullToRefresh(handleRefresh, pageRef);

  useEffect(() => {
    Promise.all([fetchPhotos(), fetchStatus()]).then(() => {
      loading.value = false;
    });

    const sse = createSSE("/api/events", {
      listeners: {
        "photo:added": handleRefresh,
        "photo:deleted": handleRefresh,
        "slideshow:now_playing": (evt) => {
          try {
            const data = JSON.parse(evt.data);
            nowPlaying.value = data;
          } catch (parseErr) {
            console.warn("Upload: failed to parse now_playing", parseErr);
          }
        },
        "heartbeat": () => onHeartbeat(),
        "sync": () => handleRefresh(),
      },
    });
    sseRef.current = sse;

    /** ESC exits bulk selection mode. */
    function onKeyDown(evt) {
      if (evt.key === "Escape" && selectionMode.value) {
        exitSelectionMode();
      }
    }
    document.addEventListener("keydown", onKeyDown);

    return () => {
      sse.close();
      document.removeEventListener("keydown", onKeyDown);
      if (batchClearTimer.current) clearTimeout(batchClearTimer.current);
    };
  }, []);

  /** Apply threshold to storage bar on disk change. */
  useEffect(() => {
    if (storageBarRef.current && disk.value) {
      applyThreshold(storageBarRef.current, disk.value.percent || 0);
    }
  }, [disk.value]);

  // Re-fetch when filter changes
  useEffect(() => {
    if (!loading.value) fetchPhotos();
  }, [filter.value]);

  /** Handle batch file selection from dropzone. */
  const handleBatchUpload = useCallback(async (fileList) => {
    if (!fileList || fileList.length === 0) return;

    const files = Array.from(fileList);
    const batchState = {
      files: files.map((file) => ({ name: file.name, status: "PENDING", progress: 0 })),
      total: files.length,
      completed: 0,
      failed: 0,
    };
    setBatch({ ...batchState });
    uploadProgress.value = { current: 0, total: files.length };

    // Upload sequentially to avoid Pi 3 OOM
    for (let idx = 0; idx < files.length; idx++) {
      // Update current file to UPLOADING
      batchState.files[idx].status = "UPLOADING";
      uploadProgress.value = { current: idx + 1, total: files.length };
      setBatch({ ...batchState });

      const result = await uploadFileWithRetry(
        files[idx],
        (pct) => {
          batchState.files[idx].progress = pct;
          setBatch({ ...batchState });
        },
      );

      batchState.files[idx].status = result.status;
      batchState.files[idx].progress = result.status === "COMPLETE" ? 100 : 0;
      if (result.error) batchState.files[idx].error = result.error;

      if (result.status === "COMPLETE") {
        batchState.completed++;
      } else {
        batchState.failed++;
      }
      setBatch({ ...batchState });
    }

    // Clear global progress toast
    uploadProgress.value = null;

    // Refresh data after batch completes
    fetchPhotos();
    fetchStatus();

    // Show summary toast
    if (batchState.failed === 0) {
      setToast({ type: "info", message: `${batchState.completed} UPLOADED` });
    } else {
      setToast({
        type: "error",
        message: `${batchState.completed} UPLOADED. ${batchState.failed} FAILED`,
      });
    }

    // Clear batch after 5s
    if (batchClearTimer.current) clearTimeout(batchClearTimer.current);
    batchClearTimer.current = setTimeout(() => setBatch(null), 5000);
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
    fetchPhotos();
    fetchStatus();
  }

  const currentDisk = disk.value;
  const isLoading = loading.value;
  const diskPct = currentDisk.percent || 0;
  const isLowDisk = diskPct >= 90;
  const isUploadBlocked = diskPct >= 95;
  const currentFilter = filter.value;

  // Apply user filter + sort
  const allPhotos = photos.value;
  const filterValue = userFilter.value;
  const filteredPhotos = filterValue === "all"
    ? allPhotos
    : allPhotos.filter((p) => p.uploaded_by === filterValue);
  const displayPhotos = sortPhotos(filteredPhotos, sortBy.value);

  if (isLoading) {
    return (
      <main class="sh-frame" style="padding: 24px; text-align: center;" role="main">
        <div class="sh-ansi-dim">STANDBY</div>
      </main>
    );
  }

  return (
    <main class="sh-animate-page-enter fc-page" role="main" ref={pageRef}>
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <ShPageBanner namespace="FRAMECAST" page="UPLOAD" />
        <button
          class="sh-input sh-clickable"
          style="min-width: 44px; min-height: 44px; padding: 8px; background: none; border: none; color: var(--sh-phosphor); font-size: 1.2rem; cursor: pointer; flex-shrink: 0;"
          onClick={openSearch}
          aria-label="Search photos"
        >
          &#x1F50D;
        </button>
      </div>
      {pullDistance > 0 && (
        <div class="fc-pull-indicator" style={{ opacity: Math.min(pullDistance / 80, 1), transform: `translateY(${Math.min(pullDistance * 0.5, 40)}px)` }}>
          {pullDistance >= 80 ? "RELEASE TO REFRESH" : "PULL TO REFRESH"}
        </div>
      )}
      <OfflineBanner />

      {/* Search modal */}
      <SearchModal onSelect={handlePhotoSelect} />

      {/* Now playing — current photo on TV */}
      <NowPlaying />

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
        onBatchUpload={handleBatchUpload}
        disabled={isUploadBlocked}
      />

      {/* Batch upload progress */}
      {batch && (
        <section class="sh-frame" data-label="TRANSFER" aria-label="Upload progress">
          <div style="display: grid; gap: var(--space-2, 8px);">
            <div class="sh-label">
              UPLOADING {Math.min(batch.completed + batch.failed + 1, batch.total)}/{batch.total}
            </div>
            <div class="sh-threshold-bar" style={`--sh-fill: ${Math.round(((batch.completed + batch.failed) / batch.total) * 100)}`} />
            <div style="display: grid; gap: var(--space-1, 4px); max-height: 200px; overflow-y: auto;">
              {batch.files.map((file) => (
                <div
                  key={file.name}
                  style="display: grid; grid-template-columns: 1fr auto; gap: var(--space-2, 8px); align-items: center; font-size: 0.8rem;"
                >
                  <span
                    class="sh-ansi-dim"
                    style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                  >
                    {file.name}
                  </span>
                  <span
                    class={
                      file.status === "COMPLETE" ? "sh-ansi-fg-green" :
                      file.status === "FAULT" ? "sh-ansi-fg-red" :
                      file.status === "UPLOADING" ? "" :
                      "sh-ansi-dim"
                    }
                    style="font-size: 0.75rem; white-space: nowrap;"
                  >
                    {file.status === "UPLOADING" ? `${file.progress}%` : file.status}
                  </span>
                </div>
              ))}
            </div>
            {/* Completion summary */}
            {batch.completed + batch.failed === batch.total && (
              <div style="margin-top: var(--space-2, 8px); font-size: 0.8rem;">
                <span class="sh-value">
                  {batch.completed} UPLOADED
                  {batch.failed > 0 && (
                    <span class="sh-ansi-fg-red">
                      . {batch.failed} FAILED
                    </span>
                  )}
                </span>
                {batch.files.filter((file) => file.error).map((file) => (
                  <div key={file.name} class="sh-ansi-dim" style="font-size: 0.75rem; margin-top: 2px;">
                    {file.name} — {file.error}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Storage indicator */}
      <section class="sh-frame" data-label="STORAGE" aria-label="Storage usage">
        <div style="padding: var(--space-3, 12px);">
          <div style="display: grid; grid-template-columns: 1fr auto; gap: var(--space-2, 8px); align-items: center;">
            <div
              class="sh-threshold-bar"
              style={`--sh-fill: ${diskPct}`}
              ref={storageBarRef}
              role="meter"
              aria-label="Storage usage"
              aria-valuenow={diskPct}
              aria-valuemin="0"
              aria-valuemax="100"
            />
            <span style="white-space: nowrap;">
              {diskPct}%
              {isLowDisk && (
                <span class="sh-status-badge" data-sh-status="critical" style="margin-left: var(--space-2, 8px);">LOW DISK</span>
              )}
            </span>
          </div>
          <div class="sh-ansi-dim" style="margin-top: var(--space-1, 4px); font-size: 0.8rem;">
            {currentDisk.used} USED / {currentDisk.total} TOTAL / {currentDisk.free} FREE
          </div>
        </div>
      </section>

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

      {/* Filter bar + sort */}
      <div class="sh-filter-panel" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
        <span
          class={`sh-filter-chip${currentFilter === "all" ? " sh-filter-chip--active" : ""}`}
          onClick={() => { filter.value = "all"; }}
          style="cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem; padding: 4px 10px;"
        >
          ALL
        </span>
        <span
          class={`sh-filter-chip${currentFilter === "favorites" ? " sh-filter-chip--active" : ""}`}
          onClick={() => { filter.value = "favorites"; }}
          style="cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem; padding: 4px 10px;"
        >
          FAVORITES
        </span>
        <span
          class={`sh-filter-chip${currentFilter === "hidden" ? " sh-filter-chip--active" : ""}`}
          onClick={() => { filter.value = "hidden"; }}
          style="cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem; padding: 4px 10px;"
        >
          HIDDEN
        </span>
        <select
          class="sh-select"
          value={sortBy.value}
          onChange={(evt) => { sortBy.value = evt.target.value; }}
          aria-label="Sort photos"
          style="max-width: 140px; margin-left: auto;"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Photo grid */}
      {displayPhotos.length === 0 && !fetchError.value ? (
        <ShEmptyState message="NO PHOTOS" hint="DROP FILES TO BEGIN" />
      ) : (
        <ShFrozen timestamp={photosLastUpdated}>
          <PhotoGrid
            photos={displayPhotos}
            onDelete={handleDelete}
            onToggleFavorite={handleToggleFavorite}
            onSelect={handlePhotoSelect}
            selectionMode={selectionMode.value}
            selectedIds={selectedIds.value}
            onSelectionToggle={handleSelectionToggle}
            onEnterSelection={handleEnterSelection}
          />
        </ShFrozen>
      )}

      {/* Floating bulk action bar */}
      {selectionMode.value && (
        <div class="fc-bulk-bar" role="toolbar" aria-label="Bulk actions">
          <ShStatusBadge status="warning" label={`${selectedIds.value.size} SELECTED`} />
          <div class="fc-bulk-bar__actions">
            <button
              class="fc-bulk-bar__btn"
              onClick={() => {
                const allSelected = selectedIds.value.size === displayPhotos.length;
                if (allSelected) {
                  exitSelectionMode();
                } else {
                  selectAllVisible(displayPhotos);
                }
              }}
              type="button"
            >
              {selectedIds.value.size === displayPhotos.length ? "CLEAR" : "SELECT ALL"}
            </button>
            <button
              class="fc-bulk-bar__btn"
              onClick={handleBatchFavorite}
              type="button"
            >
              FAVORITE
            </button>
            <ShThreatPulse active={selectedIds.value.size > 0}>
              <button
                class="fc-bulk-bar__btn fc-bulk-bar__btn--danger"
                onClick={handleBatchDelete}
                type="button"
              >
                DELETE
              </button>
            </ShThreatPulse>
            <button
              class="fc-bulk-bar__btn fc-bulk-bar__btn--exit"
              onClick={exitSelectionMode}
              aria-label="Exit selection mode"
              type="button"
            >
              X
            </button>
          </div>
        </div>
      )}

      {/* Context menu (long-press) */}
      <ContextMenu />

      {/* Lightbox */}
      <Lightbox
        onToggleFavorite={handleToggleFavorite}
        onDelete={handleDelete}
        onAddTag={handleAddTag}
        onRemoveTag={handleRemoveTag}
      />

      {/* Fetch error */}
      {fetchError.value && (
        <ShErrorState
          title="FAULT"
          message={fetchError.value}
          onRetry={() => { fetchError.value = null; fetchPhotos(); fetchStatus(); }}
        />
      )}

      {/* Toast — batch upload */}
      {toast && (
        <div class="fc-toast-container">
          <ShToast
            type={toast.type}
            message={toast.message}
            duration={4000}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </main>
  );
}
