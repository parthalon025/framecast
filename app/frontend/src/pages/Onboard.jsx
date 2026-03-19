/** @fileoverview Onboarding page — WiFi setup wizard with scan, select, connect steps. */
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { ShSkeleton } from "superhot-ui/preact";
import { ShToast } from "superhot-ui/preact";
import { navigate } from "../components/Router.jsx";

/** Map 0-100 signal percentage to 1-5 bar level. */
function signalLevel(pct) {
  if (pct <= 20) return 1;
  if (pct <= 40) return 2;
  if (pct <= 60) return 3;
  if (pct <= 80) return 4;
  return 5;
}

/** WiFi signal bars component using superhot-ui CSS. */
function SignalBars({ signal: pct }) {
  const level = signalLevel(pct);
  return (
    <span class="sh-signal-bars" data-sh-signal={level}>
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
      <span class="sh-signal-bar" />
    </span>
  );
}

/** Progress steps header showing wizard position. */
function ProgressSteps({ current, error }) {
  const steps = ["SCAN", "SELECT", "CONNECT", "DONE"];
  const currentIdx = steps.indexOf(current);
  const errorIdx = error ? steps.indexOf(error) : -1;

  return (
    <div class="sh-progress-steps" style="margin-bottom: 16px;">
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
          <div key={step} class={cls}>
            <span class="sh-progress-step-number">{idx + 1}</span>
            <span>{step}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Network list item — clickable frame with SSID, signal bars, lock icon. */
function NetworkItem({ network, onSelect }) {
  const isSecured = network.security && network.security !== "" && network.security !== "--";
  return (
    <div
      class="sh-frame sh-clickable"
      style="cursor: pointer; margin-bottom: 8px;"
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
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 0;">
        <div style="display: flex; align-items: center; gap: 10px; min-width: 0;">
          <SignalBars signal={network.signal} />
          <span style="font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {network.ssid}
          </span>
        </div>
        <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
          {isSecured && (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-label="Secured">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
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
 * Onboard — WiFi setup wizard.
 * 4 steps: SCAN → SELECT → CONNECT → DONE
 */
export function Onboard() {
  const [step, setStep] = useState("SCAN");
  const [networks, setNetworks] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState(null);
  const [password, setPassword] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [toast, setToast] = useState(null);
  const [errorStep, setErrorStep] = useState(null);
  const redirectTimer = useRef(null);

  /** Scan for WiFi networks. */
  const doScan = useCallback(() => {
    setScanning(true);
    setErrorStep(null);
    fetch("/api/wifi/scan")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setNetworks(data);
        setStep("SELECT");
      })
      .catch((err) => {
        setToast({ type: "error", message: `SCAN FAILED: ${err.message}` });
        setErrorStep("SCAN");
      })
      .finally(() => {
        setScanning(false);
      });
  }, []);

  // Auto-scan on mount
  useEffect(() => {
    doScan();
    return () => {
      if (redirectTimer.current) clearTimeout(redirectTimer.current);
    };
  }, [doScan]);

  /** Handle network selection. */
  function handleSelect(network) {
    setSelected(network);
    setPassword("");
    setErrorStep(null);
    const isSecured = network.security && network.security !== "" && network.security !== "--";
    if (isSecured) {
      setStep("CONNECT");
    } else {
      // Open network — connect immediately
      doConnect(network.ssid, "");
    }
  }

  /** Connect to selected network. */
  function doConnect(ssid, pass) {
    setConnecting(true);
    setErrorStep(null);
    setStep("CONNECT");
    fetch("/api/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid: ssid, password: pass }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setStep("DONE");
          setToast({ type: "info", message: `CONNECTED TO ${ssid}` });
          // Redirect to upload page after 3 seconds
          redirectTimer.current = setTimeout(() => {
            navigate("/");
          }, 3000);
        } else {
          setToast({ type: "error", message: data.message || "CONNECTION FAILED" });
          setErrorStep("CONNECT");
          setStep("CONNECT");
        }
      })
      .catch((err) => {
        setToast({ type: "error", message: `CONNECTION ERROR: ${err.message}` });
        setErrorStep("CONNECT");
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

  /** Go back to network list for retry. */
  function handleRetry() {
    setSelected(null);
    setPassword("");
    setErrorStep(null);
    setToast(null);
    doScan();
  }

  return (
    <div class="sh-animate-page-enter" style="padding: 12px; display: flex; flex-direction: column; gap: 12px;">
      <ProgressSteps current={step} error={errorStep} />

      {/* STEP 1: SCANNING */}
      {step === "SCAN" && (
        <div class="sh-frame" data-label="WIFI SETUP">
          {scanning ? (
            <div style="text-align: center;">
              <div class="sh-ansi-dim" style="margin-bottom: 12px;">SCANNING...</div>
              <ShSkeleton rows={4} height="2.5em" />
            </div>
          ) : (
            <div style="text-align: center;">
              <div class="sh-ansi-dim" style="margin-bottom: 12px;">PREPARING SCAN...</div>
              <ShSkeleton rows={3} height="2em" />
            </div>
          )}
        </div>
      )}

      {/* STEP 2: SELECT NETWORK */}
      {step === "SELECT" && (
        <div class="sh-frame" data-label="SELECT NETWORK">
          {networks.length === 0 ? (
            <div style="text-align: center; padding: 24px 0;">
              <div class="sh-ansi-dim">NO NETWORKS FOUND</div>
              <button
                class="sh-input"
                style="margin-top: 16px; cursor: pointer; text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;"
                onClick={doScan}
                disabled={scanning}
              >
                {scanning ? "SCANNING..." : "RESCAN"}
              </button>
            </div>
          ) : (
            <div>
              {networks.map((net) => (
                <NetworkItem
                  key={net.ssid}
                  network={net}
                  onSelect={handleSelect}
                />
              ))}
              <button
                class="sh-input"
                style="width: 100%; margin-top: 8px; cursor: pointer; text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                onClick={doScan}
                disabled={scanning}
              >
                {scanning ? "SCANNING..." : "RESCAN"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* STEP 3: CONNECT (password entry) */}
      {step === "CONNECT" && selected && (
        <div class="sh-frame" data-label={`CONNECT TO ${selected.ssid}`}>
          {connecting ? (
            <div style="text-align: center; padding: 24px 0;">
              <div style="margin-bottom: 12px;">CONNECTING...</div>
              <div class="sh-ansi-dim">{selected.ssid}</div>
              <div style="margin-top: 16px;">
                <ShSkeleton rows={1} height="2em" width="60%" />
              </div>
            </div>
          ) : (
            <form onSubmit={handleConnect} style="display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <SignalBars signal={selected.signal} />
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
              <div style="display: flex; gap: 8px;">
                <button
                  type="button"
                  class="sh-input"
                  style="flex: 1; cursor: pointer; text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-tertiary);"
                  onClick={handleRetry}
                >
                  BACK
                </button>
                <button
                  type="submit"
                  class="sh-input"
                  style="flex: 2; cursor: pointer; text-align: center; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--sh-phosphor); border-color: var(--sh-phosphor);"
                >
                  CONNECT
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* STEP 4: DONE */}
      {step === "DONE" && (
        <div class="sh-frame" data-label="CONNECTED">
          <div style="text-align: center; padding: 24px 0;">
            <div style="font-size: 1.5rem; color: var(--sh-phosphor); margin-bottom: 12px;">
              CONNECTED
            </div>
            {selected && (
              <div class="sh-ansi-dim" style="margin-bottom: 16px;">
                {selected.ssid}
              </div>
            )}
            <div class="sh-ansi-dim" style="font-size: 0.8rem;">
              REDIRECTING TO UPLOAD...
            </div>
          </div>
        </div>
      )}

      {/* TOAST */}
      {toast && (
        <div style="position: fixed; bottom: 80px; left: 12px; right: 12px; z-index: 100;">
          <ShToast
            type={toast.type}
            message={toast.message}
            duration={4000}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </div>
  );
}

export default Onboard;
