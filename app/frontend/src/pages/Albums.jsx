/** @fileoverview Albums page — album management with smart albums, create/delete, photo grid. */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { ShModal, ShFrozen, ShToast, ShPageBanner, ShEmptyState, ShErrorState } from "superhot-ui/preact";
import { fetchWithTimeout } from "../lib/fetch.js";
import { PhotoGrid } from "../components/PhotoGrid.jsx";
import { PhotoCard } from "../components/PhotoCard.jsx";
import { Lightbox, openLightbox } from "../components/Lightbox.jsx";

/** Reactive state */
const albums = signal([]);
const loading = signal(true);
const selectedAlbum = signal(null);
const albumPhotos = signal([]);
const albumPhotosLoading = signal(false);

/** Create modal state */
const createOpen = signal(false);
const createName = signal("");
const createDesc = signal("");
const creating = signal(false);

/** Delete modal state */
const deleteTarget = signal(null);
const deleting = signal(false);

/** Filter: 'all' | 'smart' | 'user' */
const albumFilter = signal("all");

/** Toast state */
const albumToast = signal(null);

/** Fetch error state */
const fetchError = signal(null);

/** Data freshness timestamps for ShFrozen */
const albumsLastUpdated = signal(null);
const albumPhotosLastUpdated = signal(null);

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

function fetchAlbums() {
  return fetchWithTimeout("/api/albums")
    .then((resp) => resp.json())
    .then((data) => {
      albums.value = data;
      albumsLastUpdated.value = Date.now();
    })
    .catch((err) => {
      console.warn("Albums: fetchAlbums failed", err);
      fetchError.value = err.message || "ALBUMS FETCH FAILED";
    });
}

function fetchAlbumPhotos(albumId) {
  albumPhotosLoading.value = true;
  const isSmart = String(albumId).startsWith("smart:");

  let url;
  if (isSmart) {
    const key = albumId.replace("smart:", "");
    url = `/api/albums/smart/${key}/photos`;
  } else {
    url = `/api/albums/${albumId}/photos`;
  }

  return fetchWithTimeout(url)
    .then((resp) => resp.json())
    .then((data) => {
      // Augment with name field for PhotoCard compatibility
      for (const photo of data) {
        photo.name = photo.name || photo.filename;
        photo.size_human = photo.size_human || "";
      }
      albumPhotos.value = data;
      albumPhotosLastUpdated.value = Date.now();
    })
    .catch((err) => {
      console.warn("Albums: fetchAlbumPhotos failed", err);
      albumPhotos.value = [];
      albumToast.value = { type: "error", message: "PHOTO FETCH FAILED" };
    })
    .finally(() => {
      albumPhotosLoading.value = false;
    });
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function handleCreateAlbum() {
  const name = createName.value.trim();
  if (!name || creating.value) return;

  creating.value = true;
  fetch("/api/albums", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: createDesc.value.trim() || null }),
  })
    .then((resp) => {
      if (resp.ok) {
        createOpen.value = false;
        createName.value = "";
        createDesc.value = "";
        fetchAlbums();
      } else {
        return resp.json().then((data) => {
          console.warn("Create album failed:", data.error);
        });
      }
    })
    .catch((err) => {
      console.warn("Create album error:", err);
      albumToast.value = { type: "error", message: "CREATE ALBUM FAILED" };
    })
    .finally(() => { creating.value = false; });
}

function handleDeleteAlbum() {
  const album = deleteTarget.value;
  if (!album || deleting.value) return;

  deleting.value = true;
  fetch(`/api/albums/${album.id}`, { method: "DELETE" })
    .then((resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      deleteTarget.value = null;
      if (selectedAlbum.value && selectedAlbum.value.id === album.id) {
        selectedAlbum.value = null;
        albumPhotos.value = [];
      }
      fetchAlbums();
    })
    .catch((err) => {
      console.warn("Delete album error:", err);
      albumToast.value = { type: "error", message: "DELETE ALBUM FAILED" };
    })
    .finally(() => { deleting.value = false; });
}

function handleToggleFavorite(photo) {
  fetch(`/api/photos/${photo.id}/favorite`, { method: "POST" })
    .then((resp) => resp.json())
    .then(() => {
      if (selectedAlbum.value) fetchAlbumPhotos(selectedAlbum.value.id);
    })
    .catch((err) => {
      console.warn("Favorite toggle error:", err);
      albumToast.value = { type: "error", message: "FAVORITE TOGGLE FAILED" };
    });
}

function handlePhotoSelect(photo) {
  const photoList = albumPhotos.value;
  const idx = photoList.findIndex((p) => p.id === photo.id);
  openLightbox(photoList, idx >= 0 ? idx : 0);
}

