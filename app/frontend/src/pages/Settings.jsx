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
import { TransitionPreview } from "../components/TransitionPreview.jsx";

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
const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const TIMEZONE_OPTIONS = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Australia/Sydney",
  "Pacific/Auckland",
  "UTC",
];

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
  const [currentTz, setCurrentTz] = useState("UTC");
  const [frames, setFrames] = useState([]);
  const [scanningFrames, setScanningFrames] = useState(false);
  const [sshEnabled, setSshEnabled] = useState(false);
  const [sshToggling, setSshToggling] = useState(false);
  const [httpsStatus, setHttpsStatus] = useState({ has_cert: false, enabled: false });
  const [httpsToggling, setHttpsToggling] = useState(false);
  const [guestToken, setGuestToken] = useState(null);
  const [guestTtl, setGuestTtl] = useState(24);
  const [guestExpiry, setGuestExpiry] = useState(null);
  const [generatingGuest, setGeneratingGuest] = useState(false);
  const storageBarRef = useRef(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("framecast-theme") || "dark");

  /** Toggle phone UI theme (dark/light). TV display always stays dark. */
  function handleThemeToggle(isLight) {
    const next = isLight ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("framecast-theme", next);
    document.documentElement.setAttribute("data-theme", next);
  }

  /** Load settings + status + wifi info + timezone + frames + ssh + https on mount. */
  useEffect(() => {
    loadSettings();
    loadStatus();
    loadWifiStatus();
    loadTimezone();
    loadFrames();
    loadSshStatus();
    loadHttpsStatus();
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

  function loadFrames() {
    setScanningFrames(true);
    fetchWithTimeout("/api/frames")
      .then((res) => res.json())
      .then((data) => setFrames(data.frames || []))
      .catch((err) => console.warn("Settings: frame discovery failed", err))
      .finally(() => setScanningFrames(false));
  }

  function loadTimezone() {
    fetchWithTimeout("/api/timezone")
      .then((res) => res.json())
      .then((data) => setCurrentTz(data.timezone || "UTC"))
      .catch((err) => console.warn("Settings: timezone load failed", err));
  }

  function loadSshStatus() {
    fetchWithTimeout("/api/ssh/status")
      .then((res) => res.json())
      .then((data) => setSshEnabled(data.enabled || false))
      .catch((err) => console.warn("Settings: SSH status load failed", err));
  }

  async function handleSshToggle() {
    setSshToggling(true);
    try {
      const res = await fetchWithTimeout("/api/ssh/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !sshEnabled }),
      });
      if (res.ok) {
        setSshEnabled(!sshEnabled);
        setToast({ type: "info", message: sshEnabled ? "SSH DISABLED" : "SSH ENABLED" });
      } else {
        const body = await res.json();
        setToast({ type: "error", message: body.error || "SSH TOGGLE FAULT" });
      }
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setSshToggling(false);
    }
  }

  function loadHttpsStatus() {
    fetchWithTimeout("/api/https/status")
      .then((res) => res.json())
      .then((data) => setHttpsStatus(data))
      .catch((err) => console.warn("Settings: HTTPS status load failed", err));
  }

  async function handleHttpsToggle() {
    setHttpsToggling(true);
    try {
      const res = await fetchWithTimeout("/api/https/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !httpsStatus.enabled }),
      });
      if (res.ok) {
        const body = await res.json();
        setHttpsStatus({ has_cert: true, enabled: body.enabled });
        setToast({
          type: "info",
          message: body.enabled ? "HTTPS ENABLED — RESTART REQUIRED" : "HTTPS DISABLED — RESTART REQUIRED",
        });
      } else {
        const body = await res.json();
        setToast({ type: "error", message: body.error || "HTTPS TOGGLE FAULT" });
      }
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setHttpsToggling(false);
    }
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

  async function handleGenerateGuestLink() {
    setGeneratingGuest(true);
    setGuestToken(null);
    setGuestExpiry(null);
    try {
      const res = await fetchWithTimeout("/api/guest/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ttl_hours: guestTtl }),
      });
      const body = await res.json();
      if (res.ok && body.token) {
        setGuestToken(body.token);
        // Parse expiry from token (format: "expires:sig")
        const expires = parseInt(body.token.split(":")[0], 10);
        setGuestExpiry(new Date(expires * 1000));
        setToast({ type: "info", message: "GUEST LINK GENERATED" });
      } else {
        setToast({ type: "error", message: body.error || "GENERATE FAULT" });
      }
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK FAULT" });
    } finally {
      setGeneratingGuest(false);
    }
  }

  function copyGuestLink() {
    if (!guestToken) return;
    const url = `${window.location.origin}/?guest=${guestToken}`;
    navigator.clipboard.writeText(url).then(
      () => setToast({ type: "info", message: "LINK COPIED" }),
      () => setToast({ type: "error", message: "COPY FAULT" }),
    );
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
            <SettingRow label="THEME">
              <Toggle
                on={theme === "light"}
                onToggle={handleThemeToggle}
                labelOn="LIGHT"
                labelOff="DARK"
              />
            </SettingRow>

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
                <div style="display: flex; align-items: center; gap: 12px;">
                  <select
                    class="sh-select"
                    value={settings.transition_type}
                    onChange={(evt) => update("transition_type", evt.target.value)}
                  >
                    {TRANSITION_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>{opt.toUpperCase()}</option>
                    ))}
                  </select>
                  <TransitionPreview type={settings.transition_type || "fade"} />
                </div>
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

            <SettingRow label="MAX VIDEO DURATION (S)">
              <input
                class="sh-range"
                type="range"
                min="5"
                max="300"
                step="5"
                value={settings.max_video_duration || 30}
                onInput={(evt) => update("max_video_duration", parseInt(evt.target.value, 10))}
              />
              <span class="sh-value fc-range-value">{settings.max_video_duration || 30}s</span>
            </SettingRow>
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

            <SettingRow label="SSH ACCESS">
              <button
                class="sh-input sh-clickable"
                style="min-width: 100px; text-align: center;"
                onClick={handleSshToggle}
                disabled={sshToggling}
              >
                {sshToggling ? "STANDBY" : sshEnabled ? "ENABLED" : "DISABLED"}
              </button>
            </SettingRow>

            <SettingRow label="HTTPS">
              <div style="display: flex; align-items: center; gap: var(--space-2, 8px);">
                <button
                  class="sh-input sh-clickable"
                  style="min-width: 100px; text-align: center;"
                  onClick={handleHttpsToggle}
                  disabled={httpsToggling}
                >
                  {httpsToggling ? "STANDBY" : httpsStatus.enabled ? "ENABLED" : "DISABLED"}
                </button>
                {httpsStatus.has_cert && (
                  <span class="sh-ansi-dim" style="font-size: 0.75rem;">CERT OK</span>
                )}
              </div>
            </SettingRow>
            {httpsStatus.enabled && (
              <div class="fc-setting-row">
                <span class="sh-label" style="white-space: nowrap; color: var(--sh-phosphor, #39ff14); font-size: 0.75rem;">
                  RESTART REQUIRED FOR CHANGES
                </span>
              </div>
            )}
          </div>
        </ShCollapsible>
      </section>

      {/* ── GUEST UPLOAD ── */}
      <section aria-label="Guest upload settings">
        <ShCollapsible title="GUEST UPLOAD" defaultOpen={false}>
          <div class="fc-settings-section">
            <SettingRow label="LINK DURATION">
              <select
                class="sh-select"
                value={guestTtl}
                onChange={(evt) => setGuestTtl(parseInt(evt.target.value, 10))}
              >
                <option value="1">1 HOUR</option>
                <option value="6">6 HOURS</option>
                <option value="12">12 HOURS</option>
                <option value="24">24 HOURS</option>
                <option value="48">48 HOURS</option>
                <option value="168">7 DAYS</option>
              </select>
            </SettingRow>

            <SettingRow label="GENERATE LINK">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={handleGenerateGuestLink}
                disabled={generatingGuest}
              >
                {generatingGuest ? "STANDBY" : "GENERATE"}
              </button>
            </SettingRow>

            {guestToken && (
              <>
                <SettingRow label="GUEST URL">
                  <div style="display: flex; flex-direction: column; gap: 4px; max-width: 240px;">
                    <span
                      class="sh-value"
                      style="font-family: var(--font-mono, monospace); font-size: 0.7rem; word-break: break-all; opacity: 0.8;"
                    >
                      {`${window.location.origin}/?guest=${guestToken}`}
                    </span>
                    <button
                      class="sh-input sh-clickable"
                      style="text-align: center; min-width: 80px;"
                      onClick={copyGuestLink}
                    >
                      COPY LINK
                    </button>
                  </div>
                </SettingRow>

                <SettingRow label="EXPIRES">
                  <span class="sh-value" style="font-family: var(--font-mono, monospace);">
                    {guestExpiry
                      ? guestExpiry.toLocaleString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                          hour12: false,
                        })
                      : "UNKNOWN"}
                  </span>
                </SettingRow>
              </>
            )}
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
                <ScheduleTimeline onTime={settings.hdmi_on_time} offTime={settings.hdmi_off_time} />
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

            <SettingRow label="OTHER FRAMES">
              <div style="display: flex; align-items: center; gap: var(--space-2, 8px);">
                {scanningFrames ? (
                  <span class="sh-ansi-dim">SCANNING</span>
                ) : frames.length === 0 ? (
                  <span class="sh-ansi-dim">NONE FOUND</span>
                ) : (
                  <div style="display: flex; flex-direction: column; gap: 4px;">
                    {frames.map((frame) => (
                      <a
                        key={frame.hostname}
                        href={frame.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        class="sh-clickable"
                        style="font-family: var(--font-mono, monospace); font-size: 0.8rem; color: var(--sh-phosphor, #39ff14); text-decoration: none;"
                      >
                        {frame.hostname.toUpperCase()}
                      </a>
                    ))}
                  </div>
                )}
                <button
                  class="sh-input sh-clickable"
                  style="text-align: center; min-width: 60px; font-size: 0.75rem; padding: 2px 8px;"
                  onClick={loadFrames}
                  disabled={scanningFrames}
                >
                  SCAN
                </button>
              </div>
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

            <SettingRow label="TIMEZONE">
              <select
                class="sh-select"
                value={currentTz}
                onChange={(evt) => {
                  const tz = evt.target.value;
                  fetchWithTimeout("/api/timezone", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ timezone: tz }),
                  })
                    .then((res) => {
                      if (!res.ok) throw new Error("SET FAULT");
                      setCurrentTz(tz);
                      setToast({ type: "info", message: `TIMEZONE: ${tz}` });
                    })
                    .catch(() => {
                      setToast({ type: "error", message: "TIMEZONE SET FAULT" });
                    });
                }}
              >
                {TIMEZONE_OPTIONS.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz.toUpperCase().replace(/_/g, " ")}
                  </option>
                ))}
                {/* Show current timezone even if not in preset list */}
                {!TIMEZONE_OPTIONS.includes(currentTz) && (
                  <option value={currentTz}>
                    {currentTz.toUpperCase().replace(/_/g, " ")}
                  </option>
                )}
              </select>
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

            <SettingRow label="EXPORT PHOTOS">
              <a
                class="sh-input sh-clickable"
                href="/api/export"
                style="text-align: center; min-width: 120px; text-decoration: none; display: inline-block;"
              >
                DOWNLOAD ZIP
              </a>
            </SettingRow>

            <SettingRow label="RESTORE BACKUP">
              <input
                type="file"
                accept=".db,.backup,.sqlite"
                class="sh-input"
                style="max-width: 200px;"
                onChange={async (evt) => {
                  const file = evt.target.files[0];
                  if (!file) return;
                  if (!confirm("RESTORE will replace all current data. Continue?")) {
                    evt.target.value = "";
                    return;
                  }
                  const form = new FormData();
                  form.append("backup", file);
                  try {
                    const res = await fetch("/api/restore", { method: "POST", body: form });
                    const data = await res.json();
                    if (res.ok) {
                      alert("RESTORED — restart recommended");
                    } else {
                      alert(data.error || "Restore failed");
                    }
                  } catch (err) {
                    alert("Network error: " + err.message);
                  }
                  evt.target.value = "";
                }}
              />
            </SettingRow>

            <SettingRow label="EXPORT SETTINGS">
              <button
                class="sh-input sh-clickable"
                style="text-align: center; min-width: 120px;"
                onClick={async () => {
                  try {
                    const res = await fetch("/api/settings/export");
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const data = await res.json();
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "framecast-settings.json";
                    a.click();
                    URL.revokeObjectURL(url);
                    setToast({ type: "info", message: "SETTINGS EXPORTED" });
                  } catch (err) {
                    setToast({ type: "error", message: err.message || "EXPORT FAULT" });
                  }
                }}
              >
                DOWNLOAD JSON
              </button>
            </SettingRow>

            <SettingRow label="IMPORT SETTINGS">
              <input
                type="file"
                accept=".json"
                class="sh-input"
                style="max-width: 200px;"
                onChange={async (evt) => {
                  const file = evt.target.files[0];
                  if (!file) return;
                  try {
                    const text = await file.text();
                    const data = JSON.parse(text);
                    const res = await fetch("/api/settings/import", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(data),
                    });
                    const result = await res.json();
                    if (res.ok) {
                      setToast({ type: "info", message: `IMPORTED ${result.imported} SETTINGS` });
                      loadSettings();
                    } else {
                      setToast({ type: "error", message: result.error || "IMPORT FAULT" });
                    }
                  } catch (err) {
                    setToast({ type: "error", message: "INVALID JSON FILE" });
                  }
                  evt.target.value = "";
                }}
              />
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
        {saving ? "STANDBY" : "SAVE"}
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

