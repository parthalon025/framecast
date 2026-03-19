"""Configuration management - reads and writes .env files."""

import logging
import os
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.parent
ENV_FILE = SCRIPT_DIR / ".env"

_cache = {}
_lock = threading.Lock()


def load_env():
    """Load .env file into a dict."""
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    value = value.strip().strip("'\"")
                    env[key.strip()] = value
    return env


def get(key, default=""):
    """Read a config value: os.environ > .env file > default."""
    global _cache
    with _lock:
        if not _cache:
            _cache = load_env()
        return os.environ.get(key, _cache.get(key, default))


def save(updates: dict):
    """Update .env file with new values, preserving comments and order.

    Thread-safe: serializes read-modify-write to prevent concurrent
    settings saves from clobbering each other.
    """
    with _lock:
        lines = []
        if ENV_FILE.exists():
            with open(ENV_FILE) as f:
                lines = f.readlines()

        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}\n")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        # Atomic write: temp file -> fsync -> rename to prevent corruption on
        # power loss (common on Raspberry Pi without graceful shutdown).
        fd, tmp_path = tempfile.mkstemp(
            dir=str(ENV_FILE.parent), prefix=".env.tmp.", suffix=""
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.writelines(new_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(ENV_FILE))
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError as cleanup_exc:
                log.warning("Failed to clean up temp file %s: %s", tmp_path, cleanup_exc)
            raise

        _cache.update(updates)


def reload():
    """Force reload config from disk."""
    global _cache
    with _lock:
        _cache = load_env()
        return _cache.copy()
