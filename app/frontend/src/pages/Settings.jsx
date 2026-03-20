/** @fileoverview Settings page — complete configuration panel with collapsible sections.
 *
 * Sections: DISPLAY, SECURITY, SCHEDULE, NETWORK (read-only), SYSTEM.
 * All forms use superhot-ui terminal form elements (.sh-input, .sh-select, .sh-toggle).
 * piOS voice throughout: STANDBY, FAULT, CONFIRM, etc.
 */
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { ShCollapsible, ShModal, ShToast, ShSkeleton } from "superhot-ui/preact";
import { applyThreshold } from "superhot-ui";
import { fetchWithTimeout } from "../lib/fetch.js";
import { navigate } from "../components/Router.jsx";

const TRANSITION_OPTIONS = ["fade", "slide", "zoom", "dissolve", "none"];
const TRANSITION_MODE_OPTIONS = [
  { value: "single", label: "SINGLE" },
  { value: "random", label: "RANDOM" },
];
const ORDER_OPTIONS = [
  { value: "shuffle", label: "SHUFFLE" },
  { value: "newest", label: "NEWEST FIRST" },
  { value: "oldest", label: "OLDEST FIRST" },
  { value: "alphabetical", label: "ALPHABETICAL" },
];
const KENBURNS_OPTIONS = [
  { value: "subtle", label: "SUBTLE" },
  { value: "moderate", label: "MODERATE" },
  { value: "dramatic", label: "DRAMATIC" },
];
const MAP_OVERLAY_OPTIONS = [
  { value: "off", label: "OFF" },
  { value: "top-left", label: "TOP LEFT" },
  { value: "top-right", label: "TOP RIGHT" },
  { value: "bottom-left", label: "BOTTOM LEFT" },
  { value: "bottom-right", label: "BOTTOM RIGHT" },
];
const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

