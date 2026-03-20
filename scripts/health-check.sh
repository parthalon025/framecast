#!/bin/bash
# health-check.sh — Post-update health check with HMAC-validated auto-rollback
#
# Runs on boot after an OTA update.  If the core services fail to start,
# rolls back to the previous git tag and reboots.
set -euo pipefail

ROLLBACK_FILE="/var/lib/framecast/rollback-tag"
ROLLBACK_SIG="/var/lib/framecast/rollback-sig"
INSTALL_DIR="/opt/framecast"
ENV_FILE="$INSTALL_DIR/app/.env"

# Only run if a rollback tag exists (meaning we just updated)
if [ ! -f "$ROLLBACK_FILE" ]; then
    exit 0
fi

PREV_TAG=$(cat "$ROLLBACK_FILE")

# Validate tag format to prevent injection
if ! [[ "$PREV_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "INVALID rollback tag format: $PREV_TAG — aborting"
    rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"
    exit 1
fi

# Validate HMAC signature
if [ ! -f "$ROLLBACK_SIG" ]; then
    echo "MISSING rollback signature — refusing to roll back (tag may be tampered)"
    rm -f "$ROLLBACK_FILE"
    exit 1
fi

# Read secret key from .env
SECRET=""
if [ -f "$ENV_FILE" ]; then
    SECRET=$(grep "^FLASK_SECRET_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
fi
if [ -z "$SECRET" ]; then
    echo "ERROR: FLASK_SECRET_KEY not found in $ENV_FILE — cannot validate rollback signature"
    rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"
    exit 1
fi

EXPECTED_SIG=$(echo -n "$PREV_TAG" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')
ACTUAL_SIG=$(cat "$ROLLBACK_SIG")

if [ "$EXPECTED_SIG" != "$ACTUAL_SIG" ]; then
    echo "HMAC MISMATCH — rollback tag signature invalid, refusing rollback"
    rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"
    exit 1
fi

# Ensure rollback files are always cleaned up, even on script failure
trap 'rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"' EXIT

# Validate tag exists in git
cd "$INSTALL_DIR" || {
    echo "CRITICAL: Cannot cd to $INSTALL_DIR"
    exit 1
}

if ! git tag -l "$PREV_TAG" | grep -q "$PREV_TAG"; then
    echo "INVALID: tag $PREV_TAG does not exist in git — aborting rollback"
    exit 1
fi

echo "Post-update health check. Rollback target: $PREV_TAG"

# Wait for Flask to be ready (not just systemd "active")
WEB_PORT=8080
if [ -f "$ENV_FILE" ]; then
    WEB_PORT=$(grep "^WEB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8080")
    WEB_PORT="${WEB_PORT:-8080}"
fi

echo "Waiting for Flask readiness on port ${WEB_PORT}..."
HEALTHY=false
for i in $(seq 1 30); do
    if curl -sf --max-time 2 "http://localhost:${WEB_PORT}/api/status" >/dev/null 2>&1; then
        HEALTHY=true
        echo "Flask ready after ${i}s"
        break
    fi
    sleep 2
done

# Also verify kiosk service
if [ "$HEALTHY" = "true" ]; then
    if ! systemctl is-active --quiet framecast-kiosk; then
        echo "WARN: Flask ready but kiosk is not active — giving extra time"
        sleep 10
        if ! systemctl is-active --quiet framecast-kiosk; then
            echo "FAIL: framecast-kiosk is not active"
            HEALTHY=false
        fi
    fi
fi

if [[ "$HEALTHY" == "true" ]]; then
    echo "Health check PASSED — update confirmed"
    exit 0
fi

# Rollback
echo "Health check FAILED — rolling back to $PREV_TAG"
if ! git checkout --force "$PREV_TAG" 2>&1; then
    echo "ERROR: git checkout $PREV_TAG failed, trying main"
    if ! git checkout --force main 2>&1; then
        echo "CRITICAL: All rollback attempts failed. Manual intervention required."
        exit 1
    fi
fi
git clean -fd 2>/dev/null || true
sudo reboot
