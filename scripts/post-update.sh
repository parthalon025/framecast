#!/usr/bin/env bash
set -euo pipefail
# Post-update script — runs after git checkout to sync deps and services.
# Called by updater.apply_update() with 300s timeout.
# Built frontend assets are now tracked in git — no npm rebuild needed.
cd /opt/framecast

log() { echo "POST-UPDATE: $*"; }
err() { echo "POST-UPDATE ERROR: $*" >&2; }

# 1. Reinstall pip if purged by image build
if ! command -v pip3 >/dev/null 2>&1; then
    log "Reinstalling pip (purged by image build)..."
    if ! { sudo apt-get update -qq && sudo apt-get install -y -qq python3-pip >/dev/null; }; then
        err "Failed to install pip — Python deps may be stale"
    fi
fi

# 2. Install/upgrade Python dependencies
log "Installing Python dependencies..."
pip3 install --break-system-packages -q -r requirements.txt 2>&1 || {
    err "pip install failed — some features may not work"
}

# 3. Reload systemd in case unit files changed
log "Reloading systemd..."
sudo systemctl daemon-reload

# 4. Clean up removed services from previous versions
sudo systemctl disable wifi-manager.service 2>/dev/null || true

# 5. Restart services (kiosk follows via BindsTo=framecast)
log "Restarting services..."
sudo systemctl restart framecast

log "Complete"
