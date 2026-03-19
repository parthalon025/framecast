"""Server-Sent Events (SSE) support for FrameCast.

Thread-safe client management with keepalive and stale client cleanup.
"""

import json
import logging
import threading
from queue import Empty, Full, Queue

log = logging.getLogger(__name__)

# Connected SSE clients. Each client is a Queue that receives events.
_clients = []
_clients_lock = threading.Lock()

# Max events buffered per client before it's considered stale
_MAX_QUEUE_SIZE = 50

# Keepalive interval in seconds (SSE comment to prevent timeout)
_KEEPALIVE_INTERVAL = 30


def subscribe():
    """Generator that yields SSE-formatted events for a single client.

    Yields:
        SSE-formatted strings (event + data lines, or keepalive comments).
    """
    q = Queue(maxsize=_MAX_QUEUE_SIZE)
    with _clients_lock:
        _clients.append(q)
    log.info("SSE client connected (total: %d)", len(_clients))

    try:
        while True:
            try:
                event, data = q.get(timeout=_KEEPALIVE_INTERVAL)
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
            except Empty:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
    except GeneratorExit:
        pass
    finally:
        with _clients_lock:
            try:
                _clients.remove(q)
            except ValueError:
                pass
        log.info("SSE client disconnected (total: %d)", len(_clients))


def notify(event, data=None):
    """Push an event to all connected SSE clients.

    Drops the event for clients whose queues are full (stale clients).

    Args:
        event: Event name string (e.g., "photo:added").
        data: JSON-serializable data payload.
    """
    if data is None:
        data = {}

    stale = []
    with _clients_lock:
        for q in _clients:
            try:
                q.put_nowait((event, data))
            except Full:
                stale.append(q)

        # Remove stale clients whose queues are full
        for q in stale:
            try:
                _clients.remove(q)
            except ValueError:
                pass

    if stale:
        log.warning("Dropped %d stale SSE client(s)", len(stale))


def client_count():
    """Return the number of connected SSE clients."""
    with _clients_lock:
        return len(_clients)