/** 24-hour timeline bar showing active (ON) vs standby (OFF) hours. */
function ScheduleTimeline({ onTime, offTime }) {
  const parseTime = (str) => {
    const [hh, mm] = (str || "08:00").split(":").map(Number);
    return hh + mm / 60;
  };

  const on = parseTime(onTime);
  const off = parseTime(offTime);

  let activeStart, activeWidth;
  if (on < off) {
    activeStart = (on / 24) * 100;
    activeWidth = ((off - on) / 24) * 100;
  } else {
    activeStart = (on / 24) * 100;
    activeWidth = ((24 - on + off) / 24) * 100;
  }

  const hours = [0, 6, 12, 18];

  return (
    <div class="fc-schedule-timeline">
      <div class="fc-timeline-bar">
        {on < off ? (
          <div class="fc-timeline-active" style={{ left: `${activeStart}%`, width: `${activeWidth}%` }} />
        ) : (
          <>
            <div class="fc-timeline-active" style={{ left: `${activeStart}%`, width: `${100 - activeStart}%` }} />
            <div class="fc-timeline-active" style={{ left: "0%", width: `${(off / 24) * 100}%` }} />
          </>
        )}
      </div>
      <div class="fc-timeline-labels">
        {hours.map(hr => (
          <span key={hr} class="sh-ansi-dim" style={{ left: `${(hr / 24) * 100}%` }}>
            {String(hr).padStart(2, "0")}
          </span>
        ))}
      </div>
    </div>
  );
}

export default Settings;
