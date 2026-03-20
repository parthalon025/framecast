import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createSSE } from "../lib/sse.js";

// --- Mock EventSource ---

class MockEventSource {
  constructor(url) {
    MockEventSource.instances.push(this);
    this.url = url;
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    this.readyState = 0;
  }

  addEventListener(event, handler) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(handler);
  }

  close() {
    this.readyState = 2;
  }

  // Test helpers
  _triggerOpen() {
    this.readyState = 1;
    if (this.onopen) this.onopen();
  }

  _triggerError() {
    if (this.onerror) this.onerror();
  }
}

MockEventSource.instances = [];

// --- Tests ---

describe("createSSE", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("connects to the given URL", () => {
    const sse = createSSE("/api/events");
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toBe("/api/events");
    sse.close();
  });

  it("attaches named event listeners", () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    const sse = createSSE("/api/events", {
      listeners: { "photo:added": handler1, "settings:changed": handler2 },
    });

    const source = MockEventSource.instances[0];
    expect(source.listeners["photo:added"]).toContain(handler1);
    expect(source.listeners["settings:changed"]).toContain(handler2);
    sse.close();
  });

  it("calls onOpen callback when connected", () => {
    const onOpen = vi.fn();
    const sse = createSSE("/api/events", { onOpen });

    MockEventSource.instances[0]._triggerOpen();
    expect(onOpen).toHaveBeenCalledOnce();
    sse.close();
  });

  it("reconnects with 1000ms backoff on error", () => {
    const sse = createSSE("/api/events");
    expect(MockEventSource.instances).toHaveLength(1);

    // Trigger error on first connection
    MockEventSource.instances[0]._triggerError();
    expect(MockEventSource.instances).toHaveLength(1);

    // Advance past the 1000ms backoff
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(2);
    sse.close();
  });

  it("doubles backoff on consecutive errors", () => {
    const sse = createSSE("/api/events");

    // First error: backoff = 1000ms
    MockEventSource.instances[0]._triggerError();
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(2);

    // Second error: backoff = 2000ms
    MockEventSource.instances[1]._triggerError();
    vi.advanceTimersByTime(1999);
    expect(MockEventSource.instances).toHaveLength(2); // not yet
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances).toHaveLength(3);

    // Third error: backoff = 4000ms
    MockEventSource.instances[2]._triggerError();
    vi.advanceTimersByTime(3999);
    expect(MockEventSource.instances).toHaveLength(3); // not yet
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances).toHaveLength(4);
    sse.close();
  });

  it("caps backoff at 60 seconds", () => {
    const sse = createSSE("/api/events");

    // Run through enough errors to exceed 60s cap
    // 1000 -> 2000 -> 4000 -> 8000 -> 16000 -> 32000 -> 64000 (capped to 60000)
    for (let i = 0; i < 6; i++) {
      const last = MockEventSource.instances[MockEventSource.instances.length - 1];
      last._triggerError();
      vi.advanceTimersByTime(65000); // well past any backoff
    }
    expect(MockEventSource.instances).toHaveLength(7);

    // Next error should use 60000ms (capped), not 128000ms
    const last = MockEventSource.instances[MockEventSource.instances.length - 1];
    last._triggerError();

    // Should NOT reconnect at 59999ms
    vi.advanceTimersByTime(59999);
    expect(MockEventSource.instances).toHaveLength(7);

    // Should reconnect at 60000ms
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances).toHaveLength(8);
    sse.close();
  });

  it("resets backoff on successful open", () => {
    const sse = createSSE("/api/events");

    // Error twice: backoff goes 1000 -> 2000 -> 4000
    MockEventSource.instances[0]._triggerError();
    vi.advanceTimersByTime(1000);
    MockEventSource.instances[1]._triggerError();
    vi.advanceTimersByTime(2000);

    // Successful open resets backoff to 1000
    MockEventSource.instances[2]._triggerOpen();

    // Error again: backoff should be 1000 (reset), not 4000
    MockEventSource.instances[2]._triggerError();
    vi.advanceTimersByTime(999);
    expect(MockEventSource.instances).toHaveLength(3); // not yet
    vi.advanceTimersByTime(1);
    expect(MockEventSource.instances).toHaveLength(4);
    sse.close();
  });

  it("close() prevents further reconnection", () => {
    const sse = createSSE("/api/events");
    expect(MockEventSource.instances).toHaveLength(1);

    // Close, then trigger error
    sse.close();

    // The source should have been closed
    expect(MockEventSource.instances[0].readyState).toBe(2);

    // Even with time passing, no new connections
    vi.advanceTimersByTime(120000);
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
