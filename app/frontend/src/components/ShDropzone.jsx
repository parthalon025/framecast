/** @fileoverview Drag-and-drop upload component with XHR progress tracking. */
import { signal } from "@preact/signals";
import { useRef, useCallback, useEffect } from "preact/hooks";
import { glitchText } from "superhot-ui";

/** Module-level signals for ShDropzone (prevent stale subscriber bugs). */
const dropzoneState = signal("idle");
const dropzoneProgress = signal(0);
const dropzoneErrorMsg = signal("");

/**
 * ShDropzone — file upload via drag-and-drop or click-to-browse.
 *
 * States (data-sh-dropzone attribute):
 *   idle      — dashed phosphor border, awaiting input
 *   hover     — solid border + glow, drop to upload
 *   receiving — solid border, ASCII progress bar + percentage
 *   error     — threat border, transfer failed
 *   complete  — received label, glitch burst, resets to idle after 2s
 *
 * @param {object}   props
 * @param {Function} [props.onUpload]      - Called with uploaded filename on success (single file)
 * @param {Function} [props.onBatchUpload] - Called with FileList for batch upload (multi-file, handled externally)
 * @param {number}   [props.maxSizeMB]     - Max file size in MB (client-side validation)
 * @param {boolean}  [props.disabled]      - Block uploads (e.g. disk full)
 */
export function ShDropzone({ onUpload, onBatchUpload, maxSizeMB = 200, disabled = false }) {
  const zoneRef = useRef(null);
  const inputRef = useRef(null);
  const activeUploads = useRef(0);

  // Reset module-level signals on mount
  useEffect(() => {
    dropzoneState.value = "idle";
    dropzoneProgress.value = 0;
    dropzoneErrorMsg.value = "";
  }, []);

  /** Build ASCII progress bar: [▓▓▓░░░] */
  function asciiBar(pct) {
    const width = 20;
    const filled = Math.round((pct / 100) * width);
    const empty = width - filled;
    return "[" + "\u2593".repeat(filled) + "\u2591".repeat(empty) + "]";
  }

  /** Upload a single file via XHR for progress events. */
  function uploadFile(file) {
    // Client-side size validation
    const maxBytes = maxSizeMB * 1024 * 1024;
    if (file.size > maxBytes) {
      dropzoneState.value = "error";
      dropzoneErrorMsg.value = `FILE EXCEEDS ${maxSizeMB}MB LIMIT`;
      setTimeout(() => {
        dropzoneState.value = "idle";
        dropzoneErrorMsg.value = "";
      }, 3000);
      return;
    }

    activeUploads.current++;
    dropzoneState.value = "receiving";
    dropzoneProgress.value = 0;

    const form = new FormData();
    form.append("files", file);

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (evt) => {
      if (evt.lengthComputable) {
        dropzoneProgress.value = Math.round((evt.loaded / evt.total) * 100);
      }
    });

    xhr.addEventListener("load", () => {
      activeUploads.current--;
      if (xhr.status >= 200 && xhr.status < 300) {
        dropzoneState.value = "complete";
        dropzoneProgress.value = 100;

        // Glitch burst on the label
        const label = zoneRef.current?.querySelector("[data-dropzone-label]");
        if (label) glitchText(label, { duration: 400, intensity: "high" });

        // Parse JSON response if available
        let filename = file.name;
        try {
          const resp = JSON.parse(xhr.responseText);
          if (resp.uploaded && resp.uploaded.length > 0) {
            filename = resp.uploaded[0];
          }
        } catch (_) {
          // Non-JSON response (redirect), use original filename
        }

        onUpload?.(filename);

        setTimeout(() => {
          if (activeUploads.current === 0) {
            dropzoneState.value = "idle";
            dropzoneProgress.value = 0;
          }
        }, 2000);
      } else {
        dropzoneState.value = "error";
        dropzoneErrorMsg.value = `TRANSFER FAILED (${xhr.status})`;
        setTimeout(() => {
          dropzoneState.value = "idle";
          dropzoneErrorMsg.value = "";
        }, 3000);
      }
    });

    xhr.addEventListener("error", () => {
      activeUploads.current--;
      dropzoneState.value = "error";
      dropzoneErrorMsg.value = "NETWORK ERROR";
      setTimeout(() => {
        dropzoneState.value = "idle";
        dropzoneErrorMsg.value = "";
      }, 3000);
    });

    xhr.open("POST", "/upload");
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.send(form);
  }

  /** Process dropped/selected files. */
  function handleFiles(fileList) {
    if (disabled || !fileList || fileList.length === 0) return;
    // Delegate to batch handler when available (Upload page manages progress UI)
    if (onBatchUpload && fileList.length > 0) {
      onBatchUpload(fileList);
      return;
    }
    for (let i = 0; i < fileList.length; i++) {
      uploadFile(fileList[i]);
    }
  }

  const onDragOver = useCallback((evt) => {
    evt.preventDefault();
    if (!disabled) dropzoneState.value = "hover";
  }, [disabled]);

  const onDragLeave = useCallback((evt) => {
    evt.preventDefault();
    if (activeUploads.current === 0) dropzoneState.value = "idle";
  }, []);

  const onDrop = useCallback((evt) => {
    evt.preventDefault();
    handleFiles(evt.dataTransfer?.files);
  }, [disabled, maxSizeMB]);

  const onClick = useCallback(() => {
    if (!disabled) inputRef.current?.click();
  }, [disabled]);

  const onFileChange = useCallback((evt) => {
    handleFiles(evt.target.files);
    // Reset so the same file can be selected again
    evt.target.value = "";
  }, [disabled, maxSizeMB]);

  const currentState = dropzoneState.value;
  const currentProgress = dropzoneProgress.value;
  const currentError = dropzoneErrorMsg.value;

  return (
    <div
      class="sh-dropzone"
      data-sh-dropzone={currentState}
      ref={zoneRef}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label="Upload files"
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,video/*"
        style="display: none;"
        onChange={onFileChange}
      />

      {currentState === "idle" && (
        <div>
          <div class="sh-label" data-dropzone-label>AWAITING INPUT</div>
          <div class="sh-ansi-dim" style="margin-top: 8px;">
            {disabled ? "STORAGE FULL — UPLOADS BLOCKED" : "TAP OR DRAG FILES"}
          </div>
        </div>
      )}

      {currentState === "hover" && (
        <div>
          <div class="sh-label" data-dropzone-label>DROP TO UPLOAD</div>
        </div>
      )}

      {currentState === "receiving" && (
        <div>
          <div class="sh-label" data-dropzone-label>TRANSFERRING</div>
          <div class="sh-value" style="font-family: var(--font-mono, monospace); margin-top: 8px;">
            {asciiBar(currentProgress)} {currentProgress}%
          </div>
        </div>
      )}

      {currentState === "error" && (
        <div>
          <div class="sh-label" data-dropzone-label>TRANSFER FAILED</div>
          <div class="sh-ansi-dim" style="margin-top: 8px;">{currentError}</div>
        </div>
      )}

      {currentState === "complete" && (
        <div>
          <div class="sh-label" data-dropzone-label>RECEIVED</div>
        </div>
      )}
    </div>
  );
}
