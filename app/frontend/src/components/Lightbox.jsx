/** @fileoverview Lightbox — full-screen photo viewer with swipe navigation and actions. */
import { signal } from "@preact/signals";
import { useEffect, useRef, useCallback } from "preact/hooks";
import { formatTime } from "superhot-ui";
import { fetchWithTimeout } from "../lib/fetch.js";

/** Lightbox state: { photos, index } or null when closed. */
export const lightboxState = signal(null);

/**
 * Open the lightbox at a given photo within a list.
 * @param {Array} photos - Full photo list for navigation
 * @param {number} index - Starting index
 */
export function openLightbox(photos, index) {
  lightboxState.value = { photos, index };
}

/** Close the lightbox. */
export function closeLightbox() {
  lightboxState.value = null;
}

/**
 * Lightbox — full-screen overlay photo viewer.
 *
 * Features:
 * - Swipe left/right to navigate (touch events)
 * - Bottom action bar: [FAV], [TAG], [DELETE], [INFO]
 * - Info panel with EXIF date, upload date, view count, file size, dimensions
 * - Escape or overlay tap to close
 */
export function Lightbox({ onToggleFavorite, onDelete, onAddTag, onRemoveTag, tags }) {
  const state = lightboxState.value;
  const overlayRef = useRef(null);
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const infoOpen = signal(false);
  const tagInput = signal("");
  const tagSuggestions = signal([]);
  const allTags = signal([]);

  // Fetch all tags + current photo tags in parallel
  useEffect(() => {
    if (!state) return;
    const photo = state.photos[state.index];
    if (!photo || !photo.id) return;

    Promise.all([
      fetchWithTimeout("/api/tags").then((resp) => resp.ok ? resp.json() : []),
      fetchWithTimeout(`/api/photos/${photo.id}/tags`).then((resp) => resp.ok ? resp.json() : []),
    ])
      .then(([all, current]) => {
        allTags.value = all;
        tagSuggestions.value = current;
      })
      .catch((err) => {
        console.warn("Lightbox: tag fetch failed", err);
        allTags.value = [];
        tagSuggestions.value = [];
      });
  }, [state ? state.index : -1]);

  // Keyboard navigation
  useEffect(() => {
    if (!state) return;
    function handleKey(evt) {
      if (evt.key === "Escape") closeLightbox();
      else if (evt.key === "ArrowLeft") navigate(-1);
      else if (evt.key === "ArrowRight") navigate(1);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [state]);

  if (!state) return null;

  const { photos: photoList, index } = state;
  const photo = photoList[index];
  if (!photo) {
    closeLightbox();
    return null;
  }

  function navigate(direction) {
    const newIndex = index + direction;
    if (newIndex >= 0 && newIndex < photoList.length) {
      lightboxState.value = { photos: photoList, index: newIndex };
    }
  }

  // Touch swipe handlers
  function handleTouchStart(evt) {
    touchStartX.current = evt.touches[0].clientX;
    touchStartY.current = evt.touches[0].clientY;
  }

  function handleTouchEnd(evt) {
    const dx = evt.changedTouches[0].clientX - touchStartX.current;
    const dy = evt.changedTouches[0].clientY - touchStartY.current;
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);

    // Horizontal swipe (must be dominant axis, min 50px)
    if (absDx > 50 && absDx > absDy * 1.5) {
      if (dx > 0) navigate(-1); // swipe right = previous
      else navigate(1);          // swipe left = next
    }
    // Downward swipe to close
    else if (dy > 80 && absDy > absDx * 1.5) {
      closeLightbox();
    }
  }

  function handleOverlayClick(evt) {
    if (evt.target === overlayRef.current) closeLightbox();
  }

  function handleFav() {
    if (onToggleFavorite) onToggleFavorite(photo);
  }

  function handleDeleteAction() {
    if (onDelete) onDelete(photo);
    closeLightbox();
  }

  function toggleInfo() {
    infoOpen.value = !infoOpen.value;
  }

  // Tag input handling
  function handleTagKeyDown(evt) {
    if (evt.key === "Enter") {
      const name = tagInput.value.trim();
      if (name && onAddTag) {
        onAddTag(photo, name);
        tagInput.value = "";
        // Refresh tags
        setTimeout(() => {
          fetchWithTimeout(`/api/photos/${photo.id}/tags`)
            .then((resp) => resp.ok ? resp.json() : [])
            .then((data) => { tagSuggestions.value = data; })
            .catch((err) => console.warn("Lightbox: tag refresh failed", err));
        }, 300);
      }
    }
  }

  function handleRemoveTag(tag) {
    if (onRemoveTag) {
      onRemoveTag(photo, tag);
      // Refresh tags
      setTimeout(() => {
        fetchWithTimeout(`/api/photos/${photo.id}/tags`)
          .then((resp) => resp.ok ? resp.json() : [])
          .then((data) => { tagSuggestions.value = data; })
          .catch((err) => console.warn("Lightbox: tag refresh failed", err));
      }, 300);
    }
  }

  // Filter autocomplete suggestions
  const currentInput = tagInput.value.toLowerCase();
  const currentTagIds = new Set((tagSuggestions.value || []).map((tg) => tg.id));
  const autoSuggestions = currentInput.length > 0
    ? (allTags.value || []).filter(
        (tg) => tg.name.toLowerCase().includes(currentInput) && !currentTagIds.has(tg.id)
      ).slice(0, 5)
    : [];

  const filename = photo.name || photo.filename;
  const photoSrc = photo.is_video ? `/thumbnail/${filename}` : `/media/${filename}`;

  // Format file size
  function formatSize(bytes) {
    if (!bytes) return "UNKNOWN";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  return (
    <div
      class="sh-modal-overlay fc-lightbox-overlay"
      ref={overlayRef}
      onClick={handleOverlayClick}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      role="dialog"
      aria-modal="true"
      aria-label={`Viewing ${filename}`}
      style="z-index: 200; background: rgba(0,0,0,0.95); display: flex; flex-direction: column;"
    >
      {/* Close button */}
      <button
        class="fc-lightbox-close"
        onClick={closeLightbox}
        type="button"
        aria-label="Close lightbox"
        style="position: absolute; top: 8px; right: 12px; z-index: 210; background: none; border: none; color: var(--sh-phosphor); font-size: 1.5rem; cursor: pointer; padding: 8px;"
      >
        X
      </button>

      {/* Counter */}
      <div
        class="sh-ansi-dim"
        style="position: absolute; top: 12px; left: 12px; z-index: 210; font-size: 0.8rem;"
      >
        {index + 1} / {photoList.length}
      </div>

      {/* Main image */}
      <div style="flex: 1; display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 48px 8px 0;">
        {photo.is_video ? (
          <video
            src={`/media/${filename}`}
            controls
            autoplay
            style="max-width: 100%; max-height: 100%; object-fit: contain;"
          />
        ) : (
          <img
            src={`/media/${filename}`}
            alt={filename}
            style="max-width: 100%; max-height: 100%; object-fit: contain;"
          />
        )}
      </div>

      {/* Navigation arrows (large touch targets) */}
      {index > 0 && (
        <button
          class="fc-lightbox-nav fc-lightbox-nav--prev"
          onClick={(evt) => { evt.stopPropagation(); navigate(-1); }}
          type="button"
          aria-label="Previous photo"
          style="position: absolute; left: 0; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.4); border: none; color: var(--sh-phosphor); font-size: 2rem; padding: 16px 12px; cursor: pointer; z-index: 205;"
        >
          &lt;
        </button>
      )}
      {index < photoList.length - 1 && (
        <button
          class="fc-lightbox-nav fc-lightbox-nav--next"
          onClick={(evt) => { evt.stopPropagation(); navigate(1); }}
          type="button"
          aria-label="Next photo"
          style="position: absolute; right: 0; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.4); border: none; color: var(--sh-phosphor); font-size: 2rem; padding: 16px 12px; cursor: pointer; z-index: 205;"
        >
          &gt;
        </button>
      )}

      {/* Bottom action bar */}
      <div
        class="fc-lightbox-actions"
        onClick={(evt) => evt.stopPropagation()}
        style="display: flex; gap: var(--space-3, 12px); justify-content: center; padding: 12px 16px; background: rgba(0,0,0,0.7); border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.1));"
      >
        <button
          class={`fc-action-btn${photo.is_favorite ? " fc-action-btn--active" : ""}`}
          onClick={handleFav}
          type="button"
          style="background: none; border: 1px solid var(--border-subtle); color: inherit; padding: 8px 14px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
        >
          [FAV]
        </button>
        <button
          class="fc-action-btn"
          onClick={toggleInfo}
          type="button"
          style="background: none; border: 1px solid var(--border-subtle); color: inherit; padding: 8px 14px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
        >
          [INFO]
        </button>
        <button
          class="fc-action-btn"
          onClick={handleDeleteAction}
          type="button"
          style="background: none; border: 1px solid var(--border-subtle); color: inherit; padding: 8px 14px; cursor: pointer; font-family: var(--font-mono, monospace); font-size: 0.8rem;"
        >
          [DELETE]
        </button>
      </div>

      {/* Info panel (toggled) */}
      {infoOpen.value && (
        <div
          class="fc-lightbox-info sh-card"
          onClick={(evt) => evt.stopPropagation()}
          style="padding: 12px 16px; background: rgba(0,0,0,0.85); border-top: 1px solid var(--border-subtle); font-size: 0.8rem; font-family: var(--font-mono, monospace);"
        >
          <div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 16px; margin-bottom: 12px;">
            <span class="sh-ansi-dim">FILE</span>
            <span>{filename}</span>

            {photo.exif_date && (
              <>
                <span class="sh-ansi-dim">EXIF DATE</span>
                <span>{photo.exif_date}</span>
              </>
            )}

            <span class="sh-ansi-dim">UPLOADED</span>
            <span>{photo.uploaded_at || "UNKNOWN"}</span>

            <span class="sh-ansi-dim">VIEWS</span>
            <span>{photo.view_count != null ? photo.view_count : 0}</span>

            <span class="sh-ansi-dim">SIZE</span>
            <span>{formatSize(photo.file_size)}</span>

            {(photo.width && photo.height) && (
              <>
                <span class="sh-ansi-dim">DIMENSIONS</span>
                <span>{photo.width} x {photo.height}</span>
              </>
            )}

            <span class="sh-ansi-dim">UPLOADED BY</span>
            <span>{photo.uploaded_by || "default"}</span>
          </div>

          {/* Tags section */}
          <div style="border-top: 1px solid var(--border-subtle); padding-top: 8px;">
            <div class="sh-ansi-dim" style="margin-bottom: 6px;">TAGS</div>
            <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px;">
              {(tagSuggestions.value || []).map((tag) => (
                <span
                  key={tag.id}
                  class="sh-filter-chip sh-filter-chip--active"
                  onClick={() => handleRemoveTag(tag)}
                  style="cursor: pointer; font-size: 0.75rem;"
                  title="Click to remove"
                >
                  {tag.name} x
                </span>
              ))}
              {(!tagSuggestions.value || tagSuggestions.value.length === 0) && (
                <span class="sh-ansi-dim" style="font-size: 0.75rem;">NO TAGS</span>
              )}
            </div>

            {/* Tag input with autocomplete */}
            <div style="position: relative;">
              <input
                class="sh-input"
                type="text"
                placeholder="ADD TAG..."
                value={tagInput.value}
                onInput={(evt) => { tagInput.value = evt.target.value; }}
                onKeyDown={handleTagKeyDown}
                style="width: 100%; font-size: 0.8rem; padding: 6px 8px;"
              />
              {autoSuggestions.length > 0 && (
                <div
                  class="sh-card"
                  style="position: absolute; bottom: 100%; left: 0; right: 0; z-index: 220; margin-bottom: 2px; padding: 4px 0;"
                >
                  {autoSuggestions.map((sug) => (
                    <button
                      key={sug.id}
                      class="fc-ctx-item"
                      type="button"
                      onClick={() => {
                        if (onAddTag) onAddTag(photo, sug.name);
                        tagInput.value = "";
                        setTimeout(() => {
                          fetchWithTimeout(`/api/photos/${photo.id}/tags`)
                            .then((resp) => resp.ok ? resp.json() : [])
                            .then((data) => { tagSuggestions.value = data; })
                            .catch((err) => console.warn("Lightbox: tag refresh failed", err));
                        }, 300);
                      }}
                      style="font-size: 0.75rem;"
                    >
                      {sug.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
