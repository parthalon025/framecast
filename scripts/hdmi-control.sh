#!/bin/bash
# hdmi-control.sh — Turn HDMI output on/off using wlr-randr (Wayland).
#
# Usage: hdmi-control.sh on|off
#
# Designed for Pi running cage (Wayland kiosk compositor).
# HDMI-A-1 is the standard output name for Raspberry Pi HDMI on Wayland.
set -euo pipefail

ACTION="${1:-}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): HDMI: $*"; }

case "$ACTION" in
    off)
        log "Turning HDMI off..."
        wlr-randr --output HDMI-A-1 --off
        ;;
    on)
        log "Turning HDMI on..."
        wlr-randr --output HDMI-A-1 --on
        ;;
    *)
        echo "Usage: $0 on|off" >&2
        exit 1
        ;;
esac
