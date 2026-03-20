/** @fileoverview NowPlaying — shows current TV photo at top of Upload page.
 *
 * Displays a small thumbnail + filename for the photo currently on the TV.
 * Updated via SSE "slideshow:now_playing" events.
 */
import { signal } from "@preact/signals";

export const nowPlaying = signal(null);

export function NowPlaying() {
  const photo = nowPlaying.value;
  if (!photo || !photo.filename) return null;

  return (
    <div
      style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; margin-bottom: 8px; border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.08));"
    >
      <img
        src={`/thumbnail/${photo.filename}`}
        onError={(evt) => { evt.target.src = `/media/${photo.filename}`; evt.target.onerror = null; }}
        alt={photo.filename}
        style="width: 40px; height: 40px; object-fit: cover; border-radius: 3px; flex-shrink: 0;"
      />
      <div style="min-width: 0; flex: 1;">
        <div style="font-family: var(--font-mono, monospace); font-size: 0.7rem; letter-spacing: 0.1em; color: var(--sh-phosphor, #39ff14); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
          NOW ON TV
        </div>
        <div class="sh-ansi-dim" style="font-size: 0.7rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
          {photo.filename}
        </div>
      </div>
    </div>
  );
}
