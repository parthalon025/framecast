"""WiFi provisioning via NetworkManager (nmcli).

Provides station/AP mode control for Raspberry Pi WiFi setup.
All subprocess calls use timeout=15 to prevent hangs.
"""

import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from modules import config

log = logging.getLogger(__name__)

_TIMEOUT = 15

# AP auto-timeout: restart AP if no client connects within this window (seconds)
_AP_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
_ap_timer = None
_ap_timer_lock = threading.Lock()

# Marker file to persist AP start time across restarts
_AP_MARKER_FILE = Path(config.get("MEDIA_DIR", "/home/pi/media")).parent / ".ap_started"


def _write_ap_marker():
    """Write current timestamp to AP marker file."""
    try:
        _AP_MARKER_FILE.write_text(str(time.time()))
    except OSError as exc:
        log.warning("Failed to write AP marker: %s", exc)


def _clear_ap_marker():
    """Remove AP marker file."""
    try:
        _AP_MARKER_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def check_stale_ap(timeout_minutes=30):
    """Check if AP has been running longer than timeout. Stop if stale.

    Called at startup to handle the case where the service crashed
    while AP was active and the in-memory timer was lost.
    """
    if not _AP_MARKER_FILE.exists():
        return
    try:
        started = float(_AP_MARKER_FILE.read_text().strip())
        elapsed = time.time() - started
        if elapsed > timeout_minutes * 60:
            log.warning(
                "AP has been running %.0f minutes (limit: %d). Stopping.",
                elapsed / 60,
                timeout_minutes,
            )
            stop_ap()
        else:
            # Still within timeout — restart the timer for remaining time
            remaining = timeout_minutes * 60 - elapsed
            log.info(
                "AP running for %.0f minutes, %.0f remaining. Restarting timer.",
                elapsed / 60,
                remaining / 60,
            )
            _start_ap_timer(remaining)
    except (ValueError, OSError) as exc:
        log.warning("Failed to read AP marker: %s. Clearing.", exc)
        _clear_ap_marker()


def _redact_password(cmd):
    """Return a copy of *cmd* with the argument after 'password' replaced by '***'."""
    redacted = list(cmd)
    for i, arg in enumerate(redacted):
        if arg == "password" and i + 1 < len(redacted):
            redacted[i + 1] = "***"
    return redacted


