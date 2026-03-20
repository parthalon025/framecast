/** @fileoverview Centralized toast manager — single stack for entire app. */
import { signal } from "@preact/signals";

/** Current toast state: { type, message } or null */
export const toast = signal(null);

/** Show a toast — auto-clears after duration (0 = persistent). */
export function showToast(message, type = "info", duration = 4000) {
  toast.value = { type, message };
  if (duration > 0) {
    setTimeout(() => {
      if (toast.value?.message === message) toast.value = null;
    }, duration);
  }
}

/** Clear the current toast. */
export function clearToast() {
  toast.value = null;
}
