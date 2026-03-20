#!/usr/bin/env bash
# wifi-check.sh — Check WiFi connectivity on boot.
# Called by wifi-manager.service (Type=oneshot, RemainAfterExit=yes).
set -euo pipefail

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): WIFI: $*"; }

# Wait for NetworkManager to be ready
MAX_WAIT=30
for i in $(seq 1 "$MAX_WAIT"); do
    if nmcli general status >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq "$MAX_WAIT" ]; then
        log "NetworkManager not ready after ${MAX_WAIT}s"
        exit 0  # Non-fatal — AP mode handled by web app
    fi
    sleep 1
done

# Check if already connected
STATE=$(nmcli -t -f GENERAL.STATE dev show wlan0 2>/dev/null || true)
if echo "$STATE" | grep -qi "connected" && ! echo "$STATE" | grep -qi "disconnected"; then
    SSID=$(nmcli -t -f GENERAL.CONNECTION dev show wlan0 2>/dev/null | cut -d: -f2 || true)
    log "Connected to ${SSID:-unknown}"
    exit 0
fi

# Not connected — log for visibility, AP mode handled by web app on demand
log "Not connected — AP mode will be available via web interface"
exit 0