def _run(cmd, timeout=_TIMEOUT):
    """Run a subprocess command, returning (returncode, stdout, stderr).

    Logs errors and never swallows exceptions silently.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        log.error("Command timed out after %ds: %s", timeout, _redact_password(cmd))
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        log.error("Command not found: %s", cmd[0])
        return -1, "", f"Command not found: {cmd[0]}"
    except OSError as exc:
        log.error("OS error running %s: %s", _redact_password(cmd), exc)
        return -1, "", str(exc)


def is_connected():
    """Check if WiFi is connected to a network."""
    rc, stdout, _ = _run(["nmcli", "-t", "-f", "GENERAL.STATE", "dev", "show", "wlan0"])
    if rc != 0:
        return False
    # GENERAL.STATE:100 (connected) or similar
    return "connected" in stdout.lower() and "disconnected" not in stdout.lower()


def get_current_ssid():
    """Get currently connected SSID, or None."""
    rc, stdout, _ = _run(
        ["nmcli", "-t", "-f", "GENERAL.CONNECTION", "dev", "show", "wlan0"]
    )
    if rc != 0:
        return None
    # Output: GENERAL.CONNECTION:MyNetwork
    parts = stdout.split(":", 1)
    if len(parts) == 2 and parts[1] and parts[1] != "--":
        return parts[1]
    return None


def scan_networks():
    """Scan for available WiFi networks.

    Returns:
        List of dicts: [{"ssid": str, "signal": int, "security": str}].
        Signal is 0-100 (percentage).
    """
    rc, stdout, stderr = _run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"]
    )
    if rc != 0:
        log.error("WiFi scan failed: %s", stderr)
        return []

    networks = []
    seen_ssids = set()
    for line in stdout.splitlines():
        # nmcli -t uses ':' as separator but escapes literal colons in
        # values as '\:'.  Split on unescaped colons only (max 3 fields:
        # SSID, SIGNAL, SECURITY).
        parts = re.split(r"(?<!\\):", line, maxsplit=2)
        if len(parts) < 3:
            continue
        # Unescape literal colons in each field
        ssid = parts[0].replace("\\:", ":")
        if not ssid or ssid in seen_ssids:
            continue
        try:
            signal = int(parts[1].replace("\\:", ":"))
        except (ValueError, IndexError):
            signal = 0
        security = parts[2].replace("\\:", ":") if len(parts) > 2 else ""
        seen_ssids.add(ssid)
        networks.append({
            "ssid": ssid,
            "signal": signal,
            "security": security,
        })

    # Sort by signal strength descending
    networks.sort(key=lambda net: net["signal"], reverse=True)
    return networks


def connect(ssid, password):
    """Connect to a WiFi network.

    Args:
        ssid: Network SSID.
        password: Network password.

    Returns:
        Tuple of (success: bool, message: str).
    """
    log.info("Attempting WiFi connection to '%s'", ssid)
    cmd = ["nmcli", "dev", "wifi", "connect", ssid, "password", password]
    rc, stdout, stderr = _run(cmd, timeout=30)
    if rc == 0:
        log.info("Connected to WiFi network '%s'", ssid)
        return True, f"Connected to {ssid}"
    log.error("Failed to connect to '%s': %s", ssid, stderr or stdout)
    # Parse common nmcli error messages
    error_msg = stderr or stdout
    if "secrets were required" in error_msg.lower() or "no suitable" in error_msg.lower():
        return False, "AUTH FAILED — CHECK PASSWORD"
    if "no network" in error_msg.lower():
        return False, "NETWORK NOT FOUND"
    return False, f"CONNECTION FAILED: {error_msg[:80]}"


def _cancel_ap_timer():
    """Cancel any pending AP auto-timeout timer."""
    global _ap_timer
    with _ap_timer_lock:
        if _ap_timer is not None:
            _ap_timer.cancel()
            _ap_timer = None


def _has_ap_clients():
    """Check if any clients are connected to the AP."""
    rc, stdout, _ = _run(
        ["nmcli", "-t", "-f", "GENERAL.CLIENTS", "dev", "show", "wlan0"]
    )
    if rc != 0:
        return False
    # Output: GENERAL.CLIENTS:N
    parts = stdout.split(":", 1)
    if len(parts) == 2:
        try:
            return int(parts[1]) > 0
        except (ValueError, IndexError) as exc:
            log.warning("WiFi: failed to parse AP client count: %s", exc)
    return False


def _ap_timeout_handler():
    """Called when AP timeout expires. Restart AP if no clients connected."""
    global _ap_timer
    with _ap_timer_lock:
        _ap_timer = None

    if not is_ap_active():
        log.info("AP timeout fired but AP is no longer active — no action")
        return

    if _has_ap_clients():
        log.info("AP timeout fired but clients are connected — resetting timer")
        _start_ap_timer()
        return

    log.warning("AP timeout: no clients connected in %d minutes — restarting AP",
                _AP_TIMEOUT_SECONDS // 60)
    # Cycle AP to reset state
    stop_ap()
    start_ap()


def _start_ap_timer(seconds=None):
    """Start (or restart) the AP auto-timeout timer.

    Args:
        seconds: Optional override for timer duration. Defaults to _AP_TIMEOUT_SECONDS.
    """
    global _ap_timer
    if seconds is None:
        seconds = _AP_TIMEOUT_SECONDS
    _cancel_ap_timer()
    with _ap_timer_lock:
        _ap_timer = threading.Timer(seconds, _ap_timeout_handler)
        _ap_timer.daemon = True
        _ap_timer.start()
    log.info("AP auto-timeout set: %.0f minutes", seconds / 60)


def start_ap(ssid=None):
    """Start WiFi hotspot AP.

    SSID defaults to FrameCast-XXXX (last 4 of MAC).
    Starts a 30-minute auto-timeout timer that restarts the AP if no
    clients connect.

    Args:
        ssid: Optional custom AP SSID.

    Returns:
        Tuple of (success: bool, message: str).
    """
    if ssid is None:
        ssid = get_ap_ssid()

    log.info("AP STATE: starting with SSID '%s'", ssid)

    # SECURITY TRADEOFF: Open hotspot (no password) for onboarding UX.
    # The user must be physically present to see the SSID on the TV screen.
    # The AP only serves the upload/settings UI on a local subnet — no
    # internet gateway, no stored credentials exposed. Acceptable risk for
    # a device that requires physical access to operate.
    cmd = [
        "nmcli", "dev", "wifi", "hotspot",
        "ifname", "wlan0",
        "ssid", ssid,
        "password", "",
        "band", "bg",
    ]
    rc, stdout, stderr = _run(cmd, timeout=30)
    if rc == 0:
        log.info("AP STATE: started — %s", ssid)
        _write_ap_marker()
        _start_ap_timer()
        return True, f"AP STARTED: {ssid}"
    log.error("AP STATE: start failed — %s", stderr or stdout)
    return False, f"AP START FAILED: {(stderr or stdout)[:80]}"


def stop_ap():
    """Stop the WiFi hotspot and return to station mode.

    Returns:
        Tuple of (success: bool, message: str).
    """
    log.info("AP STATE: stopping")
    _cancel_ap_timer()
    _clear_ap_marker()
    rc, stdout, stderr = _run(["nmcli", "connection", "down", "Hotspot"])
    if rc == 0:
        log.info("AP STATE: stopped")
        return True, "AP STOPPED"
    log.error("AP STATE: stop failed — %s", stderr or stdout)
    return False, f"AP STOP FAILED: {(stderr or stdout)[:80]}"


def get_ap_ssid():
    """Generate AP SSID: FrameCast-XXXX using last 4 of wlan0 MAC."""
    rc, stdout, _ = _run(
        ["nmcli", "-t", "-f", "GENERAL.HWADDR", "dev", "show", "wlan0"]
    )
    if rc == 0 and ":" in stdout:
        # Output: GENERAL.HWADDR:AA:BB:CC:DD:EE:FF
        mac_part = stdout.split(":", 1)[1] if "HWADDR:" in stdout else stdout
        # Get last 4 hex chars (last 2 octets without colons)
        mac_clean = mac_part.replace(":", "")
        suffix = mac_clean[-4:].upper()
        return f"FrameCast-{suffix}"
    return "FrameCast-WIFI"


def is_ap_active():
    """Check if AP mode is currently active."""
    rc, stdout, _ = _run(
        ["nmcli", "-t", "-f", "GENERAL.CONNECTION", "dev", "show", "wlan0"]
    )
    if rc != 0:
        return False
    # When hotspot is active, connection name is "Hotspot"
    return "Hotspot" in stdout
