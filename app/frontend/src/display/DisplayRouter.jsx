/** @fileoverview State-based router for the TV display surface.
 *
 * Determines what to show on the TV:
 *   "boot"      - Startup animation (placeholder)
 *   "setup"     - WiFi/network setup screen (placeholder)
 *   "welcome"   - No photos yet, show upload instructions (placeholder)
 *   "slideshow" - Photo slideshow
 *
 * Connects to SSE /api/events for real-time state transitions.
 */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { Slideshow } from "./Slideshow.jsx";

/** Current display state -- exported for other components to read. */
export const displayState = signal("boot");

// --- Placeholder components (filled in Batch 5) ---

function BootScreen() {
  return (
    <div class="boot-screen">
      <div class="boot-logo">FrameCast</div>
      <div class="boot-status">Starting...</div>
    </div>
  );
}

function SetupScreen() {
  return (
    <div class="boot-screen">
      <div class="boot-logo">FrameCast</div>
      <div class="boot-status">Setup required</div>
    </div>
  );
}

function WelcomeScreen() {
  return (
    <div class="boot-screen">
      <div class="boot-logo">FrameCast</div>
      <div class="boot-status">
        No photos yet. Upload photos from your phone to get started.
      </div>
    </div>
  );
}

/** Map state name to component. */
function renderState(stateName) {
  switch (stateName) {
    case "boot":
      return <BootScreen />;
    case "setup":
      return <SetupScreen />;
    case "welcome":
      return <WelcomeScreen />;
    case "slideshow":
      return <Slideshow />;
    default:
      return <BootScreen />;
  }
}

export function DisplayRouter() {
  // On mount: determine initial state from /api/status
  useEffect(() => {
    let cancelled = false;

    async function determineState() {
      try {
        const res = await fetch("/api/status");
        if (cancelled) return;
        const data = await res.json();

        const totalMedia = (data.photo_count || 0) + (data.video_count || 0);
        if (totalMedia > 0) {
          displayState.value = "slideshow";
        } else {
          displayState.value = "welcome";
        }
      } catch (err) {
        console.error("DisplayRouter: status fetch failed", err);
        // Stay on boot screen on error -- will retry via SSE
        displayState.value = "welcome";
      }
    }

    determineState();

    // SSE: react to photo changes
    const source = new EventSource("/api/events");

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
        .catch(() => {});
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, []);

  return (
    <div style="position:fixed;inset:0;background:#000;">
      {renderState(displayState.value)}
    </div>
  );
}
