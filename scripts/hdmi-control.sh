#!/usr/bin/env bash
# hdmi-control.sh — HDMI display control, CEC-first with wlr-randr fallback.
#
# Usage: hdmi-control.sh {on|off|status|check-schedule}
#
# CEC via cec-ctl (v4l-utils). Falls back to wlr-randr if CEC unavailable.
# Research: docs/plans/2026-03-19-v2-polish-research.md § 2a
set -euo pipefail

ACTION="${1:-}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

# Auto-detect HDMI output name for wlr-randr fallback
HDMI_OUTPUT=$(wlr-randr 2>/dev/null | grep -oP 'HDMI-\S+' | head -1 || true)
HDMI_OUTPUT="${HDMI_OUTPUT:-HDMI-A-1}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): HDMI: $*"; }

case "$ACTION" in
  on)
    if cec-ctl --playback -t0 --image-view-on 2>/dev/null; then
      log "CEC: TV powered on"
    elif [ -n "$HDMI_OUTPUT" ]; then
      wlr-randr --output "$HDMI_OUTPUT" --on
      log "FALLBACK: wlr-randr enabled $HDMI_OUTPUT"
    else
      log "ERROR: No CEC or HDMI output available"
      exit 1
    fi
    ;;
  off)
    if cec-ctl --playback -t0 --standby 2>/dev/null; then
      log "CEC: TV standby"
    elif [ -n "$HDMI_OUTPUT" ]; then
      wlr-randr --output "$HDMI_OUTPUT" --off
      log "FALLBACK: wlr-randr disabled $HDMI_OUTPUT"
    else
      log "ERROR: No CEC or HDMI output available"
      exit 1
    fi
    ;;
  status)
    if cec-ctl -d0 --give-device-power-status 2>/dev/null; then
      true  # cec-ctl already printed status
    else
      log "CEC: unavailable"
    fi
    ;;
  check-schedule)
    ON_TIME="${DISPLAY_ON_TIME:-07:00}"
    OFF_TIME="${DISPLAY_OFF_TIME:-23:00}"
    NOW=$(date +%H:%M)
    if [[ "$NOW" > "$ON_TIME" || "$NOW" == "$ON_TIME" ]] && [[ "$NOW" < "$OFF_TIME" ]]; then
      "$0" on
    else
      "$0" off
    fi
    ;;
  *)
    echo "Usage: $0 {on|off|status|check-schedule}" >&2
    exit 1
    ;;
esac
