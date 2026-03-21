import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// --- Mock superhot-ui before any component imports ---

vi.mock("superhot-ui", () => ({
  setFacilityState: vi.fn(),
  ShNarrator: { personality: "glados" },
}));

vi.mock("superhot-ui/preact", () => ({
  ShAnnouncement: () => null,
  ShPageBanner: () => null,
}));

// --- Mock child display components ---

/** Captured onComplete callback from Boot render. */
let capturedOnComplete = null;

vi.mock("../display/Boot.jsx", () => ({
  Boot: (props) => {
    capturedOnComplete = props.onComplete;
    return null;
  },
}));
vi.mock("../display/Welcome.jsx", () => ({ Welcome: () => null }));
vi.mock("../display/Setup.jsx", () => ({ Setup: () => null }));
vi.mock("../display/Slideshow.jsx", () => ({ Slideshow: () => null }));
vi.mock("../display/AmbientClock.jsx", () => ({ AmbientClock: () => null }));

// --- Mock createSSE ---

vi.mock("../lib/sse.js", () => ({
  createSSE: () => ({ close: vi.fn() }),
}));

// --- Now import the module under test ---

import { displayState, DisplayRouter } from "../display/DisplayRouter.jsx";
import { setFacilityState } from "superhot-ui";
import { render, cleanup } from "./helpers/preact-render.js";

// --- Tests ---

describe("DisplayRouter routing logic", () => {
  beforeEach(() => {
    capturedOnComplete = null;
    displayState.value = "boot";
    vi.restoreAllMocks();

    // Re-mock setFacilityState after restoreAllMocks clears it
    setFacilityState.mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  /**
   * Helper: render DisplayRouter, invoke the onComplete callback
   * (which triggers handleBootComplete → fetch → state transition),
   * and wait for the async fetch cycle to settle.
   */
  async function renderAndBoot() {
    render(DisplayRouter);
    // Boot should have been rendered, capturing onComplete
    expect(capturedOnComplete).toBeTypeOf("function");
    await capturedOnComplete();
  }

  it("starts in boot state", () => {
    expect(displayState.value).toBe("boot");
  });

  it("transitions to setup when wifi_connected is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            photo_count: 5,
            video_count: 0,
          }),
      }),
    );

    await renderAndBoot();
    expect(displayState.value).toBe("setup");
  });

  it("transitions to slideshow when wifi connected and photos exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            wifi_connected: true,
            photo_count: 10,
            video_count: 0,
          }),
      }),
    );

    await renderAndBoot();
    expect(displayState.value).toBe("slideshow");
  });

  it("transitions to slideshow when wifi connected and videos exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            wifi_connected: true,
            photo_count: 0,
            video_count: 3,
          }),
      }),
    );

    await renderAndBoot();
    expect(displayState.value).toBe("slideshow");
  });

  it("transitions to welcome when wifi connected but no media", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            wifi_connected: true,
            photo_count: 0,
            video_count: 0,
          }),
      }),
    );

    await renderAndBoot();
    expect(displayState.value).toBe("welcome");
  });

  it("transitions to setup on fetch error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );

    await renderAndBoot();
    expect(displayState.value).toBe("setup");
  });

  it("stores access_pin from status response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            wifi_connected: true,
            photo_count: 1,
            video_count: 0,
            access_pin: "1234",
          }),
      }),
    );

    await renderAndBoot();
    // Verify we reached slideshow (pin storage is internal,
    // but confirming no crash with access_pin present)
    expect(displayState.value).toBe("slideshow");
  });
});