function handleAddTag(photo, tagName) {
  fetch(`/api/photos/${photo.id}/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: tagName }),
  }).catch((err) => {
    console.warn("Add tag error:", err);
    albumToast.value = { type: "error", message: "ADD TAG FAILED" };
  });
}

function handleRemoveTag(photo, tag) {
  fetch(`/api/photos/${photo.id}/tags/${tag.id}`, { method: "DELETE" })
    .catch((err) => {
      console.warn("Remove tag error:", err);
      albumToast.value = { type: "error", message: "REMOVE TAG FAILED" };
    });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Albums() {
  useEffect(() => {
    fetchAlbums().then(() => { loading.value = false; });
  }, []);

  const isLoading = loading.value;
  const allAlbums = albums.value;
  const currentAlbum = selectedAlbum.value;
  const currentFilter = albumFilter.value;

  // Filter albums
  const filteredAlbums = allAlbums.filter((album) => {
    if (currentFilter === "smart") return album.smart;
    if (currentFilter === "user") return !album.smart;
    return true;
  });

  // Separate smart and user albums for display order (smart first)
  const smartAlbums = filteredAlbums.filter((a) => a.smart);
  const userAlbums = filteredAlbums.filter((a) => !a.smart);
  const orderedAlbums = [...smartAlbums, ...userAlbums];

  if (isLoading) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">STANDBY</div>
      </div>
    );
  }

  // --- Album detail view ---
  if (currentAlbum) {
    return (
      <div class="sh-animate-page-enter fc-page">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
          <button
            class="fc-action-btn"
            onClick={() => { selectedAlbum.value = null; albumPhotos.value = []; }}
            type="button"
            style="background: none; border: 1px solid var(--border-subtle); color: var(--sh-phosphor); padding: 6px 12px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
          >
            BACK
          </button>
          <span style="font-family: var(--font-mono, monospace); font-size: 1rem; font-weight: 700;">
            {currentAlbum.name}
          </span>
          {currentAlbum.smart && (
            <span class="sh-status-badge" data-sh-status="active" style="font-size: 0.65rem;">SMART</span>
          )}
        </div>

        {albumPhotosLoading.value ? (
          <div class="sh-frame" style="padding: 24px; text-align: center;">
            <div class="sh-ansi-dim">STANDBY</div>
          </div>
        ) : albumPhotos.value.length === 0 ? (
          <ShEmptyState message="NO PHOTOS" hint="ADD PHOTOS TO THIS ALBUM" />
        ) : (
          <ShFrozen timestamp={albumPhotosLastUpdated}>
            <div class="sh-grid sh-grid-3">
              {albumPhotos.value.map((photo) => (
                <PhotoCard
                  key={photo.id}
                  photo={photo}
                  onSelect={handlePhotoSelect}
                  onToggleFavorite={handleToggleFavorite}
                />
              ))}
            </div>
          </ShFrozen>
        )}

        {!currentAlbum.smart && (
          <div style="margin-top: 12px;">
            <button
              class="fc-action-btn fc-action-btn--danger"
              onClick={() => { deleteTarget.value = currentAlbum; }}
              type="button"
              style="background: none; border: 1px solid var(--sh-threat, #ff4444); color: var(--sh-threat, #ff4444); padding: 8px 14px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
            >
              [DELETE] ALBUM
            </button>
          </div>
        )}

        {/* Delete album modal */}
        <ShModal
          open={!!deleteTarget.value}
          title="CONFIRM: DELETE ALBUM?"
          body="PHOTOS PRESERVED. Only the album grouping will be removed."
          confirmLabel={deleting.value ? "STANDBY" : "DELETE"}
          cancelLabel="CANCEL"
          onConfirm={handleDeleteAlbum}
          onCancel={() => { deleteTarget.value = null; }}
        />

        {/* Lightbox */}
        <Lightbox
          onToggleFavorite={handleToggleFavorite}
          onAddTag={handleAddTag}
          onRemoveTag={handleRemoveTag}
        />

        {/* Toast */}
        {albumToast.value && (
          <div class="fc-toast-container">
            <ShToast
              type={albumToast.value.type}
              message={albumToast.value.message}
              duration={4000}
              onDismiss={() => { albumToast.value = null; }}
            />
          </div>
        )}
      </div>
    );
  }

  // --- Album grid view ---
  return (
    <div class="sh-animate-page-enter fc-page">
      <ShPageBanner namespace="FRAMECAST" page="ALBUMS" />
      {/* Fetch error */}
      {fetchError.value && (
        <ShErrorState
          title="FAULT"
          message={fetchError.value}
          onRetry={() => { fetchError.value = null; fetchAlbums(); }}
        />
      )}
      {/* Header + create button */}
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <button
          class="fc-action-btn"
          onClick={() => { createOpen.value = true; }}
          type="button"
          style="background: none; border: 1px solid var(--sh-phosphor); color: var(--sh-phosphor); padding: 6px 12px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
        >
          [ADD] CREATE ALBUM
        </button>
      </div>

      {/* Filter chips */}
      <div class="sh-filter-panel" style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;">
        {["all", "smart", "user"].map((filterKey) => (
          <span
            key={filterKey}
            class={`sh-filter-chip${currentFilter === filterKey ? " sh-filter-chip--active" : ""}`}
            onClick={() => { albumFilter.value = filterKey; }}
            style="cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem; padding: 4px 10px;"
          >
            {filterKey.toUpperCase()}
          </span>
        ))}
      </div>

      {/* Album cards grid */}
      <ShFrozen timestamp={albumsLastUpdated}>
      {orderedAlbums.length === 0 ? (
        <ShEmptyState message="NO ALBUMS" hint="CREATE ONE TO ORGANIZE" />
      ) : (
        <div class="sh-grid sh-grid-3">
          {orderedAlbums.map((album) => (
            <div
              key={album.id}
              class="sh-card sh-clickable"
              onClick={() => {
                selectedAlbum.value = album;
                fetchAlbumPhotos(album.id);
              }}
              role="button"
              tabIndex={0}
              aria-label={`Album: ${album.name}`}
              style="position: relative; overflow: hidden;"
            >
              {/* Cover image or placeholder */}
              {album.cover_photo_id ? (
                <div style="width: 100%; aspect-ratio: 1; background: var(--surface-void, #111); display: flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 4px;">
                  <img
                    src={`/thumbnail/${album.cover_filename || ""}`}
                    alt=""
                    loading="lazy"
                    style="width: 100%; height: 100%; object-fit: cover;"
                    onError={(evt) => {
                      if (!evt.target.dataset.fallback) {
                        evt.target.dataset.fallback = "1";
                        evt.target.src = `/media/${album.cover_filename || ""}`;
                      } else {
                        evt.target.style.display = "none";
                      }
                    }}
                  />
                </div>
              ) : (
                <div style="width: 100%; aspect-ratio: 1; background: var(--surface-void, #111); display: flex; align-items: center; justify-content: center; border-radius: 4px;">
                  <span class="sh-ansi-dim" style="font-size: 2rem;">
                    {album.smart ? "SYS" : "USR"}
                  </span>
                </div>
              )}

              {/* Album info */}
              <div style="padding: 6px 0 0;">
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="font-family: var(--font-mono, monospace); font-size: 0.8rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    {album.name}
                  </span>
                  {album.smart && (
                    <span class="sh-status-badge" data-sh-status="active" style="font-size: 0.55rem;">SMART</span>
                  )}
                </div>
                <div class="sh-ansi-dim" style="font-size: 0.7rem;">
                  {album.photo_count != null ? album.photo_count : "?"} PHOTOS
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      </ShFrozen>

      {/* Create album modal */}
      {createOpen.value && (
        <div
          class="sh-modal-overlay"
          onClick={(evt) => { if (evt.target === evt.currentTarget) createOpen.value = false; }}
          role="dialog"
          aria-modal="true"
          aria-label="Create album"
        >
          <div class="sh-modal" onClick={(evt) => evt.stopPropagation()}>
            <div class="sh-modal-title">CREATE ALBUM</div>
            <div class="sh-modal-body" style="display: flex; flex-direction: column; gap: 12px;">
              <div>
                <label class="sh-ansi-dim" style="font-size: 0.75rem; display: block; margin-bottom: 4px;">NAME</label>
                <input
                  class="sh-input"
                  type="text"
                  value={createName.value}
                  onInput={(evt) => { createName.value = evt.target.value; }}
                  placeholder="Album name"
                  style="width: 100%; font-size: 0.9rem; padding: 8px;"
                  autofocus
                />
              </div>
              <div>
                <label class="sh-ansi-dim" style="font-size: 0.75rem; display: block; margin-bottom: 4px;">DESCRIPTION</label>
                <input
                  class="sh-input"
                  type="text"
                  value={createDesc.value}
                  onInput={(evt) => { createDesc.value = evt.target.value; }}
                  placeholder="Optional"
                  style="width: 100%; font-size: 0.9rem; padding: 8px;"
                />
              </div>
            </div>
            <div class="sh-modal-actions">
              <button
                class="sh-modal-action"
                onClick={() => { createOpen.value = false; createName.value = ""; createDesc.value = ""; }}
                type="button"
              >
                [CANCEL]
              </button>
              <button
                class="sh-modal-action sh-modal-action--confirm"
                onClick={handleCreateAlbum}
                disabled={creating.value || !createName.value.trim()}
                type="button"
              >
                [{creating.value ? "STANDBY" : "CONFIRM"}]
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {albumToast.value && (
        <div class="fc-toast-container">
          <ShToast
            type={albumToast.value.type}
            message={albumToast.value.message}
            duration={4000}
            onDismiss={() => { albumToast.value = null; }}
          />
        </div>
      )}
    </div>
  );
}
