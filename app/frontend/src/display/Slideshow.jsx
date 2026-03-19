/** @fileoverview Full-viewport photo/video slideshow with CSS transitions.
 *
 * Architecture: Two stacked layers (A and B). One is "active" (z-index 2,
 * visible) and the other is "standby" (z-index 1, hidden). On advance:
 *   1. Load the next image into the standby layer.
 *   2. Apply fade-in class to standby, fade-out to active.
 *   3. After transition ends, swap which layer is active.
 *
 * This avoids Preact re-render timing issues by keeping both layers in the
 * DOM permanently and toggling their content via refs.
 */
import { signal } from "@preact/signals";
import { useRef, useEffect, useCallback } from "preact/hooks";

// --- Signals (module-level for SSE reactivity) ---
const photoList = signal([]);
const settingsData = signal(null);

// --- Helpers ---

/** Fisher-Yates shuffle (returns new array). */
function shuffleArray(arr) {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Order photos based on photo_order setting. */
function orderPhotos(list, order) {
  if (!list || list.length === 0) return [];
  switch (order) {
    case "shuffle":
      return shuffleArray(list);
    case "newest":
      return list.slice().sort((a, b) => b.modified - a.modified);
    case "oldest":
      return list.slice().sort((a, b) => a.modified - b.modified);
    case "alphabetical":
      return list.slice().sort((a, b) => a.name.localeCompare(b.name));
    default:
      return shuffleArray(list);
  }
}

/** Build the URL for a media file. */
function mediaUrl(photo) {
  return `/media/${encodeURIComponent(photo.path)}`;
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

/** Get CSS class name for a transition type + direction. */
function transitionClass(type, dir) {
  switch (type) {
    case "fade":
      return dir === "in" ? "slideshow-fade-in" : "slideshow-fade-out";
    case "slide":
      return dir === "in" ? "slideshow-slide-in" : "slideshow-slide-out";
    case "zoom":
      return "slideshow-ken-burns";
    case "none":
      return "";
    default:
      return dir === "in" ? "slideshow-fade-in" : "slideshow-fade-out";
  }
}

/** Duration in ms for a given transition type. */
function transitionMs(type) {
  switch (type) {
    case "fade": return 1000;
    case "slide": return 600;
    case "zoom": return 1000;
    case "none": return 0;
    default: return 1000;
  }
}

/** Remove all child nodes from a DOM element (safe alternative to innerHTML). */
function clearChildren(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/**
 * Set the source of a layer element (img or video).
 * Replaces the element's children to switch between img/video cleanly.
 */
function setLayerContent(layer, photo, onVideoEnded) {
  if (!layer || !photo) return;
  clearChildren(layer);
  if (photo.is_video) {
    const vid = document.createElement("video");
    vid.src = mediaUrl(photo);
    vid.autoplay = true;
    vid.muted = true;
    vid.playsInline = true;
    vid.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;";
    if (onVideoEnded) {
      vid.addEventListener("ended", onVideoEnded, { once: true });
    }
    layer.appendChild(vid);
  } else {
    const img = document.createElement("img");
    img.src = mediaUrl(photo);
    img.alt = photo.name;
    img.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;image-orientation:from-image;";
    layer.appendChild(img);
  }
}

export function Slideshow() {
  // Refs for the two permanent layer divs
  const layerARef = useRef(null);
  const layerBRef = useRef(null);

  // Mutable state (not signals -- no re-render needed)
  const state = useRef({
    ordered: [],
    index: 0,
    activeLayer: "A", // which layer is currently showing
    transitioning: false,
    timer: null,
  });

  /** Advance to the next photo/video. */
  const advance = useCallback(() => {
    const s = state.current;
    if (s.transitioning || s.ordered.length <= 1) return;

    const cfg = settingsData.value;
    const type = cfg ? cfg.transition_type : "fade";
    const ms = transitionMs(type);

    s.transitioning = true;
    s.index = (s.index + 1) % s.ordered.length;

    const activeEl = s.activeLayer === "A" ? layerARef.current : layerBRef.current;
    const standbyEl = s.activeLayer === "A" ? layerBRef.current : layerARef.current;

    // Load next content into standby
    setLayerContent(standbyEl, s.ordered[s.index], advance);

    // Bring standby to front and apply transitions
    standbyEl.style.zIndex = "3";
    standbyEl.style.opacity = "1";
    if (type !== "none") {
      standbyEl.className = "slideshow-layer " + transitionClass(type, "in");
      activeEl.className = "slideshow-layer " + transitionClass(type, "out");
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

    async function init() {
      try {
        const [photosRes, settingsRes] = await Promise.all([
          fetch("/api/photos"),
          fetch("/api/settings"),
        ]);
        if (cancelled) return;

        const list = await photosRes.json();
        const cfg = await settingsRes.json();

        settingsData.value = cfg;
        const ordered = orderPhotos(list, cfg.photo_order);
        photoList.value = ordered;

        const s = state.current;
        s.ordered = ordered;
        s.index = 0;

        if (ordered.length > 0) {
          // Load first photo into layer A
          setLayerContent(layerARef.current, ordered[0], advance);
          layerARef.current.style.zIndex = "2";
          layerARef.current.style.opacity = "1";

          // Preload next 2
          if (ordered.length > 1) {
            preloadAhead(ordered, 0, 2);
          }

          resetTimer();
        }
      } catch (err) {
        console.error("Slideshow: fetch failed", err);
      }
    }

    init();

    // SSE: refresh list on photo:added / photo:deleted
    const source = new EventSource("/api/events");

    function handlePhotoChange() {
      if (cancelled) return;
      fetch("/api/photos")
        .then((res) => res.json())
        .then((list) => {
          const cfg = settingsData.value;
          const ordered = orderPhotos(list, cfg ? cfg.photo_order : "shuffle");
          photoList.value = ordered;
          const s = state.current;
          s.ordered = ordered;
          // Clamp index
          if (s.index >= ordered.length) {
            s.index = 0;
          }
        })
        .catch((err) => console.error("Slideshow: SSE refetch failed", err));
    }

    source.addEventListener("photo:added", handlePhotoChange);
    source.addEventListener("photo:deleted", handlePhotoChange);
    source.addEventListener("settings:changed", (evt) => {
      if (cancelled) return;
      try {
        const cfg = JSON.parse(evt.data);
        settingsData.value = cfg;
      } catch (_ignore) {
        // Malformed SSE data -- ignore
      }
    });

    return () => {
      cancelled = true;
      source.close();
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
          <div class="boot-status">No photos yet</div>
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
    </div>
  );
}
