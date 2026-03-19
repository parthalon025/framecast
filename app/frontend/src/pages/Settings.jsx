/** @fileoverview Settings page — reads/writes FrameCast configuration via API. */
import { useState, useEffect, useCallback } from "preact/hooks";
import { ShCollapsible } from "superhot-ui/preact";
import { ShToast } from "superhot-ui/preact";

const TRANSITION_OPTIONS = ["fade", "slide", "zoom", "dissolve", "none"];
const ORDER_OPTIONS = [
  { value: "shuffle", label: "SHUFFLE" },
  { value: "newest", label: "NEWEST FIRST" },
  { value: "oldest", label: "OLDEST FIRST" },
  { value: "alphabetical", label: "ALPHABETICAL" },
];

export function Settings() {
  const [settings, setSettings] = useState(null);
  const [dirty, setDirty] = useState({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setSettings(data))
      .catch((err) => setError(err.message));
  }, []);

  const update = useCallback(
    (key, value) => {
      setSettings((prev) => ({ ...prev, [key]: value }));
      setDirty((prev) => ({ ...prev, [key]: true }));
    },
    [],
  );

  const save = useCallback(async () => {
    if (!settings) return;
    const changed = {};
    for (const key of Object.keys(dirty)) {
      changed[key] = settings[key];
    }
    if (Object.keys(changed).length === 0) return;

    setSaving(true);
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changed),
      });
      const body = await res.json();
      if (!res.ok) {
        setToast({ type: "error", message: body.error || "SAVE FAILED" });
        return;
      }
      setSettings(body.settings);
      setDirty({});
      setToast({ type: "info", message: "SETTINGS SAVED" });
    } catch (err) {
      setToast({ type: "error", message: err.message || "NETWORK ERROR" });
    } finally {
      setSaving(false);
    }
  }, [settings, dirty]);

  if (error) {
    return (
      <div class="sh-frame" data-label="SETTINGS" style="padding: 20px;">
        <span class="sh-label" style="color: var(--status-critical, #ff4444);">
          LOAD FAILED: {error}
        </span>
      </div>
    );
  }

  if (!settings) {
    return (
      <div class="sh-frame" data-label="SETTINGS" style="padding: 20px;">
        <span class="sh-label">LOADING...</span>
      </div>
    );
  }

  const hasDirty = Object.keys(dirty).length > 0;

  return (
    <div class="fc-page">
      {/* DISPLAY */}
      <div class="sh-frame" data-label="DISPLAY">
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <SettingRow label="SLIDESHOW INTERVAL (S)">
            <input
              class="sh-input"
              type="number"
              min="1"
              value={settings.photo_duration}
              onInput={(evt) => update("photo_duration", parseInt(evt.target.value, 10) || 1)}
            />
          </SettingRow>

          <SettingRow label="TRANSITION">
            <select
              class="sh-select"
              value={settings.transition_type}
              onChange={(evt) => update("transition_type", evt.target.value)}
            >
              {TRANSITION_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt.toUpperCase()}
                </option>
              ))}
            </select>
          </SettingRow>

          <SettingRow label="PHOTO ORDER">
            <select
              class="sh-select"
              value={settings.photo_order}
              onChange={(evt) => update("photo_order", evt.target.value)}
            >
              {ORDER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </SettingRow>

          <SettingRow label="QR DISPLAY (S)">
            <input
              class="sh-input"
              type="number"
              min="1"
              value={settings.qr_display_seconds}
              onInput={(evt) => update("qr_display_seconds", parseInt(evt.target.value, 10) || 1)}
            />
          </SettingRow>
        </div>
      </div>

      {/* NETWORK */}
      <div class="sh-frame" data-label="NETWORK">
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <SettingRow label="HDMI SCHEDULE">
            <Toggle
              on={settings.hdmi_schedule_enabled}
              onToggle={(val) => update("hdmi_schedule_enabled", val)}
            />
          </SettingRow>

          {settings.hdmi_schedule_enabled && (
            <>
              <SettingRow label="HDMI OFF">
                <input
                  class="sh-input"
                  type="text"
                  value={settings.hdmi_off_time}
                  placeholder="HH:MM"
                  onInput={(evt) => update("hdmi_off_time", evt.target.value)}
                />
              </SettingRow>

              <SettingRow label="HDMI ON">
                <input
                  class="sh-input"
                  type="text"
                  value={settings.hdmi_on_time}
                  placeholder="HH:MM"
                  onInput={(evt) => update("hdmi_on_time", evt.target.value)}
                />
              </SettingRow>
            </>
          )}
        </div>
      </div>

      {/* ADVANCED (contains SYSTEM) */}
      <ShCollapsible title="ADVANCED" defaultOpen={false} summary="SYSTEM">
        <div class="sh-frame" data-label="SYSTEM">
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <SettingRow label="AUTO-UPDATE">
              <Toggle
                on={settings.auto_update_enabled}
                onToggle={(val) => update("auto_update_enabled", val)}
              />
            </SettingRow>

            <SettingRow label="UPLOAD LIMIT (MB)">
              <input
                class="sh-input"
                type="number"
                min="1"
                value={settings.max_upload_mb}
                onInput={(evt) => update("max_upload_mb", parseInt(evt.target.value, 10) || 1)}
              />
            </SettingRow>

            <SettingRow label="AUTO-RESIZE MAX (PX)">
              <input
                class="sh-input"
                type="number"
                min="1"
                value={settings.auto_resize_max}
                onInput={(evt) => update("auto_resize_max", parseInt(evt.target.value, 10) || 1)}
              />
            </SettingRow>
          </div>
        </div>
      </ShCollapsible>

      {/* SAVE */}
      <button
        class="sh-input"
        style={`
          width: 100%;
          cursor: ${hasDirty && !saving ? "pointer" : "default"};
          text-align: center;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          opacity: ${hasDirty ? 1 : 0.4};
          color: ${hasDirty ? "var(--sh-phosphor)" : "var(--text-tertiary)"};
          border-color: ${hasDirty ? "var(--sh-phosphor)" : "var(--border-subtle)"};
        `}
        disabled={!hasDirty || saving}
        onClick={save}
      >
        {saving ? "SAVING..." : "SAVE"}
      </button>

      {/* TOAST */}
      {toast && (
        <div style="position: fixed; bottom: 80px; left: 12px; right: 12px; z-index: 100;">
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

/** Row with UPPERCASE label on left, control on right. */
function SettingRow({ label, children }) {
  return (
    <div class="fc-setting-row">
      <span class="sh-label" style="white-space: nowrap;">{label}</span>
      {children}
    </div>
  );
}

/** Terminal-style ON/OFF toggle using sh-toggle CSS. */
function Toggle({ on, onToggle }) {
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
      <span class="sh-toggle-indicator">{on ? "ON" : "OFF"}</span>
    </div>
  );
}

export default Settings;
