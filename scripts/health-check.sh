#!/bin/bash
# health-check.sh — Post-update health check with auto-rollback
#
# Runs on boot after an OTA update.  If the core services fail to start,
# rolls back to the previous git tag and reboots.
set -euo pipefail

ROLLBACK_FILE="/tmp/framecast-rollback-tag"
INSTALL_DIR="/opt/framecast"

# Only run if a rollback tag exists (meaning we just updated)
if [ ! -f "$ROLLBACK_FILE" ]; then
    exit 0
fi

PREV_TAG=$(cat "$ROLLBACK_FILE")
echo "Post-update health check. Rollback target: $PREV_TAG"

# Wait for services to come up
sleep 10

# Check services
HEALTHY=true
for svc in framecast framecast-kiosk; do
    if ! systemctl is-active --quiet "$svc"; then
        echo "FAIL: $svc is not active"
        HEALTHY=false
    fi
done

if $HEALTHY; then
    echo "Health check PASSED — update confirmed"
    rm -f "$ROLLBACK_FILE"
    exit 0
fi

# Rollback
echo "Health check FAILED — rolling back to $PREV_TAG"
cd "$INSTALL_DIR"
git checkout "$PREV_TAG" 2>/dev/null || git checkout main
rm -f "$ROLLBACK_FILE"
sudo reboot
