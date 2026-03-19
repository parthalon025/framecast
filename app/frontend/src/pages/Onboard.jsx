/** @fileoverview Onboarding wizard — 4-step first-boot flow.
 *
 * Steps: WIFI -> UPLOAD -> CONFIGURE -> DONE
 * Auto-redirects on first boot when ONBOARDING_COMPLETE is not set.
 * TV display shows QR code + "SCAN TO CONFIGURE" throughout.
 * piOS voice: terse, uppercase, no conversational language.
 */
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { ShSkeleton, ShToast } from "superhot-ui/preact";
import { navigate } from "../components/Router.jsx";
import { ShDropzone } from "../components/ShDropzone.jsx";
import { fetchWithTimeout } from "../lib/fetch.js";

/** Map 0-100 signal percentage to 1-5 bar level. */
function signalLevel(pct) {
  if (pct <= 20) return 1;
  if (pct <= 40) return 2;
  if (pct <= 60) return 3;
  if (pct <= 80) return 4;
  return 5;
}

/** WiFi signal bars component using superhot-ui CSS. */
function SignalBars({ strength }) {
  const level = signalLevel(strength);
  return (
    <span
      class="sh-signal-bars"
      data-sh-signal={level}
      aria-label={`SIGNAL: ${strength}%`}
    >
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
    </span>
  );
}

