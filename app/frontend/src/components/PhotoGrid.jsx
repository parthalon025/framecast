/** @fileoverview Photo thumbnail grid with delete confirmation modal. */
import { signal } from "@preact/signals";
import { ShModal } from "superhot-ui/preact";
import { PhotoCard } from "./PhotoCard.jsx";

/** Currently selected photo for delete confirmation. null = modal closed. */
const deleteTarget = signal(null);
const deleting = signal(false);

/**
 * PhotoGrid — grid of photo thumbnails with delete action.
 *
 * @param {object}   props
 * @param {Array}    props.photos   - Array of photo objects from /api/photos
 * @param {Function} [props.onDelete] - Called with filename after successful delete
 * @param {Function} [props.onToggleFavorite] - Called to toggle favorite on a photo
 * @param {Function} [props.onSelect] - Called when a photo is tapped (opens lightbox)
 * @param {boolean}  [props.selectionMode] - Whether bulk selection mode is active
 * @param {Set}      [props.selectedIds] - Set of selected photo IDs
 * @param {Function} [props.onSelectionToggle] - Toggle selection on a single photo
 * @param {Function} [props.onEnterSelection] - Enter selection mode via long-press
 */
export function PhotoGrid({
  photos = [],
  onDelete,
  onToggleFavorite,
  onSelect,
  selectionMode,
  selectedIds,
  onSelectionToggle,
  onEnterSelection,
}) {
  function openDeleteModal(photo) {
    deleteTarget.value = photo;
  }

  function closeDeleteModal() {
    deleteTarget.value = null;
  }

  function confirmDelete() {
    const photo = deleteTarget.value;
    if (!photo || deleting.value) return;

    deleting.value = true;

    const form = new FormData();
    form.append("filename", photo.name || photo.filename);

    fetch("/delete", { method: "POST", body: form })
      .then((resp) => {
        if (resp.ok || resp.redirected) {
          onDelete?.(photo.name || photo.filename);
        }
      })
      .catch((err) => {
        console.warn("Delete request failed", err);
      })
      .finally(() => {
        deleting.value = false;
        deleteTarget.value = null;
      });
  }

  const target = deleteTarget.value;
  const isDeleting = deleting.value;

  // Empty state
  if (photos.length === 0) {
    return (
      <div class="sh-frame" data-label="MEDIA">
        <div style="padding: 32px; text-align: center;">
          <div class="sh-ansi-dim">NO DATA</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div class="sh-grid sh-grid-3">
        {photos.map((photo) => (
          <PhotoCard
            key={photo.name || photo.id}
            photo={photo}
            onDelete={openDeleteModal}
            onToggleFavorite={onToggleFavorite}
            onSelect={onSelect}
            selectable={!!selectionMode}
            selected={selectedIds ? selectedIds.has(photo.id) : false}
            onSelectionToggle={onSelectionToggle}
            onEnterSelection={onEnterSelection}
          />
        ))}
      </div>

      <ShModal
        open={!!target}
        title="CONFIRM: DELETE FILE"
        body={target ? `Remove "${target.name || target.filename}" (${target.size_human || ""})? IRREVERSIBLE.` : ""}
        confirmLabel={isDeleting ? "STANDBY" : "DELETE"}
        cancelLabel="CANCEL"
        onConfirm={confirmDelete}
        onCancel={closeDeleteModal}
      />
    </div>
  );
}
