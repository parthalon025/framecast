/** @fileoverview PinGate — full-screen PIN overlay for phone UI auth.
 *
 * Shows when any API call returns 401 with `needs_pin: true`.
 * Submits PIN to POST /api/auth/verify, dismisses on success.
 * piOS aesthetic: monospace, uppercase, green phosphor.
 */
import { signal } from "@preact/signals";
import { useState, useCallback, useRef, useEffect } from "preact/hooks";
import { ShToast } from "superhot-ui/preact";

/** Global signal: when true, the PIN gate overlay is shown. */
export const pinRequired = signal(false);

/** Stash the original request so we can retry after auth. */
let _pendingRetry = null;

/**
 * Wrap fetch with automatic PIN gate trigger.
 * If a response comes back 401 with needs_pin, show the gate.
 * After auth, the caller can retry by checking pinRequired.
 *
 * @param {string} url
 * @param {RequestInit} [opts]
 * @returns {Promise<Response>}
 */
export async function authedFetch(url, opts) {
  const resp = await fetch(url, opts);
  if (resp.status === 401) {
    try {
      const body = await resp.clone().json();
      if (body && body.needs_pin) {
        _pendingRetry = { url, opts };
        pinRequired.value = true;
        // Return the original response -- caller should check pinRequired
        return resp;
      }
    } catch (_ignore) {
      // Not JSON 401, pass through
    }
  }
  return resp;
}

/**
 * PinGate — full-screen overlay with 4-digit PIN input.
 * Renders only when pinRequired signal is true.
 */
export function PinGate() {
  const [pinValue, setPinValue] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [toast, setToast] = useState(null);
  const [pinLength, setPinLength] = useState(4);
  const dismissTimer = useRef(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((res) => res.json())
      .then((data) => { if (data.pin_length) setPinLength(data.pin_length); })
      .catch((err) => console.warn("PinGate: failed to fetch pin length", err));
    return () => {
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
    };
  }, []);

  const handleVerify = useCallback(async () => {
    if (pinValue.length !== pinLength || verifying) return;

    setVerifying(true);
    try {
      const resp = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: pinValue }),
      });

      if (resp.ok) {
        setToast({ type: "info", message: "AUTHORIZED" });
        setPinValue("");
        // Dismiss the overlay after brief feedback
        if (dismissTimer.current) clearTimeout(dismissTimer.current);
        dismissTimer.current = setTimeout(() => {
          pinRequired.value = false;
          setToast(null);
          // Retry the original request if caller is watching
          if (_pendingRetry) {
            _pendingRetry = null;
          }
        }, 600);
      } else {
        setToast({ type: "error", message: "INVALID PIN" });
        setPinValue("");
      }
    } catch (err) {
      setToast({ type: "error", message: "NETWORK ERROR" });
    } finally {
      setVerifying(false);
    }
  }, [pinValue, verifying]);

  const handleInput = useCallback((evt) => {
    const val = evt.target.value.replace(/\D/g, "").slice(0, pinLength);
    setPinValue(val);
  }, [pinLength]);

  const handleKeyDown = useCallback(
    (evt) => {
      if (evt.key === "Enter") {
        handleVerify();
      }
    },
    [handleVerify],
  );

  if (!pinRequired.value) return null;

  return (
    <div
      style={`
        position: fixed; inset: 0; z-index: 9999;
        background: var(--surface-void, #000);
        display: flex; align-items: center; justify-content: center;
      `}
    >
      <div
        class="sh-frame"
        data-label="ACCESS PIN"
        style="width: 280px; text-align: center;"
      >
        <div
          style={`
            display: flex; flex-direction: column; align-items: center;
            gap: 16px; padding: 24px 16px;
          `}
        >
          <span
            class="sh-label"
            style="font-size: 0.85rem; letter-spacing: 0.15em;"
          >
            ENTER ACCESS PIN
          </span>

          <input
            class="sh-input"
            type="tel"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={String(pinLength)}
            value={pinValue}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            autoFocus
            style={`
              width: 140px; text-align: center;
              font-size: 2rem; letter-spacing: 0.5em;
              font-family: var(--font-mono, monospace);
            `}
            placeholder="----"
          />

          <button
            class="sh-input"
            onClick={handleVerify}
            disabled={pinValue.length !== pinLength || verifying}
            style={`
              width: 100%; cursor: pointer;
              text-align: center; font-weight: 700;
              text-transform: uppercase; letter-spacing: 0.1em;
              opacity: ${pinValue.length === pinLength && !verifying ? 1 : 0.4};
              color: ${pinValue.length === pinLength ? "var(--sh-phosphor)" : "var(--text-tertiary)"};
              border-color: ${pinValue.length === pinLength ? "var(--sh-phosphor)" : "var(--border-subtle)"};
            `}
          >
            {verifying ? "VERIFYING..." : "VERIFY"}
          </button>
        </div>
      </div>

      {toast && (
        <div
          style="position: fixed; bottom: 24px; left: 12px; right: 12px; z-index: 10000;"
        >
          <ShToast
            type={toast.type}
            message={toast.message}
            duration={3000}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </div>
  );
}
