"""Threading stress tests for SSE module concurrency safety.

Validates that the threading.Lock guards in sse.py hold under contention:
- Event ID monotonicity under parallel access
- notify() thread-safety with concurrent client add/remove
- Recent event buffer respects maxlen bound under parallel writes
"""

import os
import sys
import threading
from queue import Queue

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import sse


def _reset_sse_state():
    """Reset SSE module globals to a clean state between tests."""
    with sse._clients_lock:
        sse._clients.clear()
    with sse._event_id_lock:
        sse._event_id = 0
    with sse._recent_lock:
        sse._recent_events.clear()


class TestEventIdMonotonicity:
    """Event IDs must be strictly monotonic even under high thread contention."""

    def setup_method(self):
        _reset_sse_state()

    def test_parallel_id_generation_unique_and_sequential(self):
        """10 threads x 100 IDs = 1000 unique, contiguous IDs starting at 1."""
        num_threads = 10
        ids_per_thread = 100
        results = []
        results_lock = threading.Lock()
        errors = []
        errors_lock = threading.Lock()

        def grab_ids():
            try:
                local_ids = [sse._next_event_id() for _ in range(ids_per_thread)]
                with results_lock:
                    results.extend(local_ids)
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=grab_ids) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), f"Thread {t.name} deadlocked"

        assert not errors, f"Threads raised exceptions: {errors}"

        # All 1000 IDs must be unique
        assert len(results) == num_threads * ids_per_thread
        assert len(set(results)) == len(results), "Duplicate event IDs detected"

        # Sorted IDs must form a contiguous range 1..1000
        assert sorted(results) == list(range(1, num_threads * ids_per_thread + 1))


class TestConcurrentNotify:
    """notify() must be thread-safe: no crashes, no lost clients, no corruption."""

    def setup_method(self):
        _reset_sse_state()

    def test_parallel_notify_no_exceptions(self):
        """10 threads x 50 notify calls — no thread raises."""
        num_threads = 10
        calls_per_thread = 50
        errors = []
        errors_lock = threading.Lock()

        # Add a few clients to exercise the broadcast path
        clients = []
        for _ in range(3):
            q = Queue(maxsize=sse._MAX_QUEUE_SIZE)
            with sse._clients_lock:
                sse._clients.append(q)
            clients.append(q)

        def call_notify(thread_idx):
            try:
                for i in range(calls_per_thread):
                    sse.notify(f"test:{thread_idx}", {"i": i})
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=call_notify, args=(idx,))
            for idx in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), f"Thread {t.name} deadlocked"

        assert not errors, f"Threads raised exceptions: {errors}"

    def test_concurrent_notify_with_client_churn(self):
        """notify + add/remove clients simultaneously — client_count stays consistent."""
        num_notify_threads = 5
        calls_per_thread = 50
        errors = []
        errors_lock = threading.Lock()
        stop_churn = threading.Event()

        def churn_clients():
            """Rapidly add and remove clients to stress the _clients list."""
            try:
                while not stop_churn.is_set():
                    q = Queue(maxsize=sse._MAX_QUEUE_SIZE)
                    with sse._clients_lock:
                        if len(sse._clients) < sse._MAX_CLIENTS:
                            sse._clients.append(q)
                    with sse._clients_lock:
                        if sse._clients:
                            sse._clients.pop(0)
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        def call_notify(thread_idx):
            try:
                for i in range(calls_per_thread):
                    sse.notify(f"churn:{thread_idx}", {"i": i})
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        churn_thread = threading.Thread(target=churn_clients)
        churn_thread.start()

        notify_threads = [
            threading.Thread(target=call_notify, args=(idx,))
            for idx in range(num_notify_threads)
        ]
        for t in notify_threads:
            t.start()
        for t in notify_threads:
            t.join(timeout=10)
            assert not t.is_alive(), f"Thread {t.name} deadlocked"

        stop_churn.set()
        churn_thread.join(timeout=10)
        assert not churn_thread.is_alive(), "Churn thread deadlocked"

        assert not errors, f"Threads raised exceptions: {errors}"

        # After all threads finish, client_count must match actual list length
        with sse._clients_lock:
            actual_len = len(sse._clients)
        assert sse.client_count() == actual_len


class TestRecentBufferBound:
    """The recent events deque must never exceed _RECENT_BUFFER_SIZE."""

    def setup_method(self):
        _reset_sse_state()

    def test_buffer_respects_maxlen_under_contention(self):
        """5 threads x 200 notify calls — buffer stays within bound."""
        num_threads = 5
        calls_per_thread = 200
        errors = []
        errors_lock = threading.Lock()

        def call_notify(thread_idx):
            try:
                for i in range(calls_per_thread):
                    sse.notify(f"buf:{thread_idx}", {"i": i})
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=call_notify, args=(idx,))
            for idx in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), f"Thread {t.name} deadlocked"

        assert not errors, f"Threads raised exceptions: {errors}"

        with sse._recent_lock:
            buffer_len = len(sse._recent_events)
        assert buffer_len <= sse._RECENT_BUFFER_SIZE, (
            f"Recent buffer overflowed: {buffer_len} > {sse._RECENT_BUFFER_SIZE}"
        )