/** 4-step progress indicator using sh-progress-steps. */
function WizardSteps({ currentStep, errorStep }) {
  const steps = [
    { key: "WIFI", label: "WIFI" },
    { key: "UPLOAD", label: "UPLOAD" },
    { key: "CONFIGURE", label: "CONFIGURE" },
    { key: "DONE", label: "DONE" },
  ];
  const currentIdx = steps.findIndex((step) => step.key === currentStep);
  const errorIdx = errorStep ? steps.findIndex((step) => step.key === errorStep) : -1;

  return (
    <div class="sh-progress-steps" style="margin-bottom: var(--space-4, 16px);" role="navigation" aria-label="Setup progress">
      {steps.map((step, idx) => {
        let cls = "sh-progress-step";
        if (errorIdx === idx) {
          cls += " sh-progress-step--error";
        } else if (idx < currentIdx) {
          cls += " sh-progress-step--complete";
        } else if (idx === currentIdx) {
          cls += " sh-progress-step--current";
        }
        return (
          <div key={step.key} class={cls}>
            <span class="sh-progress-step-number">{idx + 1}</span>
            <span>{step.label}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Network list item — clickable frame with SSID, signal bars, lock indicator. */
function NetworkItem({ network, onSelect }) {
  const isSecured = network.security && network.security !== "" && network.security !== "--";
  return (
    <div
      class="sh-frame sh-clickable"
      style="cursor: pointer; margin-bottom: var(--space-2, 8px); min-height: 44px;"
      onClick={() => onSelect(network)}
      role="button"
      tabIndex={0}
      onKeyDown={(evt) => {
        if (evt.key === "Enter" || evt.key === " ") {
          evt.preventDefault();
          onSelect(network);
        }
      }}
    >
      <div style="display: grid; grid-template-columns: 1fr auto; gap: var(--space-3, 12px); align-items: center; padding: 4px 0;">
        <div style="display: grid; grid-template-columns: auto 1fr; gap: var(--space-2, 8px); align-items: center; min-width: 0;">
          <SignalBars strength={network.signal} />
          <span style="font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {network.ssid}
          </span>
        </div>
        <div style="display: grid; grid-auto-flow: column; gap: var(--space-1, 4px); align-items: center;">
          {isSecured && (
            <span class="sh-ansi-dim" style="font-size: 0.75rem;" aria-label="Secured network">SECURED</span>
          )}
          <span class="sh-ansi-dim" style="font-size: 0.75rem;">
            {network.signal}%
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Onboard — first-boot onboarding wizard.
 * 4 steps: WIFI -> UPLOAD -> CONFIGURE -> DONE
 */
export function Onboard() {
  const [step, setStep] = useState("WIFI");
  const [networks, setNetworks] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState(null);
  const [password, setPassword] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [toast, setToast] = useState(null);
  const [errorStep, setErrorStep] = useState(null);
  const [uploaded, setUploaded] = useState(false);
  const [settings, setSettings] = useState(null);
  const redirectTimer = useRef(null);

  /** Check if onboarding already complete — redirect if so. */
  useEffect(() => {
    fetchWithTimeout("/api/settings")
      .then((res) => res.json())
      .then((data) => {
        setSettings(data);
        if (data.onboarding_complete) {
          navigate("/");
        }
      })
      .catch((err) => console.warn("Onboard: settings check failed", err));

    return () => {
      if (redirectTimer.current) clearTimeout(redirectTimer.current);
    };
  }, []);

  /** Auto-scan WiFi on mount. */
  useEffect(() => {
    doScan();
  }, []);

  /** Scan for WiFi networks. */
  const doScan = useCallback(() => {
    setScanning(true);
    setErrorStep(null);
    fetchWithTimeout("/api/wifi/scan")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setNetworks(data);
      })
      .catch((err) => {
        setToast({ type: "error", message: `SCAN FAULT: ${err.message}` });
        setErrorStep("WIFI");
      })
      .finally(() => {
        setScanning(false);
      });
  }, []);

  /** Handle network selection. */
  function handleSelect(network) {
    setSelected(network);
    setPassword("");
    setErrorStep(null);
    const isSecured = network.security && network.security !== "" && network.security !== "--";
    if (!isSecured) {
      doConnect(network.ssid, "");
    }
  }

  /** Connect to selected network. */
  function doConnect(ssid, pass) {
    setConnecting(true);
    setErrorStep(null);
    fetchWithTimeout("/api/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid, password: pass }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setToast({ type: "info", message: `CONNECTED: ${ssid}` });
          setStep("UPLOAD");
        } else {
          setToast({ type: "error", message: data.message || "CONNECTION FAULT" });
          setErrorStep("WIFI");
        }
      })
      .catch((err) => {
        setToast({ type: "error", message: `CONNECTION FAULT: ${err.message}` });
        setErrorStep("WIFI");
      })
      .finally(() => {
        setConnecting(false);
      });
  }

  /** Handle connect button click from password form. */
  function handleConnect(evt) {
    evt.preventDefault();
    if (!selected) return;
    doConnect(selected.ssid, password);
  }

  /** Handle first photo upload. */
  function handleUpload() {
    setUploaded(true);
    setToast({ type: "info", message: "PHOTO RECEIVED" });
  }

  /** Proceed from upload to configure step. */
  function handleUploadContinue() {
    setStep("CONFIGURE");
  }

  /** Finalize onboarding. */
  async function handleFinish() {
    // Save configure step settings
    const configUpdates = {};
    if (settings?.photo_duration) configUpdates.photo_duration = settings.photo_duration;
    if (settings?.transition_type) configUpdates.transition_type = settings.transition_type;
    configUpdates.onboarding_complete = true;

    try {
      await fetchWithTimeout("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configUpdates),
      });
    } catch (err) {
      console.warn("Onboard: save failed (non-critical)", err);
    }
    setStep("DONE");
    redirectTimer.current = setTimeout(() => {
      navigate("/");
    }, 3000);
  }

  return (
    <main class="sh-animate-page-enter fc-page" role="main">
      <WizardSteps currentStep={step} errorStep={errorStep} />

      {/* ── STEP 1: WIFI ── */}
      {step === "WIFI" && (
        <section class="sh-frame" data-label="WIFI SETUP" aria-label="WiFi setup">
          {scanning ? (
            <div style="text-align: center;">
              <div class="sh-ansi-dim" style="margin-bottom: var(--space-3, 12px);">SCANNING</div>
              <ShSkeleton rows={4} height="2.5em" />
            </div>
          ) : networks.length === 0 ? (
            <div style="text-align: center; padding: var(--space-4, 16px) 0;">
              <div class="sh-ansi-dim">NO NETWORKS FOUND</div>
              <button
                class="sh-input sh-clickable fc-btn-primary"
                onClick={doScan}
                disabled={scanning}
                style="margin-top: var(--space-4, 16px);"
              >
                RESCAN
              </button>
            </div>
          ) : selected && !connecting ? (
            /* Password entry for secured network */
            <form onSubmit={handleConnect} style="display: grid; gap: var(--space-3, 12px);">
              <div style="display: grid; grid-template-columns: auto 1fr; gap: var(--space-2, 8px); align-items: center;">
                <SignalBars strength={selected.signal} />
                <span style="font-weight: 600;">{selected.ssid}</span>
              </div>
              <input
                class="sh-input"
                type="password"
                placeholder="PASSWORD"
                value={password}
                onInput={(evt) => setPassword(evt.target.value)}
                autoFocus
                style="width: 100%;"
              />
              <div style="display: grid; grid-template-columns: 1fr 2fr; gap: var(--space-2, 8px);">
                <button
                  type="button"
                  class="sh-input sh-clickable"
                  style="text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                  onClick={() => { setSelected(null); setPassword(""); }}
                >
                  BACK
                </button>
                <button
                  type="submit"
                  class="sh-input sh-clickable fc-btn-primary"
                >
                  CONNECT
                </button>
              </div>
            </form>
          ) : connecting ? (
            <div style="text-align: center; padding: var(--space-4, 16px) 0;">
              <div style="margin-bottom: var(--space-3, 12px);">CONNECTING</div>
              <div class="sh-ansi-dim">{selected?.ssid}</div>
              <div style="margin-top: var(--space-4, 16px);">
                <ShSkeleton rows={1} height="2em" width="60%" />
              </div>
            </div>
          ) : (
            /* Network list */
            <div>
              {networks.map((net) => (
                <NetworkItem
                  key={net.ssid}
                  network={net}
                  onSelect={handleSelect}
                />
              ))}
              <button
                class="sh-input sh-clickable"
                style="width: 100%; margin-top: var(--space-2, 8px); text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                onClick={doScan}
                disabled={scanning}
              >
                RESCAN
              </button>
            </div>
          )}
        </section>
      )}

      {/* ── STEP 2: UPLOAD FIRST PHOTO ── */}
      {step === "UPLOAD" && (
        <section class="sh-frame" data-label="UPLOAD FIRST PHOTO" aria-label="Upload first photo">
          <div style="display: grid; gap: var(--space-4, 16px); text-align: center;">
            <div class="sh-label" style="font-size: 1rem;">
              {uploaded ? "PHOTO RECEIVED" : "UPLOAD FIRST PHOTO"}
            </div>
            <div class="sh-ansi-dim">
              {uploaded
                ? "ADD MORE OR CONTINUE TO CONFIGURE"
                : "YOUR FRAME NEEDS AT LEAST ONE PHOTO"}
            </div>
            <ShDropzone onUpload={handleUpload} />
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2, 8px);">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                onClick={() => setStep("WIFI")}
              >
                BACK
              </button>
              <button
                class="sh-input sh-clickable fc-btn-primary"
                onClick={handleUploadContinue}
                disabled={!uploaded}
                style={`opacity: ${uploaded ? 1 : 0.4};`}
              >
                CONTINUE
              </button>
            </div>
          </div>
        </section>
      )}

      {/* ── STEP 3: CONFIGURE ── */}
      {step === "CONFIGURE" && (
        <section class="sh-frame" data-label="CONFIGURE" aria-label="Configure basic settings">
          <div style="display: grid; gap: var(--space-3, 12px);">
            <div class="sh-label" style="text-align: center; font-size: 1rem;">
              BASIC CONFIGURATION
            </div>

            <div class="fc-setting-row">
              <span class="sh-label" style="white-space: nowrap;">DURATION</span>
              <div style="display: grid; grid-template-columns: 1fr auto; gap: var(--space-2, 8px); align-items: center;">
                <input
                  class="sh-input"
                  type="range"
                  min="5"
                  max="60"
                  step="1"
                  value={settings?.photo_duration || 10}
                  onInput={(evt) => setSettings((prev) => ({ ...prev, photo_duration: parseInt(evt.target.value, 10) }))}
                  aria-label="Slideshow duration in seconds"
                />
                <span class="sh-value" style="min-width: 32px; text-align: right;">
                  {settings?.photo_duration || 10}s
                </span>
              </div>
            </div>

            <div class="fc-setting-row">
              <span class="sh-label" style="white-space: nowrap;">TRANSITION</span>
              <select
                class="sh-select"
                value={settings?.transition_type || "fade"}
                onChange={(evt) => setSettings((prev) => ({ ...prev, transition_type: evt.target.value }))}
              >
                {["fade", "slide", "zoom", "dissolve", "none"].map((opt) => (
                  <option key={opt} value={opt}>{opt.toUpperCase()}</option>
                ))}
              </select>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2, 8px); margin-top: var(--space-2, 8px);">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                onClick={() => setStep("UPLOAD")}
              >
                BACK
              </button>
              <button
                class="sh-input sh-clickable fc-btn-primary"
                onClick={handleFinish}
              >
                FINISH
              </button>
            </div>
          </div>
        </section>
      )}

      {/* ── STEP 4: DONE ── */}
      {step === "DONE" && (
        <section class="sh-frame" data-label="COMPLETE" aria-label="Setup complete">
          <div style="text-align: center; padding: var(--space-6, 32px) 0;">
            <div style="font-size: 1.5rem; color: var(--sh-phosphor); margin-bottom: var(--space-3, 12px);">
              FRAME READY
            </div>
            <div class="sh-ansi-dim" style="font-size: 0.8rem;">
              REDIRECTING TO SLIDESHOW
            </div>
          </div>
        </section>
      )}

      {/* ── TOAST ── */}
      {toast && (
        <div class="fc-toast-container">
          <ShToast
            type={toast.type}
            message={toast.message}
            duration={4000}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </main>
  );
}

export default Onboard;
