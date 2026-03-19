/** @fileoverview Photo thumbnail grid with delete confirmation modal. */
import { signal } from "@preact/signals";
import { ShModal } from "superhot-ui/preact";

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
      .catch(() => {
        // Silently handle — the SSE event will confirm deletion
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
          <div
            key={photo.name}
            class="sh-card sh-clickable"
            onClick={() => openDeleteModal(photo)}
            role="button"
            tabIndex={0}
            aria-label={`${photo.name} — click to delete`}
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
