/** @fileoverview Setup screen — shown when no WiFi is configured (AP mode). */
import { useEffect } from "preact/hooks";
import { signal } from "@preact/signals";
import { ShPageBanner } from "superhot-ui/preact";
import { QRCode } from "../components/QRCode.jsx";

/** AP SSID fetched from /api/wifi/status, falls back to generic. */
const apSsid = signal("FrameCast-XXXX");

/**
 * Setup — guides the user through WiFi onboarding in AP mode.
 * PIN display is handled by PinDisplay in DisplayRouter — not duplicated here.
 */
export function Setup() {
  const apUrl = "http://192.168.4.1:8080";

  useEffect(() => {
    fetch("/api/wifi/status")
      .then((res) => res.json())
      .then((data) => {
        if (data.ap_ssid) {
          apSsid.value = data.ap_ssid;
        }
      })
      .catch((err) => {
        console.warn("Setup: wifi status fetch failed, will retry", err);
        setTimeout(() => {
            fetch("/api/wifi/status")
                .then((res) => res.json())
                .then((data) => { if (data.ap_ssid) apSsid.value = data.ap_ssid; })
                .catch(() => {});
        }, 3000);
      });
  }, []);

  return (
    <div class="boot-screen" style={{ alignItems: "center", textAlign: "center" }}>
      <ShPageBanner namespace="FRAMECAST" page="SETUP" />

      <div class="sh-frame" data-label="SETUP REQUIRED" style={{ maxWidth: "600px", width: "100%" }}>
        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          1. CONNECT TO WIFI NETWORK:
        </p>
        <p style={{ fontSize: "var(--type-heading)", color: "var(--sh-phosphor)", marginBottom: "var(--space-6)" }}>
          {apSsid.value}
        </p>

        <p class="sh-label" style={{ marginBottom: "var(--space-4)" }}>
          2. SCAN OR OPEN:
        </p>
        <QRCode url={apUrl} size={200} />
        <p class="sh-ansi-dim" style={{ marginTop: "var(--space-3)" }}>
          {apUrl}
        </p>
      </div>
    </div>
  );
}
