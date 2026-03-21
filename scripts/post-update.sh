#!/usr/bin/env bash
set -euo pipefail
# Post-update script — runs after git checkout to install deps and rebuild
cd /opt/framecast

echo "POST-UPDATE: Installing Python dependencies..."
pip3 install --break-system-packages -q -r requirements.txt 2>&1 || {
    echo "WARNING: pip install failed — some features may not work" >&2
}

# Rebuild frontend if package.json changed
if [ -f app/frontend/package.json ] && [ -d app/frontend/node_modules ]; then
    echo "POST-UPDATE: Rebuilding frontend..."
    cd app/frontend && npm ci && npm run build && cd /opt/framecast
fi

# Restart the main service (kiosk follows via BindsTo)
echo "POST-UPDATE: Restarting services..."
sudo systemctl restart framecast

echo "POST-UPDATE: Complete"
