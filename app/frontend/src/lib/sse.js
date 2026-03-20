/**
 * SSE connection helper with exponential backoff reconnection.
 *
 * Handles connect/reconnect/cleanup. Consumers provide named event
 * listeners via the `listeners` map — these are re-attached on each
 * reconnect so they survive connection drops.
 *
 * Usage:
 *   const sse = createSSE("/api/events", {
 *     listeners: {
 *       "photo:added": (evt) => refresh(),
 *       "settings:changed": (evt) => applySettings(JSON.parse(evt.data)),
 *     },
 *     onOpen: () => console.log("connected"),
 *   });
 *   // cleanup:
 *   sse.close();
 */

const BACKOFF_INITIAL = 1000;
const BACKOFF_MAX = 60000;

export function createSSE(url, { listeners = {}, onOpen } = {}) {
  let source = null;
  let backoff = BACKOFF_INITIAL;
  let reconnectTimer = null;
  let closed = false;

  function connect() {
    if (closed) return;
    if (source) source.close();

    source = new EventSource(url);

    // Attach named event listeners (survive reconnect)
    for (const [event, handler] of Object.entries(listeners)) {
      source.addEventListener(event, handler);
    }

    source.onopen = () => {
      backoff = BACKOFF_INITIAL;
      if (onOpen) onOpen();
    };

    source.onerror = () => {
      source.close();
      source = null;
      if (!closed) {
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, BACKOFF_MAX);
      }
    };
  }

  function close() {
    closed = true;
    document.removeEventListener("visibilitychange", handleVisibility);
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (source) source.close();
    source = null;
  }

  // Pause SSE when page is backgrounded to reduce battery drain
  function handleVisibility() {
    if (closed) return;
    if (document.hidden) {
      // Tear down connection while backgrounded
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      if (source) source.close();
      source = null;
    } else {
      // Reconnect immediately when foregrounded
      backoff = BACKOFF_INITIAL;
      connect();
    }
  }
  document.addEventListener("visibilitychange", handleVisibility);

  connect();
  return { close };
}
