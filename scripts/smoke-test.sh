#!/bin/bash
# smoke-test.sh — Quick validation of FrameCast installation
#
# Run on the Pi after installation to verify everything is working.
# Usage: bash scripts/smoke-test.sh
#
# Exit codes:
#   0 - All checks passed
#   1 - Warnings only (non-critical issues)
#   2 - Critical failures detected

set -euo pipefail

INSTALL_DIR="/opt/framecast"
PASS=0
FAIL=0
WARN=0

# Colors (if terminal supports them)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    NC='\033[0m'
else
    GREEN=''
    RED=''
    YELLOW=''
    NC=''
fi

pass() {
    echo -e "  ${GREEN}PASS${NC}  $1"
    PASS=$((PASS + 1))
}

fail() {
    echo -e "  ${RED}FAIL${NC}  $1"
    FAIL=$((FAIL + 1))
}

warn() {
    echo -e "  ${YELLOW}WARN${NC}  $1"
    WARN=$((WARN + 1))
}

echo "========================================"
echo "  FrameCast — Smoke Test"
echo "========================================"
echo ""

# -----------------------------------------------------------------------
# 1. Install directory
# -----------------------------------------------------------------------
echo "--- Install Directory ---"

if [ -d "$INSTALL_DIR" ]; then
    pass "Install directory exists: $INSTALL_DIR"
else
    fail "Install directory missing: $INSTALL_DIR"
fi

if [ -f "$INSTALL_DIR/app/web_upload.py" ]; then
    pass "Web upload module present"
else
    fail "Web upload module missing: $INSTALL_DIR/app/web_upload.py"
fi

if [ -f "$INSTALL_DIR/kiosk/kiosk.sh" ]; then
    pass "Kiosk launcher present"
else
    fail "Kiosk launcher missing: $INSTALL_DIR/kiosk/kiosk.sh"
fi

if [ -x "$INSTALL_DIR/kiosk/kiosk.sh" ]; then
    pass "Kiosk launcher is executable"
else
    fail "Kiosk launcher is not executable"
fi

if [ -x "$INSTALL_DIR/scripts/hdmi-control.sh" ]; then
    pass "HDMI control script is executable"
else
    fail "HDMI control script missing or not executable"
fi

echo ""

# -----------------------------------------------------------------------
# 2. Frontend assets
# -----------------------------------------------------------------------
echo "--- Frontend Assets ---"

JS_COUNT=0
if [ -d "$INSTALL_DIR/app/static/js" ]; then
    JS_COUNT=$(find "$INSTALL_DIR/app/static/js" -name '*.js' -type f 2>/dev/null | wc -l)
fi
if [ "$JS_COUNT" -gt 0 ]; then
    pass "Frontend JS assets: $JS_COUNT file(s) in app/static/js/"
else
    fail "No JS assets found in app/static/js/ — run npm run build"
fi

CSS_COUNT=0
if [ -d "$INSTALL_DIR/app/static/css" ]; then
    CSS_COUNT=$(find "$INSTALL_DIR/app/static/css" -name '*.css' -type f 2>/dev/null | wc -l)
fi
if [ "$CSS_COUNT" -gt 0 ]; then
    pass "Frontend CSS assets: $CSS_COUNT file(s) in app/static/css/"
else
    fail "No CSS assets found in app/static/css/ — run npm run build"
fi

echo ""

# -----------------------------------------------------------------------
# 3. Python syntax check
# -----------------------------------------------------------------------
echo "--- Python Syntax ---"

PY_ERRORS=0
if [ -d "$INSTALL_DIR/app" ]; then
    while IFS= read -r pyfile; do
        if ! python3 -m py_compile "$pyfile" 2>/dev/null; then
            fail "Syntax error: $pyfile"
            PY_ERRORS=$((PY_ERRORS + 1))
        fi
    done < <(find "$INSTALL_DIR/app" -name '*.py' -type f 2>/dev/null)

    if [ "$PY_ERRORS" -eq 0 ]; then
        pass "All Python files pass syntax check"
    fi
else
    fail "App directory not found for syntax check"
fi

echo ""

# -----------------------------------------------------------------------
# 4. Configuration
# -----------------------------------------------------------------------
echo "--- Configuration ---"

MEDIA_DIR=""

if [ -f "$INSTALL_DIR/app/.env" ]; then
    pass ".env config file exists"
else
    fail ".env config file missing"
fi

if [ -f "$INSTALL_DIR/app/.env" ]; then
    PERMS=$(stat -c '%a' "$INSTALL_DIR/app/.env" 2>/dev/null || echo "unknown")
    if [ "$PERMS" = "600" ]; then
        pass ".env file permissions are 600 (secure)"
    else
        warn ".env file permissions are $PERMS (expected 600)"
    fi

    if grep -q "^FLASK_SECRET_KEY=.\+" "$INSTALL_DIR/app/.env" 2>/dev/null; then
        pass "Flask secret key is set"
    else
        fail "Flask secret key is empty or missing"
    fi

    if grep -q "^MEDIA_DIR=" "$INSTALL_DIR/app/.env" 2>/dev/null; then
        MEDIA_DIR=$(grep "^MEDIA_DIR=" "$INSTALL_DIR/app/.env" | cut -d= -f2)
        pass "MEDIA_DIR configured: $MEDIA_DIR"
    else
        fail "MEDIA_DIR not configured in .env"
    fi
