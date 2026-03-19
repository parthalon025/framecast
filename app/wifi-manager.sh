#!/bin/bash
# wifi-manager.sh - WiFi AP fallback for Pi Photo Display
#
# When the Pi cannot connect to a configured WiFi network, this script
# creates a "PiPhotoFrame" hotspot so users can connect directly and
# upload photos via the web UI at http://192.168.4.1:8080
#
# Supports two backends:
#   1. nmcli (NetworkManager) - default on Pi OS Bookworm and later
#   2. hostapd + dnsmasq     - fallback for Pi OS Bullseye and older
#
# Designed to run as a systemd service (wifi-manager.service).
# The main loop checks connectivity every 30 seconds and switches
# between client mode and AP mode as needed.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IFACE="wlan0"
AP_SSID="PiPhotoFrame"
AP_PASS="photoframe"
AP_IP="192.168.4.1"
AP_SUBNET="192.168.4.0/24"
AP_DHCP_START="192.168.4.10"
AP_DHCP_END="192.168.4.50"
AP_CHANNEL="6"
NM_CON_NAME="PiPhotoFrame-AP"

# How long (seconds) to wait for a WiFi connection before switching to AP
CONNECT_TIMEOUT=30
# How often (seconds) to re-check connectivity while in AP mode
AP_CHECK_INTERVAL=60

LOGPREFIX="[wifi-manager]"
HOSTAPD_CONF="/tmp/piphoto-hostapd.conf"
DNSMASQ_CONF="/tmp/piphoto-dnsmasq.conf"

# Track current mode: "client" or "ap"
CURRENT_MODE="client"
SLEEP_PID=""

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { echo "$LOGPREFIX $*"; }
warn() { echo "$LOGPREFIX WARNING: $*" >&2; }

# ---------------------------------------------------------------------------
# Detect backend: nmcli (NetworkManager) or hostapd/dnsmasq
# ---------------------------------------------------------------------------
use_nmcli() {
    command -v nmcli &>/dev/null && systemctl is-active --quiet NetworkManager 2>/dev/null
}

# ---------------------------------------------------------------------------
# Connectivity check - does wlan0 have a routable IP?
# ---------------------------------------------------------------------------
has_wifi_ip() {
    local ip
    ip=$(ip -4 addr show "$IFACE" 2>/dev/null \
         | grep -oP 'inet \K[0-9.]+' \
         | head -1 || true)
    # In AP mode wlan0 has 192.168.4.1 - that does not count as "connected"
    if [ -n "$ip" ] && [ "$ip" != "$AP_IP" ]; then
        return 0
    fi
    return 1
}

# Quick internet / gateway reachability test
can_reach_gateway() {
    local gw
    gw=$(ip route show default dev "$IFACE" 2>/dev/null | awk '{print $3}' | head -1 || true)
    if [ -n "$gw" ]; then
        ping -c1 -W2 "$gw" &>/dev/null && return 0
    fi
    return 1
}

is_connected() {
    has_wifi_ip && can_reach_gateway
}

# ---------------------------------------------------------------------------
# Wait for WiFi client connection (up to CONNECT_TIMEOUT seconds)
# ---------------------------------------------------------------------------
wait_for_wifi() {
    log "Waiting up to ${CONNECT_TIMEOUT}s for WiFi connection on $IFACE..."
    local elapsed=0
    while [ "$elapsed" -lt "$CONNECT_TIMEOUT" ]; do
        if is_connected; then
            local ip
            ip=$(ip -4 addr show "$IFACE" | grep -oP 'inet \K[0-9.]+' | head -1)
            log "Connected to WiFi - IP: $ip"
            return 0
        fi
        safe_sleep 5
        elapsed=$((elapsed + 5))
    done
    log "No WiFi connection after ${CONNECT_TIMEOUT}s."
    return 1
}

