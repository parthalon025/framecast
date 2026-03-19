"""Gunicorn configuration for FrameCast web server."""

import os
import sys

# Bind to all interfaces on WEB_PORT (default 8080)
bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '8080')}"

# Enforce workers=1: SSE client list is per-process, so events don't
# propagate across workers.  Multiple workers break SSE and create
# singleton conflicts (Lesson #1356).  This is a hard constraint, not
# a default.
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
