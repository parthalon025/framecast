/** @fileoverview Offline detection banner — shows when navigator.onLine is false.
 *
 * Uses navigator.onLine + online/offline events for detection.
 * Drives facility state: alert when offline, normal when recovered.
 * piOS voice: "OFFLINE" — no conversational language.
 */
import { useState, useEffect } from "preact/hooks";
import { setFacilityState } from "superhot-ui";

/**
 * OfflineBanner — fixed banner at top of viewport when offline.
 * Returns null when online. Sets facility state to 'alert' when offline.
 */
export function OfflineBanner() {
  const [offline, setOffline] = useState(
    typeof navigator !== "undefined" ? !navigator.onLine : false,
  );

  useEffect(() => {
    function handleOnline() {
      setOffline(false);
      setFacilityState("normal");
    }
    function handleOffline() {
      setOffline(true);
      setFacilityState("alert");
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    // Set initial facility state based on current connectivity
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setFacilityState("alert");
    }

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
