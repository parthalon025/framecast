/** @fileoverview Boot screen with superhot-ui typewriter animation. */
import { useRef, useEffect } from "preact/hooks";
import { bootSequence } from "superhot-ui";

/**
 * Boot — full-screen startup animation.
 *
 * @param {Object} props
 * @param {Function} [props.onComplete] - Called after the last line finishes
 */
export function Boot({ onComplete }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cleanup = bootSequence(containerRef.current, [
      "piOS v1.0",
      "FRAMECAST PHOTO SYSTEM",
      "INITIALIZING...",
      "CHECKING NETWORK...",
      "LOADING MEDIA...",
    ], {
      onComplete: () => onComplete?.(),
    });

    return cleanup;
  }, []);

  return (
    <div class="boot-screen">
      <div ref={containerRef} class="sh-boot-container" />
    </div>
  );
}
