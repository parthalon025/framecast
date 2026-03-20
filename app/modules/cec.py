"""HDMI-CEC TV control via cec-ctl (v4l-utils).

Uses cec-ctl from v4l-utils, NOT cec-client (broken on Bookworm/Pi 5).
All functions are designed for graceful degradation — return False/unknown
on failure, never raise.

Reference: docs/plans/2026-03-19-v2-polish-research.md § 2a
"""

import logging
import re
import subprocess

log = logging.getLogger(__name__)
_TIMEOUT = 5

# CEC power status patterns (compiled once)
_CEC_STATUS_ON = re.compile(r"\bpwr-status:\s*on\b", re.IGNORECASE)
_CEC_STATUS_STANDBY = re.compile(r"\bpwr-status:\s*standby\b", re.IGNORECASE)


def _cec_cmd(args, timeout=_TIMEOUT):
    """Run cec-ctl command, return stdout or None on failure."""
    cmd = ["cec-ctl"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            log.warning(
                "CEC command failed: %s → %s",
                " ".join(cmd),
                result.stderr.strip(),
            )
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        log.warning(
            "CEC command timed out after %ds: %s", timeout, " ".join(cmd)
        )
        return None
    except FileNotFoundError:
        log.warning("cec-ctl not found — CEC disabled")
        return None
    except Exception as exc:
        log.warning("CEC command error: %s — %s", " ".join(cmd), exc)
        return None


def tv_power_on():
    """Power on TV via CEC Image View On command."""
    out = _cec_cmd(["--playback", "-t0", "--image-view-on"])
    return out is not None


def tv_standby():
    """Put TV into standby via CEC."""
    out = _cec_cmd(["--playback", "-t0", "--standby"])
    return out is not None


def tv_status():
    """Query TV power status. Returns 'on', 'standby', or 'unknown'."""
    out = _cec_cmd(["-d0", "--give-device-power-status"])
    if out is None:
        return "unknown"
    if _CEC_STATUS_ON.search(out):
        return "on"
    if _CEC_STATUS_STANDBY.search(out):
        return "standby"
    log.debug("CEC: unrecognized status output: %s", out.strip())
    return "unknown"


def set_active_source():
    """Set Pi as active HDMI source."""
    out = _cec_cmd(
        ["--playback", "-t0", "--active-source", "phys-addr=1.0.0.0"]
    )
    return out is not None


def init_cec():
    """Query current TV state on startup (Lesson #7 — don't assume).

    Returns the detected TV power status string.
    """
    status = tv_status()
    log.info("CEC INIT: TV power status is %s", status.upper())
    if status == "unknown":
        log.warning(
            "CEC: TV not responding — will retry on first schedule trigger"
        )
    return status
