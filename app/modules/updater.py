"""OTA update module — checks GitHub Releases and applies updates.

Uses urllib.request (stdlib only) to query the GitHub API.  All subprocess
calls carry timeouts and log errors before returning fallback values.

Security: after git fetch, the tag's commit SHA is verified against what
the GitHub API reported.  If the SHA does not match (e.g. tag was force-pushed
or MITM), the update is aborted.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from modules import config

log = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"
INSTALL_DIR = VERSION_FILE.parent
ROLLBACK_FILE = Path("/var/lib/framecast/rollback-tag")
ROLLBACK_SIG_FILE = Path("/var/lib/framecast/rollback-sig")
EXPECTED_SHA_FILE = Path("/var/lib/framecast/expected-sha")
# Configurable via .env for forks. Default: official FrameCast repo.
_GITHUB_OWNER = config.get("GITHUB_OWNER", "parthalon025")
_GITHUB_REPO = config.get("GITHUB_REPO", "framecast")
GITHUB_API_URL = (
    f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest"
)
_SUBPROCESS_TIMEOUT = 30
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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
        {"available": bool, "current": str, "latest": str, "url": str,
         "tag_name": str, "target_commitish": str}

    The ``target_commitish`` field is the commit SHA from the GitHub API
    response, used to verify the fetched tag matches expectations.
    """
    current = get_current_version()
    result = {
        "available": False,
        "current": current,
        "latest": current,
        "url": "",
        "tag_name": "",
        "target_commitish": "",
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
        target_commitish = data.get("target_commitish", "")

        if not tag:
            log.warning("GitHub release response missing tag_name")
            return result

        result["latest"] = tag.lstrip("v")
        result["url"] = html_url
        result["tag_name"] = tag
        result["target_commitish"] = target_commitish

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


def _hmac_sign(data: str) -> str:
    """Compute HMAC-SHA256 of *data* using FLASK_SECRET_KEY."""
    secret = config.get("FLASK_SECRET_KEY", "")
    if not secret:
        log.warning("FLASK_SECRET_KEY not set — rollback signature will be weak")
        secret = "framecast-fallback"
    return hmac.new(
        secret.encode(), data.encode(), hashlib.sha256
    ).hexdigest()


def _atomic_write(path: Path, content: str):
    """Write *content* to *path* atomically (tmp + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(path) + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            log.warning("Failed to clean up temp file %s: %s", tmp_path, cleanup_exc)
        raise


def _verify_tag_sha(tag: str, expected_sha: str) -> tuple:
    """Verify the local tag commit SHA matches the expected SHA from GitHub API.

    After git fetch, resolve the tag to its commit SHA and compare.

    Returns:
        (match: bool, message: str)
    """
    if not expected_sha:
        log.warning("No expected SHA provided for tag %s — skipping verification", tag)
        return True, "No expected SHA (skipped)"

    # Resolve tag to commit SHA (dereference annotated tags with ^{})
    ok, local_sha = _git("rev-parse", f"{tag}^{{}}")
    if not ok:
        log.error("Failed to resolve tag %s to commit SHA: %s", tag, local_sha)
        return False, f"Cannot resolve tag {tag}: {local_sha}"

    local_sha = local_sha.strip()
    if not _SHA_RE.match(local_sha):
        log.error("Unexpected SHA format for tag %s: %r", tag, local_sha)
        return False, f"Invalid SHA format: {local_sha}"

    if local_sha == expected_sha:
        log.info("Tag %s SHA verified: %s", tag, local_sha[:12])
        return True, f"SHA verified: {local_sha[:12]}"

    log.error(
        "TAG SHA MISMATCH for %s: expected=%s, got=%s — possible tampering",
        tag, expected_sha[:12], local_sha[:12],
    )
    return False, f"SHA mismatch: expected {expected_sha[:12]}, got {local_sha[:12]}"


def apply_update(tag: str, expected_sha: str = "") -> tuple:
    """Apply update: git fetch, verify SHA, git checkout <tag>.

    Saves current version tag to ``/var/lib/framecast/rollback-tag`` with
    an HMAC signature in ``rollback-sig`` before switching so the
    health-check script can validate and roll back on failure.

    The expected_sha is the target_commitish from check_for_update().
    If provided, the fetched tag's commit SHA is verified before checkout.

    Returns:
        (success: bool, message: str)
    """
    if not _TAG_RE.match(tag):
        return False, f"Invalid tag format: {tag}"

    current = get_current_version()
    rollback_tag = f"v{current}"

    # Save rollback tag with HMAC signature (atomic writes)
    try:
        _atomic_write(ROLLBACK_FILE, rollback_tag)
        _atomic_write(ROLLBACK_SIG_FILE, _hmac_sign(rollback_tag))
        log.info("Saved rollback tag %s to %s (HMAC signed)", rollback_tag, ROLLBACK_FILE)
    except OSError as exc:
        log.error("Failed to write rollback file: %s", exc)
        return False, f"Failed to save rollback tag: {exc}"

    # Store expected SHA for post-fetch verification
    if expected_sha:
        try:
            _atomic_write(EXPECTED_SHA_FILE, expected_sha)
            log.info("Stored expected SHA for %s: %s", tag, expected_sha[:12])
        except OSError as exc:
            log.warning("Failed to write expected SHA file: %s", exc)

    # Fetch latest tags
    ok, msg = _git("fetch", "--tags")
    if not ok:
        return False, f"git fetch failed: {msg}"

    # Verify tag SHA matches what GitHub API reported
    if expected_sha:
        sha_ok, sha_msg = _verify_tag_sha(tag, expected_sha)
        if not sha_ok:
            log.error("Update ABORTED for %s: %s", tag, sha_msg)
            return False, f"Update aborted — {sha_msg}"

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
