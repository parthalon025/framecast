/** @fileoverview PhotoCard — single photo thumbnail card with favorite toggle, selection, long-press context. */
import { signal } from "@preact/signals";
import { useRef, useCallback } from "preact/hooks";

/** Context menu state: { photo, x, y } or null. */
export const contextTarget = signal(null);

/** Long-press threshold in ms. */
const LONG_PRESS_MS = 500;

/**
 * PhotoCard — displays a single photo/video thumbnail with actions.
 *
 * @param {object}   props
 * @param {object}   props.photo            - Photo object from API
 * @param {Function} [props.onDelete]       - Called when delete action invoked
 * @param {Function} [props.onToggleFavorite] - Called to toggle favorite
 * @param {Function} [props.onSelect]       - Called when card is selected (tap opens lightbox, etc.)
 * @param {boolean}  [props.selected]       - Whether this card is selected
 * @param {boolean}  [props.selectable]     - Whether selection checkbox is shown
 * @param {Function} [props.onSelectionToggle] - Called when selection checkbox is toggled
 * @param {Function} [props.onAddToAlbum]   - Called for "add to album" context action
 */
export function PhotoCard({
  photo,
  onDelete,
  onToggleFavorite,
  onSelect,
  selected,
  selectable,
  onSelectionToggle,
  onAddToAlbum,
}) {
  const longPressTimer = useRef(null);
  const didLongPress = useRef(false);

  function handleClick(evt) {
    // If long-press just fired, swallow the click
    if (didLongPress.current) {
      didLongPress.current = false;
      return;
    }
    // If in selection mode, toggle selection
    if (selectable && onSelectionToggle) {
      evt.stopPropagation();
      onSelectionToggle(photo);
      return;
    }
    // Default: open lightbox / select
    if (onSelect) {
      onSelect(photo);
    }
  }

  function handleFavClick(evt) {
    evt.stopPropagation();
    if (onToggleFavorite) onToggleFavorite(photo);
  }

  function handleCheckboxChange(evt) {
    evt.stopPropagation();
    if (onSelectionToggle) onSelectionToggle(photo);
  }

  // --- Long-press handlers (touch + mouse) ---
  function startLongPress(evt) {
    didLongPress.current = false;
    longPressTimer.current = setTimeout(() => {
      didLongPress.current = true;
      const rect = evt.currentTarget.getBoundingClientRect();
      contextTarget.value = {
        photo,
        x: rect.left + rect.width / 2,
        y: rect.top,
        onDelete,
        onToggleFavorite,
        onAddToAlbum,
      };
    }, LONG_PRESS_MS);
  }

  function cancelLongPress() {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }

  const isFav = photo.is_favorite;

  return (
    <div
      class={`sh-card sh-clickable${selected ? " sh-card--selected" : ""}${isFav ? " fc-card--favorite" : ""}`}
      onClick={handleClick}
      onTouchStart={startLongPress}
      onTouchEnd={cancelLongPress}
      onTouchCancel={cancelLongPress}
      onMouseDown={startLongPress}
      onMouseUp={cancelLongPress}
      onMouseLeave={cancelLongPress}
      role="button"
      tabIndex={0}
      aria-label={`${photo.name || photo.filename} — ${isFav ? "favorite" : "photo"}`}
      style="position: relative;"
    >
      {/* Selection checkbox */}
      {selectable && (
        <label
          class="fc-select-check"
          onClick={(evt) => evt.stopPropagation()}
          style="position: absolute; top: 4px; left: 4px; z-index: 2; cursor: pointer;"
        >
          <input
            type="checkbox"
            checked={!!selected}
            onChange={handleCheckboxChange}
            aria-label={`Select ${photo.name || photo.filename}`}
            style="width: 18px; height: 18px; accent-color: var(--sh-phosphor);"
          />
        </label>
      )}

      {/* Favorite toggle */}
      <button
        class={`fc-fav-btn${isFav ? " fc-fav-btn--active" : ""}`}
        onClick={handleFavClick}
        aria-label={isFav ? "Remove from favorites" : "Add to favorites"}
        aria-pressed={!!isFav}
        type="button"
        style={`
          position: absolute; top: 4px; right: 4px; z-index: 2;
          background: rgba(0,0,0,0.6); border: none; cursor: pointer;
          color: ${isFav ? "gold" : "rgba(255,255,255,0.5)"};
          font-size: 1rem; padding: 2px 4px; line-height: 1;
          border-radius: 2px;
        `}
      >
        {isFav ? "\u2605" : "\u2606"}
      </button>

      <img
        src={photo.is_video ? `/thumbnail/${photo.name || photo.filename}` : `/media/${photo.name || photo.filename}`}
        alt={photo.name || photo.filename}
        loading="lazy"
        style="width: 100%; aspect-ratio: 1; object-fit: cover; display: block; border-radius: 4px;"
      />
      {photo.is_video && (
        <span class="sh-status-badge" data-sh-status="active" style="position: absolute; top: 6px; right: 6px; margin-top: 22px;">
          VIDEO
        </span>
      )}
      <div class="sh-ansi-dim" style="padding: 6px 0 0; font-size: 0.75rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
        {photo.name || photo.filename}
      </div>
    </div>
  );
}

/**
 * ContextMenu — rendered once, positioned at contextTarget location.
 * Dismiss by clicking outside or selecting an action.
 */
export function ContextMenu() {
  const ctx = contextTarget.value;
  if (!ctx) return null;

  function dismiss() {
    contextTarget.value = null;
  }

  function doFavorite() {
    if (ctx.onToggleFavorite) ctx.onToggleFavorite(ctx.photo);
    dismiss();
  }

  function doAlbum() {
    if (ctx.onAddToAlbum) ctx.onAddToAlbum(ctx.photo);
    dismiss();
  }

  function doDelete() {
    if (ctx.onDelete) ctx.onDelete(ctx.photo);
    dismiss();
  }

  return (
    <div
      class="sh-modal-overlay"
      onClick={dismiss}
      style="z-index: 100; background: rgba(0,0,0,0.4);"
    >
      <div
        class="sh-card fc-context-menu"
        style={`
          position: fixed;
          left: ${Math.max(8, ctx.x - 80)}px;
          top: ${Math.max(8, ctx.y - 10)}px;
          z-index: 101;
          min-width: 160px;
          padding: 4px 0;
        `}
        onClick={(evt) => evt.stopPropagation()}
      >
        <button class="fc-ctx-item" onClick={doFavorite} type="button">
          [FAV] {ctx.photo.is_favorite ? "UNFAVORITE" : "FAVORITE"}
        </button>
        {ctx.onAddToAlbum && (
          <button class="fc-ctx-item" onClick={doAlbum} type="button">
            [ADD] TO ALBUM
          </button>
        )}
        <button class="fc-ctx-item fc-ctx-item--danger" onClick={doDelete} type="button">
          [DELETE] REMOVE
        </button>
      </div>
    </div>
  );
}