fi

echo ""

# -----------------------------------------------------------------------
# 5. Media directory
# -----------------------------------------------------------------------
echo "--- Media Directory ---"

if [ -n "${MEDIA_DIR:-}" ]; then
    if [ -d "$MEDIA_DIR" ]; then
        pass "Media directory exists: $MEDIA_DIR"
    else
        fail "Media directory missing: $MEDIA_DIR"
    fi

    if [ -d "$MEDIA_DIR" ]; then
        OWNER=$(stat -c '%U' "$MEDIA_DIR" 2>/dev/null || echo "unknown")
        if [ "$OWNER" != "root" ]; then
            pass "Media directory owned by: $OWNER (not root)"
        else
            warn "Media directory owned by root (should be the Pi user)"
        fi

        if [ -w "$MEDIA_DIR" ] || [ "$(id -u)" -eq 0 ]; then
            pass "Media directory is writable"
        else
            fail "Media directory is not writable"
        fi
    fi
else
    warn "MEDIA_DIR not set, skipping media directory checks"
fi

echo ""

# -----------------------------------------------------------------------
# 6. Systemd services
# -----------------------------------------------------------------------
echo "--- Systemd Services ---"

for SVC in framecast framecast-kiosk wifi-manager; do
    if systemctl is-enabled "$SVC" &>/dev/null; then
        pass "$SVC service is enabled"
    else
        fail "$SVC service is not enabled"
    fi

    STATUS=$(systemctl is-active "$SVC" 2>/dev/null || echo "inactive")
    if [ "$STATUS" = "active" ]; then
        pass "$SVC service is running"
    else
        warn "$SVC service is $STATUS"
    fi
done

echo ""

# -----------------------------------------------------------------------
# 7. Web server
# -----------------------------------------------------------------------
echo "--- Web Server ---"

WEB_PORT="8080"
if [ -f "$INSTALL_DIR/app/.env" ]; then
    WEB_PORT=$(grep "^WEB_PORT=" "$INSTALL_DIR/app/.env" 2>/dev/null | cut -d= -f2 || echo "8080")
    WEB_PORT="${WEB_PORT:-8080}"
fi

if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${WEB_PORT}/" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        pass "Web server responding on port $WEB_PORT (HTTP $HTTP_CODE)"
    else
        fail "Web server not responding on port $WEB_PORT (HTTP $HTTP_CODE)"
    fi

    # Check API endpoint
    API_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${WEB_PORT}/api/status" 2>/dev/null || echo "000")
    if [ "$API_CODE" = "200" ]; then
        pass "API endpoint /api/status responding (HTTP $API_CODE)"
    else
        fail "API endpoint /api/status not responding (HTTP $API_CODE)"
    fi
else
    warn "curl not installed, skipping web server checks"
fi

echo ""

# -----------------------------------------------------------------------
# 8. Hardware watchdog
# -----------------------------------------------------------------------
echo "--- Hardware Watchdog ---"

if systemctl is-active watchdog &>/dev/null; then
    pass "Watchdog service is active"
else
    warn "Watchdog service is not active"
fi

if [ -e /dev/watchdog ]; then
    pass "Watchdog device exists (/dev/watchdog)"
else
    warn "Watchdog device not found (/dev/watchdog)"
fi

echo ""

# -----------------------------------------------------------------------
# 9. System dependencies
# -----------------------------------------------------------------------
echo "--- System Dependencies ---"

for CMD in python3 gunicorn ffmpeg qrencode cage; do
    if command -v "$CMD" &>/dev/null; then
        pass "$CMD is installed"
    else
        fail "$CMD is not installed"
    fi
done

# Check Python modules
if python3 -c "import flask" &>/dev/null; then
    pass "Python flask module available"
else
    fail "Python flask module not available"
fi

if python3 -c "from PIL import Image" &>/dev/null; then
    pass "Python Pillow module available"
else
    warn "Python Pillow module not available (image validation may fail)"
fi

echo ""

# -----------------------------------------------------------------------
# 10. Network / mDNS
# -----------------------------------------------------------------------
echo "--- Network ---"

if systemctl is-active avahi-daemon &>/dev/null; then
    pass "Avahi (mDNS) daemon is active"
else
    warn "Avahi (mDNS) daemon is not active"
fi

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$IP_ADDR" ]; then
    pass "Network IP: $IP_ADDR"
else
    warn "No network IP detected"
fi

echo ""

# -----------------------------------------------------------------------
# 11. Permissions
# -----------------------------------------------------------------------
echo "--- Permissions ---"

if [ -d "/var/lib/framecast" ]; then
    pass "State directory exists: /var/lib/framecast"
else
    warn "State directory missing: /var/lib/framecast"
fi

if [ -f /etc/sudoers.d/framecast ]; then
    pass "Sudoers file exists for service control"
else
    warn "Sudoers file missing (/etc/sudoers.d/framecast)"
fi

echo ""

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
TOTAL=$((PASS + FAIL + WARN))
echo "========================================"
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings (of $TOTAL checks)"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  CRITICAL: Some checks failed. Review the output above."
    echo "  Try re-running the installer: sudo bash install.sh"
    exit 2
elif [ "$WARN" -gt 0 ]; then
    echo ""
    echo "  All critical checks passed with some warnings."
    exit 1
else
    echo ""
    echo "  All checks passed. Installation looks good."
    exit 0
fi
