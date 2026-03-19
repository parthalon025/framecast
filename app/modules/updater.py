"""OTA update module — checks GitHub Releases and applies updates.

Uses urllib.request (stdlib only) to query the GitHub API.  All subprocess
calls carry timeouts and log errors before returning fallback values.
"""

import json
import logging
import re
import subprocess
import urllib.request
from pathlib import Path

from modules import config

log = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"
INSTALL_DIR = VERSION_FILE.parent
ROLLBACK_FILE = Path("/tmp/framecast-rollback-tag")
# Configurable via .env for forks. Default: official FrameCast repo.
_GITHUB_OWNER = config.get("GITHUB_OWNER", "parthalon025")
_GITHUB_REPO = config.get("GITHUB_REPO", "framecast")
GITHUB_API_URL = (
    f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest"
)
_SUBPROCESS_TIMEOUT = 30
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def validate_tag(tag: str) -> bool:
    """Return True if *tag* matches the expected release tag format (vX.Y.Z)."""
    return bool(_TAG_RE.match(tag))


def get_current_version() -> str:
    """Read version from VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        log.error("Failed to read VERSION file at %s", VERSION_FILE)
        return "0.0.0"


def check_for_update() -> dict:
    """Check GitHub Releases API for a newer version.

    Returns:
        {"available": bool, "current": str, "latest": str, "url": str}
    """
    current = get_current_version()
    result = {
        "available": False,
        "current": current,
        "latest": current,
        "url": "",
    }

    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "FrameCast-Updater",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        html_url = data.get("html_url", "")

        if not tag:
            log.warning("GitHub release response missing tag_name")
            return result

        result["latest"] = tag.lstrip("v")
        result["url"] = html_url

        # Compare stripped semver strings (e.g. "1.0.0" vs "1.1.0")
        if _version_newer(tag.lstrip("v"), current):
            result["available"] = True

    except urllib.error.HTTPError as exc:
        log.error("GitHub API HTTP error: %s %s", exc.code, exc.reason)
    except urllib.error.URLError as exc:
        log.error("GitHub API URL error: %s", exc.reason)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.error("Failed to parse GitHub release response: %s", exc)

    return result


def apply_update(tag: str) -> tuple:
    """Apply update: git fetch, git checkout <tag>.

    Saves current version tag to ``/tmp/framecast-rollback-tag`` before
    switching so the health-check script can roll back on failure.

    Returns:
        (success: bool, message: str)
    """
    if not _TAG_RE.match(tag):
        return False, f"Invalid tag format: {tag}"

    current = get_current_version()

    # Save rollback tag
    try:
        ROLLBACK_FILE.write_text(f"v{current}")
        log.info("Saved rollback tag v%s to %s", current, ROLLBACK_FILE)
    except OSError as exc:
        log.error("Failed to write rollback file: %s", exc)
        return False, f"Failed to save rollback tag: {exc}"

    # Fetch latest tags
    ok, msg = _git("fetch", "--tags")
    if not ok:
        return False, f"git fetch failed: {msg}"

    # Checkout the target tag
    ok, msg = _git("checkout", tag)
    if not ok:
        return False, f"git checkout {tag} failed: {msg}"

    log.info("Update applied: v%s -> %s", current, tag)
    return True, f"Updated from v{current} to {tag}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(*args) -> tuple:
    """Run a git command inside INSTALL_DIR.

    Returns:
        (success: bool, output_or_error: str)
    """
    cmd = ["git", "-C", str(INSTALL_DIR), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            log.error("git %s failed (rc=%d): %s", args, result.returncode, result.stderr.strip())
            return False, result.stderr.strip() or result.stdout.strip()
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.error("git %s timed out after %ds", args, _SUBPROCESS_TIMEOUT)
        return False, f"Timed out after {_SUBPROCESS_TIMEOUT}s"
    except OSError as exc:
        log.error("git %s OS error: %s", args, exc)
        return False, str(exc)


def _version_newer(latest: str, current: str) -> bool:
    """Return True if *latest* is strictly newer than *current*.

    Both should be bare semver strings (no leading 'v').
    Falls back to lexicographic comparison if parsing fails.
    """
    try:
        latest_parts = tuple(int(x) for x in latest.split("."))
        current_parts = tuple(int(x) for x in current.split("."))
        return latest_parts > current_parts
    except (ValueError, TypeError):
        log.warning("Semver parse failed (latest=%r, current=%r), falling back to string comparison", latest, current)
        return latest > current
