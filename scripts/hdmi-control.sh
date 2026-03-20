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

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): HDMI: $*"; }

case "$ACTION" in
  on)
    HDMI_OUTPUT=$(wlr-randr 2>/dev/null | grep -Eo 'HDMI-[^ ]+' | head -1 || true)
    HDMI_OUTPUT="${HDMI_OUTPUT:-HDMI-A-1}"
    if OUTPUT=$(cec-ctl --playback -t0 --image-view-on 2>&1); then
      log "CEC: TV powered on"
    elif [ -n "$HDMI_OUTPUT" ]; then
      log "CEC: failed — $OUTPUT"
      wlr-randr --output "$HDMI_OUTPUT" --on
      log "FALLBACK: wlr-randr enabled $HDMI_OUTPUT"
    else
      log "ERROR: No CEC or HDMI output available"
      exit 1
    fi
    ;;
  off)
    HDMI_OUTPUT=$(wlr-randr 2>/dev/null | grep -Eo 'HDMI-[^ ]+' | head -1 || true)
    HDMI_OUTPUT="${HDMI_OUTPUT:-HDMI-A-1}"
    if OUTPUT=$(cec-ctl --playback -t0 --standby 2>&1); then
      log "CEC: TV standby"
    elif [ -n "$HDMI_OUTPUT" ]; then
      log "CEC: failed — $OUTPUT"
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
    # Check if schedule is enabled
    SCHEDULE_ENABLED="${HDMI_SCHEDULE_ENABLED:-no}"
    if [[ "$SCHEDULE_ENABLED" != "yes" ]]; then
      exit 0
    fi

    # Day-of-week check (0=Sunday, 6=Saturday)
    SCHEDULE_DAYS="${DISPLAY_SCHEDULE_DAYS:-0,1,2,3,4,5,6}"
    TODAY_DOW=$(date +%w)
    if [[ ",$SCHEDULE_DAYS," != *",$TODAY_DOW,"* ]]; then
      exit 0  # Not a scheduled day
    fi

    ON_TIME="${HDMI_ON_TIME:-08:00}"
    OFF_TIME="${HDMI_OFF_TIME:-22:00}"
    to_minutes() { IFS=: read -r h m <<< "$1"; echo $(( 10#$h * 60 + 10#$m )); }
    NOW_M=$(to_minutes "$(date +%H:%M)")
    ON_M=$(to_minutes "$ON_TIME")
    OFF_M=$(to_minutes "$OFF_TIME")

    # Handle overnight ranges (e.g., ON=20:00, OFF=06:00)
    if [[ $ON_M -le $OFF_M ]]; then
      # Normal range (e.g., 08:00-22:00)
      [[ $NOW_M -ge $ON_M && $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
    else
      # Overnight range (e.g., 20:00-06:00)
      [[ $NOW_M -ge $ON_M || $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
    fi
    ;;
  *)
    echo "Usage: $0 {on|off|status|check-schedule}" >&2
    exit 1
    ;;
esac
