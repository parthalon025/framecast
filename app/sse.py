"""Server-Sent Events (SSE) support for FrameCast.

Thread-safe client management with keepalive, stale client cleanup,
event coalescing, and reconnection support via event IDs.
"""

import json
import logging
import os
import threading
import time
from queue import Empty, Full, Queue

log = logging.getLogger(__name__)

# Connected SSE clients. Each client is a Queue that receives events.
_clients = []
_clients_lock = threading.Lock()

# Max events buffered per client before it's considered stale
_MAX_QUEUE_SIZE = 50

# Max concurrent SSE clients (Pi has limited RAM)
_MAX_CLIENTS = 10

# Keepalive interval in seconds (SSE comment to prevent timeout)
_KEEPALIVE_INTERVAL = int(os.environ.get("SSE_KEEPALIVE", "20"))

# Event coalescing window — rapid events within this window are merged
_COALESCE_WINDOW = 2.0

# Monotonic event ID counter for last-event-id reconnection
_event_id = 0
_event_id_lock = threading.Lock()

# Recent event buffer for reconnection (ring buffer of (id, event, data))
_RECENT_BUFFER_SIZE = 50
_recent_events = []
_recent_lock = threading.Lock()


def _next_event_id():
    """Return the next monotonically increasing event ID."""
    global _event_id
    with _event_id_lock:
        _event_id += 1
        return _event_id


def _get_current_state():
    """Build a state:current payload from the app's current state.

    Returns a dict with basic state info, or None if unavailable.
    Called on initial SSE connect (Lesson #604 — send current state first).
    """
    try:
        return {"connected": True, "clients": client_count()}
    except Exception as exc:
        log.warning("Failed to build current state for SSE connect: %s", exc)
        return {"connected": True}


def _replay_events_after(last_id):
    """Yield SSE-formatted events that occurred after *last_id*.

    Used for reconnection: the client sends Last-Event-ID and we replay
    any events that were buffered since that ID.
    """
    try:
        last_id = int(last_id)
    except (TypeError, ValueError):
        return

    with _recent_lock:
        for eid, event, data in _recent_events:
            if eid > last_id:
                yield f"id: {eid}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def subscribe(last_event_id=None):
    """Generator that yields SSE-formatted events for a single client.

    Args:
        last_event_id: If provided, replay buffered events after this ID
            before switching to live stream (reconnection support).

    Yields:
        SSE-formatted strings (event + data lines, or keepalive comments).
    """
    q = Queue(maxsize=_MAX_QUEUE_SIZE)
    with _clients_lock:
        if len(_clients) >= _MAX_CLIENTS:
            log.warning("SSE connection rejected: max clients (%d) reached", _MAX_CLIENTS)
            yield "event: error\ndata: {\"error\": \"Too many connections\"}\n\n"
            return
        _clients.append(q)
        count = len(_clients)
    log.info("SSE client connected (total: %d)", count)

    try:
        # Send current state as first event (Lesson #604)
        state = _get_current_state()
        eid = _next_event_id()
        yield f"id: {eid}\nevent: state:current\ndata: {json.dumps(state)}\n\n"

        # Replay missed events on reconnection
        if last_event_id is not None:
            for replayed in _replay_events_after(last_event_id):
                yield replayed

        # Coalescing state: track last event type and time
        pending_event = None
        pending_data = None
        pending_time = 0.0

        while True:
            try:
                event, data = q.get(timeout=min(_KEEPALIVE_INTERVAL, _COALESCE_WINDOW))

                now = time.monotonic()
                # Coalesce: if same event type arrives within window, replace
                if pending_event == event and (now - pending_time) < _COALESCE_WINDOW:
                    pending_data = data
                    pending_time = now
                    continue

                # Flush any pending coalesced event
                if pending_event is not None:
                    eid = _next_event_id()
                    yield f"id: {eid}\nevent: {pending_event}\ndata: {json.dumps(pending_data)}\n\n"

                # Buffer this event as pending
                pending_event = event
                pending_data = data
                pending_time = now

            except Empty:
                # Flush any pending coalesced event before keepalive
                if pending_event is not None:
                    eid = _next_event_id()
                    yield f"id: {eid}\nevent: {pending_event}\ndata: {json.dumps(pending_data)}\n\n"
                    pending_event = None
                    pending_data = None

                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
    except (BrokenPipeError, GeneratorExit):
        # Client disconnected — expected during normal operation (Lesson #36)
        pass
    except Exception as exc:
        log.warning("SSE subscribe generator error: %s", exc)
    finally:
        with _clients_lock:
            try:
                _clients.remove(q)
            except ValueError:
                pass
            count = len(_clients)
        log.info("SSE client disconnected (total: %d)", count)


def notify(event: str, data: dict | None = None):
    """Push an event to all connected SSE clients.

    Drops the event for clients whose queues are full (stale clients).
    Buffers the event for reconnection replay.

    Args:
        event: Event name string (e.g., "photo:added").
        data: JSON-serializable dict payload.
    """
    if data is None:
        data = {}

    # Assign an event ID and buffer for reconnection
    eid = _next_event_id()
    with _recent_lock:
        _recent_events.append((eid, event, data))
        # Trim ring buffer
        while len(_recent_events) > _RECENT_BUFFER_SIZE:
            _recent_events.pop(0)

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
