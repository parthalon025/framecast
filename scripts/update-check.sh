#!/bin/bash
# update-check.sh — Daily OTA update check (called by framecast-update.timer)
#
# Checks if auto-update is enabled, queries GitHub for a newer release,
# and optionally applies the update + reboots.
#
# Exit codes:
#   0 - Check completed (update applied, or no update, or auto-update disabled)
#   1 - Error during check or apply
set -euo pipefail

INSTALL_DIR="/opt/framecast"
ENV_FILE="$INSTALL_DIR/app/.env"
LOG_TAG="framecast-update"

log() { echo "[$LOG_TAG] $*"; }

# Read .env value with default
env_get() {
    local key="$1" default="${2:-}"
    if [ -f "$ENV_FILE" ]; then
        local val
        val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

# Check if auto-update is enabled
AUTO_UPDATE=$(env_get "AUTO_UPDATE_ENABLED" "no")
if [ "${AUTO_UPDATE,,}" != "yes" ]; then
    log "Auto-update disabled (AUTO_UPDATE_ENABLED=$AUTO_UPDATE)"
    exit 0
fi

# Read GitHub repo config (supports forks)
GITHUB_OWNER=$(env_get "GITHUB_OWNER" "parthalon025")
GITHUB_REPO=$(env_get "GITHUB_REPO" "framecast")
API_URL="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest"

# Read current version
if [ ! -f "$INSTALL_DIR/VERSION" ]; then
    log "ERROR: VERSION file not found at $INSTALL_DIR/VERSION"
    exit 1
fi
CURRENT=$(cat "$INSTALL_DIR/VERSION")
log "Current version: $CURRENT"

# Query GitHub Releases API
log "Checking $API_URL"
RESPONSE=$(curl -sf --max-time 30 \
    -H "Accept: application/vnd.github.v3+json" \
    -H "User-Agent: FrameCast-Updater" \
    "$API_URL" 2>&1) || {
    log "ERROR: GitHub API request failed: $RESPONSE"
    exit 1
}

TAG=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null)

if [ -z "$TAG" ]; then
    log "ERROR: No tag_name in GitHub response"
    exit 1
fi

# Validate tag format (vX.Y.Z)
if ! [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    log "ERROR: Invalid tag format: $TAG"
    exit 1
fi

LATEST="${TAG#v}"
log "Latest version: $LATEST"

# Compare versions using Python (reliable semver comparison)
IS_NEWER=$(python3 -c "
current = tuple(int(x) for x in '$CURRENT'.split('.'))
latest = tuple(int(x) for x in '$LATEST'.split('.'))
print('yes' if latest > current else 'no')
" 2>/dev/null)

if [ "$IS_NEWER" != "yes" ]; then
    log "System is up to date (v$CURRENT)"
    exit 0
fi

log "Update available: v$CURRENT -> $TAG"

# Apply update via the Python updater module (handles rollback tag, SHA verification, git ops)
cd "$INSTALL_DIR"
python3 -c "
import sys
sys.path.insert(0, 'app')
from modules.updater import apply_update, _fetch_tag_sha
expected_sha = _fetch_tag_sha('$TAG')
success, message = apply_update('$TAG', expected_sha=expected_sha)
print(message)
sys.exit(0 if success else 1)
" || {
    log "ERROR: Update apply failed"
    exit 1
}

log "Update applied successfully. Rebooting in 5 seconds..."
sleep 5
reboot
