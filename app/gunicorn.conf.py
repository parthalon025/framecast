"""Gunicorn configuration for FrameCast web server."""

import os

# Bind to all interfaces on WEB_PORT (default 8080)
bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '8080')}"

# Default to 1 worker: SSE client list is per-process, so events don't
# propagate across workers.  1 worker + gthread is sufficient for Pi
# hardware.  Override via GUNICORN_WORKERS env var if needed.
workers = int(os.environ.get("GUNICORN_WORKERS", 1))

if workers > 1:
    import warnings

    warnings.warn(
        f"GUNICORN_WORKERS={workers} may break SSE — events are per-process. "
        "Set workers=1 or use a Redis pub/sub broker.",
        stacklevel=1,
    )

# Use gthread worker class for SSE streaming support
worker_class = "gthread"

# Threads per worker
threads = 4

# Timeout: 120s to handle large uploads over slow connections
timeout = 120

# Graceful timeout for in-flight requests during restart
graceful_timeout = 30

# Access log to stdout
accesslog = "-"

# Error log to stderr
errorlog = "-"

# Log level
loglevel = os.environ.get("LOG_LEVEL", "info")
