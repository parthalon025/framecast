/** @fileoverview Offline detection banner — shows when navigator.onLine is false.
 *
 * Uses navigator.onLine + online/offline events for detection.
 * piOS voice: "OFFLINE" — no conversational language.
 */
import { useState, useEffect } from "preact/hooks";

/**
 * OfflineBanner — fixed banner at top of viewport when offline.
 * Returns null when online.
 */
export function OfflineBanner() {
  const [offline, setOffline] = useState(
    typeof navigator !== "undefined" ? !navigator.onLine : false,
  );

  useEffect(() => {
    function handleOnline() {
      setOffline(false);
    }
    function handleOffline() {
      setOffline(true);
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div
      class="fc-offline-banner"
      role="alert"
      aria-live="assertive"
    >
      OFFLINE
    </div>
  );
}