export function Settings() {
  const [settings, setSettings] = useState(null);
  const [dirty, setDirty] = useState({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [wifiStatus, setWifiStatus] = useState(null);
  const [pin, setPin] = useState(null);
  const [restartOpen, setRestartOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [regeneratingPin, setRegeneratingPin] = useState(false);
  const storageBarRef = useRef(null);

  /** Load settings + status + wifi info on mount. */
  useEffect(() => {
    loadSettings();
    loadStatus();
    loadWifiStatus();
  }, []);

  /** Apply threshold color to storage bar when status changes. */
  useEffect(() => {
    if (storageBarRef.current && status && status.disk) {
      applyThreshold(storageBarRef.current, status.disk.percent);
    }
  }, [status]);

  function loadSettings() {
    setError(null);
    fetchWithTimeout("/api/settings")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setSettings(data))
      .catch((err) => setError(err.message));
  }

  function loadStatus() {
    fetchWithTimeout("/api/status")
      .then((res) => res.json())
      .then((data) => {
        setStatus(data);
        if (data.access_pin) setPin(data.access_pin);
      })
      .catch((err) => console.warn("Settings: status load failed", err));
  }

  function loadWifiStatus() {
    fetchWithTimeout("/api/wifi/status")
      .then((res) => res.json())
      .then((data) => setWifiStatus(data))
      .catch((err) => console.warn("Settings: wifi status load failed", err));
  }

  const update = useCallback((key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty((prev) => ({ ...prev, [key]: true }));
  }, []);

  const save = useCallback(async () => {
    if (!settings) return;
    const changed = {};
    for (const key of Object.keys(dirty)) {
      changed[key] = settings[key];
    }
    if (Object.keys(changed).length === 0) return;

    setSaving(true);
    try {
      const res = await fetchWithTimeout("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changed),
      });
      const body = await res.json();
      if (!res.ok) {
        setToast({ type: "error", message: body.error || "SAVE FAULT" });
        return;
      }
      setSettings(body.settings);
      setDirty({});
      setToast({ type: "info", message: "SETTINGS SAVED" });
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setSaving(false);
    }
  }, [settings, dirty]);

  async function handleRestart() {
    setRestarting(true);
    setRestartOpen(false);
    try {
      const res = await fetchWithTimeout("/api/restart-slideshow", {
        method: "POST",
      });
      if (res.ok) {
        setToast({ type: "info", message: "SERVICES RESTARTED" });
      } else {
        setToast({ type: "error", message: "RESTART FAULT" });
      }
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setRestarting(false);
    }
  }

  async function handleRegeneratePin() {
    setRegeneratingPin(true);
    try {
      const res = await fetchWithTimeout("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regenerate_pin: true }),
      });
      if (res.ok) {
        setToast({ type: "info", message: "PIN REGENERATED" });
        loadStatus();
      } else {
        setToast({ type: "error", message: "REGENERATE FAULT" });
      }
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setRegeneratingPin(false);
    }
  }

  /* Error state with retry */
  if (error) {
    return (
      <main class="fc-page" role="main">
        <div class="sh-frame" data-label="SETTINGS" role="alert">
          <div class="fc-settings-section">
            <span class="sh-label" style="color: var(--status-critical, #ff4444);">
              LOAD FAULT: {error}
            </span>
            <button
              class="sh-input sh-clickable fc-btn-primary"
              onClick={loadSettings}
              style="margin-top: var(--space-4, 16px);"
            >
              RETRY
            </button>
          </div>
        </div>
      </main>
    );
  }

  /* Loading state */
  if (!settings) {
    return (
      <main class="fc-page" role="main">
        <div class="sh-frame" data-label="SETTINGS">
          <div class="fc-settings-section">
            <span class="sh-label">STANDBY</span>
            <ShSkeleton rows={6} height="2.5em" />
          </div>
        </div>
      </main>
    );
  }

  const hasDirty = Object.keys(dirty).length > 0;
  const diskPct = status?.disk?.percent || 0;
  const version = status?.version || "UNKNOWN";
  const sseClients = status?.sse_clients || 0;

  return (
    <main class="sh-animate-page-enter fc-page" role="main">
      {/* ── DISPLAY ── */}
      <section aria-label="Display settings">
        <ShCollapsible title="DISPLAY" defaultOpen={true}>
          <div class="fc-settings-section">
            <SettingRow label="DURATION" suffix="s">
              <input
                class="sh-input"
                type="range"
                min="5"
                max="60"
                step="1"
                value={settings.photo_duration}
                onInput={(evt) => update("photo_duration", parseInt(evt.target.value, 10))}
                aria-label="Slideshow duration in seconds"
              />
              <span class="sh-value fc-range-value">{settings.photo_duration}s</span>
            </SettingRow>

            <SettingRow label="TRANSITION MODE">
              <select
                class="sh-select"
                value={settings.transition_mode || "single"}
                onChange={(evt) => update("transition_mode", evt.target.value)}
              >
                {TRANSITION_MODE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </SettingRow>

            {(settings.transition_mode || "single") === "single" && (
              <SettingRow label="TRANSITION">
                <select
                  class="sh-select"
                  value={settings.transition_type}
                  onChange={(evt) => update("transition_type", evt.target.value)}
                >
                  {TRANSITION_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>{opt.toUpperCase()}</option>
                  ))}
                </select>
              </SettingRow>
            )}

            <SettingRow label="TRANSITION SPEED" suffix="ms">
              <input
                class="sh-input"
                type="range"
                min="500"
                max="3000"
                step="100"
                value={settings.transition_duration_ms || 1000}
                onInput={(evt) => update("transition_duration_ms", parseInt(evt.target.value, 10))}
                aria-label="Transition duration in milliseconds"
              />
              <span class="sh-value fc-range-value">{settings.transition_duration_ms || 1000}ms</span>
            </SettingRow>

            <SettingRow label="PHOTO ORDER">
              <select
                class="sh-select"
                value={settings.photo_order}
                onChange={(evt) => update("photo_order", evt.target.value)}
              >
                {ORDER_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </SettingRow>

            <SettingRow label="KEN BURNS">
              <select
                class="sh-select"
                value={settings.kenburns_intensity || "moderate"}
                onChange={(evt) => update("kenburns_intensity", evt.target.value)}
              >
                {KENBURNS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </SettingRow>

            <SettingRow label="MAP OVERLAY">
              <select
                class="sh-select"
                value={settings.map_overlay_position || "off"}
                onChange={(evt) => update("map_overlay_position", evt.target.value)}
              >
                {MAP_OVERLAY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </SettingRow>

            {(settings.map_overlay_position || "off") !== "off" && (
              <>
                <SettingRow label="OVERLAY OPACITY">
                  <input
                    class="sh-input"
                    type="range"
                    min="0.3"
                    max="1"
                    step="0.05"
                    value={settings.map_overlay_opacity != null ? settings.map_overlay_opacity : 0.75}
                    onInput={(evt) => update("map_overlay_opacity", parseFloat(evt.target.value))}
                    aria-label="Map overlay opacity"
                  />
                  <span class="sh-value fc-range-value">
                    {(settings.map_overlay_opacity != null ? settings.map_overlay_opacity : 0.75).toFixed(2)}
                  </span>
                </SettingRow>

                <SettingRow label="OVERLAY SIZE" suffix="px">
                  <input
                    class="sh-input"
                    type="range"
                    min="80"
                    max="300"
                    step="10"
                    value={settings.map_overlay_size || 180}
                    onInput={(evt) => update("map_overlay_size", parseInt(evt.target.value, 10))}
                    aria-label="Map overlay size in pixels"
                  />
                  <span class="sh-value fc-range-value">{settings.map_overlay_size || 180}px</span>
                </SettingRow>

                <SettingRow label="MAP ZOOM">
                  <input
                    class="sh-input"
                    type="range"
                    min="8"
                    max="14"
                    step="1"
                    value={settings.map_overlay_zoom || 11}
                    onInput={(evt) => update("map_overlay_zoom", parseInt(evt.target.value, 10))}
                    aria-label="Map tile zoom level"
                  />
                  <span class="sh-value fc-range-value">{settings.map_overlay_zoom || 11}</span>
                </SettingRow>

                <SettingRow label="CORNER OFFSET" suffix="px">
                  <input
                    class="sh-input"
                    type="range"
                    min="8"
                    max="64"
                    step="4"
                    value={settings.map_overlay_offset != null ? settings.map_overlay_offset : 24}
                    onInput={(evt) => update("map_overlay_offset", parseInt(evt.target.value, 10))}
                    aria-label="Map overlay corner offset in pixels"
                  />
                  <span class="sh-value fc-range-value">
                    {settings.map_overlay_offset != null ? settings.map_overlay_offset : 24}px
                  </span>
                </SettingRow>

                <SettingRow label="BORDER RADIUS" suffix="px">
                  <input
                    class="sh-input"
                    type="range"
                    min="0"
                    max="20"
                    step="1"
                    value={settings.map_overlay_radius != null ? settings.map_overlay_radius : 6}
                    onInput={(evt) => update("map_overlay_radius", parseInt(evt.target.value, 10))}
                    aria-label="Map overlay border radius"
                  />
                  <span class="sh-value fc-range-value">
                    {settings.map_overlay_radius != null ? settings.map_overlay_radius : 6}px
                  </span>
                </SettingRow>

                <SettingRow label="DOT SIZE" suffix="px">
                  <input
                    class="sh-input"
                    type="range"
                    min="4"
                    max="16"
                    step="1"
                    value={settings.map_overlay_dot_size || 8}
                    onInput={(evt) => update("map_overlay_dot_size", parseInt(evt.target.value, 10))}
                    aria-label="Location dot size"
                  />
                  <span class="sh-value fc-range-value">{settings.map_overlay_dot_size || 8}px</span>
                </SettingRow>

                <SettingRow label="DOT PULSE">
                  <Toggle
                    on={settings.map_overlay_dot_pulse !== false}
                    onToggle={(val) => update("map_overlay_dot_pulse", val)}
                  />
                </SettingRow>

                <SettingRow label="PHOSPHOR BORDER">
                  <Toggle
                    on={settings.map_overlay_border !== false}
                    onToggle={(val) => update("map_overlay_border", val)}
                  />
                </SettingRow>
              </>
            )}
          </div>
        </ShCollapsible>
      </section>

      {/* ── SECURITY ── */}
      <section aria-label="Security settings">
        <ShCollapsible title="SECURITY" defaultOpen={false}>
          <div class="fc-settings-section">
            <SettingRow label="ACCESS PIN">
              <span class="sh-value" style="font-family: var(--font-mono, monospace); letter-spacing: 0.3em;">
                {pin || "----"}
              </span>
            </SettingRow>

            <SettingRow label="REGENERATE PIN">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={handleRegeneratePin}
                disabled={regeneratingPin}
              >
                {regeneratingPin ? "STANDBY" : "REGENERATE"}
              </button>
            </SettingRow>

            <SettingRow label="PIN LENGTH">
              <Toggle
                on={(settings.pin_length || 4) === 6}
                onToggle={(val) => update("pin_length", val ? 6 : 4)}
                labelOn="6"
                labelOff="4"
              />
            </SettingRow>
          </div>
        </ShCollapsible>
      </section>

      {/* ── SCHEDULE ── */}
      <section aria-label="Schedule settings">
        <ShCollapsible title="SCHEDULE" defaultOpen={false}>
          <div class="fc-settings-section">
            <SettingRow label="DISPLAY SCHEDULE">
              <Toggle
                on={settings.hdmi_schedule_enabled}
                onToggle={(val) => update("hdmi_schedule_enabled", val)}
              />
            </SettingRow>

            {settings.hdmi_schedule_enabled && (
              <>
                <SettingRow label="ON TIME">
                  <input
                    class="sh-input"
                    type="time"
                    value={settings.hdmi_on_time || "08:00"}
                    onInput={(evt) => update("hdmi_on_time", evt.target.value)}
                    aria-label="Display on time"
                  />
                </SettingRow>

                <SettingRow label="OFF TIME">
                  <input
                    class="sh-input"
                    type="time"
                    value={settings.hdmi_off_time || "22:00"}
                    onInput={(evt) => update("hdmi_off_time", evt.target.value)}
                    aria-label="Display off time"
                  />
                </SettingRow>

                <div class="fc-setting-row">
                  <span class="sh-label" style="white-space: nowrap;">DAYS</span>
                  <div class="fc-day-grid">
                    {DAYS.map((day, idx) => {
                      const activeDays = settings.schedule_days || [0, 1, 2, 3, 4, 5, 6];
                      const isActive = activeDays.includes(idx);
                      return (
                        <button
                          key={day}
                          class={`sh-input fc-day-btn${isActive ? " fc-day-btn--active" : ""}`}
                          onClick={() => {
                            const next = isActive
                              ? activeDays.filter((dayIdx) => dayIdx !== idx)
                              : [...activeDays, idx].sort();
                            update("schedule_days", next);
                          }}
                          aria-pressed={isActive}
                          aria-label={day}
                        >
                          {day}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}

            <SettingRow label="DISPLAY POWER">
              <Toggle
                on={settings.display_on !== false}
                onToggle={(val) => update("display_on", val)}
              />
            </SettingRow>
          </div>
        </ShCollapsible>
      </section>

      {/* ── NETWORK (read-only) ── */}
      <section aria-label="Network information">
        <ShCollapsible title="NETWORK" defaultOpen={false}>
          <div class="fc-settings-section">
            <SettingRow label="WIFI">
              <span class="sh-value">
                {wifiStatus ? (wifiStatus.ssid || "NOT CONNECTED") : "STANDBY"}
              </span>
            </SettingRow>

            <SettingRow label="IP ADDRESS">
              <span class="sh-value">
                {status?.ip_address || "UNKNOWN"}
              </span>
            </SettingRow>

            <SettingRow label="HOSTNAME">
              <span class="sh-value">
                {status?.hostname || "UNKNOWN"}
              </span>
            </SettingRow>

            <SettingRow label="SSE CLIENTS">
              <span class="sh-value">{sseClients}</span>
            </SettingRow>
          </div>
        </ShCollapsible>
      </section>

      {/* ── SYSTEM ── */}
      <section aria-label="System settings">
        <ShCollapsible title="SYSTEM" defaultOpen={false}>
          <div class="fc-settings-section">
            <SettingRow label="STORAGE">
              <div style="display: grid; gap: var(--space-2, 8px); width: 100%; max-width: 200px;">
                <div
                  class="sh-threshold-bar"
                  style={`--sh-fill: ${diskPct}`}
                  ref={storageBarRef}
                  role="meter"
                  aria-label="Storage usage"
                  aria-valuenow={diskPct}
                  aria-valuemin="0"
                  aria-valuemax="100"
                />
                <span class="sh-ansi-dim" style="font-size: 0.75rem;">
                  {status?.disk
                    ? `${status.disk.used} / ${status.disk.total}`
                    : "STANDBY"}
                </span>
              </div>
            </SettingRow>

            <SettingRow label="VERSION">
              <span class="sh-value">{version}</span>
            </SettingRow>

            <SettingRow label="AUTO-UPDATE">
              <Toggle
                on={settings.auto_update_enabled}
                onToggle={(val) => update("auto_update_enabled", val)}
              />
            </SettingRow>

            <SettingRow label="UPLOAD LIMIT">
              <div style="display: grid; grid-template-columns: 1fr auto; gap: var(--space-2, 8px); align-items: center; width: 100%; max-width: 160px;">
                <input
                  class="sh-input"
                  type="number"
                  min="1"
                  value={settings.max_upload_mb}
                  onInput={(evt) => update("max_upload_mb", parseInt(evt.target.value, 10) || 1)}
                  aria-label="Upload limit in megabytes"
                />
                <span class="sh-ansi-dim">MB</span>
              </div>
            </SettingRow>

            <SettingRow label="RESTART SERVICES">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={() => setRestartOpen(true)}
                disabled={restarting}
              >
                {restarting ? "STANDBY" : "RESTART"}
              </button>
            </SettingRow>

            <SettingRow label="STATS">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={() => navigate("/stats")}
              >
                VIEW STATS
              </button>
            </SettingRow>

            <SettingRow label="UPDATES">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={() => navigate("/update")}
              >
                SYSTEM UPDATE
              </button>
            </SettingRow>
          </div>
        </ShCollapsible>
      </section>

      {/* ── SAVE BAR ── */}
      <button
        class="sh-input fc-btn-primary"
        disabled={!hasDirty || saving}
        onClick={save}
        style={`opacity: ${hasDirty ? 1 : 0.4};`}
      >
        {saving ? "SAVING" : "SAVE"}
      </button>

      {/* ── RESTART CONFIRMATION MODAL ── */}
      <ShModal
        open={restartOpen}
        title="CONFIRM: RESTART SERVICES?"
        body="SLIDESHOW WILL INTERRUPT BRIEFLY."
        confirmLabel="RESTART"
        cancelLabel="CANCEL"
        onConfirm={handleRestart}
        onCancel={() => setRestartOpen(false)}
      />

      {/* ── TOAST ── */}
      {toast && (
        <div class="fc-toast-container">
          <ShToast
            type={toast.type}
            message={toast.message}
            duration={3000}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </main>
  );
}

/** Row with UPPERCASE label on left, control on right. */
function SettingRow({ label, suffix, children }) {
  return (
    <div class="fc-setting-row">
      <span class="sh-label" style="white-space: nowrap;">
        {label}{suffix ? ` (${suffix.toUpperCase()})` : ""}
      </span>
      <div style="display: grid; grid-auto-flow: column; gap: var(--space-2, 8px); align-items: center;">
        {children}
      </div>
    </div>
  );
}

/** Terminal-style ON/OFF toggle using sh-toggle CSS. */
function Toggle({ on, onToggle, labelOn, labelOff }) {
  return (
    <div
      class="sh-toggle"
      data-sh-on={on ? "true" : "false"}
      onClick={() => onToggle(!on)}
      role="switch"
      aria-checked={on}
      tabIndex={0}
      onKeyDown={(evt) => {
        if (evt.key === "Enter" || evt.key === " ") {
          evt.preventDefault();
          onToggle(!on);
        }
      }}
    >
      <span class="sh-toggle-indicator">{on ? (labelOn || "ON") : (labelOff || "OFF")}</span>
    </div>
  );
}

export default Settings;
