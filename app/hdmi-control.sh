#!/bin/bash
# hdmi-control.sh - Turn HDMI output on/off on Raspberry Pi
# Usage: hdmi-control.sh [on|off|status]
set -euo pipefail

log() { echo "$(date): HDMI: $*"; }

case "${1:-}" in
    off)
        log "Turning HDMI off..."
        if command -v vcgencmd &>/dev/null; then
            vcgencmd display_power 0
        elif command -v tvservice &>/dev/null; then
            tvservice -o
        elif command -v xrandr &>/dev/null; then
            HDMI_OUTPUT=$(xrandr --query | grep ' connected' | head -1 | awk '{print $1}')
            xrandr --output "${HDMI_OUTPUT:-HDMI-1}" --off
        else
            log "ERROR: No display control command found" >&2
            exit 1
        fi
        ;;
    on)
        log "Turning HDMI on..."
        if command -v vcgencmd &>/dev/null; then
            vcgencmd display_power 1
        elif command -v tvservice &>/dev/null; then
            tvservice -p
            fbset -depth 8 2>/dev/null || true
            fbset -depth 16 2>/dev/null || true
        elif command -v xrandr &>/dev/null; then
            HDMI_OUTPUT=$(xrandr --query | grep ' connected' | head -1 | awk '{print $1}')
            xrandr --output "${HDMI_OUTPUT:-HDMI-1}" --auto
        else
            log "ERROR: No display control command found" >&2
            exit 1
        fi
        ;;
    status)
        if command -v vcgencmd &>/dev/null; then
            vcgencmd display_power
        elif command -v tvservice &>/dev/null; then
            tvservice -s
        else
            log "Unknown" >&2
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {on|off|status}" >&2
        exit 1
        ;;
esac
