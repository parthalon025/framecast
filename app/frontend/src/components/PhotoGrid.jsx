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
 */
export function PhotoGrid({ photos = [], onDelete }) {
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
    form.append("filename", photo.name);

    fetch("/delete", { method: "POST", body: form })
      .then((resp) => {
        if (resp.ok || resp.redirected) {
          onDelete?.(photo.name);
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
          <div class="sh-ansi-dim">NO ACTIVE PHOTOS</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div class="sh-grid sh-grid-3">
        {photos.map((photo) => (
          <PhotoCard
            key={photo.name}
            photo={photo}
            onDelete={openDeleteModal}
          />
        ))}
      </div>

      <ShModal
        open={!!target}
        title="CONFIRM: DELETE FILE"
        body={target ? `Remove "${target.name}" (${target.size_human})? This cannot be undone.` : ""}
        confirmLabel={isDeleting ? "DELETING..." : "DELETE"}
        cancelLabel="CANCEL"
        onConfirm={confirmDelete}
        onCancel={closeDeleteModal}
      />
    </div>
  );
}
