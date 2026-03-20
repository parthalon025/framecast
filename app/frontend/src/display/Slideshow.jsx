/** @fileoverview Full-viewport photo/video slideshow with CSS transitions.
 *
 * Architecture: Two stacked layers (A and B). One is "active" (z-index 2,
 * visible) and the other is "standby" (z-index 1, hidden). On advance:
 *   1. Load the next image into the standby layer.
 *   2. Apply fade-in class to standby, fade-out to active.
 *   3. After transition ends, swap which layer is active.
 *
 * Playlist mode: Fetches a 50-photo weighted playlist from the server.
 * Plays through locally, requests a new playlist when current exhausts.
 *
 * This avoids Preact re-render timing issues by keeping both layers in the
 * DOM permanently and toggling their content via refs.
 */
import { signal } from "@preact/signals";
import { useRef, useEffect, useCallback } from "preact/hooks";
import { createSSE } from "../lib/sse.js";

// --- Signals (module-level for SSE reactivity) ---
const photoList = signal([]);
const settingsData = signal(null);
const onThisDayText = signal("");
const connectionLost = signal(false);

// --- Constants ---
const TRANSITION_TYPES = ["fc-fade", "fc-slide", "fc-kenburns", "fc-dissolve"];
const DEFAULT_TRANSITION_MS = 1000;
const MIN_TRANSITION_MS = 500;
const MAX_TRANSITION_MS = 3000;

// Ken Burns anchor points (9 positions)
const KB_ANCHORS = [
  "0% 0%", "50% 0%", "100% 0%",
  "0% 50%", "50% 50%", "100% 50%",
  "0% 100%", "50% 100%", "100% 100%",
];

// --- Helpers ---

/** Build the URL for a media file. */
function mediaUrl(photo) {
  const path = photo.filepath || photo.path || photo.filename;
  return `/media/${encodeURIComponent(path)}`;
}

/** Preload next N images using throwaway Image objects. */
function preloadAhead(ordered, fromIdx, count) {
  for (let i = 1; i <= count; i++) {
    const idx = (fromIdx + i) % ordered.length;
    const item = ordered[idx];
    if (item && !item.is_video) {
      const img = new Image();
      img.src = mediaUrl(item);
    }
  }
}

/** Pick a transition type for this slide based on settings. */
function pickTransition(cfg) {
  const mode = cfg ? (cfg.transition_mode || "single") : "single";
  if (mode === "random") {
    return TRANSITION_TYPES[Math.floor(Math.random() * TRANSITION_TYPES.length)];
  }
  // single mode: map legacy names to new CSS class names
  const type = cfg ? cfg.transition_type : "fade";
  switch (type) {
    case "fade": return "fc-fade";
    case "slide": return "fc-slide";
    case "zoom": return "fc-kenburns";
    case "dissolve": return "fc-dissolve";
    case "none": return "none";
    default: return "fc-fade";
  }
}

/** Get configured transition duration in ms, clamped to valid range. */
function getTransitionMs(cfg) {
  if (!cfg) return DEFAULT_TRANSITION_MS;
  const ms = parseInt(cfg.transition_duration_ms, 10);
  if (isNaN(ms)) return DEFAULT_TRANSITION_MS;
  return Math.max(MIN_TRANSITION_MS, Math.min(MAX_TRANSITION_MS, ms));
}

/** Check if user prefers reduced motion. */
function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Remove all child nodes from a DOM element (safe alternative to innerHTML). */
function clearChildren(el) {
  while (el.firstChild) {
    const child = el.firstChild;
    // Clear any pending error timeout before removing (prevents leak)
    if (child._errTimeout) clearTimeout(child._errTimeout);
    el.removeChild(child);
  }
}

/** Apply Ken Burns effect to an image element with randomized anchors.
 * Aspect-aware: portrait images get vertical pan, landscape get horizontal.
 */
