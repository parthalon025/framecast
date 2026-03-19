"""Gunicorn configuration for FrameCast web server."""

import multiprocessing
import os

# Bind to all interfaces on WEB_PORT (default 8080)
bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '8080')}"

# Workers: min of CPU count and 2 (Pi has limited RAM)
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count(), 2)))

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
