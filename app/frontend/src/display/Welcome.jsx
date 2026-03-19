/** @fileoverview Welcome screen — shown when WiFi is connected but no photos exist. */
import { QRCode } from "../components/QRCode.jsx";

/**
 * Welcome — instructs the user to scan QR code to upload photos.
 * PIN display is handled by PinDisplay in DisplayRouter — not duplicated here.
 */
export function Welcome() {
  const url = `http://${window.location.hostname}:8080`;

  return (
    <div class="boot-screen" style={{ alignItems: "center", textAlign: "center" }}>
      <h1 style={{ fontSize: "var(--type-display)", color: "var(--sh-phosphor)", marginBottom: "var(--space-6)" }}>
        FRAMECAST
      </h1>

      <div data-sh-mantra="AWAITING INPUT" style={{ marginBottom: "var(--space-8)" }}>
        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          SCAN TO UPLOAD PHOTOS
        </p>
        <QRCode url={url} size={256} />
        <p class="sh-ansi-dim" style={{ marginTop: "var(--space-4)", fontSize: "var(--type-body)" }}>
          {url}
        </p>
      </div>
    </div>
  );
}
