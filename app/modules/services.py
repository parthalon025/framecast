"""System service control for FrameCast.

Manages systemd services: status checks, restarts, and bulk status queries.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

# Logical name -> systemd unit name
SERVICE_MAP: dict[str, str] = {
    "app": "framecast",
    "kiosk": "framecast-kiosk",
    "update": "framecast-update",
}


def is_service_active(name: str) -> bool:
    """Check if a systemd service is active by logical name.

    Args:
        name: Logical service name (key in SERVICE_MAP) or raw unit name.

    Returns:
        True if the service is active, False otherwise.
    """
    unit = SERVICE_MAP.get(name, name)
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        log.warning("Failed to check service %s", unit, exc_info=True)
        return False


def restart_service(name: str) -> tuple[bool, str]:
    """Restart a systemd service by logical name.

    Args:
        name: Logical service name (key in SERVICE_MAP) or raw unit name.

    Returns:
        Tuple of (success: bool, message: str).
    """
    unit = SERVICE_MAP.get(name, name)
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", unit],
            check=True,
            capture_output=True,
            timeout=10,
        )
        log.info("Service %s (%s) restarted", name, unit)
        return True, f"Service {name} restarted"
    except subprocess.CalledProcessError as exc:
        log.error("Failed to restart %s: %s", unit, exc.stderr)
        return False, f"Failed to restart {name}"
    except subprocess.TimeoutExpired:
        log.error("Timeout restarting %s", unit)
        return False, f"Timeout restarting {name}"


def all_service_status() -> dict[str, bool]:
    """Return status of all known services.

    Returns:
        Dict mapping logical name to bool (active or not).
    """
    return {name: is_service_active(name) for name in SERVICE_MAP}


# --- Backward-compatible aliases ---

def is_slideshow_running() -> bool:
    """Check if the kiosk/slideshow service is active."""
    return is_service_active("kiosk")


def restart_slideshow() -> tuple[bool, str]:
    """Restart the kiosk/slideshow service. Returns (success, message)."""
    return restart_service("kiosk")
