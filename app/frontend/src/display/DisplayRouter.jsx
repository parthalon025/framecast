/** @fileoverview State-based router for the TV display surface.
 *
 * Determines what to show on the TV:
 *   "boot"      - Startup animation (bootSequence typewriter + narrator greeting)
 *   "setup"     - WiFi/network setup screen (AP mode) — facility: alert
 *   "welcome"   - No photos yet, show upload instructions + QR — facility: normal
 *   "slideshow" - Photo slideshow — facility: normal
 *
 * Facility state and narrator personality shift with display state.
 * Connects to SSE /api/events for real-time state transitions.
 */
import { signal, effect } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { ShPageBanner } from "superhot-ui/preact";
import { createSSE } from "../lib/sse.js";
import { setFacilityState, ShNarrator } from "superhot-ui";
import { Boot } from "./Boot.jsx";
import { Welcome } from "./Welcome.jsx";
import { Setup } from "./Setup.jsx";
import { Slideshow } from "./Slideshow.jsx";
import { AmbientClock } from "./AmbientClock.jsx";

/** Current display state -- exported for other components to read. */
export const displayState = signal("boot");

/** Access PIN fetched from /api/status -- shown on TV screens. */
const accessPin = signal("");

// Shift facility state + narrator personality when display state changes
effect(() => {
  const state = displayState.value;
  if (state === "setup") {
    setFacilityState("alert");
    ShNarrator.personality = "wheatley";
  } else if (state === "boot") {
    // Boot handles its own facility transitions
  } else {
    setFacilityState("normal");
    ShNarrator.personality = "glados";
  }
});

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
 * After boot animation completes, determine which screen to show next.
 * Accepts statusData from Boot (already fetched) to avoid a duplicate
 * /api/status round-trip. Falls back to a fresh fetch if not provided.
 */
async function handleBootComplete(statusData) {
  try {
    const data =
      statusData ||
      (await fetch("/api/status").then((r) => r.json()).catch(() => null));

    if (!data) {
      // Can't reach API — likely no network
      displayState.value = "setup";
      return;
    }

    if (data.access_pin) {
      accessPin.value = data.access_pin;
    }

    // No WiFi → setup screen (facility shifts to alert via effect)
    if (!data.wifi_connected) {
      displayState.value = "setup";
      return;
    }

    const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
    if (totalMedia > 0) {
      displayState.value = "slideshow";
    } else {
      displayState.value = "welcome";
    }
  } catch (err) {
    console.error("DisplayRouter: status fetch failed", err);
    // Default to setup on error — can't reach API, likely no network
    displayState.value = "setup";
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
      return (
        <>
          <Welcome />
          <AmbientClock />
        </>
      );
    case "slideshow":
      return <Slideshow />;
    default:
      return <Boot onComplete={handleBootComplete} />;
  }
}

export function DisplayRouter() {
  // SSE: react to photo and wifi changes after initial boot
  useEffect(() => {
    let cancelled = false;

    const sse = createSSE("/api/events", {
      pauseOnHidden: false,
      listeners: {
        "photo:added": () => {
          if (cancelled) return;
          // Transition from welcome or setup to slideshow
          if (displayState.value === "welcome" || displayState.value === "setup") {
            displayState.value = "slideshow";
          }
        },
        "photo:deleted": () => {
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
        },
        "wifi:connecting": () => {
          // No state change — Setup component shows its own connecting UI
        },
        "wifi:connected": () => {
          if (cancelled) return;
          // WiFi just connected — re-check status to determine next state
          fetch("/api/status")
            .then((res) => res.json())
            .then((data) => {
              if (cancelled) return;
              const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
              displayState.value = totalMedia > 0 ? "slideshow" : "welcome";
            })
            .catch((err) => {
              console.warn("DisplayRouter: wifi:connected refetch failed", err);
            });
        },
        "wifi:failed": () => {
          if (cancelled) return;
          // Stay in setup — AP will have restarted server-side
          displayState.value = "setup";
        },
        "wifi:disconnected": () => {
          if (cancelled) return;
          // Home WiFi lost — watchdog will start AP for recovery
          displayState.value = "setup";
        },
        "wifi:ap_restarted": () => {
          if (cancelled) return;
          // AP timeout fired, AP restarted — show setup screen
          displayState.value = "setup";
        },
        "sync": () => {
          if (cancelled) return;
          // Peer lost sync — re-check current state
          fetch("/api/status")
            .then((res) => res.json())
            .then((data) => {
              if (cancelled) return;
              const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
              if (totalMedia === 0) {
                displayState.value = "welcome";
              } else if (displayState.value === "welcome") {
                displayState.value = "slideshow";
              }
            })
            .catch((err) => {
              console.warn("DisplayRouter: sync refetch failed", err);
            });
        },
      },
    });

    return () => {
      cancelled = true;
      sse.close();
    };
  }, []);

  // Fallback: periodic re-check when stuck in setup (in case SSE missed)
  useEffect(() => {
    if (displayState.value !== "setup") return;
    const interval = setInterval(() => {
      fetch("/api/status")
        .then((res) => res.json())
        .then((data) => {
          if (data.wifi_connected) {
            const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
            displayState.value = totalMedia > 0 ? "slideshow" : "welcome";
          }
        })
        .catch(() => {});
    }, 60000);
    return () => clearInterval(interval);
  }, [displayState.value]);

  const state = displayState.value;
  const showPin = state === "setup" || state === "welcome";

  return (
    <div style="position:fixed;inset:0;background:#000;">
      <ShPageBanner namespace="FRAMECAST" page="DISPLAY" />
      {renderState(state)}
      {showPin && (
        <div style="position:fixed;bottom:48px;left:0;right:0;text-align:center;">
          <PinDisplay />
        </div>
      )}
    </div>
  );
}