function applyKenBurns(imgEl, photo) {
  if (prefersReducedMotion()) return;

  const startAnchor = KB_ANCHORS[Math.floor(Math.random() * KB_ANCHORS.length)];
  let endAnchor = KB_ANCHORS[Math.floor(Math.random() * KB_ANCHORS.length)];
  // Avoid same start/end
  while (endAnchor === startAnchor && KB_ANCHORS.length > 1) {
    endAnchor = KB_ANCHORS[Math.floor(Math.random() * KB_ANCHORS.length)];
  }

  // Aspect-aware: constrain pan direction
  const width = photo.width || 0;
  const height = photo.height || 0;
  if (width > 0 && height > 0) {
    if (height > width) {
      // Portrait: prefer vertical pan (use column 1 anchors: 50% x%)
      const vertAnchors = ["50% 0%", "50% 50%", "50% 100%"];
      imgEl.style.setProperty("--kb-start", vertAnchors[Math.floor(Math.random() * vertAnchors.length)]);
      imgEl.style.setProperty("--kb-end", vertAnchors[Math.floor(Math.random() * vertAnchors.length)]);
    } else {
      // Landscape: prefer horizontal pan (use row 1 anchors: x% 50%)
      const horizAnchors = ["0% 50%", "50% 50%", "100% 50%"];
      imgEl.style.setProperty("--kb-start", horizAnchors[Math.floor(Math.random() * horizAnchors.length)]);
      imgEl.style.setProperty("--kb-end", horizAnchors[Math.floor(Math.random() * horizAnchors.length)]);
    }
  } else {
    imgEl.style.setProperty("--kb-start", startAnchor);
    imgEl.style.setProperty("--kb-end", endAnchor);
  }

  // Randomized scale: 1.15 to 1.3
  const scale = 1.15 + Math.random() * 0.15;
  imgEl.style.setProperty("--kb-scale", scale.toFixed(3));
}

/**
 * Set the source of a layer element (img or video).
 * Replaces the element's children to switch between img/video cleanly.
 */
function setLayerContent(layer, photo, onAdvance, cfg) {
  if (!layer || !photo) return;
  clearChildren(layer);

  // Clear "On This Day" overlay
  onThisDayText.value = "";

  if (photo.is_video) {
    const vid = document.createElement("video");
    vid.src = mediaUrl(photo);
    vid.autoplay = true;
    vid.muted = true;
    vid.playsInline = true;
    vid.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;";

    // Cap video duration at SLIDESHOW_DURATION * 3 (default 30s)
    const maxDuration = ((cfg ? cfg.photo_duration : 10) || 10) * 3;
    vid.addEventListener("loadedmetadata", () => {
      if (vid.duration > maxDuration) {
        // Auto-advance after max duration
        setTimeout(() => {
          if (onAdvance) onAdvance();
        }, maxDuration * 1000);
      }
    }, { once: true });

    vid.addEventListener("error", () => {
      console.warn("Slideshow: video decode failed", photo.filename || photo.name);
      // Quarantine via API (fire-and-forget)
      if (photo.id) {
        fetch(`/api/photos/${photo.id}/quarantine`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: "unsupported_codec" }),
        }).catch((err) => console.warn("Slideshow: quarantine request failed", err));
      }
      // Skip to next
      if (onAdvance) onAdvance();
    }, { once: true });

    if (onAdvance) {
      vid.addEventListener("ended", onAdvance, { once: true });
    }
    layer.appendChild(vid);
  } else {
    const img = document.createElement("img");
    img.src = mediaUrl(photo);
    img.alt = photo.filename || photo.name || "";
    img.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;image-orientation:from-image;";

    // Apply Ken Burns positioning to the image if transition is kenburns
    applyKenBurns(img, photo);

    img.onerror = () => {
      console.warn("Slideshow: failed to load image", photo.filename || photo.name);
      if (onAdvance) {
        img._errTimeout = setTimeout(onAdvance, 3000);
      }
    };
    layer.appendChild(img);
  }

  // Show "On This Day" overlay if applicable
  if (photo.on_this_day && photo.years_ago) {
    const yearsAgo = photo.years_ago;
    onThisDayText.value = yearsAgo === 1 ? "1 YEAR AGO" : `${yearsAgo} YEARS AGO`;
  }
}

