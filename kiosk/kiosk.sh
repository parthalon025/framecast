#!/bin/bash
# kiosk.sh — Wait for Flask, then launch cage with the GJS kiosk browser.
# Called by framecast-kiosk.service.
set -euo pipefail

FLASK_URL="http://localhost:8080/api/status"
MAX_WAIT=30

echo "FrameCast kiosk: waiting for Flask (up to ${MAX_WAIT}s)..."

ready=0
for i in $(seq 1 "$MAX_WAIT"); do
    if curl -sf "$FLASK_URL" >/dev/null 2>&1; then
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

# Launch cage (Wayland kiosk compositor) with the GJS browser
exec cage -- gjs /opt/framecast/kiosk/browser.js
