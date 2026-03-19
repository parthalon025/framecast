/** @fileoverview State-based router for the TV display surface.
 *
 * Determines what to show on the TV:
 *   "boot"      - Startup animation (bootSequence typewriter)
 *   "setup"     - WiFi/network setup screen (AP mode)
 *   "welcome"   - No photos yet, show upload instructions + QR
 *   "slideshow" - Photo slideshow
 *
 * Connects to SSE /api/events for real-time state transitions.
 */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { Boot } from "./Boot.jsx";
import { Welcome } from "./Welcome.jsx";
import { Setup } from "./Setup.jsx";
import { Slideshow } from "./Slideshow.jsx";

/** Current display state -- exported for other components to read. */
export const displayState = signal("boot");

/** Access PIN fetched from /api/status -- shown on TV screens. */
const accessPin = signal("");

/** PIN display shown on Setup and Welcome screens. */
function PinDisplay() {
  const pin = accessPin.value;
  if (!pin) return null;
  return (
    <div style="margin-top: 24px;">
      <span
        class="sh-label"
        style="font-size: 1.1rem; letter-spacing: 0.2em; opacity: 0.85;"
      >
        ACCESS PIN: {pin}
      </span>
    </div>
  );
}

/**
 * After boot animation completes, check /api/status to determine
 * which screen to show next.
 */
async function handleBootComplete() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    if (data.access_pin) {
      accessPin.value = data.access_pin;
    }

    const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
    if (totalMedia > 0) {
      displayState.value = "slideshow";
    } else {
      displayState.value = "welcome";
    }
  } catch (err) {
    console.error("DisplayRouter: status fetch failed", err);
    // Default to welcome on error -- SSE will correct if needed
    displayState.value = "welcome";
  }
}

/** Map state name to component. */
function renderState(stateName) {
  switch (stateName) {
    case "boot":
      return <Boot onComplete={handleBootComplete} />;
    case "setup":
      return <Setup />;
    case "welcome":
      return <Welcome />;
    case "slideshow":
      return <Slideshow />;
    default:
      return <Boot onComplete={handleBootComplete} />;
  }
}

export function DisplayRouter() {
  // SSE: react to photo changes after initial boot
  useEffect(() => {
    let cancelled = false;
    let source = null;

    function connectSSE() {
      if (source) source.close();
      source = new EventSource("/api/events");

      source.addEventListener("photo:added", () => {
        if (cancelled) return;
        // If we were on welcome, switch to slideshow
        if (displayState.value === "welcome") {
          displayState.value = "slideshow";
        }
      });

      source.addEventListener("photo:deleted", () => {
        if (cancelled) return;
        // Re-check if any photos remain
        fetch("/api/status")
          .then((res) => res.json())
          .then((data) => {
            if (cancelled) return;
            const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
            if (totalMedia === 0) {
              displayState.value = "welcome";
            }
          })
          .catch((err) => {
              console.warn("DisplayRouter: status refetch after delete failed", err);
          });
      });

      source.onerror = () => {
        source.close();
        setTimeout(connectSSE, 3000);
      };
    }

    connectSSE();

    return () => {
      cancelled = true;
      if (source) source.close();
    };
  }, []);

  const state = displayState.value;
  const showPin = state === "setup" || state === "welcome";

  return (
    <div style="position:fixed;inset:0;background:#000;">
      {renderState(state)}
      {showPin && (
        <div style="position:fixed;bottom:48px;left:0;right:0;text-align:center;">
          <PinDisplay />
        </div>
      )}
    </div>
  );
}