/** Fetch a playlist from the server. Returns { photos, playlist_id }. */
async function fetchPlaylist() {
  const res = await fetch("/api/slideshow/playlist");
  if (!res.ok) throw new Error(`Playlist fetch failed: ${res.status}`);
  return res.json();
}

/** Track consecutive fetchPlaylist failures for connection-lost indicator. */
let playlistFailCount = 0;

function onPlaylistSuccess() {
  playlistFailCount = 0;
  connectionLost.value = false;
}

function onPlaylistFailure() {
  playlistFailCount++;
  if (playlistFailCount >= 3) connectionLost.value = true;
}

export function Slideshow() {
  // Refs for the two permanent layer divs
  const layerARef = useRef(null);
  const layerBRef = useRef(null);
  const otdOverlayRef = useRef(null);

  // Mutable state (not signals -- no re-render needed)
  const state = useRef({
    ordered: [],
    index: 0,
    activeLayer: "A", // which layer is currently showing
    transitioning: false,
    timer: null,
    playlistId: null,
  });

  /** Advance to the next photo/video. */
  const advance = useCallback(() => {
    const s = state.current;
    if (s.transitioning || s.ordered.length === 0) return;

    // Single photo: no transition needed
    if (s.ordered.length === 1) return;

    const cfg = settingsData.value;
    const currentPhoto = s.ordered[s.index];
    const isVideo = currentPhoto && currentPhoto.is_video;

    // Pick transition: videos use fade only, images use configured transition
    let transType;
    if (isVideo || prefersReducedMotion()) {
      transType = "fc-fade";
    } else {
      transType = pickTransition(cfg);
    }
    const ms = transType === "none" ? 0 : getTransitionMs(cfg);

    s.transitioning = true;
    s.index = (s.index + 1) % s.ordered.length;

    // If we've exhausted the playlist, fetch a new one in the background
    if (s.index === 0) {
      fetchPlaylist()
        .then((data) => {
          onPlaylistSuccess();
          if (data.photos && data.photos.length > 0) {
            s.ordered = data.photos;
            s.playlistId = data.playlist_id;
            // Don't reset index — we're at 0 which is correct for new playlist
          }
        })
        .catch((err) => {
          onPlaylistFailure();
          console.warn("Slideshow: playlist refresh failed", err);
        });
    }

    const activeEl = s.activeLayer === "A" ? layerARef.current : layerBRef.current;
    const standbyEl = s.activeLayer === "A" ? layerBRef.current : layerARef.current;

    // Load next content into standby
    setLayerContent(standbyEl, s.ordered[s.index], advance, cfg);

    // Bring standby to front and apply transitions
    standbyEl.style.zIndex = "3";
    standbyEl.style.opacity = "1";

    if (transType !== "none" && ms > 0) {
      standbyEl.className = `slideshow-layer ${transType}-in`;
      activeEl.className = `slideshow-layer ${transType}-out`;

      // Set transition duration via CSS custom property
      standbyEl.style.setProperty("--fc-transition-ms", `${ms}ms`);
      activeEl.style.setProperty("--fc-transition-ms", `${ms}ms`);
    }

    const finalize = () => {
      // Swap roles
      s.activeLayer = s.activeLayer === "A" ? "B" : "A";
      s.transitioning = false;

      // Active layer on top, standby hidden underneath
      const newActive = s.activeLayer === "A" ? layerARef.current : layerBRef.current;
      const newStandby = s.activeLayer === "A" ? layerBRef.current : layerARef.current;
      newActive.style.zIndex = "2";
      newActive.className = "slideshow-layer";
      newStandby.style.zIndex = "1";
      newStandby.style.opacity = "0";
      newStandby.className = "slideshow-layer";

      // Preload next 2
      preloadAhead(s.ordered, s.index, 2);

      // Restart timer for images (videos advance on ended)
      resetTimer();
    };

    if (ms > 0) {
      setTimeout(finalize, ms);
    } else {
      finalize();
    }
  }, []);

  /** Reset the auto-advance timer. */
  const resetTimer = useCallback(() => {
    const s = state.current;
    if (s.timer) {
      clearTimeout(s.timer);
      s.timer = null;
    }
    if (s.ordered.length <= 1) return;

    const cfg = settingsData.value;
    const duration = (cfg ? cfg.photo_duration : 10) * 1000;

    // Only auto-advance for images; videos advance via ended event
    const currentPhoto = s.ordered[s.index];
    if (currentPhoto && !currentPhoto.is_video) {
      s.timer = setTimeout(() => {
        advance();
      }, duration);
    }
  }, [advance]);

  // Fetch data on mount, set up SSE
  useEffect(() => {
    let cancelled = false;

    async function init(retryCount = 0) {
      try {
        // Fetch playlist and settings in parallel
        const [playlistData, settingsRes] = await Promise.all([
          fetchPlaylist(),
          fetch("/api/settings"),
        ]);
        if (cancelled) return;

        const cfg = await settingsRes.json();
        settingsData.value = cfg;

        connectionLost.value = false;
        const ordered = playlistData.photos || [];
        photoList.value = ordered;

        const s = state.current;
        s.ordered = ordered;
        s.index = 0;
        s.playlistId = playlistData.playlist_id;

        if (ordered.length > 0) {
          // Load first photo into layer A
          setLayerContent(layerARef.current, ordered[0], advance, cfg);
          layerARef.current.style.zIndex = "2";
          layerARef.current.style.opacity = "1";

          // Preload next 2
          if (ordered.length > 1) {
            preloadAhead(ordered, 0, 2);
          }

          resetTimer();
        }
      } catch (err) {
        console.error("Slideshow: init failed (attempt %d)", retryCount + 1, err);
        if (!cancelled) {
          if (retryCount >= 2) connectionLost.value = true;
          const delay = Math.min(1000 * Math.pow(2, retryCount), 60000);
          setTimeout(() => { if (!cancelled) init(retryCount + 1); }, delay);
        }
      }
    }

    init();

    // SSE: refresh playlist on photo:added / photo:deleted
    function handlePhotoChange() {
      if (cancelled) return;
      fetchPlaylist()
        .then((data) => {
          onPlaylistSuccess();
          if (!data.photos) return;
          const s = state.current;
          // Only replace if we're not mid-transition
          if (!s.transitioning) {
            s.ordered = data.photos;
            s.playlistId = data.playlist_id;
            photoList.value = data.photos;
            if (s.index >= s.ordered.length) {
              s.index = 0;
            }
          }
        })
        .catch((err) => {
          onPlaylistFailure();
          console.error("Slideshow: SSE refetch failed", err);
        });
    }

    const sse = createSSE("/api/events", {
      listeners: {
        "photo:added": handlePhotoChange,
        "photo:deleted": handlePhotoChange,
        "settings:changed": (evt) => {
          if (cancelled) return;
          try {
            const cfg = JSON.parse(evt.data);
            settingsData.value = cfg;
          } catch (parseErr) {
            console.warn("Slideshow: failed to parse settings:changed SSE data", parseErr);
          }
        },
      },
    });

    return () => {
      cancelled = true;
      sse.close();
      const s = state.current;
      if (s.timer) {
        clearTimeout(s.timer);
        s.timer = null;
      }
    };
  }, [advance, resetTimer]);

  // Empty state
  const isEmpty = photoList.value.length === 0;

  return (
    <div class="slideshow-container">
      {isEmpty && (
        <div class="boot-screen">
          <div class="boot-status">STANDBY</div>
          <div class="boot-status" style="opacity:0.5">NO PHOTOS</div>
        </div>
      )}
      <div
        ref={layerARef}
        class="slideshow-layer"
        style="position:absolute;inset:0;z-index:1;opacity:0;"
      />
      <div
        ref={layerBRef}
        class="slideshow-layer"
        style="position:absolute;inset:0;z-index:1;opacity:0;"
      />
      {onThisDayText.value && (
        <div class="fc-otd-overlay" ref={otdOverlayRef}>
          <span class="fc-otd-label">{onThisDayText.value}</span>
        </div>
      )}
      {connectionLost.value && (
        <div class="fc-connection-lost">CONNECTION LOST — RETRYING</div>
      )}
    </div>
  );
}