# ---------------------------------------------------------------------------
# AP mode - NetworkManager (nmcli) backend
# ---------------------------------------------------------------------------
nmcli_start_ap() {
    log "Starting AP hotspot via NetworkManager..."

    # Remove any previous AP connection with this name
    nmcli connection delete "$NM_CON_NAME" 2>/dev/null || true

    # Create and activate a hotspot
    # 802-11-wireless.band bg = 2.4 GHz, channel from config
    nmcli connection add \
        type wifi \
        ifname "$IFACE" \
        con-name "$NM_CON_NAME" \
        autoconnect no \
        ssid "$AP_SSID" \
        -- \
        wifi.mode ap \
        wifi.band bg \
        wifi.channel "$AP_CHANNEL" \
        ipv4.method shared \
        ipv4.addresses "${AP_IP}/24" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$AP_PASS" \
        2>/dev/null

    nmcli connection up "$NM_CON_NAME" 2>/dev/null

    CURRENT_MODE="ap"
    log "AP hotspot '$AP_SSID' active at $AP_IP (password: ***)"
    log "Web upload available at http://${AP_IP}:8080"
}

nmcli_stop_ap() {
    log "Stopping AP hotspot (NetworkManager)..."
    nmcli connection down "$NM_CON_NAME" 2>/dev/null || true
    nmcli connection delete "$NM_CON_NAME" 2>/dev/null || true
    CURRENT_MODE="client"
}

