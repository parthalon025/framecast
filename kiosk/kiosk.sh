#!/usr/bin/env bash
# kiosk.sh — Wait for Flask, then launch cage with the GJS kiosk browser.
# Called by framecast-kiosk.service.
set -euo pipefail

# Read port from .env if available
ENV_FILE="/opt/framecast/app/.env"
WEB_PORT=8080
if [ -f "$ENV_FILE" ]; then
    WEB_PORT=$(grep "^WEB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8080")
    WEB_PORT="${WEB_PORT:-8080}"
fi

FLASK_URL="http://localhost:${WEB_PORT}/api/status"
MAX_WAIT=30

echo "FrameCast kiosk: waiting for Flask on port ${WEB_PORT} (up to ${MAX_WAIT}s)..."

ready=0
for i in $(seq 1 "$MAX_WAIT"); do
    if curl -sf --max-time 2 "$FLASK_URL" >/dev/null 2>&1; then
        ready=1
        echo "FrameCast kiosk: Flask ready after ${i}s"
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "FrameCast kiosk: ERROR — Flask did not respond within ${MAX_WAIT}s" >&2
    exit 1
fi

DISPLAY_ROTATION="${DISPLAY_ROTATION:-0}"

# Export WAYLAND_DISPLAY for other services (hdmi-control, schedule timer)
echo "${WAYLAND_DISPLAY:-wayland-1}" > /run/user/1000/framecast-wayland-display

# Disable hardware cursors (Wayland kiosk)
export WLR_NO_HARDWARE_CURSORS=1

# Launch cage (Wayland kiosk compositor) with the GJS browser
# Pass WEB_PORT as argument so browser.js can build TARGET_URI without hardcoding
if [ "$DISPLAY_ROTATION" != "0" ]; then
    # Start cage in background, apply rotation, then wait
    cage -d -- gjs /opt/framecast/kiosk/browser.js "$WEB_PORT" &
    CAGE_PID=$!
    sleep 2
    wlr-randr --output HDMI-A-1 --transform "$DISPLAY_ROTATION" 2>/dev/null || true
    wait "$CAGE_PID"
else
    exec cage -d -- gjs /opt/framecast/kiosk/browser.js "$WEB_PORT"
fi
