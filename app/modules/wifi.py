"""WiFi provisioning via NetworkManager (nmcli).

Provides station/AP mode control for Raspberry Pi WiFi setup.
All subprocess calls use timeout=15 to prevent hangs.
"""

import logging
import re
import subprocess

log = logging.getLogger(__name__)

_TIMEOUT = 15


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


def start_ap(ssid=None):
    """Start WiFi hotspot AP.

    SSID defaults to FrameCast-XXXX (last 4 of MAC).

    Args:
        ssid: Optional custom AP SSID.

    Returns:
        Tuple of (success: bool, message: str).
    """
    if ssid is None:
        ssid = get_ap_ssid()

    log.info("Starting AP mode with SSID '%s'", ssid)

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
        log.info("AP started: %s", ssid)
        return True, f"AP STARTED: {ssid}"
    log.error("Failed to start AP: %s", stderr or stdout)
    return False, f"AP START FAILED: {(stderr or stdout)[:80]}"


def stop_ap():
    """Stop the WiFi hotspot and return to station mode.

    Returns:
        Tuple of (success: bool, message: str).
    """
    log.info("Stopping AP mode")
    rc, stdout, stderr = _run(["nmcli", "connection", "down", "Hotspot"])
    if rc == 0:
        log.info("AP stopped")
        return True, "AP STOPPED"
    log.error("Failed to stop AP: %s", stderr or stdout)
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