nmcli_reconnect_wifi() {
    log "Attempting to reconnect to a known WiFi network..."
    nmcli_stop_ap
    # Let NetworkManager auto-connect to a known network
    nmcli device set "$IFACE" autoconnect yes 2>/dev/null || true
    nmcli device connect "$IFACE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# AP mode - hostapd + dnsmasq backend (fallback)
# ---------------------------------------------------------------------------
hostapd_start_ap() {
    log "Starting AP hotspot via hostapd + dnsmasq..."

    # Stop any running instances
    hostapd_stop_ap 2>/dev/null || true

    # Bring interface down, assign static IP
    ip link set "$IFACE" down 2>/dev/null || true
    ip addr flush dev "$IFACE" 2>/dev/null || true
    ip addr add "${AP_IP}/24" dev "$IFACE"
    ip link set "$IFACE" up

    # Write hostapd config
    cat > "$HOSTAPD_CONF" << EOF
interface=$IFACE
driver=nl80211
ssid=$AP_SSID
hw_mode=g
channel=$AP_CHANNEL
wmm_enabled=0
macaddr_acl=0
auth_algs=1
wpa=2
wpa_passphrase=$AP_PASS
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

    # Write dnsmasq config
    cat > "$DNSMASQ_CONF" << EOF
interface=$IFACE
bind-interfaces
dhcp-range=${AP_DHCP_START},${AP_DHCP_END},255.255.255.0,24h
dhcp-option=3,$AP_IP
dhcp-option=6,$AP_IP
log-queries
log-dhcp
EOF

    # Start hostapd in background
    hostapd -B "$HOSTAPD_CONF" 2>/dev/null
    # Start dnsmasq with our config (separate instance)
    dnsmasq -C "$DNSMASQ_CONF" --pid-file=/tmp/piphoto-dnsmasq.pid 2>/dev/null

    CURRENT_MODE="ap"
    log "AP hotspot '$AP_SSID' active at $AP_IP (password: ***)"
    log "Web upload available at http://${AP_IP}:8080"
}

hostapd_stop_ap() {
    log "Stopping AP hotspot (hostapd + dnsmasq)..."

    # Kill our hostapd instance
    if pgrep -f "hostapd.*$HOSTAPD_CONF" &>/dev/null; then
        pkill -f "hostapd.*$HOSTAPD_CONF" 2>/dev/null || true
    fi

    # Kill our dnsmasq instance
    if [ -f /tmp/piphoto-dnsmasq.pid ]; then
        kill "$(cat /tmp/piphoto-dnsmasq.pid)" 2>/dev/null || true
        rm -f /tmp/piphoto-dnsmasq.pid
    fi

    # Flush the static IP
    ip addr flush dev "$IFACE" 2>/dev/null || true

    rm -f "$HOSTAPD_CONF" "$DNSMASQ_CONF"
    CURRENT_MODE="client"
}

hostapd_reconnect_wifi() {
    log "Attempting to reconnect to a known WiFi network..."
    hostapd_stop_ap

    # Restart wpa_supplicant to reconnect
    ip link set "$IFACE" up 2>/dev/null || true
    systemctl restart wpa_supplicant 2>/dev/null || true

    # If dhcpcd is used (Pi OS Bullseye)
    if systemctl is-enabled dhcpcd 2>/dev/null; then
        systemctl restart dhcpcd 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Unified start/stop functions (pick backend automatically)
# ---------------------------------------------------------------------------
start_ap() {
    if use_nmcli; then
        nmcli_start_ap
    else
        hostapd_start_ap
    fi
}

stop_ap() {
    if use_nmcli; then
        nmcli_stop_ap
    else
        hostapd_stop_ap
    fi
}

reconnect_wifi() {
    if use_nmcli; then
        nmcli_reconnect_wifi
    else
        hostapd_reconnect_wifi
    fi
}

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
    log "Shutting down wifi-manager..."
    [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null || true
    if [ "$CURRENT_MODE" = "ap" ]; then
        stop_ap
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT EXIT

# Signal-safe sleep: sleep in background so signals are caught immediately
# (same pattern as slideshow.sh)
safe_sleep() {
    sleep "$1" &
    SLEEP_PID=$!
    wait "$SLEEP_PID" 2>/dev/null || true
    SLEEP_PID=""
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
main() {
    log "Starting wifi-manager (interface: $IFACE)"

    if use_nmcli; then
        log "Backend: NetworkManager (nmcli)"
    else
        log "Backend: hostapd + dnsmasq (legacy)"
    fi

    while true; do
        case "$CURRENT_MODE" in
            client)
                # In client mode - check if we still have connectivity
                if is_connected; then
                    # All good, check again later
                    safe_sleep "$AP_CHECK_INTERVAL"
                else
                    # Lost connection (or never had one) - try to reconnect
                    if ! wait_for_wifi; then
                        # Could not connect - switch to AP mode
                        start_ap
                    fi
                fi
                ;;

            ap)
                # In AP mode - periodically check if a known WiFi is available
                safe_sleep "$AP_CHECK_INTERVAL"
                log "Checking if a known WiFi network is now available..."

                if use_nmcli; then
                    # Ask NetworkManager to scan
                    nmcli device wifi rescan ifname "$IFACE" 2>/dev/null || true
                    safe_sleep 5

                    # Check if any known/saved connection is in range
                    # List saved connections that are wifi type
                    local known_ssids
                    known_ssids=$(nmcli -t -f NAME,TYPE connection show \
                                  | grep ':.*wireless' \
                                  | grep -v "$NM_CON_NAME" \
                                  | cut -d: -f1 || true)

                    if [ -z "$known_ssids" ]; then
                        # No saved WiFi networks besides our AP - stay in AP mode
                        continue
                    fi

                    # Check if any known SSID is visible in scan results
                    local visible
                    visible=$(nmcli -t -f SSID device wifi list ifname "$IFACE" 2>/dev/null || true)

                    local found=false
                    while IFS= read -r ssid; do
                        if echo "$visible" | grep -qF "$ssid"; then
                            found=true
                            break
                        fi
                    done <<< "$known_ssids"

                    if $found; then
                        log "Known WiFi network found - switching back to client mode"
                        reconnect_wifi
                        safe_sleep 10
                        if ! wait_for_wifi; then
                            # Failed to connect - go back to AP
                            start_ap
                        fi
                    fi
                else
                    # hostapd backend: try to reconnect and see if it works
                    # We do this less aggressively to avoid disrupting AP clients
                    # Only attempt every 5th check (every ~5 minutes)
                    if [ -f /tmp/piphoto-ap-check-count ]; then
                        local count
                        count=$(cat /tmp/piphoto-ap-check-count)
                        count=$((count + 1))
                        if [ "$count" -ge 5 ]; then
                            echo 0 > /tmp/piphoto-ap-check-count
                            log "Attempting WiFi reconnection (periodic check)..."
                            reconnect_wifi
                            safe_sleep 15
                            if ! wait_for_wifi; then
                                start_ap
                            fi
                        else
                            echo "$count" > /tmp/piphoto-ap-check-count
                        fi
                    else
                        echo 1 > /tmp/piphoto-ap-check-count
                    fi
                fi
                ;;
        esac
    done
}

main "$@"
