/** @fileoverview Incident state — tracks active device-level incidents. */
import { signal } from "@preact/signals";

/** Active incident: { severity, message, startedAt } or null */
export const incident = signal(null);

/** Set an active incident. */
export function raiseIncident(message, severity = "warning") {
  if (!incident.value) {
    incident.value = { severity, message, startedAt: Date.now() };
  }
}

/** Clear the active incident. */
export function clearIncident() {
  incident.value = null;
}
