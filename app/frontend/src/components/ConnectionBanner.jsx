/** @fileoverview TV connection status banner — shown when heartbeat is missed. */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";

const HEARTBEAT_TIMEOUT = 60000; // 60s
export const tvConnected = signal(true);
let lastHeartbeat = Date.now();

/** Call this from SSE listener when heartbeat received. */
export function onHeartbeat() {
  lastHeartbeat = Date.now();
  tvConnected.value = true;
}

export function ConnectionBanner() {
  useEffect(() => {
    const timer = setInterval(() => {
      if (Date.now() - lastHeartbeat > HEARTBEAT_TIMEOUT) {
        tvConnected.value = false;
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  if (tvConnected.value) return null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      style="position: fixed; top: 0; left: 0; right: 0; z-index: 200; background: var(--sh-threat, #ff3333); color: #000; font-family: var(--font-mono, monospace); font-size: 0.8rem; text-align: center; padding: 8px 16px; display: flex; align-items: center; justify-content: center; gap: 12px;"
    >
      <span style="letter-spacing: 0.1em;">TV CONNECTION LOST</span>
      <button
        type="button"
        onClick={() => {
          if (confirm("Restart the device? The display will be unavailable briefly.")) {
            fetch("/api/reboot", { method: "POST" }).catch((err) => {
              console.warn("ConnectionBanner: reboot request failed", err);
            });
          }
        }}
        style="background: #000; color: var(--sh-threat, #ff3333); border: 1px solid #000; font-family: var(--font-mono, monospace); font-size: 0.75rem; padding: 4px 12px; cursor: pointer; letter-spacing: 0.1em;"
      >
        RESTART
      </button>
    </div>
  );
}
