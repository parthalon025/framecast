"""Gunicorn configuration for FrameCast web server."""

import os
import sys

# Bind to all interfaces on WEB_PORT (default 8080)
bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '8080')}"

# MANDATORY: workers=1. SSE, stats buffer, CEC are process-singletons.
# See issue #34 and Lesson #1356.
# Also guarded at Flask init time in web_upload.py (_check_single_worker).
_requested_workers = int(os.environ.get("GUNICORN_WORKERS", 1))
if _requested_workers != 1:
    print(
        f"FATAL: GUNICORN_WORKERS={_requested_workers} is not supported. "
        "FrameCast requires exactly 1 worker (SSE is per-process, singletons "
        "are not shared). Remove GUNICORN_WORKERS from your environment.",
        file=sys.stderr,
    )
    raise SystemExit(1)

workers = 1

# Use gthread worker class for SSE streaming support
worker_class = "gthread"

# Threads per worker
threads = int(os.environ.get("GUNICORN_THREADS", "2"))

# Timeout: 120s to handle large uploads over slow connections
timeout = 120

# Graceful timeout for in-flight requests during restart (match request timeout)
graceful_timeout = 120

# Access log to stdout
accesslog = "-"

# Error log to stderr
errorlog = "-"

# Log level
loglevel = os.environ.get("LOG_LEVEL", "info")

# ---------------------------------------------------------------------------
# Optional self-signed HTTPS
# ---------------------------------------------------------------------------
# When HTTPS_ENABLED=yes and certs exist under MEDIA_DIR/certs/, gunicorn
# serves TLS directly. Generate certs with scripts/generate-cert.sh.
_cert_dir = os.path.join(
    os.environ.get("MEDIA_DIR", "/home/pi/framecast-data"), "certs"
)
_cert = os.path.join(_cert_dir, "server.crt")
_key = os.path.join(_cert_dir, "server.key")

if (
    os.path.exists(_cert)
    and os.path.exists(_key)
    and os.environ.get("HTTPS_ENABLED", "no").lower() == "yes"
):
    certfile = _cert
    keyfile = _key
