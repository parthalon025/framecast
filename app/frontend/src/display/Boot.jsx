/** @fileoverview Boot screen with superhot-ui atmosphere system.
 *
 * Two-phase boot:
 *   Phase 1 (mechanical): bootSequence typewriter — system lines
 *   Phase 2 (alive): ShAnnouncement — narrator greeting with personality
 *
 * Facility state shifts based on /api/status result:
 *   WiFi missing → alert, photos exist → normal, no photos → normal
 */
import { useRef, useEffect, useState } from "preact/hooks";
import {
  bootSequence,
  narrate,
  ShNarrator,
  setFacilityState,
} from "superhot-ui";
import { ShAnnouncement } from "superhot-ui/preact";

const VERSION = "2.0";

/**
 * Boot — full-screen startup animation with atmosphere.
 *
 * @param {Object} props
 * @param {Function} [props.onComplete] - Called after boot + status check
 */
export function Boot({ onComplete }) {
  const containerRef = useRef(null);
  const [greeting, setGreeting] = useState("");
  const [personality, setPersonality] = useState("glados");
  const [phase, setPhase] = useState("boot"); // boot | greeting | done

  useEffect(() => {
    if (!containerRef.current) return;

    // Phase 1: mechanical typewriter
    const cleanup = bootSequence(
      containerRef.current,
      [
        `piOS v${VERSION}`,
        "FRAMECAST PHOTO SYSTEM",
        "INITIALIZING...",
        "CHECKING NETWORK...",
        "LOADING MEDIA...",
      ],
      {
        charSpeed: 25,
        lineDelay: 150,
        onComplete: () => checkStatusAndGreet(),
      },
    );

    return cleanup;
  }, []);

  async function checkStatusAndGreet() {
    let statusData = null;

    try {
      const res = await fetch("/api/status");
      statusData = await res.json();
    } catch (err) {
      console.warn("Boot: status fetch failed", err);
    }

    // Determine facility state from system health
    const wifiOk = statusData?.wifi_connected ?? false;

    if (!wifiOk) {
      setFacilityState("alert");
      setPersonality("wheatley");
      ShNarrator.personality = "wheatley";
    } else {
      setFacilityState("normal");
      ShNarrator.personality = "glados";
    }

    // Phase 2: narrator greeting
    const msg = narrate("greeting");
    setGreeting(msg);
    setPhase("greeting");

    // Let the greeting type out, then complete — pass statusData to avoid
    // a duplicate /api/status fetch in DisplayRouter (R: remove duplicate)
    const greetDuration = msg.length * 30 + 1500;
    setTimeout(() => {
      setPhase("done");
      onComplete?.(statusData);
    }, greetDuration);
  }

  return (
    <div class="boot-screen">
      <div ref={containerRef} class="sh-boot-container" />
      {phase === "greeting" && greeting && (
        <div style="margin-top: var(--space-6); max-width: 600px;">
          <ShAnnouncement
            message={greeting}
            personality={personality}
            source="ENRICHMENT CENTER"
            typeSpeed={30}
          />
        </div>
      )}
    </div>
  );
}
