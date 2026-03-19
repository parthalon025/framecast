/** @fileoverview Update page — OTA update stub (backend in Batch 8). */
import { useState, useEffect } from "preact/hooks";

const STEPS = ["DOWNLOAD", "INSTALL", "VERIFY", "REBOOT"];

export function Update() {
  const [version, setVersion] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/status")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setVersion(data.version || "UNKNOWN"))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div style="display: flex; flex-direction: column; gap: 12px; padding: 12px;">
      <div class="sh-frame" data-label="SYSTEM UPDATE">
        <div style="display: flex; flex-direction: column; gap: 16px;">
          {/* Version display */}
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <span class="sh-label">CURRENT VERSION</span>
            <span class="sh-value">
              {error ? "UNAVAILABLE" : version || "..."}
            </span>
          </div>

          {/* Progress steps — all pending */}
          <div class="sh-progress-steps">
            {STEPS.map((step, idx) => (
              <div key={step} class="sh-progress-step">
                <span class="sh-progress-step-number">{idx + 1}</span>
                <span>{step}</span>
              </div>
            ))}
          </div>

          {/* Check button — disabled stub */}
          <button
            class="sh-input"
            disabled
            style={`
              width: 100%;
              text-align: center;
              font-weight: 700;
              text-transform: uppercase;
              letter-spacing: 0.1em;
              opacity: 0.4;
              cursor: default;
            `}
          >
            CHECK FOR UPDATES
          </button>
        </div>
      </div>
    </div>
  );
}

export default Update;
