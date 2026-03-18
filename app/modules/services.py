"""System service control - slideshow status, restart, reboot."""

import logging
import subprocess

log = logging.getLogger(__name__)


def is_slideshow_running():
    """Check if the slideshow systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "slideshow"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def restart_slideshow():
    """Restart the slideshow service. Returns (success, message)."""
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "slideshow"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        log.info("Slideshow restarted via web UI")
        return True, "Slideshow restarted"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.error("Failed to restart slideshow")
        return False, "Failed to restart slideshow"
