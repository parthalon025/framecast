"""OTA update module — checks GitHub Releases and applies updates.

Uses urllib.request (stdlib only) to query the GitHub API.  All subprocess
calls carry timeouts and log errors before returning fallback values.

Security: after git fetch, the tag's commit SHA is verified against what
the GitHub API reported.  If the SHA does not match (e.g. tag was force-pushed
or MITM), the update is aborted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
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
UPDATE_IN_PROGRESS_FILE = Path("/var/lib/framecast/update-in-progress")
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


def check_for_update() -> dict[str, object]:
    """Check GitHub Releases API for a newer version.

    Returns:
        {"available": bool, "current": str, "latest": str, "url": str,
         "tag_name": str, "expected_sha": str}

    The ``expected_sha`` field is the commit SHA resolved via the GitHub
    Tags API (with annotated-tag dereferencing).  The Releases API
    ``target_commitish`` is a branch name, not a SHA, so we fetch the
    real commit SHA separately.
    """
    current = get_current_version()
    result: dict[str, object] = {
        "available": False,
        "current": current,
        "latest": current,
        "url": "",
        "tag_name": "",
        "expected_sha": "",
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
        result["tag_name"] = tag

        # Resolve actual commit SHA via Tags API (not target_commitish which is a branch name)
        expected_sha = _fetch_tag_sha(tag)
        result["expected_sha"] = expected_sha

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
    """Compute HMAC-SHA256 of *data* using FLASK_SECRET_KEY.

    Raises RuntimeError if the secret key is not configured — an ephemeral
    key would produce signatures the health-check can never validate.
    """
    secret = config.get("FLASK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "FLASK_SECRET_KEY not set in .env — cannot sign rollback tag. "
            "OTA updates require a stable secret key."
        )
    return hmac.new(
        secret.encode(), data.encode(), hashlib.sha256
    ).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (tmp + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(path) + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            log.warning("Failed to clean up temp file %s: %s", tmp_path, cleanup_exc)
        raise


def _verify_tag_sha(tag: str, expected_sha: str) -> tuple[bool, str]:
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


def _fetch_tag_sha(tag: str) -> str:
    """Fetch the commit SHA for a tag via GitHub Tags API.

    Dereferences annotated tags to get the underlying commit SHA.
    Returns empty string on failure.
    """
    repo = f"{_GITHUB_OWNER}/{_GITHUB_REPO}"
    url = f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "FrameCast-Updater"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        obj_type = data["object"]["type"]
        sha = data["object"]["sha"]

        # Dereference annotated tags
        if obj_type == "tag":
            tag_url = data["object"]["url"]
            with urllib.request.urlopen(
                urllib.request.Request(
                    tag_url,
                    headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "FrameCast-Updater"},
                ),
                timeout=30,
            ) as resp2:
                tag_data = json.loads(resp2.read())
            sha = tag_data["object"]["sha"]

        return str(sha)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        log.error("Failed to fetch tag SHA for %s: %s", tag, exc)
        return ""


def apply_update(tag: str, expected_sha: str = "") -> tuple[bool, str]:
    """Apply update: git fetch, verify SHA, git checkout <tag>, run post-update.

    Saves current version tag to ``/var/lib/framecast/rollback-tag`` with
    an HMAC signature in ``rollback-sig`` before switching so the
    health-check script can validate and roll back on failure.

    The expected_sha is the commit SHA resolved via the Tags API.
    If provided, the fetched tag's commit SHA is verified before checkout.

    Returns:
        (success: bool, message: str)
    """
    if not _TAG_RE.match(tag):
        return False, f"Invalid tag format: {tag}"

    # Pre-flight: disk space check (I20 — 100MB minimum)
    try:
        usage = shutil.disk_usage(str(INSTALL_DIR))
        if usage.free < 100 * 1024 * 1024:
            return False, "Insufficient disk space for update"
    except OSError as exc:
        log.warning("Disk space check failed: %s", exc)

    # Pre-flight: verify git repo is intact
    ok, msg = _git("rev-parse", "--git-dir")
    if not ok:
        return False, f"Git repo missing or corrupt at {INSTALL_DIR}: {msg}"
    ok, remote_url = _git("remote", "get-url", "origin")
    if not ok:
        return False, f"Git remote 'origin' not configured: {remote_url}"

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

    # Mark update in progress (health-check forces rollback if found on boot)
    try:
        _atomic_write(UPDATE_IN_PROGRESS_FILE, f"{rollback_tag} -> {tag}")
    except OSError as exc:
        log.warning("Failed to write update-in-progress flag: %s", exc)

    # Preserve health check before checkout (C13 — new version might break it)
    stable_health = Path("/var/lib/framecast/health-check-stable.sh")
    current_health = Path(INSTALL_DIR) / "scripts" / "health-check.sh"
    if current_health.exists():
        try:
            shutil.copy2(str(current_health), str(stable_health))
            log.info("Copied health-check.sh to stable location: %s", stable_health)
        except OSError as exc:
            log.warning("Failed to copy health-check to stable location: %s", exc)

    # Fetch latest tags (--force handles re-created tags, I18)
    ok, msg = _git("fetch", "--tags", "--force")
    if not ok:
        _cleanup_update_flag()
        return False, f"git fetch failed: {msg}"

    # Verify tag SHA matches what GitHub API reported
    if expected_sha:
        sha_ok, sha_msg = _verify_tag_sha(tag, expected_sha)
        if not sha_ok:
            _cleanup_update_flag()
            log.error("Update ABORTED for %s: %s", tag, sha_msg)
            return False, f"Update aborted — {sha_msg}"

    # Stop Flask service before checkout to avoid serving mixed code (I19)
    try:
        subprocess.run(
            ["sudo", "systemctl", "stop", "framecast"],
            timeout=30,
            check=False,
        )
    except Exception as exc:
        log.warning("Failed to stop framecast service before update: %s", exc)

    # Checkout the target tag
    ok, msg = _git("checkout", tag)
    if not ok:
        _cleanup_update_flag()
        return False, f"git checkout {tag} failed: {msg}"

    # Run post-update deps/rebuild (C7)
    post_script = Path(INSTALL_DIR) / "scripts" / "post-update.sh"
    if post_script.exists():
        try:
            subprocess.run(
                ["bash", str(post_script)],
                timeout=300,
                capture_output=True,
                text=True,
                check=True,
            )
            log.info("Post-update script completed successfully")
        except Exception as exc:
            log.warning("Post-update script failed: %s", exc)

    # Sync VERSION file with the new tag
    new_version = tag.lstrip("v")
    try:
        _atomic_write(VERSION_FILE, new_version)
        log.info("VERSION file updated to %s", new_version)
    except OSError as exc:
        log.warning("Failed to update VERSION file: %s", exc)

    log.info("Update applied: v%s -> %s", current, tag)
    return True, f"Updated from v{current} to {tag}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cleanup_update_flag() -> None:
    """Remove the update-in-progress flag (called on success or abort)."""
    try:
        UPDATE_IN_PROGRESS_FILE.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Failed to remove update-in-progress flag: %s", exc)


def _git(*args: str) -> tuple[bool, str]:
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
