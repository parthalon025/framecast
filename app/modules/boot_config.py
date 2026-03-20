"""Boot partition config reader for first-boot provisioning.

On startup, checks for:
  1. WiFi config on the boot partition:
     /boot/firmware/framecast-wifi.txt   (Pi OS Bookworm+)
     /boot/framecast-wifi.txt            (Pi OS Bullseye)

     File format (plain text):
       SSID=MyNetwork
       PASSWORD=MyPassword

     If found and connection succeeds, the file is deleted to prevent
     re-reading on subsequent boots.

  2. SSH enable flag on the boot partition (standard Pi convention):
     /boot/firmware/ssh   (Pi OS Bookworm+)
     /boot/ssh            (Pi OS Bullseye)

     If the file exists, SSH is enabled via systemctl and the file is
     deleted. This is the same convention used by Raspberry Pi OS.
"""

import logging
import subprocess
from pathlib import Path

from modules import wifi

log = logging.getLogger(__name__)

_CONFIG_PATHS = [
    Path("/boot/firmware/framecast-wifi.txt"),
    Path("/boot/framecast-wifi.txt"),
]

_SSH_FLAG_PATHS = [
    Path("/boot/firmware/ssh"),
    Path("/boot/ssh"),
]


def _find_config():
    """Find the first existing boot config file, or None."""
    for path in _CONFIG_PATHS:
        if path.exists():
            return path
    return None


def _parse_config(path):
    """Parse SSID and PASSWORD from a boot config file.

    Args:
        path: Path to the config file.

    Returns:
        Tuple of (ssid, password) or (None, None) if parsing fails.
    """
    ssid = None
    password = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().upper()
            value = value.strip().strip("'\"")
            if key == "SSID":
                ssid = value
            elif key == "PASSWORD":
                password = value
    except OSError as exc:
        log.error("Failed to read boot config %s: %s", path, exc)
        return None, None

    return ssid, password


def apply_boot_config():
    """Check for boot partition WiFi config and connect if found.

    Called at Flask app startup. Connects via wifi.connect() and
    deletes the config file on success to prevent re-reading.

    Returns:
        True if a config was found and connection succeeded, False otherwise.
    """
    config_path = _find_config()
    if config_path is None:
        return False

    log.info("Boot WiFi config found: %s", config_path)
    ssid, password = _parse_config(config_path)

    if not ssid:
        log.warning("Boot config at %s has no SSID — skipping", config_path)
        return False

    if password is None:
        password = ""

    success, message = wifi.connect(ssid, password)

    if success:
        log.info("Boot WiFi config applied: connected to '%s'", ssid)
        try:
            config_path.unlink()
            log.info("Boot config file deleted: %s", config_path)
        except OSError as exc:
            log.warning("Failed to delete boot config %s: %s", config_path, exc)
        return True

    log.warning(
        "Boot WiFi config failed for '%s': %s (file preserved for retry)",
        ssid,
        message,
    )
    return False


def apply_boot_ssh():
    """Check for boot partition SSH flag and enable SSH if found.

    Standard Raspberry Pi convention: an empty file named "ssh" on the
    boot partition enables SSH on first boot. The file is deleted after
    enabling to prevent re-enabling on subsequent boots.

    Returns:
        True if SSH was enabled via boot flag, False otherwise.
    """
    flag_path = None
    for path in _SSH_FLAG_PATHS:
        if path.exists():
            flag_path = path
            break

    if flag_path is None:
        return False

    log.info("Boot SSH flag found: %s — enabling SSH", flag_path)
    try:
        subprocess.run(
            ["sudo", "systemctl", "enable", "--now", "ssh"],
            capture_output=True, timeout=10, check=True,
        )
        log.info("SSH enabled via boot partition flag")
    except subprocess.CalledProcessError as exc:
        log.error("Failed to enable SSH from boot flag: %s", exc)
        return False
    except Exception as exc:
        log.error("Failed to enable SSH from boot flag: %s", exc)
        return False

    try:
        flag_path.unlink()
        log.info("Boot SSH flag deleted: %s", flag_path)
    except OSError as exc:
        log.warning("Failed to delete boot SSH flag %s: %s", flag_path, exc)

    return True
