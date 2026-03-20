/** @fileoverview Update page — OTA update check, install, and reboot flow. */
import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import { ShToast } from "superhot-ui/preact";
import { bootSequence } from "superhot-ui";
import { authedFetch } from "../components/PinGate.jsx";

const STEPS = ["DOWNLOAD", "INSTALL", "VERIFY", "REBOOT"];

/** Map step index to progress-step CSS modifier. */
function stepClass(idx, activeIdx, errorIdx) {
  let cls = "sh-progress-step";
  if (errorIdx >= 0 && idx === errorIdx) {
    cls += " sh-progress-step--error";
  } else if (idx < activeIdx) {
    cls += " sh-progress-step--complete";
  } else if (idx === activeIdx) {
    cls += " sh-progress-step--current";
  }
  return cls;
}

/** ASCII progress bar using block chars. */
function AsciiBar({ percent }) {
  const filled = Math.floor(percent / 5);
  const empty = 20 - filled;
  return (
    <span class="sh-progress" style="font-family: var(--font-mono, monospace); letter-spacing: 0.05em;">
      {"\u2593".repeat(filled)}{"\u2591".repeat(empty)}
    </span>
  );
}

export function Update() {
  const [version, setVersion] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  // Update state
  const [checking, setChecking] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [activeStep, setActiveStep] = useState(-1);
  const [errorStep, setErrorStep] = useState(-1);
  const [progress, setProgress] = useState(0);
  const [rebooting, setRebooting] = useState(false);

  const bootRef = useRef(null);
  const sseRef = useRef(null);
  const progressTimer = useRef(null);
  const activeStepRef = useRef(-1);

  // Load current version on mount
  useEffect(() => {
    fetch("/api/status")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setVersion(data.version || "UNKNOWN"))
      .catch((err) => setError(err.message));
  }, []);

  // SSE listener for reboot event
  useEffect(() => {
    const evtSource = new EventSource("/api/events");
    sseRef.current = evtSource;

    evtSource.onerror = () => {
      console.warn("Update: SSE connection lost");
    };

    evtSource.addEventListener("update:rebooting", (evt) => {
      setActiveStep(3); // REBOOT
      setProgress(100);
      setRebooting(true);
    });

    return () => {
      evtSource.close();
    };
  }, []);

  // Boot animation when rebooting
  useEffect(() => {
    if (!rebooting || !bootRef.current) return;
    const cleanup = bootSequence(bootRef.current, [
      "piOS v1.0",
      "FRAMECAST UPDATE SYSTEM",
      "APPLYING UPDATE...",
      "RESTARTING SERVICES...",
      "REBOOTING...",
    ]);
    return cleanup;
  }, [rebooting]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (progressTimer.current) clearInterval(progressTimer.current);
    };
  }, []);

  /** Check for updates via API. */
  const handleCheck = useCallback(async () => {
    setChecking(true);
    setUpdateInfo(null);
    setErrorStep(-1);
    setActiveStep(-1);

    try {
      const res = await authedFetch("/api/update/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.needs_pin) return; // PinGate handles it
        throw new Error(body.error || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setUpdateInfo(data);

      if (data.available) {
        setToast({ type: "info", message: `UPDATE AVAILABLE: v${data.latest}` });
      } else {
        setToast({ type: "info", message: "SYSTEM IS UP TO DATE" });
      }
    } catch (err) {
      setToast({ type: "error", message: `CHECK FAILED: ${err.message}` });
    } finally {
      setChecking(false);
    }
  }, []);

  /** Install the update. */
  const handleInstall = useCallback(async () => {
    if (!updateInfo || !updateInfo.available) return;

    const tag = `v${updateInfo.latest}`;
    setInstalling(true);
    setErrorStep(-1);
    activeStepRef.current = 0;
    setActiveStep(0); // DOWNLOAD
    setProgress(0);

    // Simulate progress during fetch + install
    let pct = 0;
    progressTimer.current = setInterval(() => {
      pct = Math.min(pct + 2, 85);
      setProgress(pct);
    }, 200);

    try {
      // Step 0: DOWNLOAD (fetch triggers git fetch on server)
      const res = await authedFetch("/api/update/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag }),
      });

      clearInterval(progressTimer.current);
      progressTimer.current = null;

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.needs_pin) return;
        throw new Error(body.error || `HTTP ${res.status}`);
      }

      const data = await res.json();

      if (!data.success) {
        throw new Error(data.message || "UPDATE FAILED");
      }

      // Step 1: INSTALL
      activeStepRef.current = 1;
      setActiveStep(1);
      setProgress(90);

      // Step 2: VERIFY
      setTimeout(() => {
        activeStepRef.current = 2;
        setActiveStep(2);
        setProgress(95);
      }, 1000);

      // SSE will trigger REBOOT step via update:rebooting event

    } catch (err) {
      clearInterval(progressTimer.current);
      progressTimer.current = null;
      setErrorStep(activeStepRef.current >= 0 ? activeStepRef.current : 0);
      setInstalling(false);
      setToast({ type: "error", message: err.message });
    }
  }, [updateInfo]);

  // Show boot animation during reboot
  if (rebooting) {
    return (
      <div class="boot-screen">
        <div ref={bootRef} class="sh-boot-container" />
      </div>
    );
  }

  return (
    <div class="fc-page">
      <div class="sh-frame" data-label="SYSTEM UPDATE">
        <div style="display: flex; flex-direction: column; gap: 16px;">
          {/* Version display */}
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <span class="sh-label">CURRENT VERSION</span>
            <span class="sh-value">
              {error ? "UNAVAILABLE" : version ? `v${version}` : "..."}
            </span>
          </div>

          {/* Latest version (after check) */}
          {updateInfo && (
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span class="sh-label">LATEST VERSION</span>
              <span
                class="sh-value"
                style={updateInfo.available ? "color: var(--sh-phosphor);" : ""}
              >
                v{updateInfo.latest}
              </span>
            </div>
          )}

          {/* Progress steps */}
          <div class="sh-progress-steps">
            {STEPS.map((step, idx) => (
              <div key={step} class={stepClass(idx, activeStep, errorStep)}>
                <span class="sh-progress-step-number">{idx + 1}</span>
                <span>{step}</span>
              </div>
            ))}
          </div>

          {/* ASCII progress bar (visible during install) */}
          {installing && (
            <div style="text-align: center;">
              <AsciiBar percent={progress} />
              <div class="sh-ansi-dim" style="margin-top: 4px; font-size: 0.8rem;">
                {STEPS[activeStep] || "PREPARING"}...
              </div>
            </div>
          )}

          {/* Action buttons */}
          {!installing && !updateInfo?.available && (
            <button
              class="sh-input"
              onClick={handleCheck}
              disabled={checking}
              style={`
                width: 100%;
                text-align: center;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                cursor: ${checking ? "default" : "pointer"};
                opacity: ${checking ? 0.4 : 1};
                color: ${checking ? "var(--text-tertiary)" : "var(--sh-phosphor)"};
                border-color: ${checking ? "var(--border-subtle)" : "var(--sh-phosphor)"};
              `}
            >
              {checking ? "STANDBY" : "CHECK FOR UPDATES"}
            </button>
          )}

          {!installing && updateInfo?.available && (
            <button
              class="sh-input"
              onClick={handleInstall}
              style={`
                width: 100%;
                text-align: center;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                cursor: pointer;
                color: var(--sh-phosphor);
                border-color: var(--sh-phosphor);
              `}
            >
              INSTALL UPDATE v{updateInfo.latest}
            </button>
          )}

          {/* Retry button after error */}
          {errorStep >= 0 && !installing && (
            <button
              class="sh-input"
              onClick={handleCheck}
              style={`
                width: 100%;
                text-align: center;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                cursor: pointer;
                color: var(--status-critical, #ff4444);
                border-color: var(--status-critical, #ff4444);
              `}
            >
              RETRY
            </button>
          )}
        </div>
      </div>

      {/* Toast */}
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

export default Update;
