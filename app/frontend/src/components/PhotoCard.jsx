/** @fileoverview PhotoCard — single photo thumbnail card extracted from PhotoGrid. */

/**
 * PhotoCard — displays a single photo/video thumbnail with optional actions.
 *
 * Pure presentational component. Renders identically to the cards
 * previously inline in PhotoGrid's .map() body.
 *
 * @param {object}   props
 * @param {object}   props.photo            - Photo object from API
 * @param {Function} [props.onDelete]       - Called when card is clicked (opens delete modal)
 * @param {Function} [props.onToggleFavorite] - Called to toggle favorite (future use)
 * @param {Function} [props.onSelect]       - Called when card is selected (future use)
 * @param {boolean}  [props.selected]       - Whether this card is selected (future use)
 */
export function PhotoCard({ photo, onDelete, onToggleFavorite, onSelect, selected }) {
  function handleClick() {
    if (onSelect) {
      onSelect(photo);
    } else if (onDelete) {
      onDelete(photo);
    }
  }

  return (
    <div
      key={photo.name}
      class={`sh-card sh-clickable${selected ? " sh-card--selected" : ""}`}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-label={`${photo.name} — click to ${onSelect ? "select" : "delete"}`}
    >
      <img
        src={photo.is_video ? `/thumbnail/${photo.name}` : `/media/${photo.name}`}
        alt={photo.name}
        loading="lazy"
        style="width: 100%; aspect-ratio: 1; object-fit: cover; display: block; border-radius: 4px;"
      />
      {photo.is_video && (
        <span class="sh-status-badge" data-sh-status="active" style="position: absolute; top: 6px; right: 6px;">
          VIDEO
        </span>
      )}
      <div class="sh-ansi-dim" style="padding: 6px 0 0; font-size: 0.75rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
        {photo.name}
      </div>
    </div>
  );
}
